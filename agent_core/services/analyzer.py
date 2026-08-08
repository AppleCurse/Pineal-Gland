"""
Profile Analyzer Service — Behavioral Signal Extraction.

Gozlemlenebilir iletisim oruntulerini cikarir.
Asla teshis koymaz, asla mental durum cikarmaz.
Yalnizca gozlemlenebilir sinyalleri tanimlar ve her sinyal icin guven skoru uretir.

Cikti: CommunicationSignals, TopicAffinity, PostingPattern, InteractionPattern.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from services.llm_gateway import LLMGateway, get_llm_gateway

logger = logging.getLogger("agent_core.analyzer")

# ---------------------------------------------------------------------------
# Behavioral Signal Schemas
# ---------------------------------------------------------------------------



class Evidence(BaseModel):
    """Specific observable evidence supporting a classification."""
    excerpt: str = Field(..., description="The specific quote or observed detail (e.g. 'bio line: ...')")
    source: str = Field(default="unknown", description="Where this was found (e.g., 'post', 'bio', 'reply')")
    timestamp: Optional[str] = Field(default=None, description="ISO 8601 timestamp if applicable")

class CommunicationSignals(BaseModel):
    """Gozlemlenebilir iletisim tarzi sinyalleri."""

    tone_style: str = Field(
        ...,
        description="One of: assertive, collaborative, questioning, declarative, narrative, instructional, provocative, reflective, dry_humor, earnest, sarcastic",
    )
    language_complexity: str = Field(
        ..., description="One of: simple, moderate, complex, mixed"
    )
    emotional_expressiveness: str = Field(
        ..., description="One of: reserved, balanced, expressive, highly_expressive"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="How certain the LLM is about this classification (0-1)")
    stability: float = Field(..., ge=0.0, le=1.0, description="How consistent this signal is across the sample (0-1). Low stability = based on few posts, may change.")
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Specific observable examples supporting this classification (e.g. '7/12 posts use ironic contrast', 'bio contains self-deprecating humor')",
    )


class TopicAffinity(BaseModel):
    """Gozlemlenebilir konu egilimleri."""

    primary_themes: List[str] = Field(
        ..., description="Top 3-5 observable themes (e.g. technology, fitness, politics, art)"
    )
    theme_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in theme classification")
    emotional_valence: str = Field(
        ..., description="Overall emotional valence: positive, negative, neutral, mixed"
    )
    stability: float = Field(..., ge=0.0, le=1.0, description="How consistent themes are across the sample")
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Specific posts or bio snippets that support theme classification",
    )


class PostingPattern(BaseModel):
    """Gozlemlenebilir paylasim oruntuleri."""

    frequency_indicator: str = Field(
        ..., description="One of: frequent, moderate, sparse, episodic"
    )
    content_type_mix: List[str] = Field(
        ..., description="Content types: personal, professional, curated, reactive, promotional, educational, entertainment"
    )
    engagement_seeking_level: str = Field(
        ..., description="One of: low, moderate, high"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this signal set (0-1)")
    stability: float = Field(..., ge=0.0, le=1.0, description="How consistent posting behavior is across the sample")
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Observed posting behaviors supporting this classification",
    )


class InteractionPattern(BaseModel):
    """Gozlemlenebilir etkilesim oruntuleri."""

    response_style: str = Field(
        ..., description="One of: reciprocating, initiating, observational, selective"
    )
    community_orientation: str = Field(
        ..., description="One of: individual_focused, community_focused, mixed"
    )
    conflict_engagement: str = Field(
        ..., description="One of: avoidant, diplomatic, direct, confrontational"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this signal set (0-1)")
    stability: float = Field(..., ge=0.0, le=1.0, description="How consistent interaction patterns are across the sample")
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Specific interaction examples observed in the data",
    )


class BehavioralProfile(BaseModel):
    """Tam davranissal sinyal profili."""

    schema_version: str = Field(default="1.1", description="Schema version for forward compatibility")
    communication_signals: CommunicationSignals
    topic_affinity: TopicAffinity
    posting_pattern: PostingPattern
    interaction_pattern: InteractionPattern
    overall_confidence: float = Field(..., ge=0.0, le=1.0, description="Aggregate confidence across all signals")
    sample_size: int = Field(..., ge=0, description="Number of data points analyzed (posts, bio lines, etc.)")
    period_days: Optional[float] = Field(default=None, description="Time span of observed data in days, if known")
    extraction_timestamp: str = Field(..., description="ISO 8601 extraction time")


# ---------------------------------------------------------------------------
# System Prompt (strict guardrails)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a behavioral signal extractor.

Your job is to describe observable communication patterns from social media data.
You work ONLY with what is directly observable in the provided text.

CRITICAL RULES:
- NEVER diagnose. You are not a clinician.
- NEVER infer mental illness, disorders, or psychological conditions.
- NEVER infer trauma, abuse history, or personal suffering.
- NEVER use psychological labels (narcissistic, depressed, anxious, bipolar, etc.).
- ONLY describe observable communication patterns and content themes.

For EVERY signal, return TWO scores:
  - "confidence" (0-1): How certain you are about this classification.
  - "stability" (0-1): How CONSISTENT this signal is across the sample.
    High stability = the pattern appears in most posts consistently.
    Low stability = the pattern appears in only 1-2 posts and may not hold.

For EVERY signal, include "evidence" as a list of objects containing:
  - "excerpt": The specific quote or observed detail.
  - "source": Where you found it (e.g. "post", "bio", "reply").
Evidence is NOT optional — every signal decision must be traceable to the source.

For "sample_size": count all analyzed data points (posts + bio + interactions).
For "period_days": estimate the time span if post dates suggest it, otherwise null.

You are an engineer extracting structured signals from unstructured text. Nothing more."""


# ---------------------------------------------------------------------------
# Profile Analyzer
# ---------------------------------------------------------------------------


class ProfileAnalyzer:
    """Sosyal medya verisinden gozlemlenebilir davranissal sinyalleri cikarir.

    LLM cagrilari LLMGateway uzerinden yapilir — hangi model oldugu analyzer'i
    ilgilendirmez.
    """

    def __init__(self, gateway: Optional[LLMGateway] = None):
        self.gateway = gateway or get_llm_gateway()

    async def analyze(self, scraped_data: Dict[str, Any]) -> Dict[str, Any]:
        """Scraper'dan gelen veriyi analiz eder ve BehavioralProfile dondurur."""
        if not scraped_data:
            return {}

        bio = scraped_data.get("bio", "")
        posts_list = scraped_data.get("recent_posts", [])[:10]
        posts = "\n".join(posts_list)
        followers = scraped_data.get("followers", "N/A")

        content = f"Profile Bio: {bio}\nFollowers: {followers}\nRecent Posts:\n{posts}"
        logger.info(
            "Davranissal sinyal cikarimi basliyor (bio=%d chars, posts=%d)",
            len(bio), len(posts_list),
        )

        messages = [
            {
                "role": "user",
                "content": (
                    f"Extract behavioral communication signals from this social media profile.\n\n"
                    f"{content}\n\n"
                    f"Remember: only observable patterns, no diagnosis, no inference of mental state."
                ),
            },
        ]

        try:
            profile = await self.gateway.chat_and_parse(
                messages=messages,
                schema=BehavioralProfile,
                system=SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=1024,
            )
            result = profile.model_dump()
            logger.info(
                "Sinyal cikarimi tamamlandi (overall_confidence=%.2f, themes=%s)",
                profile.overall_confidence,
                profile.topic_affinity.primary_themes,
            )
            return result

        except Exception as exc:
            logger.error("Sinyal cikarimi basarisiz: %s", exc)
            return {
                "communication_signals": None,
                "topic_affinity": None,
                "posting_pattern": None,
                "interaction_pattern": None,
                "overall_confidence": 0.0,
                "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
