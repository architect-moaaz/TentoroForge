// A phone squeezes a screen's containers to the screen's height, so a list inside them scrolls; a browser lets a container
// grow to its content and the list never scrolls. This lets the containers that hold a scrollable list shrink, as they do on
// a phone. Only those: letting every box shrink squashes the text inside cards.
// Used only by the editor's phone preview.
(function () {
  var queued = false;

  // A phone has no permanent scrollbar: the list just moves under a finger. A browser's bar is not part of the app.
  var style = document.createElement("style");
  style.textContent = "*{scrollbar-width:none;-ms-overflow-style:none}*::-webkit-scrollbar{display:none}";
  document.head.appendChild(style);

  function scrolls(el) {
    var o = getComputedStyle(el).overflowY;
    return o === "auto" || o === "scroll";
  }

  function fit() {
    queued = false;
    var boxes = document.querySelectorAll("div");
    for (var i = 0; i < boxes.length; i++) {
      if (!scrolls(boxes[i])) continue;
      for (var p = boxes[i].parentElement; p && p !== document.body && p.id !== "root"; p = p.parentElement) {
        if (p.getAttribute("data-forge-fit")) break;
        p.setAttribute("data-forge-fit", "1");
        p.style.flexShrink = "1";
        p.style.minHeight = "0";
      }
    }
  }

  function later() {
    if (queued) return;
    queued = true;
    setTimeout(fit, 120);
  }

  new MutationObserver(later).observe(document.documentElement, { childList: true, subtree: true });
  later();
})();
