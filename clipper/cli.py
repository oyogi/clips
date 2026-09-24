"""One guided terminal session, with desktop clipboard and rendering progress."""

import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.prompt import IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from .clipboard import copy_prompt
from .manual import make_prompt, parse_reply
from .models import ClipsError
from .render import check_encoder, render_clip
from .youtube import YouTube

console = Console(highlight=False)


def choose(title, options):
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", justify="right")
    table.add_column()
    for number, (label, _) in enumerate(options, 1):
        table.add_row(str(number), label)
    console.print(f"\n[bold]{title}[/bold]")
    console.print(table)
    selection = Prompt.ask("Choose", choices=[str(i) for i in range(1, len(options) + 1)], default="1", console=console)
    return options[int(selection) - 1][1]


def read_reply():
    console.print("\n[bold cyan]Paste ChatGPT's JSON reply[/bold cyan]")
    console.print("Finish with [bold]END[/bold] on a new line. [dim]Ctrl+C to quit.[/dim]")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            return "\n".join(lines)
        lines.append(line)


def progress_bar():
    return Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
        TaskProgressColumn(), TimeElapsedColumn(), console=console,
    )


def run():
    console.print(Panel(
        "[bold cyan]YouTube Clips[/bold cyan]\n[dim]Choose a video · Ask ChatGPT · Get your clips[/dim]",
        border_style="cyan", padding=(1, 2),
    ))
    with console.status("Checking video tools...", spinner="dots"):
        encoder = check_encoder()
    youtube = YouTube(Path(".cache/clips"))
    console.rule("[bold]1 · Video[/bold]", align="left", style="cyan")
    while True:
        url = Prompt.ask("YouTube video URL [dim](Enter to quit)[/dim]", default="", show_default=False, console=console).strip()
        if not url:
            return 0
        try:
            with console.status("Reading existing captions...", spinner="dots"):
                video, cues, track = youtube.captions(url)
            break
        except ClipsError as error:
            console.print(Text(f"Skipped: {error}", style="yellow"))

    details = Text(video.title, style="bold")
    if video.channel:
        details.append(f"\n{video.channel}", style="dim")
    kind = "automatic" if track["automatic"] else "manual"
    details.append(f"\nCaptions: {track['language']} ({kind})", style="green")
    console.print(Panel(details, border_style="dim"))
    while True:
        count = IntPrompt.ask("How many clips?", default=1, console=console)
        if 1 <= count <= 100:
            break
        console.print("[yellow]Enter a number from 1 to 100.[/yellow]")

    console.rule("[bold]2 · Layout[/bold]", align="left", style="cyan")
    console.print("[dim]Portrait · 9:16 · 1080 × 1920[/dim]")
    layout = choose("Framing", [
        ("Blur background   Keep the whole picture", "blur"),
        ("Black bars        Keep the whole picture", "black"),
        ("Center crop       Fill the frame from the center", "crop"),
        ("Follow faces      Move the crop to follow a visible face", "face"),
    ])

    console.rule("[bold]3 · ChatGPT[/bold]", align="left", style="cyan")
    prompt = make_prompt(video, cues, count)
    if copy_prompt(prompt):
        console.print(Panel(
            "[bold green]Prompt copied to your clipboard.[/bold green]\n"
            "Paste it into ChatGPT, then copy its JSON reply back here.\n"
            "[dim]Keep this terminal open.[/dim]", border_style="green",
        ))
    else:
        console.print("[yellow]Clipboard unavailable. Copy the prompt between these markers.[/yellow]")
        console.print("----- PROMPT START -----", style="dim")
        console.print(prompt, markup=False, soft_wrap=True)
        console.print("----- PROMPT END -----", style="dim")
    while True:
        try:
            clips = parse_reply(read_reply(), video, cues, count)
        except ClipsError as error:
            console.print(Panel(Text(f"{error}\nPaste the corrected reply to try again."), border_style="yellow", title="Check the reply"))
            continue
        if clips:
            break
        console.print("[yellow]No clips selected. Ask ChatGPT for another selection and paste it here.[/yellow]")

    console.rule("[bold]4 · Create clips[/bold]", align="left", style="cyan")
    selection = Table("#", "Title", "Length", box=None, padding=(0, 2))
    for number, clip in enumerate(clips, 1):
        selection.add_row(str(number), Text(clip.title), f"{clip.duration:.1f}s")
    console.print(selection)
    if len(clips) < count:
        console.print(f"[yellow]ChatGPT selected {len(clips)} of the {count} requested clips.[/yellow]")
    with progress_bar() as progress:
        task = progress.add_task("Downloading source", total=None)

        def update(stage, fraction):
            progress.update(task, description=stage, total=100 if fraction is not None else None,
                            completed=fraction * 100 if fraction is not None else 0)

        source = youtube.download(video, update)
        update("Source ready", 1.0)

    output = Path("output") / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    completed = 0
    for number, clip in enumerate(clips, 1):
        try:
            with progress_bar() as progress:
                task = progress.add_task(f"Clip {number}/{len(clips)}", total=100)

                def update(stage, fraction):
                    progress.update(task, description=f"Clip {number}/{len(clips)} · {stage}", completed=fraction * 100)

                path, note = render_clip(source, clip, cues, output, number, encoder, layout=layout, progress=update)
            completed += 1
            console.print(Text(f"✓ {path.name} · {clip.title}", style="green"))
            if note:
                console.print(Text(note, style="yellow"))
        except ClipsError as error:
            console.print(Text(f"Could not render clip {number}: {error}", style="red"))

    if completed:
        summary = Text(f"Created {completed}/{count} clips\n", style="bold green")
        summary.append(str(output.resolve()), style="cyan")
        summary.append("\nMP4 videos + TXT publishing text", style="dim")
        console.print(Panel(summary, border_style="green", padding=(1, 2)))
    else:
        console.print("[red]No clips were created.[/red]")
    return 0 if completed == count else 1


def main():
    if len(sys.argv) > 1:
        console.print("Run: [bold]uv run clips.py[/bold]\nThen follow the prompts in this terminal.")
        return 0 if sys.argv[1:] in (["--help"], ["-h"]) else 1
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    try:
        return run()
    except (ClipsError, OSError) as error:
        console.print(Text(f"Error: {error}", style="red"))
        return 1
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Stopped. Finished clips and cached downloads are kept.[/dim]")
        return 130
