import { chromium } from "playwright";
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout: 120000 });
await p.waitForTimeout(5000);
console.log(JSON.stringify(await p.evaluate(() => {
  const out = [];
  for (const a of document.querySelectorAll('a')) {
    const r = a.getBoundingClientRect();
    const cs = getComputedStyle(a);
    const cx = r.left + r.width/2, cy = r.top + r.height/2;
    const hit = document.elementFromPoint(cx, cy);
    out.push({
      text: a.innerText.slice(0,20), href: a.getAttribute('href'),
      rect: [Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],
      pe: cs.pointerEvents, vis: cs.visibility, disp: cs.display, op: cs.opacity,
      hit: hit ? hit.tagName + '.' + (hit.className||'').toString().slice(0,40) + '|' + (hit.textContent||'').slice(0,20) : null,
      isSelf: hit === a || a.contains(hit),
    });
  }
  return out;
}), null, 1));
await b.close();
