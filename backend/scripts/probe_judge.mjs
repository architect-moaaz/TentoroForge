// What pressing a control did, judged from two fingerprints of the page. Pure,
// so it is tested without a browser (tests/services/test_a_choice_is_not_a_dead_button.py).
//
// A CHOICE (aria-pressed / aria-checked / aria-selected: Dine-in | Delivery) does
// its work by changing what is selected and what depends on it, not by
// navigating or calling anything. Reading that as "no navigation, no request,
// no visible change" called a working toggle dead (UAT F&B /order, 2026-10-04).
// A button that claims a selected state but never changes it is still dead.

/** True when the page looks different in any way a person would see. */
export function stateChanged(before, after) {
  return after.dialogs !== before.dialogs || after.expanded !== before.expanded
    || after.toasts > before.toasts || after.text !== before.text
    || after.pressed !== before.pressed || after.fields !== before.fields;
}

/**
 * The outcome of a press that made no request and went nowhere.
 * `choice`: the control carries a selected-state attribute; `wasSelected`:
 * it was the selected one before the press (pressing it again changes nothing,
 * and that is correct for a choice) - but ONLY when it has siblings that could
 * be selected instead. A lone control that is permanently "pressed" and never
 * changes anything is a dead button wearing a selected state.
 */
export function judgeQuiet({ before, after, choice = false, wasSelected = false, dialog = null, siblings = 0 }) {
  if (choice && (after.pressed !== before.pressed || after.fields !== before.fields)) {
    return { outcome: "chose", detail: "its selected state changed" + (after.fields !== before.fields ? " and so did the fields shown" : "") };
  }
  if (dialog || stateChanged(before, after)) {
    return { outcome: "changed", detail: dialog ? `asked "${dialog}"` : "the page changed" };
  }
  if (choice && wasSelected && siblings >= 1) {
    return { outcome: "chose", detail: "already the selected option" };
  }
  return { outcome: "nothing", detail: "no navigation, no request, no visible change" };
}

/** Run inside the page: the parts of the fingerprint a choice changes. */
export function choiceFingerprintSource() {
  const SELECTED = "[aria-pressed='true'], [aria-checked='true'], [aria-selected='true'], [data-state='on'], [data-state='active'], [data-state='checked'], [data-selected='true']";
  const main = document.querySelector("main") || document.body;
  const pressed = [...main.querySelectorAll(SELECTED)].map((e) => (e.textContent || "").trim().slice(0, 30)).join("|");
  const fields = [...main.querySelectorAll("input, select, textarea")]
    .filter((e) => e.type !== "hidden" && e.getBoundingClientRect().width > 0).length;
  return { pressed, fields };
}
