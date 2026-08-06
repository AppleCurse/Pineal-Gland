"""
Profile Analyzer Service — Psikolojik Profil Analizi.

Claude API kullanarak hedeflenen profillerin psikolojik analizini yapar,
json olarak döndürür: dominant_emotion, achilles_heel, trigger_words, resonance_score.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger("agent_core.analyzer")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-5"


class PsychologicalProfile(BaseModel):
    dominant_emotion: str = Field(..., description="Baskın duygu hali")
    achilles_heel: str = Field(..., description="Zayıf nokta / Aşil tendonu")
    trigger_words: List[str] = Field(..., description="Tetikleyici kelimeler (3-5 adet)")
    resonance_score: float = Field(..., description="Rezonans skoru (0-10 arası, uygunluk)")


SYSTEM_PROMPT = """Sen uzman bir psikolojik profil analizcisisin.
Kullanıcının gönderdiği sosyal medya verilerini (bio ve son gönderiler) analiz ederek,
kullanıcının psikolojik profilini çıkaracaksın.
Çıktını sadece aşağıdaki JSON formatında üret. Başka hiçbir şey yazma.

{
  "dominant_emotion": "<Baskın duygu hali, 1-2 kelime>",
  "achilles_heel": "<Zayıf nokta, Aşil tendonu, güvensizlik veya ihtiyaç duyulan şey>",
  "trigger_words": ["<kelime1>", "<kelime2>", "<kelime3>"],
  "resonance_score": <0.0 ile 10.0 arası bir sayı>
}"""

class ProfileAnalyzer:
    async def analyze(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Scraper'dan gelen veriyi analiz eder ve psikolojik profil döner."""
        if not scraped_data:
            return {}

        bio = scraped_data.get("bio", "")
        posts = "\n".join(scraped_data.get("recent_posts", [])[:10])
        followers = scraped_data.get("followers", "N/A")

        content = f"Profil Bio: {bio}\nTakipçi: {followers}\nSon Gönderiler:\n{posts}"
        logger.info(f"Profil analizi başlıyor (Bio uzunluğu: {len(bio)}, Gönderi sayısı: {len(scraped_data.get('recent_posts', []))})")

        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Şu profil verilerini analiz et:\n\n{content}"},
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        }

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5060",
            "X-Title": "DijitalVarlik-AgentCore",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            raw_json_str = data["choices"][0]["message"]["content"]

            # JSON parse
            try:
                parsed = json.loads(raw_json_str)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", raw_json_str, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                else:
                    raise ValueError(f"Geçerli JSON bulunamadı:\n{raw_json_str[:200]}")

            # Pydantic validation
            profile = PsychologicalProfile(**parsed)
            return profile.model_dump()

        except Exception as e:
            logger.error(f"Profil analizi sırasında hata oluştu: {e}")
            return {
                "dominant_emotion": "Bilinmiyor",
                "achilles_heel": "Bilinmiyor",
                "trigger_words": [],
                "resonance_score": 0.0,
                "error": str(e)
            }
