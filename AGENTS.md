# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

智能口播智能体 (Intelligent Oral Video Agent) — a monorepo for a short-video dubbing tool. Users paste a Douyin share link; the system downloads the video, transcribes the speech, rewrites the script via LLM, synthesizes new audio, and renders a final MP4 with voice, BGM, and subtitles.

```
oral-video-agent/
├── apps/client/        # Flutter client (Windows + Android)
├── services/api/       # FastAPI backend
├── storage/            # Local file storage (videos, audio, subtitles, outputs)
└── docs/               # Product spec
```

## Backend (services/api)

**Runtime**: Python 3.10+, managed with `uv`.

```bash
cd services/api
uv sync                                                        # install deps
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
uv run pytest tests/                                           # all tests
uv run pytest tests/test_tasks.py::test_health_check          # single test
```

**Environment**: Copy `.env.example` to `.env` and set providers. Settings are loaded from `.env` automatically via `python-dotenv` in `app/settings.py`.

Key env vars:
- `ASR_PROVIDER=faster-whisper` + `WHISPER_MODEL=small` — enables local Whisper ASR (CPU, int8)
- `REWRITE_PROVIDER=anthropic` + `ANTHROPIC_API_KEY=sk-...` — enables Codex rewriting
- Default for both is `placeholder` (returns dummy text, no external deps needed)

## Flutter Client (apps/client)

**Flutter path on this machine**: `<workspace>\flutter\bin\flutter.bat`

```bash
cd apps/client
flutter pub get
flutter run -d windows --dart-define=API_BASE=http://127.0.0.1:8000
flutter run -d android --dart-define=API_BASE=http://10.0.2.2:8000
flutter analyze lib/main.dart
```

## Architecture

### Provider Pattern

Every AI/video capability has a `Protocol` interface and multiple implementations selected by env var:

| Capability | Env var | Implementations |
|---|---|---|
| ASR | `ASR_PROVIDER` | `PlaceholderAsrProvider`, `FasterWhisperAsrProvider` |
| Rewrite | `REWRITE_PROVIDER` | `PlaceholderRewriteProvider`, `AnthropicRewriteProvider` |
| TTS | `VOICE_PROVIDER` | `PlaceholderVoiceProvider`, `ExternalVoiceProvider` |
| Video import | — | `VideoImporter` (Playwright browser interception) |

Factory functions (`create_asr_provider`, etc.) in each provider module read `Settings` and return the right implementation.

### Task Lifecycle

```
created → (import) → transcribed → (rewrite) → rewritten → (render) → completed
                                                                          ↓ failed
```

Each task has 6 progress steps: `import → transcribe → rewrite → voice → subtitle → render`.

Douyin import runs in a **background thread** (`threading.Thread`) so `POST /api/tasks` returns immediately. The Flutter client polls `GET /api/tasks/{id}` every 3 seconds until status is `transcribed` or `failed`.

### Persistence

- Tasks: `storage/tasks/tasks.json` (in-memory dict + JSON flush on every write)
- Assets: `storage/assets/assets.json`
- Files: UUID-named files under `storage/uploads/`, `extracted_audio/`, `subtitles/`, `outputs/`, `bgm/`, `voice_refs/`

### Douyin Video Extraction

`VideoImporter` uses Playwright to open the share URL in a headless Chromium browser, intercepts the `aweme/v1/web/aweme/detail` API response, extracts the CDN video URL (prefers `douyinvod.com`), and downloads it with browser headers. No cookies or API keys needed. Falls back gracefully — on `VideoImportError`, task status is set to `failed` with an error message.

### Flutter Video Playback

`media_kit` is used for Windows-compatible video playback. **Critical**: `Player` and `VideoController` must be created inside the dialog widget that owns the `Video` widget — not in a parent `initState`. Creating them before the `Video` widget renders causes a native texture crash (0×0 size). The `_VideoPlayerDialog` widget owns its own player lifecycle and calls `_player.open()` via `addPostFrameCallback` after the first frame.

### Subtitle Generation

`generate_srt()` in `pipeline/subtitles.py` wraps text by `max_chars_per_line` (default 18), breaks on Chinese punctuation, and assigns 1-second intervals per line. The `SubtitleStyle` model controls font size, color, outline color, position, and chars-per-line.

## File Upload Limits

Defined in `app/asset_store.py`:
- Source video: 500 MB
- Voice reference: 50 MB  
- BGM: 100 MB

Accepted MIME types are checked on upload; unsupported types return HTTP 400.
