"""
Phase 3: Sync highlights data to Notion.

Architecture:
  - Master Database ("Stream Content Log"): one row per stream
  - Each master row's page contains an INLINE DATABASE of clips
  - No shared child database — each stream is self-contained

Requires:
  - NOTION_API_KEY in .env
  - NOTION_MASTER_DB_ID in .env
  - Master database must exist in Notion with correct properties (see --setup)
"""
import json
import time
import requests
from config import NOTION_API_KEY, NOTION_MASTER_DB_ID, OUTPUT_DIR, CATEGORIES, CHANNEL

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Notion select colors, cycled across the configured CATEGORIES so each tag
# gets a stable, distinct color without hardcoding any specific taxonomy.
NOTION_SELECT_COLORS = [
    "blue", "green", "yellow", "orange", "red",
    "pink", "purple", "brown", "gray", "default",
]


def _category_select_options() -> list[dict]:
    """Build Notion select options from the configured CATEGORIES list."""
    return [
        {"name": cat, "color": NOTION_SELECT_COLORS[i % len(NOTION_SELECT_COLORS)]}
        for i, cat in enumerate(CATEGORIES)
    ]


def _headers() -> dict:
    if not NOTION_API_KEY:
        raise ValueError(
            "NOTION_API_KEY not set. Add it to your .env file. "
            "Create an integration at: https://www.notion.so/my-integrations"
        )
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def _rate_limit_wait():
    """Notion allows ~3 requests/sec."""
    time.sleep(0.35)


# ============================================================
# Step 1: Create master row in Stream Content Log
# ============================================================

def create_master_row(
    stream_date: str,
    channel: str,
    video_url: str = "",
    title: str = "",
    clip_count: int = 0,
    dropbox_folder_link: str = "",
) -> str:
    """Create a row in the Master Database. Returns Notion page ID."""
    properties = {
        "Name": {
            "title": [{"text": {"content": title or f"{channel} — {stream_date}"}}]
        },
        "Date": {
            "date": {"start": stream_date}
        },
        "Channel": {
            "rich_text": [{"text": {"content": channel}}]
        },
    }

    if video_url:
        properties["URL"] = {"url": video_url}
    elif dropbox_folder_link:
        properties["URL"] = {"url": dropbox_folder_link}

    payload = {
        "parent": {"database_id": NOTION_MASTER_DB_ID},
        "properties": properties,
    }

    resp = requests.post(f"{NOTION_API_URL}/pages", headers=_headers(), json=payload)
    if not resp.ok:
        print(f"[Notion ERROR] {resp.text}")
    resp.raise_for_status()
    page_id = resp.json()["id"]
    print(f"[Notion] Master row created: {title or channel} ({page_id})")
    _rate_limit_wait()
    return page_id


# ============================================================
# Step 2: Create inline clip database inside the master page
# ============================================================

def create_inline_clip_database(master_page_id: str, title: str = "Clips") -> str:
    """
    Create an inline database inside the master row's page body.
    Returns the new database ID.
    """
    payload = {
        "parent": {"type": "page_id", "page_id": master_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "is_inline": True,
        "properties": {
            "Clip": {
                "title": {}
            },
            "Timeframe": {
                "rich_text": {}
            },
            "Duration": {
                "number": {"format": "number"}
            },
            "Category": {
                "select": {
                    "options": _category_select_options()
                }
            },
            "Content Quality": {
                "number": {"format": "percent"}
            },
            "Dropbox Link": {
                "url": {}
            },
        },
    }

    resp = requests.post(f"{NOTION_API_URL}/databases", headers=_headers(), json=payload)
    if not resp.ok:
        print(f"[Notion ERROR] {resp.text}")
    resp.raise_for_status()
    db_id = resp.json()["id"]
    print(f"[Notion] Inline clip database created ({db_id})")
    _rate_limit_wait()
    return db_id


# ============================================================
# Step 3: Add clip rows to the inline database
# ============================================================

def add_clip_row(db_id: str, highlight: dict) -> str:
    """Add a single clip row to the inline database."""
    clip_id = highlight.get("id", "C0")
    tldr = highlight.get("tldr", "Untitled clip")
    timeframe = highlight.get("timeframe", "")
    dropbox_link = highlight.get("dropbox_link", "")
    category = highlight.get("category", "")
    confidence = highlight.get("confidence", 0)
    duration = highlight.get("duration_sec", 0)

    properties = {
        "Clip": {
            "title": [{"text": {"content": f"{clip_id} — {tldr}"}}]
        },
        "Timeframe": {
            "rich_text": [{"text": {"content": timeframe}}]
        },
        "Duration": {
            "number": duration
        },
        "Category": {
            "select": {"name": category}
        },
        "Content Quality": {
            "number": confidence
        },
    }

    if dropbox_link:
        properties["Dropbox Link"] = {"url": dropbox_link}

    payload = {
        "parent": {"database_id": db_id},
        "properties": properties,
    }

    resp = requests.post(f"{NOTION_API_URL}/pages", headers=_headers(), json=payload)
    if not resp.ok:
        print(f"[Notion ERROR] {resp.text}")
    resp.raise_for_status()
    page_id = resp.json()["id"]
    print(f"  + {clip_id}: {tldr[:50]}")
    _rate_limit_wait()
    return page_id


# ============================================================
# Full sync: master row → inline DB → clip rows
# ============================================================

def sync_to_notion(
    highlights: list[dict],
    stream_date: str,
    channel: str = CHANNEL,
    video_url: str = "",
    stream_title: str = "",
    dropbox_folder_link: str = "",
) -> dict:
    """
    Full sync: create master row, inline clip database, and all clip rows.
    """
    print(f"\n[Notion] Syncing {len(highlights)} clips to Notion...")

    # Check idempotency
    if stream_exists(stream_date, channel, stream_title):
        print("[Notion] Stream already exists — skipping to avoid duplicates.")
        return {"master_page_id": None, "skipped": True}

    # 1. Create master row
    master_id = create_master_row(
        stream_date=stream_date,
        channel=channel,
        video_url=video_url,
        title=stream_title,
        clip_count=len(highlights),
        dropbox_folder_link=dropbox_folder_link,
    )

    # 2. Create inline clip database inside the master page
    db_title = f"Clips — {stream_title or stream_date}"
    inline_db_id = create_inline_clip_database(master_id, title=db_title)

    # 3. Add clip rows
    print(f"\n[Notion] Adding {len(highlights)} clips...")
    child_ids = []
    for h in highlights:
        try:
            child_id = add_clip_row(inline_db_id, h)
            child_ids.append(child_id)
        except requests.HTTPError as e:
            print(f"  ✗ {h.get('id', '?')}: Failed — {e}")
            child_ids.append(None)

    successful = sum(1 for c in child_ids if c)
    master_url = f"https://notion.so/{master_id.replace('-', '')}"
    print(f"\n[Notion] Done: {successful}/{len(highlights)} clips added")
    print(f"[Notion] Page: {master_url}")

    return {
        "master_page_id": master_id,
        "inline_db_id": inline_db_id,
        "child_page_ids": child_ids,
        "master_url": master_url,
    }


def stream_exists(stream_date: str, channel: str = CHANNEL, title: str = "") -> bool:
    """Check if a stream already exists (idempotency). Matches on date + channel + title."""
    if not NOTION_MASTER_DB_ID:
        return False

    filters = [
        {"property": "Date", "date": {"equals": stream_date}},
        {"property": "Channel", "rich_text": {"contains": channel}},
    ]
    if title:
        filters.append({"property": "Name", "title": {"equals": title}})

    payload = {"filter": {"and": filters}}

    resp = requests.post(
        f"{NOTION_API_URL}/databases/{NOTION_MASTER_DB_ID}/query",
        headers=_headers(), json=payload,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    _rate_limit_wait()
    return len(results) > 0


def print_setup_instructions():
    """Print Notion setup instructions."""
    print("""
╔══════════════════════════════════════════════════════════╗
║           NOTION DATABASE SETUP INSTRUCTIONS            ║
╠══════════════════════════════════════════════════════════╣
║                                                         ║
║  1. Create a Notion integration:                        ║
║     → https://www.notion.so/my-integrations             ║
║     → Copy the "Internal Integration Secret"            ║
║     → Add to .env as NOTION_API_KEY                     ║
║                                                         ║
║  2. Create ONE database: "Stream Content Log"           ║
║     Properties:                                         ║
║     • Title (title)   — auto-created                    ║
║     • Date (date)                                       ║
║     • Channel (rich_text)                               ║
║     • Video URL (url)                                   ║
║     • Clip Count (number)                               ║
║     • Dropbox Folder (url)                              ║
║                                                         ║
║  3. Share the database with your integration            ║
║     → Click ••• → Connections → your integration        ║
║                                                         ║
║  4. Copy database ID to .env:                           ║
║     → Open database as full page                        ║
║     → URL: notion.so/<DB_ID>?v=...                      ║
║     → NOTION_MASTER_DB_ID=<db id>                       ║
║                                                         ║
║  That's it! The script will automatically create an     ║
║  inline clip database inside each stream page.          ║
╚══════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    import sys

    if "--setup" in sys.argv:
        print_setup_instructions()
        sys.exit(0)

    h_path = OUTPUT_DIR / "highlights.json"
    if not h_path.exists():
        print("No highlights.json found. Run pipeline.py first.")
        sys.exit(1)

    with open(h_path) as f:
        highlights = json.load(f)

    date = None
    title = ""
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--date" and i + 1 <= len(sys.argv) - 1:
            date = sys.argv[i + 1]
        elif arg == "--title" and i + 1 <= len(sys.argv) - 1:
            title = sys.argv[i + 1]

    if not date:
        print("Usage: python notion_sync.py --date YYYY-MM-DD [--title 'Stream Title']")
        print("       python notion_sync.py --setup")
        sys.exit(1)

    sync_to_notion(highlights, stream_date=date, stream_title=title)
