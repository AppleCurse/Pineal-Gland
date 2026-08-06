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

    async def _human_typing(self, page: Page, selector: str, text: str):
        for char in text:
            await page.type(selector, char, delay=random.randint(50, 150))
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.2, 0.6))
        await asyncio.sleep(random.uniform(0.5, 1.0))

    async def send_dm(self, platform: str, username: str, message: str) -> Dict[str, Any]:
        """Kullanıcıya DM gönderir."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        page = await self.context.new_page()
        try:
            if platform == "instagram":
                url = f"https://www.instagram.com/direct/t/{username}/"
                await page.goto(url, wait_until="domcontentloaded")
                await self._human_delay(3, 6)

                # Mesaj kutusunu bul (Instagram DOM sık değişir, genel selector)
                msg_box_selector = 'div[aria-label="Message"]'
                if await page.locator(msg_box_selector).count() > 0:
                    await page.click(msg_box_selector)
                    await self._human_typing(page, msg_box_selector, message)
                    await page.keyboard.press("Enter")
                    logger.info(f"DM gönderildi (Instagram -> {username})")
                    return {"status": "ok", "platform": platform, "username": username}
                else:
                    return {"status": "failed", "error": "Message box not found"}

            elif platform == "x":
                url = f"https://x.com/messages/compose?recipient_id={username}"
                await page.goto(url, wait_until="domcontentloaded")
                await self._human_delay(3, 6)

                # Mesaj kutusu
                msg_box_selector = '[data-testid="dmComposerTextInput"]'
                if await page.locator(msg_box_selector).count() > 0:
                    await page.click(msg_box_selector)
                    await self._human_typing(page, msg_box_selector, message)
                    await page.keyboard.press("Enter")
                    logger.info(f"DM gönderildi (X -> {username})")
                    return {"status": "ok", "platform": platform, "username": username}
                else:
                    return {"status": "failed", "error": "Message box not found"}
            else:
                return {"status": "failed", "error": f"Platform {platform} supported"}
        except Exception as e:
            logger.error(f"DM gönderilirken hata oluştu: {e}")
            return {"status": "error", "error": str(e)}
        finally:
            await page.close()

    async def like_post(self, platform: str, url: str) -> Dict[str, Any]:
        """Gönderiyi beğenir."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await self._human_delay(2, 4)

            if platform == "instagram":
                like_btn = 'span > svg[aria-label="Like"]'
                if await page.locator(like_btn).count() > 0:
                    await page.click(like_btn)
                    logger.info(f"Beğenildi (Instagram -> {url})")
                    return {"status": "ok"}
            elif platform == "x":
                like_btn = '[data-testid="like"]'
                if await page.locator(like_btn).count() > 0:
                    await page.click(like_btn)
                    logger.info(f"Beğenildi (X -> {url})")
                    return {"status": "ok"}

            return {"status": "failed", "error": "Like button not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            await page.close()

    async def follow_user(self, platform: str, username: str) -> Dict[str, Any]:
        """Kullanıcıyı takip eder."""
        if not self.context:
            return {"status": "error", "error": "Browser not started"}

        page = await self.context.new_page()
        try:
            if platform == "instagram":
                url = f"https://www.instagram.com/{username}/"
                await page.goto(url, wait_until="domcontentloaded")
                await self._human_delay(2, 4)

                # Takip et butonu
                follow_btn = 'button:has-text("Follow")'
                if await page.locator(follow_btn).count() > 0:
                    await page.click(follow_btn)
                    logger.info(f"Takip edildi (Instagram -> {username})")
                    return {"status": "ok"}
            elif platform == "x":
                url = f"https://x.com/{username}"
                await page.goto(url, wait_until="domcontentloaded")
                await self._human_delay(2, 4)

                # Takip et butonu
                follow_btn = f'[aria-label="Follow @{username}"]'
                if await page.locator(follow_btn).count() > 0:
                    await page.click(follow_btn)
                    logger.info(f"Takip edildi (X -> {username})")
                    return {"status": "ok"}

            return {"status": "failed", "error": "Follow button not found"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            await page.close()
