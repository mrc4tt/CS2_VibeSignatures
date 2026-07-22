"""Semantic helpers for GitHub Actions workflow contract tests."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from trusted_yaml import SAFE_LOADER


class GitHubActionsLoader(SAFE_LOADER):
    """Safe loader that keeps GitHub Actions' ``on`` key as a string."""


GitHubActionsLoader.yaml_implicit_resolvers = {
    key: [resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"]
    for key, resolvers in SAFE_LOADER.yaml_implicit_resolvers.items()
}
GitHubActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def load_workflow(name: str) -> dict:
    path = Path(".github/workflows") / name
    payload = yaml.load(path.read_bytes(), Loader=GitHubActionsLoader)
    if not isinstance(payload, dict):
        raise AssertionError(f"workflow root must be a mapping: {path}")
    return payload


def workflow_job(workflow: dict, job_id: str) -> dict:
    jobs = workflow.get("jobs") or {}
    if job_id not in jobs:
        raise AssertionError(f"missing workflow job: {job_id}")
    return jobs[job_id]


def steps_by_id(job: dict) -> dict[str, dict]:
    indexed = {}
    for index, step in enumerate(job.get("steps") or []):
        step_id = step.get("id")
        if not step_id:
            raise AssertionError(
                f"workflow step[{index}] is missing a stable id: {step.get('name') or step.get('uses')}"
            )
        if step_id in indexed:
            raise AssertionError(f"duplicate workflow step id: {step_id}")
        indexed[step_id] = step
    return indexed


def step_order(job: dict, *step_ids: str) -> list[int]:
    indexed = steps_by_id(job)
    positions = {step["id"]: index for index, step in enumerate(job.get("steps") or [])}
    missing = [step_id for step_id in step_ids if step_id not in indexed]
    if missing:
        raise AssertionError(f"missing workflow step ids: {', '.join(missing)}")
    return [positions[step_id] for step_id in step_ids]
