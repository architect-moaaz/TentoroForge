"""§16 — ask before defining, when the brief leaves something material unsaid.

Smith asks well once an application exists: `understand_ask` weighs a change
against the Blueprint and returns a question rather than a guess. Before the
first definition it asked nothing at all. A brief went straight to the DAG
under "Let me define that first", and whatever it had not said was settled by
twenty agents inventing an answer each.

That is the expensive place to guess. A definition run costs a couple of
minutes and every later node builds on it, so a question worth thirty seconds
here saves a rebuild.

ONE QUESTION AT A TIME, IN TURNS. Called on every pre-definition turn against
the brief accumulated so far — which now carries the answers to earlier
questions — and the caller asks only the first question it returns, so each
decision gets a considered answer instead of a wall of them arriving together.
Because the brief grows with each answer, the model asks the NEXT open decision
and returns nothing once they are settled; the caller also caps the rounds, so
a clarifier that could otherwise fire forever always stops and defines. §16
wants Smith to ask rather than to interrogate.

SILENCE IS THE DEFAULT. A brief that names what the application is for and
what people do in it needs no question, and asking anyway is worse than not
asking: it reads as not having listened. Every failure — no provider, bad
JSON, an empty answer — resolves to no question and the definition proceeds.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_PROMPT = """Someone has described an application they want built. It will now
be defined in detail by a team of agents, and anything the description leaves
unsaid will be decided for them.

Ask about what would change what gets built, and about nothing else. At most
three questions; fewer is better and none is a good answer for a description
that already says enough. They are asked one at a time, so put the single most
important open decision first — and anything the description already answers is
not an open decision.

TWO THINGS ARE WORTH ASKING ABOUT ALMOST WHENEVER THEY ARE UNSAID, because
both are decided once and inherited by every screen:

  LANGUAGE. If the description hints at a language for the INTERFACE — it
  names one, it is written in one, it describes an audience who would expect
  one — ask which language the interface should be in and offer the plausible
  answers. Do not infer it silently: a Cairo hospital may well run in English,
  and a country, currency or market is not a language. Where the description
  settles it outright, do not ask.

  COLOUR. If the description names no colours and points at no existing
  design, propose three palettes the domain actually earns and ask which.
  THEY MUST BE THREE DIFFERENT DIRECTIONS, not three shades of one: one
  warm, one cool, and one that is dark-grounded or otherwise characterful
  (a deep green, an oxblood, a plum) — and never more than one of them a
  slate, navy or charcoal scheme, which is what every app was offered and
  what made every app look the same. Name each one and say what it is for —
  "Ink and oxblood: quiet, papery, for long reading", "Slate and amber:
  dense and operational, for a queue worked all day", "Forest and cream on
  a dark ground: evening, a workshop". Not "blue or green": a choice between
  adjectives is not a choice. The LAST option is always "Let the designer
  choose from the domain" — many people have no preference and should not
  be made to invent one. Where colours are named or a reference is
  attached, do not ask. This question is also where taste is asked, so end
  it by inviting a picture: "…or attach a screenshot of a product whose
  look you like, and it will be designed to that standard." A screenshot
  reaches the designer, the director and the reviewer; an adjective does not.

NEVER ASK WHAT TECHNOLOGY IT IS BUILT IN. Every application is built the same
way — a responsive web app that also installs on phones — so "which framework",
"React Native or Flutter", "web or native", "which database" are not decisions
anyone can make here. Do not ask them.

Otherwise ask only what a definition cannot proceed honestly without: who uses
this and whether they differ, whether records are shared or private, what
happens after the last step described. Not anything you can reasonably decide,
not anything already said, and nothing so broad it asks them to write the
brief again.

Return ONLY a JSON object:

  "questions": a list, at most three, each
      {{"question": "...", "options": ["...", "..."]}}.
      Options are 2-4 short concrete answers they could pick; [] only when the
      question is genuinely open. Offering answers is how a question stops
      being homework.
      An empty list asks nothing, which is the right answer more often than
      not.

Do not explain. Do not wrap the JSON in prose or code fences.

WHAT THEY WROTE:
{brief}"""


#: Words that make an application more than a small one: several kinds of
#: person, reporting, money, scheduling, approvals.
_BIG_WORDS = re.compile(
    r"\b(dashboard|admin|administrator|report|reports|analytics|roles?|permissions?|multiple|several|many|"
    r"workflow|approval|approvals|inventory|payments?|invoice|invoicing|calendar|booking|marketplace|"
    r"e-?commerce|cart|checkout|crm|erp|portal|integration|integrations|notifications?)\b", re.I)
_SMALL_WORDS = re.compile(r"\b(simple|small|tiny|basic|single|one[- ](?:form|page|screen)|just a|only a)\b", re.I)
#: A brief is VERY SMALL - and gets a default look rather than a colour question
#: - when it names nothing that makes an app big and is short: at most 25
#: words, or at most 80 when it says it is simple/small/one form. A colour named
#: in the request is honoured either way (the model is told not to ask then).
SMALL_WORDS_MAX = 25
SMALL_WORDS_MAX_STATED = 80


_ROLES = re.compile(
    r"\b(customer|client|staff|employee|manager|admin(?:istrator)?|seller|vendor|buyer|doctor|patient|nurse|teacher|student|"
    r"parent|driver|rider|tenant|landlord|agent|member|owner|technician|reviewer|approver|supplier|guest|host|recruiter|"
    r"candidate|instructor|pharmacist|cashier|waiter|chef|courier|shopper|merchant|clinician|receptionist)s?\b", re.I)


def _roles(text: str) -> int:
    return len({m.group(1).lower().replace("administrator", "admin") for m in _ROLES.finditer(text)})


def is_very_small(brief: str) -> bool:
    """Short, no big-app keyword, and at most ONE kind of person: two kinds
    (customers and staff, sellers and buyers) is a bigger app than its word count."""
    text = re.sub(r"\s+", " ", brief or "").strip()
    if not text or _BIG_WORDS.search(text) or _roles(text) >= 2:
        return False
    n = len(text.split())
    return n <= SMALL_WORDS_MAX or (n <= SMALL_WORDS_MAX_STATED and bool(_SMALL_WORDS.search(text)))


_COLOUR_Q = re.compile(r"colou?r|palette|look and feel|visual (?:direction|style|identity)|design (?:direction|style)|"
                       r"\bmood\b|\bstyling\b|\bfonts?\b|typeface|typograph|\btheme\b|playful|serious|"
                       r"dark (?:or|mode|theme)|light (?:or|mode|theme)|aesthetic", re.I)
#: A TECHNOLOGY-CHOICE question - what it is built in, on, or for - never a
#: product question. Precise on purpose: "swiftly or in a batch" and "the kotlin
#: team lead" are business questions and pass.
_FRAMEWORK_Q = re.compile(
    # "framework" only as a technology choice: followed/paired by build words or tech names - "a framework of
    # rules applies to vaccine stock" is a product question.
    r"\bframeworks?\b(?=.{0,50}\b(?:built|written|coded|develop\w*|use|using|prefer|react|angular|vue|django|rails|laravel|next|node|"
    r"swift|kotlin|flutter|should it|should the app|should we)\b)|\b(?:what|which)\s+framework\s+(?:should|do you|would you|to use|will|are we|is it|for (?:it|the app|this))\b|\btech(?:nology|nologies)?\s+stack\b|"
    # "which platform/stack/database ..." only as a CHOICE of technology (should / do you / to use / it run /
    # built ...), not "which platform NUMBER", "which stack OF vaccines", "which database OF patients".
    r"\b(?:what|which)\s+(?:technology|technologies|stack|platform|database|programming language|tech)\s+"
    r"(?:should|do you|would you|to use|will|is it|are we|are you|for it|it |built|runs?|be\b|do we|can)|"
    r"\bstack\b.{0,30}\bprefer|\bweb(?: app)?\s+(?:or|vs\.?)\s+(?:a\s+)?(?:mobile|native)\b|"
    r"\bmobile(?: app)?\s+(?:or|vs\.?)\s+(?:a\s+)?(?:web|native|website)\b|\bwebsite\s+(?:or|vs\.?)\s+(?:a\s+)?(?:mobile|native)\b|"
    r"\bnative\s+(?:or|vs\.?)\b|"
    r"\b(?:ios|android)\b.{0,25}\b(?:or|and)\b.{0,25}\b(?:ios|android|web)\b|\bpwa\b|\bprogressive web\b|"
    r"\b(?:postgres(?:ql)?|mysql|mongo(?:db)?|sqlite|sql server)\b|\breact[- ]native\b|\bflutter\b|\bswiftui\b|"
    r"\bbuilt (?:in|with|using) (?:which|swift|kotlin|java|python|react|flutter|node|php|ruby|rust|\.net)\b|"
    r"\b(?:should|do you want|would you like)\b.{0,25}\bbe (?:built|written|developed|coded) (?:in|with|using)\b|"
    r"\bwhich\b.{0,40}\bbe (?:built|written|coded|developed) (?:in|with|using)\b|"
    r"\b(?:native|cross[- ]platform)\s+(?:app|apps|development)\b|\bprogramming languages?\b|"
    # a LANGUAGE question is a technology question only when it is about CODE (written/coded/built in, programmed ...);
    # "which language should the interface be in?" is the spoken-language question and must be asked.
    r"\b(?:which|what)\s+(?:programming\s+)?language\b.{0,50}\b(?:written|coded|programmed|built|developed|implemented)\b|"
    r"\blanguage\s+and\s+framework\b|\b(?:which|what)\s+(?:tech|technology|stack)\b.{0,30}\blanguage\b", re.I)
#: A question about which DEVICE or PLACE people use (the ward screen or their phones) is a product
#: question, even though it says "platform"; it is not a technology choice.
_DEVICE_PRODUCT = re.compile(
    r"\b(?:nurses?|staff|patients?|customers?|doctors?|guests?|employees?|drivers?|cashiers?|clerks?|receptionists?|managers?|users?)\b"
    r".{0,60}\b(?:kiosk|ward screen|front desk|reception|counter|tablet|their (?:own )?phones?|desktop|terminal|screen)\b|"
    r"\b(?:kiosk|ward screen|front desk|their (?:own )?phones?)\b", re.I)
_TECH_WORDS = re.compile(r"framework|stack|database|\bpwa\b|native|react|flutter|swift|kotlin|\bios\b|android|programming|language|postgres|mysql|mongo", re.I)


#: Words that make a "language" question about what PEOPLE read or speak, not about code.
_SPOKEN_LANGUAGE = re.compile(
    r"\b(?:interface|ui|screens?|display|labels?|text|spoken|speak|speaking|user[- ]facing|app'?s? (?:language|text)|translat\w*|"
    r"multi-?lingual|multiple languages|arabic|english|hindi|french|german|spanish|urdu|support\s+\w+)\b", re.I)
_CODE_WORDS = re.compile(r"\bprogramming\b|\bcoded?\b|\bprogrammed\b|\bframework\b|\bstack\b|\btech(?:nology)?\b|\bbackend\b|\bfrontend\b", re.I)


def _is_technology_question(question: str) -> bool:
    if not _FRAMEWORK_Q.search(question):
        return False
    if re.search(r"\blanguages?\b", question, re.I) and _SPOKEN_LANGUAGE.search(question) and not _CODE_WORDS.search(question):
        return False
    if re.search(r"\bplatform\b", question, re.I) and _DEVICE_PRODUCT.search(question) and not _TECH_WORDS.search(question):
        return False
    return True
#: A native demand that is STRONG on its own (no web/responsive context can soften it).
_NATIVE_STRONG = re.compile(
    r"\b(?:react[- ]native|flutter|swiftui|xamarin|ionic|native\s+(?:ios|android|mobile|phone|iphone)?\s*apps?|"
    r"(?:in|using|with|written in)\s+(?:swift|kotlin)\b(?!\s+(?:developers?|team|lead|fans?))|(?:swift|kotlin)\s+(?:ios|android)|"
    r"(?<!taylor\s)(?:swift|kotlin)\s+apps?)\b", re.I)
#: "not a website", "instead of a web app", "rather than a website": the person is ruling the web out.
_NOT_WEB = re.compile(r"\b(?:not|never|no)\s+(?:a\s+|an\s+|just\s+a\s+)?(?:web\s?apps?|web\s?sites?|pwa|browser)\b|"
                      r"\b(?:instead of|rather than|and not)\s+(?:a\s+|an\s+)?(?:web\s?apps?|web\s?sites?|pwa)\b", re.I)
#: A WEAKER demand: an iOS/Android/mobile app. Softened by "web app", "responsive", "website", or by iOS/Android being the
#: subject of a business ("Android phone repair shop", "iOS app development agency").
_NATIVE_WEAK = re.compile(
    r"\b(?:(?:ios|android|iphone|ipad)\s+(?:native\s+)?apps?|apps?\s+for\s+(?:ios|android|iphone|ipad)|mobile\s+apps?|"
    r"(?:ios|android)\s+native)\b", re.I)
_SOFTENERS = re.compile(r"\b(?:web\s?apps?|responsive|web\s?sites?|progressive web|pwa|works? (?:on|in) (?:the )?browser)\b", re.I)
_BUSINESS_AFTER = re.compile(r"^\W*(?:\w+\W+){0,3}(?:repair|shop|store|agency|development|developers?|training|course|lessons|support|"
                             r"consult\w*|retail|reseller)", re.I)
_BUSINESS_BEFORE = re.compile(r"(?:repair|sell\w*|resell\w*|train\w*|teach\w*|support|consult\w*)\s+(?:\w+\s+){0,2}$", re.I)


WEB_AND_PHONE = ("This will be built as a responsive web app that also installs on phones "
                 "(an iOS and Android wrapper).")
#: Said once when the request itself demands a native app. EITHER answer's words
#: in the brief mean it was answered, so it is never asked twice.
NATIVE_CONFIRM_YES = "Continue with the web app and phone wrapper"
NATIVE_CONFIRM_NO = "No, I need a native app"


def _native_demanded(brief: str) -> bool:
    """The request itself demands a native phone app. "mobile-first" and "responsive"
    are design stances; iOS/Android as the SUBJECT of a business is not a demand."""
    text = re.sub(r"mobile[- ]first", "", brief or "", flags=re.I)
    if _NATIVE_STRONG.search(text):
        return True
    if _SOFTENERS.search(text) and not (_NOT_WEB.search(text) and _NATIVE_WEAK.search(text)):
        return False
    for m in _NATIVE_WEAK.finditer(text):
        if _BUSINESS_AFTER.match(text[m.end():m.end() + 40]) or _BUSINESS_BEFORE.search(text[max(0, m.start() - 30):m.start()]):
            continue
        return True
    return False


def native_declined(brief: str) -> bool:
    """The person said they need a native app after all."""
    return NATIVE_CONFIRM_NO.lower() in (brief or "").lower()


def native_confirmation(brief: str) -> dict | None:
    """The single question when the request demands a native app: it cannot be
    honoured, so say so and ask once whether to continue."""
    low = (brief or "").lower()
    if not _native_demanded(brief) or NATIVE_CONFIRM_YES.lower() in low or NATIVE_CONFIRM_NO.lower() in low:
        return None
    return {"question": ("You asked for a native app. " + WEB_AND_PHONE + " It is not a native "
                         "React Native, Flutter or Swift project. Shall I continue on that basis?"),
            "options": [NATIVE_CONFIRM_YES, NATIVE_CONFIRM_NO]}


#: What to tell a person who still needs a native app, plainly.
NATIVE_DECLINED_SAY = ("A native project is not something I build here: the app will be the responsive web app with "
                       "the phone wrapper, and the code can be taken and built natively outside. Say so plainly, "
                       "do not ask again, and define it.")


def _default_provider(prompt: str) -> str:
    from services.llm_client import complete

    return complete(content=prompt, max_tokens=400)


_DESIGN_ATTACHED = """

A DESIGN FILE IS ATTACHED to this brief as its visual specification. Colour,
typography, spacing and layout are settled by it: do not ask about any of
them, and do not propose palettes."""


#: Appended when the ORGANISATION has a design language on record.
#:
#: Not a suppression, unlike `_DESIGN_ATTACHED`. A Figma file attached to this
#: brief has settled the question; a company palette has only made an answer
#: available, and "not every app a company builds should look like the
#: company" is a real position — a public storefront or a white-label tool are
#: the obvious cases. So the question still gets asked, with the company's own
#: palette as the first thing offered.
#:
#: Which is the whole point: the clarifier was asking "which colour palette
#: should this use?" of an organisation that had already told us, during
#: onboarding, exactly what it looks like. Being asked to retype an answer the
#: product already holds is the same failure the discovery exists to prevent.
_COMPANY_PALETTE = """

THIS ORGANISATION HAS A DESIGN LANGUAGE ON RECORD, read from its own website.
If you ask about colour, the FIRST option you offer must be exactly this
string, copied verbatim:

    {option}

Offer one or two alternatives after it for an application that should NOT look
like the rest of the company's things, and keep them concrete in the usual
way. Do not describe the company's palette in your own words and do not
propose a variation on it."""


def company_palette_option(company_name: str, summary: str = "") -> str:
    """The exact option string offered for the company's own design language.

    One definition, used by the prompt that offers it and by the recogniser
    that reads the answer back — two spellings of this would mean a person
    picking the option and nothing happening.
    """
    label = (company_name or "").strip() or "our company"
    detail = f" ({summary.strip()})" if summary.strip() else ""
    return f"Use {label}'s own palette{detail}"


def clarify_brief(
    brief: str,
    *,
    provider: Callable[[str], str] | None = None,
    design_attached: bool = False,
    company_palette: str = "",
) -> list[dict[str, Any]]:
    """`[{question, options}]` — empty when the brief stands on its own.

    `design_attached` says a Figma file travels with the brief. The prompt
    already tells the model not to ask about colour when a reference is
    attached; a bare link in the prose did not read as one, and it asked which
    palette fits a design that had already chosen its own.

    `company_palette` is the option string for the organisation's own design
    language, when it has one (`company_palette_option`). An attached design
    outranks it — that file was attached to THIS application, which is a
    statement about this application specifically — so the two are not
    combined.
    """
    text = (brief or "").strip()
    if not text:
        return []
    # THE BUILD HAS ONE SHAPE, SO THE ONLY THING TO SAY ABOUT IT IS SAID ONCE.
    native = native_confirmation(text)
    if native is not None:
        return [native]
    small = is_very_small(text)
    if small:
        text += ("\n\n(A very small application: do NOT ask about colour. The designer chooses "
                 "the direction from the domain.)")
    if design_attached:
        text = text + _DESIGN_ATTACHED
    elif company_palette.strip():
        text = text + _COMPANY_PALETTE.format(option=company_palette.strip())

    # BUILT BEFORE THE TRY. `str.format` on a prompt containing literal JSON
    # braces raises KeyError, and inside the guard below that is indis-
    # tinguishable from a provider that declined to answer — the clarifier
    # simply stopped asking anything and looked like it had decided not to.
    # A broken template is a bug here, not a degraded turn out there.
    prompt = _PROMPT.format(brief=text)

    call = provider or _default_provider
    try:
        raw = call(prompt)
    except Exception:  # noqa: BLE001 — a question is a courtesy, never a gate
        return []

    data = _parse(raw)
    if not isinstance(data, dict):
        return []

    out: list[dict[str, Any]] = []
    for item in (data.get("questions") or [])[:3]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        if _is_technology_question(question) or (small and _COLOUR_Q.search(question)):
            continue
        options = [str(o).strip() for o in (item.get("options") or [])
                   if str(o).strip()]
        out.append({"question": question, "options": options[:4]})
    return out


def _parse(raw: str) -> dict | None:
    """The JSON object in `raw`, however it was wrapped."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return None
