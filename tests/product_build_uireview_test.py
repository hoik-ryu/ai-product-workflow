#!/usr/bin/env python3
"""/product-build M3.5 테스트(자체 완결형): UI 배치 필수 조건, browser_pending, UI 검토 묶음, 수정 요청 분류(①–⑤)·해결, UI 최종 승인·무효화.

사례 프로젝트와 무관한 독립 픽스처(도서관 좌석 예약). M3.3·M3.4 테스트의 픽스처·테스트 실행기·브라우저 대역을 재사용합니다.
실행: python3 tests/product_build_uireview_test.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_build_ui_test as UT  # noqa: E402
import product_build_uiev_test as UE  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G
w, st, res, scenario, verify = UE.w, UE.st, UE.res, UE.scenario, UE.verify

ALL_TESTS = ["case passed [SCR-001-ST1] [AC-001] 빈 좌석이 보인다",
             "case passed [SCR-001-ST2] 좌석을 불러오는 중 표시",
             "case passed [SCR-001-ST3] [AC-002] 오류 시 다시 시도 안내",
             "case passed [AC-002] 빈 좌석이 없으면 대기 안내",
             "case passed [SCR-002-ST1] [AC-003] 좌석을 고르면 예약이 확정된다",
             "case passed [SCR-002-ST2] 확정 중 버튼 비활성",
             "case passed [SCR-002-ST3] [AC-004] 중복 예약 거부(409)"]
BROWSER_OK = [res("SCR-001-ST1", acs=["AC-001"], interactions=[{"name": "좌석 선택", "passed": True}]),
              res("SCR-002-ST1", interactions=[{"name": "예약 확정", "passed": True}])]


def review(d, bid="B1"):
    return pb(d, "ui-review", "--batch", bid)


def approve(d, rid, by="도서관 운영 담당", note="화면을 직접 확인했고 승인합니다", bid="B1"):
    args = ["approve", "batch", "--batch", bid, "--note", note]
    if rid:
        args += ["--review", rid]
    if by:
        args += ["--by", by]
    return pb(d, *args)


def fb(d, summary, facts, note="사용자 요청 원문", **kw):
    args = ["ui-feedback", "add", "--batch", "B1", "--summary", summary, "--note", note]
    for f in facts:
        args += ["--fact", json.dumps(f, ensure_ascii=False)]
    for k, v in kw.items():
        args += [f"--{k}", v]
    return pb(d, *args)


def flow(root: Path) -> None:
    d = UE.setup(root)
    snap = T.protected_snapshot(d)

    # 비UI(foundation) 배치: UI Brief 없이 시작·검증·승인(M2 경로)
    lock = UE.start(d, "B0")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    UE.finish(d, "B0", lock)
    pb(d, "ui-map", "register", "--cmp", "CMP-002", "--source", "built", "--batch", "B0", "--path", "web/src/components/SeatMap.view",
       "--export", "SeatMap")
    code, out = verify(d, "B0", avail=False)
    check("C0 비UI(foundation) 배치에서 필수 브라우저 단계 미실행은 경고가 아니라 verify 실패(M2 규칙)",
          code == 2 and out["status"] == "verify_failed" and out.get("browser") is None
          and any("검증 단계 browser: not_run" in r for r in out["reasons"]), UE.reasons(out))
    code, out = verify(d, "B0")
    check("C1 foundation 배치는 UI Brief 없이 시작·검증(브라우저 실행 시 verified, UI 판정 없음)",
          code == 0 and out["status"] == "verified" and "ui" not in out, UE.reasons(out))
    code, out = pb(d, "approve", "batch", "--batch", "B0", "--note", "공통 부품을 승인합니다")
    check("C2 비UI 배치 최종 승인은 M2 경로 그대로(검토 묶음·승인 주체 불필요)", code == 0 and out["status"] == "approved", out)

    # UI 배치: UI Brief·검증된 UI Plan 없이는 시작 불가
    code, out = pb(d, "batch-start", "--batch", "B1", "--owner", "t")
    check("R1 UI 배치는 UI Brief 없이 시작 불가(ui_plan_required)", code == 2 and out["error"] == "ui_plan_required"
          and any("ui_brief_missing" in p for p in out["problems"]), out)
    code, bout = pb(d, "ui-brief", "--batch", "B1")
    code, out = pb(d, "batch-start", "--batch", "B1", "--owner", "t")
    check("R2 UI Plan이 없으면 시작 불가", code == 2 and any("ui_plan_missing" in p for p in out.get("problems", [])), out)
    UT.write_ui_plan(d, UT.good_ui_plan(bout["digest"]))
    code, out = pb(d, "batch-start", "--batch", "B1", "--owner", "t")
    check("R3 검증(ui-plan-validate)되지 않은 UI Plan이면 시작 불가", code == 2 and any("ui_plan_not_validated" in p for p in out.get("problems", [])), out)
    pb(d, "ui-plan-validate", "--batch", "B1")
    lock = UE.start(d, "B1")
    check("R4 Brief·검증된 UI Plan이 있으면 시작", bool(lock))
    w(d, "web/src/features/seats/SeatStatusPage.view", "import { Button } from '../../components/Button.view'\nexport const SeatStatusPage = 1\n")
    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = 1\n")
    w(d, "web/src/mocks/seats.data", "A1 free\n")
    UE.tests_file(d, ALL_TESTS)
    UE.finish(d, "B1", lock)

    # 정책 1: 필수 브라우저 단계 미실행 → verify 완료 + browser_pending, UI 승인 차단
    code, out = verify(d, avail=False)
    check("P1 필수 상태 E2·AC 통과 + 브라우저 미실행 → verified + browser_pending", code == 0 and out["status"] == "verified"
          and out.get("browser") == "browser_pending" and out["ui"]["browser"]["status"] == "browser_pending", UE.reasons(out))
    code, rv = review(d)
    check("P2 검토 묶음: browser_pending이 승인 차단 항목, ready=false", code == 0 and not rv["ready"]
          and any("browser_pending" in x for x in rv["blockers"]), rv.get("blockers"))
    code, out = approve(d, rv["review_id"])
    check("P3 브라우저 미실행 상태에서 승인 우회 불가(ui_approval_blocked)", code == 2 and out["error"] == "ui_approval_blocked", out)
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "승인합니다")
    check("P4 --review·--by 없이 M2 방식으로도 우회 불가", code == 2 and out["error"] in ("approver_required", "ui_approval_blocked"), out)
    scenario(d, "ok", [res("SCR-001-ST1", interactions=[{"name": "좌석 선택", "passed": False}])])
    code, out = verify(d)
    check("P5 브라우저 실패는 기존대로 verify 실패", code == 2 and out["status"] == "verify_failed"
          and any("interaction_failed" in r for r in out["reasons"]), UE.reasons(out))
    scenario(d, "bad_json")
    code, out = verify(d)
    check("P6 잘못된 리포트도 verify 실패(browser_pending 아님)", code == 2 and out["run"]["steps"]["browser"]["status"] == "report_invalid"
          and out.get("browser") is None, out["run"]["steps"].get("browser"))

    # 브라우저 실행 → 검토 묶음 → 승인
    scenario(d, "ok", BROWSER_OK)
    code, out = verify(d)
    check("A1 브라우저 통과 → verified, browser passed", code == 0 and out["ui"]["browser"]["status"] == "passed", UE.reasons(out))
    code, rv = review(d)
    s1 = rv["screens"]["SCR-001"]
    check("A2 검토 묶음: 화면별 상태 증거(출처)·브라우저 결과·AC·토큰·컴포넌트 대응", code == 0 and rv["ready"]
          and s1["states"]["SCR-001-ST1"]["sources"] == ["browser", "test"] and s1["states"]["SCR-001-ST1"]["browser"][0]["viewport"] == "mobile"
          and s1["acs"]["AC-001"]["status"] == "verified" and rv["tokens"]["now"]["ok"]
          and rv["components"]["CMP-001"]["source"] == "existing" and rv["components"]["CMP-002"]["source"] == "built", rv.get("blockers"))
    check("A3 검토 묶음 기록 파일", (d / ".ai-workflow/build/ui/B1/review.json").is_file())
    code, out = approve(d, rv["review_id"], by="")
    check("A4 승인 주체(--by) 없으면 거부", code == 2 and out["error"] == "approver_required", out)
    code, out = approve(d, "0000000000000000")
    check("A5 지금 검토 묶음과 다른 ID로는 승인 불가(review_mismatch)", code == 2 and out["error"] == "review_mismatch", out)
    code, out = approve(d, rv["review_id"])
    ap = st(d)["batches"]["B1"]["approvals"][-1]
    check("A6 사용자 UI 승인 → approved, 기록에 검토 묶음·승인 주체·시각·코드 버전·UI 증거 연결", code == 0 and out["status"] == "approved"
          and ap["ui"]["review_id"] == rv["review_id"] and ap["by"] == "도서관 운영 담당" and ap["at"] and ap["ui"]["code"]["head"]
          and ap["ui"]["scope_tree"] and ap["ui"]["evidence_digest"] and ap["ui"]["ui_plan_sha"], ap)
    code, out = verify(d)
    check("A7 같은 코드·같은 UI 증거로 재검증 → 승인 유지", code == 0 and out["status"] == "approved", out.get("status"))
    code, out = verify(d, avail=False)
    check("A8 재검증에서 브라우저 미실행(browser_pending) → 승인 무효, verified로", code == 0 and out["status"] == "verified"
          and st(d)["batches"]["B1"]["approvals"][-1]["valid"] is False, out.get("status"))
    code, out = verify(d)
    code, rv = review(d)
    code, out = approve(d, rv["review_id"])
    check("A9 다시 검토·승인", code == 0 and out["status"] == "approved", out)

    # 승인 뒤 변경 → 승인 유효성 재검사
    tp = d / "web/src/styles/tokens.css"
    orig = tp.read_text()
    tp.write_text(orig.replace("--radius-md: 8px", "--radius-md: 6px"))
    pb(d, "check")
    b1 = st(d)["batches"]["B1"]
    check("S1 승인 뒤 토큰 출력 파일 변경(다른 배치 범위) → B1 stale, 승인 무효", b1["status"] == "stale" and b1["approvals"][-1]["valid"] is False
          and "토큰" in b1["verification"]["stale_reason"], b1["verification"].get("stale_reason"))
    code, rv = review(d)
    check("S2 검토 묶음: stale·토큰 불일치가 차단 항목", any("stale" in x for x in rv["blockers"]) and any("토큰 불일치" in x for x in rv["blockers"]), rv["blockers"])
    tp.write_text(orig)
    verify(d, "B0")  # 토큰 파일은 B0 범위(shared)라 B0도 stale → 다시 검증
    code, out = verify(d)
    code, rv = review(d)
    approve(d, rv["review_id"])
    up = json.loads((d / ".ai-workflow/build/ui/B1/plan.json").read_text())
    up["notes"] = ["승인 뒤 메모"]
    up["screens"]["SCR-001"]["states"]["SCR-001-ST2"]["ref"] = "loading=true(변경)"
    UT.write_ui_plan(d, up)
    pb(d, "check")
    b1 = st(d)["batches"]["B1"]
    check("S3 승인 뒤 UI Plan 변경 → stale, 승인 무효(영향 화면 표시)", b1["status"] == "stale" and b1["approvals"][-1]["valid"] is False
          and "SCR-001" in b1["verification"]["stale_reason"], b1["verification"].get("stale_reason"))
    code, out = approve(d, rv["review_id"])
    check("S4 stale 상태에서 승인 불가", code == 2 and out["error"] == "not_verified", out)
    pb(d, "ui-plan-validate", "--batch", "B1")
    verify(d)
    code, rv = review(d)
    code, out = approve(d, rv["review_id"])
    check("S5 UI Plan 재검증·재검증 후 재승인", code == 0 and out["status"] == "approved", out)

    # 수정 요청 ① 결함(코드 수정)
    code, out = fb(d, "좌석 선택 후 확인 화면 제목이 명세와 다릅니다", [{"kind": "defect", "screen": "SCR-002"}], screen="SCR-002")
    b1 = st(d)["batches"]["B1"]
    check("F1 결함 → code_fix, 승인 뒤 요청이면 승인 무효·verified", code == 0 and out["feedback"]["route"] == "code_fix"
          and out["feedback"]["category"] == "결함" and b1["status"] == "verified" and b1["approvals"][-1]["valid"] is False, out)
    check("F2 코드 수정 요청은 기획·디자인 승인을 바꾸지 않음(계획 승인 유지)", st(d)["plan"]["status"] == "approved" and T.protected_snapshot(d) == snap)
    code, rv = review(d)
    code2, out2 = approve(d, rv["review_id"])
    check("F3 열린 수정 요청이 있으면 승인 불가", not rv["ready"] and any("FB-001" in x for x in rv["blockers"]) and code2 == 2, rv["blockers"])
    code, out = pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-001", "--note", "고쳤습니다")
    check("F4 고치고 다시 검증하기 전에는 해결로 기록 불가", code == 2 and out["error"] in ("not_reverified", "code_unchanged"), out)
    code, out = pb(d, "resume", "--batch", "B1", "--owner", "t3")
    lock = out.get("lock_id")
    check("F5 code_fix 요청이 있는 verified 배치를 resume으로 다시 엶", code == 0 and lock, out)
    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = 1 // 제목: 예약 확인\n")
    pb(d, "checkpoint", "--batch", "B1", "--lock", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    code, out = verify(d)
    code, out = pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-001", "--note", "수정된 화면을 확인했습니다")
    check("F6 코드 수정·재검증 뒤 해결(실행 ID·코드 버전 기록)", code == 0 and out["status"] == "resolved" and out["resolution"]["kind"] == "code_fixed"
          and out["resolution"]["run_id"], out)

    # ⑤ 구현 메모 → code_fix, ① 정보·행동 → design_change, 미확정 → 사용자 결정
    code, out = fb(d, "로딩 표시 컴포넌트 이름 정리", [{"kind": "implementation_note"}])
    check("F7 ⑤ 구현 메모 → code_fix", code == 0 and out["feedback"]["route"] == "code_fix" and "⑤" in out["feedback"]["category"], out)
    pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-002", "--withdraw", "--reason", "필요 없음", "--note", "요청을 거둡니다")
    code, out = fb(d, "좌석 현황에 층 정보를 추가해 주세요", [{"kind": "info", "op": "add", "screen": "SCR-001"}], screen="SCR-001")
    cls = out.get("classification") or {}
    check("F8 ① 정보 추가 → design_change, 재승인 단계(ux_spec)와 소유 Skill 절차 안내, 코드로 바꾸지 않음",
          code == 0 and out["feedback"]["route"] == "design_change" and "①" in out["feedback"]["category"]
          and "ux_spec" in (cls.get("reapproval_stages") or []) and "reopen" in out["next"], out)
    check("F9 분류만으로 디자인·기획 상태를 바꾸지 않음", T.protected_snapshot(d) == snap and st(d)["plan"]["status"] == "approved")
    code, out = pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-003", "--note", "반영됐습니다")
    check("F10 디자인 재승인 없이 design_change 해결 불가", code == 2 and out["error"] == "design_not_reapproved", out)
    code, out = pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-003", "--withdraw", "--reason", "다음 버전으로", "--note", "이번에는 하지 않습니다")
    check("F11 사용자가 요청을 거두면 withdrawn(기록 유지)", code == 0 and out["status"] == "withdrawn", out)
    code, out = fb(d, "시간 표기를 바꿔 주세요", [{"kind": "notation", "screen": "SCR-002"}])
    check("F12 판단 필요(needs_review) → needs_decision", code == 0 and out["feedback"]["route"] == "needs_decision"
          and out["feedback"]["status"] == "needs_decision", out)
    code, out = pb(d, "ui-feedback", "decide", "--batch", "B1", "--id", "FB-001", "--route", "code_fix", "--note", "x")
    check("F13 확정된 요청의 경로는 바꿀 수 없음", code == 2 and out["error"] == "not_needs_decision", out)
    code, out = pb(d, "ui-feedback", "decide", "--batch", "B1", "--id", "FB-004", "--route", "design_change", "--note", "명세의 표기 규칙을 바꾸는 요청입니다")
    check("F14 사용자 결정으로 경로 확정", code == 0 and out["route"] == "design_change", out)
    pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-004", "--withdraw", "--reason", "보류", "--note", "보류합니다")
    code, out = fb(d, "버튼 모서리를 더 둥글게", [{"kind": "style", "property": "radius", "component": "CMP-001", "screen": "SCR-001"}])
    cls = out.get("classification") or {}
    check("F15 ④ 시각 표현: 재승인 필요 여부에 따라 경로(필요하면 design_change, 아니면 code_fix)",
          code == 0 and "④" in out["feedback"]["category"]
          and out["feedback"]["route"] == ("design_change" if cls.get("reapproval_required") else "code_fix"), (out.get("feedback"), cls.get("reapproval_stages")))
    pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-005", "--withdraw", "--reason", "보류", "--note", "보류합니다")
    code, out = pb(d, "ui-feedback", "add", "--batch", "B1", "--summary", "x", "--fact", '{"kind":"defect"}')
    check("F16 사용자 원문 없는 수정 요청 거부", code == 2 and out["error"] == "approval_statement_required", out)

    code, rv = review(d)
    code, out = approve(d, rv["review_id"])
    check("F17 수정 요청을 모두 해결·철회한 뒤 재승인", code == 0 and out["status"] == "approved", (out, rv.get("blockers")))
    code, out = pb(d, "ui-feedback", "list", "--batch", "B1")
    check("F18 수정 요청 이력 유지(해결·철회 포함)", [f["status"] for f in out["feedback"]["B1"]] == ["resolved", "withdrawn", "withdrawn", "withdrawn", "withdrawn"],
          [f["status"] for f in out["feedback"]["B1"]])

    # EM이 stale이면 승인 차단(수동 근거가 현재 코드와 다름)
    pb(d, "evidence-manual", "add", "--batch", "B1", "--state", "SCR-001-ST2", "--check", "스크린리더로 로딩 안내 확인", "--method", "screen_reader",
       "--result", "passed", "--note", "직접 확인했습니다")
    verify(d)
    code, rv = review(d)
    check("E1 EM 추가 → 재검증 대상, 재검증 후 EM은 유효(차단 없음)", rv["ready"] and rv["manual"][0]["status_now"] == "active", rv["blockers"])
    code, out = pb(d, "resume", "--batch", "B1", "--owner", "t4")
    code2, out2 = fb(d, "확정 버튼 문구 오타", [{"kind": "defect"}])
    lock = pb(d, "resume", "--batch", "B1", "--owner", "t4")[1].get("lock_id")
    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = 2 // 문구 수정\n")
    pb(d, "checkpoint", "--batch", "B1", "--lock", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    verify(d)
    pb(d, "ui-feedback", "resolve", "--batch", "B1", "--id", "FB-006", "--note", "확인했습니다")
    code, rv = review(d)
    check("E2 코드가 바뀌어 EM이 stale → 승인 차단(다시 확인하거나 철회)", not rv["ready"] and any("수동 증거" in x for x in rv["blockers"]), rv["blockers"])

    check("P9 승인 문서·state.yaml·design.json·프리뷰 불변", T.protected_snapshot(d) == snap)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-uireview-test-"))
    try:
        flow(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
