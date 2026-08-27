/**
 * Design2UI Bridge Script
 *
 * Injected into the generated Next.js app to enable visual editing.
 * Communicates with the parent frame via postMessage.
 *
 * Protocol: all messages use type prefix "design2ui:"
 */
(function () {
  "use strict";

  if (window.__design2ui_bridge) return;
  // Only activate inside the Tentoro Forge editor iframe — not when running standalone
  if (window.parent === window) return;
  window.__design2ui_bridge = true;

  var PREFIX = "design2ui:";
  var MAX_TREE_DEPTH = 12;
  var OVERLAY_Z = 2147483640;
  var IGNORED_TAGS = { SCRIPT: 1, STYLE: 1, LINK: 1, META: 1, NOSCRIPT: 1, SVG: 1 };

  // SVG elements have className as SVGAnimatedString — coerce to plain string
  function getClassName(el) {
    var cn = el.className;
    if (!cn) return "";
    if (typeof cn === "string") return cn;
    // SVGAnimatedString
    if (cn.baseVal !== undefined) return cn.baseVal;
    return "";
  }

  // --- Overlay elements ---
  var hoverOverlay = createOverlay("rgba(59, 130, 246, 0.3)", "2px solid rgba(59, 130, 246, 0.8)");
  var selectOverlay = createOverlay("rgba(239, 68, 68, 0.15)", "2px solid rgba(239, 68, 68, 0.9)");
  document.body.appendChild(hoverOverlay);
  document.body.appendChild(selectOverlay);

  var selectedElement = null;
  var hoveredElement = null;

  function createOverlay(bg, border) {
    var el = document.createElement("div");
    el.style.cssText =
      "position:fixed;pointer-events:none;z-index:" + OVERLAY_Z +
      ";background:" + bg + ";border:" + border +
      ";display:none;transition:all 0.05s ease-out;border-radius:2px;";
    el.setAttribute("data-bridge-overlay", "true");
    return el;
  }

  function positionOverlay(overlay, rect) {
    overlay.style.top = rect.top + "px";
    overlay.style.left = rect.left + "px";
    overlay.style.width = rect.width + "px";
    overlay.style.height = rect.height + "px";
    overlay.style.display = "block";
  }

  function hideOverlay(overlay) {
    overlay.style.display = "none";
  }

  function isBridgeElement(el) {
    return el && el.getAttribute && el.getAttribute("data-bridge-overlay") === "true";
  }

  // --- Element info extraction ---
  function getXPath(el) {
    if (!el || el === document.body) return "/body";
    var parts = [];
    var node = el;
    while (node && node !== document.body && node.nodeType === 1) {
      var tag = node.tagName.toLowerCase();
      var idx = 1;
      var sib = node.previousElementSibling;
      while (sib) {
        if (sib.tagName === node.tagName) idx++;
        sib = sib.previousElementSibling;
      }
      parts.unshift(tag + "[" + idx + "]");
      node = node.parentElement;
    }
    return "/body/" + parts.join("/");
  }

  function getElementInfo(el) {
    var rect = el.getBoundingClientRect();
    var source = null;
    var srcFile = el.getAttribute("data-source-file");
    if (srcFile) {
      source = {
        file: srcFile,
        line: parseInt(el.getAttribute("data-source-line") || "0", 10),
        component: el.getAttribute("data-source-component") || null,
      };
    }
    // Walk up to find nearest source annotation if this element doesn't have one
    if (!source) {
      var ancestor = el.parentElement;
      while (ancestor && ancestor !== document.body) {
        var sf = ancestor.getAttribute("data-source-file");
        if (sf) {
          source = {
            file: sf,
            line: parseInt(ancestor.getAttribute("data-source-line") || "0", 10),
            component: ancestor.getAttribute("data-source-component") || null,
          };
          break;
        }
        ancestor = ancestor.parentElement;
      }
    }
    return {
      tagName: el.tagName.toLowerCase(),
      className: getClassName(el),
      textContent: (el.textContent || "").trim().substring(0, 100),
      id: el.id || null,
      rect: {
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
      },
      source: source,
      xpath: getXPath(el),
    };
  }

  // --- DOM tree building ---
  function buildTree(el, depth) {
    if (!el || depth > MAX_TREE_DEPTH) return null;
    if (el.nodeType !== 1) return null;
    if (IGNORED_TAGS[el.tagName]) return null;
    if (isBridgeElement(el)) return null;

    var source = null;
    var srcFile = el.getAttribute("data-source-file");
    if (srcFile) {
      source = {
        file: srcFile,
        line: parseInt(el.getAttribute("data-source-line") || "0", 10),
        component: el.getAttribute("data-source-component") || null,
      };
    }

    var children = [];
    var child = el.firstElementChild;
    while (child) {
      var node = buildTree(child, depth + 1);
      if (node) children.push(node);
      child = child.nextElementSibling;
    }

    // Get direct text content (not from children)
    var textPreview = null;
    for (var i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3) {
        var t = el.childNodes[i].textContent.trim();
        if (t) {
          textPreview = t.substring(0, 60);
          break;
        }
      }
    }

    return {
      tagName: el.tagName.toLowerCase(),
      className: getClassName(el),
      id: el.id || null,
      source: source,
      childCount: el.children.length,
      textPreview: textPreview,
      children: children.length > 0 ? children : null,
      xpath: getXPath(el),
    };
  }

  function sendTree() {
    var body = document.body;
    if (!body) return;
    var tree = [];
    var child = body.firstElementChild;
    while (child) {
      var node = buildTree(child, 0);
      if (node) tree.push(node);
      child = child.nextElementSibling;
    }
    send("tree", { tree: tree });
  }

  // --- postMessage ---
  function send(type, payload) {
    if (window.parent && window.parent !== window) {
      try {
        window.parent.postMessage({ type: PREFIX + type, payload: payload }, "*");
      } catch (e) {
        // DataCloneError — payload contains non-cloneable objects, skip
      }
    }
  }

  // --- Element lookup by xpath ---
  function findByXPath(xpath) {
    try {
      var result = document.evaluate(
        xpath.replace(/^\/body/, "/html/body"),
        document,
        null,
        XPathResult.FIRST_ORDERED_NODE_TYPE,
        null
      );
      return result.singleNodeValue;
    } catch (e) {
      return null;
    }
  }

  // --- Event handlers ---
  document.addEventListener("mousemove", function (e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || isBridgeElement(el) || el === document.documentElement) return;

    if (el !== hoveredElement) {
      hoveredElement = el;
      var rect = el.getBoundingClientRect();
      positionOverlay(hoverOverlay, rect);
      send("hover", getElementInfo(el));
    }
  }, true);

  document.addEventListener("click", function (e) {
    var el = document.elementFromPoint(e.clientX, e.clientY);
    if (!el || isBridgeElement(el)) return;

    e.preventDefault();
    e.stopPropagation();

    selectedElement = el;
    var rect = el.getBoundingClientRect();
    positionOverlay(selectOverlay, rect);
    send("select", getElementInfo(el));
  }, true);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && selectedElement) {
      selectedElement = null;
      hideOverlay(selectOverlay);
      send("deselect", {});
    }
  });

  // Reposition overlays on scroll/resize
  function repositionOverlays() {
    if (hoveredElement && hoveredElement.isConnected) {
      positionOverlay(hoverOverlay, hoveredElement.getBoundingClientRect());
    }
    if (selectedElement && selectedElement.isConnected) {
      positionOverlay(selectOverlay, selectedElement.getBoundingClientRect());
    } else if (selectedElement) {
      selectedElement = null;
      hideOverlay(selectOverlay);
    }
  }

  window.addEventListener("scroll", repositionOverlays, true);
  window.addEventListener("resize", repositionOverlays);

  // --- Incoming commands from parent ---
  window.addEventListener("message", function (e) {
    if (!e.data || typeof e.data.type !== "string") return;
    if (!e.data.type.startsWith(PREFIX)) return;

    var cmd = e.data.type.slice(PREFIX.length);
    var payload = e.data.payload || {};

    switch (cmd) {
      case "get-tree":
        sendTree();
        break;
      case "scroll-to":
        var target = findByXPath(payload.xpath);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          selectedElement = target;
          positionOverlay(selectOverlay, target.getBoundingClientRect());
          send("select", getElementInfo(target));
        }
        break;
      case "highlight":
        var hlEl = findByXPath(payload.xpath);
        if (hlEl) {
          positionOverlay(hoverOverlay, hlEl.getBoundingClientRect());
        }
        break;
      case "ping":
        send("pong", {});
        break;

      case "edit-complete":
        // After a code edit, wait for HMR to apply DOM mutations, then re-scan.
        // Falls back if no mutation fires within 2s.
        var editXpath = payload.xpath || null;
        var editSettled = false;
        var editObserver = new MutationObserver(function () {
          if (editSettled) return;
          editSettled = true;
          editObserver.disconnect();
          // Wait 200ms for HMR to fully settle
          setTimeout(function () {
            sendTree();
            repositionOverlays();
            // Re-select element if it still exists
            if (editXpath) {
              var el = findByXPath(editXpath);
              if (el) {
                selectedElement = el;
                positionOverlay(selectOverlay, el.getBoundingClientRect());
                send("select", getElementInfo(el));
              }
            }
            send("edit-settled", { hmr: true });
          }, 200);
        });
        editObserver.observe(document.body, {
          childList: true,
          subtree: true,
          attributes: true,
          characterData: true,
        });
        // Fallback: if no mutation within 2s, notify anyway
        setTimeout(function () {
          if (!editSettled) {
            editSettled = true;
            editObserver.disconnect();
            sendTree();
            repositionOverlays();
            send("edit-settled", { hmr: false });
          }
        }, 2000);
        break;
    }
  });

  // --- MutationObserver for HMR ---
  var treeTimer = null;
  var observer = new MutationObserver(function () {
    // Debounce tree updates
    clearTimeout(treeTimer);
    treeTimer = setTimeout(function () {
      sendTree();
      repositionOverlays();
    }, 300);
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class", "className", "data-source-file"],
  });

  // --- Error Capture ---
  // Captures runtime errors and sends them to the parent frame for auto-fix.
  var lastErrorKey = "";
  var lastErrorTime = 0;

  function sendError(info) {
    // Debounce: skip duplicate errors within 2 seconds
    var key = info.file + ":" + info.line + ":" + info.message;
    var now = Date.now();
    if (key === lastErrorKey && now - lastErrorTime < 2000) return;
    lastErrorKey = key;
    lastErrorTime = now;
    send("runtime-error", info);
  }

  window.onerror = function (message, source, lineno, colno, error) {
    sendError({
      message: String(message),
      file: source || "",
      line: lineno || 0,
      column: colno || 0,
      stack: error && error.stack ? error.stack : "",
      type: "runtime",
    });
  };

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    var message = reason instanceof Error ? reason.message : String(reason);
    var stack = reason instanceof Error ? reason.stack || "" : "";
    sendError({
      message: message,
      file: "",
      line: 0,
      column: 0,
      stack: stack,
      type: "unhandled_rejection",
    });
  });

  // Intercept Next.js error overlay — extract error details from the overlay DOM
  var errorObserver = new MutationObserver(function (mutations) {
    for (var i = 0; i < mutations.length; i++) {
      var nodes = mutations[i].addedNodes;
      for (var j = 0; j < nodes.length; j++) {
        var node = nodes[j];
        if (node.nodeType !== 1) continue;
        // Next.js error overlay uses nextjs-portal or data-nextjs-dialog
        if (node.id === "__next" || node.tagName === "NEXTJS-PORTAL") {
          // Wait a tick for the overlay to populate
          setTimeout(function () {
            var overlay = document.querySelector("nextjs-portal");
            if (!overlay) return;
            var shadow = overlay.shadowRoot;
            if (!shadow) return;
            // Extract error text from the overlay
            var dialogBody = shadow.querySelector("[data-nextjs-dialog-body]");
            if (!dialogBody) return;
            var heading = shadow.querySelector("h1, h2, [data-nextjs-dialog-header]");
            var codeFrame = shadow.querySelector("pre, code, [data-nextjs-codeframe]");
            var fileInfo = shadow.querySelector("[data-nextjs-dialog-body] p");

            var message = heading ? heading.textContent.trim() : "Unknown error";
            var file = "";
            var line = 0;

            // Parse file:line from the overlay text
            if (fileInfo) {
              var fileMatch = fileInfo.textContent.match(/(src\/[^\s:(]+)\s*\((\d+)[:\d)]*\)/);
              if (fileMatch) {
                file = fileMatch[1];
                line = parseInt(fileMatch[2], 10);
              }
            }

            sendError({
              message: message,
              file: file,
              line: line,
              column: 0,
              stack: codeFrame ? codeFrame.textContent : "",
              type: "nextjs_overlay",
            });
          }, 200);
        }
      }
    }
  });

  errorObserver.observe(document.documentElement, {
    childList: true,
    subtree: true,
  });

  // --- Ready ---
  send("ready", {});
  sendTree();
})();
