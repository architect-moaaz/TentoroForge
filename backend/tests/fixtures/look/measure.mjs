// Run page_shots.mjs's MEASURE and OPENED on one static page: node measure.mjs <page_shots.mjs> <file.html>
// Prints {measured, opened}. The two functions are taken from the script as written, not copied.
import { chromium } from "playwright";
import fs from "node:fs";

const src = fs.readFileSync(process.argv[2], "utf8");
const grab = (name) => {
  const at = src.indexOf(`const ${name} = () => {`);
  const end = src.indexOf("\n};\n", at);
  return src.slice(at + `const ${name} = `.length, end + 2);
};
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
await page.goto("file://" + process.argv[3]);
const measured = await page.evaluate(`(${grab("MEASURE")})()`);
await page.evaluate(() => {
  for (const el of document.querySelectorAll("body *")) {
    const r = el.getBoundingClientRect();
    if (r.width >= 2 && r.height >= 2) el.setAttribute("data-forge-seen", "");
  }
});
await page.locator(measured.openers[0].path).click();
await page.waitForTimeout(200);
const opened = await page.evaluate(`(${grab("OPENED")})()`);
console.log(JSON.stringify({ measured, opened }));
await browser.close();
