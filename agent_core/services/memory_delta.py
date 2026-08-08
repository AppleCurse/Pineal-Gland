"""
Memory Delta Tracking — BehavioralProfile degisimlerini izler.

Her analiz sonrasi profil kaydedilir. Eski kayit varsa delta hesaplanir.
COLLECT_MORE verdiginde sistem yeniden scrape zamanlamasini ayarlar.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.memory_delta")

MEMORY_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILE_HISTORY_FILE = MEMORY_DIR / "profile_history.json"


@dataclass
class ProfileSnapshot:
    """Tek bir zaman dilimindeki BehavioralProfile + metadata."""
    username: str
    platform: str
    timestamp: str
    profile: Dict[str, Any]
    overall_confidence: float
    sample_size: int
    flagged_signals: List[str] = field(default_factory=list)
    stability_avg: float = 0.0


@dataclass
class BehavioralDelta:
    """Iki snapshot arasindaki fark."""
    username: str
    platform: str
    prev_timestamp: str
    next_timestamp: str
    changed_fields: List[str] = field(default_factory=list)
    evidence_delta: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def _load_history() -> Dict[str, List[Dict[str, Any]]]:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILE_HISTORY_FILE.exists():
        try:
            return json.loads(PROFILE_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_history(data: Dict[str, List[Dict[str, Any]]]) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_HISTORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _compute_delta(prev: Dict[str, Any], next_snap: Dict[str, Any]) -> BehavioralDelta:
    """Iki snapshot arasindaki farki hesaplar."""
    changed: List[str] = []
    evidence_deltas: List[Dict[str, Any]] = []

    # Signal alanlarini karsilastir
    for sig in ["communication_signals", "topic_affinity", "posting_pattern", "interaction_pattern"]:
        p = (prev.get(sig) or {}).get(sig.split("_")[0], {})
        n = (next_snap.get(sig) or {})
        # Basit karsilastirma: major alanlar degisti mi?
        for key in ["tone_style", "primary_themes", "frequency_indicator", "response_style"]:
            if p.get(key) != n.get(key):
                changed.append(f"{sig}.{key}")
                evidence_deltas.append({
                    "field": f"{sig}.{key}",
                    "prev": p.get(key),
                    "next": n.get(key),
                })

    reason = ""
    if changed:
        reason = f"{len(changed)} signal changed: {', '.join(changed[:5])}"
    else:
        reason = "no behavioral change detected"

    return BehavioralDelta(
        username=next_snap.get("username", prev.get("username", "")),
        platform=next_snap.get("platform", prev.get("platform", "unknown")),
        prev_timestamp=prev.get("extraction_timestamp", ""),
        next_timestamp=next_snap.get("extraction_timestamp", ""),
        changed_fields=changed,
        evidence_delta=evidence_deltas,
        reason=reason,
    )


def record_profile(profile: Dict[str, Any]) -> Optional[BehavioralDelta]:
    """Profili history'ye kaydeder. Onceki kayit varsa delta hesaplar."""
    username = profile.get("username")
    platform = profile.get("platform", "unknown")
    if not username:
        return None

    key = f"{platform}:{username.lower()}"
    history = _load_history()

    current_snap = dict(profile)
    prev_confidence = profile.get("overall_confidence", 0.0)
    prev_sample = profile.get("sample_size", 0)

    # Flagged sinyaler
    from services.uncertainty import evaluate_profile
    flagged = []
    try:
        report = evaluate_profile(profile)
        flagged = [s.signal_name for s in report.signals if s.verdict == "FLAG"]
    except Exception:
        pass

    snapshot = {
        "username": username,
        "platform": platform,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "overall_confidence": prev_confidence,
        "sample_size": prev_sample,
        "flagged_signals": flagged,
    }

    delta: Optional[BehavioralDelta] = None
    if key in history:
        prev_entry = history[key][-1]
        prev_profile = prev_entry.get("profile", {})
        delta = _compute_delta(prev_profile, profile)
        logger.info(
            "Memory delta for %s: %s", key, delta.reason
        )

    history.setdefault(key, []).append(snapshot)
    # Son 20 snapshot tut
    if len(history[key]) > 20:
        history[key] = history[key][-20:]

    _save_history(history)
    logger.info("Memory kaydedildi: %s (toplam %d snapshot)", key, len(history[key]))
    return delta


def get_latest(username: str, platform: str = "instagram") -> Optional[Dict[str, Any]]:
    """En son profile snapshot'u dondurur."""
    key = f"{platform}:{username.lower()}"
    history = _load_history()
    if key in history and history[key]:
        return history[key][-1]
    return None


def get_history(username: str, platform: str = "instagram", limit: int = 10) -> List[Dict[str, Any]]:
    """Profil gecmisini dondurur."""
    key = f"{platform}:{username.lower()}"
    history = _load_history()
    entries = history.get(key, [])
    return entries[-limit:] if entries else []


def should_collect_more(profile: Dict[str, Any]) -> bool:
    """COLLECT_MORE gerekip gerekmedigini belirler."""
    # Kullanimda degil — orchestrator UncertaintyEngine'e soracak
    return True
