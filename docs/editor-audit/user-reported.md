# User-reported issues — 2026-09-05 (from uploaded doc)

Reported by the user while click-testing the editor on the Inventory Manager project.
Cross-referenced against the automated audit; "already found" means the automated
audit independently recorded the same defect.

| # | Report | Audit cross-ref | Status |
|---|--------|-----------------|--------|
| 1 | Radius does nothing — no visible difference | `panels.md`: "Style — Padding / Radius / Shadow / Motion / Duration silently ignored by 28 components" | ALREADY FOUND |
| 2 | Calendar looks terrible | none | NEW |
| 4 | Radius scale + Elevation in Style not working | `panels.md`: "Design System writes are correct but destroyed downstream" (token pipeline) | ALREADY FOUND |
| 5 | The "today" control does nothing | none | NEW |
| 6 | Switch / Radio / Checkbox take the full width; Switch also misbehaves | related to drop-sizing leaving fixed-geometry controls unsized | NEW |
| 7 | Is FileUpload working? | none | NEW — needs test |
| 8 | Cannot add anything except Input inside a Form | `containment.md` #7: `Form.accepts` lists 6 components, refuses 127 | ALREADY FOUND |
| 9 | Every component opens as blank space; no demo/placeholder so the user knows what to do. Applies to ALL components, not one. | `containment.md` #4: 14/133 render nothing; plus the empty-Card/empty-Stack class | PARTIALLY FOUND — the "ship demo content" ask is new |

## Verbatim report

1. The Radius here is not working there is no difference changing anything
2. Calender — This calender definitely needs a fix in the looks it looks terrible
4. Radius scale and Elevation in the style is not working
5. What does this today do it is not doing anything
6. Switch , Radio , checkbox — They take the complete size , it should be exactly what is required and also , switch is also not working properly
7. check if the fileupload is wokring
8. i cannot add every component inside the form only input field i cannot add rest like checkbox and others i cannot add check this
9. Every thing i open it shows a blank space and how does user know what do do with it atleast somedemo you can put so that user will understand . THis is not a particular component this is about all component
