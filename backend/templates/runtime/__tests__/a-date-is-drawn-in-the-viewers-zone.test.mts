/**
 * The server draws a date in the viewer's zone and language, as their browser
 * will: React kept throwing DITANS's server pages away (#418) because every
 * date without a zone came out in UTC on the server and in the person's own
 * zone in the browser (2026-11-18).
 *
 * Runs the SHIPPED lib/viewer-time.ts with the process in UTC, as a server is.
 */
import { installHarness, eqJson, ok, done } from "./_harness.mts";

installHarness();
process.env.TZ = "UTC";
const vt: any = await import("../viewer-time.ts");

const at = new Date("2026-11-18T22:30:00Z");  // 02:30 on the 19th in Dubai

console.log("who the viewer is");
eqJson(vt.viewerOf({ cookie: encodeURIComponent("Asia/Dubai|en-GB") }), { timeZone: "Asia/Dubai", locale: "en-GB" }, "the browser's own word first");
eqJson(vt.viewerOf({ ipTimeZone: "Asia/Riyadh", acceptLanguage: "ar-SA,ar;q=0.9,en;q=0.8" }), { timeZone: "Asia/Riyadh", locale: "ar-SA" }, "else the address's zone and the first language asked for");
eqJson(vt.viewerOf({ cookie: encodeURIComponent("Not/AZone|xx-!!"), ipTimeZone: "Asia/Kolkata" }), { timeZone: "Asia/Kolkata", locale: undefined }, "a made-up zone or language is not believed");
eqJson(vt.viewerOf({ pathname: "/api/workflows/abc/execute", cookie: encodeURIComponent("Asia/Dubai|en-GB") }), null, "an API route keeps the server's defaults");
eqJson(vt.viewerOf({}), null, "a request that says nothing changes nothing");

console.log("nothing changes until it is installed, or outside a page");
const before = at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
eqJson(before, "22:30", "the server's own zone, as before");

let viewer: any = { timeZone: "Asia/Dubai", locale: "en-GB" };
vt.installViewerTime(() => viewer);

console.log("drawn as the viewer's browser draws it");
eqJson(at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }), "02:30", "a time in the viewer's zone");
eqJson(at.toLocaleDateString("en-GB", { day: "numeric", month: "short" }), "19 Nov", "and the viewer's day");
eqJson(at.toLocaleDateString(), "19/11/2026", "no language given: the viewer's");
eqJson(new Intl.DateTimeFormat("en-GB", { weekday: "long" }).format(at), "Thursday", "Intl.DateTimeFormat with new");
eqJson(Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(at), "02:30", "and called without new");
eqJson(Intl.DateTimeFormat().resolvedOptions().timeZone, "Asia/Dubai", "a page that shows 'your time zone' names theirs");
ok(new Intl.DateTimeFormat() instanceof Intl.DateTimeFormat, "instanceof still holds");
eqJson(Intl.DateTimeFormat.supportedLocalesOf(["en-GB"]), ["en-GB"], "supportedLocalesOf still answers");
eqJson(typeof new Intl.DateTimeFormat("en-GB").formatToParts(at), "object", "formatToParts still works");

console.log("what a page names is kept");
eqJson(at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }), "22:30", "its own zone");
eqJson(at.toLocaleDateString("en-US", { month: "short", day: "numeric" }), "Nov 19", "its own language, in the viewer's zone");

console.log("numbers in the viewer's language");
viewer = { timeZone: "Europe/Berlin", locale: "de-DE" };
eqJson((1234.5).toLocaleString(), "1.234,5", "a number with no language given");
eqJson((1234.5).toLocaleString("en-GB"), "1,234.5", "one with its own language kept");
eqJson(new Intl.NumberFormat().format(1234.5), "1.234,5", "Intl.NumberFormat too");

console.log("outside a page request, the server's defaults");
viewer = null;
eqJson(at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }), "22:30", "a job or an API route sees UTC");
viewer = { timeZone: "Asia/Dubai" };
vt.installViewerTime(() => ({ timeZone: "Asia/Kolkata" }));
eqJson(at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }), "04:00", "installed twice: the new reader, never wrapped twice");
vt.installViewerTime(() => { throw new Error("no store"); });
eqJson(at.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }), "22:30", "a reader that fails changes nothing");

done("viewer time-zone");
