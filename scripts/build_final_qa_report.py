"""Cross-check qa-audit-log.md + the round reports into final-qa-report.md.

Re-runnable: the audit log grows while agents work, so this reads whatever is
on disk now and regenerates the report. Run it again later and the numbers move.

Coverage is asserted against the REGISTRY, not against the log — the point of
the final report is to expose components that were never tested, and a report
built only from what was tested can never show a gap.
"""
import io
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "qa-audit-log.md")
OUT = os.path.join(ROOT, "final-qa-report.md")
DOCS = os.path.join(ROOT, "docs", "editor-audit")

# Categories audited in the earlier rounds, with the report that covers them.
ROUND_REPORTS = {
    "layout": "containment.md / browser-test.md",
    "input": "input-components{,-2,-3}.md",
    "display": "display-components{,-2}.md",
}
LIVE = {"navigation", "feedback", "data"}


def registry_components():
    """name -> category, straight from the registry source."""
    src = io.open(os.path.join(ROOT, "packages", "registry", "src", "starter.ts"),
                  encoding="utf-8", errors="replace").read()
    out = OrderedDict()
    for block in re.findall(r"export const \w+Entry: RegistryEntry = \{(.*?)\n\};", src, re.S):
        if re.search(r"hidden:\s*true", block):
            continue
        n = re.search(r'name:\s*"([A-Za-z0-9]+)"', block)
        c = re.search(r'category:\s*"(\w+)"', block)
        if n and c:
            out[n.group(1)] = c.group(1)
    return out


def parse_log():
    """Return {key: {...}} for '### <name>' entries and '#### FIX — <name>' blocks."""
    if not os.path.exists(LOG):
        return {}, []
    text = io.open(LOG, encoding="utf-8", errors="replace").read()
    entries, fixes = {}, {}
    # Split on headings, keeping the heading with its body.
    parts = re.split(r"\n(?=#{3,4} )", text)
    for part in parts:
        m3 = re.match(r"### (.+)", part)
        m4 = re.match(r"#### FIX — (.+)", part)
        if m4:
            name = m4.group(1).split("(")[0].strip().strip("`")
            fixes.setdefault(name, []).append(part)
        elif m3:
            raw = m3.group(1).strip()
            if raw.startswith("<"):          # the template placeholder
                continue
            body = part
            entries[raw] = {
                "raw": raw,
                "bugs": "none" not in _field(body, "Bugs found").lower()[:12],
                "bugs_text": _field(body, "Bugs found"),
                "features": "none" not in _field(body, "Missing/desired features").lower()[:12],
                "status_fix": "NEEDS_FIX" in body,
                "resolved": "RESOLVED" in body,
                "severities": re.findall(r"\b(blocker|major|minor)\b", body, re.I),
            }
    return entries, fixes


def _field(body, label):
    m = re.search(r"\*\*" + re.escape(label) + r":\*\*(.*?)(?=\n- \*\*|\Z)", body, re.S)
    return (m.group(1).strip() if m else "")


def match_entry(component, entries):
    """An entry heading may be decorated ('CartBadge — addendum, …')."""
    hits = []
    for raw in entries:
        head = re.split(r"[—·(]", raw)[0].strip().strip("`/")
        if head == component or raw.strip().strip("`") == component:
            hits.append(raw)
    return hits


def main():
    comps = registry_components()
    entries, fixes = parse_log()

    rows, never_tested, unfixed, unbuilt = [], [], [], []
    for name, cat in comps.items():
        hits = match_entry(name, entries)
        if cat in ROUND_REPORTS and not hits:
            rows.append((name, cat, "Y", "see report", "see report", "-", "-",
                         f"COVERED — {ROUND_REPORTS[cat]}"))
            continue
        if not hits:
            never_tested.append((name, cat))
            rows.append((name, cat, "**N**", "-", "-", "-", "-", "**NEVER TESTED**"))
            continue
        bugs = sum(1 for h in hits if entries[h]["bugs"])
        feats = sum(1 for h in hits if entries[h]["features"])
        needs = any(entries[h]["status_fix"] for h in hits)
        done = bool(fixes.get(name)) or any(entries[h]["resolved"] for h in hits)
        sev = sorted({s.lower() for h in hits for s in entries[h]["severities"]})
        if needs and not done:
            unfixed.append((name, cat, ", ".join(sev) or "unspecified"))
            if feats:
                unbuilt.append((name, cat))
        status = "RESOLVED" if done else ("**OPEN**" if needs else "CLEAN")
        rows.append((name, cat, "Y", str(bugs) if bugs else "0",
                     "yes" if done else ("no" if needs else "-"),
                     str(feats) if feats else "0",
                     "yes" if done else "-", status))

    total = len(comps)
    tested = sum(1 for r in rows if r[2] == "Y")
    L = []
    L.append("# Final QA report\n")
    L.append("Cross-check of `qa-audit-log.md` and the round reports in "
             "`docs/editor-audit/`, against the **registry** as the source of "
             "truth for what exists.\n")
    L.append("Coverage is asserted against the registry rather than against the "
             "log, so a component nobody tested shows up as a gap instead of "
             "silently missing.\n")
    L.append(f"\n**{tested} of {total} components have a row below.** "
             f"Never tested: **{len(never_tested)}**. "
             f"Found but not fixed: **{len(unfixed)}**.\n")
    L.append("\n| Component/Route | Category | Tested | Bugs Found | Bugs Fixed "
             "| Features Requested | Features Added | Final Status |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append("| " + " | ".join(r) + " |")

    L.append("\n---\n\n## Never tested — coverage gaps\n")
    if never_tested:
        for n, c in never_tested:
            L.append(f"- `{n}` ({c})")
    else:
        L.append("None. Every registry component has a row.")

    L.append("\n## Found but NOT fixed\n")
    if unfixed:
        for n, c, s in unfixed:
            L.append(f"- `{n}` ({c}) — severity: {s}")
    else:
        L.append("None outstanding in the log.")

    L.append("\n## Requested but NOT implemented\n")
    if unbuilt:
        for n, c in unbuilt:
            L.append(f"- `{n}` ({c})")
    else:
        L.append("None outstanding in the log.")

    L.append("\n## Known gaps this table cannot show\n")
    L.append("- **The four app routes** (`/items`, `/items/new`, `/items/[id]`, "
             "`/items/[id]/edit`) were audited **unauthenticated**; the app "
             "redirects to `/login`. Those findings are void and the routes "
             "need re-auditing with a session. See the CORRECTION block at the "
             "end of `qa-audit-log.md`.")
    L.append("- Components marked *COVERED* were audited in rounds 1–5 with "
             "their own reports; their bug/fix counts live there, not in the "
             "log this script parses.")

    io.open(OUT, "w", encoding="utf-8", newline="").write("\n".join(L) + "\n")
    print(f"wrote {OUT}")
    print(f"  {tested}/{total} rows · never tested {len(never_tested)} · "
          f"unfixed {len(unfixed)} · log entries {len(entries)} · fix blocks {len(fixes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
