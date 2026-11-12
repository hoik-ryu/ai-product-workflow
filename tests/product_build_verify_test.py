#!/usr/bin/env python3
"""/product-build M2.3 AC 기반 자동 검증 테스트(자체 완결형).

도서관 좌석 예약 픽스처에 Python 코드·unittest와 `pb-test-report/v1` JSON을 내는 작은 실행기(tools/run_tests.py)를 두고,
verify가 실제로 테스트를 실행해 AC별 증거 수준(E0–E3)을 판정하는지, 리포트 출처·코드 버전·무효화·우회를 검사합니다.
테스트 코드는 Claude 대신 이 테스트가 씁니다.

실행: python3 tests/product_build_verify_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_build_exec_test as X  # noqa: E402

sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
import pb_verify as V  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G

RUNNER = r'''import json, os, pathlib, sys, unittest
sys.path.insert(0, "src")
cases = []
class R(unittest.TestResult):
    def _add(self, t, st):
        mod = t.id().split(".")
        f = "/".join(mod[:-2]) + ".py" if len(mod) > 2 else None
        cases.append({"id": t.id(), "name": t.shortDescription() or t.id(), "file": f, "status": st})
    def addSuccess(self, t): self._add(t, "passed")
    def addFailure(self, t, e): self._add(t, "failed")
    def addError(self, t, e): self._add(t, "error")
    def addSkip(self, t, r): self._add(t, "skipped")
r = R()
unittest.TestLoader().discover("tests", top_level_dir=".").run(r)
out = pathlib.Path(os.environ.get("PB_REPORT_DIR", ".")) / "unit.json"  # 환경 변수가 없으면 저장소 루트(오염 확인용)
out.write_text(json.dumps({"format": "pb-test-report/v1", "tool": "unittest", "cases": cases}, ensure_ascii=False))
sys.exit(0 if all(c["status"] in ("passed", "skipped") for c in cases) else 1)
'''

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["src"]
tests = ["tests"]
components = ["src/common"]
exclude = ["__pycache__"]
[approval]
default = "auto"
waived_ui = "auto"
[execution]
max_retries = 3
lock_ttl_minutes = 30
[[verify.steps]]
name = "unit"
stage = "test"
run = "python3 -B tools/run_tests.py"
cwd = "."
requires = []
report = { format = "pb-json", file = "unit.json" }
[[verify.steps]]
name = "browser"
stage = "browser"
run = "echo e2e"
cwd = "."
requires = ["playwright"]
optional = true
[verify]
tag_style = "bracket"
"""

SEATS_BUG = "def free(seats):\n    return [s for s in seats if not s.get('taken')]\n\n\ndef reserve(seat, taken):\n    return None  # 버그: 아직 구현 안 됨\n"
SEATS_OK = "def free(seats):\n    return [s for s in seats if not s.get('taken')]\n\n\ndef reserve(seat, taken):\n    if seat in taken:\n        raise ValueError('중복 예약')\n    taken.add(seat)\n    return f'R-{seat}'\n"
TEST_SEATS_V1 = '''import unittest
from seats.seats import free, reserve


class Seats(unittest.TestCase):
    def test_free(self):
        """[AC-001] 빈 좌석이 표시된다"""
        self.assertEqual(len(free([{"taken": True}, {"taken": False}])), 1)

    def test_wait(self):
        """AC-002 대기 안내(태그 없이 언급만)"""
        self.assertEqual(free([{"taken": True}]), [])

    def test_reserve(self):
        """[AC-003] 좌석을 고르면 예약이 확정된다"""
        self.assertEqual(reserve("A1", set()), "R-A1")
'''
TEST_SEATS_V2 = TEST_SEATS_V1.replace('"""AC-002 대기 안내(태그 없이 언급만)"""', '"""[AC-002] 빈 좌석이 없으면 대기 안내"""') + '''
    def test_dup(self):
        """[AC-004] 같은 좌석 중복 예약은 거부된다"""
        t = {"A1"}
        with self.assertRaises(ValueError):
            reserve("A1", t)
'''


def st(d):
    return json.loads((d / ".ai-workflow/build.json").read_text())


def w(d, rel, text):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def setup(root: Path) -> Path:
    d = T.make_product(root, "lib-verify", T.LIBRARY)
    w(d, "tools/run_tests.py", RUNNER)
    for pkg in ("src/common/__init__.py", "src/seats/__init__.py", "src/reservations/__init__.py", "src/admin/__init__.py", "tests/__init__.py"):
        w(d, pkg, "")
    w(d, "tests/test_existing.py", "import unittest\n\n\nclass E(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    T.save_plan(d, X.LIB_PLAN)
    pb(d, "waiver", "add", "--reason", "배치 구현", "--all-ui", "--note", "프리뷰 없이 구현 승인", "--confirm")
    code, out = pb(d, "submit", "plan"); assert code == 0, out
    code, out = pb(d, "approve", "plan", "--revision", "1", "--note", "구현 계획 승인"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "plan (user)")
    return d


def start(d, bid, *extra):
    code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t", *extra)
    assert code == 0, out
    return out["lock_id"]


def done_all(d, bid, lock):
    for t in [x for x, v in st(d)["batches"][bid]["run"]["tasks"].items() if v["status"] != "done"]:
        code, out = pb(d, "task-done", "--batch", bid, "--task", t, "--lock", lock)
        assert code == 0, out


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-verify-test-"))
    try:
        unit_checks(root)
        flow(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


# ---------------------------------------------------------------- 리포트 출처·형식(직접 호출)
def unit_checks(root: Path) -> None:
    d = root / "rp"
    d.mkdir()
    G(d, "init", "-q")
    w(d, "src/a.py", "x = 1\n")
    w(d, "README.md", "x\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "i")
    prof = {"paths": {"source": ["src"], "tests": [], "exclude": []}, "verify": {"tag_style": "bracket"}}
    good = 'printf \'{"format":"pb-test-report/v1","cases":[{"name":"[AC-001] ok","status":"passed"}]}\' > "$PB_REPORT_DIR/r.json"'

    def one(step):
        return V.run_steps(d, prof, "B9", [step], set(), 30)["steps"][0]

    s = one({"name": "ok", "run": good, "report": {"format": "pb-json", "file": "r.json"}})
    check("R1 정상: 실행 중 만든 리포트만 수집·해시 기록", s["status"] == "passed" and s["report"]["cases"] == 1 and len(s["report"]["sha256"]) == 64, s)
    s = one({"name": "missing", "run": "true", "report": {"format": "pb-json", "file": "r.json"}})
    check("R2 리포트 미생성 → report_invalid", s["status"] == "report_invalid" and "만들어지지" in s["reason"], s)
    w(d, "out/old.json", '{"format":"pb-test-report/v1","cases":[{"name":"[AC-001] ok","status":"passed"}]}')
    os.utime(d / "out/old.json", (1, 1))
    s = one({"name": "old", "run": "true", "report": {"format": "pb-json", "path": "out/old.json"}})
    check("R3 실행 전에 있던 오래된 리포트(고정 경로) → 거부", s["status"] == "report_invalid" and "오래된" in s["reason"], s)
    s = one({"name": "same", "run": "touch out/old.json", "report": {"format": "pb-json", "path": "out/old.json"}})
    check("R3a 고정 경로 리포트가 이번 실행에서 바뀌지 않음(시각만 갱신) → 거부", s["status"] == "report_invalid" and "재사용" in s["reason"], s)
    s = one({"name": "empty", "run": 'printf \'{"format":"pb-test-report/v1","cases":[]}\' > "$PB_REPORT_DIR/r.json"', "report": {"format": "pb-json", "file": "r.json"}})
    check("R4 케이스 없는 리포트 → report_empty", s["status"] == "report_empty", s)
    s = one({"name": "badjson", "run": 'printf "{not json" > "$PB_REPORT_DIR/r.json"', "report": {"format": "pb-json", "file": "r.json"}})
    check("R5 오염된(해석 불가) 리포트 → report_invalid", s["status"] == "report_invalid" and "해석" in s["reason"], s)
    s = one({"name": "incons", "run": good + "; exit 1", "report": {"format": "pb-json", "file": "r.json"}})
    check("R6 종료 코드 실패인데 리포트는 통과 → inconsistent(신뢰 불가)", s["status"] == "inconsistent", s)
    dup = 'printf \'{"format":"pb-test-report/v1","cases":[{"id":"t1","name":"[AC-001] x","status":"passed"},{"id":"t1","name":"[AC-001] x","status":"failed"}]}\' > "$PB_REPORT_DIR/r.json"'
    s = one({"name": "dup", "run": dup, "report": {"format": "pb-json", "file": "r.json"}})
    check("R7 같은 케이스 중복(통과·실패) → 나쁜 쪽(failed), 종료 0과 모순 → failed", s["status"] == "failed" and s["cases"][0]["status"] == "failed", s)
    run = V.run_steps(d, prof, "B9", [{"name": "mut", "run": "echo y >> src/a.py; " + good, "report": {"format": "pb-json", "file": "r.json"}}], set(), 30)
    check("R8 실행 중 코드가 바뀜 → 실행 무효(valid=false)", run["valid"] is False and "바뀌었습니다" in run["invalid_reason"], run.get("invalid_reason"))
    s = one({"name": "slow", "run": "sleep 5", "timeout": 1})
    check("R9 중단(시간 초과) → timeout", s["status"] == "timeout", s)
    s = one({"name": "env", "run": "true", "requires": ["playwright"]})
    check("R10 환경 없음(Playwright) → not_run(실행 안 함)", s["status"] == "not_run" and "playwright" in s["reason"], s)
    w(d, "j.xml", '<testsuite><testcase classname="c" name="[AC-001] a"/><testcase classname="c" name="b"><properties><property name="ac" value="AC-002"/></properties><failure/></testcase>'
                  '<testcase classname="c" name="AC-003 언급만"/><testcase classname="c" name="d"><skipped/></testcase></testsuite>')
    cs = {c["name"]: c for c in V.parse_report(d / "j.xml", "junit-xml", "bracket")}
    check("R11 JUnit: [AC] 태그·property 태그·실패·skip, 언급만은 태그 아님", cs["[AC-001] a"]["acs"] == ["AC-001"] and cs["b"]["acs"] == ["AC-002"]
          and cs["b"]["status"] == "failed" and cs["AC-003 언급만"]["acs"] == [] and cs["AC-003 언급만"]["mentions"] == ["AC-003"] and cs["d"]["status"] == "skipped", cs)
    check("R12 prefix 태그 형식(SMAPSH식 'SCR-212 / AC-010 / AC-016: …')은 프로필에서 고를 때만",
          V._tags("SCR-212 / AC-010 / AC-016: edit", None, "prefix") == ["AC-010", "AC-016"] and V._tags("SCR-212 / AC-010: edit", None, "bracket") == []
          and V._tags("edit AC-010: x", None, "prefix") == []
          and V._tags("B4 club > SCR-222→223→224 / AC-042·071·073: create", None, "prefix") == ["AC-042", "AC-071", "AC-073"]
          and V._tags("suite > SCR-223-ST6 / AC-080: stale", None, "prefix") == ["AC-080"]
          and V._tags("suite > AC-006 / AC-007 / UXD-012: admins", None, "prefix") == ["AC-006", "AC-007"]
          and V._tags("suite > shows AC-001 in text: x", None, "prefix") == [])


# ---------------------------------------------------------------- 배치 검증 흐름
def flow(root: Path) -> None:
    d = setup(root)
    snap = T.protected_snapshot(d)

    # B0(AC 없음)
    lock = start(d, "B0")
    w(d, "src/common/button.py", "def button(x):\n    return f'[{x}]'\n")
    done_all(d, "B0", lock)
    pb(d, "batch-submit", "--batch", "B0", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    check("F0 시작도 안 한 배치는 검증 불가", code == 2 and out.get("error") == "not_verifiable", out)
    code, out = pb(d, "verify", "--batch", "B0")
    check("F1 B0 검증: 단위 단계 통과, 선택 단계(browser, Playwright 없음)는 막지 않음 → verified",
          code == 0 and out["status"] == "verified" and out["run"]["steps"]["browser"]["status"] == "not_run", out)

    # B1: 구현 중 확인 실행(빨강) → 제출 → 최종 검증 실패(AC별 사유)
    lock = start(d, "B1")
    w(d, "src/seats/seats.py", SEATS_BUG)
    w(d, "tests/test_seats.py", TEST_SEATS_V1)
    code, out = pb(d, "check-run", "--batch", "B1", "--lock", lock, "--step", "unit")
    check("F1a check-run도 리포트를 저장소가 아닌 증거 폴더에 씀(작업 트리 오염 없음)", not (d / "unit.json").exists() and code == 0, out)
    code, out = pb(d, "verify", "--batch", "B1", "--lock", lock)
    check("F2 구현 중 확인 실행(probe): 상태 유지, AC-003 실패 기록", code == 0 and out["mode"] == "probe" and out["acs"]["AC-003"]["status"] == "failing"
          and st(d)["batches"]["B1"]["status"] == "in_progress", out.get("acs"))
    done_all(d, "B1", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    code, out = pb(d, "batch-start", "--batch", "B2", "--confirm-risk", "--note", "확인")
    check("F3 선행 배치(B1)가 구현만 되고 검증 전 → 의존 배치 시작 차단", code == 2 and out.get("error") == "dependencies_not_ready"
          and out["pending"] == {"B1": "implemented"}, out)
    code, out = pb(d, "verify", "--batch", "B1")
    acs = out.get("acs", {})
    check("F4 최종 검증 실패: AC별 사유(E2 통과·E1 언급만·실패·태그 없음)", code == 2 and out["status"] == "verify_failed"
          and acs["AC-001"]["status"] == "verified" and acs["AC-001"]["level"] == "E2"
          and acs["AC-002"]["status"] == "untested" and acs["AC-002"]["level"] == "E1"
          and acs["AC-003"]["status"] == "failing" and acs["AC-004"]["status"] == "untested" and acs["AC-004"]["level"] == "E0", acs)
    check("F4a 테스트 이름에 AC 번호(태그 없이)만 있으면 E2 이상 없음", acs["AC-002"]["level"] == "E1")
    code, rep = pb(d, "ac-report", "--batch", "B1")
    check("F5 ac-report: AC별 상태·수준·목표·사유", code == 0 and rep["batches"]["B1"]["acs"]["AC-003"]["status"] == "failing"
          and rep["batches"]["B1"]["acs"]["AC-004"]["reason"].startswith("태그된 테스트 없음"), rep)

    # 고치기: resume --batch → 수정 → 제출 → 검증
    code, out = pb(d, "resume", "--batch", "B1", "--owner", "t2")
    lock = out.get("lock_id")
    check("F6 검증 실패 배치를 resume --batch로 다시 엶", code == 0 and lock, out)
    w(d, "src/seats/seats.py", SEATS_OK)
    w(d, "tests/test_seats.py", TEST_SEATS_V2)
    pb(d, "checkpoint", "--batch", "B1", "--lock", lock)
    pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B1")
    acs = out.get("acs", {})
    check("F7 수정 후 verified: AC-003은 실패→수정→통과 이력으로 E3, 나머지 E2", code == 0 and out["status"] == "verified"
          and acs["AC-003"]["level"] == "E3" and acs["AC-001"]["level"] == "E2" and acs["AC-004"]["level"] == "E2", acs)

    # 무효화: 검증 뒤 배치 범위 코드 변경 → stale, 의존 배치 차단, 재검증
    w(d, "src/seats/seats.py", SEATS_OK + "# 검증 뒤 변경\n")
    code, out = pb(d, "status")
    check("F8 검증 뒤 코드 변경 → 재검증 필요 표시(status)", "B1" in out.get("needs_reverify", {}), out.get("needs_reverify"))
    code, out = pb(d, "batch-start", "--batch", "B2", "--confirm-risk", "--note", "확인")
    check("F9 선행 배치 증거가 무효 → 의존 배치 시작 차단", code == 2 and out.get("error") == "dependencies_not_ready" and "B1" in out["pending"], out)
    pb(d, "check")
    check("F10 check가 stale로 기록(재검증 필요 상태)", st(d)["batches"]["B1"]["status"] == "stale")
    code, out = pb(d, "verify", "--batch", "B1")
    check("F11 재검증 → verified", code == 0 and out["status"] == "verified", out.get("reasons"))

    # B2(삭제 → E3 목표): 테스트 먼저(빨강) → 구현(초록) → E3
    lock = start(d, "B2", "--confirm-risk", "--note", "사용자 확인: 예약 삭제 구현")
    w(d, "tests/test_reservations.py", 'import unittest\nfrom reservations.cancel import cancel\n\n\nclass C(unittest.TestCase):\n'
      '    def test_cancel(self):\n        """[AC-005] 내 예약을 삭제하면 좌석이 다시 빈다"""\n        t = {"A1"}\n        cancel("A1", t)\n        self.assertNotIn("A1", t)\n')
    w(d, "src/reservations/cancel.py", "def cancel(seat, taken):\n    pass  # 아직\n")
    code, out = pb(d, "verify", "--batch", "B2", "--lock", lock)
    check("F12 테스트 먼저 실행(빨강) 기록", out["acs"]["AC-005"]["status"] == "failing", out.get("acs"))
    w(d, "src/reservations/cancel.py", "def cancel(seat, taken):\n    taken.discard(seat)\n")
    done_all(d, "B2", lock)
    pb(d, "batch-submit", "--batch", "B2", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B2")
    check("F13 위험 AC(삭제, 목표 E3): 실패→수정→통과 증거로 verified", code == 0 and out["acs"]["AC-005"]["level"] == "E3"
          and out["acs"]["AC-005"]["target"] == "E3" and out["status"] == "verified", out.get("acs"))

    # B3(권한, 목표 E3): 통과만 있으면 E2 → insufficient. 최종 검증 연속 실패 한도
    lock = start(d, "B3", "--confirm-risk", "--note", "사용자 확인: 관리자 권한")
    w(d, "src/admin/admin.py", "def add_seat(role, seats, s):\n    if role != 'admin':\n        raise PermissionError\n    seats.append(s)\n")
    w(d, "tests/test_admin.py", 'import unittest\nfrom admin.admin import add_seat\n\n\nclass A(unittest.TestCase):\n'
      '    def test_perm(self):\n        """[AC-006] 권한 없는 사용자는 좌석 관리 불가"""\n        with self.assertRaises(PermissionError):\n            add_seat("member", [], "A9")\n\n'
      '    def test_add(self):\n        """[AC-007] 관리자는 좌석을 추가"""\n        s = []\n        add_seat("admin", s, "A9")\n        self.assertEqual(s, ["A9"])\n')
    done_all(d, "B3", lock)
    pb(d, "batch-submit", "--batch", "B3", "--lock", lock)
    outs = [pb(d, "verify", "--batch", "B3") for _ in range(3)]
    o1 = outs[0][1]
    check("F14 통과만 있는 위험 AC → insufficient(E2 < 목표 E3), 사유 표시", o1["acs"]["AC-006"]["status"] == "insufficient"
          and o1["acs"]["AC-006"]["level"] == "E2" and "실패→수정→통과" in o1["acs"]["AC-006"]["reason"], o1.get("acs"))
    check("F15 최종 검증 연속 3회 실패 → failed(무한 재시도 없음)", [x[1].get("status") for x in outs] == ["verify_failed", "verify_failed", "failed"]
          and st(d)["batches"]["B3"]["status"] == "failed", [x[1].get("status") for x in outs])
    code, out = pb(d, "resume", "--batch", "B3")
    check("F16 한도 초과 후 사용자 결정 없이 재개 불가", code == 2 and out.get("error") == "failed_needs_decision", out)
    code, out = pb(d, "resume", "--batch", "B3", "--retry-failed", "--note", "사용자 결정: 실패 우선 테스트로 증거 보강")
    lock = out.get("lock_id")
    # 회귀: 이 배치 작업 중 B1 코드를 깨뜨리면(범위 밖) 확인 실행에서 B1이 회귀로 표시됨
    w(d, "src/seats/seats.py", SEATS_BUG)
    w(d, "src/admin/admin.py", "def add_seat(role, seats, s):\n    return None  # 실패 우선: 권한 검사·추가 모두 아직\n")
    code, out = pb(d, "verify", "--batch", "B3", "--lock", lock)
    check("F17 다른 배치의 태그 테스트 실패 → 그 배치 회귀(stale) 표시", out.get("regressed_batches", {}).get("B1") and st(d)["batches"]["B1"]["status"] == "stale", out.get("regressed_batches"))
    w(d, "src/seats/seats.py", SEATS_OK + "# 검증 뒤 변경\n")
    w(d, "src/admin/admin.py", "def add_seat(role, seats, s):\n    if role != 'admin':\n        raise PermissionError\n    seats.append(s)\n")
    pb(d, "checkpoint", "--batch", "B3", "--lock", lock)
    pb(d, "batch-submit", "--batch", "B3", "--lock", lock)
    code, out = pb(d, "verify", "--batch", "B3")
    # M2.4 정책: 통과하던 정상 코드를 일부러 훼손했다가 복구한 이력은 실제 결함 수정(E3)이 아니라 '결함 주입' 유형으로 따로 기록
    check("F18 정상 코드 훼손→복구 이력은 E3 아님(fault_injection 유형으로 구분, insufficient)", code == 2 and out["status"] == "verify_failed"
          and out["acs"]["AC-006"]["level"] == "E2" and out["acs"]["AC-006"]["evidence"][0]["type"] == "fault_injection"
          and out["acs"]["AC-007"]["status"] == "insufficient", out.get("acs"))
    pb(d, "accept-fault-injection", "--batch", "B3", "--ac", "AC-006", "--note", "사용자 승인: 기존 구현이라 결함 주입 증거를 인정")
    pb(d, "accept-fault-injection", "--batch", "B3", "--ac", "AC-007", "--note", "사용자 승인: 기존 구현이라 결함 주입 증거를 인정")
    code, out = pb(d, "verify", "--batch", "B3")
    check("F18a AC별 사용자 승인 후에만 결함 주입 증거로 목표 충족(유형은 계속 구분)", code == 0 and out["status"] == "verified"
          and "결함 주입" in out["acs"]["AC-006"]["reason"] and out["acs"]["AC-006"]["level"] == "E2", out.get("acs"))
    code, out = pb(d, "verify", "--batch", "B1")
    check("F19 회귀 배치 재검증 → verified", code == 0 and out["status"] == "verified", out.get("reasons"))

    # 우회 차단
    s0 = (d / ".ai-workflow/build.json").read_text()
    data = json.loads(s0)
    data["batches"]["B0"]["status"] = "verified"; data["batches"]["B0"].pop("verification")
    (d / ".ai-workflow/build.json").write_text(json.dumps(data))
    code, out = pb(d, "status")
    check("F20 검증 기록 없이 verified로 바꾼 상태 파일 → invalid_state(자동 수정 없음)", code == 2 and out.get("error") == "invalid_state", out)
    data = json.loads(s0)
    data["batches"]["B2"]["run"].pop("submitted")
    (d / ".ai-workflow/build.json").write_text(json.dumps(data))
    code, out = pb(d, "verify", "--batch", "B2")
    check("F21 구현 제출 기록 없이 검증 시도 → 거부(상태 파일 무결성)", code == 2 and out.get("error") == "invalid_state", out)
    (d / ".ai-workflow/build.json").write_text(s0)
    rj = d / st(d)["batches"]["B1"]["verification"]["dir"] / "run.json"
    body = json.loads(rj.read_text()); body["steps"][0]["status"] = "passed"; body["valid"] = True; body["tree_after"] = "x"
    rj.write_text(json.dumps(body))
    code, out = pb(d, "status")
    check("F22 증거 원본(run.json) 변조 → 재검증 필요(digest 불일치)", "B1" in out.get("needs_reverify", {}) and "digest" in out["needs_reverify"]["B1"], out.get("needs_reverify"))
    code, out = pb(d, "verify", "--batch", "B1")
    check("F23 변조 뒤 재검증으로만 복구", code == 0 and out["status"] == "verified", out.get("reasons"))
    code, out = pb(d, "verify", "--batch", "B1", "--steps", "unit")
    check("F24 최종 검증은 일부 단계만 골라 실행할 수 없음", code == 2 and out.get("error") == "partial_final_verify", out)
    code, out = pb(d, "check")
    check("F25 승인 문서·state.yaml 불변, 잠금 없음", T.protected_snapshot(d) == snap and not (d / ".ai-workflow/build/lock.json").exists() and code == 0, out)
    check("F26 증거 원본은 Git 제외 경로(.ai-workflow/build/evidence/)", all(not x.startswith(".ai-workflow/build/evidence") for x in
          subprocess.run(["git", "-C", str(d), "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True).stdout.split()))


if __name__ == "__main__":
    sys.exit(main())
