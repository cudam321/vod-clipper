"""
VOD Dropbox Watcher — Polls a Dropbox folder for new VODs and auto-runs the pipeline.

Usage:
    python watcher.py [--folder /VODs] [--interval 30]

How it works:
  1. Polls a Dropbox folder (default: /VODs) for new video files
  2. Downloads new VODs to a local temp folder
  3. Runs the full pipeline (Phase 1 → 2 → 3)
  4. Moves the raw VOD into the per-stream folder alongside its clips

Upload a VOD from anywhere (phone, browser, another PC) and it auto-triggers.

Filename format (for auto-parsing date + title):
    "YYYY-MM-DD — Stream Title.mp4"
    "Live Stream.mp4"  (uses today's date)
"""
import os
import sys
import time
import re

from pathlib import Path
from datetime import date, datetime
from io import StringIO

import dropbox
from dropbox.exceptions import ApiError
from dropbox.common import PathRoot

from config import (
    DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN,
    DROPBOX_ACCESS_TOKEN, DROPBOX_VODS_FOLDER,
    OUTPUT_DIR,
)
from pipeline_full import run_full_pipeline

# Defaults
DEFAULT_DROPBOX_FOLDER = DROPBOX_VODS_FOLDER
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
POLL_INTERVAL = 30  # seconds between Dropbox API polls
LOGS_DIR = OUTPUT_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _get_client() -> dropbox.Dropbox:
    """
    Get authenticated Dropbox client.
    Uses namespace routing so it automatically looks in the team space
    if the account is part of a Dropbox Business team with a team space.
    """
    if DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY:
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET or "",
        )
        # Automatically route all API calls to the root namespace (handles both personal & team)
        root_ns = dbx.users_get_current_account().root_info.root_namespace_id
        return dbx.with_path_root(PathRoot.root(root_ns))

    elif DROPBOX_ACCESS_TOKEN:
        return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
    else:
        raise ValueError("No Dropbox credentials. Run: python setup_dropbox.py")


def parse_filename(filename: str) -> tuple[str, str]:
    """
    Extract date and title from filename.
    "2026-02-25 — Live Stream.mp4" → (2026-02-25, Live Stream)
    "Live Stream.mp4"              → (today, Live Stream)
    """
    stem = Path(filename).stem
    
    # Try YYYY-MM-DD format: "2025-02-25 - Title"
    match_ymd = re.match(r'^(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(.+)$', stem)
    if match_ymd:
        return match_ymd.group(1), match_ymd.group(2).strip()
        
    # Try MM.DD.YY or MM.DD.YYYY format: "12.04.25 - Title" or "12.04.2025 - Title"
    match_mdy = re.match(r'^(\d{2})\.(\d{2})\.(\d{2}|\d{4})\s*[—–-]\s*(.+)$', stem)
    if match_mdy:
        mm = match_mdy.group(1)
        dd = match_mdy.group(2)
        year_str = match_mdy.group(3)
        yyyy = year_str if len(year_str) == 4 else f"20{year_str}"
        return f"{yyyy}-{mm}-{dd}", match_mdy.group(4).strip()
        
    # Try MM.DD format: "02.25 - Title"
    match_md = re.match(r'^(\d{2}\.\d{2})\s*[—–-]\s*(.+)$', stem)
    if match_md:
        current_year = date.today().year
        mm_dd = match_md.group(1).replace('.', '-')
        return f"{current_year}-{mm_dd}", match_md.group(2).strip()
        
    # Fallback to today's date
    return date.today().isoformat(), stem.strip()


def list_new_videos(dbx: dropbox.Dropbox, folder: str, processed: set) -> list:
    """List video files in Dropbox folder that haven't been processed."""
    try:
        result = dbx.files_list_folder(folder)
    except ApiError as e:
        if "not_found" in str(e):
            # Create the folder if it doesn't exist
            dbx.files_create_folder_v2(folder)
            print(f"[Watcher] Created Dropbox folder: {folder}")
            return []
        raise

    videos = []
    for entry in result.entries:
        if not isinstance(entry, dropbox.files.FileMetadata):
            continue
        ext = Path(entry.name).suffix.lower()
        if ext not in VIDEO_EXTENSIONS:
            continue
        if entry.name in processed:
            continue
        videos.append(entry)

    return videos


def download_video(dbx: dropbox.Dropbox, dropbox_path: str, local_dir: str) -> str:
    """Download a video from Dropbox to a local directory."""
    filename = Path(dropbox_path).name
    local_path = os.path.join(local_dir, filename)

    print(f"  ↓ Downloading: {filename} directly to disk (streaming)...")
    metadata = dbx.files_download_to_file(local_path, dropbox_path)
    size_mb = metadata.size / 1024 / 1024

    print(f"  ✓ Downloaded: {size_mb:.0f} MB")
    return local_path



def load_processed(state_file: Path) -> set:
    """Load processed filenames from state file."""
    if state_file.exists():
        return set(state_file.read_text().strip().splitlines())
    return set()


def mark_processed(state_file: Path, filename: str):
    """Mark a file as processed."""
    with open(state_file, "a") as f:
        f.write(filename + "\n")




def log_job(filename: str, stream_date: str, stream_title: str,
           status: str, duration: float, result: dict = None, error: str = None):
    """Write a job log entry."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_name = re.sub(r'[^\w\-.]', '_', Path(filename).stem)
    log_file = LOGS_DIR / f"{timestamp}_{safe_name}.log"

    with open(log_file, "w") as f:
        f.write(f"{'='*60}\n")
        f.write(f"VOD Pipeline Job Log\n")
        f.write(f"{'='*60}\n")
        f.write(f"Timestamp:   {datetime.now().isoformat()}\n")
        f.write(f"File:        {filename}\n")
        f.write(f"Date:        {stream_date}\n")
        f.write(f"Title:       {stream_title}\n")
        f.write(f"Status:      {status}\n")
        f.write(f"Duration:    {duration:.1f}s\n")
        f.write(f"{'='*60}\n\n")

        if result:
            f.write(f"Clips found:     {result.get('clips_cut', 0)}\n")
            f.write(f"Clips uploaded:  {result.get('clips_uploaded', 0)}\n")
            if result.get('folder_link'):
                f.write(f"Dropbox folder:  {result['folder_link']}\n")
            if result.get('notion_result') and result['notion_result'].get('master_url'):
                f.write(f"Notion page:     {result['notion_result']['master_url']}\n")

        if error:
            f.write(f"\nERROR:\n{error}\n")

    return log_file


def show_history():
    """Show recent job logs."""
    logs = sorted(LOGS_DIR.glob("*.log"), reverse=True)

    if not logs:
        print("\n  No jobs yet. Start the watcher and upload a VOD.\n")
        return

    print(f"\n{'='*60}")
    print(f"  JOB HISTORY — {len(logs)} job(s)")
    print(f"{'='*60}\n")

    for log in logs[:20]:  # Show last 20
        lines = log.read_text().splitlines()
        info = {}
        for line in lines:
            if ":" in line and line[0] != "=":
                key, _, val = line.partition(":")
                info[key.strip()] = val.strip()

        status = info.get("Status", "?")
        icon = "✅" if status == "SUCCESS" else "❌" if status == "FAILED" else "⚠️"
        title = info.get("Title", "?")
        ts = info.get("Timestamp", "?")[:19]
        dur = info.get("Duration", "?")
        clips = info.get("Clips found", "?")

        print(f"  {icon} {ts}  {title:30s}  {clips} clips  {dur}  [{log.name}]")

    print(f"\n  Logs dir: {LOGS_DIR}")
    print(f"  View full log: cat {LOGS_DIR}/<filename>.log\n")


def run_watcher(dropbox_folder: str = None, interval: int = POLL_INTERVAL):
    """Main watcher loop — polls Dropbox for new VODs."""
    folder = dropbox_folder or DEFAULT_DROPBOX_FOLDER
    dbx = _get_client()

    # Verify connection
    account = dbx.users_get_current_account()

    # State file to track processed videos
    state_file = OUTPUT_DIR / ".watcher_processed"

    # Local download directory
    download_dir = OUTPUT_DIR / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  VOD WATCHER — Monitoring Dropbox")
    print(f"{'='*60}")
    print(f"  Account:    {account.name.display_name}")
    print(f"  Folder:     {folder}")
    print(f"  Poll:       every {interval}s")
    print(f"  Downloads:  {download_dir}")
    print(f"  Logs:       {LOGS_DIR}")
    print(f"{'='*60}")
    print(f"\n  Upload a .mp4 to Dropbox:{folder}")
    print(f"  Name it: \"2026-02-25 — Stream Title.mp4\"")
    print(f"  View history: python watcher.py --history")
    print(f"\n  Waiting for new files... (Ctrl+C to stop)\n")

    processed = load_processed(state_file)

    try:
        while True:
            try:
                videos = list_new_videos(dbx, folder, processed)
            except Exception as e:
                print(f"  ⚠ Dropbox poll error: {e}")
                time.sleep(interval)
                continue

            for video in videos:
                dropbox_path = f"{folder}/{video.name}"

                print(f"\n{'━'*60}")
                print(f"  📹 New VOD: {video.name}")
                size_mb = video.size / 1024 / 1024
                print(f"  📦 Size: {size_mb:.0f} MB")
                print(f"{'━'*60}")

                # Parse date + title
                stream_date, stream_title = parse_filename(video.name)
                print(f"  > Date:  {stream_date}")
                print(f"  > Title: {stream_title}")

                # Disk-space guard — ensure enough space for the VOD + processing overhead
                import shutil
                disk_free = shutil.disk_usage(str(download_dir)).free / (1024 ** 3)
                needed_gb = (video.size / (1024 ** 3)) + 3.0  # VOD size + ~3GB for audio/clips
                if disk_free < 5 or disk_free < needed_gb:
                    print(f"  !! Skipping: only {disk_free:.1f}GB free (need ~{needed_gb:.1f}GB)")
                    print(f"     Free up disk space and restart the watcher.")
                    continue

                # Download locally
                try:
                    local_path = download_video(dbx, dropbox_path, str(download_dir))
                except Exception as e:
                    print(f"  !! Download failed: {e}")
                    mark_processed(state_file, video.name)
                    processed.add(video.name)
                    continue

                # Run pipeline
                print(f"\n  🚀 Starting pipeline...\n")
                job_start = time.time()
                job_status = "FAILED"
                job_result = None
                job_error = None

                try:
                    job_result = run_full_pipeline(
                        video_path=local_path,
                        stream_date=stream_date,
                        stream_title=stream_title,
                        raw_dropbox_path=dropbox_path,
                    )
                    job_status = "SUCCESS"

                    # Clean up local download (raw VOD already moved to stream folder in Dropbox)
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass


                except Exception as e:
                    job_error = f"{e}\n{__import__('traceback').format_exc()}"
                    print(f"\n  ❌ Pipeline failed: {e}")
                    import traceback
                    traceback.print_exc()


                # Log the job
                job_duration = time.time() - job_start
                log_file = log_job(
                    filename=video.name,
                    stream_date=stream_date,
                    stream_title=stream_title,
                    status=job_status,
                    duration=job_duration,
                    result=job_result,
                    error=job_error,
                )
                print(f"\n  📋 Log saved: {log_file.name}")

                # Mark processed
                mark_processed(state_file, video.name)
                processed.add(video.name)

                print(f"\n  Resuming watch...\n")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n  Watcher stopped. Processed {len(processed)} files total.\n")


if __name__ == "__main__":
    if "--history" in sys.argv:
        show_history()
        sys.exit(0)

    folder = None
    interval = POLL_INTERVAL

    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--folder" and i + 1 <= len(sys.argv) - 1:
            folder = sys.argv[i + 1]
        elif arg == "--interval" and i + 1 <= len(sys.argv) - 1:
            interval = int(sys.argv[i + 1])

    run_watcher(folder, interval)
