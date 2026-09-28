"""Basic well-formedness checks for the two smoke-test bundles under
tests/fixtures/ -- valid YAML, the shape section 1's custom-capability
manifest format describes, and every declared task file actually on disk.
Running a task end to end is scripts/smoke_test.py's job, against a built
image; these tests need nothing but a YAML parser."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUNDLES = ["bash-bundle", "python-bundle"]


@pytest.mark.parametrize("bundle", BUNDLES)
def test_capability_yaml_is_well_formed(bundle):
    manifest = yaml.safe_load((FIXTURES / bundle / "capability.yaml").read_text())
    assert manifest["apiVersion"] == "runwhen.com/custom-capability/v1"
    assert manifest["name"]
    assert manifest["tasks"], "fixture bundle must declare at least one task"
    for task in manifest["tasks"]:
        assert task["name"]
        assert task["file"]


@pytest.mark.parametrize("bundle", BUNDLES)
def test_every_task_file_exists(bundle):
    manifest = yaml.safe_load((FIXTURES / bundle / "capability.yaml").read_text())
    for task in manifest["tasks"]:
        task_path = FIXTURES / bundle / task["file"]
        assert task_path.is_file(), f"{bundle}: {task['file']} does not exist"
