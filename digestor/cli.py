from __future__ import annotations

from datetime import date
from pathlib import Path
import argparse
import time

from .articles import rank_articles
from .config import FeedConfig, load_env, load_or_create_profile, load_profile, save_profile
from .db import (
    add_saved_url,
    candidate_articles,
    connect,
    latest_digest,
    mark_digest_sent,
    mark_saved_url_consumed,
    pending_saved_urls,
    store_digest,
    upsert_article,
)
from .emailer import digest_subject, render_digest_html, send_digest, write_digest_html
from .feeds import fetch_feed, fetch_saved_article
from .llm import build_digest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env()
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    return args.func(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m digestor")
    parser.add_argument("--db", default=None, help="SQLite path, default data/digestor.sqlite")
    sub = parser.add_subparsers()

    add_feed = sub.add_parser("add-feed", help="Add an RSS/Atom feed to a profile")
    add_feed.add_argument("--profile", required=True)
    add_feed.add_argument("url")
    add_feed.add_argument("--title", default="")
    add_feed.add_argument("--weight", type=int, default=1)
    add_feed.set_defaults(func=cmd_add_feed)

    add_url = sub.add_parser("add-url", help="Add a one-off article URL to a profile inbox")
    add_url.add_argument("--profile", required=True)
    add_url.add_argument("url")
    add_url.add_argument("--title", default="")
    add_url.add_argument("--note", default="")
    add_url.set_defaults(func=cmd_add_url)

    fetch = sub.add_parser("fetch", help="Fetch profile feeds and saved URLs")
    fetch.add_argument("--profile", required=True)
    fetch.set_defaults(func=cmd_fetch)

    digest = sub.add_parser("digest", help="Build and archive an HTML digest")
    digest.add_argument("--profile", required=True)
    digest.add_argument("--date", default="today")
    digest.add_argument("--require-llm", action="store_true")
    digest.add_argument("--dry-run", action="store_true", help="Do not store the digest in SQLite")
    digest.set_defaults(func=cmd_digest)

    send = sub.add_parser("send", help="Send an archived digest via SMTP")
    send.add_argument("--profile", required=True)
    send.add_argument("--date", default="today")
    send.add_argument("--to", default=None)
    send.set_defaults(func=cmd_send)

    run_daily = sub.add_parser("run-daily", help="Fetch, digest and send once, or loop with --watch")
    run_daily.add_argument("--profile", required=True)
    run_daily.add_argument("--date", default="today")
    run_daily.add_argument("--watch", action="store_true")
    run_daily.add_argument("--interval-minutes", type=int, default=1440)
    run_daily.set_defaults(func=cmd_run_daily)
    return parser


def cmd_add_feed(args: argparse.Namespace) -> int:
    profile = load_or_create_profile(args.profile)
    if not any(feed.url == args.url for feed in profile.feeds):
        profile.feeds.append(FeedConfig(url=args.url, title=args.title, weight=args.weight))
    path = save_profile(profile)
    print(f"Saved feed in {path}")
    return 0


def cmd_add_url(args: argparse.Namespace) -> int:
    conn = connect(_db_path(args))
    saved_id = add_saved_url(conn, args.profile, args.url, args.title, args.note)
    print(f"Saved URL #{saved_id}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    conn = connect(_db_path(args))
    fetched = 0
    created = 0

    for feed in profile.feeds:
        try:
            articles = fetch_feed(feed.url, feed.title)
        except Exception as exc:  # noqa: BLE001 - CLI should keep going across feeds
            print(f"Feed failed: {feed.url} ({exc})")
            continue
        for article in articles:
            _, inserted = upsert_article(conn, profile.name, article)
            fetched += 1
            created += int(inserted)

    for saved in pending_saved_urls(conn, profile.name):
        try:
            article = fetch_saved_article(saved["url"], saved["title"] or "")
            _, inserted = upsert_article(conn, profile.name, article)
            created += int(inserted)
            fetched += 1
            mark_saved_url_consumed(conn, int(saved["id"]))
        except Exception as exc:  # noqa: BLE001
            print(f"Saved URL failed: {saved['url']} ({exc})")

    print(f"Fetched {fetched} article candidates, {created} new")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    conn = connect(_db_path(args))
    digest_date = _parse_date_arg(args.date)
    candidates = candidate_articles(conn, profile.name, digest_date, profile.max_articles)
    articles = rank_articles(profile, candidates, profile.max_articles)
    payload = build_digest(profile, articles, require_llm=args.require_llm)
    article_ids = sorted({article_id for topic in payload.get("topics", []) for article_id in topic.get("article_ids", [])})
    if not article_ids:
        article_ids = [item["id"] for item in articles]
    html = render_digest_html(profile, digest_date.isoformat(), payload)
    html_path = write_digest_html(profile, digest_date.isoformat(), html)
    subject = digest_subject(profile, digest_date.isoformat(), payload)
    if not args.dry_run:
        digest_id = store_digest(conn, profile.name, digest_date, subject, html_path, payload, article_ids)
        print(f"Stored digest #{digest_id}: {html_path}")
    else:
        print(f"Dry-run digest: {html_path}")
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    conn = connect(_db_path(args))
    digest_date = _parse_date_arg(args.date)
    row = latest_digest(conn, profile.name, digest_date)
    if not row:
        raise SystemExit(f"No digest found for {profile.name} on {digest_date}")
    html_path = row["html_path"]
    html = open(html_path, encoding="utf-8").read()
    send_digest(profile, row["subject"], html, args.to)
    mark_digest_sent(conn, int(row["id"]))
    print(f"Sent digest #{row['id']} to {args.to or profile.recipient_email}")
    return 0


def cmd_run_daily(args: argparse.Namespace) -> int:
    while True:
        cmd_fetch(args)
        cmd_digest(argparse.Namespace(**vars(args), require_llm=False, dry_run=False))
        cmd_send(args)
        if not args.watch:
            return 0
        time.sleep(max(args.interval_minutes, 1) * 60)


def _parse_date_arg(value: str) -> date:
    if value == "today":
        return date.today()
    return date.fromisoformat(value)


def _db_path(args: argparse.Namespace):
    return Path(args.db) if args.db else None
