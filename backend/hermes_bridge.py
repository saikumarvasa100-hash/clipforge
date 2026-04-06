"""
ClipForge -- HERMES Bridge
Calls local HERMES agent (OpenRouter :free models) at localhost:7890 for LLM tasks.
Replaces OpenAI GPT calls with local/self-hosted alternatives.
"""
from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger("clipforge.hermes_bridge")

HERMES_BASE_URL = "http://localhost:7890/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
DEFAULT_TIMEOUT = 30.0  # seconds


class HermesBridge:
    """Thin bridge to a local HERMES agent exposing OpenAI-compatible chat/completions."""

    def __init__(self, base_url: str = HERMES_BASE_URL, model: str = DEFAULT_MODEL, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> dict:
        """
        Send a chat completion request and parse the response as JSON.
        Returns the parsed JSON dict, or {"error": "..."} if parsing fails.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout)) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

        content = body["choices"][0]["message"]["content"].strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = content.index("\n")
            content = content[first_newline + 1:]
            # Remove closing fence
            if content.endswith("```"):
                content = content[:-3].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            log.error("Failed to parse HERMES response as JSON: %s", content[:300])
            return {"error": "invalid_json", "raw": content}


# Singleton
_bridge: HermesBridge | None = None


def get_bridge(base_url: str = HERMES_BASE_URL, model: str = DEFAULT_MODEL) -> HermesBridge:
    global _bridge
    if _bridge is None:
        _bridge = HermesBridge(base_url=base_url, model=model)
    return _bridge


def reset_bridge() -> None:
    """Reset singleton (useful for testing)."""
    global _bridge
    _bridge = None
