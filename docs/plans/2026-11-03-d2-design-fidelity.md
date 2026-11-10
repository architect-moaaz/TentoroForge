# DITANS D2 (Candidate web) against its Figma design (2026-11-03)

The app on forge-v3 was compared with the 110 frames of D2, the Candidate web journey. The forge-v3 copy's D2 page code is identical to the local copy, so it was rendered locally as the seeded demo candidate at 1440 px. Each screen was scored against its frame with `page_look.pixel_likeness`. All fixes below were made by hand; Smith was not used.

## 1. Why the app differed from the drawings

Every D2 screen's code still held its converted drawing. The differences came from four platform faults and how the page writers worked around them:

1. **The candidate sidebar was bound as one flat list.**
   - The drawn menu has sections (MY CAREER, ME, ACCOUNT), a group that opens ("My Jobs"), chevrons and a message count.
   - The menu rows carried no section or parent structure. The converter printed every row, sub-pages included, at the top, then empty section headings, then the sub-pages again.
   - Sub-pages have no icon, so they rendered as blank boxes.
   - This shell wraps every framed D2 screen.
2. **Pages drawn without the shell were put inside it.**
   - Onboarding (05a–05h, with its pharma and healthcare-management variants) and the journey start are drawn full screen with their own brand panel.
   - The frame chooser had no notion of an unframed drawing, so it squeezed all 24 into the sidebar and top bar. "Build your profile" scored 0.31.
3. **Every dialog was converted as an empty scrim.**
   - In a drawer or modal frame, the widest layer beside the sidebar is the full-width scrim. The converter took it as the page and dropped the panel.
   - All 18 D2 dialogs came out as about 300 characters of grey. That was 48 across the app: 18 in D2, 30 in the other portals.
   - The page writers worked around the empty parts:
     - **Withdraw** used the scrim as a "working…" screen and ran at once, with no confirmation (QA D-50). Decline and Ask for more time did the same.
     - **The timeline editors, Contact request, Edit job and the photo editor** rendered an empty grey page on desktop, or the phone form instead.
4. **Free shapes were written `relative absolute`.**
   - In Tailwind's order `relative` wins, so the layer sat in the flow over its neighbours. The menu's guide line ran through the labels.
   - There were 637 occurrences across DITANS.

Smaller faults:
- Initials took the first character of each word, so "Candidate (demo)" became "C(". This was in the shell loader and in the platform's account menu.
- The shell's search box was a fixed empty value with a change handler that did nothing.
- A loader returned the drawing's example data as a default ("Linked to: Novartis Egypt — 2 roles").
- One onboarding frame (CW-05d-SN) is bound to the Offer page.

## 2. What was fixed, and the measurement

**Platform, on `claude/smith-learns`, each with tests:**
- `a1f10fbe`: screens record `framed` (`DrawnView.framed`), and the shell wrapper shows an unframed drawing bare. A portal drawn with no shell (the phone app) keeps the frame it had.
- `58ace2f1`: one position per element, and an auto-layout row holds a child placed in it.
- `7527326a` and `df5c9a96`:
  - the page column is chosen only among laid-out layers;
  - a scrim across the frame with panels drawn after it makes the screen a dialog: fixed over the window, the scrim filling it, a drawer on its drawn edge, a modal centred;
  - the dialog is found by drawing order too, because free frames mark no layer absolute.
- `6585fccd`: account initials are letters only.

**DITANS, Blueprint versions 1661–1668, hand edits only:**
- **Candidate shell:**
  - the menu is rebuilt from the drawing's own markup: sections, the opening group, chevrons, the message count read from unread conversations, the active highlight;
  - the breadcrumb follows the page you're on;
  - the search box opens the job search with what was typed;
  - initials are letters only.
- **Bare pages:** the 24 unframed D2 pages now render bare.
- **Dialogs:** all 18 D2 dialogs are converted again with the fixed reader.
  - 10 were bound by Forge's converter. API credit then ran out.
  - The other 8 were bound by hand through the converter's own `params.apply` step, with the binding answer written by hand.
  - Each is wired to its page's existing form state and handlers.
  - Withdraw, Decline and Ask for more time now confirm first. On desktop, the editors open their drawn drawer.
- **Empty names:** the D2 loaders now say what an empty name shows. The honest SDK types (`47940c36`) surfaced the remaining `fullName` null sites.

**Measured, at 1440 px as the demo candidate:**

| | Before | After |
|---|---|---|
| Mean likeness, 106 mapped frames (route screenshots) | 0.66 | 0.77 |
| Frames at 0.85 or better | 52 | 66 |
| Frames below 0.6 | 41 | 20 |
| 18 dialogs, captured open | 0.24 (never shown) | 0.79 (all 18 open) |

Most of the remaining gap in a dialog is behind it: the drawing shows the page dimmed, while the app shows the dimmed shell. Most of the remaining gap on a page is data, such as one job listed instead of the drawing's four, or an empty search box.

Withdraw was tested by clicking: pressing Withdraw shows the drawn confirmation, and "Keep application" closes it with the application still `applied`.

**Not done:**
- The 30 dialogs in the other portals still need converting again.
- The CW-05d-SN mapping is unchanged.

## 3. Why Forge and Smith did not catch it, and what they need

**Why:**

- **Nothing compared the built app with the drawing.**
  - The build's visual check (`page_look`) needs a model call. DITANS was built by hand while API credit was out (2026-10-30), so it never ran.
  - Even when it runs, it compares a screen's content area with the page in its rest state. It never sees the shell, and never sees a dialog open.
  - Smith's `run_checks drawing` checks coverage (does every frame have a page), not likeness.
  - Smith's `open_page look` sees one page when asked.
- **The converter failed silently.**
  - An empty dialog is valid markup. The binder's "lost" guard compares rows of a list; it cannot notice that a panel was never read.
  - The shell binding passed the same guard because its sections were static text.
- **Page writers worked around a broken part instead of reporting it.**
  - Given a dialog part with no props, the writer used it as a busy screen, or used the phone form on desktop. It left comments saying so, such as "The desktop drawing is only the scrim behind this form", and nothing read them.
- **Framing was never a decision.** The frame chooser only knew "which portal", so a full-screen drawing could not be expressed.
- **Smith could not repair a conversion.** It has no tool to re-read a frame or re-bind a drawn view. It can only edit code, which the next projection overwrites.

**What Forge needs:**

1. **A likeness gate for drawn apps.** After a build and after every turn, render each mapped frame's page as a real person of the role. Open each dialog through its trigger, or through a `?dialog=` state the page exposes. Score it against the frame, and hand screens below a threshold to the owning writer, with the side-by-side image as feedback. The measurement used here, `pixel_likeness` and `side_by_side` over Playwright captures, is that gate, and it ran without a model.
2. **Converter self-checks that refuse rather than accept.**
   - A dialog frame whose screen has no panel is refused.
   - A drawn view whose rendered size is a fraction of its frame's is refused.
   - A shell whose bound menu renders a different number of rows than the drawing is refused.
3. **Writers report a broken drawn part as a platform fault** (`report_platform_fault`) instead of working around it, and the fault blocks the page from being accepted.
4. **Framing and dialogs are part of the definition** (`framed`, dialog screens). That is done now.

**What Smith needs:**

1. **A whole-app likeness check** (`run_checks drawing` with the capture and score above) that ranks screens by how far they are from the drawing, so "does it match the design" gets a measured answer.
2. **A tool to convert one frame again** (the fixed reader plus the binder) and to re-bind a drawn view, writing the Blueprint row, so a drawing fault is fixed at its source.
3. **The rule already given on `claude/smith-learns`:** "a drawn app follows its drawing" and "look at what they see". With the check above, Smith can act on it.
