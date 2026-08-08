"""
Interaction Service — Playwright ile Sosyal Medya Etkileşimleri (İnsan-Gibi).

Instagram ve X için beğeni, takip ve DM gönderimi.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth

logger = logging.getLogger("agent_core.interaction")
logging.basicConfig(level=logging.INFO)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

class InteractionAgent:
    def __init__(self):
        self.browser: Optional[Any] = None
        self.context: Optional[Any] = None
        self._pw: Optional[Any] = None

    async def start(self, cookies: Optional[list] = None) -> None:
        """Playwright tarayıcısını başlatır."""
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ua = random.choice(USER_AGENTS)
        self.context = await self.browser.new_context(
            user_agent=ua,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(720, 1080)}
        )

        if cookies:
            await self.context.add_cookies(cookies)
            logger.info(f"Loaded {len(cookies)} cookies into context.")

        stealth = Stealth()
        await stealth.apply_stealth_async(self.context)

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self._pw:
            await self._pw.stop()

    async def _human_delay(self, min_s: float = 2.0, max_s: float = 5.0):
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _human_jitter(self, page: Page):
        """Adds a small jittery mouse movement to avoid bot detection."""
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        for _ in range(random.randint(1, 3)):
            x = random.randint(100, viewport["width"] - 100)
            y = random.randint(100, viewport["height"] - 100)
            await page.mouse.move(x, y, steps=random.randint(5, 10))
            await asyncio.sleep(random.uniform(0.1, 0.5))

    async def _human_typing(self, page: Page, selector: str, text: str):
        for char in text:
            await page.type(selector, char, delay=random.randint(50, 150))
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.6))
        await asyncio.sleep(random.uniform(0.5, 1.0))

    async def send_dm(self, platform: str, username: str, message: str, retries: int = 3) -> Dict[str, Any]:
        """Kullanıcıya DM gönderir. Hata durumunda exponential backoff ile tekrar dener."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        for attempt in range(retries):
            page = await self.context.new_page()
            try:
                if platform == "instagram":
                    url = f"https://www.instagram.com/direct/t/{username}/"
                    await page.goto(url, wait_until="domcontentloaded")
                    await self._human_delay(3, 6)
                    await self._human_jitter(page)

                    # Mesaj kutusunu bul (Instagram DOM sık değişir, genel selector)
                    msg_box_selector = 'div[aria-label="Message"]'
                    if await page.locator(msg_box_selector).count() > 0:
                        await self._human_delay(1, 2)
                        await page.click(msg_box_selector)
                        await self._human_typing(page, msg_box_selector, message)
                        await self._human_delay(0.5, 1.5)
                        await page.keyboard.press("Enter")
                        logger.info(f"DM gönderildi (Instagram -> {username})")
                        return {"status": "ok", "platform": platform, "username": username}
                    else:
                        raise Exception("Message box not found")

                elif platform == "x":
                    url = f"https://x.com/messages/compose?recipient_id={username}"
                    await page.goto(url, wait_until="domcontentloaded")
                    await self._human_delay(3, 6)
                    await self._human_jitter(page)

                    # Mesaj kutusu
                    msg_box_selector = '[data-testid="dmComposerTextInput"]'
                    if await page.locator(msg_box_selector).count() > 0:
                        await self._human_delay(1, 2)
                        await page.click(msg_box_selector)
                        await self._human_typing(page, msg_box_selector, message)
                        await self._human_delay(0.5, 1.5)
                        await page.keyboard.press("Enter")
                        logger.info(f"DM gönderildi (X -> {username})")
                        return {"status": "ok", "platform": platform, "username": username}
                    else:
                        raise Exception("Message box not found")
                else:
                    return {"status": "failed", "error": f"Platform {platform} not supported"}
            except Exception as e:
                logger.warning(f"DM gönderme hatasi (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    backoff_time = (2 ** attempt) + random.uniform(1.0, 3.0)
                    logger.info(f"Exponential backoff: {backoff_time:.1f} saniye bekleniyor...")
                    await asyncio.sleep(backoff_time)
                else:
                    logger.error(f"DM gönderilirken maksimum deneme asildi: {e}")
                    return {"status": "error", "error": str(e)}
            finally:
                await page.close()

    async def like_post(self, platform: str, url: str, retries: int = 3) -> Dict[str, Any]:
        """Gönderiyi beğenir. Hata durumunda exponential backoff uygular."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        for attempt in range(retries):
            page = await self.context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await self._human_delay(2, 4)
                await self._human_jitter(page)

                if platform == "instagram":
                    like_btn = 'span > svg[aria-label="Like"]'
                    if await page.locator(like_btn).count() > 0:
                        await self._human_delay(1.5, 3.5)
                        await page.click(like_btn)
                        logger.info(f"Beğenildi (Instagram -> {url})")
                        return {"status": "ok"}
                    else:
                        raise Exception("Like button not found")
                elif platform == "x":
                    like_btn = '[data-testid="like"]'
                    if await page.locator(like_btn).count() > 0:
                        await self._human_delay(1.5, 3.5)
                        await page.click(like_btn)
                        logger.info(f"Beğenildi (X -> {url})")
                        return {"status": "ok"}
                    else:
                        raise Exception("Like button not found")
                else:
                    return {"status": "failed", "error": f"Platform {platform} not supported"}
            except Exception as e:
                logger.warning(f"Begenme hatasi (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep((2 ** attempt) + random.uniform(1.0, 3.0))
                else:
                    return {"status": "error", "error": str(e)}
            finally:
                await page.close()

    async def follow_user(self, platform: str, username: str, retries: int = 3) -> Dict[str, Any]:
        """Kullanıcıyı takip eder. Hata durumunda exponential backoff uygular."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        for attempt in range(retries):
            page = await self.context.new_page()
            try:
                if platform == "instagram":
                    url = f"https://www.instagram.com/{username}/"
                    await page.goto(url, wait_until="domcontentloaded")
                    await self._human_delay(2, 4)
                    await self._human_jitter(page)

                    # Takip et butonu
                    follow_btn = 'button:has-text("Follow")'
                    if await page.locator(follow_btn).count() > 0:
                        await self._human_delay(1.5, 3.5)
                        await page.click(follow_btn)
                        logger.info(f"Takip edildi (Instagram -> {username})")
                        return {"status": "ok"}
                    else:
                        raise Exception("Follow button not found")
                elif platform == "x":
                    url = f"https://x.com/{username}"
                    await page.goto(url, wait_until="domcontentloaded")
                    await self._human_delay(2, 4)
                    await self._human_jitter(page)

                    # Takip et butonu
                    follow_btn = f'[aria-label="Follow @{username}"]'
                    if await page.locator(follow_btn).count() > 0:
                        await self._human_delay(1.5, 3.5)
                        await page.click(follow_btn)
                        logger.info(f"Takip edildi (X -> {username})")
                        return {"status": "ok"}
                    else:
                        raise Exception("Follow button not found")
                else:
                    return {"status": "failed", "error": f"Platform {platform} not supported"}
            except Exception as e:
                logger.warning(f"Takip hatasi (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep((2 ** attempt) + random.uniform(1.0, 3.0))
                else:
                    return {"status": "error", "error": str(e)}
            finally:
                await page.close()
