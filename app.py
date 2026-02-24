import os
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Query

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Secret used by your GPT Action (set on Render as SERVER_API_KEY)
SERVER_API_KEY = os.getenv("SERVER_API_KEY", "")

# YouTube Data API key (set on Render as YOUTUBE_API_KEY)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Simple rate limit (set on Render as RATE_LIMIT_PER_MIN, optional)
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
_visits: Dict[str, List[float]] = {}


def require_youtube_key() -> str:
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="Missing YOUTUBE_API_KEY on server")
    return YOUTUBE_API_KEY


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def require_action_key(x_api_key: Optional[str], authorization: Optional[str]) -> None:
    """
    Accept either:
      - X-API-Key: <SERVER_API_KEY>
      - Authorization: Bearer <SERVER_API_KEY>
    """
    bearer = extract_bearer_token(authorization)
    provided = x_api_key or bearer

    # If you didn't set SERVER_API_KEY, then anyone can use it (not recommended)
    if SERVER_API_KEY and provided != SERVER_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def rate_limit(client_id: str) -> None:
    now = time.time()
    window_start = now - 60
    arr = _visits.get(client_id, [])
    arr = [t for t in arr if t > window_start]
    if len(arr) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
    arr.append(now)
    _visits[client_id] = arr


def yt_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    key = require_youtube_key()
    params = {**params, "key": key}
    r = requests.get(f"{YOUTUBE_API_BASE}{path}", params=params, timeout=30)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


app = FastAPI(title="YouTube Tools API", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/search")
def youtube_search(
    q: str = Query(..., description="Search query"),
    max: int = Query(5, ge=1, le=50),
    order: str = Query("relevance", description="relevance|date|viewCount|rating|title|videoCount"),
    published_after: Optional[str] = Query(None, description="ISO8601 e.g. 2026-02-24T00:00:00Z"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    require_action_key(x_api_key, authorization)
    rate_limit("global")  # simple for now

    params: Dict[str, Any] = {
        "part": "snippet",
        "type": "video",
        "q": q,
        "maxResults": max,
        "order": order,
    }
    if published_after:
        params["publishedAfter"] = published_after

    data = yt_get("/search", params)

    results = []
    for it in data.get("items", []):
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {}) or {}
        thumbs = sn.get("thumbnails", {}) or {}
        thumb_url = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")

        results.append(
            {
                "videoId": vid,
                "title": sn.get("title"),
                "channelTitle": sn.get("channelTitle"),
                "publishedAt": sn.get("publishedAt"),
                "thumbnail": thumb_url,
                "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
            }
        )

    return {"results": results}


@app.get("/stats")
def youtube_stats(
    ids: str = Query(..., description="Comma-separated video IDs"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    require_action_key(x_api_key, authorization)
    rate_limit("global")

    data = yt_get("/videos", {"part": "snippet,statistics", "id": ids})

    out = []
    for it in data.get("items", []):
        stats = it.get("statistics", {}) or {}
        sn = it.get("snippet", {}) or {}
        vid = it.get("id")

        out.append(
            {
                "videoId": vid,
                "title": sn.get("title"),
                "channelTitle": sn.get("channelTitle"),
                "publishedAt": sn.get("publishedAt"),
                "viewCount": stats.get("viewCount"),
                "likeCount": stats.get("likeCount"),
                "commentCount": stats.get("commentCount"),
                "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
            }
        )

    return {"videos": out}


@app.get("/comments")
def youtube_comments(
    video_id: str = Query(...),
    max: int = Query(20, ge=1, le=100),
    order: str = Query("relevance", description="relevance|time"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    require_action_key(x_api_key, authorization)
    rate_limit("global")

    data = yt_get(
        "/commentThreads",
        {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": max,
            "order": order,
            "textFormat": "plainText",
        },
    )

    comments = []
    for it in data.get("items", []):
        top = (it.get("snippet", {}) or {}).get("topLevelComment", {}) or {}
        sn = top.get("snippet", {}) or {}
        comments.append(
            {
                "author": sn.get("authorDisplayName"),
                "publishedAt": sn.get("publishedAt"),
                "likeCount": sn.get("likeCount"),
                "text": sn.get("textDisplay"),
            }
        )

    return {"videoId": video_id, "comments": comments}
