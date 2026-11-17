"""Does this app need zones on a map, and which ones: read from the brief, in plain words, nothing hidden.

A brief needs geofencing when it says something happens WHEN something moves into, out of or near a place: "alert me when a
driver reaches the customer", "clock a nurse in when she is on site", "tell the manager when a truck leaves the depot". The
word "geofence" is one signal, not the only one. A brief that only says "live tracking" is NOT a geofencing brief: following a
dot on a map needs no zones.

WHAT COMES OUT (`Plan`):
  * `scenario` — delivery, ride, fleet, attendance, retail pickup or restricted area: the one the words fit best.
  * `evidence` — the phrases that decided it, so a person can see why.
  * `zones` — the places to draw. A zone gets coordinates ONLY when the brief gives them
    ("Zone: Depot — circle 150 m at 12.9716, 77.5946"). Forge has no map lookup and will not invent where a restaurant is:
    the others are `needsDrawing` and the owner draws them on the zones screen.
  * `rules` — what to do when a crossing happens, already safe: an action that finishes a job, takes payment or marks someone
    present is never produced from a crossing alone (a crossing is where a phone SAYS it is). Rules tell people or put a
    named event on the bus; a workflow does the rest. A rule is bound to one zone by NAME; it is created only when that zone
    exists, never left loose to fire at every zone.

The plan is kept at `<output>/.forge/geofence-plan.json`, copied into the app as `contracts/geofence-plan.json`, and the
blueprint's `geofencing` section is filled from it. The app's seed creates the zones that have coordinates and the rules
that belong to them (see `runtime/geofence/plan.ts`).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

FILE = ".forge/geofence-plan.json"

# ---- is it a geofencing brief --------------------------------------------------------------------------------------
# (weight, pattern). "geofence" itself is conclusive; the rest must agree with each other (two separate phrases).
_STRONG = re.compile(r"\bgeo[- ]?fenc\w*|\bvirtual (?:fence|perimeter|boundar\w+)|\bgeo[- ]?zones?\b", re.I)
_WEAK: tuple[re.Pattern[str], ...] = tuple(re.compile(p, re.I) for p in (
    r"\b(?:when|once|as soon as|if|whenever)\b[^.\n]{0,60}\b(?:arriv\w+|reach\w*|enter\w*|leav\w+|exit\w*|cross\w*|near|approach\w*|within \d+\s?(?:m|km|meters?|metres?|ft|feet|miles?))\b",
    r"\b(?:arriv\w+|reach\w*|enter\w*|leav\w+|exit\w*|cross\w*) (?:at |in |into |from )?(?:the |a |an |their |his |her )?(?:pickup|pick-up|drop[- ]?off|drop|restaurant|store|shop|site|depot|warehouse|campus|school|hospital|office|area|zone|region|boundary|perimeter|destination|customer'?s?\w*|location|on[- ]?site)",
    r"\bwithin \d+\s?(?:m|km|meters?|metres?|ft|feet|miles?) of\b",
    r"\b(?:auto|automatic\w*)[- ]?(?:check|clock)[- ]?(?:in|out)\b",
    r"\b(?:out of|outside|inside|restricted|unauthori[sz]ed|off[- ]limits)\b[^.\n]{0,25}\b(?:area|zone|region|boundary|perimeter|route)\b",
    r"\b(?:alert|notify|tell|warn|ping|message)\b[^.\n]{0,50}\b(?:arriv\w+|leav\w+|enter\w*|exit\w*|near|reach\w*|out of|outside)\b",
    r"\bdwell\w*|\bidle (?:at|in)\b|\bstays? (?:at|in|for)\b[^.\n]{0,20}\b(?:minutes?|mins?|hours?)\b",
))

_DISTANCE = re.compile(r"\b(?:when|once|as soon as|if|whenever|alert|notify|tell)\b[^.\n]{0,70}\bwithin \d+(?:\.\d+)?\s?(?:m|km|meters?|metres?|ft|feet|miles?)\b", re.I)

#: A scenario and the words that point at it. The one with the most distinct hits wins; a tie goes to the earlier line.
_SCENARIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("delivery", (r"\bdeliver\w*", r"\bdelivery partners?\b", r"\bcourier\w*", r"\brestaurant\w*", r"\bfood\b", r"\bparcel\w*", r"\border\w*", r"\bdrop[- ]?off\b", r"\bgrocer\w+")),
    ("ride", (r"\brides?\b", r"\bpassenger\w*", r"\btaxi\b|\bcab\b", r"\btrips?\b", r"\bpick[- ]?up (?:point|location)\b", r"\bfare\b")),
    ("fleet", (r"\bfleet\b", r"\bvehicles?\b", r"\btrucks?\b", r"\bdepot\b", r"\bwarehouse\b", r"\bconsignment\w*|\bshipment\w*|\bcargo\b", r"\broute\w*")),
    ("attendance", (r"\battendance\b", r"\bclock[- ]?(?:in|out)\b", r"\bcheck[- ]?(?:in|out)\b", r"\bshift\w*", r"\bon[- ]?site\b", r"\bfield (?:staff|employees?|workers?)\b", r"\btimesheet\w*", r"\bnurses?\b|\bcaregivers?\b")),
    ("retail", (r"\bcurbside\b", r"\bin[- ]?store\b", r"\bclick (?:and|&) collect\b", r"\bstore pickup\b", r"\bnear (?:the |our )?store\b", r"\bloyalty\b")),
    ("restricted", (r"\brestricted\b", r"\bunauthori[sz]ed\b", r"\boff[- ]limits\b", r"\bperimeter\b", r"\bwander\w*", r"\bchild\w*|\bkids?\b", r"\bsafe zone\b", r"\bdanger\w*")),
)
_SCENARIO_RX = {k: [re.compile(p, re.I) for p in ps] for k, ps in _SCENARIOS}


# ---- what each scenario gets ---------------------------------------------------------------------------------------
# A zone is (name, shape, radiusM, what it is for). A rule is (zone name | None, onEvent, action, note). None = every zone — used only
# where the same thing is right for every zone of the app.
def _notify(title: str, body: str, role: str = "Admin") -> dict:
    return {"kind": "notify", "title": title, "body": body, "role": role}


def _emit(event: str, **payload: str) -> dict:
    return {"kind": "emit_event", "event": event, "payload": payload}


_TEMPLATES: dict[str, dict] = {
    "delivery": {
        "zones": [("Restaurant pickup", 100, "where a driver counts as arrived at the kitchen"),
                  ("Customer drop-off", 150, "where a driver counts as near the customer's door", {"approachM": 400})],
        "rules": [
            ("Restaurant pickup", "geofence.entered", _emit("order.driver_at_restaurant", orderId="{{entityId}}"), "tell the order's workflow the driver is at the kitchen"),
            ("Customer drop-off", "geofence.approaching", _emit("order.driver_near_customer", orderId="{{entityId}}"), "the customer's own workflow can tell them the driver is close"),
            ("Customer drop-off", "geofence.entered", _emit("order.driver_at_customer", orderId="{{entityId}}"), "the driver is at the door; handing over is still confirmed by a code or a tap, never by the crossing"),
        ],
        "notes": ["Arriving never marks an order delivered or paid. Hand-over stays a person's tap or a customer's code."],
    },
    "ride": {
        "zones": [("Pickup point", 80, "where a driver counts as arrived for the passenger", {"approachM": 300}),
                  ("Drop-off point", 120, "where a trip counts as at its destination")],
        "rules": [
            ("Pickup point", "geofence.entered", _emit("trip.driver_at_pickup", tripId="{{entityId}}"), "the passenger's workflow can say the driver is here"),
            ("Drop-off point", "geofence.entered", _emit("trip.vehicle_at_destination", tripId="{{entityId}}"), "the trip is not ended or charged by this; the driver ends it"),
        ],
        "notes": ["A trip is never ended or charged from a crossing."],
    },
    "fleet": {
        "zones": [("Depot", 250, "the home base of the fleet", {"dwellSec": 1800})],
        "rules": [
            ("Depot", "geofence.entered", _emit("vehicle.arrived_at_depot", vehicleId="{{entityId}}"), "a vehicle is back"),
            ("Depot", "geofence.exited", _emit("vehicle.left_depot", vehicleId="{{entityId}}"), "a vehicle went out"),
            ("Depot", "geofence.dwell", _notify("Vehicle idle at depot", "A vehicle has stayed at the depot a long time."), "tell a manager about a long stay"),
        ],
        "notes": ["Dwell is judged by the zone's stay time, set on the zone."],
    },
    "attendance": {
        "zones": [("Work site", 200, "where a person counts as on site")],
        "rules": [
            ("Work site", "geofence.entered", _emit("person.entered_site", personId="{{entityId}}"), "a person's phone reached the site"),
            ("Work site", "geofence.exited", _emit("person.left_site", personId="{{entityId}}"), "a person's phone left the site"),
        ],
        "notes": ["Being near the site is NOT being checked in. Checking in or out stays a tap by the person or a manager, because a phone's position can be wrong or faked."],
    },
    "retail": {
        "zones": [("Store", 150, "close enough to start getting an order ready", {"approachM": 500})],
        "rules": [
            ("Store", "geofence.approaching", _emit("order.customer_near_store", orderId="{{entityId}}"), "start preparing"),
            ("Store", "geofence.entered", _emit("order.customer_at_store", orderId="{{entityId}}"), "bring it out; the pickup itself is confirmed by staff"),
        ],
        "notes": [],
    },
    "restricted": {
        "zones": [("Restricted area", 200, "an area that should be entered only by those allowed")],
        "rules": [
            ("Restricted area", "geofence.entered", _notify("Entered a restricted area", "Someone has entered a restricted area."), "tell a manager at once"),
        ],
        "notes": [],
    },
}

_UNIT_M = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0, "km": 1000.0, "ft": 0.3048, "feet": 0.3048, "mi": 1609.344, "mile": 1609.344, "miles": 1609.344}

#: "Zone: Depot — circle 150 m at 12.9716, 77.5946"   /   `geofence "North gate" 80m @ 12.97,77.59`
_ZONE_RX = re.compile(
    r"(?:zone|geo[- ]?fence|fence)s?\s*[:\-–—]?\s*[\"“']?(?P<name>[A-Za-z][\w &/'\-]{1,40}?)[\"”']?\s*[,:\-–—(]*\s*"
    r"(?:(?:a |an )?(?:circle|circular|radius)\s*(?:of\s*)?)?(?P<r>\d+(?:\.\d+)?)\s*(?P<u>km|mi|miles?|ft|feet|m|meters?|metres?)\b\s*(?:radius\s*)?"
    r"(?:around|at|@|centred on|centered on|near)?\s*\(?\s*(?P<lat>-?\d{1,2}\.\d+)\s*[,;/ ]\s*(?P<lng>-?\d{1,3}\.\d+)\)?",
    re.I)


@dataclass
class Zone:
    name: str
    radiusM: float
    purpose: str = ""
    lat: float | None = None
    lng: float | None = None
    #: True when the brief gave no coordinates: the owner draws it.
    needsDrawing: bool = True
    #: How the zone behaves (the zone settings): approachM, dwellSec... Without them "driver is near" and "stayed a long time" never fire.
    rules: dict = field(default_factory=dict)


@dataclass
class Plan:
    needed: bool
    scenario: str = ""
    evidence: list[str] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    why_not: str = ""

    def to_json(self) -> dict:
        return asdict(self)


# ---- reading the brief ---------------------------------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "")


def _evidence(text: str) -> list[str]:
    seen: list[str] = []
    for rx in (_STRONG, _DISTANCE, *_WEAK):
        for m in rx.finditer(text):
            line = re.sub(r"\s+", " ", m.group(0)).strip()
            if line.lower() not in (s.lower() for s in seen):
                seen.append(line)
            if len(seen) >= 6:
                return seen
    return seen


def _hits(text: str) -> tuple[bool, list[str]]:
    """True when this is a geofencing brief, with the phrases that say so. The word itself decides alone. Otherwise two DIFFERENT weak
    phrases must agree, so a stray "when a customer arrives" in a bookings app does not give it zones."""
    strong = bool(_STRONG.search(text))
    weak = [rx for rx in _WEAK if rx.search(text)]
    # A distance is as good as a second phrase: "when the driver is within 300 m" can only mean a zone.
    if _DISTANCE.search(text):
        weak.append(_DISTANCE)
    moving = re.search(r"\b(?:gps|location|driver|courier|vehicle|truck|fleet|rider|deliver\w*|nurse|technician|field|on[- ]?site|tracking|phone|app)\b", text, re.I)
    return strong or (len(weak) >= 2 and bool(moving)), _evidence(text)


def _scenario(text: str) -> str:
    best, top = "", 0
    for name, rxs in _SCENARIO_RX.items():
        n = sum(1 for rx in rxs if rx.search(text))
        if n > top:
            best, top = name, n
    return best


def _given_zones(text: str) -> list[Zone]:
    out: list[Zone] = []
    for m in _ZONE_RX.finditer(text):
        lat, lng = float(m["lat"]), float(m["lng"])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue
        r = float(m["r"]) * _UNIT_M.get(m["u"].lower(), 1.0)
        if not (5 <= r <= 50_000):
            continue
        name = re.sub(r"\s+", " ", m["name"]).strip(" -–—,:")
        if name and name.lower() not in (z.name.lower() for z in out):
            out.append(Zone(name=name[:60], radiusM=round(r, 1), purpose="given in the brief", lat=lat, lng=lng, needsDrawing=False))
    return out


def analyse(brief: str) -> Plan:
    text = _clean(brief)
    needed, evidence = _hits(text)
    if not needed:
        return Plan(needed=False, why_not="The brief does not say that anything happens when something enters, leaves or comes near a place.")
    scenario = _scenario(text) or "restricted"
    tpl = _TEMPLATES[scenario]
    given = _given_zones(text)
    planned = [Zone(name=z[0], radiusM=float(z[1]), purpose=z[2], rules=dict(z[3]) if len(z) > 3 else {}) for z in tpl["zones"]]
    # A zone given in the brief stands in for the template zone it names; the rest of the template stays to be drawn.
    zones: list[Zone] = list(given)
    for g in given:
        t = next((z for z in planned if z.name.lower() == g.name.lower()), None)
        if t:
            g.rules = dict(t.rules)
    for z in planned:
        if not any(g.name.lower() == z.name.lower() for g in given):
            zones.append(z)
    names = {z.name.lower() for z in zones}
    rules = [{"zone": z, "onEvent": ev, "action": act, "note": note} for z, ev, act, note in tpl["rules"] if z is None or z.lower() in names]
    return Plan(needed=True, scenario=scenario, evidence=evidence, zones=zones, rules=rules, notes=list(tpl["notes"]))


# ---- keeping it ----------------------------------------------------------------------------------------------------

def write(output_dir: str | Path, plan: Plan) -> Path:
    p = Path(output_dir) / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan.to_json(), indent=2), encoding="utf-8")
    return p


def read(output_dir: str | Path) -> dict | None:
    try:
        d = json.loads((Path(output_dir) / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("needed") else None


def section(plan: dict | None) -> dict | None:
    """The blueprint's `geofencing` section for a plan read back from disk, or None."""
    if not plan or not plan.get("needed"):
        return None
    return {
        "enabled": True,
        "scenario": plan.get("scenario", ""),
        "evidence": list(plan.get("evidence") or []),
        "zones": [{k: z.get(k) for k in ("name", "radiusM", "purpose", "lat", "lng", "needsDrawing", "rules")} for z in plan.get("zones") or []],
        "rules": [{k: r.get(k) for k in ("zone", "onEvent", "action", "note")} for r in plan.get("rules") or []],
        "notes": list(plan.get("notes") or []),
    }


def apply(doc: dict, plan: dict | None) -> None:
    """Put the `geofencing` section on the blueprint. No plan, no section."""
    s = section(plan)
    if s:
        doc["geofencing"] = s
    else:
        doc.pop("geofencing", None)


def question(plan: Plan) -> str:
    """What Smith says to the owner: what was understood and what is left for them. Plain words."""
    if not plan.needed:
        return ""
    drawn = [z for z in plan.zones if not z.needsDrawing]
    todo = [z for z in plan.zones if z.needsDrawing]
    out = [f"This app reacts when something enters, leaves or comes near a place ({plan.scenario.replace('_', ' ')})."]
    if drawn:
        out.append("Zones from your brief: " + ", ".join(f"{z.name} ({z.radiusM:g} m)" for z in drawn) + ".")
    if todo:
        out.append("Zones for you to draw on the Zones screen once the app is up: " + ", ".join(z.name for z in todo) + ". I do not guess where a place is.")
    out.extend(plan.notes)
    return " ".join(out)
