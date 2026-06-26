# VOD Clipper

> Automated VOD → highlight clips → Dropbox + Notion pipeline for any creator.

Drop a long video (livestream VOD, podcast, talk) into a Dropbox folder and the
pipeline transcribes it, uses an LLM to find the most clip-worthy moments, cuts
those moments into standalone clips with FFmpeg, uploads them to Dropbox with
shareable links, and logs everything to a Notion database — fully unattended.

It is **content-agnostic**: the creator description and clip taxonomy live in
environment variables (`CREATOR_CONTEXT`, `CHANNEL`) and config (`CATEGORIES`),
so you tailor highlight selection to your own content without touching code.

---

## How it works

```
Upload a VOD to Dropbox:/VODs/
        │
        ▼
WATCHER (watcher.py) — polls Dropbox, detects new video, downloads it,
                       parses date + title from the filename
        │
        ▼
PHASE 1 — Highlight detection (pipeline.py)
  1. FFmpeg     → extract audio
  2. Whisper    → transcribe
  3. LLM        → identify clip-worthy moments (via OpenRouter)
  4. FFmpeg     → detect scene changes
  5. Merge      → group moments into clips, score, deduplicate → highlights.json
        │
        ▼
PHASE 2 — Cut + upload (clip_cutter.py, dropbox_upload.py)
  • FFmpeg stream-copies each clip out of the VOD
  • Clips upload to a per-stream Dropbox folder with shared links
        │
        ▼
PHASE 3 — Notion sync (notion_sync.py)
  • Creates a master row in your "Stream Content Log" database
  • Adds an inline clip table with category, duration, and Dropbox links
        │
        ▼
DONE — clips in Dropbox, a Notion page with links, and a job log in output/logs/
```

---

## Requirements

- **Python 3.9+**
- **FFmpeg** (`ffmpeg` + `ffprobe` on your PATH) — `brew install ffmpeg` / `apt-get install ffmpeg`
- API access: OpenAI (Whisper), OpenRouter (analysis), Dropbox, Notion

---

## Setup

1. **Install dependencies:**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # then edit .env and fill in your keys
   ```

3. **Dropbox auth (one-time):**
   ```bash
   python setup_dropbox.py
   ```
   Follow the prompts; paste the printed `DROPBOX_APP_KEY` / `DROPBOX_APP_SECRET` /
   `DROPBOX_REFRESH_TOKEN` into your `.env`.

4. **Notion setup:**
   ```bash
   python notion_sync.py --setup
   ```
   Create the database it describes, share it with your integration, and put its
   ID in `NOTION_MASTER_DB_ID`.

5. **Customize for your content (optional but recommended):**
   - `CHANNEL` — label used in filenames and Notion rows
   - `CREATOR_CONTEXT` — describes the creator and what to prioritize when picking clips
   - `CATEGORIES` (in `config.py`) — the clip taxonomy used by the analyzer and Notion

---

## Usage

### Automatic (watcher mode — recommended)
```bash
python watcher.py
# Then upload an .mp4 to Dropbox:/VODs/
# Name it "2026-02-25 — Stream Title.mp4" for auto date/title parsing.
```

Options:
```bash
python watcher.py --folder /VODs --interval 30
python watcher.py --history       # show recent job logs
```

### One-shot (single local VOD)
```bash
python pipeline_full.py "/path/to/vod.mp4" --date 2026-02-25 --title "Stream Title"

# Useful flags:
#   --url 'https://...'   original VOD URL (recorded in Notion)
#   --skip-dropbox        run locally, skip upload
#   --skip-notion         skip Notion sync
```

### Phase 1 only (highlights, no cutting/upload)
```bash
python pipeline.py "/path/to/vod.mp4"
```

### Retry failed Notion syncs
```bash
python notion_retry.py            # retry all pending
python notion_retry.py --list     # list pending
```

---

## Filename format

Any `.mp4` works. For automatic date/title parsing:

| Filename | Parsed date | Parsed title |
|----------|-------------|--------------|
| `2026-02-25 — Stream Title.mp4` | 2026-02-25 | Stream Title |
| `02.25.26 — Stream Title.mp4`   | 2026-02-25 | Stream Title |
| `Live Stream.mp4`               | today      | Live Stream  |

---

## Dropbox layout

```
Dropbox:/VODs/                          ← upload VODs here
└── 02.25 - Stream Title/               ← created per stream
    ├── <original VOD>.mp4              ← moved here after processing
    └── Highlights/
        ├── C1 — Clip Title.mp4
        ├── C2 — Another Clip.mp4
        └── ...
```

Local working files live under `output/` (gitignored):

```
output/
├── <video_name>/          # per-video processing data (audio, transcript, scenes, highlights)
├── clips/                 # locally cut clips before upload
├── downloads/             # temp VOD downloads (auto-cleaned)
├── logs/                  # per-job logs with status + errors
└── notion_pending/        # manifests for Notion syncs to retry
```

---

## Files

| File | Purpose |
|------|---------|
| `watcher.py` | Polls Dropbox for new videos, triggers the pipeline |
| `pipeline_full.py` | Chains Phase 1 → 2 → 3 end-to-end |
| `pipeline.py` | Phase 1: Whisper + LLM + FFmpeg → highlights.json |
| `ffmpeg_extract.py` | Audio extraction, chunking, scene detection |
| `transcribe.py` | Whisper API transcription |
| `analyze.py` | LLM highlight classification (creator-configurable prompt) |
| `merge_highlights.py` | Groups short moments into full clips, scores, deduplicates |
| `clip_cutter.py` | FFmpeg stream-copy clip cutting |
| `dropbox_upload.py` | Upload clips + generate shared links |
| `notion_sync.py` | Master row + inline clip database creation |
| `notion_retry.py` | Retry Notion syncs that failed during a run |
| `config.py` | API keys, thresholds, paths, creator context, categories |
| `setup_dropbox.py` | One-time Dropbox OAuth2 setup (refresh token) |

---

## Deploy as a service (systemd)

The watcher can run as a background service. The deploy script assumes the
project lives at `/opt/vod-clipper`.

```bash
# Copy/clone the project to /opt/vod-clipper, then on a Debian/Ubuntu host:
sudo bash deploy.sh
# Put your API keys in /opt/vod-clipper/.env, then:
sudo systemctl start vod-clipper
sudo systemctl status vod-clipper
journalctl -u vod-clipper -f
```

`deploy.sh` installs system deps (Python, FFmpeg), creates a service user, sets
up a virtualenv, and installs the `vod-clipper.service` unit.

---

## Approximate cost per ~30 min VOD

| Service | Cost |
|---------|------|
| Whisper API | ~$0.36 |
| Analysis model (gpt-4o-mini) | ~$0.10 |
| Dropbox / Notion | Free tier |
| **Total** | **~$0.50 / VOD** |

Actual cost varies with VOD length and the analysis model you choose.

---

## License

MIT — see [LICENSE](LICENSE).
