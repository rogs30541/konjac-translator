"""真實管線煙霧測試:TTS 合成音檔 → 上游 faster-whisper(CUDA)→ 引擎 API。

用法:.venv\\Scripts\\python smoke_real.py
不進 CI(需要 vendor venv + 模型);Phase 1 出口準則的手動驗證項。
"""
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import Store
from app.main import create_app
from app.providers.jt_bridge import JtBridgeConfig, JtOfflineBridge, VENDOR_PYTHON

WAV = Path(__file__).parent / "tests" / "fixtures" / "smoke_en.wav"

def main() -> int:
    assert WAV.is_file(), f"missing fixture: {WAV}"
    assert VENDOR_PYTHON.is_file(), f"vendor venv missing: {VENDOR_PYTHON}"

    # 真實上游寫死連 19780,不能用臨時埠
    offline = JtOfflineBridge(JtBridgeConfig(port=19780), timeout=600.0)
    app = create_app(store=Store(":memory:"), offline_pipeline=offline)

    t0 = time.time()
    with TestClient(app) as client:
        r = client.post(
            "/api/offline/jobs",
            files={"file": ("smoke_en.wav", WAV.read_bytes(), "audio/wav")},
            params={"mode": "en", "diarize": False, "title": "真實煙霧測試"})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        print(f"job {job_id} submitted, waiting for real ASR...", flush=True)

        while True:
            job = client.get(f"/api/offline/jobs/{job_id}").json()
            if job["status"] != "processing":
                break
            if time.time() - t0 > 600:
                print("TIMEOUT"); return 1
            time.sleep(2)

        elapsed = time.time() - t0
        print(f"job status: {job['status']} ({elapsed:.1f}s)")
        if job["status"] != "done":
            print("error:", job.get("error")); return 1

        sid = job["session_id"]
        caps = client.get(f"/api/sessions/{sid}/captions").json()
        print(f"\ncaptions ({len(caps)}):")
        for c in caps:
            print(f"  [{c['t_start']:7.2f}-{c['t_end'] or 0:7.2f}] {c['source_text']}")

        md = client.get(f"/api/sessions/{sid}/export?format=md").text
        print("\n--- NotebookLM markdown (head) ---")
        print("\n".join(md.splitlines()[:12]))

        text = " ".join(c["source_text"].lower() for c in caps)
        expected = ["quarterly", "revenue", "roadmap"]
        hits = [w for w in expected if w in text]
        print(f"\nkeyword check: {hits} / {expected}")
        if len(hits) < 2:
            print("SMOKE FAIL: transcript missing expected keywords"); return 1

    print("\nSMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
