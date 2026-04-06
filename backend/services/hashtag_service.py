"""
ClipForge -- Local Hashtag Generation Service (SELF-HOSTED)
Uses HERMES bridge (OpenRouter :free models) instead of OpenAI GPT-4o-mini.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from backend.hermes_bridge import get_bridge

log = logging.getLogger("clipforge.hashtag_service")

PLATFORM_HASHTAG_RULES = {
    "tiktok": {"max_hashtags": 5, "placement": "caption", "strategy": "Mix 2 viral + 2 niche + 1 trending"},
    "instagram_reels": {"max_hashtags": 20, "placement": "first_comment", "strategy": "Mix 7 broad + 8 niche + 5 micro"},
    "youtube_shorts": {"max_hashtags": 3, "placement": "caption", "strategy": "Highly specific, topic-relevant only"},
    "linkedin_video": {"max_hashtags": 5, "placement": "end_of_post", "strategy": "Professional, industry-specific hashtags"},
    "facebook_reels": {"max_hashtags": 5, "placement": "caption", "strategy": "Broad viral + trending + niche"},
    "twitter_x": {"max_hashtags": 3, "placement": "inline", "strategy": "Trending topics + 1 brand hashtag"},
}


async def generate_hashtags(
    hook_text: str,
    transcript_segment: str,
    platform: str,
    niche: Optional[str] = None,
    clip_id: Optional[str] = None,
) -> dict:
    """
    Call HERMES bridge (free OpenRouter models) for hashtag generation.
    Platform-aware with rules per platform.
    """
    niche_str = niche or "general"
    rules = PLATFORM_HASHTAG_RULES.get(platform, PLATFORM_HASHTAG_RULES["tiktok"])

    system_prompt = (
        f"You are a social media growth expert specializing in hashtag strategy "
        f"for {platform}. Generate optimal hashtags for maximum reach."
    )

    user_prompt = (
        f"Generate hashtags for this {platform} clip.\n\n"
        f"Hook: {hook_text[:200]}\n"
        f"Transcript: {transcript_segment[:500]}\n"
        f"Niche: {niche_str}\n\n"
        f"Rules: max {rules['max_hashtags']} hashtags, {rules['strategy']}\n\n"
        "Return ONLY valid JSON with: primary_hashtags (array), niche_hashtags (array), "
        "trending_hashtags (array), caption_with_hashtags (string), hashtag_count (int), "
        "estimated_reach (low/medium/high)"
    )

    bridge = get_bridge()
    try:
        result = await bridge.chat_json(system_prompt, user_prompt, temperature=0.7)
        if "error" not in result and "primary_hashtags" in result:
            result["hashtag_count"] = (
                len(result.get("primary_hashtags", []))
                + len(result.get("niche_hashtags", []))
                + len(result.get("trending_hashtags", []))
            )
            log.info("Generated %d hashtags for %s", result["hashtag_count"], platform)
            return result
    except Exception:
        log.exception("HERMES hashtag generation failed")

    return _fallback_hashtags(hook_text, platform)


def get_platform_hashtag_rules(platform: str) -> dict:
    return PLATFORM_HASHTAG_RULES.get(platform, PLATFORM_HASHTAG_RULES["tiktok"])


def append_hashtags_to_caption(caption_text: str, hashtags: list, platform: str) -> dict:
    rules = get_platform_hashtag_rules(platform)
    hashtag_str = " ".join(f"#{h.strip('#')}" for h in hashtags[:rules["max_hashtags"]])
    if rules["placement"] == "first_comment":
        return {"caption": caption_text, "first_comment": hashtag_str, "hashtag_count": len(hashtags)}
    return {"caption": f"{caption_text}\n\n{hashtag_str}", "first_comment": None, "hashtag_count": len(hashtags)}


def _fallback_hashtags(hook_text: str, platform: str) -> dict:
    words = [w.strip(".,!?;:\"'()") for w in hook_text.lower().split() if len(w) > 3]
    platform_defaults = {
        "tiktok": ["fyp", "foryou", "viral", "trending", "shorts"],
        "instagram_reels": ["reels", "viral", "trending", "instareels", "explore"],
        "youtube_shorts": ["shorts", "youtubeshorts", "viral"],
        "linkedin_video": ["professional", "growth", "insights", "career", "business"],
        "facebook_reels": ["viral", "trending", "fyp", "reels", "facebook"],
        "twitter_x": ["trending", "viral", "thread"],
    }
    return {
        "primary_hashtags": words[:5] or ["viral", "trending"],
        "niche_hashtags": ["contentcreator", "growth"],
        "trending_hashtags": platform_defaults.get(platform, ["fyp"])[:3],
        "caption_with_hashtags": hook_text,
        "hashtag_count": len(words[:5]) + 5,
        "estimated_reach": "medium",
    }
