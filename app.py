import os
import requests
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

def _require_api_key() -> str:
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Missing YOUTUBE_API_KEY env var.")
    return key

def _yt_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    key = _require_api_key()
    params = {**params, "key": key}
    r = requests.get(f"{YOUTUBE_API_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()

mcp = FastMCP(
    name="YouTube MCP Server",
    instructions="Search YouTube, fetch video stats, and fetch comments using YouTube Data API v3."
)

@mcp.tool()
def youtube_search(
    query: str,
    max_results: int = 5,
    order: str = "relevance",
    published_after: Optional[str] = None,
) -> Dict[str, Any]:
    max_results = max(1, min(int(max_results), 50))
    params: Dict[str, Any] = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max_results,
        "order": order,
    }
    if published_after:
        params["publishedAfter"] = published_after

    data = _yt_get("/search", params)

    results = []
    for it in data.get("items", []):
        vid = it.get("id", {}).get("videoId")
        sn = it.get("snippet", {})
        results.append({
            "videoId": vid,
            "title": sn.get("title"),
            "channelTitle": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "thumbnail": (sn.get("thumbnails", {}).get("high", {}) or sn.get("thumbnails", {}).get("default", {})).get("url"),
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        })
    return {"results": results}

@mcp.tool()
def youtube_video_stats(video_ids: List[str]) -> Dict[str, Any]:
    ids = ",".join([v for v in video_ids if v])
    data = _yt_get("/videos", {"part": "snippet,statistics", "id": ids})

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

@mcp.tool()
def youtube_comments(video_id: str, max_results: int = 20, order: str = "relevance") -> Dict[str, Any]:
    max_results = max(1, min(int(max_results), 100))
    data = _yt_get("/commentThreads", {
        "part": "snippet",
        "videoId": video_id,
        "maxResults": max_results,
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

if __name__ == "__main__":
    # Render provides PORT automatically
    port = int(os.environ.get("PORT", "8000"))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
