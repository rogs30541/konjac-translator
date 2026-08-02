import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                          # noqa: E402
from app.main import create_app                   # noqa: E402
from app.providers.cloud_llm import SettingsStore  # noqa: E402


@pytest.fixture()
def store() -> Store:
    return Store(":memory:")


from app.providers.mock import MockOfflinePipeline  # noqa: E402


@pytest.fixture()
def client(store: Store, tmp_path):
    # settings 隔離 + 顯式 mock 離線管線(預設接線現在會抓真實 vendor)
    app = create_app(store=store,
                     offline_pipeline=MockOfflinePipeline(),
                     settings_store=SettingsStore(tmp_path / "settings.json"))
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def live_session(client) -> str:
    r = client.post("/api/sessions", json={
        "title": "產品開發會議", "kind": "live", "mode": "en2zh",
        "topic": "產品開發"})
    assert r.status_code == 201
    return r.json()["id"]


def ingest(client, sid: str, seq: int, text: str, zh: str, *,
           speaker: str | None = "S1", final: bool = True,
           t0: float = 0.0, t1: float | None = None, channel: str = "system"):
    r = client.post(f"/api/sessions/{sid}/ingest", json={
        "seq": seq, "t_start": t0, "t_end": t1 if t1 is not None else t0 + 3,
        "speaker_id": speaker, "source_channel": channel,
        "source_text": text, "translated_text": zh, "is_final": final})
    return r
