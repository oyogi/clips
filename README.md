# YouTube Clips

Turn a captioned YouTube video into portrait clips in one terminal session.
Paste a link, send the generated prompt to ChatGPT in your browser, then paste
its reply back. The app downloads, frames, subtitles and exports the clips.
Clip creation needs no API key or speech transcription service.

## Features

- **1080 × 1920 MP4s**, with large subtitles and a gold highlight on the current word.
- **Faces framing, by default:** follow one person, stack two with subtitles in
  the middle, or keep the whole picture on black for crowds and scenes without
  faces. Layouts hold for at least four seconds and ignore brief detection changes.
  Choose **Black** to keep the full picture throughout.
- **Better moment selection:** the prompt compares a wider candidate pool and ranks
  it for hook, clarity, payoff and retention.
- **Less waiting:** downloading overlaps the ChatGPT step; encoding uses VA-API
  when available. Face detection selects a faster GPU backend when supported.
- **Ready-to-post text:** each MP4 comes with a TXT containing its title,
  description, hashtags and the full source video title. The prompt and a single
  clip's publishing text copy to the clipboard automatically.
- **YouTube publishing:** public uploads, always marked not made for kids. Choose
  the first posting time and an interval for the remaining clips. Everything
  uploads now; YouTube handles publication after your computer turns off.
  Review individual clips or use automatic mode with saved timing.

Videos without usable captions are skipped. Word highlight timing is estimated
from the captions; face tracking detects visible people, not the active speaker.
Finished files go into `output/`. Source videos and working files are temporary.

## Requirements

Linux, **Python 3.12+**, and:

- `ffmpeg` and `ffprobe`, with libass, AAC and H.264 support through VA-API,
  libx264 or libopenh264.
- Node.js or Deno for YouTube downloads.
- `wl-copy`, `xclip`, `xsel`, or system Python with GTK 3 for clipboard support.

The bundled face model is [OpenCV YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet);
its license is included. GPU detection needs a compute driver separate from the
video encoder's driver. See [GPU support](docs/gpu.md).

## Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
youtube-clips
```

Or use `uv run clips.py`. With dependencies installed, `python clips.py` and
`python -m clipper` work too. **uv is optional.**

Paste ChatGPT's JSON reply and press **Ctrl+D**, or type `END` on a new line and
press Enter. Everything else is guided in the terminal.

| Command | Purpose |
| --- | --- |
| `youtube-clips` | Create clips and optionally review and publish |
| `youtube-clips auto` | Use Faces framing and upload without clip review |
| `youtube-clips auto-setup` | Change automatic posting timing |
| `youtube-clips accounts` | Connect or remove your YouTube account |
| `youtube-clips queue` | Check uploads, cancel jobs or retry failures |
| `youtube-clips doctor` | Check encoding and face-detection hardware |

The same commands work after `python clips.py` or `uv run clips.py`.
Automatic mode still uses your manually pasted ChatGPT reply.

Publishing uses a Google Desktop OAuth client. See [YouTube setup and scheduling](docs/publishing.md).
Keep the computer online until every upload and schedule is accepted by YouTube.
The exported MP4 and TXT files are also ready for manual posting elsewhere.

## Build

Python does not need compiling to run. To build a wheel and source archive:

```bash
python -m pip install build
python -m build
```

Artifacts are written to `dist/`, including the face model and license notices.
Building or installing can create `build/` and `youtube_clips.egg-info/`; these
generated directories are ignored by Git and can be deleted afterward.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Ruff rules are defined in `pyproject.toml`. The project’s Zed settings give that
file priority over global editor rules, so editor and terminal checks agree.
Restart the Ruff language server after changing these settings. Docstrings for
every method, per-file copyright headers, and numeric-literal style rules are
not required; Ruff's formatter handles layout.

## License

[MIT](LICENSE). The bundled YuNet model retains its original
[MIT license and attribution](clipper/assets/LICENSE-YuNet).
