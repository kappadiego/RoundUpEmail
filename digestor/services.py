from __future__ import annotations

from datetime import date
import sqlite3

from .articles import rank_articles
from .db import (
    candidate_articles,
    latest_digest,
    list_feeds,
    mark_digest_sent,
    mark_feed_fetched,
    mark_saved_url_consumed,
    pending_saved_urls,
    store_digest,
    upsert_article,
    workspace_profile,
)
from .emailer import digest_subject, render_digest_html, send_digest, write_digest_html
from .feeds import fetch_feed, fetch_saved_article
from .llm import build_digest


def fetch_workspace(conn: sqlite3.Connection, workspace: str) -> dict[str, int]:
    profile = workspace_profile(conn, workspace)
    fetched = 0
    created = 0
    failed = 0

    for feed in list_feeds(conn, workspace):
        try:
            articles = fetch_feed(feed["url"], feed["title"] or "")
            mark_feed_fetched(conn, int(feed["id"]))
        except Exception:
            failed += 1
            continue
        for article in articles:
            _, inserted = upsert_article(conn, profile.name, article)
            fetched += 1
            created += int(inserted)

    for saved in pending_saved_urls(conn, workspace):
        try:
            article = fetch_saved_article(saved["url"], saved["title"] or "")
            _, inserted = upsert_article(conn, profile.name, article)
            created += int(inserted)
            fetched += 1
            mark_saved_url_consumed(conn, int(saved["id"]))
        except Exception:
            failed += 1

    return {"fetched": fetched, "created": created, "failed": failed}


def generate_digest(
    conn: sqlite3.Connection,
    workspace: str,
    digest_date: date | None = None,
    require_llm: bool = False,
) -> dict:
    profile = workspace_profile(conn, workspace)
    day = digest_date or date.today()
    candidates = candidate_articles(conn, profile.name, day, profile.max_articles)
    articles = rank_articles(profile, candidates, profile.max_articles)
    payload = build_digest(profile, articles, require_llm=require_llm)
    article_ids = sorted({article_id for topic in payload.get("topics", []) for article_id in topic.get("article_ids", [])})
    if not article_ids:
        article_ids = [item["id"] for item in articles]
    html = render_digest_html(profile, day.isoformat(), payload)
    html_path = write_digest_html(profile, day.isoformat(), html)
    subject = digest_subject(profile, day.isoformat(), payload)
    digest_id = store_digest(conn, profile.name, day, subject, html_path, payload, article_ids)
    return {
        "id": digest_id,
        "subject": subject,
        "html_path": str(html_path),
        "topic_count": len(payload.get("topics", [])),
        "article_count": len(article_ids),
    }


def send_digest_for_date(conn: sqlite3.Connection, workspace: str, digest_date: date | None = None, to_email: str | None = None) -> int:
    profile = workspace_profile(conn, workspace)
    row = latest_digest(conn, workspace, digest_date or date.today())
    if not row:
        generated = generate_digest(conn, workspace, digest_date)
        row = latest_digest(conn, workspace, digest_date or date.today())
        if not row:
            raise RuntimeError(f"Digest generation failed for {workspace}: {generated}")
    html = open(row["html_path"], encoding="utf-8").read()
    send_digest(profile, row["subject"], html, to_email)
    mark_digest_sent(conn, int(row["id"]))
    return int(row["id"])
