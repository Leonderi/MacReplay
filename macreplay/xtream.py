import json
import logging
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler

logger = logging.getLogger("MacReplay.xtream")


def normalize_base_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    url = url.rstrip("/")
    if url.endswith("player_api.php"):
        url = url.rsplit("/", 1)[0]
    return url


def _build_player_api_url(base_url, username, password, action=None, params=None):
    base = normalize_base_url(base_url)
    query = {"username": username or "", "password": password or ""}
    if action:
        query["action"] = action
    if params:
        query.update(params)
    return f"{base}/player_api.php?{urlencode(query)}"


def _request_json(url, proxy=None, timeout=20):
    handlers = []
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    opener = build_opener(*handlers) if handlers else build_opener()
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8", errors="ignore"))
    except Exception as exc:
        logger.warning("Xtream JSON parse failed: %s", exc)
        return None


def get_live_categories(base_url, username, password, proxy=None):
    url = _build_player_api_url(base_url, username, password, action="get_live_categories")
    payload = _request_json(url, proxy=proxy)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("categories") or payload.get("category") or payload.get("data") or []
    return []


def get_live_streams(base_url, username, password, proxy=None):
    url = _build_player_api_url(base_url, username, password, action="get_live_streams")
    payload = _request_json(url, proxy=proxy)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("streams") or payload.get("data") or []
    return []


def build_stream_url(base_url, username, password, stream_id, ext="m3u8"):
    base = normalize_base_url(base_url)
    sid = str(stream_id).strip()
    if not sid:
        return ""
    if ext:
        return f"{base}/live/{username}/{password}/{sid}.{ext}"
    return f"{base}/live/{username}/{password}/{sid}"


def get_simple_epg_map(base_url, username, password, stream_ids, proxy=None):
    epg_map = {}
    base = normalize_base_url(base_url)
    for stream_id in stream_ids:
        sid = str(stream_id)
        if not sid:
            continue
        url = _build_player_api_url(
            base,
            username,
            password,
            action="get_simple_data_table",
            params={"stream_id": sid},
        )
        payload = _request_json(url, proxy=proxy)
        if not payload or not isinstance(payload, dict):
            continue
        listings = payload.get("epg_listings") or payload.get("listings") or []
        if not isinstance(listings, list):
            continue
        programmes = []
        for item in listings:
            if not isinstance(item, dict):
                continue
            start_ts = item.get("start_timestamp") or item.get("start") or item.get("start_time")
            stop_ts = item.get("stop_timestamp") or item.get("end") or item.get("end_time")
            if start_ts is None or stop_ts is None:
                continue
            programmes.append(
                {
                    "start_timestamp": start_ts,
                    "stop_timestamp": stop_ts,
                    "name": item.get("title") or item.get("name") or "",
                    "descr": item.get("description") or item.get("desc") or "",
                }
            )
        if programmes:
            epg_map[sid] = programmes
    return epg_map
