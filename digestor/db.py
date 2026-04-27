from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import json
import sqlite3

from .articles import Article, canonical_url, fingerprint
from .config import DATA_DIR


DEFAULT_DB = DATA_DIR / "digestor.sqlite"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else DEFAULT_DB
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
            sent_at TEXT,
            UNIQUE(profile, canonical_url)
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
    conn.commit()


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
