#!/usr/bin/env python3
"""
Auto-slice a pixel art sprite sheet into individual PNG files with transparency.

Dependencies (install via pip):
    pip install Pillow numpy scipy

Usage:
    python tools/slice_sprites.py [input_image_path] [--preview]

If no input path is given, defaults to a known location.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


# ── Default paths ──────────────────────────────────────────────────────────────

DEFAULT_INPUT = "/Users/m/Downloads/ChatGPT Image Mar 9, 2026, 02_03_27 AM.png"
DEFAULT_OUTPUT = "/Users/m/Work/code/poc/design2ui/frontend/public/sprites"

# ── Row definitions ────────────────────────────────────────────────────────────
# Each entry: (row_index, expected_count, output_subdir, filename_prefix, labels)

ROW_DEFS = [
    (0, 7, "tiles", "floor", [
        "floor_wood", "floor_carpet", "floor_checkerboard",
        "floor_dark_grid", "floor_marble", "floor_grass", "floor_concrete",
    ]),
    (1, 7, "tiles", "wall", [
        "wall_plain", "wall_window", "wall_whiteboard",
        "wall_monitor", "wall_doorway", "wall_inner_corner", "wall_outer_corner",
    ]),
    (2, 8, "furniture", "furniture", [
        "desk_monitor", "office_chair", "dev_desk", "dual_monitor_workstation",
        "whiteboard", "cork_board", "bookshelf", "filing_cabinet",
    ]),
    (3, 8, "furniture", "furniture", [
        "plant", "water_cooler", "coffee_machine", "trash_can",
        "rug", "server_rack", "test_bench", "shipping_crate",
    ]),
    (4, 8, "characters", "character", [
        "planner", "security", "mechanic", "artist",
        "inspector", "detective", "farmer", "scientist",
    ]),
    (5, None, "effects", "effect", [
        "sparkle", "error", "checkmark", "speech_bubble", "lightbulb",
        "folder", "gear", "heart", "star", "warning",
        "arrow", "cursor", "lock", "key", "coin",
    ]),
]


def detect_sprites(img_path: str, bg_threshold: int = 240):
    """Load image, find connected non-background regions, return sorted bounding boxes."""
    img = Image.open(img_path).convert("RGBA")
    arr = np.array(img)

    # Background mask: pixels where R, G, B are all above threshold
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # Also treat fully transparent pixels as background
    a = arr[:, :, 3]
    is_bg = ((r > bg_threshold) & (g > bg_threshold) & (b > bg_threshold)) | (a < 10)
    foreground = ~is_bg

    # Label connected components (8-connectivity)
    structure = np.ones((3, 3), dtype=int)
    labeled, num_features = ndimage.label(foreground, structure=structure)

    # Extract bounding boxes: (min_row, min_col, max_row, max_col)
    bboxes = []
    for i in range(1, num_features + 1):
        rows, cols = np.where(labeled == i)
        if len(rows) < 4:  # skip tiny noise (< 4 pixels)
            continue
        min_r, max_r = rows.min(), rows.max()
        min_c, max_c = cols.min(), cols.max()
        w = max_c - min_c + 1
        h = max_r - min_r + 1
        if w < 3 or h < 3:  # skip very thin slivers
            continue
        bboxes.append((min_r, min_c, max_r, max_c))

    # Sort by y then x
    bboxes.sort(key=lambda b: (b[0], b[1]))
    return img, arr, bboxes


def group_into_rows(bboxes, row_gap_ratio=0.3):
    """Group bounding boxes into rows based on vertical overlap / proximity."""
    if not bboxes:
        return []

    rows = []
    current_row = [bboxes[0]]
    # Use the vertical center of each bbox for grouping
    for bbox in bboxes[1:]:
        prev_mid = np.mean([b[0] + b[2] for b in current_row]) / 2
        curr_mid = (bbox[0] + bbox[2]) / 2
        # Estimate row height from current row members
        row_height = max(b[2] - b[0] for b in current_row)
        if row_height < 1:
            row_height = 1
        if abs(curr_mid - prev_mid) > row_height * row_gap_ratio:
            rows.append(current_row)
            current_row = [bbox]
        else:
            current_row.append(bbox)
    rows.append(current_row)

    # Sort sprites within each row by x position
    for row in rows:
        row.sort(key=lambda b: b[1])

    return rows


def merge_close_bboxes(bboxes, merge_distance=3):
    """Merge bounding boxes that are very close together (likely parts of same sprite)."""
    if not bboxes:
        return bboxes

    merged = True
    while merged:
        merged = False
        new_bboxes = []
        used = set()
        for i in range(len(bboxes)):
            if i in used:
                continue
            min_r, min_c, max_r, max_c = bboxes[i]
            for j in range(i + 1, len(bboxes)):
                if j in used:
                    continue
                jr, jc, jmr, jmc = bboxes[j]
                # Check if bboxes are close enough to merge
                vert_close = (min_r <= jmr + merge_distance) and (jr <= max_r + merge_distance)
                horiz_close = (min_c <= jmc + merge_distance) and (jc <= max_c + merge_distance)
                if vert_close and horiz_close:
                    min_r = min(min_r, jr)
                    min_c = min(min_c, jc)
                    max_r = max(max_r, jmr)
                    max_c = max(max_c, jmc)
                    used.add(j)
                    merged = True
            new_bboxes.append((min_r, min_c, max_r, max_c))
            used.add(i)
        bboxes = new_bboxes
        bboxes.sort(key=lambda b: (b[0], b[1]))

    return bboxes


def extract_sprite(arr, bbox, bg_threshold=240, padding=1):
    """Extract a sprite from the image array, converting white-ish bg to transparent."""
    min_r, min_c, max_r, max_c = bbox
    # Add a tiny padding to avoid clipping
    h, w = arr.shape[:2]
    min_r = max(0, min_r - padding)
    min_c = max(0, min_c - padding)
    max_r = min(h - 1, max_r + padding)
    max_c = min(w - 1, max_c + padding)

    crop = arr[min_r:max_r + 1, min_c:max_c + 1].copy()

    # Convert near-white pixels to transparent
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    is_bg = (r > bg_threshold) & (g > bg_threshold) & (b > bg_threshold)
    crop[is_bg, 3] = 0  # set alpha to 0 for background pixels

    return Image.fromarray(crop, "RGBA")


def preview(rows):
    """Print detected bounding boxes and row assignments."""
    print(f"Detected {sum(len(r) for r in rows)} sprites in {len(rows)} rows:\n")
    for i, row in enumerate(rows):
        print(f"Row {i + 1}: {len(row)} sprites")
        for j, bbox in enumerate(row):
            min_r, min_c, max_r, max_c = bbox
            w = max_c - min_c + 1
            h = max_r - min_r + 1
            print(f"  [{j + 1}] y={min_r}-{max_r} x={min_c}-{max_c}  ({w}x{h}px)")
        print()


def save_sprites(img, arr, rows, output_dir):
    """Extract and save each sprite, plus generate manifest.json."""
    output_dir = Path(output_dir)
    manifest = {}

    for row_idx, row_bboxes in enumerate(rows):
        if row_idx >= len(ROW_DEFS):
            # Extra rows beyond what we defined -- save as extras
            subdir = "extras"
            prefix = "extra"
            labels = [f"extra_{j + 1}" for j in range(len(row_bboxes))]
            category = "extras"
        else:
            _, expected, subdir, prefix, labels = ROW_DEFS[row_idx]

        category = subdir
        if category not in manifest:
            manifest[category] = {}

        dir_path = output_dir / subdir
        dir_path.mkdir(parents=True, exist_ok=True)

        # For furniture rows 2 and 3 (row_idx 2 and 3), offset the numbering
        num_offset = 0
        if row_idx == 3:  # second furniture row
            num_offset = 8

        for j, bbox in enumerate(row_bboxes):
            sprite_img = extract_sprite(arr, bbox)
            num = j + 1 + num_offset
            filename = f"{prefix}_{num}.png"
            rel_path = f"{subdir}/{filename}"
            filepath = dir_path / filename
            sprite_img.save(filepath, "PNG")

            # Determine label
            if j < len(labels):
                label = labels[j]
            else:
                label = f"{prefix}_{num}"

            manifest[category][label] = rel_path
            print(f"  Saved {rel_path} ({sprite_img.size[0]}x{sprite_img.size[1]}px)")

    # Write manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest written to {manifest_path}")

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Slice a sprite sheet into individual PNGs")
    parser.add_argument("input", nargs="?", default=DEFAULT_INPUT,
                        help="Path to the sprite sheet image")
    parser.add_argument("--output", "-o", default=DEFAULT_OUTPUT,
                        help="Output directory for sprites")
    parser.add_argument("--preview", action="store_true",
                        help="Only print detected bounding boxes, don't save")
    parser.add_argument("--threshold", "-t", type=int, default=240,
                        help="Background brightness threshold (0-255, default 240)")
    parser.add_argument("--merge-distance", "-m", type=int, default=3,
                        help="Max pixel gap to merge adjacent components (default 3)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {args.input}")
    img, arr, bboxes = detect_sprites(args.input, bg_threshold=args.threshold)
    print(f"Image size: {img.size[0]}x{img.size[1]}")
    print(f"Found {len(bboxes)} raw components")

    # Merge nearby components (parts of the same sprite)
    bboxes = merge_close_bboxes(bboxes, merge_distance=args.merge_distance)
    print(f"After merging: {len(bboxes)} sprites")

    # Group into rows
    rows = group_into_rows(bboxes)

    if args.preview:
        preview(rows)
        return

    print(f"\nSaving sprites to: {args.output}\n")
    save_sprites(img, arr, rows, args.output)
    print("\nDone!")


if __name__ == "__main__":
    main()
