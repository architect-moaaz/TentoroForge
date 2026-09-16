"""§16 — what the user is asking, or what Smith still needs to know.

`run_iteration` has always handled all three outcomes: a clarification
short-circuits the turn to `status="asked"`, a missing `target_file` asks which
screen, and everything else proceeds to the move. The gate was written and had
nothing feeding it — `understand_ask_fn` was never wired, so every iteration
asserted before reaching any of it.

The contract is three fields, and the useful discipline is that ASKING IS A
FIRST-CLASS ANSWER. A model told to always produce a target will always produce
one, including for "make it nicer", and the turn then edits a file nobody
chose. Naming clarification as the preferred outcome when the request is
underspecified is what makes §16's gate real rather than decorative.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_PROMPT = """You are reading one request from someone changing an application \
they own, against the part of its Blueprint that seems relevant.

Return ONLY a JSON object with exactly these keys:

  "answer": if they are ASKING ABOUT the application rather than asking you to
      change it — how something works, whether something is stored, what
      happens when they do X — answer it from the Blueprint below and leave
      every other field "". Answer only what the Blueprint actually says; if
      it does not say, reply that it does not and name what you would need.
      "" when the request is a change.
      SHAPE OF AN ANSWER (it is shown as markdown in a chat bubble): one
      short lead sentence, then a bulleted list whenever you are naming more
      than two things — screens, routes, fields, requirements, roles — one
      per line, with the name in **bold** and its route or id in `code`.
      Keep each bullet to one line. No headings, no closing summary.
  "clarification_needed": a question to ask them, or "" if the request is
      clear enough to act on. Ask when the request names no screen or element,
      when it could plausibly mean two different changes, or when acting on
      the wrong reading would be expensive to undo. Asking is not a failure.
  "clarification_options": when the question offers CHOICES, the choices as
      short labels, 2 to 5, each a complete answer on its own that they can
      pick with one click — ["A new page of its own", "A panel on the screen
      they named", "Both"]. Draw them from THIS application: a choice between
      screens names its own screens and their routes. Put the choices here
      rather than spelling them out in the question; the question then asks.
      [] when the question is open (a name, a URL, a value).
  "verb": WHICH KIND OF CHANGE this is. Exactly one of:
      "rename"        — change the wording of something that already exists.
      "remove"        — take a control OFF a screen that exists: "remove the
                        delete button", "get rid of the export link", "drop
                        the Add Nurse button". The screen is not rebuilt;
                        the one control goes, and the screen stops offering
                        what it did. NOT compose_route — that lays the whole
                        screen out again with the control still declared.
      "restyle"       — change how the application LOOKS: theme or brand
                        colour, palette, typography, spacing, density —
                        "change the theme colour from blue to green", "make
                        it darker", "more compact". This is the design
                        system, not any one screen: NOT rename (no label
                        changes), NOT compose_route (no screen is rebuilt).
      "edit_navigation" — the MENU: what is in it, in what order, under
                        what label or icon or group heading, and which
                        page the app opens on: "put Master Data first",
                        "rename the menu item to Nurse Directory", "hide
                        registration from the sidebar", "open on Master
                        Data". NOT rename — a menu entry is not a control
                        on a screen — and NOT compose_route.
      "add_workflow"  — a NEW business process: "email the admin after a
                        registration", "archive a nurse instead of deleting",
                        "send a reminder every Monday". Something the app
                        should DO, not something a screen should show.
      "edit_workflow" — change what an EXISTING process does: "when a nurse
                        is registered also notify the ward manager", "the
                        delete should ask for a reason first". "When <a thing
                        an existing workflow already does> happens, also do
                        Y" is THIS verb, on that workflow — not add_workflow.
      "remove_workflow" — retire a process: "remove the delete nurse
                        workflow", "stop sending the welcome email".
      "edit_access"   — WHO may do WHAT: roles, permissions, screen access:
                        "add a Ward Manager role", "only admins can delete a
                        nurse", "make Master Data admin-only", "let anyone
                        open registration without signing in".
      "add_rule"      — a NEW business rule constraining a form or a record:
                        "years of experience cannot exceed 60", "a nurse
                        needs at least one speciality".
      "edit_rule"     — change an EXISTING rule: "raise the experience cap
                        to 70". "remove_rule" — retire one.
      "add_entity"    — a NEW ENTITY in the data model: "add a Ward entity
                        with a name and a capacity". NOT add_field (one new
                        column on an existing entity is add_field).
      "remove_entity" — retire an entity and everything on it: "we don't
                        need the Department entity".
      "rename_field"  — a field of an entity gets a new name: "rename
                        yearsOfExperience to experienceYears".
      "remove_field"  — a field goes: "drop the location field from nurses".
      "add_requirement" / "edit_requirement" / "remove_requirement" — the
                        stated requirements: "the app should also let a
                        nurse mark herself unavailable" (add), "REQ-012
                        should say…" (edit), "we no longer need…" (remove).
      "edit_product"  — what the app is called or is for: "call the app
                        Nurse Roster", "the objective is…", "it is for ward
                        managers", "the interface should be in Arabic".
      "add_api" / "remove_api" — an API endpoint: "an endpoint that lists
                        wards", "remove the export endpoint".
      "add_integration" / "remove_integration" — a third-party service:
                        "send email through SendGrid", "drop the Stripe
                        integration".
      "compose_route" — build or rebuild the whole screen at a route. Use this
                        when a route renders nothing, is empty, or 404s, or
                        when they want it laid out again from scratch.
      "add_widgets"   — add named sections to a screen that exists: "put
                        upcoming sessions and quorum status on the dashboard".
                        NOT for a new data-model field — that is add_field.
                        A field the entity ALREADY HAS that a screen does not
                        show ("I cannot see fathersName on the registration
                        page", "show phone on the nurse form") is THIS verb,
                        with the field as the widget — not compose_route,
                        which lays the whole screen out again.
      "add_field"     — add ONE NEW field/attribute to an existing entity's
                        DATA MODEL: "add a discount field to offers", "give
                        tasks a due date", "customers need a phone number".
                        Use this WHENEVER the ask introduces a new field on an
                        entity, EVEN IF it also says "and show it on <page>":
                        the column must exist before any page can display it,
                        and add_widgets/compose_route CANNOT create a column
                        (they only recompose a screen, so the field would bind
                        to nothing). Pick add_field; showing the field is a
                        separate later edit_page turn — not this one.
      "connect_figma" — they named a Figma design to build from or to use as
                        the visual reference. Any figma.com/design or
                        figma.com/file link is this verb.
      "connect_uxpilot" — they named a UX Pilot page (a uxpilot.ai link, or
                        "UX Pilot page <id>") to build from or to use as the
                        visual reference.
      "disconnect_design" — they want the connected design gone and the
                        screens composed from the component library instead:
                        "disconnect the Figma design", "drop the design",
                        "stop using the frames", "compose every page from
                        components". Needs no fields.
    "rebuild"       — build or regenerate the WHOLE application: "build",
                      "build it", "start the build", "generate the app",
                      "rebuild everything". No route, no single screen.
                      THE DIFFERENCE FROM compose_route IS SCOPE, and it was
                      missing from this list entirely — so a bare "Build"
                      became a compose of "/" and answered "there is no page
                      at '/' in this application", which is true, unhelpful,
                      and reads as a broken app rather than a misread word.
      "" when you are asking or answering rather than changing.

Then fill in ONLY the fields that verb needs. Leave the others "".

  rename needs:
  "target_file": the route or schema path the change belongs to. Use a value
      that appears in the Blueprint below — do not invent a path.
  "element_label": the visible text of the thing to change AS IT IS NOW (a
      button's current label, the current heading).
  "new_value": what it should say or become instead, or "" if the request is
      a removal. Give the literal text to write, not a description of it: for
      "call it New plant" the value is "New plant", not "a clearer label".

  remove needs:
  "target_file": the route or schema path of the screen the control is on —
      a value that appears in the Blueprint below.
  "element_label": the control's visible text AS IT IS NOW, exactly — a
      Table row action's label ("Delete") is a control as much as a Button's.
      Copy it from the Blueprint below; do not paraphrase it.

  rename_field needs:
  "entity": the entity's name as the Blueprint spells it; "field": the field's
      current name; "new_value": the new name.

  remove_field needs:
  "entity" and "field", as above.

  add_requirement needs "requirement": the requirement in the user's words.
  edit_requirement needs "requirement": which one (its id or its wording) and
      "change": what it should say instead.
  remove_requirement needs "requirement": which one.

  edit_product needs "change": what should be different, in the user's words.

  add_api needs "api": the endpoint in the user's words; remove_api needs
      "api": which one (method and path, or its id).

  add_integration needs "integration": the service in the user's words;
      remove_integration needs "integration": which one.

  edit_navigation needs:
  "change": what should be different about the menu, in the user's words.

  edit_access needs:
  "change": who should be able to do what, in the user's words.

  add_rule needs:
  "rule": the rule in the user's words.

  edit_rule / remove_rule need:
  "rule": which rule, by the name the Blueprint below gives it; edit_rule
      also "change": what should be different.

  add_entity needs:
  "entity": the entity in the user's words — its name and what it holds.

  remove_entity needs:
  "entity": which entity, by the name the Blueprint below gives it.

  add_workflow needs:
  "workflow": what the new process should do, in the user's own words.
  "route": optional — the screen a person starts it from, as a route in the
      Blueprint below, when they named one.

  edit_workflow needs:
  "workflow": which existing workflow, by the name the Blueprint below gives it.
  "change": what should be different about it, in the user's words.

  remove_workflow needs:
  "workflow": which existing workflow, by the name the Blueprint below gives it.

  restyle needs:
  "change": what should look different, in the user's own words ("theme
      colour green instead of blue", "darker, more compact"). Not a hex
      value unless they gave one; the design agent decides the scheme.

  compose_route needs:
  "route": the path of the screen, as it appears in the Blueprint ("/",
      "/sessions"). The screen's name works too if that is how they said it.

  add_widgets needs:
  "route": as above, and
  "widgets": a JSON array of the sections to add, each naming WHAT IT SHOWS
      ("Upcoming Sessions", "Quorum Status"). Never an empty array — the
      widgets are the request.

  add_field needs:
  "entity": the name of the existing entity gaining the field, as the Blueprint
      spells it ("Offer", "Task").
  "field": a JSON object with "name", "type" and "label" for the new column —
      name in the app's style ("fathersName"), type one of text / varchar /
      int / decimal / boolean / date / timestamp, label the words they used
      ("Father's Name"), which is what the form will show.
      (Optional: length, precision, scale.)

  connect_figma needs:
      "figma_url": the Figma link exactly as they gave it, whole.
      "token_env": the NAME of the environment variable holding their Figma
          token — "FIGMA_TOKEN", not the token. If they have not said which
          variable, leave this "" and ask for the NAME in
          "clarification_needed", saying plainly that they must not paste
          the token itself: the conversation is written to disk and a
          credential must never come to rest there. IF THEY PASTE A TOKEN
          ANYWAY (a value starting `figd_`), leave "token_env" empty, do not
          repeat the value anywhere in your reply, and tell them to export it
          as an environment variable and give you the name instead.
      "treat_as": whether this design is the SPECIFICATION or a REFERENCE.
          "specification" when they want exactly the screens they drew and
          nothing else — "only these pages", "just what is in the design",
          "build this and nothing more". "evidence" when the design informs
          an application that is larger than it — the usual case, and the
          right reading of "use this design", "match this style", "build
          from this". Leave "" if they have not said, and ask which in
          "clarification_needed": the difference is a four-page app versus
          a fourteen-page one, and it is cheap to ask and expensive to undo.

  connect_uxpilot needs:
      "uxpilot_ref": the UX Pilot page id or URL exactly as they gave it.
      "key_env": the NAME of the environment variable holding their UX Pilot
          API key — "UXPILOT_API_KEY", not the key. The same rule as
          "token_env": never repeat a pasted key (a value starting `ep_`);
          leave this "" and ask for the NAME in "clarification_needed".
      "treat_as": as for connect_figma.

Do not explain. Do not wrap the JSON in prose or code fences.

CHOOSE THE VERB FROM WHAT THEY WANT TO EXIST, NOT FROM HOW MUCH IS THERE. "The
page is empty", "add a dashboard at /", "build the screen at /X" and "put these
five things on the dashboard" are compose_route or add_widgets. Calling one of
them a rename means looking for a label that was never mentioned, finding
nothing, and reporting that the current state already matches — which is
useless to someone whose screen is blank.

A NEW FIELD IS A DATA-MODEL CHANGE, NOT A DISPLAY ONE. "Add a discount field to
offers and show it on the detail page" is add_field — the column comes first;
"and show it" is a second turn. Do not read the "show it" half as add_widgets:
a widget bound to a column that does not exist yet renders nothing, which is the
exact failure this verb removes. When the ask EXPLICITLY names a new field or
attribute to add to an entity, the verb this turn is add_field.

BUT add_field IS ONLY FOR AN EXPLICIT "add a field" ASK. A policy, rule, or
approval/workflow request — "managers must approve offers above 150000", "reject
orders over $10k", "notify the owner when a task is overdue" — is NOT a field-add,
even though you could imagine a column behind it. Do not invent an `approvalStatus`
or `isApproved` field and call it add_field: that request needs impact analysis
(a new actor, a new status, an approval workflow, a business rule), which is more
than a single column. Only pick add_field when the user actually says to add a
named field/attribute; leave a rule/policy/workflow ask for the fuller path
(answer with the impact, or clarification_needed, not add_field).

A REPLY IS PART OF AN EXCHANGE. When the conversation below ends with a
question of yours, read the request as its answer: "yes" confirms what you
just proposed, and you should act on that proposal rather than ask what it
meant. Do not ask a question the conversation has already answered. If your
question named a route and five widgets and they said "yes please", the verb
is add_widgets and you already know the route and the widgets.

CONVERSATION SO FAR (oldest first, may be empty):
{history}

BLUEPRINT (the relevant part):
{ctx}

REQUEST:
{message}"""


def _design_scope(raw: object) -> str:
    """`evidence`, `specification`, or "" when they have not said.

    THE WORD SMITH ASKS FOR MUST BE A WORD SMITH ACCEPTS. The question offers
    "specification or reference", and `reference` is what a person then says —
    while the Blueprint's own vocabulary for it is `evidence` (§48). Mapping
    here rather than changing the contract: `evidence` is the accurate name for
    what the frames are to the rest of the pipeline, and `reference` is the
    accurate word for what the user is telling you.
    """
    text = str(raw or "").strip().lower()
    if text in ("specification", "spec", "the specification"):
        return "specification"
    if text in ("evidence", "reference", "a reference", "the reference"):
        return "evidence"
    return ""


def _env_name_only(raw: object) -> str:
    """An environment variable NAME, or "" — never a credential.

    §42's first forbidden resting place for a raw token is chat history, and
    this return value is written to the conversation log. A Figma personal
    access token is `figd_...`; anything carrying that, or too long or too
    punctuated to be a variable name, is a secret the model was told not to
    return. Dropping it is the point: Smith then asks for the NAME, and the
    token never reaches disk.
    """
    text = str(raw or "").strip()
    if not text or "figd_" in text or len(text) > 64:
        return ""
    return text if all(c.isalnum() or c == "_" for c in text) else ""


def _default_provider(prompt: str, reasoning: Callable[[str], None] | None = None) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=1200,
                    reasoning_callback=reasoning)


def _render_history(history: list | None) -> str:
    """The exchange as plain lines, oldest first.

    Bounded to the last few turns: a clarifying question and its answer are
    adjacent, so the window only has to be long enough to hold the pair, and a
    whole transcript would crowd out the Blueprint slice beside it.
    """
    turns = [t for t in (history or []) if t]
    if not turns:
        return "(nothing yet — this is the first turn)"
    lines = []
    for t in turns[-6:]:
        role, text = (t if isinstance(t, (tuple, list)) and len(t) == 2
                      else ("user", t))
        who = "Smith" if str(role).lower() in ("smith", "assistant") else "They"
        lines.append(f"{who}: {str(text).strip()}")
    return "\n".join(lines)


def understand_ask(
    user_message: str,
    blueprint_ctx: str,
    *,
    history: list | None = None,
    provider: Callable[[str], str] | None = None,
    reasoning: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """(message, ctx) -> {clarification_needed, target_file, element_label, new_value}.

    Never raises. An unreachable or unparseable model becomes a clarification
    request, because the alternative — returning a blank understanding — reads
    downstream as "clear enough to act on, but no target", and `run_iteration`
    would ask a generic question while the real reason went unrecorded.
    """
    ask = (user_message or "").strip()
    if not ask:
        return _blank(clarification_needed="What would you like to change?")

    # SHOWN, NOT JUST HAD. `reasoning` is where Smith's thinking goes on its
    # way to the user; without it the model still reasons and nobody sees it.
    # An INJECTED provider keeps the one-argument seam it has always had —
    # every test supplies a plain `lambda prompt: "..."` and none of them
    # should have to grow a parameter to say it does no thinking.
    call = provider or (lambda prompt: _default_provider(prompt, reasoning))
    try:
        raw = call(_PROMPT.format(ctx=blueprint_ctx or "(nothing yet)",
                                  history=_render_history(history),
                                  message=ask))
    except Exception:  # noqa: BLE001 — a turn degrades, it does not crash
        return _blank(clarification_needed=(
            "I could not reach my reasoning service just then — say that "
            "again and I will try once more."))

    data = _parse(raw)
    if data is None:
        return _blank(clarification_needed=(
            "I did not follow that. Which screen should I change, and "
            "what on it?"))

    # Normalised so `run_iteration`'s `.strip()` checks see strings, not None.
    return {
        # A QUESTION IS NOT AN UNDERSPECIFIED CHANGE. The contract already knew
        # questions arrive here — `new_value` says a question has none — but
        # gave the model nowhere to put one, so the only outcome left was
        # `clarification_needed`. Asked whether the app stores data in a
        # database, Smith replied "could you describe what you'd like to
        # change", with the answer sitting in the Blueprint slice it had been
        # handed. Naming the field is the whole fix; the material was already
        # in the prompt.
        "answer": str(data.get("answer") or "").strip(),
        "clarification_needed": str(data.get("clarification_needed") or "").strip(),
        # WHICH KIND OF CHANGE, asked before which fields. Every request used
        # to be held to a rename's five fields because this prompt only knew
        # how to describe a rename — so "the page at / is empty" came back
        # with an invented element_label, the dispatcher found nothing to
        # rename, and Smith reported that the current state already matched.
        # Six times in one conversation, on a screen that rendered nothing.
        #
        # Empty is still `rename` downstream (`verbs.verb_of`), which is what
        # every caller predating this field already did.
        "verb": str(data.get("verb") or "").strip().lower(),
        "route": str(data.get("route") or "").strip(),
        "widgets": [str(w).strip() for w in (data.get("widgets") or [])
                    if str(w).strip()],
        "figma_url": str(data.get("figma_url") or "").strip(),
        # THE NAME OF A VARIABLE, NOT ITS VALUE. §42 forbids the raw token
        # from resting in chat history, and this reply is written to the
        # conversation log. A model that returns the token anyway must not
        # have it persisted here, so anything shaped like a Figma PAT is
        # dropped and the user is asked for the variable name instead.
        "token_env": _env_name_only(data.get("token_env")),
        "uxpilot_ref": str(data.get("uxpilot_ref") or "").strip(),
        # A NAME, never an `ep_` key — the same guard `token_env` has.
        "key_env": _env_name_only(data.get("key_env")),
        "treat_as": _design_scope(data.get("treat_as")),
        "target_file": str(data.get("target_file") or "").strip(),
        "element_label": str(data.get("element_label") or "").strip(),
        # restyle: the change to the look, in the user's words.
        "change": str(data.get("change") or "").strip(),
        # workflows: what a new process should do, or which existing one is meant.
        "workflow": str(data.get("workflow") or "").strip(),
        # rules: the rule in the user's words, or which existing one is meant.
        "rule": str(data.get("rule") or "").strip(),
        # the definition after the build
        "requirement": str(data.get("requirement") or "").strip(),
        "api": str(data.get("api") or "").strip(),
        "integration": str(data.get("integration") or "").strip(),
        # What to write, not a description of it. `move_dispatcher` needs a
        # literal — "a clearer label" is a note to a person, not an edit — and
        # a removal or a question legitimately has none, so "" is a real value
        # here rather than a missing one.
        "new_value": str(data.get("new_value") or "").strip(),
        # add_field: the entity gaining a column, and the column spec. Kept as a
        # string + a dict so `missing_fields` sees them and `run_iteration` can
        # hand them to the seam. Absent for every other verb.
        "entity": str(data.get("entity") or "").strip(),
        # add_field wants {name, type}; rename_field / remove_field name the
        # field as a string. A string is kept as {"name": …} rather than
        # dropped — dropped, "rename yearsOfExperience" reached the seam as
        # "Nurse has no field ''".
        "field": (data.get("field") if isinstance(data.get("field"), dict)
                  else {"name": str(data.get("field")).strip()} if isinstance(data.get("field"), str) and str(data.get("field")).strip()
                  else {}),
        # THE CHOICES, AS CHIPS. A question that offers alternatives used to
        # spell them out in prose ("a new page, or a panel on Nurse
        # Registration or Master Data — which?") and the person typed one
        # back. Carried separately, the panel offers them as chips, the way
        # the definition's own questions are offered.
        "clarification_options": _labels(data.get("clarification_options")),
    }


#: Every key an understanding carries, so a caller's `.get()` never meets a
#: partial dict on exactly the paths that already went wrong.
SHAPE: frozenset[str] = frozenset({
    "answer", "clarification_needed", "clarification_options", "verb", "route",
    "widgets", "figma_url", "token_env", "uxpilot_ref", "key_env", "treat_as",
    "target_file", "element_label", "change", "workflow", "rule", "requirement",
    "api", "integration", "new_value", "entity", "field",
})


def _blank(**given: Any) -> dict[str, Any]:
    """An understanding with nothing in it but `given` — the full shape."""
    out: dict[str, Any] = {k: "" for k in SHAPE}
    out.update({"widgets": [], "field": {}, "clarification_options": []})
    out.update(given)
    return out


def _labels(raw: Any) -> list[str]:
    """Chip labels: strings, trimmed, non-empty, deduplicated, at most five."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip() if not isinstance(item, dict) else str(item.get("label") or "").strip()
        if text and text not in out:
            out.append(text)
    return out[:5]


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped.

    Models fence JSON in ```json blocks and prepend a sentence often enough
    that a bare `json.loads` fails on output that is otherwise perfectly good.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass
    try:
        parsed = json.loads(_escape_inner_quotes(match.group(0)))
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        return None


def _escape_inner_quotes(text: str) -> str:
    """`text` with the double quotes INSIDE its string values escaped.

    Asked which requirements came from the uploaded document, the model
    answered well — and wrote the document's title in quotes inside the
    JSON string, so the object would not load and the turn fell through to
    "I did not follow that": a change-request deflection to a question it
    had just answered. A quote inside a string that is not followed (after
    whitespace) by `,` `}` `]` or `:` cannot be closing the string, so it is
    content. Only reached when a plain load has already failed.
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if ch == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == '"':
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in ",}]:":
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)
