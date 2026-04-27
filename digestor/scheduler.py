from __future__ import annotations

from datetime import date, datetime
from threading import Event, Thread
from zoneinfo import ZoneInfo
import os
import sqlite3

from .db import connect, latest_digest, list_workspaces
from .emailer import smtp_configured
from .services import fetch_workspace, generate_digest, send_digest_for_date


class DigestScheduler:
    def __init__(
        self,
        db_path: str | None = None,
        interval_minutes: int | None = None,
        stop_event: Event | None = None,
    ) -> None:
        self.db_path = db_path
        self.interval_minutes = interval_minutes or int(os.environ.get("FETCH_INTERVAL_MINUTES", "60"))
        self.stop_event = stop_event or Event()
        self.thread: Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = Thread(target=self.run_forever, name="digest-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            self.run_once()
            self.stop_event.wait(max(self.interval_minutes, 1) * 60)

    def run_once(self, now: datetime | None = None) -> list[dict]:
        conn = connect(self.db_path)
        results = []
        for workspace in list_workspaces(conn):
            slug = workspace["slug"]
            result = {"workspace": slug, "fetched": None, "digest": None, "sent": None, "error": None}
            try:
                result["fetched"] = fetch_workspace(conn, slug)
                if self._digest_due(conn, workspace, now):
                    result["digest"] = generate_digest(conn, slug)
                    if smtp_configured():
                        result["sent"] = send_digest_for_date(conn, slug)
                    else:
                        result["sent"] = "skipped: smtp not configured"
            except Exception as exc:  # noqa: BLE001 - scheduler must keep the app alive
                result["error"] = str(exc)
            results.append(result)
        conn.close()
        return results

    def _digest_due(self, conn: sqlite3.Connection, workspace: sqlite3.Row, now: datetime | None = None) -> bool:
        tz = ZoneInfo(workspace["timezone"] or "Europe/Rome")
        current = now.astimezone(tz) if now else datetime.now(tz)
        digest_date = date(current.year, current.month, current.day)
        digest_time = workspace["digest_time"] or "08:00"
        hour, minute = [int(part) for part in digest_time.split(":", 1)]
        if (current.hour, current.minute) < (hour, minute):
            return False
        existing = latest_digest(conn, workspace["slug"], digest_date)
        return not existing or existing["sent_at"] is None


def scheduler_enabled() -> bool:
    return os.environ.get("SCHEDULER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
