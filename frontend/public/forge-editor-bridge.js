/**
 * Forge editor bridge — injected by the editor into its own same-origin
 * preview iframe (never shipped with the app).
 *
 * What it does: turns clicks into selections of the element's source node
 * (`data-fid`, which the editor stamps on the running copy of each page),
 * draws hover/selection outlines, supports a region drag that resolves to
 * node ids, takes a palette item dropped onto the page (the editor decides
 * where it lands and inserts it), reports where the app navigates to, and
 * steps out of the way entirely in Preview mode.
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
  var selectBoxes = [];
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
  function fidEl(el) {
    if (!el || !el.closest) return null;
    var f = el.closest("[data-fid]");
    return f && !isOurs(f) ? f : null;
  }
  function byFid(fid) {
    if (!fid) return null;
    var els = document.querySelectorAll('[data-fid="' + fid.replace(/"/g, '\\"') + '"]');
    return els.length ? els[0] : null;
  }
  function rectOf(el) {
    var r = el.getBoundingClientRect();
    return { top: r.top, left: r.left, width: r.width, height: r.height };
  }
  function send(type, payload) {
    try { window.parent.postMessage({ type: PREFIX + type, payload: payload || {} }, window.location.origin); } catch (e) { /* not cloneable */ }
  }

  function drawSelection() {
    while (selectBoxes.length) layer.removeChild(selectBoxes.pop());
    if (mode === "preview") return;
    var rects = {};
    for (var i = 0; i < selected.length; i++) {
      var el = byFid(selected[i]);
      if (!el) continue;
      var r = rectOf(el);
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
    if (mode !== "design") return;
    var el = fidEl(e.target);
    if (el !== hovered) {
      hovered = el;
      if (el) { place(hoverBox, rectOf(el)); send("hover", { fid: el.getAttribute("data-fid"), rect: rectOf(el) }); }
      else { hoverBox.style.display = "none"; send("hover", { fid: null }); }
    }
  }, true);
  document.addEventListener("mouseleave", function () { hoverBox.style.display = "none"; }, true);

  function swallow(e) { e.preventDefault(); e.stopPropagation(); }
  document.addEventListener("click", function (e) {
    if (mode === "preview") return;
    swallow(e);
    if (mode !== "design") return;
    var el = fidEl(e.target);
    send("select", { fid: el ? el.getAttribute("data-fid") : null, rect: el ? rectOf(el) : null,
                     shift: e.shiftKey, meta: e.metaKey || e.ctrlKey });
  }, true);
  document.addEventListener("dblclick", function (e) {
    if (mode !== "design") return;
    swallow(e);
    var el = fidEl(e.target);
    if (el) send("edit-text", { fid: el.getAttribute("data-fid"), rect: rectOf(el) });
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
    if (e.key === "Escape") { send("key", { key: "escape" }); return; }
    if (typing) return;
    var mod = e.metaKey || e.ctrlKey;
    if (e.key === "Delete" || e.key === "Backspace") { swallow(e); send("key", { key: "delete" }); }
    else if (mod && e.key.toLowerCase() === "z") { swallow(e); send("key", { key: e.shiftKey ? "redo" : "undo" }); }
    else if (mod && e.key.toLowerCase() === "d") { swallow(e); send("key", { key: "duplicate" }); }
    else if (mod && e.key.toLowerCase() === "a") { swallow(e); send("key", { key: "select-all" }); }
    else if (e.key === "ArrowUp" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowRight") { swallow(e); send("key", { key: e.key.toLowerCase(), shift: e.shiftKey, alt: e.altKey }); }
    else if (e.key === "Enter") { swallow(e); send("key", { key: "enter" }); }
  }, true);

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
    var all = document.querySelectorAll("[data-fid]");
    var inside = [];
    for (var i = 0; i < all.length; i++) {
      var b = all[i].getBoundingClientRect();
      if (b.width === 0 && b.height === 0) continue;
      if (b.left >= r.left && b.right <= r.right && b.top >= r.top && b.bottom <= r.bottom) inside.push(all[i]);
    }
    var top = inside.filter(function (el) {
      return !inside.some(function (other) { return other !== el && other.contains(el); });
    });
    send("region", { fids: top.map(function (el) { return el.getAttribute("data-fid"); }),
                     rect: { top: r.top, left: r.left, width: r.right - r.left, height: r.bottom - r.top } });
  }, true);

  // --- dropping a palette item onto the page ---------------------------------
  // The drag starts in the editor; the frame only says what is under the
  // pointer and how far down it (0 top .. 1 bottom), and where it was let go.
  var dragAt = null;
  function hideDrop() { dropBox.style.display = "none"; dropBar.style.display = "none"; }
  function dropTarget(e) {
    var el = fidEl(e.target) || document.querySelector("[data-fid]");
    if (!el) return { fid: null, y: 1 };
    var r = el.getBoundingClientRect();
    return { fid: el.getAttribute("data-fid"), y: r.height ? Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) : 1 };
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
        hoverBox.style.display = "none";
        document.documentElement.style.cursor = mode === "region" ? "crosshair" : "";
        reportRects();
        break;
      case "select":
        selected = p.fids || [];
        labels = p.labels || {};
        reportRects();
        break;
      case "hover": {
        var el = byFid(p.fid);
        if (el) place(hoverBox, rectOf(el)); else hoverBox.style.display = "none";
        break;
      }
      case "scroll-to": {
        var t = byFid(p.fid);
        if (t) t.scrollIntoView({ behavior: "smooth", block: "center" });
        break;
      }
      case "drop-hint": {
        hideDrop();
        var d = byFid(p.fid);
        if (!d || !p.where) break;
        var dr = rectOf(d);
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
  var mo = new MutationObserver(function () { reportRects(); });
  mo.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
  window.addEventListener("scroll", reportRects, true);
  window.addEventListener("resize", reportRects);
  window.addEventListener("error", function (e) {
    send("error", { message: String(e.message || e.error || "Something on this page could not load"), file: e.filename || "", line: e.lineno || 0 });
  });

  send("ready", { path: window.location.pathname + window.location.search, width: window.innerWidth });
})();
