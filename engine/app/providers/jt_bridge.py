"""jt-live-whisper 子程序橋接。

上游協定(vendor/jt-live-whisper):以 `--webui` 啟動時,translate_meeting.py
會以 TCP client 連到 127.0.0.1:19780,送出換行分隔的 JSON 事件(NDJSON)。
本模組反向實作 webui.py 的接收端:開 TCP server、spawn 子程序、
把事件交給 on_event callback。

真實腳本固定連 19780;測試用 fake 腳本讀 KONJAC_JT_PORT 環境變數,
因此測試可用臨時埠並行。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

OnEvent = Callable[[dict], Awaitable[None]]


def _upstream_log():
    """上游輸出寫到 ~/.konjac/jt-upstream.log(取代丟棄,便於診斷)。"""
    try:
        log_dir = Path.home() / ".konjac"
        log_dir.mkdir(parents=True, exist_ok=True)
        return open(log_dir / "jt-upstream.log", "ab")
    except OSError:
        return asyncio.subprocess.DEVNULL


async def _auto_confirm(proc: asyncio.subprocess.Process) -> None:
    """上游即使參數齊全仍會問「確認開始?(Y/n)」(_confirm_start),
    經 stdin 送 y 自動確認;pipe 保持開啟避免後續 read 收到 EOF 取消。"""
    if proc.stdin is not None:
        proc.stdin.write(b"y\n")
        try:
            await proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass  # 子程序未讀 stdin(fake/已退出)是正常情況

# 設定頁指定的路徑(app 啟動與存檔時呼叫 set_vendor_override)
_vendor_override: Optional[Path] = None


def set_vendor_override(path: str | None) -> None:
    global _vendor_override
    _vendor_override = Path(path) if path else None


def vendor_dir() -> Path:
    """jt-live-whisper 位置,call-time 四段解析(設定可即時生效):
    1. 設定頁指定的路徑(settings.json 的 vendor_dir)
    2. KONJAC_VENDOR_DIR 環境變數
    3. repo 相對路徑(開發模式)
    4. C:\\jt-live-whisper(上游 install.ps1 一鍵安裝的預設位置)"""
    if (_vendor_override
            and (_vendor_override / "translate_meeting.py").is_file()):
        return _vendor_override
    env = os.environ.get("KONJAC_VENDOR_DIR")
    if env and (Path(env) / "translate_meeting.py").is_file():
        return Path(env)
    dev = Path(__file__).resolve().parents[3] / "vendor" / "jt-live-whisper"
    if (dev / "translate_meeting.py").is_file():
        return dev
    return Path(r"C:\jt-live-whisper")


def vendor_script() -> Path:
    return vendor_dir() / "translate_meeting.py"


def vendor_available() -> bool:
    return vendor_script().is_file()


def _default_python() -> str:
    # 上游依賴(faster-whisper/torch 等)裝在 vendor venv,存在就優先用
    py = vendor_dir() / "venv" / "Scripts" / "python.exe"
    return str(py) if py.is_file() else sys.executable


@dataclass
class JtBridgeConfig:
    script: Path = field(default_factory=vendor_script)
    python_exe: str = field(default_factory=_default_python)
    port: int = 19780          # 上游寫死的埠;測試傳 0 取臨時埠
    extra_args: list[str] = field(default_factory=list)


class JtLiveBridge:
    """一個 bridge 綁一場即時 session:start() 後事件持續流入 on_event。"""

    def __init__(self, config: JtBridgeConfig, on_event: OnEvent):
        self._cfg = config
        self._on_event = on_event
        self._server: Optional[asyncio.AbstractServer] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._closed = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self, mode: str) -> None:
        if not self._cfg.script.is_file():
            raise FileNotFoundError(f"jt script not found: {self._cfg.script}")
        # 先開 server 再 spawn,子程序重試 3 次連線的窗口內必定就緒
        self._server = await asyncio.start_server(
            self._handle_conn, "127.0.0.1", self._cfg.port)
        actual_port = self._server.sockets[0].getsockname()[1]

        env = dict(os.environ)
        env["KONJAC_JT_PORT"] = str(actual_port)
        # live 必要參數(Windows):
        # --asr faster-whisper:whisper.cpp 未編譯,用已裝的 faster-whisper CUDA
        # -d -100:WASAPI Loopback sentinel,跳過會 hard-exit 的 GGML 模型探測
        log = _upstream_log()
        self._proc = await asyncio.create_subprocess_exec(
            self._cfg.python_exe, str(self._cfg.script),
            "--webui", "--mode", mode,
            "--asr", "faster-whisper", "--local-asr", "-d", "-100",
            *self._cfg.extra_args,
            cwd=str(self._cfg.script.parent), env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=log, stderr=asyncio.subprocess.STDOUT)
        await _auto_confirm(self._proc)

    async def wait_proc(self) -> int | None:
        """等待子程序結束,回傳 returncode(給 LiveRunner 看門狗用)。"""
        if self._proc is None:
            return None
        return await self._proc.wait()

    async def _handle_conn(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> None:
        try:
            while not self._closed:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue  # 壞行直接略過,不中斷串流
                await self._on_event(event)
        except (ConnectionResetError, OSError):
            pass  # 子程序被 terminate 時連線必然中斷,非錯誤
        finally:
            writer.close()

    async def stop(self) -> None:
        """graceful terminate → 3 秒後 kill(參考上游 webui.py 三段停止)。"""
        self._closed = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class JtOfflineBridge:
    """離線管線:上游 process_audio_file 在 --webui 模式同樣經 TCP 送
    transcription 事件(帶 speaker 與 [HH:MM:SS-HH:MM:SS] 時戳),
    因此離線與即時共用同一條事件通道,不解析 log 檔。

    需要 vendor venv(含 faster-whisper 與模型);translator 相關模式
    (en2zh 等)另需 Ollama/NLLB,純轉錄用 mode=en/zh/ja。
    """

    def __init__(self, config: Optional[JtBridgeConfig] = None,
                 timeout: float = 3600.0):
        self._cfg = config or JtBridgeConfig()
        self._timeout = timeout

    async def transcribe_file(self, path: str, mode: str,
                              diarize: bool) -> list:
        from ..live import event_to_caption  # 延遲載入避免循環 import

        events: list[dict] = []
        done = asyncio.Event()

        async def on_event(ev: dict) -> None:
            if ev.get("type") == "transcription":
                events.append(ev)
            # 上游處理完成後會「按 ESC 鍵退出」永不退出,
            # 以完成事件為訊號,由我們主動終止子程序
            elif (ev.get("type") == "progress"
                  and "完成" in str(ev.get("stage", ""))
                  and "處理" in str(ev.get("stage", ""))):
                done.set()

        bridge = JtLiveBridge(self._cfg, on_event)
        if not self._cfg.script.is_file():
            raise FileNotFoundError(f"jt script not found: {self._cfg.script}")
        bridge._server = await asyncio.start_server(
            bridge._handle_conn, "127.0.0.1", self._cfg.port)
        actual_port = bridge._server.sockets[0].getsockname()[1]

        env = dict(os.environ)
        env["KONJAC_JT_PORT"] = str(actual_port)
        args = [self._cfg.python_exe, str(self._cfg.script),
                "--webui", "--input", path, "--mode", mode,
                "--local-asr", *self._cfg.extra_args]
        if diarize:
            args.append("--diarize")
        bridge._proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(self._cfg.script.parent), env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await _auto_confirm(bridge._proc)

        try:
            # 兩種結束方式取先到者:完成事件(真實上游,之後卡 ESC)
            # 或程序自行退出(fake / 錯誤)
            proc_task = asyncio.ensure_future(bridge._proc.wait())
            done_task = asyncio.ensure_future(done.wait())
            finished, pending = await asyncio.wait(
                {proc_task, done_task},
                timeout=self._timeout,
                return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            if not finished:
                raise TimeoutError(
                    f"jt offline pipeline timed out after {self._timeout}s")
            if done.is_set():
                await asyncio.sleep(0.3)  # 收尾:等最後幾個事件送達
            elif bridge._proc.returncode != 0:
                raise RuntimeError(
                    f"jt offline process exited with {bridge._proc.returncode}")
        finally:
            await bridge.stop()

        caps = []
        for i, ev in enumerate(events, 1):
            cap = event_to_caption(ev, i, t_default=float(i))
            if cap:
                caps.append(cap)
        # 重新編號(空事件被濾掉後 seq 需連續)
        for i, cap in enumerate(caps, 1):
            cap.seq = i
        return caps
