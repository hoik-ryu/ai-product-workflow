"""/product-design 변경 요청(CR) Type B: 영향 화면·상태의 실제 브라우저 검증(reference/change-request.md §3.4).

- 전체 앱 빌드(`preview_build`)와 별개의 검증입니다. 둘을 섞어 기록하지 않습니다.
- 승인된 프리뷰 트리는 바꾸지 않습니다. 저장소 밖 임시 사본에 화면 단독 측정 엔트리(`__pd_measure.html`)를 붙여 프로젝트 vite 설정으로
  따로 빌드하고, 로컬 HTTP(127.0.0.1)로 띄운 뒤 **사용자가 확인한 측정 명령**(`config.exploration.measure_cmd`, 지문 확인)을 실행합니다.
- 어댑터는 사실만 기록하고(design-explore-report/v1 + `images`), 판정은 이 모듈이 합니다.
- 측정이 실제로 끝나지 않으면(`not_run`·`invalid`) 화면 검증 완료로 기록하지 않습니다.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.request
from pathlib import Path

from pd_core import PREVIEW_DIR, PREVIEW_MANIFEST, now, read_text, sha256_file
import pd_measure as MS

MEASURE_ENTRY = "__pd_measure.html"
MEASURE_TSX = "src/__pd_measure.tsx"
MEASURE_CONFIG = "vite.pdmeasure.config.ts"
OUT_DIR = "__pd_measure_dist"
ASPECT_TOL = 0.02
EXCLUDE = {"node_modules", "dist", ".vite", OUT_DIR}

ENTRY_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>pd-measure</title><link rel="icon" href="data:," /></head>
<body><div id="root"></div><script type="module" src="/src/__pd_measure.tsx"></script></body></html>
"""
ENTRY_TSX = """// /product-design change verify 전용 측정 엔트리(임시 사본에서만 존재, 승인 트리에 쓰지 않음)
import { createRoot } from 'react-dom/client'
import './tokens.css'
import './preview.css'
import { screens } from './registry'
const [id, state] = window.location.hash.replace(/^#/, '').split('/')
const s = (screens as Record<string, { render: (st: string) => unknown }>)[id]
createRoot(document.getElementById('root')!).render(
  <div data-target={id} data-state={state}>{s ? (s.render(state) as any) : null}</div>,
)
"""
CONFIG_TS = """import { defineConfig, mergeConfig } from 'vite'
// @ts-ignore 프로젝트 프리뷰 설정을 그대로 쓰고 입력·출력만 바꿉니다
import base from './vite.config'
export default defineConfig(async (env) => mergeConfig(typeof base === 'function' ? await (base as any)(env) : base, {
  logLevel: 'error',
  build: { outDir: '__pd_measure_dist', emptyOutDir: true, assetsInlineLimit: 0, rollupOptions: { input: '__pd_measure.html' } },
}))
"""


def manifest_states(project: Path) -> dict[str, list[str]]:
    try:
        man = json.loads(read_text(project, PREVIEW_MANIFEST) or "{}")
    except json.JSONDecodeError:
        return {}
    return {sid: list(m.get("states") or []) for sid, m in (man.get("screens") or {}).items() if isinstance(m, dict) and not m.get("skip")}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_bundle(project: Path, tmp: Path, timeout: int) -> tuple[bool, str]:
    src = project / PREVIEW_DIR
    dst = tmp / "preview"

    def ignore(d, names):
        return [n for n in names if n in EXCLUDE] if Path(d) == src else [n for n in names if n in ("node_modules",)]
    shutil.copytree(src, dst, ignore=ignore, symlinks=False)
    nm = src / "node_modules"
    if not nm.is_dir():
        return False, "design-preview/node_modules가 없습니다(먼저 프리뷰 빌드가 필요)"
    (dst / "node_modules").symlink_to(nm.resolve(), target_is_directory=True)
    (dst / MEASURE_ENTRY).write_text(ENTRY_HTML, encoding="utf-8")
    (dst / MEASURE_TSX).write_text(ENTRY_TSX, encoding="utf-8")
    if not any((dst / f).is_file() for f in ("vite.config.ts", "vite.config.js", "vite.config.mjs")):
        return False, "프리뷰 vite 설정 파일이 없습니다"
    cfg = CONFIG_TS if (dst / "vite.config.ts").is_file() else CONFIG_TS.replace("'./vite.config'", "'./vite.config.js'" if (dst / "vite.config.js").is_file() else "'./vite.config.mjs'")
    (dst / MEASURE_CONFIG).write_text(cfg, encoding="utf-8")
    vite = dst / "node_modules/.bin/vite"
    try:
        p = subprocess.run([str(vite), "build", "--config", MEASURE_CONFIG], cwd=dst, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"측정용 번들 빌드 실패: {e}"
    if p.returncode != 0 or not (dst / OUT_DIR / MEASURE_ENTRY).is_file():
        return False, "측정용 번들 빌드 실패: " + (p.stderr or p.stdout or "").strip()[-400:]
    return True, ""


def _serve(root: Path) -> tuple[subprocess.Popen, int]:
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(root)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/{MEASURE_ENTRY}", timeout=1).read(10)
            return proc, port
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise OSError("측정용 로컬 서버가 열리지 않았습니다")


def judge(r: dict, expected_images: list[dict], where: str) -> tuple[list[str], list[str], dict]:
    """한 화면·상태·뷰포트 결과 판정. Type B는 '보이는 결과가 승인 계약 안'이어야 하므로 레이아웃·이미지 결함도 차단입니다."""
    B, W, info = MS.common_findings(r, where)
    W = [w for w in W if w not in ("overflow", "clipped")]
    lay = r.get("layout") if isinstance(r.get("layout"), dict) else None
    if lay is None:
        B.append("layout_not_measured")
    else:
        sw, cw = MS._num(lay.get("scroll_width", 0), "scroll_width", where), MS._num(lay.get("client_width", 0), "client_width", where)
        if sw > cw + 1:
            B.append(f"horizontal_scroll({sw:g}>{cw:g})")
    if r.get("clipped") is True:
        B.append("content_clipped")
    imgs = r.get("images")
    detail = {"images": []}
    if imgs is None:
        if expected_images:
            B.append("images_not_measured(어댑터가 이미지 측정을 지원하지 않음)")
        else:
            W.append("images_not_measured")
        return B, W, info | detail
    if not isinstance(imgs, list):
        raise MS.ReportError(f"{where}: images는 목록이어야 합니다")
    for i, im in enumerate(imgs):
        if not isinstance(im, dict):
            raise MS.ReportError(f"{where}.images[{i}]: 객체여야 합니다")
        nat = im.get("natural") or [0, 0]
        box = MS._box(im.get("box"), f"{where}.images[{i}]")
        src = str(im.get("src") or "")
        rec = {"src": src, "natural": nat, "box": box, "object_fit": im.get("object_fit"), "clipped_by": im.get("clipped_by")}
        detail["images"].append(rec)
        if not im.get("visible"):
            continue
        if not im.get("complete") or not nat or nat[0] == 0:
            B.append(f"image_broken:{src}")
            continue
        if im.get("object_fit") in (None, "fill") and box[2] and box[3]:
            ra, rn = box[2] / box[3], nat[0] / nat[1]
            if abs(ra - rn) / rn > ASPECT_TOL:
                B.append(f"image_distorted:{src}(렌더 비율 {ra:.3f}, 원본 {rn:.3f})")
        if im.get("clipped_by"):
            W.append(f"image_cropped:{src}(by {im['clipped_by']})")
        if box[0] < -1 or (lay and box[0] + box[2] > float(lay.get("client_width") or 0) + 1):
            B.append(f"image_clipped_viewport:{src}")
    for e in expected_images:  # 패치한 자산이 그 화면에서 실제로(같은 원본 크기로) 렌더되는지
        stem = e["stem"]
        hits = [x for x in detail["images"] if x["src"].startswith(stem)]
        if not hits:
            B.append(f"expected_image_missing:{stem}")
        elif not any(list(x["natural"]) == [e["width"], e["height"]] for x in hits):
            B.append(f"expected_image_size:{stem}(기대 {e['width']}×{e['height']})")
    return B, W, info | detail


def parse(path: Path, run_id: str, rdir: Path, spec: dict, expected: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise MS.ReportError(f"JSON 해석 실패: {e}")
    if not isinstance(data, dict) or data.get("format") != MS.REPORT_FORMAT:
        raise MS.ReportError(f"{MS.REPORT_FORMAT} 형식이 아닙니다")
    if data.get("run_id") != run_id:
        raise MS.ReportError("리포트의 run_id가 이번 실행과 다릅니다(이전 결과 재사용 의심)")
    if data.get("status", "completed") == "not_run":
        return {"status": "not_run", "reason": str(data.get("reason") or "측정 도구를 실행하지 못함")[:300], "results": [], "invalid": []}
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise MS.ReportError("results가 비어 있습니다")
    import pd_reference as RF
    pages = {(p["variant"], p["target"]): p for p in spec["pages"]}
    vps = {v["name"]: v for v in spec["viewports"]}
    out, invalid, seen = [], [], set()
    for i, r in enumerate(results):
        where = f"results[{i}]"
        if not isinstance(r, dict):
            raise MS.ReportError(f"{where}: 객체여야 합니다")
        key = (r.get("variant"), r.get("target"))
        vp = vps.get(r.get("viewport"))
        if key not in pages or vp is None:
            raise MS.ReportError(f"{where}: 측정 명세에 없는 화면·상태·뷰포트입니다")
        if (key, vp["name"]) in seen:
            raise MS.ReportError(f"{where}: 같은 결과가 중복됩니다")
        seen.add((key, vp["name"]))
        act = r.get("viewport_actual") or {}
        actual = {k: MS._num(act.get(k, 0), f"viewport_actual.{k}", where) for k in ("width", "height", "dpr")}
        B, W, info = judge(r, expected.get(key[1], []), where)
        unknown = not r.get("rendered") and actual["width"] == 0
        if not unknown and ((actual["width"], actual["height"]) != (vp["width"], vp["height"]) or abs(actual["dpr"] - vp["dpr"]) > 0.01):
            invalid.append(f"{key[1]}/{key[0]}@{vp['name']}: viewport_mismatch")
        shot = r.get("screenshot")
        shot_rec = None
        if isinstance(shot, str) and not shot.startswith("/") and ".." not in Path(shot).parts and (rdir / shot).is_file():
            fmt, sw_, sh_ = RF.sniff((rdir / shot).read_bytes()[:4096])
            shot_rec = {"path": shot, "sha256": sha256_file(rdir / shot), "width": sw_, "height": sh_}
        else:
            W.append("screenshot_missing")
        out.append({"screen": key[1], "state": key[0], "viewport": vp["name"], "actual": actual, "rendered": r.get("rendered"),
                    "blocking": B, "warnings": W, "console_errors": info.get("console_errors"), "a11y": info.get("a11y"),
                    "images": info.get("images"), "screenshot": shot_rec})
    missing = [f"{p['target']}/{p['variant']}@{v}" for p in spec["pages"] for v in vps if ((p["variant"], p["target"]), v) not in seen]
    if missing:
        invalid.append("결과 누락: " + ", ".join(missing[:10]))
    return {"status": "completed", "tool": str(data.get("tool") or "")[:120], "browser": str(data.get("browser") or "")[:120],
            "results": out, "invalid": invalid}


def verify_screens(project: Path, st: dict, cid: str, screens: list[str] | None, expected_images: dict, timeout: int = 600) -> dict:
    """영향 화면 검증. 반환 status: completed(측정 완료 — passed 여부 별도) | not_run | invalid."""
    sett = MS.measure_settings(st)
    states = manifest_states(project)
    targets = sorted(states) if screens is None else [s for s in screens if s in states]
    rec = {"kind": "screen_verification", "at": now(), "screens_requested": screens, "screens": targets,
           "expanded_to_all": screens is None, "viewports": sett["viewports"], "method": sett["method"], "status": None, "passed": False}
    if not targets:
        return rec | {"status": "not_applicable", "reason": "프리뷰 manifest에 영향 화면이 없습니다", "passed": True}
    if not sett["cmd"]:
        return rec | {"status": "not_run", "reason": "측정 명령(config.exploration.measure_cmd)이 없습니다"}
    prob = MS.measure_confirmation_problem(project, st)
    if prob:
        return rec | {"status": "not_run", "reason": f"{prob}. 확인되지 않은 명령은 실행하지 않습니다"}
    run_id = f"CV{now().replace('-', '').replace(':', '').replace('T', '-')[:15]}-{uuid.uuid4().hex[:6]}"
    rdir = project / ".ai-workflow/changes" / cid / "runs" / run_id
    rdir.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="pd-change-measure-"))
    server = None
    try:
        ok, why = _build_bundle(project, tmp, timeout)
        if not ok:
            return rec | {"status": "invalid", "reason": why, "run_id": run_id}
        server, port = _serve(tmp / "preview" / OUT_DIR)
        pages = [{"variant": state, "target": sid, "file": str(tmp / "preview" / OUT_DIR / MEASURE_ENTRY),
                  "url": f"http://127.0.0.1:{port}/{MEASURE_ENTRY}#{sid}/{state}", "elements": [], "layouts": []}
                 for sid in targets for state in (states[sid] or [""])]
        spec = {"format": MS.SPEC_FORMAT, "run_id": run_id, "round": cid, "phase": "change", "mode": "change", "method": sett["method"],
                "viewports": sett["viewports"], "checks": sett["checks"], "pages": pages, "report": str((rdir / MS.REPORT_NAME).resolve()),
                "screenshot_dir": "shots", "extensions": {}, "asset_fallback": False, "asset_block_pattern": None,
                "rules": ["변경 요청 영향 화면 검증: 화면 단독 렌더(data-target=화면 ID). 사실만 기록하고 판정은 엔진이 합니다."]}
        (rdir / MS.SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        env = dict(os.environ) | {"PD_RUN_ID": run_id, "PD_REPORT_DIR": str(rdir.resolve()), "PD_MEASURE_SPEC": str((rdir / MS.SPEC_NAME).resolve()),
                                  "PD_ROUND": cid}
        res, why = MS._run_cmd(sett["cmd"], project, env, sett["timeout_s"])
    finally:
        if server is not None:
            server.kill()
            server.wait()
        shutil.rmtree(tmp, ignore_errors=True)
    rp = rdir / MS.REPORT_NAME
    rec |= {"run_id": run_id, "report": str(rp.relative_to(project)), "cmd_sha256": MS.measure_fingerprint(project, sett["cmd"])["cmd_sha256"]}
    if res == "not_run":
        return rec | {"status": "not_run", "reason": why}
    if res == "timeout" or not rp.is_file():
        return rec | {"status": "invalid", "reason": why or "측정 명령이 리포트를 쓰지 않았습니다"}
    try:
        rep = parse(rp, run_id, rdir, spec, expected_images)
    except MS.ReportError as e:
        return rec | {"status": "invalid", "reason": f"리포트 형식 오류: {e}", "report_sha256": sha256_file(rp)}
    rec |= {"report_sha256": sha256_file(rp), "spec_sha256": sha256_file(rdir / MS.SPEC_NAME), "tool": rep.get("tool"), "browser": rep.get("browser")}
    if rep["status"] == "not_run":
        return rec | {"status": "not_run", "reason": rep["reason"]}
    if rep["invalid"]:
        return rec | {"status": "invalid", "reason": "측정 환경 불일치: " + "; ".join(rep["invalid"][:6]), "results": rep["results"]}
    blocking = sorted({f"{x['screen']}/{x['state']}@{x['viewport']}: {b}" for x in rep["results"] for b in x["blocking"]})
    warnings = sorted({f"{x['screen']}/{x['state']}@{x['viewport']}: {w}" for x in rep["results"] for w in x["warnings"]})
    return rec | {"status": "completed", "passed": not blocking, "blocking": blocking, "warnings": warnings[:40],
                  "results": rep["results"], "measured": len(rep["results"])}
