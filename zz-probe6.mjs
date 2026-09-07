import { chromium } from "playwright";
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout: 180000 });
await p.waitForTimeout(6000);
console.log(JSON.stringify(await p.evaluate(() => {
  const cb = document.querySelector('[data-cart-badge]');
  const main = document.querySelector('main');
  return {
    text: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,300),
    cartBadge: cb ? {rect:[Math.round(cb.getBoundingClientRect().width),Math.round(cb.getBoundingClientRect().height)], text: cb.innerText, href: cb.getAttribute('href'), known: cb.getAttribute('data-cart-count-known')} : null,
    mainId: main?.id, mainHasId: !!main?.id,
    navlinks: [...document.querySelectorAll('a')].map(a=>({t:a.innerText.slice(0,20), href:a.getAttribute('href'), cur:a.getAttribute('aria-current'), unset:a.hasAttribute('data-navlink-unset')||a.hasAttribute('data-link-unset')})),
  };
}), null, 1));
// activate skip link
await p.evaluate(()=>{ const s=document.querySelector('[data-forge-skip-link]'); s.click(); });
await p.waitForTimeout(500);
console.log("after skiplink:", JSON.stringify(await p.evaluate(()=>({ mainId: document.querySelector('main')?.id, active: document.activeElement?.tagName, tabindex: document.querySelector('main')?.getAttribute('tabindex') }))));
await b.close();
