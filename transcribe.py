"""
Step 2: Transcribe audio using OpenAI Whisper API.

Produces word-level timestamps from audio chunks.
"""
import json
from pathlib import Path
from openai import OpenAI
from config import OPENAI_API_KEY, WHISPER_MODEL, OUTPUT_DIR

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def transcribe_audio(audio_path: str, chunk_offset_sec: float = 0.0) -> dict:
    """
    Transcribe a single audio file using Whisper API.
    Returns segments with adjusted timestamps (accounting for chunk offset).
    """
    print(f"[Whisper] Transcribing: {Path(audio_path).name} (offset: {chunk_offset_sec}s)")

    with open(audio_path, "rb") as f:
        response = _get_client().audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"]
        )

    # Adjust timestamps for chunk offset
    segments = []
    for seg in (response.segments or []):
        segments.append({
            "start": round(seg.start + chunk_offset_sec, 2),
            "end": round(seg.end + chunk_offset_sec, 2),
            "text": seg.text.strip(),
        })

    words = []
    for w in (response.words or []):
        words.append({
            "word": w.word.strip(),
            "start": round(w.start + chunk_offset_sec, 2),
            "end": round(w.end + chunk_offset_sec, 2),
        })

    return {
        "full_text": response.text,
        "segments": segments,
        "words": words,
    }


def transcribe_chunked(audio_chunks: list[str], chunk_duration_sec: float = 1800.0) -> dict:
    """
    Transcribe multiple audio chunks and merge results.
    Handles offset adjustment so timestamps are relative to the full VOD.
    """
    all_segments = []
    all_words = []
    full_text_parts = []

    for i, chunk_path in enumerate(audio_chunks):
        offset = i * chunk_duration_sec
        result = transcribe_audio(chunk_path, chunk_offset_sec=offset)
        all_segments.extend(result["segments"])
        all_words.extend(result["words"])
        full_text_parts.append(result["full_text"])
        print(f"[Whisper] Chunk {i+1}/{len(audio_chunks)} done — {len(result['segments'])} segments")

    merged = {
        "full_text": " ".join(full_text_parts),
        "segments": all_segments,
        "words": all_words,
    }

    # Save transcript
    output_path = OUTPUT_DIR / "transcript.json"
    with open(output_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"[Whisper] Full transcript saved: {output_path} ({len(all_segments)} segments, {len(all_words)} words)")

    return merged


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <audio_file_or_chunk_1> [chunk_2] ...")
        sys.exit(1)

    chunks = sys.argv[1:]
    result = transcribe_chunked(chunks)
    print(f"\nTranscript preview (first 500 chars):\n{result['full_text'][:500]}...")
