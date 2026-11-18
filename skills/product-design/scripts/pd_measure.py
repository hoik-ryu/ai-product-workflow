"""/product-design EX4: 디자인 탐색 시안의 브라우저 측정(`explore-verify`)과 선택 게이트(설계 §2.6·§2.7·§2.7.2).

원칙
- 엔진은 브라우저를 모릅니다. 프로젝트 측정 명령(`config.exploration.measure_cmd`)을 실행하고, 그 명령이 쓴
  `design-explore-report/v1`의 **형식과 사실**만 판정합니다. 측정 사실(상자·뷰포트·콘솔·적중 검사)은 어댑터가 기록하고,
  차단·경고 분류는 엔진이 합니다(어댑터가 차단 여부를 정하지 않음).
- `pb-ui-report/v1`(product-build)과 같은 필드(`viewport`·`rendered`·`console_errors`·`a11y`·`overflow`·`clipped`·
  `touch_target_violations`·`interactions`·`screenshot`·`run_id`)를 같은 분류로 판정합니다. 코드는 독립(Skill 간 import 없음).
- 확인 수준을 섞지 않습니다: 정적 검사 `checked`, 자동 측정 `measured`, 모델 시각 평가 `visually_reviewed: model`.
  모델 평가(critique.md)는 측정 기록에 들어가지 않고, 측정 결과도 모델 평가로 대신하지 않습니다.
- 측정 미실행(`not_run`: 명령·도구·환경 없음)과 측정 무효(`invalid`: 형식 오류·다른 실행·시간 초과·뷰포트 불일치)와
  측정된 결함(시안의 차단·경고)을 구분합니다.
- 측정 기록은 시안 파일 해시(`basis`)와 묶입니다. 측정 뒤 시안이 바뀌면 그 결과는 무효(`stale`)입니다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from pd_core import add_history, block, emit, now, require_state, save_state, sha256_file

REPORT_FORMAT = "design-explore-report/v1"
SPEC_FORMAT = "design-explore-measure-spec/v1"
REPORT_NAME = "report.json"
SPEC_NAME = "measure-spec.json"
METHODS = ("emulation", "iframe", "window")
DEFAULT_VIEWPORTS = [{"name": "mobile", "width": 390, "height": 844, "dpr": 2, "mobile": True},
                     {"name": "desktop", "width": 1280, "height": 800, "dpr": 1, "mobile": False}]
DEFAULT_CHECKS = {"touch_min_px": 44, "contrast_min": 4.5, "contrast_large_min": 3.0, "overlap_min_px": 4}
DEFAULT_TIMEOUT = 300
# 차단(선택 불가) — product-build 브라우저 판정과 같은 분류 + 구조 탐색에서 "선택 대상이 선언과 다르게 렌더링됨"
CRITICAL = ("render_failed", "console_errors", "a11y_critical", "interaction_failed", "layout_mismatch", "required_not_rendered",
            "required_unreachable", "component_inconsistent")
# 측정 환경 문제(시안 결함이 아님): 그 실행 전체가 무효
RUN_INVALID = ("viewport_mismatch", "screenshot_mismatch")
EXTENSION_KEYS = ("reference_compare",)  # EX5 예약: 레퍼런스 이미지와 렌더 결과 비교. 지금은 기록만 하고 판정하지 않음


class ReportError(Exception):
    pass


# ---------------------------------------------------------------- 공통
def _ex():
    import pd_explore as EX  # 순환 import 방지
    return EX


def measure_settings(st: dict) -> dict:
    cfg = _ex().exploration_config(st) or {}
    m = cfg.get("measure") if isinstance(cfg.get("measure"), dict) else {}
    return {"cmd": cfg.get("measure_cmd"), "method": m.get("method") or "emulation",
            "viewports": m.get("viewports") or DEFAULT_VIEWPORTS, "timeout_s": int(m.get("timeout_s") or DEFAULT_TIMEOUT),
            "checks": DEFAULT_CHECKS | {k: v for k, v in (m.get("checks") or {}).items() if k in DEFAULT_CHECKS}}


def measure_fingerprint(project: Path, cmd: str) -> dict:
    """측정 명령 지문(P1-5): 명령 문자열 SHA-256 + 명령 인자 중 프로젝트 안 파일(어댑터 스크립트 등)의 SHA-256.
    프로젝트 밖 실행 파일(python·node)과 그 스크립트가 불러오는 다른 파일은 지문에 들어가지 않습니다(한계)."""
    files = {}
    root = project.resolve()
    for tok in shlex.split(cmd):
        if tok.startswith("-"):
            continue
        try:
            q = (project / tok).resolve()
        except (OSError, ValueError):
            continue
        if (q == root or root in q.parents) and q.is_file():
            files[q.relative_to(root).as_posix()] = sha256_file(q)
    return {"cmd_sha256": hashlib.sha256(cmd.encode("utf-8")).hexdigest(), "files": files}


def measure_confirmation_problem(project: Path, st: dict) -> str | None:
    """현재 측정 명령이 사용자가 확인한 지문과 같은지. 같으면 None, 다르면 사유."""
    sett = measure_settings(st)
    if not sett["cmd"]:
        return None
    conf = (_ex().exploration_config(st) or {}).get("measure_confirmed")
    if not isinstance(conf, dict) or not conf.get("statement"):
        return "사용자 확인 지문이 없는 측정 명령입니다(이전 설정이거나 상태 파일에서 직접 바꿈)"
    fp = measure_fingerprint(project, sett["cmd"])
    if conf.get("cmd_sha256") != fp["cmd_sha256"]:
        return "측정 명령이 사용자 확인 이후 바뀌었습니다"
    changed = sorted(k for k in set(conf.get("files") or {}) | set(fp["files"]) if (conf.get("files") or {}).get(k) != fp["files"].get(k))
    if changed:
        return f"측정 스크립트 파일이 사용자 확인 이후 바뀌었습니다: {', '.join(changed)}"
    return None


def parse_viewports(spec: str) -> list[dict]:
    """"mobile=390x844@2,desktop=1280x800@1" → 뷰포트 목록. 이름이 mobile로 시작하면 모바일 에뮬레이션."""
    out = []
    for part in [p.strip() for p in (spec or "").split(",") if p.strip()]:
        m = re.fullmatch(r"([a-z][a-z0-9_-]{0,30})=(\d{2,5})x(\d{2,5})(?:@(\d(?:\.\d{1,2})?))?", part)
        if not m:
            block("invalid_arguments", f"--viewports 형식: mobile=390x844@2,desktop=1280x800@1 (받은 값 {part})")
        out.append({"name": m.group(1), "width": int(m.group(2)), "height": int(m.group(3)), "dpr": float(m.group(4) or 1),
                    "mobile": m.group(1).startswith("mobile")})
    if len({v["name"] for v in out}) != len(out):
        block("invalid_arguments", "뷰포트 이름이 중복됩니다.")
    return out


def variant_basis(project: Path, rid: str, lb: str, mr: dict) -> str:
    """측정 결과를 묶는 시안 기준: 렌더 산출물(plan.md 제외) 해시 + manifest의 시안 선언(요소·레이아웃) + 라운드 필수 항목."""
    EX = _ex()
    files = {k: h for k, h in EX._variant_files(project, rid, lb).items() if not k.endswith("/plan.md")}
    v = dict((mr.get("variants") or {}).get(lb) or {})
    for k in ("title", "concept", "plan"):
        v.pop(k, None)
    body = json.dumps({"files": files, "variant": v, "coverage": mr.get("coverage"), "targets": mr.get("targets")},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


def target_view(text: str, base_href: str, tid: str) -> str:
    """원본 시안은 그대로 두고 다른 대상 영역을 숨긴 파생 페이지(비교 페이지·측정 공용)."""
    inject = f'<base href="{base_href}"><style>[data-target]:not([data-target="{tid}"]){{display:none!important}}</style>'
    if re.search(r"<head[^>]*>", text, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + inject, text, count=1, flags=re.I)
    return inject + text


def _required(v: dict, phase: str = "structure") -> set[str]:
    """필수 요소: 1차는 필수 항목을 덮는(covers) 요소, 2차는 승인 구조의 모든 정보·행동 요소(장식 제외)."""
    if phase == "visual":
        return {e["id"] for e in v.get("elements") or [] if isinstance(e, dict) and e.get("kind") != "decoration" and e.get("id")}
    return {e["id"] for e in v.get("elements") or [] if isinstance(e, dict) and e.get("covers")}


def _core(v: dict, phase: str = "structure") -> set[str]:
    EX = _ex()
    return {e["id"] for e in v.get("elements") or [] if isinstance(e, dict) and e.get("id") in _required(v, phase) and e.get("kind") in EX.BACKED_INTERACTIVE_KINDS}


# ---------------------------------------------------------------- 측정 명세(엔진 → 어댑터)
def write_spec(project: Path, r: dict, mr: dict, run_id: str, rdir: Path, sett: dict, variants: list[str], fallback: bool = False) -> dict:
    EX = _ex()
    pages_dir = rdir / "pages"
    pages_dir.mkdir(parents=True)
    pages = []
    for lb in variants:
        v = (mr.get("variants") or {}).get(lb) or {}
        html_rel = (v.get("render") or {}).get("html")
        if not html_rel or EX.variant_path_problem(project, r["id"], lb, html_rel):  # 시안 폴더 밖 파일은 읽지 않음(경로 안전성)
            continue
        src = project / EX.EXPLORE_DIR / str(html_rel)
        if not src.is_file():
            continue
        text = src.read_text(encoding="utf-8")
        req, core = _required(v, r.get("phase", "structure")), _core(v, r.get("phase", "structure"))
        for t in r["targets"]:
            tid = t["id"]
            page = pages_dir / f"{lb}-{tid}.html"
            # 리포트 폴더(<라운드>/shots/<run>/pages/)에서 시안 폴더(<라운드>/<시안>/)로: ../../../<시안>/
            page.write_text(target_view(text, f"../../../{lb}/", tid), encoding="utf-8")
            els = [{"id": e["id"], "kind": e.get("kind"), "required": e["id"] in req, "core": e["id"] in core}
                   for e in v.get("elements") or [] if isinstance(e, dict) and e.get("target") == tid]
            lays = [x for x in (v.get("layouts") or []) if isinstance(x, dict) and x.get("target") == tid]
            pages.append({"variant": lb, "target": tid, "file": str(page.resolve()), "url": page.resolve().as_uri(),
                          "elements": els, "layouts": lays})
    spec = {"format": SPEC_FORMAT, "run_id": run_id, "round": r["id"], "phase": r.get("phase", "structure"), "mode": r.get("mode", "ai"),
            "method": sett["method"], "viewports": sett["viewports"], "checks": sett["checks"], "pages": pages,
            "report": str((rdir / REPORT_NAME).resolve()), "screenshot_dir": "shots",
            "extensions": {k: None for k in EXTENSION_KEYS},
            "asset_fallback": fallback, "asset_block_pattern": "*/_assets/*" if fallback else None,
            "rules": ["어댑터는 측정 사실만 기록합니다(상자·뷰포트·콘솔·적중 검사·스크린샷). 차단·경고 판정은 엔진이 합니다.",
                      "screenshot은 뷰포트 크기 캡처(전체 페이지 아님)이고 리포트 폴더 안 상대 경로입니다.",
                      "viewport_actual은 페이지 안에서 잰 innerWidth·innerHeight·devicePixelRatio입니다(요청값을 그대로 복사하지 않음).",
                      "레퍼런스 원본 이미지를 입력으로 받지 않으며 외부 서비스로 보내지 않습니다."]}
    (rdir / SPEC_NAME).write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec


# ---------------------------------------------------------------- 리포트 판정
def _int(v, field: str, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ReportError(f"{where}: {field}는 0 이상 정수여야 합니다")
    return v


def _num(v, field: str, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ReportError(f"{where}: {field}는 숫자여야 합니다")
    return float(v)


def _box(v, where: str) -> list[float]:
    if not isinstance(v, list) or len(v) != 4:
        raise ReportError(f"{where}: box는 [x, y, w, h]여야 합니다")
    return [_num(x, "box", where) for x in v]


def common_findings(r: dict, where: str) -> tuple[list[str], list[str], dict]:
    """pb-ui-report/v1과 같은 필드·같은 분류(차단: 렌더 실패·콘솔 오류·critical 접근성·핵심 상호작용 실패, 보고: 나머지)."""
    if not isinstance(r.get("rendered"), bool):
        raise ReportError(f"{where}: rendered(true/false)가 필요합니다. 스크린샷만으로는 측정 결과가 아닙니다")
    ce = r.get("console_errors")
    n_console = len(ce) if isinstance(ce, list) else _int(ce if ce is not None else 0, "console_errors", where)
    a11y = r.get("a11y")
    if a11y is not None and not isinstance(a11y, dict):
        raise ReportError(f"{where}: a11y는 심각도별 개수 객체여야 합니다")
    a11y = {k: _int(v, f"a11y.{k}", where) for k, v in a11y.items()} if a11y is not None else None
    ints = r.get("interactions") or []
    if not isinstance(ints, list):
        raise ReportError(f"{where}: interactions는 목록이어야 합니다")
    inter = []
    for j, x in enumerate(ints):
        if not isinstance(x, dict) or not isinstance(x.get("name"), str) or not isinstance(x.get("passed"), bool):
            raise ReportError(f"{where}.interactions[{j}]: name과 passed(true/false)가 필요합니다")
        inter.append({"name": x["name"], "element": x.get("element"), "passed": x["passed"], "core": x.get("core", True) is not False})
    blocking, warns = [], []
    if not r["rendered"]:
        blocking.append("render_failed")
    if n_console:
        blocking.append(f"console_errors:{n_console}")
    if a11y is None:
        warns.append("a11y_not_checked")
    else:
        if a11y.get("critical", 0):
            blocking.append(f"a11y_critical:{a11y['critical']}")
        if a11y.get("serious", 0):
            warns.append(f"a11y_serious:{a11y['serious']}")
    for x in inter:
        if not x["passed"]:
            (blocking if x["core"] else warns).append(f"interaction_failed:{x['name']}")
    if r.get("overflow") is True:
        warns.append("overflow")
    if r.get("clipped") is True:
        warns.append("clipped")
    if r.get("touch_target_violations"):
        warns.append(f"touch_target:{_int(r['touch_target_violations'], 'touch_target_violations', where)}")
    return blocking, warns, {"console_errors": n_console, "console_samples": [str(x)[:200] for x in ce[:5]] if isinstance(ce, list) else [],
                             "a11y": a11y, "a11y_tool": str(r.get("a11y_tool") or "")[:60] or None, "interactions": inter}


def _inter(a: list[float], b: list[float]) -> tuple[float, float]:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return (w, h) if w > 0 and h > 0 else (0.0, 0.0)


def columns_of(boxes: list[list[float]]) -> int:
    """문서 순서의 상자들을 같은 줄(위쪽 위치가 가까움)끼리 묶어 한 줄의 최대 개수(실제 열 수)를 셉니다."""
    rows: list[list[list[float]]] = []
    for b in boxes:
        if rows:
            first = rows[-1][0]
            tol = max(4.0, 0.25 * min(first[3], b[3]))
            if abs(b[1] - first[1]) <= tol and b[0] >= rows[-1][-1][0] + rows[-1][-1][2] - 1:
                rows[-1].append(b)
                continue
        rows.append([b])
    return max((len(x) for x in rows), default=0)


def layout_findings(lay: dict, page: dict, vp: dict, checks: dict, where: str) -> tuple[list[str], list[str], dict]:
    """어댑터가 잰 상자 사실 → 넘침·잘림·겹침·고정 요소 가림·도달 불가·선언 레이아웃 불일치·터치 영역·대비(엔진 판정)."""
    if not isinstance(lay, dict):
        raise ReportError(f"{where}: layout은 객체여야 합니다")
    sw = _num(lay.get("scroll_width"), "layout.scroll_width", where)
    cw = _num(lay.get("client_width"), "layout.client_width", where)
    vh = _num(lay.get("viewport_height", vp["height"]), "layout.viewport_height", where)
    els_raw = lay.get("elements")
    if not isinstance(els_raw, list):
        raise ReportError(f"{where}: layout.elements는 목록이어야 합니다")
    els = {}
    for i, e in enumerate(els_raw):
        w = f"{where}.layout.elements[{i}]"
        if not isinstance(e, dict) or not isinstance(e.get("id"), str):
            raise ReportError(f"{w}: id가 필요합니다")
        els[e["id"]] = {"id": e["id"], "box": _box(e.get("box"), w), "visible": e.get("visible") is True,
                        "reachable": e.get("reachable"), "in_fixed": e.get("in_fixed") is True, "contains_fixed": e.get("contains_fixed") is True,
                        "within": e.get("within") if isinstance(e.get("within"), str) else None, "contrast": e.get("contrast"),
                        "font_size": e.get("font_size"), "font_weight": e.get("font_weight")}
    fixed = []
    for i, f in enumerate(lay.get("fixed") or []):
        if not isinstance(f, dict):
            raise ReportError(f"{where}.layout.fixed[{i}]: 객체여야 합니다")
        fixed.append({"label": str(f.get("label") or f"fixed{i}")[:60], "box": _box(f.get("box"), f"{where}.layout.fixed[{i}]"),
                      "position": str(f.get("position") or "fixed")})
    B, W = [], []
    detail = {"columns": {}, "overlaps": [], "fixed_overlaps": [], "unreachable": [], "touch": [], "contrast": []}
    if sw > cw + 1:
        W.append(f"horizontal_scroll:{int(sw - cw)}px")
    req = {e["id"] for e in page["elements"] if e["required"]}
    for e in page["elements"]:
        m = els.get(e["id"])
        if m is None or not m["visible"] or m["box"][2] <= 0 or m["box"][3] <= 0:
            (B if e["required"] else W).append(f"{'required_not_rendered' if e['required'] else 'element_not_rendered'}:{e['id']}")
    vis = [m for m in els.values() if m["visible"] and m["box"][2] > 0 and m["box"][3] > 0]
    for m in vis:
        x, _, w, _ = m["box"]
        if not m["in_fixed"] and (x < -1 or x + w > cw + 1):
            W.append(f"clipped:{m['id']}")
    # 겹침: 서로 포함 관계가 아닌 요소끼리
    anc = {m["id"]: m["within"] for m in vis}

    def ancestors(i):
        out, cur = set(), anc.get(i)
        while cur and cur not in out:
            out.add(cur)
            cur = anc.get(cur)
        return out
    mn = float(checks.get("overlap_min_px", 4))
    for i, a in enumerate(vis):
        for b in vis[i + 1:]:
            if a["in_fixed"] or b["in_fixed"] or a["id"] in ancestors(b["id"]) or b["id"] in ancestors(a["id"]):
                continue
            w_, h_ = _inter(a["box"], b["box"])
            if w_ >= mn and h_ >= mn:
                detail["overlaps"].append([a["id"], b["id"], int(w_), int(h_)])
                W.append(f"overlap:{a['id']}+{b['id']}")
    # 고정·sticky 요소(하단 탭 등)가 첫 화면의 콘텐츠를 가림
    for m in vis:
        if m["in_fixed"] or m["contains_fixed"] or m["box"][1] >= vh:
            continue
        for f in fixed:
            w_, h_ = _inter(m["box"], f["box"])
            if w_ >= mn and h_ >= mn:
                detail["fixed_overlaps"].append([m["id"], f["label"], int(h_)])
                W.append(f"fixed_overlap:{m['id']}<{f['label']}")
    # 적중 검사(어댑터 사실): 어떤 스크롤 위치에서도 눌리거나 보이지 않는 요소
    for m in vis:
        if m["reachable"] is False:
            detail["unreachable"].append(m["id"])
            (B if m["id"] in req else W).append(f"{'required_unreachable' if m['id'] in req else 'unreachable'}:{m['id']}")
    # 선언한 열·격자 구조와 실제 배치
    for L in page.get("layouts") or []:
        if L.get("viewports") and vp["name"] not in L["viewports"]:
            continue
        ids = [i for i in L.get("elements") or [] if i in els and els[i]["visible"]]
        want = min(int(L.get("columns") or 1), len(ids)) if ids else int(L.get("columns") or 1)
        got = columns_of([els[i]["box"] for i in ids])
        detail["columns"][L.get("id")] = {"declared": int(L.get("columns") or 1), "actual": got, "elements": ids}
        if got != want:
            B.append(f"layout_mismatch:{L.get('id')}(선언 {L.get('columns')}열·실제 {got}열)")
    # 터치 영역(모바일 뷰포트)
    tmin = float(checks.get("touch_min_px", 44))
    for i, t in enumerate(lay.get("touch") or []):
        if isinstance(t, dict) and isinstance(t.get("w"), (int, float)) and isinstance(t.get("h"), (int, float)) and vp.get("mobile"):
            if min(t["w"], t["h"]) < tmin:
                detail["touch"].append([t.get("el") or t.get("label") or f"#{i}", int(t["w"]), int(t["h"])])
    if detail["touch"]:
        W.append(f"touch_target_small:{len(detail['touch'])}")
    # 주요 텍스트 대비
    for m in vis:
        c = m["contrast"]
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            size, weight = float(m["font_size"] or 16), float(m["font_weight"] or 400)
            large = size >= 24 or (size >= 18.66 and weight >= 700)
            need = float(checks["contrast_large_min" if large else "contrast_min"])
            if c < need:
                detail["contrast"].append([m["id"], round(float(c), 2), need])
                W.append(f"contrast_low:{m['id']}({round(float(c), 2)}<{need})")
    return B, W, detail


def parse_report(path: Path, run_id: str, report_dir: Path, spec: dict) -> dict:
    """design-explore-report/v1 → {status, reason, tool, results, invalid}. 형식이 틀리면 ReportError(리포트 전체를 믿지 않음)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ReportError(f"JSON 해석 실패: {e}")
    if not isinstance(data, dict) or data.get("format") != REPORT_FORMAT:
        raise ReportError(f"{REPORT_FORMAT} 형식이 아닙니다")
    if data.get("run_id") != run_id:
        raise ReportError("리포트의 run_id가 이번 실행(PD_RUN_ID)과 다릅니다(이전 실행 결과 재사용 의심)")
    tool = str(data.get("tool") or "")[:120]
    status = data.get("status", "completed")
    if status == "not_run":
        return {"status": "not_run", "reason": str(data.get("reason") or "측정 도구를 실행하지 못함")[:300], "tool": tool, "results": [], "invalid": []}
    if status != "completed":
        raise ReportError("status는 completed 또는 not_run이어야 합니다")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ReportError("results가 비어 있습니다(실행했다면 시안·대상·뷰포트별 결과가 있어야 함)")
    import pd_reference as RF
    pages = {(p["variant"], p["target"]): p for p in spec["pages"]}
    vps = {v["name"]: v for v in spec["viewports"]}
    rdir = report_dir.resolve()
    out, invalid, seen = [], [], set()
    for i, r in enumerate(results):
        where = f"results[{i}]"
        if not isinstance(r, dict):
            raise ReportError(f"{where}: 객체여야 합니다")
        key = (r.get("variant"), r.get("target"))
        if key not in pages:
            raise ReportError(f"{where}: variant·target {key}가 측정 명세에 없습니다")
        vp = vps.get(r.get("viewport"))
        if vp is None:
            raise ReportError(f"{where}: viewport는 측정 명세의 이름({', '.join(vps)}) 중 하나여야 합니다")
        if (key, vp["name"]) in seen:
            raise ReportError(f"{where}: 같은 시안·대상·뷰포트 결과가 중복됩니다")
        seen.add((key, vp["name"]))
        act = r.get("viewport_actual")
        if not isinstance(act, dict):
            raise ReportError(f"{where}: viewport_actual(width·height·dpr, 페이지 안에서 잰 값)이 필요합니다")
        actual = {"width": _num(act.get("width"), "viewport_actual.width", where), "height": _num(act.get("height"), "viewport_actual.height", where),
                  "dpr": _num(act.get("dpr"), "viewport_actual.dpr", where)}
        method = str(r.get("method") or "")[:20]
        if method not in METHODS:
            raise ReportError(f"{where}: method는 {'/'.join(METHODS)} 중 하나")
        B, W, info = common_findings(r, where)
        inv = []
        unknown = not r["rendered"] and actual["width"] == 0  # 측정 자체가 실패한 페이지: 렌더 실패로 판정(뷰포트 불일치 아님)
        if not unknown and ((actual["width"], actual["height"]) != (vp["width"], vp["height"]) or abs(actual["dpr"] - vp["dpr"]) > 0.01):
            inv.append(f"viewport_mismatch(요청 {vp['width']}×{vp['height']}@{vp['dpr']}, 실제 {actual['width']:g}×{actual['height']:g}@{actual['dpr']:g})")
        shot = r.get("screenshot")
        shot_rec = None
        if shot is not None:
            if not isinstance(shot, str) or shot.startswith("/") or ".." in Path(shot).parts:
                raise ReportError(f"{where}: screenshot은 리포트 폴더(PD_REPORT_DIR) 안 상대 경로여야 합니다")
            sp = (report_dir / shot).resolve()
            if not str(sp).startswith(str(rdir) + "/") or not sp.is_file():
                raise ReportError(f"{where}: screenshot 파일 {shot}이 이번 실행의 리포트 폴더에 없습니다")
            fmt, sw_, sh_ = RF.sniff(sp.read_bytes()[:4096])
            if fmt != "png":
                raise ReportError(f"{where}: screenshot은 PNG여야 합니다")
            want = (round(vp["width"] * vp["dpr"]), round(vp["height"] * vp["dpr"]))
            if (sw_, sh_) != want and not unknown:
                inv.append(f"screenshot_mismatch(기대 {want[0]}×{want[1]}px, 실제 {sw_}×{sh_}px)")
            shot_rec = {"path": shot, "sha256": sha256_file(sp), "width": sw_, "height": sh_}
        else:
            W.append("screenshot_missing")
        page = pages[key]
        # 핵심 상호작용은 엔진이 정함(필수 항목을 덮는 행동·이동·입력 요소). 어댑터가 core=false로 낮춰도 차단 판정
        core_ids = {e["id"] for e in page["elements"] if e["core"]}
        for x in info["interactions"]:
            if not x["passed"] and not x["core"] and x.get("element") in core_ids:
                W = [w for w in W if w != f"interaction_failed:{x['name']}"]
                B.append(f"interaction_failed:{x['name']}")
        detail = {}
        if r.get("layout") is not None:
            lB, lW, detail = layout_findings(r["layout"], page, vp, spec["checks"], where)
            B += lB
            W += [w for w in lW if not (w.startswith("horizontal_scroll") and "overflow" in W)]
            if detail.get("touch") is not None and any(w.startswith("touch_target:") for w in W):  # 같은 사실을 두 번 세지 않음(엔진 계산 우선)
                W = [w for w in W if not w.startswith("touch_target:")]
        else:
            W.append("layout_not_measured")
        comps = (r.get("layout") or {}).get("components") if isinstance(r.get("layout"), dict) else None
        if comps is not None and not isinstance(comps, list):
            raise ReportError(f"{where}: layout.components는 목록이어야 합니다")
        fill = None
        if isinstance(r.get("layout"), dict) and r["rendered"]:
            vh_ = float(r["layout"].get("viewport_height") or vp["height"])
            bots = [e["box"][1] + e["box"][3] for e in r["layout"].get("elements") or [] if isinstance(e, dict) and e.get("visible")
                    and not e.get("in_fixed") and not e.get("contains_fixed") and isinstance(e.get("box"), list) and len(e["box"]) == 4]
            fill = round(min(1.0, max(bots) / vh_), 3) if bots and vh_ else None
        ext = r.get("extensions") if isinstance(r.get("extensions"), dict) else {}
        out.append({"variant": key[0], "target": key[1], "viewport": vp["name"], "requested": {k: vp[k] for k in ("width", "height", "dpr")},
                    "actual": actual, "method": method, "rendered": r["rendered"], **info, "screenshot": shot_rec,
                    "blocking": B, "warnings": W, "invalid": inv, "detail": detail, "fill": fill,
                    "components": [c for c in (comps or []) if isinstance(c, dict)][:200], "layout": {"components": comps or []},
                    "extensions": {k: "recorded_not_judged" for k in ext if k in EXTENSION_KEYS}})
        invalid += [f"{key[0]}/{key[1]}@{vp['name']}: {x}" for x in inv]
    missing = [f"{p['variant']}/{p['target']}@{v}" for p in spec["pages"] for v in vps if ((p["variant"], p["target"]), v) not in seen]
    if missing:
        invalid.append("측정 명세의 결과가 빠졌습니다: " + ", ".join(missing[:10]))
    return {"status": "completed", "reason": None, "tool": tool, "browser": str(data.get("browser") or "")[:120], "results": out, "invalid": invalid}


# ---------------------------------------------------------------- explore-verify
def _run_cmd(cmd: str, project: Path, env: dict, timeout: int) -> tuple[str, str]:
    """→ (결과, 사유). 결과: ok | not_run(명령·도구 없음) | timeout | failed."""
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return "failed", f"측정 명령을 해석하지 못했습니다: {e}"
    if not argv or (shutil.which(argv[0]) is None and not (project / argv[0]).is_file()):
        return "not_run", f"측정 명령 {argv[0] if argv else ''}을 찾지 못했습니다(환경 없음)"
    try:
        p = subprocess.run(argv, cwd=project, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "timeout", f"측정 명령이 {timeout}초 안에 끝나지 않았습니다"
    except OSError as e:
        return "not_run", f"측정 명령을 실행하지 못했습니다: {e}"
    if p.returncode != 0:
        return "failed", f"측정 명령 종료 코드 {p.returncode}: {(p.stderr or p.stdout or '').strip()[-300:]}"
    return "ok", ""


def cmd_explore_verify(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    phase, r = EX._round(st, a.round)
    if not EX.exploration_enabled(st, phase):
        block("exploration_disabled", f"{phase} 탐색이 꺼져 있습니다.")
    sett = measure_settings(st)
    if a.method:
        sett["method"] = a.method
    if a.viewports:
        sett["viewports"] = parse_viewports(a.viewports)
    if a.timeout:
        sett["timeout_s"] = a.timeout
    fallback = bool(getattr(a, "asset_fallback", False))
    variants = [x.strip() for x in (a.variants or "").split(",") if x.strip()] or list(r["variants"])
    if any(x not in r["variants"] for x in variants):
        block("invalid_arguments", f"{r['id']}의 시안은 {', '.join(r['variants'])}입니다.")
    man = EX.load_manifest(project)
    mr = (man.get("rounds") or {}).get(r["id"])
    if not isinstance(mr, dict):
        block("invalid_manifest", f"manifest에 라운드 {r['id']}가 없습니다.")
    import pd_render as RD  # EX7: 브라우저로 잴 수 있는 렌더러(html·adapter 정적 HTML)만 측정
    skipped = [lb for lb in variants if RD.render_kind((mr.get("variants") or {}).get(lb) or {}) == "figma"]
    variants = [lb for lb in variants if lb not in skipped]
    if not variants:
        emit({"ok": True, "round": r["id"], "status": "not_run", "reason": "측정 가능한 시안이 없습니다(figma 렌더러는 브라우저 측정 불가)",
              "skipped": skipped, "level": "declared"})
    unconfirmed = measure_confirmation_problem(project, st)
    if unconfirmed:
        block("measure_cmd_unconfirmed", f"{unconfirmed}. 확인되지 않은 명령은 실행하지 않습니다. 명령과 스크립트를 사용자에게 보여 주고 "
              "explore-config --measure-cmd \"<명령>\" --confirm --note \"<사용자 문장>\"으로 다시 확인합니다(P1-5).")
    run_id = f"M{now().replace('-', '').replace(':', '').replace('T', '-')[:15]}-{uuid.uuid4().hex[:6]}"
    rec = {"run_id": run_id, "at": now(), "asset_fallback": fallback, "method": sett["method"], "viewports": sett["viewports"], "cmd": sett["cmd"], "variants_requested": variants,
           "status": None, "reason": None, "tool": None, "variants": {}}
    if not sett["cmd"]:
        rec |= {"status": "not_run", "reason": "측정 명령(config.exploration.measure_cmd)이 없습니다"}
    else:
        rdir = project / EX.round_rel(r["id"]) / "shots" / run_id
        rdir.mkdir(parents=True)
        spec = write_spec(project, r, mr, run_id, rdir, sett, variants, fallback)
        bases = {lb: variant_basis(project, r["id"], lb, mr) for lb in variants}
        env = dict(os.environ) | {"PD_RUN_ID": run_id, "PD_REPORT_DIR": str(rdir.resolve()), "PD_MEASURE_SPEC": str((rdir / SPEC_NAME).resolve()),
                                  "PD_ROUND": r["id"]}
        res, why = _run_cmd(sett["cmd"], project, env, sett["timeout_s"])
        rp = rdir / REPORT_NAME
        rec["report"] = str(rp.relative_to(project))
        if res == "not_run":
            rec |= {"status": "not_run", "reason": why}
        elif res == "timeout":
            rec |= {"status": "invalid", "reason": why}
        elif not rp.is_file():
            rec |= {"status": "invalid", "reason": why or "측정 명령이 리포트(report.json)를 쓰지 않았습니다"}
        else:
            try:
                rep = parse_report(rp, run_id, rdir, spec)
            except ReportError as e:
                rep = None
                rec |= {"status": "invalid", "reason": f"리포트 형식 오류: {e}"}
            if rep is not None:
                rec["report_sha256"] = sha256_file(rp)
                conf = (EX.exploration_config(st) or {}).get("measure_confirmed") or {}
                rec["provenance"] = {"cmd_sha256": conf.get("cmd_sha256"), "files": conf.get("files"), "confirmed_at": conf.get("at"),
                                     "report_sha256": rec["report_sha256"], "spec_sha256": sha256_file(rdir / SPEC_NAME)}
                rec["tool"] = rep["tool"]
                if rep["status"] == "not_run":
                    rec |= {"status": "not_run", "reason": rep["reason"]}
                elif rep["invalid"]:
                    rec |= {"status": "invalid", "reason": "측정 환경 불일치: " + "; ".join(rep["invalid"][:6])}
                else:
                    rec["status"] = "completed"
                rec["browser"] = rep.get("browser")
                for lb in variants:
                    rs = [x for x in rep["results"] if x["variant"] == lb]
                    cB = []
                    if r.get("phase") == "visual":  # EX5: 같은 시안의 화면·인스턴스 간 같은 컴포넌트 스타일
                        import pd_visual as VS
                        cB, _ = VS.component_findings(rs)
                    rec["variants"][lb] = {
                        "basis": bases[lb], "blocking": sorted({f"{x['target']}@{x['viewport']}: {b}" for x in rs for b in x["blocking"]}) + [f"컴포넌트 일관성 @{x}" for x in cB],
                        "warnings": sorted({f"{x['target']}@{x['viewport']}: {w}" for x in rs for w in x["warnings"]}),
                        "results": [{k: x[k] for k in ("target", "viewport", "requested", "actual", "method", "rendered", "console_errors", "console_samples",
                                                        "a11y", "a11y_tool", "screenshot", "blocking", "warnings", "invalid", "detail", "extensions", "components", "fill")}
                                    for x in rs]}
                if rec["status"] == "completed":
                    write_summary(rdir, r, rec)
    ms = r.setdefault("measurements", [])
    ms.append(rec)
    add_history(st, EX.PHASE_STAGE[phase], "exploration_measured", st["stages"][EX.PHASE_STAGE[phase]]["revision"],
                f"{r['id']} {run_id}: {rec['status']}" + (f" ({rec['reason'][:100]})" if rec.get("reason") else ""))
    save_state(project, st)
    out = {"ok": rec["status"] != "invalid", "round": r["id"], "run_id": run_id, "status": rec["status"], "reason": rec.get("reason"), "asset_fallback": fallback,
           "skipped_renderer": {lb: "figma(측정 불가, declared)" for lb in skipped},
           "method": rec["method"], "viewports": [f"{v['name']} {v['width']}×{v['height']}@{v['dpr']}" for v in rec["viewports"]],
           "variants": {lb: {"blocking": v["blocking"], "warnings": v["warnings"][:20],
                             "measurement_blocks_choice": bool(v["blocking"]) if rec["status"] == "completed" else None}
                        for lb, v in rec["variants"].items()},
           "report": rec.get("report"), "level": "measured",
           "note": "자동 측정 결과입니다(measured). 시각 품질 평가(visually_reviewed: model)와 사용자 선택을 대신하지 않습니다."}
    if rec["status"] == "not_run":
        out["next"] = "측정 미실행: 경고 후 선택할 수 있습니다(D3). 사람이 확인한 화면 캡처를 --evidence로 남깁니다."
    elif rec["status"] == "invalid":
        out["next"] = "측정이 무효입니다. 원인을 고쳐 다시 측정하거나, 측정 없이 진행할지 사용자에게 확인합니다(--measurement-waiver \"<사용자 문장>\")."
    else:
        out["next"] = "critique.md에 측정 스크린샷을 근거로 시각 평가를 쓰고(근거 스크린샷 항목), 비교 페이지를 사용자에게 보여 줍니다."
    emit(out, 0 if rec["status"] != "invalid" else 2)


def write_summary(rdir: Path, r: dict, rec: dict) -> None:
    """엔진 판정 요약(측정 사실과 판정, measured). 모델 평가가 아닙니다."""
    lines = [f"# {r['id']} 측정 요약 ({rec['run_id']}) — 엔진 판정(measured), 모델 평가 아님", "",
             f"- 방식: {rec['method']} · 도구: {rec.get('tool') or '-'} · 브라우저: {rec.get('browser') or '-'}",
             f"- 뷰포트: " + ", ".join(f"{v['name']} {v['width']}×{v['height']}@{v['dpr']}" for v in rec["viewports"]), ""]
    for lb, v in rec["variants"].items():
        lines.append(f"## {r['id']}-{lb}: {'차단 ' + str(len(v['blocking'])) + '건' if v['blocking'] else '차단 없음'} · 경고 {len(v['warnings'])}건")
        for x in v["results"]:
            a = x["actual"]
            lines.append(f"- {x['target']}@{x['viewport']} 실제 {a['width']:g}×{a['height']:g}@{a['dpr']:g} · 스크린샷 {x['screenshot']['path'] if x['screenshot'] else '없음'}"
                         + (f" · 차단: {', '.join(x['blocking'])}" if x["blocking"] else "") + (f" · 경고: {', '.join(x['warnings'][:8])}" if x["warnings"] else ""))
        lines.append("")
    (rdir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 선택 게이트(D3)
def variant_measurement(project: Path, st: dict, r: dict, lb: str, mr: dict | None = None) -> dict:
    """시안의 측정 상태: not_run | pending | invalid | stale | blocked | passed."""
    sett = measure_settings(st)
    if mr is None:
        mr = (_ex().load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    import pd_render as RD
    if RD.render_kind((mr.get("variants") or {}).get(lb) or {}) == "figma":  # EX7: 브라우저 DOM이 없는 렌더러
        return {"status": "not_run", "reason": "figma 렌더러: 브라우저 측정 불가(선언 검사 declared, 렌더러 스크린샷이 증거)", "renderer": "figma"}
    runs = [x for x in r.get("measurements") or [] if lb in x.get("variants_requested", r["variants"]) and not x.get("asset_fallback")]
    last = runs[-1] if runs else None
    if last is None:
        return {"status": "pending" if sett["cmd"] else "not_run",
                "reason": "측정 명령이 있지만 이 시안을 아직 측정하지 않았습니다(explore-verify)" if sett["cmd"] else "측정 명령 없음(measure_cmd)"}
    base = {"run_id": last["run_id"], "at": last["at"]}
    if sett["cmd"] and last["status"] != "not_run":  # P1-5: 확인된 명령이 실행한 결과만 근거
        why = measure_confirmation_problem(project, st)
        prov = last.get("provenance") or {}
        conf = (_ex().exploration_config(st) or {}).get("measure_confirmed") or {}
        if why:
            return base | {"status": "pending", "reason": f"{why}. 재확인 후 다시 측정합니다(measure_cmd_unconfirmed)"}
        if last["status"] == "completed" and (prov.get("cmd_sha256") != conf.get("cmd_sha256") or prov.get("files") != conf.get("files")):
            return base | {"status": "pending", "reason": "이 측정은 지금 확인된 측정 명령으로 실행한 결과가 아닙니다(실행 출처 기록 없음 또는 다름). 다시 측정합니다"}
    if last["status"] == "not_run":
        if sett["cmd"] and last.get("cmd") != sett["cmd"]:  # 명령이 없던(또는 다른) 때의 미실행 기록은 지금 설정에 대한 답이 아님
            return base | {"status": "pending", "reason": "측정 명령이 바뀐 뒤 이 시안을 아직 측정하지 않았습니다(explore-verify)"}
        return base | {"status": "not_run", "reason": last.get("reason")}
    if last["status"] == "invalid":
        return base | {"status": "invalid", "reason": last.get("reason")}
    v = (last.get("variants") or {}).get(lb)
    if not v:
        return base | {"status": "invalid", "reason": "최근 측정 결과에 이 시안이 없습니다"}
    if mr is None:
        mr = (_ex().load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    if variant_basis(project, r["id"], lb, mr) != v["basis"]:
        return base | {"status": "stale", "reason": "측정 이후 시안 파일이나 선언(요소·레이아웃)이 바뀌었습니다. 다시 측정합니다"}
    if v["blocking"]:
        return base | {"status": "blocked", "blocking": v["blocking"], "warnings": v["warnings"]}
    return base | {"status": "passed", "warnings": v["warnings"], "results": v["results"], "report_sha256": last.get("report_sha256"),
                   "report": last.get("report")}


def choice_measurement(project: Path, st: dict, r: dict, chosen: list[str], sel: dict, waiver: str) -> dict:
    """explore-choose의 측정 게이트. 차단 결과가 있는 시안은 거부(문장으로도 우회 불가). 무효·오래됨·미측정은 재측정 또는 사용자 문장."""
    mr = (_ex().load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    states = {lb: variant_measurement(project, st, r, lb, mr) for lb in chosen}
    blocked = {lb: s["blocking"] for lb, s in states.items() if s["status"] == "blocked"}
    if blocked:
        block("variant_has_blocking_findings", "측정에서 차단 결과(렌더 실패·콘솔 오류·critical 접근성·핵심 상호작용 실패·선언과 다른 배치·필수 요소 미표시)가 확인된 시안은 선택할 수 없습니다. "
              "시안을 고쳐 다시 측정하거나 다른 시안을 고릅니다(D3).", findings={lb: b[:12] for lb, b in blocked.items()},
              other_variants={lb: variant_measurement(project, st, r, lb, mr)["status"] for lb in r["variants"] if lb not in chosen})
    odd = {lb: s for lb, s in states.items() if s["status"] in ("invalid", "stale", "pending")}
    if odd and not waiver:
        code = "measurement_stale" if any(s["status"] == "stale" for s in odd.values()) else (
            "measurement_pending" if all(s["status"] == "pending" for s in odd.values()) else "measurement_invalid")
        block(code, "측정 결과를 쓸 수 없습니다(무효·측정 이후 변경·미측정). 다시 측정(explore-verify)하거나, 측정 없이 진행할지 사용자에게 확인해 "
              "--measurement-waiver \"<사용자 문장>\"으로 기록합니다. 측정 무효를 숨기지 않습니다.", states={lb: {k: s.get(k) for k in ("status", "reason", "run_id")} for lb, s in odd.items()})
    status = "passed" if all(s["status"] == "passed" for s in states.values()) else ("waived" if odd else "not_run")
    warnings = []
    for lb, s in states.items():
        if s["status"] == "not_run":
            warnings.append(f"{r['id']}-{lb}: 브라우저 측정 미실행(measurement_not_run): 경고 후 선택을 허용합니다(D3). {s.get('reason') or ''}".strip())
        elif s["status"] in ("invalid", "stale", "pending"):
            warnings.append(f"{r['id']}-{lb}: 측정 {s['status']} — 사용자 문장으로 측정 없이 진행(measurement_waived): {waiver[:80]}")
        elif s.get("warnings"):
            warnings.append(f"{r['id']}-{lb}: 측정 보고 {len(s['warnings'])}건(선택 허용·기록): " + "; ".join(s["warnings"][:5]))
    # 측정 스크린샷 = 핵심 시각 증거(선택한 대상 × 뷰포트). 파일이 지워졌거나 바뀌었으면 쓰지 않음
    evidence, ev_missing = [], []
    if status == "passed":
        for tid, lb in sel.items():
            for x in states[lb]["results"]:
                if x["target"] != tid or not x.get("screenshot"):
                    continue
                p = project / _ex().round_rel(r["id"]) / "shots" / states[lb]["run_id"] / x["screenshot"]["path"]
                if p.is_file() and sha256_file(p) == x["screenshot"]["sha256"]:
                    evidence.append({"file": p, "variant": lb, "target": tid, "viewport": x["viewport"], "sha256": x["screenshot"]["sha256"]})
                else:
                    ev_missing.append(str(p.relative_to(project)))
    detail = {"status": status, "waiver": waiver or None,
              "variants": {lb: {k: s.get(k) for k in ("status", "run_id", "at", "reason", "warnings", "report", "report_sha256")} for lb, s in states.items()},
              "level": "measured" if status == "passed" else None}
    return {"status": status, "warnings": warnings, "evidence": evidence, "evidence_missing": ev_missing, "detail": detail, "states": states}


_SHOT_RE = re.compile(r"shots/(M[0-9A-Za-z-]+)/(shots/[^\s)`'\"]+\.png)")


def critique_screenshot_gaps(project: Path, r: dict, labels: list[str]) -> list[str]:
    """측정이 완료된 시안의 모델 평가는 실제 측정 스크린샷을 근거로 씁니다(`- **근거 스크린샷**: shots/<run>/shots/<파일>`)."""
    EX = _ex()
    path = project / EX.round_rel(r["id"]) / "critique.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    shots = {}
    for run in r.get("measurements") or []:
        for lb, v in (run.get("variants") or {}).items():
            for x in v.get("results") or []:
                if x.get("screenshot"):
                    shots.setdefault(lb, set()).add((run["run_id"], x["screenshot"]["path"]))
    gaps = []
    for lb in labels:
        if lb not in shots:
            continue
        m = re.search(rf"^##[ \t]+{re.escape(r['id'])}-{lb}[ \t]*$(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
        val = EX.critique_fields(m.group(1)).get("근거 스크린샷", "") if m else ""
        cited = set(_SHOT_RE.findall(val))
        if not cited & shots[lb]:
            gaps.append(f"{r['id']}-{lb}")
    return gaps


def round_measure_summary(project: Path, st: dict, r: dict) -> dict:
    mr = (_ex().load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    return {lb: {k: v for k, v in variant_measurement(project, st, r, lb, mr).items() if k in ("status", "run_id", "reason", "blocking")}
            for lb in r["variants"]}


def check_layouts(v: dict, tids: list[str], tag: str) -> list[str]:
    """manifest 시안의 레이아웃 선언(`layouts`) 형식: 측정이 실제 배치와 대조할 기준(정적 검사)."""
    lays = v.get("layouts")
    if lays is None:
        return []
    if not isinstance(lays, list):
        return [f"{tag}: layouts는 목록이어야 합니다(layout_invalid)"]
    E, ids = [], set()
    decl = {e.get("id"): e for e in v.get("elements") or [] if isinstance(e, dict)}
    for i, L in enumerate(lays):
        w = f"{tag}: layouts[{i}]"
        if not isinstance(L, dict) or not isinstance(L.get("id"), str) or not L["id"]:
            E.append(f"{w}에 id가 필요합니다(layout_invalid)")
            continue
        if L["id"] in ids:
            E.append(f"{w}: id {L['id']} 중복(layout_invalid)")
        ids.add(L["id"])
        if L.get("target") not in tids:
            E.append(f"{w}: target {L.get('target')}이 라운드 대상이 아닙니다(layout_invalid)")
        c = L.get("columns")
        if isinstance(c, bool) or not isinstance(c, int) or not 1 <= c <= 12:
            E.append(f"{w}: columns는 1–12 정수(layout_invalid)")
        els = L.get("elements")
        if not isinstance(els, list) or len(els) < 2:
            E.append(f"{w}: elements는 요소 id 2개 이상(layout_invalid)")
            continue
        for x in els:
            if x not in decl:
                E.append(f"{w}: 요소 {x}가 manifest에 없습니다(layout_invalid)")
            elif decl[x].get("target") != L.get("target"):
                E.append(f"{w}: 요소 {x}는 {L.get('target')}의 요소가 아닙니다(layout_invalid)")
        vps = L.get("viewports")
        if vps is not None and (not isinstance(vps, list) or not all(isinstance(x, str) for x in vps)):
            E.append(f"{w}: viewports는 뷰포트 이름 목록(layout_invalid)")
    return E


def cmd_measure_config(st: dict, a, project: Path) -> list[str]:
    """explore-config --measure-cmd / --measure-method: 측정 설정(사용자 문장 필요, 승인과 무관)."""
    cfg = st["config"]["exploration"]
    changes = []
    if a.measure_cmd is not None:
        cmd = a.measure_cmd.strip() or None
        if cmd:
            try:
                shlex.split(cmd)
            except ValueError as e:
                block("invalid_arguments", f"측정 명령을 해석하지 못했습니다: {e}")
        if cfg.get("measure_cmd") != cmd:
            cfg["measure_cmd"] = cmd
            changes.append(f"config.exploration.measure_cmd = {cmd!r}")
        if cmd:
            fp = measure_fingerprint(project, cmd)
            old = cfg.get("measure_confirmed") or {}
            if not old.get("statement") or {k: old.get(k) for k in fp} != fp:
                cfg["measure_confirmed"] = fp  # 확인 문장·시각은 --confirm 때 기록
                changes.append("측정 명령 지문 확인: 명령 SHA-256 " + fp["cmd_sha256"][:12] + "…, 프로젝트 안 파일 "
                               + (", ".join(f"{k}={v[:8]}…" for k, v in fp["files"].items()) or "없음"))
        else:
            if cfg.pop("measure_confirmed", None) is not None:
                changes.append("측정 명령 지문 기록 제거")
    if a.measure_method:
        m = cfg.setdefault("measure", {})
        if m.get("method") != a.measure_method:
            m["method"] = a.measure_method
            changes.append(f"config.exploration.measure.method = {a.measure_method}")
    if a.measure_viewports:
        m = cfg.setdefault("measure", {})
        vps = parse_viewports(a.measure_viewports)
        if m.get("viewports") != vps:
            m["viewports"] = vps
            changes.append("config.exploration.measure.viewports = " + ", ".join(f"{v['name']} {v['width']}×{v['height']}@{v['dpr']}" for v in vps))
    return changes


def fallback_state(project: Path, st: dict, r: dict, lb: str) -> str:
    """자산 없이(대체 표시) 측정한 최근 결과: none | passed | failed | stale."""
    runs = [x for x in r.get("measurements") or [] if x.get("asset_fallback") and lb in (x.get("variants") or {})]
    if not runs:
        return "none"
    last = runs[-1]
    v = last["variants"][lb]
    mr = (_ex().load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    if variant_basis(project, r["id"], lb, mr) != v["basis"]:
        return "stale"
    return "passed" if last["status"] == "completed" and not v["blocking"] else "failed"
