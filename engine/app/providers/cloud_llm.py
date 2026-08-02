"""雲端 LLM 層:Whisper 轉錄 + AI API 校正/翻譯/摘要。

支援 OpenAI / Gemini / Anthropic / 自訂 OpenAI 相容端點。
API Key 只存本機 settings.json,引擎僅綁 127.0.0.1,不經第三方轉送。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-haiku-4-5",
}

SUMMARY_TEMPLATES = {
    "general":   "## 摘要\n- 重點條列(3-8 條)\n### 決議事項\n### 待辦事項(含負責講者)",
    "interview": "## 摘要\n- 受訪者背景與核心觀點\n### 關鍵引述(標時間戳)\n### 待追問事項",
    "lecture":   "## 摘要\n- 課程大綱重點\n### 核心概念解釋\n### 建議複習項目",
    "support":   "## 摘要\n- 客戶問題描述\n### 處理過程與結果\n### 後續追蹤事項",
}

MODE_TARGETS = {  # 翻譯模式 → 目標語言描述
    "en2zh": ("英文", "台灣繁體中文"),
    "zh2en": ("中文", "English"),
    "ja2zh": ("日文", "台灣繁體中文"),
}


@dataclass
class LLMSettings:
    provider: str = ""            # openai | gemini | anthropic | custom;空 = 未設定
    api_key: str = ""
    model: str = ""
    base_url: str = ""            # custom / OpenAI 相容端點用

    @property
    def configured(self) -> bool:
        return bool(self.provider and self.api_key)

    def resolved_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "")

    def masked(self) -> dict:
        d = {"provider": self.provider, "model": self.model,
             "base_url": self.base_url, "configured": self.configured}
        d["api_key_masked"] = (self.api_key[:6] + "…" + self.api_key[-4:]
                               if len(self.api_key) > 12 else ("已設定" if self.api_key else ""))
        return d


APP_DEFAULTS = {"keywords": [], "webhooks": [], "retention_days": 0}


class SettingsStore:
    """settings.json 讀寫(預設 ~/.konjac/settings.json;測試給 tmp 路徑)。
    同一檔存 LLM 設定與 app 設定(keywords/webhooks/retention_days),互不覆蓋。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or (Path.home() / ".konjac" / "settings.json")

    def _raw(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def load(self) -> LLMSettings:
        data = self._raw()
        try:
            return LLMSettings(**{k: data.get(k, "") for k in
                                  ("provider", "api_key", "model", "base_url")})
        except TypeError:
            return LLMSettings()

    def save(self, s: LLMSettings) -> None:
        data = self._raw()
        data.update(s.__dict__)
        self._write(data)

    def load_app(self) -> dict:
        data = self._raw()
        out = dict(APP_DEFAULTS)
        for k in APP_DEFAULTS:
            if k in data:
                out[k] = data[k]
        return out

    def save_app(self, app_cfg: dict) -> dict:
        data = self._raw()
        for k in APP_DEFAULTS:
            if k in app_cfg and app_cfg[k] is not None:
                data[k] = app_cfg[k]
        self._write(data)
        return {k: data.get(k, APP_DEFAULTS[k]) for k in APP_DEFAULTS}


class CloudLLM:
    def __init__(self, settings: LLMSettings, timeout: float = 60.0):
        self.s = settings
        self._timeout = timeout

    async def _chat(self, prompt: str, max_tokens: int = 2000) -> str:
        p, model = self.s.provider, self.s.resolved_model()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            if p == "anthropic":
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.s.api_key,
                             "anthropic-version": "2023-06-01"},
                    json={"model": model, "max_tokens": max_tokens,
                          "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                return "".join(b.get("text", "") for b in r.json()["content"])
            if p == "gemini":
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": self.s.api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]})
                r.raise_for_status()
                cands = r.json().get("candidates", [])
                return "".join(part.get("text", "")
                               for part in cands[0]["content"]["parts"]) if cands else ""
            # openai 與 custom(OpenAI 相容)
            base = (self.s.base_url or "https://api.openai.com").rstrip("/")
            r = await client.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.s.api_key}"},
                json={"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def translate(self, text: str, mode: str,
                        topic: Optional[str] = None) -> Optional[str]:
        """校正 ASR 錯字後翻譯;非翻譯模式回 None。"""
        if mode not in MODE_TARGETS:
            return None
        src_lang, dst_lang = MODE_TARGETS[mode]
        topic_line = f"會議主題:{topic}。專有名詞請依主題領域翻譯。\n" if topic else ""
        prompt = (
            f"以下是一句{src_lang}語音辨識結果,可能含辨識錯字。\n{topic_line}"
            f"請先在心中校正明顯的辨識錯誤,再翻譯成{dst_lang}。\n"
            f"只輸出翻譯結果,不要任何解釋或引號。\n\n{text}")
        out = (await self._chat(prompt, max_tokens=1000)).strip()
        return out or None

    async def summarize(self, transcript_md: str, topic: Optional[str],
                        template: str = "general") -> str:
        topic_line = f"主題:{topic}\n" if topic else ""
        structure = SUMMARY_TEMPLATES.get(template, SUMMARY_TEMPLATES["general"])
        prompt = (
            f"以下是一段音訊的逐字稿(含講者與時間戳)。{topic_line}"
            f"請用台灣繁體中文輸出 Markdown 摘要,格式:\n{structure}\n"
            "嚴格根據逐字稿內容,絕對不可捏造逐字稿中沒有的資訊;"
            "無內容的小節寫「(無)」。\n\n" + transcript_md)
        return (await self._chat(prompt, max_tokens=2000)).strip()


class CloudSummarizer:
    """符合引擎 Summarizer 介面的包裝。"""

    def __init__(self, llm: CloudLLM):
        self._llm = llm

    async def summarize(self, transcript_md: str, topic: Optional[str],
                        template: str = "general") -> str:
        return await self._llm.summarize(transcript_md, topic, template)


def needs_translation(mode: str) -> bool:
    return mode in MODE_TARGETS
