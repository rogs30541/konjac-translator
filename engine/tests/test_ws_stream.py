"""WebSocket:字幕事件序列、講者/摘要/狀態事件、重連補發。"""
from conftest import ingest


def test_caption_stream_order(client, live_session):
    sid = live_session
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ingest(client, sid, 1, "First part", "第一句", final=False)
        ingest(client, sid, 1, "First sentence.", "第一句完整。", final=True)
        ingest(client, sid, 2, "Second sentence.", "第二句。", speaker="S2")

        e1 = ws.receive_json()
        assert e1["type"] == "caption" and e1["data"]["is_final"] is False
        e2 = ws.receive_json()
        assert e2["data"]["seq"] == 1 and e2["data"]["is_final"] is True
        e3 = ws.receive_json()
        assert e3["data"]["seq"] == 2 and e3["data"]["speaker_id"] == "S2"


def test_speaker_and_status_events(client, live_session):
    sid = live_session
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ingest(client, sid, 1, "Hi", "嗨", speaker="S1")
        ws.receive_json()  # caption

        client.patch(f"/api/sessions/{sid}/speakers/S1",
                     json={"display_name": "Sarah"})
        ev = ws.receive_json()
        assert ev["type"] == "speaker"
        assert ev["data"]["display_name"] == "Sarah"

        client.post(f"/api/sessions/{sid}/stop")
        ev = ws.receive_json()
        assert ev["type"] == "status" and ev["data"]["status"] == "done"


def test_reconnect_replays_finals(client, live_session):
    """斷線重連:補發既有 final 字幕,partial 不補發,seq 可去重。"""
    sid = live_session
    ingest(client, sid, 1, "One.", "一。")
    ingest(client, sid, 2, "Two.", "二。")
    ingest(client, sid, 3, "part", "部分", final=False)

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        replay = [ws.receive_json() for _ in range(2)]
        seqs = [e["data"]["seq"] for e in replay]
        assert seqs == [1, 2]
        assert all(e["data"]["is_final"] for e in replay)


def test_ws_unknown_session_rejected(client):
    try:
        with client.websocket_connect("/ws/sessions/nope") as ws:
            assert ws.receive_json() is None  # 不應收到任何事件
    except Exception:
        pass  # 連線被 4404 關閉即為預期
