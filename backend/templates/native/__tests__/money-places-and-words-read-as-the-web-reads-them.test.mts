/**
 * Figures, places and words — the pure half of money, distance, language and
 * stored-file addresses. Money is MAJOR units in the app's currency; a distance
 * is shown, never the coordinates; a text is picked in the chosen language, else
 * the primary; a stored file's id is loaded through the preview route.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const f = await import("../src/sdk/format.ts");
const geo = await import("../src/sdk/geo.ts");

console.log("money");
eqJson(f.formatMoney(1240.5, { currency: "USD", locale: "en-US" }), "$1,240.50", "USD in en-US");
eqJson(f.formatMoney(1240.5, { currency: "GBP", locale: "en-GB" }), "£1,240.50", "GBP in en-GB");
eqJson(f.formatMoney(1234567.891, { currency: "INR", locale: "en-IN" }), "₹12,34,567.89", "INR groups in lakhs");
eqJson(f.formatMoney(12.5, { currency: "EUR", locale: "de-DE" }).replace(/ /g, " "), "12,50 €", "EUR the German way");
eqJson(f.formatMoney(0, { currency: "USD", locale: "en-US" }), "$0.00", "zero is an amount");
eqJson(f.formatMoney(Number.NaN, { currency: "USD" }), "", "not a number is nothing, not 'NaN'");
eqJson(f.formatMoney(12.5, { currency: "NOT-A-CODE" }), "NOT-A-CODE 12.50", "a bad currency code falls back to the code and the figure instead of throwing");
eqJson(f.currencySymbol("GBP", "en-GB"), "£", "a currency's symbol, for a money field's prefix");
eqJson(f.currencySymbol("NOT-A-CODE"), "NOT-A-CODE", "…the code when it cannot say");

console.log("numbers and cells");
eqJson(f.formatPercent(0.125, "en-US"), "12.5%", "0.125 is 12.5%");
eqJson(f.formatNumber(1234.5678, "en-US"), "1,234.57", "two decimals at most");
eqJson(f.formatCompact(1200, "en-US"), "1.2K", "compact for an axis");
eqJson(f.formatCell(null, "number", { currency: "USD" }), "—", "an empty cell is a dash");
eqJson(f.formatCell("Open", "currency", { currency: "USD" }), "Open", "a non-number is itself");
eqJson(f.formatCell(5, "currency", { currency: "USD", locale: "en-US" }), "$5.00", "a number in a currency column");
eqJson(f.humanize("placedAtLabel"), "Placed At", "a label key is humanised, 'Label' dropped");
eqJson(f.humanize("order_total"), "Order total", "snake case too");
eqJson([f.niceCeiling(0), f.niceCeiling(7), f.niceCeiling(130), f.niceCeiling(0.3)], [1, 10, 200, 0.5], "a gauge's round maximum");

console.log("dates");
eqJson(f.formatDate("2026-03-01", "en-US"), "Mar 1, 2026", "a bare date is that calendar day (not the day before, west of Greenwich)");
eqJson(f.formatDate("nonsense"), "nonsense", "unreadable in, same out");
eqJson(f.formatDate(null), "", "nothing in, nothing out");

console.log("language");
const T = { en: "Orders", hi: "ऑर्डर" };
eqJson([f.pick(T, "hi", "en"), f.pick(T, "hi-IN", "en"), f.pick(T, "fr", "en"), f.pick("plain", "hi", "en"), f.pick({ de: "x" }, "fr", "en")],
  ["ऑर्डर", "ऑर्डर", "Orders", "plain", "x"], "chosen language, its base tag, else the primary; a plain string as it is; else any");
const offered = [{ tag: "en" }, { tag: "hi" }];
eqJson([f.knownLanguage("hi", offered), f.knownLanguage("hi-IN", offered), f.knownLanguage("fr", offered), f.knownLanguage(null, offered)], ["hi", "hi", null, null],
  "a saved language tag is kept only if the app offers it");

console.log("stored files");
const id = "0f8fad5b-d9cb-469f-a165-70867728950e";
eqJson(f.filePath(id), `/api/files/preview?src=${id}`, "an id is loaded through the preview route");
eqJson(f.filePath("https://cdn.example/a.png"), "https://cdn.example/a.png", "a URL is used as it is");
eqJson([f.filePath(""), f.filePath(null)], [null, null], "nothing is nothing");

console.log("places");
const london = { lat: 51.507, lng: -0.128 }, paris = { lat: 48.857, lng: 2.352 };
ok(Math.abs((geo.distanceKm(london, paris) ?? 0) - 343) < 3, "London to Paris is about 343 km");
eqJson(geo.distanceKm(london, null), null, "an unknown end is no distance");
eqJson(geo.distanceKm(london, london), 0, "here to here is zero");
eqJson([geo.formatDistance(0.64, "en-GB"), geo.formatDistance(12, "en-GB"), geo.formatDistance(0.01, "en-US")], ["0.4 mi", "7.5 mi", "< 0.1 mi"], "miles where people count in miles");
eqJson([geo.formatDistance(0.65, "fr-FR"), geo.formatDistance(4.26, "fr-FR"), geo.formatDistance(12.4, "fr-FR")], ["700 m", "4.3 km", "12 km"], "metres and kilometres elsewhere");
eqJson(geo.formatDistance(null), "", "an unknown distance is blank");
eqJson(geo.parseNear("51.507,-0.128"), london, "?near= parses");
eqJson([geo.parseNear("91,0"), geo.parseNear("x"), geo.parseNear(null)], [null, null, null], "out of range, junk and nothing are not places");
eqJson(geo.roundPoint({ lat: 51.50735, lng: -0.12776 }), { lat: 51.507, lng: -0.128 }, "a position is kept to about 100 m");
ok(geo.isPoint(london) && !geo.isPoint({ lat: "1", lng: 2 }) && !geo.isPoint(null), "isPoint");

done("money, places and words");
