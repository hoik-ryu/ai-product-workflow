#!/usr/bin/env python3
"""/product-build M2.4 테스트(자체 완결형): E3 증거 유형·기존 구현 등록·목표 변경 승인·최종 사용자 승인·영향 분석·무효화.

도서관 좌석 예약 픽스처(product_build_verify_test.py와 같은 실행기·프로필)를 씁니다. 코드·테스트는 Claude 대신 이 테스트가 씁니다.
실행: python3 tests/product_build_approval_test.py
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

CANCEL_TEST_WRONG = ('import unittest\nfrom reservations.cancel import cancel\n\n\nclass C(unittest.TestCase):\n    def test_cancel(self):\n'
                     '        """[AC-005] 내 예약을 삭제하면 좌석이 다시 빈다"""\n        t = {"A1"}\n        cancel("A1", t)\n        self.assertIn("A1", t)  # 잘못된 기대\n')
CANCEL_TEST_RIGHT = CANCEL_TEST_WRONG.replace('        self.assertIn("A1", t)  # 잘못된 기대\n', '        self.assertNotIn("A1", t)\n')


def ev_types(out: dict, ac: str) -> list[str]:
    return [x["type"] for x in out.get("acs", {}).get(ac, {}).get("evidence", [])]


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-approval-test-"))
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

    # ---- G1 실제 결함 수정(테스트 먼저) → fix 유형, E3
    lock = start(d, "B1")
    w(d, "src/seats/seats.py", VT.SEATS_BUG)
    w(d, "tests/test_seats.py", VT.TEST_SEATS_V2)
    pb(d, "verify", "--batch", "B1", "--lock", lock)
    w(d, "src/seats/seats.py", VT.SEATS_OK)
    done_all(d, "B1", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    check("G1 테스트 먼저 실패 → 코드 수정 → 통과: 증거 유형 fix(E3)", code == 0 and ev_types(out, "AC-003") == ["fix"] and out["acs"]["AC-003"]["level"] == "E3"
          and ev_types(out, "AC-001") == [] and out["acs"]["AC-001"]["level"] == "E2", out.get("acs"))

    # ---- G2 실패와 통과 사이에 테스트 기대값을 바꿈 → test_changed(E3 아님) → 목표 변경은 사용자 승인으로만
    lock = start(d, "B2", "--confirm-risk", "--note", "사용자 확인: 예약 삭제")
    w(d, "src/reservations/cancel.py", "def cancel(seat, taken):\n    taken.discard(seat)\n")
    w(d, "tests/test_reservations.py", CANCEL_TEST_WRONG)
    pb(d, "verify", "--batch", "B2", "--lock", lock)
    w(d, "tests/test_reservations.py", CANCEL_TEST_RIGHT)
    done_all(d, "B2", lock)
    pb(d, "batch-submit", "--batch", "B2", "--lock", lock, "--confirm-test-changes", "--note", "확인")
    code, out = pb(d, "verify", "--batch", "B2")
    check("G2 실패 뒤 테스트 기대값을 바꿔 통과 → test_changed 유형, E3 아님(insufficient)", code == 2 and "test_changed" in ev_types(out, "AC-005")
          and out["acs"]["AC-005"]["status"] == "insufficient", out.get("acs"))
    code, out = pb(d, "target", "--batch", "B2", "--ac", "AC-005", "--level", "E2", "--reason", "기존 동작 확인 위주")
    check("G3 목표 변경은 사용자 승인 문장 없이는 거부(자동 하향 없음)", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(d, "target", "--batch", "B2", "--ac", "AC-005", "--level", "E2", "--reason", "테스트 수정 이력 때문에 E3 증거 불가",
                   "--note", "사용자 승인: AC-005 목표를 E2로 낮춤")
    b2 = st(d)["batches"]["B2"]
    check("G3a 승인된 목표 변경: 원래 목표(ac_targets) 유지 + 변경 이력(target_overrides) 추가", code == 0 and b2["ac_targets"]["AC-005"] == "E3"
          and b2["target_overrides"][-1]["to"] == "E2" and b2["target_overrides"][-1]["statement"].startswith("사용자 승인"), b2.get("target_overrides"))
    code, out = pb(d, "verify", "--batch", "B2")
    check("G3b 변경된 목표로 재검증 → verified(목표 E2)", code == 0 and out["status"] == "verified" and out["acs"]["AC-005"]["target"] == "E2", out.get("acs"))

    # ---- G4 기존 구현 등록 → E2부터, 위험 AC는 기존 구현 안내와 함께 insufficient
    w(d, "src/admin/admin.py", "def add_seat(role, seats, s):\n    if role != 'admin':\n        raise PermissionError\n    seats.append(s)\n")
    w(d, "tests/test_admin.py", 'import unittest\nfrom admin.admin import add_seat\n\n\nclass A(unittest.TestCase):\n'
      '    def test_perm(self):\n        """[AC-006] 권한 없는 사용자는 좌석 관리 불가"""\n        with self.assertRaises(PermissionError):\n            add_seat("member", [], "A9")\n\n'
      '    def test_add(self):\n        """[AC-007] 관리자는 좌석을 추가"""\n        s = []\n        add_seat("admin", s, "A9")\n        self.assertEqual(s, ["A9"])\n')
    code, out = pb(d, "adopt-register", "--batch", "B3")
    check("G4 기존 구현 등록은 사용자 확인 문장 필요", code == 2 and out.get("error") == "confirmation_required", out)
    code, out = pb(d, "adopt-register", "--batch", "B3", "--note", "사용자 확인: 관리 화면은 이미 구현됨")
    check("G4a 등록 → imported(구현 이력·검증·승인 아님)", code == 0 and st(d)["batches"]["B3"]["status"] == "imported"
          and st(d)["batches"]["B3"]["run"]["submitted"]["kind"] == "adopt", out)
    code, out = pb(d, "verify", "--batch", "B3")
    check("G4b 기존 구현 검증: E2 확보, 목표 E3 AC는 기존 구현 안내와 함께 insufficient(목표 자동 하향 없음)", code == 2
          and out["acs"]["AC-006"]["level"] == "E2" and "기존 구현" in out["acs"]["AC-006"]["reason"] and out["acs"]["AC-006"]["target"] == "E3", out.get("acs"))

    # ---- G5 최종 사용자 승인
    code, out = pb(d, "approve", "batch", "--batch", "B1")
    check("G5 최종 승인은 승인 문장 필요", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(d, "approve", "batch", "--batch", "B3", "--note", "승인")
    check("G5a 검증되지 않은 배치는 최종 승인 불가(검증≠승인)", code == 2 and out.get("error") == "not_verified", out)
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "사용자 승인: 좌석 기능 확인")
    check("G5b verified 배치 최종 승인 → approved, 승인 기록(실행·범위 해시 포함)", code == 0 and st(d)["batches"]["B1"]["status"] == "approved"
          and st(d)["batches"]["B1"]["approvals"][0]["valid"] and st(d)["batches"]["B1"]["approvals"][0]["run_id"], out)
    code, out = pb(d, "verify", "--batch", "B1")
    check("G5c 같은 코드로 재검증 → 최종 승인 유지", code == 0 and st(d)["batches"]["B1"]["status"] == "approved", out.get("status"))

    # ---- G6 영향 분석: 관련 배치만 재검증, 후속 배치 차단
    w(d, "src/seats/seats.py", VT.SEATS_OK + "# 변경\n")
    code, out = pb(d, "impact")
    check("G6 B1 범위 변경 → B1만 재검증 대상, B2는 후속 차단, B0는 영향 없음", code == 0 and set(out["reverify"]) == {"B1"}
          and out["downstream_blocked"].get("B2") == ["B1"] and "B0" in out["unaffected_verified"], out)
    pb(d, "check")
    b1 = st(d)["batches"]["B1"]
    check("G6a 무효화: approved → stale, 승인 기록은 지우지 않고 무효 표시", b1["status"] == "stale" and len(b1["approvals"]) == 1
          and b1["approvals"][0]["valid"] is False and b1["approvals"][0]["invalidations"], b1.get("approvals"))
    code, out = pb(d, "approve", "batch", "--batch", "B2", "--note", "승인")
    check("G6b 선행 배치(B1) 재검증 전에는 후속 배치(B2) 최종 승인 불가", code == 2 and out.get("error") == "upstream_not_verified", out)
    pb(d, "verify", "--batch", "B1")
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "사용자 승인: 변경 후 재확인")
    check("G6c 재검증 → verified(승인은 새로) → 재승인 시 승인 이력 2건(첫 건은 무효로 남음)", code == 0 and len(st(d)["batches"]["B1"]["approvals"]) == 2
          and [x["valid"] for x in st(d)["batches"]["B1"]["approvals"]] == [False, True], st(d)["batches"]["B1"]["approvals"])

    # ---- G7 의존성 파일 변경: 디렉터리 기준으로 관련 배치만
    w(d, "tools/package.json", '{"name": "tools"}\n')
    code, out = pb(d, "impact")
    check("G7 하위 디렉터리 의존성 파일(tools/package.json)은 그 디렉터리를 쓰는 배치만(없음)", "B1" not in out["reverify"] and "B0" not in out["reverify"], out)
    w(d, "requirements.txt", "requests==2.0\n")
    code, out = pb(d, "impact")
    check("G7a 저장소 루트 의존성 파일 추가 → 검증된 배치 모두 재검증 필요", {"B0", "B1", "B2"} <= set(out["reverify"]), out)
    (d / "requirements.txt").unlink()
    code, out = pb(d, "impact")
    check("G7b 원상 복구하면 재검증 필요 없음", not out["reverify"], out)

    # ---- G8 전이 차단: B0 무효 → B1·B2(간접)까지 후속 차단
    w(d, "src/common/button.py", "def button(x):\n    return f'<{x}>'\n")
    code, out = pb(d, "impact")
    check("G8 B0 변경 → B0 재검증, B1·B2(간접)·B3 후속 차단", set(out["reverify"]) == {"B0"} and set(out["downstream_blocked"]) >= {"B1", "B2", "B3"}
          and "B0" in out["downstream_blocked"]["B2"], out)
    w(d, "src/common/button.py", "def button(x):\n    return f'[{x}]'\n")

    # ---- G9 회귀 후 복구: 같은 코드로 되돌림 = 결함 주입·복구(E3 아님), 다른 코드로 수정 = regression_fix
    code, out = pb(d, "resume", "--batch", "B3", "--owner", "t")
    check("G9-0 등록 뒤 다른 단계의 변경(B1 파일·tools) → resume이 외부 변경으로 보고(덮어쓰지 않음)", code == 2 and out.get("error") == "external_changes", out)
    code, out = pb(d, "resume", "--batch", "B3", "--owner", "t", "--accept-changes", "--note", "사용자 확인: 앞 단계 테스트의 변경")
    lock = out.get("lock_id")
    w(d, "src/seats/seats.py", "def free(seats):\n    return []\n\n\n" + VT.SEATS_OK.split("\n\n\n", 1)[1])
    code, out = pb(d, "verify", "--batch", "B3", "--lock", lock)
    check("G9 다른 배치(B3) 작업 중 B1 테스트 실패 → B1 회귀(stale)", out.get("regressed_batches", {}).get("B1") == ["AC-001"], out.get("regressed_batches"))
    w(d, "src/seats/seats.py", VT.SEATS_OK)
    pb(d, "pause", "--batch", "B3", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    check("G9a 회귀 뒤 이전 통과 때와 같은 코드로 되돌림 → fault_injection(수정이 아니라 복구)", "fault_injection" in ev_types(out, "AC-001"), out.get("acs", {}).get("AC-001"))
    code, out = pb(d, "resume", "--owner", "t", "--accept-changes", "--note", "사용자 확인: B1 재검증 중 변경")
    if code == 2 and out.get("error") != "external_changes":
        code, out = pb(d, "resume", "--owner", "t")
    lock = out.get("lock_id")
    w(d, "src/seats/seats.py", "def free(seats):\n    return []\n\n\n" + VT.SEATS_OK.split("\n\n\n", 1)[1])
    pb(d, "verify", "--batch", "B3", "--lock", lock)
    w(d, "src/seats/seats.py", "def free(seats):\n    # 회귀 수정: 빈 좌석만\n    return [s for s in seats if not s.get('taken')]\n\n\n" + VT.SEATS_OK.split("\n\n\n", 1)[1])
    pb(d, "pause", "--batch", "B3", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    check("G9b 다른 배치 실행에서 감지된 회귀를 새 코드로 수정 → regression_fix(E3)", "regression_fix" in ev_types(out, "AC-001")
          and out["acs"]["AC-001"]["level"] == "E3" and out["status"] == "verified", out.get("acs", {}).get("AC-001"))

    # ---- G10 상태 무결성(우회 차단)
    s0 = (d / ".ai-workflow/build.json").read_text()
    data = json.loads(s0)
    data["batches"]["B0"]["status"] = "approved"
    (d / ".ai-workflow/build.json").write_text(json.dumps(data))
    code, out = pb(d, "status")
    check("G10 사용자 승인 기록 없이 approved로 바꾼 상태 → invalid_state", code == 2 and out.get("error") == "invalid_state", out)
    data = json.loads(s0)
    data["batches"]["B2"]["target_overrides"].append({"ac": "AC-005", "from": "E2", "to": "E1", "at": "x"})
    (d / ".ai-workflow/build.json").write_text(json.dumps(data))
    code, out = pb(d, "status")
    check("G10a 승인 문장 없는 목표 변경 기록 → invalid_state", code == 2 and out.get("error") == "invalid_state", out)
    (d / ".ai-workflow/build.json").write_text(s0)
    code, out = pb(d, "ac-report", "--batch", "B2")
    check("G11 ac-report: 목표 변경 이력·증거 유형 표시", code == 0 and out["batches"]["B2"]["target_overrides"]
          and out["batches"]["B2"]["acs"]["AC-005"]["evidence"], out)
    check("G12 승인 문서·state.yaml 불변", T.protected_snapshot(d) == snap)


if __name__ == "__main__":
    sys.exit(main())
