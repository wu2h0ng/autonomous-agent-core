"""M2 textual TUI smoke test via textual's headless pilot.

The protocol behavior is covered hermetically in test_tui_controller; this
only proves the presentation layer wires widgets, polling, and key actions
to the controller without a real terminal.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Footer, Input, RichLog, Static

from apps.cli.tui_app import AgentTuiApp
from apps.cli.tui_controller import TuiController
from agent_os_contracts import SurfaceStreamFrameKind

from test_tui_controller import _FakeStreamClient, _frame


def _app_client() -> _FakeStreamClient:
    client = _FakeStreamClient(
        frames=[
            _frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": "Hello"}),
            _frame(2, SurfaceStreamFrameKind.CHUNK, {"delta": " world"}),
            _frame(3, SurfaceStreamFrameKind.STREAM_END, {}),
        ]
    )
    client.queue_turn_completed(total_tokens=12)
    return client


def test_tui_app_streams_and_shows_unknown_cost() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "say hi"
            await pilot.click("#prompt")
            await pilot.press("enter")
            for _ in range(5):
                await pilot.pause(0.15)
            chat = app.query_one("#chat", RichLog)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "user> say hi" in text
            assert "assistant> Hello world" in text
            assert "UNKNOWN" in (app.sub_title or "")

    asyncio.run(_drive())


def test_tui_app_shows_home_screen_on_empty_startup() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test():
            home = app.query_one("#home", Static)
            text = str(home.content)
            assert "Welcome to Agent OS" in text
            assert "Directory:" in text
            assert "Session:" in text
            assert "Mode:" in text
            assert "Version:" in text
            assert "No session yet" in text

    asyncio.run(_drive())


def test_tui_app_hides_home_screen_after_first_message() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "say hi"
            await pilot.click("#prompt")
            await pilot.press("enter")
            for _ in range(5):
                await pilot.pause(0.15)
            home = app.query_one("#home", Static)
            assert str(home.content) == ""

    asyncio.run(_drive())


def test_tui_app_f2_cycles_permission_mode() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.press("f2")
            await pilot.pause(0.1)
            assert client.mode_calls == ["ACCEPT_READ_ONLY"]
            assert "Approvals: auto-read" in (app.sub_title or "")
            assert "ASK" not in (app.sub_title or "")
            assert "ACCEPT_READ_ONLY" not in (app.sub_title or "")

    asyncio.run(_drive())


def test_tui_app_renders_new_messages_after_a_wrapping_message() -> None:
    # Regression: the old cursor used len(RichLog.lines), which counts
    # physical wrapped rows. After one wrapping assistant reply, later
    # messages were silently never rendered. The app must track messages,
    # not rows.
    long_reply = "lorem ipsum dolor sit amet " * 40
    client = _FakeStreamClient(
        frames=[
            _frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": long_reply}),
            _frame(2, SurfaceStreamFrameKind.STREAM_END, {}),
        ]
    )
    client.queue_turn_completed(total_tokens=50)
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "first"
            await pilot.click("#prompt")
            await pilot.press("enter")
            for _ in range(5):
                await pilot.pause(0.15)
            chat = app.query_one("#chat", RichLog)
            # The reply wraps: physical rows far exceed the 3 messages.
            assert len(chat.lines) > 10
            first_render = "\n".join(str(line.text) for line in chat.lines)
            assert "lorem ipsum" in first_render

            # Second turn after the wrapping message completed.
            client.frames.extend(
                [
                    _frame(
                        3, SurfaceStreamFrameKind.CHUNK, {"delta": "SECOND-TURN-REPLY"}
                    ),
                    _frame(4, SurfaceStreamFrameKind.STREAM_END, {}),
                ]
            )
            client.queue_turn_completed(total_tokens=7)
            app.query_one("#prompt", Input).value = "second"
            await pilot.click("#prompt")
            await pilot.press("enter")
            for _ in range(5):
                await pilot.pause(0.15)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "SECOND-TURN-REPLY" in text
            assert "user> second" in text

    asyncio.run(_drive())


def test_tui_app_shows_full_reply_when_chunks_arrive_across_polls() -> None:
    # Regression: a message was rendered whole on the first poll that saw
    # it; chunks appended afterwards mutated the message in place without
    # re-rendering, so the on-screen reply was frozen at the first prefix.
    # The in-flight assistant message must be held back until the turn
    # completes, then rendered in full.
    client = _FakeStreamClient(
        frames=[
            _frame(1, SurfaceStreamFrameKind.CHUNK, {"delta": "CHUNK-ONE "}),
        ]
    )
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app.query_one("#prompt", Input).value = "stream please"
            await pilot.click("#prompt")
            await pilot.press("enter")
            await pilot.pause(0.1)
            # Drive polls deterministically instead of relying on wall-clock
            # intervals: the first poll captures only the prefix chunk.
            app._poll()
            chat = app.query_one("#chat", RichLog)
            early = "\n".join(str(line.text) for line in chat.lines)
            assert "user> stream please" in early
            assert "CHUNK-ONE" not in early

            # Remaining chunks land in a later poll.
            client.frames.extend(
                [
                    _frame(2, SurfaceStreamFrameKind.CHUNK, {"delta": "CHUNK-TWO"}),
                    _frame(3, SurfaceStreamFrameKind.STREAM_END, {}),
                ]
            )
            client.queue_turn_completed(total_tokens=21)
            app._poll()
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "CHUNK-ONE CHUNK-TWO" in text

    asyncio.run(_drive())


def test_tui_app_renders_session_todo_panel() -> None:
    client = _app_client()
    client.queue_todo_write(
        action_id="action:todo",
        receipt_id="receipt:todo",
        status="SUCCEEDED",
        output_todos=[
            {"id": "a", "content": "write tests", "status": "done"},
            {"id": "b", "content": "wire TUI panel", "status": "in_progress"},
            {"id": "c", "content": "run verification", "status": "pending"},
        ],
    )
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app._poll()
            chat = app.query_one("#chat", RichLog)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "plan" in text
            assert "✓ write tests" in text
            assert "▶ wire TUI panel" in text
            assert "• run verification" in text

    asyncio.run(_drive())


def test_tui_app_renders_tool_activity_panel() -> None:
    client = _app_client()
    client.queue_tool_activity(
        action_id="action:read",
        capability_id="workspace.read",
        status="SUCCEEDED",
    )
    client.queue_tool_activity(
        action_id="action:test",
        capability_id="workspace.run_tests",
        status="FAILED",
    )
    client.queue_approval_pending()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app._poll()
            chat = app.query_one("#chat", RichLog)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "tool" in text
            assert "✓ workspace.read" in text
            assert "✗ workspace.run_tests" in text
            assert "permission request" in text
            assert "workspace.shell" in text
            assert "run: pytest" in text
            assert "› Approve" in text
            assert "Reject" in text

    asyncio.run(_drive())


def test_tui_app_does_not_render_footer_shortcut_bar() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test():
            assert list(app.query(Footer)) == []

    asyncio.run(_drive())


def test_tui_app_shows_mainstream_command_hints_without_footer() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test():
            hints = app.query_one("#hints", Static)
            text = str(hints.content)
            assert "/ commands" in text
            assert "@ files" in text
            assert "! shell" in text
            assert list(app.query(Footer)) == []

    asyncio.run(_drive())


def test_tui_app_shows_mainstream_status_bar() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test():
            status = app.query_one("#status", Static)
            text = str(status.content)
            assert "manual" in text
            assert "context:" in text
            assert "0/" in text
            assert "Agent OS" in text

    asyncio.run(_drive())


def test_tui_app_shows_command_palette_when_slash_is_typed() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/"
            await pilot.pause(0.1)
            palette = app.query_one("#command-palette", Static)
            text = str(palette.content)
            assert "› /model" in text
            assert "choose model and reasoning effort" in text
            assert "/permissions" in text
            assert "choose what Agent OS is allowed to do" in text
            assert "/exit" in text

    asyncio.run(_drive())


def test_tui_app_hides_command_palette_when_prompt_is_not_a_command() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "ordinary task"
            await pilot.pause(0.1)
            palette = app.query_one("#command-palette", Static)
            assert str(palette.content) == ""

    asyncio.run(_drive())


def test_tui_app_command_palette_filters_by_prefix() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/per"
            await pilot.pause(0.1)
            palette = app.query_one("#command-palette", Static)
            text = str(palette.content)
            assert "› /permissions" in text
            assert "/model" not in text
            assert "/exit" not in text

    asyncio.run(_drive())


def test_tui_app_command_palette_selection_moves_with_arrow_keys() -> None:
    client = _app_client()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/"
            await pilot.pause(0.1)
            await pilot.press("down")
            palette = app.query_one("#command-palette", Static)
            text = str(palette.content)
            assert "  /model" in text
            assert "› /permissions" in text

    asyncio.run(_drive())


def test_tui_app_permission_prompt_selection_can_move_to_reject() -> None:
    client = _app_client()
    client.queue_approval_pending()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app._poll()
            chat = app.query_one("#chat", RichLog)
            before = "\n".join(str(line.text) for line in chat.lines)
            assert "› Approve" in before

            await pilot.press("right")
            app._poll()
            after = "\n".join(str(line.text) for line in chat.lines)
            assert "Approve    › Reject" in after

    asyncio.run(_drive())


def test_tui_app_enter_applies_selected_permission_option() -> None:
    client = _app_client()
    client.queue_approval_pending()
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            app._poll()
            await pilot.press("right")
            await pilot.click("#prompt")
            await pilot.press("enter")
            assert client.approval_calls == [("digest:1", "REJECT")]

    asyncio.run(_drive())


def test_tui_app_permission_prompt_compacts_long_multiline_preview() -> None:
    client = _app_client()
    client.queue_approval_pending(
        preview="run: pytest\nline 1\nline 2\nline 3\nline 4\nline 5"
    )
    controller = TuiController(
        client=client,  # type: ignore[arg-type]
        session_id="session:1",
        task_id="task:1",
    )
    app = AgentTuiApp(controller)

    async def _drive() -> None:
        async with app.run_test():
            app._poll()
            chat = app.query_one("#chat", RichLog)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "run: pytest ↵ 5 lines" in text
            assert "line 5" not in text

    asyncio.run(_drive())
