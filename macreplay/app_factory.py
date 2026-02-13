import os
import secrets
from flask import Flask

from macreplay.blueprints.registry import register_blueprints


def create_app(*, state=None, test_config=None):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    templates_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")
    app = Flask(__name__, template_folder=templates_dir, static_folder=static_dir)
    app.secret_key = secrets.token_urlsafe(32)
    if test_config:
        app.config.update(test_config)
    if state:
        register_blueprints(app=app, state=state)

    @app.context_processor
    def inject_static_version():
        # Cache-bust static assets so browser always pulls latest JS/CSS after deploy.
        try:
            style_path = os.path.join(static_dir, "style.css")
            static_version = int(os.path.getmtime(style_path))
        except Exception:
            static_version = 1
        return {"static_version": static_version}

    return app
