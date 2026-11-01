from datetime import datetime

import pytest

from backend import campus_api

NOW = datetime(2026, 11, 4, 12, 0)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_DB", str(tmp_path / "campus.db"))
    monkeypatch.setattr(campus_api, "_now", lambda: NOW)
    campus_api.init_db(reset=True)
    return campus_api
