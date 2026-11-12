#!/usr/bin/env python3
"""/product-build M2.3 AC 검증을 실제 프로젝트(SMAPSH) **복제본**에서 시도합니다(원본 경로는 거부).

전제: 복제본의 frontend/에 의존성이 설치되어 있어야 합니다(복제본 안에서 `pnpm install --frozen-lockfile`).
프로필은 프런트엔드 vitest 단계(JUnit 리포트, tag_style=prefix) 하나만 씁니다. 백엔드 테스트는 복제본에 가상환경이 없어 넣지 않았고,
그래서 서버 규칙 AC는 '태그된 테스트 없음'으로 보고됩니다(검증 안 된 것을 통과로 세지 않음).
흐름: 계획 승인 → B0(공통, AC 없음) 구현 제출·검증 → 명단 배치 구현 제출(기존 코드 그대로) → 실제 테스트로 AC별 판정.

실행: python3 tests/product_build_smapsh_verify_check.py <복제본 경로> [--original <원본 경로>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
import pb_verify as V  # noqa: E402

results = T.results
check, pb = T.check, T.pb

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["frontend/src"]
tests = ["frontend/src"]
components = ["frontend/src/components"]
exclude = ["node_modules", "dist", "__pycache__"]
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
[verify]
tag_style = "prefix"
"""


def main() -> int:
    clone = Path(sys.argv[1]).resolve()
    original = Path(sys.argv[sys.argv.index("--original") + 1]).resolve() if "--original" in sys.argv else (Path.home() / "Desktop/badminton-playbook").resolve()
    if clone == original or original in clone.parents:
        print("원본 저장소에서는 실행하지 않습니다.")
        return 2
    if not (clone / "frontend/node_modules").exists():
        print("복제본 frontend/에 의존성이 없습니다. 복제본 안에서 pnpm install --frozen-lockfile을 먼저 실행하세요.")
        return 2
    snap = T.protected_snapshot(clone)
    report = {}
    pb(clone, "init")
    (clone / "docs/build/build-profile.toml").write_text(PROFILE)
    plan = T.draft_of(clone)
    b0 = plan["batches"][0]
    roster = next(b for b in plan["batches"] if "SCR-211" in b["screens"])
    b0["paths"] = {"allow": ["frontend/src/components/"], "shared": []}
    roster["paths"] = {"allow": ["frontend/src/features/roster/", "frontend/src/pages/RosterPage.tsx"], "shared": []}
    T.save_plan(clone, plan)
    pb(clone, "waiver", "add", "--reason", "복제본 검증", "--all-ui", "--note", "복제본 검증용 승인", "--confirm")
    c1, o1 = pb(clone, "submit", "plan")
    c2, o2 = pb(clone, "approve", "plan", "--revision", "1", "--note", "복제본 검증용 계획 승인")
    check("Y1 복제본 계획 승인(프로필: vitest JUnit, prefix 태그)", c1 == 0 and c2 == 0, (o1, o2))
    st = json.loads((clone / ".ai-workflow/build.json").read_text())
    report["roster_batch"] = {"id": roster["id"], "screens": roster["screens"], "acs": len(roster["acs"]),
                              "targets": {k: v for k, v in st["batches"][roster["id"]]["ac_targets"].items()}}

    def implement(bid):
        c, o = pb(clone, "batch-start", "--batch", bid, "--owner", "clone", "--allow-dirty-in-scope", "--confirm-risk", "--note", "복제본 검증: 기존 구현을 이 배치 작업으로 확인")
        assert c == 0, o
        for t in [t["id"] for t in o["tasks"]]:
            c, x = pb(clone, "task-done", "--batch", bid, "--task", t, "--lock", o["lock_id"])
            assert c == 0, x
        c, x = pb(clone, "batch-submit", "--batch", bid, "--lock", o["lock_id"])
        assert c == 0, x

    implement(b0["id"])
    code, out = pb(clone, "verify", "--batch", b0["id"])
    st0 = out.get("run", {}).get("steps", {}).get("fe-unit", {})
    report["B0_verify"] = {"status": out.get("status"), "fe-unit": st0}
    check("Y2 B0 검증: 실제 vitest 실행·JUnit 리포트 수집(케이스 수·해시)", out.get("run", {}).get("valid") and st0.get("report", {}).get("cases", 0) > 50, out)
    implement(roster["id"])
    code, out = pb(clone, "verify", "--batch", roster["id"])
    acs = out.get("acs", {})
    report["roster_verify"] = {"status": out.get("status"), "counts": out.get("counts"),
                               "acs": {k: {x: v.get(x) for x in ("status", "level", "target", "reason")} for k, v in sorted(acs.items())}}
    check("Y3 명단 배치 AC별 판정 산출(통과·부족·미검증 사유)", acs and all(v.get("status") for v in acs.values()), out)
    check("Y4 E2 이상은 태그된 테스트 통과에서만(언급만 E1)", all(v["level"] in ("E0", "E1") or v["cases"] for v in acs.values()))
    # 전체 AC 매핑(이번 실행의 리포트 기준)
    run = V.load_run(clone, json.loads((clone / ".ai-workflow/build.json").read_text())["batches"][roster["id"]]["verification"])
    cases = [c for s in run["steps"] for c in s.get("cases", [])]
    model_acs = set(json.loads(json.dumps(pb(clone, "scope")[1]["scope"]["AC_active"])))
    tagged_prefix = {a for c in cases for a in c["acs"]}
    passed_tagged = {a for c in cases if c["status"] == "passed" for a in c["acs"]}
    mentioned = {a for c in cases for a in c["mentions"]} | V.mentions_in_tests(clone, {"paths": {"source": ["frontend/src"], "tests": ["frontend/src"], "exclude": ["node_modules"]}})
    rep_path = clone / run["steps"][0]["report"]["path"]
    bracket = {a for c in V.parse_report(rep_path, "junit-xml", "bracket") for a in c["acs"]}
    report["global_mapping"] = {"active_Must_AC": len(model_acs), "tagged_prefix": len(tagged_prefix & model_acs),
                                "passed_tagged(E2 후보)": len(passed_tagged & model_acs), "mentioned_only(E1)": len((mentioned - tagged_prefix) & model_acs),
                                "no_mention(E0)": len(model_acs - mentioned - tagged_prefix), "tagged_with_bracket_style": len(bracket & model_acs),
                                "cases": len(cases)}
    check("Y5 태그 형식 비교: bracket이면 태그 0(모두 언급), prefix면 머리 태그만 인정", len(bracket) == 0 and len(tagged_prefix) > 0, report["global_mapping"])
    check("Y6 승인 문서·상태 불변", T.protected_snapshot(clone) == snap)
    print("\n=== 보고용 요약 ===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
