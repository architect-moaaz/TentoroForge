/**
 * The arithmetic under a map-first screen, without a device: the resting heights of a bottom sheet (shares of the room, or
 * points, never too small, never past the room, no repeats), where a drag comes to rest (a slow drag to the nearest height,
 * a flick on in its direction), how far a sheet gives past its ends, and when a map is drawn dark (under a dark design).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const logic = await import("../src/ui/logic.ts");
const types = await import("../src/sdk/map-types.ts");

console.log("resting heights");
eqJson(logic.sheetHeights([0.2, 0.5, 0.9], 1000), [200, 500, 900], "shares of the room become points");
eqJson(logic.sheetHeights([150, 400], 1000), [150, 400], "points stay points");
eqJson(logic.sheetHeights([0.9, 0.2, 0.5], 1000), [200, 500, 900], "they are sorted");
eqJson(logic.sheetHeights([10, 0.5], 1000), [72, 500], "never under the floor (a thumb must find the handle)");
eqJson(logic.sheetHeights([0.5, 1, 2000], 800), [400, 800], "never past the room, and the repeat is dropped");
eqJson(logic.sheetHeights([0.3, 0.3], 600), [180], "two the same are one");

console.log("where a drag comes to rest");
const rest = [200, 500, 900];
eqJson(logic.settleSheet(230, 0, rest), 0, "a slow drag near the bottom goes to the bottom");
eqJson(logic.settleSheet(380, 0, rest), 1, "a slow drag goes to the nearest height");
eqJson(logic.settleSheet(700, 0, rest), 1, "700 is nearer 500 than 900");
eqJson(logic.settleSheet(760, 0, rest), 2, "and 760 is nearer 900");
eqJson(logic.settleSheet(300, -2, rest), 2, "a hard flick UP from near the bottom carries it to the top");
eqJson(logic.settleSheet(800, 2, rest), 1, "a flick DOWN from near the top carries it to the middle");
eqJson(logic.settleSheet(800, 3, rest), 0, "a very hard flick DOWN carries it all the way to the bottom");
eqJson(logic.settleSheet(500, 0.2, rest), 1, "a gentle push down does not leave the middle");
eqJson(logic.settleSheet(500, 0, []), 0, "no heights, no move");

console.log("a drag has a little give past its ends");
eqJson(logic.dragShown(500, 100, rest), 400, "dragging down 100 from 500 shows 400");
eqJson(logic.dragShown(500, -100, rest), 600, "dragging up shows more");
const pastTop = logic.dragShown(900, -400, rest);
ok(pastTop > 900 && pastTop <= 924, `past the top it gives a little, not all the way (${pastTop})`);
const pastBottom = logic.dragShown(200, 400, rest);
ok(pastBottom < 200 && pastBottom >= 176, `past the bottom likewise (${pastBottom})`);
eqJson(logic.dragShown(500, 50, []), 500, "nothing to drag between: it stays");

console.log("a map goes dark under a dark design");
ok(types.isDarkColour("#0f1117") === true, "near-black hex is dark");
ok(types.isDarkColour("#fafafa") === false, "near-white hex is not");
ok(types.isDarkColour("#111") === true, "three-digit hex");
ok(types.isDarkColour("rgb(20, 22, 30)") === true, "rgb dark");
ok(types.isDarkColour("rgb(240, 240, 240)") === false, "rgb light");
ok(types.isDarkColour("hsl(222 20% 8%)") === true || types.isDarkColour("hsl(222, 20%, 8%)") === true, "hsl dark");
ok(types.isDarkColour("hsl(210, 20%, 98%)") === false, "hsl light");
ok(types.isDarkColour("") === false && types.isDarkColour(null) === false && types.isDarkColour("banana") === false, "unreadable is not dark (never a dark map by guess)");

done("a map-first screen's arithmetic");
