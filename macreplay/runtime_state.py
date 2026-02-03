from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class RuntimeState:
    # Core services/functions
    logger: Any
    job_manager: Any
    get_epg_refresh_interval: Callable[[], float]
    get_channel_refresh_interval: Callable[[], float]

    # Blueprint factories
    create_settings_blueprint: Callable[..., Any]
    create_epg_blueprint: Callable[..., Any]
    create_portal_blueprint: Callable[..., Any]
    create_editor_blueprint: Callable[..., Any]
    create_misc_blueprint: Callable[..., Any]
    create_hdhr_blueprint: Callable[..., Any]
    create_playlist_blueprint: Callable[..., Any]
    create_streaming_blueprint: Callable[..., Any]

    # Shared runtime data
    refresh_xmltv: Callable[..., Any]
    refresh_xmltv_for_epg_ids: Callable[..., Any]
    refresh_xmltv_for_portal: Callable[..., Any]
    get_cached_xmltv: Callable[[], Any]
    get_last_updated: Callable[[], Any]
    get_epg_refresh_status: Callable[[], Any]
    getPortals: Callable[[], Any]
    get_db_connection: Callable[[], Any]
    effective_epg_name: Callable[..., Any]
    getSettings: Callable[[], Any]
    open_epg_source_db: Callable[..., Any]
    savePortals: Callable[..., Any]
    ACTIVE_GROUP_CONDITION: str
    channelsdvr_match_status: Any
    channelsdvr_match_status_lock: Any
    normalize_mac_data: Callable[..., Any]
    defaultPortal: Any
    DB_PATH: str
    set_cached_xmltv: Callable[..., Any]
    filter_cache: Any
    get_epg_channel_ids: Callable[[], Any]
    get_epg_channel_map: Callable[[], Any]
    suggest_channelsdvr_matches: Callable[..., Any]
    host: str
    refresh_lineup: Callable[..., Any]
    set_last_playlist_host: Callable[..., Any]
    refresh_custom_sources: Callable[..., Any]
    LOG_DIR: str
    occupied: Any
    get_cached_lineup: Callable[[], Any]
    effective_display_name: Callable[..., Any]
    get_cached_playlist: Callable[[], Any]
    set_cached_playlist: Callable[..., Any]
    get_last_playlist_host: Callable[[], Any]
    moveMac: Callable[..., Any]
    score_mac_for_selection: Callable[..., Any]
    hls_manager: Any
