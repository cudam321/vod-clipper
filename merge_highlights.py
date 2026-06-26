"""
Step 4: Merge signals from transcript analysis + scene detection into final highlights.

Combines GPT-4o highlights with FFmpeg scene changes to produce
a scored, deduplicated, and formatted highlights.json.
"""
import json
from config import (
    OUTPUT_DIR,
    MIN_CLIP_DURATION_SEC,
    MAX_CLIP_DURATION_SEC,
    MIN_CONFIDENCE,
)


def merge_highlights(
    raw_highlights: list[dict],
    scene_changes: list[dict],
    scene_boost: float = 0.05,
    proximity_gap_sec: float = 30.0,
) -> list[dict]:
    """
    Merge AI-detected highlights with scene change data.
    
    Strategy: The AI returns precise short moments (5-20s). We group nearby
    moments into full clips (30-180s) that a video editor can cut.
    
    Steps:
    1. Sort all highlights by start time
    2. Group highlights within proximity_gap_sec of each other
    3. Boost confidence for groups near scene changes
    4. Filter by confidence threshold
    5. Deduplicate overlapping clips
    """
    if not raw_highlights:
        return []

    # Build scene change lookup
    scene_times = [s["timestamp_sec"] for s in scene_changes]

    # Sort by start time
    sorted_h = sorted(raw_highlights, key=lambda x: float(x.get("start", 0)))

    # --- Step 1: Group nearby highlights into clips ---
    groups = []
    current_group = [sorted_h[0]]

    for h in sorted_h[1:]:
        prev_end = float(current_group[-1].get("end", 0))
        curr_start = float(h.get("start", 0))

        # If this highlight is close to the previous group, merge it in
        if curr_start - prev_end <= proximity_gap_sec:
            current_group.append(h)
        else:
            groups.append(current_group)
            current_group = [h]

    groups.append(current_group)  # Don't forget the last group

    # --- Step 2: Convert groups into clips ---
    clips = []
    for group in groups:
        start = float(group[0].get("start", 0))
        end = max(float(h.get("end", 0)) for h in group)
        duration = end - start

        # Skip clips still too short after grouping
        if duration < MIN_CLIP_DURATION_SEC:
            continue

        # Cap at MAX_CLIP_DURATION
        if duration > MAX_CLIP_DURATION_SEC:
            end = start + MAX_CLIP_DURATION_SEC
            duration = MAX_CLIP_DURATION_SEC

        # Pick best TLDR (highest confidence moment in the group)
        best = max(group, key=lambda h: float(h.get("confidence", 0)))
        avg_confidence = sum(float(h.get("confidence", 0)) for h in group) / len(group)

        # Collect all categories
        categories = [h.get("category", "unknown") for h in group]
        primary_category = max(set(categories), key=categories.count)

        # Boost: scene change near the clip
        has_scene_change = any(
            abs(st - start) < 5 or abs(st - end) < 5
            for st in scene_times
        )
        if has_scene_change:
            avg_confidence = min(1.0, avg_confidence + scene_boost)

        # Filter: minimum confidence
        if avg_confidence < MIN_CONFIDENCE:
            continue

        # Build clip descriptor
        tldrs = [h.get("tldr", "") for h in group if h.get("tldr")]
        if len(tldrs) > 1:
            tldr = f"{best.get('tldr', '')} + {len(group)-1} more moments"
        else:
            tldr = best.get("tldr", "")

        clips.append({
            "start": start,
            "end": end,
            "start_fmt": format_timestamp(start),
            "end_fmt": format_timestamp(end),
            "duration_sec": round(duration, 1),
            "category": primary_category,
            "confidence": round(avg_confidence, 3),
            "tldr": tldr,
            "moment_count": len(group),
        })

    # Sort by start time
    clips.sort(key=lambda x: x["start"])

    # Deduplicate overlapping clips
    deduped = deduplicate(clips)

    # Assign sequential clip IDs
    for i, clip in enumerate(deduped, 1):
        clip["id"] = f"C{i}"
        clip["timeframe"] = f"{clip['start_fmt']} - {clip['end_fmt']}"

    return deduped


def deduplicate(highlights: list[dict], overlap_threshold: float = 0.5) -> list[dict]:
    """
    Remove overlapping highlights, keeping the one with higher confidence.
    Two clips overlap if >50% of the shorter one is within the longer one.
    """
    if not highlights:
        return []

    result = [highlights[0]]
    for current in highlights[1:]:
        prev = result[-1]
        overlap_start = max(prev["start"], current["start"])
        overlap_end = min(prev["end"], current["end"])
        overlap_duration = max(0, overlap_end - overlap_start)

        shorter_duration = min(prev["duration_sec"], current["duration_sec"])
        if shorter_duration > 0 and (overlap_duration / shorter_duration) > overlap_threshold:
            # Overlapping — keep higher confidence
            if current["confidence"] > prev["confidence"]:
                result[-1] = current
        else:
            result.append(current)

    return result


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_highlights(raw_highlights_path: str = None, scene_changes_path: str = None) -> list[dict]:
    """
    Main entry point: load raw data, merge, and save final highlights.json.
    """
    # Load raw highlights
    rh_path = raw_highlights_path or (OUTPUT_DIR / "raw_highlights.json")
    with open(rh_path) as f:
        raw_highlights = json.load(f)

    # Load scene changes (optional — may not exist for audio-only analysis)
    scenes = []
    sc_path = scene_changes_path or (OUTPUT_DIR / "scene_changes.json")
    if sc_path and sc_path.exists() if hasattr(sc_path, 'exists') else False:
        try:
            with open(sc_path) as f:
                scenes = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            print("[Merge] No scene changes found, proceeding without visual signal")

    # Merge and score
    highlights = merge_highlights(raw_highlights, scenes)

    # Save
    output_path = OUTPUT_DIR / "highlights.json"
    with open(output_path, "w") as f:
        json.dump(highlights, f, indent=2, ensure_ascii=False)

    print(f"[Merge] Final highlights: {len(highlights)} clips")
    print(f"[Merge] Saved to: {output_path}")

    # Print summary
    print(f"\n{'ID':<6} {'Timeframe':<25} {'Category':<15} {'Conf':<6} {'TLDR'}")
    print("-" * 90)
    for h in highlights:
        print(f"{h['id']:<6} {h['timeframe']:<25} {h['category']:<15} {h['confidence']:<6} {h['tldr'][:40]}")

    return highlights


if __name__ == "__main__":
    build_highlights()
