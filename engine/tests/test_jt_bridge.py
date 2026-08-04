"""jt bridge 整合測試:fake 子程序 → TCP NDJSON → captions,與停止流程。"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                                        # noqa: E402
from app.main import create_app                                 # noqa: E402
from app.providers.cloud_llm import SettingsStore               # noqa: E402
from app.providers.jt_bridge import JtBridgeConfig, JtLiveBridge  # noqa: E402

FAKE_SCRIPT = Path(__file__).parent / "fake_jt.py"


def fake_factory(on_event):
    # port=0 → 臨時埠,經 KONJAC_JT_PORT 傳給 fake 子程序
    return JtLiveBridge(JtBridgeConfig(script=FAKE_SCRIPT, port=0), on_event)


@pytest.fixture()
def client(tmp_path):
    app = create_app(store=Store(":memory:"), bridge_factory=fake_factory,
                     settings_store=SettingsStore(tmp_path / "settings.json"))
    with TestClient(app) as c:
        yield c


def _wait_captions(client, sid, n, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        caps = client.get(f"/api/sessions/{sid}/captions").json()
        if len(caps) >= n:
            return caps
        time.sleep(0.1)
    raise AssertionError(f"expected {n} captions, got {len(caps)}")


def test_live_bridge_end_to_end(client):
    r = client.post("/api/live/start", json={
        "title": "橋接測試會議", "kind": "live", "mode": "en2zh"})
    assert r.status_code == 201
    sid = r.json()["id"]

    caps = _wait_captions(client, sid, 2)
    # 劇本 4 事件:status 不是字幕、空事件被略過 → 恰好 2 筆
    assert len(caps) == 2

    c1, c2 = caps
    assert c1["seq"] == 1 and c2["seq"] == 2
    assert c1["source_channel"] == "system"
    assert c1["source_text"] == "We need to finalize the Q3 roadmap."
    assert c1["translated_text"] == "我們需要確定第三季路線圖。"
    assert c1["is_final"] is True
    assert c2["source_channel"] == "mic"
    assert c2["translated_text"] is None
    assert c2["t_start"] >= c1["t_start"]

    # 錄製中不允許再開一場
    r = client.post("/api/live/start", json={"title": "第二場", "kind": "live"})
    assert r.status_code == 409

    # 停止:子程序被 terminate、session 標記 done
    r = client.post(f"/api/sessions/{sid}/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["ended_at"] is not None

    # 停止後可再開新的一場
    r = client.post("/api/live/start", json={"title": "第二場", "kind": "live"})
    assert r.status_code == 201
    client.post(f"/api/sessions/{r.json()['id']}/stop")


def test_live_bridge_ws_replay(client):
    r = client.post("/api/live/start", json={"title": "WS 補發", "kind": "live"})
    sid = r.json()["id"]
    _wait_captions(client, sid, 2)

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        replay = [ws.receive_json() for _ in range(2)]
        assert [e["data"]["seq"] for e in replay] == [1, 2]

    client.post(f"/api/sessions/{sid}/stop")


def test_live_watchdog_marks_error_on_process_death(client, monkeypatch):
    """上游 live 程序異常結束 → 看門狗把 session 標記 error 並廣播。"""
    monkeypatch.setenv("KONJAC_FAKE_LIVE_CRASH", "1")
    r = client.post("/api/live/start", json={"title": "崩潰測試", "kind": "live"})
    assert r.status_code == 201
    sid = r.json()["id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        s = client.get(f"/api/sessions/{sid}").json()["session"]
        if s["status"] == "error":
            break
        time.sleep(0.2)
    assert s["status"] == "error"
    assert s["ended_at"] is not None


def test_idle_auto_stop(client):
    """超過閒置逾時沒有新字幕 → 引擎自動停止錄製並標記 done。"""
    # 0.03 分鐘 = 1.8 秒;fake 送完 3 事件後掛著不動 → 觸發閒置
    client.put("/api/settings/app", json={"idle_stop_minutes": 0.03})
    r = client.post("/api/live/start", json={"title": "閒置測試", "kind": "live"})
    assert r.status_code == 201
    sid = r.json()["id"]

    deadline = time.time() + 15
    s = None
    while time.time() < deadline:
        s = client.get(f"/api/sessions/{sid}").json()["session"]
        if s["status"] != "recording":
            break
        time.sleep(0.3)
    assert s["status"] == "done", s
    assert s["ended_at"] is not None
    # 字幕仍保留(自動停止≠刪除)
    assert len(client.get(f"/api/sessions/{sid}/captions").json()) == 2
    client.put("/api/settings/app", json={"idle_stop_minutes": 5})


def test_live_unavailable_when_script_missing():
    missing = JtBridgeConfig(script=Path("D:/nope/translate_meeting.py"), port=0)

    def broken_factory(on_event):
        return JtLiveBridge(missing, on_event)

    app = create_app(store=Store(":memory:"), bridge_factory=broken_factory)
    with TestClient(app) as c:
        r = c.post("/api/live/start", json={"title": "x", "kind": "live"})
        assert r.status_code == 500
        # session 應標記 error 而非殘留 recording
        sessions = c.get("/api/sessions").json()
        assert sessions[0]["status"] == "error"
