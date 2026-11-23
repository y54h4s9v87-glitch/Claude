# Video upload bot (Claude in Chrome)

Drop videos in a folder. The bot gives each one a time slot on **every**
account you post to (YouTube channels, TikTok, Instagram, Facebook Pages, X),
then writes a step-by-step brief that **Claude in Chrome** follows to upload
and schedule them in your logged-in browser. Claude sends back a RESULTS block,
you paste it in, and the queue is updated.

Python 3.11+ standard library only. No API keys, no passwords stored.
Run it on the same computer as the Chrome you use Claude in, because the brief
gives Claude the local path of each video file.

## One-time setup

```bash
./uploader init            # creates ~/VideoUploads/{inbox,library,briefs} + accounts.toml
```

Open `~/VideoUploads/accounts.toml` and replace the example accounts with
yours: handle, posting days/times, max posts per day, hashtags, caption
template, and a `login_hint` telling Claude how to switch to that account.
Set `enabled = true/false` per account. Check it with:

```bash
./uploader accounts
```

Log in to every account in Chrome once yourself (Claude stops and asks on any
login, 2FA or CAPTCHA screen; it never tries to get around them).

## Every time you have videos

1. Put the videos in `~/VideoUploads/inbox/`. Optional: a text file with the
   same name for the title/caption (see below).
2. Run:
   ```bash
   ./uploader go --copy
   ```
   This queues every video for every enabled account, moves the files to
   `library/`, and writes `briefs/brief-<time>.md` (and copies it to the clipboard).
3. Open Claude in Chrome, paste the brief, let it work. It handles one account
   at a time and schedules each video for its slot.
4. Claude ends with a block like:
   ```
   RESULTS
   JOB 1 | SCHEDULED | https://youtu.be/...
   JOB 2 | FAILED | wrong account
   END
   ```
   Copy it and run `./uploader report`, paste, then Ctrl-D (Ctrl-Z Enter on Windows).
   Or save it to a file and run `./uploader report reply.txt`.

Videos post in the order you dropped them. A video goes to each account's next
free slot, so if you drop 10 videos and YouTube posts daily at 15:00, they fill
the next 10 days.

## Scattering times and order

Two optional settings per account in `accounts.toml`:

```toml
jitter_minutes = 30   # each post lands a different 0-30 min before/after the slot
shuffle = true        # this account gets each inbox batch in its own random order
```

With `shuffle = true` on several accounts, the same batch of videos goes out in
a different order on each one. Jitter is stable per video, so re-running a
brief doesn't keep moving times around.

## Title and caption (optional sidecar file)

`my_clip.mp4` + `my_clip.txt`:

```
My 5am morning routine
What I actually do before work.

#morning #routine
accounts: yt-main, tt-main        (optional: only these accounts)
not_before: 2026-12-01 09:00      (optional: don't schedule earlier)
```

Line 1 is the title, the rest is the description, a final line of hashtags
becomes the hashtag list. Each account's `caption_template` and `hashtags`
are applied on top. No sidecar: the title comes from the file name.

Need different text per platform? Use `my_clip.toml`:

```toml
title = "My 5am morning routine"
description = "What I actually do before work."
hashtags = ["morning", "routine"]

[tiktok]
title = "5am routine that changed my life"

[account.x-main]
caption = "New video: my 5am routine"
```

Captions over a platform's limit (X 280, TikTok/IG 2200, YouTube title 100…)
are caught when you run `go`, and that video stays in the inbox until fixed.

## Other commands

| command | what it does |
|---|---|
| `./uploader queue` / `--all` | pending + failed jobs / everything |
| `./uploader brief --account tt-main --limit 5` | brief for one account, at most 5 jobs |
| `./uploader retry 12` | put a failed job back in the queue |
| `./uploader reschedule 12 [--at "2026-12-01 18:30"]` | next free slot, or a set time |
| `./uploader done 12 --url ...` / `fail 12 --reason ...` / `cancel 12` | mark by hand |
| `./uploader ingest --dry-run` | check the inbox without queuing |

## Things worth knowing

- **Scheduling windows.** TikTok only lets you schedule ~10 days ahead and Meta
  Business Suite ~4 weeks. Jobs further out wait in the queue and show up in a
  later brief once their window opens; `brief` lists what is waiting. Override
  with `horizon_days` on the account if a site changes its limit.
- **Missed slots.** If you run `brief` after a job's time has passed, that job
  is moved to the account's next free slot automatically.
- **File picking.** Depending on your Claude in Chrome version, it may not be
  able to operate the system file dialog. The brief tells it to give you the
  job number and path and wait while you pick the file, then continue.
- **Sites change.** The per-site steps live in `upload_bot/playbooks/*.md`.
  Edit them if a site's layout moves; Claude is also told to find the
  equivalent control and mark a job FAILED rather than guess.
- **Time zone.** All times are in `settings.timezone`; Claude is told to
  convert if a site's scheduler shows a different zone.
- Workspace location: `~/VideoUploads`, or set `UPLOADER_HOME`, or `--home`.
