"""模擬 jt-live-whisper --webui 的假子程序:同一 TCP NDJSON 協定。

讀 KONJAC_JT_PORT 決定連線埠(真實上游寫死 19780)。
送出劇本事件後保持存活,直到被 terminate —— 用來驗證 stop() 三段停止。
"""
import argparse
import json
import os
import socket
import time

# 離線模式劇本:speaker 是 1-based int、timestamp 是音檔秒數區間。
# 上游 <1h 用 [MM:SS-MM:SS]、>=1h 用 [HH:MM:SS-HH:MM:SS],兩種都放
OFFLINE_EVENTS = [
    {"type": "progress", "stage": "辨識中", "detail": "1/3"},
    {"type": "transcription", "source": "main", "src_lang": "EN",
     "src_text": "Welcome to the quarterly review.",
     "dst_lang": "中", "dst_text": "歡迎參加季度檢討會。",
     "timestamp": "[00:01-00:04]", "speaker": 1},
    {"type": "transcription", "source": "main", "src_lang": "EN",
     "src_text": "Numbers look good this time.",
     "dst_lang": "中", "dst_text": "這次的數字看起來不錯。",
     "timestamp": "[01:00:05-01:00:08]", "speaker": 2},
    {"type": "transcription", "source": "main", "src_text": "",
     "dst_text": "", "timestamp": "[00:09-00:09]", "speaker": 1},
    {"type": "progress", "stage": "處理完成", "detail": "2 段 | 1.0s"},
]

EVENTS = [
    {"type": "status", "detail": "model loaded"},
    {"type": "transcription", "source": "main", "src_lang": "EN",
     "src_text": "We need to finalize the Q3 roadmap.",
     "dst_lang": "中", "dst_text": "我們需要確定第三季路線圖。",
     "asr_time": 0.8, "translate_time": 0.5, "timestamp": "14:00:01"},
    {"type": "transcription", "source": "mic", "src_lang": "中",
     "src_text": "好的收到。", "asr_time": 0.3, "timestamp": "14:00:03"},
    # 幻覺過濾後的空事件:引擎應略過
    {"type": "transcription", "source": "main", "src_text": "  ", "dst_text": ""},
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webui", action="store_true")
    parser.add_argument("--mode", default="en2zh")
    parser.add_argument("--input", nargs="+", default=None)
    parser.add_argument("--local-asr", action="store_true")
    parser.add_argument("--diarize", action="store_true")
    # 上游 live 參數(引擎會帶),fake 接受即可
    args, _unknown = parser.parse_known_args()

    if os.environ.get("KONJAC_FAKE_LIVE_CRASH") == "1" and not args.input:
        raise SystemExit(3)  # 模擬上游 live 啟動後立刻崩潰

    port = int(os.environ.get("KONJAC_JT_PORT", "19780"))
    conn = None
    for _ in range(10):
        try:
            conn = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            break
        except OSError:
            time.sleep(0.2)
    if conn is None:
        raise SystemExit(1)

    if args.input:
        # 離線模式:送完事件後正常結束(上游 process_audio_file 行為)
        # 內容為 b"bad" 的檔案模擬損壞音檔 → 非零退出
        with open(args.input[0], "rb") as f:
            if f.read(16) == b"bad":
                raise SystemExit(2)
        events = OFFLINE_EVENTS if args.diarize else [
            {**e, "speaker": None} for e in OFFLINE_EVENTS]
        for ev in events:
            conn.sendall((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
            time.sleep(0.02)
        while True:  # 模擬上游「按 ESC 鍵退出」:送完事件後不退出
            time.sleep(0.5)

    for ev in EVENTS:
        conn.sendall((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
        time.sleep(0.05)

    while True:  # 等待被 terminate
        time.sleep(0.5)


if __name__ == "__main__":
    main()
