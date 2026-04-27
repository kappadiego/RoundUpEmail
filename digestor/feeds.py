from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.request import Request, urlopen
import re
import xml.etree.ElementTree as ET

from .articles import Article, normalize_text


USER_AGENT = "PersonalDigestor/0.1 (+local)"


def fetch_bytes(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_feed(url: str, title: str = "") -> list[Article]:
    xml = fetch_bytes(url).decode("utf-8", errors="replace")
    return parse_feed(xml, source_url=url, fallback_source=title)


def parse_feed(xml: str, source_url: str = "", fallback_source: str = "") -> list[Article]:
    root = ET.fromstring(xml)
    source = fallback_source or _first_text(root, ["title"]) or source_url
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    articles: list[Article] = []
    for item in items:
        title = _child_text(item, "title") or "Untitled"
        link = _child_text(item, "link") or _atom_link(item)
        if not link:
            continue
        summary = (
            _child_text(item, "description")
            or _child_text(item, "summary")
            or _child_text(item, "content")
            or ""
        )
        articles.append(
            Article(
                url=link,
                title=clean_text(title),
                source=clean_text(source),
                source_url=source_url,
                author=clean_text(_child_text(item, "creator") or _child_text(item, "author") or ""),
                published_at=parse_date(
                    _child_text(item, "pubDate")
                    or _child_text(item, "published")
                    or _child_text(item, "updated")
                    or ""
                ),
                summary=clean_text(summary),
                content=clean_text(summary),
            )
        )
    return articles


def fetch_saved_article(url: str, title: str = "") -> Article:
    html = fetch_bytes(url).decode("utf-8", errors="replace")
    extracted = extract_html(html)
    return Article(
        url=url,
        title=title or extracted["title"] or url,
        source=extracted["site_name"],
        source_url=url,
        summary=extracted["description"],
        content=extracted["content"],
        published_at=extracted["published_at"],
    )


def extract_html(html: str) -> dict[str, str]:
    parser = _HTMLExtractor()
    parser.feed(html)
    title = parser.title.strip()
    description = parser.meta.get("description") or parser.meta.get("og:description") or ""
    site_name = parser.meta.get("og:site_name") or ""
    published_at = parser.meta.get("article:published_time") or ""
    paragraphs = " ".join(parser.paragraphs[:20])
    content = clean_text(paragraphs or description)
    return {
        "title": clean_text(parser.meta.get("og:title") or title),
        "description": clean_text(description),
        "site_name": clean_text(site_name),
        "published_at": parse_date(published_at) if published_at else "",
        "content": content[:6000],
    }


def parse_date(value: str) -> str:
    if not value:
        return ""
    raw = value.strip()
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: str) -> str:
    text = unescape(value or "")
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _child_text(element: ET.Element, name: str) -> str:
    for child in list(element):
        if _local_name(child.tag).lower() == name.lower():
            return child.text or ""
    return ""


def _first_text(element: ET.Element, names: list[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in element.iter():
        if _local_name(child.tag).lower() in wanted and child.text:
            return child.text
    return ""


def _atom_link(element: ET.Element) -> str:
    for child in list(element):
        if _local_name(child.tag).lower() == "link":
            href = child.attrib.get("href")
            if href:
                return href
            if child.text:
                return child.text
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class _HTMLExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self.paragraphs: list[str] = []
        self._capture: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = attrs_dict.get("name") or attrs_dict.get("property")
            content = attrs_dict.get("content")
            if key and content:
                self.meta[key.lower()] = content
        if tag in {"title", "p"}:
            self._capture = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self._capture == tag:
            text = normalize_text(" ".join(self._buffer))
            if tag == "title":
                self.title = text
            elif tag == "p" and len(text) > 40:
                self.paragraphs.append(text)
            self._capture = None
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)
