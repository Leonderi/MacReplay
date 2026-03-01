import threading
import time


def start_epg_scheduler(state):
    """Start a background thread that periodically refreshes EPG data."""
    def epg_refresh_loop():
        while True:
            try:
                scheduler = state.scheduler
                interval_hours = scheduler.get_epg_refresh_interval()
                interval_seconds = max(60, int(interval_hours * 3600))

                scheduler.logger.info(
                    "EPG scheduler: Next refresh in %s hours (%s seconds)",
                    interval_hours,
                    interval_seconds,
                )
                time.sleep(interval_seconds)

                scheduler.logger.info("EPG scheduler: Queueing scheduled EPG refresh...")
                scheduler.job_manager.enqueue_epg_refresh(reason="scheduled")
                scheduler.logger.info("EPG scheduler: EPG refresh queued.")

            except Exception as exc:
                scheduler.logger.error("EPG scheduler error: %s", exc)
                time.sleep(300)

    scheduler_thread = threading.Thread(target=epg_refresh_loop, daemon=True)
    scheduler_thread.start()
    state.scheduler.logger.info("EPG background scheduler started!")


def start_channel_scheduler(state):
    """Start a background thread that periodically refreshes channel data from portals."""
    def channel_refresh_loop():
        while True:
            try:
                scheduler = state.scheduler
                interval_hours = scheduler.get_channel_refresh_interval()

                if interval_hours <= 0:
                    scheduler.logger.info(
                        "Channel scheduler: Automatic channel refresh disabled (interval = 0)"
                    )
                    time.sleep(3600)
                    continue

                interval_seconds = max(60, int(interval_hours * 3600))

                scheduler.logger.info(
                    "Channel scheduler: Next refresh in %s hours (%s seconds)",
                    interval_hours,
                    interval_seconds,
                )
                time.sleep(interval_seconds)

                scheduler.logger.info("Channel scheduler: Queueing scheduled channel refresh...")
                total = scheduler.job_manager.enqueue_refresh_all(reason="scheduled")
                scheduler.logger.info(
                    "Channel scheduler: Channel refresh queued (%s portals).", total
                )

            except Exception as exc:
                scheduler.logger.error("Channel scheduler error: %s", exc)
                time.sleep(300)

    scheduler_thread = threading.Thread(target=channel_refresh_loop, daemon=True)
    scheduler_thread.start()
    state.scheduler.logger.info("Channel background scheduler started!")


def start_vacuum_channels_scheduler(*, getSettings, logger):
    def vacuum_loop():
        while True:
            try:
                interval_hours = float(getSettings().get("vacuum channels interval hours", 0) or 0)
                if interval_hours <= 0:
                    time.sleep(3600)
                    continue
                logger.info("Channels DB vacuum scheduler: next run in %s hours", interval_hours)
                time.sleep(max(60, int(interval_hours * 3600)))
                logger.info("Channels DB vacuum scheduler: running VACUUM...")
                from macreplay.db import vacuum_channels_db
                vacuum_channels_db()
                logger.info("Channels DB vacuum scheduler: completed.")
            except Exception as exc:
                logger.error("Channels DB vacuum scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=vacuum_loop, daemon=True).start()
    logger.info("Channels DB vacuum scheduler started!")


def start_vacuum_epg_scheduler(*, getSettings, logger):
    def vacuum_loop():
        while True:
            try:
                interval_hours = float(getSettings().get("vacuum epg interval hours", 0) or 0)
                if interval_hours <= 0:
                    time.sleep(3600)
                    continue
                logger.info("EPG DB vacuum scheduler: next run in %s hours", interval_hours)
                time.sleep(max(60, int(interval_hours * 3600)))
                logger.info("EPG DB vacuum scheduler: running VACUUM...")
                from macreplay.db import vacuum_epg_dbs
                count = vacuum_epg_dbs()
                logger.info("EPG DB vacuum scheduler: completed (%s dbs).", count)
            except Exception as exc:
                logger.error("EPG DB vacuum scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=vacuum_loop, daemon=True).start()
    logger.info("EPG DB vacuum scheduler started!")


def start_custom_epg_scheduler(*, refresh_custom_sources, logger):
    """Start a lightweight scheduler for custom XMLTV sources.

    The per-source interval enforcement is handled inside refresh_custom_sources().
    This loop only triggers periodic checks.
    """

    def custom_epg_loop():
        while True:
            try:
                logger.info("Custom EPG scheduler: checking custom sources...")
                refresh_custom_sources()
            except Exception as exc:
                logger.error("Custom EPG scheduler error: %s", exc)
            # Keep checks frequent enough so per-source intervals are respected reliably.
            time.sleep(300)

    threading.Thread(target=custom_epg_loop, daemon=True).start()
    logger.info("Custom EPG scheduler started!")


def start_event_channel_cleanup_scheduler(*, getSettings, logger):
    """Start scheduler that removes expired event-generated channels."""

    def cleanup_loop():
        while True:
            try:
                interval_min = float(
                    getSettings().get("events cleanup interval minutes", 5) or 5
                )
                if interval_min <= 0:
                    time.sleep(3600)
                    continue

                time.sleep(max(30, int(interval_min * 60)))
                from macreplay.db import cleanup_expired_event_channels

                deleted = cleanup_expired_event_channels()
                if deleted:
                    logger.info(
                        "Event channel cleanup: removed %s expired channel(s).",
                        deleted,
                    )
            except Exception as exc:
                logger.error("Event channel cleanup scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=cleanup_loop, daemon=True).start()
    logger.info("Event channel cleanup scheduler started!")


def start_event_auto_create_scheduler(*, getSettings, logger, run_auto_create):
    """Start scheduler that auto-creates event channels for enabled rules."""

    def auto_create_loop():
        while True:
            try:
                interval_min = float(
                    getSettings().get("events auto create interval minutes", 0) or 0
                )
                if interval_min <= 0:
                    time.sleep(3600)
                    continue

                logger.info(
                    "Event auto-create scheduler: next run in %s minute(s)",
                    interval_min,
                )
                time.sleep(max(30, int(interval_min * 60)))
                result = run_auto_create() or {}
                logger.info(
                    "Event auto-create scheduler: done (rules=%s, ok=%s, failed=%s).",
                    result.get("rules", 0),
                    result.get("ok", 0),
                    result.get("failed", 0),
                )
            except Exception as exc:
                logger.error("Event auto-create scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=auto_create_loop, daemon=True).start()
    logger.info("Event auto-create scheduler started!")


def start_xtream_logins_scheduler(*, getSettings, logger, refresh_xtream_logins):
    """Start scheduler that refreshes Xtream login health/status."""

    def xtream_login_loop():
        while True:
            try:
                interval_min = float(
                    getSettings().get("xtream login check interval minutes", 0) or 0
                )
                if interval_min <= 0:
                    time.sleep(3600)
                    continue

                logger.info(
                    "Xtream login scheduler: next run in %s minute(s)",
                    interval_min,
                )
                time.sleep(max(60, int(interval_min * 60)))
                result = refresh_xtream_logins() or {}
                logger.info(
                    "Xtream login scheduler: done (portals=%s, logins=%s, invalid=%s).",
                    result.get("portals", 0),
                    result.get("logins", 0),
                    result.get("invalid", 0),
                )
            except Exception as exc:
                logger.error("Xtream login scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=xtream_login_loop, daemon=True).start()
    logger.info("Xtream login scheduler started!")


def start_stalker_macs_scheduler(*, getSettings, logger, refresh_stalker_macs):
    """Start scheduler that refreshes stalker MAC status/expiry."""

    def stalker_mac_loop():
        while True:
            try:
                interval_min = float(
                    getSettings().get("stalker mac check interval minutes", 0) or 0
                )
                if interval_min <= 0:
                    time.sleep(3600)
                    continue

                logger.info(
                    "Stalker MAC scheduler: next run in %s minute(s)",
                    interval_min,
                )
                time.sleep(max(60, int(interval_min * 60)))
                result = refresh_stalker_macs() or {}
                logger.info(
                    "Stalker MAC scheduler: done (portals=%s, macs=%s, expired=%s, unreachable=%s).",
                    result.get("portals", 0),
                    result.get("macs", 0),
                    result.get("expired", 0),
                    result.get("unreachable", 0),
                )
            except Exception as exc:
                logger.error("Stalker MAC scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=stalker_mac_loop, daemon=True).start()
    logger.info("Stalker MAC scheduler started!")


def start_speedtest_scheduler(*, getSettings, logger, run_speedtests):
    """Start scheduler that runs proxy/direct speedtests periodically."""

    def speedtest_loop():
        while True:
            try:
                interval_min = float(getSettings().get("speedtest interval minutes", 0) or 0)
                if interval_min <= 0:
                    time.sleep(3600)
                    continue

                logger.info(
                    "Speedtest scheduler: next run in %s minute(s)",
                    interval_min,
                )
                time.sleep(max(60, int(interval_min * 60)))
                result = run_speedtests() or {}
                logger.info(
                    "Speedtest scheduler: done (proxy_ok=%s, direct_ok=%s).",
                    result.get("proxy", {}).get("ok"),
                    result.get("direct", {}).get("ok"),
                )
            except Exception as exc:
                logger.error("Speedtest scheduler error: %s", exc)
                time.sleep(300)

    threading.Thread(target=speedtest_loop, daemon=True).start()
    logger.info("Speedtest scheduler started!")
