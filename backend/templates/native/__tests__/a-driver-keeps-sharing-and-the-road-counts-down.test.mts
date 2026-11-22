/**
 * Live tracking on the phone, the half with no screen in it: how a driver's notes go out (a reading at most every
 * 4 s, waiting notes retried, "still here" when they stand still, a refusal that retrying cannot mend ends the
 * queue) and how the road counts down (the line decodes, the distance left shrinks as they move, the arrival
 * time follows, a driver off the line is noticed). The same rules as the web's.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const sender = await import("../src/sdk/tracking-core.ts");
const geo = await import("../src/sdk/geo.ts");
const route = await import("../src/sdk/route-core.ts");

// ---- the sender -----------------------------------------------------------------------------------------------
function rig(answers: Array<{ status: number; error?: string }>) {
  const log = { clock: 1_000_000, posted: [] as any[], sent: 0, errors: [] as Array<string | null> };
  let i = 0;
  const s = sender.createSender({
    now: () => log.clock,
    post: async (note: any) => { log.posted.push(note); return answers[Math.min(i++, answers.length - 1)]; },
    onSent: () => { log.sent++; },
    onError: (m: string | null) => { log.errors.push(m); },
  });
  return { s, log };
}
const note = (lat: number, at = 0) => ({ entity: "Ride", trip: "r1", lat, lng: 77.59, at });
const settle = () => new Promise((r) => setTimeout(r, 0));

console.log("a reading goes out, and not again too soon");
{
  const { s, log } = rig([{ status: 200 }]);
  ok(s.reading(note(12.97)) === true, "the first reading is taken");
  await settle();
  eqJson(log.sent, 1, "and sent");
  log.clock += 1_000;
  ok(s.reading(note(12.98)) === false, "a reading one second later is too soon");
  log.clock += 4_000;
  ok(s.reading(note(12.99)) === true, "one after the interval is taken");
}

console.log("a note that could not go out waits, and is tried again without a new reading");
{
  const { s, log } = rig([{ status: 0 }, { status: 0 }, { status: 200 }]);
  s.reading(note(12.97));
  await settle();
  eqJson(s.waiting(), 1, "the note waits after a network failure");
  eqJson(log.errors.at(-1), "Could not send your location — trying again.", "and says so in words");
  await s.tick();
  eqJson(s.waiting(), 1, "a retry while the line is still down keeps it");
  await s.tick();
  eqJson(s.waiting(), 0, "a retry once the line is back sends it");
  eqJson(log.sent, 1, "and counts it");
  eqJson(log.errors.at(-1), null, "and the message goes away");
}

console.log("the phone says it is online: waiting notes go at once");
{
  const { s } = rig([{ status: 503 }, { status: 200 }]);
  s.reading(note(12.97));
  await settle();
  eqJson(s.waiting(), 1, "a server in trouble keeps the note");
  await s.online();
  eqJson(s.waiting(), 0, "back online sends it");
}

console.log("a driver standing still says 'still here'");
{
  const { s, log } = rig([{ status: 200 }]);
  s.reading(note(12.97));
  await settle();
  log.clock += 10_000;
  await s.tick();
  eqJson(log.posted.length, 1, "ten seconds of quiet is not yet worth a note");
  log.clock += 15_000;
  await s.tick();
  eqJson(log.posted.length, 2, "twenty-five seconds is");
  eqJson(log.posted[1].lat, 12.97, "the last known spot");
  ok(log.posted[1].at > log.posted[0].at, "with a fresh time, so the line does not read as lost");
}

console.log("a long outage keeps the latest notes only");
{
  const { s, log } = rig([{ status: 0 }]);
  for (let n = 0; n < 60; n++) { log.clock += 5_000; s.reading(note(12 + n / 1000, log.clock)); await settle(); }
  eqJson(s.waiting(), sender.MAX_QUEUE, "never more than the cap");
}

console.log("a refusal retrying cannot mend ends the queue; a lapsed sign-in keeps it");
{
  const a = rig([{ status: 403 }]);
  a.s.reading(note(12.97)); await settle();
  eqJson(a.s.waiting(), 0, "not your trip: the queue is emptied");
  eqJson(a.log.errors.at(-1), "This trip is not yours to share.", "and it says so");
  const b = rig([{ status: 409, error: "The ride was cancelled." }]);
  b.s.reading(note(12.97)); await settle();
  eqJson(b.s.waiting(), 0, "the job is over: emptied");
  eqJson(b.log.errors.at(-1), "The ride was cancelled.", "with the server's own sentence");
  const c = rig([{ status: 401 }]);
  c.s.reading(note(12.97)); await settle();
  eqJson(c.s.waiting(), 1, "a lapsed sign-in keeps the note");
  eqJson(c.log.errors.at(-1), "Sign in to share your location.", "and says to sign in");
}

// ---- the road -------------------------------------------------------------------------------------------------
console.log("the line decodes");
{
  const p = geo.decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@");
  eqJson(p.length, 3, "Google's own example has three points");
  ok(Math.abs(p[0].lat - 38.5) < 1e-5 && Math.abs(p[0].lng + 120.2) < 1e-5, "the first place is right");
  ok(Math.abs(p[2].lat - 43.252) < 1e-5 && Math.abs(p[2].lng + 126.453) < 1e-5, "and the last");
  eqJson(geo.decodePolyline("").length, 0, "nothing is no points");
}

console.log("the distance left counts down as they move along it");
{
  const path = Array.from({ length: 101 }, (_, i) => ({ lat: 12 + i * 0.001, lng: 77 }));
  const info = { provider: "google", path, distanceKm: geo.pathKm(path), durationMin: 30, approximate: false } as any;
  const start = route.progress(info, path[0], 0);
  const half = route.progress(info, { lat: 12.05, lng: 77 }, 0);
  const end = route.progress(info, path[100], 0);
  ok(Math.abs(start.remainingKm - info.distanceKm) < 0.05 && Math.abs(start.etaMin - 30) < 0.5, "all of it is left at the start");
  ok(Math.abs(half.remainingKm - info.distanceKm / 2) < 0.2 && Math.abs(half.etaMin - 15) < 0.7, "half at the middle");
  ok(end.remainingKm < 0.05 && end.etaMin < 0.5, "none at the end");
  ok(half.arriveAt.getTime() - 0 === Math.round(half.etaMin * 60_000) || Math.abs(half.arriveAt.getTime() - half.etaMin * 60_000) < 5, "the arrival is the time left from now");
  ok(route.progress(info, { lat: 12.05, lng: 77.02 }, 0).offRoute === true, "two kilometres off the line is noticed");
  ok(half.offRoute === false, "on the line is not");
  const straight = { provider: "straight-line", path: [path[0], path[100]], distanceKm: info.distanceKm * 1.3, durationMin: 40, approximate: true } as any;
  ok(Math.abs(route.progress(straight, path[0], 0).remainingKm - info.distanceKm * 1.3) < 0.1, "a straight line is counted 30% longer, as the server did");
}

console.log("when to ask for a new road");
{
  const a = { lat: 12.9, lng: 77.5 }, b = { lat: 12.95, lng: 77.6 };
  const info = { provider: "google", path: [a, b], distanceKm: 8, durationMin: 20, approximate: false } as any;
  ok(route.shouldAsk(null, null, a, b, 1_000, false) === true, "the first time, yes");
  const asked = { at: 1_000, from: a, to: b };
  ok(route.shouldAsk(asked, info, a, b, 2_000, false) === false, "nothing changed, no");
  ok(route.shouldAsk(asked, info, a, { lat: 13.1, lng: 77.7 }, 2_000, false) === true, "a new destination, yes at once");
  ok(route.shouldAsk(asked, info, { lat: 12.9, lng: 77.55 }, b, 5_000, false) === false, "off the line but asked three seconds ago: wait");
  ok(route.shouldAsk(asked, info, { lat: 12.9, lng: 77.55 }, b, 20_000, false) === true, "off the line, and long enough: ask");
  ok(route.shouldAsk(asked, info, a, b, 20_000, true) === false, "never twice at once");
  ok(route.shouldAsk(asked, info, { lat: 12.9, lng: 77.5004 }, b, 70_000, false) === false, "a minute old but they have not moved: no");
}

console.log("the words");
eqJson(route.minutesText(0.2), "< 1 min", "under a minute");
eqJson(route.minutesText(26.4), "26 min", "minutes");
eqJson(route.minutesText(65), "1 h 5 min", "hours");
eqJson(route.minutesText(null), "", "unknown is nothing");
ok(/Google/.test(route.routeSource({ provider: "google" } as any)), "Google is named");
ok(/straight line/.test(route.routeSource({ provider: "straight-line" } as any)), "a straight line is called one");

done("live tracking on the phone");
