I want you to set up and post to my 20 GTA YouTube channels using Claude in Chrome. I'm already signed in to the Google account that will own them in Chrome. Use the repo below for everything; don't redesign anything.

**Repo:** github.com/y54h4s9v87-glitch/Claude, branch `claude/zealous-edison-nghvdq`. Clone it (or `git pull` that branch if it's already on this computer) and read `upload_bot/README.md` and `channels/README.md` first.

**What's in it:**
- `channels/README.md` has the 20 channel names, suggested handles and descriptions, plus which clip goes to which channel.
- `channels/avatars/` has the 20 profile pictures. The number in each file name matches the channel's number in the README.
- `channels/accounts_gta.toml` has each channel's posting schedule: every 2 hours from 8am to midnight on its own offset, with times scattered and order shuffled.
- `upload_bot/` is the uploader. Its `./uploader go` command writes a brief with the exact file, title, caption and time for each upload.
- The 9 edited clips with their caption `.txt` files are in `clips_with_captions.zip`, which I'll put at: **[PUT THE PATH WHERE YOU SAVED THE ZIP HERE]**

**Step 1: Create the 20 channels.** For each channel in `channels/README.md`, in order:
1. Go to youtube.com → avatar → Settings → **Create a new channel**.
2. Enter the channel name. Use the suggested handle, or the closest free one if it's taken.
3. In YouTube Studio → Customization, upload its picture from `channels/avatars/` and paste its description.
4. Write down the real handle YouTube gave it.

Stop and ask me if Google asks for phone verification, a CAPTCHA or my password. If Google stops letting you create channels for today, tell me how many you finished and stop there. After each channel, give me a one-line status update.

**Step 2: Set up the uploader.**
1. Run `./uploader init`.
2. Unzip the clips into `~/VideoUploads/inbox/`.
3. Copy every `[[account]]` entry from `channels/accounts_gta.toml` into `~/VideoUploads/accounts.toml`, replacing the example accounts.
4. In each copied entry, put the real handle from Step 1 and set `enabled = true`. Only do this for channels that actually got created.
5. Run `./uploader accounts` to check the file.

**Step 3: Upload and schedule.**
1. Run `./uploader go`.
2. Follow the brief it writes in `~/VideoUploads/briefs/` exactly: switch to the right channel for each upload, then schedule it at the exact time given. Never publish anything immediately.
3. When you're done, record the results with `./uploader report <file>`.
4. Show me `./uploader queue --all` at the end.

Don't change the captions, the schedule or the clip-to-channel assignments unless I ask.
