"""The plugin ships its own hooks (PR-5e).

``.claude-plugin/plugin.json`` is the Claude Code manifest, ``.codex-plugin/plugin.json``
the Codex one; both hosts discover ``hooks/hooks.json`` at the plugin root by default, so
neither manifest names it (an explicit value REPLACES default discovery under Codex and is
MERGED with it under Claude Code — omitted, each host sees exactly one definition). The
plugin hook is the checkout's ``.claude/settings.json`` hook with the script path rooted at
``${CLAUDE_PLUGIN_ROOT}``; the pins below keep the three files from drifting apart and run
the hook the way a host does: through a shell, from a foreign working directory.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
PLUGIN_HOOKS = REPO_ROOT / "hooks" / "hooks.json"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

# Handler keys one host documents and the other does not: keep them out so the one file
# means the same thing on both.
CLAUDE_ONLY_HANDLER_KEYS = {"if", "once", "async", "args"}
CODEX_ONLY_HANDLER_KEYS = {"statusMessage", "additionalContextLimit"}
# SessionStart sources both hosts document (Claude Code also has `fork`; Codex does not).
PORTABLE_SESSION_START_SOURCES = {"startup", "resume", "clear", "compact"}


def _load(path):
    return json.loads(path.read_text())


def _rooted(command):
    """The settings command with its ``scripts/...`` path rooted at the plugin directory."""
    m = re.fullmatch(r"(\S+) (scripts/\S+)(.*)", command)
    assert m, f"settings hook command is not '<interpreter> scripts/<file> ...': {command!r}"
    return f'{m.group(1)} "${{CLAUDE_PLUGIN_ROOT}}/{m.group(2)}"{m.group(3)}'


class TestManifests:
    def test_claude_manifest_mirrors_the_codex_manifest(self):
        claude, codex = _load(CLAUDE_MANIFEST), _load(CODEX_MANIFEST)
        for key in ("name", "version", "description", "skills"):
            assert claude[key] == codex[key], key

    def test_claude_manifest_identity(self):
        claude = _load(CLAUDE_MANIFEST)
        assert claude["name"] == "rfe-creator"
        assert re.fullmatch(r"\d+\.\d+\.\d+", claude["version"])
        assert claude["skills"] == "./.claude/skills/"
        assert claude["repository"] == "https://github.com/fullsend-ai/rfe-creator"
        assert claude["author"]["name"]

    @pytest.mark.parametrize("manifest", [CLAUDE_MANIFEST, CODEX_MANIFEST], ids=["claude", "codex"])
    def test_no_manifest_names_the_hooks_file(self, manifest):
        assert "hooks" not in _load(manifest), (
            f"{manifest.relative_to(REPO_ROOT)}: hooks/hooks.json is discovered by default on "
            "both hosts; naming it would replace (Codex) or double (Claude Code) that discovery"
        )


class TestPluginHooks:
    def test_plugin_hooks_are_the_settings_hooks_rooted_at_the_plugin(self):
        plugin = _load(PLUGIN_HOOKS)["hooks"]
        settings = _load(SETTINGS)["hooks"]
        assert set(plugin) == set(settings)
        for event, groups in settings.items():
            assert len(plugin[event]) == len(groups), event
            for expected, actual in zip(groups, plugin[event]):
                assert actual.get("matcher") == expected.get("matcher"), event
                assert [h["command"] for h in actual["hooks"]] == [
                    _rooted(h["command"]) for h in expected["hooks"]
                ], event

    def test_handlers_are_portable_shell_form(self):
        plugin = _load(PLUGIN_HOOKS)
        assert isinstance(plugin.get("description"), str) and plugin["description"]
        for event, groups in plugin["hooks"].items():
            for group in groups:
                for handler in group["hooks"]:
                    assert handler["type"] == "command", event
                    assert '"${CLAUDE_PLUGIN_ROOT}/' in handler["command"], (
                        "root the script at the (quoted) plugin directory"
                    )
                    assert isinstance(handler.get("timeout"), int) and handler["timeout"] > 0
                    stray = set(handler) & (CLAUDE_ONLY_HANDLER_KEYS | CODEX_ONLY_HANDLER_KEYS)
                    assert not stray, f"{event}: host-specific handler keys {sorted(stray)}"

    def test_session_start_matchers_are_portable(self):
        for group in _load(PLUGIN_HOOKS)["hooks"].get("SessionStart", []):
            sources = set(group.get("matcher", "*").split("|"))
            assert sources <= PORTABLE_SESSION_START_SOURCES, sources


class TestHookRuns:
    """Run the plugin hook as a host does: ``sh -c <command>`` with CLAUDE_PLUGIN_ROOT set,
    the working directory being the user's project, never the plugin."""

    @pytest.fixture
    def run_hook(self, tmp_path):
        command = _load(PLUGIN_HOOKS)["hooks"]["SessionStart"][0]["hooks"][0]["command"]

        def _run(gate):
            env = {k: v for k, v in os.environ.items() if k != "RFE_CREATOR_ENABLE_CONTEXT_HOOK"}
            env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
            if gate:
                env["RFE_CREATOR_ENABLE_CONTEXT_HOOK"] = "1"
            return subprocess.run(
                ["sh", "-c", command],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )

        return _run

    @pytest.fixture
    def pipeline_state(self, tmp_path):
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "pipeline_state.py"),
                "init",
                "--type",
                "rfe",
                "--headless",
            ],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        assert (tmp_path / "tmp" / "pipeline-state.yaml").is_file()

    def test_prints_a_plain_text_banner_in_a_pipeline_directory(self, run_hook, pipeline_state):
        result = run_hook(gate=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("[PIPELINE STATE RECOVERY]"), result.stdout
        # Plain text is added to the context on both hosts; a leading "{" would be parsed
        # as a hook JSON envelope instead, and both hosts cap the injected text.
        assert not result.stdout.lstrip().startswith("{")
        assert len(result.stdout) < 10_000

    def test_silent_without_the_opt_in(self, run_hook, pipeline_state):
        result = run_hook(gate=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_silent_outside_a_pipeline_directory(self, run_hook):
        result = run_hook(gate=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
