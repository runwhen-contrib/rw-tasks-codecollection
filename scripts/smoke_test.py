#!/usr/bin/env python3
"""Smoke-test a built rw-task image: the two labels every consumer of this
image reads, and the bundle host actually running a task from each of the
two fixture bundles under tests/fixtures/, under the runner's own real
executor pod spec -- uid 65532, a read-only root filesystem, and a writable
`/work` (see executor_pool.go's BuildExecutorPod), with no writable `/tmp`
anywhere.

The image's own manifest/schemas smoke checks (rwtask --help, the capability
manifest label, `rwtask serve` logging that it loaded rw-task) are the
reusable capability-image workflow's job, not this script's -- see
.github/workflows/build-push.yaml's `smoke-command`. This script covers what
that workflow cannot know how to check: that rw-task's bundle host actually
runs a bash task and a Python task end to end under that pod spec (see
run_bundle_task's own docstring for why), that a bundle request is refused
when this executor was not started with --allow-bundles (see
check_bundle_refused_without_allow_bundles), and that the
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
    request through, with no relay involved. `--local` bypasses
    --allow-bundles entirely (that gate is `rwtask serve`-only -- see
    check_bundle_refused_without_allow_bundles), so this exercises the
    bundle host itself, not the flag.

    Run under the runner's own real executor pod spec, not a plain `docker
    run`: `--user 65532:65532`, `--read-only`, and a writable `/work` via
    `--tmpfs` -- no writable `/tmp` anywhere, matching executor_pool.go's
    BuildExecutorPod exactly. This is the one scenario that would NOT be
    caught by building the image alone -- the bundle host has to actually
    write each request's scratch files somewhere under a filesystem that
    starts empty at container start, not whatever happened to survive from
    the image's own build layer, as any uid, not just the image's own.

    `--workdir /work/scratch` is passed explicitly rather than left to
    `run --local`'s own default (a fresh `tempfile.mkdtemp()`, rooted at
    $TMPDIR): the image sets TMPDIR=/work/tmp, but nothing creates that
    directory when CMD is overridden like this -- see Dockerfile.rw-task's
    TMPDIR comment. An explicit --workdir sidesteps that entirely, and
    `run --local` never deletes a caller-supplied one (run_local.py:
    `owns_workdir = workdir is None`).
    """
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "65532:65532",
            "--read-only",
            "--tmpfs",
            "/work:rw,uid=65532,gid=65532",
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
            "--workdir",
            "/work/scratch",
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


# Drives `rwtask serve` for exactly one poll, against a fake `requests.Session`
# rather than a real relay: --allow-bundles gates `serve`, not `run --local`
# (see run_bundle_task's docstring), so this is the only way to exercise the
# refusal without standing up a relay + executor token inside the test. The
# fake session hands back one bundle-shaped "next task" response, then
# records what gets posted back as the result.
_BUNDLE_REFUSAL_SCRIPT = """
from pathlib import Path

from runwhen_capability.serve import BUNDLES_NOT_ALLOWED, serve

workdir = Path("/work/refusal-scratch")
token_file = Path("/work/fake-token")
token_file.write_text("smoke-test-token\\n")

bundle_task = {
    "requestId": "smoke-refused-1",
    "scopeId": "smoke-refused-scope",
    "deadlineMs": 5000,
    "credentials": {},
    "request": {"bundle": {"hash": "0" * 64, "files": []}, "tasks": [], "inputs": {}},
}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append((url, json))
        if url.endswith("/v1/tasks/next"):
            return FakeResponse(200, bundle_task)
        return FakeResponse(200, {})


session = FakeSession()
serve(
    relay="http://fake-relay.invalid",
    pool_id="smoke-pool",
    workdir=workdir,
    capability_dir=Path("/app/capabilities/rw-task"),
    token_file=token_file,
    session=session,
    max_iterations=1,
    allow_bundles=False,
)

results = [payload for url, payload in session.calls if url.endswith("/result")]
assert len(results) == 1, f"expected exactly one result post, got {results!r}"
payload = results[0]
assert payload["status"] == "failed", payload
assert payload["error"] == BUNDLES_NOT_ALLOWED, payload
assert not any(workdir.iterdir()), "a refused bundle request must not create a scope"
print("REFUSED_OK")
"""


def check_bundle_refused_without_allow_bundles(image: str) -> None:
    """A bundle request reaching `rwtask serve` when this executor was not
    started with --allow-bundles gets a failed result naming
    BUNDLES_NOT_ALLOWED, no scope directory created, and the bundle host
    never called (serve.py's `_poll_once`) -- this is the property this
    image's own default CMD relies on being the OPPOSITE of (it always
    passes --allow-bundles); this check would catch that flag silently
    disappearing from CMD again. Run under the same hardened flags as the
    bundle-execution checks above.
    """
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "65532:65532",
            "--read-only",
            "--tmpfs",
            "/work:rw,uid=65532,gid=65532",
            image,
            "python3",
            "-c",
            _BUNDLE_REFUSAL_SCRIPT,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or "REFUSED_OK" not in proc.stdout:
        raise SmokeTestFailure(
            "a bundle request without --allow-bundles was not refused as expected\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    print("bundle request without --allow-bundles: refused as expected")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <image>", file=sys.stderr)
        return 2
    image = sys.argv[1]

    checks = [
        check_toolbox_label,
        check_capability_label,
        check_bash_bundle,
        check_python_bundle,
        check_bundle_refused_without_allow_bundles,
    ]
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
