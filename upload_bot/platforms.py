"""What each platform allows, so a job is checked before Claude ever opens a tab.

Limits are conservative on purpose: a caption that fits here fits on the site.
`horizon_days` is how far ahead the site's own scheduler lets you pick a time
(None = no practical limit). Jobs further out than that wait in the queue and
show up in a brief once their window opens. Override per account in
accounts.toml with `horizon_days = N` if a site changes its rules.
"""

from __future__ import annotations

PLATFORMS: dict[str, dict] = {
    "youtube": {
        "name": "YouTube",
        "upload_url": "https://studio.youtube.com",
        "title_max": 100,
        "caption_max": 5000,
        "hashtag_max": 15,
        "horizon_days": None,
        "min_lead_minutes": 15,
        "needs_title": True,
    },
    "tiktok": {
        "name": "TikTok",
        "upload_url": "https://www.tiktok.com/tiktokstudio/upload",
        "title_max": None,
        "caption_max": 2200,
        "hashtag_max": 30,
        "horizon_days": 10,
        "min_lead_minutes": 15,
        "needs_title": False,
    },
    "instagram": {
        "name": "Instagram (via Meta Business Suite)",
        "upload_url": "https://business.facebook.com/latest/composer",
        "title_max": None,
        "caption_max": 2200,
        "hashtag_max": 30,
        "horizon_days": 28,
        "min_lead_minutes": 20,
        "needs_title": False,
    },
    "facebook": {
        "name": "Facebook Page (via Meta Business Suite)",
        "upload_url": "https://business.facebook.com/latest/composer",
        "title_max": 255,
        "caption_max": 5000,
        "hashtag_max": 30,
        "horizon_days": 28,
        "min_lead_minutes": 20,
        "needs_title": False,
    },
    "x": {
        "name": "X",
        "upload_url": "https://x.com/compose/post",
        "title_max": None,
        "caption_max": 280,
        "hashtag_max": 5,
        "horizon_days": 365,
        "min_lead_minutes": 10,
        "needs_title": False,
    },
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
