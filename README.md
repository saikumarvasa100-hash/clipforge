# ClipForge

**Turn long YouTube videos into viral short-form clips automatically.**

ClipForge monitors connected YouTube channels, downloads new videos, transcribes them with OpenAI Whisper, scores every segment for virality using a 3-signal AI engine, cuts the best clips with FFmpeg, burns in captions, and publishes them to TikTok, YouTube Shorts, and Instagram Reels.

---

## Architecture

```
                    ┌─────────────┐
                    │  YouTube    │
                    │  PubSubHubbub│
                    └──────┬──────┘
                           │ new video notification
                           ▼
 ┌──────────┐      ┌──────────────┐      ┌───────────────────┐
 │  Celery  │◄─────│ FastAPI API  │◄─────│  Next.js Frontend │
 │  Workers │      │  (port 8000) │      │  (port 3000)      │
 └────┬─────┘      └──────────────┘      └───────────────────┘
      │
      │ queue
      ▼
 ┌─────────────────────────────────────────────────────┐
 │                  Processing Pipeline                 │
 │                                                      │
 │  1. DOWNLOAD  (yt-dlp) ──► audio file               │
 │  2. TRANSCRIBE (Whisper) ──► word timestamps          │
 │  3. SCORE (LLM + Audio + Phrases) ──► top 4 clips    │
 │  4. CUT + REFORMAT (FFmpeg 9:16) ──► ready clips     │
 │  5. PUBLISH (TikTok / Shorts / Reels API)            │
 └─────────────────────────────────────────────────────┘
      │
      ▼
 ┌──────────────────┐    ┌──────────────────┐
 │ Cloudflare R2    │    │ Supabase /       │
 │ (video storage)  │    │ PostgreSQL (DB)  │
 └──────────────────┘    └──────────────────┘
```

---

## 5-Minute Quickstart

### 1. Clone and configure

```bash
git clone https://github.com/yourorg/clipforge.git
cd clipforge
cp backend/.env.example backend/.env
```

### 2. Set required environment variables

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/clipforge
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-proj-...
YOUTUBE_API_KEY=AIza...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
PUBSUBHUBBUB_CALLBACK_URL=https://yourdomain.com
CLOUDFLARE_R2_ACCOUNT_ID=...
CLOUDFLARE_R2_ACCESS_KEY_ID=...
CLOUDFLARE_R2_SECRET_ACCESS_KEY=...
CLOUDFLARE_R2_BUCKET_NAME=clipforge
CLOUDFLARE_R2_PUBLIC_URL=https://cdn.yourdomain.com
FRONTEND_URL=http://localhost:3000
TIKTOK_CLIENT_KEY=...
TIKTOK_CLIENT_SECRET=...
```

### 3. Start with Docker Compose

```bash
docker compose up -d
```

This starts: PostgreSQL, Redis, FastAPI backend, Celery worker, Celery beat, and Nginx.

### 4. Connect your first YouTube channel

1. Open http://localhost in your browser
2. Sign in with Google (Supabase OAuth)
3. Go to Channels → "Connect YouTube Channel"
4. Authorise your YouTube account
5. Click "Sync Now" to process the latest video

### 5. Watch clips get generated

The pipeline runs automatically:
- **Download** — yt-dlp grabs audio from the latest video
- **Transcribe** — Whisper creates word-level timestamps
- **Score** — 3-signal AI engine finds the best 4 viral segments
- **Cut** — FFmpeg crops to 9:16, burns captions, adds zoom effect
- **Publish** — Clips post to TikTok, Shorts, and Reels

Check the dashboard at http://localhost/dashboard for progress.

---

## All Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string (asyncpg) |
| `REDIS_URL` | Yes | Redis connection for Celery broker/backend |
| `OPENAI_API_KEY` | Yes | For Whisper transcription + GPT-4o-mini scoring |
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 for channel info |
| `STRIPE_SECRET_KEY` | Yes | Stripe API key for billing |
| `STRIPE_WEBHOOK_SECRET` | Yes | Stripe webhook signature verification |
| `PUBSUBHUBBUB_CALLBACK_URL` | Yes | Public URL for YouTube PubSub notifications |
| `CLOUDFLARE_R2_*` | Yes | R2/S3 credentials for video storage |
| `TIKTOK_CLIENT_KEY` | Conditional | Required for TikTok publishing |
| `TIKTOK_CLIENT_SECRET` | Conditional | Required for TikTok publishing |
| `FRONTEND_URL` | No | Frontend URL for CORS (default: http://localhost:3000) |
| `NEXT_PUBLIC_SUPABASE_URL` | Yes | Supabase project URL (frontend) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | Supabase anon key (frontend) |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Yes | Stripe publishable key (frontend) |

---

## Billing

ClipForge uses Stripe for subscription management:

| Plan | Price | Clips/Month | Platforms |
|---|---|---|---|
| Free | $0 | 5 | 1 |
| Pro | $19/mo | 100 | 3 |
| Agency | $49/mo | Unlimited | All |

Upgrade via Settings → Billing → Stripe Checkout portal. Webhooks auto-update plan status.

---

## Development

### Run locally without Docker

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Celery worker (in another terminal)
cd backend
celery -A celery_app worker --loglevel=info

# Frontend
cd frontend
npm install
npm run dev
```

### Run tests

```bash
cd backend
pytest tests/ -v
```

### Run launch checklist

```bash
bash scripts/launch_checklist.sh
```

---

## Tech Stack

- **Backend:** FastAPI, Celery, Redis, PostgreSQL (Supabase)
- **AI:** OpenAI Whisper (transcription), GPT-4o-mini (virality scoring), librosa (audio analysis)
- **Video:** FFmpeg (cut, 9:16, captions, zoom), yt-dlp (download)
- **Storage:** Cloudflare R2 (S3-compatible)
- **Frontend:** Next.js 14 App Router, TypeScript, Tailwind CSS, shadcn/ui
- **Auth:** Supabase Auth (Google OAuth)
- **Billing:** Stripe Checkout + Webhooks
- **Deploy:** Docker Compose, Nginx, GitHub Actions CI/CD
