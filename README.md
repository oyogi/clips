# YouTube Clips

A small Linux terminal app that turns YouTube videos into subtitled clips for
Reels, TikTok and Shorts. Use ChatGPT in your browser to choose the moments;
the app handles downloading, framing and rendering. No API key or speech
transcription service is needed.

## Features

- Portrait MP4 clips at **1080×1920, 30 fps**, with burned-in subtitles and active-word highlights.
- Automatic framing: follow one face, stack two faces, or keep the full picture on black when there are no faces or several. Manual framing remains available.
- Existing YouTube captions, including automatic captions. Videos without captions are skipped.
- Downloads run while you use ChatGPT. VA-API GPU encoding is selected when available, with CPU fallback.
- Each clip includes a TXT with its title, description, hashtags and the full source video title.
- Automatic clipboard copying for the ChatGPT prompt and, when one clip is created, its publishing text.
- A selection prompt that compares a larger candidate pool and ranks clips for hook, clarity, payoff and retention.
- Optional YouTube and Instagram publishing, with scheduling and a local upload queue; TikTok inbox drafts.
- An opt-in automatic mode that frames and uploads clips using saved choices, without a review step.

Finished files go into `output/`. Source videos and working files are temporary
and removed when the session ends. Publishing is optional; account setup and
platform limits are covered in [Publishing accounts](docs/publishing.md).
Word highlights use estimated timing within the existing captions.

## Requirements

- Linux and Python **3.12+**.
- `ffmpeg` and `ffprobe`, with libass, AAC and a working H.264 encoder:
  VA-API, libx264 or libopenh264.
- Node.js or Deno for yt-dlp's YouTube support.
- For clipboard integration: `wl-copy`, `xclip`, `xsel` or system Python with GTK 3.

Face tracking uses the bundled [OpenCV YuNet model](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
and compares available CPU and GPU backends, choosing GPU only when it is faster
on a sample frame. CPU fallback is automatic. Its license is included in `clipper/assets/`.
Run `youtube-clips doctor` to check encoding and face-detection hardware.
See [GPU support](docs/gpu.md) for driver details.

## Install and run

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
youtube-clips
```

Alternatively, use `uv run clips.py`. With dependencies installed,
`python clips.py` works too; uv is optional.

Follow the prompts, paste the generated prompt into ChatGPT, then paste its JSON
reply into the terminal. Submit with **Ctrl+D**, or type `END` on a new line and
press Enter.

Use `youtube-clips auto` for automatic framing and uploads after pasting the
ChatGPT reply. Its first run saves your destinations and immediate or spaced
posting schedule. Change those choices with `youtube-clips auto-setup`.
TikTok still requires finishing drafts in its app.

## Build

No compilation is needed to run this Python project. To build an installable wheel
and source archive:

```bash
python -m pip install build
python -m build
```

Packages are written to `dist/`, including the face-detection model and its license.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
```
