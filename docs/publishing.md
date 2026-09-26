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

This app uses **Instagram API with Facebook Login**. You need an Instagram
**Business or Creator** account, a Facebook Page linked to it, and a Facebook
user with full control of that Page. A personal Instagram account will not work.
Meta also offers an Instagram Login integration; its credentials and permissions
are different. Follow the Facebook Login setup below.

### 1. Prepare the account and Meta app

1. In Instagram settings, switch to a professional account if needed. In your
   Facebook Page's settings, open **Linked accounts** and connect that Instagram
   account. Confirm that you can manage this Page from your Facebook user.
2. Open [Meta's app dashboard](https://developers.facebook.com/apps/) and create
   an app. Choose the setup for **Instagram API with Facebook Login**; if the
   wizard asks for an app type, use **Business**. Meta changes its wizard labels,
   so check the integration name in the app dashboard.
3. Use your Facebook user as an app administrator or developer for testing with
   your own account. Complete any business or app verification the dashboard
   requires. Access for people outside the app's roles needs Meta's approval.
4. Open **App settings → Basic**. Keep the **App ID** and **App secret** available
   for the terminal. These belong to the Meta app; neither is your Instagram ID.

See Meta's [Instagram API setup and permission requirements](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-6fa9ed1d-3310-4844-ad25-f0001ab66f11).

### 2. Generate a User access token

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select **the app you just created** in the Meta App selector. Choose a **User
   access token** for your Facebook user.
3. Add all four permissions below, then select **Generate Access Token**:

   ```text
   pages_show_list
   pages_read_engagement
   instagram_basic
   instagram_content_publish
   ```

4. In Facebook's authorization dialog, grant access to the linked Page and
   Instagram account. Copy the resulting token.

If your Page is managed through a business portfolio and does not appear,
check your access to that business and whether `business_management` is required.
The [official Reels example](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample)
includes this permission in its Facebook Login flow.

### 3. Connect it here

```bash
uv run clips.py accounts
```

Choose **2 · Instagram**, then enter:

| Terminal prompt | Where to get it |
| --- | --- |
| Meta App ID | App settings → Basic |
| Meta App secret | App settings → Basic → Show |
| User access token from Graph API Explorer | The token generated in step 2 |
| Instagram account | Choose from the discovered accounts |

The program exchanges the User token for a long-lived token, checks its
permissions, and [finds the Instagram account through your Pages](https://www.postman.com/meta/instagram/request/lpx8lul/get-access-tokens-of-pages-you-manage).
It stores the selected Page's publishing token. You do not need to find or paste
an Instagram numeric ID. The App secret is used during setup and is not saved.
Long-lived tokens can still expire or be revoked; reconnect when necessary.

### If connection fails

| What you see | What to check |
| --- | --- |
| Required permissions missing from Explorer | Select your own Meta app and check its Facebook Login integration and permission access. Instagram Login uses different scope names. |
| Missing permissions in the terminal | Add the named permissions, generate a new User token, and approve them in the authorization dialog. |
| No linked Instagram accounts found | Check professional account status, the Page link, full control of the Page, and which assets you selected during authorization. |
| Token exchange fails | The App ID, App secret and User token must all belong to the same app. Generate a fresh User token. |
| API error 190 | The token is invalid, expired or revoked. Reconnect with a fresh token. |

Uploads use Graph API v25.0 and local MP4 files; no public video hosting is needed.
Instagram scheduling runs locally: the worker uploads and publishes at the chosen
time. Keep this computer awake, online and logged in. Processing can make the
actual publication a little later.

## TikTok drafts

TikTok setup requires developer app access to **video.upload**. Creating an app
and copying its key alone is not enough: TikTok must permit the requested scope,
and you must grant it during login. See the [Upload API prerequisites](https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content).

### 1. Configure the developer app

1. Sign in to [TikTok for Developers](https://developers.tiktok.com/), open
   **Manage apps**, and create or open your app.
2. Add **Login Kit** and configure its **Desktop** platform. Add this exact
   redirect URI, including the trailing slash:

   ```text
   http://127.0.0.1:8765/callback/
   ```

3. Add **Content Posting API** with upload access. In **Scopes**, add
   `video.upload`; keep `user.info.basic` for identifying your account.
4. Save the app settings. For development in **Sandbox**, add your TikTok account
   under **Target users** and apply the changes. Use that environment's client
   credentials when connecting. Sandbox is for testing and does not grant
   unrestricted publishing access.
5. Check whether `video.upload` is available to your app. If TikTok requires
   review, complete that process before connecting. The review may require a
   website, privacy policy, terms and a video demonstrating the integration.
   This tool cannot bypass that approval.

Official guides: [Desktop Login Kit](https://developers.tiktok.com/doc/login-kit-desktop),
[scopes](https://developers.tiktok.com/doc/scopes-overview),
[Sandbox setup](https://developers.tiktok.com/doc/add-a-sandbox),
[app review](https://developers.tiktok.com/doc/app-review-guidelines).

### 2. Connect it here

1. Open your app's details in TikTok's developer portal and find **Client key**
   and **Client secret**.
2. Run `uv run clips.py accounts`, choose **3 · TikTok**, and enter those values.
3. Log in to the intended TikTok account in the browser and approve the requested
   access. Keep the terminal open until it shows the connected account.

| What you see | What to check |
| --- | --- |
| Redirect URI error | Use the Desktop configuration and the exact URI above, including `http`, `127.0.0.1`, port `8765` and `/callback/`. |
| Scope error or `video.upload` not granted | Check Content Posting API, requested scopes, TikTok approval, and the permissions you accepted at login. |
| Sandbox login denied | Add your account to Target users, apply changes, and use the matching Sandbox credentials. |
| Pending-share limit | Open TikTok and finish or remove existing inbox drafts before sending more. |

### What uploading does

An upload arrives as a **TikTok inbox notification**. Open it, add the caption from
the clip's TXT file, review, and finish posting. A scheduled upload schedules
**draft delivery**, not public publication, and needs this computer awake and online.
Until your developer app has upload access, you can always upload the exported MP4
and copy its TXT caption manually.

[TikTok's Upload API](https://developers.tiktok.com/doc/content-posting-api-reference-upload-video)
requires that final in-app step. Direct Post is not implemented: its
[review and consent requirements](https://developers.tiktok.com/doc/content-sharing-guidelines)
and restrictions on private/internal tools do not suit unattended use of this app.

## Queue and recovery

After rendering, choose whether to upload. The program lists all clips with their
file paths. Review them in your video player, type a clip's number to delete its
MP4 and TXT, or press Enter to continue with the listed clips. Numbers stay the
same after deletions. Then choose destinations and a posting time for each clip.
Times use this computer's local timezone; an explicit UTC offset is also accepted.
Future times must be at least ten minutes away.

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
clips with Faces framing and no review or upload confirmation after rendering.
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
