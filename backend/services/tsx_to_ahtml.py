"""TSX → AHTML reverse compiler.

Reads generated page.tsx files and converts them to Annotated HTML
suitable for the GrapeJS-based Build & Design editor.

Strategy:
  1. Extract the JSX return block from the component function.
  2. Convert JSX syntax to HTML (className→class, self-closing, etc.).
  3. Detect useQuery / useMutation calls → emit <meta data-source-*> tags.
  4. Detect useState calls → preserve as state bindings.
  5. Wrap in an AHTML page shell with route metadata.

This is intentionally 80/20 — it captures visual structure and layout
faithfully while leaving complex interactivity for re-annotation in the
editor panels.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# shadcn/ui component → default styling classes
# ---------------------------------------------------------------------------
# When converting <Card> to <div data-component="Card">, these classes are
# added so the GrapeJS canvas visually matches the running app.

_COMPONENT_STYLES: dict[str, str] = {
    # Layout shells
    "Card":            "rounded-xl border bg-card text-card-foreground shadow-sm",
    "CardHeader":      "flex flex-col space-y-1.5 p-6",
    "CardTitle":       "text-lg font-semibold leading-none tracking-tight",
    "CardDescription": "text-sm text-muted-foreground",
    "CardContent":     "p-6 pt-0",
    "CardFooter":      "flex items-center p-6 pt-0",

    # Buttons
    "Button":          "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors bg-primary text-primary-foreground shadow-sm h-9 px-4 py-2",

    # Inputs
    "Input":           "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    "Textarea":        "flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
    "Label":           "text-sm font-medium leading-none",
    "Select":          "flex h-9 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm",
    "Switch":          "inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors bg-input",

    # Data display
    "Table":           "w-full caption-bottom text-sm",
    "TableHeader":     "border-b bg-muted/50",
    "TableBody":       "[&_tr:last-child]:border-0",
    "TableRow":        "border-b transition-colors hover:bg-muted/50",
    "TableHead":       "h-10 px-2 text-left align-middle font-medium text-muted-foreground",
    "TableCell":       "p-2 align-middle",
    "DataTable":       "w-full overflow-auto rounded-lg border",

    # Navigation
    "Tabs":            "w-full",
    "TabsList":        "inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground",
    "TabsTrigger":     "inline-flex items-center justify-center rounded-md px-3 py-1 text-sm font-medium transition-all",
    "TabsContent":     "mt-2",

    # Feedback
    "Badge":           "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors bg-secondary text-secondary-foreground",
    "Skeleton":        "animate-pulse rounded-md bg-muted",
    "Alert":           "relative w-full rounded-lg border px-4 py-3 text-sm",

    # Dialog
    "Dialog":          "",
    "DialogContent":   "fixed left-[50%] top-[50%] z-50 grid w-full max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 border bg-background p-6 shadow-lg rounded-lg",
    "DialogHeader":    "flex flex-col space-y-1.5 text-center sm:text-left",
    "DialogTitle":     "text-lg font-semibold leading-none tracking-tight",
    "DialogFooter":    "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2",

    # Icons (lucide) → show as placeholder box
    "Hash":            "h-4 w-4 text-muted-foreground inline-block",
    "Inbox":           "h-8 w-8 text-muted-foreground inline-block",
    "Search":          "h-4 w-4 text-muted-foreground inline-block",
    "Plus":            "h-4 w-4 inline-block",
    "Check":           "h-4 w-4 inline-block",
    "Loader2":         "h-4 w-4 animate-spin inline-block",
}

# Some components should use semantic HTML tags instead of <div>
_COMPONENT_TAGS: dict[str, str] = {
    "Button": "button",
    "Input": "input",
    "Textarea": "textarea",
    "Label": "label",
    "Table": "table",
    "TableHeader": "thead",
    "TableBody": "tbody",
    "TableRow": "tr",
    "TableHead": "th",
    "TableCell": "td",
    "Badge": "span",
    "Alert": "div",
}


def _component_tag(name: str) -> str:
    """Return the HTML tag to use for a given React component name."""
    return _COMPONENT_TAGS.get(name, "div")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reverse_compile_project(output_dir: str) -> list[dict[str, Any]]:
    """Scan src/app/**/page.tsx and convert each to an AHTML page dict.

    Returns a list of ``{ pageId, route, title, html }`` dicts ready for
    ``ahtml_storage.save_pages()``.
    """
    root = Path(output_dir)
    app_dir = root / "src" / "app"
    if not app_dir.exists():
        logger.warning("No src/app directory in %s", output_dir)
        return []

    pages: list[dict[str, Any]] = []
    for page_file in sorted(app_dir.rglob("page.tsx")):
        if "node_modules" in str(page_file):
            continue

        try:
            tsx = page_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Derive route from file path relative to app_dir
        rel = page_file.relative_to(app_dir)
        route_parts = list(rel.parent.parts)  # e.g. ["users", "[id]"]
        route = "/" + "/".join(route_parts) if route_parts and route_parts != ["."] else "/"

        # Skip route groups like (dashboard) — unwrap them
        route = re.sub(r'/\([^)]+\)', '', route)
        route = route or "/"

        page_id = _route_to_page_id(route)
        title = _extract_title(tsx, route)

        html = tsx_to_ahtml_html(tsx, page_id, route, title)
        if not html:
            continue

        pages.append({
            "pageId": page_id,
            "route": route,
            "title": title,
            "html": html,
        })

    logger.info("Reverse-compiled %d pages from %s", len(pages), output_dir)
    return pages


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------


def tsx_to_ahtml_html(
    tsx: str,
    page_id: str,
    route: str,
    title: str,
) -> str | None:
    """Convert a single page.tsx string to an AHTML HTML document."""

    # Step 1: Extract data sources from useQuery calls
    data_sources = _extract_data_sources(tsx)

    # Step 2: Extract the JSX return block
    jsx = _extract_jsx_return(tsx)
    if not jsx:
        logger.debug("Could not extract JSX from page %s", page_id)
        return None

    # Step 3: Convert JSX to HTML
    html_body = _jsx_to_html(jsx)

    # Step 4: Build full AHTML document
    meta_tags = _build_meta_tags(data_sources)

    auth_attr = ""
    if "'use client'" in tsx or '"use client"' in tsx:
        # Client components with useSession likely need auth
        if "useSession" in tsx or "session" in tsx.lower():
            auth_attr = ' data-auth-required="true"'

    doc = (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'  <meta charset="utf-8" />\n'
        f'  <title>{_escape_html(title)}</title>\n'
        f'{meta_tags}'
        f'</head>\n'
        f'<body data-page-id="{page_id}" data-route="{route}"{auth_attr}>\n'
        f'{html_body}\n'
        f'</body>\n'
        f'</html>\n'
    )
    return doc


# ---------------------------------------------------------------------------
# JSX extraction
# ---------------------------------------------------------------------------


def _extract_jsx_return(tsx: str) -> str | None:
    """Extract the JSX content from the component's return(...) statement.

    Skips ``return`` inside nested functions (queryFn, useEffect, callbacks)
    by tracking brace depth to find the top-level component body.
    """
    # Strategy: find the component function, then find its top-level return.
    # The component is typically: export default function Name() { ... }
    # or: function Name() { ... }
    # We look for `return (` where the preceding `{` depth == 1 (component body).

    # Find the component function opening brace
    comp_match = re.search(
        r'(?:export\s+default\s+)?function\s+\w+\s*\([^)]*\)\s*\{',
        tsx,
    )
    if not comp_match:
        # Arrow function: const Name = () => { ... }
        comp_match = re.search(
            r'(?:export\s+default\s+)?(?:const|let)\s+\w+\s*=\s*(?:\([^)]*\)|[^=])\s*=>\s*\{',
            tsx,
        )
    if not comp_match:
        return None

    body_start = comp_match.end()  # Position right after opening {

    # Now scan forward, tracking brace depth.
    # At depth 0 (relative to component body), a `return (` is the JSX return.
    depth = 0
    i = body_start
    while i < len(tsx):
        ch = tsx[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            if depth == 0:
                break  # End of component body
            depth -= 1
        elif depth == 0 and tsx[i:i + 6] == 'return':
            # Check if this is `return (` with JSX
            rest = tsx[i + 6:].lstrip()
            if rest.startswith('('):
                paren_start = tsx.index('(', i + 6) + 1
                paren_depth = 1
                j = paren_start
                while j < len(tsx) and paren_depth > 0:
                    if tsx[j] == '(':
                        paren_depth += 1
                    elif tsx[j] == ')':
                        paren_depth -= 1
                    j += 1
                if paren_depth == 0:
                    return tsx[paren_start:j - 1].strip()
            elif rest.startswith('<'):
                # return <div>...</div>; — find end of JSX
                # Simple: take until the matching closing tag or semicolon at depth 0
                jsx_start = tsx.index('<', i + 6)
                # Use bracket matching for < >
                tag_match = re.match(r'<(\w+)', rest)
                if tag_match:
                    closing = f'</{tag_match.group(1)}>'
                    close_idx = tsx.find(closing, jsx_start)
                    if close_idx >= 0:
                        return tsx[jsx_start:close_idx + len(closing)].strip()
        i += 1

    return None


# ---------------------------------------------------------------------------
# JSX → HTML conversion
# ---------------------------------------------------------------------------


def _jsx_to_html(jsx: str) -> str:
    """Convert JSX string to HTML, handling common React patterns."""
    html = jsx

    # 1. Remove data-source-file and data-source-line attributes (runtime injector noise)
    html = re.sub(r'\s+data-source-file="[^"]*"', '', html)
    html = re.sub(r'\s+data-source-line="[^"]*"', '', html)

    # 2. className → class
    html = re.sub(r'\bclassName=', 'class=', html)

    # 3. Convert JSX expression attributes: prop={value} → prop="value"
    # Handle string expressions: class={"some-class"}
    html = re.sub(r'=\{"([^"{}]+)"\}', r'="\1"', html)
    html = re.sub(r"=\{'([^'{}]+)'\}", r'="\1"', html)

    # 4. Convert template literal classNames: class={`...`}
    # Extract just the static part, drop ${} expressions
    def _simplify_template(m: re.Match) -> str:
        template = m.group(1)
        # Remove ${...} expressions
        static = re.sub(r'\$\{[^}]+\}', '', template)
        static = re.sub(r'\s+', ' ', static).strip()
        return f'class="{static}"'
    html = re.sub(r'class=\{`([^`]*)`\}', _simplify_template, html)

    # 5. Convert ternary class expressions: class={condition ? "a" : "b"} → class="a b"
    def _merge_ternary_class(m: re.Match) -> str:
        expr = m.group(1)
        # Extract quoted strings from ternary
        strings = re.findall(r'"([^"]*)"', expr)
        # Merge all classes
        all_classes = ' '.join(strings)
        # Deduplicate
        unique = ' '.join(dict.fromkeys(all_classes.split()))
        return f'class="{unique}"'
    html = re.sub(r'class=\{([^}]+\?[^}]+)\}', _merge_ternary_class, html)

    # 6. Strip remaining JSX expression attributes (e.g. onClick={...}, style={...})
    # But preserve data-* attributes
    html = re.sub(r'\s+(?:on[A-Z]\w+|ref|key|style|dangerouslySetInnerHTML)=\{[^}]*\}', '', html)

    # 7. Convert {/* comments */} to HTML comments
    html = re.sub(r'\{/\*\s*(.*?)\s*\*/\}', r'<!-- \1 -->', html)

    # 8. Handle .map() expressions → keep one iteration
    html = _handle_map_expressions(html)

    # 9. Handle conditional rendering: {condition && (<div>...</div>)}
    html = _handle_conditionals(html)

    # 10. Replace remaining {expression} with placeholder text
    # But not inside attributes
    html = _replace_expressions(html)

    # 11. Convert self-closing JSX components: <Component /> → <div data-component="Component"></div>
    # Known HTML self-closing tags (leave as-is)
    void_tags = {'img', 'input', 'br', 'hr', 'meta', 'link', 'area', 'base', 'col', 'embed', 'source', 'track', 'wbr'}
    def _convert_self_closing(m: re.Match) -> str:
        tag = m.group(1)
        attrs = m.group(2).strip()
        if tag.lower() in void_tags:
            return m.group(0)  # Keep as-is
        if tag[0].isupper():
            style_cls = _COMPONENT_STYLES.get(tag, "")
            if style_cls and attrs and 'class="' in attrs:
                existing_match = re.search(r'class="([^"]*)"', attrs)
                if existing_match:
                    merged = style_cls + ' ' + existing_match.group(1)
                    attrs = attrs[:existing_match.start()] + f'class="{merged}"' + attrs[existing_match.end():]
                attr_str = f' {attrs}'
            elif style_cls:
                attr_str = f' class="{style_cls}"' + (f' {attrs}' if attrs else '')
            else:
                attr_str = f' {attrs}' if attrs else ''
            return f'<{_component_tag(tag)} data-component="{tag}"{attr_str}></{_component_tag(tag)}>'
        return f'<{tag} {attrs}></{tag}>' if attrs else f'<{tag}></{tag}>'
    html = re.sub(r'<(\w+)((?:\s+[^>]*?)?)?\s*/>', _convert_self_closing, html)

    # 12. Convert JSX component tags: <Card> → styled div
    def _convert_component_open(m: re.Match) -> str:
        tag = m.group(1)
        attrs = m.group(2) or ''
        style_cls = _COMPONENT_STYLES.get(tag, "")
        # Merge style classes with any existing class attribute
        if style_cls:
            existing_match = re.search(r'class="([^"]*)"', attrs)
            if existing_match:
                merged = style_cls + ' ' + existing_match.group(1)
                attrs = attrs[:existing_match.start()] + f'class="{merged}"' + attrs[existing_match.end():]
            else:
                attrs = f' class="{style_cls}"' + attrs
        return f'<{_component_tag(tag)} data-component="{tag}"{attrs}>'
    html = re.sub(r'<([A-Z]\w+)((?:\s+[^>]*)?)>', _convert_component_open, html)

    # Handle closing tags
    def _convert_component_close(m: re.Match) -> str:
        tag = m.group(1)
        return f'</{_component_tag(tag)}>'
    html = re.sub(r'</([A-Z]\w+)>', _convert_component_close, html)

    # 13. Remove JSX fragments: <> → nothing, </> → nothing
    html = re.sub(r'<>', '', html)
    html = re.sub(r'</>', '', html)

    # 14. Clean up any remaining {expression} inside attributes
    html = re.sub(r'=\{[^}]*\}', '=""', html)

    # 15. Clean up whitespace
    html = re.sub(r'\n{3,}', '\n\n', html)

    return html.strip()


def _handle_map_expressions(html: str) -> str:
    """Convert {items.map(item => (...))} → keep the inner content once."""
    # Simple pattern: {expr.map((item) => ( <jsx> ))}
    # We extract the inner JSX and include it once
    pattern = r'\{[\w.]+\.map\(\s*\(?[\w,\s{}:]+\)?\s*=>\s*\(?'

    result = html
    for m in re.finditer(pattern, html):
        start = m.end()
        # Find matching closing
        depth_paren = 1
        depth_brace = 0
        i = start
        content_start = start
        while i < len(html):
            ch = html[i]
            if ch == '(':
                depth_paren += 1
            elif ch == ')':
                depth_paren -= 1
                if depth_paren == 0:
                    # Find the closing }
                    j = i + 1
                    while j < len(html) and html[j] in ' \n\t':
                        j += 1
                    if j < len(html) and html[j] == ')':
                        j += 1
                    while j < len(html) and html[j] in ' \n\t':
                        j += 1
                    if j < len(html) and html[j] == '}':
                        j += 1
                    inner = html[content_start:i].strip()
                    # Replace the whole .map expression with the inner content
                    result = result[:m.start()] + inner + result[j:]
                    break
            elif ch == '{':
                depth_brace += 1
            elif ch == '}':
                if depth_brace > 0:
                    depth_brace -= 1
                else:
                    # Unmatched brace — .map without parens around body
                    inner = html[content_start:i].strip()
                    result = result[:m.start()] + inner + result[i + 1:]
                    break
            i += 1
        # Only process first match to avoid offset issues
        break

    return result


def _handle_conditionals(html: str) -> str:
    """Convert {condition && (<div>...</div>)} → include the JSX part."""
    # Pattern: {expr && ( <jsx> )}
    pattern = r'\{[^}]*&&\s*\('
    result = html
    for m in re.finditer(pattern, html):
        start = m.end()
        depth = 1
        i = start
        while i < len(html) and depth > 0:
            if html[i] == '(':
                depth += 1
            elif html[i] == ')':
                depth -= 1
            i += 1
        if depth == 0:
            inner = html[start:i - 1].strip()
            # Find closing }
            j = i
            while j < len(html) and html[j] in ' \n\t':
                j += 1
            if j < len(html) and html[j] == '}':
                j += 1
            result = result[:m.start()] + inner + result[j:]
            break  # One at a time to avoid offset issues

    # Simple form without parens: {condition && <div>text</div>}
    result = re.sub(
        r'\{[^{}]*&&\s*(<[^{}]+>)\}',
        r'\1',
        result,
    )

    return result


def _replace_expressions(html: str) -> str:
    """Replace {expression} in text content with readable placeholders."""
    # Don't replace inside tags (attribute values)
    # Simple heuristic: replace {expr} that's NOT preceded by =
    def _expr_replacer(m: re.Match) -> str:
        expr = m.group(1).strip()
        if not expr or expr.startswith('/'):
            return m.group(0)
        # Clean up the expression for display
        # e.g. "item.name" → "{{item.name}}"
        # e.g. "stats.totalUsers.toLocaleString()" → "{{stats.totalUsers}}"
        clean = re.sub(r'\.\w+\([^)]*\)', '', expr)  # strip method calls
        clean = re.sub(r'\s*\|\|\s*["\'][^"\']*["\']', '', clean)  # strip || "default"
        clean = clean.strip()
        if clean:
            return f'{{{{{clean}}}}}'  # {{expr}}
        return '...'

    # Match {expression} that's not an attribute value (not preceded by =)
    result = re.sub(r'(?<!=)\{([^{}]+)\}', _expr_replacer, html)
    return result


# ---------------------------------------------------------------------------
# Data source extraction
# ---------------------------------------------------------------------------


def _extract_data_sources(tsx: str) -> list[dict[str, str]]:
    """Extract useQuery calls → data source definitions."""
    sources: list[dict[str, str]] = []

    # Pattern: useQuery({ queryKey: ["name", ...], queryFn: async () => { fetch("/api/...") } })
    for m in re.finditer(
        r'useQuery\(\s*\{\s*queryKey:\s*\["(\w+)"',
        tsx,
    ):
        name = m.group(1)
        # Find the fetch URL in the queryFn
        # Look ahead for fetch("/api/...")
        rest = tsx[m.end():m.end() + 500]
        url_match = re.search(r'fetch\(\s*["`\']([^"`\']+)["`\']', rest)
        if url_match:
            path = url_match.group(1)
        else:
            # Try template literal: fetch(`/api/.../${id}`)
            url_match = re.search(r'fetch\(\s*`([^`]+)`', rest)
            path = url_match.group(1) if url_match else f"/api/{name}"

        # Determine method (default GET)
        method = "GET"
        method_match = re.search(r'method:\s*["\'](\w+)["\']', rest)
        if method_match:
            method = method_match.group(1)

        sources.append({"name": name, "method": method, "path": path})

    return sources


def _build_meta_tags(data_sources: list[dict[str, str]]) -> str:
    """Build <meta> tags for AHTML data source definitions."""
    if not data_sources:
        return ''

    lines = []
    for ds in data_sources:
        name = _escape_html(ds["name"])
        method = _escape_html(ds["method"])
        path = _escape_html(ds["path"])
        lines.append(
            f'  <meta data-source="{name}" '
            f'data-source-method="{method}" '
            f'data-source-path="{path}" />'
        )
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_to_page_id(route: str) -> str:
    """Convert route path to a page ID slug."""
    page_id = route.strip('/')
    if not page_id:
        return "home"
    # Replace / with - and [param] with param
    page_id = page_id.replace('/', '-')
    page_id = re.sub(r'\[(\w+)\]', r'\1', page_id)
    return page_id


def _extract_title(tsx: str, route: str) -> str:
    """Extract a human-readable title from the component or route."""
    # Try to find a title string in the JSX
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', tsx)
    if m:
        title = m.group(1).strip()
        if title and not title.startswith('{'):
            return title

    # Try page heading
    m = re.search(r'title[=:]?\s*["\']([^"\']+)["\']', tsx)
    if m:
        return m.group(1)

    # Derive from route
    parts = route.strip('/').split('/')
    parts = [p for p in parts if not p.startswith('[')]
    if parts:
        return parts[-1].replace('-', ' ').title()
    return "Home"


def _escape_html(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )
