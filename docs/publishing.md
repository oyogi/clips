# YouTube publishing

Publishing is optional. Every upload requests **public visibility** and is marked
**not made for kids**. Scheduled clips stay private until YouTube publishes them
at the chosen time. Clip creation works without connecting an account.

## Connect your channel

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select
   your project and enable **YouTube Data API v3**.
2. Configure the app in **Google Auth Platform**. If its audience is External and
   publishing status is Testing, add your Google account under **Audience → Test users**.
3. Under **Clients**, create an OAuth client of type **Desktop app** and download
   its JSON file. See [Google's Desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app).
4. Run `youtube-clips accounts` (or `uv run clips.py accounts`), choose `connect`,
   and enter the JSON file's path. Authorize the intended channel in your browser.
   The terminal shows the connected channel name.

Run the same command to replace or disconnect the channel. Disconnecting cancels
pending local uploads; videos already uploaded to YouTube stay there.
Credentials are stored under `${XDG_STATE_HOME:-~/.local/state}/youtube-clips/`
with private filesystem permissions. They are not encrypted.

## Schedule a batch

After rendering, accept the YouTube upload offer. Open the listed MP4 paths in
your video player to review them. Type a clip number to delete its MP4 and TXT,
or press Enter to keep the remaining clips. Numbers stay stable after deletions.

Enter the first clip's posting time as `YYYY-MM-DD HH:MM`, or `now`. Then enter the
interval in **hours**; the default is `2`. For example, a first time of 18:00 and
an interval of 2 schedules three clips for **18:00, 20:00 and 22:00**. An interval
of `0.5` means 30 minutes; `0` posts the batch together. One clip only needs its
posting time.

Times use the computer's local timezone, shown in the terminal. An explicit UTC
offset is also accepted. Future times must be at least ten minutes away. Check
the generated schedule, then confirm the upload.

**All clips upload immediately**, including clips scheduled for later days.
The queue does not wait for each posting time. Keep the computer online and the
MP4 files in place until `youtube-clips queue` confirms every upload and schedule.
You can then turn the computer off: [YouTube stores the publication times](https://developers.google.com/youtube/v3/docs/videos#status.publishAt).
Processing and platform review can still delay availability.

[Unverified API projects can be restricted to private uploads](https://developers.google.com/youtube/v3/docs/videos/insert).
The app reports an unconfirmed public upload or schedule as **check account**,
so it is not mistaken for a completed publication request. Google OAuth testing
credentials can expire; reconnect if required. These are account/API restrictions,
not local settings.

## Queue and recovery

Run `youtube-clips queue` to check results, restart pending uploads after a
reboot, or cancel uploads that have not started. Use `refresh`, `cancel ID`, or
`retry ID`. Retrying asks for a new time and uses the saved caption, original
file, and original channel.

The worker can continue after the terminal closes. A reboot or logout may stop
it. Missed schedules fail instead of becoming immediate public uploads. A failed
or interrupted upload may already exist in YouTube Studio: check there before
retrying to avoid duplicates. The queue saves its video reference when available.
YouTube schedules already accepted are managed in **YouTube Studio**, not the
local queue. Changing channels never redirects an old upload to another channel.

## Automatic mode

`youtube-clips auto` uses Faces framing and uploads every finished clip without
review or a final upload confirmation. On first use, connect your channel and
save a delay before the first post plus an interval in hours. The delay starts
after rendering; `0` means the first clip goes public as soon as its upload finishes.
Both values at `0` upload the whole batch for immediate public posting.

You still choose the source, clip count and paste ChatGPT's reply. Each run starts
its own schedule; it does not reserve slots across runs. Use
`youtube-clips auto-setup` to change timing. Replacing or disconnecting the channel
requires setup again.

## Updating from the multi-platform version

The first use of publishing keeps your YouTube connection and upload history,
and removes other platforms' saved credentials and queue entries. Automatic-mode
preferences are reset once, so save your timing again. Old pending jobs with
incompatible visibility or audience settings are cancelled locally; review and
retry them to use public visibility and not made for kids. Uploaded videos and
exported MP4/TXT files are unchanged.
