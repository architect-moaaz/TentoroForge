/**
 * The road and the time: a route line comes from a service as an encoded string.
 * It must decode to the right places, be thinned without losing its ends, and
 * "how far is left" must count down as the traveller moves along it.
 */
let failed = 0;
const ok = (c: unknown, name: string) => { if (!c) { failed++; console.error("FAIL", name); } };
const near = (a: number, b: number, tol: number, name: string) => ok(Math.abs(a - b) <= tol, `${name} (got ${a}, want ${b})`);

const { decodePolyline, thinPath, pathKm, alongPath }: any = await import("../../app-foundation/src/sdk/geo.ts");

// the worked example in Google's own polyline documentation
const p = decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@");
ok(p.length === 3, "three points");
near(p[0].lat, 38.5, 1e-5, "lat 0"); near(p[0].lng, -120.2, 1e-5, "lng 0");
near(p[1].lat, 40.7, 1e-5, "lat 1"); near(p[1].lng, -120.95, 1e-5, "lng 1");
near(p[2].lat, 43.252, 1e-5, "lat 2"); near(p[2].lng, -126.453, 1e-5, "lng 2");
ok(decodePolyline("").length === 0, "empty string, no points");

// thinning keeps both ends and the count
const long = Array.from({ length: 1000 }, (_, i) => ({ lat: 12 + i * 0.0001, lng: 77 }));
const thin = thinPath(long, 100);
ok(thin.length <= 101 && thin.length >= 50, `thinned (${thin.length})`);
ok(thin[0].lat === long[0].lat && thin[thin.length - 1].lat === long[999].lat, "ends kept");
ok(thinPath(long.slice(0, 5), 100).length === 5, "a short path is left alone");

// counting down along a line
const line = Array.from({ length: 101 }, (_, i) => ({ lat: 12 + i * 0.001, lng: 77 }));
const total = pathKm(line);
near(total, 11.12, 0.1, "length of 0.1 degree of latitude");
const halfway = alongPath(line, { lat: 12.05, lng: 77 });
near(halfway.remainingKm, total / 2, 0.2, "half left at the middle");
ok(halfway.offRouteKm < 0.05, "on the line");
const start = alongPath(line, line[0]);
near(start.remainingKm, total, 0.05, "all left at the start");
const away = alongPath(line, { lat: 12.05, lng: 77.02 });
ok(away.offRouteKm > 1.5, `off the line is noticed (${away.offRouteKm})`);

console.log(failed ? `road: ${failed} failed` : "road: all passed");
process.exit(failed ? 1 : 0);
