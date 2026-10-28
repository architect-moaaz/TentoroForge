"""Where people will use the app: what Smith asks, and what the answer sets.

Smith asks this once, first, before the app is defined (`services.smith4.definition`). The answer is kept beside where
the Blueprint will be (`<output>/.forge/app-target.json`) and read when the Blueprint is created
(`BlueprintService.create`), which writes it to `mobile.surface` and sets `mobile.native.enabled` from it. From then
on the Blueprint is the only truth: the Publish step turns the mobile app on for an app built without it by changing
that field, and never reads this file.

  web          a website that also works on phones
  web_native   the website AND a native (Expo) app: every page is also written as a phone screen
  web_pwa      the website, installable from the browser (a PWA)
  native_only  only the phone app: the web app is its backend and has no pages
  pwa_only     a phone-first website, installed from the browser

An app made before Smith asked has `responsive` or `native` in this file; they are read as `web` and `web_native`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FILE = ".forge/app-target.json"
SURFACES = ("web", "web_native", "web_pwa", "native_only", "pwa_only")
#: The two values the create dialog used to send, and what they meant.
_LEGACY = {"responsive": "web", "native": "web_native"}
#: Every value `write` accepts. (Kept under its old name: the build scripts and tests import it.)
TARGETS = SURFACES + tuple(_LEGACY)

#: The chips, in the order they are offered: `(surface, label)`. A person answers with a chip, so these are also the
#: words `parse_choice` matches first.
OPTIONS: tuple[tuple[str, str], ...] = (
    ("web", "Web only"),
    ("web_native", "Web + native app"),
    ("web_pwa", "Web + PWA"),
    ("native_only", "Native app only"),
    ("pwa_only", "PWA only"),
)
LABEL = dict(OPTIONS)

#: What Smith asks, word for word. A PWA's limits are said here, where the choice is made, not discovered later.
QUESTION = (
    "Where will people use it?\n\n"
    "• Web only: a website that works on computers and phones.\n\n"
    "• Web + native app: the website, plus an app people download on iPhone and Android.\n\n"
    "• Web + PWA: the website, which people can also add to their phone's home screen like an app.\n\n"
    "• Native app only: just the iPhone and Android app. There is no website.\n\n"
    "• PWA only: just a phone-friendly website that people add to their home screen.\n\n"
    "A PWA is a website added to the home screen, so it has some limits:\n\n"
    "• It is not in the app stores.\n\n"
    "• On iPhone, people add it by hand (Share, then Add to Home Screen).\n\n"
    "• Bluetooth, NFC and location tracking in the background do not work on iPhone.\n\n"
    "• It works offline only for screens already opened.\n\n"
    "• It feels a little less like a downloaded app."
)


def write(output_dir: str | Path, target: str) -> bool:
    """Keep the choice for the Blueprint to read. False when `target` is not one we know."""
    surface = _LEGACY.get(target, target)
    if surface not in SURFACES:
        return False
    path = Path(output_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target": surface}) + "\n", encoding="utf-8")
    return True


def read(output_dir: str | Path) -> str | None:
    """One of `SURFACES`, or None when nothing was chosen (an app made before the choice existed)."""
    try:
        said = json.loads((Path(output_dir) / FILE).read_text(encoding="utf-8")).get("target")
    except (OSError, ValueError, AttributeError):
        return None
    said = _LEGACY.get(said, said)
    return said if said in SURFACES else None


def parse_choice(text: str) -> str | None:
    """The surface a person's answer names: one of the chips as it was sent, or the same thing in their own words.
    None when it names none, or more than one."""
    said = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not said:
        return None
    for surface, label in OPTIONS:
        if said == label.lower():
            return surface
    web = bool(re.search(r"\b(web|website|site)\b", said))
    native = bool(re.search(r"\b(native|iphone|android|ios)\b", said))
    pwa = bool(re.search(r"\bpwa\b|installable|progressive", said))
    only = bool(re.search(r"\b(only|just)\b", said))
    if native and pwa:
        return None                                  # both named: that is not one choice
    if native or pwa:
        # "web and native" is the website AND the app; "only native" is the app alone; "native" by itself could be
        # either, so it is not an answer and the question is asked again.
        if web and not only:
            return "web_native" if native else "web_pwa"
        if only and not web:
            return "native_only" if native else "pwa_only"
        return None
    if web:
        return "web"
    return None


def bundle_for(name: str) -> str:
    """The id the stores know the app by, made from its name: `com.tentoro.leafy`. Each part starts with a letter
    (a name that starts with a digit or has no letters gets `app` in front), as the Blueprint's contract asks."""
    word = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    if not word or not word[0].isalpha():
        word = "app" + word
    return f"com.tentoro.{word}"


def has_web_pages(surface: str | None) -> bool:
    """False only for the choice that has no website: the web app is then a backend, and writes no pages."""
    return surface != "native_only"


def has_native(surface: str | None) -> bool:
    return surface in ("web_native", "native_only")


def web_pages_enabled(doc: object) -> bool:
    """Does this application write web pages? The Blueprint answers: `mobile.surface`. True for an app made before the
    choice existed (nothing there) and for every choice but `native_only`."""
    mobile = doc.get("mobile") if isinstance(doc, dict) else None
    surface = mobile.get("surface") if isinstance(mobile, dict) else None
    return has_web_pages(surface if isinstance(surface, str) else None)


def apply(doc: dict, target: str | None) -> dict:
    """Record the choice in the Blueprint (`mobile.surface`) and set `mobile.native.enabled` from it. An explicit False
    when there is no native app, so the choice is written down and a later reader (or Smith) sees that the owner asked
    for none, and the server's own default can never start the native agent for them.

    A NATIVE APP NAMES ITS BUNDLE ID: the Blueprint's contract refuses `mobile.native` without `mobile.store.bundleId`
    (the first real build failed its requirements step on exactly this), so a native choice carries one made from
    the app's name, which the owner can change later."""
    surface = _LEGACY.get(target or "", target)
    if surface in SURFACES:
        mobile = doc.setdefault("mobile", {})
        mobile["surface"] = surface
        mobile.setdefault("native", {})["enabled"] = has_native(surface)
        if has_native(surface):
            store = mobile.setdefault("store", {})
            if not str(store.get("bundleId") or "").strip():
                store["bundleId"] = bundle_for((doc.get("application") or {}).get("name"))
    return doc
