"""匯出格式(md/txt/srt/vtt)與 NotebookLM 轉發流程。"""
from pathlib import Path

from conftest import ingest


def _seed(client, sid):
    ingest(client, sid, 1, "We need to finalize the Q3 roadmap.",
           "我們需要確定第三季路線圖。", speaker="S1", t0=838.0, t1=841.5)
    ingest(client, sid, 2, "I can share results by Friday.",
           "我週五前可以分享結果。", speaker="S2", t0=850.2, t1=853.0)
    client.patch(f"/api/sessions/{sid}/speakers/S1", json={"display_name": "王經理"})


def test_notebooklm_markdown_structure(client, live_session):
    """規格:標題 → 摘要 → 逐字稿(講者 + hh:mm:ss 時戳 + 原文縮排)。"""
    sid = live_session
    _seed(client, sid)
    client.post(f"/api/sessions/{sid}/summary")

    md = client.get(f"/api/sessions/{sid}/export?format=md").text
    lines = md.splitlines()

    assert lines[0].startswith("# 產品開發會議 — ")
    assert "## 摘要" in md
    assert "## 逐字稿" in md
    # 摘要必須在逐字稿之前
    assert md.index("## 摘要") < md.index("## 逐字稿")
    assert "[00:13:58] 王經理:我們需要確定第三季路線圖。" in md
    assert "    └ 原文:We need to finalize the Q3 roadmap." in md


def test_txt_srt_vtt(client, live_session):
    sid = live_session
    _seed(client, sid)

    txt = client.get(f"/api/sessions/{sid}/export?format=txt").text
    assert "[00:13:58] 王經理: 我們需要確定第三季路線圖。" in txt

    srt = client.get(f"/api/sessions/{sid}/export?format=srt").text
    assert "1\n00:13:58,000 --> 00:14:01,500\n我們需要確定第三季路線圖。" in srt

    vtt = client.get(f"/api/sessions/{sid}/export?format=vtt").text
    assert vtt.startswith("WEBVTT")
    assert "00:14:10.200 --> 00:14:13.000" in vtt

    assert client.get(f"/api/sessions/{sid}/export?format=doc").status_code == 400


def test_export_save_to_downloads(client, live_session, tmp_path):
    """實際存檔:寫入下載資料夾、檔名含標題與時間、內容完整。"""
    sid = live_session
    _seed(client, sid)
    r = client.post(f"/api/sessions/{sid}/export/save?format=md&reveal=false")
    assert r.status_code == 200
    body = r.json()
    p = Path(body["path"])
    assert p.is_file() and p.parent == tmp_path / "downloads"
    assert body["filename"].endswith(".md") and "產品開發會議" in body["filename"]
    content = p.read_text(encoding="utf-8-sig")
    assert "## 逐字稿" in content
    assert "我們需要確定第三季路線圖。" in content  # 完整逐字稿在檔內

    r2 = client.post(f"/api/sessions/{sid}/export/save?format=srt&reveal=false")
    assert Path(r2.json()["path"]).suffix == ".srt"
    assert client.post(
        f"/api/sessions/{sid}/export/save?format=doc&reveal=false").status_code == 400


def test_forward_notebooklm_and_dedupe(client, live_session):
    sid = live_session
    _seed(client, sid)
    client.post(f"/api/sessions/{sid}/summary")

    r = client.post(f"/api/sessions/{sid}/forward/notebooklm",
                    json={"target_notebook": "團隊會議紀錄 2026 Q3", "scope": "full"})
    assert r.status_code == 200
    body = r.json()
    assert body["payload_md"].startswith("# 產品開發會議")
    assert "## 逐字稿" in body["payload_md"]

    # 已轉發徽章:session 記錄目標與時間
    s = client.get(f"/api/sessions/{sid}").json()["session"]
    assert s["notebooklm_target"] == "團隊會議紀錄 2026 Q3"
    assert s["notebooklm_forwarded_at"] is not None

    # 防重複:再次轉發要 409,force 才放行
    r = client.post(f"/api/sessions/{sid}/forward/notebooklm",
                    json={"target_notebook": "另一本", "scope": "full"})
    assert r.status_code == 409
    r = client.post(f"/api/sessions/{sid}/forward/notebooklm?force=true",
                    json={"target_notebook": "另一本", "scope": "full"})
    assert r.status_code == 200


def test_forward_scope_summary_only(client, live_session):
    sid = live_session
    _seed(client, sid)
    client.post(f"/api/sessions/{sid}/summary")
    r = client.post(f"/api/sessions/{sid}/forward/notebooklm",
                    json={"target_notebook": "N", "scope": "summary_only"})
    payload = r.json()["payload_md"]
    assert "## 摘要" in payload
    assert "## 逐字稿" not in payload


def test_forward_scope_starred_only(client, live_session):
    sid = live_session
    _seed(client, sid)
    client.post(f"/api/sessions/{sid}/captions/2/star")
    r = client.post(f"/api/sessions/{sid}/forward/notebooklm",
                    json={"target_notebook": "N", "scope": "starred_only"})
    payload = r.json()["payload_md"]
    assert "我週五前可以分享結果。" in payload
    assert "我們需要確定第三季路線圖。" not in payload
