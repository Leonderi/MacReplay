import re
import sqlite3
import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect, render_template, request, flash

from ..security import authorise
import stb
from macreplay import xtream


def create_portal_blueprint(
    *,
    logger,
    getPortals,
    savePortals,
    getSettings,
    get_db_connection,
    ACTIVE_GROUP_CONDITION,
    channelsdvr_match_status,
    channelsdvr_match_status_lock,
    normalize_mac_data,
    job_manager,
    defaultPortal,
    DB_PATH,
    set_cached_xmltv,
    filter_cache,
):
    bp = Blueprint("portal", __name__)

    def _parse_xtream_credentials(raw_credentials):
        logins = []
        seen = set()
        for line in (raw_credentials or "").splitlines():
            line = (line or "").strip()
            if not line:
                continue
            if ":" not in line:
                continue
            username, password = line.split(":", 1)
            username = username.strip()
            password = password.strip()
            if not username or not password:
                continue
            key = (username, password)
            if key in seen:
                continue
            seen.add(key)
            logins.append({"username": username, "password": password})
        return logins

    def _ensure_xtream_logins(portal):
        raw = portal.get("xtream logins")
        logins = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                username = str(item.get("username") or "").strip()
                password = str(item.get("password") or "").strip()
                if not username or not password:
                    continue
                normalized = dict(item)
                normalized["username"] = username
                normalized["password"] = password
                logins.append(normalized)

        if not logins:
            legacy_user = str(portal.get("xtream username") or "").strip()
            legacy_pass = str(portal.get("xtream password") or "").strip()
            if legacy_user and legacy_pass:
                logins = [{"username": legacy_user, "password": legacy_pass}]
        return logins

    def _hydrate_xtream_login_infos(url, proxy, user_agent, logins):
        out = []
        for login in logins:
            username = str(login.get("username") or "").strip()
            password = str(login.get("password") or "").strip()
            if not username or not password:
                continue
            info = xtream.get_account_info(
                url,
                username,
                password,
                proxy=proxy,
                user_agent=user_agent,
            )
            merged = dict(login)
            merged["username"] = username
            merged["password"] = password
            if info and info.get("_error"):
                error = info.get("_error") or {}
                status_code = error.get("status_code")
                if status_code == 403:
                    merged["status"] = "FORBIDDEN (403)"
                elif status_code == 401:
                    merged["status"] = "UNAUTHORIZED (401)"
                elif status_code:
                    merged["status"] = f"ERROR ({status_code})"
                else:
                    merged["status"] = "UNREACHABLE"
                merged["auth_error"] = True
                merged["status_code"] = status_code
                merged["expires_iso"] = ""
                merged["days_left"] = None
                merged["active_cons"] = 0
                merged["max_connections"] = 0
            elif info:
                merged["status"] = info.get("status") or merged.get("status", "")
                merged["auth_error"] = False
                merged["status_code"] = None
                merged["is_trial"] = info.get("is_trial")
                merged["exp_timestamp"] = info.get("exp_timestamp")
                merged["expires_iso"] = info.get("expires_iso") or ""
                merged["days_left"] = info.get("days_left")
                merged["active_cons"] = info.get("active_cons", 0)
                merged["max_connections"] = info.get("max_connections", 0)
                merged["created_at"] = info.get("created_at")
                merged["server_timezone"] = info.get("server_timezone") or ""
                merged["server_time_now"] = info.get("server_time_now") or ""
            out.append(merged)
        return out

    def _sync_xtream_legacy_fields(portal):
        logins = _ensure_xtream_logins(portal)
        portal["xtream logins"] = logins
        if logins:
            portal["xtream username"] = logins[0].get("username", "")
            portal["xtream password"] = logins[0].get("password", "")
        else:
            portal["xtream username"] = ""
            portal["xtream password"] = ""
        return logins

    @bp.route("/api/portals", methods=["GET"])
    @authorise
    def portals():
        """Legacy template route"""
        portal_data = getPortals()
        changed = False
        for portal in portal_data.values():
            if portal.get("type", "stalker") == "xtream":
                before = portal.get("xtream logins")
                _sync_xtream_legacy_fields(portal)
                if before != portal.get("xtream logins"):
                    changed = True
        if changed:
            savePortals(portal_data)

        portal_stats = {}
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT portal_id, total_channels, active_channels, total_groups, active_groups
                FROM portal_stats
                """
            )
            for row in cursor.fetchall():
                portal_stats[row["portal_id"]] = {
                    "channels": row["active_channels"] or 0,
                    "total_channels": row["total_channels"] or 0,
                    "groups": row["active_groups"] or 0,
                    "total_groups": row["total_groups"] or 0,
                }
            conn.close()
        except Exception as e:
            logger.error(f"Error getting portal stats: {e}")

        for portal_id, _portal in portal_data.items():
            if portal_id not in portal_stats:
                portal_stats[portal_id] = {
                    "channels": 0,
                    "total_channels": 0,
                    "groups": 0,
                    "total_groups": 0,
                }

        return render_template(
            "portals.html",
            portals=portal_data,
            portal_stats=portal_stats,
            settings=getSettings(),
        )

    @bp.route("/api/portal/groups", methods=["POST"])
    @authorise
    def portal_groups_from_db():
        data = request.get_json(silent=True) or {}
        portal_id = data.get("portal_id")
        if not portal_id:
            return jsonify({"success": False, "message": "Portal ID required"}), 400

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT genre_id AS id,
                       name AS title,
                       channel_count,
                       active
                FROM groups
                WHERE portal_id = ?
                ORDER BY name COLLATE NOCASE
                """,
                (portal_id,),
            )
            rows = cursor.fetchall()
            conn.close()

            groups = []
            for row in rows:
                title = row["title"] or row["id"]
                groups.append(
                    {
                        "id": row["id"],
                        "title": title,
                        "channel_count": row["channel_count"] or 0,
                        "active": bool(row["active"]),
                    }
                )
            return jsonify({"success": True, "groups": groups})
        except Exception as e:
            logger.error(f"Error loading groups from DB: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/portal/genres/list", methods=["POST"])
    @authorise
    def portal_genres_from_api():
        data = request.get_json(silent=True) or {}
        url = data.get("url")
        mac = data.get("mac")
        proxy = data.get("proxy") or ""

        if not url or not mac:
            return jsonify({"success": False, "message": "Portal URL and MAC required"}), 400

        token = stb.getToken(url, mac, proxy)
        if not token:
            return jsonify({"success": False, "message": "Could not get token"}), 400

        genres = stb.getGenres(url, mac, token, proxy) or []
        return jsonify({"success": True, "genres": genres})

    @bp.route("/api/portal/xtream/categories/list", methods=["POST"])
    @authorise
    def portal_xtream_categories_from_api():
        data = request.get_json(silent=True) or {}
        url = data.get("url")
        username = data.get("username")
        password = data.get("password")
        proxy = data.get("proxy") or ""
        user_agent = data.get("user_agent") or ""

        if not url or not username or not password:
            return jsonify({"success": False, "message": "URL, username and password required"}), 400

        categories = xtream.get_live_categories(
            url, username, password, proxy, user_agent=user_agent
        ) or []
        genres = []
        for item in categories:
            if not isinstance(item, dict):
                continue
            genres.append(
                {
                    "id": str(item.get("category_id") or ""),
                    "title": item.get("category_name") or item.get("name") or "Unknown",
                    "channel_count": 0,
                }
            )
        return jsonify({"success": True, "genres": genres})

    @bp.route("/api/portal/genres", methods=["POST"])
    @authorise
    def update_portal_genres():
        data = request.get_json(silent=True) or {}
        portal_id = data.get("portal_id")
        selected_genres = data.get("selected_genres") or []

        if not portal_id:
            return jsonify({"success": False, "message": "Portal ID required"}), 400

        portals = getPortals()
        if portal_id not in portals:
            return jsonify({"success": False, "message": "Portal not found"}), 404

        selected_genres = [str(g) for g in selected_genres if g is not None]

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("UPDATE groups SET active = 0 WHERE portal_id = ?", (portal_id,))
            if selected_genres:
                placeholders = ",".join(["?"] * len(selected_genres))
                cursor.execute(
                    f"UPDATE groups SET active = 1 WHERE portal_id = ? AND genre_id IN ({placeholders})",
                    [portal_id, *selected_genres],
                )

            cursor.execute(
                """
                SELECT COUNT(*) as total_groups,
                       SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active_groups
                FROM groups
                WHERE portal_id = ?
                """,
                (portal_id,),
            )
            row = cursor.fetchone()
            total_groups = row[0] or 0
            active_groups = row[1] or 0

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM channels c
                LEFT JOIN groups g ON c.portal_id = g.portal_id AND c.genre_id = g.genre_id
                WHERE c.portal_id = ? AND {ACTIVE_GROUP_CONDITION}
                """.format(ACTIVE_GROUP_CONDITION=ACTIVE_GROUP_CONDITION),
                (portal_id,),
            )
            active_channels = cursor.fetchone()[0] or 0

            cursor.execute(
                "SELECT COUNT(*) FROM channels WHERE portal_id = ?",
                (portal_id,),
            )
            total_channels = cursor.fetchone()[0] or 0

            portal = portals[portal_id]
            portal_name = portal.get("name", portal_id)
            cursor.execute(
                """
                INSERT INTO portal_stats (portal_id, portal_name, total_channels, active_channels, total_groups, active_groups, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(portal_id) DO UPDATE SET
                    portal_name = excluded.portal_name,
                    total_channels = excluded.total_channels,
                    active_channels = excluded.active_channels,
                    total_groups = excluded.total_groups,
                    active_groups = excluded.active_groups,
                    updated_at = excluded.updated_at
                """,
                (
                    portal_id,
                    portal_name,
                    total_channels,
                    active_channels,
                    total_groups,
                    active_groups,
                    datetime.utcnow().isoformat(),
                ),
            )

            conn.commit()
            conn.close()

            portal["selected_genres"] = selected_genres
            portal["total_groups"] = total_groups
            portal["total_channels"] = total_channels
            portals[portal_id] = portal
            savePortals(portals)
            filter_cache.clear()

            logger.info(
                "Updated genres for %s: %s/%s groups active, %s/%s channels",
                portal_name,
                active_groups,
                total_groups,
                active_channels,
                total_channels,
            )

            set_cached_xmltv(None)

            match_started = False
            if (
                getSettings().get("channelsdvr enabled", False)
                and portals.get(portal_id, {}).get("auto match", False)
            ):
                match_started = True

            refresh_status = job_manager.enqueue_refresh_portal(
                portal_id, reason="groups_update"
            )

            return jsonify(
                {
                    "success": True,
                    "message": "Genres updated successfully",
                    "total_groups": total_groups,
                    "active_groups": active_groups,
                    "total_channels": total_channels,
                    "active_channels": active_channels,
                    "match_started": match_started,
                    "refresh_status": refresh_status,
                }
            )

        except Exception as e:
            logger.error(f"Error updating genres: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/portal/match/status", methods=["POST"])
    @authorise
    def portal_match_status():
        data = request.get_json(silent=True) or {}
        portal_id = data.get("portal_id")
        if not portal_id:
            return jsonify({"success": False, "message": "Portal ID required"})
        with channelsdvr_match_status_lock:
            status = channelsdvr_match_status.get(portal_id)
        if not status:
            return jsonify({"success": True, "status": "idle"})
        return jsonify({"success": True, **status})

    @bp.route("/api/portal/flag", methods=["POST"])
    @authorise
    def portal_flag_update():
        data = request.get_json(silent=True) or {}
        portal_id = data.get("portal_id")
        flag = data.get("flag")
        raw_value = data.get("value")

        if not portal_id or not flag:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "portal_id and flag are required",
                    }
                ),
                400,
            )

        key_map = {
            "enabled": "enabled",
            "fetch_epg": "fetch epg",
            "auto_match": "auto match",
        }
        if flag not in key_map:
            return jsonify({"success": False, "message": "Unsupported flag"}), 400

        value = False
        if isinstance(raw_value, bool):
            value = raw_value
        elif isinstance(raw_value, (int, float)):
            value = raw_value != 0
        elif raw_value is not None:
            value = str(raw_value).strip().lower() in ("1", "true", "yes", "on")

        portals = getPortals()
        portal = portals.get(portal_id)
        if not portal:
            return jsonify({"success": False, "message": "Portal not found"}), 404

        portal[key_map[flag]] = value
        savePortals(portals)
        filter_cache.clear()

        return jsonify(
            {
                "success": True,
                "portal_id": portal_id,
                "flag": flag,
                "value": value,
            }
        )

    @bp.route("/portal/add", methods=["POST"])
    @authorise
    def portalsAdd():
        set_cached_xmltv(None)
        portal_id = uuid.uuid4().hex
        enabled = "true"
        name = request.form["name"]
        portalCode = request.form.get("portal code", "").strip().upper()
        portalCode = re.sub(r"[^A-Z0-9]", "", portalCode)
        if portalCode:
            portalCode = portalCode[:2]
        url = request.form["url"]
        macs = list(set(request.form["macs"].split(",")))
        streamsPerMac = request.form["streams per mac"]
        epgOffset = request.form["epg offset"]
        proxy = request.form["proxy"]
        fetchEpg = "true" if request.form.get("fetch epg") else "false"
        autoNormalize = "true" if request.form.get("auto normalize names") else "false"
        autoMatch = "true" if request.form.get("auto match") else "false"
        selectedGenres = request.form.getlist("selected_genres")

        if not url.endswith(".php"):
            url = stb.getUrl(url, proxy)
            if not url:
                logger.error("Error getting URL for Portal(%s)", name)
                flash(f"Error getting URL for Portal({name})", "danger")
                return redirect("/portals", code=302)

        macsd = {}
        tested_total = 0
        tested_success = 0
        tested_failed = 0

        for mac in macs:
            tested_total += 1
            logger.info("Testing MAC(%s) for Portal(%s)...", mac, name)
            token = stb.getToken(url, mac, proxy)
            if token:
                logger.debug("Got token for MAC(%s), getting profile and expiry...", mac)
                profile = stb.getProfile(url, mac, token, proxy)
                expiry = stb.getExpires(url, mac, token, proxy)
                if expiry:
                    macsd[mac] = {
                        "expiry": expiry,
                        "watchdog_timeout": profile.get("watchdog_timeout", 0)
                        if profile
                        else 0,
                        "playback_limit": profile.get("playback_limit", 0)
                        if profile
                        else 0,
                    }
                    logger.info("Successfully tested MAC(%s) for Portal(%s)", mac, name)
                    tested_success += 1
                    continue
                logger.error("Failed to get expiry for MAC(%s) for Portal(%s)", mac, name)
            else:
                logger.error("Failed to get token for MAC(%s) for Portal(%s)", mac, name)

            logger.error("Error testing MAC(%s) for Portal(%s)", mac, name)
            tested_failed += 1

        if tested_total > 0:
            if tested_success > 0 and tested_failed == 0:
                flash(
                    f"{tested_success}/{tested_total} MACs successfully added for Portal({name})",
                    "success",
                )
            elif tested_success > 0:
                flash(
                    f"{tested_success}/{tested_total} MACs successfully tested for Portal({name}). {tested_failed} failed.",
                    "warning",
                )
            else:
                flash(
                    f"0/{tested_total} MACs successfully tested for Portal({name}).",
                    "danger",
                )

        if len(macsd) > 0:
            portal = {
                "type": "stalker",
                "enabled": enabled,
                "name": name,
                "portal code": portalCode,
                "url": url,
                "macs": macsd,
                "streams per mac": streamsPerMac,
                "epg offset": epgOffset,
                "proxy": proxy,
                "fetch epg": fetchEpg,
                "selected_genres": selectedGenres,
                "auto normalize names": autoNormalize,
                "auto match": autoMatch,
            }

            for setting, default in defaultPortal.items():
                if not portal.get(setting):
                    portal[setting] = default

            portals = getPortals()
            portals[portal_id] = portal
            savePortals(portals)
            filter_cache.clear()
            logger.info("Portal(%s) added!", portal["name"])
            flash(f"Portal({portal['name']}) added!", "success")

            refresh_status = job_manager.enqueue_refresh_portal(portal_id, reason="portal_add")
            if refresh_status == "queued":
                flash("Portal refresh queued.", "info")
            elif refresh_status == "running":
                flash("Portal refresh already running.", "warning")
            elif refresh_status == "completed":
                flash("Portal refresh completed.", "success")
            else:
                flash("Portal refresh started.", "info")

        else:
            logger.error(
                "None of the MACs tested OK for Portal(%s). Adding not successful",
                name,
            )

        return redirect("/portals", code=302)

    @bp.route("/portal/add_xtream", methods=["POST"])
    @authorise
    def portalsAddXtream():
        set_cached_xmltv(None)
        portal_id = uuid.uuid4().hex
        enabled = "true"
        name = request.form["name"]
        portalCode = request.form.get("portal code", "").strip().upper()
        portalCode = re.sub(r"[^A-Z0-9]", "", portalCode)
        if portalCode:
            portalCode = portalCode[:2]
        url = request.form["url"].strip().rstrip("/")
        credentials_raw = request.form.get("xtream_credentials", "")
        parsed_logins = _parse_xtream_credentials(credentials_raw)
        username = request.form.get("xtream_username", "").strip()
        password = request.form.get("xtream_password", "").strip()
        if (not parsed_logins) and username and password:
            parsed_logins = [{"username": username, "password": password}]
        user_agent = request.form.get("xtream_user_agent", "").strip()
        proxy = request.form.get("proxy", "").strip()
        fetchEpg = "true" if request.form.get("fetch epg") else "false"
        autoNormalize = "true" if request.form.get("auto normalize names") else "false"
        autoMatch = "true" if request.form.get("auto match") else "false"

        if not url or not parsed_logins:
            flash("Xtream URL and at least one login (username:password) are required.", "danger")
            return redirect("/portals", code=302)

        hydrated_logins = _hydrate_xtream_login_infos(
            url=url,
            proxy=proxy,
            user_agent=user_agent,
            logins=parsed_logins,
        )
        if not hydrated_logins:
            hydrated_logins = parsed_logins

        portal = {
            "type": "xtream",
            "enabled": enabled,
            "name": name,
            "portal code": portalCode,
            "url": url,
            "macs": {},
            "xtream username": hydrated_logins[0].get("username", ""),
            "xtream password": hydrated_logins[0].get("password", ""),
            "xtream logins": hydrated_logins,
            "xtream user agent": user_agent,
            "streams per mac": 1,
            "epg offset": 0,
            "proxy": proxy,
            "fetch epg": fetchEpg,
            "selected_genres": [],
            "auto normalize names": autoNormalize,
            "auto match": autoMatch,
        }

        for setting, default in defaultPortal.items():
            if not portal.get(setting):
                portal[setting] = default

        portals = getPortals()
        portals[portal_id] = portal
        savePortals(portals)
        filter_cache.clear()
        logger.info("Xtream Portal(%s) added!", portal["name"])
        flash(f"Xtream Portal({portal['name']}) added!", "success")

        refresh_status = job_manager.enqueue_refresh_portal(portal_id, reason="portal_add")
        if refresh_status == "queued":
            flash("Portal refresh queued.", "info")
        elif refresh_status == "running":
            flash("Portal refresh already running.", "warning")
        elif refresh_status == "completed":
            flash("Portal refresh completed.", "success")
        else:
            flash("Portal refresh started.", "info")

        return redirect("/portals", code=302)

    @bp.route("/portal/update", methods=["POST"])
    @authorise
    def portalUpdate():
        set_cached_xmltv(None)
        portal_id = request.form["id"]
        enabled = request.form.get("enabled", "false")
        name = request.form["name"]
        portalCode = request.form.get("portal code", "").strip().upper()
        portalCode = re.sub(r"[^A-Z0-9]", "", portalCode)
        if portalCode:
            portalCode = portalCode[:2]
        url = request.form["url"]
        newmacs = list(set(request.form["macs"].split(",")))
        streamsPerMac = request.form["streams per mac"]
        epgOffset = request.form["epg offset"]
        proxy = request.form["proxy"]
        fetchEpg = "true" if request.form.get("fetch epg") else "false"
        autoNormalize = "true" if request.form.get("auto normalize names") else "false"
        autoMatch = "true" if request.form.get("auto match") else "false"
        retest = request.form.get("retest", None)
        selectedGenres = request.form.getlist("selected_genres")

        if not url.endswith(".php"):
            url = stb.getUrl(url, proxy)
            if not url:
                logger.error("Error getting URL for Portal(%s)", name)
                flash(f"Error getting URL for Portal({name})", "danger")
                return redirect("/portals", code=302)

        portals = getPortals()
        oldmacs = portals[portal_id]["macs"]
        macsout = {}
        deadmacs = []
        tested_total = 0
        tested_success = 0
        tested_failed = 0

        for mac in newmacs:
            if retest or mac not in oldmacs.keys():
                tested_total += 1
                logger.info("Testing MAC(%s) for Portal(%s)...", mac, name)
                token = stb.getToken(url, mac, proxy)
                if token:
                    logger.debug(
                        "Got token for MAC(%s), getting profile and expiry...", mac
                    )
                    profile = stb.getProfile(url, mac, token, proxy)
                    expiry = stb.getExpires(url, mac, token, proxy)
                    if expiry:
                        macsout[mac] = {
                            "expiry": expiry,
                            "watchdog_timeout": profile.get("watchdog_timeout", 0)
                            if profile
                            else 0,
                            "playback_limit": profile.get("playback_limit", 0)
                            if profile
                            else 0,
                        }
                        logger.info(
                            "Successfully tested MAC(%s) for Portal(%s)", mac, name
                        )
                        tested_success += 1
                    else:
                        logger.error(
                            "Failed to get expiry for MAC(%s) for Portal(%s)", mac, name
                        )
                else:
                    logger.error(
                        "Failed to get token for MAC(%s) for Portal(%s)", mac, name
                    )

                if mac not in list(macsout.keys()):
                    deadmacs.append(mac)
                    tested_failed += 1

            if mac in oldmacs.keys() and mac not in deadmacs:
                macsout[mac] = oldmacs[mac]

            if mac not in macsout.keys():
                logger.error("Error testing MAC(%s) for Portal(%s)", mac, name)

        if tested_total > 0:
            if tested_success > 0 and tested_failed == 0:
                flash(
                    f"{tested_success}/{tested_total} MACs successfully tested for Portal({name})",
                    "success",
                )
            elif tested_success > 0:
                flash(
                    f"{tested_success}/{tested_total} MACs successfully tested for Portal({name}). {tested_failed} failed.",
                    "warning",
                )
            else:
                flash(
                    f"0/{tested_total} MACs successfully tested for Portal({name}).",
                    "danger",
                )

        if len(macsout) > 0:
            portals[portal_id]["enabled"] = enabled
            portals[portal_id]["name"] = name
            portals[portal_id]["type"] = "stalker"
            portals[portal_id]["portal code"] = portalCode
            portals[portal_id]["url"] = url
            portals[portal_id]["macs"] = macsout
            portals[portal_id]["streams per mac"] = streamsPerMac
            portals[portal_id]["epg offset"] = epgOffset
            portals[portal_id]["proxy"] = proxy
            portals[portal_id]["fetch epg"] = fetchEpg
            portals[portal_id]["selected_genres"] = selectedGenres
            portals[portal_id]["auto normalize names"] = autoNormalize
            portals[portal_id]["auto match"] = autoMatch
            savePortals(portals)
            filter_cache.clear()
            logger.info("Portal(%s) updated!", name)
            flash(f"Portal({name}) updated!", "success")

        else:
            logger.error(
                "None of the MACs tested OK for Portal(%s). Adding not successful",
                name,
            )

        return redirect("/portals", code=302)

    @bp.route("/portal/update_xtream", methods=["POST"])
    @authorise
    def portalUpdateXtream():
        set_cached_xmltv(None)
        portal_id = request.form["id"]
        enabled = request.form.get("enabled", "false")
        name = request.form["name"]
        portalCode = request.form.get("portal code", "").strip().upper()
        portalCode = re.sub(r"[^A-Z0-9]", "", portalCode)
        if portalCode:
            portalCode = portalCode[:2]
        url = request.form["url"].strip().rstrip("/")
        credentials_raw = request.form.get("xtream_credentials", "")
        parsed_logins = _parse_xtream_credentials(credentials_raw)
        username = request.form.get("xtream_username", "").strip()
        password = request.form.get("xtream_password", "").strip()
        if (not parsed_logins) and username and password:
            parsed_logins = [{"username": username, "password": password}]
        user_agent = request.form.get("xtream_user_agent", "").strip()
        proxy = request.form.get("proxy", "").strip()
        fetchEpg = "true" if request.form.get("fetch epg") else "false"
        autoNormalize = "true" if request.form.get("auto normalize names") else "false"
        autoMatch = "true" if request.form.get("auto match") else "false"

        portals = getPortals()
        if portal_id not in portals:
            flash("Portal not found.", "danger")
            return redirect("/portals", code=302)
        if not parsed_logins:
            flash("At least one Xtream login (username:password) is required.", "danger")
            return redirect("/portals", code=302)

        hydrated_logins = _hydrate_xtream_login_infos(
            url=url,
            proxy=proxy,
            user_agent=user_agent,
            logins=parsed_logins,
        )
        if not hydrated_logins:
            hydrated_logins = parsed_logins

        portals[portal_id]["enabled"] = enabled
        portals[portal_id]["name"] = name
        portals[portal_id]["type"] = "xtream"
        portals[portal_id]["portal code"] = portalCode
        portals[portal_id]["url"] = url
        portals[portal_id]["xtream logins"] = hydrated_logins
        portals[portal_id]["xtream username"] = hydrated_logins[0].get("username", "")
        portals[portal_id]["xtream password"] = hydrated_logins[0].get("password", "")
        portals[portal_id]["xtream user agent"] = user_agent
        portals[portal_id]["proxy"] = proxy
        portals[portal_id]["fetch epg"] = fetchEpg
        portals[portal_id]["auto normalize names"] = autoNormalize
        portals[portal_id]["auto match"] = autoMatch
        savePortals(portals)
        filter_cache.clear()
        logger.info("Xtream Portal(%s) updated!", name)
        flash(f"Xtream Portal({name}) updated!", "success")

        return redirect("/portals", code=302)

    @bp.route("/portal/remove", methods=["POST"])
    @authorise
    def portalRemove():
        portal_id = request.form["deleteId"]
        portals = getPortals()

        if portal_id not in portals:
            logger.error(f"Attempted to delete non-existent portal: {portal_id}")
            if request.is_json or request.headers.get("Accept", "").startswith(
                "application/json"
            ):
                return jsonify({"error": "Portal not found"}), 404
            flash("Portal not found", "danger")
            return redirect("/portals", code=302)

        name = portals[portal_id]["name"]
        del portals[portal_id]
        savePortals(portals)
        filter_cache.clear()
        logger.info("Portal (%s) removed!", name)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE portal_id = ?", (portal_id,))
            deleted_count = cursor.rowcount
            cursor.execute("DELETE FROM channel_tags WHERE portal_id = ?", (portal_id,))
            cursor.execute("DELETE FROM group_stats WHERE portal_id = ?", (portal_id,))
            cursor.execute("DELETE FROM portal_stats WHERE portal_id = ?", (portal_id,))
            conn.commit()
            conn.close()
            logger.info(
                "Removed %s channels for portal %s from database",
                deleted_count,
                name,
            )
        except Exception as e:
            logger.error(f"Error removing channels from database for portal {name}: {e}")

        if request.is_json or request.headers.get("Accept", "").startswith(
            "application/json"
        ):
            return jsonify({"success": True, "message": f"Portal {name} removed"})

        flash(f"Portal ({name}) removed!", "success")
        return redirect("/portals", code=302)

    @bp.route("/api/portal/refresh", methods=["POST"])
    @authorise
    def refreshPortalChannels():
        try:
            data = request.get_json()
            portal_id = data.get("portal_id")

            if not portal_id:
                return jsonify({"status": "error", "message": "Portal ID required"}), 400

            portals = getPortals()
            if portal_id not in portals:
                return (
                    jsonify({"status": "error", "message": "Portal not found"}),
                    404,
                )

            portal_name = portals[portal_id].get("name", portal_id)
            logger.info("Refreshing channels for portal: %s", portal_name)
            refresh_status = job_manager.enqueue_refresh_portal(
                portal_id, reason="manual_refresh"
            )
            status_payload = job_manager.get_portal_refresh_status(portal_id)
            status_payload.update(
                {
                    "status": refresh_status,
                    "portal": portal_name,
                }
            )
            return jsonify(status_payload), 202
        except Exception as e:
            logger.error(f"Error refreshing portal channels: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/portal/refresh/status", methods=["POST"])
    @authorise
    def portal_refresh_status():
        data = request.get_json(silent=True) or {}
        portal_id = data.get("portal_id")
        if not portal_id:
            return jsonify({"status": "error", "message": "Portal ID required"}), 400
        status = job_manager.get_portal_refresh_status(portal_id)
        if not status:
            return jsonify({"status": "idle"})
        return jsonify(status)

    @bp.route("/api/portal/macs/refresh", methods=["POST"])
    @authorise
    def portal_refresh_macs():
        try:
            data = request.get_json(silent=True) or {}
            portal_id = data.get("portal_id") or data.get("portalId")
            if not portal_id:
                return jsonify({"success": False, "message": "Portal ID required"}), 400

            portals = getPortals()
            if portal_id not in portals:
                return jsonify({"success": False, "message": "Portal not found"}), 404

            portal = portals[portal_id]
            if portal.get("type", "stalker") != "stalker":
                return jsonify({"success": False, "message": "MAC refresh not supported for Xtream portals"}), 400
            url = portal.get("url", "")
            proxy = portal.get("proxy", "")
            macs = portal.get("macs", {}) or {}
            if not macs:
                return jsonify({"success": False, "message": "No MACs configured"}), 400

            tested_total = 0
            tested_success = 0
            tested_failed = 0
            macsout = {}

            for mac, old_data in macs.items():
                tested_total += 1
                logger.info("Refreshing MAC(%s) for Portal(%s)...", mac, portal.get("name", portal_id))
                token = stb.getToken(url, mac, proxy)
                if token:
                    profile = stb.getProfile(url, mac, token, proxy)
                    expiry = stb.getExpires(url, mac, token, proxy)
                    if expiry:
                        macsout[mac] = {
                            "expiry": expiry,
                            "watchdog_timeout": profile.get("watchdog_timeout", 0)
                            if profile
                            else 0,
                            "playback_limit": profile.get("playback_limit", 0)
                            if profile
                            else 0,
                        }
                        tested_success += 1
                    else:
                        tested_failed += 1
                        macsout[mac] = old_data
                else:
                    tested_failed += 1
                    macsout[mac] = old_data

            portals[portal_id]["macs"] = macsout
            savePortals(portals)
            filter_cache.clear()

            message = f"{tested_success}/{tested_total} MACs refreshed"
            if tested_failed:
                message += f", {tested_failed} failed"

            return jsonify({"success": True, "message": message, "macs": macsout})
        except Exception as e:
            logger.error(f"Error refreshing MACs: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    @bp.route("/api/portal/xtream/logins/refresh", methods=["POST"])
    @authorise
    def refresh_xtream_logins():
        try:
            data = request.get_json(silent=True) or {}
            portal_id = data.get("portal_id")
            if not portal_id:
                return jsonify({"success": False, "message": "Portal ID required"}), 400

            portals = getPortals()
            portal = portals.get(portal_id)
            if not portal:
                return jsonify({"success": False, "message": "Portal not found"}), 404
            if portal.get("type", "stalker") != "xtream":
                return jsonify({"success": False, "message": "Only available for Xtream portals"}), 400

            logins = _sync_xtream_legacy_fields(portal)
            if not logins:
                return jsonify({"success": False, "message": "No Xtream logins configured"}), 400

            refreshed = _hydrate_xtream_login_infos(
                url=portal.get("url", ""),
                proxy=portal.get("proxy", ""),
                user_agent=portal.get("xtream user agent", ""),
                logins=logins,
            )
            if refreshed:
                portal["xtream logins"] = refreshed
                _sync_xtream_legacy_fields(portal)
                savePortals(portals)
                filter_cache.clear()

            return jsonify(
                {
                    "success": True,
                    "message": f"Refreshed {len(refreshed or logins)} Xtream logins",
                    "logins": refreshed or logins,
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            logger.error(f"Error refreshing Xtream logins: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

    return bp
