#!/usr/bin/env python3
"""/product-build M2.4를 실제 프로젝트(SMAPSH) **복제본**에서 확인합니다(원본 경로는 거부).

전제: 복제본의 frontend/ 의존성(pnpm install)과 backend/ 가상환경(uv sync --frozen)이 설치되어 있어야 합니다.
대상: I1 회원 명단·게스트·점수(명단 배치, SCR-211–213). 프런트엔드 vitest + 백엔드 pytest(JUnit)로 AC를 판정합니다.
PostgreSQL 연동 테스트(pytest -m db)는 복제본에 DB가 없어 선택 단계로 두고 not_run으로 보고합니다(통과로 세지 않음).
흐름: 기존 구현 등록(adopt-register) → 검증(E2부터) → 코드·의존성 변경 → 영향 분석·무효화 → 다른 세션 파일 보호 → 재검증·최종 승인.

실행: python3 tests/product_build_smapsh_m24_check.py <복제본 경로> [--original <원본 경로>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

results = T.results
check, pb = T.check, T.pb

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["frontend/src", "backend/app"]
tests = ["frontend/src", "backend/tests"]
components = ["frontend/src/components"]
exclude = ["node_modules", "dist", "__pycache__", ".venv"]
[execution]
max_retries = 3
lock_ttl_minutes = 30
[[verify.steps]]
name = "fe-unit"
stage = "test"
run = "pnpm --dir frontend exec vitest run --reporter=junit --outputFile=$PB_REPORT_DIR/fe.xml"
cwd = "."
requires = []
report = { format = "junit-xml", file = "fe.xml" }
timeout = 600
[[verify.steps]]
name = "be-unit"
stage = "test"
run = "uv run --frozen pytest -q -p no:cacheprovider --junitxml=$PB_REPORT_DIR/be.xml"
cwd = "backend"
requires = []
report = { format = "junit-xml", file = "be.xml" }
timeout = 600
[[verify.steps]]
name = "be-db"
stage = "db"
run = "uv run --frozen pytest -q -p no:cacheprovider -m db --junitxml=$PB_REPORT_DIR/be-db.xml"
cwd = "backend"
requires = ["postgres"]
optional = true
report = { format = "junit-xml", file = "be-db.xml" }
[verify]
tag_style = ["prefix", "pytest_name"]
"""


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
    (clone / "docs/build/build-profile.toml").write_text(PROFILE)
    plan = T.draft_of(clone)
    b0 = plan["batches"][0]
    roster = next(b for b in plan["batches"] if "SCR-211" in b["screens"])
    b0["paths"] = {"allow": ["frontend/src/components/"], "shared": []}
    roster["paths"] = {"allow": ["frontend/src/features/roster/", "frontend/src/pages/RosterPage.tsx", "backend/app/modules/roster/",
                                 "backend/tests/modules/test_roster.py", "backend/tests/modules/test_roster_db.py"], "shared": []}
    T.save_plan(clone, plan)
    pb(clone, "waiver", "add", "--reason", "복제본 검증", "--all-ui", "--note", "복제본 검증용 승인", "--confirm")
    c1, _ = pb(clone, "submit", "plan")
    c2, _ = pb(clone, "approve", "plan", "--revision", "1", "--note", "복제본 검증용 계획 승인")
    check("Z1 복제본 계획 승인(프로필: vitest + pytest JUnit, 태그 prefix·pytest_name, DB 테스트는 선택 단계)", c1 == 0 and c2 == 0)
    rid = roster["id"]

    code, out = pb(clone, "adopt-register", "--batch", b0["id"], "--note", "복제본 검증: 공통 컴포넌트는 이미 구현됨")
    code2, out2 = pb(clone, "verify", "--batch", b0["id"])
    check("Z2 공통 배치 기존 구현 등록 → 검증(vitest·pytest 실제 실행) verified", code == 0 and out2.get("status") == "verified", out2.get("reasons"))
    rep["B0_steps"] = out2.get("run", {}).get("steps")
    code, out = pb(clone, "adopt-register", "--batch", rid, "--note", "복제본 검증: I1 명단·게스트·점수 API는 이미 구현됨")
    rep["roster_registered_files"] = out.get("files")
    code, out = pb(clone, "verify", "--batch", rid)
    acs = out.get("acs", {})
    rep["roster_first_verify"] = {"status": out.get("status"), "counts": out.get("counts"), "steps": out.get("run", {}).get("steps"),
                                  "acs": {k: {x: v.get(x) for x in ("status", "level", "target", "reason")} | {"cases": len(v.get("cases", []))} for k, v in sorted(acs.items())}}
    be_cases = [c for c in (out.get("acs") or {}).values() for c in c.get("cases", []) if "::" in c["id"] and "tests.modules" in c["id"]]
    check("Z3 I1 명단 AC가 백엔드 pytest(test_ac_xxx)와 프런트 vitest에 연결됨", len(be_cases) > 0 and any(v["level"] == "E2" for v in acs.values()), rep["roster_first_verify"]["acs"])
    check("Z4 기존 구현의 위험 AC(목표 E3)는 E2까지만, 기존 구현 안내와 함께 insufficient(목표 자동 하향 없음)",
          any(v["target"] == "E3" and v["status"] == "insufficient" and "기존 구현" in (v.get("reason") or "") for v in acs.values())
          and all(v["target"] in ("E2", "E3") for v in acs.values()), rep["roster_first_verify"]["acs"])
    check("Z5 DB 연동 테스트는 not_run(선택 단계, 통과로 세지 않음)", out.get("run", {}).get("steps", {}).get("be-db", {}).get("status") == "not_run")

    # 위험 AC: 사용자 승인으로 목표 변경(기록·이력) → verified → 최종 승인
    e3 = sorted(k for k, v in acs.items() if v["status"] == "insufficient")
    other = sorted(k for k, v in acs.items() if v["status"] not in ("verified", "insufficient"))
    rep["e3_insufficient"], rep["other_unverified"] = e3, other
    for a in e3:
        pb(clone, "target", "--batch", rid, "--ac", a, "--level", "E2", "--reason", "기존 구현(I1)이라 실패 우선 기록 없음 — 복제본 검증",
           "--note", "복제본 검증용 사용자 승인: 기존 구현은 E2부터")
    code, out = pb(clone, "verify", "--batch", rid)
    rep["roster_after_target"] = {"status": out.get("status"), "counts": out.get("counts"), "reasons": out.get("reasons")}
    st = json.loads((clone / ".ai-workflow/build.json").read_text())["batches"][rid]
    check("Z6 목표 변경은 이력으로만(원래 목표 보존)", all(st["ac_targets"][a] == "E3" for a in e3) and len(st.get("target_overrides", [])) == len(e3))
    rep["roster_status_after_target"] = out.get("status")
    check("Z6a 태그된 테스트가 없는 AC는 목표 변경 없이 untested로 남아 명단 배치는 verified가 되지 않음(정직한 결과)",
          out.get("status") == "verify_failed" and all(r.split(":")[0] in other for r in out.get("reasons", [])), out.get("reasons"))

    # 다른 세션의 미커밋 작업 보호: 명단 배치를 다시 열어 고치는 중 auth 모듈(다른 세션 작업)을 건드리면 차단
    code, out = pb(clone, "resume", "--batch", rid, "--owner", "clone")
    lock = out.get("lock_id")
    auth = sorted((clone / "backend/app/modules/auth").glob("*.py"))[0]
    aorig = auth.read_text()
    auth.write_text(aorig + "\n# 잘못 건드림\n")
    code, out = pb(clone, "checkpoint", "--batch", rid, "--lock", lock)
    rel = str(auth.relative_to(clone))
    dirty_auth = rel in json.loads((clone / ".ai-workflow/build.json").read_text())["batches"][rid]["run"]["base"]["dirty"]
    check("Z7 다른 세션의 미커밋 백엔드 작업(auth) 변경 → 차단(base_conflict)" if dirty_auth else "Z7 범위 밖 백엔드 파일 변경 → 범위 밖 보고",
          (code == 2 and out.get("error") == "base_conflict") if dirty_auth else (code == 0 and rel in out["findings"]["out_of_scope"]), out)
    rep["auth_was_uncommitted_at_start"] = dirty_auth
    auth.write_text(aorig)
    pb(clone, "pause", "--batch", rid, "--lock", lock, "--note", "복제본 검증: 태그 테스트 보강 전 중지")

    # 검증된 공통 배치(B0) 최종 승인 → 코드·의존성 변경 → 영향 분석(관련 배치만)·무효화(승인 이력 보존)
    bid0 = b0["id"]
    code, out = pb(clone, "approve", "batch", "--batch", bid0, "--note", "복제본 검증용 최종 승인")
    check("Z8 검증된 공통 배치 최종 승인(검증과 별개 기록)", code == 0 and out.get("status") == "approved", out)
    comp = clone / "frontend/src/components/Button.tsx"
    corig = comp.read_text()
    comp.write_text(corig + "\n// 검증 뒤 변경\n")
    code, out = pb(clone, "impact")
    check("Z9 공통 컴포넌트 변경 → B0만 재검증, 명단 배치는 후속 차단", set(out["reverify"]) == {bid0} and bid0 in out["downstream_blocked"].get(rid, []), out)
    comp.write_text(corig)
    code, out = pb(clone, "impact")
    check("Z9a 되돌리면 재검증 필요 없음", not out["reverify"], out)
    for lf, expect in (("backend/uv.lock", False), ("frontend/pnpm-lock.yaml", True)):
        f = clone / lf
        o = f.read_text()
        f.write_text(o + "\n")
        code, out = pb(clone, "impact")
        check(f"Z10 {lf} 변경 → 프런트 전용 공통 배치 재검증 {'필요' if expect else '불필요'}(디렉터리 기준 관련 배치만)", (bid0 in out["reverify"]) == expect, out)
        f.write_text(o)
    comp.write_text(corig + "\n// 검증 뒤 변경\n")
    pb(clone, "check")
    b = json.loads((clone / ".ai-workflow/build.json").read_text())["batches"][bid0]
    check("Z10a 무효화: approved → stale, 승인 기록은 남기고 무효 표시", b["status"] == "stale" and len(b["approvals"]) == 1 and b["approvals"][0]["valid"] is False)
    comp.write_text(corig)
    code, out = pb(clone, "verify", "--batch", bid0)
    code2, out2 = pb(clone, "approve", "batch", "--batch", bid0, "--note", "복제본 검증용 재승인")
    b = json.loads((clone / ".ai-workflow/build.json").read_text())["batches"][bid0]
    check("Z10b 재검증(실제 vitest·pytest) → 재승인, 승인 이력 2건", out.get("status") == "verified" and code2 == 0 and [x["valid"] for x in b["approvals"]] == [False, True], (out.get("reasons"), out2))
    check("Z11 승인 문서·상태 불변", T.protected_snapshot(clone) == snap)
    print("\n=== 보고용 요약 ===")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
