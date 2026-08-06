"""
Sosyal Medya Oturum Yöneticisi — Instagram ve X için Playwright Login.

Kullanim:
  - /login instagram kullanici@mail.com sifre123
  - /login x kullanici sifre123

Oturum cookies olarak session_store.json'a kaydedilir.
Sonraki isteklerde browser bu cookie'leri yukler → login duvarini aser.

Guvenlik: session_store.json .gitignore'da, asla commit edilmez.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("cockpit.social_login")

SESSION_FILE = Path(__file__).resolve().parent / "session_store.json"


def load_sessions() -> Dict[str, Any]:
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_sessions(data: Dict[str, Any]) -> None:
    SESSION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_session_cookies(platform: str) -> Optional[list]:
    """Kaydedilmis oturum cookie'lerini dondur."""
    sessions = load_sessions()
    return sessions.get(platform, {}).get("cookies")


async def instagram_login(page, username: str, password: str) -> bool:
    """Instagram'a Playwright ile giris yapar, cookies'i kaydeder."""
    try:
        await page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(2, 3))

        # Kullanici adi
        await page.fill('input[name="username"]', username)
        await asyncio.sleep(random.uniform(0.5, 1.2))

        # Sifre
        await page.fill('input[name="password"]', password)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # Giris butonu
        await page.click('button[type="submit"]')
        await asyncio.sleep(random.uniform(3, 5))

        # Basarili giris kontrolu
        current = page.url
        if "accounts/login" not in current and "challenge" not in current:
            # Cookies kaydet
            cookies = await page.context.cookies()
            sessions = load_sessions()
            sessions["instagram"] = {
                "username": username,
                "cookies": cookies,
            }
            save_sessions(sessions)
            logger.info("Instagram girisi basarili: %s", username)
            return True
        elif "challenge" in current or "two_factor" in current:
            logger.warning("Instagram 2FA veya challenge gerektiriyor: %s", current)
            return False
        else:
            logger.error("Instagram giris basarisiz. URL: %s", current)
            return False
    except Exception as exc:
        logger.error("Instagram giris hatasi: %s", exc)
        return False


async def x_login(page, username: str, password: str) -> bool:
    """X (Twitter)'a Playwright ile giris yapar, cookies'i kaydeder."""
    try:
        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(2, 3))

        # Kullanici adi / email
        await page.fill('input[autocomplete="username"]', username)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        await page.press('input[autocomplete="username"]', "Enter")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        # Sifre
        try:
            await page.fill('input[name="password"]', password, timeout=8000)
        except Exception:
            # Bazen ara adim cikiyor (telefon dogrulama isteyebilir)
            pass
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # Giris butonu
        try:
            await page.click('[data-testid="LoginForm_Login_Button"]', timeout=6000)
        except Exception:
            await page.press('input[name="password"]', "Enter")
        await asyncio.sleep(random.uniform(3, 5))

        current = page.url
        if "home" in current or "x.com/?lang" in current or current == "https://x.com/":
            cookies = await page.context.cookies()
            sessions = load_sessions()
            sessions["x"] = {
                "username": username,
                "cookies": cookies,
            }
            save_sessions(sessions)
            logger.info("X girisi basarili: %s", username)
            return True
        else:
            logger.error("X giris basarisiz. URL: %s", current)
            return False
    except Exception as exc:
        logger.error("X giris hatasi: %s", exc)
        return False


async def apply_session(context, platform: str) -> bool:
    """Kaydedilmis cookie'leri browser context'e yukle."""
    cookies = get_session_cookies(platform)
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
        logger.info("%s session yuklendi (%d cookie)", platform, len(cookies))
        return True
    except Exception as exc:
        logger.error("Cookie yukleme hatasi: %s", exc)
        return False


def has_session(platform: str) -> bool:
    """Platform icin kayitli oturum var mi?"""
    return bool(get_session_cookies(platform))
