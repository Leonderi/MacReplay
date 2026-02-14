import os
import sqlite3
import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import flask
from flask import Blueprint, Response, jsonify, redirect, render_template, request

from ..config import DATA_DIR
from ..security import authorise


def create_misc_blueprint(
    *,
    LOG_DIR,
    occupied,
    get_db_connection=None,
    getPortals=None,
    getSettings=None,
    recent_stream_history=None,
    recent_failed_macs=None,
    refresh_custom_sources=None,
    get_epg_source_status=None,
):
    bp = Blueprint("misc", __name__)

    @bp.route("/api/dashboard")
    @authorise
    def dashboard():
        """Legacy template route"""
        return render_template("dashboard.html")

    @bp.route("/streaming")
    @authorise
    def streaming():
        return flask.jsonify(occupied)

    @bp.route("/api/dashboard/stats")
    @authorise
    def dashboard_stats():
        stats = {
            "portals_total": 0,
            "portals_enabled": 0,
            "stalker_portals": 0,
            "xtream_portals": 0,
            "channels_total": 0,
            "channels_enabled": 0,
            "event_channels_enabled": 0,
            "groups_total": 0,
            "groups_active": 0,
            "active_streams": 0,
            "active_clients": 0,
            "last_epg_refresh": None,
            "macs_expired": 0,
            "macs_expiring_7d": 0,
            "macs_expiring_30d": 0,
            "xtream_logins_expiring_7d": 0,
            "xtream_logins_expiring_30d": 0,
            "recent_channels": [],
            "top_portals_active": [],
            "top_failed_macs": [],
            "top_mac_durations": [],
            "top_reliable_channels": [],
            "status_epg": "unknown",
            "status_streaming": "ok",
        }

        def _parse_dt(value):
            if not value:
                return None
            text = str(value).strip()
            if not text or text.lower() in {"unknown", "none", "-"}:
                return None
            text = text.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
            # Common portal date formats used in UI/cards.
            for fmt in (
                "%B %d, %Y, %I:%M %p",
                "%B %d, %Y, %I:%M:%S %p",
                "%b %d, %Y, %I:%M %p",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
            ):
                try:
                    dt = datetime.strptime(text, fmt)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
            try:
                dt = parsedate_to_datetime(text)
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt:
                    return dt.astimezone(timezone.utc)
            except Exception:
                pass
            return None

        try:
            portals = getPortals() if callable(getPortals) else {}
            stats["portals_total"] = len(portals)
            stats["portals_enabled"] = sum(
                1 for p in portals.values() if str(p.get("enabled", "true")).lower() == "true"
            )
            stats["stalker_portals"] = sum(
                1 for p in portals.values() if (p.get("type", "stalker") or "stalker") == "stalker"
            )
            stats["xtream_portals"] = sum(
                1 for p in portals.values() if (p.get("type", "stalker") or "stalker") == "xtream"
            )

            now = datetime.now(timezone.utc)
            for portal in portals.values():
                portal_type = (portal.get("type", "stalker") or "stalker")
                if portal_type == "stalker":
                    macs = portal.get("macs", {}) or {}
                    for mac_data in macs.values():
                        expiry = (
                            mac_data.get("expiry") if isinstance(mac_data, dict) else mac_data
                        )
                        dt = _parse_dt(expiry)
                        if not dt:
                            continue
                        days_left = (dt.date() - now.date()).days
                        if days_left < 0:
                            stats["macs_expired"] += 1
                        elif days_left <= 7:
                            stats["macs_expiring_7d"] += 1
                            stats["macs_expiring_30d"] += 1
                        elif days_left <= 30:
                            stats["macs_expiring_30d"] += 1
                elif portal_type == "xtream":
                    for login in portal.get("xtream logins", []) or []:
                        days_left = login.get("days_left")
                        if days_left is None:
                            dt = _parse_dt(login.get("expires_iso"))
                            if not dt:
                                continue
                            days_left = (dt.date() - now.date()).days
                        try:
                            days_left = int(days_left)
                        except Exception:
                            continue
                        if days_left <= 7:
                            stats["xtream_logins_expiring_7d"] += 1
                            stats["xtream_logins_expiring_30d"] += 1
                        elif days_left <= 30:
                            stats["xtream_logins_expiring_30d"] += 1
        except Exception:
            pass

        try:
            active_streams = 0
            active_clients = set()
            recent = []
            for streams in occupied.values():
                active_streams += len(streams)
                for stream in streams:
                    client = stream.get("client")
                    if client:
                        active_clients.add(client)
                    portal_name = stream.get("portal name", "-")
                    recent.append(
                        {
                            "portal_name": portal_name,
                            "channel_name": stream.get("channel name", "-"),
                            "source_portal_name": stream.get("source portal name", ""),
                            "source_channel_name": stream.get("source channel name", ""),
                            "client": stream.get("client", "-"),
                            "start_time": stream.get("start time", 0),
                        }
                    )
            stats["active_streams"] = active_streams
            stats["active_clients"] = len(active_clients)
            stats["recent_channels"] = sorted(
                recent, key=lambda x: int(x.get("start_time") or 0), reverse=True
            )[:8]
        except Exception:
            pass

        if callable(get_db_connection):
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                now_ts = int(datetime.now(timezone.utc).timestamp())
                since_24h = now_ts - 86400
                stats["channels_total"] = cursor.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
                stats["channels_enabled"] = cursor.execute(
                    "SELECT COUNT(*) FROM channels WHERE enabled = 1"
                ).fetchone()[0]
                stats["event_channels_enabled"] = cursor.execute(
                    "SELECT COUNT(*) FROM channels WHERE enabled = 1 AND is_event = 1"
                ).fetchone()[0]
                stats["groups_total"] = cursor.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
                stats["groups_active"] = cursor.execute(
                    "SELECT COUNT(*) FROM groups WHERE active = 1"
                ).fetchone()[0]
                stats["last_epg_refresh"] = cursor.execute(
                    "SELECT MAX(last_refresh) FROM epg_sources"
                ).fetchone()[0]
                top_portals_rows = cursor.execute(
                    """
                    SELECT portal_name, COUNT(*) AS cnt
                    FROM stream_sessions
                    WHERE started_at >= ?
                    GROUP BY portal_name
                    ORDER BY cnt DESC
                    LIMIT 6
                    """,
                    [since_24h],
                ).fetchall()
                stats["top_portals_active"] = [
                    {"portal_name": row["portal_name"] or "-", "count": int(row["cnt"] or 0)}
                    for row in top_portals_rows
                ]

                top_mac_rows = cursor.execute(
                    """
                    SELECT
                        mac,
                        COUNT(*) AS streams,
                        SUM(COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at))) AS total_duration,
                        AVG(COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at))) AS avg_duration,
                        MAX(COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at))) AS max_duration
                    FROM stream_sessions
                    WHERE started_at >= ?
                      AND mac IS NOT NULL
                      AND TRIM(mac) <> ''
                    GROUP BY mac
                    ORDER BY total_duration DESC
                    LIMIT 6
                    """,
                    [since_24h],
                ).fetchall()
                stats["top_mac_durations"] = [
                    {
                        "mac": row["mac"],
                        "streams": int(row["streams"] or 0),
                        "total_duration": int(row["total_duration"] or 0),
                        "avg_duration": int(row["avg_duration"] or 0),
                        "max_duration": int(row["max_duration"] or 0),
                    }
                    for row in top_mac_rows
                ]

                top_failed_rows = cursor.execute(
                    """
                    SELECT portal_name, mac, COUNT(*) AS cnt
                    FROM mac_failures
                    WHERE failed_at >= ?
                    GROUP BY portal_name, mac
                    ORDER BY cnt DESC
                    LIMIT 6
                    """,
                    [since_24h],
                ).fetchall()
                stats["top_failed_macs"] = [
                    {
                        "label": f"{(row['portal_name'] or '-')} - {(row['mac'] or '-')}",
                        "count": int(row["cnt"] or 0),
                    }
                    for row in top_failed_rows
                ]

                success_min_seconds = 45
                try:
                    success_min_seconds = int(
                        (getSettings() if callable(getSettings) else {}).get(
                            "stream success min seconds", 45
                        )
                        or 45
                    )
                except Exception:
                    success_min_seconds = 45
                success_min_seconds = max(5, min(600, success_min_seconds))

                reliability_rows = cursor.execute(
                    """
                    SELECT
                        ss.portal_name,
                        ss.channel_name,
                        COUNT(*) AS starts,
                        SUM(
                            CASE
                                WHEN COALESCE(
                                    ss.duration_sec,
                                    MAX(0, strftime('%s','now') - ss.started_at)
                                ) >= ? THEN 1 ELSE 0
                            END
                        ) AS successes
                    FROM stream_sessions ss
                    WHERE ss.started_at >= ?
                    GROUP BY ss.portal_name, ss.channel_name
                    HAVING COUNT(*) >= 2
                    ORDER BY (CAST(successes AS REAL) / CAST(starts AS REAL)) DESC, starts DESC
                    LIMIT 20
                    """,
                    [success_min_seconds, since_24h],
                ).fetchall()

                reliable = []
                for row in reliability_rows:
                    starts = int(row["starts"] or 0)
                    successes = int(row["successes"] or 0)
                    if starts <= 0:
                        continue
                    ratio = successes / starts
                    reliable.append(
                        {
                            "portal_name": row["portal_name"] or "-",
                            "channel_name": row["channel_name"] or "-",
                            "starts": starts,
                            "successes": successes,
                            "ratio": ratio,
                        }
                    )
                reliable.sort(key=lambda item: (item["ratio"], item["starts"]), reverse=True)
                stats["top_reliable_channels"] = reliable[:6]
            except Exception:
                # Fallback for pre-migration runtimes: keep volatile in-memory failed MAC ranking.
                try:
                    failed_counts = {}
                    for item in list(recent_failed_macs or []):
                        ts = int(item.get("timestamp") or 0)
                        if ts <= 0 or (now_ts - ts) > 86400:
                            continue
                        portal_name = item.get("portal_name", "-")
                        mac = item.get("mac", "-")
                        key = f"{portal_name} - {mac}"
                        failed_counts[key] = failed_counts.get(key, 0) + 1
                    stats["top_failed_macs"] = [
                        {"label": label, "count": count}
                        for label, count in sorted(
                            failed_counts.items(), key=lambda x: x[1], reverse=True
                        )[:6]
                    ]
                except Exception:
                    pass
            finally:
                if conn is not None:
                    conn.close()

        try:
            settings = getSettings() if callable(getSettings) else {}
            refresh_hours = float(settings.get("epg update", 2) or 2)
            refresh_hours = max(0.25, refresh_hours)
            last_refresh_dt = _parse_dt(stats["last_epg_refresh"])
            if last_refresh_dt is None:
                stats["status_epg"] = "unknown"
            else:
                age_hours = (datetime.now(timezone.utc) - last_refresh_dt).total_seconds() / 3600.0
                stats["status_epg"] = "ok" if age_hours <= (refresh_hours * 1.5) else "stale"
        except Exception:
            stats["status_epg"] = "unknown"

        return jsonify(stats)

    @bp.route("/log")
    @authorise
    def log():
        logFilePath = os.path.join(LOG_DIR, "MacReplay.log")
        try:
            with open(logFilePath) as f:
                return f.read()
        except FileNotFoundError:
            return "Log file not found"

    @bp.route("/logs")
    @authorise
    def logs_page():
        return render_template("logs.html")

    @bp.route("/logs/stream")
    @authorise
    def logs_stream():
        logFilePath = os.path.join(LOG_DIR, "MacReplay.log")
        lines_param = request.args.get("lines", "500")

        try:
            with open(logFilePath, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()

            all_lines = [line.rstrip() for line in all_lines if line.strip()]

            if lines_param != "all":
                try:
                    num_lines = int(lines_param)
                    all_lines = all_lines[-num_lines:]
                except ValueError:
                    pass

            return flask.jsonify({"lines": all_lines, "total": len(all_lines)})
        except FileNotFoundError:
            return flask.jsonify({"lines": [], "error": "Log file not found"})
        except Exception as e:
            return flask.jsonify({"lines": [], "error": str(e)})

    @bp.route("/api/epg/source/refresh", methods=["POST"])
    @authorise
    def epg_source_refresh():
        payload = request.get_json(silent=True) or {}
        source_id = (payload.get("id") or "").strip()
        if not source_id:
            return jsonify({"ok": False, "error": "missing id"}), 400
        if not all(ch.isalnum() or ch in ("-", "_") for ch in source_id):
            return jsonify({"ok": False, "error": "invalid id"}), 400

        cache_dir = os.path.join(DATA_DIR, "epg_sources")
        cache_path = os.path.join(cache_dir, f"{source_id}.xml")
        meta_path = cache_path + ".meta"
        for path in (cache_path, meta_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        if refresh_custom_sources:
            worker = threading.Thread(
                target=refresh_custom_sources,
                args=([source_id],),
                daemon=True,
            )
            worker.start()

        return jsonify({"ok": True})

    @bp.route("/api/epg/source/status")
    @authorise
    def epg_source_status():
        source_id = (request.args.get("id") or "").strip()
        if not source_id:
            return jsonify({"ok": False, "error": "missing id"}), 400
        if get_epg_source_status is None:
            return jsonify({"ok": True, "status": "unknown", "detail": None, "updated_at": None})
        status = get_epg_source_status(source_id) or {}
        return jsonify(
            {
                "ok": True,
                "status": status.get("status", "unknown"),
                "detail": status.get("detail"),
                "updated_at": status.get("updated_at"),
            }
        )

    @bp.route("/api/epg/sources/meta")
    @authorise
    def epg_sources_meta():
        try:
            db_path = os.path.join(DATA_DIR, "channels.db")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT source_id, source_type, last_fetch, last_refresh
                FROM epg_sources
                """
            ).fetchall()
            conn.close()

            return jsonify(
                {
                    "ok": True,
                    "sources": [
                        {
                            "source_id": row["source_id"],
                            "source_type": row["source_type"],
                            "last_fetch": row["last_fetch"],
                            "last_refresh": row["last_refresh"],
                        }
                        for row in rows
                    ],
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @bp.route("/api/image-proxy")
    @authorise
    def image_proxy():
        url = (request.args.get("url") or "").strip()
        if not url:
            return jsonify({"ok": False, "error": "missing url"}), 400
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return jsonify({"ok": False, "error": "invalid url"}), 400

        try:
            req = Request(url, headers={"User-Agent": "MacReplay"})
            with urlopen(req, timeout=10) as resp:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                data = resp.read(2 * 1024 * 1024)
            return Response(data, content_type=content_type)
        except (HTTPError, URLError, OSError, ValueError):
            placeholder = (
                "<svg xmlns='http://www.w3.org/2000/svg' width='36' height='36' viewBox='0 0 36 36'>"
                "<rect width='36' height='36' rx='6' fill='#252b33'/>"
                "<path d='M11 12h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H11a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2zm2 14h10'"
                " fill='none' stroke='#8b99a6' stroke-width='2' stroke-linecap='round'/>"
                "</svg>"
            )
            return Response(placeholder, content_type="image/svg+xml")

    @bp.route("/", methods=["GET"])
    def home():
        try:
            return flask.current_app.send_static_file("dist/index.html")
        except Exception:
            return redirect("/api/dashboard", code=302)

    @bp.route("/<path:path>")
    def catch_all(path):
        if path == "portals":
            return redirect("/api/portals", code=302)
        if path == "editor":
            return redirect("/api/editor", code=302)
        if path == "settings":
            return redirect("/settings", code=302)
        if path == "dashboard":
            return redirect("/api/dashboard", code=302)

        try:
            return flask.current_app.send_static_file(f"dist/{path}")
        except Exception:
            return redirect("/api/dashboard", code=302)

    return bp
