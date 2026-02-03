import atexit


def start_runtime(
    *,
    loadConfig,
    init_db,
    getPortals,
    logger,
    start_refresh,
    hls_manager,
    enable_jobs=True,
):
    loadConfig()
    init_db(getPortals, logger)
    if enable_jobs:
        start_refresh()
        hls_manager.start_monitoring()
        atexit.register(hls_manager.cleanup_all)
