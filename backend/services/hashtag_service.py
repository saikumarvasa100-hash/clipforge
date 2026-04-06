"""
ClipForge — Auto Hashtag Generation Service
Uses GPT-4o-mini to generate platform-specific trending hashtags per clip.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

log = logging.getLogger("clipforge.hashtag_service")


async def generate_hashtags(
    hook_text: str,
    transcript_segment: str,
    platform: str,
    niche: Optional[str] = None,
    clip_id: Optional[str] = None,
) -> dict:
    """
    Call GPT-4o-mini to generate optimal hashtag set for a clip.
    Platform-aware: different rules per platform.
    Cache results in Redis (TTL 24h) if clip_id provided.
    """
    # Check Redis cache first
    if clip_id:
        try:
            from redis import Redis
            r = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            cached = r.get(f"hashtags:{clip_id}:{platform}")
            if cached:
                log.info("Hashtag cache hit for %s:%s", clip_id, platform)
                return json.loads(cached)
        except Exception:
            pass

    niche_str = niche or "general"

    system_prompt = (
        f"You are a social media growth expert specializing in hashtag strategy "
        f"for {platform}. You know which hashtags are currently performing well "
        f"and how to mix broad, niche, and micro hashtags for maximum reach."
    )

    user_prompt = (
        f"Generate the optimal hashtag set for this {platform} clip.\n\n"
        f"Clip topic/hook: {hook_text}\n"
        f"Clip transcript: {transcript_segment[:500]}\n"
        f"Creator niche (if known): {niche_str}\n\n"
        "Return JSON with:\n"
        "{\n"
        '  "primary_hashtags": ["5 high-volume hashtags directly about the topic"],\n'
        '  "niche_hashtags": ["5 medium-volume niche-specific hashtags"],\n'
        '  "trending_hashtags": ["3 currently trending hashtags that fit this content"],\n'
        '  "caption_with_hashtags": "Full optimized caption text with hashtags woven in naturally",\n'
        '  "hashtag_count": total_count,\n'
        '  "estimated_reach": "low/medium/high"\n'
        "}\n\n"
        "Platform rules:\n"
        "- TikTok: 3-5 hashtags max, mix viral + niche\n"
        "- Instagram: 15-20 hashtags, mix all types\n"
        "- YouTube Shorts: 3 hashtags only, highly specific\n"
        "- LinkedIn: 3-5 professional hashtags\n"
        "- Facebook: 3-5 hashtags, focus on viral topics\n"
        "- Twitter/X: 2-3 hashtags, trending topics\n\n"
        "Return ONLY valid JSON. No markdown. No explanation."
    )

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=500,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code block if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines)

        result = json.loads(raw)

        # Ensure all expected keys are present
        for key in ("primary_hashtags", "niche_hashtags", "trending_hashtags",
                     "caption_with_hashtags", "hashtag_count", "estimated_reach"):
            if key not in result:
                result[key] = [] if key.endswith("hashtags") else ("Unknown" if key == "estimated_reach" else "")

        result["hashtag_count"] = (
            len(result.get("primary_hashtags", []))
            + len(result.get("niche_hashtags", []))
            + len(result.get("trending_hashtags", []))
        )

        # Cache in Redis
        if clip_id:
            try:
                from redis import Redis
                r = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
                r.setex(f"hashtags:{clip_id}:{platform}", 86400, json.dumps(result))
            except Exception:
                pass

        log.info(
            "Generated %d hashtags for %s clip: %s",
            result["hashtag_count"], platform, result.get("estimated_reach", ""),
        )
        return result

    except json.JSONDecodeError:
        log.warning("Failed to parse hashtag JSON: %s", raw[:200])
        return _fallback_hashtags(hook_text, platform)
    except Exception:
        log.exception("Hashtag generation failed")
        return _fallback_hashtags(hook_text, platform)


PLATFORM_HASHTAG_RULES = {
    "tiktok": {
        "max_hashtags": 5,
        "placement": "caption",
        "strategy": "Mix 2 viral + 2 niche + 1 trending",
    },
    "instagram_reels": {
        "max_hashtags": 20,
        "placement": "first_comment",
        "strategy": "Mix 7 broad + 8 niche + 5 micro/trending",
    },
    "youtube_shorts": {
        "max_hashtags": 3,
        "placement": "caption",
        "strategy": "Highly specific, topic-relevant only",
    },
    "linkedin_video": {
        "max_hashtags": 5,
        "placement": "end_of_post",
        "strategy": "Professional, industry-specific hashtags",
    },
    "facebook_reels": {
        "max_hashtags": 5,
        "placement": "caption",
        "strategy": "Broad viral + trending + niche",
    },
    "twitter_x": {
        "max_hashtags": 3,
        "placement": "inline",
        "strategy": "Trending topics + 1 brand hashtag",
    },
}


def get_platform_hashtag_rules(platform: str) -> dict:
    """Return hashtag strategy rules for a platform."""
    return PLATFORM_HASHTAG_RULES.get(platform, PLATFORM_HASHTAG_RULES["tiktok"])


def append_hashtags_to_caption(
    caption_text: str,
    hashtags: list,
    platform: str,
) -> dict:
    """
    Format caption with hashtags according to platform rules.
    Returns dict with formatted caption and optional first comment.
    """
    rules = get_platform_hashtag_rules(platform)
    hashtag_str = " ".join(f"#{h.strip('#')}" for h in hashtags[:rules["max_hashtags"]])

    first_comment = None
    final_caption = caption_text

    if rules["placement"] == "first_comment":
        # Instagram: put hashtags in first comment
        final_caption = caption_text
        first_comment = hashtag_str
    elif rules["placement"] == "end_of_post":
        final_caption = f"{caption_text}\n\n{hashtag_str}"
    else:
        final_caption = f"{caption_text}\n\n{hashtag_str}"

    return {
        "caption": final_caption,
        "first_comment": first_comment,
        "hashtag_count": len(hashtags),
    }


def _fallback_hashtags(hook_text: str, platform: str) -> dict:
    """Generate basic fallback hashtags when LLM is unavailable."""
    words = hook_text.lower().split()[:5]
    base_hashtags = [
        w.strip(".,!?;:\"'()")
        for w in words
        if len(w) > 3
    ]

    primary = [h for h in base_hashtags[:5] if h]
    platform_defaults = {
        "tiktok": ["fyp", "foryou", "viral"],
        "instagram_reels": ["reels", "instagramreels", "trending"],
        "youtube_shorts": ["shorts", "youtubeshorts", "fyp"],
        "linkedin_video": ["professional", "growth", "insights"],
        "facebook_reels": ["viral", "trending", "fyp"],
    }

    return {
        "primary_hashtags": primary[:5] or ["viral", "trending"],
        "niche_hashtags": ["contentcreator", "growthhacks"],
        "trending_hashtags": platform_defaults.get(platform, ["fyp"]),
        "caption_with_hashtags": hook_text,
        "hashtag_count": len(primary) + 2 + 1,
        "estimated_reach": "medium",
    }
