# rw-tasks-codecollection

RunWhen CodeCollection for custom capabilities -- a **capability image**, built on the
`runwhen_capability` SDK and its `rwtask` task host, not a Robot codebundle collection.

## What this is

This repository ships the **`rw-task`** capability: not a capability with tasks of its own, but
the generic runtime every **custom capability** on the RunWhen platform compiles onto. A workspace
author writes a small, plain-text bundle (a `capability.yaml` plus a task file per task -- see
[`capabilities/rw-task/README.md`](capabilities/rw-task/README.md) for the full shape and how a run
actually executes); the platform validates and compiles it, and every run of it lands on this one
image, this one pod pool, under this one set of resource and timeout limits.

- **`capabilities/rw-task/`** -- the capability: a manifest with no tasks and no `appliesTo` of its
  own (see its header comment for why), and a `tasks.py` that registers none.
- **`Dockerfile.rw-task`** -- builds the image: Python 3.12, bash, kubectl, jq, yq, curl, the
  PostgreSQL client, redis-cli, and the SDK.
- **`tools/tools.yaml`** / **`sbom/tools.cdx.json`** -- the two GitHub-release binaries (kubectl,
  yq) this image ships, pinned and sha256-verified; see `scripts/install_tools.sh`.
- **`scripts/apt-packages.txt`** -- every apt-installed runtime tool, pinned to an exact Debian
  package version.
- **`scripts/gen_toolbox_label.py`** -- generates the `com.runwhen.rw-task.toolbox` label (see
  below); **`scripts/gen_tool_sbom.py`** regenerates the SBOM from `tools/tools.yaml`.
- **`tests/fixtures/`** -- two minimal bundles (one bash task, one Python task) that
  `scripts/smoke_test.py` runs against a built image.

## Toolbox label

`com.runwhen.rw-task.toolbox` is a base64'd JSON list of `{"name", "version"}`, one entry per
binary and Python library this image ships -- every pinned apt package, kubectl, yq, and the SDK's
own Python dependency tree. Unlike the `com.runwhen.capability.manifest.v1` /
`schemas.v1` labels (computed from files already in this repo and passed as Docker build args by
CI), this one is generated ahead of `docker build` and checked directly into
`Dockerfile.rw-task` as literal text -- `scripts/gen_toolbox_label.py`'s header explains why: the
reusable image workflow this repo's CI calls builds with a fixed set of build args, with no slot
for a fifth, image-specific one.

```
make toolbox-label         # recompute it and rewrite Dockerfile.rw-task
make toolbox-label-check   # fail if it has drifted (what CI runs)
```

Both targets run in a throwaway venv (`pip install .`, nothing extra), so the Python-library part
of the label always matches what the image itself installs -- never whatever else happens to be in
a developer's own environment.

## Hardening

- **Non-root.** The image creates and runs as `runwhen` (uid 1000); nothing in it needs root at
  runtime.
- **A `/tmp`-rooted work directory**, not this organisation's usual `/work`: rw-task's bundle host
  writes each request's files to a fresh scratch directory, and `/tmp` is the directory most likely
  to be a writable, tmpfs-backed mount under an otherwise read-only root filesystem -- the pod
  hardening this image is built to be compatible with, even though the pod's own security context
  (read-only root filesystem, no ServiceAccount token automount) is a runner/pod-spec concern
  outside this repo, not something a Dockerfile sets.
- **`execution.serviceAccountToken: false`** in `capabilities/rw-task/manifest.yaml`, explicit even
  though it is already the platform default: this image executes arbitrary, unreviewed third-party
  task code, so it must never carry a projected ServiceAccount token letting that code reach the
  cluster's own API server as the runner's identity.
- **No `git`, no C toolchain** in the final image -- `Dockerfile.rw-task`'s multi-stage build
  installs the SDK (the one dependency that needs `git`) into an isolated venv in a `builder` stage
  and copies only that venv into the image actually shipped.

## Local development

A bundle author needs no image to develop against the SDK -- `rwtask run --local` (from
`runwhen_capability`, this repo's SDK dependency) is the reference implementation: the same code
path the bundle host runs in production, against a bundle directory on disk.

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

rwtask run --local tests/fixtures/bash-bundle --task echo-greeting --inputs '{"greeting": "hi"}'
rwtask run --local tests/fixtures/python-bundle --task count-chars --inputs '{"text": "runwhen"}'
```

### Running the image directly

```
manifest_b64="$(rwtask label capabilities/rw-task)"
docker build -f Dockerfile.rw-task -t rw-task:dev \
  --build-arg CAPABILITY_MANIFEST_B64="${manifest_b64}" .
docker run --rm rw-task:dev rwtask --help
```

In production the image is never driven directly: `rwtask serve --relay <url> --pool <poolId>`
long-polls the runner as a warm executor, and each request it receives carries its own bundle (see
`capabilities/rw-task/README.md`) rather than naming one of this image's own tasks -- it has none.

## Tests

```
make lint         # ruff check .
make fmt-check    # ruff format --check .
python3 scripts/smoke_test.py <image>   # against an already-built image; see that file's header
```

`scripts/smoke_test.py` is what both CI workflows run: `.github/workflows/test.yaml` builds a
single-arch image with plain `docker build` and runs it directly, on every push and pull request;
`.github/workflows/build-push.yaml` runs the identical script as the reusable capability-image
workflow's `smoke-command`, after that workflow's own full multi-arch build.

## SDK dependency

This repo depends on `runwhen_capability` and its `rwtask` host from
[runwhen-capability](https://github.com/runwhen-contrib/runwhen-capability), pinned to a release
tag in `pyproject.toml` and, identically, in `Dockerfile.rw-task` (pip's `--require-hashes` mode
does not support VCS requirements at all, so this one dependency installs in its own,
non-hash-checked step; see that file's header comment). Move both pins to a new release together
when the SDK's bundle-execution contract changes.
