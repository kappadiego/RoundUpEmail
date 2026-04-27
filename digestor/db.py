from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import json
import sqlite3

from .articles import Article, canonical_url, fingerprint
from .config import FeedConfig, Profile, get_data_dir


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else get_data_dir() / "digestor.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            url TEXT NOT NULL,
            canonical_url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT,
            source_url TEXT,
            author TEXT,
            published_at TEXT,
            fetched_at TEXT NOT NULL,
            summary TEXT,
            content TEXT,
            fingerprint TEXT NOT NULL,
            read_at TEXT,
            saved_at TEXT,
            sent_at TEXT,
            UNIQUE(profile, canonical_url)
        );

        CREATE TABLE IF NOT EXISTS workspaces (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            include_keywords TEXT NOT NULL DEFAULT '[]',
            exclude_keywords TEXT NOT NULL DEFAULT '[]',
            language TEXT NOT NULL DEFAULT 'it',
            timezone TEXT NOT NULL DEFAULT 'Europe/Rome',
            digest_time TEXT NOT NULL DEFAULT '08:00',
            recipient_email TEXT,
            max_articles INTEGER NOT NULL DEFAULT 50,
            model TEXT NOT NULL DEFAULT 'gpt-5.4-mini',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            weight INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_fetched_at TEXT,
            UNIQUE(workspace, url),
            FOREIGN KEY(workspace) REFERENCES workspaces(slug) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS saved_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            note TEXT,
            added_at TEXT NOT NULL,
            consumed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            digest_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            html_path TEXT NOT NULL,
            json_payload TEXT NOT NULL,
            article_ids TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sent_at TEXT,
            UNIQUE(profile, digest_date)
        );

        CREATE TABLE IF NOT EXISTS topic_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            digest_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            json_payload TEXT NOT NULL,
            FOREIGN KEY(digest_id) REFERENCES digests(id) ON DELETE CASCADE
        );
        """
    )
    _add_column(conn, "articles", "read_at", "TEXT")
    _add_column(conn, "articles", "saved_at", "TEXT")
    conn.commit()


def _add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_workspace(
    conn: sqlite3.Connection,
    slug: str,
    name: str = "",
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    language: str = "it",
    timezone_name: str = "Europe/Rome",
    digest_time: str = "08:00",
    recipient_email: str = "",
    max_articles: int = 50,
    model: str = "gpt-5.4-mini",
) -> None:
    conn.execute(
        """
        INSERT INTO workspaces(
            slug, name, include_keywords, exclude_keywords, language, timezone,
            digest_time, recipient_email, max_articles, model, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            name = excluded.name,
            include_keywords = excluded.include_keywords,
            exclude_keywords = excluded.exclude_keywords,
            language = excluded.language,
            timezone = excluded.timezone,
            digest_time = excluded.digest_time,
            recipient_email = excluded.recipient_email,
            max_articles = excluded.max_articles,
            model = excluded.model
        """,
        (
            slug,
            name or slug,
            json.dumps(include_keywords or []),
            json.dumps(exclude_keywords or []),
            language,
            timezone_name,
            digest_time,
            recipient_email,
            max_articles,
            model,
            utcnow(),
        ),
    )
    conn.commit()


def list_workspaces(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM workspaces ORDER BY name COLLATE NOCASE"))


def get_workspace(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM workspaces WHERE slug = ?", (slug,)).fetchone()


def ensure_workspace(conn: sqlite3.Connection, slug: str, name: str = "") -> sqlite3.Row:
    existing = get_workspace(conn, slug)
    if not existing:
        create_workspace(conn, slug, name or slug)
    row = get_workspace(conn, slug)
    assert row is not None
    return row


def workspace_profile(conn: sqlite3.Connection, slug: str) -> Profile:
    row = ensure_workspace(conn, slug)
    feeds = [FeedConfig(url=feed["url"], title=feed["title"] or "", weight=int(feed["weight"])) for feed in list_feeds(conn, slug)]
    return Profile(
        name=row["slug"],
        feeds=feeds,
        include_keywords=json.loads(row["include_keywords"] or "[]"),
        exclude_keywords=json.loads(row["exclude_keywords"] or "[]"),
        language=row["language"],
        timezone=row["timezone"],
        digest_time=row["digest_time"],
        recipient_email=row["recipient_email"] or "",
        max_articles=int(row["max_articles"]),
        model=row["model"],
    )


def add_feed(conn: sqlite3.Connection, workspace: str, url: str, title: str = "", weight: int = 1) -> int:
    ensure_workspace(conn, workspace)
    cur = conn.execute(
        """
        INSERT INTO feeds(workspace, url, title, weight, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(workspace, url) DO UPDATE SET
            title = excluded.title,
            weight = excluded.weight,
            active = 1
        RETURNING id
        """,
        (workspace, url, title, weight, utcnow()),
    )
    row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def update_feed(conn: sqlite3.Connection, feed_id: int, title: str, weight: int, active: bool) -> None:
    conn.execute(
        "UPDATE feeds SET title = ?, weight = ?, active = ? WHERE id = ?",
        (title, weight, int(active), feed_id),
    )
    conn.commit()


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> None:
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()


def list_feeds(conn: sqlite3.Connection, workspace: str, active_only: bool = True) -> list[sqlite3.Row]:
    if active_only:
        return list(conn.execute("SELECT * FROM feeds WHERE workspace = ? AND active = 1 ORDER BY title, url", (workspace,)))
    return list(conn.execute("SELECT * FROM feeds WHERE workspace = ? ORDER BY active DESC, title, url", (workspace,)))


def mark_feed_fetched(conn: sqlite3.Connection, feed_id: int) -> None:
    conn.execute("UPDATE feeds SET last_fetched_at = ? WHERE id = ?", (utcnow(), feed_id))
    conn.commit()


def list_articles(
    conn: sqlite3.Connection,
    profile: str,
    limit: int = 100,
    saved_only: bool = False,
    unread_only: bool = False,
) -> list[sqlite3.Row]:
    where = ["profile = ?"]
    params: list[object] = [profile]
    if saved_only:
        where.append("saved_at IS NOT NULL")
    if unread_only:
        where.append("read_at IS NULL")
    query = f"""
        SELECT * FROM articles
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT ?
    """
    params.append(limit)
    return list(conn.execute(query, params))


def get_article(conn: sqlite3.Connection, article_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def set_article_read(conn: sqlite3.Connection, article_id: int, read: bool) -> None:
    conn.execute("UPDATE articles SET read_at = ? WHERE id = ?", (utcnow() if read else None, article_id))
    conn.commit()


def set_article_saved(conn: sqlite3.Connection, article_id: int, saved: bool) -> None:
    conn.execute("UPDATE articles SET saved_at = ? WHERE id = ?", (utcnow() if saved else None, article_id))
    conn.commit()


def list_digests(conn: sqlite3.Connection, profile: str, limit: int = 30) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT * FROM digests
            WHERE profile = ?
            ORDER BY digest_date DESC, created_at DESC
            LIMIT ?
            """,
            (profile, limit),
        )
    )


def add_saved_url(conn: sqlite3.Connection, profile: str, url: str, title: str = "", note: str = "") -> int:
    cur = conn.execute(
        """
        INSERT INTO saved_urls(profile, url, title, note, added_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (profile, url, title, note, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def pending_saved_urls(conn: sqlite3.Connection, profile: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM saved_urls WHERE profile = ? AND consumed_at IS NULL ORDER BY added_at",
            (profile,),
        )
    )


def mark_saved_url_consumed(conn: sqlite3.Connection, saved_url_id: int) -> None:
    conn.execute("UPDATE saved_urls SET consumed_at = ? WHERE id = ?", (utcnow(), saved_url_id))
    conn.commit()


def upsert_article(conn: sqlite3.Connection, profile: str, article: Article) -> tuple[int, bool]:
    canonical = canonical_url(article.url)
    fp = fingerprint(article.title, article.content or article.summary)
    fetched = utcnow()
    existing = conn.execute(
        "SELECT id FROM articles WHERE profile = ? AND canonical_url = ?",
        (profile, canonical),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO articles(
            profile, url, canonical_url, title, source, source_url, author,
            published_at, fetched_at, summary, content, fingerprint
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(profile, canonical_url) DO UPDATE SET
            title = excluded.title,
            source = COALESCE(NULLIF(excluded.source, ''), articles.source),
            source_url = COALESCE(NULLIF(excluded.source_url, ''), articles.source_url),
            author = COALESCE(NULLIF(excluded.author, ''), articles.author),
            published_at = COALESCE(NULLIF(excluded.published_at, ''), articles.published_at),
            fetched_at = excluded.fetched_at,
            summary = COALESCE(NULLIF(excluded.summary, ''), articles.summary),
            content = COALESCE(NULLIF(excluded.content, ''), articles.content),
            fingerprint = excluded.fingerprint
        """,
        (
            profile,
            article.url,
            canonical,
            article.title or canonical,
            article.source,
            article.source_url,
            article.author,
            article.published_at,
            fetched,
            article.summary,
            article.content,
            fp,
        ),
    )
    row = conn.execute(
        "SELECT id FROM articles WHERE profile = ? AND canonical_url = ?",
        (profile, canonical),
    ).fetchone()
    conn.commit()
    return int(row["id"]), existing is None


def candidate_articles(conn: sqlite3.Connection, profile: str, digest_date: date, limit: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM articles
        WHERE profile = ?
          AND sent_at IS NULL
          AND (
            published_at IS NULL OR published_at = ''
            OR substr(published_at, 1, 10) <= ?
          )
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT ?
        """,
        (profile, digest_date.isoformat(), limit * 3),
    )
    return [dict(row) for row in rows]


def store_digest(
    conn: sqlite3.Connection,
    profile: str,
    digest_date: date,
    subject: str,
    html_path: Path,
    payload: dict,
    article_ids: list[int],
) -> int:
    existing = conn.execute(
        "SELECT id FROM digests WHERE profile = ? AND digest_date = ?",
        (profile, digest_date.isoformat()),
    ).fetchone()
    if existing:
        digest_id = int(existing["id"])
        conn.execute("DELETE FROM topic_clusters WHERE digest_id = ?", (digest_id,))
        conn.execute(
            """
            UPDATE digests
            SET subject = ?, html_path = ?, json_payload = ?, article_ids = ?, created_at = ?, sent_at = NULL
            WHERE id = ?
            """,
            (
                subject,
                str(html_path),
                json.dumps(payload, ensure_ascii=False),
                json.dumps(article_ids),
                utcnow(),
                digest_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO digests(profile, digest_date, subject, html_path, json_payload, article_ids, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile,
                digest_date.isoformat(),
                subject,
                str(html_path),
                json.dumps(payload, ensure_ascii=False),
                json.dumps(article_ids),
                utcnow(),
            ),
        )
        digest_id = int(cur.lastrowid)

    for topic in payload.get("topics", []):
        conn.execute(
            "INSERT INTO topic_clusters(digest_id, title, json_payload) VALUES (?, ?, ?)",
            (digest_id, topic.get("title", "Topic"), json.dumps(topic, ensure_ascii=False)),
        )
    conn.commit()
    return digest_id


def latest_digest(conn: sqlite3.Connection, profile: str, digest_date: date | None = None) -> sqlite3.Row | None:
    if digest_date:
        return conn.execute(
            "SELECT * FROM digests WHERE profile = ? AND digest_date = ?",
            (profile, digest_date.isoformat()),
        ).fetchone()
    return conn.execute(
        "SELECT * FROM digests WHERE profile = ? ORDER BY digest_date DESC, created_at DESC LIMIT 1",
        (profile,),
    ).fetchone()


def mark_digest_sent(conn: sqlite3.Connection, digest_id: int) -> None:
    row = conn.execute("SELECT article_ids FROM digests WHERE id = ?", (digest_id,)).fetchone()
    if not row:
        return
    sent_at = utcnow()
    ids = json.loads(row["article_ids"] or "[]")
    conn.execute("UPDATE digests SET sent_at = ? WHERE id = ?", (sent_at, digest_id))
    if ids:
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE articles SET sent_at = ? WHERE id IN ({placeholders})",
            [sent_at, *ids],
        )
    conn.commit()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
