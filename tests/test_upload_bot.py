"""Tests for the multi-account video upload scheduler."""

import os
from datetime import datetime, time

import pytest

from upload_bot import cli
from upload_bot.brief import parse_results
from upload_bot.config import ConfigError, parse_config
from upload_bot.metadata import read_meta, render_for
from upload_bot.schedule import is_ready, next_slot

FIXED_NOW = datetime(2026, 11, 23, 9, 0)  # a Monday

CONFIG = """
[settings]
timezone = "America/New_York"
min_lead_minutes = 60

[[account]]
id = "yt"
platform = "youtube"
handle = "@chan"
days = "daily"
times = ["15:00"]
hashtags = ["#shorts"]
caption_template = "{description}\\n\\n{hashtags}"

[[account]]
id = "tt"
platform = "tiktok"
handle = "@tt"
days = "daily"
times = ["12:00", "19:00"]
max_per_day = 2
caption_template = "{title} {hashtags}"

[[account]]
id = "x"
platform = "x"
handle = "@x"
days = "daily"
times = ["17:00"]
caption_template = "{title} {hashtags}"
enabled = false
"""


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    home = tmp_path / "ws"
    assert cli.main(["--home", str(home), "init"]) == 0
    (home / "accounts.toml").write_text(CONFIG)
    monkeypatch.setattr(cli, "now_in", lambda tz: FIXED_NOW)
    return home


def run(ws, *args):
    return cli.main(["--home", str(ws), *args])


def drop(ws, name, size=1000, sidecar=None, ext=".txt", mtime=None):
    p = ws / "inbox" / name
    p.write_bytes(os.urandom(size))
    if sidecar is not None:
        p.with_suffix(ext).write_text(sidecar)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def cfg():
    import tomllib

    return parse_config(tomllib.loads(CONFIG))


# -- scheduling ------------------------------------------------------------


def test_next_slot_respects_taken_and_max_per_day():
    tt = cfg().account("tt")
    earliest = datetime(2026, 11, 23, 10, 0)
    assert next_slot(tt, [], earliest) == datetime(2026, 11, 23, 12, 0)
    taken = [datetime(2026, 11, 23, 12, 0)]
    assert next_slot(tt, taken, earliest) == datetime(2026, 11, 23, 19, 0)
    taken.append(datetime(2026, 11, 23, 19, 0))
    assert next_slot(tt, taken, earliest) == datetime(2026, 11, 24, 12, 0)


def test_weekday_only_account_skips_weekend():
    c = parse_config({"account": [{"id": "a", "platform": "facebook", "handle": "P",
                                   "days": "weekdays", "times": ["13:00"]}]})
    a = c.account("a")
    fri_late = datetime(2026, 11, 27, 14, 0)  # Friday after the slot
    assert next_slot(a, [], fri_late) == datetime(2026, 11, 30, 13, 0)  # Monday


def test_tiktok_jobs_wait_for_ten_day_window():
    tt = cfg().account("tt")
    assert is_ready(tt, datetime(2026, 11, 30, 12, 0), FIXED_NOW)
    assert not is_ready(tt, datetime(2026, 12, 10, 12, 0), FIXED_NOW)
    assert is_ready(cfg().account("yt"), datetime(2027, 6, 1, 15, 0), FIXED_NOW)


def test_bad_config_is_reported():
    with pytest.raises(ConfigError, match="platform 'myspace'"):
        parse_config({"account": [{"id": "a", "platform": "myspace", "handle": "h",
                                   "days": "daily", "times": ["10:00"]}]})
    with pytest.raises(ConfigError, match="HH:MM"):
        parse_config({"account": [{"id": "a", "platform": "x", "handle": "h",
                                   "days": "daily", "times": ["6pm"]}]})


# -- metadata --------------------------------------------------------------


def test_txt_sidecar_title_description_hashtags(tmp_path):
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"x")
    v.with_suffix(".txt").write_text(
        "Big title\nLine one of the description.\naccounts: yt, tt\n\n#one #two\n"
    )
    m = read_meta(v)
    assert m.title == "Big title"
    assert m.description == "Line one of the description."
    assert m.hashtags == ["#one", "#two"]
    assert m.accounts == ["yt", "tt"]
    r = render_for(m, cfg().account("yt"))
    assert r.caption == "Line one of the description.\n\n#one #two #shorts"
    assert r.title == "Big title"


def test_toml_overrides_per_platform(tmp_path):
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"x")
    v.with_suffix(".toml").write_text(
        'title = "Base"\nhashtags = ["a"]\n[tiktok]\ntitle = "TT title"\n[account.yt]\ncaption = "custom"\n'
    )
    m = read_meta(v)
    assert render_for(m, cfg().account("tt")).caption == "TT title #a"
    assert render_for(m, cfg().account("yt")).caption == "custom"


def test_no_sidecar_uses_filename(tmp_path):
    v = tmp_path / "my_best-clip.mp4"
    v.write_bytes(b"x")
    assert read_meta(v).title == "My best clip"


def test_too_long_caption_is_flagged(tmp_path):
    v = tmp_path / "c.mp4"
    v.write_bytes(b"x")
    v.with_suffix(".txt").write_text("T\n" + "word " * 100)
    c = parse_config({"account": [{"id": "x", "platform": "x", "handle": "@x", "days": "daily",
                                   "times": ["10:00"], "caption_template": "{title} {description}"}]})
    assert any("280" in p for p in render_for(read_meta(v), c.account("x")).problems)


# -- end to end ------------------------------------------------------------


def test_go_queues_every_enabled_account_and_writes_brief(ws, capsys):
    drop(ws, "first.mp4", sidecar="First video\nhello\n#tag", mtime=1000)
    drop(ws, "second.mp4", mtime=2000)
    assert run(ws, "go") == 0
    out = capsys.readouterr().out
    assert "Queued 4 upload job(s)" in out           # 2 videos x 2 enabled accounts
    assert not list((ws / "inbox").iterdir())         # inbox emptied
    brief = sorted((ws / "briefs").glob("*.md"))[-1].read_text()
    assert "@chan on YouTube" in brief and "@tt on TikTok" in brief
    assert "@x" not in brief                          # disabled account
    assert "First video #tag" in brief                # tiktok caption
    # first-dropped video gets the earliest slot on each account
    conn = cli.Ctx(ws).conn
    rows = {(r["title"], r["account_id"]): r["slot"] for r in conn.execute("SELECT * FROM jobs")}
    assert rows[("First video", "yt")] == "2026-11-23 15:00"
    assert rows[("Second", "yt")] == "2026-11-24 15:00"
    assert rows[("First video", "tt")] == "2026-11-23 12:00"
    assert rows[("Second", "tt")] == "2026-11-23 19:00"


def test_duplicate_video_is_refused(ws, capsys):
    p = drop(ws, "a.mp4")
    data = p.read_bytes()
    run(ws, "ingest")
    (ws / "inbox" / "renamed.mp4").write_bytes(data)
    run(ws, "ingest")
    assert "already queued" in capsys.readouterr().out
    assert (ws / "inbox" / "renamed.mp4").exists()


def test_report_round_trip(ws, capsys):
    drop(ws, "a.mp4")
    run(ws, "ingest")
    reply = tmp = ws / "reply.txt"
    tmp.write_text(
        "Sure!\n```\nRESULTS\nJOB 1 | SCHEDULED | https://youtu.be/xyz\nJOB 2 | FAILED | wrong account\nEND\n```"
    )
    assert run(ws, "report", str(reply)) == 0
    conn = cli.Ctx(ws).conn
    st = {r["id"]: (r["status"], r["result_url"], r["note"]) for r in conn.execute("SELECT * FROM jobs")}
    assert st[1] == ("scheduled", "https://youtu.be/xyz", "")
    assert st[2] == ("failed", "", "wrong account")
    run(ws, "retry", "2")
    assert conn.execute("SELECT status FROM jobs WHERE id=2").fetchone()[0] == "pending"


def test_missed_slots_are_moved_forward(ws, monkeypatch, capsys):
    drop(ws, "a.mp4")
    run(ws, "ingest")
    monkeypatch.setattr(cli, "now_in", lambda tz: datetime(2026, 11, 23, 20, 0))
    run(ws, "brief")
    assert "moved missed slot" in capsys.readouterr().out
    slots = [r[0] for r in cli.Ctx(ws).conn.execute("SELECT slot FROM jobs ORDER BY id")]
    assert all(s > "2026-11-23 21:00" for s in slots)


def test_parse_results_tolerates_formatting():
    res, bad = parse_results("- JOB #3: done: link\n`JOB 4 | skipped |`\nJOB 9 | STATUS | link or reason\nJOB x | ???")
    assert [(r.job_id, r.status) for r in res] == [(3, "scheduled"), (4, "pending")]
    assert bad == ["JOB x | ???"]


# -- scatter: jitter + per-account shuffle ---------------------------------

SCATTER = """
[settings]
timezone = "America/New_York"
min_lead_minutes = 60
""" + "".join(f"""
[[account]]
id = "ch{i}"
platform = "youtube"
handle = "@ch{i}"
days = "daily"
times = ["15:00"]
jitter_minutes = 25
shuffle = true
""" for i in range(6))


def test_jitter_stays_in_range_and_never_before_earliest():
    from upload_bot.schedule import jittered

    c = parse_config({"account": [{"id": "a", "platform": "youtube", "handle": "h", "days": "daily",
                                   "times": ["15:00"], "jitter_minutes": 20}]})
    a = c.account("a")
    base = datetime(2026, 11, 24, 15, 0)
    outs = {jittered(a, base, f"k{i}", datetime(2026, 11, 23, 10, 0)) for i in range(50)}
    assert len(outs) > 10                                    # actually scattered
    assert all(abs((o - base).total_seconds()) <= 20 * 60 for o in outs)
    assert jittered(a, base, "k1", base) >= base            # clamp at earliest
    assert jittered(a, base, "same", base) == jittered(a, base, "same", base)  # stable


def test_each_channel_gets_its_own_order_and_times(ws):
    (ws / "accounts.toml").write_text(SCATTER)
    for i in range(8):
        drop(ws, f"v{i}.mp4", mtime=1000 + i)
    assert run(ws, "ingest") == 0
    conn = cli.Ctx(ws).conn
    orders, minutes = [], set()
    for i in range(6):
        rows = conn.execute(
            "SELECT v.title, j.slot, j.base_slot FROM jobs j JOIN videos v ON v.id = j.video_id"
            " WHERE account_id = ? ORDER BY j.base_slot", (f"ch{i}",)).fetchall()
        assert len(rows) == 8
        assert len({r["base_slot"][:10] for r in rows}) == 8    # still one per day
        orders.append(tuple(r["title"] for r in rows))
        minutes |= {r["slot"][11:] for r in rows}
    assert len(set(orders)) >= 5          # channels post the batch in different orders
    assert len(minutes) > 10              # times are not all 15:00


def test_old_database_gets_base_slot_column(tmp_path):
    import sqlite3

    from upload_bot import db as dbm

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(dbm.SCHEMA.replace("    base_slot   TEXT,                   -- the schedule slot before jitter\n", ""))
    old.close()
    conn = dbm.connect(path)
    assert "base_slot" in {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
