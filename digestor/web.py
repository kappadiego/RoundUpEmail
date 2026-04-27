from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
from urllib.parse import quote_plus

try:
    from fastapi import Depends, FastAPI, Form, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without web deps installed
    raise RuntimeError("Install web dependencies with `pip install -e .` before running the web app") from exc

from .config import data_dir_warning, get_data_dir, load_env
from .db import (
    add_feed,
    add_saved_url,
    connect,
    create_workspace,
    delete_feed,
    get_workspace,
    list_articles,
    list_digests,
    list_feeds,
    list_workspaces,
    set_article_read,
    set_article_saved,
    update_feed,
    workspace_profile,
)
from .emailer import smtp_configured
from .scheduler import DigestScheduler, scheduler_enabled
from .services import fetch_workspace, generate_digest, send_digest_for_date


load_env()

app = FastAPI(title="RoundUpEmail")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "web_templates"))
templates.env.filters["from_json"] = lambda value: json.loads(value or "{}")
templates.env.filters["short_date"] = lambda value: (value or "")[:10]

_scheduler = DigestScheduler()


@asynccontextmanager
async def lifespan(_: FastAPI):
    connect().close()
    if scheduler_enabled():
        _scheduler.start()
    try:
        yield
    finally:
        _scheduler.stop()


app.router.lifespan_context = lifespan


def current_user(request: Request) -> bool:
    token = request.cookies.get("roundup_session")
    if token and hmac.compare_digest(token, _session_token()):
        return True
    raise HTTPException(status_code=401)


def require_user(request: Request) -> bool:
    return current_user(request)


@app.exception_handler(401)
async def unauthorized(_: Request, __: HTTPException) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {
        "ok": True,
        "app": app.title,
        "storage": str(get_data_dir()),
        "smtp": smtp_configured(),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "scheduler": scheduler_enabled(),
    }


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
def login(password: str = Form("")):
    expected = os.environ.get("APP_PASSWORD", "change-me")
    if not hmac.compare_digest(password, expected):
        return RedirectResponse("/login?error=Password+non+valida", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("roundup_session", _session_token(), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("roundup_session")
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request, _: bool = Depends(require_user)):
    conn = connect()
    workspaces = list_workspaces(conn)
    if not workspaces:
        create_workspace(conn, "default", "Default")
        workspaces = list_workspaces(conn)
    return templates.TemplateResponse("workspaces.html", {"request": request, "workspaces": workspaces})


@app.post("/workspaces")
def create_workspace_route(
    name: str = Form(...),
    include_keywords: str = Form(""),
    digest_time: str = Form("08:00"),
    recipient_email: str = Form(""),
    _: bool = Depends(require_user),
):
    slug = slugify(name)
    conn = connect()
    create_workspace(
        conn,
        slug,
        name=name.strip(),
        include_keywords=csv(include_keywords),
        digest_time=digest_time or "08:00",
        recipient_email=recipient_email.strip(),
    )
    return RedirectResponse(f"/w/{slug}", status_code=303)


@app.get("/w/{workspace}", response_class=HTMLResponse)
def workspace_dashboard(request: Request, workspace: str, _: bool = Depends(require_user)):
    conn = connect()
    row = _workspace_or_404(conn, workspace)
    articles = list_articles(conn, workspace, limit=8)
    feeds = list_feeds(conn, workspace, active_only=False)
    digests = list_digests(conn, workspace, limit=5)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "workspace": row,
            "profile": workspace_profile(conn, workspace),
            "articles": articles,
            "feeds": feeds,
            "digests": digests,
            "setup_status": setup_status(),
            "notice": request.query_params.get("notice", ""),
        },
    )


@app.get("/w/{workspace}/feeds", response_class=HTMLResponse)
def feeds_page(request: Request, workspace: str, _: bool = Depends(require_user)):
    conn = connect()
    row = _workspace_or_404(conn, workspace)
    return templates.TemplateResponse(
        "feeds.html",
        {"request": request, "workspace": row, "feeds": list_feeds(conn, workspace, active_only=False)},
    )


@app.post("/w/{workspace}/feeds")
def add_feed_route(
    workspace: str,
    url: str = Form(...),
    title: str = Form(""),
    weight: int = Form(1),
    _: bool = Depends(require_user),
):
    conn = connect()
    _workspace_or_404(conn, workspace)
    add_feed(conn, workspace, url.strip(), title.strip(), weight)
    return RedirectResponse(f"/w/{workspace}/feeds", status_code=303)


@app.post("/w/{workspace}/feeds/{feed_id}/update")
def update_feed_route(
    workspace: str,
    feed_id: int,
    title: str = Form(""),
    weight: int = Form(1),
    active: str = Form("0"),
    _: bool = Depends(require_user),
):
    update_feed(connect(), feed_id, title.strip(), weight, active == "1")
    return RedirectResponse(f"/w/{workspace}/feeds", status_code=303)


@app.post("/w/{workspace}/feeds/{feed_id}/delete")
def delete_feed_route(workspace: str, feed_id: int, _: bool = Depends(require_user)):
    delete_feed(connect(), feed_id)
    return RedirectResponse(f"/w/{workspace}/feeds", status_code=303)


@app.get("/w/{workspace}/articles", response_class=HTMLResponse)
def articles_page(request: Request, workspace: str, filter: str = "all", _: bool = Depends(require_user)):
    conn = connect()
    row = _workspace_or_404(conn, workspace)
    articles = list_articles(conn, workspace, limit=120, saved_only=filter == "saved", unread_only=filter == "unread")
    return templates.TemplateResponse(
        "articles.html",
        {"request": request, "workspace": row, "articles": articles, "filter": filter},
    )


@app.post("/w/{workspace}/articles/{article_id}/read")
def mark_read_route(workspace: str, article_id: int, read: str = Form("1"), _: bool = Depends(require_user)):
    set_article_read(connect(), article_id, read == "1")
    return RedirectResponse(f"/w/{workspace}/articles", status_code=303)


@app.post("/w/{workspace}/articles/{article_id}/saved")
def mark_saved_route(workspace: str, article_id: int, saved: str = Form("1"), _: bool = Depends(require_user)):
    set_article_saved(connect(), article_id, saved == "1")
    return RedirectResponse(f"/w/{workspace}/articles", status_code=303)


@app.post("/w/{workspace}/saved-urls")
def add_saved_url_route(workspace: str, url: str = Form(...), title: str = Form(""), _: bool = Depends(require_user)):
    add_saved_url(connect(), workspace, url.strip(), title.strip())
    return RedirectResponse(f"/w/{workspace}/articles?notice=URL+salvato", status_code=303)


@app.post("/w/{workspace}/fetch")
def fetch_route(workspace: str, _: bool = Depends(require_user)):
    result = fetch_workspace(connect(), workspace)
    notice = f"Fetch completato: {result['created']} nuovi articoli"
    return RedirectResponse(f"/w/{workspace}?notice={quote_plus(notice)}", status_code=303)


@app.post("/w/{workspace}/digest")
def digest_route(workspace: str, _: bool = Depends(require_user)):
    result = generate_digest(connect(), workspace, date.today())
    notice = f"Digest generato: {result['topic_count']} topic"
    return RedirectResponse(f"/w/{workspace}/digests?notice={quote_plus(notice)}", status_code=303)


@app.post("/w/{workspace}/send")
def send_route(workspace: str, _: bool = Depends(require_user)):
    try:
        digest_id = send_digest_for_date(connect(), workspace, date.today())
        notice = f"Digest inviato #{digest_id}"
    except RuntimeError as exc:
        notice = str(exc)
    return RedirectResponse(f"/w/{workspace}/digests?notice={quote_plus(notice)}", status_code=303)


@app.get("/w/{workspace}/digests", response_class=HTMLResponse)
def digests_page(request: Request, workspace: str, _: bool = Depends(require_user)):
    conn = connect()
    row = _workspace_or_404(conn, workspace)
    return templates.TemplateResponse(
        "digests.html",
        {
            "request": request,
            "workspace": row,
            "digests": list_digests(conn, workspace),
            "notice": request.query_params.get("notice", ""),
        },
    )


@app.get("/w/{workspace}/digests/{digest_id}", response_class=HTMLResponse)
def digest_detail(request: Request, workspace: str, digest_id: int, _: bool = Depends(require_user)):
    conn = connect()
    row = conn.execute("SELECT * FROM digests WHERE id = ? AND profile = ?", (digest_id, workspace)).fetchone()
    if not row:
        raise HTTPException(status_code=404)
    html = Path(row["html_path"]).read_text(encoding="utf-8") if Path(row["html_path"]).exists() else ""
    return templates.TemplateResponse("digest_detail.html", {"request": request, "workspace": workspace, "digest": row, "html": html})


def _workspace_or_404(conn, workspace: str):
    row = get_workspace(conn, workspace)
    if not row:
        raise HTTPException(status_code=404)
    return row


def _session_token() -> str:
    secret = os.environ.get("APP_PASSWORD", "change-me").encode("utf-8")
    return hmac.new(secret, b"roundup-session", hashlib.sha256).hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def setup_status() -> dict[str, object]:
    return {
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "smtp": smtp_configured(),
        "scheduler": scheduler_enabled(),
        "app_password": bool(os.environ.get("APP_PASSWORD")),
        "data_dir": str(get_data_dir()),
        "data_dir_warning": data_dir_warning(),
    }
