"""Copy prompts and publishing text, including after the main program exits."""

import atexit
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

_holder: subprocess.Popen[bytes] | None = None
_keep_alive = False


def close_clipboard() -> None:
    global _holder, _keep_alive
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
    _keep_alive = False


def _cleanup() -> None:
    if not _keep_alive:
        close_clipboard()


atexit.register(_cleanup)


def copy_text(text: str, *, persist: bool = False) -> bool:
    global _holder, _keep_alive
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
                )
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                pass

    if not commands or not Path("/usr/bin/python3").is_file():
        return False
    close_clipboard()
    environment = os.environ.copy()
    if environment.get("DISPLAY"):
        environment["GDK_BACKEND"] = "x11"
    try:
        args = ["/usr/bin/python3", str(Path(__file__).resolve())]
        if persist:
            args.append("--persist")
        _holder = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
        assert _holder.stdin is not None and _holder.stdout is not None
        _holder.stdin.write(text.encode("utf-8"))
        _holder.stdin.close()
        ready, _, _ = select.select([_holder.stdout], [], [], 5)
        if ready and _holder.stdout.readline() == b"ready\n":
            _keep_alive = persist
            return True
    except OSError:
        pass
    close_clipboard()
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
