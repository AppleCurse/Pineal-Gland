"""
LLM Gateway — butun LLM cagrilari icin tek giris noktasi.

LiteLLM (localhost:4000) birincil, OpenRouter yedek.
Circuit breaker: bir model art arda N kez hata verirse gecici olarak devre disi birakilir.
Analyzer dahil hicbir servis hangi modelin kullanildigini bilmez.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel

logger = logging.getLogger("agent_core.llm_gateway")

LITELLM_URL = os.getenv("LLM_GATEWAY_URL", "http://localhost:4000/v1")
LITELLM_API_KEY = os.getenv("LITELLM_MASTER_KEY", os.getenv("LLM_GATEWAY_API_KEY", ""))
DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "openrouter-chat")

T = TypeVar("T", bound=BaseModel)


class LLMGatewayError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Circuit Breaker — model bazinda, surec capinda (in-process)
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Bir model art arda N kez hata verirse gecici olarak devre disi birakir.

    Paylasilan durum (class-level): ayni model tum LLMGateway instance'lari
    tarafindan ayni devrede gorulur. Thread-safe degil (async coroutine'ler
    arasi guvenli — Python GIL + asyncio cooperative multitasking yeterli).
    """

    _consecutive_failures: Dict[str, int] = {}
    _cooldown_until: Dict[str, float] = {}

    def __init__(self, threshold: int = 5, cooldown_seconds: float = 600.0):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds

    def is_open(self, model: str) -> bool:
        """Bu model su anda devre disi mi?"""
        until = self._cooldown_until.get(model, 0.0)
        if until and time.monotonic() < until:
            return True
        # Cooldown suresi doldu — resetle ve tekrar dene
        if until and time.monotonic() >= until:
            self._cooldown_until.pop(model, None)
            self._consecutive_failures.pop(model, None)
        return False

    def record_failure(self, model: str) -> None:
        current = self._consecutive_failures.get(model, 0) + 1
        self._consecutive_failures[model] = current
        if current >= self.threshold:
            until = time.monotonic() + self.cooldown_seconds
            self._cooldown_until[model] = until
            logger.warning(
                "CIRCUIT BREAKER OPEN — model=%s (%d art arda hata, %.0fs devre disi)",
                model, current, self.cooldown_seconds,
            )

    def record_success(self, model: str) -> None:
        """Basarili cagri — hata sayacini sifirla."""
        self._consecutive_failures.pop(model, None)
        self._cooldown_until.pop(model, None)

    def status(self, model: str) -> Dict[str, Any]:
        return {
            "model": model,
            "open": self.is_open(model),
            "consecutive_failures": self._consecutive_failures.get(model, 0),
            "cooldown_remaining": max(0.0, self._cooldown_until.get(model, 0) - time.monotonic()),
        }


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class LLMGateway:
    """Tek duragin LLM cagri adaptoru.

    Kullanim:
        gateway = LLMGateway()
        result = await gateway.chat_and_parse(
            messages=[{"role": "user", "content": "..."}],
            system="You are...",
            schema=MyPydanticModel,
            temperature=0.3,
        )
    """

    def __init__(
        self,
        base_url: str = LITELLM_URL,
        api_key: str = LITELLM_API_KEY,
        model: str = DEFAULT_MODEL,
        fallback_model: str = FALLBACK_MODEL,
        max_retries: int = 3,
        timeout: float = 90.0,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.max_retries = max_retries
        self.timeout = timeout
        self.cb = circuit_breaker or CircuitBreaker()

    # -- raw chat ----------------------------------------------------------
    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        model: Optional[str] = None,
    ) -> str:
        """Ham metin yaniti dondurur. Retry + circuit breaker + fallback dahil."""
        full_messages: List[Dict[str, str]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        models_to_try = [model or self.model]
        if self.fallback_model and self.fallback_model not in models_to_try:
            models_to_try.append(self.fallback_model)

        last_error: Optional[str] = None

        for m in models_to_try:
            if self.cb.is_open(m):
                logger.warning(
                    "Circuit breaker acik — model=%s atlaniyor (sonraki modele gecilir)", m
                )
                continue

            for attempt in range(1, self.max_retries + 1):
                try:
                    result = await self._raw_request(
                        messages=full_messages,
                        model=m,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    self.cb.record_success(m)
                    return result
                except LLMGatewayError as exc:
                    last_error = str(exc)
                    self.cb.record_failure(m)
                    logger.warning(
                        "LLM istegi basarisiz (model=%s, attempt=%d/%d): %s",
                        m, attempt, self.max_retries, last_error,
                    )
                    if self.cb.is_open(m):
                        break  # circuit breaker acti, bu modeli birak
                    if attempt < self.max_retries:
                        await asyncio.sleep(2 ** attempt)

        raise LLMGatewayError(
            f"LLM cagrisi tum denemeler sonrasi basarisiz: {last_error}"
        )

    async def _raw_request(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                detail = resp.text[:500]
                raise LLMGatewayError(
                    f"HTTP {resp.status_code} (model={model}): {detail}"
                )
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logger.debug("LLM yanit alindi (model=%s, %d token)", model, len(content))
            return content

    # -- structured output + schema enforcement ----------------------------
    async def chat_and_parse(
        self,
        messages: List[Dict[str, str]],
        schema: Type[T],
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        model: Optional[str] = None,
        max_parse_retries: int = 2,
    ) -> T:
        """LLM cagrisi yapar, JSON ciktiyi Pydantic schema ile dogrular.

        Malformed JSON durumunda otomatik regex extraction + retry.
        Schema validation hatalarinda LLM'e duzeltme istegi gonderir.
        """
        # Schema'yi prompt'a gom
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        schema_instruction = (
            f"\n\nReturn ONLY valid JSON matching this schema. "
            f"No markdown, no explanation, just the JSON object:\n```json\n{schema_json}\n```"
        )

        effective_system = (system or "") + schema_instruction

        last_content: Optional[str] = None
        last_error: Optional[str] = None

        for parse_attempt in range(max_parse_retries + 1):
            if parse_attempt == 0:
                content = await self.chat(
                    messages=messages,
                    system=effective_system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model,
                )
            else:
                # Retry: hatayi LLM'e soyle, tekrar dene
                retry_msg = (
                    f"Your previous response was invalid JSON or failed schema "
                    f"validation. Error: {last_error}\n"
                    f"Please return ONLY a valid JSON object matching the schema."
                )
                retry_messages = list(messages)
                if last_content:
                    retry_messages.append({"role": "assistant", "content": last_content})
                retry_messages.append({"role": "user", "content": retry_msg})
                content = await self.chat(
                    messages=retry_messages,
                    system=effective_system,
                    temperature=temperature * 0.7,  # daha deterministik
                    max_tokens=max_tokens,
                    model=model,
                )

            last_content = content

            # JSON extraction: try direct parse, then regex
            parsed: Dict[str, Any]
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", content, re.DOTALL)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                    except json.JSONDecodeError as exc:
                        last_error = f"JSON parse error: {exc}"
                        logger.warning(
                            "LLM JSON parse hatasi (attempt %d/%d): %s",
                            parse_attempt + 1, max_parse_retries + 1, exc,
                        )
                        continue
                else:
                    last_error = "No JSON object found in response"
                    logger.warning(
                        "LLM yanitinda JSON bulunamadi (attempt %d/%d)",
                        parse_attempt + 1, max_parse_retries + 1,
                    )
                    continue

            # Schema validation
            try:
                return schema(**parsed)
            except Exception as exc:
                last_error = f"Schema validation error: {exc}"
                logger.warning(
                    "LLM yanit schema validasyon hatasi (attempt %d/%d): %s",
                    parse_attempt + 1, max_parse_retries + 1, exc,
                )

        raise LLMGatewayError(
            f"Schema parse basarisiz ({max_parse_retries + 1} deneme): {last_error}"
        )


# -- module-level singleton (lazy) ---------------------------------------
_gateway: Optional[LLMGateway] = None


def get_llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
