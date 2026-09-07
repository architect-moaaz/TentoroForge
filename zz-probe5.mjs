import { chromium } from "playwright";
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
const errs=[]; p.on("pageerror", e=>errs.push(String(e).slice(0,200)));
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout: 180000 });
await p.waitForTimeout(6000);
await p.evaluate(() => { const a=[...document.querySelectorAll('a')].find(x=>x.innerText.includes('Learn more')); a.click(); });
for (let i=0;i<12;i++){ await p.waitForTimeout(2500); console.log(i, p.url()); if(!p.url().includes('nav-lab-6')) break; }
console.log("text:", (await p.evaluate(()=> (document.body.innerText||'').replace(/\s+/g,' ').slice(0,150))));
console.log("errs:", errs.slice(0,5));
await b.close();
