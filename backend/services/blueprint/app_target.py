"""What the person chose when they created the app: a website that works on phones, or a website AND a mobile app.

The choice is made in the "Describe Your App" dialog, before there is a Blueprint. It is kept beside where the
Blueprint will be (`<output>/.forge/app-target.json`) and read when the Blueprint is created
(`BlueprintService.create`), which sets `mobile.native.enabled`. From then on the Blueprint is the only truth: the
Publish step turns the mobile app on for an app built without it by changing that field, and never reads this file.

  responsive   a website that works on phones - the native agent never runs, whatever the server's default says
  native       a website and a native (Expo) app: every page is also written as a phone screen
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FILE = ".forge/app-target.json"
TARGETS = ("responsive", "native")


def write(output_dir: str | Path, target: str) -> bool:
    """Keep the choice for the Blueprint to read. False when `target` is not one of the two."""
    if target not in TARGETS:
        return False
    path = Path(output_dir) / FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target": target}) + "\n", encoding="utf-8")
    return True


def read(output_dir: str | Path) -> str | None:
    """`responsive`, `native`, or None when nothing was chosen (an app made before the choice existed)."""
    try:
        said = json.loads((Path(output_dir) / FILE).read_text(encoding="utf-8")).get("target")
    except (OSError, ValueError, AttributeError):
        return None
    return said if said in TARGETS else None


def bundle_for(name: str) -> str:
    """The id the stores know the app by, made from its name: `com.tentoro.leafy`. Each part starts with a letter
    (a name that starts with a digit or has no letters gets `app` in front), as the Blueprint's contract asks."""
    word = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    if not word or not word[0].isalpha():
        word = "app" + word
    return f"com.tentoro.{word}"


def apply(doc: dict, target: str | None) -> dict:
    """Set `mobile.native.enabled` from the choice. An explicit False for `responsive`, so the server's own default
    (`FORGE_NATIVE_APP`) cannot start the native agent for an app whose owner asked for a website.

    A NATIVE APP NAMES ITS BUNDLE ID: the Blueprint's contract refuses `mobile.native` without `mobile.store.bundleId`
    (the first real build failed its requirements step on exactly this), so a native choice carries one made from
    the app's name, which the owner can change later."""
    if target in TARGETS:
        mobile = doc.setdefault("mobile", {})
        mobile.setdefault("native", {})["enabled"] = target == "native"
        if target == "native":
            store = mobile.setdefault("store", {})
            if not str(store.get("bundleId") or "").strip():
                store["bundleId"] = bundle_for((doc.get("application") or {}).get("name"))
    return doc
