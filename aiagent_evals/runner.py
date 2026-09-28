"""Run a tier: build each branch's site, run the tier's cells on it one at a time, write results.json."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import statistics
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import context
from .config import (ROOT, Cell, Tier, load_env, load_matrix, load_provider_sources, load_tasks, load_versions,
                     plugin_release, provider_source, supported_branches)
from .site import Site, SiteError

DEFAULT_TOKEN_CAP = 3_000_000


def matches(value: str, patterns: str) -> bool:
    """Whether value matches one of the comma-separated globs; an empty filter matches everything."""
    globs = [pattern.strip() for pattern in patterns.split(",") if pattern.strip()] or ["*"]
    return any(fnmatch.fnmatchcase(value, glob) for glob in globs)


def cell_status(cell: Cell, branch: str, sources: dict, env: Mapping[str, str]) -> str | None:
    """Why the cell cannot run on the branch, or None when it can."""
    source = provider_source(sources, cell.provider, branch)
    if source is None:
        return "not_available"
    if source == "skip":
        return "not_tested"
    if any(not env.get(variable) for variable in cell.secrets.values()):
        return "not_configured"
    return None


def branches_for(tier: Tier, version_php: str, versions: dict, requested: str = "") -> list[str]:
    """The tier's branches (every supported one, or the newest), or the requested ones if all are supported."""
    supported = supported_branches(version_php, versions)
    if requested:
        wanted = [branch.strip() for branch in requested.split(",") if branch.strip()]
        unsupported = [branch for branch in wanted if branch not in supported]
        if unsupported:
            raise SystemExit(f"not supported by this build: {', '.join(unsupported)} "
                             f"(supported: {', '.join(supported)})")
        return wanted
    return supported if tier.moodle == "supported" else supported[-1:]


def samples_from_log(log: Any) -> list[dict]:
    """One dict per trial of an Inspect log: task, passed, infrastructure error, rate limit, seconds, tokens."""
    trials = []
    for sample in log.samples or []:
        score = (sample.scores or {}).get("graded")
        meta = (score.metadata or {}) if score else {}
        trials.append({
            "task": str(sample.id),
            "error": sample.error is not None or score is None,
            "passed": score is not None and score.value == "C",
            "rate_limited": bool(meta.get("rate_limited")),
            "seconds": float(meta.get("seconds") or 0),
            "tokens": int(meta.get("prompt_tokens") or 0) + int(meta.get("completion_tokens") or 0),
        })
    return trials


def summarise(trials: list[dict]) -> dict[str, dict]:
    """Per task: trials scored and passed, infrastructure errors, rate limiting, median seconds and tokens."""
    out: dict[str, dict] = {}
    for trial in trials:
        entry = out.setdefault(trial["task"], {"trials": 0, "passed": 0, "errors": 0, "rate_limited": False,
                                               "seconds": [], "tokens": []})
        if trial["error"]:
            entry["errors"] += 1
            continue
        entry["trials"] += 1
        entry["passed"] += int(trial["passed"])
        entry["rate_limited"] = entry["rate_limited"] or trial["rate_limited"]
        entry["seconds"].append(trial["seconds"])
        entry["tokens"].append(trial["tokens"])
    for entry in out.values():
        seconds, tokens = entry.pop("seconds"), entry.pop("tokens")
        entry["median_seconds"] = round(statistics.median(seconds), 1) if seconds else None
        entry["median_tokens"] = int(statistics.median(tokens)) if tokens else None
    return out


def read_build_version_php(repo: str, ref: str) -> str:
    """version.php of the DISTR-TEST ref, from a fresh shallow clone in .cache/."""
    target = ROOT / ".cache" / "distrtest"
    if target.exists():
        shutil.rmtree(target)
    result = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, repo, str(target)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"could not clone the DISTR-TEST ref {ref}: {result.stderr.strip()[-500:]}")
    return (target / "version.php").read_text(encoding="utf-8")


def run(args: argparse.Namespace, env: Mapping[str, str]) -> Path:
    """Run one tier on its branches; results.json is rewritten after every cell, so a crash keeps the rest."""
    from inspect_ai import eval as inspect_eval

    from .evaltask import build_task

    versions = load_versions()
    cells, tiers = load_matrix()
    tier = tiers[args.tier]
    if args.trials:
        tier = replace(tier, trials=args.trials)
    tasks = [task for task in load_tasks() if tier.name in task.tiers and matches(task.id, args.tasks)]
    selected = [cell for cell in cells if cell.id in tier.cells and matches(cell.id, args.cells)]
    if not tasks or not selected:
        raise SystemExit("no task or no cell of the tier matches the filters")
    version_php = read_build_version_php(env["DISTRTEST_REPO"], args.distrtest_ref)
    branches = branches_for(tier, version_php, versions, args.moodle)
    sources = load_provider_sources()
    out = Path(args.out) if args.out else ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "distrtest_ref": args.distrtest_ref,
        "plugin_release": plugin_release(version_php),
        "tier": tier.name,
        "trials": tier.trials,
        "tasks": {task.id: task.description for task in tasks},
        "runs": [],
    }
    tokens_used = 0
    for branch in branches:
        site = Site(versions[branch], args.distrtest_ref, env["DISTRTEST_REPO"])
        manifest: dict = {}
        passwords: dict[str, str] = {}
        try:
            site.ensure(env["TOOL_AIAGENT_TEST_LICENSE_KEY"], env["TOOL_AIAGENT_TEST_API_ENDPOINT_STAGING"])
            site.refresh_helper()
            problems = site.preflight()
            if not problems:
                manifest = site.seed()
                passwords = site.passwords(manifest)
                problems = site.check_logins(sorted({task.user for task in tasks}), passwords)
        except SiteError as error:
            problems = [str(error)]
        if problems:
            # The problems stay in results.json for the maintainer; the scoreboard only says "not run".
            results["runs"].append({"branch": branch, "status": "site_failed", "problems": problems})
            _write(out, results)
            continue
        context.current = context.RunContext(site.version.wwwroot, passwords, site.usage, manifest["courses"])
        for cell in selected:
            record: dict[str, Any] = {"branch": branch, "cell": cell.id, "provider": cell.provider_label(),
                                      "api": cell.api_label(), "model": cell.model}
            status = cell_status(cell, branch, sources, env)
            if status is None and args.token_cap and tokens_used >= args.token_cap:
                status = "skipped_token_cap"
            if status is None:
                try:
                    site.activate(cell, env)
                except SiteError as error:
                    status = "site_failed"
                    record["problems"] = [str(error)]
            if status is not None:
                results["runs"].append({**record, "status": status})
                _write(out, results)
                continue
            [log] = inspect_eval(build_task(tier, tasks), model=f"moodle/{cell.id}",
                                 log_dir=str(out / "logs" / branch), display="plain", max_samples=1,
                                 retry_on_error=2, fail_on_error=False)
            trials = samples_from_log(log)
            tokens_used += sum(trial["tokens"] for trial in trials)
            results["runs"].append({**record, "status": "ran", "tasks": summarise(trials),
                                    "log": os.path.relpath(log.location, out)})
            _write(out, results)
    results["tokens_used"] = tokens_used
    _write(out, results)
    return out


def _write(out: Path, results: dict) -> None:
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = argparse.ArgumentParser(prog="aiagent-evals", description="Evaluations for the AI agent for Moodle.")
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run", help="build the sites and run one tier")
    run_parser.add_argument("--distrtest-ref", default=os.environ.get("DISTRTEST_REF", "main"))
    run_parser.add_argument("--tier", required=True)
    run_parser.add_argument("--moodle", default="", help="comma-separated branches, e.g. 405,502 (default: the tier's)")
    run_parser.add_argument("--cells", default="*", help="comma-separated cell id globs")
    run_parser.add_argument("--tasks", default="*", help="comma-separated task id globs")
    run_parser.add_argument("--trials", type=int, default=0, help="override the tier's number of trials")
    run_parser.add_argument("--token-cap", type=int, default=int(os.environ.get("EVAL_TOKEN_CAP", DEFAULT_TOKEN_CAP)),
                            help="start no further cell once this many tokens are spent (0: no cap)")
    run_parser.add_argument("--out", default="", help="results directory (default: results/<timestamp>)")

    branches_parser = commands.add_parser("branches", help="print the tier's Moodle branches as JSON")
    branches_parser.add_argument("--distrtest-ref", default=os.environ.get("DISTRTEST_REF", "main"))
    branches_parser.add_argument("--tier", required=True)
    branches_parser.add_argument("--moodle", default="")

    down_parser = commands.add_parser("down", help="delete branches' sites (database and moodledata)")
    down_parser.add_argument("--moodle", required=True, help="comma-separated branches")

    publish_parser = commands.add_parser("publish", help="write the scoreboard into a docs repo checkout")
    publish_parser.add_argument("--results", nargs="+", required=True, help="results.json paths or globs")
    publish_parser.add_argument("--docs-dir", required=True)

    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.command == "run":
        print(run(args, env))
    elif args.command == "branches":
        tier = load_matrix()[1][args.tier]
        version_php = read_build_version_php(env["DISTRTEST_REPO"], args.distrtest_ref)
        print(json.dumps(branches_for(tier, version_php, load_versions(), args.moodle)))
    elif args.command == "down":
        versions = load_versions()
        for branch in args.moodle.split(","):
            Site(versions[branch.strip()], "", "").destroy()
    elif args.command == "publish":
        from .publish import publish

        publish(args.results, Path(args.docs_dir))
    return 0
