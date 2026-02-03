def test_create_app_testing(app):
    assert app.config["TESTING"] is True
