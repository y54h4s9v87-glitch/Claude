"""Workspace layout and accounts.toml loading/validation."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

from .platforms import PLATFORMS

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigError(Exception):
    pass


def default_home() -> Path:
    return Path(os.environ.get("UPLOADER_HOME", Path.home() / "VideoUploads")).expanduser()


@dataclass
class Workspace:
    home: Path

    @property
    def inbox(self) -> Path:
        return self.home / "inbox"

    @property
    def library(self) -> Path:
        return self.home / "library"

    @property
    def briefs(self) -> Path:
        return self.home / "briefs"

    @property
    def config_path(self) -> Path:
        return self.home / "accounts.toml"

    @property
    def db_path(self) -> Path:
        return self.home / "uploader.db"


@dataclass
class Account:
    id: str
    platform: str
    handle: str
    days: list[int]
    times: list[time]
    max_per_day: int = 1
    enabled: bool = True
    chrome_profile: str = ""
    login_hint: str = ""
    visibility: str = "public"
    hashtags: list[str] = field(default_factory=list)
    caption_template: str = "{title}\n\n{description}\n\n{hashtags}"
    title_template: str = "{title}"
    horizon_days: int | None = None
    notes: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def spec(self) -> dict:
        return PLATFORMS[self.platform]


@dataclass
class Settings:
    timezone: str = "America/New_York"
    min_lead_minutes: int = 60
    default_accounts: list[str] = field(default_factory=list)


@dataclass
class Config:
    settings: Settings
    accounts: list[Account]

    def account(self, account_id: str) -> Account:
        for a in self.accounts:
            if a.id == account_id:
                return a
        raise ConfigError(f"No account with id '{account_id}' in accounts.toml")

    @property
    def enabled(self) -> list[Account]:
        return [a for a in self.accounts if a.enabled]


def _parse_time(value: str, where: str) -> time:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        raise ConfigError(f"{where}: time '{value}' must be HH:MM (24-hour), e.g. 18:30")


def _parse_days(value, where: str) -> list[int]:
    if value in ("daily", "every", ["daily"]):
        return list(range(7))
    if value in ("weekdays", ["weekdays"]):
        return list(range(5))
    if value in ("weekends", ["weekends"]):
        return [5, 6]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: days must be a list like [\"mon\", \"wed\"] or \"daily\"")
    out = []
    for d in value:
        key = str(d).strip().lower()[:3]
        if key not in DAYS:
            raise ConfigError(f"{where}: unknown day '{d}'")
        out.append(DAYS.index(key))
    return sorted(set(out))


def parse_config(data: dict) -> Config:
    s = data.get("settings", {})
    settings = Settings(
        timezone=s.get("timezone", "America/New_York"),
        min_lead_minutes=int(s.get("min_lead_minutes", 60)),
        default_accounts=list(s.get("default_accounts", [])),
    )
    raw_accounts = data.get("account", [])
    if not raw_accounts:
        raise ConfigError("accounts.toml has no [[account]] entries yet")

    known = {
        "id", "platform", "handle", "days", "times", "max_per_day", "enabled",
        "chrome_profile", "login_hint", "visibility", "hashtags",
        "caption_template", "title_template", "horizon_days", "notes",
    }
    accounts: list[Account] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_accounts, 1):
        where = f"account #{i} ({raw.get('id', '?')})"
        for req in ("id", "platform", "handle", "days", "times"):
            if req not in raw:
                raise ConfigError(f"{where}: missing '{req}'")
        if raw["id"] in seen:
            raise ConfigError(f"{where}: duplicate id")
        seen.add(raw["id"])
        platform = str(raw["platform"]).lower()
        if platform not in PLATFORMS:
            raise ConfigError(
                f"{where}: platform '{platform}' not supported. Use one of: {', '.join(PLATFORMS)}"
            )
        times = raw["times"] if isinstance(raw["times"], list) else [raw["times"]]
        acct = Account(
            id=raw["id"],
            platform=platform,
            handle=raw["handle"],
            days=_parse_days(raw["days"], where),
            times=sorted(_parse_time(t, where) for t in times),
            max_per_day=int(raw.get("max_per_day", 1)),
            enabled=bool(raw.get("enabled", True)),
            chrome_profile=raw.get("chrome_profile", ""),
            login_hint=raw.get("login_hint", ""),
            visibility=raw.get("visibility", "public"),
            hashtags=list(raw.get("hashtags", [])),
            caption_template=raw.get("caption_template", Account.caption_template),
            title_template=raw.get("title_template", Account.title_template),
            horizon_days=raw.get("horizon_days"),
            notes=raw.get("notes", ""),
            extra={k: v for k, v in raw.items() if k not in known},
        )
        if acct.max_per_day < 1:
            raise ConfigError(f"{where}: max_per_day must be at least 1")
        if acct.horizon_days is None:
            acct.horizon_days = acct.spec["horizon_days"]
        accounts.append(acct)

    for d in settings.default_accounts:
        if d not in seen:
            raise ConfigError(f"settings.default_accounts names unknown account '{d}'")
    return Config(settings=settings, accounts=accounts)


def load_config(path: Path) -> Config:
    if not path.exists():
        raise ConfigError(f"{path} not found. Run `./uploader init` first.")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}")
    return parse_config(data)


EXAMPLE_CONFIG = Path(__file__).with_name("accounts.example.toml")
