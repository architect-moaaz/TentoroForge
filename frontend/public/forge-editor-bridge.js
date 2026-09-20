/**
 * Forge editor bridge — injected by the editor into its own same-origin
 * preview iframe (never shipped with the app).
 *
 * What it does: turns clicks into selections of the element's source node
 * (`data-fid`, which the editor stamps on the running copy of each page),
 * draws hover/selection outlines, supports a region drag that resolves to
 * node ids, takes a palette item dropped onto the page (the editor decides
 * where it lands and inserts it), lets a selected element be dragged to a
 * new place on the page (the editor decides where it lands and moves it),
 * treats one field of a form as a thing of its own (click to choose it, drag
 * to reorder it, its right edge to widen it), offers a resize edge on the
 * selected element, reports where the app navigates to, and steps out of the
 * way entirely in Preview mode.
 *
 * Protocol: messages are `{type: "forge-editor:<name>", payload}`, posted to
 * the parent at the page's own origin.
 */
(function () {
  "use strict";
  if (window.__forgeEditorBridge || window.parent === window) return;
  window.__forgeEditorBridge = true;

  var PREFIX = "forge-editor:";
  var Z = 2147483000;
  var mode = "design"; // design | preview | region
  var selected = [];
  var labels = {};
  var hovered = null;
  var selectedField = null;   // the name of the chosen field of the one selected form

  // --- overlays ------------------------------------------------------------
  var layer = document.createElement("div");
  layer.setAttribute("data-forge-editor", "layer");
  layer.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:" + Z + ";";
  var hoverBox = box("rgba(37,99,235,0.08)", "1px dashed rgba(37,99,235,0.9)");
  layer.appendChild(hoverBox);
  var regionBox = box("rgba(37,99,235,0.10)", "1px solid rgba(37,99,235,0.9)");
  layer.appendChild(regionBox);
  // Where a dragged palette item would land: a box for "inside", a bar for
  // "before"/"after" — the editor decides which and says so (drop-hint).
  var dropBox = box("rgba(37,99,235,0.12)", "2px solid #2563eb");
  layer.appendChild(dropBox);
  var dropBar = box("#2563eb", "0");
  layer.appendChild(dropBar);
  // The element being moved, travelling with the pointer.
  var ghost = box("rgba(37,99,235,0.10)", "2px dashed #2563eb");
  ghost.style.opacity = "0.85";
  layer.appendChild(ghost);
  var selectBoxes = [];
  // The chosen field of a form, inside the form's own outline.
  var fieldBox = box("rgba(37,99,235,0.10)", "2px solid #2563eb");
  layer.appendChild(fieldBox);
  // The right edge of what is selected, to drag wider or narrower.
  var edge = document.createElement("div");
  edge.setAttribute("data-forge-editor", "edge");
  edge.style.cssText = "position:fixed;display:none;width:8px;margin-left:-4px;cursor:ew-resize;pointer-events:auto;background:transparent;z-index:" + (Z + 1) + ";";
  var edgeGrip = document.createElement("div");
  edgeGrip.style.cssText = "position:absolute;left:1px;top:50%;width:6px;height:24px;margin-top:-12px;border-radius:3px;background:#2563eb;border:1px solid #fff;";
  edge.appendChild(edgeGrip);
  layer.appendChild(edge);
  var resizeBox = box("rgba(37,99,235,0.06)", "2px dashed #2563eb");
  layer.appendChild(resizeBox);
  document.documentElement.appendChild(layer);

  function box(bg, border) {
    var el = document.createElement("div");
    el.style.cssText = "position:fixed;display:none;box-sizing:border-box;border-radius:3px;background:" + bg + ";border:" + border + ";";
    return el;
  }
  function tag(text) {
    var el = document.createElement("div");
    el.textContent = text;
    el.style.cssText = "position:absolute;left:-1px;top:-20px;padding:1px 6px;font:11px/16px system-ui,sans-serif;color:#fff;background:#2563eb;border-radius:3px 3px 0 0;white-space:nowrap;";
    return el;
  }
  function place(el, r) {
    el.style.display = "block";
    el.style.top = r.top + "px";
    el.style.left = r.left + "px";
    el.style.width = r.width + "px";
    el.style.height = r.height + "px";
  }
  function isOurs(el) {
    return !!(el && el.closest && el.closest("[data-forge-editor]"));
  }
  // --- which source node a DOM node belongs to ------------------------------
  // The editor stamps `data-fid` on every JSX element of the page. An HTML
  // element renders it as an attribute; a COMPONENT receives it as a prop and
  // most never pass it on — WidgetView, Chart, WorkflowForm drew a chart with
  // no `data-fid` anywhere in it, so a click on the chart selected the grid
  // around it. React still knows: every DOM node points at its fiber, and a
  // component's fiber keeps its props. So ownership is read off the fiber
  // tree — the innermost element OR component carrying `data-fid` — and a
  // component's outline is the union of the DOM it rendered. The DOM lookup
  // stays as the fallback when there is no fiber to read.
  function fiberOf(el) {
    if (!el) return null;
    for (var k in el) if (k.indexOf("__reactFiber$") === 0) return el[k];
    return null;
  }
  function fidOfFiber(f) {
    var p = f && f.memoizedProps;
    return p && typeof p === "object" && typeof p["data-fid"] === "string" ? p["data-fid"] : null;
  }
  /** The fid that owns a DOM node, or null. */
  function ownerFid(node) {
    if (!node || isOurs(node)) return null;
    var el = node.nodeType === 1 ? node : node.parentElement;
    // A library draws some of its own DOM (ECharts makes its <canvas> and
    // the divs around it): climb to the nearest node React made.
    var start = el;
    while (start && !fiberOf(start)) start = start.parentElement;
    for (var f = fiberOf(start); f; f = f.return) {
      var fid = fidOfFiber(f);
      if (fid) return fid;
    }
    var d = el && el.closest ? el.closest("[data-fid]") : null;
    return d && !isOurs(d) ? d.getAttribute("data-fid") : null;
  }
  var fidIndex = null;   // fid -> fiber, rebuilt after the page changes
  function fiberForFid(fid) {
    if (!fidIndex) {
      fidIndex = {};
      var all = document.body.getElementsByTagName("*");
      for (var i = 0; i < all.length; i++) {
        if (isOurs(all[i])) continue;
        for (var f = fiberOf(all[i]); f; f = f.return) {
          var id = fidOfFiber(f);
          if (id && !fidIndex[id]) fidIndex[id] = f;
        }
      }
    }
    return fidIndex[fid] || null;
  }
  /** The top-level DOM nodes a fid rendered, in order. */
  function nodesOf(fid) {
    if (!fid) return [];
    var f = fiberForFid(fid);
    if (!f) {
      var el = document.querySelector('[data-fid="' + fid.replace(/"/g, '\\"') + '"]');
      return el ? [el] : [];
    }
    if (f.stateNode && f.stateNode.nodeType === 1) return [f.stateNode];
    var out = [];
    (function walk(c) {
      for (; c; c = c.sibling) {
        if (c.stateNode && c.stateNode.nodeType === 1) out.push(c.stateNode);
        else walk(c.child);
      }
    })(f.child);
    return out;
  }
  function byFid(fid) { return nodesOf(fid)[0] || null; }
  /** The form field a DOM node sits in: `{fid, name, el}`, or null. The SDK
   *  stamps `data-forge-field`; an older SDK's field is the grid child that
   *  holds a control labelled `f-<name>`. */
  function fieldOf(node) {
    if (!node || isOurs(node)) return null;
    var el = node.nodeType === 1 ? node : node.parentElement;
    var w = el && el.closest ? el.closest("[data-forge-field]") : null;
    var name = w ? w.getAttribute("data-forge-field") : null;
    if (!w) {
      var lab = el && el.closest ? el.closest("form") : null;
      if (!lab) return null;
      for (var c = el; c && c !== lab; c = c.parentElement) {
        var ctl = c.querySelector && c.querySelector("[id^='f-']");
        if (ctl && c.parentElement && c.parentElement.parentElement === lab) { w = c; name = ctl.id.slice(2); break; }
      }
    }
    if (!w || !name) return null;
    var fid = ownerFid(w);
    return fid ? { fid: fid, name: name, el: w } : null;
  }
  /** Every field of the form that owns `fid`, in order. */
  function fieldsOf(fid) {
    var out = [];
    var els = nodesOf(fid);
    for (var i = 0; i < els.length; i++) {
      var form = els[i].tagName === "FORM" ? els[i] : els[i].querySelector("form");
      if (!form) continue;
      var stamped = form.querySelectorAll("[data-forge-field]");
      if (stamped.length) { for (var j = 0; j < stamped.length; j++) out.push({ name: stamped[j].getAttribute("data-forge-field"), el: stamped[j] }); return out; }
      var grid = form.firstElementChild;
      for (var k = 0; grid && k < grid.children.length; k++) {
        var ctl = grid.children[k].querySelector("[id^='f-']");
        if (ctl) out.push({ name: ctl.id.slice(2), el: grid.children[k] });
      }
      return out;
    }
    return out;
  }
  function fieldEl(fid, name) {
    var fs = fieldsOf(fid);
    for (var i = 0; i < fs.length; i++) if (fs[i].name === name) return fs[i].el;
    return null;
  }
  function rectOfFid(fid) {
    var els = nodesOf(fid);
    var t = Infinity, l = Infinity, b = -Infinity, r = -Infinity;
    for (var i = 0; i < els.length; i++) {
      var x = els[i].getBoundingClientRect();
      if (!x.width && !x.height) continue;
      t = Math.min(t, x.top); l = Math.min(l, x.left); b = Math.max(b, x.bottom); r = Math.max(r, x.right);
    }
    return t === Infinity ? null : { top: t, left: l, width: r - l, height: b - t };
  }
  function rectOf(el) {
    var r = el.getBoundingClientRect();
    return { top: r.top, left: r.left, width: r.width, height: r.height };
  }
  function send(type, payload) {
    try { window.parent.postMessage({ type: PREFIX + type, payload: payload || {} }, window.location.origin); } catch (e) { /* not cloneable */ }
  }

  function drawEdge() {
    fieldBox.style.display = "none";
    edge.style.display = "none";
    if (mode !== "design" || selected.length !== 1) return;
    var r = rectOfFid(selected[0]);
    if (selectedField) {
      var fe = fieldEl(selected[0], selectedField);
      if (!fe) { selectedField = null; } else { r = rectOf(fe); place(fieldBox, r); }
    }
    if (!r) return;
    place(edge, { top: r.top, left: r.left + r.width, width: 8, height: r.height });
  }
  function drawSelection() {
    while (selectBoxes.length) layer.removeChild(selectBoxes.pop());
    if (mode === "preview") return;
    drawEdge();
    var rects = {};
    for (var i = 0; i < selected.length; i++) {
      var r = rectOfFid(selected[i]);
      if (!r) continue;
      rects[selected[i]] = r;
      var b = box("rgba(37,99,235,0.06)", "2px solid #2563eb");
      place(b, r);
      if (labels[selected[i]] && r.top > 22) b.appendChild(tag(labels[selected[i]]));
      layer.appendChild(b);
      selectBoxes.push(b);
    }
    return rects;
  }
  var rectsTimer = null;
  function reportRects() {
    clearTimeout(rectsTimer);
    rectsTimer = setTimeout(function () {
      var rects = drawSelection() || {};
      send("rects", { rects: rects, scrollY: window.scrollY, width: window.innerWidth });
    }, 40);
  }

  // --- pointer -------------------------------------------------------------
  document.addEventListener("mousemove", function (e) {
    if (mode !== "design" || (moving && moving.started) || resizing || isOurs(e.target)) return;
    var fid = ownerFid(e.target);
    if (fid !== hovered) {
      hovered = fid;
      var hr = fid && rectOfFid(fid);
      if (hr) { place(hoverBox, hr); send("hover", { fid: fid, rect: hr }); }
      else { hoverBox.style.display = "none"; send("hover", { fid: null }); }
    }
  }, true);
  document.addEventListener("mouseleave", function () { hoverBox.style.display = "none"; }, true);

  function swallow(e) { e.preventDefault(); e.stopPropagation(); }
  document.addEventListener("click", function (e) {
    if (mode === "preview") return;
    swallow(e);
    if (mode !== "design") return;
    // The click that ends a move is not a selection.
    if (moved) { moved = false; return; }
    var fid = ownerFid(e.target);
    var fld = fieldOf(e.target);
    send("select", { fid: fid, rect: fid ? rectOfFid(fid) : null, field: fld && fld.fid === fid ? fld.name : null,
                     shift: e.shiftKey, meta: e.metaKey || e.ctrlKey });
  }, true);
  document.addEventListener("dblclick", function (e) {
    if (mode !== "design") return;
    swallow(e);
    var fid = ownerFid(e.target);
    if (fid) send("edit-text", { fid: fid, rect: rectOfFid(fid) });
  }, true);
  // In design mode nothing in the app should run from a pointer.
  ["mousedown", "mouseup", "pointerdown", "pointerup", "submit", "change", "input"].forEach(function (evt) {
    document.addEventListener(evt, function (e) {
      if (mode === "design" && !isOurs(e.target)) { if (evt === "submit" || evt === "mousedown" || evt === "pointerdown") swallow(e); }
    }, true);
  });

  document.addEventListener("keydown", function (e) {
    if (mode === "preview") return;
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "") || (e.target && e.target.isContentEditable);
    if (e.key === "Escape") { if (moving && moving.started) { cancelMove(); return; } send("key", { key: "escape" }); return; }
    if (typing) return;
    var mod = e.metaKey || e.ctrlKey;
    if (e.key === "Delete" || e.key === "Backspace") { swallow(e); send("key", { key: "delete" }); }
    else if (mod && e.key.toLowerCase() === "z") { swallow(e); send("key", { key: e.shiftKey ? "redo" : "undo" }); }
    else if (mod && e.key.toLowerCase() === "d") { swallow(e); send("key", { key: "duplicate" }); }
    else if (mod && e.key.toLowerCase() === "a") { swallow(e); send("key", { key: "select-all" }); }
    else if (e.key === "ArrowUp" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowRight") { swallow(e); send("key", { key: e.key.toLowerCase(), shift: e.shiftKey, alt: e.altKey }); }
    else if (e.key === "Enter") { swallow(e); send("key", { key: "enter" }); }
  }, true);

  // --- moving a selected element --------------------------------------------
  // Click selects; a drag that starts on something selected moves it. The
  // frame only reports what is under the pointer (never the moving element
  // or anything inside it) and where it was let go; the editor decides.
  // Pointer events, not mouse events: design mode prevents the default of
  // every pointerdown (so the app runs nothing), and a prevented pointerdown
  // suppresses the mouse events that would have followed it.
  var moving = null;   // { fid, x, y, started, rect, dx, dy }
  var moved = false;   // the click after a move is swallowed
  function isUnder(fid, ancestor) { return fid === ancestor || fid.indexOf(ancestor + ".") === 0; }
  /** The fid under a DOM node that is not the moving element or inside it. */
  function ownerFidOutside(node, movingFid) {
    if (!node || isOurs(node)) return null;
    var el = node.nodeType === 1 ? node : node.parentElement;
    var start = el;
    while (start && !fiberOf(start)) start = start.parentElement;
    for (var f = fiberOf(start); f; f = f.return) {
      var fid = fidOfFiber(f);
      if (fid && !isUnder(fid, movingFid)) return fid;
    }
    for (var d = el && el.closest ? el.closest("[data-fid]") : null; d; d = d.parentElement && d.parentElement.closest("[data-fid]")) {
      var id = d.getAttribute("data-fid");
      if (id && !isUnder(id, movingFid)) return id;
    }
    return null;
  }
  function moveTarget(e) {
    ghost.style.display = "none";   // so the element under the pointer is the page's, not ours
    var under = document.elementFromPoint(e.clientX, e.clientY);
    ghost.style.display = "block";
    var fid = ownerFidOutside(under, moving.fid);
    var r = fid && rectOfFid(fid);
    if (!r) return { fid: null, y: 1 };
    return { fid: fid, y: r.height ? Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) : 1 };
  }
  function endMove() {
    moving = null;
    ghost.style.display = "none";
    hideDrop();
    document.documentElement.style.cursor = "";
  }
  var resizing = null;  // { fid, field, x, rect, parentWidth }
  document.addEventListener("pointerdown", function (e) {
    if (mode !== "design" || e.button !== 0 || !e.isPrimary) return;
    if (e.target === edge || e.target === edgeGrip) {
      // The right edge of the selection: drag it to a new width.
      swallow(e);
      var sfid = selected[0];
      var sel = selectedField ? fieldEl(sfid, selectedField) : byFid(sfid);
      var sr = selectedField ? (sel ? rectOf(sel) : null) : rectOfFid(sfid);
      if (!sel || !sr) return;
      var parent = selectedField ? sel.parentElement : sel.parentElement;
      var pw = parent ? parent.getBoundingClientRect().width : sr.width;
      resizing = { fid: sfid, field: selectedField, x: e.clientX, rect: sr, parentWidth: pw, width: sr.width };
      document.documentElement.style.cursor = "ew-resize";
      place(resizeBox, sr);
      return;
    }
    if (isOurs(e.target)) return;
    var fid = ownerFid(e.target);
    if (!fid || selected.indexOf(fid) < 0) return;
    var fld = fieldOf(e.target);
    if (fld && fld.fid === fid && selectedField === fld.name) {
      // The chosen field: drag it to another place in its form.
      var fr = rectOf(fld.el);
      moving = { fid: fid, field: fld.name, x: e.clientX, y: e.clientY, started: false, rect: fr, dx: e.clientX - fr.left, dy: e.clientY - fr.top };
      return;
    }
    if (fld && fld.fid === fid) return;   // a field not yet chosen: the click will choose it
    var r = rectOfFid(fid);
    if (!r) return;
    moving = { fid: fid, x: e.clientX, y: e.clientY, started: false, rect: r, dx: e.clientX - r.left, dy: e.clientY - r.top };
  }, true);
  document.addEventListener("pointermove", function (e) {
    if (!resizing || !e.isPrimary) return;
    var w = Math.max(24, Math.min(resizing.parentWidth, resizing.rect.width + (e.clientX - resizing.x)));
    resizing.width = w;
    place(resizeBox, { top: resizing.rect.top, left: resizing.rect.left, width: w, height: resizing.rect.height });
    place(edge, { top: resizing.rect.top, left: resizing.rect.left + w, width: 8, height: resizing.rect.height });
  }, true);
  document.addEventListener("pointerup", function (e) {
    if (!resizing) return;
    swallow(e);
    var r = resizing;
    resizing = null;
    resizeBox.style.display = "none";
    document.documentElement.style.cursor = "";
    moved = true;
    if (Math.abs(r.width - r.rect.width) >= 4) send("resize", { fid: r.fid, field: r.field, width: r.width, parentWidth: r.parentWidth });
    else reportRects();
  }, true);
  document.addEventListener("pointermove", function (e) {
    if (!moving || !e.isPrimary) return;
    if (!moving.started) {
      if (Math.abs(e.clientX - moving.x) < 5 && Math.abs(e.clientY - moving.y) < 5) return;
      moving.started = true;
      document.documentElement.style.cursor = "grabbing";
      hoverBox.style.display = "none";
    }
    place(ghost, { top: e.clientY - moving.dy, left: e.clientX - moving.dx, width: moving.rect.width, height: moving.rect.height });
    if (moving.field) {
      ghost.style.display = "none";
      var underF = document.elementFromPoint(e.clientX, e.clientY);
      ghost.style.display = "block";
      var over = fieldOf(underF);
      hideDrop();
      if (over && over.fid === moving.fid && over.name !== moving.field) {
        var orr = rectOf(over.el);
        var above = e.clientY < orr.top + orr.height / 2;
        place(dropBar, { top: (above ? orr.top : orr.top + orr.height) - 1.5, left: orr.left, width: orr.width, height: 3 });
        moving.over = { name: over.name, y: above ? 0 : 1 };
      } else moving.over = null;
      return;
    }
    var t = moveTarget(e);
    var band = t.y < 0.3 ? 0 : t.y > 0.7 ? 2 : 1;
    if (!dragAt || dragAt.fid !== t.fid || dragAt.band !== band) {
      dragAt = { fid: t.fid, band: band };
      send("drag-over", { fid: t.fid, y: t.y, moving: moving.fid });
    }
  }, true);
  document.addEventListener("pointerup", function (e) {
    if (!moving) return;
    if (!moving.started) { moving = null; return; }
    swallow(e);
    if (moving.field) {
      var mf = moving;
      moved = true;
      endMove();
      if (mf.over) send("field-drop", { fid: mf.fid, name: mf.field, over: mf.over.name, y: mf.over.y });
      return;
    }
    var t = moveTarget(e);
    var fid = moving.fid;
    moved = true;
    dragAt = null;
    endMove();
    send("move-drop", { fid: t.fid, y: t.y, moving: fid });
  }, true);
  function cancelMove() {
    if (resizing) { resizing = null; resizeBox.style.display = "none"; document.documentElement.style.cursor = ""; reportRects(); }
    if (!moving) return;
    var started = moving.started;
    endMove();
    if (started) send("move-cancel", {});
  }
  document.addEventListener("pointercancel", cancelMove, true);

  // --- region selection ----------------------------------------------------
  var drag = null;
  document.addEventListener("mousedown", function (e) {
    if (mode !== "region") return;
    swallow(e);
    drag = { x: e.clientX, y: e.clientY };
    place(regionBox, { top: e.clientY, left: e.clientX, width: 0, height: 0 });
  }, true);
  document.addEventListener("mousemove", function (e) {
    if (mode !== "region" || !drag) return;
    place(regionBox, { top: Math.min(drag.y, e.clientY), left: Math.min(drag.x, e.clientX),
                       width: Math.abs(e.clientX - drag.x), height: Math.abs(e.clientY - drag.y) });
  }, true);
  document.addEventListener("mouseup", function (e) {
    if (mode !== "region" || !drag) return;
    swallow(e);
    var r = { top: Math.min(drag.y, e.clientY), left: Math.min(drag.x, e.clientX),
              right: Math.max(drag.x, e.clientX), bottom: Math.max(drag.y, e.clientY) };
    drag = null;
    regionBox.style.display = "none";
    // Fully enclosed elements, reduced to the topmost of them (CANVAS-003).
    // Components count too (a chart has no `data-fid` of its own in the DOM):
    // every fid the page rendered, by the outline it draws. Fids are paths,
    // so "inside another enclosed one" is a prefix.
    fiberForFid("");
    var fids = Object.keys(fidIndex || {});
    var dom = document.querySelectorAll("[data-fid]");
    for (var j = 0; j < dom.length; j++) if (fids.indexOf(dom[j].getAttribute("data-fid")) < 0) fids.push(dom[j].getAttribute("data-fid"));
    var inside = fids.filter(function (fid) {
      var b = rectOfFid(fid);
      return b && b.left >= r.left && b.left + b.width <= r.right && b.top >= r.top && b.top + b.height <= r.bottom;
    });
    var top = inside.filter(function (fid) {
      return !inside.some(function (other) { return other !== fid && fid.indexOf(other + ".") === 0; });
    });
    send("region", { fids: top,
                     rect: { top: r.top, left: r.left, width: r.right - r.left, height: r.bottom - r.top } });
  }, true);

  // --- dropping a palette item onto the page ---------------------------------
  // The drag starts in the editor; the frame only says what is under the
  // pointer and how far down it (0 top .. 1 bottom), and where it was let go.
  var dragAt = null;
  function hideDrop() { dropBox.style.display = "none"; dropBar.style.display = "none"; }
  function dropTarget(e) {
    var fid = ownerFid(e.target);
    if (!fid) { var first = document.querySelector("[data-fid]"); fid = first ? first.getAttribute("data-fid") : null; }
    var r = fid && rectOfFid(fid);
    if (!r) return { fid: null, y: 1 };
    return { fid: fid, y: r.height ? Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) : 1 };
  }
  document.addEventListener("dragover", function (e) {
    if (mode !== "design") return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    var t = dropTarget(e);
    var band = t.y < 0.3 ? 0 : t.y > 0.7 ? 2 : 1;
    if (!dragAt || dragAt.fid !== t.fid || dragAt.band !== band) {
      dragAt = { fid: t.fid, band: band };
      send("drag-over", t);
    }
  }, true);
  document.addEventListener("dragleave", function (e) {
    if (!e.relatedTarget) { dragAt = null; hideDrop(); }
  }, true);
  document.addEventListener("drop", function (e) {
    if (mode !== "design") return;
    swallow(e);
    var t = dropTarget(e);
    var comp = "";
    try { comp = (e.dataTransfer && e.dataTransfer.getData("application/x-forge-component")) || ""; } catch (err) { /* not readable here */ }
    dragAt = null;
    hideDrop();
    send("drop", { fid: t.fid, y: t.y, component: comp });
  }, true);

  // --- where the app is ----------------------------------------------------
  function reportLocation() { send("navigate", { path: window.location.pathname + window.location.search }); }
  ["pushState", "replaceState"].forEach(function (name) {
    var orig = history[name];
    history[name] = function () { var out = orig.apply(this, arguments); setTimeout(reportLocation, 0); return out; };
  });
  window.addEventListener("popstate", reportLocation);

  // --- commands ------------------------------------------------------------
  window.addEventListener("message", function (e) {
    if (e.origin !== window.location.origin) return;
    var d = e.data;
    if (!d || typeof d.type !== "string" || d.type.indexOf(PREFIX) !== 0) return;
    var cmd = d.type.slice(PREFIX.length);
    var p = d.payload || {};
    switch (cmd) {
      case "set-mode":
        mode = p.mode === "preview" || p.mode === "region" ? p.mode : "design";
        cancelMove();
        hoverBox.style.display = "none";
        document.documentElement.style.cursor = mode === "region" ? "crosshair" : "";
        reportRects();
        break;
      case "select":
        selected = p.fids || [];
        labels = p.labels || {};
        selectedField = p.field || null;
        reportRects();
        break;
      case "hover": {
        var hr2 = rectOfFid(p.fid);
        if (hr2) place(hoverBox, hr2); else hoverBox.style.display = "none";
        break;
      }
      case "scroll-to": {
        var t = byFid(p.fid);
        if (t) t.scrollIntoView({ behavior: "smooth", block: "center" });
        break;
      }
      case "drop-hint": {
        hideDrop();
        var dr = rectOfFid(p.fid);
        if (!dr || !p.where) break;
        if (p.where === "inside") place(dropBox, dr);
        else place(dropBar, { top: (p.where === "before" ? dr.top : dr.top + dr.height) - 1.5, left: dr.left, width: dr.width, height: 3 });
        break;
      }
      case "get-rects": reportRects(); break;
      case "navigate": window.location.assign(p.path); break;
      case "reload": window.location.reload(); break;
    }
  });

  // --- keep outlines honest ------------------------------------------------
  var mo = new MutationObserver(function () { fidIndex = null; reportRects(); });
  mo.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
  window.addEventListener("scroll", reportRects, true);
  window.addEventListener("resize", reportRects);
  window.addEventListener("error", function (e) {
    send("error", { message: String(e.message || e.error || "Something on this page could not load"), file: e.filename || "", line: e.lineno || 0 });
  });

  send("ready", { path: window.location.pathname + window.location.search, width: window.innerWidth });
})();
