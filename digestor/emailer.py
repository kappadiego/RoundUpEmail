from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path
import os
import smtplib

from .config import Profile, get_digests_dir


def render_digest_html(profile: Profile, digest_date: str, payload: dict) -> str:
    subject = digest_subject(profile, digest_date, payload)
    body = _render_topics(payload.get("topics", []))
    template = (Path(__file__).parent / "templates" / "digest.html").read_text(encoding="utf-8")
    try:
        from jinja2 import Template  # type: ignore

        return Template(template).render(
            subject=subject,
            profile=profile,
            digest_date=digest_date,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            body=body,
        )
    except ModuleNotFoundError:
        return (
            template.replace("{{ subject }}", escape(subject))
            .replace("{{ profile.name }}", escape(profile.name))
            .replace("{{ digest_date }}", escape(digest_date))
            .replace("{{ generated_at }}", escape(datetime.now().strftime("%Y-%m-%d %H:%M")))
            .replace("{{ body|safe }}", body)
        )


def write_digest_html(profile: Profile, digest_date: str, html: str) -> Path:
    out_dir = get_digests_dir() / profile.name
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{digest_date}.html"
    path.write_text(html, encoding="utf-8")
    return path


def digest_subject(profile: Profile, digest_date: str, payload: dict) -> str:
    count = len(payload.get("topics", []))
    return f"{profile.name}: digest {digest_date} ({count} topic)"


def send_digest(profile: Profile, subject: str, html: str, to_email: str | None = None) -> None:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("SMTP_FROM") or username
    recipient = to_email or profile.recipient_email or os.environ.get("SMTP_TO")
    if not host or not from_email or not recipient:
        raise RuntimeError("SMTP_HOST, SMTP_FROM/SMTP_USER and recipient email are required")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = recipient
    message.set_content("Il digest HTML e disponibile in un client compatibile.")
    message.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def _render_topics(topics: list[dict]) -> str:
    if not topics:
        return "<p>Nessun nuovo articolo da includere oggi.</p>"
    parts: list[str] = []
    for topic in topics:
        links = "".join(
            f'<li><a href="{escape(link.get("url", ""))}">{escape(link.get("title", "Fonte"))}</a>'
            f' <span>{escape(link.get("source", ""))}</span></li>'
            for link in topic.get("source_links", [])[:2]
        )
        points = "".join(f"<li>{escape(point)}</li>" for point in topic.get("key_points", [])[:5])
        parts.append(
            f"""
            <section class="topic">
              <h2>{escape(topic.get("title", "Topic"))}</h2>
              <p class="summary">{escape(topic.get("summary", ""))}</p>
              <p class="why">{escape(topic.get("why_it_matters", ""))}</p>
              <ul class="points">{points}</ul>
              <h3>Fonti da consultare</h3>
              <ul class="sources">{links}</ul>
            </section>
            """
        )
    return "\n".join(parts)
