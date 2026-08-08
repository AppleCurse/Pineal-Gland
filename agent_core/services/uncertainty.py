"""
Uncertainty Engine — cross-validates LLM confidence against evidence strength.

Problem: LLM bazen confidence=0.95 der ama evidence 1 zayif cumledir.
         Veya confidence=0.3 der ama evidence gucludur (daha fazla veri lazim).

Bu motor:
  1. Evidence kalitesini olcer (specificity, quantity, coverage)
  2. Confidence ile evidence arasindaki celiskiyi tespit eder
  3. Aksiyon onerisi uretir: FLAG, COLLECT_MORE, TRUST
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.uncertainty")

# ---------------------------------------------------------------------------
# Evidence quality heuristics
# ---------------------------------------------------------------------------


def _evidence_strength(evidence: List[Any], sample_size: int) -> float:
    """Evidence kalitesini 0-1 arasi skorlar.

    Kriterler:
      - Kapsama: evidence item sayisi / sample_size
      - Specificity: sayisal ifade, alinti, veya gozlemlenebilir detay iceriyor mu
    """
    if not evidence or sample_size == 0:
        return 0.0

    coverage = min(len(evidence) / max(sample_size, 1), 1.0)

    specific_count = 0
    for e in evidence:
        e_str = e.get("excerpt", str(e)) if isinstance(e, dict) else str(e)
        # Fraction pattern: "7/12", "3 of 8"
        if re.search(r'\d+/\d+|\d+\s*of\s*\d+', e_str):
            specific_count += 1
        # Quoted text
        elif '"' in e_str or "'" in e_str or '`' in e_str:
            specific_count += 1
        # Percentage
        elif re.search(r'\d+%', e_str):
            specific_count += 1
        # Contains a number AND is longer than 20 chars (not just "user 123")
        elif re.search(r'\d+', e_str) and len(e_str) > 20:
            specific_count += 1
        # Contains observable detail keywords
        elif any(kw in e_str.lower() for kw in ('daily', 'weekly', 'always', 'never', 'every', 'most', 'majority', 'minority', 'typically', 'usually')):
            specific_count += 1

    specificity = specific_count / max(len(evidence), 1)

    # Weighted: coverage 0.4 + specificity 0.6
    return round(0.4 * coverage + 0.6 * specificity, 2)


def _stability_gap(confidence: float, stability: float) -> float:
    """Confidence yuksek ama stability dusukse gap buyuk → FLAG."""
    return confidence - stability


# ---------------------------------------------------------------------------
# Signal-level verdict
# ---------------------------------------------------------------------------


@dataclass
class SignalVerdict:
    signal_name: str
    confidence: float
    stability: float
    evidence_strength: float
    verdict: str  # TRUST | FLAG | COLLECT_MORE
    reason: str


def evaluate_signal(
    name: str,
    confidence: float,
    stability: float,
    evidence: List[Any],
    sample_size: int,
) -> SignalVerdict:
    """Tek bir sinyal kategorisini degerlendirir."""
    strength = _evidence_strength(evidence, sample_size)
    gap = _stability_gap(confidence, stability)

    # High confidence + low evidence strength = FLAG (LLM overconfident)
    if confidence >= 0.7 and strength < 0.35:
        return SignalVerdict(
            signal_name=name,
            confidence=confidence,
            stability=stability,
            evidence_strength=strength,
            verdict="FLAG",
            reason=f"High confidence ({confidence:.2f}) but weak evidence (strength={strength:.2f}). LLM may be overconfident.",
        )

    # High confidence + low stability = FLAG (pattern not consistent)
    if gap > 0.5:
        return SignalVerdict(
            signal_name=name,
            confidence=confidence,
            stability=stability,
            evidence_strength=strength,
            verdict="FLAG",
            reason=f"Confidence-stability gap ({gap:.2f}): signal is clear but not consistent across sample.",
        )

    # Low confidence + decent evidence = COLLECT_MORE
    if confidence < 0.5 and strength >= 0.4:
        return SignalVerdict(
            signal_name=name,
            confidence=confidence,
            stability=stability,
            evidence_strength=strength,
            verdict="COLLECT_MORE",
            reason=f"Decent evidence (strength={strength:.2f}) but low confidence ({confidence:.2f}). More data may clarify.",
        )

    # Low confidence + low stability + low sample = COLLECT_MORE
    if confidence < 0.5 and stability < 0.3 and sample_size < 10:
        return SignalVerdict(
            signal_name=name,
            confidence=confidence,
            stability=stability,
            evidence_strength=strength,
            verdict="COLLECT_MORE",
            reason=f"Low confidence ({confidence:.2f}), low stability ({stability:.2f}), small sample ({sample_size}). Need more data.",
        )

    return SignalVerdict(
        signal_name=name,
        confidence=confidence,
        stability=stability,
        evidence_strength=strength,
        verdict="TRUST",
        reason=f"Confidence ({confidence:.2f}) aligns with evidence strength ({strength:.2f}) and stability ({stability:.2f}).",
    )


# ---------------------------------------------------------------------------
# Profile-level verdict
# ---------------------------------------------------------------------------


@dataclass
class UncertaintyReport:
    schema_version: str = "1.0"
    profile_overall_confidence: float = 0.0
    sample_size: int = 0
    period_days: Optional[float] = None
    signals: List[SignalVerdict] = field(default_factory=list)
    flagged_count: int = 0
    collect_more_count: int = 0
    trusted_count: int = 0
    summary: str = ""


def evaluate_profile(profile: Dict[str, Any]) -> UncertaintyReport:
    """Tam BehavioralProfile'i degerlendirir, UncertaintyReport dondurur.

    Bu fonksiyon hic LLM cagirmaz — tamamen deterministic.
    """
    sample_size = profile.get("sample_size", 0)
    period_days = profile.get("period_days")

    signal_specs = [
        ("communication_signals", ["confidence", "stability", "evidence"]),
        ("topic_affinity", ["theme_confidence", "stability", "evidence"]),
        ("posting_pattern", ["confidence", "stability", "evidence"]),
        ("interaction_pattern", ["confidence", "stability", "evidence"]),
    ]

    verdicts: List[SignalVerdict] = []
    for sig_name, (conf_key, stab_key, ev_key) in signal_specs:
        sig_data = profile.get(sig_name) or {}
        if not sig_data:
            verdicts.append(SignalVerdict(
                signal_name=sig_name,
                confidence=0.0, stability=0.0, evidence_strength=0.0,
                verdict="COLLECT_MORE",
                reason="Signal data missing.",
            ))
            continue

        confidence = float(sig_data.get(conf_key, 0.0))
        stability = float(sig_data.get(stab_key, 0.0))
        evidence = sig_data.get(ev_key, []) or []

        verdicts.append(evaluate_signal(
            name=sig_name,
            confidence=confidence,
            stability=stability,
            evidence=evidence,
            sample_size=sample_size,
        ))

    flagged = sum(1 for v in verdicts if v.verdict == "FLAG")
    collect = sum(1 for v in verdicts if v.verdict == "COLLECT_MORE")
    trusted = sum(1 for v in verdicts if v.verdict == "TRUST")

    # Summary
    if flagged > 0:
        summary = f"⚠️ {flagged} signal(s) FLAGGED — confidence-evidence mismatch. Do not trust blindly."
    elif collect > 0:
        summary = f"📊 {collect} signal(s) need more data. Profile is usable but incomplete."
    elif sample_size < 5:
        summary = f"📊 Small sample ({sample_size} points). Signals look consistent but verify with more data."
    else:
        summary = f"✅ All {trusted} signals TRUSTed — confidence aligns with evidence."

    return UncertaintyReport(
        profile_overall_confidence=profile.get("overall_confidence", 0.0),
        sample_size=sample_size,
        period_days=period_days,
        signals=verdicts,
        flagged_count=flagged,
        collect_more_count=collect,
        trusted_count=trusted,
        summary=summary,
    )
