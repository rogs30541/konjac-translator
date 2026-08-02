"""PyInstaller 進入點:konjac-engine.exe。

固定綁 127.0.0.1:8765;資料在 ~/.konjac/。
vendor jt-live-whisper 以 KONJAC_VENDOR_DIR 或 C:\\jt-live-whisper 解析。
"""
import sys
from pathlib import Path

# --noconsole(windowed)模式下 stdout/stderr 為 None,
# uvicorn 寫 log 會炸 → 導向 ~/.konjac/engine.log(兼作診斷日誌)
if sys.stdout is None or sys.stderr is None:
    _log_dir = Path.home() / ".konjac"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log = open(_log_dir / "engine.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

# PyInstaller onefile 下 __file__ 在暫存解壓目錄,app 套件隨 exe 打包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import run  # noqa: E402

if __name__ == "__main__":
    run()
