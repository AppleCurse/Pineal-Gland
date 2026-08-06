"""UI-TARS görsel (piksel tabanlı) ajanı.

DOM/CSS/XPath seçicisi YOKTUR. Akış (UI-TARS-desktop SDK'sı ile birebir aynı):

    operator --> GUIAgent  : base64 ekran görüntüsü + fiziksel ekran boyutu
    model    --> GUIAgent  : prediction, örn. click(start_box='(27,496)')
    GUIAgent --> operator  : tıklama/kaydırma/klavye eylemini koordinatlarla uygula
    ...finished() veya max_step olana dek tekrarla

Model endpoint'i UI-TARS kontrolleri servis eden OpenAI-uyumlu bir sunucudur:
    vllm serve ByteDance/UI-TARS-1.5-7B --chat-template <ui_tars.jinja> --dtype bfloat16
Yoksa istemci "UITARS_MODEL_ENDPOINT yapılandırılmamış" hatası verir (sahte iş yok).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("agent_core.uitars")


class UITarsError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Operator: gerçek tarayıcıyı koordinatlarla yönetir (Playwright tabanlı)
# ---------------------------------------------------------------------------
class PlaywrightOperator:
    """Ekranı base64 veren + koordinat eylemleri uygulayan gerçek operator."""

    def __init__(self, start_url: str = "about:blank", viewport: Tuple[int, int] = (1280, 800)):
        self.start_url = start_url
        self.viewport = viewport
        self._pw: Optional[Any] = None
        self._browser: Optional[Any] = None
        self._page: Optional[Any] = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        context = await self._browser.new_context(viewport={"width": self.viewport[0], "height": self.viewport[1]})
        self._page = await context.new_page()
        self._page.set_default_timeout(20000)
        if self.start_url and self.start_url != "about:blank":
            try:
                await self._page.goto(self.start_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                logger.warning("operator başlangıç URL'ine gidemedi: %s", exc)

    async def stop(self) -> None:
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass

    async def screenshot_base64(self) -> str:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        buf = await self._page.screenshot(type="png")
        return base64.b64encode(buf).decode()

    async def click(self, x: int, y: int, double: bool = False) -> None:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        if double:
            await self._page.mouse.dblclick(x, y)
        else:
            await self._page.mouse.click(x, y)

    async def hover(self, x: int, y: int) -> None:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        await self._page.mouse.move(x, y)

    async def scroll(self, dx: int = 0, dy: int = 500) -> None:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        await self._page.mouse.wheel(dx, dy)

    async def type_text(self, text: str) -> None:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        await self._page.keyboard.type(text, delay=10)

    async def press(self, key: str) -> None:
        if self._page is None:
            raise UITarsError("operator başlatılmamış")
        await self._page.keyboard.press(key)

    async def wait(self, ms: int = 600) -> None:
        await asyncio.sleep(ms / 1000.0)


# ---------------------------------------------------------------------------
# UI-TARS model istemcisi (OpenAI-uyumlu /chat/completions, image_url)
# ---------------------------------------------------------------------------
class UITarsModelClient:
    def __init__(self, endpoint: str, model: str = "ui-tars-1.5", timeout: float = 120.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def predict(self, instruction: str, screenshot_b64: str) -> str:
        if not self.endpoint:
            raise UITarsError(
                "UITARS_MODEL_ENDPOINT yapılandırılmamış. "
                "Önce bir UI-TARS sunucusu başlatın: "
                "vllm serve ByteDance/UI-TARS-1.5-7B --chat-template <ui_tars.jinja>"
            )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                        {"type": "text", "text": instruction},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": 512,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.endpoint}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# GUIAgent: screenshot -> prediction -> eylem döngüsü
# ---------------------------------------------------------------------------
_ACTION_RE = re.compile(
    r"(click|double_click|hover|type|scroll|press|finished|failed)\s*\("
    r"(.*)"
    r"\)",
    re.IGNORECASE | re.DOTALL,
)


def parse_action(prediction: str) -> Dict[str, Any]:
    """'click(start_box='(27,496)')' -> {"action":"click","x":27,"y":496, ...}"""
    m = _ACTION_RE.search(prediction)
    if not m:
        raise UITarsError(f"Anlaşılamayan UI-TARS eylemi: {prediction[:120]!r}")
    name = m.group(1).lower()
    body = m.group(2)
    action: Dict[str, Any] = {"action": name}

    box = re.search(r"start_box\s*=\s*['\"]?\((\d+)\s*,\s*(\d+)\)", body)
    if box:
        action["x"] = int(box.group(1))
        action["y"] = int(box.group(2))
    end_box = re.search(r"end_box\s*=\s*['\"]?\((\d+)\s*,\s*(\d+)\)", body)
    if end_box:
        action["end_x"] = int(end_box.group(1))
        action["end_y"] = int(end_box.group(2))
    content = re.search(r"content\s*=\s*['\"](.*?)['\"]", body)
    if content:
        action["content"] = content.group(1).encode().decode("unicode_escape")
    direction = re.search(r"direction\s*=\s*['\"](.*?)['\"]", body)
    if direction:
        action["direction"] = direction.group(1)
    return action


class GUIAgent:
    """UI-TARS görsel ajanı. max_step'i aşarsa veya eylem başarısızsa hata fırlatır."""

    def __init__(
        self,
        operator: PlaywrightOperator,
        model: UITarsModelClient,
        instruction: str,
        max_step: int = 25,
        pause_ms: int = 700,
    ):
        self.operator = operator
        self.model = model
        self.instruction = instruction
        self.max_step = max_step
        self.pause_ms = pause_ms
        self.step = 0
        self.history: List[Dict[str, Any]] = []

    async def _execute(self, action: Dict[str, Any]) -> None:
        name = action["action"]
        op = self.operator
        if name == "click":
            await op.click(action["x"], action["y"])
        elif name == "double_click":
            await op.click(action["x"], action["y"], double=True)
        elif name == "hover":
            await op.hover(action["x"], action["y"])
        elif name == "scroll":
            end = (action.get("end_x", 0), action.get("end_y", 0))
            start = (action.get("x", 0), action.get("y", 0))
            dy = end[1] - start[1] if action.get("end_y") is not None else (600 if action.get("direction") != "up" else -600)
            await op.scroll(dy=dy)
        elif name == "type":
            if "content" not in action:
                raise UITarsError("type eylemi content olmadan geldi")
            await op.type_text(action["content"])
        elif name == "press":
            await op.press(action.get("content", "Enter"))
        else:
            raise UITarsError(f"Desteklenmeyen eylem: {name}")
        await op.wait(self.pause_ms)

    async def run(self) -> Dict[str, Any]:
        await self.operator.start()
        try:
            while self.step < self.max_step:
                self.step += 1
                shot = await self.operator.screenshot_base64()
                try:
                    prediction = await self.model.predict(self.instruction, shot)
                except httpx.HTTPError as exc:
                    raise UITarsError(f"UI-TARS model hatası: {exc}") from exc
                logger.info("[UI-TARS adım %d] %s", self.step, prediction[:200])
                self.history.append({"step": self.step, "prediction": prediction})

                low = prediction.lower()
                if "finished()" in low or "finished(" in low:
                    logger.info("UI-TARS görevi tamamladı (adım %d)", self.step)
                    return {"status": "finished", "step": self.step, "history": self.history}
                if "failed(" in low:
                    raise UITarsError(f"UI-TARS görevi başarısız işaretledi: {prediction[:200]}")

                action = parse_action(prediction)
                try:
                    await self._execute(action)
                except UITarsError:
                    raise
                except Exception as exc:
                    logger.warning("eylem uygulanamadı (%s): %s", action.get("action"), exc)
                    await self.operator.wait(400)

            raise UITarsError(f"max_step ({self.max_step}) aşıldı — görev tamamlanamadı")
        finally:
            await self.operator.stop()
