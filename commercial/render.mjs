// Render the commercial to PNG frames (or a few stills) with the pre-installed Playwright.
//   node render.mjs stills 3,9,17,20.5,26,33,39,44,46,50,53.5,57.5   -> out/still-*.png
//   node render.mjs frames 30                                         -> out/frames/%05d.png
import { createRequire } from "module";
import path from "path";
import fs from "fs";
import http from "http";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = path.dirname(new URL(import.meta.url).pathname);
const [mode = "stills", arg = ""] = process.argv.slice(2);

const types = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".mp3": "audio/mpeg" };
const server = http.createServer((req, res) => {
  const f = path.join(here, decodeURIComponent(req.url.split("?")[0]).replace(/^\/$/, "/index.html"));
  if (!f.startsWith(here) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": types[path.extname(f)] || "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
}).listen(0);
const port = server.address().port;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on("pageerror", e => console.error("PAGE ERROR", e.message));
await page.goto(`http://127.0.0.1:${port}/index.html?render=1`);
await page.evaluate(() => window.__ready);
await page.waitForTimeout(500);
const canvas = page.locator("canvas");
fs.mkdirSync(path.join(here, "out", "frames"), { recursive: true });
if (mode === "stills") {
  for (const t of arg.split(",").map(Number)) {
    await page.evaluate(t => window.__render(t), t);
    await canvas.screenshot({ path: path.join(here, "out", `still-${String(t).padStart(5, "0")}.png`) });
  }
} else {
  const fps = Number(arg) || 30, n = 60 * fps;
  for (let i = 0; i < n; i++) {
    const png = await page.evaluate(t => { window.__render(t); return document.getElementById("c").toDataURL("image/png"); }, i / fps);
    fs.writeFileSync(path.join(here, "out", "frames", String(i).padStart(5, "0") + ".png"), Buffer.from(png.split(",")[1], "base64"));
    if (i % 150 === 0) console.log("frame", i, "/", n);
  }
}
await browser.close(); server.close();
