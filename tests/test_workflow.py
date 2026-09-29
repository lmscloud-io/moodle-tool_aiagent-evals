from aiagent_evals.config import ROOT

import yaml

REPOSITORY_GUARD = "github.repository == 'lmscloud-io/moodle-tool_aiagent-evals'"


def test_every_job_refuses_to_run_outside_the_evals_repository():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "evals.yml").read_text(encoding="utf-8"))
    for name, job in workflow["jobs"].items():
        assert REPOSITORY_GUARD in str(job.get("if", "")), f"job {name} can run on a fork"
