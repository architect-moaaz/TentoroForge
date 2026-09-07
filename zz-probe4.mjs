import { chromium } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext();
const p = await ctx.newPage();
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout: 120000 });
await p.waitForTimeout(5000);
// stability probe
console.log("rect samples:", JSON.stringify(await p.evaluate(async () => {
  const a = [...document.querySelectorAll('a')].find(x=>x.innerText.includes('Learn more'));
  const s = [];
  for (let i=0;i<4;i++){ await new Promise(r=>requestAnimationFrame(r)); const r=a.getBoundingClientRect(); s.push([Math.round(r.x),Math.round(r.y),Math.round(r.width)]); }
  return s;
})));
const before = p.url();
await p.evaluate(() => { const a=[...document.querySelectorAll('a')].find(x=>x.innerText.includes('Learn more')); a.click(); });
await p.waitForTimeout(3000);
console.log("after JS .click():", p.url(), "(was", before + ")");
// dropdown
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout:120000 });
await p.waitForTimeout(4000);
await p.evaluate(() => { const btn=[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='Actions'); btn.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,button:0,ctrlKey:false})); btn.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,button:0})); btn.click(); });
await p.waitForTimeout(1500);
console.log("menus after click:", JSON.stringify(await p.evaluate(() => ({
  menus: [...document.querySelectorAll('[role=menu]')].map(m=>({kids:m.childElementCount, text:(m.innerText||'').slice(0,60), rect:[Math.round(m.getBoundingClientRect().width),Math.round(m.getBoundingClientRect().height)]})),
  expanded: [...document.querySelectorAll('button')].map(b=>b.getAttribute('aria-expanded')),
}))));
await b.close();
