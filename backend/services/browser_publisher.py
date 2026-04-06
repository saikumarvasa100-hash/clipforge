"""
ClipForge — Browser-based Publisher (Playwright automation)
Replaces TikTok / Instagram / LinkedIn / Facebook API publishers
with headless browser automation using cookie-based authentication.

Usage:
  Export session cookies from your browser:
    1. Log in to the platform in Chrome/Edge
    2. Use extension like "EditThisCookie" to export as JSON
    3. Save to e.g. ~/cookies/tiktok.json
  Pass the cookies file path to the publish functions.

Cookie format (list of dicts):
  [{"name": "sid_tt", "value": "...", "domain": ".tiktok.com", "path": "/"}]

Requirements:
  pip install playwright
  playwright install chromium
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("clipforge.browser_publisher")

# ── helpers ─────────────────────────────────────────────────────────────


def _load_cookies(cookies_file: str) -> List[Dict]:
    """Load cookie dicts from a JSON file."""
    import json

    path = Path(cookies_file)
    if not path.exists():
        raise FileNotFoundError(f"Cookies file not found: {cookies_file}")
    with open(path) as f:
        data = json.load(f)
    # support both raw list and {"cookies": [...]} wrappers
    if isinstance(data, dict):
        data = data.get("cookies", data.get("data", []))
    return data


async def _launch_browser() -> tuple:
    """Launch a Chromium browser. Returns (browser, playwright_instance)."""
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=os.getenv("BROWSER_HEADLESS", "true").lower() == "true",
        args=["--disable-blink-features=AutomationControlled"],
    )
    return browser, pw


async def _new_context_with_cookies(browser, cookies_file: str):
    """Create a browser context and inject cookies."""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    cookies = _load_cookies(cookies_file)
    if cookies:
        # Normalise cookies for Playwright
        normalised = []
        for c in cookies:
            entry = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            if "expires" in c:
                entry["expires"] = c["expires"]
            if "httpOnly" in c:
                entry["httpOnly"] = c["httpOnly"]
            if "secure" in c:
                entry["secure"] = c["secure"]
            normalised.append(entry)
        await context.add_cookies(normalised)
        log.info("Loaded %d cookies into browser context", len(normalised))
    return context


# ── TikTok ──────────────────────────────────────────────────────────────


async def publish_tiktok_browser(
    video_path: str,
    description: str,
    cookies_file: str,
    timeout_sec: float = 300,
) -> str:
    """
    Upload a video to TikTok via Playwright browser automation.

    Steps:
      1. Navigate to https://www.tiktok.com/upload
      2. Wait for upload area, set file input to video_path
      3. Fill description / caption
      4. Click Publish and wait for success indicator

    Returns a status string (the browser does not expose a post_id easily).
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    browser, pw = None, None
    try:
        browser, pw = await _launch_browser()
        ctx = await _new_context_with_cookies(browser, cookies_file)
        page = await ctx.new_page()

        log.info("TikTok: navigating to upload page")
        await page.goto("https://www.tiktok.com/upload", wait_until="domcontentloaded", timeout=30000)

        # Wait for the page to render (short delay for JS)
        await page.wait_for_timeout(3000)

        # Check if already redirected to login — cookies may be stale
        current_url = page.url
        if "login" in current_url.lower():
            raise RuntimeError("TikTok: not authenticated — cookies may be expired")

        # ── File upload: TikTok uses a hidden file input ──
        await page.set_input_files(
            'input[type="file"]',
            video_path,
            timeout=30000,
        )
        log.info("TikTok: video file attached")

        # Wait for upload progress
        await page.wait_for_timeout(5000)

        # ── Fill description / caption ──
        # TikTok uses a contenteditable or textarea for the description
        desc_field = await page.query_selector(
            '[data-e2e="video-upload-caption"]'
        )
        if desc_field is None:
            desc_field = await page.query_selector(
                'div[contenteditable="true"], textarea[placeholder*="escription"], textarea[placeholder*="aption"]'
            )
        if desc_field is None:
            # Broad fallback
            desc_field = await page.query_selector(
                'div.public-DraftEditor-content, [role="textbox"]'
            )

        if desc_field:
            await desc_field.click()
            await page.wait_for_timeout(500)
            # Use page.keyboard.type for contenteditable
            description = description[:2800]  # TikTok max caption length
            await page.keyboard.type(description, delay=20)
            log.info("TikTok: description filled")
        else:
            log.warning("TikTok: could not locate description field")

        # Let description processing settle
        await page.wait_for_timeout(2000)

        # ── Publish ──
        post_button = await page.query_selector(
            'button[data-e2e="video-publish-button"]'
        )
        if post_button is None:
            post_button = await page.query_selector(
                'button:has-text("Post"), button:has-text("Publish")'
            )

        if post_button:
            await post_button.click()
            log.info("TikTok: clicked Publish button")
        else:
            raise RuntimeError("TikTok: could not locate Publish button")

        # Wait for publish confirmation
        published = False
        for _ in range(int(timeout_sec / 3)):
            await page.wait_for_timeout(3000)

            # Check for success indicators
            success_text = await page.query_selector(
                'div:has-text("Published successfully"), div:has-text("Posted successfully"), '
                '[data-e2e="upload-success-info"]'
            )
            if success_text:
                published = True
                break

            # Check if we're back at upload page (published and redirected)
            current = page.url
            if "upload" not in current.lower() and "posted" in current.lower():
                published = True
                break

        if not published:
            # Partial success — file uploaded, may still be processing
            log.warning("TikTok: publish button clicked but no explicit confirmation received")
            return "pending"

        log.info("TikTok: upload complete")
        return "published"

    except Exception as exc:
        log.error("TikTok browser publish failed: %s", exc, exc_info=True)
        raise
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


# ── Instagram ───────────────────────────────────────────────────────────


async def publish_instagram_browser(
    video_path: str,
    caption: str,
    cookies_file: str,
    timeout_sec: float = 300,
) -> str:
    """
    Upload a video to Instagram as a Reel via Playwright.

    Steps:
      1. Navigate to https://www.instagram.com/
      2. Click Create (+) button
      3. Attach video file
      4. Fill caption
      5. Share
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    browser, pw = None, None
    try:
        browser, pw = await _launch_browser()
        ctx = await _new_context_with_cookies(browser, cookies_file)
        page = await ctx.new_page()

        log.info("Instagram: navigating to feed")
        await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        # Check auth
        current_url = page.url
        if "login" in current_url.lower():
            raise RuntimeError("Instagram: not authenticated — cookies may be expired")

        # ── Click Create (+) to open composer ──
        # Try multiple selectors for the create button
        create_button = await page.query_selector(
            'svg[aria-label="New post"]'
        )
        if create_button is None:
            create_button = await page.query_selector(
                'a[href="/create/"]'
            )
        if create_button is None:
            create_button = await page.query_selector(
                'span:has-text("+ New Post"), svg:has-text("plus")'
            )
        if create_button is None:
            # Click via keyboard shortcut
            await page.keyboard.press("N")
            await page.wait_for_timeout(2000)
        else:
            await create_button.click()
            log.info("Instagram: clicked create button")
        await page.wait_for_timeout(3000)

        # ── File upload ──
        file_input = await page.query_selector('input[type="file"][accept*="video"]')
        if file_input is None:
            file_input = await page.query_selector('input[type="file"]')
        if file_input and file_input.is_visible():
            await file_input.set_files(video_path)
        else:
            # Some IG flows require clicking into a dialog zone first
            drop_zone = await page.query_selector(
                'div:has-text("Drag photos and videos here"), '
                'div._ab1d:has-text("Drag")'
            )
            if drop_zone:
                await drop_zone.set_input_files(video_path)
            else:
                raise RuntimeError("Instagram: could not find upload input zone")
        log.info("Instagram: video file attached")
        await page.wait_for_timeout(5000)

        # ── Advance through dialogs (crop → filters → caption) ──
        for _ in range(3):
            # Wait a moment for current step to settle
            await page.wait_for_timeout(2000)

            # Look for "Next" or "Share" buttons
            share_btn = await page.query_selector('button:has-text("Share")')
            next_btn = await page.query_selector('button:has-text("Next")')

            if share_btn:
                break
            elif next_btn:
                await next_btn.click()
                log.info("Instagram: clicked Next")

        # ── Fill caption ──
        caption_field = await page.query_selector(
            'textarea[placeholder*="Write a caption"], '
            'textarea[placeholder*="aption"], '
            'textarea'
        )
        if caption_field:
            await caption_field.click()
            await page.wait_for_timeout(500)
            caption = caption[:2200]  # Instagram max caption length
            await page.keyboard.type(caption, delay=20)
            log.info("Instagram: caption filled")

        await page.wait_for_timeout(1000)

        # ── Final Share ──
        final_share = await page.query_selector('button:has-text("Share")')
        if final_share:
            await final_share.click()
            log.info("Instagram: clicked Share")
        else:
            done_btn = await page.query_selector('button:has-text("Done")')
            if done_btn:
                await done_btn.click()
                log.info("Instagram: clicked Done")
            else:
                raise RuntimeError("Instagram: could not find Share or Done button")

        # Wait for confirmation
        for _ in range(int(timeout_sec / 3)):
            await page.wait_for_timeout(3000)
            done_text = await page.query_selector(
                'div:has-text("Your reel has been shared"), '
                'div:has-text("Posted"), '
                'div:has-text("Shared to"'
            )
            if done_text:
                break

        log.info("Instagram: upload complete")
        return "published"

    except Exception as exc:
        log.error("Instagram browser publish failed: %s", exc, exc_info=True)
        raise
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


# ── LinkedIn ────────────────────────────────────────────────────────────


async def publish_linkedin_browser(
    video_path: str,
    description: str,
    cookies_file: str,
    timeout_sec: float = 300,
) -> str:
    """
    Upload a video to LinkedIn via Playwright.

    Steps:
      1. Navigate to https://www.linkedin.com/feed
      2. Click the Media / Video button in the composer
      3. Attach video file
      4. Fill description
      5. Click Post
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    browser, pw = None, None
    try:
        browser, pw = await _launch_browser()
        ctx = await _new_context_with_cookies(browser, cookies_file)
        page = await ctx.new_page()

        log.info("LinkedIn: navigating to feed")
        await page.goto("https://www.linkedin.com/feed", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        # Check auth
        current_url = page.url
        if "login" in current_url.lower() or "signin" in current_url.lower():
            raise RuntimeError("LinkedIn: not authenticated — cookies may be expired")

        # Dismiss any initial popup / modal
        try:
            dismiss = await page.query_selector('button:has-text("Got it"), button:has-text("Dismiss")')
            if dismiss:
                await dismiss.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # ── Click Media (photo + video) icon in composer ──
        # LinkedIn uses different selectors; try multiple
        media_button = await page.query_selector(
            'button[aria-label="Add media"][data-control-name*="update"], '
            'button:has-text("Media"), '
            'button[data-control-name="update-media"]'
        )
        if media_button is None:
            media_button = await page.query_selector(
                '[data-control-name="update-media"], [data-control-name="share-box-media"]'
            )
        if media_button is None:
            # Click start-post area first to expand composer
            start_post = await page.query_selector(
                'div.feed-shared-box__content, button:has-text("Start a post")'
            )
            if start_post:
                await start_post.click()
                await page.wait_for_timeout(3000)
                media_button = await page.query_selector(
                    'button[aria-label*="Media"], button[data-control-name*="media"]'
                )

        if media_button:
            await media_button.click()
            log.info("LinkedIn: clicked media button")
        else:
            log.warning("LinkedIn: could not find media button, attempting file input fallback")

        await page.wait_for_timeout(3000)

        # ── File upload ──
        file_input = await page.query_selector('input[type="file"][accept*="video"]')
        if file_input is None:
            file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_files(video_path)
            log.info("LinkedIn: video file attached")
        else:
            raise RuntimeError("LinkedIn: could not find file input")

        await page.wait_for_timeout(8000)

        # ── Fill description ──
        editor = await page.query_selector(
            'div.ql-editor[contenteditable="true"], '
            'div[data-placeholder*="escription"], '
            'div[data-placeholder*="What do you want to talk about?"]'
        )
        if editor is None:
            # Generic contenteditable
            editor = await page.query_selector('[contenteditable="true"]')

        if editor:
            await editor.click()
            await page.wait_for_timeout(500)
            description = description[:3000]  # LinkedIn max caption
            await page.keyboard.type(description, delay=20)
            log.info("LinkedIn: description filled")
        else:
            log.warning("LinkedIn: could not locate description field")

        await page.wait_for_timeout(2000)

        # ── Click Post ──
        post_button = await page.query_selector(
            'button:has-text("Post"), button[data-control-name*="post-submit"]'
        )
        if post_button:
            await post_button.click()
            log.info("LinkedIn: clicked Post")
        else:
            raise RuntimeError("LinkedIn: could not find Post button")

        # Wait for confirmation
        for _ in range(int(timeout_sec / 3)):
            await page.wait_for_timeout(3000)
            current = page.url
            if "feed" in current.lower() or "home" in current.lower():
                break
            success = await page.query_selector(
                'div:has-text("Post is now live"), div:has-text("Your post is live")'
            )
            if success:
                break

        log.info("LinkedIn: upload complete")
        return "published"

    except Exception as exc:
        log.error("LinkedIn browser publish failed: %s", exc, exc_info=True)
        raise
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()


# ── Facebook ────────────────────────────────────────────────────────────


async def publish_facebook_browser(
    video_path: str,
    description: str,
    cookies_file: str,
    timeout_sec: float = 300,
) -> str:
    """
    Upload a video to Facebook via Playwright.

    Steps:
      1. Navigate to https://www.facebook.com
      2. Click Photo/Video in composer
      3. Attach video file
      4. Fill description
      5. Click Post

    For Page uploads, use:  https://www.facebook.com/{page_username}/posts/
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    browser, pw = None, None
    try:
        browser, pw = await _launch_browser()
        ctx = await _new_context_with_cookies(browser, cookies_file)
        page = await ctx.new_page()

        log.info("Facebook: navigating to feed")
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Check auth
        current_url = page.url
        if "login" in current_url.lower() or "privacy" in current_url.lower():
            raise RuntimeError("Facebook: not authenticated — cookies may be expired")

        # ── Click Photo/Video button ──
        photo_video_button = await page.query_selector(
            'button[aria-label*="Photo/video"], '
            'div:has-text("Photo/video")'
        )
        if photo_video_button is None:
            photo_video_button = await page.query_selector(
                'button:has-text("Photo/video"), button:has-text("Photo/Video")'
            )
        if photo_video_button is None:
            # Click "What's on your mind?" to open composer first
            whats_up = await page.query_selector(
                'button:has-text("What"), div:has-text("What\'s on your mind")'
            )
            if whats_up:
                await whats_up.click()
                await page.wait_for_timeout(3000)
            photo_video_button = await page.query_selector(
                'button[aria-label*="Photo/video"]'
            )

        if photo_video_button:
            await photo_video_button.click()
            log.info("Facebook: opened photo/video dialog")
        else:
            log.warning("Facebook: could not locate photo/video button")

        await page.wait_for_timeout(4000)

        # ── File upload ──
        file_input = await page.query_selector('input[type="file"][accept*="video"]')
        if file_input is None:
            file_input = await page.query_selector(
                'input[type="file"][accept*="image"], input[type="file"]'
            )
        if file_input:
            await file_input.set_files(video_path)
            log.info("Facebook: video file attached")
        else:
            raise RuntimeError("Facebook: could not find file input")

        # Wait for video upload processing
        await page.wait_for_timeout(10000)

        # ── Fill description ──
        desc_box = await page.query_selector(
            'div[contenteditable="true"][data-contents="true"], '
            'div[contenteditable="true"][placeholder*="escription"], '
            'div[role="textbox"]'
        )
        if desc_box is None:
            desc_box = await page.query_selector('div[contenteditable="true"]')

        if desc_box:
            await desc_box.click()
            await page.wait_for_timeout(500)
            description = description[:5000]  # Facebook allows long captions
            await page.keyboard.type(description, delay=20)
            log.info("Facebook: description filled")

        await page.wait_for_timeout(2000)

        # ── Click Post ──
        post_button = await page.query_selector(
            'button:has-text("Post"), button[data-automationid="post_button"], '
            'div:has-text("Post"):not([hidden])'
        )
        if post_button:
            await post_button.click()
            log.info("Facebook: clicked Post")
        else:
            raise RuntimeError("Facebook: could not find Post button")

        # Wait for confirmation
        for _ in range(int(timeout_sec / 3)):
            await page.wait_for_timeout(3000)
            success = await page.query_selector(
                'div:has-text("Your post has been shared"), '
                'div:has-text("Post shared")'
            )
            if success:
                break

            current = page.url
            if "/posts/" in current or "/reel/" in current:
                # Redirected to the post — success
                break

        log.info("Facebook: upload complete")
        return "published"

    except Exception as exc:
        log.error("Facebook browser publish failed: %s", exc, exc_info=True)
        raise
    finally:
        if browser:
            await browser.close()
        if pw:
            await pw.stop()
