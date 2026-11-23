"""Render the task brief you paste into Claude in Chrome, and parse its reply."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Account, Config

PLAYBOOKS = Path(__file__).with_name("playbooks")

RULES = """\
You are uploading and scheduling videos to my own social accounts in this
Chrome browser. Work through the accounts below in order, one job at a time.

Rules -- follow all of them:
1. Before the first job of each account, confirm on screen that the logged-in
   account/channel is EXACTLY the handle given. If it is not and you cannot
   switch to it, do not upload anything there: mark that account's jobs FAILED
   with the reason "wrong account" and move on to the next account.
2. Never post immediately. Every job is SCHEDULED for the exact date and time
   given (unless the job says otherwise). If scheduling is not offered, stop
   that job and mark it FAILED -- do not publish it now instead.
3. Login screens, 2-step verification, CAPTCHAs and "confirm it's you" prompts:
   stop and ask me to handle them, then continue. Never try to get around them.
4. Choosing the file: click the site's upload/select button. If a system file
   dialog opens that you cannot operate, tell me the job number and file path,
   wait for me to pick the file, then carry on.
5. Paste TITLE and CAPTION exactly as written inside their boxes below -- no
   edits, no added hashtags, no emojis.
6. Times are {tz} ({utc_note}). Look at the time zone the site's scheduler
   shows. If it is different, convert before entering the time.
7. Wait for each upload to finish before clicking Schedule. Do not close the
   tab or navigate away while a file is uploading.
8. Do not change any other account settings, delete anything, reply to
   messages, or accept offers/upsells. Dismiss "what's new" pop-ups.
9. If a step in a playbook does not match what you see (sites change their
   layout), find the equivalent control. If you truly cannot, mark the job
   FAILED with a one-line reason and move to the next job.
10. When finished (or if you have to stop), reply with the RESULTS block at the
    end of this brief, filled in, one line per job, nothing else in the block.
"""


def _yn(v) -> str:
    return "on" if v in (True, "true", "yes", 1, None) else "off"


def playbook_for(account: Account) -> str:
    text = (PLAYBOOKS / f"{account.platform}.md").read_text(encoding="utf-8")
    x = account.extra
    vis = account.visibility.lower()
    if vis == "public":
        visibility_step = (
            "choose **Schedule** (not *Save* / *Publish*), set the job's date and "
            "time, and make sure it will go **Public** at that time."
        )
    else:
        visibility_step = (
            f"do NOT schedule. Select **{vis.capitalize()}** and save. "
            "(This account is set to upload without publishing.)"
        )
    values = {
        "upload_url": account.spec["upload_url"],
        "handle": account.handle,
        "login_hint": f"Hint: {account.login_hint}." if account.login_hint else "",
        "playlist": f"add it to the playlist **{x['playlist']}**." if x.get("playlist") else "leave as none.",
        "made_for_kids": "**Yes, it's made for kids**" if x.get("made_for_kids") else "**No, it's not made for kids**",
        "category": f"Under *Show more*, set Category to **{x['category']}**." if x.get("category") else "",
        "visibility_step": visibility_step,
        "visibility": {"everyone": "Everyone", "friends": "Friends", "only_me": "Only you"}.get(vis, "Everyone"),
        "allow_comments": _yn(x.get("allow_comments")),
        "allow_duet": _yn(x.get("allow_duet")),
        "allow_stitch": _yn(x.get("allow_stitch")),
        "share_to_facebook": (
            "Also tick the linked Facebook Page." if x.get("also_share_to_facebook")
            else "Untick any Facebook Page."
        ),
    }
    return "\n".join(l.rstrip() for l in text.format(**values).strip().splitlines())


def utc_note(tz_name: str, when: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo

        off = when.replace(tzinfo=ZoneInfo(tz_name)).strftime("%z")
        return f"UTC{off[:3]}:{off[3:]}"
    except Exception:
        return "my local time"


def fence(text: str) -> str:
    return "````text\n" + text + "\n````"


def render_brief(cfg: Config, jobs: list, now: datetime) -> str:
    """jobs: sqlite rows joined with videos (id, account_id, slot, title,
    caption, path). Grouped by account so Claude switches accounts once."""
    tz = cfg.settings.timezone
    out = [f"# Video upload run -- {now:%a %b %d %Y %H:%M} ({tz})", "", RULES.format(tz=tz, utc_note=utc_note(tz, now))]
    order = [a.id for a in cfg.accounts]
    by_account: dict[str, list] = {}
    for j in jobs:
        by_account.setdefault(j["account_id"], []).append(j)

    for n, acct_id in enumerate(sorted(by_account, key=order.index), 1):
        acct = cfg.account(acct_id)
        acct_jobs = by_account[acct_id]
        out += [
            "",
            f"## Account {n}: {acct.handle} on {acct.spec['name']}  ({len(acct_jobs)} job{'s' if len(acct_jobs) != 1 else ''})",
        ]
        if acct.chrome_profile:
            out.append(f"Chrome profile: **{acct.chrome_profile}** (if you can't switch profiles, ask me).")
        if acct.notes:
            out.append(f"Notes: {acct.notes}")
        out += ["", "### How to upload on this site", "", playbook_for(acct), ""]
        for j in acct_jobs:
            when = datetime.strptime(j["slot"], "%Y-%m-%d %H:%M")
            out += [
                f"### JOB {j['id']}",
                f"- File: `{j['path']}`",
                f"- Schedule for: **{when:%A %B %d %Y, %I:%M %p}** ({tz}) -- `{j['slot']}`",
            ]
            if acct.spec["needs_title"] or acct.platform == "facebook":
                out += ["- TITLE:", fence(j["title"])]
            out += ["- CAPTION:", fence(j["caption"]), ""]

    out += [
        "## RESULTS (fill in and send back)",
        "",
        "One line per job. STATUS is SCHEDULED, FAILED or SKIPPED.",
        "",
        "```",
        "RESULTS",
    ]
    for acct_id in sorted(by_account, key=order.index):
        for j in by_account[acct_id]:
            out.append(f"JOB {j['id']} | STATUS | link or reason")
    out += ["END", "```", ""]
    return "\n".join(out)


@dataclass
class Result:
    job_id: int
    status: str
    detail: str


LINE = re.compile(r"^\s*[-*]?\s*JOB\s*#?(\d+)\s*[|:]\s*(\w+)\s*(?:[|:]\s*(.*))?$", re.I)
STATUS_MAP = {
    "scheduled": "scheduled", "done": "scheduled", "ok": "scheduled", "uploaded": "scheduled",
    "success": "scheduled", "posted": "scheduled",
    "failed": "failed", "fail": "failed", "error": "failed",
    "skipped": "pending", "skip": "pending",
}


def parse_results(text: str) -> tuple[list[Result], list[str]]:
    results, unreadable = [], []
    for line in text.splitlines():
        if not re.search(r"\bJOB\b", line, re.I):
            continue
        m = LINE.match(line.strip().strip("`"))
        if not m or m.group(2).lower() not in STATUS_MAP:
            if "STATUS | link or reason" not in line:
                unreadable.append(line.strip())
            continue
        results.append(Result(int(m.group(1)), STATUS_MAP[m.group(2).lower()], (m.group(3) or "").strip()))
    return results, unreadable
