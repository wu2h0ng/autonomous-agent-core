"""Streaming terminal UI for Agent OS Mandate terminal.

Uses Rich Live when installed; otherwise ANSI progressive fallback.
Not Ink/Ratatui (those are TS/Rust); this is the Python-native equivalent surface.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, TextIO


@dataclass
class TerminalFrame:
    status: str = ""
    assistant: str = ""
    tools: list[str] = field(default_factory=list)


class TerminalRenderer:
    def __init__(self, stdout: TextIO | None = None) -> None:
        self._stdout = stdout or sys.stdout
        self._rich = None
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.panel import Panel
            from rich.text import Text

            self._Console = Console
            self._Live = Live
            self._Panel = Panel
            self._Text = Text
            self._console = Console(file=self._stdout)
            self._rich = True
        except Exception:
            self._rich = False
        self._live = None
        self._frame = TerminalFrame()

    @property
    def rich_enabled(self) -> bool:
        return bool(self._rich)

    def start(self, title: str = "Agent OS Terminal") -> None:
        self._frame = TerminalFrame(status=title)
        if self._rich:
            self._live = self._Live(
                self._render_rich(),
                console=self._console,
                refresh_per_second=12,
            )
            self._live.start()
        else:
            self._write(f"\n=== {title} ===\n")

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def set_status(self, status: str) -> None:
        self._frame.status = status
        self._refresh()

    def append_assistant(self, delta: str) -> None:
        self._frame.assistant += delta
        self._refresh(stream_plain=delta)

    def add_tool(self, line: str) -> None:
        self._frame.tools.append(line)
        if len(self._frame.tools) > 12:
            self._frame.tools = self._frame.tools[-12:]
        self._refresh()
        if not self._rich:
            self._write(f"[tool] {line}\n")

    def set_assistant(self, text: str) -> None:
        self._frame.assistant = text
        self._refresh()

    def _refresh(self, stream_plain: str | None = None) -> None:
        if self._live is not None:
            self._live.update(self._render_rich())
        elif stream_plain:
            self._write(stream_plain)

    def _render_rich(self):  # noqa: ANN201
        body = self._Text(self._frame.assistant or "")
        tools = "\n".join(self._frame.tools) if self._frame.tools else "(no tools yet)"
        return self._Panel(
            body,
            title=self._frame.status or "Agent OS",
            subtitle=tools[:200],
            border_style="cyan",
        )

    def _write(self, text: str) -> None:
        self._stdout.write(text)
        self._stdout.flush()


def stream_text_callback(renderer: TerminalRenderer) -> Callable[[str], None]:
    return renderer.append_assistant
