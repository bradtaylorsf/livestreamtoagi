"""Tests for CI/CD configuration (#353)."""

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXPECTED_COST_KILL_TESTS = [
    "tests/backend/test_cost_tracking.py",
    "tests/backend/test_management.py",
    "tests/backend/test_cost_governor.py",
    "tests/backend/test_kill_switch_routes.py",
    "tests/backend/test_kill_switch_e2e.py",
    "tests/backend/test_bridge_contract.py",
    "tests/backend/test_bridge_server.py",
    "tests/backend/test_bridge_node_client.py",
    "tests/backend/test_spend_kill_alerts.py",
    "tests/backend/test_admin_auth.py",
]


def _load_workflow(name: str) -> dict:
    path = ROOT / ".github" / "workflows" / name
    assert path.exists(), f"Workflow {name} must exist"
    return yaml.safe_load(path.read_text())


def _job_run_script(job: dict) -> str:
    return "\n".join(
        step["run"]
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    )


def test_ci_workflow_exists():
    """CI workflow file must exist."""
    assert (ROOT / ".github" / "workflows" / "ci.yml").exists()


def test_security_workflow_exists():
    """Security workflow file must exist."""
    assert (ROOT / ".github" / "workflows" / "security.yml").exists()


def test_ci_has_required_jobs():
    """CI workflow must include lint, test, and integration jobs."""
    ci = _load_workflow("ci.yml")
    jobs = set(ci.get("jobs", {}).keys())
    assert "backend-lint" in jobs
    assert "backend-test" in jobs
    assert "frontend-test" in jobs
    assert "website-test" in jobs
    assert "cost-kill-regression" in jobs
    assert "integration-test" in jobs


def test_ci_has_cost_kill_regression_gate():
    """CI workflow must include a dedicated cost/kill regression gate."""
    ci = _load_workflow("ci.yml")
    job = ci["jobs"].get("cost-kill-regression")
    assert job is not None
    assert job.get("name") == "Cost/Kill Regression Gate"


def test_cost_kill_regression_gate_references_expected_tests():
    """Cost/kill gate should pin the regression test set."""
    ci = _load_workflow("ci.yml")
    run_script = _job_run_script(ci["jobs"]["cost-kill-regression"])

    assert "pytest" in run_script
    for test_file in EXPECTED_COST_KILL_TESTS:
        assert test_file in run_script


def test_ci_triggers_on_push_and_pr():
    """CI workflow must trigger on push and pull_request."""
    ci = _load_workflow("ci.yml")
    # PyYAML parses the YAML key `on` as boolean True
    triggers = ci.get(True, ci.get("on", {}))
    assert "push" in triggers
    assert "pull_request" in triggers


def test_integration_tests_only_on_main():
    """Integration tests should only run on main branch."""
    ci = _load_workflow("ci.yml")
    integration = ci["jobs"]["integration-test"]
    assert integration.get("if") == "github.ref == 'refs/heads/main'"


def test_security_has_bandit():
    """Security workflow must include bandit scanning."""
    sec = _load_workflow("security.yml")
    jobs = set(sec.get("jobs", {}).keys())
    assert "bandit" in jobs
