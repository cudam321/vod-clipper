"""
Full Pipeline — Runs Phase 1 + Phase 2 + Phase 3 end-to-end.

Usage:
    python pipeline_full.py <path_to_vod.mp4> --date YYYY-MM-DD --title "Stream Title"

Phases:
  1. Highlight detection (Whisper + GPT-4o + FFmpeg)
  2. Clip cutting + Dropbox upload
  3. Notion sync (master + child tables)
"""
import sys
import json
import time
from pathlib import Path

from config import OUTPUT_DIR, CLIPS_DIR, DROPBOX_VODS_FOLDER, CHANNEL
from pipeline import run_pipeline
from clip_cutter import cut_clips
from dropbox_upload import upload_clips, _get_client
from dropbox.exceptions import ApiError
from notion_sync import sync_to_notion


def run_full_pipeline(
    video_path: str,
    stream_date: str,
    stream_title: str = "",
    channel: str = CHANNEL,
    video_url: str = "",
    skip_dropbox: bool = False,
    skip_notion: bool = False,
    raw_dropbox_path: str = None,
) -> dict:
    """
    Run the complete VOD-to-distribution pipeline.

    Args:
        video_path: Path to the source VOD file
        stream_date: ISO date string (YYYY-MM-DD)
        stream_title: Stream title
        channel: Channel name
        video_url: URL to the original VOD
        skip_dropbox: Skip Dropbox upload
        skip_notion: Skip Notion sync
        raw_dropbox_path: Original Dropbox path of the raw VOD (e.g. /VODs/filename.mp4).
                          If provided, the raw VOD will be moved into the stream folder
                          after clips are uploaded.

    Returns:
        Summary dict with all results
    """
    total_start = time.time()

    print(f"\n{'='*60}")
    print(f"VOD CLIPPER — Full Pipeline")
    print(f"{'='*60}")
    print(f"  Video:   {video_path}")
    print(f"  Date:    {stream_date}")
    print(f"  Title:   {stream_title or '(none)'}")
    print(f"  Channel: {channel}")
    print(f"{'='*60}\n")

    # ==========================================
    # PHASE 1: Highlight Detection
    # ==========================================
    print(f"\n{'━'*60}")
    print(f"  PHASE 1: Highlight Detection")
    print(f"{'━'*60}\n")
    highlights, run_dir = run_pipeline(video_path)

    if not highlights:
        print("\n❌ No highlights found. Stopping.")
        return {"highlights": [], "clips": 0}

    # ==========================================
    # PHASE 2: Clip Cutting + Dropbox Upload
    # ==========================================
    print(f"\n{'━'*60}")
    print(f"  PHASE 2: Clip Cutting + Dropbox Upload")
    print(f"{'━'*60}\n")

    # Cut clips
    print("▸ Cutting clips from VOD...")
    highlights = cut_clips(
        video_path=video_path,
        highlights_path=f"{run_dir}/highlights.json",
        stream_date=stream_date,
        stream_title=stream_title,
        channel=channel,
    )

    # Upload to Dropbox
    folder_link = ""
    if not skip_dropbox:
        print("\n▸ Uploading clips to Dropbox...")
        try:
            dbx = _get_client()

            # Build per-stream folder: MM.DD - Title (matches team convention)
            if stream_date and stream_title:
                mm_dd = stream_date[5:].replace("-", ".")  # "2025-02-25" → "02.25"
                stream_folder_name = f"{mm_dd} - {stream_title}"
            elif stream_date:
                mm_dd = stream_date[5:].replace("-", ".")
                stream_folder_name = f"{mm_dd} - {channel}"
            else:
                stream_folder_name = channel
            stream_folder = f"{DROPBOX_VODS_FOLDER}/{stream_folder_name}"

            # Create the per-stream folder on Dropbox
            try:
                dbx.files_get_metadata(stream_folder)
            except ApiError:
                dbx.files_create_folder_v2(stream_folder)
                print(f"[Dropbox] Created stream folder: {stream_folder}")

            # Upload clips into stream_folder/Highlights/
            highlights, folder_link = upload_clips(
                highlights=highlights,
                stream_folder=stream_folder,
            )

            # Move raw VOD into stream folder (if watcher provided its Dropbox path)
            if raw_dropbox_path:
                raw_filename = Path(raw_dropbox_path).name
                dest_path = f"{stream_folder}/{raw_filename}"
                try:
                    dbx.files_move_v2(raw_dropbox_path, dest_path)
                    print(f"[Dropbox] Moved raw VOD to: {dest_path}")
                except ApiError as e:
                    print(f"[Dropbox] \u26a0 Could not move raw VOD: {e}")

            # Save highlights with Dropbox links to per-video dir
            import json
            h_path = f"{run_dir}/highlights.json"
            with open(h_path, "w") as f:
                json.dump(highlights, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"\n\u26a0 Dropbox upload failed: {e}")
            print("  Continuing without Dropbox. Some clips might not have links.")
            # folder_link remains empty if it failed early, but highlights might have some links if it failed late.
    else:
        print("⊘ Dropbox upload skipped (--skip-dropbox)")

    # ==========================================
    # PHASE 3: Notion Sync
    # ==========================================
    print(f"\n{'━'*60}")
    print(f"  PHASE 3: Notion Sync")
    print(f"{'━'*60}\n")

    notion_result = None
    if not skip_notion:
        try:
            notion_result = sync_to_notion(
                highlights=highlights,
                stream_date=stream_date,
                channel=channel,
                video_url=video_url,
                stream_title=stream_title,
                dropbox_folder_link=folder_link or "",
            )
        except Exception as e:
            print(f"\n⚠ Notion sync failed: {e}")
            print("  Add NOTION_API_KEY and NOTION_MASTER_DB_ID to .env and retry.")
    else:
        print("⊘ Notion sync skipped (--skip-notion)")

    # ==========================================
    # SAVE RETRY MANIFEST (if Notion failed/skipped)
    # ==========================================
    notion_ok = notion_result and notion_result.get("master_page_id")
    if not notion_ok and highlights:
        pending_dir = OUTPUT_DIR / "notion_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        safe_name = stream_date or "unknown"
        if stream_title:
            import re as _re
            safe_title = _re.sub(r'[^\w\-.]', '_', stream_title)[:60]
            safe_name = f"{safe_name}_{safe_title}"
        manifest_path = pending_dir / f"{safe_name}.json"
        manifest = {
            "stream_date": stream_date,
            "stream_title": stream_title,
            "channel": channel,
            "video_url": video_url,
            "folder_link": folder_link,
            "highlights": highlights,
        }
        with open(manifest_path, "w") as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)
        print(f"\n  💾 Notion retry manifest saved: {manifest_path.name}")
        print(f"     Run: python notion_retry.py")

    # ==========================================
    # SUMMARY
    # ==========================================
    total_time = time.time() - total_start
    clips_cut = sum(1 for h in highlights if h.get("clip_path"))
    clips_uploaded = sum(1 for h in highlights if h.get("dropbox_link"))

    print(f"\n{'='*60}")
    print(f"  FULL PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"  Total time:      {total_time:.1f}s")
    print(f"  Highlights:      {len(highlights)}")
    print(f"  Clips cut:       {clips_cut}")
    print(f"  Clips uploaded:  {clips_uploaded}")
    if folder_link:
        print(f"  Dropbox folder:  {folder_link}")
    if notion_result:
        master_id = notion_result['master_page_id'].replace('-', '')
        print(f"  Notion page:     https://notion.so/{master_id}")
    print(f"{'='*60}\n")

    # Cleanup: remove per-video processing files to free space
    # (audio, transcript, scenes \u2014 already safely uploaded to Dropbox)
    if clips_uploaded > 0 and run_dir:
        import shutil
        from clip_cutter import sanitize_filename
        cleaned_mb = 0

        # Remove per-video output dir (audio, transcript, scenes, etc.)
        run_dir_path = Path(run_dir)
        if run_dir_path.exists():
            dir_size = sum(f.stat().st_size for f in run_dir_path.rglob("*") if f.is_file())
            shutil.rmtree(run_dir_path)
            cleaned_mb += dir_size / 1024 / 1024

        # Remove cut clips (they're in Dropbox)
        if stream_date and stream_title:
            folder_name = sanitize_filename(f"{stream_date} \u2014 {stream_title} \u2014 {channel}")
        elif stream_date:
            folder_name = f"{stream_date} \u2014 {channel}"
        else:
            folder_name = channel
            
        clips_dir_path = CLIPS_DIR / folder_name
        
        if clips_dir_path.exists():
            dir_size = sum(f.stat().st_size for f in clips_dir_path.rglob("*") if f.is_file())
            shutil.rmtree(clips_dir_path)
            cleaned_mb += dir_size / 1024 / 1024

        if cleaned_mb > 0:
            print(f"  [cleanup] Cleaned up {cleaned_mb:.0f} MB of local files")

    return {
        "highlights": highlights,
        "clips_cut": clips_cut,
        "clips_uploaded": clips_uploaded,
        "folder_link": folder_link,
        "notion_result": notion_result,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline_full.py <path_to_vod.mp4> --date YYYY-MM-DD [--title 'Title']")
        print("\nOptions:")
        print("  --date YYYY-MM-DD     Stream date (required)")
        print("  --title 'Title'       Stream title")
        print("  --url 'URL'           Original VOD URL")
        print("  --skip-dropbox        Skip Dropbox upload")
        print("  --skip-notion         Skip Notion sync")
        sys.exit(1)

    video = sys.argv[1]
    date = None
    title = ""
    url = ""
    skip_db = "--skip-dropbox" in sys.argv
    skip_notion = "--skip-notion" in sys.argv

    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--date" and i + 1 < len(sys.argv):
            date = sys.argv[i + 1]
        elif arg == "--title" and i + 1 < len(sys.argv):
            title = sys.argv[i + 1]
        elif arg == "--url" and i + 1 < len(sys.argv):
            url = sys.argv[i + 1]

    if not date:
        print("Error: --date YYYY-MM-DD is required")
        sys.exit(1)

    run_full_pipeline(
        video_path=video,
        stream_date=date,
        stream_title=title,
        video_url=url,
        skip_dropbox=skip_db,
        skip_notion=skip_notion,
    )
