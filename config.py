"""
Centralized configuration for the VOD clipper pipeline.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
# Whisper transcription: must be direct OpenAI (OpenRouter doesn't support audio)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Analysis (highlight detection): uses OpenRouter as proxy
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# --- Paths ---
PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Whisper (direct OpenAI) ---
WHISPER_MODEL = "whisper-1"

# --- Analysis Model (via OpenRouter) ---
# Recommended: "openai/gpt-4o-mini" (cheap + fast + good)
# Alternatives: "openai/gpt-4o", "anthropic/claude-3.5-sonnet",
#               "google/gemini-2.0-flash-001", "deepseek/deepseek-chat"
ANALYSIS_MODEL = os.getenv("ANALYSIS_MODEL", "openai/gpt-4o-mini")
ANALYSIS_TEMPERATURE = 0.3  # Low temp = more deterministic, consistent tagging

# --- Creator / Content Context (user-configurable) ---
# CHANNEL is the default creator/channel label used in filenames and Notion rows.
CHANNEL = os.getenv("CHANNEL", "channel")

# CREATOR_CONTEXT describes the creator and what to prioritize when picking clips.
# Override it in .env to tailor highlight selection to your own content.
CREATOR_CONTEXT = os.getenv(
    "CREATOR_CONTEXT",
    "A content creator who hosts live streams and long-form videos. "
    "Prioritize moments that are engaging, informative, entertaining, or shareable: "
    "strong opinions and hot takes, stories and personal anecdotes, teaching or how-to "
    "explanations, reactions to news or events, announcements, and funny or memorable "
    "exchanges.",
)

# CATEGORIES is the clip taxonomy the analyzer may assign and Notion exposes as a
# select. Keep these generic, or replace with categories that fit your content.
CATEGORIES = [
    "educational",
    "funny",
    "inspirational",
    "story",
    "reaction",
    "opinion",
    "tutorial",
    "qna",
    "announcement",
    "highlight",
]

# --- FFmpeg Scene Detection ---
SCENE_THRESHOLD = 0.3  # 0-1, higher = fewer scenes detected (stricter)

# --- Highlight Scoring ---
MIN_CLIP_DURATION_SEC = 20    # Allow clips slightly under the 30s prompt target
MAX_CLIP_DURATION_SEC = 300   # Cap clips at 5 minutes
MIN_CONFIDENCE = 0.4          # Drop highlights below this confidence
AUDIO_ENERGY_FLOOR_DB = -30   # Skip near-silent segments

# --- Chunking (for long VODs) ---
CHUNK_DURATION_MIN = 30  # Process VODs in 30-min chunks for Whisper

# --- Phase 2: Clip Cutting ---
CLIPS_DIR = OUTPUT_DIR / "clips"
CLIPS_DIR.mkdir(exist_ok=True)

# --- Phase 2: Dropbox ---
DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN")
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")  # Fallback (expires in 4h)
DROPBOX_VODS_FOLDER = os.getenv("DROPBOX_VODS_FOLDER", "/VODs")

# --- Phase 3: Notion ---
NOTION_API_KEY = os.getenv("NOTION_API_KEY")

def _extract_notion_id(raw_id: str) -> str:
    """Extract 32-char hex database ID from a Notion URL slug or raw ID."""
    if not raw_id:
        return raw_id
    import re
    # The Notion ID is always the last 32 hex chars in the URL slug
    clean = raw_id.replace("-", "")
    match = re.search(r'[0-9a-f]{32}$', clean)
    if match:
        hex_id = match.group(0)
        # Format as Notion expects: 8-4-4-4-12
        return f"{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"
    return raw_id  # Return as-is if no match

NOTION_MASTER_DB_ID = _extract_notion_id(os.getenv("NOTION_MASTER_DB_ID", ""))
