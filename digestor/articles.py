from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re

from .config import Profile


TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref"}


@dataclass
class Article:
    url: str
    title: str
    source: str = ""
    source_url: str = ""
    author: str = ""
    published_at: str = ""
    summary: str = ""
    content: str = ""


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        low = key.lower()
        if low in TRACKING_PARAMS or any(low.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def fingerprint(title: str, content: str) -> str:
    normalized = normalize_text(f"{title}\n{content}")[:4000]
    return sha256(normalized.encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def rank_articles(profile: Profile, articles: list[dict], limit: int | None = None) -> list[dict]:
    include = [kw.lower() for kw in profile.include_keywords]
    exclude = [kw.lower() for kw in profile.exclude_keywords]
    now = datetime.now(timezone.utc)
    scored: list[tuple[float, dict]] = []

    for article in articles:
        haystack = normalize_text(
            " ".join(
                [
                    str(article.get("title") or ""),
                    str(article.get("summary") or ""),
                    str(article.get("content") or ""),
                    str(article.get("source") or ""),
                ]
            )
        )
        if exclude and any(keyword in haystack for keyword in exclude):
            continue

        score = 1.0
        if include:
            score += sum(2.5 for keyword in include if keyword in haystack)
        published_at = _parse_dt(str(article.get("published_at") or ""))
        if published_at:
            age_hours = max((now - published_at).total_seconds() / 3600, 0)
            score += max(0, 3 - age_hours / 24)
        if article.get("summary"):
            score += 0.4
        if article.get("content"):
            score += 0.6
        scored.append((score, article))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [article for _, article in scored[: limit or profile.max_articles]]


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None
