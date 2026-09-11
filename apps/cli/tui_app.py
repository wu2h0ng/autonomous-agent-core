"""M2 textual TUI: thin presentation layer over TuiController.

All protocol behavior lives in apps/cli.tui_controller (hermetically
tested); this module only binds controller state to widgets and schedules
incremental stream polls. textual is a UI-only extra (frozen D2 boundary).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label, RichLog

from apps.cli.tui_controller import (
    STATUS_AWAITING_APPROVAL,
    STATUS_STALLED,
    TuiController,
)

POLL_INTERVAL_SECONDS = 0.1


class AgentTuiApp(App[None]):
    """Rich terminal client for one Agent OS surface session."""

    TITLE = "Agent OS · Terminal Coding Agent"

    BINDINGS = [
        Binding("f2", "cycle_mode", "mode"),
        Binding("y", "approve", "approve"),
        Binding("n", "reject", "reject"),
        Binding("ctrl+c", "quit", "quit"),
    ]

    def __init__(self, controller: TuiController) -> None:
        super().__init__()
        self._controller = controller
        # Track rendered messages ourselves: RichLog.lines counts physical
        # wrapped rows, not messages, so len(chat.lines) is wrong as a
        # message cursor once any message wraps.
        self._rendered_messages = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield RichLog(id="chat", wrap=True, markup=True)
            with Horizontal(id="approval-bar"):
                yield Label("", id="approval")
            yield Input(placeholder="message the agent…", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_chat()
        self.set_interval(POLL_INTERVAL_SECONDS, self._poll)

    # -- polling -----------------------------------------------------------
    def _poll(self) -> None:
        self._controller.poll_stream()
        self._controller.tick()
        self._refresh_chat()

    def _refresh_chat(self) -> None:
        chat = self.query_one("#chat", RichLog)
        messages = self._controller.messages
        for message in messages[self._rendered_messages :]:
            style = "bold cyan" if message.role == "user" else "default"
            text = message.content + (
                "  [dim]…stream interrupted[/dim]" if message.interrupted else ""
            )
            chat.write(
                f"[{style}]{message.role}> {text}[/{style}]"
                if message.role == "user"
                else f"{message.role}> {text}"
            )
            self._rendered_messages += 1
        approval = self.query_one("#approval", Label)
        if self._controller.status == STATUS_AWAITING_APPROVAL:
            approval.update(
                f"approval required: {self._controller.pending_preview}  [y] approve / [n] reject"
            )
        elif self._controller.status == STATUS_STALLED:
            approval.update("stream stalled; waiting for the runtime…")
        else:
            approval.update("")
        self.sub_title = (
            f"{self._controller.status_line()} · {self._controller.usage_line()}"
        )

    # -- input -------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        if text in {"/exit", "/quit"}:
            self.exit()
            return
        try:
            self._controller.submit(text)
        except (RuntimeError, ValueError) as exc:
            self.query_one("#chat", RichLog).write(f"[red]error: {exc}[/red]")
        self._refresh_chat()

    # -- key actions ---------------------------------------------------------
    def action_cycle_mode(self) -> None:
        self._controller.cycle_mode()
        self._refresh_chat()

    def action_approve(self) -> None:
        if self._controller.status != STATUS_AWAITING_APPROVAL:
            return
        self._controller.approve(reason="approved in TUI")
        self._refresh_chat()

    def action_reject(self) -> None:
        if self._controller.status != STATUS_AWAITING_APPROVAL:
            return
        self._controller.reject(reason="rejected in TUI")
        self._refresh_chat()


def run_tui(controller: TuiController) -> None:
    AgentTuiApp(controller).run()
