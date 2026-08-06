"""錄後講者精析:離線重跑取代字幕、講者建檔、防呆。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                           # noqa: E402
from app.main import create_app                    # noqa: E402
from app.providers.cloud_llm import SettingsStore  # noqa: E402
from app.providers.mock import MockOfflinePipeline  # noqa: E402
from conftest import ingest                        # noqa: E402


@pytest.fixture()
def client(tmp_path):
    # Mock 離線管線回傳固定 2 句、S1/S2 講者 → 當作精析結果
    app = create_app(store=Store(":memory:"),
                     offline_pipeline=MockOfflinePipeline(),
                     settings_store=SettingsStore(tmp_path / "s.json"))
    with TestClient(app) as c:
        yield c


def _mk_done_session(client, rec: str | None):
    sid = client.post("/api/sessions", json={
        "title": "講者精析測試", "kind": "live", "mode": "en"}).json()["id"]
    for i in range(1, 6):
        ingest(client, sid, i, f"live sentence {i}", f"第{i}句", speaker=None,
               t0=i * 5.0, t1=i * 5.0 + 3)
    client.post(f"/api/sessions/{sid}/stop")
    if rec:
        client.app.state.store.set_recording_path(sid, rec)
    return sid


def test_diarize_replaces_with_offline_rerun(client, tmp_path):
    rec = tmp_path / "rec.mp3"
    rec.write_bytes(b"ID3")
    sid = _mk_done_session(client, str(rec))

    r = client.post(f"/api/sessions/{sid}/diarize")
    assert r.status_code == 200
    assert r.json()["updated"] == 2  # mock 離線管線輸出 2 句

    caps = client.get(f"/api/sessions/{sid}/captions").json()
    # 原 5 句 live 字幕被精析結果整批取代
    assert len(caps) == 2
    assert [c["speaker_id"] for c in caps] == ["S1", "S2"]
    assert caps[0]["t_start"] == 0.0  # 精析時間戳 = 真實音檔秒數
    speakers = client.get(f"/api/sessions/{sid}").json()["speakers"]
    assert {s["id"] for s in speakers} == {"S1", "S2"}


def test_diarize_requires_recording(client):
    sid = _mk_done_session(client, None)
    r = client.post(f"/api/sessions/{sid}/diarize")
    assert r.status_code == 400
    assert "錄音檔" in r.json()["detail"]


def test_diarize_rejects_while_recording(client, tmp_path):
    sid = client.post("/api/sessions", json={
        "title": "錄製中", "kind": "live", "mode": "en"}).json()["id"]
    rec = tmp_path / "r.mp3"
    rec.write_bytes(b"ID3")
    client.app.state.store.set_recording_path(sid, str(rec))
    assert client.post(f"/api/sessions/{sid}/diarize").status_code == 409