"""A disposable Moodle site per branch, run with docker compose. It never touches any other site."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import ROOT, GitSource, MoodleVersion, load_provider_sources, provider_source

COMPOSE_FILE = ROOT / "docker" / "compose.yaml"
CONFIG_TEMPLATE = ROOT / "docker" / "config.php.template"
HELPER_PLUGIN = ROOT / "moodle" / "local_aiagentevals"
SITES_DIR = ROOT / ".sites"
ADMIN_PASSWORD = "Eval-admin-1"
PROVIDER_COMPONENTS = (
    "aiprovider_openai", "aiprovider_azureai", "aiprovider_anthropic",
    "aiprovider_claude", "aiprovider_gemini", "aiprovider_openaicompatible",
)


class SiteError(RuntimeError):
    """The evaluation site could not be built or answered wrongly: an infrastructure failure."""


def render_config(wwwroot: str, license_key: str, api_endpoint: str) -> str:
    """config.php for an evaluation site, from docker/config.php.template."""
    template = CONFIG_TEMPLATE.read_text(encoding="utf-8")
    return (template.replace("{{WWWROOT}}", _php_string(wwwroot))
            .replace("{{LICENSE_KEY}}", _php_string(license_key))
            .replace("{{API_ENDPOINT}}", _php_string(api_endpoint)))


def _php_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _run(cmd: list[str], env: dict[str, str] | None = None, stdin: str | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, env=env, input=stdin, text=True, capture_output=True)
    if check and result.returncode != 0:
        # Name the program only: a clone URL can carry a token.
        raise SiteError(f"{cmd[0]} {cmd[1]} exited with {result.returncode}: {result.stderr.strip()[-2000:]}")
    return result


@dataclass
class Site:
    version: MoodleVersion
    distrtest_ref: str
    distrtest_repo: str

    @property
    def workdir(self) -> Path:
        return SITES_DIR / self.version.branch

    @property
    def moodle_dir(self) -> Path:
        return self.workdir / "moodle"

    @property
    def project(self) -> str:
        return f"aiagent-evals-{self.version.branch}"

    @property
    def web_prefix(self) -> str:
        """Where plugins live below the checkout: 'public/' from Moodle 5.1, '' before."""
        return "public/" if (self.moodle_dir / "public").is_dir() else ""

    def plugin_path(self, relative: str) -> Path:
        return self.moodle_dir / (self.web_prefix + relative)

    def compose(self, *args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        env = {**os.environ, "EVAL_PHP": self.version.php, "EVAL_PORT": str(self.version.port),
               "EVAL_MOODLE_DIR": str(self.moodle_dir)}
        return _run(["docker", "compose", "-f", str(COMPOSE_FILE), "-p", self.project, *args],
                    env=env, stdin=stdin, check=check)

    def cli(self, script: str, *args: str, stdin: str | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
        """Run a PHP CLI script (a path relative to the checkout) in the web container as www-data."""
        return self.compose("exec", "-T", "-u", "www-data", "web", "php", f"/var/www/html/{script}", *args,
                            stdin=stdin, check=check)

    def prepare_code(self) -> None:
        """Moodle at the branch, DISTR-TEST at the ref, the branch's provider plugins, the helper plugin."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        if not (self.moodle_dir / ".git").is_dir():
            _run(["git", "clone", "--quiet", "--depth", "1", "--branch", self.version.git_ref,
                  "https://github.com/moodle/moodle.git", str(self.moodle_dir)])
        self._clone(self.distrtest_repo, self.distrtest_ref, self.plugin_path("admin/tool/aiagent"))
        sources = load_provider_sources()
        for component in PROVIDER_COMPONENTS:
            source = provider_source(sources, component, self.version.branch)
            if isinstance(source, GitSource):
                name = component.split("_", 1)[1]
                self._clone(source.repo, source.branch, self.plugin_path(f"ai/provider/{name}"))
        helper = self.plugin_path("local/aiagentevals")
        if helper.exists():
            shutil.rmtree(helper)
        shutil.copytree(HELPER_PLUGIN, helper)

    @staticmethod
    def _clone(repo: str, ref: str, target: Path) -> None:
        if target.exists():
            shutil.rmtree(target)
        _run(["git", "clone", "--quiet", "--depth", "1", "--branch", ref, repo, str(target)])

    def ensure(self, license_key: str, api_endpoint: str) -> None:
        """Build the site, or reuse it when it was built for the same DISTR-TEST ref and wwwroot."""
        marker = self.workdir / "installed.json"
        wanted = {"ref": self.distrtest_ref, "wwwroot": self.version.wwwroot}
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) == wanted:
            self.compose("up", "-d", "--wait")
            self.wait_http()
            return
        self.destroy()
        self.prepare_code()
        config_php = render_config(self.version.wwwroot, license_key, api_endpoint)
        (self.moodle_dir / "config.php").write_text(config_php, encoding="utf-8")
        self.compose("up", "-d", "--wait")
        self.compose("exec", "-T", "web", "chown", "-R", "www-data:www-data", "/var/www/moodledata")
        self.cli("admin/cli/install_database.php", "--agree-license", "--lang=en",
                 "--fullname=AI agent evaluations", "--shortname=evals", "--adminuser=admin",
                 f"--adminpass={ADMIN_PASSWORD}", "--adminemail=admin@example.com")
        self.wait_http()
        marker.write_text(json.dumps(wanted), encoding="utf-8")

    def destroy(self) -> None:
        """Stop the site and delete its database and moodledata; the code checkout stays for reuse."""
        self.compose("down", "-v", "--remove-orphans", check=False)
        (self.workdir / "installed.json").unlink(missing_ok=True)

    def wait_http(self, timeout: float = 180) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if requests.get(f"{self.version.wwwroot}/login/index.php", timeout=10).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(2)
        raise SiteError(f"{self.version.wwwroot} did not answer within {timeout:.0f} seconds")

    def helper(self, script: str, *args: str, stdin: str | None = None,
               check: bool = True) -> subprocess.CompletedProcess:
        """Run one of the helper plugin's CLI scripts."""
        return self.cli(f"{self.web_prefix}local/aiagentevals/cli/{script}", *args, stdin=stdin, check=check)

    def refresh_helper(self) -> None:
        """Copy the helper plugin into the checkout again, so edits reach a site that is already built."""
        target = self.plugin_path("local/aiagentevals")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(HELPER_PLUGIN, target)

    def preflight(self) -> list[str]:
        """What makes the site unusable for evaluation; empty when it is ready."""
        result = self.helper("preflight.php", check=False)
        try:
            return list(json.loads(result.stdout)["problems"])
        except (json.JSONDecodeError, KeyError):
            return [f"preflight.php printed no report: {result.stderr.strip()[-500:]}"]

    def usage(self, chat_hash: str) -> list[dict]:
        return json.loads(self.helper("usage.php", f"--hash={chat_hash}").stdout)
