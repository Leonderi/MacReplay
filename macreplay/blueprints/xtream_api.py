import hashlib
import re
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, redirect, request

from ..security import validate_xc_credentials


def create_xtream_api_blueprint(
    *,
    logger,
    getSettings,
    get_db_connection,
    ACTIVE_GROUP_CONDITION,
):
    bp = Blueprint("xtream_api", __name__)

    def _credentials_valid(username, password):
        return validate_xc_credentials(username, password)

    def _unauthorized_player_api():
        return jsonify(
            {
                "user_info": {
                    "auth": 0,
                    "status": "Disabled",
                    "message": "Invalid credentials",
                },
                "server_info": {},
            }
        )

    def _normalize_group(value):
        text = (value or "").strip()
        if not text:
            return "Default Group"
        text = re.sub(r"\s*\|\s*", " | ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        return text or "Default Group"

    def _stable_stream_id(portal_id, channel_id):
        digest = hashlib.sha1(f"{portal_id}:{channel_id}".encode("utf-8")).hexdigest()
        # Keep it positive and short enough for common Xtream clients.
        return int(digest[:12], 16)

    def _build_channels():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT
                c.portal_id,
                c.channel_id,
                c.name,
                c.number,
                c.genre,
                c.custom_name,
                c.auto_name,
                c.matched_name,
                c.custom_number,
                c.custom_genre,
                c.custom_epg_id,
                c.logo,
                c.is_event,
                c.country,
                c.resolution,
                c.video_codec
            FROM channels c
            LEFT JOIN groups g ON c.portal_id = g.portal_id AND c.genre_id = g.genre_id
            WHERE c.enabled = 1 AND {ACTIVE_GROUP_CONDITION}
            ORDER BY CAST(COALESCE(NULLIF(c.custom_number, ''), c.number) AS INTEGER),
                     COALESCE(NULLIF(c.custom_name, ''), NULLIF(c.auto_name, ''), c.name)
            """
        )
        rows = cursor.fetchall()
        conn.close()

        channels = []
        by_stream_id = {}
        category_name_to_id = {}
        categories = {}
        next_cat_id = 1

        for row in rows:
            display_name = (
                row["custom_name"]
                or row["matched_name"]
                or row["auto_name"]
                or row["name"]
                or ""
            ).strip()
            group_name = _normalize_group(row["custom_genre"] or row["genre"] or "")

            if group_name not in category_name_to_id:
                category_name_to_id[group_name] = str(next_cat_id)
                categories[str(next_cat_id)] = group_name
                next_cat_id += 1
            category_id = category_name_to_id[group_name]

            stream_id = _stable_stream_id(row["portal_id"], row["channel_id"])
            while str(stream_id) in by_stream_id:
                stream_id += 1
            stream_id = str(stream_id)

            epg_id = (row["custom_epg_id"] or display_name).strip()
            logo = (row["logo"] or "").strip()

            item = {
                "stream_id": stream_id,
                "portal_id": row["portal_id"],
                "channel_id": row["channel_id"],
                "name": display_name,
                "category_id": category_id,
                "category_name": group_name,
                "epg_channel_id": epg_id,
                "stream_icon": logo,
                "num": str((row["custom_number"] or row["number"] or "")).strip(),
                "is_event": bool(row["is_event"]),
                "country": (row["country"] or "").strip(),
                "resolution": (row["resolution"] or "").strip(),
                "video_codec": (row["video_codec"] or "").strip(),
            }
            channels.append(item)
            by_stream_id[stream_id] = item

        return channels, by_stream_id, categories

    def _base_server_info():
        parsed = urlparse(request.host_url)
        scheme = parsed.scheme or request.scheme
        host = parsed.hostname or request.host.split(":")[0]
        port = parsed.port
        default_port = 443 if scheme == "https" else 80
        if port is None:
            port = default_port
        return {
            "url": host,
            "port": str(port),
            "https_port": "443",
            "server_protocol": scheme,
            "timezone": "UTC",
            "timestamp_now": "",
            "time_now": "",
        }

    @bp.route("/player_api.php", methods=["GET"])
    def xtream_player_api():
        username = request.args.get("username", "").strip()
        password = request.args.get("password", "").strip()
        if not _credentials_valid(username, password):
            return _unauthorized_player_api(), 401

        action = (request.args.get("action") or "").strip().lower()
        channels, by_stream_id, categories = _build_channels()

        if action == "get_live_categories":
            payload = [
                {"category_id": category_id, "category_name": category_name, "parent_id": 0}
                for category_id, category_name in categories.items()
            ]
            return jsonify(payload)

        if action == "get_live_streams":
            payload = []
            for item in channels:
                payload.append(
                    {
                        "num": item["num"],
                        "name": item["name"],
                        "stream_type": "live",
                        "stream_id": int(item["stream_id"]),
                        "stream_icon": item["stream_icon"],
                        "epg_channel_id": item["epg_channel_id"],
                        "added": "0",
                        "is_adult": "0",
                        "category_id": item["category_id"],
                        "category_ids": [int(item["category_id"])],
                        "custom_sid": "",
                        "tv_archive": 0,
                        "direct_source": "",
                    }
                )
            return jsonify(payload)

        if action == "get_live_info":
            stream_id = str(request.args.get("stream_id", "")).strip()
            item = by_stream_id.get(stream_id)
            if not item:
                return jsonify({"info": {}, "movie_data": {}}), 404
            return jsonify(
                {
                    "info": {
                        "name": item["name"],
                        "stream_icon": item["stream_icon"],
                        "category_id": item["category_id"],
                    },
                    "movie_data": {
                        "stream_id": int(item["stream_id"]),
                        "name": item["name"],
                        "container_extension": "ts",
                    },
                }
            )

        # Default Xtream response (no action): user/server info.
        return jsonify(
            {
                "user_info": {
                    "username": username,
                    "password": password,
                    "auth": 1,
                    "status": "Active",
                    "is_trial": "0",
                    "active_cons": "0",
                    "max_connections": "1",
                    "allowed_output_formats": ["ts", "m3u8"],
                },
                "server_info": _base_server_info(),
            }
        )

    @bp.route("/get.php", methods=["GET"])
    def xtream_get():
        username = request.args.get("username", "").strip()
        password = request.args.get("password", "").strip()
        if not _credentials_valid(username, password):
            return Response("Unauthorized", status=401, mimetype="text/plain")

        req_type = (request.args.get("type") or "m3u_plus").strip().lower()
        if req_type not in {"m3u", "m3u_plus"}:
            return Response("Unsupported type", status=400, mimetype="text/plain")

        channels, _, _ = _build_channels()
        lines = ["#EXTM3U"]
        base = request.host_url.rstrip("/")
        for item in channels:
            tvg_name = item["name"].replace('"', "'")
            group_name = item["category_name"].replace('"', "'")
            epg_id = item["epg_channel_id"].replace('"', "'")
            stream_url = f"{base}/live/{username}/{password}/{item['stream_id']}.ts"
            lines.append(
                f'#EXTINF:-1 tvg-id="{epg_id}" tvg-name="{tvg_name}" group-title="{group_name}",{tvg_name}'
            )
            lines.append(stream_url)
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    @bp.route("/live/<username>/<password>/<stream_path>", methods=["GET"])
    def xtream_live(username, password, stream_path):
        if not _credentials_valid(username, password):
            return Response("Unauthorized", status=401, mimetype="text/plain")

        stream_token = stream_path.rsplit(".", 1)[0].strip()
        if not stream_token:
            return Response("Stream not found", status=404, mimetype="text/plain")

        _, by_stream_id, _ = _build_channels()
        item = by_stream_id.get(stream_token)
        if not item:
            logger.warning("Xtream live request with unknown stream_id: %s", stream_token)
            return Response("Stream not found", status=404, mimetype="text/plain")

        return redirect(f"/play/{item['portal_id']}/{item['channel_id']}")

    return bp
