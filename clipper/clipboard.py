"""Copy prompts and publishing text, including after the main program exits."""

import atexit
import os
import select
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ClipboardOwner:
    """Keep the GTK helper alive while it owns the clipboard selection."""

    process: subprocess.Popen[bytes] | None = None
    persist: bool = False

    def close(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.process.stdout:
                self.process.stdout.close()
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            self.process = None
        self.persist = False

    def cleanup(self) -> None:
        if not self.persist:
            self.close()


_owner = ClipboardOwner()
atexit.register(_owner.cleanup)


def copy_text(text: str, *, persist: bool = False) -> bool:
    commands = []
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(["wl-copy", "--type", "text/plain;charset=utf-8"])
    if os.environ.get("DISPLAY"):
        commands.extend((["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]))
    for command in commands:
        if shutil.which(command[0]):
            try:
                result = subprocess.run(
                    command,
                    input=text,
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass

    if not commands or not Path("/usr/bin/python3").is_file():
        return False
    _owner.close()
    environment = os.environ.copy()
    if environment.get("DISPLAY"):
        environment["GDK_BACKEND"] = "x11"
    try:
        args = ["/usr/bin/python3", str(Path(__file__).resolve())]
        if persist:
            args.append("--persist")
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
        _owner.process = process
        if process.stdin is None or process.stdout is None:
            raise OSError("The clipboard helper did not open its pipes.")
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
        ready, _, _ = select.select([process.stdout], [], [], 5)
        if ready and process.stdout.readline() == b"ready\n":
            _owner.persist = persist
            return True
    except OSError:
        pass
    _owner.close()
    return False


def serve_gtk(persist: bool = False) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    text = sys.stdin.buffer.read().decode("utf-8")
    if not Gtk.init_check()[0]:
        return 1
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)
    owner = Gdk.selection_owner_get(Gdk.SELECTION_CLIPBOARD)

    def ownership_changed(_clipboard: Gtk.Clipboard, _event: Gdk.EventOwnerChange) -> None:
        if owner is not None and Gdk.selection_owner_get(Gdk.SELECTION_CLIPBOARD) != owner:
            Gtk.main_quit()

    clipboard.connect("owner-change", ownership_changed)

    def ready() -> bool:
        print("ready", flush=True)
        sys.stdout.close()
        if persist:
            clipboard.set_can_store(None)
            clipboard.store()
        return False

    GLib.idle_add(ready)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_gtk(persist="--persist" in sys.argv))
