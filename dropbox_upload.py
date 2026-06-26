"""
Phase 2b: Upload cut clips to Dropbox and generate shared links.

Uploads clips from the local clips folder to Dropbox, creating a mirrored
folder structure. Generates shared links for each clip and the folder.
"""
import dropbox
from dropbox.exceptions import ApiError
from dropbox.files import WriteMode
import json
import time
from pathlib import Path
from dropbox.common import PathRoot
from config import (
    DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN,
    DROPBOX_ACCESS_TOKEN, DROPBOX_VODS_FOLDER, OUTPUT_DIR, CHANNEL,
)

# Dropbox API upload limit: 150MB per single upload, use sessions for larger
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks for upload sessions


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
            timeout=900,
        )
        # Automatically route all API calls to the root namespace (handles both personal & team)
        root_ns = dbx.users_get_current_account().root_info.root_namespace_id
        return dbx.with_path_root(PathRoot.root(root_ns))

    elif DROPBOX_ACCESS_TOKEN:
        return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN, timeout=900)
    else:
        raise ValueError(
            "No Dropbox credentials. Run: python setup_dropbox.py\n"
            "Or add DROPBOX_ACCESS_TOKEN to .env (expires in 4h)"
        )


def upload_clips(
    highlights: list[dict],
    stream_folder: str,
) -> list[dict]:
    """
    Upload cut clips to Dropbox into a Highlights/ subfolder within stream_folder.

    Args:
        highlights: List of highlight dicts (must have 'clip_path' from clip_cutter)
        stream_folder: Dropbox path of the per-stream folder (e.g. /VODs/2025-02-25 — Title — channel)

    Returns:
        Updated highlights with 'dropbox_path' and 'dropbox_link' fields
    """
    dbx = _get_client()

    # Clips go into a Highlights/ subfolder within the stream folder
    folder = f"{stream_folder}/Highlights"

    # Ensure Highlights folder exists
    try:
        dbx.files_get_metadata(folder)
    except ApiError:
        dbx.files_create_folder_v2(folder)
        print(f"[Dropbox] Created folder: {folder}")

    clips_to_upload = [h for h in highlights if h.get("clip_path")]
    print(f"[Dropbox] Uploading {len(clips_to_upload)} clips to: {folder}\n")

    for h in highlights:
        clip_path = h.get("clip_path")
        if not clip_path or not Path(clip_path).exists():
            print(f"  ⊘ {h.get('id', '?')}: No clip file, skipping")
            continue

        filename = h.get("clip_filename", Path(clip_path).name)
        dropbox_path = f"{folder}/{filename}"

        # Upload
        file_size = Path(clip_path).stat().st_size
        try:
            if file_size < CHUNK_SIZE:
                # Small file: single upload
                with open(clip_path, "rb") as f:
                    dbx.files_upload(
                        f.read(),
                        dropbox_path,
                        mode=WriteMode.overwrite,
                    )
            else:
                # Large file: chunked upload session
                _chunked_upload(dbx, clip_path, dropbox_path)

            size_mb = file_size / 1024 / 1024
            print(f"  ↑ {h.get('id', '?')}: {filename} ({size_mb:.1f}MB)")

            # Generate shared link
            try:
                link_meta = dbx.sharing_create_shared_link_with_settings(dropbox_path)
                shared_link = link_meta.url
            except ApiError as e:
                if "shared_link_already_exists" in str(e):
                    links = dbx.sharing_list_shared_links(path=dropbox_path).links
                    shared_link = links[0].url if links else ""
                else:
                    shared_link = ""
                    print(f"    ⚠ Could not create shared link: {e}")

            h["dropbox_path"] = dropbox_path
            h["dropbox_link"] = shared_link

        except Exception as e:
            print(f"  ✗ {h.get('id', '?')}: Upload failed — {e}")
            h["dropbox_path"] = None
            h["dropbox_link"] = None

    # Generate folder shared link (for the parent stream folder, not just Highlights)
    folder_link = ""
    try:
        link_meta = dbx.sharing_create_shared_link_with_settings(stream_folder)
        folder_link = link_meta.url
    except ApiError as e:
        if "shared_link_already_exists" in str(e):
            links = dbx.sharing_list_shared_links(path=stream_folder).links
            folder_link = links[0].url if links else ""

    # Note: highlights are returned with dropbox_path/dropbox_link fields
    # The caller is responsible for saving to the correct location

    uploaded = sum(1 for h in highlights if h.get("dropbox_path"))
    print(f"\n[Dropbox] Done: {uploaded}/{len(highlights)} clips uploaded")
    if folder_link:
        print(f"[Dropbox] Folder link: {folder_link}")

    return highlights, folder_link


def _chunked_upload(dbx: dropbox.Dropbox, local_path: str, dropbox_path: str, max_retries: int = 3):
    """Upload a large file using upload sessions with retry logic."""
    file_size = Path(local_path).stat().st_size

    with open(local_path, "rb") as f:
        # Start session
        for attempt in range(max_retries):
            try:
                data = f.read(CHUNK_SIZE)
                session = dbx.files_upload_session_start(data)
                break
            except Exception as e:
                print(f"    ⚠ Session start failed ({e}), retrying ({attempt+1}/{max_retries})...")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))
                f.seek(0)
                
        cursor = dropbox.files.UploadSessionCursor(
            session_id=session.session_id,
            offset=f.tell(),
        )
        commit = dropbox.files.CommitInfo(
            path=dropbox_path,
            mode=WriteMode.overwrite,
        )

        # Upload chunks
        while f.tell() < file_size:
            remaining = file_size - f.tell()
            chunk_size = min(remaining, CHUNK_SIZE)
            
            for attempt in range(max_retries):
                current_pos = f.tell()
                try:
                    data = f.read(chunk_size)
                    if remaining <= CHUNK_SIZE:
                        dbx.files_upload_session_finish(data, cursor, commit)
                    else:
                        dbx.files_upload_session_append_v2(data, cursor)
                        cursor.offset = f.tell()
                    break
                except Exception as e:
                    print(f"    ⚠ Chunk upload failed ({e}), retrying ({attempt+1}/{max_retries})...")
                    if attempt == max_retries - 1:
                        raise
                    time.sleep(2 * (attempt + 1))
                    f.seek(current_pos)


if __name__ == "__main__":
    import sys

    # Load highlights
    h_path = OUTPUT_DIR / "highlights.json"
    if not h_path.exists():
        print("No highlights.json found. Run pipeline.py first.")
        sys.exit(1)

    with open(h_path) as f:
        highlights = json.load(f)

    # Parse optional args
    date = None
    title = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--date" and i + 1 <= len(sys.argv) - 1:
            date = sys.argv[i + 1]
        elif arg == "--title" and i + 1 <= len(sys.argv) - 1:
            title = sys.argv[i + 1]

    # Build the per-stream Dropbox folder path from the provided args
    if date and title:
        stream_folder_name = f"{date} — {title} — {CHANNEL}"
    elif date:
        stream_folder_name = f"{date} — {CHANNEL}"
    else:
        stream_folder_name = CHANNEL
    stream_folder = f"{DROPBOX_VODS_FOLDER}/{stream_folder_name}"

    upload_clips(highlights, stream_folder=stream_folder)
