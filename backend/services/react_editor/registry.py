"""The component registry — what a page can be made of, in a person's words.

One definition per kind of thing: how it is found in the palette (label,
category, words people search by), what it looks like when added (JSX against
the app's UI kit and SDK), and which of its settings are shown to whom. The
settings a first-time user sees are named by outcome ("Colour", "Opens page");
everything else sits under Advanced. The generator, the editor and Smith all
read this one list, so a kind that is here is a kind that compiles.

Settings targets are structural, never free code:

* ``{"kind": "text"}``                     — the element's own text
* ``{"kind": "prop", "name": ...}``        — one attribute, as a string
* ``{"kind": "page", "name": ...}``        — an attribute that names a page (href)
* ``{"kind": "workflow", "name": ...}``    — an attribute that names a workflow
* ``{"kind": "classGroup", "group": ...}`` — one Tailwind class family (spacing, size…)
"""
from __future__ import annotations

from typing import Any

REGISTRY_VERSION = "1"

_BUTTON_VARIANTS = [
    {"value": "default", "label": "Primary"},
    {"value": "secondary", "label": "Secondary"},
    {"value": "outline", "label": "Outlined"},
    {"value": "ghost", "label": "Plain"},
    {"value": "destructive", "label": "Danger"},
    {"value": "link", "label": "Looks like a link"},
]
_BUTTON_SIZES = [
    {"value": "sm", "label": "Small"},
    {"value": "default", "label": "Normal"},
    {"value": "lg", "label": "Large"},
]
_BADGE_VARIANTS = [
    {"value": "default", "label": "Primary"},
    {"value": "secondary", "label": "Neutral"},
    {"value": "success", "label": "Success"},
    {"value": "warning", "label": "Warning"},
    {"value": "destructive", "label": "Danger"},
    {"value": "outline", "label": "Outlined"},
    {"value": "muted", "label": "Muted"},
]
_INPUT_TYPES = [
    {"value": "text", "label": "Text"},
    {"value": "email", "label": "Email address"},
    {"value": "number", "label": "Number"},
    {"value": "password", "label": "Password"},
    {"value": "date", "label": "Date"},
    {"value": "tel", "label": "Phone"},
]


def _s(key: str, label: str, control: str, target: dict[str, Any], *, section: str = "simple",
       options: list[dict[str, str]] | None = None, help: str = "", default: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"key": key, "label": label, "control": control, "target": target, "section": section}
    if options is not None:
        spec["options"] = options
    if help:
        spec["help"] = help
    if default is not None:
        spec["default"] = default
    return spec


def _c(id: str, label: str, category: str, description: str, *, search: list[str], types: list[str],
       jsx: str, imports: list[dict[str, Any]] | None = None, container: bool = False,
       settings: list[dict[str, Any]] | None = None, events: list[dict[str, Any]] | None = None,
       guide: str | None = None, status: str = "ready") -> dict[str, Any]:
    return {
        "id": id, "label": label, "category": category, "description": description,
        "search": search, "match": {"types": types}, "jsx": jsx, "imports": imports or [],
        "container": container, "settings": settings or [], "events": events or [],
        "guide": guide, "status": status,
    }


TEXT = _s("text", "Text", "text", {"kind": "text"})

COMPONENTS: list[dict[str, Any]] = [
    # ---- Layout -----------------------------------------------------------
    _c("section", "Section", "Layout", "A block of the page with space around it",
       search=["group", "block", "area", "div"], types=["section", "div", "main", "article", "aside"],
       jsx='<section className="space-y-4">\n</section>', container=True),
    _c("card", "Card", "Layout", "A framed box for related content",
       search=["panel", "box", "tile"], types=["Card"],
       jsx='<Card>\n  <CardHeader>\n    <CardTitle>Card title</CardTitle>\n  </CardHeader>\n  <CardContent>\n  </CardContent>\n</Card>',
       imports=[{"source": "@/components/ui/card", "names": ["Card", "CardHeader", "CardTitle", "CardContent"]}],
       container=True),
    _c("row", "Side by side", "Layout", "Things placed next to each other in a row",
       search=["row", "horizontal", "flex", "inline"], types=[],
       jsx='<div className="flex items-center gap-4">\n</div>', container=True),
    _c("columns", "Columns", "Layout", "Two columns on wide screens, stacked on phones",
       search=["grid", "two columns", "split", "half"], types=[],
       jsx='<div className="grid gap-4 md:grid-cols-2">\n</div>', container=True,
       settings=[_s("cols", "Columns on wide screens", "select", {"kind": "classGroup", "group": "gridCols"},
                    options=[{"value": "md:grid-cols-2", "label": "2"}, {"value": "md:grid-cols-3", "label": "3"},
                             {"value": "md:grid-cols-4", "label": "4"}])]),
    _c("stack", "Stack", "Layout", "Things placed one under another with even spacing",
       search=["vertical", "list", "column"], types=[],
       jsx='<div className="flex flex-col gap-4">\n</div>', container=True),
    _c("divider", "Divider", "Layout", "A thin line between two parts",
       search=["line", "separator", "rule", "hr"], types=["Separator", "hr"],
       jsx="<Separator />", imports=[{"source": "@/components/ui/separator", "names": ["Separator"]}]),
    _c("spacer", "Spacer", "Layout", "Empty space between things",
       search=["gap", "space", "padding"], types=[],
       jsx='<div className="h-6" aria-hidden="true" />',
       settings=[_s("height", "Height", "select", {"kind": "classGroup", "group": "height"},
                    options=[{"value": "h-2", "label": "Small"}, {"value": "h-6", "label": "Medium"},
                             {"value": "h-12", "label": "Large"}])]),
    # ---- Content ----------------------------------------------------------
    _c("heading", "Heading", "Content", "A title for the page or a section",
       search=["title", "header", "h1", "h2"], types=["h1", "h2", "h3", "h4", "CardTitle"],
       jsx='<h2 className="text-xl font-semibold text-foreground">New heading</h2>',
       settings=[TEXT,
                 _s("size", "Size", "select", {"kind": "classGroup", "group": "textSize"},
                    options=[{"value": "text-lg", "label": "Small"}, {"value": "text-xl", "label": "Medium"},
                             {"value": "text-2xl", "label": "Large"}, {"value": "text-3xl", "label": "Extra large"}])]),
    _c("text", "Text", "Content", "A paragraph or a line of text",
       search=["paragraph", "label", "caption", "description", "p", "span"],
       types=["p", "span", "label", "CardDescription", "Label", "AlertDescription", "AlertTitle", "small", "em", "strong"],
       jsx='<p className="text-sm text-muted-foreground">Some text</p>',
       settings=[TEXT,
                 _s("size", "Size", "select", {"kind": "classGroup", "group": "textSize"},
                    options=[{"value": "text-xs", "label": "Tiny"}, {"value": "text-sm", "label": "Small"},
                             {"value": "text-base", "label": "Normal"}, {"value": "text-lg", "label": "Large"}]),
                 _s("tone", "Colour", "select", {"kind": "classGroup", "group": "textColor"},
                    options=[{"value": "text-foreground", "label": "Normal"},
                             {"value": "text-muted-foreground", "label": "Muted"},
                             {"value": "text-primary", "label": "Accent"},
                             {"value": "text-destructive", "label": "Danger"}])]),
    _c("badge", "Badge", "Content", "A small coloured label, for a status",
       search=["status", "tag", "chip", "pill"], types=["Badge"],
       jsx='<Badge variant="secondary">Status</Badge>',
       imports=[{"source": "@/components/ui/badge", "names": ["Badge"]}],
       settings=[TEXT, _s("variant", "Colour", "select", {"kind": "prop", "name": "variant"},
                          options=_BADGE_VARIANTS, default="default")]),
    _c("link", "Link", "Content", "Text that opens another page",
       search=["anchor", "href", "navigate", "go to"], types=["Link", "a"],
       jsx='<Link href="/" className="text-primary underline-offset-4 hover:underline">Open page</Link>',
       imports=[{"source": "next/link", "names": ["default:Link"]}],
       settings=[TEXT, _s("href", "Opens page", "page", {"kind": "page", "name": "href"})]),
    _c("image", "Image", "Content", "A picture from a web address",
       search=["photo", "picture", "img", "logo"], types=["img", "Image"],
       jsx='<img src="https://placehold.co/600x300" alt="Describe the picture" className="rounded-lg" />',
       settings=[_s("src", "Picture address", "text", {"kind": "prop", "name": "src"}),
                 _s("alt", "Description for screen readers", "text", {"kind": "prop", "name": "alt"},
                    help="Read aloud to people who cannot see the picture.")]),
    # ---- Form -------------------------------------------------------------
    _c("form", "Form", "Form", "A form that saves information by running one of the app's workflows",
       search=["save", "submit", "create", "input", "fields", "enter"], types=["WorkflowForm"],
       jsx="", imports=[{"source": "@/sdk/client", "names": ["WorkflowForm"]}, {"source": "@/sdk", "names": ["workflows"]}],
       guide="form",
       settings=[_s("submitLabel", "Button text", "text", {"kind": "prop", "name": "submitLabel"}),
                 _s("successMessage", "Message after saving", "text", {"kind": "prop", "name": "successMessage"}),
                 _s("columns", "Layout", "select", {"kind": "prop", "name": "columns", "expr": True},
                    options=[{"value": "1", "label": "One column"}, {"value": "2", "label": "Two columns"}]),
                 _s("workflow", "Saves by running", "workflow", {"kind": "workflow", "name": "workflow"},
                    section="data")]),
    _c("text-field", "Text field", "Form", "A box to type into, with its label",
       search=["input", "textbox", "field", "email", "number"], types=["Input"],
       jsx='<div className="space-y-1.5">\n  <Label htmlFor="field">Label</Label>\n  <Input id="field" name="field" placeholder="Type here" />\n</div>',
       imports=[{"source": "@/components/ui/input", "names": ["Input"]}, {"source": "@/components/ui/label", "names": ["Label"]}],
       settings=[_s("placeholder", "Hint shown when empty", "text", {"kind": "prop", "name": "placeholder"}),
                 _s("type", "Kind of information", "select", {"kind": "prop", "name": "type"}, options=_INPUT_TYPES, default="text"),
                 _s("required", "Must be filled in", "toggle", {"kind": "prop", "name": "required", "boolean": True}, section="validation"),
                 _s("name", "Name used when sending", "text", {"kind": "prop", "name": "name"}, section="advanced")]),
    _c("text-area", "Text area", "Form", "A larger box for several lines of text",
       search=["notes", "comment", "message", "multiline"], types=["Textarea", "textarea"],
       jsx='<div className="space-y-1.5">\n  <Label htmlFor="notes">Notes</Label>\n  <Textarea id="notes" name="notes" placeholder="Type here" />\n</div>',
       imports=[{"source": "@/components/ui/textarea", "names": ["Textarea"]}, {"source": "@/components/ui/label", "names": ["Label"]}],
       settings=[_s("placeholder", "Hint shown when empty", "text", {"kind": "prop", "name": "placeholder"}),
                 _s("required", "Must be filled in", "toggle", {"kind": "prop", "name": "required", "boolean": True}, section="validation")]),
    _c("checkbox", "Checkbox", "Form", "A yes/no choice",
       search=["tick", "boolean", "toggle", "agree"], types=["Checkbox"],
       jsx='<div className="flex items-center gap-2">\n  <Checkbox id="agree" />\n  <Label htmlFor="agree">I agree</Label>\n</div>',
       imports=[{"source": "@/components/ui/checkbox", "names": ["Checkbox"]}, {"source": "@/components/ui/label", "names": ["Label"]}]),
    _c("file-input", "File upload", "Form", "Lets people attach a file — needs an upload service first",
       search=["upload", "attachment", "document"], types=[], jsx="", status="unsupported"),
    # ---- Actions ----------------------------------------------------------
    _c("button", "Button", "Actions", "Something to press",
       search=["click", "action", "cta", "press"], types=["Button", "button"],
       jsx='<Button>Button</Button>', imports=[{"source": "@/components/ui/button", "names": ["Button"]}],
       settings=[TEXT,
                 _s("variant", "Colour", "select", {"kind": "prop", "name": "variant"}, options=_BUTTON_VARIANTS, default="default"),
                 _s("size", "Size", "select", {"kind": "prop", "name": "size"}, options=_BUTTON_SIZES, default="default"),
                 _s("disabled", "Greyed out", "toggle", {"kind": "prop", "name": "disabled", "boolean": True}, section="advanced")],
       events=[{"name": "click", "label": "What happens when clicked?", "prop": "onClick"}]),
    _c("button-page", "Button that opens a page", "Actions", "A button that takes people to another page",
       search=["navigate", "go to", "open", "link button"], types=[],
       jsx='<Button asChild>\n  <Link href="/">Open page</Link>\n</Button>',
       imports=[{"source": "@/components/ui/button", "names": ["Button"]}, {"source": "next/link", "names": ["default:Link"]}]),
    _c("button-workflow", "Button that runs a workflow", "Actions", "A button that does something in the app — approve, close, delete",
       search=["run", "action", "approve", "delete", "workflow"], types=["WorkflowButton"],
       jsx="", imports=[{"source": "@/sdk/client", "names": ["WorkflowButton"]}, {"source": "@/sdk", "names": ["workflows"]}],
       guide="workflow-button",
       settings=[TEXT,
                 _s("variant", "Colour", "select", {"kind": "prop", "name": "variant"},
                    options=[{"value": "primary", "label": "Primary"}, {"value": "secondary", "label": "Secondary"},
                             {"value": "outline", "label": "Outlined"}, {"value": "ghost", "label": "Plain"},
                             {"value": "danger", "label": "Danger"}], default="primary"),
                 _s("size", "Size", "select", {"kind": "prop", "name": "size"},
                    options=[{"value": "sm", "label": "Small"}, {"value": "md", "label": "Normal"}], default="md"),
                 _s("confirm", "Ask before doing it", "text", {"kind": "prop", "name": "confirm"},
                    help="Leave empty to run straight away."),
                 _s("successMessage", "Message when done", "text", {"kind": "prop", "name": "successMessage"}),
                 _s("workflow", "Runs", "workflow", {"kind": "workflow", "name": "workflow"}, section="data")]),
    # ---- Collections ------------------------------------------------------
    _c("table", "Table", "Collections", "Rows and columns of the page's records",
       search=["list", "grid", "rows", "records", "data"], types=["Table"],
       jsx="", imports=[{"source": "@/components/ui/table",
                         "names": ["Table", "TableHeader", "TableBody", "TableRow", "TableHead", "TableCell"]}],
       guide="table"),
    _c("empty-state", "Empty state", "Collections", "What people see when there is nothing to show yet",
       search=["nothing", "placeholder", "no results", "blank"], types=[],
       jsx='<div className="rounded-lg border border-dashed border-border p-8 text-center">\n  <p className="text-sm font-medium text-foreground">Nothing here yet</p>\n  <p className="mt-1 text-sm text-muted-foreground">When there is, it will show up here.</p>\n</div>',
       container=True),
    # ---- Charts -----------------------------------------------------------
    _c("chart", "Chart", "Charts", "A bar, line, pie or other chart of the app's records",
       search=["graph", "bar", "line", "pie", "donut", "analytics", "report", "echarts", "trend"], types=["WidgetView"],
       jsx="", imports=[{"source": "@/sdk/client", "names": ["WidgetView"]}, {"source": "@/sdk", "names": ["widgets"]}],
       guide="chart",
       settings=[_s("height", "Height", "select", {"kind": "prop", "name": "height", "expr": True},
                    options=[{"value": "200", "label": "Short"}, {"value": "260", "label": "Normal"},
                             {"value": "360", "label": "Tall"}, {"value": "480", "label": "Very tall"}], default="260")]),
    _c("metric", "Number tile", "Charts", "One number — a count, a total or an average",
       search=["kpi", "stat", "count", "total", "average", "tile", "metric"], types=[],
       jsx="", imports=[{"source": "@/sdk/client", "names": ["WidgetView"]}, {"source": "@/sdk", "names": ["widgets"]}],
       guide="metric"),
    # ---- Navigation -------------------------------------------------------
    _c("tabs", "Tabs", "Navigation", "Several views in one place, one shown at a time",
       search=["switch", "sections", "views"], types=["Tabs"],
       jsx='<Tabs defaultValue="one">\n  <TabsList>\n    <TabsTrigger value="one">First</TabsTrigger>\n    <TabsTrigger value="two">Second</TabsTrigger>\n  </TabsList>\n  <TabsContent value="one">\n    <p className="text-sm text-muted-foreground">First tab</p>\n  </TabsContent>\n  <TabsContent value="two">\n    <p className="text-sm text-muted-foreground">Second tab</p>\n  </TabsContent>\n</Tabs>',
       imports=[{"source": "@/components/ui/tabs", "names": ["Tabs", "TabsList", "TabsTrigger", "TabsContent"]}],
       container=True),
    # ---- Overlays ---------------------------------------------------------
    _c("dialog", "Dialog", "Overlays", "A window that opens over the page",
       search=["modal", "popup", "confirm"], types=["Dialog"],
       jsx='<Dialog>\n  <DialogTrigger asChild>\n    <Button variant="outline">Open</Button>\n  </DialogTrigger>\n  <DialogContent>\n    <DialogHeader>\n      <DialogTitle>Dialog title</DialogTitle>\n      <DialogDescription>What this dialog is for.</DialogDescription>\n    </DialogHeader>\n  </DialogContent>\n</Dialog>',
       imports=[{"source": "@/components/ui/dialog",
                 "names": ["Dialog", "DialogTrigger", "DialogContent", "DialogHeader", "DialogTitle", "DialogDescription"]},
                {"source": "@/components/ui/button", "names": ["Button"]}],
       container=True),
    # ---- Feedback ---------------------------------------------------------
    _c("alert", "Alert", "Feedback", "A message that stands out — a warning or a note",
       search=["notice", "warning", "message", "callout", "info"], types=["Alert"],
       jsx='<Alert>\n  <AlertTitle>Heads up</AlertTitle>\n  <AlertDescription>Something worth knowing.</AlertDescription>\n</Alert>',
       imports=[{"source": "@/components/ui/alert", "names": ["Alert", "AlertTitle", "AlertDescription"]}],
       container=True,
       settings=[_s("variant", "Kind", "select", {"kind": "prop", "name": "variant"},
                    options=[{"value": "default", "label": "Note"}, {"value": "destructive", "label": "Warning"}],
                    default="default")]),
    _c("loading", "Loading placeholder", "Feedback", "Grey blocks shown while something loads",
       search=["skeleton", "spinner", "wait"], types=["Skeleton"],
       jsx='<Skeleton className="h-6 w-48" />', imports=[{"source": "@/components/ui/skeleton", "names": ["Skeleton"]}]),
]

#: Kinds by the JSX names they are recognised as on an existing page.
_BY_TYPE: dict[str, dict[str, Any]] = {}
for _comp in COMPONENTS:
    for _t in _comp["match"]["types"]:
        _BY_TYPE.setdefault(_t, _comp)


def component_for(type_name: str) -> dict[str, Any] | None:
    return _BY_TYPE.get(type_name)


def registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "components": COMPONENTS}


def palette_summary() -> str:
    """The registry as Smith reads it — one line per kind, ready to insert."""
    lines = []
    for c in COMPONENTS:
        if c["status"] != "ready" or not c["jsx"]:
            continue
        one = c["jsx"].replace("\n", " ")
        lines.append(f"- {c['label']} ({c['category']}): {one[:160]}")
    return "\n".join(lines)
