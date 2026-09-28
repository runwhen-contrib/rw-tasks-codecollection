# rw-task

`rw-task` is not a capability with tasks of its own -- it is the shared runtime image every
**custom capability** compiles onto. `manifest.yaml` here carries only rw-task's own scheduling
knobs (pool size, concurrency, timeouts) and hardening (no ServiceAccount token, a stateless pod);
`tasks.py` registers nothing. There is no `appliesTo` and no `needs.credentials` -- both are
properties of whatever custom capability is running, never of this image.

## How a custom capability compiles onto it

A workspace author writes a small, plain-text bundle: one `capability.yaml` declaring the
capability's inputs and tasks, plus a task file per task (`.sh` or `.py`), optionally a `setup`
file and JSON Schema files for escape-hatch output shapes. The bundle is deliberately small and
sandboxed -- text only, a handful of allowed paths (`capability.yaml`, `tasks/**`, `lib/**`,
`schemas/**`, `tests/**`, `README.md`), and bounded in size and file count.

The platform validates that bundle statically (no execution) and compiles it into the same
manifest shape a packaged capability like this one has -- tasks, declared inputs, and JSON Schema
outputs -- but with no `execution` block of its own: **its execution profile is rw-task's**, the
one in this directory's `manifest.yaml`. That's the "compiles onto it": every custom capability's
compiled manifest and every run of it shares this one image, this one pod pool, and these same
resource and timeout limits, regardless of which workspace or author wrote the bundle.

## What actually runs

A run request against a custom capability carries the bundle itself -- its content hash and every
file's path and text -- inside the request envelope, alongside which task(s) to run, their inputs,
the target resource, and credentials. This image's task host:

1. writes the bundle's files to a fresh scratch directory for that request only;
2. verifies the files against the declared hash;
3. loads `capability.yaml` from that directory;
4. runs the bundle's own `setup` (if any), then each requested task, each in its own process group
   under its own deadline -- a Python task's `main(ctx, **inputs)` return value becomes its named
   outputs, a bash task writes them with `rw_append`/`rw_set` from the SDK's shell helpers;
5. checks every output against its compiled JSON Schema;
6. redacts every secret and credential value used by the run from both the outputs and the log
   tail;
7. returns the same result envelope shape as a packaged capability: `status`, `outputs` by name,
   `errors`, and a bounded `logTail`.

`rwtask run --local <bundle-dir> --task <name> --inputs '<json>'` runs the identical code path with
no server, against a bundle directory on disk -- see `tests/fixtures/` in this repository for two
minimal bundles (one bash task, one Python task) and `../../README.md` for how the smoke tests
exercise them against the built image.
