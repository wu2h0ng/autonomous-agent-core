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
