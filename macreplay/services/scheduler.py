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
