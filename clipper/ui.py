"""Terminal layout, input, and progress display."""

import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich.table import Column, Table
from rich.text import Text
from rich.theme import Theme

from .download import SourceDownload
from .models import Framing, ProgressCallback, Transcript
from .render import Encoder

PALETTE = {"accent": "#d6a35e", "success": "#69b4a2", "error": "#e27878"}
THEME = Theme(
    PALETTE
    | {
        "muted": "dim",
        "warning": PALETTE["accent"],
        "heading": f"bold {PALETTE['accent']}",
        "result": f"bold {PALETTE['success']}",
    }
)
console = Console(highlight=False, theme=THEME)
LAYOUTS: tuple[tuple[str, str, Framing], ...] = (
    ("Faces", "Follow one person · Split two · Full picture otherwise", "face"),
    ("Black", "Full picture, black background", "black"),
)


def header(encoder: Encoder) -> None:
    console.print("\n[bold]clips[/bold]  [muted]/  YouTube to portrait video[/muted]")
    console.print(
        f"[muted]1080 × 1920 · 30 fps[/muted]   [success]{encoder.kind}[/success] [muted]{encoder.name}[/muted]"
    )


def section(title: str) -> None:
    console.print()
    console.rule(Text(title, style="heading"), align="left", style="dim")
    console.print()


def video_details(source: Transcript) -> None:
    video = source.video
    console.print(Text(video.title, style="bold"))
    meta = [video.channel] if video.channel else []
    if video.duration:
        minutes, seconds = divmod(round(video.duration), 60)
        meta.append(f"{minutes}:{seconds:02d}")
    meta.append(f"{source.language} captions ({'automatic' if source.automatic else 'manual'})")
    console.print(Text(" · ".join(meta), style="muted"))
    console.print()


def choose_layout() -> Framing:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="accent")
    table.add_column(style="bold")
    table.add_column(style="muted")
    for number, (label, detail, _) in enumerate(LAYOUTS, 1):
        table.add_row(str(number), label, detail)
    console.print()
    console.print(table)
    console.print()
    answer = Prompt.ask(
        "Framing",
        choices=[str(i) for i in range(1, len(LAYOUTS) + 1)],
        default="1",
        console=console,
    )
    return LAYOUTS[int(answer) - 1][2]


def read_reply(download: SourceDownload) -> str:
    if not sys.stdin.isatty() or not console.is_terminal or console.is_dumb_terminal:
        console.print("Paste the JSON reply. Finish with END on a new line.")
        lines = []
        while (line := input()).strip() != "END":
            lines.append(line)
        return "\n".join(lines)

    editor = TextArea(multiline=True, scrollbar=True, height=max(3, min(6, console.height - 8)))
    bindings = KeyBindings()

    def submit(event: KeyPressEvent) -> None:
        lines = editor.text.rstrip().splitlines()
        if lines and lines[-1].strip() == "END":
            lines.pop()
        event.app.exit(result="\n".join(lines))

    @bindings.add("c-d")
    def finish(event: KeyPressEvent) -> None:
        if editor.text.strip():
            submit(event)
        else:
            event.app.exit(exception=EOFError())

    @bindings.add("enter")
    def newline_or_submit(event: KeyPressEvent) -> None:
        document = editor.document
        if document.current_line.strip() == "END" and not document.text_after_cursor.strip():
            submit(event)
        else:
            editor.buffer.newline(copy_margin=False)

    @bindings.add("c-c")
    def cancel(event: KeyPressEvent) -> None:
        event.app.exit(exception=KeyboardInterrupt())

    def status() -> StyleAndTextTuples:
        state = download.poll()
        if state.error:
            return [("class:error", f"Download failed: {state.error}")]
        if state.source:
            return [("class:success", "Video downloaded")]
        detail = f"  {state.fraction:.0%}" if state.fraction is not None else "…"
        return [("class:accent", state.stage + detail)]

    return Application[str](
        layout=Layout(
            HSplit(
                [
                    Frame(editor, title="ChatGPT reply"),
                    Window(FormattedTextControl(status), height=1),
                    Window(
                        FormattedTextControl(
                            "Ctrl+D submit · END + Enter also works · Ctrl+C quit"
                        ),
                        height=1,
                        style="class:muted",
                    ),
                ]
            ),
            focused_element=editor,
        ),
        key_bindings=bindings,
        style=Style.from_dict(
            PALETTE
            | {
                "frame.border": "ansibrightblack",
                "frame.label": PALETTE["accent"],
                "muted": "ansibrightblack",
            }
        ),
        color_depth=ColorDepth.DEPTH_1_BIT if "NO_COLOR" in os.environ else None,
        erase_when_done=True,
        refresh_interval=0.25,
    ).run()


@contextmanager
def progress(label: str, kind: str = "") -> Iterator[ProgressCallback]:
    with Progress(
        SpinnerColumn(style="accent"),
        TextColumn("{task.description}", table_column=Column(ratio=1)),
        BarColumn(
            bar_width=None,
            complete_style="accent",
            finished_style="success",
            table_column=Column(ratio=1),
        ),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        expand=True,
        transient=True,
    ) as bar:
        task = bar.add_task(label, total=None)

        def update(stage: str, fraction: float | None) -> None:
            description = f"Encoding · {kind}" if stage == "Encoding" and kind else stage
            total = 100 if fraction is not None else None
            if bar.tasks[task].description != description:
                bar.reset(task, description=description, total=total)
            bar.update(task, description=description, total=total, completed=(fraction or 0) * 100)

        yield update


def summary(paths: Sequence[Path], total: int, elapsed: float, copied: bool) -> None:
    console.print()
    noun = "clip" if len(paths) == 1 else "clips"
    console.print(f"[result]Saved {len(paths)} {noun}[/result]  [muted]{elapsed:.1f}s[/muted]")
    if len(paths) < total:
        console.print(f"[warning]{total - len(paths)} could not be rendered.[/warning]")
    folder = paths[0].parent
    console.print(Text(str(folder), style=f"link {folder.resolve().as_uri()}"))
    console.print(
        "[success]Publishing text copied.[/success]"
        if copied
        else "[muted]MP4 video + TXT publishing text[/muted]"
    )
    console.print()
