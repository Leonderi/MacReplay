import os
import pytest

from macreplay.app_factory import create_app
from macreplay.db import init_db
from macreplay.config import loadConfig, getPortals
from macreplay.logging_setup import setup_logging


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("DB_PATH", "file:memdb1?mode=memory&cache=shared")
    monkeypatch.setenv("CONFIG", "/tmp/MacReplay.test.json")
    monkeypatch.setenv("DATA_DIR", "/tmp")
    monkeypatch.setenv("LOG_DIR", "/tmp")

    logger = setup_logging("/tmp")
    loadConfig()
    init_db(getPortals, logger)

    app = create_app(test_config={"TESTING": True})
    yield app
