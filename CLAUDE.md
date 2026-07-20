# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (`backend/`, FastAPI + Python 3.10)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
alembic upgrade head                     # apply DB migrations
uvicorn main:app --reload --port 8000     # dev server

ruff check .                              # lint (CI: backend-lint job)
ruff format --check .                     # format check (ruff format . to fix)

pytest -v                                 # full suite
pytest tests/test_health.py -v            # single module
pytest tests/test_avatars.py::test_upload_avatar -v   # single test
pytest --cov=app --cov-report=html        # coverage
```

Backend tests need Postgres + Redis reachable (see `.github/workflows/ci.yml` for the exact service containers/env vars it spins up: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, plus `SECRET_KEY`/`JWT_SECRET_KEY` — both enforced at import time to be ≥32 chars and not one of the placeholder defaults, so tests fail immediately without them). `ffmpeg` must be installed for animator tests.

### Frontend (`frontend/`, Next.js 14 App Router + TypeScript)

```bash
npm install
npm run dev         # localhost:3000
npm run build        # also the TS-error gate used in CI/CONTRIBUTING checklist
npm run lint          # eslint .
npm run typecheck      # tsc --noEmit
```

There is no frontend test runner configured (no `npm test` script) despite `SETUP_GUIDE.md` referencing one — don't assume it exists.

### Full stack via Docker

```bash
cp .env.example .env              # add ANTHROPIC_API_KEY (or OPENAI_API_KEY / point OPENAI_BASE_URL at Ollama)
docker compose up -d               # frontend :3000, backend :8000, docs :8000/docs, Flower :5555
```

Production overlay: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (adds GPU reservation, float16 inference, no bind mounts, log rotation, disables Flower).

## Architecture

Real-time conversational AI avatar system: browser mic/text → STT → LLM → TTS → lip-sync video, streamed back over a single WebSocket per session.

```
Browser ── REST (upload/auth/history) ──► FastAPI (backend/main.py)
        └─ WS /ws/session/{id} ──────────► app/websocket.py (WebSocketManager)
                                               │
                                    splits LLM reply into sentences,
                                    pipelines each sentence: TTS → animator → chunk out
                                               │
              ┌───────────┬───────────┬───────┴───────┬─────────────┐
        app/services/llm  stt        tts           animator       storage
        (Claude/GPT/      (Whisper,  (Chatterbox→   (MuseTalk      (local FS or
         Ollama, streaming) faster-   edge-tts→gTTS  persistent     S3, behind
                            whisper)  fallback chain) worker/simple) USE_LOCAL_STORAGE)
```

- **`backend/main.py`** — FastAPI app assembly: CORS, security headers, rate-limit and request-logging middleware (`app/middleware/`), Prometheus instrumentation, optional Sentry/OpenTelemetry (`app/telemetry.py`, gated by `OTEL_ENABLED` — spans are no-ops when off), and route registration for `app/api/v1/{users,avatars,sessions,messages,conversations,voices}.py`. On startup it runs `create_all` only as a dev convenience for a fresh DB — production schema state comes from `alembic upgrade head` in `entrypoint.sh` *before* the app starts, so don't rely on `create_all` to pick up migration changes (it silently skips index/column changes on existing tables).
- **`app/websocket.py`** — the real-time core. One connection per session; on each user turn it streams LLM tokens (`app/services/llm.py`), buffers them into sentences, and for each sentence kicks off TTS → animator in a pipeline so the first video chunk can play before the LLM finishes generating. Handles `stop` (barge-in — cancels the in-flight turn), `set_voice`, `set_language`, and `ping`. See the README's "WebSocket" section for the exact message schema (`token`, `video_chunk`, `tts_fallback`, `interrupted`, etc.) — treat that schema as the contract; the frontend's `ChatInterface.tsx`/`lib/api.ts` and the backend must stay in sync on it.
- **`app/services/animator.py`** (`AvatarAnimator`) — engine selected by `AVATAR_ENGINE` (`musetalk` or `simple`; the README's `sadtalker`/`liveportrait` mentions in `SETUP_GUIDE.md` are stale, ignore them). `musetalk` talks to a **persistent worker subprocess** (`backend/musetalk_worker.py`) so models load into VRAM once instead of per-request; falls back to `simple` (ffmpeg still-image + audio, no lip-sync) if MuseTalk models aren't present at `MUSETALK_PATH` (fetched via `scripts/setup_musetalk.sh`, ~9 GB). float16 is auto-enabled on CUDA.
- **`app/services/tts.py`** — fallback chain `chatterbox` (zero-shot voice cloning, 23 languages) → `edge-tts` (free neural voices) → `gTTS`, so the pipeline is never silent even without GPU/network access to the primary engine.
- **`app/services/storage.py`** — abstracts local filesystem (`USE_LOCAL_STORAGE=true`, default, writes under `backend/uploads/`) vs. S3 (+ presigned URLs / CloudFront) behind one interface; most local dev doesn't need AWS at all.
- **`app/config.py`** (`Settings`, pydantic-settings) — the single source of truth for env-driven config; read this before assuming a setting name. Notably validates `SECRET_KEY`/`JWT_SECRET_KEY` are ≥32 chars and not a placeholder (raises at import time otherwise), and accepts `CORS_ORIGINS`/`ALLOWED_EXTENSIONS` as either JSON or comma-separated strings.
- **Auth** — JWT set in an httpOnly cookie on login (not readable by JS, XSS-resistant), `AUTH_COOKIE_SECURE` should be `true` in `.env.prod`.
- **`backend/alembic/`** — migrations are append-only (ruff excludes `alembic/versions` from lint churn); add new migrations rather than editing old ones.
- **Frontend** (`frontend/`) — Next.js 14 App Router, Zustand for global state (`store/useStore.ts`), Axios client in `lib/api.ts`, TanStack Query for server state. Key components: `ChatInterface.tsx` (WebSocket + chat UI), `AvatarUpload.tsx`/`AvatarList.tsx`, `VoicePanel.tsx` (cloning), `SettingsPanel.tsx`, `HistoryPanel.tsx`, `WaveformVisualizer.tsx`. `frontend/next.config.js` — this is a normal server-rendered/deployed Next app (Dockerfile-built), **not** a static export like the sibling `elyashar-nirko-labs` project.
- **`infrastructure/`** — Terraform for the AWS ECS path (RDS, ElastiCache, S3, CloudFront); `scripts/deploy-aws.sh` is the alternate one-command EC2 GPU path (installs Docker/nvidia-docker2, downloads MuseTalk models, brings up `docker-compose.prod.yml` with GPU passthrough). These are two distinct deployment targets — check which one a task actually concerns before editing either.

### Docs accuracy note

`README.md` reflects current behavior (config names, model defaults, engine names) and should be treated as authoritative; `SETUP_GUIDE.md` is older and contains stale/contradictory details (Windows-specific paths, `AVATAR_ENGINE=sadtalker|liveportrait`, an outdated Claude model string, placeholder support URLs) — don't copy from it without cross-checking against `app/config.py` and the README first.

## Key Constraints

- **CI is path-filtered** (`.github/workflows/ci.yml`): backend jobs (ruff lint/format, pytest+coverage, pip-audit) only run when `backend/**` changed; frontend jobs (eslint, `next build`) only run when `frontend/**` changed. A PR touching only one side won't trigger the other's checks.
- **Secrets validation is fail-fast**: missing or weak `SECRET_KEY`/`JWT_SECRET_KEY` aborts the entire app/test process at import time, not at request time — if tests or the server won't start at all, check these first.
- **Model/version defaults live in `app/config.py`**, not scattered across the codebase — update them there (e.g. `LLM_MODEL`, `WHISPER_MODEL`, `TTS_PROVIDER`) rather than hardcoding elsewhere.
- **GPU is optional but changes behavior**, not just speed: `AvatarAnimator` and TTS both branch on `torch.cuda.is_available()` (float16, worker vs. fallback engine). When touching either service, consider both code paths, not just whichever one your dev machine has.
