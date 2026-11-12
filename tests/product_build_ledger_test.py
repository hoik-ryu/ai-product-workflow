#!/usr/bin/env python3
"""/product-build M2.4b 테스트(자체 완결형): 정책·편차 원장, 차단 정책, decide, 문서 반영 대기열.

도서관 좌석 예약 픽스처(product_build_verify_test.py)를 씁니다. 코드·테스트는 Claude 대신 이 테스트가 씁니다.
실행: python3 tests/product_build_ledger_test.py
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
import product_build_verify_test as VT  # noqa: E402

results = T.results
check, pb = T.check, T.pb
st, w, start, done_all = VT.st, VT.w, VT.start, VT.done_all


def led(d):
    return json.loads((d / ".ai-workflow/build/ledger.json").read_text())


def item(d, iid):
    return next(i for i in led(d)["items"] if i["id"] == iid)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-ledger-test-"))
    try:
        flow(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


def flow(root: Path) -> None:
    d = VT.setup(root)
    snap = T.protected_snapshot(d)
    lock = start(d, "B0")
    w(d, "src/common/button.py", "def button(x):\n    return f'[{x}]'\n")
    done_all(d, "B0", lock)
    pb(d, "batch-submit", "--batch", "B0", "--lock", lock)
    pb(d, "verify", "--batch", "B0")

    # ---- 분류 규칙
    code, out = pb(d, "ledger", "add", "--type", "evidence_gap", "--title", "AC-001 테스트 없음", "--acs", "AC-001", "--blocking")
    check("L1 검증 증거 부족은 차단 정책으로 만들 수 없음(정책 미결정과 구분)", code == 2 and out.get("error") == "evidence_gap_not_policy", out)
    code, out = pb(d, "ledger", "add", "--type", "deviation", "--title", "x", "--category", "⑨")
    check("L1a 편차 분류는 WF-D01 ①–⑤만", code == 2 and out.get("error") == "invalid_category", out)

    # ---- 실행 중 배치에 새 차단 정책 → 체크포인트에서 멈춤, 관련 없는 독립 배치는 진행
    lock = start(d, "B1")
    w(d, "src/seats/seats.py", VT.SEATS_OK)
    code, out = pb(d, "ledger", "add", "--type", "policy", "--title", "예약 확정 전 결제 필요 여부", "--desc", "AC-003 확정 조건이 기획에 없음",
                   "--acs", "AC-003", "--blocking", "--rationale", "결제·외부 계약에 해당(되돌리기 어려움)", "--docs", "docs/planning/05-acceptance-criteria.md")
    pol = out.get("item", {}).get("id")
    check("L2 차단 정책 등록: 관련 AC로 영향 배치 계산(B1)", code == 0 and pol == "POL-001" and out["affected_batches"] == ["B1"], out)
    code, out = pb(d, "task-done", "--batch", "B1", "--task", "B1-T1", "--lock", lock)
    check("L3 실행 중 새 차단 정책 → 작업 기록 후 체크포인트에서 일시 중지(잠금 해제)", code == 0 and out.get("status") == "paused"
          and out["paused_by_policy"] == ["POL-001"] and st(d)["batches"]["B1"]["run"]["tasks"]["B1-T1"]["status"] == "done"
          and not (d / ".ai-workflow/build/lock.json").exists(), out)
    code, out = pb(d, "resume", "--batch", "B1")
    check("L4 미해결 차단 정책 동안 재개 불가", code == 2 and out.get("error") == "blocked_by_policy", out)
    code, out = pb(d, "batch-start", "--batch", "B3", "--confirm-risk", "--note", "확인")
    lock3 = out.get("lock_id")
    check("L5 관련 없는 독립 배치(B3)는 진행 가능(정책 대기 배치는 활성 배치로 세지 않음)", code == 0 and lock3, out)
    pb(d, "pause", "--batch", "B3", "--lock", lock3)

    # ---- decide: 조회·미리보기(기록 없음)·사용자 결정(원문·확인 필요)
    before = (d / ".ai-workflow/build/ledger.json").read_text()
    code, out = pb(d, "decide")
    check("L6 decide 목록: 결정 대상은 정책·편차만, 영향 배치 표시", code == 0 and [x["id"] for x in out["open"]] == ["POL-001"]
          and "B1" in out["open"][0]["affected_batches"], out)
    code, out = pb(d, "decide", "--id", "POL-001", "--decision", "결제 없음")
    check("L7 사용자 원문·확인 없이 결정 기록 안 함(미리보기만, 원장 불변)", code == 0 and out["status"] == "preview"
          and (d / ".ai-workflow/build/ledger.json").read_text() == before, out)
    code, out = pb(d, "decide", "--id", "POL-001", "--decision", "예약 확정에 결제 없음", "--note", "결제는 MVP 범위 밖입니다", "--confirm",
                   "--propose", "docs/planning/05-acceptance-criteria.md::AC-003에 '결제 없이 확정' 문구 추가")
    i = item(d, "POL-001")
    check("L8 결정 기록(사용자 원문, 결정자 user) + 문서 변경 제안 생성(원본 미수정)", code == 0 and i["status"] == "decided"
          and i["decisions"][0]["statement"] == "결제는 MVP 범위 밖입니다" and out["proposals"] == ["DOC-001"] and T.protected_snapshot(d) == snap, out)
    code, out = pb(d, "resume", "--batch", "B1", "--owner", "t")
    lock = out.get("lock_id")
    check("L9 결정 후 재개 가능", code == 0 and lock, out)
    w(d, "tests/test_seats.py", VT.TEST_SEATS_V2)
    done_all(d, "B1", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    pb(d, "approve", "batch", "--batch", "B1", "--note", "최종 승인")
    check("L10 결정 뒤에도 검증·최종 승인은 정상 절차로", code == 0 and st(d)["batches"]["B1"]["status"] == "approved", out.get("reasons"))

    # ---- 결정 변경: 새 이력, 원문 보존, 관련 배치 재검증·승인 무효 표시
    orig_desc = item(d, "POL-001")["description"]
    code, out = pb(d, "decide", "--id", "POL-001", "--decision", "예약 확정 시 보증금 결제", "--note", "보증금을 받기로 바꿉니다", "--confirm")
    i = item(d, "POL-001")
    b1 = st(d)["batches"]["B1"]
    check("L11 결정 변경 = 새 이력(supersedes), 원래 설명·첫 결정 보존", code == 0 and len(i["decisions"]) == 2 and i["decisions"][1]["supersedes"] == 1
          and i["decisions"][0]["decision"] == "예약 확정에 결제 없음" and i["description"] == orig_desc, i["decisions"])
    check("L12 결정 반영 → 검증·승인된 영향 배치는 재검증 필요(stale), 승인 기록은 무효 표시로 보존", b1["status"] == "stale"
          and b1["approvals"][0]["valid"] is False and out["reverify"] == ["B1"], b1.get("approvals"))
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "다시 승인")
    check("L13 해결돼도 재검증 없이 최종 승인 불가", code == 2 and out.get("error") in ("not_verified", "verification_stale"), out)
    pb(d, "verify", "--batch", "B1")

    # ---- 차단 정책은 최종 승인도 막음
    pb(d, "ledger", "add", "--type", "deviation", "--title", "좌석 지도 대신 목록으로 구현", "--category", "①", "--batches", "B1", "--blocking",
       "--rationale", "① 정보·행동 변경 → UX Spec 개정 필요")
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "승인")
    check("L14 미해결 차단 편차(①)가 있으면 최종 승인 차단", code == 2 and out.get("error") == "blocked_by_policy", out)
    code, out = pb(d, "decide", "--id", "DEV-001", "--decision", "목록 구현을 받아들이고 UX Spec 개정", "--note", "목록이 더 낫습니다. UX Spec을 고쳐 주세요",
                   "--confirm", "--propose", "docs/design/02-screens.md::SCR-001 좌석 지도 → 좌석 목록")
    code2, out2 = pb(d, "approve", "batch", "--batch", "B1", "--note", "승인")
    check("L15 편차 결정 → 영향 배치 재검증 필요(결정 뒤 바로 승인 불가)", code == 0 and out["reverify"] == ["B1"] and code2 == 2, (out, out2))
    pb(d, "verify", "--batch", "B1")
    code2, out2 = pb(d, "approve", "batch", "--batch", "B1", "--note", "승인")
    check("L15a 재검증 뒤 최종 승인", code2 == 0, out2)

    # ---- 문서 반영 대기열: 제안 → 승인 → 적용 확인(소유 Skill 재승인 필요)
    code, out = pb(d, "doc-proposal", "apply-check", "--id", "DOC-001")
    check("L16 승인 전에는 적용 확인 불가(승인과 적용 구분)", code == 2 and out.get("error") == "not_approved", out)
    code, out = pb(d, "doc-proposal", "approve", "--id", "DOC-001")
    check("L17 문서 변경 승인은 사용자 문장 필요", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(d, "doc-proposal", "approve", "--id", "DOC-001", "--note", "AC 문구 변경 승인")
    check("L18 승인 → 소유 Skill로 적용 안내(원본은 그대로)", code == 0 and out["status"] == "approved" and "/product-start" in out["next"]
          and T.protected_snapshot(d) == snap, out)
    code, out = pb(d, "doc-proposal", "apply-check", "--id", "DOC-001")
    check("L19 문서가 아직 바뀌지 않음 → not_applied", code == 2 and out.get("error") == "not_applied", out)
    ac = d / "docs/planning/05-acceptance-criteria.md"
    ac_orig = ac.read_text()
    ac.write_text(ac_orig + "\n<!-- 손으로만 고침 -->\n")
    code, out = pb(d, "doc-proposal", "apply-check", "--id", "DOC-001")
    check("L20 재승인 없이 고친 문서는 적용으로 인정 안 함(승인 해시 불일치)", code == 2 and out.get("error") == "not_reapproved", out)
    ac.write_text(ac_orig)
    code, out = pb(d, "resume", "--batch", "B3", "--owner", "t")  # 진행 중 배치를 마무리해야 계획을 다시 열 수 있음
    check("L20a 멈춘 사이 다른 배치가 바꾼 파일 → 외부 변경으로 보고", code == 2 and out.get("error") == "external_changes", out)
    code, out = pb(d, "resume", "--batch", "B3", "--owner", "t", "--accept-changes", "--note", "B1 작업의 변경 확인")
    lock3 = out.get("lock_id")
    w(d, "src/admin/admin.py", "def add_seat(role, seats, s):\n    seats.append(s)\n")
    done_all(d, "B3", lock3)
    pb(d, "batch-submit", "--batch", "B3", "--lock", lock3)
    code, out = pb(d, "ledger", "add", "--type", "policy", "--title", "B2 작업 분해 변경", "--batches", "B2")
    pol2 = out["item"]["id"]
    code, out = pb(d, "decide", "--id", pol2, "--decision", "B2에 감사 로그 작업 추가", "--note", "감사 로그도 넣어 주세요", "--confirm",
                   "--propose", "docs/build/implementation-plan.json::B2에 감사 로그 작업 추가")
    pr_plan = out["proposals"][0]
    pb(d, "doc-proposal", "approve", "--id", pr_plan, "--note", "계획 변경 승인")
    plan = json.loads((d / "docs/build/implementation-plan.json").read_text())
    pb(d, "reopen", "plan", "--reason", pr_plan)
    plan["batches"][2]["tasks"].append({"id": "B2-T2", "layer": "be", "title": "감사 로그", "depends_on": ["B2-T1"]})
    T.save_plan(d, plan)
    pb(d, "submit", "plan")
    pb(d, "approve", "plan", "--revision", "2", "--note", "계획 r2 승인")
    code, out = pb(d, "doc-proposal", "apply-check", "--id", pr_plan)
    check("L21 구현 계획 제안: 계획 재제출·재승인 뒤 적용 확인(applied)", code == 0 and out["status"] == "applied", out)
    b1 = st(d)["batches"]["B1"]
    check("L21a 계획 재승인 뒤에도 기존 배치의 실행·검증·승인 기록 보존", b1["status"] == "approved" and b1.get("run") and b1.get("verification")
          and len(b1.get("approvals", [])) >= 2 and st(d)["batches"]["B0"]["status"] == "verified", {k: b1.get(k) is not None for k in ("run", "verification", "approvals")})

    # ---- sync: 증거 부족·목표 변경·TODO(POL)
    lock = start(d, "B2", "--confirm-risk", "--note", "확인")
    w(d, "src/reservations/cancel.py", "def cancel(seat, taken):\n    # TODO(POL): 취소 마감 시간 미정(임시 0분)\n    taken.discard(seat)\n")
    done_all(d, "B2", lock)
    pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    pb(d, "verify", "--batch", "B2")
    code, out = pb(d, "ledger", "sync")
    evd = [i for i in led(d)["items"] if i["type"] == "evidence_gap" and i["status"] == "open"]
    todo = [i for i in led(d)["items"] if i["source"].get("kind") == "todo_pol"]
    check("L22 sync: 검증 증거 부족 → evidence_gap(비차단), TODO(POL) → 비차단 정책(B2)", code == 0 and any("AC-005" in i["related"]["acs"] for i in evd)
          and all(not i["blocking"] for i in evd) and todo and todo[0]["related"]["batches"] == ["B2"] and not todo[0]["blocking"]
          and todo[0]["provisional"].startswith("취소 마감"), out)
    pb(d, "target", "--batch", "B2", "--ac", "AC-005", "--level", "E2", "--reason", "테스트 보강 예정", "--note", "사용자 승인: E2로")
    w(d, "tests/test_reservations.py", 'import unittest\nfrom reservations.cancel import cancel\n\n\nclass C(unittest.TestCase):\n'
      '    def test_cancel(self):\n        """[AC-005] 내 예약을 삭제하면 좌석이 다시 빈다"""\n        t = {"A1"}\n        cancel("A1", t)\n        self.assertNotIn("A1", t)\n')
    code, out = pb(d, "resume", "--batch", "B2", "--owner", "t", "--accept-changes", "--note", "테스트 추가")
    lock = out.get("lock_id")
    pb(d, "checkpoint", "--batch", "B2", "--lock", lock)
    pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    pb(d, "verify", "--batch", "B2")
    code, out = pb(d, "ledger", "sync")
    tgt = [i for i in led(d)["items"] if i["type"] == "target_change"]
    closed = [i for i in led(d)["items"] if i["type"] == "evidence_gap" and "AC-005" in i["related"]["acs"]]
    check("L23 sync: 목표 변경 승인 → target_change(결정됨, 사용자 원문), 증거가 채워진 evidence_gap은 닫힘(이력)", tgt and tgt[0]["status"] == "decided"
          and tgt[0]["decisions"][0]["statement"] == "사용자 승인: E2로" and closed and closed[0]["status"] == "closed" and closed[0]["history"], out)
    code, out = pb(d, "ledger", "sync")
    check("L24 sync 멱등(중복 항목 없음)", code == 0 and not out["added"], out)
    code, out = pb(d, "decide", "--id", evd[0]["id"])
    check("L25 검증 증거 부족은 decide 대상 아님", code == 2 and out.get("error") == "not_decidable", out)
    code, out = pb(d, "ledger", "dismiss", "--id", todo[0]["id"], "--reason", "중복")
    check("L26 기각은 사유·사용자 문장 필요", code == 2 and out.get("error") == "approval_statement_required", out)

    # ---- 무결성
    raw = (d / ".ai-workflow/build/ledger.json").read_text()
    j = json.loads(raw)
    j["items"][0]["description"] = "몰래 바꾼 설명"
    (d / ".ai-workflow/build/ledger.json").write_text(json.dumps(j))
    code, out = pb(d, "ledger", "list")
    check("L27 원문 수정 → ledger_invalid(원문은 이력으로만)", code == 2 and out.get("error") == "ledger_invalid", out)
    j = json.loads(raw)
    j["items"][0]["decisions"] = [{"seq": 1, "decision": "x", "at": "x"}]
    (d / ".ai-workflow/build/ledger.json").write_text(json.dumps(j))
    code, out = pb(d, "status")
    check("L28 사용자 문장 없는 결정 기록 → ledger_invalid", code == 2 and out.get("error") == "ledger_invalid", out)
    (d / ".ai-workflow/build/ledger.json").write_text(raw)
    code, out = pb(d, "status")
    check("L29 status에 원장 요약(미결·차단·문서 대기열)", code == 0 and "ledger" in out and out["ledger"]["proposals_pending"], out.get("ledger"))
    view = (d / "docs/build/10-decisions.md").read_text()
    check("L30 사람용 보기 생성(유형별·문서 반영 대기열)", "정책 미결정" in view and "문서 반영 대기열" in view and "검증 증거 부족" in view)
    check("L31 승인 문서·state.yaml 불변", T.protected_snapshot(d) == snap)


if __name__ == "__main__":
    sys.exit(main())
