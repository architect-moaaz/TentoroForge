"""What a turn is asking for, and what each kind of asking needs.

`_UNDERSTAND_ASK_REQUIRED` demanded `screen`, `element_label`,
`current_behavior`, `desired_behavior` and `target_file` of every request. All
five describe a rename. So "build a dashboard at / with five widgets" could not
be EXPRESSED in the structure Smith answers in, let alone executed — the model
either failed validation or produced an `element_label` it had invented, and
the dispatcher then found nothing to rename and reported that the current state
already matched.

The fix is not to make the fields optional. That turns a mis-shaped contract
into no contract, and the relevance check that closes the "cheapest-edit-wins"
loophole — diff must touch `target_file` + `element_label` — depends on them
being present FOR A RENAME. Requirements are per verb, because a rename and a
composition genuinely need different facts.

WHY A CLOSED SET. An open `verb` string would let the model invent
`refactor_everything` and the dispatcher would fall through to the same silent
no-op this exists to remove. Unknown verbs are named as unknown and answered
honestly.
"""

from __future__ import annotations

#: verb -> the fields a turn must carry to be actionable.
#:
#: `rename` keeps exactly what it always required. The others ask for what
#: their own machinery needs and nothing more: a composition needs a route, not
#: a `current_behavior` for a page that does not exist yet.
REQUIRED_BY_VERB: dict[str, set[str]] = {
    "rename": {"screen", "element_label", "current_behavior",
               "desired_behavior", "target_file"},
    # A control taken off a screen: the screen and the control's exact visible
    # text. No `new_value` — that is what makes it a removal to the move.
    # Without this verb the model had to express "remove the delete button"
    # as a rename with nothing to write, and as often chose compose_route,
    # which re-laid the screen out with the control still declared on it.
    "remove": {"target_file", "element_label"},
    # The look of the application — colours, type, density. Lives in
    # `designSystem`, a section no other verb touches; "change the theme
    # colour to green" was squeezed into a rename of the palette decision's
    # wording. Needs only the change, in the user's words: the design agent
    # re-decides the section against it.
    "restyle": {"change"},
    # Workflows — the business processes. `workflow` is what the new one
    # should do (add) or which existing one is meant (edit/remove); `change`
    # is what should be different about it. `route` may name the screen a
    # new manual workflow starts from.
    # The menu — entries, order, labels, groups, landing route. `navigation`
    # is a singleton section; the ask in the user's words is all it needs.
    "edit_navigation": {"change"},
    "add_workflow": {"workflow"},
    "edit_workflow": {"workflow", "change"},
    "remove_workflow": {"workflow"},
    # Access — roles, permissions, who reaches which screen. One verb: the
    # security agent re-decides the model and a second call the screens.
    "edit_access": {"change"},
    # Business rules — what constrains a form or a record.
    "add_rule": {"rule"},
    "edit_rule": {"rule", "change"},
    "remove_rule": {"rule"},
    # The data model — a new entity, or one retired with everything on it.
    "add_entity": {"entity"},
    "remove_entity": {"entity"},
    # A field renamed or removed across the whole document (deterministic).
    "rename_field": {"entity", "field", "new_value"},
    "remove_field": {"entity", "field"},
    # The definition after the build: requirements flow to what cites them;
    # the product is what the app is called and for; APIs and integrations.
    "add_requirement": {"requirement"},
    "edit_requirement": {"requirement", "change"},
    "remove_requirement": {"requirement"},
    "edit_product": {"change"},
    "add_api": {"api"},
    "remove_api": {"api"},
    "add_integration": {"integration"},
    "remove_integration": {"integration"},
    "compose_route": {"route"},
    "add_widgets": {"route", "widgets"},
    # A whole screen retired: the route stops resolving, the entry leaves the
    # menu, and every link to it comes off the screens that held it. Needs the
    # route and nothing else — a page is named by where it is.
    "remove_page": {"route"},
    # A new field on an existing entity's data model. `field` carries at least
    # {name, type}; the column is created nullable via drizzle-kit push, so it
    # is a migration, never a rebuild. Displaying it is a separate edit_page.
    "add_field": {"entity", "field"},
    # `token_env` is the NAME of an environment variable, never the token.
    # §42 puts `chat history` first on the list of places the raw
    # credential must not come to rest, and Smith's conversation is
    # persisted — so the field Smith may ask for is the reference.
    # `treat_as` is deliberately NOT required here. Smith asks for it in
    # `_connect_figma` with the consequence spelled out, because "specification"
    # and "reference" build different applications from the same file — and a
    # missing-field message ("I just need treat as") would be a worse way to
    # ask than the sentence that explains the difference.
    "connect_figma": {"figma_url", "token_env"},
    # The same contract for the second design tool: the page, and the NAME of
    # the variable holding the API key — never the key.
    "connect_uxpilot": {"uxpilot_ref", "key_env"},
    # Undoes what the two above did to the page set: the design record goes,
    # every page stops naming a frame, and the screens are composed from the
    # component library. Needs nothing — there is only ever one design set.
    "disconnect_design": set(),
    # Undo. Needs nothing: it is always the last change, and asking which one
    # would be asking the person to know what Smith recorded.
    "revert": set(),
    # THE ASKS THAT REACH NOTHING, GIVEN SOMEWHERE TO LAND. Each of these is a
    # thing people ask for that Smith genuinely cannot do. Without a verb they
    # were classified as whatever was nearest — "delete the Wards page" as a
    # control removal — or fell to "I did not recognise that", which is true
    # and useless. As verbs they are recognised, answered with the REASON, and
    # offered the nearest thing that does work. They change nothing.
    "rename_entity": {"entity", "new_value"},
    "change_field_type": {"entity", "field"},
    "edit_api": {"api"},
    "reorder": {"route"},
    "rebuild": set(),
}

#: What each verb is for, in the words a model should recognise. Shown in the
#: tool description so the choice is made from a list rather than guessed.
VERB_HELP: dict[str, str] = {
    "rename": (
        "Change the wording of something that already exists. Needs the exact "
        "current text and what it should say instead."
    ),
    "remove": (
        "Take a control off a screen that exists — a button, a row action, a "
        "link: \"remove the delete button\". Needs the screen and the control's "
        "exact visible text. The screen stops declaring what the control did."
    ),
    "restyle": (
        "Change how the application LOOKS — theme colour, palette, type, "
        "density: \"change the theme colour to green\", \"make it darker and "
        "more compact\". Re-decides the design system against the request; "
        "every screen picks it up through the tokens. Needs the change in the "
        "user's words."
    ),
    "edit_navigation": (
        "Change the app's menu: \"put Master Data first\", \"call it Nurse "
        "Directory\", \"hide the registration page from the menu\", \"group "
        "these under Admin\", \"open on Master Data\". Needs the change in the "
        "user's words."
    ),
    "add_workflow": (
        "Add a business process: \"email the admin after a registration\", "
        "\"archive a nurse instead of deleting\". Declares the workflow, authors "
        "its steps against the node catalogue, and puts a control for it on the "
        "screen it starts from. Needs what it should do, in the user's words; "
        "the screen is optional."
    ),
    "edit_workflow": (
        "Change what an existing workflow does: \"when a nurse is registered, "
        "also notify the ward manager\". Re-authors its steps against the "
        "change; its name and inputs stay. Needs which workflow and what should "
        "be different."
    ),
    "remove_workflow": (
        "Retire a workflow and take its controls off every screen: \"remove the "
        "delete nurse workflow\". Needs which workflow."
    ),
    "edit_access": (
        "Change who can do what: \"add a Ward Manager role\", \"only admins can "
        "delete a nurse\", \"make Master Data admin-only\", \"let anyone open "
        "registration without signing in\". Re-decides roles, permissions and "
        "screen access. Needs the change in the user's words."
    ),
    "add_rule": (
        "Add a business rule: \"years of experience cannot exceed 60\", \"a nurse "
        "needs at least one speciality\". Authored against the entities and "
        "projected so it fires on the form. Needs the rule in the user's words."
    ),
    "edit_rule": (
        "Change an existing business rule. Needs which rule and what should be "
        "different."
    ),
    "remove_rule": ("Retire a business rule. Needs which rule."),
    "add_entity": (
        "Add a NEW ENTITY to the data model: \"add a Ward entity with a name and "
        "a capacity\". Declares it, authors its fields, projects the data layer. "
        "NOT add_field (that is one column on an existing entity). Needs the "
        "entity in the user's words."
    ),
    "remove_entity": (
        "Retire an entity and everything standing on it — its screens, its "
        "workflows, its relationships. Needs which entity."
    ),
    "rename_field": (
        "Rename a field of an entity everywhere it is used — columns, forms, "
        "bindings, workflows, rules. Needs the entity, the field and the new name."
    ),
    "remove_field": (
        "Remove a field from an entity and from every screen, workflow and rule "
        "that used it. Needs the entity and the field."
    ),
    "add_requirement": ("Record a new requirement in the user's words. Nothing implements it until asked."),
    "edit_requirement": (
        "Restate an existing requirement; the screens, workflows and rules that "
        "cite it are re-authored against the new wording. Needs which "
        "requirement and what it should say."
    ),
    "remove_requirement": ("Retire a requirement. Needs which one."),
    "edit_product": (
        "Change what the application is called or is for: its name, "
        "description, objectives, terminology, personas, language. Needs the "
        "change in the user's words."
    ),
    "add_api": ("Declare an API endpoint: \"an endpoint that lists wards\". Needs it in the user's words."),
    "remove_api": ("Retire an endpoint. Needs which one (method and path, or id)."),
    "add_integration": (
        "Declare an integration: \"send email through SendGrid\". Records the "
        "NAMES of the secrets it needs, never their values. Needs it in the "
        "user's words."
    ),
    "remove_integration": ("Retire an integration. Needs which one."),
    "compose_route": (
        "Build or rebuild the screen at a route — when a route renders "
        "nothing, or the user wants it laid out again from scratch."
    ),
    "add_widgets": (
        "Add named sections or widgets to a screen that exists: "
        '"put upcoming sessions and quorum status on the dashboard". NOT for a '
        "new data-model field — that is add_field."
    ),
    "remove_page": (
        "Take a whole SCREEN out of the application: \"delete the Wards page\", "
        "\"remove the reports screen\". Its route stops resolving, it leaves the "
        "menu, and every link to it comes off the screens that had one. The "
        "screen is retired rather than deleted, so undo brings it back. NOT "
        "`remove`, which takes one control off a screen that stays. Needs the "
        "route."
    ),
    "add_field": (
        "Add ONE NEW field/attribute to an existing entity's DATA MODEL: "
        '"add a discount field to offers", "give tasks a due date". This is '
        "the verb whenever the ask introduces a new field on an entity, EVEN "
        "IF it also says \"and show it on <page>\" — the column must exist "
        "before any page can show it, and add_widgets/compose_route cannot "
        "create a column. Needs the entity name and the field ({name, type}). "
        "Displaying the field is a separate later edit_page turn."
    ),
    "connect_figma": (
        "Attach a Figma design as evidence for the application: \"use this "
        "Figma design <url>\". Needs the design URL and the NAME of the "
        "environment variable holding the Figma token — never the token. Smith then asks whether the design is the specification or a reference."
    ),
    "connect_uxpilot": (
        "Attach a UX Pilot page as evidence for the application: \"use this "
        "UX Pilot page <id or url>\". Needs the page and the NAME of the "
        "environment variable holding the UX Pilot API key — never the key. "
        "Smith then asks whether the design is the specification or a reference."
    ),
    "disconnect_design": (
        "Stop building screens from the connected Figma or UX Pilot design: "
        "\"disconnect the Figma design\", \"drop the design\", \"compose the "
        "pages from components instead\". The design record is removed, no "
        "page names a frame any more, and every screen is composed from the "
        "component library. The requirements, entities and rules are untouched."
    ),
    "rename_entity": (
        "They want a whole KIND OF RECORD called something else everywhere: "
        "\"call nurses colleagues\", \"rename the Ward record to Unit\". "
        "Cannot be done. Needs the record and the new name. NOT rename_field, "
        "which is one box on a record."
    ),
    "change_field_type": (
        "They want an existing box to hold a different KIND of value: \"make "
        "the phone number a number instead of text\", \"the date should be a "
        "date, not free text\". Cannot be done. Needs the record and the box."
    ),
    "edit_api": (
        "They want an existing endpoint CHANGED rather than added or removed: "
        "\"make that endpoint take a date range\". Cannot be done. Needs "
        "which endpoint."
    ),
    "reorder": (
        "They want things MOVED AROUND on a screen that already exists: "
        "\"move the chart above the table\", \"put the search at the top\". "
        "Nothing rearranges a composed screen. Needs the screen."
    ),
    "revert": (
        "Undo the last change: \"undo that\", \"undo\", \"put it back\", "
        "\"that was wrong, revert it\", \"go back\". The application is "
        "restored as it stood before the change and every projection is "
        "written out again. Said twice it goes back two changes. Needs "
        "nothing — it is always the most recent change."
    ),
    "rebuild": (
        "Regenerate the application from its definition. The honest answer "
        "when a change is larger than a single screen."
    ),
}

DEFAULT_VERB = "rename"


def verb_of(understanding: dict) -> str:
    """The verb this understanding is asking for.

    Defaults to `rename` when unset, so an older caller — or a model that
    ignores the field — behaves exactly as before rather than falling into an
    unknown-verb branch it has never seen.
    """
    verb = str((understanding or {}).get("verb") or "").strip().lower()
    return verb or DEFAULT_VERB


def missing_fields(understanding: dict) -> list[str]:
    """Fields this verb needs and does not have.

    A list value counts as present when it is non-empty: `widgets` is the point
    of `add_widgets`, and an empty list is the request without its content.
    """
    verb = verb_of(understanding)
    required = REQUIRED_BY_VERB.get(verb)
    if required is None:
        return []                      # unknown verb: reported separately
    out = []
    for key in sorted(required):
        value = (understanding or {}).get(key)
        if isinstance(value, str):
            if not value.strip():
                out.append(key)
        elif isinstance(value, (list, tuple)):
            if not value:
                out.append(key)
        elif value is None:
            out.append(key)
    return out


def is_known(understanding: dict) -> bool:
    return verb_of(understanding) in REQUIRED_BY_VERB
