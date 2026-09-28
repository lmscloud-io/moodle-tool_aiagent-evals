# Evaluations for the AI agent for Moodle

Runs the real AI agent (`tool_aiagent`, DISTR-TEST build, activated against staging) against real AI
providers on disposable Moodle sites, and grades what happens. Design:
`docs/plans/2026-09-28-evals-design.md` in the plugin repository.

## Run it locally

Needs Docker and Python 3.11.

1. `cp .env.example .env` and fill it in: the provider keys, the staging license key and endpoint, and the
   DISTR-TEST repository URL.
2. `./run.sh run --tier compat --moodle 502 --cells 'openai-*' --tasks plain-reply`
3. `.venv/bin/inspect view --log-dir results/<timestamp>/logs` to read the transcripts.

The first run for a branch clones Moodle and installs a site, which takes several minutes. Later runs reuse
it while the DISTR-TEST ref stays the same. `./run.sh down --moodle 502` deletes a branch's site.

Never run a branch locally while the workflow runs the same branch. Both sites use the same wwwroot, so they
share one license seat, and the second activation rotates the first site's key.

## Concepts

- **Task** (`tasks/*.yaml`): what to ask, as whom, and which graders decide pass or fail. Its `description`
  is published on the scoreboard, so write it for site administrators, and say "function", never "tool".
- **Cell** (`matrix.yaml`): one provider plugin, one model, one API mode.
- **Tier:** `compat` runs one cheap cell per provider plugin and API mode on every supported Moodle version;
  `models` runs every cell on the newest.
- **Trial:** one run of a task. A cell "works" when every trial of every task passes.

## Add a task

Write `tasks/<id>.yaml` with `id`, `description`, `tiers`, `user` (a seeded username, or `admin`), `turns`
and `graders`, plus optional `launch` (`{course: ZA101}`), `autoapprove` and `budget_seconds`. The graders are
`no_error`, `reply_contains: <text>`, `reply_matches: <regex>`, `tool_succeeded` and `usage_recorded`; each
takes an optional `turn: <n>`. The seeded world (users, courses, groups) is
`moodle/local_aiagentevals/profiles/standard.json`.

## Add a cell

Add an entry to `matrix.yaml` (`id`, `provider`, `model`, `plugin_settings` for the API mode, `secrets` naming
the environment variables that hold its keys), then list it in a tier. A provider plugin new to the harness
needs its setting shapes in `PROVIDER_DEFAULTS` (`aiagent_evals/config.py`) and its sources per branch in
`providers.yaml`.

## GitHub Actions

The **Evaluations** workflow runs on demand: pick the DISTR-TEST ref, the tier, and optionally branches,
cells and tasks. Each Moodle branch runs as its own job. The results, including full transcripts, are kept as
workflow artifacts for 90 days. With **publish** ticked, it opens a pull request with the scoreboard on the
public docs repository; nothing is published until that pull request is merged.

Secrets: `TOOL_AIAGENT_TEST_LICENSE_KEY`, `TOOL_AIAGENT_TEST_API_ENDPOINT_STAGING`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `MOONSHOT_API_KEY`,
`DISTRTEST_READ_TOKEN`, `DOCS_PR_TOKEN`.

## What is public

Only verdicts, model names, counts, times and token numbers. Transcripts, prompts, the plugin's system
instructions and function descriptions, and provider error texts stay in the private artifacts.
