from functools import wraps

from flask import make_response, request

from .config import getSettings


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_users(settings):
    users = settings.get("access users", [])
    normalized = []
    if isinstance(users, list):
        for entry in users:
            if not isinstance(entry, dict):
                continue
            username = str(entry.get("username", "") or "").strip()
            password = str(entry.get("password", "") or "").strip()
            if not username or not password:
                continue
            normalized.append(
                {
                    "username": username,
                    "password": password,
                    "enabled": _to_bool(entry.get("enabled"), True),
                    "web": _to_bool(entry.get("web"), True),
                    "admin": _to_bool(entry.get("admin"), False),
                    "m3u": _to_bool(entry.get("m3u"), False),
                    "xc": _to_bool(entry.get("xc"), False),
                }
            )

    # Backward-compatible fallback to legacy single account.
    if not normalized:
        legacy_user = str(settings.get("username", "") or "").strip()
        legacy_pass = str(settings.get("password", "") or "").strip()
        if legacy_user and legacy_pass:
            normalized.append(
                {
                    "username": legacy_user,
                    "password": legacy_pass,
                    "enabled": True,
                    "web": True,
                    "admin": True,
                    "m3u": True,
                    "xc": True,
                }
            )
    return normalized


def _find_user(settings, username, password):
    if not username or not password:
        return None
    for user in _normalize_users(settings):
        if not user.get("enabled", True):
            continue
        if user["username"] == username and user["password"] == password:
            return user
    return None


def _requires_admin_path(path):
    admin_prefixes = ("/settings", "/portal", "/portals", "/api/settings", "/api/portal")
    return any(path.startswith(prefix) for prefix in admin_prefixes)


def _challenge():
    return make_response(
        "Could not verify your login!",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'},
    )


def authorise(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        settings = getSettings()
        if not _to_bool(settings.get("enable security"), False):
            return f(*args, **kwargs)

        auth = request.authorization
        user = _find_user(
            settings,
            auth.username if auth else None,
            auth.password if auth else None,
        )
        if not user:
            return _challenge()
        if not user.get("web", False):
            return make_response("Forbidden", 403)

        method = request.method.upper()
        needs_admin = method in {"POST", "PUT", "PATCH", "DELETE"} or _requires_admin_path(request.path)
        if needs_admin and not user.get("admin", False):
            return make_response("Forbidden", 403)

        return f(*args, **kwargs)

    return decorated


def authorise_m3u(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        settings = getSettings()
        if not _to_bool(settings.get("enable security"), False):
            return f(*args, **kwargs)
        auth = request.authorization
        user = _find_user(
            settings,
            auth.username if auth else None,
            auth.password if auth else None,
        )
        if not user:
            return _challenge()
        if not user.get("m3u", False):
            return make_response("Forbidden", 403)
        return f(*args, **kwargs)

    return decorated


def validate_xc_credentials(username, password):
    settings = getSettings()
    if not _to_bool(settings.get("xtream api enabled"), False):
        return False
    user = _find_user(settings, username, password)
    if user:
        return bool(user.get("xc", False))

    # Backward-compatible Xtream credentials fallback.
    legacy_user = str(settings.get("xtream api username", "") or "").strip()
    legacy_pass = str(settings.get("xtream api password", "") or "").strip()
    if legacy_user and legacy_pass and username == legacy_user and password == legacy_pass:
        return True
    return False
