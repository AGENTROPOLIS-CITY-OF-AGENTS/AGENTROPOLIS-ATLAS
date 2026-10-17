/**
 * Headless smoke of the allowlisted Pages tree.
 * Serves _site at /AGENTROPOLIS-ATLAS/ and fails unless the vendored baseline
 * executes, every page asset is 200, no design-system host is requested, a
 * former repo-root path such as /tests/ is absent, and a tampered baseline
 * file is blocked by SRI.
 */
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { cp, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publishRoot = path.join(repoRoot, "_site");
const BASE = "/AGENTROPOLIS-ATLAS";
const EXPECTED_INTEGRITY = "sha384-YXPNohgGheUM32mm6qMBBKuRXhwU5Wkrwu9dgTmQBJRRIY0TdgcgxoEtvhxgTaqY";
const REQUIRED = [
  `${BASE}/`,
  `${BASE}/styles.css`,
  `${BASE}/script.js`,
  `${BASE}/agentropolis-loop-baseline.js`,
];
const FORBIDDEN = ["tests/", "services/", "docs/", "policies/", "skills/", ".agentropolis/"];
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
      if (url.pathname === "/favicon.ico" || url.pathname === `${BASE}/favicon.ico`) {
        res.writeHead(204).end();
        return;
      }
      if (url.pathname === BASE) {
        res.writeHead(308, { location: `${BASE}/` }).end();
        return;
      }
      if (!url.pathname.startsWith(`${BASE}/`)) {
        res.writeHead(404).end("not found");
        return;
      }
      let rel = decodeURIComponent(url.pathname.slice(BASE.length + 1));
      if (rel.split("/").includes("..")) {
        res.writeHead(400).end("bad path");
        return;
      }
      if (rel === "" || rel.endsWith("/")) rel += "index.html";
      const file = path.resolve(root, rel);
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

async function listFiles(dir) {
  const out = [];
  async function walk(current) {
    for (const entry of await readdir(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile()) out.push(path.relative(dir, full).split(path.sep).join("/"));
    }
  }
  await walk(dir);
  return out.sort();
}

function sha384(bytes) {
  return createHash("sha384").update(bytes).digest("base64");
}

function pathname(url) {
  return new URL(url).pathname;
}

async function exercise(browser, root) {
  const server = await startServer(root);
  const { port } = server.address();
  const origin = `http://127.0.0.1:${port}`;
  const requests = [];
  const responses = [];
  const consoleMessages = [];
  const pageErrors = [];
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("request", (request) => {
    requests.push({ url: request.url(), resourceType: request.resourceType() });
  });
  page.on("response", (response) => {
    responses.push({ url: response.url(), status: response.status() });
  });
  page.on("console", (message) => {
    consoleMessages.push({ type: message.type(), text: message.text() });
  });
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  try {
    const response = await page.goto(`${origin}${BASE}/`, { waitUntil: "load", timeout: 15000 });
    const state = await page.evaluate(() => ({
      href: location.href,
      loaded: window.__AGENTROPOLIS_LOOP_BASELINE__ === true,
      version: window.__AGENTROPOLIS_LOOP_BASELINE_VERSION__ ?? null,
      host: Boolean(document.getElementById("agentropolis-loop-baseline")),
      tamper: window.__AGENTROPOLIS_LOOP_BASELINE_TAMPER__ === true,
      scripts: [...document.scripts].map((script) => ({
        src: script.getAttribute("src"),
        integrity: script.getAttribute("integrity"),
        crossorigin: script.getAttribute("crossorigin"),
      })),
    }));
    return {
      origin,
      status: response?.status() ?? 0,
      state,
      requests,
      responses,
      consoleMessages,
      pageErrors,
    };
  } finally {
    await context.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

function printCase(label, result) {
  console.log(`CASE=${label}`);
  console.log(`SMOKE_ORIGIN=${result.origin}`);
  console.log(`PAGE_STATUS=${result.status}`);
  console.log(`PAGE_HREF=${result.state.href}`);
  console.log(`BASELINE_LOADED=${result.state.loaded}`);
  console.log(`BASELINE_VERSION=${result.state.version}`);
  console.log(`BASELINE_HOST=${result.state.host}`);
  console.log(`TAMPER_FLAG=${result.state.tamper}`);
  for (const script of result.state.scripts) {
    console.log(
      `SCRIPT src=${script.src} integrity=${script.integrity ?? ""} crossorigin=${script.crossorigin ?? ""}`,
    );
  }
  for (const request of result.requests) {
    console.log(`REQUEST ${request.resourceType} ${request.url}`);
  }
  for (const response of result.responses) {
    console.log(`RESPONSE ${response.status} ${response.url}`);
  }
  for (const message of result.consoleMessages) {
    console.log(`CONSOLE ${message.type} ${message.text}`);
  }
  for (const message of result.pageErrors) console.log(`PAGE_ERROR ${message}`);
}

const publishStat = await stat(publishRoot).catch(() => null);
if (!publishStat?.isDirectory()) {
  fail(`missing publish tree at ${publishRoot}; run tests/vendor_baseline_regression.py first`);
  process.exit(1);
}

const siteFiles = await listFiles(publishRoot);
console.log(`SITE_FILES=${siteFiles.join(",")}`);
for (const forbidden of FORBIDDEN) {
  const prefix = forbidden.replace(/\/$/, "");
  const present = siteFiles.some((file) => file === prefix || file.startsWith(`${prefix}/`));
  console.log(`SITE_HAS_${prefix}=${present ? "yes" : "no"}`);
  if (present) fail(`_site contains ${prefix}`);
}
for (const required of ["index.html", "styles.css", "script.js", "agentropolis-loop-baseline.js"]) {
  if (!siteFiles.includes(required)) fail(`_site missing ${required}`);
}

const honestBytes = await readFile(path.join(publishRoot, "agentropolis-loop-baseline.js"));
const honestDigest = sha384(honestBytes);
console.log(`HONEST_SHA384=${honestDigest}`);
if (`sha384-${honestDigest}` !== EXPECTED_INTEGRITY) {
  fail(`honest baseline sha384 ${honestDigest} != pinned integrity`);
}

const tamperRoot = await mkdtemp(path.join(tmpdir(), "atlas-sri-"));
await cp(publishRoot, tamperRoot, { recursive: true });
const tamperPath = path.join(tamperRoot, "agentropolis-loop-baseline.js");
await writeFile(
  tamperPath,
  Buffer.concat([
    await readFile(tamperPath),
    Buffer.from("\n;window.__AGENTROPOLIS_LOOP_BASELINE_TAMPER__=true;\n"),
  ]),
);
const tamperDigest = sha384(await readFile(tamperPath));
console.log(`TAMPER_SHA384=${tamperDigest}`);
if (tamperDigest === honestDigest) fail("tamper did not change baseline bytes");

const browser = await chromium.launch({
  executablePath: await findChrome(),
  headless: true,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});
console.log(`CHROME=${browser.version()}`);

try {
  const honest = await exercise(browser, publishRoot);
  printCase("honest", honest);

  const probeServer = await startServer(publishRoot);
  const probePort = probeServer.address().port;
  try {
    for (const forbidden of FORBIDDEN) {
      const url = `http://127.0.0.1:${probePort}${BASE}/${forbidden}`;
      const response = await fetch(url);
      const body = await response.text();
      console.log(`PROBE ${response.status} ${url} bytes=${body.length}`);
      if (response.status !== 404) fail(`${forbidden} returned ${response.status}`);
      if (body.includes("AGENTROPOLIS") || body.includes("<html")) {
        fail(`${forbidden} served page HTML`);
      }
    }
  } finally {
    await new Promise((resolve) => probeServer.close(resolve));
  }

  const tamper = await exercise(browser, tamperRoot);
  printCase("tamper", tamper);

  const honestErrors = honest.consoleMessages.filter((message) => message.type === "error");
  const assetStatus = new Map(honest.responses.map((response) => [pathname(response.url), response.status]));
  for (const asset of REQUIRED) {
    const status = assetStatus.get(asset);
    console.log(`ASSET ${asset} ${status ?? "missing"}`);
    if (status !== 200) fail(`${asset} status ${status ?? "missing"}`);
  }
  const designSystem = [...honest.requests, ...tamper.requests].filter((request) =>
    /AGENTROPOLIS-DESIGN-SYSTEM|agentropolis-city-of-agents\.github\.io/i.test(request.url),
  );
  console.log(`DESIGN_SYSTEM_REQUESTS=${designSystem.length}`);
  for (const request of designSystem) console.log(`DESIGN_SYSTEM ${request.url}`);
  const remote = honest.requests.filter((request) => {
    try {
      return new URL(request.url).hostname !== "127.0.0.1";
    } catch {
      return true;
    }
  });
  console.log(`REMOTE_REQUESTS=${remote.length}`);
  const badStatus = honest.responses.filter((response) => response.status >= 400);
  const baseline = honest.state.scripts.find((script) => script.src?.includes("agentropolis-loop-baseline.js"));
  if (honest.status !== 200) fail(`index status ${honest.status}`);
  if (!honest.state.loaded || honest.state.version !== "1.0.0" || !honest.state.host) {
    fail("local baseline did not execute");
  }
  if (honest.state.tamper) fail("honest page set the tamper flag");
  if (!baseline || baseline.integrity !== EXPECTED_INTEGRITY || baseline.crossorigin !== "anonymous") {
    fail("served script tag is missing the pinned integrity");
  }
  if (designSystem.length) fail("page requested the design system");
  if (remote.length) fail("page requested a remote URL");
  if (honestErrors.length || honest.pageErrors.length) fail("console or page error on honest load");
  if (badStatus.length) fail("honest load had an HTTP error");
  if (!honest.state.href.includes(`${BASE}/`)) fail(`page URL is not under ${BASE}/`);

  const tamperScript = tamper.responses.find((response) =>
    pathname(response.url).endsWith("/agentropolis-loop-baseline.js"),
  );
  const integritySignals = [
    ...tamper.consoleMessages.map((message) => message.text),
    ...tamper.pageErrors,
  ].filter((text) => /integrity|digest|blocked/i.test(text));
  console.log(`TAMPER_SCRIPT_STATUS=${tamperScript?.status ?? "missing"}`);
  console.log(`TAMPER_INTEGRITY_SIGNALS=${integritySignals.length}`);
  if (tamper.state.loaded || tamper.state.tamper || tamper.state.host) {
    fail("tampered baseline executed");
  }
  if (!tamperScript || tamperScript.status !== 200) fail("tampered file was not fetched");
  if (!integritySignals.length) fail("browser did not report an integrity block");
  const tamperTag = tamper.state.scripts.find((script) => script.src?.includes("agentropolis-loop-baseline.js"));
  if (!tamperTag || tamperTag.integrity !== EXPECTED_INTEGRITY) {
    fail("tamper page did not keep the pinned integrity attribute");
  }

  if (process.exitCode) process.exit(process.exitCode);
  console.log("SMOKE=pass");
} finally {
  await browser.close();
  await rm(tamperRoot, { recursive: true, force: true });
}
