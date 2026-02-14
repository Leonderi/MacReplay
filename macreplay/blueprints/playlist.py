import base64
import json
import re
import unicodedata
from urllib.parse import quote, urlparse

from flask import Blueprint, Response, request

from ..security import authorise_m3u


def create_playlist_blueprint(
    *,
    logger,
    host,
    getPortals,
    getSettings,
    get_db_connection,
    ACTIVE_GROUP_CONDITION,
    effective_display_name,
    effective_epg_name,
    get_cached_playlist,
    set_cached_playlist,
    get_last_playlist_host,
    set_last_playlist_host,
):
    bp = Blueprint("playlist", __name__)

    def _normalize_host(value):
        if not value:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        if "//" in text:
            try:
                parsed = urlparse(text)
                if parsed.netloc:
                    return parsed.netloc
            except Exception:
                pass
        return text

    def _determine_base_host():
        forwarded_proto = request.headers.get("X-Forwarded-Proto")
        forwarded_host = request.headers.get("X-Forwarded-Host")
        forwarded_port = request.headers.get("X-Forwarded-Port")
        if forwarded_host:
            if forwarded_port and ":" not in forwarded_host:
                return f"{forwarded_host}:{forwarded_port}", forwarded_proto or request.scheme
            return forwarded_host, forwarded_proto or request.scheme
        return request.host, request.scheme

    def _normalize_alias(value):
        if not value:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"[^a-z0-9]", "", text)
        return text

    def _normalize_country_code(value):
        if not value:
            return ""
        text = str(value).strip().upper()
        text = re.sub(r"[^A-Z]", "", text)
        if not text:
            return ""
        return text[:2]

    def _normalize_quality(value):
        if not value:
            return ""
        text = str(value).strip().upper()
        return text

    def _clean_text(value):
        if value is None:
            return ""
        text = unicodedata.normalize("NFKC", str(value))
        # Remove control chars that often break M3U parsers.
        text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        text = re.sub(r"[\x00-\x1f\x7f]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _escape_m3u_attr(value):
        text = _clean_text(value)
        return (
            text.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _normalize_group_title(value):
        text = _clean_text(value)
        if not text:
            return "UNGROUPED"
        # Normalize separators so group names collapse consistently in clients.
        text = re.sub(r"\s*\|\s*", " | ", text)
        text = re.sub(r"\s*-\s*", " - ", text)
        text = re.sub(r"\s{2,}", " ", text).strip(" -|")
        return text or "UNGROUPED"

    def _is_hevc(value):
        if not value:
            return False
        text = str(value).lower()
        return "hevc" in text or "h265" in text

    def _format_display_name(fmt, *, name, country, portal_code, quality, hevc, event):
        prefix = " | ".join([p for p in [country, portal_code] if p])
        suffix_parts = []
        if quality:
            suffix_parts.append(quality)
        if hevc:
            suffix_parts.append("HEVC")
        if event:
            suffix_parts.append("EVENT")
        suffix = " | ".join([p for p in suffix_parts if p])
        mapping = {
            "prefix": prefix,
            "name": name,
            "suffix": suffix,
            "country": country,
            "portal_code": portal_code,
            "quality": quality,
            "hevc": "HEVC" if hevc else "",
            "event": "EVENT" if event else "",
        }
        try:
            formatted = str(fmt or "").format_map({**{k: "" for k in mapping}, **mapping})
        except Exception:
            formatted = f"{prefix} {name} {suffix}"
        formatted = re.sub(r"\(\s*\)", "", formatted)
        formatted = re.sub(r"\s{2,}", " ", formatted).strip()
        formatted = re.sub(r"\(\s+", "(", formatted)
        formatted = re.sub(r"\s+\)", ")", formatted)
        return formatted

    def _encode_group_token(name_key, quality, is_hevc, is_raw):
        payload = {
            "n": str(name_key or "").strip().lower(),
            "q": str(quality or "").strip().upper(),
            "h": 1 if is_hevc else 0,
            "r": 1 if is_raw else 0,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def generate_playlist(base_host, scheme):
        logger.info("Generating playlist.m3u from database...")

        channels = []
        seen_groups = set()

        conn = get_db_connection()
        cursor = conn.cursor()
        portals = getPortals() or {}

        settings = getSettings()
        include_per_portal = bool(settings.get("playlist export per portal channels", True))
        include_grouped = bool(settings.get("playlist export grouped channels", False))
        if not include_per_portal and not include_grouped:
            include_per_portal = True

        order_clause = ""
        if settings.get("sort playlist by channel name", True):
            order_clause = (
                "ORDER BY COALESCE(NULLIF(c.custom_name, ''), NULLIF(c.auto_name, ''), c.name)"
            )
        elif settings.get("use channel numbers", True):
            if settings.get("sort playlist by channel number", False):
                order_clause = (
                    "ORDER BY CAST(COALESCE(NULLIF(c.custom_number, ''), c.number) AS INTEGER)"
                )
        elif settings.get("use channel genres", True):
            if settings.get("sort playlist by channel genre", False):
                order_clause = (
                    "ORDER BY COALESCE(NULLIF(c.custom_genre, ''), c.genre)"
                )

        cursor.execute(
            f"""
            SELECT
                c.portal_id as portal, c.channel_id, c.name, c.number, c.genre,
                c.custom_name, c.auto_name, c.matched_name, c.custom_number, c.custom_genre, c.custom_epg_id,
                c.is_event, c.is_raw, c.country, c.resolution, c.video_codec
            FROM channels c
            LEFT JOIN groups g ON c.portal_id = g.portal_id AND c.genre_id = g.genre_id
            WHERE c.enabled = 1 AND {ACTIVE_GROUP_CONDITION}
            {order_clause}
            """
        )
        rows = cursor.fetchall()
        normalized = []
        name_format = settings.get("playlist name format", "({prefix}) {name} ({suffix})")

        for row in rows:
            portal = row["portal"]
            channel_name = effective_display_name(
                row["custom_name"], row["matched_name"], row["auto_name"], row["name"]
            )
            channel_number = row["custom_number"] if row["custom_number"] else row["number"]
            channel_number = channel_number or ""
            genre = row["custom_genre"] if row["custom_genre"] else row["genre"]
            if row["is_event"] and not genre:
                genre = "EVENTS"
            epg_id = row["custom_epg_id"] if row["custom_epg_id"] else effective_epg_name(
                row["custom_name"], row["auto_name"], row["name"]
            )
            portal_data = portals.get(portal, {})
            portal_code = str(portal_data.get("portal code", "")).strip().upper() if portal_data else ""
            portal_code = re.sub(r"[^A-Z0-9]", "", portal_code)[:2]
            country_code = _normalize_country_code(row["country"])
            quality = _normalize_quality(row["resolution"])
            is_hevc = _is_hevc(row["video_codec"])
            is_event = bool(row["is_event"])
            is_raw = bool(row["is_raw"])
            display_name = _format_display_name(
                name_format,
                name=channel_name,
                country=country_code,
                portal_code=portal_code,
                quality=quality,
                hevc=is_hevc,
                event=is_event,
            )
            name_key = str(channel_name or "").strip().lower()
            group_key = None
            if row["matched_name"] and name_key:
                group_key = (name_key, quality, is_hevc, is_raw)
            normalized.append(
                {
                    "portal": portal,
                    "channel_id": row["channel_id"],
                    "channel_name": channel_name,
                    "channel_number": channel_number,
                    "group_title": _normalize_group_title(genre or ""),
                    "epg_id": epg_id,
                    "country_code": country_code,
                    "quality": quality,
                    "is_hevc": is_hevc,
                    "is_event": is_event,
                    "is_raw": is_raw,
                    "display_name": display_name,
                    "group_key": group_key,
                    "matched_name": row["matched_name"],
                }
            )

        grouped_candidates = {}
        for item in normalized:
            if item["group_key"] is not None:
                grouped_candidates.setdefault(item["group_key"], []).append(item)
        grouped_keys = {
            key for key, members in grouped_candidates.items() if len(members) > 1
        }

        def append_playlist_entry(item, stream_url):
            group_title = item["group_title"]
            if group_title not in seen_groups:
                seen_groups.add(group_title)
                dummy_name = _clean_text(f"::: {group_title} :::")
                dummy_entry = (
                    "#EXTINF:-1"
                    + ' tvg-id="'
                    + _escape_m3u_attr(f"dummy:{group_title}")
                    + '"'
                    + ' tvg-name="'
                    + _escape_m3u_attr(dummy_name)
                    + '"'
                    + ' group-title="'
                    + _escape_m3u_attr(group_title)
                    + '",'
                    + dummy_name
                )
                dummy_url = (
                    f"{scheme}://{base_host}/playlist_dummy.m3u8"
                    f"?group={quote(group_title, safe='')}"
                )
                channels.append(dummy_entry)
                channels.append(dummy_url)

            tvg_id = item["display_name"] if item["is_event"] else item["epg_id"]
            title_text = _clean_text(f"{item['channel_number']} {item['display_name']}".strip())
            channel_entry = (
                "#EXTINF:-1"
                + ' tvg-id="'
                + _escape_m3u_attr(tvg_id)
                + '"'
                + ' tvg-name="'
                + _escape_m3u_attr(item["display_name"])
                + '"'
                + ' group-title="'
                + _escape_m3u_attr(group_title)
                + '",'
                + title_text
            )
            channels.append(channel_entry)
            if item["is_event"]:
                channels.append(f"#EXTGRP:{group_title or 'EVENTS'}")
            channels.append(stream_url)

        if include_grouped:
            for key in grouped_keys:
                members = grouped_candidates.get(key, [])
                if not members:
                    continue
                representative = members[0]
                any_event = any(m["is_event"] for m in members)
                group_channel_number = next((m["channel_number"] for m in members if m["channel_number"]), "")
                group_epg_id = next((m["epg_id"] for m in members if m["epg_id"]), "")
                group_title = representative["group_title"]
                grouped_display_name = _format_display_name(
                    name_format,
                    name=representative["channel_name"],
                    country=representative["country_code"],
                    portal_code="",
                    quality=representative["quality"],
                    hevc=representative["is_hevc"],
                    event=any_event,
                )
                group_token = _encode_group_token(
                    key[0], representative["quality"], representative["is_hevc"], representative["is_raw"]
                )
                item = {
                    "channel_number": group_channel_number,
                    "display_name": grouped_display_name,
                    "is_event": any_event,
                    "epg_id": group_epg_id,
                    "group_title": group_title,
                }
                stream_url = f"{scheme}://{base_host}/play_group/{group_token}?web=true"
                append_playlist_entry(item, stream_url)

        if include_per_portal:
            for item in normalized:
                stream_url = f"{scheme}://{base_host}/play/{item['portal']}/{item['channel_id']}?web=true"
                append_playlist_entry(item, stream_url)
        else:
            for item in normalized:
                if item["group_key"] in grouped_keys:
                    continue
                stream_url = f"{scheme}://{base_host}/play/{item['portal']}/{item['channel_id']}?web=true"
                append_playlist_entry(item, stream_url)

        conn.close()

        playlist_content = "#EXTM3U\n" + "\n".join(channels)
        return playlist_content

    @bp.route("/playlist.m3u", methods=["GET"])
    @authorise_m3u
    def playlist():
        logger.info("Playlist Requested")

        base_host, scheme = _determine_base_host()
        current_host = _normalize_host(base_host) or host
        cache_key = f"{scheme}://{current_host}"
        cached_playlist = get_cached_playlist() or {}

        logger.info(
            "Regenerating playlist for request host: %s",
            current_host,
        )
        set_last_playlist_host(current_host)
        playlist_content = generate_playlist(current_host, scheme)
        cached_playlist[cache_key] = playlist_content
        set_cached_playlist(cached_playlist)

        return Response(playlist_content, mimetype="text/plain")

    @bp.route("/playlist_plus.m3u", methods=["GET"])
    @authorise_m3u
    def playlist_plus():
        base_host, scheme = _determine_base_host()
        current_host = _normalize_host(base_host) or host
        playlist_content = generate_playlist(current_host, scheme)
        return Response(playlist_content, mimetype="text/plain")

    @bp.route("/playlist_dispatcharr.m3u", methods=["GET"])
    def playlist_dispatcharr_removed():
        return Response("Removed. Use /playlist.m3u or /playlist_plus.m3u", status=404)

    @bp.route("/playlist_dummy.m3u8", methods=["GET"])
    def playlist_dummy():
        # Keepalive endpoint for synthetic per-group channels in M3U imports.
        return Response(status=204)

    @bp.route("/update_playlistm3u", methods=["POST"])
    def update_playlistm3u():
        base_host, scheme = _determine_base_host()
        current_host = _normalize_host(base_host) or host
        cache_key = f"{scheme}://{current_host}"
        playlist_content = generate_playlist(current_host, scheme)
        cached_playlist = get_cached_playlist() or {}
        cached_playlist[cache_key] = playlist_content
        set_cached_playlist(cached_playlist)
        return Response("Playlist updated successfully", status=200)

    return bp
