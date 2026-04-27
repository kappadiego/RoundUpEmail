from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os
import textwrap


ROOT = Path.cwd()
PROFILES_DIR = ROOT / "profiles"
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DIGESTS_DIR = DATA_DIR / "digests"


@dataclass
class FeedConfig:
    url: str
    title: str = ""
    weight: int = 1


@dataclass
class Profile:
    name: str
    feeds: list[FeedConfig] = field(default_factory=list)
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    language: str = "it"
    timezone: str = "Europe/Rome"
    digest_time: str = "08:00"
    recipient_email: str = ""
    max_articles: int = 50
    model: str = "gpt-5.4-mini"


def load_env(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    refresh_paths()


def refresh_paths() -> None:
    global DATA_DIR, DIGESTS_DIR
    DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
    DIGESTS_DIR = Path(os.environ.get("DIGESTS_DIR", DATA_DIR / "digests"))


def get_data_dir() -> Path:
    refresh_paths()
    return DATA_DIR


def get_digests_dir() -> Path:
    refresh_paths()
    return DIGESTS_DIR


def profile_path(name: str) -> Path:
    return PROFILES_DIR / f"{name}.yaml"


def load_profile(name: str) -> Profile:
    path = profile_path(name)
    if not path.exists():
        raise FileNotFoundError(f"Profile not found: {path}")
    data = _load_mapping(path)
    return profile_from_mapping(name, data)


def load_or_create_profile(name: str) -> Profile:
    path = profile_path(name)
    if path.exists():
        return load_profile(name)
    return Profile(name=name)


def save_profile(profile: Profile) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = profile_path(profile.name)
    path.write_text(_dump_profile(profile), encoding="utf-8")
    return path


def profile_from_mapping(name: str, data: dict[str, Any]) -> Profile:
    feeds: list[FeedConfig] = []
    for item in data.get("feeds", []) or []:
        if isinstance(item, str):
            feeds.append(FeedConfig(url=item))
        elif isinstance(item, dict) and item.get("url"):
            feeds.append(
                FeedConfig(
                    url=str(item["url"]),
                    title=str(item.get("title") or ""),
                    weight=int(item.get("weight") or 1),
                )
            )
    return Profile(
        name=name,
        feeds=feeds,
        include_keywords=_string_list(data.get("include_keywords")),
        exclude_keywords=_string_list(data.get("exclude_keywords")),
        language=str(data.get("language") or "it"),
        timezone=str(data.get("timezone") or "Europe/Rome"),
        digest_time=str(data.get("digest_time") or "08:00"),
        recipient_email=str(data.get("recipient_email") or ""),
        max_articles=int(data.get("max_articles") or 50),
        model=str(data.get("model") or "gpt-5.4-mini"),
    )


def _string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Expected mapping in {path}")
        return loaded
    except ModuleNotFoundError:
        return _minimal_yaml_load(text)


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Small YAML subset reader for the profile shape used by this app."""
    text = textwrap.dedent(text)
    result: dict[str, Any] = {}
    current_key: str | None = None
    last_dict: dict[str, Any] | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and stripped.endswith(":"):
            current_key = stripped[:-1]
            result[current_key] = []
            last_dict = None
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            result[key.strip()] = _parse_scalar(value.strip())
            current_key = None
            last_dict = None
            continue
        if current_key and stripped.startswith("- "):
            value = stripped[2:].strip()
            if ":" in value:
                key, scalar = value.split(":", 1)
                last_dict = {key.strip(): _parse_scalar(scalar.strip())}
                result[current_key].append(last_dict)
            else:
                last_dict = None
                result[current_key].append(_parse_scalar(value))
            continue
        if current_key and last_dict is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            last_dict[key.strip()] = _parse_scalar(value.strip())

    return result


def _parse_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.isdigit():
        return int(value)
    return value


def _dump_profile(profile: Profile) -> str:
    lines = [
        f"language: {profile.language}",
        f"timezone: {profile.timezone}",
        f"digest_time: {profile.digest_time}",
        f"recipient_email: {profile.recipient_email}",
        f"max_articles: {profile.max_articles}",
        f"model: {profile.model}",
        "include_keywords:",
    ]
    lines += [f"  - {item}" for item in profile.include_keywords]
    lines.append("exclude_keywords:")
    lines += [f"  - {item}" for item in profile.exclude_keywords]
    lines.append("feeds:")
    for feed in profile.feeds:
        lines.append(f"  - url: {feed.url}")
        if feed.title:
            lines.append(f"    title: {feed.title}")
        if feed.weight != 1:
            lines.append(f"    weight: {feed.weight}")
    return "\n".join(lines).strip() + "\n"
