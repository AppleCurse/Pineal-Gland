"""
Gerçek Playwright tarayıcı ajanı.

Kokpitin "canlı aynası" bu tarayıcının gerçek durumunu gösterir.
Tüm işlemler tek bir asyncio.Lock ile sıralanır; ekran görüntüsü
akışı kilit meşgulse atlanır (bloklama yaratmaz).
"""
from __future__ import annotations

import asyncio
import base64
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import async_playwright


class BrowserAgent:
    def __init__(self) -> None:
        self._pw: Optional[Any] = None
        self.browser: Optional[Any] = None
        self.context: Optional[Any] = None
        self.page: Optional[Any] = None
        self.lock = asyncio.Lock()
        self.viewport = {"width": 1280, "height": 800}
        self.current_url: str = ""
        self.title: str = ""
        self.running: bool = False
        self.error: str = ""

    async def start(self) -> None:
        if self.running:
            return
        try:
            import random
            self._pw = await async_playwright().start()

            # Anti-bot argümanlar
            launch_args = [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--window-size=1280,800",
            ]

            self.browser = await self._pw.chromium.launch(
                headless=True,
                args=launch_args,
            )

            # Gerçek Chrome user-agent — bot tespitini azaltır
            ua = random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            ])

            self.context = await self.browser.new_context(
                viewport={"width": random.randint(1280, 1440), "height": random.randint(780, 900)},
                user_agent=ua,
                locale="tr-TR",
                timezone_id="Europe/Istanbul",
                # navigator.webdriver = false yap
                extra_http_headers={
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )

            # navigator.webdriver'ı kapat (Instagram/X için kritik)
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['tr-TR','tr','en-US','en']});
                window.chrome = { runtime: {} };
            """)

            # playwright-stealth varsa uygula
            try:
                from playwright_stealth import Stealth
                stealth = Stealth(
                    navigator_languages_override=("tr-TR", "tr", "en-US", "en"),
                    webgl_vendor_override="Intel Inc.",
                    webgl_renderer_override="Intel Iris OpenGL Engine",
                )
                await stealth.apply_stealth_async(self.context)
            except ImportError:
                pass  # stealth kurulu değilse devam et

            self.page = await self.context.new_page()
            self.page.set_default_timeout(25000)
            self.running = True

            # Kayitli session cookie'leri yukle (Instagram, X)
            try:
                from social_login import apply_session, has_session
                for platform in ("instagram", "x"):
                    if has_session(platform):
                        await apply_session(self.context, platform)
            except Exception:
                pass

            await self.goto("https://www.google.com")
        except Exception as exc:  # pragma: no cover
            self.error = str(exc)
            self.running = False

    async def stop(self) -> None:
        self.running = False
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass

    async def _sync(self) -> None:
        try:
            self.current_url = self.page.url
            self.title = await self.page.title()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Gezinti
    # ------------------------------------------------------------------
    async def goto(self, url: str) -> Dict[str, str]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        async with self.lock:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            await self._sync()
        return {"url": self.current_url, "title": self.title}

    async def back(self) -> Dict[str, str]:
        async with self.lock:
            try:
                await self.page.go_back()
            except Exception:
                pass
            await self._sync()
        return {"url": self.current_url, "title": self.title}

    async def forward(self) -> Dict[str, str]:
        async with self.lock:
            try:
                await self.page.go_forward()
            except Exception:
                pass
            await self._sync()
        return {"url": self.current_url, "title": self.title}

    async def reload(self) -> Dict[str, str]:
        async with self.lock:
            try:
                await self.page.reload()
            except Exception:
                pass
            await self._sync()
        return {"url": self.current_url, "title": self.title}

    async def scroll(self, direction: str = "down", amount: int = 600) -> None:
        delta = amount if direction == "down" else -amount
        async with self.lock:
            try:
                await self.page.mouse.wheel(0, delta)
            except Exception:
                pass
            await self._sync()

    # ------------------------------------------------------------------
    # Etkileşim
    # ------------------------------------------------------------------
    async def type_text(self, text: str, press_enter: bool = False) -> None:
        async with self.lock:
            try:
                await self.page.keyboard.type(text, delay=15)
                if press_enter:
                    await self.page.keyboard.press("Enter")
            except Exception:
                pass
            await self._sync()

    async def press(self, key: str) -> None:
        async with self.lock:
            try:
                await self.page.keyboard.press(key)
            except Exception:
                pass
            await self._sync()

    async def click(self, selector: str) -> None:
        async with self.lock:
            try:
                await self.page.click(selector)
            except Exception:
                pass
            await self._sync()

    async def search(self, query: str) -> Dict[str, str]:
        """Bing'de arama (fallback)."""
        return await self.goto("https://www.bing.com/search?q=" + quote(query))

    async def platform_search(self, query: str, platform: str = "x") -> Dict[str, str]:
        """
        Platforma gore dogrudan profil arama.
        platform: 'x' | 'instagram' | 'facebook'
        """
        # Sorguyu temizle (negatif operatorleri kaldir, URL uyumlu yap)
        clean = (
            query
            .replace("-reklam", "").replace("-spam", "").replace("-tanitim", "")
            .replace("-indirim", "").replace("lang:tr", "").replace("-satis", "")
            .strip()
        )
        encoded = quote(clean)

        if platform == "x":
            # X profil arama — login gerektirmez
            url = f"https://x.com/search?q={encoded}&f=people&src=typed_query"
        elif platform == "instagram":
            # Instagram explore arama (login varsa calisir, yoksa login'e yonlendirir)
            url = f"https://www.instagram.com/explore/search/keyword/?q={encoded}"
        elif platform == "facebook":
            # Facebook halka acik arama
            url = f"https://www.facebook.com/search/people/?q={encoded}"
        else:
            url = "https://www.bing.com/search?q=site:instagram.com+" + encoded

        return await self.goto(url)

    async def do_login(self, platform: str, username: str, password: str) -> bool:
        """
        Platforma giris yapar ve session cookie'leri kaydeder.
        Cockpit'ten /login komutu ile tetiklenir.
        """
        try:
            from social_login import instagram_login, x_login
            if platform == "instagram":
                return await instagram_login(self.page, username, password)
            elif platform in ("x", "twitter"):
                return await x_login(self.page, username, password)
            else:
                return False
        except Exception as exc:
            self.error = str(exc)
            return False

    # ------------------------------------------------------------------
    # Okuma
    # ------------------------------------------------------------------
    async def screenshot_jpeg(self, quality: int = 55) -> Optional[str]:
        """JPEG -> base64. Kilit meşgulse None döner (akış bloklanmaz)."""
        if self.lock.locked():
            return None
        async with self.lock:
            try:
                buf = await self.page.screenshot(type="jpeg", quality=quality)
            except Exception:
                return None
        return base64.b64encode(buf).decode()

    async def snapshot_text(self, max_len: int = 3000) -> str:
        async with self.lock:
            try:
                text = await self.page.inner_text("body")
            except Exception:
                return ""
        return text[:max_len]

    async def get_links(self, limit: int = 20) -> List[Dict[str, str]]:
        js = """(els) => els.slice(0, %d).map(a => ({
            href: a.href || '', text: (a.innerText || '').trim().slice(0, 60)}))""" % limit
        async with self.lock:
            try:
                return await self.page.eval_on_selector_all("a", js)
            except Exception:
                return []

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "url": self.current_url,
            "title": self.title,
            "error": self.error,
        }


browser = BrowserAgent()
