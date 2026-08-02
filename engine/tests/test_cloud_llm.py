"""雲端 LLM 層:settings CRUD、live 延遲翻譯、離線批次翻譯、雲端摘要。
全用 fake LLM(llm_factory 注入),不打真實 API。"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                                            # noqa: E402
from app.main import create_app                                     # noqa: E402
from app.providers.cloud_llm import LLMSettings, SettingsStore      # noqa: E402
from app.providers.jt_bridge import JtBridgeConfig, JtLiveBridge, JtOfflineBridge  # noqa: E402

FAKE_SCRIPT = Path(__file__).parent / "fake_jt.py"


class FakeLLM:
    """確定性假 LLM:翻譯加前綴,摘要含標記。"""

    def __init__(self, settings):
        self.s = settings

    async def translate(self, text, mode, topic=None):
        if mode not in ("en2zh", "zh2en", "ja2zh"):
            return None
        return f"[譯]{text}"

    async def list_models(self):
        if self.s.provider == "gemini":
            return ["gemini-2.5-pro", "gemini-2.5-flash",
                    "gemini-2.5-flash-lite", "gemini-2.5-flash-preview-tts"]
        raise RuntimeError(
            f"boom url?key={self.s.api_key} leaked")  # 測 Key 遮罩

    async def summarize(self, transcript_md, topic, template="general"):
        return (f"## 摘要\n- [雲端摘要][{template}] "
                f"共 {len(transcript_md.splitlines())} 行")


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        store=Store(":memory:"),
        bridge_factory=lambda cb: JtLiveBridge(
            JtBridgeConfig(script=FAKE_SCRIPT, port=0), cb),
        offline_pipeline=JtOfflineBridge(
            JtBridgeConfig(script=FAKE_SCRIPT, port=0), timeout=30.0),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        llm_factory=lambda s: FakeLLM(s))
    with TestClient(app) as c:
        yield c


def _configure(client):
    r = client.put("/api/settings", json={
        "provider": "anthropic", "api_key": "sk-test-1234567890abcd"})
    assert r.status_code == 200
    return r.json()


def test_settings_crud_and_masking(client):
    # 未設定
    s = client.get("/api/settings").json()
    assert s["configured"] is False
    # 設定後遮罩
    s = _configure(client)
    assert s["configured"] is True
    assert s["api_key_masked"].startswith("sk-tes")
    assert "1234567890" not in s["api_key_masked"]  # 完整 key 不外洩
    # 更新 provider 不重傳 key → key 保留
    s = client.put("/api/settings", json={"provider": "openai"}).json()
    assert s["configured"] is True
    # 清除 key
    s = client.put("/api/settings", json={"clear_key": True}).json()
    assert s["configured"] is False
    # health 顯示 llm 狀態
    assert client.get("/api/health").json()["llm"] is None


def test_settings_persist(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.save(LLMSettings(provider="gemini", api_key="k", model="m"))
    loaded = SettingsStore(tmp_path / "s.json").load()
    assert loaded.provider == "gemini" and loaded.configured


def _wait(cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_live_deferred_translation(client):
    """en2zh live:上游跑純轉錄(en),譯文由雲端 LLM 同 seq 補上。"""
    _configure(client)
    r = client.post("/api/live/start", json={
        "title": "雲端翻譯測試", "kind": "live", "mode": "en2zh",
        "topic": "產品開發"})
    assert r.status_code == 201
    sid = r.json()["id"]

    def translated():
        caps = client.get(f"/api/sessions/{sid}/captions").json()
        return (len(caps) >= 2
                and all(c["translated_text"] for c in caps))

    assert _wait(translated), client.get(f"/api/sessions/{sid}/captions").json()
    caps = client.get(f"/api/sessions/{sid}/captions").json()
    # fake_jt 的 live 劇本第一句已含上游譯文 → 不重譯;
    # 第二句(mic 中文無譯文)被 fake LLM 補上 [譯] 前綴
    assert any(c["translated_text"].startswith("[譯]") for c in caps)
    client.post(f"/api/sessions/{sid}/stop")


def test_offline_batch_translation(client):
    _configure(client)
    r = client.post("/api/offline/jobs",
                    files={"file": ("m_ok.wav", b"riff", "audio/wav")},
                    params={"mode": "en2zh", "diarize": False})
    job_id = r.json()["job_id"]

    def done():
        return client.get(f"/api/offline/jobs/{job_id}").json()["status"] != "processing"

    assert _wait(done, 15.0)
    job = client.get(f"/api/offline/jobs/{job_id}").json()
    assert job["status"] == "done"
    caps = client.get(f"/api/sessions/{job['session_id']}/captions").json()
    assert all(c["translated_text"] for c in caps)


def test_cloud_summary_when_configured(client):
    _configure(client)
    sid = client.post("/api/sessions", json={
        "title": "摘要測試", "kind": "live", "mode": "en"}).json()["id"]
    client.post(f"/api/sessions/{sid}/ingest", json={
        "seq": 1, "t_start": 0, "source_channel": "system",
        "source_text": "hello", "is_final": True})
    r = client.post(f"/api/sessions/{sid}/summary")
    assert "[雲端摘要]" in r.json()["content_md"]
    assert "[general]" in r.json()["content_md"]
    # 模板參數傳遞
    r = client.post(f"/api/sessions/{sid}/summary?template=interview")
    assert "[interview]" in r.json()["content_md"]


def test_list_models_and_recommend(client):
    # 未設定 → 400
    assert client.get("/api/settings/models").status_code == 400
    client.put("/api/settings", json={"provider": "gemini",
                                      "api_key": "sk-test-1234567890abcd"})
    r = client.get("/api/settings/models")
    assert r.status_code == 200
    body = r.json()
    assert "gemini-2.5-flash-lite" in body["models"]
    # CP 推薦:flash-lite 優先於 flash/pro;tts/preview 變體被降權
    assert body["recommended"] == "gemini-2.5-flash-lite"


def test_list_models_error_masks_key(client):
    client.put("/api/settings", json={"provider": "openai",
                                      "api_key": "sk-secret-9876543210xyz"})
    r = client.get("/api/settings/models")  # FakeLLM 對非 gemini 丟含 Key 例外
    assert r.status_code == 502
    assert "sk-secret-9876543210xyz" not in r.text
    assert "***KEY***" in r.text


def test_recommend_model_heuristics():
    from app.providers.cloud_llm import recommend_model
    assert recommend_model("anthropic", [
        "claude-opus-4-1", "claude-sonnet-4-5", "claude-haiku-4-5",
    ]) == "claude-haiku-4-5"
    assert recommend_model("openai", [
        "gpt-4o", "gpt-4o-mini", "gpt-4o-audio-preview", "o3-pro",
    ]) == "gpt-4o-mini"
    assert recommend_model("gemini", []) is None
    # 版本較新者優先(同為 flash)
    assert recommend_model("gemini", [
        "gemini-1.5-flash", "gemini-2.5-flash",
    ]) == "gemini-2.5-flash"


def test_mock_summary_when_not_configured(client):
    sid = client.post("/api/sessions", json={
        "title": "摘要測試2", "kind": "live", "mode": "en"}).json()["id"]
    client.post(f"/api/sessions/{sid}/ingest", json={
        "seq": 1, "t_start": 0, "source_channel": "system",
        "source_text": "hello", "is_final": True})
    r = client.post(f"/api/sessions/{sid}/summary")
    assert "mock 摘要" in r.json()["content_md"]
