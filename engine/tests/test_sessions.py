"""REST:session 生命週期(建立→錄製→停止→查詢→匯出→刪除)。"""
from conftest import ingest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_session_lifecycle(client, live_session):
    sid = live_session
    ingest(client, sid, 1, "Hello everyone.", "大家好。")

    r = client.post(f"/api/sessions/{sid}/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["ended_at"] is not None

    # 停止後不得再 ingest
    r = ingest(client, sid, 2, "late", "太遲了")
    assert r.status_code == 409

    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["session"]["title"] == "產品開發會議"

    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 204
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_unknown_session_404(client):
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/stop").status_code == 404


def test_partial_then_final_upsert(client, live_session):
    """partial 與 final 同 seq:final 覆蓋,資料庫只留一筆。"""
    sid = live_session
    ingest(client, sid, 1, "We need to fin", "我們需要確", final=False)
    ingest(client, sid, 1, "We need to finalize the roadmap.", "我們需要確定路線圖。",
           final=True)

    caps = client.get(f"/api/sessions/{sid}/captions").json()
    assert len(caps) == 1
    assert caps[0]["is_final"] is True
    assert caps[0]["translated_text"] == "我們需要確定路線圖。"


def test_star_caption(client, live_session):
    sid = live_session
    ingest(client, sid, 1, "Key decision here.", "關鍵決議。")
    assert client.post(f"/api/sessions/{sid}/captions/1/star").status_code == 200
    caps = client.get(f"/api/sessions/{sid}/captions").json()
    assert caps[0]["starred"] is True
    assert client.post(f"/api/sessions/{sid}/captions/99/star").status_code == 404


def test_speaker_auto_create_and_rename(client, live_session):
    """講者自動建檔、顏色穩定分配;改名後 detail 與匯出同步。"""
    sid = live_session
    ingest(client, sid, 1, "Hi.", "嗨。", speaker="S1")
    ingest(client, sid, 2, "Hello.", "你好。", speaker="S2")

    detail = client.get(f"/api/sessions/{sid}").json()
    names = {s["id"]: s for s in detail["speakers"]}
    assert names["S1"]["display_name"] == "Speaker 1"
    assert names["S2"]["display_name"] == "Speaker 2"
    assert names["S1"]["color"] != names["S2"]["color"]

    r = client.patch(f"/api/sessions/{sid}/speakers/S1",
                     json={"display_name": "王經理"})
    assert r.status_code == 200

    md = client.get(f"/api/sessions/{sid}/export?format=md").text
    assert "王經理" in md and "Speaker 1" not in md

    assert client.patch(f"/api/sessions/{sid}/speakers/S9",
                        json={"display_name": "無此人"}).status_code == 404


def test_search(client, live_session):
    sid = live_session
    ingest(client, sid, 1, "The roadmap is due Friday.", "路線圖週五截止。")
    hits = client.get("/api/search", params={"q": "路線圖"}).json()
    assert hits == [{"session_id": sid, "seq": 1}]
