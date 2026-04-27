from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import Profile


DIGEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "key_points": {"type": "array", "items": {"type": "string"}},
                    "source_links": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "source": {"type": "string"},
                            },
                            "required": ["title", "url", "source"],
                        },
                    },
                },
                "required": ["title", "summary", "why_it_matters", "key_points", "source_links"],
            },
        }
    },
    "required": ["topics"],
}


def build_digest(profile: Profile, articles: list[dict], require_llm: bool = False) -> dict:
    if not articles:
        return {"topics": []}
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        return _openai_digest(profile, articles, api_key)
    if require_llm:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return offline_digest(profile, articles)


def _openai_digest(profile: Profile, articles: list[dict], api_key: str) -> dict:
    payload_articles = [
        {
            "id": item["id"],
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "published_at": item.get("published_at", ""),
            "summary": item.get("summary", ""),
            "content_excerpt": (item.get("content") or "")[:2500],
        }
        for item in articles
    ]
    body = {
        "model": profile.model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You create concise personal editorial briefings. "
                    "Group related articles into dynamic topics, avoid duplicates, "
                    "write in the requested language, and include only the 1-2 best source links per topic."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "language": profile.language,
                        "workspace": profile.name,
                        "include_keywords": profile.include_keywords,
                        "articles": payload_articles,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "personal_digest_topics",
                "schema": DIGEST_SCHEMA,
                "strict": True,
            }
        },
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
    text = _extract_response_text(data)
    parsed = json.loads(text)
    return _attach_article_ids(parsed, articles)


def _extract_response_text(data: dict) -> str:
    if data.get("output_text"):
        return str(data["output_text"])
    chunks: list[str] = []
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    if not chunks:
        raise RuntimeError("OpenAI response did not include output text")
    return "\n".join(chunks)


def offline_digest(profile: Profile, articles: list[dict]) -> dict:
    clusters = _cluster_articles(profile, articles)
    topics = []
    for name, grouped in clusters:
        links = [
            {"title": item.get("title", ""), "url": item.get("url", ""), "source": item.get("source", "")}
            for item in grouped[:2]
        ]
        points = [item.get("title", "") for item in grouped[:4] if item.get("title")]
        summary = _summary_sentence(grouped)
        topics.append(
            {
                "title": name,
                "summary": summary,
                "why_it_matters": "Tema emerso da piu fonti recenti o coerente con le keyword del profilo.",
                "key_points": points,
                "source_links": links,
                "article_ids": [item["id"] for item in grouped],
            }
        )
    return {"topics": topics}


def _cluster_articles(profile: Profile, articles: list[dict]) -> list[tuple[str, list[dict]]]:
    keywords = [kw.lower() for kw in profile.include_keywords]
    clusters: dict[str, list[dict]] = defaultdict(list)
    unmatched: list[dict] = []

    for item in articles:
        text = " ".join([item.get("title", ""), item.get("summary", ""), item.get("content", "")]).lower()
        matched = [kw for kw in keywords if kw in text]
        if matched:
            clusters[matched[0].title()].append(item)
        else:
            unmatched.append(item)

    if unmatched:
        top_terms = _top_terms(unmatched)
        if top_terms:
            for item in unmatched:
                text = " ".join([item.get("title", ""), item.get("summary", "")]).lower()
                term = next((candidate for candidate in top_terms if candidate in text), top_terms[0])
                clusters[term.title()].append(item)
        else:
            clusters["Aggiornamenti principali"].extend(unmatched)

    ranked = sorted(clusters.items(), key=lambda pair: len(pair[1]), reverse=True)
    return ranked[:6]


def _top_terms(articles: list[dict]) -> list[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "che",
        "del",
        "della",
        "degli",
        "delle",
        "con",
        "per",
        "una",
        "uno",
        "nel",
        "sul",
        "gli",
        "all",
        "are",
        "this",
        "that",
    }
    counter: Counter[str] = Counter()
    for item in articles:
        words = re.findall(r"[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9]{3,}", f"{item.get('title', '')} {item.get('summary', '')}".lower())
        counter.update(word for word in words if word not in stopwords)
    return [word for word, _ in counter.most_common(6)]


def _summary_sentence(grouped: list[dict]) -> str:
    if len(grouped) == 1:
        item = grouped[0]
        return item.get("summary") or item.get("title") or "Aggiornamento da monitorare."
    sources = sorted({item.get("source") for item in grouped if item.get("source")})
    source_text = ", ".join(sources[:3]) if sources else "fonti monitorate"
    return f"{len(grouped)} articoli collegati segnalano un tema comune nelle fonti: {source_text}."


def _attach_article_ids(payload: dict, articles: list[dict]) -> dict:
    by_url = {item.get("url"): item["id"] for item in articles}
    for topic in payload.get("topics", []):
        ids = []
        for link in topic.get("source_links", []):
            article_id = by_url.get(link.get("url"))
            if article_id:
                ids.append(article_id)
        topic["article_ids"] = ids
    return payload
