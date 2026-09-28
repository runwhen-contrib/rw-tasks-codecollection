"""rw-task registers no `@setup`/`@task` functions of its own.

`runwhen_capability.loader.load_capability` requires every capability
directory to have a `tasks.py` (image == capability, 1:1), so this file has
to exist -- but rw-task's actual work happens through the bundle host: each
request carries its own small, content-hashed set of files (a compiled
custom capability's `capability.yaml` plus its task scripts), written to a
scratch directory and executed there for that one request only. See
manifest.yaml's header comment for why, and README.md for the shape of a
bundle this image runs.
"""

from __future__ import annotations
