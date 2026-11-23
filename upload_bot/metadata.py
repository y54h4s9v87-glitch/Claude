"""Per-video metadata: read the sidecar file, build each account's title/caption.

Drop a sidecar next to the video with the same name. Either:

  my_clip.txt   line 1 = title, the rest = description. Any #words become
                hashtags. Optional lines like `accounts: yt-main, tt-main`
                or `not_before: 2026-12-01 09:00` are read as settings.

  my_clip.toml  title / description / hashtags / accounts / not_before,
                plus optional [youtube] / [tiktok] / ... tables and
                [account.<id>] tables that override fields for one platform
                or one account.

No sidecar: the title comes from the file name (underscores -> spaces).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Account

HASHTAG = re.compile(r"(?<![\w#])#[\wÀ-￿]+")
SETTING_LINE = re.compile(r"^\s*(accounts|not_before|skip)\s*:\s*(.+)$", re.I)


class MetadataError(Exception):
    pass


@dataclass
class VideoMeta:
    title: str
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    accounts: list[str] | None = None        # None = use defaults
    skip: list[str] = field(default_factory=list)
    not_before: datetime | None = None
    overrides: dict = field(default_factory=dict)   # platform or "account.<id>" -> dict


def _norm_tag(tag: str) -> str:
    tag = tag.strip()
    return tag if tag.startswith("#") else f"#{tag}"


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            pass
    raise MetadataError(f"not_before '{value}' must look like 2026-12-01 09:00")


def _split_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def title_from_filename(path: Path) -> str:
    stem = re.sub(r"[_\-]+", " ", path.stem).strip()
    return stem[:1].upper() + stem[1:] if stem else path.name


def sidecar_for(video: Path) -> Path | None:
    for ext in (".toml", ".txt"):
        p = video.with_suffix(ext)
        if p.exists():
            return p
    return None


def read_meta(video: Path) -> VideoMeta:
    side = sidecar_for(video)
    if side is None:
        return VideoMeta(title=title_from_filename(video))
    if side.suffix == ".toml":
        return _read_toml(side, video)
    return _read_txt(side, video)


def _read_txt(path: Path, video: Path) -> VideoMeta:
    lines = path.read_text(encoding="utf-8").splitlines()
    meta = VideoMeta(title="")
    body: list[str] = []
    for line in lines:
        m = SETTING_LINE.match(line)
        if m:
            key, val = m.group(1).lower(), m.group(2)
            if key == "accounts":
                meta.accounts = _split_list(val)
            elif key == "skip":
                meta.skip = _split_list(val)
            else:
                meta.not_before = _parse_dt(val)
            continue
        if not meta.title and line.strip():
            meta.title = line.strip()
            continue
        if meta.title:
            body.append(line)

    # Hashtag-only trailing lines become the hashtag list; inline ones stay.
    while body and not body[-1].strip():
        body.pop()
    while body and body[-1].strip() and not HASHTAG.sub("", body[-1]).strip():
        meta.hashtags = HASHTAG.findall(body.pop()) + meta.hashtags
        while body and not body[-1].strip():
            body.pop()
    meta.description = "\n".join(body).strip()
    if not meta.title:
        meta.title = title_from_filename(video)
    return meta


def _read_toml(path: Path, video: Path) -> VideoMeta:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise MetadataError(f"{path.name}: {e}")
    overrides: dict = {}
    for key, val in data.items():
        if isinstance(val, dict) and key != "account":
            overrides[key] = val
    for acct_id, val in data.get("account", {}).items():
        overrides[f"account.{acct_id}"] = val
    return VideoMeta(
        title=str(data.get("title") or title_from_filename(video)),
        description=str(data.get("description", "")).strip(),
        hashtags=[_norm_tag(t) for t in data.get("hashtags", [])],
        accounts=_split_list(data["accounts"]) if "accounts" in data else None,
        skip=_split_list(data.get("skip", [])),
        not_before=_parse_dt(data["not_before"]) if "not_before" in data else None,
        overrides=overrides,
    )


@dataclass
class Rendered:
    title: str
    caption: str
    problems: list[str]


def render_for(meta: VideoMeta, account: Account) -> Rendered:
    """Apply overrides + templates, then check the platform's limits."""
    fields = {"title": meta.title, "description": meta.description, "hashtags": list(meta.hashtags)}
    for key in (account.platform, f"account.{account.id}"):
        ov = meta.overrides.get(key, {})
        for f in ("title", "description"):
            if f in ov:
                fields[f] = str(ov[f])
        if "hashtags" in ov:
            fields["hashtags"] = [_norm_tag(t) for t in ov["hashtags"]]
    caption_override = None
    for key in (account.platform, f"account.{account.id}"):
        if "caption" in meta.overrides.get(key, {}):
            caption_override = str(meta.overrides[key]["caption"])

    tags: list[str] = []
    for t in fields["hashtags"] + [_norm_tag(t) for t in account.hashtags]:
        if t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    values = {"title": fields["title"], "description": fields["description"], "hashtags": " ".join(tags)}

    title = account.title_template.format(**values).strip()
    caption = caption_override if caption_override is not None else account.caption_template.format(**values)
    caption = re.sub(r"\n{3,}", "\n\n", caption).strip()
    caption = re.sub(r"[ \t]+\n", "\n", caption)

    spec = account.spec
    problems = []
    if spec["needs_title"] and not title:
        problems.append("title is empty")
    if spec["title_max"] and len(title) > spec["title_max"]:
        problems.append(f"title is {len(title)} chars, {spec['name']} max is {spec['title_max']}")
    if len(caption) > spec["caption_max"]:
        problems.append(f"caption is {len(caption)} chars, {spec['name']} max is {spec['caption_max']}")
    n_tags = len(HASHTAG.findall(caption + " " + title))
    if n_tags > spec["hashtag_max"]:
        problems.append(f"{n_tags} hashtags, {spec['name']} max is {spec['hashtag_max']}")
    return Rendered(title=title, caption=caption, problems=problems)
