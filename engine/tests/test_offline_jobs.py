"""離線批次任務:上傳→處理→查詢;格式驗證與錯誤處理。"""
import time


def _wait_done(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/offline/jobs/{job_id}").json()
        if job["status"] != "processing":
            return job
        time.sleep(0.05)
    raise AssertionError("offline job did not finish in time")


def test_offline_job_happy_path(client):
    r = client.post("/api/offline/jobs",
                    files={"file": ("meeting.wav", b"fake-wav-bytes", "audio/wav")},
                    params={"mode": "en2zh", "diarize": True, "title": "訪談檔"})
    assert r.status_code == 202
    job = _wait_done(client, r.json()["job_id"])
    assert job["status"] == "done"

    sid = job["session_id"]
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["session"]["kind"] == "offline"
    assert s["session"]["status"] == "done"
    assert s["session"]["title"] == "訪談檔"

    caps = client.get(f"/api/sessions/{sid}/captions").json()
    assert len(caps) == 2
    assert {c["speaker_id"] for c in caps} == {"S1", "S2"}
    assert len(s["speakers"]) == 2  # diarize=True 建立講者檔


def test_offline_job_no_diarize(client):
    r = client.post("/api/offline/jobs",
                    files={"file": ("talk.mp3", b"x", "audio/mpeg")},
                    params={"diarize": False})
    job = _wait_done(client, r.json()["job_id"])
    sid = job["session_id"]
    caps = client.get(f"/api/sessions/{sid}/captions").json()
    assert all(c["speaker_id"] is None for c in caps)


def test_offline_job_bad_format_rejected(client):
    r = client.post("/api/offline/jobs",
                    files={"file": ("doc.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 400
    assert "unsupported format" in r.json()["detail"]


def test_offline_job_not_found(client):
    assert client.get("/api/offline/jobs/nope").status_code == 404
