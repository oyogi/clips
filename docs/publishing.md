# Publishing accounts

Instagram and TikTok setup checked against official documentation on **27 September 2026**.
The steps below use the dashboards' English labels.

Clips work without connected accounts. Uploading uses the platforms' official APIs,
which require developer app credentials and an account you control. These are
separate from ChatGPT; no OpenAI API key is needed.

Run `youtube-clips accounts` (or `python clips.py accounts`) to connect one account
per platform. Repeating the command lets you replace or disconnect an account.
Credentials are stored in a private database under
`${XDG_STATE_HOME:-~/.local/state}/youtube-clips/`, outside the repository.
They are protected by filesystem permissions, not encrypted.

| Destination | Setup route | What this program sends |
| --- | --- | --- |
| [YouTube](#youtube) | Google Desktop OAuth client | A video, optionally with a native publication schedule |
| [Instagram](#instagram) | Meta's Instagram use case **with Facebook Login** | A Reel uploaded directly from your computer |
| [TikTok](#tiktok-drafts) | Login Kit + Content Posting API; sandbox or approved app | An inbox draft that you finish in TikTok |

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

Start in **Meta for Developers**, not Meta Business Suite. In the app creation
wizard, the option is **Manage messaging and content on Instagram**. You choose
**Facebook Login later**, inside that use case.

This program uses Facebook Login because Meta documents direct local video uploads
for that integration. Instagram Login has different tokens and uses a public video
URL for publishing. A token from its **Generate access tokens** panel will not work
here. See Meta's [publishing requirements](https://developers.facebook.com/documentation/instagram-platform/content-publishing).

### 1. Link the Instagram account to a Facebook Page

Use an Instagram **Business or Creator** account and a Facebook Page you manage.
A personal Instagram account cannot use this publishing API.

1. If needed, open Instagram's profile menu → **Account type and tools** →
   **Switch to professional account** and choose Business or Creator.
2. On Facebook, use your profile menu → **See all profiles** to switch into the
   **Page**. Open its **Settings & privacy → Settings**, find **Linked accounts**,
   and connect Instagram there. Sharing a login through Accounts Center alone
   does not establish the Page link this API needs.
3. In the Page settings, **Page setup → Page access** shows who can manage it.
   Use your own Facebook user with full control for the setup below.

References: [professional accounts](https://www.facebook.com/help/instagram/2358103564437429?locale=en_US),
[Page access](https://www.facebook.com/help/510247025775149/),
[Meta's account prerequisites](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/get-started).

### 2. Create and configure the Meta app

1. Open [Create an app](https://developers.facebook.com/apps/creation/).
   Register as a developer if prompted, then enter an app name and contact email.
2. On **Use cases**, select **Manage messaging and content on Instagram**.
3. Continue through **Business** and **Requirements**. For your own account,
   choose your portfolio or **I don't want to connect a business portfolio yet**
   when offered. On **Overview**, choose **Go to dashboard**.

These are the current [app creation screens](https://developers.facebook.com/documentation/development/create-an-app).
Older apps may still use **Other → Business → Add product → Instagram**;
that older wizard is not a prerequisite for the steps below.

4. Open **Use cases**, find the Instagram use case and choose **Customize**.
   The dashboard's Instagram use-case card can also open this screen.
5. In its left menu, choose **API setup with Facebook Login**.
6. In the content-management section, click **Add all required permissions**.
   Open **Permissions and features** to check that the four permissions listed
   in step 3 below are available. `business_management` may also be added by
   this use case; keep it if your account access depends on a business portfolio.

**If you already selected Instagram Login:** Meta now permits only one Instagram
login setup per app. If Facebook Login is unavailable, create another app using
the steps above and select Facebook Login there. You can keep the existing app.
This restriction and both menu paths are in Meta's
[Instagram use-case guide](https://developers.facebook.com/documentation/development/create-an-app/instagram-use-case).

For testing your own account, the Facebook user generating the token should be
an administrator or developer under **App roles → Roles**. Access for people
outside the app's roles can require App Review and business verification.
Follow any access requirements shown for your app. This program uses a manually
generated token, so it does not need a webhook server or an OAuth callback URL
for Instagram.

### 3. Generate the Facebook User token

1. Open [Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. In the token panel, set **Meta App** to the app you just configured.
   Under **User or Page**, choose **Get User Access Token**. If this immediately
   opens Facebook authorization, complete it and return to Explorer.
3. In **Permissions**, use **Add a Permission** to add these four names, then
   click **Generate Access Token** again:

   ```text
   pages_show_list
   pages_read_engagement
   instagram_basic
   instagram_content_publish
   ```

4. In Facebook's authorization window, select the intended Page and Instagram
   account and approve the requested access. Back in Explorer, copy the value
   in **Access Token**.

If the permissions you see start with `instagram_business_`, you are using
Instagram Login. Return to step 2. The Facebook Login permissions above are
documented in [Meta's official API collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-6fa9ed1d-3310-4844-ad25-f0001ab66f11).

For a Page managed through a business portfolio, `business_management` may also
be needed. Meta's [Reels example](https://github.com/fbsamples/reels_publishing_apis/tree/main/insta_reels_publishing_api_sample)
includes it. Generate a fresh token after adding permissions.

### 4. Copy the app credentials and connect

Return to your app dashboard and open **App settings → Basic**. Copy **App ID**
and reveal **App secret** using **Show**. These are the main Meta app credentials,
not the separate Instagram app credentials shown by the other login integration.

```bash
uv run clips.py accounts
```

Choose **2 · Instagram**, then enter:

| Terminal prompt | Where to get it |
| --- | --- |
| Meta App ID | App settings → Basic |
| Meta App secret | App settings → Basic → Show |
| User access token from Graph API Explorer | The token generated in step 3 |
| Instagram account | Choose from the discovered accounts |

The program exchanges the User token for a long-lived token, checks its
permissions, and [finds the Instagram account through your Pages](https://www.postman.com/meta/instagram/request/lpx8lul/get-access-tokens-of-pages-you-manage).
It stores the selected Page's publishing token. You do not need to find or paste
an Instagram numeric ID. The App secret is used during setup and is not saved.
Long-lived tokens can still expire or be revoked; reconnect when necessary.

### If connection fails

| What you see | What to check |
| --- | --- |
| Cannot find Instagram API during app creation | Select **Manage messaging and content on Instagram** on the **Use cases** screen. |
| Only Instagram Login appears | Open **Use cases → Customize**. If the app is already committed to Instagram Login, use a separate app for Facebook Login. |
| Required permissions missing from Explorer | Select the correct **Meta App**; add content-management permissions in its Facebook Login setup, then return to Explorer. |
| Missing permissions in the terminal | Add the named permissions, generate a new User token, and approve them in the authorization dialog. |
| No linked Instagram accounts found | Check professional account status, the Page link, full control of the Page, and which assets you selected during authorization. |
| Token exchange fails | The App ID, App secret and User token must all belong to the same app. Generate a fresh User token. |
| API error 190 | The token is invalid, expired or revoked. Reconnect with a fresh token. |

Uploads use Graph API v25.0 and local MP4 files; no public video hosting is needed.
Instagram scheduling runs locally: the worker uploads and publishes at the chosen
time. Keep this computer awake, online and logged in. Processing can make the
actual publication a little later.

## TikTok drafts

**For a personal tool, start with Sandbox for testing.** TikTok's current
[app review guidelines](https://developers.tiktok.com/docs/en/app-review-guidelines)
exclude apps intended only for private or personal use. Creating a developer
app does not guarantee production upload access for this project.

This integration sends **inbox drafts**. You still open TikTok, add the caption
from the TXT file, and finish posting. Scheduling sets the draft-delivery time.
See TikTok's [Upload API prerequisites and posting flow](https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content).

### 1. Open the correct dashboard and create a sandbox

1. Sign in to [TikTok for Developers](https://developers.tiktok.com/), click your
   profile icon at the top, then **Manage apps**. This is separate from TikTok
   Studio and the advertising dashboard.
2. Open an existing app, or choose **Connect an app**, select its owner and confirm.
3. On the app page, switch the toggle beside the app name from **Production** to
   **Sandbox**. Choose **Create Sandbox**, give it a name, and confirm.

You should now see the sandbox's settings. TikTok's
[sandbox guide has screenshots of this toggle](https://developers.tiktok.com/docs/en/add-a-sandbox).
Public-video publishing is not available in Sandbox; use it to test the
integration, not as unrestricted production access.

### 2. Add products, the callback and your account

1. Under **App details**, fill in the requested information and select **Desktop**
   as the platform. TikTok asks for a website URL for desktop apps.
2. Open **Products → Add products** and add **Login Kit** and **Content Posting API**.
   These controls are shown in TikTok's [app registration guide](https://developers.tiktok.com/docs/en/getting-started-create-an-app).
3. Under **Login Kit**, find the **Desktop** configuration and register this
   redirect URI, including the final slash:

   ```text
   http://127.0.0.1:8765/callback/
   ```

   If the form refuses this local HTTP address, check that you are editing
   **Desktop**, not Web. The address follows TikTok's [Desktop redirect rules](https://developers.tiktok.com/docs/en/login-kit-desktop).

4. Open **Scopes → Add Scopes** and select `video.upload`. Keep `user.info.basic`,
   which Login Kit adds automatically. This program uses upload-to-inbox access;
   it does not request `video.publish`. See the [scope controls](https://developers.tiktok.com/docs/en/scopes-overview).
5. Open **Sandbox settings → Target users → Add account**. Log in to the TikTok
   account that will receive the drafts and accept. TikTok says the account may
   take up to an hour to appear after refreshing the page.
6. Click **Apply changes**. Confirm that the account is listed before connecting
   from the terminal.

### 3. Copy the matching credentials and connect

1. Stay in the same sandbox. Open **App details → Credentials** and copy
   **Client key** and **Client secret**. The app's numeric App ID is not its client key.
2. Run `uv run clips.py accounts`, choose **3 · TikTok**, and enter those values.
3. Authorize the same TikTok account you added as a target user. Leave the
   terminal open until it shows **Connected TikTok**.

### If your app already has production approval

Use **Production** and its credentials instead. The approved, live configuration
must include Login Kit, the Desktop callback and `video.upload`; saving a new
draft revision does not update the live configuration. App approval and your
account's consent are both required.

For an eligible public integration, production review requires a working website,
privacy policy, terms, and a recording demonstrating the requested features.
The portal's **URL properties** control handles required URL verification.
Do not substitute the local callback address for a website or policy URL.
This program uploads MP4 bytes directly, so it does not need a public video URL.
See [registration and verification](https://developers.tiktok.com/docs/en/getting-started-create-an-app)
and [review requirements](https://developers.tiktok.com/docs/en/app-review-guidelines).

### If connection fails

| What you see | What to check |
| --- | --- |
| Redirect URI error | Use the Desktop configuration and the exact URI above, including `http`, `127.0.0.1`, port `8765` and `/callback/`. |
| Cannot find Login Kit or Content Posting API | Open the app's **Products** section and click **Add products**. |
| `video.upload` missing or not granted | Add Content Posting API first, then **Scopes → Add Scopes**. Apply sandbox changes or obtain production scope approval, then authorize again. |
| Sandbox login denied | Add the account under **Sandbox settings → Target users**, apply changes, wait for it to appear, and use credentials from that sandbox. |
| The form asks for website or policy URLs | These describe your app; they are separate from the local Login Kit callback. Complete the portal's URL-verification requirements where requested. |
| Pending-share limit | Open TikTok and finish or remove existing inbox drafts before sending more. |

Keep this computer awake and online until scheduled draft delivery. If TikTok
does not grant your app upload access, use the exported MP4 and TXT manually.
There is no local setting that enables a scope TikTok has not granted.

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
