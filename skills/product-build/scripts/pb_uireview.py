"""/product-build M3.5: UI 검토 묶음(ui-review), 수정 요청(ui-feedback) 분류·경로, UI 최종 승인 조건.

원칙
- 검토 묶음은 검증 결과(verification.ui)에서 만든 요약입니다. 묶음 ID(review_id)는 내용 digest라서, 증거·코드·피드백이 바뀌면 달라집니다.
  최종 UI 승인은 '지금 기준의' 묶음 ID와 사용자 승인 문장·승인 주체가 있어야 합니다.
- 수정 요청 분류는 /product-design의 변경 분류(①–⑤, `impact --design`, 읽기 전용)를 그대로 씁니다. 엔진은 디자인 상태를 바꾸지 않습니다.
  - 결함(승인 명세와 다르게 구현됨)·⑤ 구현 메모·재승인이 필요 없는 ④ → 코드 수정(code_fix): 이 배치만 고치고 다시 검증. 기획·디자인 승인은 그대로.
  - ①·②·③, 재승인이 필요한 ④ → 디자인 변경(design_change): 코드로 바꾸지 않고 소유 Skill의 영향 분석·재승인 절차.
  - conditional·needs_review → 사용자 결정(needs_decision).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pb_core import DESIGN_STATE_REL, PD_CLI, block, digest

REVIEW_FORMAT = "pb-ui-review/v1"
ROUTES = ("code_fix", "design_change", "needs_decision")
DESIGN_CATS = {"info_behavior", "token_semantics", "theme_value"}
FB_OPEN = ("open", "needs_decision")


def ui_required(prof: dict, plan_batch: dict | None) -> bool:
    """M3 UI 흐름이 필수인 배치: 프로필에 [ui]가 있는 프로젝트에서 계획상 kind = "ui"인 배치. 그 밖(비UI·foundation·M2 프로젝트)은 선택."""
    return "ui" in prof and (plan_batch or {}).get("kind") == "ui"


# ---------------------------------------------------------------- 수정 요청 분류(①–⑤ 재사용)
def classify(project: Path, fid: str, summary: str, facts: list[dict]) -> dict:
    """/product-design impact --design --request(읽기 전용). 요청 파일은 프로젝트 밖 임시 폴더에 씁니다."""
    tmp = Path(tempfile.mkdtemp(prefix="pb-ui-feedback-"))
    try:
        req = tmp / "request.json"
        req.write_text(json.dumps({"schema": "design-change-request/v1", "items": [{"id": fid, "summary": summary, "facts": facts}]},
                                  ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, "-I", str(PD_CLI), "impact", "--design", "--request", str(req), "--project", str(project)],
                           capture_output=True, text=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        block("design_impact_failed", "/product-design 변경 분류를 실행하지 못했습니다.", tail=(p.stdout + p.stderr)[-500:])
    if not out.get("ok") or not out.get("items"):
        block("design_impact_failed", f"/product-design 변경 분류가 실패했습니다: {out.get('message') or out.get('error')}")
    return out["items"][0]


def route_of(item: dict) -> tuple[str, str]:
    cats = [c["key"] for c in item.get("categories") or []]
    if item["status"] == "excluded":
        return "code_fix", "결함 보고(승인 명세와 다르게 구현됨): 이 배치 코드만 고칩니다"
    if item["status"] in ("conditional", "needs_review"):
        return "needs_decision", "분류가 확정되지 않았습니다. 사용자가 경로(code_fix·design_change)를 정합니다"
    if set(cats) & DESIGN_CATS:
        return "design_change", "승인된 UX·토큰·테마를 바꾸는 요청입니다(" + ", ".join(c["no"] for c in item["categories"]) + ")"
    if item.get("reapproval_required"):
        return "design_change", "승인된 디자인 산출물의 재승인이 필요한 시각 변경입니다: " + ", ".join(item.get("reapproval_stages") or [])
    return "code_fix", "승인된 디자인 범위 안의 수정입니다(" + ", ".join(c["no"] for c in item["categories"]) + ")"


def next_for(route: str, bid: str, item: dict | None) -> str:
    if route == "code_fix":
        return f"resume --batch {bid} → 수정 → batch-submit → verify → ui-review → ui-feedback resolve --id <FB>"
    if route == "design_change":
        stages = ", ".join((item or {}).get("reapproval_stages") or []) or "해당 단계"
        return ("코드로 바꾸지 않습니다. /product-design impact --design으로 영향을 보여 주고 사용자 확인 후 reopen("
                f"{stages}) → 재승인 → 계획 갱신(check가 outdated를 알림) → 재구현·재검증")
    return "사용자에게 분류 조건을 설명하고 ui-feedback decide --id <FB> --route code_fix|design_change --note"


def design_revisions(project: Path) -> dict:
    p = project / DESIGN_STATE_REL
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except json.JSONDecodeError:
        d = {}
    return {k: (v or {}).get("approved_revision") for k, v in (d.get("stages") or {}).items()}


# ---------------------------------------------------------------- 검토 묶음
def build_review(bid: str, b: dict, plan_batch: dict, freshness_problem: str | None, token_now: dict | None,
                 em_now: list[dict], umap: dict | None) -> dict:
    v = b.get("verification") or {}
    ui = v.get("ui") or {}
    states = ui.get("states") or {}
    results = (ui.get("browser") or {}).get("results") or []
    ev = v.get("evaluation") or {}
    screens = {}
    for sid, r in sorted(states.items()):
        scr = screens.setdefault(r["screen"], {"states": {}, "acs": {}})
        scr["states"][sid] = {"label": r.get("label"), "required": r["required"], "status": r["status"], "level": r.get("level"),
                              "sources": sorted({e["source"] for e in r.get("evidence") or []}),
                              "manual": [m["id"] for m in r.get("manual") or []],
                              "browser": [{k: x.get(k) for k in ("viewport", "blocking", "warnings", "screenshot")} for x in results if x.get("state") == sid]}
    for a, link in (ui.get("ac_links") or {}).items():
        for sid in link.get("states") or {}:
            scr = screens.get(sid.rsplit("-", 1)[0])
            if scr is not None:
                scr["acs"][a] = {"status": (ev.get(a) or {}).get("status"), "level": (ev.get(a) or {}).get("level")}
    comps = {}
    mp = (umap or {}).get("components") or {}
    for key in ("reuse", "new"):
        for c in ((plan_batch.get("components") or {}).get(key) or []):
            m = mp.get(c) or {}
            comps[c] = {"plan": key, "mapped": bool(m), "source": m.get("source"), "path": m.get("path") or m.get("package"), "export": m.get("export")}
    fbs = [{k: f.get(k) for k in ("id", "summary", "route", "status", "category")} for f in b.get("ui_feedback") or []]
    blockers = []
    if b["status"] not in ("verified", "approved"):
        blockers.append(f"배치 상태가 {b['status']}입니다(자동 검증 verified 이후에만 UI 승인)")
    if not ui:
        blockers.append("UI 증거가 있는 최종 검증이 없습니다(verify --batch)")
    if freshness_problem:
        blockers.append(f"증거가 오래됨(stale): {freshness_problem}")
    if (ui.get("browser") or {}).get("status") == "browser_pending":
        blockers.append("필수 브라우저 검증이 실행되지 않았습니다(browser_pending)")
    blockers += [f"{sid}: 필수 상태 {r['status']}(E2 필요)" for sid, r in states.items() if r["required"] and r["status"] != "verified"]
    if ui and not ui.get("ui_plan_validated"):
        blockers.append("UI Plan이 현재 Brief 기준으로 검증되지 않았습니다")
    if token_now is not None and not token_now.get("ok"):
        blockers.append("토큰 불일치·검사 실패(현재 기준): " + (token_now.get("message") or ", ".join(
            x["token"] for x in (token_now.get("missing") or []) + (token_now.get("mismatch") or []))))
    stale_em = [m["id"] for m in em_now if m["status_now"] == "stale"]
    if stale_em:
        blockers.append(f"수동 증거가 현재 코드·입력과 맞지 않습니다(다시 확인하거나 철회): {', '.join(stale_em)}")
    open_fb = [f["id"] for f in fbs if f["status"] in FB_OPEN]
    if open_fb:
        blockers.append(f"해결되지 않은 수정 요청: {', '.join(open_fb)}")
    body = {"format": REVIEW_FORMAT, "batch": bid, "status": b["status"], "run_id": v.get("run_id"), "verified_at": v.get("at"),
            "code": ui.get("code"), "scope_tree": v.get("scope_tree"), "evidence_digest": ui.get("evidence_digest"),
            "screens": screens, "browser": {k: (ui.get("browser") or {}).get(k) for k in ("status", "steps", "blocking", "warnings", "coverage")},
            "tokens": {"at_verify": (ui.get("tokens") or {}).get("check"), "now": token_now, "audit": (ui.get("tokens") or {}).get("audit")},
            "components": comps, "manual": [{k: m.get(k) for k in ("id", "targets", "method", "result", "status_now")} for m in em_now],
            "feedback": fbs, "warnings": ui.get("warnings") or [], "blockers": blockers}
    body["review_id"] = digest(body)[:16]
    body["ready"] = not blockers
    return body
