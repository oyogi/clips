# Publishing accounts

Clips work without connected accounts. Uploading uses the platforms' official APIs,
which require developer app credentials and an account you control. These are
separate from ChatGPT; no OpenAI API key is needed.

Run `youtube-clips accounts` (or `python clips.py accounts`) to connect one account
per platform. Repeating the command lets you replace or disconnect an account.
Credentials are stored in a private database under
`${XDG_STATE_HOME:-~/.local/state}/youtube-clips/`, outside the repository.
They are protected by filesystem permissions, not encrypted.

## YouTube

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/),
   enable YouTube Data API v3, and configure its OAuth consent screen. If the app
   is in testing, add your Google account as a test user.
2. Create an OAuth client of type **Desktop app** and download its client JSON.
3. Select YouTube in account setup, enter that file's path and authorize in your
   browser. The connected channel name is shown before any uploads.

Immediate uploads offer private, unlisted or public visibility. Scheduled uploads
are sent immediately as private videos with a future `publishAt` time, then become
public. Once YouTube accepts the schedule, your computer can turn off. Processing
and platform review can delay availability. Check the returned status in
`youtube-clips queue` and manage uploaded schedules in YouTube Studio.

[Unverified API projects can be restricted to private uploads](https://developers.google.com/youtube/v3/docs/videos/insert).
OAuth testing credentials can also expire; reconnect if necessary. A local tool
cannot remove Google's verification or account restrictions.

## Instagram

Use an Instagram professional account linked to a Facebook Page and a Meta app
with Facebook Login access to that account. Obtain a long-lived access token with
`instagram_basic`, `instagram_content_publish` and `pages_read_engagement`.
Account discovery may additionally need `pages_show_list` and
`business_management`. Enter the Instagram account ID and token in account setup.
An Instagram Login token is not interchangeable with this Facebook Login flow.

The implementation uses Graph API v25.0 and uploads local MP4s through Meta's
resumable upload endpoint; you do not need to host a public video URL.
Tokens, account eligibility and app permissions remain subject to Meta's rules.
See [Meta's official Reels publishing sample](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample)
for account and permission setup.

Instagram scheduling runs locally: the worker uploads and publishes at the chosen
time. Keep this computer awake, online and logged in. Processing means the actual
publication can be a little later than the requested time.

## TikTok drafts

Create a TikTok developer app with **Desktop Login Kit** and the **Content Posting
API Upload** product, with `user.info.basic` and `video.upload` access. Register
`http://127.0.0.1:8765/callback/` as a redirect URI. Enter the app's client key and
secret in account setup, then authorize in your browser.

TikTok uploads arrive as inbox notifications. Open TikTok, add the publishing text
from the TXT file, review, and finish posting. A scheduled TikTok upload schedules
**draft delivery**, not public publication, and needs this computer awake and online.
TikTok limits pending inbox shares; clear them in the app before sending more.

[TikTok's Upload API](https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video)
requires this final in-app step. Direct Post is not implemented: its
[review and consent requirements](https://developers.tiktok.com/docs/en/content-sharing-guidelines)
and restrictions on private/internal tools do not suit unattended use of this app.

## Queue and recovery

After rendering, choose whether to upload. You can preview, edit publishing text,
skip, or delete individual MP4/TXT pairs, then select destinations and a time for
each clip. Times use this computer's local timezone; an explicit UTC offset is
also accepted. Future times must be at least ten minutes away.

The detached worker continues after the terminal closes. Keep the output files
in place until upload completion. Run `youtube-clips queue` to check results,
restart pending work after a reboot, or cancel jobs that have not started.
Use `refresh` to update the view, `cancel ID` to cancel a pending upload, or
`retry ID` to choose another time for a failed, interrupted or cancelled job.
Retries use the saved caption and the original account and file; they ask you to
verify that a post does not already exist on the destination.
This is not a system service: a reboot or logout may stop the worker. Jobs more
than 15 minutes late are marked failed instead of silently posting at another time.

Failed or interrupted jobs are not automatically retried, except for safely
resuming an active YouTube upload. An interrupted upload may already exist on the
platform; the queue keeps its remote reference when available. Check the account
before uploading again to avoid duplicates. Changing account connections never
redirects old queued jobs to a different account.

## Automatic mode

Run `youtube-clips auto` to set up saved destinations on first use, then create
clips with automatic framing and no review or upload confirmation after rendering.
You still choose the source, clip count and paste ChatGPT's reply. Every successfully
rendered clip goes into the upload queue, including when another clip failed to render.

Choose immediate uploads or spaced posting: a delay before the first clip, then
an interval between clips. Spaced YouTube posts become public at their scheduled
times; immediate uploads use your saved visibility. TikTok remains draft delivery.
Each run starts its own schedule after rendering; it does not reserve account-wide
slots or avoid times chosen by other runs.

Run `youtube-clips auto-setup` to change the saved choices. A disconnected or
replaced account requires setup again. Ordinary `youtube-clips` runs always keep
the review and upload confirmation steps.
