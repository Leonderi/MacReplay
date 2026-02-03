import os
import secrets
from flask import Flask

from macreplay.blueprints.registry import register_blueprints


def create_app(*, register_params=None):
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    templates_dir = os.path.join(base_dir, "templates")
    static_dir = os.path.join(base_dir, "static")
    app = Flask(__name__, template_folder=templates_dir, static_folder=static_dir)
    app.secret_key = secrets.token_urlsafe(32)
    if register_params:
        register_blueprints(app=app, **register_params)
    return app
