.PHONY: install test lint fmt fmt-check tools-sbom toolbox-label toolbox-label-check constraints

# The interpreter the toolbox-label targets build their throwaway venv with.
# Deliberately python3.12, not python3: Dockerfile.rw-task's builder stage
# runs on python:3.12-slim, and constraints.txt is resolved for that same
# version -- a caller whose plain `python3` happens to be something else
# (3.14 on a Homebrew-updated macOS, say) would otherwise build the venv
# these targets introspect against a different interpreter than the one the
# constraints were pinned for. actions/setup-python (CI) and Homebrew's
# python@3.12 (macOS) both put `python3.12` on PATH.
PYTHON312 := python3.12

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest -q

lint:
	ruff check .

fmt:
	ruff format .

fmt-check:
	ruff format --check .

# Regenerate sbom/tools.cdx.json from tools/tools.yaml (kubectl, yq).
tools-sbom:
	python3 scripts/gen_tool_sbom.py

# Regenerate constraints.txt: every transitive Python dependency `pip
# install .` pulls in, pinned to an exact version. Resolved inside a
# throwaway linux/amd64 python:3.12-slim container -- the same base image
# and platform Dockerfile.rw-task's builder stage installs into -- so the
# pins this produces are the ones that image actually resolves, not
# whatever the caller's own OS/arch/interpreter would pick. `--platform
# linux/amd64` is explicit even on an arm64 host (Docker Desktop emulates
# it) so the file is identical regardless of which machine regenerates it.
#
# See constraints.txt's own header for why runwhen-capability and the
# project's own dist are excluded from the output, and why pinning by
# version alone (not a per-wheel hash) is still platform-neutral.
constraints:
	sed -n '/^[^#]/q;p' constraints.txt > constraints.txt.header
	docker run --rm --platform linux/amd64 -v "$$PWD":/src -w /src \
	  python:3.12-slim bash -c '\
	    set -euo pipefail; \
	    apt-get update -qq >/dev/null; \
	    apt-get install -y -qq git >/dev/null; \
	    python -m venv /tmp/constraints-venv; \
	    /tmp/constraints-venv/bin/pip install --no-cache-dir -q .; \
	    /tmp/constraints-venv/bin/pip freeze --all \
	      | grep -v "^rw-tasks-codecollection " \
	      | grep -v "^runwhen-capability " \
	      > /src/constraints.txt.body'
	cat constraints.txt.header constraints.txt.body > constraints.txt
	rm -f constraints.txt.header constraints.txt.body
	@echo "wrote constraints.txt -- diff it, then run 'make toolbox-label' and commit both"

# Recompute the com.runwhen.rw-task.toolbox label and write it into
# Dockerfile.rw-task. Runs `pip install -c constraints.txt .` in a
# throwaway venv -- never the caller's own environment -- so the
# Python-library part of the label reflects exactly what the image itself
# installs, nothing extra a developer happens to have around (dev/test
# dependencies included), and always the same versions constraints.txt
# pins regardless of when the resolver runs.
#
# The venv's own interpreter both runs the generator (PyYAML comes in
# transitively through the SDK, so nothing extra to install) and is the one
# introspected for the Python-library part of the label. pip itself is
# force-installed to its constrained version too, not just left at
# whichever pip $(PYTHON312) happens to bootstrap a fresh venv with --
# python_libraries() in scripts/gen_toolbox_label.py records every
# distribution in the venv, pip included, so an unpinned pip would still
# make the label depend on the caller's platform.
toolbox-label:
	rm -rf .toolbox-venv
	$(PYTHON312) -m venv .toolbox-venv
	.toolbox-venv/bin/pip install --no-cache-dir -q -c constraints.txt --upgrade pip
	.toolbox-venv/bin/pip install --no-cache-dir -q -c constraints.txt .
	.toolbox-venv/bin/python3 scripts/gen_toolbox_label.py --python .toolbox-venv/bin/python3
	rm -rf .toolbox-venv

toolbox-label-check:
	rm -rf .toolbox-venv
	$(PYTHON312) -m venv .toolbox-venv
	.toolbox-venv/bin/pip install --no-cache-dir -q -c constraints.txt --upgrade pip
	.toolbox-venv/bin/pip install --no-cache-dir -q -c constraints.txt .
	.toolbox-venv/bin/python3 scripts/gen_toolbox_label.py --check --python .toolbox-venv/bin/python3
	rm -rf .toolbox-venv
