#!/usr/bin/env python3
"""/product-build M2.4b 정책·편차 원장을 실제 프로젝트(SMAPSH) **복제본**에서 시범 등록·검증합니다(원본 경로는 거부).

전제: 복제본 frontend 의존성(pnpm install)과 backend 가상환경(uv sync --frozen).
등록 대상: I1 명단의 미검증 AC(검증 결과에서 sync), E3 목표 미달 AC, 목표 변경·결함 주입 승인 이력(sync), TODO(POL)(원본에는 0건 →
복제본 코드에 시범 표지 1건), P1–P8·Q1–Q7(tests/fixtures/smapsh-policies.json의 분석 결과 — 차단은 P7·Q5만).

실행: python3 tests/product_build_smapsh_ledger_check.py <복제본 경로> [--original <원본 경로>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_build_smapsh_m24_check as M  # noqa: E402

results = T.results
check, pb = T.check, T.pb


def main() -> int:
    clone = Path(sys.argv[1]).resolve()
    original = Path(sys.argv[sys.argv.index("--original") + 1]).resolve() if "--original" in sys.argv else (Path.home() / "Desktop/badminton-playbook").resolve()
    if clone == original or original in clone.parents:
        print("원본 저장소에서는 실행하지 않습니다.")
        return 2
    if not (clone / "frontend/node_modules").exists() or not (clone / "backend/.venv").exists():
        print("복제본에 frontend 의존성과 backend 가상환경이 필요합니다.")
        return 2
    snap = T.protected_snapshot(clone)
    rep = {}
    pb(clone, "init")
    (clone / "docs/build/build-profile.toml").write_text(M.PROFILE)
    plan = T.draft_of(clone)
    by = lambda s: next(b for b in plan["batches"] if s in b["screens"])  # noqa: E731
    b0, roster, session, club = plan["batches"][0], by("SCR-211"), by("SCR-202"), by("SCR-221")
    indep = next(b for b in plan["batches"] if b["kind"] == "ui" and b["id"] not in (roster["id"], session["id"], club["id"])
                 and b.get("depends_on") == [b0["id"]] and not (set(b["screens"]) & {"SCR-001"}))
    b0["paths"] = {"allow": ["frontend/src/components/"], "shared": []}
    roster["paths"] = {"allow": ["frontend/src/features/roster/", "frontend/src/pages/RosterPage.tsx", "backend/app/modules/roster/",
                                 "backend/tests/modules/test_roster.py", "backend/tests/modules/test_roster_db.py"], "shared": []}
    session["paths"] = {"allow": ["frontend/src/features/session/", "frontend/src/pages/SessionPage.tsx"], "shared": []}
    club["paths"] = {"allow": ["frontend/src/features/clubmatch/", "frontend/src/pages/ClubMatch*.tsx"], "shared": []}
    indep["paths"] = {"allow": [f"frontend/src/features/x-{indep['id'].lower()}/"], "shared": []}
    T.save_plan(clone, plan)
    pb(clone, "waiver", "add", "--reason", "복제본 검증", "--all-ui", "--note", "복제본 검증용 승인", "--confirm")
    pb(clone, "submit", "plan")
    pb(clone, "approve", "plan", "--revision", "1", "--note", "복제본 검증용 계획 승인")
    rid = roster["id"]
    rep["batches"] = {"common": b0["id"], "roster": rid, "session": session["id"], "club": club["id"], "independent": indep["id"]}
    pb(clone, "adopt-register", "--batch", b0["id"], "--note", "복제본 검증: 공통 컴포넌트 기존 구현")
    pb(clone, "verify", "--batch", b0["id"])
    pb(clone, "adopt-register", "--batch", rid, "--note", "복제본 검증: I1 명단 기존 구현")
    code, out = pb(clone, "verify", "--batch", rid)
    rep["roster_first"] = {k: (v["status"], v["level"], v["target"]) for k, v in out.get("acs", {}).items()}
    e3 = sorted(k for k, v in out.get("acs", {}).items() if v["status"] == "insufficient")
    check("W1 I1 명단 검증: 목표 E3 미달 AC 2건(AC-013·066)과 미검증 AC 확인", e3 == ["AC-013", "AC-066"], rep["roster_first"])
    pb(clone, "target", "--batch", rid, "--ac", "AC-013", "--level", "E2", "--reason", "기존 구현이라 실패 우선 기록 없음", "--note", "복제본 검증용 사용자 승인: E2로")
    pb(clone, "accept-fault-injection", "--batch", rid, "--ac", "AC-066", "--note", "복제본 검증용 사용자 승인: 결함 주입 증거 인정")
    pb(clone, "verify", "--batch", rid)
    # TODO(POL): 원본 0건 → 복제본에 시범 표지
    mod = sorted((clone / "backend/app/modules/roster").glob("*.py"))[0]
    mod.write_text(mod.read_text() + "\n# TODO(POL): 게스트 삭제 후 익명 기록 보존 기간 미정(임시: 무기한)\n")
    code, out = pb(clone, "ledger", "sync")
    led = json.loads((clone / ".ai-workflow/build/ledger.json").read_text())
    evd = [i for i in led["items"] if i["type"] == "evidence_gap" and i["status"] == "open"]
    tgt = [i for i in led["items"] if i["type"] == "target_change"]
    todo = [i for i in led["items"] if i["source"].get("kind") == "todo_pol"]
    rep["sync"] = {"added": len(out.get("added", [])), "evidence_gap": sorted(a for i in evd for a in i["related"]["acs"]),
                   "target_change": [i["title"] for i in tgt], "todo_pol": [(i["id"], i["related"]["batches"], i["blocking"]) for i in todo]}
    check("W2 미검증 AC 6건 + E3 미달(결함 주입 인정했으나 증거 없음) → 검증 증거 부족(비차단)",
          {"AC-014", "AC-018", "AC-097", "AC-105", "AC-106", "AC-107"} <= set(rep["sync"]["evidence_gap"]) and "AC-066" in rep["sync"]["evidence_gap"]
          and all(not i["blocking"] for i in evd), rep["sync"])
    check("W3 목표 변경·결함 주입 승인 이력 → target_change(결정됨, 사용자 원문)", len(tgt) == 2 and all(i["status"] == "decided" and i["decisions"][0]["statement"] for i in tgt), rep["sync"])
    check("W4 TODO(POL) → 비차단 정책(명단 배치 연결)", len(todo) == 1 and todo[0]["related"]["batches"] == [rid] and not todo[0]["blocking"], rep["sync"])
    # P1–P8·Q1–Q7
    fx = json.loads((HERE / "fixtures/smapsh-policies.json").read_text())
    ids = {}
    for it in fx["items"]:
        bid = next(b["id"] for b in plan["batches"] if set(it["screens"]) & set(b["screens"]))
        args = ["ledger", "add", "--type", it["type"], "--title", f"{it['key']} {it['title']}", "--desc", it.get("rationale", ""),
                "--batches", bid, "--provisional", it.get("provisional", ""), "--rationale", it["rationale"], "--by", "claude(분석, 사용자 확인 필요)"]
        if it.get("category"):
            args += ["--category", it["category"]]
        if it.get("blocking"):
            args.append("--blocking")
        if it.get("docs"):
            args += ["--docs", ",".join(it["docs"])]
        if it.get("acs"):
            args += ["--acs", ",".join(it["acs"])]
        code, out = pb(clone, *args)
        ids[it["key"]] = out.get("item", {}).get("id")
    led = json.loads((clone / ".ai-workflow/build/ledger.json").read_text())
    blocking = sorted(i["title"].split()[0] for i in led["items"] if i["blocking"] and i["status"] == "open")
    rep["policies"] = {k: v for k, v in ids.items()}
    rep["blocking"] = blocking
    check("W5 P1–P8·Q1–Q7 15건 등록, 차단은 분석 결과대로 P7·Q5만(일괄 차단 아님)", all(ids.values()) and len(ids) == 15 and blocking == ["P7", "Q5"], blocking)
    code, out = pb(clone, "batch-start", "--batch", session["id"], "--allow-dirty-in-scope", "--confirm-risk", "--note", "확인")
    check("W6 차단 정책(P7)이 걸린 세션 배치 시작 차단", code == 2 and out.get("error") == "blocked_by_policy" and out["items"][0]["id"] == ids["P7"], out)
    code, out = pb(clone, "batch-start", "--batch", club["id"], "--allow-dirty-in-scope", "--confirm-risk", "--note", "확인")
    check("W7 차단 편차(Q5)가 걸린 청백전 배치 시작 차단", code == 2 and out.get("error") == "blocked_by_policy", out)
    code, out = pb(clone, "batch-start", "--batch", indep["id"], "--allow-dirty-in-scope", "--confirm-risk", "--note", "확인")
    check("W8 관련 없는 독립 배치는 진행 가능", code == 0, out)
    if code == 0:
        pb(clone, "pause", "--batch", indep["id"], "--lock", out["lock_id"])
    code, out = pb(clone, "decide")
    rep["decide_open"] = len(out.get("open", []))
    check("W9 decide 목록: 정책·편차 미결 15건 + TODO(POL) 1건(증거 부족은 제외)", rep["decide_open"] == 16, rep["decide_open"])
    code, out = pb(clone, "decide", "--id", ids["P7"])
    rep["p7_preview"] = out.get("item", {}).get("affected_batches")
    check("W10 결정 전 영향 미리보기(기록 없음)", code == 0 and out["status"] == "preview" and session["id"] in out["item"]["affected_batches"], out)
    code, out = pb(clone, "decide", "--id", ids["P2"], "--decision", "x")
    check("W11 원본 문서의 '사용자 지시'만으로 결정을 기록하지 않음(사용자 원문·확인 필요)", out.get("status") == "preview")
    code, out = pb(clone, "status")
    rep["ledger_status"] = out.get("ledger")
    check("W12 승인 문서·상태 불변", T.protected_snapshot(clone) == snap)
    print("\n=== 보고용 요약 ===")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
