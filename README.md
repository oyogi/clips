# YouTube Clips

Turn a YouTube video into subtitled clips using ChatGPT in your browser.

```bash
uv run clips.py
```

1. Enter a YouTube video URL, how many clips you want, and choose a framing style.
2. The prompt is copied to your clipboard. Paste it into ChatGPT and keep the program open.
3. Paste ChatGPT's reply back into the terminal. Type `END` on a new line and press Enter.
4. Get your clips in `output/`. The program prints the folder when finished.

Clips are always portrait **9:16 at 1080×1920**. Choose how the picture fits:

| Framing | Result |
| --- | --- |
| Blur background (default) | Keeps the whole picture over a blurred background. |
| Black bars | Keeps the whole picture and fills unused space with black. |
| Center crop | Fills the frame with a fixed crop from the center. |
| Follow faces | Fills the frame and moves the crop to follow a prominent visible face. |

To keep the whole original picture, choose **Blur background** or **Black bars**.
Face tracking samples the selected clip and smooths the movement. It briefly holds the
position when a face disappears, then returns to center. If no face is detected, the
whole clip uses a centered crop. It follows a visible face, which may not be the speaker
when several people are present. The small [OpenCV YuNet model](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
is included with its license; it runs locally on the CPU.

The terminal shows download and rendering progress. Each finished MP4 has burned-in
subtitles. A matching TXT contains its English title, description and hashtags.
Every description includes the complete original video title, added automatically if ChatGPT omits it.
The prompt targets 30–60 seconds, allowing longer clips to finish a thought.
The program shows each selection's duration and keeps the chosen caption boundaries. Posting is manual.

Existing YouTube captions are required, including YouTube's automatic captions.
English is preferred; otherwise, the program uses an available original caption track.
Subtitles keep that track's language. Videos without usable captions are skipped.
There are no API keys, Whisper, project files to manage or separate commands.
Downloads are reused automatically from `.cache/clips/`.

Clipboard copying uses `wl-copy`, `xclip` or `xsel`, with the system's GTK 3 as a fallback
(already available on this Fedora desktop). If the clipboard cannot be reached, the
prompt appears in the terminal for manual copying. For another Linux installation,
install `wl-clipboard` on Wayland or `xclip` on X11 if needed.

Requires Python 3.12+, uv, FFmpeg with libass, AAC and either libx264 or libopenh264,
and Node or Deno for yt-dlp. `uv run` installs the Python dependencies automatically:
yt-dlp, pysubs2, Rich and OpenCV. No API keys or speech recognition are used.
