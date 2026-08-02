"""Phase 4 批次一:app settings、關鍵字通知、webhook 轉發、保留清理。"""
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                           # noqa: E402
from app.main import create_app                    # noqa: E402
from app.providers.cloud_llm import SettingsStore  # noqa: E402
from conftest import ingest                        # noqa: E402


@pytest.fixture()
def env(tmp_path):
    """回傳 (client, sent_requests):webhook 經 MockTransport 捕捉。"""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    client_httpx = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(store=Store(":memory:"),
                     settings_store=SettingsStore(tmp_path / "settings.json"),
                     webhook_client=client_httpx)
    with TestClient(app) as c:
        yield c, sent


def _mk_session(client):
    return client.post("/api/sessions", json={
        "title": "P4 測試", "kind": "live", "mode": "en"}).json()["id"]


def test_app_settings_crud_and_persist(env, tmp_path):
    client, _ = env
    s = client.get("/api/settings/app").json()
    assert s["keywords"] == [] and s["webhooks"] == []
    assert s["retention_days"] == 0 and s["vendor_dir"] == ""
    assert "vendor_available" in s and "vendor_resolved" in s

    r = client.put("/api/settings/app", json={
        "keywords": ["roadmap", " deadline ", ""],
        "webhooks": [{"type": "discord", "url": "https://d.example/hook"}],
        "retention_days": 30})
    assert r.status_code == 200
    s = r.json()
    assert s["keywords"] == ["roadmap", "deadline"]  # 去空白、濾空字串
    assert s["retention_days"] == 30

    # 與 LLM 設定同檔互不覆蓋
    client.put("/api/settings", json={"provider": "openai", "api_key": "k"})
    assert client.get("/api/settings/app").json()["keywords"] == ["roadmap", "deadline"]
    assert client.get("/api/settings").json()["provider"] == "openai"


def test_keyword_event_broadcast(env):
    client, _ = env
    client.put("/api/settings/app", json={"keywords": ["roadmap", "預算"]})
    sid = _mk_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ingest(client, sid, 1, "We must fix the ROADMAP today.", "今天要確定路線圖。")
        ev1 = ws.receive_json()
        assert ev1["type"] == "caption"
        ev2 = ws.receive_json()
        assert ev2["type"] == "keyword"
        assert ev2["data"] == {"keyword": "roadmap", "seq": 1}  # 大小寫不敏感

        # 譯文命中也算
        ingest(client, sid, 2, "budget talk", "預算討論")
        assert ws.receive_json()["type"] == "caption"
        ev = ws.receive_json()
        assert ev["type"] == "keyword" and ev["data"]["keyword"] == "預算"

        # 無命中:只有 caption 事件
        ingest(client, sid, 3, "nothing here", "沒東西")
        assert ws.receive_json()["type"] == "caption"
        ingest(client, sid, 4, "ping", "乒")
        assert ws.receive_json()["data"]["seq"] == 4  # 中間沒有多餘 keyword 事件


def test_webhook_forwarding(env):
    client, sent = env
    client.put("/api/settings/app", json={"webhooks": [
        {"type": "discord", "url": "https://d.example/hook"},
        {"type": "slack", "url": "https://s.example/hook"},
        {"type": "telegram", "bot_token": "123:abc", "chat_id": "42"},
        {"type": "generic", "url": "https://g.example/hook"},
    ]})
    sid = _mk_session(client)
    ingest(client, sid, 1, "Hello world.", "哈囉世界。", speaker="S1")
    # after_caption 的 webhook 是 fire-and-forget task → 以停止請求驅動 loop 收尾
    client.post(f"/api/sessions/{sid}/stop")

    assert len(sent) == 4
    urls = {str(r.url) for r in sent}
    assert "https://api.telegram.org/bot123:abc/sendMessage" in urls
    import json as _json
    discord = next(r for r in sent if "d.example" in str(r.url))
    body = _json.loads(discord.content)
    assert "哈囉世界。" in body["content"]
    assert "P4 測試" in body["content"]
    generic = next(r for r in sent if "g.example" in str(r.url))
    gbody = _json.loads(generic.content)
    assert gbody["source_text"] == "Hello world." and gbody["seq"] == 1

    # partial 不轉發
    sid2 = _mk_session(client)
    n_before = len(sent)
    ingest(client, sid2, 1, "part", "部分", final=False)
    client.post(f"/api/sessions/{sid2}/stop")
    assert len(sent) == n_before


def test_retention_cleanup(env):
    client, _ = env
    sid_old = _mk_session(client)
    sid_new = _mk_session(client)
    # 把一筆改成 40 天前
    store: Store = client.app.state.store
    store._conn.execute(
        "UPDATE sessions SET created_at = datetime('now', '-40 days') WHERE id=?",
        (sid_old,))
    store._conn.commit()

    client.put("/api/settings/app", json={"retention_days": 30})
    r = client.post("/api/maintenance/cleanup")
    assert r.json()["deleted_sessions"] == 1
    assert client.get(f"/api/sessions/{sid_old}").status_code == 404
    assert client.get(f"/api/sessions/{sid_new}").status_code == 200

    # retention_days=0 = 不清理
    client.put("/api/settings/app", json={"retention_days": 0})
    assert client.post("/api/maintenance/cleanup").json()["deleted_sessions"] == 0


def test_vendor_dir_setting(env, tmp_path):
    """設定頁指定 AI 管線位置 → 即時生效(不需重啟引擎)。"""
    from app.providers.jt_bridge import set_vendor_override
    client, _ = env
    try:
        fake_vendor = tmp_path / "my-jt"
        fake_vendor.mkdir()
        # 路徑存在但沒有 translate_meeting.py → 覆寫無效,退回自動解析
        s = client.put("/api/settings/app",
                       json={"vendor_dir": str(fake_vendor)}).json()
        assert s["vendor_resolved"] != str(fake_vendor)
        # 放入腳本 → 立即可用,解析路徑指向設定值
        (fake_vendor / "translate_meeting.py").write_text("# stub")
        s = client.get("/api/settings/app").json()
        assert s["vendor_available"] is True
        assert s["vendor_resolved"] == str(fake_vendor)
        # health 同步反映
        h = client.get("/api/health").json()
        assert h["vendor_available"] is True
        # 清空設定 → 回到自動解析
        s = client.put("/api/settings/app", json={"vendor_dir": ""}).json()
        assert s["vendor_resolved"] != str(fake_vendor)
    finally:
        set_vendor_override(None)  # 不汙染其他測試(模組層全域)
