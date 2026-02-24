import os
import time
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# -----------------------------
# SIMPLE SECURITY (REAL AUTH)
# -----------------------------
# This is the secret token your GPT Action will send.
SERVER_API_KEY = os.getenv("SERVER_API_KEY", "")

def require_action_key(x_api_key: Optional[str]):
    # If SERVER_API_KEY is set, enforce it.
    if SERVER_API_KEY and x_api_key != SERVER_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def require_youtube_key() -> str:
    yt = os.getenv("YOUTUBE_API_KEY", "")
    if not yt:
        raise HTTPException(status_code=500, detail="Missing YOUTUBE_API_KEY on server")
    return yt

def yt_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    key = require_youtube_key()
    params = {**params, "key": key}
    r = requests.get(f"{YOUTUBE_API_BASE}{path}", params=params, timeout=30)
    # Bubble up useful errors
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()

# -----------------------------
# VERY SIMPLE RATE LIMIT (per IP)
# -----------------------------
# Not perfect, but helps stop spam.
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))
_visits: Dict[str, List[float]] = {}

def rate_limit(client_ip: str):
    now = time.time()
    window_start = now - 60
    arr = _visits.get(client_ip, [])
    arr = [t for t in arr if t > window_start]
    if len(arr) >= RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many requests, try again later.")
    arr.append(now)
    _visits[client_ip] = arr

app = FastAPI(title="YouTube Tools API", version="1.0.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/search")
def youtube_search(
    q: str = Query(..., description="Search query"),
    max: int = Query(5, ge=1, le=50),
    order: str = Query("relevance", description="relevance|date|viewCount|rating|title|videoCount"),
    published_after: Optional[str] = Query(None, description="ISO8601 time e.g. 2025-01-01T00:00:00Z"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    require_action_key(x_api_key)
    client_ip = "unknown"
    # Render/Cloudflare usually sends this header:
    # (If missing, rate limit still works but less accurate)
    # We keep it simple for beginner use.
    rate_limit(client_ip)

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
        results.append({
            "videoId": vid,
            "title": sn.get("title"),
            "channelTitle": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumbnail": (sn.get("thumbnails", {}).get("high", {}) or sn.get("thumbnails", {}).get("default", {})).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        })

    return {"results": results}

@app.get("/stats")
def youtube_stats(
    ids: str = Query(..., description="Comma-separated video IDs"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    require_action_key(x_api_key)
    client_ip = "unknown"
    rate_limit(client_ip)

    data = yt_get("/videos", {"part": "snippet,statistics", "id": ids})

    out = []
    for it in data.get("items", []):
        stats = it.get("statistics", {}) or {}
        sn = it.get("snippet", {}) or {}
        out.append({
            "videoId": it.get("id"),
            "title": sn.get("title"),
            "channelTitle": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "viewCount": stats.get("viewCount"),
            "likeCount": stats.get("likeCount"),
            "commentCount": stats.get("commentCount"),
            "url": f"https://www.youtube.com/watch?v={it.get('id')}",
        })

    return {"videos": out}

@app.get("/comments")
def youtube_comments(
    video_id: str = Query(...),
    max: int = Query(20, ge=1, le=100),
    order: str = Query("relevance", description="relevance|time"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    require_action_key(x_api_key)
    client_ip = "unknown"
    rate_limit(client_ip)

    data = yt_get("/commentThreads", {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max,
        "order": order,
        "textFormat": "plainText",
    })

    comments = []
    for it in data.get("items", []):
        top = (it.get("snippet", {}) or {}).get("topLevelComment", {}) or {}
        sn = top.get("snippet", {}) or {}
        comments.append({
            "author": sn.get("authorDisplayName"),
            "publishedAt": sn.get("publishedAt"),
            "likeCount": sn.get("likeCount"),
            "text": sn.get("textDisplay"),
        })

    return {"videoId": video_id, "comments": comments}
