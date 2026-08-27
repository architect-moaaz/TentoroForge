"""Claude Agent SDK orchestration for Figma-to-Next.js generation."""

import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query
from services.agent_messages import Message, AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from figma_tools import create_figma_server, _get_headers, _extract_styles
from figma_parser import parse_figma_url

FIGMA_API_BASE = "https://api.figma.com/v1"

# Review loop constants
MAX_REVIEW_ITERATIONS = 3

DESIGN_TO_CODE_PROMPT = r"""You are a world-class frontend developer who converts Figma designs into pixel-perfect Next.js + Tailwind CSS code.

## ABSOLUTE RULES — FOLLOW THESE WITHOUT EXCEPTION
1. NEVER guess colors, sizes, fonts, or spacing. Use ONLY the exact values from styles.json.
2. EVERY text node's content must be rendered exactly as written in styles.json `text` field.
3. EVERY node with an `imagePath` field must render as `<Image src={imagePath} />` (next/image).
4. Use Tailwind arbitrary values exclusively: `bg-[#841013]`, `text-[14px]`, `w-[320px]`, `gap-[16px]`, `rounded-[8px]`
5. The page must be full-viewport: `min-h-screen w-full` with flex centering for the main container.

## YOUR WORKFLOW — FOLLOW THIS EXACT ORDER
1. **Read** `reference.png` — SEE the visual design you must replicate
2. **Read** `styles.json` — this is the COMPLETE style tree. Study it carefully.
3. **Run** `ls public/images/` — see all available image assets
4. **Plan** your component structure by analyzing the style tree's `children[]` nesting
5. **Write** all project files (see FILES TO GENERATE below)
6. **Run** `npm install && npm run build` — verify it compiles

## HOW styles.json WORKS
The file is a recursive tree. Each node has:
- `id` — Figma node ID (matches exported image filenames: node_{id}.png/svg)
- `name`, `type` — element identity
- `width`, `height` — exact pixel dimensions
- `fills[]` — backgrounds:
  - `{type:"SOLID", color:"#hex"}` → use as bg color
  - `{type:"GRADIENT_LINEAR", stops:[{color,position},...]}` → use as CSS gradient
  - `{type:"IMAGE", imageRef:"..."}` → this node has an image background
- `imagePath` — **DIRECT PATH** to the exported image (e.g. "/images/node_1_7.png"). USE THIS IN YOUR CODE.
- `border` — `{width, color}` → border styling
- `borderRadius` — px value or [tl,tr,br,bl]
- `layout` — flexbox: `{direction, gap, padding:{top,right,bottom,left}, justify, align, sizingH, sizingV}`
- `textStyle` — `{fontFamily, fontSize, fontWeight, lineHeightPx, letterSpacing}`
- `textColor` — hex color for text
- `text` — the EXACT text to render
- `effects[]` — shadows: `{type:"DROP_SHADOW", x, y, blur, spread, color}`
- `opacity` — 0-1 value
- `children[]` — nested child nodes (RECURSE into these!)

## CONVERSION REFERENCE

### Fills
- `fills[].color: "#841013"` → `bg-[#841013]`
- `fills[].type: "GRADIENT_LINEAR"` with stops → `style={{background: "linear-gradient(180deg, #color1 0%, #color2 100%)"}}`
- Node has `imagePath: "/images/node_1_7.png"` → `<Image src="/images/node_1_7.png" alt="..." width={W} height={H} />`

### Layout (CRITICAL — this determines the visual structure)
- `layout.direction: "column"` → `flex flex-col`
- `layout.direction: "row"` → `flex flex-row`  (or just `flex`)
- `layout.gap: 16` → `gap-[16px]`
- `layout.padding: {top:40,right:48,bottom:40,left:48}` → `pt-[40px] pr-[48px] pb-[40px] pl-[48px]`
- `layout.justify`:
  - `"MIN"` → `justify-start`
  - `"CENTER"` → `justify-center`
  - `"MAX"` → `justify-end`
  - `"SPACE_BETWEEN"` → `justify-between`
- `layout.align`:
  - `"MIN"` → `items-start`
  - `"CENTER"` → `items-center`
  - `"MAX"` → `items-end`
- `layout.sizingH`:
  - `"FILL"` → `w-full` (or `flex-1` if inside a flex row)
  - `"HUG"` → `w-fit` (or omit, let content size it)
  - `"FIXED"` → `w-[{width}px]`
- `layout.sizingV`:
  - `"FILL"` → `h-full` (or `flex-1` if inside a flex column)
  - `"HUG"` → `h-fit`
  - `"FIXED"` → `h-[{height}px]`

### Typography
- `textStyle.fontFamily: "Inter"` → use Google Font import in layout.tsx
- `textStyle.fontSize: 14` → `text-[14px]`
- `textStyle.fontWeight: 600` → `font-[600]`
- `textStyle.lineHeightPx: 20` → `leading-[20px]`
- `textStyle.letterSpacing: -0.15` → `tracking-[-0.15px]` (or style={{letterSpacing:"-0.15px"}})
- `textColor: "#ffffff"` → `text-white`
- `textColor: "#6e2574"` → `text-[#6e2574]`

### Other
- `borderRadius: 12` → `rounded-[12px]`
- `border: {width:1, color:"#d1d5db"}` → `border border-[#d1d5db]`
- `effects[]: {type:"DROP_SHADOW", x:0, y:25, blur:50, spread:-12, color:"rgba(0,0,0,0.25)"}` → `style={{boxShadow:"0px 25px 50px -12px rgba(0,0,0,0.25)"}}`
- `opacity: 0.5` → `opacity-50`
- `overflow: "hidden"` → `overflow-hidden`

## COMPONENT STRATEGY
Analyze the top-level `children[]` in styles.json. Typically:
- The ROOT node is the page container
- Each direct child of the root is a major section → make each a component
- Example: A login page with left branding + right form → `<BrandingPanel />` + `<LoginForm />`
- Form inputs: use `<input>` with exact placeholder text from the `text` field
- Buttons: use `<button>` with exact text
- Links: use `<a>` with exact text

## FILES TO GENERATE
1. `package.json` — dependencies: next, react, react-dom, tailwindcss, @tailwindcss/postcss, postcss
2. `postcss.config.mjs` — `export default { plugins: { "@tailwindcss/postcss": {} } }`
3. `tsconfig.json` — standard Next.js config
4. `next.config.ts` — standard Next.js config
5. `src/app/globals.css`:
   ```css
   @import "tailwindcss";
   ```
6. `src/app/layout.tsx` — import Google Fonts matching `fontFamily` values from styles.json
7. `src/app/page.tsx` — compose components, wrap in `min-h-screen w-full flex items-center justify-center` with the root background
8. `src/components/*.tsx` — one component per major section (e.g., BrandingPanel.tsx, LoginForm.tsx)

## FINAL CHECKLIST — VERIFY EACH ONE
- [ ] Did you Read reference.png first?
- [ ] Did you Read styles.json and use its EXACT values?
- [ ] Does EVERY color come from styles.json hex values?
- [ ] Does EVERY text match the `text` field exactly?
- [ ] Does EVERY image use the `imagePath` from styles.json or a file from public/images/?
- [ ] Is the page full-viewport with `min-h-screen`?
- [ ] Did you handle ALL layout properties (direction, gap, padding, justify, align)?
- [ ] Did you run `npm install && npm run build` successfully?
"""


async def _prefetch_figma_data(
    file_key: str,
    node_id: str | None,
    output_dir: str,
    figma_token: str,
) -> dict:
    """Pre-fetch all Figma data, export images, and save to output directory."""
    headers = {"X-Figma-Token": (figma_token or "").strip()}
    info = {"frames_processed": []}

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        # 1. Fetch file tree with depth=2
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}",
            headers=headers,
            params={"depth": 2},
        )
        resp.raise_for_status()
        file_data = resp.json()

        # Find target frames
        target_node_ids = []
        pages = file_data.get("document", {}).get("children", [])

        MAX_FRAMES = 10  # Cap to avoid huge exports

        if node_id:
            # Check if node_id is a PAGE node — if so, get ALL child frames
            is_page = False
            for page in pages:
                if page.get("id") == node_id and page.get("type") == "CANVAS":
                    is_page = True
                    for child in page.get("children", []):
                        if child.get("type") == "FRAME" and len(target_node_ids) < MAX_FRAMES:
                            target_node_ids.append(child["id"])
                    break
            if not is_page:
                target_node_ids = [node_id]
        else:
            # Get ALL top-level frames from first page
            if pages:
                first_page = pages[0]
                for child in first_page.get("children", []):
                    if child.get("type") == "FRAME" and len(target_node_ids) < MAX_FRAMES:
                        target_node_ids.append(child["id"])

        if not target_node_ids:
            raise ValueError("No frames found in the Figma file")

        info["target_node_ids"] = target_node_ids

        # 2. Export reference screenshot of each frame
        all_export_ids = ",".join(target_node_ids)
        resp = await client.get(
            f"{FIGMA_API_BASE}/images/{file_key}",
            headers=headers,
            params={"ids": all_export_ids, "format": "png", "scale": 2},
        )
        resp.raise_for_status()
        export_data = resp.json()

        images_dir = Path(output_dir) / "public" / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # Download main reference screenshot (first frame)
        image_urls = export_data.get("images", {})
        for i, nid in enumerate(target_node_ids):
            url = image_urls.get(nid)
            if url:
                img_resp = await client.get(url)
                if img_resp.status_code == 200:
                    ref_path = Path(output_dir) / ("reference.png" if i == 0 else f"reference_{i}.png")
                    ref_path.write_bytes(img_resp.content)

        # 3. Fetch full node data for each target frame
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}/nodes",
            headers=headers,
            params={"ids": all_export_ids},
        )
        resp.raise_for_status()
        nodes_data = resp.json()

        # 4. Extract compact CSS styles
        all_styles = {}
        all_image_refs = set()
        all_exportable_nodes = []  # Nodes that should be exported as images

        for nid, node_info in nodes_data.get("nodes", {}).items():
            doc = node_info.get("document")
            if doc:
                styles = _extract_styles(doc)
                all_styles[nid] = styles
                info["frames_processed"].append({"id": nid, "name": doc.get("name", "")})

                # Collect all image refs and exportable nodes
                _collect_image_nodes(doc, all_image_refs, all_exportable_nodes)

        # Save styles (flatten if single frame, keyed by ID if multiple)
        styles_path = Path(output_dir) / "styles.json"
        if len(all_styles) == 1:
            # Flatten: save just the single frame's style tree directly
            single_style = next(iter(all_styles.values()))
            styles_json = json.dumps(single_style, indent=2)
        else:
            styles_json = json.dumps(all_styles, indent=2)

        # Cap styles.json at ~100KB to keep the design analyzer agent fast.
        # If larger, prune deep nesting to reduce size while preserving structure.
        MAX_STYLES_BYTES = 100_000  # noqa: N806
        if len(styles_json.encode()) > MAX_STYLES_BYTES:
            import logging
            logging.getLogger(__name__).warning(
                "styles.json is %d bytes — truncating deep nesting to keep under %d",
                len(styles_json.encode()), MAX_STYLES_BYTES,
            )
            pruned = json.loads(styles_json)
            if isinstance(pruned, dict) and "children" in pruned:
                # Single frame (flattened)
                _prune_deep_children(pruned, max_depth=8)
            elif isinstance(pruned, dict):
                # Multiple frames keyed by ID
                for key in pruned:
                    if isinstance(pruned[key], dict):
                        _prune_deep_children(pruned[key], max_depth=8)
            styles_json = json.dumps(pruned, indent=2)

        styles_path.write_text(styles_json)

        # 5. Download image fills
        if all_image_refs:
            resp = await client.get(
                f"{FIGMA_API_BASE}/files/{file_key}/images",
                headers=headers,
            )
            resp.raise_for_status()
            image_fills = resp.json().get("meta", {}).get("images", {})

            for ref in all_image_refs:
                url = image_fills.get(ref)
                if url:
                    img_resp = await client.get(url)
                    if img_resp.status_code == 200:
                        ext = "png"
                        img_path = images_dir / f"fill_{ref[:12]}.{ext}"
                        img_path.write_bytes(img_resp.content)

        # 6. Export specific nodes as images (logos, icons, etc.)
        if all_exportable_nodes:
            # Export as PNG
            export_ids = ",".join(all_exportable_nodes[:20])  # Limit to 20
            resp = await client.get(
                f"{FIGMA_API_BASE}/images/{file_key}",
                headers=headers,
                params={"ids": export_ids, "format": "png", "scale": 2},
            )
            resp.raise_for_status()
            export_urls = resp.json().get("images", {})

            for enid, url in export_urls.items():
                if url:
                    img_resp = await client.get(url)
                    if img_resp.status_code == 200:
                        safe_name = enid.replace(":", "_").replace(";", "_")
                        img_path = images_dir / f"node_{safe_name}.png"
                        img_path.write_bytes(img_resp.content)

            # Also try SVG export for vector nodes
            resp = await client.get(
                f"{FIGMA_API_BASE}/images/{file_key}",
                headers=headers,
                params={"ids": export_ids, "format": "svg"},
            )
            resp.raise_for_status()
            svg_urls = resp.json().get("images", {})

            for enid, url in svg_urls.items():
                if url:
                    img_resp = await client.get(url)
                    if img_resp.status_code == 200:
                        safe_name = enid.replace(":", "_").replace(";", "_")
                        svg_path = images_dir / f"node_{safe_name}.svg"
                        svg_path.write_bytes(img_resp.content)

        # 7. Create image manifest mapping node IDs to filenames
        image_manifest = {}
        for img_file in images_dir.iterdir():
            if img_file.is_file():
                image_manifest[img_file.name] = f"/images/{img_file.name}"
        manifest_path = Path(output_dir) / "images_manifest.json"
        manifest_path.write_text(json.dumps(image_manifest, indent=2))

        # 8. Annotate style tree with image paths for exported nodes
        _annotate_image_paths(all_styles, all_exportable_nodes, images_dir)
        # Re-save styles with image annotations (apply same size cap)
        if len(all_styles) == 1:
            single_style = next(iter(all_styles.values()))
            styles_json = json.dumps(single_style, indent=2)
        else:
            styles_json = json.dumps(all_styles, indent=2)
        if len(styles_json.encode()) > MAX_STYLES_BYTES:
            pruned = json.loads(styles_json)
            if isinstance(pruned, dict) and "children" in pruned:
                _prune_deep_children(pruned, max_depth=8)
            elif isinstance(pruned, dict):
                for key in pruned:
                    if isinstance(pruned[key], dict):
                        _prune_deep_children(pruned[key], max_depth=8)
            styles_json = json.dumps(pruned, indent=2)
        styles_path.write_text(styles_json)

    # Note: AHTML generation happens later in the IR pipeline (Step 8)
    # which is Figma-aware and runs after the main agents complete.
    # We don't pre-generate here to avoid competing for Claude API capacity.

    return info


def _prune_deep_children(node: dict, max_depth: int, depth: int = 0):
    """Recursively prune children beyond max_depth to cap styles.json size."""
    if depth >= max_depth:
        node.pop("children", None)
        return
    for child in node.get("children", []):
        _prune_deep_children(child, max_depth, depth + 1)


def _annotate_image_paths(styles: dict, exportable_nodes: list, images_dir: Path):
    """Walk style trees and add imagePath for nodes that were exported as images."""
    exported_set = set(exportable_nodes)

    def _walk(node: dict):
        nid = node.get("id", "")
        if nid and nid in exported_set:
            safe_name = nid.replace(":", "_").replace(";", "_")
            # Check which files exist
            png_path = images_dir / f"node_{safe_name}.png"
            svg_path = images_dir / f"node_{safe_name}.svg"
            if svg_path.exists():
                node["imagePath"] = f"/images/node_{safe_name}.svg"
            elif png_path.exists():
                node["imagePath"] = f"/images/node_{safe_name}.png"
        for child in node.get("children", []):
            _walk(child)

    for style_tree in styles.values():
        _walk(style_tree)


def _collect_image_nodes(node: dict, image_refs: set, exportable_nodes: list, depth: int = 0):
    """Walk the node tree to find image fills and nodes worth exporting as images."""
    # Check for image fills
    for fill in node.get("fills", []):
        if fill.get("type") == "IMAGE" and fill.get("imageRef"):
            image_refs.add(fill["imageRef"])

    # Identify nodes to export as separate images:
    # - Nodes with image fills (the parent container)
    # - VECTOR, BOOLEAN_OPERATION nodes (icons)
    # - Small FRAME/GROUP nodes that contain only vectors (icon groups)
    # - Nodes whose name suggests they're logos/icons
    node_type = node.get("type", "")
    name = node.get("name", "").lower()
    has_image_fill = any(f.get("type") == "IMAGE" for f in node.get("fills", []))

    if has_image_fill:
        exportable_nodes.append(node["id"])
    elif node_type in ("VECTOR", "BOOLEAN_OPERATION"):
        exportable_nodes.append(node["id"])
    elif node_type in ("FRAME", "GROUP", "INSTANCE", "COMPONENT") and depth > 0:
        # Check if it looks like a logo, icon, or small visual element
        bbox = node.get("absoluteBoundingBox", {})
        w = bbox.get("width", 0)
        h = bbox.get("height", 0)
        is_small = w < 200 and h < 200
        name_hints = ("logo", "icon", "image", "img", "avatar", "badge", "illustration", "graphic")
        if any(hint in name for hint in name_hints) or (is_small and node_type in ("GROUP", "INSTANCE")):
            exportable_nodes.append(node["id"])

    # Recurse into children
    for child in node.get("children", []):
        _collect_image_nodes(child, image_refs, exportable_nodes, depth + 1)


async def run_agent(
    figma_url: str,
    figma_token: str,
    output_dir: str,
    prefetch_info: dict | None = None,
    requirements: dict | None = None,
    ui_only: bool = False,
) -> AsyncIterator[Message]:
    """Run the design-to-code agent pipeline, yielding streaming messages."""
    parsed = parse_figma_url(figma_url)
    file_key = parsed["file_key"]
    node_id = parsed.get("node_id")

    # Set FIGMA_TOKEN for the tools to use (strip whitespace — browser
    # copy-paste often appends a trailing space, which httpx rejects as an
    # illegal header value).
    figma_token = (figma_token or "").strip()
    os.environ["FIGMA_TOKEN"] = figma_token

    # Unset Claude Code env vars to allow the SDK to spawn a nested CLI process
    os.environ.pop("CLAUDECODE", None)
    os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

    # Create the output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Pre-fetch if not already done by caller
    if prefetch_info is None:
        prefetch_info = await _prefetch_figma_data(file_key, node_id, output_dir, figma_token)

    # Create the Figma MCP server (still available for additional fetches if needed)
    figma_server = create_figma_server()

    frames_desc = ", ".join(
        f'"{f["name"]}" (node {f["id"]})'
        for f in prefetch_info.get("frames_processed", [])
    )

    requirements_section = ""
    if requirements:
        # Extract pages for explicit route generation instructions
        pages = requirements.get("pages", [])
        pages_instructions = ""
        if pages:
            page_list = "\n".join(
                f"  - `src/app{p.get('route', '/')}/page.tsx` — {p.get('name', 'Page')}: {p.get('description', '')}"
                for p in pages
            )
            pages_instructions = f"""

## REQUIRED Page Routes — you MUST create these files:
{page_list}
Each page must be a fully functional Next.js page component in the app directory.
The root page (src/app/page.tsx) should redirect to the main page or serve as the landing page.
"""

        # Extract data_models for schema instructions
        data_models = requirements.get("data_models", [])
        schema_instructions = ""
        if data_models:
            model_names = ", ".join(m.get("name", "") for m in data_models)
            schema_instructions = f"""

## Database Schema
A Drizzle ORM schema has been pre-generated at `src/db/schema.ts` with tables: {model_names}.
If you need to modify it, use Edit (not Write) to preserve existing content.
Import the db connection from `src/db/index.ts` in your API routes.
"""

        requirements_section = f"""

## Application Requirements (approved by user):
{json.dumps(requirements, indent=2)}

Use these requirements to guide your implementation:
- Create ALL the pages and routes listed below as actual Next.js page files
- Use the pre-generated database schema (src/db/schema.ts) if it exists
- Add the interactions and workflows described
- Generate proper navigation between pages
- Match the visual design pixel-perfectly while also implementing the functional requirements
{pages_instructions}{schema_instructions}"""

    # When ui_only=True, constrain the agent to only generate UI files.
    # Foundation files (package.json, schema, auth, API routes) already exist from relay phases.
    ui_only_prefix = ""
    if ui_only:
        ui_only_prefix = """
IMPORTANT: Foundation files already exist on disk from prior build phases.
Do NOT create or overwrite: package.json, postcss.config.mjs, tsconfig.json, next.config.ts,
drizzle.config.ts, .env, .env.local, docker-compose.yml, src/db/schema.ts, src/db/index.ts,
src/app/api/**/*.ts, src/services/**/*.ts, src/lib/auth*.ts, src/middleware.ts, seed.ts.
Read them for import paths, types, and database schema — but do NOT modify them.

ONLY generate these files:
- src/app/globals.css
- src/app/layout.tsx and src/app/**/layout.tsx
- src/components/**/*.tsx
- src/app/**/page.tsx
- src/app/error.tsx, src/app/not-found.tsx, src/app/loading.tsx

"""

    user_prompt = f"""{ui_only_prefix}Convert this Figma design to a pixel-perfect Next.js + Tailwind CSS application.

## Pre-fetched data (already in your working directory):
- `reference.png` — Screenshot of the design. READ THIS FIRST.
- `styles.json` — Recursive style tree with EVERY CSS property for EVERY element. Nodes with `imagePath` have pre-exported images.
- `public/images/` — All logos, icons, and images pre-exported as PNG/SVG.

## Frame: {frames_desc}
{requirements_section}
## MANDATORY WORKFLOW — follow this exact order:
1. `Read` reference.png — look at it carefully to understand the layout
2. `Read` styles.json — study the FULL tree structure, note every node's layout, fills, text, textStyle, textColor, imagePath
3. `Bash` `ls public/images/` — see what image files exist
4. Plan your components based on the top-level children in styles.json
5. Write ALL project files (package.json, postcss, tsconfig, next.config, globals.css, layout.tsx, page.tsx, components)
6. `Bash` `npm install && npm run build` — must compile successfully

## CRITICAL RULES:
- The root page must use `min-h-screen w-full` and center the main card/container
- EVERY color value must come from styles.json — NEVER guess or approximate
- EVERY text must match the `text` field EXACTLY (including line breaks shown as separate text nodes)
- Nodes with `imagePath` must render as `<Image src={{imagePath}} />` using next/image
- Apply ALL layout properties: direction → flex direction, gap, padding (all 4 sides), justify, align
- Apply ALL text properties: fontSize, fontWeight, lineHeightPx, letterSpacing, textColor
- Split the UI into logical components (e.g., left panel + right panel = 2 components)

Do NOT skip any node in the tree. Walk the ENTIRE styles.json tree and translate EVERY visible node to JSX."""

    import logging
    _logger = logging.getLogger("agent.stderr")

    def _on_stderr(line: str) -> None:
        _logger.warning("CLI stderr: %s", line.rstrip())

    # PHASE-2 brief injection — brief is a guardrail while Figma reference
    # remains primary for the Figma path. Adds anti-patterns and signature
    # moves as constraints; palette/type from Figma still wins on conflict.
    _brief_block = ""
    if os.getenv("FORGE_BRIEF_CONSUME", "0") == "1":
        try:
            from services.design_brief_to_prompt import (
                brief_to_prompt, load_brief_from_disk,
            )
            _b = load_brief_from_disk(output_dir)
            if _b is not None:
                _brief_block = "\n\n" + brief_to_prompt(_b)
        except Exception:  # noqa: BLE001
            pass

    options = ClaudeAgentOptions(
        system_prompt=DESIGN_TO_CODE_PROMPT + _brief_block,
        allowed_tools=[
            "Write", "Edit", "Read", "Bash", "Glob",
            "mcp__figma__fetch_figma_file",
            "mcp__figma__fetch_figma_nodes",
            "mcp__figma__get_node_css_styles",
            "mcp__figma__export_figma_images",
            "mcp__figma__get_image_fills",
            "mcp__figma__download_asset",
        ],
        mcp_servers={"figma": figma_server},
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=80,
        model="claude-sonnet-4-6",
        stderr=_on_stderr,
    )

    # WORKAROUND: Use AsyncIterable prompt instead of string prompt.
    # The Python Agent SDK has a bug where the string-prompt code path
    # calls end_input() immediately after writing the user message,
    # closing stdin before SDK MCP servers can finish their bidirectional
    # control protocol exchange. The AsyncIterable path in stream_input()
    # correctly waits for the first result before closing stdin.
    async def _single_prompt():
        yield {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": user_prompt},
            "parent_tool_use_id": None,
        }

    async for message in query(prompt=_single_prompt(), options=options):
        yield message


# ---------------------------------------------------------------------------
# Refinement Agent
# ---------------------------------------------------------------------------

REFINEMENT_SYSTEM_PROMPT = r"""You are a frontend developer making visual refinements to an existing Next.js + Tailwind CSS application based on user instructions.

## Your job
The user will describe a visual change they want (e.g., "make the button red", "increase the font size of the heading", "add more padding to the card"). You must:
1. Read the relevant source files to understand the current code
2. Make targeted edits to implement the requested change
3. Verify the build still compiles

## Rules
- Use Edit (not Write) for all changes — preserve existing working code
- Make ONLY the changes the user requested — nothing else
- Use Tailwind CSS classes or inline styles matching the project's existing patterns
- After all edits, run: npm run build — to verify compilation
- If a build fails, fix the compilation error
- Do NOT restructure, refactor, or reorganize code
- Do NOT add new dependencies
- Be precise and surgical — change the minimum amount of code needed
"""


async def run_refinement_agent(
    output_dir: str,
    instruction: str,
) -> AsyncIterator[Message]:
    """Run the refinement agent to apply a user's natural language change request.

    Yields streaming messages (AssistantMessage/ResultMessage) for SSE forwarding.
    """
    user_prompt = f"""Apply this visual change to the Next.js + Tailwind CSS project:

## User instruction:
{instruction}

## Steps:
1. Read the source files in src/ to understand the current code structure
2. Identify which file(s) and element(s) need to change
3. Use Edit to make targeted changes
4. Stop after your last successful Edit — do NOT run npm build/lint/tests;
   the platform runs downstream validation and a Vercel build on publish.
   Running builds here just burns turns and hits the max-turns cap
   (previously reported as B-006).

Start by reading src/app/page.tsx and any component files."""

    options = ClaudeAgentOptions(
        system_prompt=REFINEMENT_SYSTEM_PROMPT,
        # Bash removed — the loop no longer runs local builds; without a
        # Bash tool available, the agent can't blow the turn budget on
        # `npm install`/`npm run build` retry loops. Raising max_turns
        # gives headroom for legitimate multi-file edits.
        allowed_tools=["Write", "Edit", "Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=60,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


# ---------------------------------------------------------------------------
# Reviewer Agent
# ---------------------------------------------------------------------------

REVIEWER_SYSTEM_PROMPT = r"""You are a visual QA reviewer comparing a Figma reference design against a generated web application.

You will receive two images:
1. reference.png — the original Figma design (the GROUND TRUTH)
2. generated_screenshot.png — screenshot of the generated app

Compare them CAREFULLY and list EVERY visual difference. Be specific and actionable.

## What to compare
- **Layout structure**: element positions, flex direction, alignment, overall composition
- **Colors**: exact hex comparison — backgrounds, text colors, button colors, gradients
- **Typography**: font size, weight, color, line-height, letter-spacing
- **Spacing**: gaps between elements, padding, margins
- **Missing or extra elements**: anything in the reference that's absent, or vice versa
- **Images/logos**: missing images, wrong size, wrong position
- **Border radius, shadows, effects**: rounded corners, drop shadows, blurs
- **Sizing**: element widths and heights, whether they fill their container

## Output format
For each issue, output a numbered item with:
- WHAT is wrong (e.g., "Sign in button color")
- WHERE in the UI (e.g., "right panel, bottom")
- EXPECTED value (from reference)
- ACTUAL value (in generated)
- HOW TO FIX (specific CSS/Tailwind change)

Example:
1. Left panel gradient: should be top-to-bottom #841013→#9f5253, currently appears as solid #841013. Fix: add style={{background: "linear-gradient(180deg, #841013 0%, #9f5253 100%)"}}
2. "Sign in" button: should be bg-[#4f39f6], currently bg-[#846a13]. Fix: change bg color class.
3. Logo image missing — should use <Image src="/images/node_1_7.png">. Fix: add Image import and render.

## Important rules
- Compare ONLY visual appearance. Do not comment on code quality or structure.
- Be as specific as possible — mention exact colors, pixel sizes, Tailwind classes.
- If the designs match closely (95%+ visual similarity), respond with EXACTLY: APPROVED
- Do NOT say APPROVED if there are any noticeable differences.
- Focus on the most impactful visual differences first.
- You have access to Read and Glob tools — use them to read styles.json for the exact expected values.
"""


async def run_reviewer_agent(output_dir: str) -> str:
    """
    Run the reviewer agent to compare reference.png vs generated_screenshot.png.
    Returns the list of issues as a string, or "APPROVED" if the match is good.
    """
    reference_path = Path(output_dir) / "reference.png"
    screenshot_path = Path(output_dir) / "generated_screenshot.png"

    if not reference_path.exists() or not screenshot_path.exists():
        return "ERROR: Missing reference.png or generated_screenshot.png"

    user_prompt = f"""Compare these two images and list every visual difference.

Image 1 (REFERENCE — the ground truth): reference.png
Image 2 (GENERATED — the app screenshot): generated_screenshot.png

Read both images, then also Read styles.json to verify exact expected values (colors, sizes, fonts).

List every visual difference you find, or respond with APPROVED if they match closely."""

    options = ClaudeAgentOptions(
        system_prompt=REVIEWER_SYSTEM_PROMPT,
        allowed_tools=["Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=10,
        model="claude-sonnet-4-6",
    )

    result_text = ""
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    result_text += block.text + "\n"

    return result_text.strip()


# ---------------------------------------------------------------------------
# Fixer Agent
# ---------------------------------------------------------------------------

FIXER_SYSTEM_PROMPT = r"""You are a senior frontend developer fixing visual and functional issues in a generated Next.js + Tailwind CSS application.

Before making any changes:
1. Read `src/contracts/design-spec.json` to understand the design system, domain, and visual intent
2. Understand the domain context — your fixes should make the app look MORE like a professional {domain} application, not less

For each issue:
1. Read the relevant source file(s) using the Read tool
2. Find the exact element that needs changing
3. Use Edit to make the specific change — do NOT rewrite entire files
4. Make surgical, targeted fixes only

## Rules
- Use Edit (not Write) for all changes — preserve existing working code
- Only change what is listed in the issues — do not refactor or reorganize
- Use exact values from the issue descriptions (hex colors, pixel sizes, Tailwind classes)
- After all fixes, run: npm run build — to verify everything still compiles
- If a build fails, fix the compilation error before proceeding
- Do NOT add new dependencies or change the project structure
- Your fixes should IMPROVE the design quality, not just satisfy the reviewer — add depth (shadows), hierarchy (type scale), and polish (transitions) where they're missing

## CRITICAL: DO NOT CHANGE NAVIGATION (breaks the entire app)
- NEVER rename sidebar links or change their href values
- NEVER rename navbar links or change their href values
- NEVER rename the app brand/title to a different domain
- NEVER change quick action links to point to pages that don't exist
- Navigation links MUST match actual page routes — if you change a link, verify the target page exists
- You may ONLY change visual properties: colors, fonts, spacing, icons, hover effects, shadows
- If the reviewer says "make it look more like a {domain} app", change VISUAL styling only — not link text or URLs
"""


async def run_fixer_agent(output_dir: str, issues: str) -> AsyncIterator[Message]:
    """
    Run the fixer agent to apply corrections based on reviewer feedback.
    Yields streaming messages for SSE forwarding.
    """
    user_prompt = f"""Fix the following visual issues in this Next.js + Tailwind CSS project.

## Issues to fix:
{issues}

## Instructions:
1. Read the source files in src/ to understand the current code
2. For each issue, make the specific Edit to fix it
3. After all fixes, run: npm run build
4. If the build fails, fix the error

Start by reading the main page and component files."""

    options = ClaudeAgentOptions(
        system_prompt=FIXER_SYSTEM_PROMPT,
        allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=40,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


# ---------------------------------------------------------------------------
# Design-Aware Visual Reviewer (text-based generation — no Figma reference)
# ---------------------------------------------------------------------------

DESIGN_REVIEWER_SYSTEM_PROMPT = r"""You are a senior UI/UX design reviewer with 15+ years of experience across enterprise applications, design systems, and domain-specific software. You have deep expertise in design theory, color psychology, accessibility, information architecture, and competitive benchmarking.

You will receive:
1. A screenshot of a page from a generated application
2. Access to `src/contracts/design-spec.json` — the design system
3. Domain context, original requirements, and the plan

You evaluate SEVEN dimensions. Every generated page must pass ALL of them.

## 1. DESIGN THEORY & COLOR

### Color Theory
- **Harmony**: Are colors complementary, analogous, or triadic — not random? Primary, secondary, accent should have a deliberate relationship
- **Contrast**: WCAG AA minimum — 4.5:1 for body text, 3:1 for large headings. Text must be readable on every background
- **Emotional tone per domain**:
  - Healthcare: trust (blue), calm (teal), clinical precision (clean whites, muted backgrounds)
  - Finance: stability (navy), growth (green), authority (dark, conservative tones)
  - E-commerce: energy (orange/red CTAs), trust (blue checkout), freshness (white space)
  - Education: approachable (warm blues), scholarly (deep purple/navy), growth (green accents)
  - HR: professional (blue-gray), warm (teal accents), human (rounded, spacious)
- **Color distribution**: Primary = 10-15% (CTAs, active states). Neutral = 70% (backgrounds, text). Accent = 5% (highlights). Too much primary = overwhelming. Too little = bland
- **Status consistency**: success=green, warning=amber, error=red, info=blue — universally, not inverted

### Layout Composition
- **Visual hierarchy**: Clear reading order — hero/title → stats → content → actions
- **F-pattern / Z-pattern**: Primary content follows natural eye scanning
- **Rule of thirds**: Key elements placed at intersection points
- **Whitespace**: Deliberate spacing groups related items, separates sections. No cramping, no floating
- **Alignment**: Everything on a consistent grid — no 3px-off misalignment
- **Proximity**: Labels next to inputs, actions next to their context, related stats grouped
- **Above the fold**: Most important content visible without scrolling

## 2. INFORMATION ARCHITECTURE

- **3-click rule**: Can users reach any key action in 3 clicks or fewer?
- **Navigation labels**: Are sidebar/nav items descriptive? ("Patient Records" not "Records")
- **Grouping**: Are nav items grouped by workflow? (Clinical → Scheduling → Admin, not alphabetical)
- **Breadcrumbs**: On detail/form pages, can users see where they are?
- **Active state**: Is the current page highlighted in the sidebar?
- **Page title**: Does the page clearly state what it is?

## 3. COGNITIVE LOAD & USABILITY

- **Simplicity**: Is the page overwhelming? Too many actions/buttons/data points?
- **Progressive disclosure**: Is complex info hidden behind tabs/accordions?
- **Action clarity**: Are CTAs action-oriented? ("Save Patient" not "Submit", "Schedule Appointment" not "Create")
- **Decision fatigue**: Are there too many equal-weight buttons? One primary, rest secondary/outline
- **Scanning**: Can users scan the page in 5 seconds and understand what to do?

## 4. DOMAIN FIT

- Does this LOOK like a {domain} application? Would a {domain} professional recognize this as their tool?
- Dashboard shows DOMAIN-RELEVANT data (patient counts for healthcare, revenue for e-commerce)
- Domain-specific patterns used (timeline for records, calendar for appointments, kanban for tasks)
- Status values use domain-correct labels and colors
- Navigation reflects domain workflows, not just entity CRUD
- Density matches: compact for data-heavy, comfortable for general, spacious for consumer

## 5. REQUIREMENTS VERIFICATION

- Page shows the data/entities the user asked for
- Key features visible (scheduling → calendar view, billing → invoice list)
- Navigation includes all planned pages
- Workflow actions present (approve/reject where needed)

## 6. STATES & RESILIENCE

- **Empty state**: What does the page look like with no data? Icon + message + CTA, not just blank
- **Loading state**: Are there skeletons/shimmer while data loads, not just "Loading..."
- **Error handling**: Is there error messaging for failed loads?
- **Validation**: Do form fields show inline validation errors?

## 7. ACCESSIBILITY & RESPONSIVENESS

- **Touch targets**: Buttons/links minimum 44px on mobile
- **Focus indicators**: Visible focus rings on keyboard navigation
- **Font sizes**: Nothing smaller than 12px (text-xs). Body text 14px+ (text-sm+)
- **Color-blind safety**: Information not conveyed by color alone (add icons/text to status badges)
- **No horizontal scroll**: Page fits viewport width
- **Responsive hints**: Are there responsive classes (sm:, md:, lg:) in the code?

## COMPETITIVE BENCHMARK

For reference, the best apps in each domain look like:
- Healthcare: Epic, Athenahealth — clean clinical UI, tabbed patient views, timeline-based records
- Finance: Stripe Dashboard, Mercury — data-dense but elegant, clear number hierarchy
- E-commerce: Shopify Admin — card-based, clear stats, order pipeline
- Project Mgmt: Linear, Notion — minimal, fast, keyboard-first, clean type scale
- HR: Rippling, Gusto — warm, people-focused, photo-heavy, spacious
- CRM: HubSpot, Salesforce Lightning — pipeline views, activity feeds, deal cards

The generated app should feel like it belongs in the same category as these — not like a student project.

## Output format

For each issue:
1. **DIMENSION**: color-theory | layout | info-architecture | cognitive-load | domain-fit | requirements | states | accessibility
2. **WHAT** is wrong (specific)
3. **WHERE** on the page
4. **WHY** it matters (principle violated, domain mismatch, or requirement unmet)
5. **HOW TO FIX** (specific file + CSS/Tailwind change)
6. **PRIORITY**: critical | important | minor

If the page passes ALL SEVEN dimensions: APPROVED

Be strict. You are the last line of defense before this ships to a user.
A page that "works" but looks like a generic Bootstrap template is NOT approved.
A page that matches the design spec but has poor information architecture is NOT approved.
The bar is: would you be proud to show this to a client as your team's work?

## AUTOMATIC FAIL CONDITIONS (any one = REJECTED, don't even evaluate other dimensions)

1. **Plain white/gray background** — if the page background is white or light gray with no design intent, REJECT. Every page must use `bg-background` from the design spec, not `bg-gray-50` or `bg-white`.
2. **No brand colors visible** — if the primary color from design-spec.json is not visible ANYWHERE on the page (not in buttons, headers, accents, or branding), REJECT.
3. **No visual hierarchy** — if the page is flat text with no shadows, no cards, no depth, no border-radius, REJECT. It looks like raw HTML.
4. **Login/signup without branding** — if login page has no app logo, no gradient/hero, no brand colors — just a plain centered form — REJECT. Auth pages are the first impression.
5. **Hardcoded gray text** — if you see `text-gray-600` or `text-gray-500` styled text (muted gray that doesn't match the design spec), REJECT. The page is using default Tailwind colors, not the design system.

Check these FIRST before evaluating the 7 dimensions. If any fail, list the specific issues and do NOT output APPROVED.
"""


async def run_design_reviewer_agent(
    output_dir: str,
    route: str,
    screenshot_path: str,
    domain: str = "",
    description: str = "",
    plan_summary: str = "",
) -> str:
    """Review a generated page against design spec, domain context, and requirements.

    Returns visual issues as a string, or "APPROVED" if quality is high.
    """
    if not Path(screenshot_path).exists():
        return "ERROR: Screenshot not found"

    # Load plan summary if not provided
    if not plan_summary:
        plan_file = Path(output_dir) / "app-model.json"
        if plan_file.exists():
            try:
                import json
                plan_data = json.loads(plan_file.read_text())
                entities = [t.get("name", "") for t in plan_data.get("database", {}).get("tables", [])]
                pages = [p.get("path", "") for p in plan_data.get("pages", [])]
                plan_summary = f"Entities: {', '.join(entities[:10])}\nPages: {', '.join(pages[:10])}"
            except Exception:
                pass

    user_prompt = f"""Review this generated page for design quality, domain fit, and requirements compliance.

## Context
- **Domain**: {domain or 'Read from design-spec.json designRationale'}
- **App Description**: {description or 'Read from design-spec.json'}
- **Page Route**: {route}
- **Screenshot**: {screenshot_path}

## Plan Summary
{plan_summary or 'Read app-model.json for entity and page details'}

## Steps
1. Read the screenshot image at {screenshot_path}
2. Read `src/contracts/design-spec.json` for the complete design system (colors, typography, layout)
3. CHECK AUTOMATIC FAIL CONDITIONS FIRST:
   - Is the background plain white/gray? → REJECT
   - Are brand colors visible? → If not, REJECT
   - Is there visual depth (shadows, cards, borders)? → If not, REJECT
   - For login/signup: is there branding (logo, gradient)? → If not, REJECT
4. If no auto-fail, evaluate ALL SEVEN dimensions from the system prompt
5. List every issue with dimension, location, fix, and priority
6. Or respond APPROVED only if ALL dimensions pass and NO auto-fail conditions trigger"""

    options = ClaudeAgentOptions(
        system_prompt=DESIGN_REVIEWER_SYSTEM_PROMPT,
        allowed_tools=["Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=8,
        model="claude-sonnet-4-6",
    )

    result_text = ""
    async for message in query(prompt=user_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    result_text += block.text + "\n"

    return result_text.strip()
