.PHONY: install test lint fmt fmt-check tools-sbom toolbox-label toolbox-label-check

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

# Recompute the com.runwhen.rw-task.toolbox label and write it into
# Dockerfile.rw-task. Runs `pip install .` in a throwaway venv -- never the
# caller's own environment -- so the Python-library part of the label
# reflects exactly what the image itself installs, nothing extra a
# developer happens to have around (dev/test dependencies included).
#
# The venv's own interpreter both runs the generator (PyYAML comes in
# transitively through the SDK, so nothing extra to install) and is the one
# introspected for the Python-library part of the label.
toolbox-label:
	rm -rf .toolbox-venv
	python3 -m venv .toolbox-venv
	.toolbox-venv/bin/pip install --no-cache-dir -q .
	.toolbox-venv/bin/python3 scripts/gen_toolbox_label.py --python .toolbox-venv/bin/python3
	rm -rf .toolbox-venv

toolbox-label-check:
	rm -rf .toolbox-venv
	python3 -m venv .toolbox-venv
	.toolbox-venv/bin/pip install --no-cache-dir -q .
	.toolbox-venv/bin/python3 scripts/gen_toolbox_label.py --check --python .toolbox-venv/bin/python3
	rm -rf .toolbox-venv
