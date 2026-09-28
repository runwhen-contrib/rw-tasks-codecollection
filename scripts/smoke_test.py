#!/usr/bin/env python3
"""Smoke-test a built rw-task image: the two labels every consumer of this
image reads, and the bundle host actually running a task from each of the
two fixture bundles under tests/fixtures/.

The image's own manifest/schemas smoke checks (rwtask --help, the capability
manifest label, `rwtask serve` logging that it loaded rw-task) are the
reusable capability-image workflow's job, not this script's -- see
.github/workflows/build-push.yaml's `smoke-command`. This script covers what
that workflow cannot know how to check: that rw-task's bundle host actually
runs a bash task and a Python task end to end, and that the
com.runwhen.rw-task.toolbox label this repo generates (see
scripts/gen_toolbox_label.py) is present and well-formed on the image it
describes.

Usage:
    python3 scripts/smoke_test.py <image>
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


class SmokeTestFailure(RuntimeError):
    pass


def image_label(image: str, key: str) -> str:
    proc = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            f'{{{{ index .Config.Labels "{key}" }}}}',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def check_toolbox_label(image: str) -> None:
    """com.runwhen.rw-task.toolbox decodes to a non-empty JSON list of
    {"name", "version"} objects, and names every tool this image promises."""
    raw = image_label(image, "com.runwhen.rw-task.toolbox")
    if not raw:
        raise SmokeTestFailure("com.runwhen.rw-task.toolbox label is empty")
    try:
        toolbox = json.loads(base64.b64decode(raw))
    except Exception as exc:  # noqa: BLE001 -- report exactly what's wrong
        raise SmokeTestFailure(
            f"com.runwhen.rw-task.toolbox is not valid base64 JSON: {exc}"
        ) from exc
    if not isinstance(toolbox, list) or not toolbox:
        raise SmokeTestFailure("com.runwhen.rw-task.toolbox must decode to a non-empty list")
    names = set()
    for entry in toolbox:
        if not isinstance(entry, dict) or set(entry) != {"name", "version"}:
            raise SmokeTestFailure(
                f"toolbox entry must be exactly {{name, version}}, got {entry!r}"
            )
        if not entry["name"] or not entry["version"]:
            raise SmokeTestFailure(f"toolbox entry has an empty name or version: {entry!r}")
        names.add(entry["name"])
    expected = {"bash", "kubectl", "jq", "yq", "curl", "postgresql-client", "redis-tools"}
    missing = expected - names
    if missing:
        raise SmokeTestFailure(f"toolbox label is missing expected tools: {sorted(missing)}")
    print(f"toolbox label: {len(toolbox)} tools, including {sorted(expected)}")


def check_capability_label(image: str) -> None:
    """com.runwhen.capability.manifest.v1 decodes to rw-task's own
    manifest.yaml, byte for byte -- the same file `rwtask label` reads."""
    raw = image_label(image, "com.runwhen.capability.manifest.v1")
    if not raw:
        raise SmokeTestFailure("com.runwhen.capability.manifest.v1 label is empty")
    on_image = base64.b64decode(raw)
    on_disk = (ROOT / "capabilities" / "rw-task" / "manifest.yaml").read_bytes()
    if on_image != on_disk:
        raise SmokeTestFailure(
            "com.runwhen.capability.manifest.v1 does not match capabilities/rw-task/manifest.yaml "
            "-- the image was built from a different manifest than this checkout's"
        )
    print("capability manifest label matches capabilities/rw-task/manifest.yaml")


def run_bundle_task(image: str, bundle: str, task: str, inputs: dict) -> dict:
    """`rwtask run --local` against one fixture bundle, mounted read-only
    into the container -- the same code path `rwtask serve` runs a bundle
    request through, with no relay involved."""
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{FIXTURES}:/fixtures:ro",
            image,
            "rwtask",
            "run",
            "--local",
            f"/fixtures/{bundle}",
            "--task",
            task,
            "--inputs",
            json.dumps(inputs),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SmokeTestFailure(
            f"rwtask run --local {bundle} --task {task} exited {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SmokeTestFailure(f"{bundle}/{task}: stdout was not JSON: {proc.stdout!r}") from exc


def check_bash_bundle(image: str) -> None:
    result = run_bundle_task(
        image, "bash-bundle", "echo-greeting", {"greeting": "hi from the smoke test"}
    )
    tasks = {t["task"]: t for t in result.get("tasks", [])}
    task = tasks.get("echo-greeting")
    if task is None or task.get("status") != "ok":
        raise SmokeTestFailure(f"bash-bundle/echo-greeting did not report status ok: {result!r}")
    message = task["outputs"].get("message")
    if message != {"text": "hi from the smoke test"}:
        raise SmokeTestFailure(
            f"bash-bundle/echo-greeting: unexpected 'message' output: {message!r}"
        )
    print("bash-bundle/echo-greeting: ok, outputs match")


def check_python_bundle(image: str) -> None:
    result = run_bundle_task(image, "python-bundle", "count-chars", {"text": "runwhen"})
    tasks = {t["task"]: t for t in result.get("tasks", [])}
    task = tasks.get("count-chars")
    if task is None or task.get("status") != "ok":
        raise SmokeTestFailure(f"python-bundle/count-chars did not report status ok: {result!r}")
    length = task["outputs"].get("length")
    if length != {"count": len("runwhen")}:
        raise SmokeTestFailure(f"python-bundle/count-chars: unexpected 'length' output: {length!r}")
    print("python-bundle/count-chars: ok, outputs match")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <image>", file=sys.stderr)
        return 2
    image = sys.argv[1]

    checks = [check_toolbox_label, check_capability_label, check_bash_bundle, check_python_bundle]
    failures = []
    for check in checks:
        try:
            check(image)
        except SmokeTestFailure as exc:
            print(f"FAIL: {check.__name__}: {exc}", file=sys.stderr)
            failures.append(check.__name__)

    if failures:
        print(
            f"\n{len(failures)}/{len(checks)} smoke check(s) failed: {', '.join(failures)}",
            file=sys.stderr,
        )
        return 1
    print(f"\nall {len(checks)} smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
