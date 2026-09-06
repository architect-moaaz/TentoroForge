"""The transform's mode belongs to the call, not the module.

The page fan-out composes twelve frames at once on worker threads. The canvas
mode, the fit and the drawing depth were module globals, so one frame's
`finally: mode = False` landed in the middle of another's transform, which
finished under the off-canvas rules: a dashboard's table — positioned cells,
a drawing — came out as a wrapping flex row with its height stripped, while
its canvas record still said `fluid`. Direct calls could never reproduce it;
only the run could, and differently each time.
"""
import threading

from services.jsx_to_schema import transform_jsx_to_schema

FRAME = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="flex gap-[16px] w-[1097px] h-[85px] shrink-0" data-node-id="1:3">
          <div className="bg-white w-[355px] h-[85px] shrink-0 flex flex-col" data-node-id="1:4"><p>a</p></div>
          <div className="bg-white w-[355px] h-[85px] shrink-0 flex flex-col" data-node-id="1:5"><p>b</p></div>
        </div>
        <div className="relative w-[340px] h-[120px]" data-node-id="1:6">
          <div className="absolute left-[10px] top-[20px] w-[30px] h-[85px]" />
          <div className="absolute left-[50px] top-[40px] w-[30px] h-[65px]" />
        </div>
      </div>
    </div>
  );
}
'''


def _cls(root, node_id):
    if isinstance(root, dict):
        p = root.get("props") or {}
        if p.get("_figmaNodeId") == node_id:
            return (p.get("className") or "").split()
        for c in root.get("children") or []:
            hit = _cls(c, node_id)
            if hit is not None:
                return hit
    return None


def test_canvas_and_flow_transforms_interleaved_on_threads_stay_apart():
    failures: list[str] = []
    stop = threading.Event()

    def on_canvas():
        while not stop.is_set():
            r = transform_jsx_to_schema(FRAME, {}, canvas=(1387.0, 982.0))
            if r.get("canvasFit") != "fluid" or "max-w-[355px]" not in _cls(r, "1:4") \
                    or "w-[340px]" not in _cls(r, "1:6"):
                failures.append("canvas frame lost its canvas")

    def off_canvas():
        while not stop.is_set():
            r = transform_jsx_to_schema(FRAME, {})
            if "canvasFit" in r or "max-w-[355px]" in (_cls(r, "1:4") or []):
                failures.append("flowed frame gained a canvas")

    threads = [threading.Thread(target=on_canvas) for _ in range(4)] + \
              [threading.Thread(target=off_canvas) for _ in range(4)]
    for t in threads:
        t.start()
    import time
    time.sleep(1.5)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert not failures, failures[:3]


def test_a_thread_starts_with_no_mode():
    """A fresh thread — a worker that never called the entry point — is off
    the canvas, the same as the module was before any call."""
    from services import jsx_to_schema as m
    seen = {}
    t = threading.Thread(target=lambda: seen.update(mode=m._canvas_mode(), fit=m._canvas_fit(), drawing=m._in_drawing()))
    t.start(); t.join()
    assert seen == {"mode": False, "fit": "scale", "drawing": False}
