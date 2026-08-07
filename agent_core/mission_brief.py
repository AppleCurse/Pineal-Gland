"""
Dinamik Niyet Motoru — MissionBrief Generator.

Telegram'dan "/radar <serbest metin>" komutu alır, LLMGateway üzerinden
yapılandırılmış şema olarak ayrıştırır ve current_mission_brief.json'a kaydeder.

Kullanım:
    python mission_brief.py "/radar İstanbul'da vintage moda seven 25-35 yaş kadın"
    python mission_brief.py --text "Minimalist yaşam ve sürdürülebilirlik"
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from services.llm_gateway import get_llm_gateway

logger = logging.getLogger("agent_core.mission_brief")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Çıktı dosyası
OUTPUT_FILE = Path(__file__).resolve().parent / "current_mission_brief.json"


class MissionBrief(BaseModel):
    """Pydantic şema — tüm alanlar zorunlu."""
    vibe_concept: str = Field(..., description="Hedef kitlenin ruh hali / estetik kimliği (1-2 cümle)")
    core_triggers: List[str] = Field(..., min_length=3, max_length=8,
                                      description="Kitleyi tetikleyen duygusal/psikolojik motivasyonlar")
    dealbreakers: List[str] = Field(..., min_length=2, max_length=5,
                                     description="Kesinlikle kaçınılacak içerik/ton öğeleri")
    search_queries: List[str] = Field(..., min_length=3, max_length=8,
                                       description="X/Instagram araması için negatif operatörlü sorgular")
    raw_input: str = Field(default="", description="Ham kullanıcı girdisi")
    generated_at: str = Field(default="", description="ISO timestamp")


SYSTEM_PROMPT = """Sen bir sosyal medya strateji uzmanısın. Kullanıcının serbest metin girdisini analiz ederek
tam olarak şu JSON formatında çıktı üret. Başka hiçbir şey yazma, sadece geçerli JSON döndür:

{
  "vibe_concept": "<hedef kitlenin ruh hali ve estetik kimliği, 1-2 Türkçe cümle>",
  "core_triggers": ["<motivasyon 1>", "<motivasyon 2>", "...", "<en az 3 madde>"],
  "dealbreakers": ["<kaçınılacak öğe 1>", "<kaçınılacak öğe 2>", "<en az 2 madde>"],
  "search_queries": [
    "<konu anahtar kelime -reklam -spam lang:tr>",
    "<estetik_etiket OR mood_etiket -tanıtım>",
    "<en az 3, negatif operatörlü X/Instagram sorgusu>"
  ]
}"""


def _clean_radar_command(text: str) -> str:
    """'/radar ' önekini temizle."""
    text = text.strip()
    if text.lower().startswith("/radar"):
        text = text[6:].strip()
    return text


async def generate_mission_brief(raw_text: str) -> MissionBrief:
    """LLMGateway üzerinden MissionBrief oluşturur (model-agnostic)."""
    intent = _clean_radar_command(raw_text)
    logger.info("MissionBrief üretiliyor: '%s'", intent[:60])

    gateway = get_llm_gateway()

    brief = await gateway.chat_and_parse(
        messages=[{"role": "user", "content": f"Analiz et ve MissionBrief üret: {intent}"}],
        schema=MissionBrief,
        system=SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=1024,
    )

    # Meta alanları doldur
    brief.raw_input = intent
    brief.generated_at = datetime.now(timezone.utc).isoformat()

    # Dosyaya kaydet
    OUTPUT_FILE.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    logger.info("MissionBrief kaydedildi: %s", OUTPUT_FILE)
    return brief


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MissionBrief Generator")
    parser.add_argument("text", nargs="?", help="Serbest metin veya /radar komutu")
    parser.add_argument("--text", dest="text_flag", help="--text ile de verebilirsin")
    args = parser.parse_args()

    input_text = args.text or args.text_flag
    if not input_text:
        print("Kullanim: python mission_brief.py '/radar <metin>'")
        sys.exit(1)

    brief = asyncio.run(generate_mission_brief(input_text))
    print("\n=== MISSION BRIEF ===")
    print(brief.model_dump_json(indent=2))
