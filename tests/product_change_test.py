#!/usr/bin/env python3
"""/product-change 변경 패키지(P1–P5) 테스트(자체 완결형).

한 프로젝트(승인된 기획·디자인 v2·프리뷰·구현 계획·배치 B1/B2)에서 패키지를 차례로 실행합니다.
- 사용자 개입(Asks)은 엔진이 사용자 문장을 요구한 지점만 셉니다. 최초 요청(계약 초안)은 개입이 아닙니다.
- design.json·state.yaml·build.json을 손으로 고치는 일은 없습니다(병합 흔적 흉내 1건 제외: change.json 중복 키).
- pnpm·Chrome이 없으면 SKIP(run_all이 INCOMPLETE로 표시).

실행: python3 tests/product_change_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _tmpdirs as TMP  # noqa: E402
import change_fixture as F  # noqa: E402
import change_package_fixture as P  # noqa: E402
import product_design_test as T  # noqa: E402

results: list[tuple[str, bool, str]] = []
pd, pb, pc, ps = F.pd, F.pb, P.pc, P.ps
EVIDENCE: dict = {}


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:900]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:900]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


def bstate(d):
    return json.loads((d / ".ai-workflow/build.json").read_text())


def cstate(d):
    return json.loads((d / ".ai-workflow/change.json").read_text())


def approvals(d):
    return {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted", "last_approved")} for k, v in F.state(d)["stages"].items()}


def run_batch(d, bid, write=None):
    code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t")
    assert code == 0, out
    lock = out["lock_id"]
    for rel, text in (write or {}).items():
        (d / rel).write_text(text)
    for t in [x for x, v in bstate(d)["batches"][bid]["run"]["tasks"].items() if v["status"] != "done"]:
        assert pb(d, "task-done", "--batch", bid, "--task", t, "--lock", lock)[0] == 0
    return lock


# ================================================================ P1 영향 분석
def p1_impact(d, root):
    ids = root / "ids.json"
    ids.write_text(json.dumps({"remove": ["AC-002", "FLOW-001-S1a"]}))
    code, out = pc(d, "plan", "--ids", ids)
    imp = out["impact"]
    by = {it["loc"]: it for it in imp["items"]}
    dd = [it for it in imp["items"] if it["loc"].startswith("docs/design/07")]
    pv = [it for it in imp["items"] if it["loc"] == "design-preview/src/screens/SCR-001.tsx"]
    dd_text = (d / "docs/design/07-design-direction.md").read_text() + (d / "design-preview/src/screens/SCR-001.tsx").read_text()
    check("C1 간접 영향: AC-002를 직접 적지 않은 DD(VD-001)·프리뷰(SCR-001.tsx)를 SCR-001 경유로 탐지(직접 참조 없음 ≠ 영향 없음)",
          code == 0 and "AC-002" not in dd_text and dd and dd[0]["level"] == "indirect" and pv and pv[0]["level"] == "indirect"
          and "SCR-001" in " ".join(dd[0]["path"]), [(i["loc"], i["level"], i["path"]) for i in dd + pv])
    check("C2 직접 영향(05 추적 행·03 흐름 행·B1)과 간접 영향 구분, 영향 없는 UX Planning은 승계 후보",
          any(it["level"] == "direct" and "05-design-traceability" in it["loc"] for it in imp["items"]) and imp["batches"] == ["B1"]
          and imp["stages_inherited"] == ["ux_planning"] and set(imp["stages_affected"]) == {"ux_spec", "design_direction", "preview"}, imp["stages_affected"])
    check("C3 코드·테스트의 직접 언급(tests/test_login.py) 수집", "tests/test_login.py" in imp["code_mentions"], imp["code_mentions"])
    tok = root / "tok.json"
    tok.write_text(json.dumps({"tokens": True}))
    code, out = pc(d, "plan", "--ids", tok)
    check("C4 전역 토큰 변경 → 모든 화면·단계로 확대(사유 기록)", code == 0 and set(out["impact"]["screens"]) >= {"SCR-001", "SCR-002", "SCR-003"}
          and len(out["impact"]["stages_affected"]) == 4 and any("토큰" in w for w in out["impact"]["widened"]), out["impact"]["screens"])
    add = root / "add.json"
    add.write_text(json.dumps({"add": ["AC-005"]}))
    code, out = pc(d, "plan", "--ids", add)
    check("C5 신규 기능(추가 ID) → 참조가 없어 영향 화면을 계약에 명시하라는 확대 사유", any("추가 ID" in w for w in out["impact"]["widened"]), out["impact"]["widened"])
    EVIDENCE["impact_ac002"] = {k: imp[k] for k in ("screens", "design_units", "stages_affected", "stages_inherited", "batches", "preview_files")}


# ================================================================ S1 AC 폐기(AC-164 축소 재현) — 통합 승인 2회
def s1_retire(d, root):
    asks = P.Asks()
    before = approvals(d)
    hist0 = list(F.state(d)["history"])
    b0 = bstate(d)
    code, out = pc(d, "open", "--contract", P.contract(root, "c1-gap", design={"units": [], "screens": ["SCR-001"], "files": []}))
    check("S1a 계약이 간접 영향(VD-001)을 덮지 않으면 승인 불가(gaps)", code == 0 and out["gaps"]["design_units"] == ["VD-001"] and not out["approvable"], out.get("gaps"))
    code, out = pc(d, "approve-contract", "--id", "CP-001", "--note", "그대로 진행")
    check("S1b gaps가 있는 계약 승인 시도 → contract_gaps", code == 2 and out["error"] == "contract_gaps", out)
    code, out = pc(d, "amend-contract", "--id", "CP-001", "--contract", P.contract(root, "c1"), "--reason", "간접 영향 VD-001 포함")
    code, out = pc(d, "approve-contract", "--id", "CP-001", "--note", asks.user("contract", "이 변경 계약대로 진행해(1차 승인 시뮬레이션)"))
    check("S1c 1차 계약 승인(계약·기준·영향 digest 결합)", code == 0 and out["status"] == "executing" and len(out["approval"]["digest"]) == 64, out)
    P.retire_planning(d)
    code, out = pc(d, "plan", "--ids", root / "ids.json")
    dang_before = out["impact"]["dangling_refs"]
    P.ok(pc, d, "snapshot-planning", "--id", "CP-001")
    code, chk = pd(d, "check")
    check("S1d 패키지 제안 기획을 임시 기준으로 인정: 디자인 승인이 일괄 무효화(outdated)되지 않음", code == 0 and chk["status"] == "approved"
          and F.state(d)["validity"]["status"] == "valid", chk.get("error"))
    P.ok(pd, d, "change", "open", "--package", "CP-001")
    P.retire_design(d)
    code, out = pc(d, "plan", "--ids", root / "ids.json")
    check("C6 폐기 ID의 유효 참조(정리 필요)와 이력 참조(취소선) 구분: 정리 전 유효 참조 → 정리 후 0, 이력 참조 남음",
          dang_before and not out["impact"]["dangling_refs"] and out["impact"]["historical_refs"], (len(dang_before), out["impact"]["dangling_refs"]))
    code, v = pd(d, "change", "verify", "--id", "CR-001")
    sv = next((c for c in v.get("checks", []) if c["name"] == "screen_verification"), {})
    check("S1e 영향 DD·Preview는 패키지 안에서 수정·검증(프리뷰 빌드 + 영향 화면 실측), 별도 승인 게이트 없음", code == 0 and sv.get("state") == "passed"
          and sv.get("screens") == ["SCR-001"], v)
    P.ok(pd, d, "change", "submit", "--id", "CR-001")
    code, out = pd(d, "change", "approve", "--id", "CR-001", "--note", "승인")
    check("S1f 패키지 디자인 변경은 단계 승인으로 공식화 불가(package_cr_final_only)", code == 2 and out["error"] == "package_cr_final_only", out)
    P.ok(pc, d, "review", "--id", "CP-001", "--unit", "VD-001", "--reason", "VD-001(카드 2열)은 인증 실패 안내와 무관 — 변경 불필요")
    P.retire_build(d)
    P.ok(pc, d, "snapshot-plan", "--id", "CP-001")
    lock = run_batch(d, "B1", {"tests/test_login.py": P.T_LOGIN_RETIRED})
    code, out = pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    conf = (bstate(d)["batches"]["B1"]["run"]["confirmations"] or [{}])
    check("S1h 계약이 승인한 테스트 삭제(AC-002 테스트 단위)는 다시 묻지 않음, 위험 배치(security)도 계약 허용 범위로 시작",
          code == 0 and any(c.get("kind") == "test_changes" and c.get("by") == "package_contract" for c in conf)
          and any(c.get("kind") == "risk" and c.get("by") == "package_contract" for c in conf), (out, conf))
    P.ok(pb, d, "verify", "--batch", "B1")
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "B1 승인")
    check("S1g 패키지 진행 중 배치 최종 승인은 별도로 받지 않음(package_pending)", code == 2 and out["error"] == "package_pending", out)
    P.ok(pb, d, "verify", "--batch", "B2")
    check("S1i 패키지 기준 검증 기록(package 표시)·검증 목표는 계획 제안에서 같은 규칙으로 계산(AC-002 제외)",
          bstate(d)["batches"]["B1"]["verification"].get("package") == "CP-001" and "AC-002" not in bstate(d)["batches"]["B1"]["verification"]["targets"],
          bstate(d)["batches"]["B1"]["verification"].get("targets"))
    P.ok(pc, d, "check", "--id", "CP-001")
    P.ok(pc, d, "regression", "--id", "CP-001")
    code, sf = pc(d, "submit-final", "--id", "CP-001")
    check("S1j 최종 통합 승인 묶음: 변경 산출물·영향/승계 단계·바꾸지 않은 단위(VD-001)·배치·회귀", code == 0 and "ux_planning" in sf["show_user"]["stages_inherited"]
          and sf["show_user"]["reviewed_unchanged"] == ["VD-001"] and set(sf["show_user"]["batches"]) == {"B1", "B2"}, sf)
    p = d / "design-preview/src/screens/SCR-001.tsx"
    orig = p.read_text()
    p.write_text(orig + "\n// 늦은 수정\n")
    code, out = pc(d, "approve-final", "--id", "CP-001", "--note", "최종 승인합니다")
    check("S1k 최종 승인 직전 산출물 변경 → approve-final 거부(changed_since_final_submit)", code == 2 and out["error"] == "changed_since_final_submit", out)
    p.write_text(orig)
    code, out = pc(d, "approve-final", "--id", "CP-001", "--note", "이 변경 계약대로 진행해(1차 승인 시뮬레이션)")
    check("S1l 1차 계약 승인 문장을 최종 승인으로 재사용 → approval_reused", code == 2 and out["error"] == "approval_reused", out)
    def counts():
        """승인 기록 수: 기획 승인 history(패키지 원문 참조), 디자인 패키지 패치, 배치별 패키지 승인."""
        ys = (d / ".ai-workflow/state.yaml").read_text()
        dst = F.state(d)
        bb = bstate(d)
        return {"planning_approved": sum(1 for ln in ys.splitlines() if "stage: planning, event: approved," in ln and "[CP-001 최종 통합 승인" in ln),
                "design_amd": sum(1 for a in (dst.get("changes") or {}).get("chain") or [] if a.get("package") == "CP-001"),
                "batch": {k: sum(1 for a in bb["batches"][k].get("approvals") or [] if a.get("package") == "CP-001") for k in ("B1", "B2")}}

    def stop_ok(label, code, out, expect_step, pstatus):
        ps_ = P.ps(d, "check")[1]["submission"]["planning"]["status"]
        code_g, g = pc(d, "gate")
        code_b, bo = pb(d, "approve", "batch", "--batch", "B1", "--note", "x")
        check(f"{label} → 공식 게이트·배치 승인 차단, 패키지 finalizing 유지, 기획 {pstatus}",
              code == 2 and out.get("step") == expect_step and ps_ == pstatus and code_g == 2 and g.get("error") == "package_pending"
              and code_b == 2 and cstate(d)["packages"]["CP-001"]["status"] == "finalizing", (out.get("error"), out.get("step"), ps_, g.get("error"), bo.get("error")))

    c_before = counts()
    # 5개 중단 지점: planning:reopen → planning:submit → planning:approve → design → build (각 지점 직전에 멈춘 뒤 finalize 재실행)
    os.environ["PC_SIMULATE_FAIL_AT"] = "planning:reopen"
    code, out = pc(d, "approve-final", "--id", "CP-001", "--note", asks.user("final", "변경 결과를 확인했고 최종 승인합니다(2차 승인 시뮬레이션)"))
    os.environ.pop("PC_SIMULATE_FAIL_AT")
    stop_ok("S1m0 finalize를 기획 reopen 직전에 중단(아무 공식 기록도 없음)", code, out, "planning:reopen", "approved")
    check("S1m0' reopen 직전 중단: 최종 승인은 기록되었고 공식 승인 기록은 하나도 늘지 않음", counts() == c_before
          and (cstate(d)["packages"]["CP-001"].get("final") or {}).get("statement"), counts())
    code, out = pc(d, "approve-final", "--id", "CP-001", "--note", "변경 결과를 확인했고 최종 승인합니다(2차 승인 시뮬레이션)")
    check("S1m0'' finalizing 중 approve-final 재호출은 받지 않음(승인 중복 없음)", code == 2, out)
    os.environ["PC_SIMULATE_FAIL_AT"] = "planning:submit"
    code, out = pc(d, "finalize", "--id", "CP-001")
    os.environ.pop("PC_SIMULATE_FAIL_AT")
    stop_ok("S1m finalize가 기획 재개 직후(submit 직전) 멈춤(부분 반영)", code, out, "planning:submit", "in_progress")
    os.environ["PC_SIMULATE_FAIL_AT"] = "planning:approve"
    code, out = pc(d, "finalize", "--id", "CP-001")
    os.environ.pop("PC_SIMULATE_FAIL_AT")
    stop_ok("S1m2 finalize가 기획 제출 직후(approve 직전) 멈춤 — reopen·submit을 다시 하지 않고 이어 감", code, out, "planning:approve", "awaiting_approval")
    check("S1m2' approve 직전 중단: 기획 승인 기록 0건 추가(중복 없음)", counts() == c_before, counts())
    for stop in ("design", "build"):
        os.environ["PC_SIMULATE_FAIL_AT"] = stop
        code, out = pc(d, "finalize", "--id", "CP-001")
        os.environ.pop("PC_SIMULATE_FAIL_AT")
        check(f"S1n finalize를 {stop} 단계 직전에 강제 중단 → 이전 단계는 완료 기록, 패키지는 finalizing 유지", code == 2 and out["step"] == stop
              and cstate(d)["packages"]["CP-001"]["status"] == "finalizing" and cstate(d)["packages"]["CP-001"]["finalize"]["planning"]["done"], out)
        stop_ok(f"S1n' {stop} 직전 중단", code, out, stop, "approved")
    c_mid = counts()
    check("S1n'' build 직전 중단 시점: 기획 승인 1회·디자인 패키지 패치 1건, 배치 패키지 승인 0건", c_mid["planning_approved"] == c_before["planning_approved"] + 1
          and c_mid["design_amd"] == 1 and c_mid["batch"] == {"B1": 0, "B2": 0}, c_mid)
    code, out = pc(d, "resume", "--id", "CP-001")
    c_done = counts()
    code2, out2 = pc(d, "finalize", "--id", "CP-001")
    code3, out3 = pc(d, "resume", "--id", "CP-001")
    check("S1o resume으로 마무리, 다시 실행해도 같은 결과(멱등)", code == 0 and out["status"] == "approved" and code2 == 0 and out2["status"] == "approved"
          and code3 == 0, (out, out3))
    check("S1o' 반복 finalize·resume 후 승인 기록 중복 없음(기획 승인·디자인 패치·배치 승인 각 1회)", counts() == c_done and c_done["planning_approved"] == c_mid["planning_approved"]
          and c_done["design_amd"] == 1 and c_done["batch"] == {"B1": 1, "B2": 1}, (c_mid, c_done, counts()))
    st = F.state(d)
    after = approvals(d)
    check("S1p 기존 디자인 승인 기록(approved·submitted·last_approved·revision) 불변 — UX Planning·UX Spec·DD·Preview 모두 r1 유지",
          after == before, {k: (before[k]["revision"], after[k]["revision"]) for k in before})
    check("S1q 디자인 기준 r1 → r2(범위 한정 rebase), 패키지 패치 AMD 기록, history 덧붙이기만(rebased_scoped)", st["based_on"]["planning_revision"] == "2"
          and st["changes"]["chain"][-1].get("package") == "CP-001" and st["history"][:len(hist0)] == hist0
          and any(h["event"] == "rebased_scoped" for h in st["history"][len(hist0):]) and not any(h["event"] in ("rebased", "invalidated") for h in st["history"][len(hist0):]))
    b = bstate(d)
    check("S1r 구현 계획 r1 → r2 재승인(배치 기록 보존), B1·B2 최종 승인은 패키지 최종 승인으로 기록(이전 승인 승계 표시)",
          b["plan"]["status"] == "approved" and b["plan"]["revision"] == b0["plan"]["revision"] + 1
          and all(b["batches"][k]["approvals"][-1].get("package") == "CP-001" and b["batches"][k]["approvals"][-1].get("carried_from") for k in ("B1", "B2")), b["plan"])
    ys = (d / ".ai-workflow/state.yaml").read_text()
    check("S1s 기획 r2 공식 승인 기록은 최종 승인 원문을 참조(단계별 문장 생성 없음)", "[CP-001 최종 통합 승인" in ys and "status: approved" in ys)
    code1, c1 = pd(d, "check")
    code2, c2 = pb(d, "check")
    code3, c3 = pc(d, "gate")
    check("S1t 완료 후 디자인 check 일관·구현 계획 유효·공식 게이트 열림", code1 == 0 and code2 == 0 and c2["plan"]["status"] == "approved" and code3 == 0, (c1.get("cross_verify"), c2.get("error")))
    check("S1u 사용자 개입 2회(1차 계약·2차 최종)", asks.n == 2, asks.log)
    EVIDENCE["s1"] = {"asks": asks.n, "design_revisions": {k: v["revision"] for k, v in after.items()}, "plan_revision": b["plan"]["revision"],
                      "changed": sorted(sf["show_user"]["changed_artifacts"])}
    P.BCcommit(d, "CP-001 (user)")


# ================================================================ S2 특정 화면 레이아웃 변경(기획 변경 없음)
def s2_layout(d, root):
    asks = P.Asks()
    c = P.contract(root, "c2", purpose="대진 화면(SCR-002) 제목 영역 배치 정리", policy="기능·정보·흐름은 그대로, 제목 영역 표현만",
                   ids={"add": [], "modify": [], "remove": []}, keep=["AC-003", "AC-004"], design={"units": [], "screens": ["SCR-002"], "files": []},
                   build={"rework": [], "regression": ["B2"]}, files=[], tests={"remove": [], "modify": [], "add": []}, risky_ops=[])
    P.ok(pc, d, "open", "--contract", c)
    P.ok(pc, d, "approve-contract", "--id", "CP-002", "--note", asks.user("contract", "대진 화면 제목 배치만 바꾸는 계약 승인(시뮬레이션)"))
    P.ok(pd, d, "change", "open", "--package", "CP-002")
    p = d / "docs/design/02-screens.md"
    p.write_text(p.read_text().replace("- **목적**: 대진 생성", "- **목적**: 대진 생성(제목 영역 상단 고정)"))
    s = d / "design-preview/src/screens/SCR-002.tsx"
    s.write_text(s.read_text().replace("<h1>대진</h1>", "<h1 style={{ position: 'sticky', top: 0 }}>대진</h1>"))
    code, v = pd(d, "change", "verify", "--id", "CR-002")
    sv = next((x for x in v.get("checks", []) if x["name"] == "screen_verification"), {})
    check("S2a 화면 레이아웃 변경: 그 화면(SCR-002)만 실측", code == 0 and sv.get("screens") == ["SCR-002"], v)
    P.ok(pd, d, "change", "submit", "--id", "CR-002")
    P.ok(pb, d, "verify", "--batch", "B2")
    P.ok(pc, d, "regression", "--id", "CP-002")
    P.ok(pc, d, "submit-final", "--id", "CP-002")
    code, out = pc(d, "approve-final", "--id", "CP-002", "--note", asks.user("final", "대진 화면 결과 확인, 최종 승인(시뮬레이션)"))
    ys = (d / ".ai-workflow/state.yaml").read_text()
    check("S2b 기획 변경 없는 패키지: 기획 단계 건너뜀(r2 유지), 디자인 패치·B2 승인 승계, 승인 2회", code == 0 and out["status"] == "approved"
          and "    revision: 2" in ys and F.state(d)["changes"]["chain"][-1]["package"] == "CP-002" and asks.n == 2, out)
    P.BCcommit(d, "CP-002 (user)")
    s.write_text(s.read_text() + "\n// 승인 후 수정\n")
    code, out = pd(d, "check")
    check("S7 승인 후 패치 산출물 변경 → 디자인 approved_modified(유효 기준 대비) 차단", code == 2
          and any(x["kind"] == "approved_modified" for x in out["cross_verify"]["problems"]), out.get("cross_verify"))
    T.G(d, "checkout", "--", "design-preview/src/screens/SCR-002.tsx")


# ================================================================ S3 작은 정책 추가 + 새 디자인 결정 필요 → 에스컬레이션
def s3_policy(d, root):
    asks = P.Asks()
    c = P.contract(root, "c3", purpose="대진 생성에 같은 입력 재사용 정책 문구 추가", policy="AC-003에 '같은 조건이면 이전 대진 재사용' 문구",
                   ids={"add": [], "modify": ["AC-003"], "remove": []}, keep=["AC-004"], design={"units": ["UXD-002"], "screens": ["SCR-002"], "files": []},
                   build={"rework": [], "regression": ["B2"]}, files=["tests/test_round.py"], tests={"remove": [], "modify": [], "add": []}, risky_ops=[])
    P.ok(pc, d, "open", "--contract", c)
    P.ok(pc, d, "approve-contract", "--id", "CP-003", "--note", asks.user("contract", "정책 문구 추가 계약 승인(시뮬레이션)"))
    for f in P.PLANNING:
        p = d / f
        t = p.read_text().replace("revision: 2", "revision: 3", 1)
        if f.endswith("05-acceptance-criteria.md"):
            t = t.replace("### AC-003: 버튼 한 번으로 대진 생성", "### AC-003: 버튼 한 번으로 대진 생성(같은 조건이면 이전 대진 재사용)")
        p.write_text(t)
    P.ok(pc, d, "snapshot-planning", "--id", "CP-003")
    P.ok(pd, d, "change", "open", "--package", "CP-003")
    dd = d / "docs/design/07-design-direction.md"
    dd.write_text(dd.read_text().replace("### VD-002: 둥근 버튼", "### VD-009: 재사용 배지\n- **결정**: 재사용 배지\n- **상태**: 승인\n- **관련**: SCR-002\n### VD-002: 둥근 버튼"))
    code, out = pd(d, "change", "verify", "--id", "CR-003")
    check("S3a 계약에 없는 새 디자인 결정(VD-009) → contract_scope_exceeded로 중단", code == 2 and out["error"] == "contract_scope_exceeded", out)
    c2 = P.contract(root, "c3b", purpose="대진 생성에 같은 입력 재사용 정책 문구 추가 + 재사용 배지(VD-009)", policy="AC-003 문구 + VD-009",
                    ids={"add": [], "modify": ["AC-003"], "remove": []}, keep=["AC-004"], design={"units": ["UXD-002", "VD-009"], "screens": ["SCR-002"], "files": []},
                    build={"rework": [], "regression": ["B2"]}, files=["tests/test_round.py"], tests={"remove": [], "modify": [], "add": []}, risky_ops=[])
    P.ok(pc, d, "amend-contract", "--id", "CP-003", "--contract", c2, "--reason", "새 디자인 결정 VD-009 필요")
    code, out = pc(d, "approve-contract", "--id", "CP-003", "--note", "정책 문구 추가 계약 승인(시뮬레이션)")
    check("S3b 계약 확대 시 이전 계약 승인 문장 재사용 금지(approval_reused)", code == 2 and out["error"] == "approval_reused", out)
    P.ok(pc, d, "approve-contract", "--id", "CP-003", "--note", asks.user("contract-amend", "재사용 배지까지 포함한 개정 계약 승인(시뮬레이션)"))
    code, out = pd(d, "change", "scope", "--id", "CR-003")
    check("S3c 개정 계약 승인 후 같은 변경은 범위 안(에스컬레이션 해소)", code == 0 and not out["escalated"], out)
    check("S3d 새 디자인 결정이 생긴 경우 사용자 개입 +1(계약 1 + 개정 1, 최종 전)", asks.n == 2, asks.log)
    code, out = pc(d, "abandon", "--id", "CP-003", "--reason", "테스트: 시나리오 종료", "--restore")
    check("S3e abandon --restore: 범위 파일을 시작 전 내용으로 되돌림, 디자인 변경 요청 취소", code == 0 and out["status"] == "abandoned"
          and (out.get("design_cr_cancel") or {}).get("code") == 0 and "docs/planning/05-acceptance-criteria.md" in out["restored"], out)
    code, out = pd(d, "check")
    check("S3f 취소 후 디자인·기획 원래 상태(check 일관)", code == 0 and P.ps(d, "check")[0] == 0, out.get("cross_verify"))
    P.BCcommit(d, "CP-003 abandoned (user)")


# ================================================================ S6·위험·미커밋 보호·테스트 완화
def s6_scope(d, root):
    login = d / "src/login/login.py"
    user_wip = login.read_text() + "\n# 사용자 미커밋 작업(패키지 시작 전)\n"
    login.write_text(user_wip)
    c = P.contract(root, "c6", purpose="로그인 실패 처리 정리", policy="코드만", ids={"add": [], "modify": [], "remove": []}, keep=[],
                   design={"units": [], "screens": [], "files": []}, build={"rework": ["B1"], "regression": []}, files=["src/login/**", "tests/test_login.py"],
                   tests={"remove": [], "modify": [], "add": []}, risky_ops=[])
    code, out = pc(d, "open", "--contract", c)
    check("S6a 패키지 시작 전 미커밋 작업을 구분 기록(preexisting_uncommitted)", code == 0 and "src/login/login.py" in out["preexisting_uncommitted"], out)
    P.ok(pc, d, "approve-contract", "--id", "CP-004", "--note", "로그인 정리 계약 승인(시뮬레이션)")
    code, out = pb(d, "batch-start", "--batch", "B1", "--owner", "t")
    check("S8a 계약 밖 위험 작업(security 미허용 배치 시작) → risk_outside_contract", code == 2 and out["error"] == "risk_outside_contract", out)
    (d / "README.md").write_text("# 제품\n범위 밖 수정\n")
    (d / "migrations").mkdir(exist_ok=True)
    (d / "migrations/001.sql").write_text("drop table x;\n")
    code, out = pc(d, "check", "--id", "CP-004")
    check("S6b 계약 밖 문서 수정·마이그레이션(위험 작업) → escalated로 중단", code == 2 and out["error"] == "contract_scope_exceeded"
          and "README.md" in out["items"]["out_of_scope"] and "migrations/001.sql" in out["items"]["risky_not_allowed"], out)
    code, out = pc(d, "submit-final", "--id", "CP-004")
    check("S6c 중단된 패키지는 최종 승인 진행 불가", code == 2, out)
    login.write_text(user_wip + "def extra():\n    return 1\n")  # 패키지 작업(범위 안)
    code, out = pc(d, "abandon", "--id", "CP-004", "--reason", "범위 밖 변경으로 취소", "--restore")
    check("S6d abandon: 시작 전 미커밋 작업 보존(시작 전 내용으로 복원), 범위 밖 파일은 건드리지 않음, 새 파일은 지우지 않음",
          code == 0 and login.read_text() == user_wip and (d / "README.md").read_text().endswith("범위 밖 수정\n") and (d / "migrations/001.sql").exists()
          and any(x["file"] == "README.md" for x in out["skipped"]), out)
    T.G(d, "checkout", "--", "README.md", "src/login/login.py")
    shutil.rmtree(d / "migrations")
    P.BCcommit(d, "CP-004 abandoned (user)")


def s9_tests(d, root):
    c = P.contract(root, "c9", purpose="대진 테스트 정리", policy="AC-004 테스트 단위 삭제만", ids={"add": [], "modify": [], "remove": []}, keep=["AC-003"],
                   design={"units": [], "screens": [], "files": []}, build={"rework": ["B2"], "regression": []}, files=["src/round/**", "tests/test_round.py"],
                   tests={"remove": [{"ac": "AC-004", "paths": ["tests/test_round.py"]}], "modify": [], "add": []}, risky_ops=[])
    P.ok(pc, d, "open", "--contract", c)
    P.ok(pc, d, "approve-contract", "--id", "CP-005", "--note", "테스트 정리 계약 승인(시뮬레이션)")
    t = d / "tests/test_round.py"
    orig = t.read_text()
    weak = orig.replace('self.assertEqual(make(["b", "a"]), ["a", "b"])', 'self.assertTrue(True)  # 완화')
    lock = run_batch(d, "B2", {"tests/test_round.py": weak})
    code, out = pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    check("S9a 계약 밖 테스트 완화(AC-003 assert 약화) → test_changes_outside_contract", code == 2 and out["error"] == "test_changes_outside_contract", out)
    no_ac3 = orig.split("    def test_make")[0] + "    def test_same" + orig.split("    def test_same")[1]
    t.write_text(no_ac3)
    code, out = pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    check("S9b 폐기 AC가 아닌 테스트 단위(AC-003) 삭제 → 차단(같은 파일이어도 단위 기준)", code == 2 and out["error"] == "test_changes_outside_contract", out)
    no_ac4 = orig.split("    def test_same")[0].rstrip() + "\n"
    t.write_text(no_ac4)
    code, out = pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    check("S9c 계약이 승인한 AC-004 테스트 단위 삭제만 → 통과(다시 묻지 않음)", code == 0, out)
    t.write_text(orig)
    P.ok(pb, d, "verify", "--batch", "B2")
    code, out = pc(d, "abandon", "--id", "CP-005", "--reason", "테스트 종료")
    code2, chk = pb(d, "check")
    check("S9d 패키지 취소 시 그 패키지 기준의 배치 검증은 stale(승인 안 된 기준)", code == 0 and chk["batches"]["B2"]["status"] == "stale", chk.get("batches"))
    P.BCcommit(d, "CP-005 abandoned (user)")


def misc(d, root):
    code, out = pd(d, "change", "open", "--request", DC_req(root), "--scope-note", "배너 보정")
    c = P.contract(root, "cx", ids={"add": [], "modify": [], "remove": []})
    code2, out2 = pc(d, "open", "--contract", c)
    check("S10 진행 중 디자인 변경 요청(M1 CR)이 있으면 패키지 시작 차단(transition_in_progress)", code2 == 2 and out2["error"] == "transition_in_progress", out2)
    pd(d, "change", "cancel", "--id", out["id"], "--reason", "테스트")
    raw = (d / ".ai-workflow/change.json").read_text()
    (d / ".ai-workflow/change.json").write_text(raw.replace('"packages": {', '"packages": {"CP-001": {}, ', 1))
    code, out = pc(d, "status")
    check("S11 병합 흔적(change.json 중복 패키지 키) → state_duplicate_keys, 자동 선택 없음", code == 2 and out["error"] == "state_duplicate_keys", out)
    (d / ".ai-workflow/change.json").write_text(raw)


def parse_units() -> None:
    """실제 개정 문서 표기(SMAPSH r14)에서 나온 오탐 회귀: 긴 표 행 본문 속 '폐기' 언급은 폐기 표기가 아니다."""
    sys.path.insert(0, str(P.ENGINE / "skills/product-change/scripts"))
    import pc_graph as G
    old = {"docs/planning/02-prd.md": "| NFR-003 | 정확성 | 같은 경기 0건 | FR-013 |\n| NFR-004 | 성능 | 1초 |\n",
           "docs/planning/05-acceptance-criteria.md": "## AC-164: 취소 경기 복원\n본문\n"}
    new = {"docs/planning/02-prd.md": "| NFR-003 | 정확성 | 같은 경기 0건. (r14) 복원 기능 폐기에 따라 문장 보강 | FR-013 |\n| ~~NFR-004~~ | ~~성능~~ | (r14 폐기) |\n",
           "docs/planning/05-acceptance-criteria.md": "## ~~AC-164~~: ~~취소 경기 복원~~ *(r14에서 폐기)*\n본문\n"}
    dd = G.planning_diff(old, new)
    check("C7 ID 단위 차이: 본문에 '폐기'가 들어간 행(NFR-003)은 modified, 취소선 행(NFR-004)·제목 폐기(AC-164)만 removed",
          dd["modified"] == ["NFR-003"] and dd["removed"] == ["AC-164", "NFR-004"], dd)


def DC_req(root):
    p = root / "m1req.json"
    p.write_text(json.dumps({"items": [{"id": "R1", "summary": "배너", "facts": [{"kind": "asset_patch", "asset": "AST-001", "op": "mask", "successor": True}]}]}))
    return p


def main() -> int:
    if shutil.which("pnpm") is None or not any(Path(x).exists() for x in ("/Applications/Google Chrome.app", "/usr/bin/google-chrome", "/usr/bin/chromium")):
        skip("product-change 전체", "pnpm 또는 Chrome이 없어 프리뷰 빌드·화면 실측을 할 수 없습니다")
        return 0
    root = TMP.mkdtemp("product-change-test-")
    d, ok = P.setup(root)
    if not ok:
        skip("product-change 전체", "프리뷰 빌드 실패(환경)")
        return 0
    parse_units()
    code, out = pc(d, "enable")
    check("E1 enable dry-run(쓰지 않음)", code == 0 and out["dry_run"] and not (d / ".ai-workflow/change.json").exists(), out)
    P.ok(pc, d, "enable", "--confirm", "--note", "변경 패키지 기능을 켭니다(시뮬레이션)")
    P.BCcommit(d, "enable change packages (user)")
    p1_impact(d, root)
    s1_retire(d, root)
    s2_layout(d, root)
    s3_policy(d, root)
    s6_scope(d, root)
    s9_tests(d, root)
    misc(d, root)
    out = os.environ.get("PW_CHANGE_PKG_EVIDENCE")
    if out:
        Path(out).write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=2))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(TMP.run(main))
