"""
Step 3: Analyze transcript with GPT-4o to identify clip-worthy moments.

Sends transcript segments in batches to GPT-4o and extracts highlights
with categories, confidence scores, and TLDRs.
"""
import json
from openai import OpenAI
from config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, ANALYSIS_MODEL, ANALYSIS_TEMPERATURE,
    OUTPUT_DIR, CREATOR_CONTEXT, CATEGORIES,
)

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
    return _client

def _build_system_prompt() -> str:
    """Build the analyst system prompt from the configured creator context + categories."""
    categories_str = ", ".join(f'"{c}"' for c in CATEGORIES)
    return f"""You are an expert content analyst identifying clip-worthy moments from a creator's stream or long-form video for short-form content distribution.

ABOUT THE CREATOR / CONTEXT:
{CREATOR_CONTEXT}

DEPRIORITIZE: Small talk, greetings, logistics, filler conversation, off-topic chatter.

INPUT FORMAT:
Each line is a transcript segment: [START_SECONDS - END_SECONDS] spoken text
The numbers are timestamps in SECONDS from the start of the stream.

YOUR TASK:
Identify the best 15-25 moments worth cutting as standalone clips.

OUTPUT FORMAT — return a JSON object with key "highlights" containing an array:
- "start": number — start time IN SECONDS (must match input timestamps)
- "end": number — end time IN SECONDS (must match input timestamps)
- "category": one of [{categories_str}]
- "confidence": 0.0 to 1.0
- "tldr": short punchy clip title (what would make a viewer click)

CRITICAL RULES:
1. TIMESTAMPS MUST BE IN SECONDS matching the input. If a segment says [847.5 - 860.0], use start=847.5 and end=860.0.
2. Each clip MUST be 30 to 180 seconds long. Group multiple adjacent transcript lines into one clip.
3. DO NOT return individual sentences or sub-second moments. Each highlight is a FULL CLIP a video editor will cut out.
4. Prioritize the creator's most engaging, on-topic, and shareable moments.
5. Quality > quantity. Only return genuinely clip-worthy segments."""


SYSTEM_PROMPT = _build_system_prompt()


def analyze_transcript(transcript: dict, batch_size_segments: int = 100) -> list[dict]:
    """
    Send transcript segments to GPT-4o for highlight analysis.
    Processes in batches to stay within token limits.
    """
    segments = transcript["segments"]
    all_highlights = []

    # Process in larger batches for better context
    for i in range(0, len(segments), batch_size_segments):
        batch = segments[i:i + batch_size_segments]
        batch_text = format_segments_for_prompt(batch)

        batch_start = batch[0]["start"]
        batch_end = batch[-1]["end"]
        print(f"[Analysis] Analyzing segments {i+1}-{i+len(batch)} "
              f"({batch_start:.0f}s → {batch_end:.0f}s)")

        response = _get_client().chat.completions.create(
            model=ANALYSIS_MODEL,
            temperature=ANALYSIS_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this transcript and find clip-worthy moments. Remember: timestamps are in SECONDS, and each clip must be 30-180 seconds long.\n\n{batch_text}"}
            ]
        )

        try:
            result = json.loads(response.choices[0].message.content)
            highlights = result.get("highlights", result) if isinstance(result, dict) else result
            if isinstance(highlights, list):
                all_highlights.extend(highlights)
                print(f"[Analysis] Found {len(highlights)} highlights in this batch")
            else:
                print(f"[Analysis] Unexpected response format, skipping batch")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[Analysis] Failed to parse response for batch {i}: {e}")
            continue

    print(f"[Analysis] Total highlights found: {len(all_highlights)}")
    return all_highlights


def format_segments_for_prompt(segments: list[dict]) -> str:
    """Format transcript segments with raw second timestamps (avoids unit confusion)."""
    lines = []
    for seg in segments:
        lines.append(f"[{seg['start']:.1f} - {seg['end']:.1f}] {seg['text']}")
    return "\n".join(lines)


def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


if __name__ == "__main__":
    # Test with existing transcript
    transcript_path = OUTPUT_DIR / "transcript.json"
    if not transcript_path.exists():
        print("No transcript found. Run transcribe.py first.")
        exit(1)

    with open(transcript_path) as f:
        transcript = json.load(f)

    highlights = analyze_transcript(transcript)

    output_path = OUTPUT_DIR / "raw_highlights.json"
    with open(output_path, "w") as f:
        json.dump(highlights, f, indent=2, ensure_ascii=False)
    print(f"\nRaw highlights saved to: {output_path}")
