// 선택형 디자인 탐색 측정 어댑터 예시(Chrome DevTools Protocol, 의존성 없음). 엔진 코드가 아니며 엔진은 이 파일을 설치·수정하지 않습니다.
// 프로젝트가 tools/pd-measure/로 복사하고 검토한 뒤 explore-config --measure-cmd로 연결합니다(사용자 확인 문장 필요).
//   예: explore-config --measure-cmd "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs" --confirm --note "…"
//   (Node 22 이상은 --experimental-websocket 없이 동작. 브라우저 경로는 CHROME_PATH로 지정 가능)
//
// 하는 일: 엔진이 쓴 측정 명세($PD_MEASURE_SPEC)의 시안 × 대상 × 뷰포트마다 파생 페이지를 열어 **측정 사실만** 기록합니다.
//   - 실제 뷰포트(innerWidth·innerHeight·devicePixelRatio), 렌더 여부, 콘솔·리소스 오류, data-el 요소 상자, 고정·sticky 요소 상자,
//     적중 검사(스크롤해도 눌리거나 보이지 않는 요소), 터치 영역, 텍스트 대비, 기본 접근성 규칙 개수, 뷰포트 크기 스크린샷
//   - 판정(차단·경고)은 엔진이 합니다. 이 파일은 요청값을 실제값으로 복사하지 않습니다(불일치는 엔진이 측정 무효로 처리).
// 방식(--method= 또는 명세 method):
//   emulation(기본): Emulation.setDeviceMetricsOverride로 모바일 뷰포트를 정확히 재현(headless 최소 창 크기 문제 회피)
//   iframe: 큰 창 안의 정확한 크기 iframe에 시안을 넣어 측정(에뮬레이션이 없는 도구와 같은 방식)
//   window: 창 크기(--window-size)만 지정(재현용: 최소 창 크기 때문에 실제 뷰포트가 달라질 수 있음 → 엔진이 viewport_mismatch로 무효 처리)
// - Chrome이나 WebSocket이 없으면 status = "not_run" 리포트를 쓰고 끝냅니다(엔진이 미실행으로 기록 → 경고 후 선택 허용).
// - 외부 네트워크를 쓰지 않고 레퍼런스 원본 이미지를 입력으로 받지 않습니다.
import { spawn, execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const REPORT_DIR = process.env.PD_REPORT_DIR;
const RUN_ID = process.env.PD_RUN_ID;
const SPEC = process.env.PD_MEASURE_SPEC;
if (!REPORT_DIR || !RUN_ID || !SPEC) {
  console.error("PD_REPORT_DIR·PD_RUN_ID·PD_MEASURE_SPEC가 없습니다. /product-design explore-verify가 실행할 때만 씁니다.");
  process.exit(2);
}
const spec = JSON.parse(readFileSync(SPEC, "utf8"));
const arg = (k) => (process.argv.find((a) => a.startsWith(`--${k}=`)) || "").split("=").slice(1).join("=") || null;
const METHOD = arg("method") || spec.method || "emulation";
const write = (body) => writeFileSync(join(REPORT_DIR, "report.json"),
  JSON.stringify({ format: "design-explore-report/v1", run_id: RUN_ID, round: spec.round, tool: "pd-measure-cdp", ...body }, null, 2));

if (typeof WebSocket === "undefined") {
  write({ status: "not_run", reason: "WebSocket이 없습니다(Node 22 이상 또는 node --experimental-websocket 필요)", results: [] });
  process.exit(0);
}
function findChrome() {
  const cands = [process.env.CHROME_PATH, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].filter(Boolean);
  for (const c of cands) if (existsSync(c)) return c;
  for (const n of ["google-chrome", "chromium", "chromium-browser"]) {
    try { return execFileSync("which", [n]).toString().trim(); } catch { /* 없음 */ }
  }
  return null;
}
const CHROME = findChrome();
if (!CHROME) {
  write({ status: "not_run", reason: "Chrome·Chromium을 찾지 못했습니다(CHROME_PATH로 지정 가능, 설치는 사용자 결정)", results: [] });
  process.exit(0);
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = new Set();
    ws.onmessage = (ev) => {
      const m = JSON.parse(typeof ev.data === "string" ? ev.data : Buffer.from(ev.data).toString());
      if (m.id && this.pending.has(m.id)) {
        const p = this.pending.get(m.id); this.pending.delete(m.id);
        if (m.error) p.rej(new Error(m.error.message)); else p.res(m.result);
      } else if (m.method) for (const h of this.handlers) h(m);
    };
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); rej(new Error(`CDP 시간 초과: ${method}`)); } }, 30000);
    });
  }
  on(h) { this.handlers.add(h); return () => this.handlers.delete(h); }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function launch(winW, winH) {
  const dir = mkdtempSync(join(tmpdir(), "pd-measure-"));
  const proc = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${dir}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--allow-file-access-from-files",
    "--hide-scrollbars", `--window-size=${winW},${winH}`, "about:blank"], { stdio: "ignore" });
  const portFile = join(dir, "DevToolsActivePort");
  for (let i = 0; i < 150 && !existsSync(portFile); i++) await sleep(100);
  if (!existsSync(portFile)) { proc.kill(); throw new Error("Chrome 원격 디버깅 포트가 열리지 않았습니다"); }
  let txt = "";
  for (let i = 0; i < 20 && txt.split("\n").length < 2; i++) { txt = readFileSync(portFile, "utf8").trim(); await sleep(50); }
  const [port, path] = txt.split("\n");
  const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("CDP 연결 실패")); });
  const cdp = new CDP(ws);
  const ver = await cdp.send("Browser.getVersion").catch(() => ({}));
  return { cdp, version: ver.product || "", close: async () => {
    try { await cdp.send("Browser.close"); } catch { /* 이미 종료 */ }
    try { proc.kill(); } catch { /* 이미 종료 */ }
    await sleep(100); rmSync(dir, { recursive: true, force: true });
  } };
}

// 페이지 안에서 실행(측정 사실만 수집). frame=true면 첫 iframe 문서를 잽니다.
function MEASURE(a) {
  const frame = a.frame ? document.querySelector("iframe") : null;
  const W = frame ? frame.contentWindow : window;
  let D;
  try { D = W.document; if (!D) throw 0; } catch { return { error: "iframe 문서에 접근할 수 없습니다(--allow-file-access-from-files 필요)" }; }
  W.scrollTo(0, 0);
  const cs = (n) => W.getComputedStyle(n);
  const visible = (n) => { const s = cs(n); if (s.display === "none" || s.visibility === "hidden" || +s.opacity === 0) return false;
    const r = n.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const fixedOf = (n) => { for (let x = n; x && x.nodeType === 1; x = x.parentElement) { const p = cs(x).position; if (p === "fixed" || p === "sticky") return x; } return null; };
  const target = D.querySelector(`[data-target="${a.target}"]`);
  const scope = target || D.body;
  const rendered = !!target && visible(target);
  const label = (n) => n.getAttribute("data-el") || (n.tagName.toLowerCase() + (typeof n.className === "string" && n.className ? "." + n.className.split(/\s+/)[0] : ""));
  const fixedEls = [...scope.querySelectorAll("*")].filter((n) => { const p = cs(n).position; return (p === "fixed" || p === "sticky") && visible(n); });
  const fixed = fixedEls.map((n) => { const r = n.getBoundingClientRect(); return { label: label(n), position: cs(n).position, box: [r.x, r.y, r.width, r.height] }; });
  const parse = (c) => { const m = (c || "").match(/[\d.]+/g); if (!m || m.length < 3) return null; return { r: +m[0], g: +m[1], b: +m[2], a: m.length > 3 ? +m[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = (n) => { const layers = [];
    for (let x = n; x && x.nodeType === 1; x = x.parentElement) { const s = cs(x); if (s.backgroundImage && s.backgroundImage !== "none") return null;
      const c = parse(s.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } }
    let base = { r: 255, g: 255, b: 255 };
    for (const c of layers.reverse()) base = { r: c.r * c.a + base.r * (1 - c.a), g: c.g * c.a + base.g * (1 - c.a), b: c.b * c.a + base.b * (1 - c.a) };
    return base; };
  const items = [...scope.querySelectorAll("[data-el]")];
  const sx = W.scrollX, sy = W.scrollY;
  const elements = items.map((n) => {
    const r = n.getBoundingClientRect();
    const within = n.parentElement ? n.parentElement.closest("[data-el]") : null;
    let contrast = null, fs = null, fw = null;
    const tw = D.createTreeWalker(n, NodeFilter.SHOW_TEXT);
    for (let t = tw.nextNode(); t; t = tw.nextNode()) {
      const p = t.parentElement;
      if (!t.textContent.trim() || !p || p.closest("[data-el]") !== n || !visible(p)) continue;
      const fg = parse(cs(p).color), bg = bgOf(p);
      if (!fg || !bg) continue;
      const fgc = { r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a) };
      const L1 = lum(fgc), L2 = lum(bg); const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      if (contrast === null || ratio < contrast) { contrast = Math.round(ratio * 100) / 100; fs = parseFloat(cs(p).fontSize); fw = parseInt(cs(p).fontWeight, 10); }
    }
    return { id: n.getAttribute("data-el"), box: [r.x + sx, r.y + sy, r.width, r.height], visible: visible(n), in_fixed: !!fixedOf(n),
      contains_fixed: fixedEls.some((f) => f !== n && n.contains(f)), within: within ? within.getAttribute("data-el") : null,
      contrast, font_size: fs, font_weight: fw };
  });
  // 적중 검사: 요소를 화면 가운데로 스크롤한 뒤 여러 점에서 elementFromPoint가 그 요소(또는 안쪽)를 가리키는지
  const pts = [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];
  for (const e of elements) {
    const n = items.find((x) => x.getAttribute("data-el") === e.id);
    if (!e.visible || e.in_fixed || e.contains_fixed) { e.reachable = e.visible ? true : null; continue; }
    n.scrollIntoView({ block: "center", inline: "nearest" });
    const r = n.getBoundingClientRect();
    e.reachable = pts.some(([fx, fy]) => { const x = r.x + r.width * fx, y = r.y + r.height * fy;
      if (x < 0 || y < 0 || x >= W.innerWidth || y >= W.innerHeight) return false;
      const h = D.elementFromPoint(x, y); return !!h && (h === n || n.contains(h)); });
  }
  W.scrollTo(0, 0);
  // 컴포넌트 표지(data-cmp)의 계산된 스타일: 엔진이 같은 시안의 화면 간 일관성을 비교(EX5)
  const CPROPS = ["background-color", "background-image", "color", "border-radius", "border-top-width", "border-top-style", "border-top-color",
    "box-shadow", "font-family", "font-size", "font-weight", "padding-top", "padding-left"];
  const components = [...scope.querySelectorAll("[data-cmp]")].filter(visible).map((n) => {
    const s = cs(n); const style = {}; for (const p of CPROPS) style[p] = s.getPropertyValue(p);
    const de = n.closest("[data-el]");
    // 선언된 상태(같은 컴포넌트의 의도된 다른 모습): disabled·selected·current·pressed·checked·expanded, 또는 data-cmp-state
    const on = (k) => { const v = n.getAttribute(k); return v !== null && v !== "false"; };
    const st = new Set((n.getAttribute("data-cmp-state") || "").split(/\s+/).filter(Boolean));
    if (n.disabled || on("aria-disabled")) st.add("disabled");
    if (on("aria-selected") || on("aria-current")) st.add("selected");
    if (on("aria-pressed") || on("aria-checked")) st.add("pressed");
    if (on("aria-expanded")) st.add("expanded");
    return { cmp: n.getAttribute("data-cmp"), variant: n.getAttribute("data-cmp-variant") || "", state: [...st].sort().join(" "),
      el: de ? de.getAttribute("data-el") : null, style };
  });
  const interactive = [...scope.querySelectorAll("a[href],button,input:not([type=hidden]),select,textarea,[role=button]")].filter(visible);
  const touch = interactive.map((n) => { const r = n.getBoundingClientRect(); const de = n.closest("[data-el]");
    return { el: de ? de.getAttribute("data-el") : null, label: label(n), w: Math.round(r.width), h: Math.round(r.height) }; });
  const nameOf = (n) => (n.getAttribute("aria-label") || "").trim() || (n.getAttribute("title") || "").trim() || (n.textContent || "").trim()
    || [...n.querySelectorAll("img[alt]")].map((i) => i.alt).join("").trim();
  const a11y = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  for (const n of interactive) {
    if ((n.matches("button,[role=button]")) && !nameOf(n)) a11y.critical++;
    if (n.matches("a[href]") && !nameOf(n)) a11y.serious++;
    if (n.matches("input,select,textarea") && !(n.getAttribute("aria-label") || n.closest("label") || (n.id && D.querySelector(`label[for="${n.id}"]`)))) a11y.critical++;
  }
  for (const i of scope.querySelectorAll("img")) if (!i.hasAttribute("alt") && visible(i)) a11y.critical++;
  if (!D.documentElement.getAttribute("lang")) a11y.serious++;
  const de = D.documentElement;
  const tmin = (a.checks && a.checks.touch_min_px) || 44;
  // 이미지 사실(변경 요청 화면 검증용): 실제 픽셀 크기, 렌더 상자, object-fit, 조상 overflow에 의한 잘림. 판정은 엔진이 합니다.
  const images = [...scope.querySelectorAll("img")].map((i) => {
    const r = i.getBoundingClientRect(); const s = cs(i); let clippedBy = null;
    for (let x = i.parentElement; x && x !== D.body && x !== scope.parentElement; x = x.parentElement) {
      const xs = cs(x);
      if (xs.overflow !== "visible" || xs.overflowX !== "visible" || xs.overflowY !== "visible") {
        const xr = x.getBoundingClientRect();
        if (r.left < xr.left - 1 || r.right > xr.right + 1 || r.top < xr.top - 1 || r.bottom > xr.bottom + 1) { clippedBy = label(x); break; }
      }
    }
    return { src: (i.currentSrc || i.src || "").split("/").pop().split("?")[0].slice(0, 160), complete: i.complete,
      natural: [i.naturalWidth, i.naturalHeight], box: [r.x + sx, r.y + sy, r.width, r.height], visible: visible(i), object_fit: s.objectFit, clipped_by: clippedBy };
  });
  return {
    viewport_actual: { width: W.innerWidth, height: W.innerHeight, dpr: W.devicePixelRatio }, rendered,
    a11y, overflow: de.scrollWidth > de.clientWidth,
    clipped: elements.some((e) => e.visible && !e.in_fixed && (e.box[0] < -1 || e.box[0] + e.box[2] > de.clientWidth + 1)),
    touch_target_violations: a.mobile ? touch.filter((t) => Math.min(t.w, t.h) < tmin).length : 0,
    layout: { scroll_width: de.scrollWidth, client_width: de.clientWidth, scroll_height: de.scrollHeight, viewport_height: W.innerHeight,
      elements, fixed, touch, components },
    images,
  };
}

async function measureOne(b, page, vp, method) {
  const { targetId } = await b.cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await b.cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const S = (m, p) => b.cdp.send(m, p, sessionId);
  const errors = [];
  const off = b.cdp.on((m) => {
    if (m.sessionId !== sessionId) return;
    if (m.method === "Runtime.exceptionThrown") errors.push(String(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text).slice(0, 300));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map((x) => x.value ?? x.description ?? "").join(" ").slice(0, 300));
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error"
      && !(spec.asset_fallback && /_assets\//.test(m.params.entry.url || "") )) errors.push(`${m.params.entry.text} ${basename(m.params.entry.url || "")}`.slice(0, 300));
  });
  await S("Page.enable"); await S("Runtime.enable"); await S("Log.enable");
  if (spec.asset_fallback) { // 자산 없이 렌더(대체 표시) 측정: 라운드 자산 사본 요청을 막음 — 막은 요청의 오류는 콘솔 오류로 세지 않음
    await S("Network.enable"); await S("Network.setBlockedURLs", { urls: [spec.asset_block_pattern || "*/_assets/*"] });
  }
  if (method === "emulation") await S("Emulation.setDeviceMetricsOverride", { width: vp.width, height: vp.height, deviceScaleFactor: vp.dpr, mobile: !!vp.mobile });
  if (method === "iframe") await S("Emulation.setDeviceMetricsOverride", { width: 0, height: 0, deviceScaleFactor: vp.dpr, mobile: false });
  let url = page.url;
  if (method === "iframe") {
    const wrap = join(dirname(page.file), `_frame-${page.variant}-${page.target}-${vp.name}.html`);
    writeFileSync(wrap, `<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>html,body{margin:0;background:#fff}` +
      `iframe{border:0;display:block;width:${vp.width}px;height:${vp.height}px}</style></head><body><iframe src="${basename(page.file)}"></iframe></body></html>`);
    url = pathToFileURL(wrap).href;
  }
  const loaded = new Promise((res) => { const o = b.cdp.on((m) => { if (m.sessionId === sessionId && m.method === "Page.loadEventFired") { o(); res(true); } });
    setTimeout(() => { o(); res(false); }, 15000); });
  const nav = await S("Page.navigate", { url });
  const ok = !nav.errorText && (await loaded);
  await S("Runtime.evaluate", { expression: "document.fonts ? document.fonts.ready.then(() => 1) : 1", awaitPromise: true }).catch(() => null);
  await sleep(150);
  const ev = await S("Runtime.evaluate", { expression: `(${MEASURE.toString()})(${JSON.stringify({ target: page.target, frame: method === "iframe", mobile: !!vp.mobile, checks: spec.checks })})`,
    returnByValue: true, awaitPromise: true });
  const m = ev.result?.value || { error: ev.exceptionDetails?.text || "측정 스크립트 실패" };
  const shotRel = `shots/${page.variant}-${page.target}-${vp.name}.png`;
  const cap = method === "iframe"
    ? await S("Page.captureScreenshot", { format: "png", clip: { x: 0, y: 0, width: vp.width, height: vp.height, scale: 1 } })
    : await S("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(REPORT_DIR, shotRel), Buffer.from(cap.data, "base64"));
  off();
  await b.cdp.send("Target.closeTarget", { targetId }).catch(() => null);
  const base = { variant: page.variant, target: page.target, viewport: vp.name, viewport_requested: { width: vp.width, height: vp.height, dpr: vp.dpr },
    method, console_errors: errors, a11y_tool: "basic-dom(button-name,link-name,image-alt,label,html-lang)", screenshot: shotRel, interactions: [] };
  if (m.error || !ok) {
    return { ...base, viewport_actual: m.viewport_actual || { width: 0, height: 0, dpr: 0 }, rendered: false, a11y: null,
      console_errors: errors.concat(m.error ? [m.error] : [], nav.errorText ? [nav.errorText] : []) };
  }
  const reach = Object.fromEntries(m.layout.elements.map((e) => [e.id, e.reachable]));
  const interactions = page.elements.filter((e) => ["action", "navigation", "input"].includes(e.kind))
    .map((e) => ({ name: `tap:${e.id}`, element: e.id, passed: reach[e.id] === true, core: !!e.core }));
  return { ...base, ...m, interactions };
}

// 페이지 하나의 측정이 실패하면 그 결과만 렌더 실패로 기록(뷰포트를 모르므로 0 — 엔진이 렌더 실패로 판정)
const failed = (p, vp, method, e) => ({ variant: p.variant, target: p.target, viewport: vp.name, viewport_requested: { width: vp.width, height: vp.height, dpr: vp.dpr },
  viewport_actual: { width: 0, height: 0, dpr: 0 }, method, rendered: false, console_errors: [`측정 실패: ${String(e.message || e).slice(0, 200)}`], a11y: null, interactions: [] });
mkdirSync(join(REPORT_DIR, "shots"), { recursive: true });
const results = [];
let version = "";
try {
  if (METHOD === "window") {
    for (const vp of spec.viewports) { // 창 크기만 지정: 뷰포트마다 브라우저를 새로 띄움
      const b = await launch(vp.width, vp.height);
      version = b.version;
      try { for (const p of spec.pages) results.push(await measureOne(b, p, vp, "window").catch((e) => failed(p, vp, "window", e))); } finally { await b.close(); }
    }
  } else {
    const maxW = Math.max(1280, ...spec.viewports.map((v) => v.width + 40)), maxH = Math.max(1000, ...spec.viewports.map((v) => v.height + 40));
    const b = await launch(maxW, maxH);
    version = b.version;
    try { for (const p of spec.pages) for (const vp of spec.viewports) results.push(await measureOne(b, p, vp, METHOD).catch((e) => failed(p, vp, METHOD, e))); } finally { await b.close(); }
  }
} catch (e) {
  write({ status: "not_run", reason: `브라우저 측정을 시작하지 못했습니다: ${String(e.message || e).slice(0, 200)}`, results: [] });
  process.exit(0);
}
write({ status: "completed", browser: version, method: METHOD, results });
