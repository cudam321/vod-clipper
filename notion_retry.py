"""
Retry Notion sync for streams that failed during the pipeline.

Usage:
    python notion_retry.py              # retry all pending
    python notion_retry.py --list       # list pending syncs
    python notion_retry.py --file X.json  # retry a specific one
"""
import sys
import json
import shutil
from pathlib import Path

from config import OUTPUT_DIR, CHANNEL
from notion_sync import sync_to_notion

PENDING_DIR = OUTPUT_DIR / "notion_pending"
DONE_DIR = OUTPUT_DIR / "notion_done"


def list_pending():
    """List all pending Notion syncs."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    manifests = sorted(PENDING_DIR.glob("*.json"))

    if not manifests:
        print("\n  ✅ No pending Notion syncs.\n")
        return []

    print(f"\n{'='*60}")
    print(f"  PENDING NOTION SYNCS — {len(manifests)} stream(s)")
    print(f"{'='*60}\n")

    for m in manifests:
        data = json.loads(m.read_text())
        clip_count = len(data.get("highlights", []))
        date = data.get("stream_date", "?")
        title = data.get("stream_title", "?")
        has_links = sum(1 for h in data.get("highlights", []) if h.get("dropbox_link"))
        print(f"  📋 {m.name}")
        print(f"     {date} — {title}")
        print(f"     {clip_count} clips, {has_links} with Dropbox links\n")

    return manifests


def retry_one(manifest_path: Path) -> bool:
    """Retry Notion sync for a single manifest. Returns True on success."""
    data = json.loads(manifest_path.read_text())

    print(f"\n{'━'*60}")
    print(f"  Retrying: {data.get('stream_title', manifest_path.name)}")
    print(f"  Date: {data.get('stream_date')}")
    print(f"  Clips: {len(data.get('highlights', []))}")
    print(f"{'━'*60}\n")

    try:
        result = sync_to_notion(
            highlights=data["highlights"],
            stream_date=data["stream_date"],
            channel=data.get("channel", CHANNEL),
            video_url=data.get("video_url", ""),
            stream_title=data.get("stream_title", ""),
            dropbox_folder_link=data.get("folder_link", ""),
        )

        if result and result.get("master_page_id"):
            # Success → move to done
            DONE_DIR.mkdir(parents=True, exist_ok=True)
            done_path = DONE_DIR / manifest_path.name
            shutil.move(str(manifest_path), str(done_path))
            print(f"\n  ✅ Synced! Manifest moved to notion_done/")
            return True
        elif result and result.get("skipped"):
            # Already exists → move to done
            DONE_DIR.mkdir(parents=True, exist_ok=True)
            done_path = DONE_DIR / manifest_path.name
            shutil.move(str(manifest_path), str(done_path))
            print(f"\n  ⊘ Already in Notion. Manifest moved to notion_done/")
            return True
        else:
            print(f"\n  ❌ Sync returned no page ID. Will retry next time.")
            return False

    except Exception as e:
        print(f"\n  ❌ Failed: {e}")
        print(f"     Manifest stays in notion_pending/ for next retry.")
        return False


def retry_all():
    """Retry all pending Notion syncs."""
    manifests = list_pending()
    if not manifests:
        return

    print(f"{'='*60}")
    print(f"  Starting retry for {len(manifests)} stream(s)...")
    print(f"{'='*60}\n")

    success = 0
    for m in manifests:
        if retry_one(m):
            success += 1

    print(f"\n{'='*60}")
    print(f"  RETRY COMPLETE: {success}/{len(manifests)} synced")
    if success < len(manifests):
        print(f"  Remaining: {len(manifests) - success} still pending")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    if "--list" in sys.argv:
        list_pending()
    elif "--file" in sys.argv:
        idx = sys.argv.index("--file")
        if idx + 1 >= len(sys.argv):
            print("Usage: python notion_retry.py --file <manifest.json>")
            sys.exit(1)
        path = Path(sys.argv[idx + 1])
        if not path.exists():
            # Try in pending dir
            path = PENDING_DIR / sys.argv[idx + 1]
        if not path.exists():
            print(f"File not found: {sys.argv[idx + 1]}")
            sys.exit(1)
        retry_one(path)
    else:
        retry_all()
