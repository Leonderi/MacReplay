import os
import base64
import json
import re
import subprocess
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from flask import Blueprint, Response, current_app, make_response, redirect, request, send_file

import stb
from macreplay import xtream
from macreplay.config import get_effective_proxy


def create_streaming_blueprint(
    *,
    logger,
    getPortals,
    getSettings,
    get_db_connection,
    moveMac,
    score_mac_for_selection,
    occupied,
    hls_manager,
    recent_stream_history=None,
    recent_failed_macs=None,
):
    bp = Blueprint("streaming", __name__)
    default_xtream_user_agent = "TiviMate/5.1.6 (Android 12)"
    direct_link_cache = {}
    portal_ttl_state = {}
    xtream_portal_backoff_until = {}
    eof_backoff_cache = {}
    force_channel_lookup = set()
    _state_lock = threading.Lock()

    def _portal_ttl_bounds(portal):
        raw_min = portal.get("stalker cache ttl min seconds", 20)
        raw_max = portal.get("stalker cache ttl max seconds", 900)
        raw_initial = portal.get("stalker cache ttl seconds", 300)
        try:
            ttl_min = max(5, int(raw_min))
        except Exception:
            ttl_min = 20
        try:
            ttl_max = max(ttl_min, int(raw_max))
        except Exception:
            ttl_max = 900
        try:
            initial = int(raw_initial)
        except Exception:
            initial = 300
        initial = max(ttl_min, min(ttl_max, initial))
        return ttl_min, ttl_max, initial

    def _get_portal_ttl_state(portal_id, portal):
        ttl_min, ttl_max, initial = _portal_ttl_bounds(portal)
        with _state_lock:
            state = portal_ttl_state.get(portal_id)
            if not state:
                state = {
                    "ttl": initial,
                    "ttl_min": ttl_min,
                    "ttl_max": ttl_max,
                    "window": deque(maxlen=60),
                    "last_adjust": 0.0,
                }
                portal_ttl_state[portal_id] = state
            else:
                state["ttl_min"] = ttl_min
                state["ttl_max"] = ttl_max
                state["ttl"] = max(ttl_min, min(ttl_max, int(state.get("ttl", initial))))
            return state

    def _record_ttl_outcome(portal_id, portal, outcome):
        # outcome: success | auth_fail | other_fail
        state = _get_portal_ttl_state(portal_id, portal)
        marker = {"success": 1, "auth_fail": -1}.get(outcome, 0)
        now = time.time()
        with _state_lock:
            window = state["window"]
            window.append(marker)
            sample_count = len(window)
            if sample_count < 20:
                return
            auth_failures = sum(1 for item in window if item == -1)
            successes = sum(1 for item in window if item == 1)
            auth_rate = auth_failures / sample_count
            success_rate = successes / sample_count
            ttl_before = int(state["ttl"])
            ttl_after = ttl_before
            if now - float(state.get("last_adjust", 0.0)) >= 60:
                if auth_rate > 0.08:
                    ttl_after = max(state["ttl_min"], int(ttl_before * 0.7))
                elif auth_rate < 0.01 and success_rate > 0.85:
                    ttl_after = min(state["ttl_max"], int(ttl_before * 1.15))
            if ttl_after != ttl_before:
                state["ttl"] = ttl_after
                state["last_adjust"] = now
                logger.info(
                    "Adaptive link TTL updated | portal=%s ttl=%ss->%ss auth_rate=%.3f success_rate=%.3f samples=%s",
                    portal_id,
                    ttl_before,
                    ttl_after,
                    auth_rate,
                    success_rate,
                    sample_count,
                )

    def _get_cached_direct_link(portal_id, channel_id, portal):
        now = time.time()
        with _state_lock:
            item = direct_link_cache.get((portal_id, channel_id))
            if not item:
                return None
            if float(item.get("expires_at", 0.0)) <= now:
                direct_link_cache.pop((portal_id, channel_id), None)
                return None
            return item.get("link")

    def _set_cached_direct_link(portal_id, channel_id, portal, link):
        state = _get_portal_ttl_state(portal_id, portal)
        now = time.time()
        ttl_value = max(state["ttl_min"], min(state["ttl_max"], int(state["ttl"])))
        with _state_lock:
            direct_link_cache[(portal_id, channel_id)] = {
                "link": link,
                "cached_at": now,
                "expires_at": now + ttl_value,
                "ttl": ttl_value,
            }

    def _invalidate_cached_direct_link(portal_id, channel_id):
        with _state_lock:
            direct_link_cache.pop((portal_id, channel_id), None)

    def _mark_force_channel_lookup(portal_id, channel_id):
        with _state_lock:
            force_channel_lookup.add((str(portal_id), str(channel_id)))

    def _should_force_channel_lookup(portal_id, channel_id):
        with _state_lock:
            return (str(portal_id), str(channel_id)) in force_channel_lookup

    def _clear_force_channel_lookup(portal_id, channel_id):
        with _state_lock:
            force_channel_lookup.discard((str(portal_id), str(channel_id)))

    def _is_auth_error(stderr_lines):
        if not stderr_lines:
            return False
        joined = " ".join(stderr_lines).lower()
        if "forbidden" in joined or "unauthorized" in joined:
            return True
        return bool(re.search(r"\b(401|403)\b", joined))

    def _mark_xtream_portal_backoff(portal_id, seconds=300):
        until_ts = time.time() + max(30, int(seconds))
        with _state_lock:
            xtream_portal_backoff_until[portal_id] = until_ts

    def _is_xtream_portal_in_backoff(portal_id):
        now = time.time()
        with _state_lock:
            until_ts = float(xtream_portal_backoff_until.get(portal_id, 0.0))
            if until_ts <= now:
                if portal_id in xtream_portal_backoff_until:
                    xtream_portal_backoff_until.pop(portal_id, None)
                return False
            return True

    def _cache_backoff_state(scope, portal_id, channel_id, until_ts, streak, last_eof_ts):
        key = (scope, str(portal_id), str(channel_id or ""))
        with _state_lock:
            eof_backoff_cache[key] = {
                "until": int(until_ts),
                "streak": int(streak),
                "last_eof_ts": int(last_eof_ts),
            }

    def _delete_backoff_state(scope, portal_id, channel_id):
        key = (scope, str(portal_id), str(channel_id or ""))
        with _state_lock:
            eof_backoff_cache.pop(key, None)
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM stream_backoff WHERE scope = ? AND portal_id = ? AND channel_id = ?",
                [scope, str(portal_id), str(channel_id or "")],
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _save_backoff_state(scope, portal_id, channel_id, until_ts, streak, last_eof_ts):
        _cache_backoff_state(scope, portal_id, channel_id, until_ts, streak, last_eof_ts)
        now = int(time.time())
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO stream_backoff (scope, portal_id, channel_id, until_ts, streak, last_eof_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, portal_id, channel_id)
                DO UPDATE SET
                    until_ts = excluded.until_ts,
                    streak = excluded.streak,
                    last_eof_ts = excluded.last_eof_ts,
                    updated_at = excluded.updated_at
                """,
                [
                    scope,
                    str(portal_id),
                    str(channel_id or ""),
                    int(until_ts),
                    int(streak),
                    int(last_eof_ts),
                    now,
                ],
            )
            # keep table compact
            cur.execute("DELETE FROM stream_backoff WHERE until_ts <= ?", [now - 60])
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _get_backoff_state(scope, portal_id, channel_id):
        now = int(time.time())
        key = (scope, str(portal_id), str(channel_id or ""))
        with _state_lock:
            state = eof_backoff_cache.get(key)
            if state:
                if int(state.get("until", 0)) <= now:
                    eof_backoff_cache.pop(key, None)
                else:
                    return state
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            row = cur.execute(
                """
                SELECT until_ts, streak, last_eof_ts
                FROM stream_backoff
                WHERE scope = ? AND portal_id = ? AND channel_id = ?
                """,
                [scope, str(portal_id), str(channel_id or "")],
            ).fetchone()
            conn.close()
            if not row:
                return None
            until_ts = int(row["until_ts"] or 0)
            if until_ts <= now:
                _delete_backoff_state(scope, portal_id, channel_id)
                return None
            state = {
                "until": until_ts,
                "streak": int(row["streak"] or 0),
                "last_eof_ts": int(row["last_eof_ts"] or 0),
            }
            _cache_backoff_state(scope, portal_id, channel_id, until_ts, state["streak"], state["last_eof_ts"])
            return state
        except Exception:
            return None

    def _get_stream_eof_backoff_remaining(portal_id, channel_id):
        state = _get_backoff_state("portal_channel", portal_id, channel_id)
        if not state:
            return 0
        return max(0, int(state["until"] - int(time.time())))

    def _get_portal_eof_backoff_remaining(portal_id):
        state = _get_backoff_state("portal", portal_id, "")
        if not state:
            return 0
        return max(0, int(state["until"] - int(time.time())))

    def _mark_portal_backoff(portal_id):
        now = int(time.time())
        state = _get_backoff_state("portal", portal_id, "") or {"streak": 0, "last_eof_ts": 0, "until": 0}
        if now - int(state.get("last_eof_ts", 0)) > 600:
            state["streak"] = 0
        streak = int(state.get("streak", 0)) + 1
        backoff_seconds = min(1200, int(120 * (2 ** max(0, streak - 1))))
        until_ts = now + backoff_seconds
        _save_backoff_state("portal", portal_id, "", until_ts, streak, now)
        return backoff_seconds, streak

    def _mark_stream_eof_backoff(portal_id, channel_id, duration_sec):
        now = int(time.time())
        state = _get_backoff_state("portal_channel", portal_id, channel_id) or {
            "streak": 0,
            "last_eof_ts": 0,
            "until": 0,
        }
        if now - int(state.get("last_eof_ts", 0)) > 600:
            state["streak"] = 0
        streak = int(state.get("streak", 0)) + 1
        # very short failures should cool down faster
        base_seconds = 120 if int(duration_sec) <= 5 else 60
        backoff_seconds = min(900, int(base_seconds * (2 ** max(0, streak - 1))))
        until_ts = now + backoff_seconds
        _save_backoff_state(
            "portal_channel",
            portal_id,
            channel_id,
            until_ts,
            streak,
            now,
        )
        return backoff_seconds, streak

    def _record_eof_event_and_maybe_backoff_portal(portal_id, channel_id):
        now = int(time.time())
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO stream_eof_events (portal_id, channel_id, failed_at) VALUES (?, ?, ?)",
                [str(portal_id), str(channel_id or ""), now],
            )
            cur.execute(
                "DELETE FROM stream_eof_events WHERE failed_at < ?",
                [now - 3600],
            )
            recent_count = cur.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM stream_eof_events
                WHERE portal_id = ? AND failed_at >= ?
                """,
                [str(portal_id), now - 120],
            ).fetchone()["cnt"]
            conn.commit()
            conn.close()
        except Exception:
            recent_count = 0
        if int(recent_count) >= 3:
            return _mark_portal_backoff(portal_id), int(recent_count)
        return None, int(recent_count)

    def force_ts_link(link):
        if not link:
            return link
        if ".m3u8" in link:
            return link.replace(".m3u8", ".ts")
        return link

    def _extract_cmd_url(cmd):
        text = str(cmd or "").strip()
        if not text:
            return ""
        parts = text.split()
        return parts[-1] if parts else text

    def remember_recent_stream(*, portal_name, channel_name, client, start_time=None):
        if recent_stream_history is None:
            return
        try:
            recent_stream_history.append(
                {
                    "portal_name": portal_name or "-",
                    "channel_name": channel_name or "-",
                    "client": client or "-",
                    "start_time": int(start_time or time.time()),
                }
            )
        except Exception:
            pass

    def remember_failed_mac(*, portal_name, portal_id, mac, channel_id):
        if recent_failed_macs is None:
            return
        if not mac:
            return
        try:
            recent_failed_macs.append(
                {
                    "portal_name": portal_name or portal_id or "-",
                    "portal_id": portal_id or "-",
                    "mac": mac,
                    "channel_id": channel_id or "-",
                    "timestamp": int(time.time()),
                }
            )
        except Exception:
            pass

    def _health_lookback_seconds():
        try:
            days = int(getSettings().get("stream health lookback days", 30) or 30)
        except Exception:
            days = 30
        days = max(1, min(365, days))
        return days * 86400

    def _success_min_seconds():
        try:
            seconds = int(getSettings().get("stream success min seconds", 45) or 45)
        except Exception:
            seconds = 45
        return max(5, min(600, seconds))

    def _get_mac_health_adjustments(portal_id, channel_id, macs):
        adjustments = {m: 0 for m in macs}
        if not macs:
            return adjustments
        now_ts = int(time.time())
        since_ts = now_ts - _health_lookback_seconds()
        success_min = _success_min_seconds()
        placeholders = ",".join(["?"] * len(macs))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            success_rows = cur.execute(
                f"""
                SELECT mac, COUNT(1) AS cnt
                FROM stream_sessions
                WHERE portal_id = ?
                  AND channel_id = ?
                  AND started_at >= ?
                  AND mac IN ({placeholders})
                  AND COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at)) >= ?
                GROUP BY mac
                """,
                [str(portal_id), str(channel_id), since_ts, *macs, success_min],
            ).fetchall()
            fail_rows = cur.execute(
                f"""
                SELECT mac, COUNT(1) AS cnt
                FROM mac_failures
                WHERE portal_id = ?
                  AND channel_id = ?
                  AND failed_at >= ?
                  AND mac IN ({placeholders})
                GROUP BY mac
                """,
                [str(portal_id), str(channel_id), since_ts, *macs],
            ).fetchall()
            conn.close()
            success_map = {str(r["mac"]): int(r["cnt"] or 0) for r in success_rows}
            fail_map = {str(r["mac"]): int(r["cnt"] or 0) for r in fail_rows}
            for mac in macs:
                # Upvote stable MACs, downvote failed MACs (channel-specific).
                up = min(300, success_map.get(mac, 0) * 6)
                down = min(500, fail_map.get(mac, 0) * 22)
                adjustments[mac] = int(up - down)
        except Exception:
            return adjustments
        return adjustments
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO mac_failures (portal_id, portal_name, channel_id, mac, failed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [portal_id, portal_name, channel_id, mac, int(time.time())],
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_xtream_login(portal):
        logins = portal.get("xtream logins")
        if isinstance(logins, list):
            for login in logins:
                if not isinstance(login, dict):
                    continue
                username = str(login.get("username") or "").strip()
                password = str(login.get("password") or "").strip()
                if not (username and password):
                    continue
                status = str(login.get("status") or "").upper()
                auth_error = bool(login.get("auth_error"))
                if auth_error:
                    continue
                if "FORBIDDEN" in status or "UNAUTHORIZED" in status:
                    continue
                return username, password
            return "", ""
        return "", ""

    def _get_event_source_info(portal_id, channel_id):
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            row = cur.execute(
                """
                SELECT source_portal_id, source_channel_id
                FROM event_generated_channels
                WHERE portal_id = ? AND channel_id = ?
                LIMIT 1
                """,
                [str(portal_id), str(channel_id)],
            ).fetchone()
            if not row:
                conn.close()
                return None
            source_portal_id = str(row["source_portal_id"] or "").strip()
            source_channel_id = str(row["source_channel_id"] or "").strip()
            source_name = None
            source_tags = []
            if source_portal_id and source_channel_id:
                source_row = cur.execute(
                    """
                    SELECT
                        COALESCE(NULLIF(custom_name, ''), NULLIF(matched_name, ''), NULLIF(auto_name, ''), name) AS display_name,
                        UPPER(COALESCE(resolution, '')) AS resolution,
                        LOWER(COALESCE(video_codec, '')) AS video_codec,
                        COALESCE(is_event, 0) AS is_event,
                        COALESCE(is_header, 0) AS is_header,
                        COALESCE(is_raw, 0) AS is_raw,
                        COALESCE(matched_name, '') AS matched_name
                    FROM channels
                    WHERE portal_id = ? AND channel_id = ?
                    LIMIT 1
                    """,
                    [source_portal_id, source_channel_id],
                ).fetchone()
                if source_row:
                    source_name = source_row["display_name"]
                    resolution = str(source_row["resolution"] or "").strip().upper()
                    if resolution in {"SD", "HD", "FHD", "UHD", "4K"}:
                        source_tags.append(resolution)
                    codec = str(source_row["video_codec"] or "").lower()
                    if "hevc" in codec or "h265" in codec:
                        source_tags.append("HEVC")
                    if bool(source_row["is_event"]):
                        source_tags.append("EVENT")
                    if bool(source_row["is_header"]):
                        source_tags.append("HEADER")
                    if bool(source_row["is_raw"]):
                        source_tags.append("RAW")
                    if str(source_row["matched_name"] or "").strip():
                        source_tags.append("MATCH")
            conn.close()
            source_portal_name = (
                (getPortals() or {}).get(source_portal_id, {}).get("name")
                if source_portal_id
                else None
            )
            return {
                "source_portal_id": source_portal_id,
                "source_channel_id": source_channel_id,
                "source_channel_name": source_name or source_channel_id or "",
                "source_portal_name": source_portal_name or source_portal_id or "",
                "source_tags": source_tags,
            }
        except Exception:
            return None

    @bp.route("/play/<portalId>/<channelId>", methods=["GET"])
    def channel(portalId, channelId):
        portal = getPortals().get(portalId)
        if not portal:
            logger.error("Play request for unknown portal: %s", portalId)
            return make_response("Portal not found", 404)

        portalName = portal.get("name")
        url = portal.get("url")
        streamsPerMac = int(portal.get("streams per mac"))
        proxy = get_effective_proxy(portal.get("proxy"), getSettings())
        portal_type = portal.get("type", "stalker")
        portal_user_agent = (portal.get("xtream user agent", "") or "").strip()
        if portal_type == "xtream" and not portal_user_agent:
            portal_user_agent = default_xtream_user_agent
        web = request.args.get("web")
        ip = request.remote_addr
        channelName = portal.get("custom channel names", {}).get(channelId)
        event_source_info = _get_event_source_info(portalId, channelId)
        mac = None

        logger.info(
            "Play request | portal=%s type=%s channel=%s web=%s ip=%s",
            portalId,
            portal_type,
            channelId,
            bool(web),
            ip,
        )

        def streamData():
            ffmpeg_sp = None
            occupied_item = None
            session_id = None
            first_chunk_seen = False
            startup_ms = None
            exit_reason = "unknown"
            ffmpeg_rc = None
            stderr_buffer = []
            stderr_lock = threading.Lock()

            def _drain_stderr(pipe):
                try:
                    for line in iter(pipe.readline, b""):
                        text = line.decode(errors="ignore").strip()
                        if not text:
                            continue
                        with stderr_lock:
                            stderr_buffer.append(text)
                            if len(stderr_buffer) > 50:
                                stderr_buffer.pop(0)
                except Exception:
                    pass
            def occupy():
                nonlocal occupied_item, session_id
                if portal_type != "xtream":
                    occupied.setdefault(portalId, [])
                    occupied_item = {
                        "mac": mac,
                        "channel id": channelId,
                        "channel name": channelName,
                        "client": ip,
                        "portal name": portalName,
                        "start time": startTime,
                    }
                    if event_source_info:
                        occupied_item["source portal id"] = event_source_info.get("source_portal_id")
                        occupied_item["source portal name"] = event_source_info.get("source_portal_name")
                        occupied_item["source channel id"] = event_source_info.get("source_channel_id")
                        occupied_item["source channel name"] = event_source_info.get("source_channel_name")
                        occupied_item["source tags"] = event_source_info.get("source_tags") or []
                    occupied.get(portalId, []).append(occupied_item)
                    logger.info(
                        "Occupied Portal({} | {}):MAC({})".format(portalName, portalId, mac)
                    )
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO stream_sessions (
                            portal_id, portal_name, channel_id, channel_name,
                            client_ip, mac, started_at, stream_mode
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            portalId,
                            portalName,
                            channelId,
                            channelName,
                            ip,
                            mac,
                            int(startTime),
                            "web" if web else str(getSettings().get("stream method", "ffmpeg")),
                        ],
                    )
                    session_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                except Exception:
                    session_id = None

            def unoccupy():
                nonlocal session_id
                try:
                    if portal_type != "xtream" and occupied_item and occupied_item in occupied.get(portalId, []):
                        occupied.get(portalId, []).remove(occupied_item)
                        logger.info(
                            "Unoccupied Portal({} | {}):MAC({})".format(
                                portalName, portalId, mac
                            )
                        )
                except Exception:
                    pass
                if session_id:
                    try:
                        end_ts = int(time.time())
                        duration = max(0, end_ts - int(startTime))
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            UPDATE stream_sessions
                            SET ended_at = ?, duration_sec = ?, startup_ms = COALESCE(startup_ms, ?)
                            WHERE id = ?
                            """,
                            [end_ts, duration, startup_ms, session_id],
                        )
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass

            try:
                startTime = datetime.now(timezone.utc).timestamp()
                occupy()
                ffmpeg_sp = subprocess.Popen(
                    ffmpegcmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                stderr_thread = threading.Thread(
                    target=_drain_stderr, args=(ffmpeg_sp.stderr,), daemon=True
                )
                stderr_thread.start()
                while True:
                    chunk = ffmpeg_sp.stdout.read(1024)
                    if len(chunk) == 0:
                        rc = ffmpeg_sp.poll()
                        ffmpeg_rc = rc
                        if rc not in (None, 0):
                            exit_reason = "ffmpeg_error"
                            logger.info("Ffmpeg closed with error(%s) for Portal(%s)", str(rc), portalName)
                            auth_fail = False
                            with stderr_lock:
                                if stderr_buffer:
                                    logger.info(
                                        "Ffmpeg stderr tail: %s", " | ".join(stderr_buffer[-8:])
                                    )
                                    auth_fail = _is_auth_error(stderr_buffer[-8:])
                            if portal_type == "stalker" and auth_fail:
                                # Force one fresh channel lookup on next request to refresh cmd/link.
                                _mark_force_channel_lookup(portalId, channelId)
                            if portal_type == "stalker" and result and result.get("used_cached_link"):
                                if auth_fail:
                                    _invalidate_cached_direct_link(portalId, channelId)
                                    _record_ttl_outcome(portalId, portal, "auth_fail")
                                elif first_chunk_seen:
                                    _record_ttl_outcome(portalId, portal, "success")
                                else:
                                    _record_ttl_outcome(portalId, portal, "other_fail")
                            if portal_type != "xtream" and mac:
                                moveMac(portalId, mac)
                                remember_failed_mac(
                                    portal_name=portalName,
                                    portal_id=portalId,
                                    mac=mac,
                                    channel_id=channelId,
                                )
                        else:
                            exit_reason = "stream_eof"
                        break
                    if not first_chunk_seen:
                        first_chunk_seen = True
                        startup_ms = max(0, int((time.time() - float(startTime)) * 1000))
                    if portal_type == "stalker" and result and result.get("used_cached_link"):
                        _record_ttl_outcome(portalId, portal, "success")
                        result["used_cached_link"] = False
                    yield chunk
            except GeneratorExit:
                exit_reason = "client_disconnect"
            except BrokenPipeError:
                exit_reason = "broken_pipe"
            except Exception as e:
                exit_reason = f"stream_exception:{type(e).__name__}"
                logger.warning(
                    "Stream generator exception | portal=%s channel=%s mac=%s error=%s",
                    portalId,
                    channelId,
                    mac,
                    e,
                )
            finally:
                unoccupy()
                end_ts = int(time.time())
                duration = max(0, end_ts - int(startTime))
                if portal_type != "xtream":
                    logger.info(
                        "Stream end | portal=%s channel=%s mac=%s reason=%s duration=%ss chunks=%s rc=%s",
                        portalId,
                        channelId,
                        mac,
                        exit_reason,
                        duration,
                        int(first_chunk_seen),
                        ffmpeg_rc,
                    )
                if portal_type == "stalker" and exit_reason == "stream_eof":
                    backoff_seconds, streak = _mark_stream_eof_backoff(
                        portalId, channelId, duration
                    )
                    logger.info(
                        "EOF backoff applied | portal=%s channel=%s backoff=%ss streak=%s",
                        portalId,
                        channelId,
                        backoff_seconds,
                        streak,
                    )
                    portal_backoff, recent_eof_count = _record_eof_event_and_maybe_backoff_portal(
                        portalId, channelId
                    )
                    if portal_backoff:
                        portal_backoff_seconds, portal_streak = portal_backoff
                        logger.info(
                            "Portal EOF backoff applied | portal=%s backoff=%ss streak=%s recent_eof_120s=%s",
                            portalId,
                            portal_backoff_seconds,
                            portal_streak,
                            recent_eof_count,
                        )
                short_fail_threshold = int(getSettings().get("stream short failure seconds", 8))
                if (
                    portal_type != "xtream"
                    and mac
                    and exit_reason not in {"client_disconnect", "broken_pipe"}
                    and duration <= short_fail_threshold
                    and not first_chunk_seen
                ):
                    remember_failed_mac(
                        portal_name=portalName,
                        portal_id=portalId,
                        mac=mac,
                        channel_id=channelId,
                    )
                if ffmpeg_sp is not None:
                    try:
                        ffmpeg_sp.kill()
                    except Exception:
                        pass

        def isMacFree():
            if portal_type == "xtream":
                return True
            count = 0
            for i in occupied.get(portalId, []):
                if i["mac"] == mac:
                    count = count + 1
            if count < streamsPerMac:
                return True
            return False

        available_macs = []
        alternate_ids = []
        cached_cmd = None
        cached_channel_name = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT available_macs, alternate_ids, cmd, name FROM channels WHERE portal_id = ? AND channel_id = ?",
                [portalId, channelId],
            )
            row = cursor.fetchone()
            if row:
                if row[0]:
                    available_macs = [m.strip() for m in row[0].split(",") if m.strip()]
                if row[1]:
                    alternate_ids = [aid.strip() for aid in row[1].split(",") if aid.strip()]
                if row[2]:
                    cached_cmd = row[2]
                if row[3]:
                    cached_channel_name = row[3]
            conn.close()
        except Exception as e:
            logger.debug(f"Could not get channel data for channel {channelId}: {e}")

        channel_ids_to_try = [channelId] + alternate_ids
        if alternate_ids:
            logger.debug(f"Channel {channelId} has alternate IDs: {alternate_ids}")

        if portal_type == "xtream":
            username, password = get_xtream_login(portal)
            if not username or not password:
                logger.warning(
                    "Xtream stream blocked: no valid login for portal %s (%s)",
                    portalName,
                    portalId,
                )
                return make_response("No valid Xtream login available", 503)
            link = cached_cmd or xtream.build_stream_url(
                url, username, password, channelId, ext="ts"
            )
            link = force_ts_link(link)
            logger.info("Xtream preview link | channel=%s link=%s", channelId, link)
            if not link:
                return make_response("Stream not available", 503)

            if web:
                remember_recent_stream(
                    portal_name=portalName,
                    channel_name=channelName or cached_channel_name or channelId,
                    client=ip,
                )
                ffmpegcmd = [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-hide_banner",
                    "-analyzeduration",
                    "0",
                    "-probesize",
                    "32768",
                    "-reconnect",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-flags",
                    "low_delay",
                    "-fflags",
                    "+nobuffer+genpts+discardcorrupt",
                    "-i",
                    link,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0?",
                    "-vcodec",
                    "copy",
                    "-acodec",
                    "aac",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-b:a",
                    "128k",
                    "-f",
                    "mp4",
                    "-movflags",
                    "frag_keyframe+empty_moov",
                    "pipe:",
                ]
                if portal_user_agent:
                    ffmpegcmd.insert(1, "-user_agent")
                    ffmpegcmd.insert(2, portal_user_agent)
                if proxy:
                    ffmpegcmd.insert(1, "-http_proxy")
                    ffmpegcmd.insert(2, proxy)
                logger.debug(
                    "Xtream web ffmpeg command (ua=%s): %s",
                    portal_user_agent,
                    " ".join(ffmpegcmd),
                )
                return Response(streamData(), mimetype="application/octet-stream")

            if getSettings().get("stream method", "ffmpeg") == "ffmpeg":
                remember_recent_stream(
                    portal_name=portalName,
                    channel_name=channelName or cached_channel_name or channelId,
                    client=ip,
                )
                ffmpegcmd = str(getSettings()["ffmpeg command"])
                ffmpegcmd = ffmpegcmd.replace("<url>", link)
                ffmpegcmd = ffmpegcmd.replace(
                    "<timeout>",
                    str(int(getSettings()["ffmpeg timeout"]) * int(1000000)),
                )
                if proxy:
                    ffmpegcmd = ffmpegcmd.replace("<proxy>", proxy)
                else:
                    ffmpegcmd = ffmpegcmd.replace("-http_proxy <proxy>", "")
                " ".join(ffmpegcmd.split())
                ffmpegcmd = ffmpegcmd.split()
                if portal_user_agent and ffmpegcmd and ffmpegcmd[0] == "ffmpeg":
                    ffmpegcmd = [ffmpegcmd[0], "-user_agent", portal_user_agent] + ffmpegcmd[1:]
                return Response(streamData(), mimetype="application/octet-stream")

            remember_recent_stream(
                portal_name=portalName,
                channel_name=channelName or cached_channel_name or channelId,
                client=ip,
            )
            return redirect(link)

        macs_dict = portal["macs"]
        occupied_list = occupied.get(portalId, [])
        mac_health_adjustments = _get_mac_health_adjustments(
            portalId, channelId, list(macs_dict.keys())
        )
        mac_scores = []
        for mac, mac_data in macs_dict.items():
            score = score_mac_for_selection(mac, mac_data, occupied_list, streamsPerMac)
            score += int(mac_health_adjustments.get(mac, 0) or 0)
            mac_scores.append((mac, score))

        mac_scores.sort(key=lambda x: (x[1] >= 0, x[1]), reverse=True)
        macs = [m[0] for m in mac_scores if m[1] >= 0]
        if not macs:
            logger.warning(
                "No eligible MACs for Portal(%s):Channel(%s) after health/expiry filtering",
                portalId,
                channelId,
            )
            return make_response("No valid MAC available", 503)

        if available_macs:
            valid_available = [m for m in macs if m in available_macs]
            other_macs = [m for m in macs if m not in available_macs]
            if valid_available:
                macs = valid_available + other_macs
                logger.debug(
                    f"Prioritizing {len(valid_available)} available MACs for channel {channelId}"
                )

        logger.debug(f"MAC scores for Portal({portalName}): {mac_scores[:5]}")

        logger.info(
            "IP({}) requested Portal({}):Channel({})".format(ip, portalId, channelId)
        )

        def probe_single_mac(mac_to_test):
            try:
                if streamsPerMac != 0 and not isMacFree():
                    return None

                logger.info(
                    "Trying Portal({}):MAC({}):Channel({})".format(
                        portalId, mac_to_test, channelId
                    )
                )

                token = stb.getToken(url, mac_to_test, proxy)
                if not token:
                    return None

                stb.getProfile(url, mac_to_test, token, proxy)

                cmd = None
                channels = None
                found_channel_name = (
                    portal.get("custom channel names", {}).get(channelId)
                    or cached_channel_name
                )
                used_cached_link = False
                runtime_cached_link = _get_cached_direct_link(portalId, channelId, portal)
                force_lookup = _should_force_channel_lookup(portalId, channelId)

                if cached_cmd:
                    cmd = cached_cmd
                    logger.debug(f"Using cached cmd for channel {channelId}")

                # Prefer cached cmd/link path; only refresh full channel list when missing
                # (or explicitly forced after auth-like errors).
                needs_fresh_channel_lookup = (not cmd) or force_lookup

                if needs_fresh_channel_lookup:
                    logger.debug(
                        "Fetching all channels for MAC %s (needs_fresh=%s force=%s)",
                        mac_to_test,
                        needs_fresh_channel_lookup,
                        force_lookup,
                    )
                    channels = stb.getAllChannels(url, mac_to_test, token, proxy)
                    if channels:
                        used_channel_id = channelId
                        for try_channel_id in channel_ids_to_try:
                            for c in channels:
                                if str(c["id"]) == try_channel_id:
                                    if found_channel_name is None:
                                        found_channel_name = c["name"]
                                    cmd = c["cmd"]
                                    used_channel_id = try_channel_id
                                    if try_channel_id != channelId:
                                        logger.info(
                                            f"Using alternate channel ID {try_channel_id} instead of {channelId}"
                                        )
                                    break
                            if cmd:
                                break
                    if cmd:
                        _clear_force_channel_lookup(portalId, channelId)

                if not cmd:
                    return None

                if "http://localhost/" in cmd:
                    link = stb.getLink(url, mac_to_test, token, cmd, proxy)
                else:
                    if runtime_cached_link:
                        link = runtime_cached_link
                        used_cached_link = True
                    else:
                        link = _extract_cmd_url(cmd)
                        if link:
                            _set_cached_direct_link(portalId, channelId, portal, link)

                if not link:
                    return None

                return {
                    "mac": mac_to_test,
                    "token": token,
                    "link": link,
                    "channelName": found_channel_name,
                    "used_cached_link": used_cached_link,
                }
            except Exception as e:
                logger.error(f"Error probing MAC({mac_to_test}): {e}")
                return None

        freeMac = False
        result = None
        failed_macs = []

        parallel_enabled = getSettings().get("parallel mac probing", False)
        max_workers = int(getSettings().get("parallel mac workers", "3"))

        if parallel_enabled and len(macs) > 1:
            logger.info(
                f"Using parallel MAC probing with {max_workers} workers for {len(macs)} MACs"
            )

            with ThreadPoolExecutor(max_workers=min(max_workers, len(macs))) as executor:
                future_to_mac = {
                    executor.submit(probe_single_mac, mac): mac for mac in macs
                }

                for future in as_completed(future_to_mac):
                    mac = future_to_mac[future]
                    try:
                        probe_result = future.result()
                        if probe_result:
                            result = probe_result
                            freeMac = True
                            for f in future_to_mac:
                                f.cancel()
                            break
                        failed_macs.append(mac)
                    except Exception as e:
                        logger.error(f"Exception probing MAC({mac}): {e}")
                        failed_macs.append(mac)
        else:
            for mac in macs:
                probe_result = probe_single_mac(mac)
                if probe_result:
                    result = probe_result
                    freeMac = True
                    break
                failed_macs.append(mac)
                if not getSettings().get("try all macs", True):
                    break

        for failed_mac in failed_macs:
            logger.info("Moving MAC({}) for Portal({})".format(failed_mac, portalName))
            moveMac(portalId, failed_mac)
            remember_failed_mac(
                portal_name=portalName,
                portal_id=portalId,
                mac=failed_mac,
                channel_id=channelId,
            )

        if result:
            mac = result["mac"]
            link = result["link"]
            channelName = result["channelName"]

            if web:
                remember_recent_stream(
                    portal_name=portalName,
                    channel_name=channelName or channelId,
                    client=ip,
                )
                ffmpegcmd = [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-hide_banner",
                    "-i",
                    link,
                    "-vcodec",
                    "copy",
                    "-f",
                    "mp4",
                    "-movflags",
                    "frag_keyframe+empty_moov",
                    "pipe:",
                ]
                if proxy:
                    ffmpegcmd.insert(1, "-http_proxy")
                    ffmpegcmd.insert(2, proxy)
                return Response(streamData(), mimetype="application/octet-stream")

            if getSettings().get("stream method", "ffmpeg") == "ffmpeg":
                remember_recent_stream(
                    portal_name=portalName,
                    channel_name=channelName or channelId,
                    client=ip,
                )
                ffmpegcmd = str(getSettings()["ffmpeg command"])
                ffmpegcmd = ffmpegcmd.replace("<url>", link)
                ffmpegcmd = ffmpegcmd.replace(
                    "<timeout>",
                    str(int(getSettings()["ffmpeg timeout"]) * int(1000000)),
                )
                if proxy:
                    ffmpegcmd = ffmpegcmd.replace("<proxy>", proxy)
                else:
                    ffmpegcmd = ffmpegcmd.replace("-http_proxy <proxy>", "")
                " ".join(ffmpegcmd.split())
                ffmpegcmd = ffmpegcmd.split()
                return Response(streamData(), mimetype="application/octet-stream")

            logger.info("Redirect sent")
            remember_recent_stream(
                portal_name=portalName,
                channel_name=channelName or channelId,
                client=ip,
            )
            return redirect(link)

        if freeMac:
            logger.info(
                "No working streams found for Portal({}):Channel({})".format(
                    portalId, channelId
                )
            )
        else:
            logger.info(
                "No free MAC for Portal({}):Channel({})".format(portalId, channelId)
            )

        return make_response("No streams available", 503)

    @bp.route("/play_group/<group_token>", methods=["GET"])
    def play_group(group_token):
        def decode_token(token):
            try:
                padded = token + "=" * (-len(token) % 4)
                payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
                name_key = str(payload.get("n") or "").strip().lower()
                quality = str(payload.get("q") or "").strip().upper()
                is_hevc = bool(int(payload.get("h") or 0))
                is_raw = bool(int(payload.get("r") or 0))
                if not name_key:
                    return None
                return {
                    "name_key": name_key,
                    "quality": quality,
                    "is_hevc": is_hevc,
                    "is_raw": is_raw,
                }
            except Exception:
                return None

        token_data = decode_token(group_token)
        if not token_data:
            return make_response("Invalid group token", 400)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                c.portal_id,
                c.channel_id,
                COALESCE(NULLIF(c.custom_name, ''), NULLIF(c.matched_name, ''), NULLIF(c.auto_name, ''), c.name) AS display_name,
                UPPER(COALESCE(c.resolution, '')) AS resolution,
                LOWER(COALESCE(c.video_codec, '')) AS video_codec,
                c.is_raw
            FROM channels c
            WHERE c.enabled = 1
              AND c.matched_name IS NOT NULL
              AND c.matched_name != ''
              AND LOWER(COALESCE(NULLIF(c.custom_name, ''), NULLIF(c.matched_name, ''), NULLIF(c.auto_name, ''), c.name)) = ?
            """,
            [token_data["name_key"]],
        )
        candidates = cursor.fetchall()
        conn.close()

        if not candidates:
            return make_response("No grouped channels available", 404)

        filtered = []
        for row in candidates:
            row_quality = (row["resolution"] or "").strip().upper()
            row_is_raw = bool(row["is_raw"])
            codec = row["video_codec"] or ""
            row_is_hevc = ("hevc" in codec) or ("h265" in codec)
            if row_quality != token_data["quality"]:
                continue
            if row_is_raw != token_data["is_raw"]:
                continue
            if row_is_hevc != token_data["is_hevc"]:
                continue
            portal_cfg = (getPortals() or {}).get(row["portal_id"]) or {}
            if not bool(portal_cfg.get("enabled", True)):
                continue
            if portal_cfg.get("type", "stalker") == "xtream":
                if _is_xtream_portal_in_backoff(row["portal_id"]):
                    continue
                username, password = get_xtream_login(portal_cfg)
                if not username or not password:
                    _mark_xtream_portal_backoff(row["portal_id"], 300)
                    continue
            eof_backoff_remaining = _get_stream_eof_backoff_remaining(
                row["portal_id"], row["channel_id"]
            )
            portal_backoff_remaining = _get_portal_eof_backoff_remaining(
                row["portal_id"]
            )
            filtered.append((row, eof_backoff_remaining, portal_backoff_remaining))

        if not filtered:
            return make_response("No matching channels in group", 404)

        candidates_for_scoring = filtered
        available_now = [item for item in filtered if item[1] <= 0 and item[2] <= 0]
        if available_now:
            candidates_for_scoring = available_now

        now_ts = int(time.time())
        lookback_seconds = _health_lookback_seconds()
        cutoff_ts = now_ts - lookback_seconds
        success_min = _success_min_seconds()
        conn = get_db_connection()
        cursor = conn.cursor()
        scored = []
        for row, eof_backoff_remaining, portal_backoff_remaining in candidates_for_scoring:
            portal_id = row["portal_id"]
            channel_id = row["channel_id"]
            active_streams = len(occupied.get(portal_id, []))
            fail_count = cursor.execute(
                """
                SELECT COUNT(1) AS cnt
                FROM mac_failures
                WHERE portal_id = ? AND channel_id = ? AND failed_at >= ?
                """,
                [portal_id, channel_id, cutoff_ts],
            ).fetchone()["cnt"]
            eof_count_24h = 0
            eof_count_30m = 0
            try:
                eof_count_24h = cursor.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM stream_eof_events
                    WHERE portal_id = ? AND channel_id = ? AND failed_at >= ?
                    """,
                    [portal_id, channel_id, cutoff_ts],
                ).fetchone()["cnt"]
                eof_count_30m = cursor.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM stream_eof_events
                    WHERE portal_id = ? AND channel_id = ? AND failed_at >= ?
                    """,
                    [portal_id, channel_id, now_ts - 1800],
                ).fetchone()["cnt"]
            except Exception:
                eof_count_24h = 0
                eof_count_30m = 0
            success_count = 0
            portal_success_count = 0
            portal_fail_count = 0
            channel_startup_ms = None
            portal_startup_ms = None
            try:
                success_count = cursor.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM stream_sessions
                    WHERE portal_id = ?
                      AND channel_id = ?
                      AND started_at >= ?
                      AND COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at)) >= ?
                    """,
                    [portal_id, channel_id, cutoff_ts, success_min],
                ).fetchone()["cnt"]
                portal_success_count = cursor.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM stream_sessions
                    WHERE portal_id = ?
                      AND started_at >= ?
                      AND COALESCE(duration_sec, MAX(0, strftime('%s','now') - started_at)) >= ?
                    """,
                    [portal_id, cutoff_ts, success_min],
                ).fetchone()["cnt"]
                portal_fail_count = cursor.execute(
                    """
                    SELECT COUNT(1) AS cnt
                    FROM stream_eof_events
                    WHERE portal_id = ?
                      AND failed_at >= ?
                    """,
                    [portal_id, cutoff_ts],
                ).fetchone()["cnt"]
                startup_row = cursor.execute(
                    """
                    SELECT AVG(startup_ms) AS avg_startup_ms
                    FROM stream_sessions
                    WHERE portal_id = ?
                      AND channel_id = ?
                      AND started_at >= ?
                      AND startup_ms IS NOT NULL
                      AND startup_ms >= 0
                    """,
                    [portal_id, channel_id, cutoff_ts],
                ).fetchone()
                if startup_row and startup_row["avg_startup_ms"] is not None:
                    channel_startup_ms = int(float(startup_row["avg_startup_ms"]))
                portal_startup_row = cursor.execute(
                    """
                    SELECT AVG(startup_ms) AS avg_startup_ms
                    FROM stream_sessions
                    WHERE portal_id = ?
                      AND started_at >= ?
                      AND startup_ms IS NOT NULL
                      AND startup_ms >= 0
                    """,
                    [portal_id, cutoff_ts],
                ).fetchone()
                if portal_startup_row and portal_startup_row["avg_startup_ms"] is not None:
                    portal_startup_ms = int(float(portal_startup_row["avg_startup_ms"]))
            except Exception:
                success_count = 0
                portal_success_count = 0
                portal_fail_count = 0
                channel_startup_ms = None
                portal_startup_ms = None
            channel_latency_penalty = min(180, int(channel_startup_ms / 20)) if channel_startup_ms is not None else 0
            portal_latency_penalty = min(120, int(portal_startup_ms / 30)) if portal_startup_ms is not None else 0
            score = (
                1000
                - (int(fail_count) * 50)
                - (int(eof_count_24h) * 35)
                - (int(eof_count_30m) * 80)
                + min(300, int(success_count) * 8)
                + min(220, int(portal_success_count) * 2)
                - min(260, int(portal_fail_count) * 4)
                - (int(active_streams) * 5)
                - int(min(600, max(0, eof_backoff_remaining)))
                - int(min(900, max(0, portal_backoff_remaining)))
                - channel_latency_penalty
                - portal_latency_penalty
            )
            scored.append(
                (
                    score,
                    row,
                    eof_backoff_remaining,
                    portal_backoff_remaining,
                    int(eof_count_24h),
                    int(eof_count_30m),
                    int(success_count),
                    int(portal_success_count),
                    int(portal_fail_count),
                    channel_startup_ms,
                    portal_startup_ms,
                )
            )
        conn.close()

        scored.sort(key=lambda item: item[0], reverse=True)
        logger.info(
            "Grouped play request | token=%s candidates=%s top=%s",
            group_token,
            len(scored),
            [
                {
                    "portal": r["portal_id"],
                    "channel": r["channel_id"],
                    "score": s,
                    "eof_backoff_s": eof_backoff_s,
                    "portal_backoff_s": portal_backoff_s,
                    "eof_24h": eof_24h,
                    "eof_30m": eof_30m,
                    "success": success_count,
                    "portal_success": portal_success,
                    "portal_eof": portal_eof,
                    "startup_ms": channel_start_ms,
                    "portal_startup_ms": portal_start_ms,
                }
                for s, r, eof_backoff_s, portal_backoff_s, eof_24h, eof_30m, success_count, portal_success, portal_eof, channel_start_ms, portal_start_ms in scored[:3]
            ],
        )

        web = bool(request.args.get("web"))
        web_raw = request.args.get("web")
        client_ip = request.remote_addr
        app_obj = current_app._get_current_object()

        def _call_channel_for_group(row):
            # grouped_stream runs while iterating the response body; at that point the
            # original request context may be gone. Recreate a minimal context per call.
            query = ""
            if web_raw:
                query = "?web=" + str(web_raw)
            path = f"/play/{row['portal_id']}/{row['channel_id']}{query}"
            with app_obj.test_request_context(
                path, environ_base={"REMOTE_ADDR": client_ip}
            ):
                return channel(row["portal_id"], row["channel_id"])

        # Keep non-web behavior unchanged (redirect/direct mode).
        if not web:
            for _, row, _, _, _, _, _, _, _, _, _ in scored:
                response = _call_channel_for_group(row)
                portal_cfg = (getPortals() or {}).get(row["portal_id"]) or {}
                if (
                    portal_cfg.get("type", "stalker") == "xtream"
                    and getattr(response, "status_code", 200) == 503
                ):
                    _mark_xtream_portal_backoff(row["portal_id"], 300)
                if getattr(response, "status_code", 200) != 503:
                    return response
            return make_response("No streams available for group", 503)

        def _iter_candidate_stream(resp, row, idx):
            chunk_count = 0
            try:
                for chunk in resp.response:
                    chunk_count += 1
                    yield chunk
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            logger.info(
                "Grouped candidate ended | idx=%s portal=%s channel=%s chunks=%s",
                idx,
                row["portal_id"],
                row["channel_id"],
                chunk_count,
            )

        first_response = None
        first_idx = None
        for idx, (_, row, _, _, _, _, _, _, _, _, _) in enumerate(scored, start=1):
            response = _call_channel_for_group(row)
            portal_cfg = (getPortals() or {}).get(row["portal_id"]) or {}
            status = getattr(response, "status_code", 200)
            if (
                portal_cfg.get("type", "stalker") == "xtream"
                and status == 503
            ):
                _mark_xtream_portal_backoff(row["portal_id"], 300)
            if status == 503:
                logger.info(
                    "Grouped candidate unavailable | idx=%s portal=%s channel=%s",
                    idx,
                    row["portal_id"],
                    row["channel_id"],
                )
                continue
            first_response = response
            first_idx = idx
            break

        if first_response is None:
            return make_response("No streams available for group", 503)

        def grouped_stream():
            for idx, (_, row, _, _, _, _, _, _, _, _, _) in enumerate(scored, start=1):
                if idx == first_idx:
                    response = first_response
                elif idx < first_idx:
                    continue
                else:
                    response = _call_channel_for_group(row)
                if idx != first_idx:
                    portal_cfg = (getPortals() or {}).get(row["portal_id"]) or {}
                    status = getattr(response, "status_code", 200)
                    if (
                        portal_cfg.get("type", "stalker") == "xtream"
                        and status == 503
                    ):
                        _mark_xtream_portal_backoff(row["portal_id"], 300)
                    if status == 503:
                        logger.info(
                            "Grouped candidate unavailable | idx=%s portal=%s channel=%s",
                            idx,
                            row["portal_id"],
                            row["channel_id"],
                        )
                        continue
                logger.info(
                    "Grouped candidate selected | idx=%s portal=%s channel=%s",
                    idx,
                    row["portal_id"],
                    row["channel_id"],
                )
                try:
                    yield from _iter_candidate_stream(response, row, idx)
                except GeneratorExit:
                    raise
                except Exception as e:
                    logger.warning(
                        "Grouped candidate stream error | idx=%s portal=%s channel=%s err=%s",
                        idx,
                        row["portal_id"],
                        row["channel_id"],
                        e,
                    )
                    continue
                # If stream ended naturally (e.g. EOF), try next candidate seamlessly.
                logger.info(
                    "Grouped failover to next candidate | previous_idx=%s",
                    idx,
                )

        return Response(grouped_stream(), mimetype="application/octet-stream")

    @bp.route("/hls/<portalId>/<channelId>/<path:filename>", methods=["GET"])
    def hls_stream(portalId, channelId, filename):
        portal = getPortals().get(portalId)
        if not portal:
            logger.error(f"Portal {portalId} not found for HLS request")
            return make_response("Portal not found", 404)

        portalName = portal.get("name")
        url = portal.get("url")
        macs = list(portal["macs"].keys())
        proxy = get_effective_proxy(portal.get("proxy"), getSettings())
        portal_type = portal.get("type", "stalker")
        portal_user_agent = (portal.get("xtream user agent", "") or "").strip()
        if portal_type == "xtream" and not portal_user_agent:
            portal_user_agent = default_xtream_user_agent
        ip = request.remote_addr

        logger.info(
            f"HLS request from IP({ip}) for Portal({portalId}):Channel({channelId}):File({filename})"
        )

        stream_key = f"{portalId}_{channelId}"

        stream_exists = stream_key in hls_manager.streams

        if stream_exists:
            logger.debug(
                f"Stream already active for {stream_key}, checking for file: {filename}"
            )
            if filename.endswith(".m3u8"):
                is_passthrough = hls_manager.streams[stream_key].get(
                    "is_passthrough", False
                )
                max_wait = 100 if not is_passthrough else 10
                logger.debug(
                    f"Waiting for {filename} from active stream (passthrough={is_passthrough})"
                )

                for wait_count in range(max_wait):
                    file_path = hls_manager.get_file(portalId, channelId, filename)
                    if file_path:
                        logger.debug(f"File ready after {wait_count * 0.1:.1f}s")
                        break
                    time.sleep(0.1)
            else:
                file_path = hls_manager.get_file(portalId, channelId, filename)
        else:
            logger.debug("Stream not active, will need to start it")
            file_path = None

        if not file_path and (
            filename.endswith(".m3u8")
            or filename.endswith(".ts")
            or filename.endswith(".m4s")
        ):
            logger.debug(
                f"Fetching stream URL for channel {channelId} from portal {portalName}"
            )
            link = None
            if portal_type == "xtream":
                username, password = get_xtream_login(portal)
                if not username or not password:
                    logger.warning(
                        "Xtream HLS stream blocked: no valid login for portal %s (%s)",
                        portalName,
                        portalId,
                    )
                    return make_response("No valid Xtream login available", 503)
                try:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT cmd FROM channels WHERE portal_id = ? AND channel_id = ?",
                        [portalId, channelId],
                    )
                    row = cursor.fetchone()
                    conn.close()
                    if row and row[0]:
                        link = row[0]
                except Exception:
                    link = None
                if not link:
                    link = xtream.build_stream_url(
                        url, username, password, channelId, ext="ts"
                    )
                link = force_ts_link(link)
            else:
                for mac in macs:
                    try:
                        logger.debug(f"Trying MAC: {mac}")
                        token = stb.getToken(url, mac, proxy)
                        if token:
                            stb.getProfile(url, mac, token, proxy)
                            channels = stb.getAllChannels(url, mac, token, proxy)

                            if channels:
                                for c in channels:
                                    if str(c["id"]) == channelId:
                                        cmd = c["cmd"]
                                        if "http://localhost/" in cmd:
                                            link = stb.getLink(url, mac, token, cmd, proxy)
                                        else:
                                            link = cmd.split(" ")[1]
                                        logger.debug(
                                            f"Found stream URL for channel {channelId}"
                                        )
                                        break

                            if link:
                                break
                    except Exception as e:
                        logger.error(
                            f"Error getting stream URL for HLS with MAC {mac}: {e}"
                        )
                        continue

            if not link:
                logger.error(
                    f"✗ Could not get stream URL for Portal({portalId}):Channel({channelId}) - tried {len(macs)} MAC(s)"
                )
                return make_response("Stream not available", 503)

            try:
                logger.debug(f"Starting new stream for {stream_key}")
                stream_info = hls_manager.start_stream(
                    portalId, channelId, link, proxy, user_agent=portal_user_agent
                )

                is_passthrough = stream_info.get("is_passthrough", False)

                if filename.endswith(".m3u8"):
                    logger.debug(
                        f"Waiting for playlist file: {filename} (passthrough={is_passthrough})"
                    )
                    max_wait = 100 if not is_passthrough else 10

                    for wait_count in range(max_wait):
                        file_path = hls_manager.get_file(portalId, channelId, filename)
                        if file_path:
                            logger.debug(
                                f"Playlist ready after {wait_count * 0.1:.1f}s"
                            )
                            break
                        time.sleep(0.1)

                    if not file_path:
                        logger.warning(
                            f"Playlist {filename} not ready after {max_wait * 0.1:.0f} seconds"
                        )
                        if not is_passthrough and stream_key in hls_manager.streams:
                            process = hls_manager.streams[stream_key]["process"]
                            if process.poll() is not None:
                                logger.error(
                                    f"FFmpeg crashed during startup (exit code: {process.returncode})"
                                )
                            else:
                                temp_dir = hls_manager.streams[stream_key]["temp_dir"]
                                try:
                                    files = os.listdir(temp_dir)
                                    logger.warning(
                                        f"FFmpeg still running but {filename} not found. Temp dir contains: {files}"
                                    )
                                except Exception as e:
                                    logger.error(f"Could not list temp dir: {e}")
                else:
                    logger.debug(f"Waiting for segment file: {filename}")
                    for wait_count in range(30):
                        file_path = hls_manager.get_file(portalId, channelId, filename)
                        if file_path:
                            logger.debug(
                                f"Segment ready after {wait_count * 0.1:.1f}s"
                            )
                            break
                        time.sleep(0.1)

                    if not file_path:
                        logger.warning(f"Segment {filename} not ready after 3 seconds")

            except Exception as e:
                logger.error(f"✗ Error starting HLS stream: {e}")
                logger.debug(f"Exception details: {type(e).__name__}: {str(e)}")
                return make_response("Error starting stream", 500)

        if file_path and os.path.exists(file_path):
            try:
                if filename.endswith(".m3u8"):
                    mimetype = "application/vnd.apple.mpegurl"
                elif filename.endswith(".ts"):
                    mimetype = "video/mp2t"
                elif filename.endswith(".m4s") or filename.endswith(".mp4"):
                    mimetype = "video/mp4"
                else:
                    mimetype = "application/octet-stream"

                file_size = os.path.getsize(file_path)
                logger.debug(f"Serving {filename} ({file_size} bytes, {mimetype})")

                if filename.endswith(".m3u8") and file_path:
                    try:
                        temp_dir = hls_manager.streams[stream_key]["temp_dir"]
                        available_files = [
                            f
                            for f in os.listdir(temp_dir)
                            if f.endswith(".ts") or f.endswith(".m4s")
                        ]
                        logger.debug(
                            f"Available segments in temp dir: {sorted(available_files)}"
                        )
                    except Exception as e:
                        logger.debug(f"Could not list segments: {e}")

                if filename.endswith(".m3u8") and file_size < 5000:
                    try:
                        with open(file_path, "r") as f:
                            content = f.read()
                            logger.debug(f"Playlist content:\n{content}")
                    except Exception as e:
                        logger.debug(f"Could not read playlist content: {e}")

                return send_file(file_path, mimetype=mimetype)
            except Exception as e:
                logger.error(f"✗ Error serving HLS file {filename}: {e}")
                return make_response("Error serving file", 500)

        logger.warning(f"✗ HLS file not found: {filename} for {stream_key}")
        return make_response("File not found", 404)

    return bp
