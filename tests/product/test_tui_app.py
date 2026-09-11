"""M2 textual TUI smoke test via textual's headless pilot.

The protocol behavior is covered hermetically in test_tui_controller; this
only proves the presentation layer wires widgets, polling, and key actions
to the controller without a real terminal.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, RichLog

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
            assert "ACCEPT_READ_ONLY" in (app.sub_title or "")

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
            for _ in range(4):
                await pilot.pause(0.15)
            # First poll captured only the prefix; it must not be on screen.
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
            for _ in range(4):
                await pilot.pause(0.15)
            text = "\n".join(str(line.text) for line in chat.lines)
            assert "CHUNK-ONE CHUNK-TWO" in text

    asyncio.run(_drive())
