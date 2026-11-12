"""/product-build M3.3·M3.4: 화면 상태 증거, 수동 증거(EM), 브라우저 검증 리포트(pb-ui-report/v1) 판정.

원칙
- 기존 M2 증거 체계(verify의 실행·리포트 출처 검증·AC 판정·무효화)를 그대로 씁니다. 여기서는 그 실행 결과에서
  화면 상태(02의 `SCR-xxx-STn`) 증거를 판정하고, 브라우저 리포트를 실행 케이스로 바꿔 넣을 뿐입니다.
- 상태 태그는 AC 태그와 같은 규칙입니다: 테스트 이름의 `[SCR-001-ST2]`, pb-json `states` 필드, JUnit property `state(s)`.
- E2: 유효한 실행에서 그 상태로 태그된 테스트(또는 브라우저 결과)가 통과. 스크린샷만 있는 결과는 증거가 아닙니다.
- EM(수동 증거)은 테스트 실행 증거와 따로 기록합니다. 필수 상태의 E2를 대신하지 않습니다(표시만).
- 엔진은 브라우저 도구를 모릅니다. 프로젝트 명령이 낸 리포트 형식과 판정만 다룹니다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pb_core import TRACE_FILE, digest, read_text, screen_info, sha_file, strip_fences, table_rows

UI_REPORT_FORMAT = "pb-ui-report/v1"
UI_EVIDENCE_FORMAT = "pb-ui-evidence/v1"
STATE_ID = re.compile(r"\bSCR-\d{3}-ST\d+\b")
STATE_BRACKET = re.compile(r"\[\s*(SCR-\d{3}-ST\d+(?:\s*[,/]\s*SCR-\d{3}-ST\d+)*)\s*\]")
PREFIX_HEAD = re.compile(r"[A-Z]{2,4}-\d{3}(?:[A-Z0-9\-·→/,\s])*")
SHOT_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
EM_METHODS = ("keyboard", "screen_reader", "visual", "device", "exploratory", "other")
EM_RESULTS = ("passed", "failed")
REQUIRED_TARGET = "E2"


class UIReportError(Exception):
    pass


# ---------------------------------------------------------------- 상태 태그
def state_tags(name: str, explicit, style) -> list[str]:
    out = {s for s in (explicit or []) if isinstance(s, str) and STATE_ID.fullmatch(s)}
    for m in STATE_BRACKET.finditer(name or ""):
        out |= set(STATE_ID.findall(m.group(1)))
    styles = list(style) if isinstance(style, (list, tuple)) else [style or "bracket"]
    if "prefix" in styles:  # "SCR-001-ST2 / AC-001: …" 머리
        head, sep, _ = (name or "").split(" > ")[-1].partition(":")
        if sep and PREFIX_HEAD.fullmatch(head.strip()):
            out |= set(STATE_ID.findall(head))
    return sorted(out)


def state_mentions(project: Path, test_files: list[str]) -> set[str]:
    out = set()
    for f in test_files:
        try:
            out |= set(STATE_ID.findall((project / f).read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- 브라우저 리포트(M3.4)
def _int(v, field: str, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise UIReportError(f"{where}: {field}는 0 이상 정수여야 합니다")
    return v


def parse_ui_report(path: Path, run_id: str, report_dir: Path) -> dict:
    """pb-ui-report/v1 → {status, reason, tool, results, cases}. 형식이 틀리면 UIReportError(리포트 전체를 믿지 않음)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise UIReportError(f"JSON 해석 실패: {e}")
    if not isinstance(data, dict) or data.get("format") != UI_REPORT_FORMAT:
        raise UIReportError(f"{UI_REPORT_FORMAT} 형식이 아닙니다")
    if data.get("run_id") != run_id:
        raise UIReportError("리포트의 run_id가 이번 실행(PB_RUN_ID)과 다릅니다(이전 실행 결과 재사용 의심)")
    status = data.get("status", "completed")
    tool = str(data.get("tool") or "")[:120]
    if status == "not_run":
        return {"status": "not_run", "reason": str(data.get("reason") or "브라우저 검증 도구를 실행하지 못함")[:300], "tool": tool,
                "results": [], "cases": []}
    if status != "completed":
        raise UIReportError("status는 completed 또는 not_run이어야 합니다")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise UIReportError("results가 비어 있습니다(실행했다면 화면별 결과가 있어야 함)")
    rdir = report_dir.resolve()
    out_results, cases = [], []
    for i, r in enumerate(results):
        where = f"results[{i}]"
        if not isinstance(r, dict):
            raise UIReportError(f"{where}: 객체여야 합니다")
        scr = r.get("screen")
        if not isinstance(scr, str) or not re.fullmatch(r"SCR-\d{3}", scr):
            raise UIReportError(f"{where}: screen은 SCR-### 이어야 합니다")
        state = r.get("state")
        if state is not None and (not isinstance(state, str) or not STATE_ID.fullmatch(state) or not state.startswith(scr + "-")):
            raise UIReportError(f"{where}: state는 {scr}-STn 형식이어야 합니다")
        vp = r.get("viewport")
        if not isinstance(vp, str) or not vp.strip():
            raise UIReportError(f"{where}: viewport 이름이 필요합니다")
        if not isinstance(r.get("rendered"), bool):
            raise UIReportError(f"{where}: rendered(true/false)가 필요합니다. 스크린샷만으로는 검증 결과가 아닙니다")
        ce = r.get("console_errors")
        n_console = len(ce) if isinstance(ce, list) else _int(ce, "console_errors", where)
        a11y = r.get("a11y")
        if a11y is not None and not isinstance(a11y, dict):
            raise UIReportError(f"{where}: a11y는 심각도별 개수 객체여야 합니다")
        a11y = {k: _int(v, f"a11y.{k}", where) for k, v in (a11y or {}).items()} if a11y is not None else None
        ints = r.get("interactions") or []
        if not isinstance(ints, list):
            raise UIReportError(f"{where}: interactions는 목록이어야 합니다")
        inter = []
        for j, x in enumerate(ints):
            if not isinstance(x, dict) or not isinstance(x.get("name"), str) or not isinstance(x.get("passed"), bool):
                raise UIReportError(f"{where}.interactions[{j}]: name과 passed(true/false)가 필요합니다")
            inter.append({"name": x["name"], "passed": x["passed"], "core": x.get("core", True) is not False,
                          "acs": [a for a in (x.get("acs") or []) if isinstance(a, str) and re.fullmatch(r"AC-\d{3}", a)]})
        shot = r.get("screenshot")
        shot_rec = None
        if shot is not None:
            if not isinstance(shot, str) or shot.startswith("/") or ".." in Path(shot).parts:
                raise UIReportError(f"{where}: screenshot은 리포트 폴더(PB_REPORT_DIR) 안 상대 경로여야 합니다")
            sp = (report_dir / shot).resolve()
            if not str(sp).startswith(str(rdir) + "/") or not sp.is_file():
                raise UIReportError(f"{where}: screenshot 파일 {shot}이 이번 실행의 리포트 폴더에 없습니다")
            shot_rec = {"path": shot, "sha256": sha_file(sp)}
        acs = sorted({a for a in (r.get("acs") or []) if isinstance(a, str) and re.fullmatch(r"AC-\d{3}", a)} | {a for x in inter for a in x["acs"]})
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
        rec = {"screen": scr, "state": state, "viewport": vp, "rendered": r["rendered"], "console_errors": n_console, "a11y": a11y,
               "interactions": inter, "acs": acs, "screenshot": shot_rec, "blocking": blocking, "warnings": warns}
        out_results.append(rec)
        cases.append({"id": f"ui::{state or scr}::{vp}", "name": f"[{state or scr}] {vp}", "file": None,
                      "status": "failed" if blocking else "passed", "acs": acs, "states": [state] if state else [], "mentions": [],
                      "ui": {"screen": scr, "viewport": vp, "blocking": blocking, "warnings": warns}})
    worst = {"failed": 1, "passed": 0}
    merged: dict[str, dict] = {}
    for c in cases:  # 같은 화면·상태·뷰포트가 여러 번이면 가장 나쁜 결과
        if c["id"] not in merged or worst[c["status"]] > worst[merged[c["id"]]["status"]]:
            merged[c["id"]] = c
    return {"status": "completed", "reason": None, "tool": tool, "base_url": str(data.get("base_url") or "")[:200],
            "results": out_results, "cases": list(merged.values())}


def is_ui_step(step: dict) -> bool:
    return ((step.get("report") or {}).get("format")) == "pb-ui"


def browser_summary(run: dict, prof_steps: list[dict], brief: dict, viewports: list) -> dict:
    """브라우저 단계 판정: 차단(렌더 실패·콘솔 오류·critical 접근성·핵심 상호작용 실패), 보고, 미실행."""
    ui_steps = {s["name"]: s for s in prof_steps if is_ui_step(s)}
    steps, blocking, warnings, results, blockers = {}, [], [], [], []
    vp_names = {v if isinstance(v, str) else (v or {}).get("name") for v in (viewports or [])} - {None}
    actions = {s: {a["action"] for a in sb["actions"]} for s, sb in brief["screens"].items()}
    defined = {x["id"] for sb in brief["screens"].values() for x in sb["states"] if x["defined"]}
    for s in run["steps"]:
        if s["name"] not in ui_steps:
            continue
        req = not s.get("optional")
        steps[s["name"]] = {"status": s["status"], "required": req, "reason": s.get("reason"), "tool": (s.get("ui_report") or {}).get("tool")}
        if s["status"] == "not_run":
            (blockers if req else warnings).append(f"브라우저 단계 {s['name']} 미실행(not_run): {s.get('reason')}")
            continue
        if s["status"] in ("report_invalid", "report_empty", "inconsistent", "timeout"):
            blocking.append(f"브라우저 단계 {s['name']}: {s['status']} ({s.get('reason')})")
            continue
        for r in (s.get("ui_report") or {}).get("results", []):
            results.append({"step": s["name"], **{k: r[k] for k in ("screen", "state", "viewport", "blocking", "warnings", "acs", "screenshot")}})
            tag = f"{r['state'] or r['screen']}@{r['viewport']}"
            if r["screen"] not in brief["screens"]:
                warnings.append(f"{tag}: 이 배치가 소유한 화면이 아닙니다(증거로 쓰지 않음)")
            if r["state"] and r["state"] not in defined:
                warnings.append(f"{tag}: 02 문서에 정의된 상태가 아닙니다")
            if vp_names and r["viewport"] not in vp_names:
                warnings.append(f"{tag}: 프로필 browser.viewports에 없는 뷰포트입니다")
            for x in r["interactions"]:
                if not x["core"] and x["name"] in actions.get(r["screen"], set()):
                    blocking.append(f"{tag}: 02 행동 '{x['name']}'은 핵심 상호작용입니다(core=false로 낮출 수 없음)"
                                    + (" — 실패" if not x["passed"] else ""))
            if r["blocking"]:
                blocking.append(f"{tag}: " + ", ".join(r["blocking"]))
            for w in r["warnings"]:
                warnings.append(f"{tag}: {w}")
    if not ui_steps:
        status = "not_configured"
        warnings.append("프로필에 브라우저 검증 단계(report.format = \"pb-ui\")가 없습니다")
    elif blocking:
        status = "failed"
    elif any(v["status"] == "not_run" and v["required"] for v in steps.values()):
        status = "browser_pending"  # 필수 브라우저 검증 미실행: verify는 끝낼 수 있지만 최종 UI 승인은 차단
    elif any(v["status"] == "not_run" for v in steps.values()):
        status = "not_run"
    else:
        status = "passed"
    covered = {r["state"] for r in results if r["state"] and not r["blocking"]}
    required = sorted(x["id"] for sb in brief["screens"].values() for x in sb["states"] if x["required"])
    return {"status": status, "steps": steps, "blocking": blocking, "warnings": warnings, "results": results,
            "final_approval_blockers": blockers,
            "coverage": {"required_states": len(required), "with_browser_pass": sorted(set(required) & covered),
                         "without_browser": sorted(set(required) - covered)}}


# ---------------------------------------------------------------- 상태 증거 판정(M3.3)
def evaluate_states(brief: dict, run: dict, mentioned: set[str], manual: list[dict]) -> dict:
    """정의된 상태별: verified / insufficient / failing / not_run / untested / manual_only / invalid_run."""
    steps = run["steps"]
    not_run = [s["name"] for s in steps if s["status"] == "not_run" and not s.get("optional")]
    broken = [s["name"] for s in steps if s["status"] in ("report_invalid", "report_empty", "inconsistent", "timeout") and not s.get("optional")]
    cases = [(s["name"], c) for s in steps for c in s.get("cases", [])]
    out = {}
    for sid, sb in brief["screens"].items():
        for x in sb["states"]:
            if not x["defined"]:
                continue
            st = x["id"]
            target = REQUIRED_TARGET if x["required"] else "advisory"
            mine = [(n, c) for n, c in cases if st in (c.get("states") or [])]
            ems = [m for m in manual if st in m["targets"]["states"]]
            rec = {"screen": sid, "label": x["label"], "required": x["required"], "target": target,
                   "evidence": [{"source": "browser" if c["id"].startswith("ui::") else "test", "step": n, "case": c["id"], "status": c["status"],
                                 "run_id": run["run_id"], "at": run["at"], "code_tree": run.get("code_only_tree")} for n, c in mine][:12],
                   "manual": [{"id": m["id"], "result": m["result"], "method": m["method"], "at": m["at"]} for m in ems]}
            if not run["valid"]:
                rec.update(status="invalid_run", level="E0", reason=run.get("invalid_reason"))
            elif any(c["status"] in ("failed", "error") for _, c in mine):
                rec.update(status="failing", level="E1", reason="태그된 테스트·브라우저 결과 실패: " + ", ".join(c["id"] for _, c in mine if c["status"] in ("failed", "error"))[:300])
            elif any(m["result"] == "failed" for m in ems):
                rec.update(status="failing", level="EM", reason="수동 확인 실패 기록: " + ", ".join(m["id"] for m in ems if m["result"] == "failed"))
            elif mine and all(c["status"] == "skipped" for _, c in mine):
                rec.update(status="not_run", level="E1", reason="태그된 테스트가 모두 건너뛰어짐(skipped)")
            elif mine:
                rec.update(status="verified", level="E2", reason="태그된 테스트·브라우저 결과 통과(E2)")
            else:
                level = "E1" if st in mentioned else "E0"
                if ems:
                    rec.update(level="EM", status="manual_only" if x["required"] else "verified",
                               reason=("수동 확인만 있음 — 필수 상태는 실행 증거(E2)가 필요합니다" if x["required"] else "수동 확인(EM)"))
                elif not_run or broken:
                    rec.update(level=level, status="not_run", reason="태그된 결과 없음 — 실행되지 않은 단계: " + ", ".join(not_run + broken))
                else:
                    rec.update(level=level, status="untested", reason="상태 태그된 테스트 없음" + (" (테스트에 언급만 있음: E1)" if level == "E1" else ""))
            out[st] = rec
    return out


def ac_links(brief: dict, uplan: dict | None, ac_eval: dict, states: dict) -> dict:
    """AC ↔ 화면 상태 연결(05의 AC→상태 + UI Plan acs). 'AC는 통과했지만 연결 상태는 증거 없음' 불일치를 보고합니다."""
    links: dict[str, set] = {}
    for sb in brief["screens"].values():
        for a in sb["acs"]:
            links.setdefault(a["id"], set()).update(a["states"])
    for sp in ((uplan or {}).get("screens") or {}).values():
        if isinstance(sp, dict) and isinstance(sp.get("acs"), dict):
            for a, v in sp["acs"].items():
                if isinstance(v, dict):
                    links.setdefault(a, set()).update(x for x in v.get("states") or [] if isinstance(x, str))
    out = {}
    for a in sorted(links):
        sts = sorted(x for x in links[a] if x in states)
        e = ac_eval.get(a) or {}
        gaps = [x for x in sts if states[x]["status"] != "verified"]
        out[a] = {"ac_status": e.get("status"), "ac_level": e.get("level"), "states": {x: states[x]["status"] for x in sts},
                  "mismatch": bool(e.get("status") == "verified" and gaps), "gaps": gaps}
    return out


# ---------------------------------------------------------------- 무효화 기준(화면별·토큰)
def _vd_related(project: Path) -> list[dict]:
    from pb_ui import dd_vd_blocks  # 지역 import
    return [dict(id=k, **v) for k, v in sorted(dd_vd_blocks(project).items()) if v["status"] == "승인"]


def screen_basis(project: Path, sid: str, uplan: dict | None, umap: dict | None) -> str | None:
    """화면 한 개의 증거가 기대는 입력: 02 화면 블록, 그 화면에 연결된 05 AC 행, 관련 VD, 화면 CMP(04·대응표), UI Plan의 그 화면."""
    from pb_ui import uisys_cmps  # 지역 import
    sinfo = screen_info(project).get(sid)
    if not sinfo:
        return None
    cmps = sorted(sinfo["cmp"])
    c04 = uisys_cmps(project)
    trace = strip_fences(read_text(project, TRACE_FILE))
    ac_rows = {a: cells for a, cells in table_rows(trace, r"AC-\d{3}").items() if sid in " ".join(cells)}
    vds = [v for v in _vd_related(project) if sid in v["related"] or set(cmps) & set(re.findall(r"CMP-\d{3}", v["related"]))]
    mapping = {c: ((umap or {}).get("components") or {}).get(c) for c in cmps}
    sp = ((uplan or {}).get("screens") or {}).get(sid)
    return digest({"block": sinfo["block"], "acs": ac_rows, "vds": vds, "cmps": {c: c04.get(c) for c in cmps}, "map": mapping, "plan": sp})


def tokens_basis(project: Path, umap: dict | None) -> str:
    """토큰 기준: 승인된 토큰(04 또는 v2 테마) + 토큰 출력 설정·출력 파일 내용 + 허용 예외(토큰·직접 값). 예외 추가·변경·삭제 시 바뀜."""
    from pb_ui import approved_tokens  # 지역 import
    approved, src = approved_tokens(project)
    ex = (umap or {}).get("exceptions") or {}
    out_file = ((umap or {}).get("tokens") or {}).get("file")
    return digest({"approved": approved, "source": src, "output": (umap or {}).get("tokens"),
                   "output_sha": sha_file(project / out_file) if out_file and not Path(out_file).is_absolute() and ".." not in Path(out_file).parts else None,
                   "token_exceptions": ex.get("tokens") or [], "audit_exceptions": ex.get("audit") or []})


def current_basis(project: Path, screens: list[str], uplan: dict | None, umap: dict | None) -> dict:
    return {"screens": {s: screen_basis(project, s, uplan, umap) for s in screens}, "tokens": tokens_basis(project, umap),
            "ui_plan_components": digest((uplan or {}).get("components"))}


def basis_changes(old: dict, new: dict) -> dict:
    ch = {"screens": sorted(s for s, h in (old.get("screens") or {}).items() if (new.get("screens") or {}).get(s) != h)}
    ch["tokens"] = old.get("tokens") != new.get("tokens")
    ch["ui_plan_components"] = old.get("ui_plan_components") != new.get("ui_plan_components")
    return ch


def describe_changes(ch: dict) -> str | None:
    parts = []
    if ch["screens"]:
        parts.append("화면 입력(02 명세·AC·디자인 결정·컴포넌트·UI Plan): " + ", ".join(ch["screens"]))
    if ch["tokens"]:
        parts.append("토큰 기준(승인 토큰·출력 설정·허용 예외)")
    if ch["ui_plan_components"]:
        parts.append("UI Plan 컴포넌트 목록")
    return ("검증 이후 UI 입력이 바뀌었습니다 — " + "; ".join(parts)) if parts else None


# ---------------------------------------------------------------- 수동 증거(EM)
def next_em_id(st: dict) -> str:
    n = 0
    for b in (st.get("batches") or {}).values():
        for m in b.get("manual_evidence") or []:
            n = max(n, int(m["id"].split("-")[1]))
    return f"EM-{n + 1:03d}"


def em_status(project: Path, m: dict, scope_tree: str, basis_now: dict) -> tuple[str, str]:
    """EM 기록의 현재 유효성: active / stale / revoked."""
    if m.get("revoked"):
        return "revoked", f"철회됨: {m['revoked'].get('reason')}"
    if m["code"]["scope_tree"] != scope_tree:
        return "stale", "기록 이후 배치 범위의 코드가 바뀌었습니다"
    for s, h in (m.get("basis") or {}).items():
        if basis_now.get(s) != h:
            return "stale", f"기록 이후 {s}의 입력(명세·UI Plan·디자인)이 바뀌었습니다"
    for f in m.get("files") or []:
        if sha_file(project / f["path"]) != f["sha256"]:
            return "stale", f"근거 파일 {f['path']}이 바뀌었거나 없습니다"
    return "active", ""


def em_file_record(project: Path, rel: str) -> dict:
    return {"path": rel, "sha256": sha_file(project / rel), "kind": "screenshot" if rel.lower().endswith(SHOT_EXT) else "file"}



def evidence_digest(ui: dict) -> str:
    """UI 증거 요약 digest(승인 기록과 비교): 상태별 판정·브라우저 판정·토큰 결과·코드 버전(실행 ID는 제외: 같은 코드·같은 결과면 같음)."""
    return digest({"states": {k: (v.get("status"), v.get("level")) for k, v in (ui.get("states") or {}).items()},
                   "browser": {k: (ui.get("browser") or {}).get(k) for k in ("status", "blocking")},
                   "tokens": {k: (v or {}).get("ok") for k, v in (ui.get("tokens") or {}).items()},
                   "code": (ui.get("code") or {}).get("code_tree")})
