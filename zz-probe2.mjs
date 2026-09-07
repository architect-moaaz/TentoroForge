import { chromium } from "playwright";
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
const logs = [];
p.on("console", m => { if(m.type()==="error"||m.type()==="warning") logs.push(m.type()+": "+m.text().slice(0,200)); });
p.on("pageerror", e => logs.push("PAGEERROR: "+String(e).slice(0,300)));
await p.goto("http://localhost:6503/p/gh0mlpbp/nav-lab-6", { waitUntil: "load", timeout: 120000 });
await p.waitForTimeout(5000);
console.log(JSON.stringify(await p.evaluate(() => ({
  text: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,500),
  anchors: [...document.querySelectorAll('a')].map(a=>({t:a.innerText.slice(0,25), href:a.getAttribute('href'), cls:(a.className||'').slice(0,40)})),
  buttons: [...document.querySelectorAll('button')].map(x=>({t:x.innerText.slice(0,25), hp:x.getAttribute('aria-haspopup'), st:x.getAttribute('data-state')})),
  ctx: !!document.querySelector('[data-context-menu]'),
  cartBadge: !!document.querySelector('[data-cart-badge]'),
  menubar: !!document.querySelector('[data-menubar]'),
})), null, 1));
// click the Link
const link = await p.$('a:has-text("Learn more")');
if (link) {
  const before = p.url();
  await link.click({ timeout: 5000 }).catch(e=>console.log("click err", e.message.slice(0,100)));
  await p.waitForTimeout(3000);
  console.log("LINK CLICK: before", before, "after", p.url());
}
console.log("LOGS:\n"+logs.slice(0,20).join("\n"));
await b.close();
