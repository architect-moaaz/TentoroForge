import { chromium } from "playwright";
const url = process.argv[2];
const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
const logs = [];
p.on("console", m => logs.push(m.type()+": "+m.text().slice(0,300)));
p.on("pageerror", e => logs.push("PAGEERROR: "+String(e).slice(0,400)));
const resp = await p.goto(url, { waitUntil: "load", timeout: 120000 });
console.log("status", resp?.status());
await p.waitForTimeout(6000);
const info = await p.evaluate(() => {
  const hidden = [...document.querySelectorAll('div[hidden]')].map(d => ({id:d.id, kids:d.childElementCount, text:(d.textContent||'').replace(/\s+/g,' ').slice(0,80)}));
  const main = document.querySelector('main');
  return {
    url: location.href,
    bodyTextLen: (document.body.innerText||'').length,
    bodyText: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,400),
    hidden,
    hasRC: typeof window.$RC,
    rcScripts: [...document.querySelectorAll('script')].filter(s=>/\$RC\(/.test(s.textContent||'')).length,
    mainAttrs: main ? [...main.attributes].map(a=>a.name+'='+a.value.slice(0,30)) : null,
    mainId: main?.id ?? null,
    anchors: document.querySelectorAll('a').length,
    reactRootChildren: document.querySelectorAll('body > *').length,
  };
});
console.log(JSON.stringify(info, null, 1));
console.log("LOGS:\n"+logs.slice(0,40).join("\n"));
await b.close();
