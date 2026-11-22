import { test } from "node:test";
import assert from "node:assert/strict";
import { listen, publishCrossing, listenerCount } from "../../geofence/hub.ts";
import type { GeofenceEvent } from "../../geofence/engine.ts";

const e = (id: string): GeofenceEvent => ({ id, type: "geofence.entered", geofenceId: "z", entityId: "o", entityType: "Order", lat: 0, lng: 0, occurredAt: 1, detectedAt: 2, metadata: {} });

test("every listener hears a crossing, and stops hearing when it stops listening", () => {
  const a: string[] = [], b: string[] = [];
  const stopA = listen((x) => a.push(x.id));
  const stopB = listen((x) => b.push(x.id));
  publishCrossing(e("1"));
  stopA();
  publishCrossing(e("2"));
  stopB();
  assert.deepEqual(a, ["1"]);
  assert.deepEqual(b, ["1", "2"]);
  assert.equal(listenerCount(), 0);
});

test("a listener that throws does not stop the others", () => {
  const heard: string[] = [];
  const s1 = listen(() => { throw new Error("broken screen"); });
  const s2 = listen((x) => heard.push(x.id));
  publishCrossing(e("3"));
  s1(); s2();
  assert.deepEqual(heard, ["3"]);
});
