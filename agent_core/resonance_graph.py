"""
Resonance Engine — LangGraph tabanli state machine.

Compatibility Vector ile cok boyutlu eslesme skoru hesaplar.
Uncertainty Engine ile confidence-evidence tutarliligini kontrol eder.
"""
from __future__ import annotations

import logging
from typing import TypedDict, Any, Dict, Optional

from langgraph.graph import StateGraph, END

from services.handover import trigger_handover
from services.interaction import InteractionAgent
from services.uncertainty import evaluate_profile, UncertaintyReport

logger = logging.getLogger("agent_core.resonance_graph")
logging.basicConfig(level=logging.INFO)

# Esikler
ENGAGEMENT_THRESHOLD = 0.60  # composite compatibility minimum
FLAG_TOLERANCE = 1  # en fazla kac FLAG'e tolerans gosterilir


class CompatibilityVector(TypedDict, total=False):
    """Cok boyutlu eslesme vektoru — tek skor yerine 4 boyut."""

    communication_match: float  # tone_style + expressiveness uyumu (0-1)
    interest_match: float       # primary_themes ortusmesi (0-1)
    response_match: float       # response_style + conflict uyumu (0-1)
    pacing_match: float         # frequency + engagement uyumu (0-1)
    composite: float            # agirlikli ortalama


class ResonanceState(TypedDict, total=False):
    profile: Dict[str, Any]
    compatibility: CompatibilityVector
    strategy: str
    messages_sent: int
    handover_ready: bool
    uncertainty: Optional[Dict[str, Any]]
    status: str
    cookies: list


# ---------------------------------------------------------------------------
# Profile extractors
# ---------------------------------------------------------------------------


def _sig(profile: Dict[str, Any], name: str) -> Dict[str, Any]:
    return (profile.get(name) or {})


def _get_top_themes(profile: Dict[str, Any]) -> list:
    return _sig(profile, "topic_affinity").get("primary_themes", [])


def _get_tone(profile: Dict[str, Any]) -> str:
    return _sig(profile, "communication_signals").get("tone_style", "bilinmiyor")


# ---------------------------------------------------------------------------
# Compatibility Vector hesaplama (deterministic)
# ---------------------------------------------------------------------------


def compute_compatibility(profile: Dict[str, Any]) -> CompatibilityVector:
    """BehavioralProfile'tan cok boyutlu Compatibility Vector hesaplar.

    Her boyut 0-1 arasi. LLM cagrilmaz — tamamen deterministic.
    """
    comm = _sig(profile, "communication_signals")
    topic = _sig(profile, "topic_affinity")
    post = _sig(profile, "posting_pattern")
    inter = _sig(profile, "interaction_pattern")

    # Communication match: confidence-weighted
    comm_match = comm.get("confidence", 0.0)
    # Duzelt: stability dusukse cezalandir
    comm_stability = comm.get("stability", 0.5)
    communication_match = round(comm_match * 0.6 + comm_stability * 0.4, 2)

    # Interest match: theme confidence + evidence count as signal
    theme_conf = topic.get("theme_confidence", 0.0)
    theme_stability = topic.get("stability", 0.5)
    theme_count = len(topic.get("primary_themes", []))
    theme_bonus = min(theme_count / 5.0, 1.0) * 0.2  # max 0.2 bonus for 5+ themes
    interest_match = round(min(theme_conf * 0.5 + theme_stability * 0.3 + theme_bonus, 1.0), 2)

    # Response match: interaction confidence
    resp_conf = inter.get("confidence", 0.0)
    resp_stability = inter.get("stability", 0.5)
    response_match = round(resp_conf * 0.6 + resp_stability * 0.4, 2)

    # Pacing match: posting confidence
    pace_conf = post.get("confidence", 0.0)
    pace_stability = post.get("stability", 0.5)
    pacing_match = round(pace_conf * 0.5 + pace_stability * 0.5, 2)

    # Composite: weighted average (communication + interest heavier)
    composite = round(
        communication_match * 0.30
        + interest_match * 0.30
        + response_match * 0.20
        + pacing_match * 0.20,
        2,
    )

    return CompatibilityVector(
        communication_match=communication_match,
        interest_match=interest_match,
        response_match=response_match,
        pacing_match=pacing_match,
        composite=composite,
    )


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------


async def analyze_node(state: ResonanceState) -> ResonanceState:
    logger.info("analyze_node: Davranissal sinyal profili isleniyor.")

    profile = state.get("profile", {})

    # Compatibility Vector hesapla
    cv = compute_compatibility(profile)
    state["compatibility"] = cv
    logger.info(
        "Compatibility Vector: comm=%.2f interest=%.2f response=%.2f pacing=%.2f → composite=%.2f",
        cv["communication_match"], cv["interest_match"],
        cv["response_match"], cv["pacing_match"], cv["composite"],
    )

    # Uncertainty Engine ile confidence-evidence tutarliligini kontrol et
    try:
        report: UncertaintyReport = evaluate_profile(profile)
        uncertainty_data = {
            "flagged_count": report.flagged_count,
            "collect_more_count": report.collect_more_count,
            "trusted_count": report.trusted_count,
            "summary": report.summary,
            "signals": [
                {
                    "name": s.signal_name,
                    "verdict": s.verdict,
                    "confidence": s.confidence,
                    "stability": s.stability,
                    "evidence_strength": s.evidence_strength,
                    "reason": s.reason,
                }
                for s in report.signals
            ],
        }
        state["uncertainty"] = uncertainty_data
        logger.info("Uncertainty: %s", report.summary)
    except Exception as exc:
        logger.warning("Uncertainty Engine hatasi: %s", exc)
        state["uncertainty"] = None

    state["status"] = "analyzed"
    return state


async def strategize_node(state: ResonanceState) -> ResonanceState:
    logger.info("strategize_node: Strateji belirleniyor.")
    cv = state.get("compatibility", {})
    composite = cv.get("composite", 0.0)
    uncertainty = state.get("uncertainty") or {}
    flagged = uncertainty.get("flagged_count", 0)

    # FLAG varsa composite'i gecici olarak dustur
    if flagged > FLAG_TOLERANCE:
        logger.warning(
            "strategize_node: %d FLAG'li sinyal — composite %.2f -> %.2f (penalized)",
            flagged, composite, composite * 0.7,
        )
        composite *= 0.7

    if composite >= ENGAGEMENT_THRESHOLD:
        state["strategy"] = "direct_engagement"
    else:
        state["strategy"] = "passive_observation"

    state["status"] = "strategized"
    return state


async def act_node(state: ResonanceState) -> ResonanceState:
    logger.info(f"act_node: Aksiyon aliniyor (Strateji: {state.get('strategy')})")

    if state.get("strategy") == "direct_engagement":
        cookies = state.get("cookies", [])
        profile = state.get("profile", {})
        platform = profile.get("platform", "instagram")
        username = profile.get("username", "")
        themes = _get_top_themes(profile)
        tone = _get_tone(profile)

        if username and cookies:
            agent = InteractionAgent()
            try:
                await agent.start(cookies=cookies)
                await agent.follow_user(platform, username)

                themes_str = ", ".join(themes[:2]) if themes else "ortak ilgi alanlari"
                message = (
                    f"Merhaba. Profilini inceledim ve {tone} iletisim tarzin "
                    f"ilgimi cekti. Ozellikle {themes_str} konularinda benzer dusunuyoruz."
                )

                dm_result = await agent.send_dm(platform, username, message)
                if dm_result.get("status") == "ok":
                    state["messages_sent"] = state.get("messages_sent", 0) + 1
            except Exception as e:
                logger.error(f"InteractionAgent hatasi: {e}")
            finally:
                await agent.close()
        else:
            logger.warning("Username veya cookies eksik, InteractionAgent atlaniyor.")

    state["status"] = "acted"
    return state


async def evaluate_node(state: ResonanceState) -> ResonanceState:
    logger.info("evaluate_node: Aksiyon sonrasi degerlendirme.")
    cv = state.get("compatibility", {})
    composite = cv.get("composite", 0.0)
    uncertainty = state.get("uncertainty") or {}
    flagged = uncertainty.get("flagged_count", 0)

    if composite >= ENGAGEMENT_THRESHOLD and flagged <= FLAG_TOLERANCE:
        logger.info("evaluate_node: Handover tetikleniyor!")
        state["handover_ready"] = True

        target_username = state.get("profile", {}).get("username", "@unknown")
        profile = state.get("profile", {})
        tone = _get_tone(profile)
        themes = _get_top_themes(profile)
        summary = (
            f"Iletisim tonu: {tone}. Ilgi alanlari: {', '.join(themes[:3]) if themes else 'yok'}. "
            f"Compatibility: comm={cv.get('communication_match', 0):.2f} "
            f"interest={cv.get('interest_match', 0):.2f} "
            f"response={cv.get('response_match', 0):.2f} "
            f"pacing={cv.get('pacing_match', 0):.2f}"
        )

        try:
            await trigger_handover(
                target_username=target_username,
                achilles_tendon=summary,
                frequency_score=composite * 10,
                conversation_snippet="Aksiyon sonrasi degerlendirme.",
            )
        except Exception as e:
            logger.error(f"Handover tetiklenirken hata: {e}")
    else:
        if flagged > FLAG_TOLERANCE:
            logger.info("evaluate_node: Handover ertelendi — %d FLAG'li sinyal var.", flagged)
        else:
            logger.info("evaluate_node: Compatibility %.2f < threshold %.2f", composite, ENGAGEMENT_THRESHOLD)
        state["handover_ready"] = False

    state["status"] = "evaluated"
    return state

def create_resonance_graph():
    graph_builder = StateGraph(ResonanceState)

    graph_builder.add_node("analyze", analyze_node)

    graph_builder.add_node("strategize", strategize_node)
    graph_builder.add_node("act", act_node)
    graph_builder.add_node("evaluate", evaluate_node)

    graph_builder.set_entry_point("analyze")

    graph_builder.add_edge("analyze", "strategize")

    graph_builder.add_edge("strategize", "act")
    graph_builder.add_edge("act", "evaluate")

    # Conditional logic
    def handover_condition(state: ResonanceState) -> str:
        if state.get("handover_ready"):
            return END
        return END

    graph_builder.add_conditional_edges("evaluate", handover_condition)

    return graph_builder.compile()
