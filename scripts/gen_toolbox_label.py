#!/usr/bin/env python3
"""Generate or check the com.runwhen.rw-task.toolbox OCI label.

A JSON list of `{"name", "version"}`, one entry per binary and Python
library the image ships, base64-encoded -- same convention as the
com.runwhen.capability.manifest.v1 / schemas.v1 labels
(runwhen_capability.label).

Unlike those two, this value is NOT threaded into Dockerfile.rw-task as a
build arg. This repo's CI builds through runwhen-capability's reusable
`capability-image.yml` workflow, which passes a fixed set of build args
(REVISION, CREATED, CAPABILITY_MANIFEST_B64, CAPABILITY_SCHEMAS_B64) to
`docker/build-push-action` -- there is no slot for a fifth, image-specific
one, and this repo cannot change that reusable workflow's signature. So the
label's value is computed here, ahead of `docker build`, and written
directly into Dockerfile.rw-task's LABEL line as literal text -- the same
"generated, checked in, verified in CI" shape `rwtask schemas` uses for
output schemas.

Three sources, each read the same way Dockerfile.rw-task itself installs
from them, so the label can never describe a different image than the one
being built:

  - scripts/apt-packages.txt  -- pinned Debian package versions.
  - tools/tools.yaml          -- pinned GitHub-release binaries (kubectl, yq).
  - a Python environment that has been `pip install --no-cache-dir .`-ed --
    every distribution importlib.metadata sees there, which is exactly what
    the Dockerfile's own `pip install --no-cache-dir /app` step installs
    into the image (the SDK and its own transitive dependencies). Pass
    `--python` pointing at that environment's interpreter; `make
    toolbox-label` / `make toolbox-label-check` do this in a throwaway venv
    so the result never depends on what else happens to be installed in a
    developer's own environment.

Usage:
    python3 scripts/gen_toolbox_label.py --python /path/to/clean/venv/bin/python3
    python3 scripts/gen_toolbox_label.py --check --python ...
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile.rw-task"
APT_PACKAGES = ROOT / "scripts" / "apt-packages.txt"
TOOLS_YAML = ROOT / "tools" / "tools.yaml"

LABEL_LINE = re.compile(r'^LABEL com\.runwhen\.rw-task\.toolbox="([^"]*)"\s*$', re.MULTILINE)


def apt_tools() -> list[dict[str, str]]:
    """One entry per `name=version` line in apt-packages.txt."""
    tools = []
    for line in APT_PACKAGES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition("=")
        tools.append({"name": name, "version": version})
    return tools


def github_tools() -> list[dict[str, str]]:
    """One entry per tool in tools.yaml -- kubectl, yq."""
    import yaml

    spec = yaml.safe_load(TOOLS_YAML.read_text(encoding="utf-8"))
    return [{"name": t["name"], "version": str(t["version"])} for t in spec["tools"]]


def python_libraries(python: str) -> list[dict[str, str]]:
    """Every distribution `python`'s environment has installed, run
    out-of-process so this always reflects that interpreter, never whichever
    one happens to be running this script."""
    code = (
        "import json, importlib.metadata as m\n"
        "print(json.dumps([{'name': d.metadata['Name'], 'version': d.version} "
        "for d in m.distributions()]))\n"
    )
    proc = subprocess.run([python, "-c", code], check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def build_toolbox(python: str) -> list[dict[str, str]]:
    """Every tool from all three sources, deduplicated by (name, version)
    and sorted by name -- so the label is stable across regenerations that
    change nothing."""
    tools = apt_tools() + github_tools() + python_libraries(python)
    dedup = {(t["name"], t["version"]): t for t in tools}
    return sorted(dedup.values(), key=lambda t: t["name"].lower())


def encode(toolbox: list[dict[str, str]]) -> str:
    payload = json.dumps(toolbox, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="write nothing; fail if the label is stale"
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter whose installed distributions to record (default: this one)",
    )
    args = parser.parse_args()

    toolbox = build_toolbox(args.python)
    value = encode(toolbox)

    text = DOCKERFILE.read_text(encoding="utf-8")
    match = LABEL_LINE.search(text)
    if not match:
        print(f"{DOCKERFILE}: no com.runwhen.rw-task.toolbox LABEL line found", file=sys.stderr)
        return 1

    if args.check:
        if match.group(1) != value:
            print(
                f"{DOCKERFILE}: com.runwhen.rw-task.toolbox is stale ({len(toolbox)} tools "
                "expected) -- run `make toolbox-label` and commit the result",
                file=sys.stderr,
            )
            return 1
        print(f"toolbox label up to date ({len(toolbox)} tools)")
        return 0

    new_line = f'LABEL com.runwhen.rw-task.toolbox="{value}"'
    DOCKERFILE.write_text(text[: match.start()] + new_line + text[match.end() :], encoding="utf-8")
    print(f"wrote {DOCKERFILE.relative_to(ROOT)} ({len(toolbox)} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
