"""JtOfflineBridge:離線事件收集、時戳/講者解析、錯誤處理。"""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Store                                          # noqa: E402
from app.main import create_app                                   # noqa: E402
from app.providers.cloud_llm import SettingsStore                 # noqa: E402
from app.providers.jt_bridge import JtBridgeConfig, JtOfflineBridge  # noqa: E402

FAKE_SCRIPT = Path(__file__).parent / "fake_jt.py"


@pytest.fixture()
def client(tmp_path):
    offline = JtOfflineBridge(JtBridgeConfig(script=FAKE_SCRIPT, port=0),
                              timeout=30.0)
    app = create_app(store=Store(":memory:"), offline_pipeline=offline,
                     settings_store=SettingsStore(tmp_path / "settings.json"))
    with TestClient(app) as c:
        yield c


def _wait_done(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/offline/jobs/{job_id}").json()
        if job["status"] != "processing":
            return job
        time.sleep(0.1)
    raise AssertionError("offline job did not finish in time")


def test_offline_bridge_diarized(client):
    r = client.post("/api/offline/jobs",
                    files={"file": ("meeting_ok.wav", b"riff", "audio/wav")},
                    params={"mode": "en2zh", "diarize": True})
    job = _wait_done(client, r.json()["job_id"])
    assert job["status"] == "done", job

    sid = job["session_id"]
    caps = client.get(f"/api/sessions/{sid}/captions").json()
    # 劇本 4 事件:progress 不算、空 transcription 濾掉 → 2 筆,seq 連續
    assert [c["seq"] for c in caps] == [1, 2]
    # [MM:SS-MM:SS] 與 [HH:MM:SS-HH:MM:SS] 兩種時戳都解析為音檔秒數
    assert caps[0]["t_start"] == 1.0 and caps[0]["t_end"] == 4.0
    assert caps[1]["t_start"] == 3605.0 and caps[1]["t_end"] == 3608.0
    # 上游 int speaker → "S{n}",並自動建講者檔
    assert [c["speaker_id"] for c in caps] == ["S1", "S2"]
    speakers = client.get(f"/api/sessions/{sid}").json()["speakers"]
    assert len(speakers) == 2
    assert caps[0]["translated_text"] == "歡迎參加季度檢討會。"


def test_offline_bridge_no_diarize(client):
    r = client.post("/api/offline/jobs",
                    files={"file": ("talk_ok.wav", b"riff", "audio/wav")},
                    params={"mode": "en", "diarize": False})
    job = _wait_done(client, r.json()["job_id"])
    assert job["status"] == "done"
    caps = client.get(f"/api/sessions/{job['session_id']}/captions").json()
    assert all(c["speaker_id"] is None for c in caps)


def test_offline_bridge_process_failure(client):
    """子程序非零退出 → job error、session error,不 crash 引擎。"""
    r = client.post("/api/offline/jobs",
                    files={"file": ("crash.wav", b"bad", "audio/wav")})
    job = _wait_done(client, r.json()["job_id"])
    assert job["status"] == "error"
    assert "exited with" in job["error"]
    s = client.get(f"/api/sessions/{job['session_id']}").json()["session"]
    assert s["status"] == "error"
