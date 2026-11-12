// 선택형 브라우저 검증 어댑터 예시(React + Vite + Playwright). 엔진 코드가 아니며, 엔진은 이 파일을 실행·설치하지 않습니다.
// 프로젝트가 tools/pb-ui/로 복사하고 검토·수정한 뒤, 프로필 verify.steps의 브라우저 단계(report.format = "pb-ui")로 연결합니다.
//
// 하는 일: 시나리오 파일의 화면 상태 × 뷰포트마다 페이지를 열어 렌더 여부·콘솔 오류·접근성(axe, 있으면)·가로 넘침·상호작용을
// 확인하고 $PB_REPORT_DIR/ui.json에 pb-ui-report/v1을 씁니다. 판정(차단/보고)은 엔진이 합니다.
// - playwright 패키지나 브라우저가 없으면 status = "not_run" 리포트를 쓰고 끝냅니다(엔진이 미실행으로 기록).
// - 앱 서버를 띄우지 못하면 모든 결과를 rendered = false로 씁니다(렌더 실패 = 차단).
// - 스크린샷은 참고 자료일 뿐입니다. 엔진은 rendered·콘솔·접근성·상호작용 결과로 판정합니다.
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const REPORT_DIR = process.env.PB_REPORT_DIR;
const RUN_ID = process.env.PB_RUN_ID;
if (!REPORT_DIR || !RUN_ID) {
  console.error("PB_REPORT_DIR·PB_RUN_ID가 없습니다. /product-build verify가 실행할 때만 씁니다.");
  process.exit(2);
}
const scenarioPath = process.argv[2] || "tools/pb-ui/ui-scenarios.json";
const sc = JSON.parse(readFileSync(scenarioPath, "utf8"));
const base = (sc.base_url || "http://127.0.0.1:4173").replace(/\/$/, "");
const write = (body) => writeFileSync(join(REPORT_DIR, "ui.json"), JSON.stringify({ format: "pb-ui-report/v1", run_id: RUN_ID, base_url: base, ...body }, null, 2));

let pw;
try {
  pw = await import("playwright");
} catch {
  write({ tool: "playwright", status: "not_run", reason: "playwright 패키지가 설치되지 않았습니다(설치는 사용자 결정)", results: [] });
  process.exit(0);
}
let AxeBuilder = null;
try {
  AxeBuilder = (await import("@axe-core/playwright")).default;
} catch {
  AxeBuilder = null; // 접근성 검사 없음 → 결과의 a11y = null(엔진이 a11y_not_checked로 보고)
}

async function waitFor(url, ms) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return true;
    } catch { /* 아직 안 뜸 */ }
    await new Promise((res) => setTimeout(res, 500));
  }
  return false;
}

let server = null;
if (sc.server?.command) {
  server = spawn(sc.server.command, { shell: true, stdio: "ignore", detached: true });
}
const stopServer = () => { if (server) { try { process.kill(-server.pid); } catch { /* 이미 종료 */ } } };
const up = await waitFor(sc.server?.url || base, sc.server?.timeout_ms || 30000);

const viewports = sc.viewports || { mobile: { width: 390, height: 844 } };
const results = [];
mkdirSync(join(REPORT_DIR, "shots"), { recursive: true });

if (!up) {
  for (const s of sc.scenarios) for (const vp of s.viewports || Object.keys(viewports)) {
    results.push({ screen: s.screen, state: s.state, viewport: vp, rendered: false, console_errors: ["앱 서버에 연결하지 못함"], a11y: null,
      acs: s.acs || [], interactions: [] });
  }
  write({ tool: "playwright", status: "completed", results });
  stopServer();
  process.exit(0);
}

let browser;
try {
  browser = await pw.chromium.launch();
} catch (e) {
  write({ tool: "playwright", status: "not_run", reason: `브라우저를 실행하지 못했습니다: ${String(e.message || e).slice(0, 200)}`, results: [] });
  stopServer();
  process.exit(0);
}

async function open(ctx, s, errors) {
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 300)));
  const resp = await page.goto(base + s.path, { waitUntil: "networkidle" }).catch(() => null);
  let ok = !!resp && resp.status() < 400;
  if (ok && s.wait_for) ok = await page.locator(s.wait_for).first().isVisible({ timeout: s.timeout_ms || 5000 }).catch(() => false);
  return { page, ok };
}

async function runSteps(page, it) {
  for (const st of it.steps || []) {
    if (st.click) await page.locator(st.click).first().click({ timeout: 5000 });
    else if (st.fill) await page.locator(st.fill[0]).first().fill(st.fill[1], { timeout: 5000 });
    else if (st.press) await page.keyboard.press(st.press);
  }
  const ex = it.expect || {};
  if (ex.visible) return page.locator(ex.visible).first().isVisible({ timeout: 5000 }).catch(() => false);
  if (ex.url_contains) return page.url().includes(ex.url_contains);
  return true;
}

for (const s of sc.scenarios) {
  for (const vp of s.viewports || Object.keys(viewports)) {
    const ctx = await browser.newContext({ viewport: viewports[vp] });
    const errors = [];
    const { page, ok } = await open(ctx, s, errors);
    const shot = `shots/${s.state || s.screen}-${vp}.png`;
    await page.screenshot({ path: join(REPORT_DIR, shot), fullPage: true }).catch(() => null);
    let a11y = null;
    if (AxeBuilder && ok) {
      const r = await new AxeBuilder({ page }).analyze().catch(() => null);
      if (r) {
        a11y = { critical: 0, serious: 0, moderate: 0, minor: 0 };
        for (const v of r.violations) if (v.impact in a11y) a11y[v.impact] += 1;
      }
    }
    const overflow = ok ? await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth) : false;
    const interactions = [];
    for (const it of s.interactions || []) {
      const fresh = await open(ctx, s, []); // 상호작용마다 새로 열어 서로 영향을 주지 않게
      const passed = fresh.ok ? await runSteps(fresh.page, it).catch(() => false) : false;
      interactions.push({ name: it.name, passed, core: it.core !== false, acs: it.acs || [] });
      await fresh.page.close();
    }
    results.push({ screen: s.screen, state: s.state, viewport: vp, rendered: ok, console_errors: errors, a11y, overflow,
      acs: s.acs || [], interactions, screenshot: shot });
    await ctx.close();
  }
}
const tool = `playwright/chromium ${browser.version()}`;
await browser.close();
stopServer();
write({ tool, status: "completed", results });
process.exit(0);
