"""
Instagram / X (Twitter) Scraper — Playwright Stealth Modu + İnsan Davranışı Taklidi.

Özellikler:
  - playwright-stealth ile bot tespitini atlatır
  - Random 2-5sn bekleme, scroll hareketi, mouse simülasyonu
  - Profil bio, son 20 gönderi metni ve görsel URL'lerini JSON olarak döndürür
  - Sonuçlar data/scraped_profiles.json dosyasında önbelleklenir

Kullanım:
    python scraper.py --url https://www.instagram.com/nasa/ --platform instagram
    python scraper.py --url https://x.com/nasa --platform x
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth

logger = logging.getLogger("agent_core.scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Önbellek dosyası
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "scraped_profiles.json"

# Gerçekçi user-agent listesi
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def human_delay(min_s: float = 2.0, max_s: float = 5.0):
    """Gerçek insan gibi rastgele bekleme."""
    delay = random.uniform(min_s, max_s)
    logger.debug("İnsan gecikmesi: %.2f sn", delay)
    await asyncio.sleep(delay)


async def human_scroll(page: Page, scrolls: int = 3):
    """Rastgele miktarda scroll hareketi."""
    for _ in range(scrolls):
        scroll_amount = random.randint(300, 700)
        await page.mouse.wheel(0, scroll_amount)
        await asyncio.sleep(random.uniform(0.4, 1.2))


async def human_mouse_move(page: Page):
    """Rastgele mouse hareketi."""
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    for _ in range(3):
        x = random.randint(100, viewport["width"] - 100)
        y = random.randint(100, viewport["height"] - 100)
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.4))


def _load_cache() -> Dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _is_stale(entry: Dict[str, Any], ttl_seconds: float = 86400.0) -> bool:
    """scraped_at timestamp'ine bakarak cache girdisinin eski olup olmadigini kontrol eder.
    
    TTL default: 24 saat.
    Entry'da scraped_at yoksa eski kabul edilir (bos veya corrupted cache'den kurtulmak icin).
    """
    scraped_at_str = entry.get("scraped_at")
    if not scraped_at_str:
        return True  # timestamp yoksa yeniden cek
    try:
        from datetime import datetime, timezone
        scraped = datetime.fromisoformat(scraped_at_str.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - scraped).total_seconds()
        return age > ttl_seconds
    except (ValueError, TypeError):
        return True  # parse edilemiyorsa eski kabul et, yeniden cek


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Önbellek kaydetme hatası: %s", e)


async def scrape_instagram(page: Page, username: str) -> Dict[str, Any]:
    """Instagram profil scraping."""
    url = f"https://www.instagram.com/{username}/"
    logger.info("Instagram profil yükleniyor: %s", url)
    
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await human_delay(2, 4)
    await human_mouse_move(page)
    await human_scroll(page, scrolls=2)
    await human_delay(1, 2)

    result: Dict[str, Any] = {
        "platform": "instagram",
        "username": username,
        "url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "bio": "",
        "followers": "N/A",
        "following": "N/A",
        "posts_count": "N/A",
        "recent_posts": [],
        "post_images": [],
    }

    # Meta description'dan istatistik çek (birden fazla kaynaktan dene)
    try:
        # Önce og:description dene (daha zengin içerik)
        meta_desc = await page.get_attribute('meta[property="og:description"]', "content") or ""
        if not meta_desc:
            meta_desc = await page.get_attribute('meta[name="description"]', "content") or ""
        result["raw_meta"] = meta_desc

        # Format (EN): "9.7M Followers, 500 Following, 3,651 Posts"
        # Format (TR): "104M Takipcik, 96 Takip, 4,869 Gonderi"
        m = re.search(
            r"([\d\.,]+[KkMmBb]?)\s+(?:Followers?|Takip\w*),\s*([\d\.,]+[KkMmBb]?)\s+(?:Following|Takip),\s*([\d\.,]+[KkMmBb]?)\s+(?:Posts?|G\w+)",
            meta_desc,
            re.IGNORECASE,
        )
        if m:
            result["followers"] = m.group(1)
            result["following"] = m.group(2)
            result["posts_count"] = m.group(3)
        else:
            logger.info("Takipci verisi meta'da bulunamadi (login gerekiyor olabilir). Ham meta: %s", meta_desc[:150])
    except Exception as e:
        logger.warning("Meta okuma hatasi: %s", e)

    # Bio metni
    try:
        bio_selectors = [
            'meta[property="og:description"]',
            'meta[name="description"]',
        ]
        for sel in bio_selectors:
            bio = await page.get_attribute(sel, "content")
            if bio:
                result["bio"] = bio
                break
    except Exception:
        pass

    # Son gönderi metinleri (aria-label veya alt text)
    try:
        articles = await page.query_selector_all("article img")
        for img in articles[:20]:
            alt = await img.get_attribute("alt") or ""
            src = await img.get_attribute("src") or ""
            if alt or src:
                result["recent_posts"].append(alt[:200])
                if src and src.startswith("http"):
                    result["post_images"].append(src)
    except Exception as e:
        logger.warning("Gönderi okuma hatası: %s", e)

    logger.info(
        "Instagram scraped OK: %s | Takipçi: %s | Gönderi: %d",
        username, result["followers"], len(result["recent_posts"])
    )
    return result


async def scrape_x(page: Page, username: str) -> Dict[str, Any]:
    """X (Twitter) profil scraping."""
    url = f"https://x.com/{username}"
    logger.info("X profil yükleniyor: %s", url)

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await human_delay(2, 4)
    await human_mouse_move(page)
    await human_scroll(page, scrolls=3)
    await human_delay(1, 3)

    result: Dict[str, Any] = {
        "platform": "x",
        "username": username,
        "url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "bio": "",
        "followers": "N/A",
        "following": "N/A",
        "posts_count": "N/A",
        "recent_posts": [],
        "post_images": [],
    }

    # Meta veriler
    try:
        og_desc = await page.get_attribute('meta[property="og:description"]', "content") or ""
        result["bio"] = og_desc

        # Follower sayısı
        m = re.search(r"([\d\.,]+[KkMmBb]?)\s+Followers?", og_desc, re.IGNORECASE)
        if m:
            result["followers"] = m.group(1)
    except Exception as e:
        logger.warning("X meta okuma hatası: %s", e)

    # Tweet metinleri
    try:
        tweets = await page.query_selector_all('[data-testid="tweetText"]')
        for tweet in tweets[:20]:
            text = await tweet.inner_text()
            if text:
                result["recent_posts"].append(text.strip()[:300])
    except Exception as e:
        logger.warning("Tweet okuma hatası: %s", e)

    # Gönderi görselleri
    try:
        imgs = await page.query_selector_all('[data-testid="tweetPhoto"] img')
        for img in imgs[:20]:
            src = await img.get_attribute("src") or ""
            if src.startswith("http"):
                result["post_images"].append(src)
    except Exception as e:
        logger.warning("X görsel okuma hatası: %s", e)

    logger.info(
        "X scraped OK: %s | Takipçi: %s | Tweet: %d",
        username, result["followers"], len(result["recent_posts"])
    )
    return result


async def scrape_target(
    target: str,
    platform: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Ana scraping fonksiyonu. URL veya kullanıcı adı alır.
    Cache'de varsa döner, yoksa Playwright ile çeker.
    """
    # Platform ve kullanıcı adı tespiti
    clean = target.strip().lstrip("@")
    if "instagram.com" in clean:
        platform = "instagram"
        username = clean.split("instagram.com/")[-1].strip("/").split("?")[0]
    elif "x.com" in clean or "twitter.com" in clean:
        platform = "x"
        username = clean.split("/")[-1].split("?")[0]
    else:
        platform = platform or "instagram"
        username = clean

    cache_key = f"{platform}:{username.lower()}"
    cache = _load_cache()

    if not force_refresh and cache_key in cache:
        entry = cache[cache_key]
        if not _is_stale(entry):
            logger.info("Önbellekten döndü (taze): %s", cache_key)
            return entry
        logger.info("Önbellek eski (TTL aştı): %s — yeniden cekiliyor", cache_key)

    # Playwright stealth ile çek
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
            ],
        )

        ua = random.choice(USER_AGENTS)
        stealth_obj = Stealth(
            navigator_languages_override=("tr-TR", "tr", "en-US", "en"),
            webgl_vendor_override="Intel Inc.",
            webgl_renderer_override="Intel Iris OpenGL Engine",
        )
        context = await browser.new_context(
            user_agent=ua,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(720, 1080)},
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
        )
        await stealth_obj.apply_stealth_async(context)
        page = await context.new_page()

        try:
            if platform == "instagram":
                result = await scrape_instagram(page, username)
            else:
                result = await scrape_x(page, username)
        except Exception as exc:
            logger.error("Scraping hatası: %s", exc)
            result = {
                "platform": platform,
                "username": username,
                "url": target,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error": str(exc),
                "bio": "", "followers": "N/A", "following": "N/A",
                "posts_count": "N/A", "recent_posts": [], "post_images": [],
            }
        finally:
            await browser.close()

    # Önbelleğe kaydet
    cache[cache_key] = result
    _save_cache(cache)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Social Media Scraper")
    parser.add_argument("--url", required=True, help="Instagram/X URL veya kullanıcı adı")
    parser.add_argument("--platform", default=None, choices=["instagram", "x"])
    parser.add_argument("--fresh", action="store_true", help="Önbelleği yoksay")
    args = parser.parse_args()

    result = asyncio.run(scrape_target(args.url, platform=args.platform, force_refresh=args.fresh))
    # Windows cp1254 uyumlu çıktı
    output = json.dumps(result, ensure_ascii=True, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
