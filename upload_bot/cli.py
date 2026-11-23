"""Command line interface.

    ./uploader --help
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import db as dbm
from .brief import parse_results, render_brief
from .config import EXAMPLE_CONFIG, Config, ConfigError, Workspace, default_home, load_config
from .metadata import MetadataError, read_meta, render_for, sidecar_for
from .platforms import VIDEO_EXTENSIONS
from .schedule import earliest_for, is_ready, next_slot, now_in, window_opens

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def table(rows: list[list], headers: list[str]) -> str:
    if not rows:
        return "(nothing)"
    rows = [[str(c) for c in r] for r in rows]
    w = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(c.ljust(w[i]) for i, c in enumerate(cells)).rstrip()
    return "\n".join([line(headers), line(["-" * x for x in w]), *map(line, rows)])


def fingerprint(path: Path) -> str:
    """size + hash of the first and last MiB: fast on multi-GB files, and
    catches the same video dropped twice under a different name."""
    h = hashlib.sha256()
    size = path.stat().st_size
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), 2)
            h.update(f.read())
    return h.hexdigest()


def unique_dest(folder: Path, name: str) -> Path:
    dest = folder / name
    n = 2
    while dest.exists():
        dest = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    return dest


def pretty(slot: str) -> str:
    return datetime.strptime(slot, dbm.FMT).strftime("%a %b %d %I:%M %p")


class Ctx:
    def __init__(self, home: Path):
        self.ws = Workspace(home)
        self._cfg: Config | None = None
        self._conn = None

    @property
    def cfg(self) -> Config:
        if self._cfg is None:
            self._cfg = load_config(self.ws.config_path)
        return self._cfg

    @property
    def conn(self):
        if self._conn is None:
            self._conn = dbm.connect(self.ws.db_path)
        return self._conn

    def now(self) -> datetime:
        return now_in(self.cfg.settings.timezone)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_init(ctx: Ctx, args) -> int:
    ws = ctx.ws
    for d in (ws.inbox, ws.library, ws.briefs):
        d.mkdir(parents=True, exist_ok=True)
    if ws.config_path.exists() and not args.force:
        print(f"Kept existing {ws.config_path}")
    else:
        shutil.copy(EXAMPLE_CONFIG, ws.config_path)
        print(f"Wrote {ws.config_path}  <- put your real accounts in here")
    ctx.conn  # creates the database
    print(f"Workspace ready at {ws.home}")
    print(f"  drop videos in   {ws.inbox}")
    print("  then run         ./uploader go")
    return 0


def cmd_accounts(ctx: Ctx, args) -> int:
    cfg = ctx.cfg
    from .config import DAYS

    rows = []
    for a in cfg.accounts:
        days = "daily" if len(a.days) == 7 else ",".join(DAYS[d] for d in a.days)
        rows.append([
            a.id, a.spec["name"].split(" (")[0], a.handle, "yes" if a.enabled else "no",
            days, " ".join(t.strftime("%H:%M") for t in a.times), a.max_per_day,
        ])
    print(table(rows, ["id", "platform", "handle", "on", "days", "times", "max/day"]))
    print(f"\nTimezone {cfg.settings.timezone}. Config OK: {ctx.ws.config_path}")
    return 0


def targets_for(cfg: Config, meta) -> tuple[list, list[str]]:
    warnings = []
    if meta.accounts is not None:
        ids = meta.accounts
    elif cfg.settings.default_accounts:
        ids = cfg.settings.default_accounts
    else:
        ids = [a.id for a in cfg.enabled]
    out = []
    for i in ids:
        if i in meta.skip:
            continue
        acct = cfg.account(i)
        if not acct.enabled:
            warnings.append(f"account '{i}' is disabled in accounts.toml, skipped")
            continue
        out.append(acct)
    return out, warnings


def cmd_ingest(ctx: Ctx, args) -> int:
    cfg, conn, ws = ctx.cfg, ctx.conn, ctx.ws
    now = ctx.now()
    ws.inbox.mkdir(parents=True, exist_ok=True)
    # oldest drop first, so videos post in the order you sent them
    videos = sorted(
        (p for p in ws.inbox.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if not videos:
        print(f"Inbox is empty ({ws.inbox}).")
        return 0

    created, problems = [], 0
    for video in videos:
        try:
            meta = read_meta(video)
            accounts, warns = targets_for(cfg, meta)
        except (MetadataError, ConfigError) as e:
            print(f"! {video.name}: {e}  (left in inbox)")
            problems += 1
            continue
        for w in warns:
            print(f"  note: {video.name}: {w}")
        if not accounts:
            print(f"! {video.name}: no enabled accounts to post to (left in inbox)")
            problems += 1
            continue
        fp = fingerprint(video)
        if conn.execute("SELECT 1 FROM videos WHERE fingerprint = ?", (fp,)).fetchone():
            print(f"! {video.name}: this exact video is already queued (left in inbox)")
            problems += 1
            continue
        rendered = {a.id: render_for(meta, a) for a in accounts}
        bad = {k: r.problems for k, r in rendered.items() if r.problems}
        if bad:
            print(f"! {video.name}: fix the sidecar text first (left in inbox):")
            for k, ps in bad.items():
                for p in ps:
                    print(f"    {k}: {p}")
            problems += 1
            continue
        if args.dry_run:
            print(f"would add {video.name} -> {', '.join(a.id for a in accounts)}")
            continue

        folder = ws.library / now.strftime("%Y-%m")
        folder.mkdir(parents=True, exist_ok=True)
        dest = unique_dest(folder, video.name)
        side = sidecar_for(video)
        shutil.move(str(video), dest)
        if side:
            shutil.move(str(side), dest.with_suffix(side.suffix))

        cur = conn.execute(
            "INSERT INTO videos (path, fingerprint, title, added_at) VALUES (?, ?, ?, ?)",
            (str(dest.resolve()), fp, meta.title, dbm.stamp(now)),
        )
        vid = cur.lastrowid
        for a in accounts:
            slot = next_slot(a, dbm.taken_slots(conn, a.id), earliest_for(a, now, cfg.settings.min_lead_minutes, meta.not_before))
            r = rendered[a.id]
            conn.execute(
                "INSERT INTO jobs (video_id, account_id, platform, slot, title, caption, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (vid, a.id, a.platform, dbm.stamp(slot), r.title, r.caption, dbm.stamp(now)),
            )
            created.append([dest.name, a.id, pretty(dbm.stamp(slot))])
        conn.commit()

    if created:
        print(f"Queued {len(created)} upload job(s):")
        print(table(created, ["video", "account", "scheduled for"]))
    return 1 if problems and not created else 0


def _reslot_missed(ctx: Ctx) -> list[str]:
    """Pending jobs whose time is now too close or already past get the
    account's next free slot, so a late brief never asks for a past time."""
    cfg, conn = ctx.cfg, ctx.conn
    now = ctx.now()
    moved = []
    for j in conn.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY slot").fetchall():
        try:
            a = cfg.account(j["account_id"])
        except ConfigError:
            continue
        earliest = earliest_for(a, now, cfg.settings.min_lead_minutes, None)
        if dbm.unstamp(j["slot"]) >= earliest:
            continue
        new = next_slot(a, dbm.taken_slots(conn, a.id, exclude_job=j["id"]), earliest)
        conn.execute("UPDATE jobs SET slot = ? WHERE id = ?", (dbm.stamp(new), j["id"]))
        moved.append(f"job {j['id']} ({a.id}) {pretty(j['slot'])} -> {pretty(dbm.stamp(new))}")
    conn.commit()
    return moved


def ready_jobs(ctx: Ctx, account: str | None, limit: int | None) -> tuple[list, list]:
    cfg, now = ctx.cfg, ctx.now()
    rows = ctx.conn.execute(
        "SELECT j.*, v.path FROM jobs j JOIN videos v ON v.id = j.video_id"
        " WHERE j.status = 'pending' ORDER BY j.slot, j.id"
    ).fetchall()
    ready, waiting = [], []
    for r in rows:
        if account and r["account_id"] != account:
            continue
        try:
            a = cfg.account(r["account_id"])
        except ConfigError:
            continue
        if not a.enabled:
            continue
        (ready if is_ready(a, dbm.unstamp(r["slot"]), now) else waiting).append(r)
    if limit:
        waiting = ready[limit:] + waiting
        ready = ready[:limit]
    return ready, waiting


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["clip"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode("utf-16le" if cmd[0] == "clip" else "utf-8"), check=True)
                return True
            except (OSError, subprocess.CalledProcessError):
                continue
    return False


def cmd_brief(ctx: Ctx, args) -> int:
    for m in _reslot_missed(ctx):
        print(f"  moved missed slot: {m}")
    ready, waiting = ready_jobs(ctx, args.account, args.limit)
    if not ready:
        print("Nothing ready to upload right now.")
        _print_waiting(ctx, waiting)
        return 0
    now = ctx.now()
    text = render_brief(ctx.cfg, ready, now)
    ctx.ws.briefs.mkdir(parents=True, exist_ok=True)
    path = ctx.ws.briefs / f"brief-{datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text, encoding="utf-8")
    if args.print:
        print(text)
    print(f"Brief for {len(ready)} job(s) written to {path}")
    if args.copy:
        print("Copied to clipboard." if copy_to_clipboard(text) else "No clipboard tool found; open the file instead.")
    print("Next: open Claude in Chrome, paste the brief, and when it replies with the")
    print("RESULTS block, copy that and run:  ./uploader report   (then paste, then Ctrl-D)")
    _print_waiting(ctx, waiting)
    return 0


def _print_waiting(ctx: Ctx, waiting: list) -> None:
    if not waiting:
        return
    print(f"\n{len(waiting)} job(s) waiting for their platform's scheduling window to open:")
    for r in waiting[:10]:
        a = ctx.cfg.account(r["account_id"])
        opens = window_opens(a, dbm.unstamp(r["slot"]))
        when = f"brief-able from {opens:%a %b %d}" if opens and opens > ctx.now() else "next brief"
        print(f"  job {r['id']}  {r['account_id']:<12} {pretty(r['slot'])}  ({when})")


def cmd_go(ctx: Ctx, args) -> int:
    args.dry_run = False
    cmd_ingest(ctx, args)
    print()
    return cmd_brief(ctx, args)


def cmd_queue(ctx: Ctx, args) -> int:
    where = "" if args.all else "WHERE j.status IN ('pending','failed')"
    rows = ctx.conn.execute(
        f"SELECT j.*, v.path FROM jobs j JOIN videos v ON v.id = j.video_id {where} ORDER BY j.slot, j.id"
    ).fetchall()
    out = [[r["id"], r["status"], r["account_id"], pretty(r["slot"]), Path(r["path"]).name[:34],
            (r["result_url"] or r["note"])[:40]] for r in rows]
    print(table(out, ["job", "status", "account", "when", "video", "link / note"]))
    counts = ctx.conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
    if counts:
        print("\n" + "  ".join(f"{c['status']}: {c['n']}" for c in counts))
    return 0


def _apply(ctx: Ctx, job_id: int, status: str, detail: str) -> str:
    url, note = ("", detail)
    if status == "scheduled" and detail:
        url, note = detail, ""
    if status == "pending" and not detail:
        note = "skipped in last run"
    dbm.set_status(ctx.conn, job_id, status, url=url, note=note, now=ctx.now())
    label = "skipped, stays queued" if status == "pending" else status
    return f"job {job_id}: {label}" + (f"  {detail}" if detail else "")


def cmd_report(ctx: Ctx, args) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    results, unreadable = parse_results(text)
    if not results:
        print("No 'JOB <n> | STATUS | ...' lines found. Paste the RESULTS block from Claude.")
        return 1
    for r in results:
        try:
            print(_apply(ctx, r.job_id, r.status, r.detail))
        except KeyError:
            print(f"job {r.job_id}: no such job, ignored")
    for line in unreadable:
        print(f"  couldn't read: {line}")
    failed = [r for r in results if r.status == "failed"]
    if failed:
        print(f"\n{len(failed)} failed. Fix the cause, then `./uploader retry <job>` and run `./uploader brief`.")
    return 0


def cmd_mark(ctx: Ctx, args) -> int:
    status = {"done": "scheduled", "fail": "failed", "cancel": "cancelled"}[args.cmd]
    for j in args.jobs:
        try:
            print(_apply(ctx, j, status, args.url or args.reason or ""))
        except KeyError:
            print(f"job {j}: no such job")
            return 1
    return 0


def cmd_retry(ctx: Ctx, args) -> int:
    for j in args.jobs:
        row = ctx.conn.execute("SELECT status FROM jobs WHERE id = ?", (j,)).fetchone()
        if not row:
            print(f"job {j}: no such job")
            return 1
        dbm.set_status(ctx.conn, j, "pending", note="retry", now=ctx.now())
        print(f"job {j}: back in the queue")
    for m in _reslot_missed(ctx):
        print(f"  new time: {m}")
    return 0


def cmd_reschedule(ctx: Ctx, args) -> int:
    row = ctx.conn.execute("SELECT * FROM jobs WHERE id = ?", (args.job,)).fetchone()
    if not row:
        print(f"job {args.job}: no such job")
        return 1
    if row["status"] == "scheduled":
        print(f"job {args.job} is already scheduled on the site; change it there, then use this to record it.")
    a = ctx.cfg.account(row["account_id"])
    if args.at:
        try:
            new = datetime.strptime(args.at, dbm.FMT)
        except ValueError:
            print("--at must look like 2026-12-01 18:30")
            return 1
        if new <= ctx.now():
            print("That time is in the past.")
            return 1
    else:
        new = next_slot(a, dbm.taken_slots(ctx.conn, a.id, exclude_job=row["id"]),
                        earliest_for(a, ctx.now(), ctx.cfg.settings.min_lead_minutes, None))
    ctx.conn.execute("UPDATE jobs SET slot = ? WHERE id = ?", (dbm.stamp(new), row["id"]))
    ctx.conn.commit()
    print(f"job {row['id']} ({a.id}) -> {pretty(dbm.stamp(new))}")
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uploader",
        description="Queue videos for every account and generate Claude-in-Chrome upload briefs.",
    )
    p.add_argument("--home", type=Path, default=None, help="workspace folder (default ~/VideoUploads or $UPLOADER_HOME)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create the workspace and a starter accounts.toml")
    s.add_argument("--force", action="store_true", help="overwrite accounts.toml with the example")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("accounts", help="check accounts.toml and list accounts").set_defaults(fn=cmd_accounts)

    s = sub.add_parser("ingest", aliases=["add"], help="queue every video in the inbox")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_ingest)

    for name, fn, help_ in (
        ("brief", cmd_brief, "write the Claude-in-Chrome brief for jobs ready now"),
        ("go", cmd_go, "ingest the inbox, then write the brief (the one-command path)"),
    ):
        s = sub.add_parser(name, help=help_)
        s.add_argument("--account", help="only this account id")
        s.add_argument("--limit", type=int, help="at most N jobs in this brief")
        s.add_argument("--print", action="store_true", help="also print the brief")
        s.add_argument("--copy", action="store_true", help="copy the brief to the clipboard")
        s.set_defaults(fn=fn)

    s = sub.add_parser("queue", aliases=["status"], help="show pending and failed jobs")
    s.add_argument("--all", action="store_true", help="include scheduled and cancelled")
    s.set_defaults(fn=cmd_queue)

    s = sub.add_parser("report", help="record the RESULTS block Claude sent back (stdin or file)")
    s.add_argument("file", nargs="?")
    s.set_defaults(fn=cmd_report)

    for name, help_ in (("done", "mark job(s) scheduled"), ("fail", "mark job(s) failed"), ("cancel", "drop job(s)")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("jobs", type=int, nargs="+")
        s.add_argument("--url", default="")
        s.add_argument("--reason", default="")
        s.set_defaults(fn=cmd_mark)

    s = sub.add_parser("retry", help="put failed job(s) back in the queue")
    s.add_argument("jobs", type=int, nargs="+")
    s.set_defaults(fn=cmd_retry)

    s = sub.add_parser("reschedule", help="move a job to its next free slot, or --at a time")
    s.add_argument("job", type=int)
    s.add_argument("--at", help="'YYYY-MM-DD HH:MM'")
    s.set_defaults(fn=cmd_reschedule)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = Ctx(args.home or default_home())
    try:
        return args.fn(ctx, args)
    except ConfigError as e:
        print(f"Config problem: {e}", file=sys.stderr)
        return 2
