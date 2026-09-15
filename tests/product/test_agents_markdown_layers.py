"""M1 S3: layered AGENTS.md/CLAUDE.md discovery with per-layer change digest."""

from __future__ import annotations

from pathlib import Path

from agent_os_core import (
    AgentLoopConfig,
    DeferredApprovalGateway,
    DeterministicProvider,
    discover_agents_markdown_layers,
    layered_agents_markdown_system_section,
)

from apps.api_server.app import AgentOSApplication


def test_root_first_then_nested_sorted(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rules\n", encoding="utf-8")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "AGENTS.md").write_text("b rules\n", encoding="utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "AGENTS.md").write_text("a rules\n", encoding="utf-8")

    layers = discover_agents_markdown_layers(tmp_path)
    assert [layer.path for layer in layers] == ["AGENTS.md", "a/AGENTS.md", "b/AGENTS.md"]
    assert [layer.content for layer in layers] == ["root rules\n", "a rules\n", "b rules\n"]


def test_claude_md_is_supported_as_a_layer(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude rules\n", encoding="utf-8")
    layers = discover_agents_markdown_layers(tmp_path)
    assert [layer.path for layer in layers] == ["CLAUDE.md"]


def test_each_layer_carries_a_change_digest(tmp_path: Path) -> None:
    target = tmp_path / "pkg" / "AGENTS.md"
    target.parent.mkdir()
    target.write_text("v1\n", encoding="utf-8")
    first = discover_agents_markdown_layers(tmp_path)[0].sha256
    target.write_text("v2\n", encoding="utf-8")
    second = discover_agents_markdown_layers(tmp_path)[0].sha256
    assert first != second


def test_hidden_and_git_dirs_are_skipped(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "AGENTS.md").write_text("git\n", encoding="utf-8")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "AGENTS.md").write_text("hidden\n", encoding="utf-8")
    assert discover_agents_markdown_layers(tmp_path) == ()


def test_loose_cased_name_is_found(tmp_path: Path) -> None:
    (tmp_path / "agents.md").write_text("lower\n", encoding="utf-8")
    layers = discover_agents_markdown_layers(tmp_path)
    # On a case-insensitive FS (macOS) the exact-name probe resolves to this file;
    # the contract is that the loose-cased file IS found exactly once.
    assert len(layers) == 1
    assert layers[0].content == "lower\n"


def test_huge_directory_is_bounded(tmp_path: Path) -> None:
    # A directory with very many entries must not stall discovery (budgeted scan).
    big = tmp_path / "big"
    big.mkdir()
    for index in range(3000):
        (big / f"f{index:05d}.txt").write_text("x", encoding="utf-8")
    (big / "AGENTS.md").write_text("found\n", encoding="utf-8")
    layers = discover_agents_markdown_layers(tmp_path)
    assert [layer.path for layer in layers] == ["big/AGENTS.md"]


def test_nested_only_is_not_mislabeled_as_root(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("nested only\n", encoding="utf-8")
    layers = discover_agents_markdown_layers(tmp_path)
    assert [layer.path for layer in layers] == ["pkg/AGENTS.md"]
    rendered = layered_agents_markdown_system_section(layers)
    assert "# Nested AGENTS.md" in rendered
    assert "Project AGENTS.md" not in rendered


def test_root_claude_md_is_labeled_as_claude(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("claude root\n", encoding="utf-8")
    rendered = layered_agents_markdown_system_section(
        discover_agents_markdown_layers(tmp_path)
    )
    assert "# Project CLAUDE.md" in rendered


def test_oversized_layer_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"a" * 200_000)
    assert discover_agents_markdown_layers(tmp_path) == ()


def test_total_char_budget_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("r" * 100, encoding="utf-8")
    for index in range(5):
        directory = tmp_path / f"d{index}"
        directory.mkdir()
        (directory / "AGENTS.md").write_text("n" * 100, encoding="utf-8")
    layers = discover_agents_markdown_layers(
        tmp_path, max_total_chars=250, max_chars_per_file=1000
    )
    assert sum(len(layer.content) for layer in layers) <= 250
    assert layers[0].path == "AGENTS.md"


def test_heavy_dirs_are_pruned(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "AGENTS.md").write_text("no\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("yes\n", encoding="utf-8")
    assert [layer.path for layer in discover_agents_markdown_layers(tmp_path)] == [
        "pkg/AGENTS.md"
    ]


def test_symlinked_layer_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text("secret\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "AGENTS.md").symlink_to(tmp_path / "real.md")
    assert discover_agents_markdown_layers(tmp_path) == ()


def test_max_layers_and_total_chars_are_bounded(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("r\n" * 10, encoding="utf-8")
    for index in range(20):
        directory = tmp_path / f"d{index:02d}"
        directory.mkdir()
        (directory / "AGENTS.md").write_text(f"n{index}\n", encoding="utf-8")
    layers = discover_agents_markdown_layers(tmp_path, max_layers=3)
    assert len(layers) == 3
    assert layers[0].path == "AGENTS.md"


def test_root_only_matches_the_legacy_single_layer_render(tmp_path: Path) -> None:
    from agent_os_core import agents_markdown_system_section

    (tmp_path / "AGENTS.md").write_text("# Project rules\nBe careful.\n", encoding="utf-8")
    discovered = discover_agents_markdown_layers(tmp_path)
    assert len(discovered) == 1
    # the common root-only case renders exactly like the legacy section (no drift)
    assert layered_agents_markdown_system_section(discovered) == (
        agents_markdown_system_section(discovered[0])
    )


def _system_prompt(root: Path) -> str:
    app = AgentOSApplication(database=root / "agent-os.sqlite3", workspace=root)
    app.provider = DeterministicProvider(
        scripted=(("ok", ()),), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    _, loop = app.open_chat_session("hi", DeferredApprovalGateway())
    return loop.history[0].content


def test_chat_prompt_includes_nested_layers(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rules\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "AGENTS.md").write_text("nested rules\n", encoding="utf-8")
    system = _system_prompt(tmp_path)
    assert "Project AGENTS.md" in system
    assert "root rules" in system
    assert "Nested AGENTS.md" in system
    assert "nested rules" in system
    assert "path=pkg/AGENTS.md" in system


def test_explicit_loop_config_still_wins(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("root rules\n", encoding="utf-8")
    app = AgentOSApplication(database=tmp_path / "agent-os.sqlite3", workspace=tmp_path)
    app.provider = DeterministicProvider(
        scripted=(("ok", ()),), invocation_binding=app.provider.invocation_binding
    )
    app.provider_configured = True
    _, loop = app.open_chat_session(
        "hi", DeferredApprovalGateway(), loop_config=AgentLoopConfig(system_prompt="EXPLICIT")
    )
    assert loop.history[0].content == "EXPLICIT"
