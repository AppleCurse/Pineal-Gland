"""
Platform Adapter — Instagram / X / Facebook icin 3 erisim yontemi.

Yontem 1: Playwright Login  — kullanici adi + sifre, cookie kaydeder
Yontem 2: RapidAPI          — API key, bot tespiti yok, ~10$/ay
Yontem 3: Chrome Profile    — yerel Chrome kurulumundan cookie okur

Secim cockpit UI'dan yapilir, platform_config.json'a kaydedilir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cockpit.platform_adapter")

CONFIG_FILE = Path(__file__).resolve().parent / "platform_config.json"

DEFAULT_CONFIG = {
    "method": "login",          # "login" | "rapidapi" | "chrome_profile"
    "rapidapi_key": "",
    "chrome_profile_path": "",  # ornek: C:/Users/Ad/AppData/Local/Google/Chrome/User Data/Default
    "platforms": {
        "instagram": {"enabled": True},
        "x": {"enabled": True},
        "facebook": {"enabled": False},
    },
}


# ---------------------------------------------------------------------------
# Config yoneticisi
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_method() -> str:
    return load_config().get("method", "login")


# ---------------------------------------------------------------------------
# Yontem 1: Playwright Login
# ---------------------------------------------------------------------------
async def method_login(browser_page, platform: str, username: str, password: str) -> Dict[str, Any]:
    """Playwright ile platforma giris yapar, session cookie kaydeder."""
    try:
        from social_login import instagram_login, x_login
        if platform == "instagram":
            ok = await instagram_login(browser_page, username, password)
        elif platform in ("x", "twitter"):
            ok = await x_login(browser_page, username, password)
        else:
            return {"ok": False, "error": f"Desteklenmeyen platform: {platform}"}
        return {"ok": ok, "method": "login", "platform": platform}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Yontem 2: RapidAPI Scraper
# ---------------------------------------------------------------------------
async def method_rapidapi_search(query: str, platform: str) -> Dict[str, Any]:
    """
    RapidAPI uzerinden profil arama.
    Instagram: apidojo/instagram-scraper-2022
    X/Twitter: twitter154 veya twitter-v2
    """
    cfg = load_config()
    api_key = cfg.get("rapidapi_key", "")
    if not api_key:
        return {"ok": False, "error": "RapidAPI key girilmemis. Cockpit ayarlarindan ekle."}

    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx kurulu degil"}

    results = []

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if platform == "instagram":
                resp = await client.get(
                    "https://instagram-scraper-2022.p.rapidapi.com/ig/search_user/",
                    params={"user": query},
                    headers={
                        "X-RapidAPI-Key": api_key,
                        "X-RapidAPI-Host": "instagram-scraper-2022.p.rapidapi.com",
                    },
                )
            elif platform in ("x", "twitter"):
                resp = await client.get(
                    "https://twitter154.p.rapidapi.com/search/search",
                    params={"query": query, "limit": "20", "result_filter": "user"},
                    headers={
                        "X-RapidAPI-Key": api_key,
                        "X-RapidAPI-Host": "twitter154.p.rapidapi.com",
                    },
                )
            else:
                return {"ok": False, "error": f"RapidAPI: {platform} desteklenmiyor"}

            if resp.status_code == 200:
                data = resp.json()
                results = data if isinstance(data, list) else data.get("results", data.get("data", [data]))
                return {"ok": True, "method": "rapidapi", "platform": platform, "results": results[:20]}
            else:
                return {"ok": False, "error": f"RapidAPI HTTP {resp.status_code}: {resp.text[:200]}"}

    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Yontem 3: Chrome Profile Cookie
# ---------------------------------------------------------------------------
def get_chrome_cookies(profile_path: str, domain: str) -> List[Dict[str, Any]]:
    """
    Yerel Chrome profil dizininden cookie'leri okur.
    Windows: C:/Users/<AD>/AppData/Local/Google/Chrome/User Data/Default
    """
    cookies_db = Path(profile_path) / "Network" / "Cookies"
    if not cookies_db.exists():
        # Eski konum
        cookies_db = Path(profile_path) / "Cookies"
    if not cookies_db.exists():
        return []

    import shutil, tempfile
    # Chrome acikken dosya kilitli olabilir, gecici kopyayla calis
    tmp = Path(tempfile.mktemp(suffix=".db"))
    shutil.copy2(cookies_db, tmp)

    try:
        conn = sqlite3.connect(str(tmp))
        cur = conn.cursor()
        cur.execute(
            "SELECT name, value, host_key, path, expires_utc, is_secure FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",),
        )
        rows = cur.fetchall()
        conn.close()
        tmp.unlink(missing_ok=True)

        playwright_cookies = []
        for name, value, host, path_, expires, secure in rows:
            playwright_cookies.append({
                "name": name,
                "value": value,
                "domain": host,
                "path": path_ or "/",
                "expires": expires or -1,
                "httpOnly": False,
                "secure": bool(secure),
                "sameSite": "Lax",
            })
        return playwright_cookies
    except Exception as exc:
        logger.error("Chrome cookie okuma hatasi: %s", exc)
        tmp.unlink(missing_ok=True)
        return []


async def method_chrome_profile(browser_context, platform: str) -> Dict[str, Any]:
    """Chrome profile cookie'lerini browser context'e yukler."""
    cfg = load_config()
    profile_path = cfg.get("chrome_profile_path", "")
    if not profile_path:
        return {"ok": False, "error": "Chrome profile yolu girilmemis. Cockpit ayarlarindan ekle."}

    domain_map = {
        "instagram": "instagram.com",
        "x": "x.com",
        "twitter": "twitter.com",
        "facebook": "facebook.com",
    }
    domain = domain_map.get(platform, platform + ".com")
    cookies = get_chrome_cookies(profile_path, domain)
    if not cookies:
        return {"ok": False, "error": f"Chrome profilinde {domain} cookie bulunamadi. Tarayicida giris yapilmis mi?"}

    try:
        await browser_context.add_cookies(cookies)
        logger.info("%s icin %d Chrome cookie yuklendi", platform, len(cookies))
        return {"ok": True, "method": "chrome_profile", "platform": platform, "cookie_count": len(cookies)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Ana yonlendirici — process_radar bu fonksiyonu cagirir
# ---------------------------------------------------------------------------
async def search_profiles(
    query: str,
    platform: str,
    browser_page=None,
    browser_context=None,
) -> Dict[str, Any]:
    """
    Aktif yonteme gore profil aramasini calistirir.
    Sonucu dict olarak dondurur: {ok, method, results?, error?}
    """
    method = get_method()

    if method == "rapidapi":
        return await method_rapidapi_search(query, platform)

    elif method == "chrome_profile":
        if browser_context is None:
            return {"ok": False, "error": "Browser context gerekli"}
        result = await method_chrome_profile(browser_context, platform)
        return result

    else:  # method == "login" (varsayilan)
        # Session varsa direkt URL, yoksa login wall (kullanici /login yazmali)
        try:
            from social_login import has_session
            if has_session(platform):
                return {"ok": True, "method": "login", "session": True}
            else:
                return {"ok": False, "method": "login", "session": False,
                        "error": f"/login {platform} EMAIL SIFRE komutuyla giris yap"}
        except ImportError:
            return {"ok": False, "error": "social_login modulu bulunamadi"}
