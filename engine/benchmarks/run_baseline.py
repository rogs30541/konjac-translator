"""AI 基準線執行器(測試規劃書 §4):對評測集跑真實管線,產出 baseline.json。

用法:engine\\.venv\\Scripts\\python benchmarks\\run_baseline.py [--out baseline.json]
需要 vendor venv + faster-whisper 模型(推薦安裝已完成)。之後模型/參數變動
重跑本腳本,與既有 baseline 比較(劣化 >10% 相對值視為回歸)。

註:目前音檔為 TTS 合成(bootstrap 基準線);真人錄音評測集補齊後應重建基準。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jiwer  # noqa: E402

from app.providers.jt_bridge import JtBridgeConfig, JtOfflineBridge  # noqa: E402

BENCH = Path(__file__).resolve().parent
AUDIO = BENCH / "audio"
TRUTH = BENCH / "truth"


def norm_en(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s']", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_zh(s: str) -> str:
    s = re.sub(r"[^一-鿿0-9a-zA-Z]", "", s)
    return s


async def transcribe(path: Path, mode: str, diarize: bool):
    bridge = JtOfflineBridge(JtBridgeConfig(port=19780), timeout=600.0)
    t0 = time.monotonic()
    caps = await bridge.transcribe_file(str(path), mode=mode, diarize=diarize)
    return caps, round(time.monotonic() - t0, 1)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BENCH / "baseline.json"))
    args = parser.parse_args()

    results: dict = {"note": "TTS bootstrap baseline; model=large-v3-turbo local CUDA",
                     "fixtures": {}}

    # ---- fx01_en:英文 WER ----
    truth = norm_en(" ".join((TRUTH / "fx01_en.txt").read_text(encoding="utf-8").split()))
    caps, secs = await transcribe(AUDIO / "fx01_en.wav", "en", diarize=False)
    hyp = norm_en(" ".join(c.source_text for c in caps))
    wer = round(jiwer.wer(truth, hyp), 4)
    results["fixtures"]["fx01_en"] = {"wer": wer, "segments": len(caps), "seconds": secs}
    print(f"fx01_en  WER={wer}  segs={len(caps)}  {secs}s", flush=True)

    # ---- fx01_zh:中文 CER ----
    truth = norm_zh((TRUTH / "fx01_zh.txt").read_text(encoding="utf-8"))
    caps, secs = await transcribe(AUDIO / "fx01_zh.wav", "zh", diarize=False)
    hyp = norm_zh("".join(c.source_text for c in caps))
    cer = round(jiwer.cer(truth, hyp), 4)
    results["fixtures"]["fx01_zh"] = {"cer": cer, "segments": len(caps), "seconds": secs}
    print(f"fx01_zh  CER={cer}  segs={len(caps)}  {secs}s", flush=True)

    # ---- fx02:雙講者對話 WER + 講者數 ----
    lines = [l.split("|", 1)[1] for l in
             (TRUTH / "fx02_dialog.txt").read_text(encoding="utf-8").splitlines() if l]
    truth = norm_en(" ".join(lines))
    caps, secs = await transcribe(AUDIO / "fx02_dialog.wav", "en", diarize=True)
    hyp = norm_en(" ".join(c.source_text for c in caps))
    wer = round(jiwer.wer(truth, hyp), 4)
    n_spk = len({c.speaker_id for c in caps if c.speaker_id})
    results["fixtures"]["fx02_dialog"] = {
        "wer": wer, "segments": len(caps), "speakers_detected": n_spk,
        "speakers_expected": 2, "seconds": secs}
    print(f"fx02     WER={wer}  speakers={n_spk}/2  {secs}s", flush=True)

    # ---- fx07_silence:幻覺檢查(靜音不得產字)----
    caps, secs = await transcribe(AUDIO / "fx07_silence.wav", "en", diarize=False)
    text = "".join(c.source_text for c in caps).strip()
    results["fixtures"]["fx07_silence"] = {
        "captions": len(caps), "hallucinated_chars": len(text), "seconds": secs,
        "pass": len(text) == 0}
    print(f"fx07_silence  captions={len(caps)} chars={len(text)}"
          f"  {'PASS' if not text else 'HALLUCINATION!'}", flush=True)

    # ---- fx07_tiny:極短檔不得 crash ----
    try:
        caps, secs = await transcribe(AUDIO / "fx07_tiny.wav", "en", diarize=False)
        results["fixtures"]["fx07_tiny"] = {"ok": True, "captions": len(caps)}
        print(f"fx07_tiny  OK captions={len(caps)}", flush=True)
    except Exception as e:
        results["fixtures"]["fx07_tiny"] = {"ok": False, "error": str(e)}
        print(f"fx07_tiny  ERROR {e}", flush=True)

    # ---- fx07_corrupt:損壞檔應明確失敗、不得掛死 ----
    try:
        await transcribe(AUDIO / "fx07_corrupt.wav", "en", diarize=False)
        results["fixtures"]["fx07_corrupt"] = {"ok": False,
                                               "note": "expected failure but succeeded"}
        print("fx07_corrupt  UNEXPECTED SUCCESS", flush=True)
    except Exception as e:
        results["fixtures"]["fx07_corrupt"] = {"ok": True,
                                               "error_type": type(e).__name__}
        print(f"fx07_corrupt  expected failure: {type(e).__name__}", flush=True)

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nbaseline written -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
