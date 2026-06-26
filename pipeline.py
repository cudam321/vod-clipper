"""
VOD Clipper Pipeline — Main Runner

Usage:
    python pipeline.py <path_to_vod.mp4>

Runs the full Phase 1 highlight detection pipeline:
  1. Extract audio from VOD (FFmpeg)
  2. Transcribe audio (Whisper API)
  3. Analyze transcript for clip-worthy moments (GPT-4o)
  4. Detect scene changes (FFmpeg)
  5. Merge signals → final highlights.json
"""
import sys
import json
import time
from pathlib import Path

from config import OUTPUT_DIR, CHUNK_DURATION_MIN
from ffmpeg_extract import extract_audio, chunk_audio, detect_scene_changes
from transcribe import transcribe_chunked
from analyze import analyze_transcript
from merge_highlights import merge_highlights


def run_pipeline(video_path: str) -> list[dict]:
    """Run the full Phase 1 pipeline on a VOD file."""
    video_path = Path(video_path)
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)

    # Per-video output directory (based on filename, no extension)
    video_name = video_path.stem
    run_dir = OUTPUT_DIR / video_name.replace(" ", "_")
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"VOD CLIPPER — Phase 1 Pipeline")
    print(f"Input: {video_path}")
    print(f"Output: {run_dir}/")
    print(f"{'='*60}\n")

    start_time = time.time()

    # --- Step 1-3: Transcribe (cached) ---
    transcript_path = run_dir / "transcript.json"
    if transcript_path.exists():
        print("▸ STEP 1-3: Loading cached transcript...")
        with open(transcript_path) as f:
            transcript = json.load(f)
        print(f"  ✓ Cached ({len(transcript['segments'])} segments)\n")
    else:
        print("▸ STEP 1/5: Extracting audio...")
        audio_path = extract_audio(str(video_path), output_dir=str(run_dir))
        step1_time = time.time()
        print(f"  ✓ Done ({step1_time - start_time:.1f}s)\n")

        print("▸ STEP 2/5: Chunking audio for Whisper...")
        chunks = chunk_audio(audio_path, chunk_minutes=CHUNK_DURATION_MIN)
        print(f"  ✓ {len(chunks)} chunk(s)\n")

        print("▸ STEP 3/5: Transcribing via Whisper API...")
        transcript = transcribe_chunked(chunks, chunk_duration_sec=CHUNK_DURATION_MIN * 60)
        # Save transcript to per-video dir
        with open(transcript_path, "w") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Done — {len(transcript['segments'])} segments\n")

    # --- Step 4: Scene detection (cached) ---
    scene_path = run_dir / "scene_changes.json"
    if scene_path.exists():
        print("▸ STEP 4: Loading cached scene changes...")
        with open(scene_path) as f:
            scenes = json.load(f)
        print(f"  ✓ Cached ({len(scenes)} scene changes)\n")
    else:
        print("▸ STEP 4/5: Detecting scene changes...")
        scenes = detect_scene_changes(str(video_path))
        with open(scene_path, "w") as f:
            json.dump(scenes, f, indent=2)
        print(f"  ✓ Done — {len(scenes)} scene changes\n")

    # --- Step 5: Analyze with GPT-4o ---
    print("▸ STEP 5/5: Analyzing transcript...")
    raw_highlights = analyze_transcript(transcript)
    raw_output = run_dir / "raw_highlights.json"
    with open(raw_output, "w") as f:
        json.dump(raw_highlights, f, indent=2, ensure_ascii=False)
    step5_time = time.time()
    print(f"  ✓ Done ({step5_time - start_time:.1f}s) — {len(raw_highlights)} raw highlights\n")

    # --- Merge & Score ---
    print("▸ FINAL: Merging signals & scoring...")
    highlights = merge_highlights(raw_highlights, scenes)

    # Assign IDs and format
    for i, clip in enumerate(highlights, 1):
        clip["id"] = f"C{i}"
        clip["timeframe"] = f"{clip['start_fmt']} - {clip['end_fmt']}"

    output_path = run_dir / "highlights.json"
    with open(output_path, "w") as f:
        json.dump(highlights, f, indent=2, ensure_ascii=False)

    total_time = time.time() - start_time

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"Total time:    {total_time:.1f}s")
    print(f"Clips found:   {len(highlights)}")
    print(f"Output:        {output_path}")
    print(f"\nHighlights:")
    print(f"{'ID':<6} {'Timeframe':<25} {'Category':<15} {'Conf':<6} {'TLDR'}")
    print("-" * 90)
    for h in highlights:
        tldr = h['tldr'][:40] + "..." if len(h.get('tldr', '')) > 40 else h.get('tldr', '')
        print(f"{h['id']:<6} {h['timeframe']:<25} {h['category']:<15} {h['confidence']:<6} {tldr}")

    return highlights, str(run_dir)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <path_to_vod.mp4>")
        print("\nThis runs the full Phase 1 highlight detection pipeline.")
        print("Make sure you have set OPENAI_API_KEY in your .env file.")
        sys.exit(1)

    run_pipeline(sys.argv[1])
