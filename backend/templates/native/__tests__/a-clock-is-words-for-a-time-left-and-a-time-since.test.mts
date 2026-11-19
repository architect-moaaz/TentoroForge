/** The clocks of a map screen, as words: a time left as m:ss, a time since as `12 min`, and a time that is not there as nothing. */
import { installHarness, eqJson, done } from "./_harness.mts";

installHarness();
const logic = await import("../src/ui/logic.ts");

console.log("a time left");
eqJson(logic.countdownText(161_000), "2:41", "two minutes forty-one");
eqJson(logic.countdownText(5_000), "0:05", "seconds are padded");
eqJson(logic.countdownText(-4_000), "0:00", "never negative");
eqJson(logic.countdownText(1), "0:01", "a part of a second counts as one");

console.log("a time to an ISO moment");
eqJson(logic.msUntil(null, 1000), null, "no time, no number");
eqJson(logic.msUntil("not a date", 1000), null, "a bad time is no time");
eqJson(logic.msUntil(new Date(61_000).toISOString(), 1000), 60_000, "a minute ahead");
eqJson(logic.msUntil(new Date(0).toISOString(), 1000), -1000, "passed is negative");

console.log("a time since");
eqJson(logic.elapsedText(20_000), "just now", "under a minute");
eqJson(logic.elapsedText(12 * 60_000), "12 min", "minutes");
eqJson(logic.elapsedText(65 * 60_000), "1 h 5 min", "hours and minutes");
eqJson(logic.elapsedText(120 * 60_000), "2 h", "whole hours");

done();
