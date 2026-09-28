"""Unit tests for scripts/gen_toolbox_label.py's parsing and encoding --
not the Python-library introspection (that needs a real interpreter to
point `--python` at; covered end to end by `make toolbox-label-check` and
scripts/smoke_test.py's toolbox-label check against a built image)."""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    """scripts/ isn't an installed package (this repo ships no importable
    code of its own -- pyproject.toml's `packages = []`), so load the
    script by path, the same way runwhen_capability.loader loads a
    capability's tasks.py."""
    path = ROOT / "scripts" / "gen_toolbox_label.py"
    spec = importlib.util.spec_from_file_location("gen_toolbox_label", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen_toolbox_label = _load_module()


def test_apt_tools_parses_name_and_version():
    tools = gen_toolbox_label.apt_tools()
    names = {t["name"] for t in tools}
    assert {"bash", "curl", "jq", "postgresql-client", "redis-tools", "ca-certificates"} <= names
    for tool in tools:
        assert tool["name"] and tool["version"]


def test_apt_tools_skips_comments_and_blank_lines():
    tools = gen_toolbox_label.apt_tools()
    # scripts/apt-packages.txt opens with a comment block -- if that leaked
    # through, a "#" would show up as a bogus package name.
    assert all(not t["name"].startswith("#") for t in tools)


def test_github_tools_matches_tools_yaml():
    tools = gen_toolbox_label.github_tools()
    by_name = {t["name"]: t["version"] for t in tools}
    assert by_name == {"kubectl": "1.37.1", "yq": "4.53.6"}


def test_build_toolbox_dedupes_and_sorts(monkeypatch):
    monkeypatch.setattr(gen_toolbox_label, "apt_tools", lambda: [{"name": "z", "version": "1"}])
    monkeypatch.setattr(gen_toolbox_label, "github_tools", lambda: [{"name": "a", "version": "1"}])
    monkeypatch.setattr(
        gen_toolbox_label,
        "python_libraries",
        lambda python: [{"name": "a", "version": "1"}, {"name": "m", "version": "2"}],
    )
    toolbox = gen_toolbox_label.build_toolbox("unused")
    assert toolbox == [
        {"name": "a", "version": "1"},
        {"name": "m", "version": "2"},
        {"name": "z", "version": "1"},
    ]


def test_encode_round_trips():
    toolbox = [{"name": "jq", "version": "1.7.1"}, {"name": "bash", "version": "5.2"}]
    value = gen_toolbox_label.encode(toolbox)
    decoded = json.loads(base64.b64decode(value))
    assert sorted(decoded, key=lambda t: t["name"]) == sorted(toolbox, key=lambda t: t["name"])
