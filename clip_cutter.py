"""
Phase 2a: Cut video clips from highlights.json using FFmpeg.

Reads highlights.json and cuts each clip from the original VOD file.
Uses -c copy for speed (stream copy, no re-encoding).
"""
import json
import re
import subprocess
from pathlib import Path
from config import OUTPUT_DIR, CLIPS_DIR, CHANNEL


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Remove special characters and truncate for safe filenames."""
    # Remove characters that are problematic in filenames
    clean = re.sub(r'[<>:"/\\|?*\'\n\r]', '', name)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:max_length]


def cut_clips(
    video_path: str,
    highlights_path: str = None,
    output_dir: str = None,
    stream_title: str = None,
    stream_date: str = None,
    channel: str = CHANNEL,
) -> list[dict]:
    """
    Cut individual clips from a VOD file based on highlights.json.

    Args:
        video_path: Path to the source VOD file
        highlights_path: Path to highlights.json (default: output/highlights.json)
        output_dir: Override output directory for clips
        stream_title: Title of the stream (used in folder naming)
        stream_date: Date string YYYY-MM-DD (used in folder naming)
        channel: Channel name (default: CHANNEL env var)

    Returns:
        List of highlight dicts with added 'clip_path' field
    """
    # Load highlights
    h_path = highlights_path or str(OUTPUT_DIR / "highlights.json")
    with open(h_path) as f:
        highlights = json.load(f)

    if not highlights:
        print("[Clipper] No highlights to cut.")
        return []

    # Build output folder: /clips/YYYY-MM-DD — Stream Title — Channel/
    if stream_date and stream_title:
        folder_name = sanitize_filename(f"{stream_date} — {stream_title} — {channel}")
    elif stream_date:
        folder_name = f"{stream_date} — {channel}"
    else:
        folder_name = channel

    clip_dir = Path(output_dir) if output_dir else CLIPS_DIR / folder_name
    clip_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Clipper] Cutting {len(highlights)} clips from: {Path(video_path).name}")
    print(f"[Clipper] Output folder: {clip_dir}\n")

    results = []
    for h in highlights:
        clip_id = h.get("id", "C0")
        tldr = h.get("tldr", "clip")
        start = h.get("start", 0)
        end = h.get("end", 0)
        duration = end - start

        # Build filename: C1 — TLDR text.mp4
        safe_tldr = sanitize_filename(tldr)
        filename = f"{clip_id} — {safe_tldr}.mp4"
        clip_path = clip_dir / filename

        # FFmpeg command: stream copy (fast, no re-encoding)
        # -ss before -i for fast seeking, -t for duration
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(video_path),
            "-t", str(duration),
            "-c", "copy",          # Stream copy — instant, no quality loss
            "-avoid_negative_ts", "make_zero",
            str(clip_path)
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True)
            size_mb = clip_path.stat().st_size / 1024 / 1024
            print(f"  ✓ {clip_id}: {filename} ({duration:.0f}s, {size_mb:.1f}MB)")
            h["clip_path"] = str(clip_path)
            h["clip_filename"] = filename
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {clip_id}: FFmpeg error — {e.stderr[:200] if e.stderr else 'unknown'}")
            h["clip_path"] = None
            h["clip_filename"] = None

        results.append(h)

    # Save updated highlights with clip paths
    with open(h_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    successful = sum(1 for r in results if r.get("clip_path"))
    print(f"\n[Clipper] Done: {successful}/{len(results)} clips cut successfully")
    print(f"[Clipper] Clips saved to: {clip_dir}")

    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python clip_cutter.py <path_to_vod.mp4> [--date YYYY-MM-DD] [--title 'Stream Title']")
        sys.exit(1)

    video = sys.argv[1]
    date = None
    title = None

    # Parse optional args
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == "--date" and i + 1 < len(sys.argv):
            date = sys.argv[i + 1]
        elif arg == "--title" and i + 1 < len(sys.argv):
            title = sys.argv[i + 1]

    cut_clips(video, stream_date=date, stream_title=title)
