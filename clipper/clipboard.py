"""Copy the prompt using the desktop's clipboard, with no extra Python dependency."""

import atexit
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys

_holder = None


def close_clipboard():
    global _holder
    if _holder is not None:
        if _holder.poll() is None:
            _holder.terminate()
            try:
                _holder.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _holder.kill()
                _holder.wait()
        if _holder.stdout:
            _holder.stdout.close()
        if _holder.stdin and not _holder.stdin.closed:
            _holder.stdin.close()
        _holder = None


atexit.register(close_clipboard)


def copy_prompt(text):
    global _holder
    commands = []
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(["wl-copy", "--type", "text/plain;charset=utf-8"])
    if os.environ.get("DISPLAY"):
        commands.extend((["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]))
    for command in commands:
        if shutil.which(command[0]):
            try:
                result = subprocess.run(
                    command, input=text, text=True, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass

    # Fedora/GNOME already provides GTK in its system Python. Keep this small
    # helper alive while the user pastes; clipboard owners must serve requests.
    if not commands or not Path("/usr/bin/python3").is_file():
        return False
    close_clipboard()
    environment = os.environ.copy()
    if environment.get("DISPLAY"):
        environment["GDK_BACKEND"] = "x11"
    try:
        _holder = subprocess.Popen(
            ["/usr/bin/python3", str(Path(__file__).resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment,
        )
        _holder.stdin.write(text.encode("utf-8"))
        _holder.stdin.close()
        ready, _, _ = select.select([_holder.stdout], [], [], 5)
        if ready and _holder.stdout.readline() == b"ready\n":
            return True
    except OSError:
        pass
    close_clipboard()
    return False


def serve_gtk():
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    text = sys.stdin.buffer.read().decode("utf-8")
    if not Gtk.init_check()[0]:
        return 1
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)

    def ready():
        print("ready", flush=True)
        return False

    GLib.idle_add(ready)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve_gtk())
