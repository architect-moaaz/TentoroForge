#!/usr/bin/env python3
"""
Slice all three character sprite sheets:
  1. Idle poses (24 agents standing)
  2. Walk cycles (8 frames per character)
  3. Working-at-desk poses (24 agents at desks)

Dependencies: pip install Pillow numpy scipy
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


OUTPUT_DIR = Path("/Users/m/Work/code/poc/design2ui/frontend/public/sprites")

# All 24 agent names in order they appear in the sprite sheets
AGENT_NAMES = [
    # Row 1 (image 1)
    "discovery",        # explorer with magnifying glass
    "contract_writer",  # lawyer with briefcase
    "api_generator",    # mechanic with wrench
    "schema_designer",  # engineer with clipboard
    "seed_generator",   # farmer with seed bag
    "page_assembler",   # blue hat, color palette
    "ui_styler",        # pink, color swatches
    "figma_importer",   # purple, camera/phone
    # Row 2 (image 1)
    "qa_tester",        # yellow hard hat, QA badge
    "validator",        # robot/android
    "navigator",        # green, compass
    "data_modeler",     # green hat, tools
    "export_agent",     # brown, wrench
    "rules_writer",     # purple judge
    "chat_refiner",     # brown, clipboard
    "portal_builder",   # teal, hologram
    # Row 3 (image 1)
    "bizlogic_agent",   # dark, calculator
    "agent_builder",    # pink/magenta
    "workflow_agent",   # brown, clipboard
    "planner",          # gray hat, clipboard
    "auth_agent",       # blue, tools
    "component_builder",# portal frame
    "indexer",          # brown, box
    # last may be missing from row 3
]

# Walking sprite sheet agent order (matches color pattern)
WALK_AGENTS = [
    "planner", "security", "api_generator", "schema_designer",
    "inspector", "auth_agent", "seed_generator", "page_assembler",
    "qa_tester", "validator", "component_builder", "ui_styler",
    "figma_importer", "contract_writer", "navigator", "detective",
]

# Working at desk agent order (by color: blue, red, orange, pink, cyan, lightblue, brown)
DESK_AGENTS_ROW1 = ["planner", "security", "api_generator", "artist", "inspector", "page_assembler", "detective"]
DESK_AGENTS_ROW2 = ["contract_writer", "auth_agent", "schema_designer", "seed_generator", "component_builder", "navigator", "figma_importer"]
DESK_AGENTS_ROW3 = ["validator", "qa_tester", "export_agent", "data_modeler", "workflow_agent", "portal_builder", "rules_writer"]
DESK_AGENTS_ROW4 = ["bizlogic_agent", "agent_builder", "chat_refiner", "indexer", "ui_styler", "discovery", "appmodel_manager"]


def detect_sprites(img_path, bg_threshold=240, merge_distance=3):
    """Load image, detect connected non-background components, return (img, arr, rows)."""
    img = Image.open(img_path).convert("RGBA")
    arr = np.array(img)

    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    is_bg = ((r > bg_threshold) & (g > bg_threshold) & (b > bg_threshold)) | (a < 10)
    foreground = ~is_bg

    structure = np.ones((3, 3), dtype=int)
    labeled, num_features = ndimage.label(foreground, structure=structure)

    bboxes = []
    for i in range(1, num_features + 1):
        rows_px, cols_px = np.where(labeled == i)
        if len(rows_px) < 4:
            continue
        min_r, max_r = rows_px.min(), rows_px.max()
        min_c, max_c = cols_px.min(), cols_px.max()
        if (max_c - min_c + 1) < 3 or (max_r - min_r + 1) < 3:
            continue
        bboxes.append((min_r, min_c, max_r, max_c))

    bboxes.sort(key=lambda b: (b[0], b[1]))

    # Merge close bboxes
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
                vert_close = (min_r <= jmr + merge_distance) and (jr <= max_r + merge_distance)
                horiz_close = (min_c <= jmc + merge_distance) and (jc <= max_c + merge_distance)
                if vert_close and horiz_close:
                    min_r, min_c = min(min_r, jr), min(min_c, jc)
                    max_r, max_c = max(max_r, jmr), max(max_c, jmc)
                    used.add(j)
                    merged = True
            new_bboxes.append((min_r, min_c, max_r, max_c))
            used.add(i)
        bboxes = new_bboxes
        bboxes.sort(key=lambda b: (b[0], b[1]))

    # Group into rows
    rows = []
    if bboxes:
        current_row = [bboxes[0]]
        for bbox in bboxes[1:]:
            prev_mid = np.mean([b[0] + b[2] for b in current_row]) / 2
            curr_mid = (bbox[0] + bbox[2]) / 2
            row_height = max(b[2] - b[0] for b in current_row)
            if abs(curr_mid - prev_mid) > row_height * 0.3:
                rows.append(current_row)
                current_row = [bbox]
            else:
                current_row.append(bbox)
        rows.append(current_row)
        for row in rows:
            row.sort(key=lambda b: b[1])

    return img, arr, rows


def extract_sprite(arr, bbox, bg_threshold=240, padding=1):
    """Extract sprite with transparent background."""
    min_r, min_c, max_r, max_c = bbox
    h, w = arr.shape[:2]
    min_r = max(0, min_r - padding)
    min_c = max(0, min_c - padding)
    max_r = min(h - 1, max_r + padding)
    max_c = min(w - 1, max_c + padding)

    crop = arr[min_r:max_r + 1, min_c:max_c + 1].copy()
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    is_bg = (r > bg_threshold) & (g > bg_threshold) & (b > bg_threshold)
    crop[is_bg, 3] = 0
    return Image.fromarray(crop, "RGBA")


def slice_idle_poses(img_path):
    """Slice the 24 agent idle pose sheet."""
    print(f"\n=== Slicing idle poses: {img_path} ===")
    img, arr, rows = detect_sprites(img_path)

    out_dir = OUTPUT_DIR / "characters" / "idle"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_sprites = []
    for row in rows:
        all_sprites.extend(row)

    manifest = {}
    for i, bbox in enumerate(all_sprites):
        name = AGENT_NAMES[i] if i < len(AGENT_NAMES) else f"agent_{i+1}"
        sprite = extract_sprite(arr, bbox)
        filepath = out_dir / f"{name}.png"
        sprite.save(filepath, "PNG")
        manifest[name] = f"characters/idle/{name}.png"
        print(f"  Saved {name}.png ({sprite.size[0]}x{sprite.size[1]}px)")

    return manifest


def slice_walk_cycles(img_path):
    """Slice the walk cycle sprite sheet into per-character sprite sheets."""
    print(f"\n=== Slicing walk cycles: {img_path} ===")
    img, arr, rows = detect_sprites(img_path)

    out_dir = OUTPUT_DIR / "characters" / "walk"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Detected {len(rows)} rows, {sum(len(r) for r in rows)} total frames")

    # The walk cycle sheet has groups of characters.
    # Each character has 8 frames (4 directions x 2 frames each, arranged in 2 rows of 4)
    # We'll save each individual frame and also create grouped sprite sheets

    manifest = {}
    frame_idx = 0

    for row_idx, row in enumerate(rows):
        for j, bbox in enumerate(row):
            sprite = extract_sprite(arr, bbox)
            filename = f"walk_r{row_idx}_f{j}.png"
            filepath = out_dir / filename
            sprite.save(filepath, "PNG")
            frame_idx += 1

    print(f"  Saved {frame_idx} walk frames")

    # Also save the entire sheet as-is for sprite sheet rendering
    full_img = Image.open(img_path).convert("RGBA")
    full_arr = np.array(full_img)
    r, g, b = full_arr[:, :, 0], full_arr[:, :, 1], full_arr[:, :, 2]
    is_bg = (r > 240) & (g > 240) & (b > 240)
    full_arr[is_bg, 3] = 0
    full_out = Image.fromarray(full_arr, "RGBA")
    full_path = OUTPUT_DIR / "characters" / "walk_sheet.png"
    full_out.save(full_path, "PNG")
    print(f"  Saved full walk sheet with transparency: walk_sheet.png")

    manifest["walk_sheet"] = "characters/walk_sheet.png"
    return manifest


def slice_desk_poses(img_path):
    """Slice the working-at-desk poses."""
    print(f"\n=== Slicing desk/working poses: {img_path} ===")
    img, arr, rows = detect_sprites(img_path)

    out_dir = OUTPUT_DIR / "characters" / "working"
    out_dir.mkdir(parents=True, exist_ok=True)

    desk_rows = [DESK_AGENTS_ROW1, DESK_AGENTS_ROW2, DESK_AGENTS_ROW3, DESK_AGENTS_ROW4]

    manifest = {}
    for row_idx, row in enumerate(rows):
        names = desk_rows[row_idx] if row_idx < len(desk_rows) else []
        for j, bbox in enumerate(row):
            name = names[j] if j < len(names) else f"agent_r{row_idx}_{j}"
            sprite = extract_sprite(arr, bbox)
            filepath = out_dir / f"{name}.png"
            sprite.save(filepath, "PNG")
            manifest[name] = f"characters/working/{name}.png"
            print(f"  Saved {name}.png ({sprite.size[0]}x{sprite.size[1]}px)")

    return manifest


def main():
    idle_path = "/Users/m/Downloads/ChatGPT Image Mar 9, 2026, 02_11_19 AM.png"
    walk_path = "/Users/m/Downloads/ChatGPT Image Mar 9, 2026, 02_13_16 AM.png"
    desk_path = "/Users/m/Downloads/ChatGPT Image Mar 9, 2026, 02_14_07 AM.png"

    # Load existing manifest
    manifest_path = OUTPUT_DIR / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        manifest = {}

    # Slice each sheet
    if Path(idle_path).exists():
        idle = slice_idle_poses(idle_path)
        manifest.setdefault("characters_idle", {}).update(idle)
    else:
        print(f"Skipping idle poses (not found): {idle_path}")

    if Path(walk_path).exists():
        walk = slice_walk_cycles(walk_path)
        manifest.setdefault("characters_walk", {}).update(walk)
    else:
        print(f"Skipping walk cycles (not found): {walk_path}")

    if Path(desk_path).exists():
        desk = slice_desk_poses(desk_path)
        manifest.setdefault("characters_working", {}).update(desk)
    else:
        print(f"Skipping desk poses (not found): {desk_path}")

    # Save updated manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest updated: {manifest_path}")
    print("Done!")


if __name__ == "__main__":
    main()
