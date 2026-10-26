"""The parts a person can add to a phone screen, in the shape of the web editor's palette.

Each is one entry: where it is found (category, label, words people search by), what it is, and exactly what is added (code
against the phone's component kit). The parts that need no data. A box a person types into needs the screen to keep what was
typed, which an addition does not give it: those are `drawnOnly` — drawn right, but not typeable until Smith connects them to
the screen's data. Only a part from this list, exactly as written here, is accepted as an addition without the compiler; the
tests compile every entry against the real kit."""
from __future__ import annotations

from typing import Any

#: The parts that can hold others, so an addition can go inside them.
CONTAINERS = frozenset({"Screen", "Stack", "Row", "Card", "GradientBand"})


def _p(id: str, label: str, category: str, description: str, jsx: str, imports: list[str], *, search: list[str] | None = None,
       container: bool = False, drawn_only: bool = False) -> dict[str, Any]:
    return {"id": id, "label": label, "category": category, "description": description, "search": search or [], "jsx": jsx,
            "imports": imports, "container": container, "drawnOnly": drawn_only}


NL = "\n"

PALETTE: list[dict[str, Any]] = [
    # ---- Layout
    _p("card", "Card", "Layout", "A framed box for related content", f"<Card>{NL}  <Text>Card text</Text>{NL}</Card>", ["Card", "Text"],
       search=["panel", "box", "tile"], container=True),
    _p("row", "Side by side", "Layout", "Things placed next to each other in a row",
       f'<Row gap="sm">{NL}  <Text>Left</Text>{NL}  <Text>Right</Text>{NL}</Row>', ["Row", "Text"],
       search=["row", "horizontal", "inline"], container=True),
    _p("stack", "Stack", "Layout", "Things placed one under another with even spacing",
       f'<Stack gap="sm">{NL}  <Text>One</Text>{NL}  <Text>Two</Text>{NL}</Stack>', ["Stack", "Text"],
       search=["vertical", "column", "list"], container=True),
    _p("band", "Colour band", "Layout", "A band in the app's colours, for a title that leads the screen",
       f"<GradientBand>{NL}  <Text>Band text</Text>{NL}</GradientBand>", ["GradientBand", "Text"],
       search=["hero", "header", "gradient", "banner"], container=True),
    _p("divider", "Divider", "Layout", "A thin line between two parts", "<Divider />", ["Divider"], search=["line", "separator", "rule"]),
    _p("spacer", "Spacer", "Layout", "Empty space between things", '<Spacer size="md" />', ["Spacer"], search=["gap", "space", "padding"]),
    # ---- Content
    _p("heading", "Heading", "Content", "A title for a section", '<Text variant="heading">New heading</Text>', ["Text"],
       search=["title", "header"]),
    _p("text", "Text", "Content", "A line of words", "<Text>New text</Text>", ["Text"], search=["paragraph", "label", "words"]),
    _p("note", "Small note", "Content", "A small, quiet line", '<Text variant="caption" tone="muted">A small note</Text>', ["Text"],
       search=["caption", "hint", "help"]),
    _p("badge", "Badge", "Content", "A small coloured label", "<Badge>New</Badge>", ["Badge"], search=["label", "status", "pill"]),
    _p("tag", "Tag", "Content", "A quiet outlined label", "<Tag>Tag</Tag>", ["Tag"], search=["chip", "category"]),
    _p("icon", "Icon", "Content", "A small picture symbol", '<Icon name="star" />', ["Icon"], search=["symbol", "glyph", "picture"]),
    _p("person", "Person", "Content", "A person's picture, or their initials", '<Avatar name="Person" />', ["Avatar"],
       search=["avatar", "profile", "user"]),
    _p("amount", "Amount", "Content", "A sum of money in the app's currency", "<Money value={0} />", ["Money"],
       search=["price", "money", "cost", "total"]),
    _p("rating", "Rating dots", "Content", "A score shown as dots", "<Dots value={3} />", ["Dots"], search=["stars", "score", "level"]),
    # ---- Form
    _p("text-field", "Text field", "Form", "A box to type words into", '<TextField label="Label" value="" onChange={() => {}} />',
       ["TextField"], search=["input", "type", "box"], drawn_only=True),
    _p("number-field", "Number field", "Form", "A box to type a number into",
       '<NumberField label="Label" value={0} onChange={() => {}} />', ["NumberField"], search=["input", "quantity", "count"],
       drawn_only=True),
    _p("money-field", "Money field", "Form", "A box to type an amount into",
       '<MoneyField label="Amount" value={0} onChange={() => {}} />', ["MoneyField"], search=["price", "cost", "currency"],
       drawn_only=True),
    _p("choice-field", "Choice", "Form", "Pick one from a short list",
       '<SelectField label="Label" value={undefined} onChange={() => {}} options={[{ value: "a", label: "First" }, { value: "b", label: "Second" }]} />',
       ["SelectField"], search=["select", "dropdown", "options"], drawn_only=True),
    _p("switch-field", "Switch", "Form", "An on and off switch", '<SwitchField label="Label" value={false} onChange={() => {}} />',
       ["SwitchField"], search=["toggle", "checkbox", "on off"], drawn_only=True),
    _p("date-field", "Date field", "Form", "A box for a date or a time", '<DateField label="Date" value="" onChange={() => {}} />',
       ["DateField"], search=["calendar", "time", "day"], drawn_only=True),
    # ---- Actions
    _p("button", "Button", "Actions", "A button", "<Button onPress={() => {}}>Button</Button>", ["Button"],
       search=["press", "tap", "action"], drawn_only=True),
    _p("button-outline", "Outlined button", "Actions", "A button with just an outline",
       '<Button variant="outline" onPress={() => {}}>Button</Button>', ["Button"], search=["secondary"], drawn_only=True),
    _p("button-ghost", "Plain button", "Actions", "A button that looks like text",
       '<Button variant="ghost" onPress={() => {}}>Button</Button>', ["Button"], search=["link", "quiet"], drawn_only=True),
    _p("button-danger", "Danger button", "Actions", "A red button, for taking something away",
       '<Button variant="danger" onPress={() => {}}>Delete</Button>', ["Button"], search=["delete", "remove", "destructive"],
       drawn_only=True),
    # ---- Collections
    _p("empty", "Empty message", "Collections", "What a list says when it has nothing",
       '<Empty title="Nothing here yet" message="Add something to begin" />', ["Empty"], search=["nothing", "no results", "blank"]),
    # ---- Charts
    _p("chart", "Chart", "Charts", "Bars, a line, or a pie of a few numbers",
       '<SimpleChart type="bar" data={[{ label: "A", value: 3 }, { label: "B", value: 5 }, { label: "C", value: 2 }]} />',
       ["SimpleChart"], search=["graph", "bar", "pie", "line"]),
    _p("number-tile", "Number tile", "Charts", "One number with its name", '<StatTile label="Total" value="0" />', ["StatTile"],
       search=["stat", "kpi", "metric"]),
    # ---- Feedback
    _p("loading", "Loading", "Feedback", "A spinner with a word", "<Loading />", ["Loading"], search=["spinner", "wait"]),
    _p("error", "Error message", "Feedback", "Says something went wrong", '<ErrorState message="Something went wrong" />',
       ["ErrorState"], search=["failed", "problem", "alert"]),
]


def palette_entry_for(jsx: str) -> dict[str, Any] | None:
    """The ready part whose code this is exactly, or None: nothing else is added without the compiler."""
    return next((p for p in PALETTE if p["jsx"] == jsx), None)
