"""M2 textual TUI: thin presentation layer over TuiController.

All protocol behavior lives in apps/cli.tui_controller (hermetically
tested); this module only binds controller state to widgets and schedules
incremental stream polls. textual is a UI-only extra (frozen D2 boundary).
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Header, Input, RichLog, Static

from apps.cli.tui_controller import (
    STATUS_AWAITING_APPROVAL,
    STATUS_IDLE,
    STATUS_STALLED,
    STATUS_STREAMING,
    TuiController,
)

POLL_INTERVAL_SECONDS = 0.1


class AgentTuiApp(App[None]):
    """Rich terminal client for one Agent OS surface session."""

    TITLE = "Agent OS · Terminal Coding Agent"

    BINDINGS = [
        Binding("f2", "cycle_mode", "approvals"),
        Binding("left", "select_approve", "approve option", show=False, priority=True),
        Binding("right", "select_reject", "reject option", show=False, priority=True),
        Binding("y", "approve", "approve"),
        Binding("n", "reject", "reject"),
        Binding("ctrl+c", "quit", "quit"),
    ]

    CSS = """
    #main {
        height: 1fr;
    }

    #conversation {
        width: 1fr;
    }

    #chat {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
    }

    #prompt {
        margin: 0 1 1 1;
        border: tall $accent;
    }

    #hints {
        height: 1;
        margin: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, controller: TuiController) -> None:
        super().__init__()
        self._controller = controller
        # Track rendered messages ourselves: RichLog.lines counts physical
        # wrapped rows, not messages, so len(chat.lines) is wrong as a
        # message cursor once any message wraps.
        self._rendered_messages = 0
        self._rendered_activity = 0
        self._rendered_todo_signature: tuple[tuple[str, str, str], ...] = ()
        self._approval_selection = "approve"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="conversation"):
                yield RichLog(id="chat", wrap=True, markup=True)
                yield Input(placeholder="Tell the agent what to do…", id="prompt")
                yield Static("/ commands · @ files · ! shell", id="hints")

    def on_mount(self) -> None:
        self._refresh_chat()
        self.set_interval(POLL_INTERVAL_SECONDS, self._poll)

    # -- polling -----------------------------------------------------------
    def _poll(self) -> None:
        self._controller.poll_stream()
        if self._controller.status not in {STATUS_STREAMING, STATUS_STALLED}:
            self._controller.refresh_events()
        self._controller.tick()
        self._refresh_chat()

    def _refresh_chat(self) -> None:
        try:
            chat = self.query_one("#chat", RichLog)
        except NoMatches:
            return
        messages = self._controller.messages
        # The trailing assistant message is still being appended to in place
        # while a turn is in flight; rendering it now would freeze a prefix
        # on screen. Hold it back until the turn reaches an idle state, then
        # render the full text once.
        pending = len(messages)
        if (
            pending > self._rendered_messages
            and messages[-1].role == "assistant"
            and self._controller.status != STATUS_IDLE
        ):
            pending -= 1
        for message in messages[self._rendered_messages : pending]:
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
        if self._controller.status == STATUS_STALLED:
            chat.write("[yellow]stream stalled; waiting for the runtime…[/yellow]")
        self.sub_title = (
            f"{self._controller.status_line()} · {self._controller.usage_line()}"
        )
        self._refresh_inline_plan(chat)
        self._refresh_inline_activity(chat)

    def _refresh_inline_plan(self, chat: RichLog) -> None:
        if not self._controller.todos:
            return
        signature = tuple(
            (item["id"], item["content"], item["status"])
            for item in self._controller.todos
        )
        if signature == self._rendered_todo_signature:
            return
        self._rendered_todo_signature = signature
        rows = ["[bold]plan[/bold]"]
        icons = {"done": "✓", "in_progress": "▶", "pending": "•"}
        for item in self._controller.todos:
            rows.append(f"{icons[item['status']]} {item['content']}")
        chat.write("\n".join(rows))

    def _refresh_inline_activity(self, chat: RichLog) -> None:
        if not self._controller.activity:
            return
        icons = {
            "proposed": "…",
            "succeeded": "✓",
            "failed": "✗",
        }
        for item in self._controller.activity[self._rendered_activity :]:
            if item.status == "waiting approval":
                row = f"permission request  {item.capability_id}"
                if item.preview:
                    row = f"{row} — {_compact_preview(item.preview)}"
                if self._approval_selection == "reject":
                    row = f"{row}\n    Approve    › Reject"
                else:
                    row = f"{row}\n  › Approve      Reject"
                chat.write(row)
                self._rendered_activity += 1
                continue
            row = f"tool {icons.get(item.status, '•')} {item.capability_id}"
            if item.preview:
                row = f"{row} — {item.preview}"
            chat.write(row)
            self._rendered_activity += 1

    # -- input -------------------------------------------------------------
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text and self._controller.status == STATUS_AWAITING_APPROVAL:
            if self._approval_selection == "reject":
                self.action_reject()
            else:
                self.action_approve()
            return
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
            return
        self._poll()

    # -- key actions ---------------------------------------------------------
    def action_cycle_mode(self) -> None:
        self._controller.cycle_mode()
        self._refresh_chat()

    def action_select_approve(self) -> None:
        if self._controller.status != STATUS_AWAITING_APPROVAL:
            return
        self._approval_selection = "approve"
        self._rerender_chat()

    def action_select_reject(self) -> None:
        if self._controller.status != STATUS_AWAITING_APPROVAL:
            return
        self._approval_selection = "reject"
        self._rerender_chat()

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

    def _rerender_chat(self) -> None:
        try:
            chat = self.query_one("#chat", RichLog)
        except NoMatches:
            return
        chat.clear()
        self._rendered_messages = 0
        self._rendered_activity = 0
        self._rendered_todo_signature = ()
        self._refresh_chat()


def _compact_preview(preview: str, *, limit: int = 96) -> str:
    lines = [line.strip() for line in preview.splitlines() if line.strip()]
    if not lines:
        return ""
    head = lines[0]
    if len(head) > limit:
        head = f"{head[: limit - 1]}…"
    if len(lines) > 1:
        return f"{head} ↵ {len(lines) - 1} lines"
    return head


def run_tui(controller: TuiController) -> None:
    AgentTuiApp(controller).run()
