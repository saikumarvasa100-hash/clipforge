#!/bin/bash
# ClipForge -- Launch Checklist
# Run this before going public. Each item prints PASS or FAIL.

set -o pipefail
PASS=0
FAIL=0

check() {
  local name="$1"
  shift
  if "$@" > /dev/null 2>&1; then
    echo "  PASS  $name"
    ((PASS++))
  else
    echo "  FAIL  $name"
    ((FAIL++))
  fi
}

echo "============================================="
echo "  ClipForge Launch Checklist"
echo "============================================="
echo ""

# Database / Cache
echo "--- Database & Cache ---"
check "Supabase connection"    psql "$DATABASE_URL" -c "SELECT 1"
check "Redis connection"       redis-cli -u "$REDIS_URL" ping

# API Keys
echo "--- API Keys ---"
check "OpenAI API key valid"   bash -c 'curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" | grep -q gpt'
check "YouTube API key valid"  bash -c 'curl -s "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&key=$YOUTUBE_API_KEY" | grep -q kind'
check "TikTok app credentials set" bash -c '[[ -n "${TIKTOK_CLIENT_KEY:-}" && -n "${TIKTOK_CLIENT_SECRET:-}" ]]'
check "Stripe webhook secret set"  bash -c '[[ -n "${STRIPE_WEBHOOK_SECRET:-}" ]]'

# Network
echo "--- Network ---"
check "PubSub callback reachable" bash -c 'curl -s "$PUBSUBHUBBUB_CALLBACK_URL/api/webhooks/youtube?hub.challenge=test&hub.mode=subscribe" | grep -q test'

# System tools
echo "--- System Tools ---"
check "FFmpeg installed and working" ffmpeg -version
check "yt-dlp installed and working" yt-dlp --version

# Celery
echo "--- Celery ---"
check "Celery worker running"  celery -A celery_app inspect ping
check "Celery beat running"    pgrep -f "celery.*beat"

# Frontend
echo "--- Frontend ---"
check "Frontend builds without errors" bash -c 'cd frontend && npm run build'
check "Stripe test checkout works"     bash -c 'curl -s -X POST http://localhost:8000/api/webhooks/stripe -H "Content-Type: application/json" -d "{\"action\":\"checkout\"}" | grep -q received'

echo ""
echo "============================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================="

if [ $FAIL -gt 0 ]; then
  echo "  Fix the FAIL items before going live!"
  exit 1
else
  echo "  All checks passed. Ready to launch!"
  exit 0
fi
