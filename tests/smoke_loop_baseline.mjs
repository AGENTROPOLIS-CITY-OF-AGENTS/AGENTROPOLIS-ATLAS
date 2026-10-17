/**
 * Headless smoke against the staged Pages publish tree.
 * Serves build/publish on 127.0.0.1 and fails if the page requests any
 * non-local URL, logs a console error, or does not execute the local script.
 */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publishRoot = path.join(repoRoot, "build", "publish");
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
};

function startServer(root) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      if (url.pathname === "/favicon.ico") {
        res.writeHead(204).end();
        return;
      }
      let rel = decodeURIComponent(url.pathname);
      if (rel.endsWith("/")) rel += "index.html";
      const file = path.resolve(root, `.${rel}`);
      if (file !== root && !file.startsWith(root + path.sep)) {
        res.writeHead(403).end("forbidden");
        return;
      }
      const data = await readFile(file);
      const info = await stat(file);
      if (!info.isFile()) {
        res.writeHead(404).end("not found");
        return;
      }
      res.writeHead(200, {
        "content-type": TYPES[path.extname(file)] ?? "application/octet-stream",
        "cache-control": "no-store",
      });
      res.end(data);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const candidates = [
    "/usr/local/bin/google-chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ];
  for (const candidate of candidates) {
    try {
      await stat(candidate);
      return candidate;
    } catch {
      // try the next candidate
    }
  }
  throw new Error("CHROME_PATH is unset and no system Chrome/Chromium binary was found");
}

function fail(message) {
  console.error(`FAIL ${message}`);
  process.exitCode = 1;
}

const publishStat = await stat(publishRoot).catch(() => null);
if (!publishStat?.isDirectory()) {
  fail(`missing publish tree at ${publishRoot}; run tests/vendor_baseline_regression.py first`);
  process.exit(1);
}

const server = await startServer(publishRoot);
const { port } = server.address();
const origin = `http://127.0.0.1:${port}`;
const requests = [];
const blocked = [];
const consoleErrors = [];
const pageErrors = [];

const browser = await chromium.launch({
  executablePath: await findChrome(),
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});

try {
  const page = await browser.newPage();
  await page.route("**/*", (route) => {
    const url = route.request().url();
    let host = "";
    try {
      host = new URL(url).hostname;
    } catch {
      blocked.push(url);
      return route.abort();
    }
    if (host !== "127.0.0.1" && host !== "localhost") {
      blocked.push(url);
      return route.abort();
    }
    return route.continue();
  });
  page.on("request", (request) => requests.push(request.url()));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  const response = await page.goto(`${origin}/`, { waitUntil: "load", timeout: 15000 });
  const status = response?.status() ?? 0;
  const state = await page.evaluate(() => ({
    loaded: window.__AGENTROPOLIS_LOOP_BASELINE__ === true,
    version: window.__AGENTROPOLIS_LOOP_BASELINE_VERSION__ ?? null,
    host: Boolean(document.getElementById("agentropolis-loop-baseline")),
  }));

  const localScript = requests.filter((url) => {
    const parsed = new URL(url);
    return parsed.pathname === "/agentropolis-loop-baseline.js";
  });
  const remoteHits = [...requests, ...blocked].filter((url) =>
    /github\.io|AGENTROPOLIS-DESIGN-SYSTEM|loop-baseline\.js/.test(url) &&
    !url.startsWith(origin),
  );

  console.log(`SMOKE_ORIGIN=${origin}`);
  console.log(`PAGE_STATUS=${status}`);
  console.log(`LOCAL_SCRIPT_REQUESTS=${localScript.length}`);
  console.log(`BASELINE_LOADED=${state.loaded}`);
  console.log(`BASELINE_VERSION=${state.version}`);
  console.log(`BASELINE_HOST=${state.host}`);
  console.log(`BLOCKED_REQUESTS=${blocked.length}`);
  console.log(`CONSOLE_ERRORS=${consoleErrors.length}`);
  console.log(`PAGE_ERRORS=${pageErrors.length}`);
  for (const url of requests) console.log(`REQUEST ${url}`);
  for (const url of blocked) console.log(`BLOCKED ${url}`);
  for (const message of consoleErrors) console.log(`CONSOLE_ERROR ${message}`);
  for (const message of pageErrors) console.log(`PAGE_ERROR ${message}`);

  if (status !== 200) fail(`index status ${status}`);
  if (localScript.length !== 1) fail(`expected one local script request, saw ${localScript.length}`);
  if (!state.loaded || state.version !== "1.0.0" || !state.host) fail("local baseline did not execute");
  if (blocked.length || remoteHits.length) fail("page requested a remote URL");
  if (consoleErrors.length || pageErrors.length) fail("console or page error");
  if (process.exitCode) process.exit(process.exitCode);
  console.log("SMOKE=pass");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
