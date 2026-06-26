"""
Step 1: Extract audio from VOD using FFmpeg.
Step 1b: Detect scene changes using FFmpeg scene filter.

Handles chunking for long VODs (>30 min segments for Whisper API limits).
"""
import subprocess
import json
import math
from pathlib import Path
from config import OUTPUT_DIR, SCENE_THRESHOLD, CHUNK_DURATION_MIN


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def extract_audio(video_path: str, output_path: str = None, output_dir: str = None) -> str:
    """
    Extract audio from video as MP3 (64kbps mono — ~0.5MB/min, well under Whisper's 25MB limit).
    Returns path to the extracted audio file.
    """
    if output_path is None:
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        output_path = str(out_dir / "audio_full.mp3")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",                    # No video
        "-acodec", "libmp3lame",  # MP3 codec
        "-ar", "16000",           # 16kHz sample rate (Whisper optimal)
        "-ac", "1",               # Mono
        "-b:a", "64k",            # 64kbps — good enough for speech, keeps size small
        str(output_path)
    ]
    print(f"[FFmpeg] Extracting audio → {output_path}")
    subprocess.run(cmd, capture_output=True, check=True)
    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"[FFmpeg] Audio extracted: {size_mb:.1f} MB")
    return output_path


def chunk_audio(audio_path: str, chunk_minutes: int = CHUNK_DURATION_MIN) -> list[str]:
    """
    Split audio into chunks for Whisper API (25 MB file size limit).
    MP3 @ 64kbps = ~0.5MB/min, so 30-min chunks = ~15MB — safe margin.
    Returns list of chunk file paths.
    """
    duration = get_video_duration(audio_path)
    chunk_seconds = chunk_minutes * 60
    num_chunks = math.ceil(duration / chunk_seconds)

    # Use the same directory as the audio file
    audio_dir = Path(audio_path).parent

    if num_chunks <= 1:
        size_mb = Path(audio_path).stat().st_size / 1024 / 1024
        if size_mb < 24:
            return [audio_path]

    chunks = []
    for i in range(num_chunks):
        start = i * chunk_seconds
        chunk_path = str(audio_dir / f"audio_chunk_{i:03d}.mp3")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(audio_path),
            "-ss", str(start),
            "-t", str(chunk_seconds),
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            "-b:a", "64k",
            chunk_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        size_mb = Path(chunk_path).stat().st_size / 1024 / 1024
        chunks.append(chunk_path)
        print(f"[FFmpeg] Chunk {i+1}/{num_chunks}: {Path(chunk_path).name} ({size_mb:.1f} MB)")

    return chunks


def detect_scene_changes(video_path: str, threshold: float = SCENE_THRESHOLD) -> list[dict]:
    """
    Detect scene changes using FFmpeg's scene filter.
    Returns list of timestamps where visual intensity spikes occur.
    """
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vf", f"fps=10,scale=320:240,select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr",
        "-f", "null", "-"
    ]
    print(f"[FFmpeg] Detecting scene changes (threshold={threshold})...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse showinfo output for timestamps
    scenes = []
    for line in result.stderr.split("\n"):
        if "showinfo" in line and "pts_time:" in line:
            try:
                pts_part = line.split("pts_time:")[1].split()[0]
                timestamp = float(pts_part)
                scenes.append({
                    "timestamp_sec": timestamp,
                    "timestamp_fmt": format_timestamp(timestamp)
                })
            except (IndexError, ValueError):
                continue

    print(f"[FFmpeg] Found {len(scenes)} scene changes")
    return scenes


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ffmpeg_extract.py <video_path>")
        sys.exit(1)

    video_path = sys.argv[1]
    print(f"\n=== Processing: {video_path} ===")

    # Extract audio
    audio = extract_audio(video_path)

    # Chunk if needed
    chunks = chunk_audio(audio)
    print(f"\nAudio chunks: {len(chunks)}")

    # Detect scenes
    scenes = detect_scene_changes(video_path)
    scene_output = OUTPUT_DIR / "scene_changes.json"
    with open(scene_output, "w") as f:
        json.dump(scenes, f, indent=2)
    print(f"Scene changes saved to: {scene_output}")
