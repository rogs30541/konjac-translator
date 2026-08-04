"""音訊路徑診斷:找出系統聲音實際渲染到哪個輸出裝置。

上游 WASAPI loopback 只抓「預設輸出裝置」;使用者常見問題是聲音走了
別的裝置(HDMI 螢幕喇叭、USB 耳機)導致零字幕。本模組用 vendor venv
(有 pyaudiowpatch)對所有 loopback 裝置各收 2 秒,量測 frames/RMS。
"""
from __future__ import annotations

import asyncio
import json

from .jt_bridge import CREATE_NO_WINDOW, _default_python, vendor_available

_PROBE_CODE = r"""
import json, math, struct, time
import pyaudiowpatch as pyaudio

p = pyaudio.PyAudio()
try:
    default_idx = p.get_default_wasapi_loopback().get("index")
except Exception:
    default_idx = None

out = []
for info in p.get_loopback_device_info_generator():
    acc = {"total": 0.0, "n": 0}

    def cb(in_data, frame_count, time_info, status):
        samples = struct.unpack("<%dh" % (len(in_data) // 2), in_data)
        if samples:
            acc["total"] += math.sqrt(sum(s * s for s in samples) / len(samples))
            acc["n"] += 1
        return (None, pyaudio.paContinue)

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=min(2, info["maxInputChannels"]),
            rate=int(info["defaultSampleRate"]),
            input=True, input_device_index=info["index"],
            frames_per_buffer=1024, stream_callback=cb)
        time.sleep(2.0)
        stream.stop_stream(); stream.close()
        rms = acc["total"] / max(acc["n"], 1) / 32768
        out.append({"index": info["index"], "name": info["name"],
                    "is_default": info["index"] == default_idx,
                    "frames": acc["n"], "rms": round(rms, 4),
                    "active": acc["n"] > 0 and rms > 0.001})
    except Exception as e:
        out.append({"index": info["index"], "name": info["name"],
                    "is_default": info["index"] == default_idx,
                    "error": type(e).__name__})
p.terminate()
print(json.dumps(out, ensure_ascii=False))
"""


async def probe_audio(timeout: float = 30.0) -> dict:
    """回傳 {devices: [...], advice: str}。播放聲音時執行才有意義。"""
    if not vendor_available():
        return {"devices": [], "advice": "AI 管線未設定,無法診斷(需要 vendor venv)"}
    proc = await asyncio.create_subprocess_exec(
        _default_python(), "-c", _PROBE_CODE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW)
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"devices": [], "advice": "診斷逾時"}
    try:
        devices = json.loads(stdout.decode("utf-8", "replace").strip() or "[]")
    except json.JSONDecodeError:
        return {"devices": [],
                "advice": f"診斷失敗:{stderr.decode('utf-8', 'replace')[:200]}"}

    active = [d for d in devices if d.get("active")]
    default = next((d for d in devices if d.get("is_default")), None)
    if not active:
        advice = ("沒有偵測到任何裝置正在播放聲音。請先開始播放影片/音訊,"
                  "播放中再按一次診斷。")
    elif any(d.get("is_default") for d in active):
        advice = (f"✓ 音訊路徑正常:聲音正在預設裝置「{default['name']}」上播放,"
                  "轉錄應可收到音訊。若仍無字幕,請查看 ~/.konjac/jt-upstream.log。")
    else:
        names = "、".join(d["name"] for d in active)
        advice = (f"⚠ 找到問題:聲音在「{names}」播放,但轉錄只抓預設裝置"
                  f"「{default['name'] if default else '?'}」。解法(擇一):"
                  "① Windows 音效設定把正在播放的裝置設為「預設輸出」;"
                  "② 把播放程式的輸出切到預設裝置。切換後重新開始錄製。")
    return {"devices": devices, "advice": advice}
