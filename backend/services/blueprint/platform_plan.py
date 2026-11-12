"""Which role uses which platform: the plan Smith shows BEFORE a multi-role app is made, when it is needed.

An app with one kind of user, or whose users would all be best served the same way, needs no plan: the one question
in `app_target` ("Where will people use it?") covers it. A plan is shown only when the brief names two or more roles
AND they would not all use the same platform AND at least one of them needs a phone. A driver who must share
a location while the screen is off and get an alert for each job is not served by the same screen as the manager who reads
the month's payouts.

HOW A ROLE IS PLACED (words in the brief, nothing hidden):
  * The roles are the people the brief names (customer, driver, admin, technician, ...).
  * What each one does is read from the lines about that role: a heading such as "Driver app:" owns the lines under it,
    and a sentence that names a role is about that role.
  * Phone signals: location sharing / GPS / tracking, push alerts, camera / photos, scanning, offline, on-the-go and
    field work, accepting jobs as they arrive. Desktop signals: dashboards, reports, analytics, tables, money,
    user and role management, configuration, monitoring.
  * A role with only phone signals is `mobile`; only desktop signals, `web`; both strongly, `both`. A customer is
    never made mobile on the role's name alone: it needs a signal. A driver, courier or technician starts leaning to
    mobile, an admin or manager to web, and the words can overturn that.

The answer is kept at `<output>/.forge/platform-plan.json`, and a plan that is accepted sets the app-wide choice in
`app_target` (so the rest of Forge reads one thing, as before).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FILE = ".forge/platform-plan.json"
PLATFORMS = ("mobile", "web", "both")

ACCEPT = "Accept this plan"
WEB_ONLY = "Web only"
OPTIONS: tuple[str, ...] = (ACCEPT, WEB_ONLY)
#: The first words of the question: how Smith's own turn is recognised in the history.
MARKER = "here is how i would split this app"

# ---- roles ------------------------------------------------------------------------------------------------------
# (label, kind, pattern). `kind` sets the leaning a role starts with: "provider" (does the job on the move) leans mobile,
# "office" leans web, "consumer" and "vendor" lean nowhere.
_ROLES: tuple[tuple[str, str, str], ...] = (
    ("Driver", "provider", r"drivers?|chauffeurs?"),
    ("Delivery partner", "provider", r"delivery (?:partners?|agents?|boys?|riders?|executives?)|couriers?"),
    ("Technician", "provider", r"technicians?|mechanics?|plumbers?|electricians?|installers?"),
    ("Field employee", "provider", r"field (?:employees?|staff|workers?|agents?|executives?)|inspectors?|surveyors?"),
    ("Service provider", "provider", r"service providers?|professionals?|caregivers?"),
    ("Customer", "consumer", r"customers?|riders?|passengers?|buyers?|shoppers?|guests?|patients?|students?|clients?|members?"),
    ("Merchant", "vendor", r"merchants?|vendors?|sellers?|restaurants?|shop owners?|store owners?"),
    ("Admin", "office", r"admins?|administrators?|back[- ]office|moderators?"),
    ("Manager", "office", r"managers?|owners?|operators?|dispatchers?|supervisors?"),
    ("Support", "office", r"support (?:team|agents?|staff)|customer support|help ?desk"),
    ("Finance", "office", r"finance (?:team|staff)|accountants?|accounts team"),
)
_ROLE_RX = [(label, kind, re.compile(rf"\b(?:{pat})\b", re.I)) for label, kind, pat in _ROLES]

_MOBILE_RX = [re.compile(p, re.I) for p in (
    r"\bgps\b", r"\b(?:live |real[- ]time |background )?location (?:track|shar|updat)\w*", r"\b(?:live|real[- ]time|continuous) (?:tracking|location)",
    r"\bturn[- ]by[- ]turn\b", r"\btrack\w* (?:the |their |a |his |her )?\w+ live\b", r"\blive (?:map|position|updates?)\b", r"\bnavigat\w+", r"\bpush notification", r"\binstant alert", r"\bcamera\b", r"\bphoto(?:s)? upload",
    r"\bupload (?:a )?photos?", r"\b(?:qr|bar ?code)\b", r"\bscan(?:ning)?\b", r"\boffline\b", r"\bon[- ]the[- ]go\b",
    r"\bin the field\b", r"\bon[- ]site\b", r"\bbackground\b", r"\bgo (?:online|offline)\b", r"\baccept(?:s|ing)?(?:/| or )?(?:reject|decline)?\w* (?:a |the |incoming )?(?:ride|job|order|request|trip|task)s?",
    r"\bbiometric", r"\bbluetooth\b", r"\bnfc\b",
)]
_DESKTOP_RX = [re.compile(p, re.I) for p in (
    r"\bdashboards?\b", r"\breports?\b", r"\banalytics\b", r"\btables?\b", r"\bspreadsheets?\b", r"\bfinanc\w+", r"\bpayouts?\b",
    r"\bbilling\b", r"\binvoic\w+", r"\b(?:user|role|driver|customer) management\b", r"\bmanage (?:the )?(?:drivers|customers|users|rides|orders)\b",
    r"\bconfigur\w+", r"\bmonitor\w*", r"\bauditing?\b", r"\bexport\w*", r"\bbulk\b", r"\bsettings\b", r"\bapprov\w+",
)]
_LEAN = {"provider": (1, 0), "office": (0, 1), "consumer": (0, 0), "vendor": (0, 0)}

_WEB_ONLY_RX = re.compile(r"\b(?:web[- ]only|website[- ]only|only (?:a )?(?:web|website)|no (?:mobile|native|phone) app|without (?:a )?(?:mobile|native) app)\b", re.I)


@dataclass
class RolePlan:
    role: str
    platform: str
    why: str
    phone: list[str] = field(default_factory=list)
    desk: list[str] = field(default_factory=list)


@dataclass
class Plan:
    needed: bool
    roles: list[RolePlan] = field(default_factory=list)
    why_not: str = ""

    @property
    def surface(self) -> str:
        """The app-wide choice this plan amounts to, in `app_target`'s words."""
        if not self.roles or all(r.platform == "web" for r in self.roles):
            return "web"
        if all(r.platform == "mobile" for r in self.roles):
            return "native_only"
        return "web_native"


# ---- reading the brief ------------------------------------------------------------------------------------------

def _roles_in(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    # "customer support" must not also make a Customer: a longer role name hides the shorter one inside it
    scrub = text
    for label, kind, rx in sorted(_ROLE_RX, key=lambda r: r[0] not in ("Support", "Finance", "Delivery partner", "Field employee", "Service provider")):
        if rx.search(scrub):
            found.append((label, kind))
            scrub = rx.sub(" ", scrub)
    return found


def _sentences(brief: str) -> list[tuple[str, str | None]]:
    """(sentence, the role whose heading it sits under or None). A short line naming one role, with no full stop, is a heading."""
    out: list[tuple[str, str | None]] = []
    heading: str | None = None
    for raw in re.split(r"[\r\n]+", brief):
        line = raw.strip(" \t-*•#>")
        if not line:
            continue
        roles = _roles_in(line)
        if len(line) <= 60 and len(roles) == 1 and not line.rstrip(":").endswith("."):
            heading = roles[0][0]
            out.append((line, heading))
            continue
        for sentence in re.split(r"(?<=[.!?;])\s+", line):
            if sentence.strip():
                out.append((sentence.strip(), heading))
    return out


def _owners(sentence: str, named: list[tuple[str, str]], heading: str | None) -> list[str]:
    """Whose line this is. A sentence that starts with a role ("Customers book a ride...") is that role's. Otherwise it
    belongs to the heading it sits under (an Admin line that says "manage drivers" is the Admin's, not the Driver's);
    with no heading, to every role it names."""
    rest = re.sub(r"^\W*(?:the |all |each |every |a |an )?", "", sentence, flags=re.I)
    for label, _kind, rx in _ROLE_RX:
        if (m := rx.search(rest)) and m.start() == 0:
            return [label]
    if heading:
        return [heading]
    return [label for label, _k in named]


def _hits(rx_list: list[re.Pattern], text: str) -> list[str]:
    return [m.group(0).lower() for rx in rx_list if (m := rx.search(text))]


def analyse(brief: str) -> Plan:
    """Place each role the brief names, and say whether a plan is worth showing."""
    text = str(brief or "")
    if not text.strip():
        return Plan(False, why_not="nothing to read")
    if _WEB_ONLY_RX.search(text):
        return Plan(False, why_not="the brief asks for the web only")

    kinds: dict[str, str] = {}
    phone: dict[str, list[str]] = {}
    desk: dict[str, list[str]] = {}
    for sentence, heading in _sentences(text):
        named = _roles_in(sentence)
        for label, kind in named:
            kinds.setdefault(label, kind)
        owners = _owners(sentence, named, heading)
        if heading and heading not in kinds:
            kinds[heading] = next(k for l, k, _r in _ROLE_RX if l == heading)
        m, d = _hits(_MOBILE_RX, sentence), _hits(_DESKTOP_RX, sentence)
        for owner in owners:
            phone.setdefault(owner, []).extend(m)
            desk.setdefault(owner, []).extend(d)

    if len(kinds) < 2:
        return Plan(False, why_not="one kind of user")

    roles: list[RolePlan] = []
    for label, kind in kinds.items():
        m = sorted(set(phone.get(label, [])))
        d = sorted(set(desk.get(label, [])))
        lean_m, lean_d = _LEAN[kind]
        score_m, score_d = len(m) + lean_m, len(d) + lean_d
        if kind == "consumer" and not m:
            platform, why = "web", "needs no phone features: it works in a browser, on a computer or a phone"
        elif kind == "consumer":
            # books or browses on the web, and wants the alerts and the live map on a phone
            platform, why = "both", "has phone needs (" + ", ".join(m[:3]) + "), and can still use the website"
        elif len(m) >= 2 and len(d) >= 2:
            platform, why = "both", "does phone work (" + ", ".join(m[:3]) + ") and desk work (" + ", ".join(d[:3]) + ")"
        elif score_m > score_d:
            platform = "mobile"
            why = ("needs " + ", ".join(m[:4])) if m else "works on the move, so a phone app suits it"
        else:
            platform = "web"
            why = ("works with " + ", ".join(d[:4])) if d else "is desk work: tables, forms and reports"
        roles.append(RolePlan(label, platform, why, m, d))

    platforms = {r.platform for r in roles}
    if len(platforms) == 1:
        return Plan(False, roles, f"every role would use the same platform ({platforms.pop()})")
    if not any(r.platform in ("mobile", "both") for r in roles):
        return Plan(False, roles, "no role needs a phone")
    return Plan(True, roles)


# ---- asking and reading the answer -------------------------------------------------------------------------------

_PLATFORM_WORDS = {"mobile": "Phone app", "web": "Website", "both": "Phone app and website"}


def question(plan: Plan) -> str:
    """What Smith says: the plan in short lines a customer can read, then how to answer."""
    lines = ["Here is how I would split this app, because your people do different jobs:", ""]
    for r in plan.roles:
        lines += [f"• {r.role}: {_PLATFORM_WORDS[r.platform]}. It {r.why}.", ""]
    lines += [
        "All of them share one back end, so a ride booked, a job accepted or a trip finished shows up everywhere at once.",
        "",
        "Accept this plan, or tell me what to change (for example: \"drivers: website too\" or \"web only\").",
    ]
    return "\n".join(lines)


def asked(history: list) -> int:
    """How many times Smith has put this plan: its own turns that begin with the marker words."""
    n = 0
    for turn in history:
        role, text = (turn if isinstance(turn, (tuple, list)) and len(turn) == 2 else (getattr(turn, "role", ""), getattr(turn, "text", "")))
        if str(role) != "user" and MARKER in str(text or "").lower():
            n += 1
    return n


_OVERRIDE_RX = re.compile(r"\b([a-z][a-z \-]{2,30}?)\s*(?::|=|->|as|on|should be|is|use|uses)\s*(web(?:site)?|mobile|phone(?: app)?|app|both)\b(?:\s+too)?", re.I)


def read_reply(text: str, plan: Plan) -> tuple[str, Plan] | None:
    """What a person's answer to the plan means: ("accept", plan), ("web", plan) or ("edit", changed plan); None when it
    is neither (the question is put again)."""
    said = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not said:
        return None
    if said == ACCEPT.lower() or re.fullmatch(r"(?:yes|ok(?:ay)?|accept|accepted|looks good|go ahead|sounds good|do it|that works)[.! ]*", said):
        return "accept", plan
    if said == WEB_ONLY.lower() or re.search(r"\bweb(?:site)?[- ]only\b|\bno (?:mobile|native|phone) app\b|\bjust (?:the )?(?:web|website)\b", said):
        return "web", plan
    changed = [RolePlan(r.role, r.platform, r.why, r.phone, r.desk) for r in plan.roles]
    touched = False
    for m in _OVERRIDE_RX.finditer(said):
        who, what = m.group(1).strip(), m.group(2).lower()
        too = m.group(0).lower().endswith(" too")
        what = "both" if what == "both" or too else "web" if what.startswith("web") else "mobile"
        for r in changed:
            label = r.role.lower()
            if who.rstrip("s") == label.rstrip("s") or label in who or who.rstrip("s") in label:
                if what != r.platform:
                    r.platform, r.why, touched = what, "was set by you", True
                else:
                    touched = True
    if touched:
        return "edit", Plan(plan.needed, changed)
    return None


def write(output_dir: str | Path, plan: Plan, status: str, decided_by: str = "person") -> None:
    path = Path(output_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": status, "decidedBy": decided_by, "surface": plan.surface,
        "roles": [{"role": r.role, "platform": r.platform, "why": r.why} for r in plan.roles],
    }, indent=2) + "\n", encoding="utf-8")


def read(output_dir: str | Path) -> dict | None:
    try:
        data = json.loads((Path(output_dir) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
