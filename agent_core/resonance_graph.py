"""
Resonance Engine — LangGraph tabanlı state machine.
Psikolojik profil verisiyle skorlama yapar ve handover tetikler.
"""

import logging
from typing import TypedDict, Any, Dict
from langgraph.graph import StateGraph, END
from services.handover import trigger_handover
from services.interaction import InteractionAgent

logger = logging.getLogger("agent_core.resonance_graph")
logging.basicConfig(level=logging.INFO)

class ResonanceState(TypedDict, total=False):
    profile: Dict[str, Any]
    score: float
    strategy: str
    messages_sent: int
    handover_ready: bool
    status: str
    cookies: list

async def analyze_node(state: ResonanceState) -> ResonanceState:
    logger.info("analyze_node: Psikolojik profil analiz ediliyor.")
    # Profil analizi ProfileAnalyzer tarafindan daha onceden yapilmis ve state'e eklenmis olmali.
    state["status"] = "analyzed"
    return state

async def score_node(state: ResonanceState) -> ResonanceState:
    profile = state.get("profile", {})
    score = profile.get("resonance_score", 0.0)
    logger.info(f"score_node: Rezonans skoru hesaplandı -> {score}")
    state["score"] = score
    state["status"] = "scored"
    return state

async def strategize_node(state: ResonanceState) -> ResonanceState:
    logger.info("strategize_node: Strateji belirleniyor.")
    score = state.get("score", 0.0)

    if score >= 7.0:
        state["strategy"] = "direct_engagement"
    else:
        state["strategy"] = "passive_observation"

    state["status"] = "strategized"
    return state

async def act_node(state: ResonanceState) -> ResonanceState:
    logger.info(f"act_node: Aksiyon alınıyor (Strateji: {state.get('strategy')})")

    if state.get("strategy") == "direct_engagement":
        cookies = state.get("cookies", [])
        profile = state.get("profile", {})
        platform = profile.get("platform", "instagram")
        username = profile.get("username", "")
        achilles_heel = profile.get("achilles_heel", "")
        trigger_words = profile.get("trigger_words", [])

        if username and cookies:
            agent = InteractionAgent()
            try:
                await agent.start(cookies=cookies)
                # Takip Et
                await agent.follow_user(platform, username)

                # Kişiselleştirilmiş DM
                triggers_str = ", ".join(trigger_words[:2])
                message = f"Merhaba. Profilini inceledim. {achilles_heel} konusunda benzer düşünüyoruz. Özellikle {triggers_str} ilgimi çekti."

                dm_result = await agent.send_dm(platform, username, message)
                if dm_result.get("status") == "ok":
                    state["messages_sent"] = state.get("messages_sent", 0) + 1
            except Exception as e:
                logger.error(f"InteractionAgent hatası: {e}")
            finally:
                await agent.close()
        else:
            logger.warning("Username veya cookies eksik, InteractionAgent atlanıyor.")

    state["status"] = "acted"
    return state

async def evaluate_node(state: ResonanceState) -> ResonanceState:
    logger.info("evaluate_node: Aksiyon sonrası değerlendirme.")

    # Eger skor 7.0 ve uzerindeyse, hedef kullaniciya human-in-the-loop ile devret
    if state.get("score", 0.0) >= 7.0:
        logger.info("evaluate_node: Handover tetikleniyor!")
        state["handover_ready"] = True

        target_username = state.get("profile", {}).get("username", "@unknown")
        achilles_tendon = state.get("profile", {}).get("achilles_heel", "Bilinmiyor")

        try:
            await trigger_handover(
                target_username=target_username,
                achilles_tendon=achilles_tendon,
                frequency_score=state.get("score", 0.0),
                conversation_snippet="Aksiyon sonrası değerlendirme.",
            )
        except Exception as e:
            logger.error(f"Handover tetiklenirken hata: {e}")
    else:
        state["handover_ready"] = False

    state["status"] = "evaluated"
    return state

def create_resonance_graph():
    graph_builder = StateGraph(ResonanceState)

    graph_builder.add_node("analyze", analyze_node)
    graph_builder.add_node("score", score_node)
    graph_builder.add_node("strategize", strategize_node)
    graph_builder.add_node("act", act_node)
    graph_builder.add_node("evaluate", evaluate_node)

    graph_builder.set_entry_point("analyze")

    graph_builder.add_edge("analyze", "score")
    graph_builder.add_edge("score", "strategize")
    graph_builder.add_edge("strategize", "act")
    graph_builder.add_edge("act", "evaluate")

    # Conditional logic
    def handover_condition(state: ResonanceState) -> str:
        if state.get("handover_ready"):
            return END
        return END

    graph_builder.add_conditional_edges("evaluate", handover_condition)

    return graph_builder.compile()
