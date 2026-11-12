"""/product-build 대화 검증용 제품 저장소 생성(의원 진료 예약, L3). tests/product_build_test.py 픽스처를 씁니다.
계획은 제출(awaiting_approval)까지만 해 두고 승인은 대화로 받습니다. 사용법: python3 mk.py <작업 폴더>"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
W = Path(sys.argv[1]); ENGINE = Path(os.environ["ENGINE"])
sys.path.insert(0, str(ENGINE / "tests"))
import product_build_test as T  # noqa: E402

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["app"]
tests = ["tests"]
components = []
exclude = ["__pycache__"]
[approval]
default = "auto"
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
[verify]
tag_style = "bracket"
"""
RUNNER = r'''import json, os, pathlib, sys, unittest
sys.path.insert(0, ".")
cases = []
class R(unittest.TestResult):
    def _add(self, t, st):
        mod = t.id().split(".")
        cases.append({"id": t.id(), "name": t.shortDescription() or t.id(), "file": "/".join(mod[:-2]) + ".py", "status": st})
    def addSuccess(self, t): self._add(t, "passed")
    def addFailure(self, t, e): self._add(t, "failed")
    def addError(self, t, e): self._add(t, "error")
    def addSkip(self, t, r): self._add(t, "skipped")
r = R()
unittest.TestLoader().discover("tests", top_level_dir=".").run(r)
pathlib.Path(os.environ.get("PB_REPORT_DIR", ".")).joinpath("unit.json").write_text(json.dumps({"format": "pb-test-report/v1", "tool": "unittest", "cases": cases}, ensure_ascii=False))
print(f"{len(cases)} tests, {sum(c['status'] in ('failed', 'error') for c in cases)} failed")
sys.exit(0 if all(c["status"] in ("passed", "skipped") for c in cases) else 1)
'''
PLAN = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
    {"id": "B0", "title": "진료 시간·예약 신청", "goal": "환자가 빈 시간을 보고 예약하며 하루 전 알림 문구를 받는다", "kind": "ui",
     "screens": ["SCR-101", "SCR-102"], "acs": ["AC-001", "AC-002", "AC-003", "AC-006"],
     "paths": {"allow": ["app/patient/", "tests/test_patient.py"], "shared": []},
     "tasks": [
         {"id": "B0-T1", "layer": "be", "title": "app/patient/schedule.py: available_slots(taken) — 09:00부터 11:30까지 30분 간격 시간 중 taken(집합)에 없는 것을 정렬해 반환", "refs": ["SCR-101", "AC-001"]},
         {"id": "B0-T2", "layer": "be", "title": "app/patient/booking.py: book(slot, taken) — slot이 taken에 있으면 ValueError('이미 찬 시간입니다'), 아니면 taken에 추가하고 접수 번호 문자열 'R-<HHMM>' 반환. reminder(slot) — '내일 <slot> 진료 예약이 있습니다' 반환", "refs": ["SCR-102", "AC-002", "AC-003", "AC-006"], "depends_on": ["B0-T1"]},
         {"id": "B0-T3", "layer": "test", "title": "tests/test_patient.py: unittest로 AC-001·AC-002·AC-003·AC-006 확인(테스트 이름에 [AC-xxx] 표기)", "refs": ["AC-001", "AC-002", "AC-003", "AC-006"], "depends_on": ["B0-T2"]}]},
    {"id": "B1", "title": "내 정보(연락처)", "goal": "환자가 연락처를 고친다", "kind": "ui", "screens": ["SCR-103"], "acs": ["AC-007"], "depends_on": ["B0"],
     "paths": {"allow": ["app/me/", "tests/test_me.py"], "shared": []},
     "tasks": [
         {"id": "B1-T1", "layer": "be", "title": "app/me/profile.py: update_contact(profile, phone) — 숫자와 하이픈만 허용(아니면 ValueError), profile['phone']을 바꿔 반환", "refs": ["SCR-103", "AC-007"]},
         {"id": "B1-T2", "layer": "test", "title": "tests/test_me.py: [AC-007] 연락처 수정·잘못된 형식 거부 테스트", "refs": ["AC-007"], "depends_on": ["B1-T1"]}]},
    {"id": "B2", "title": "접수(직원)", "goal": "직원만 접수한다", "kind": "ui", "screens": ["SCR-201"], "acs": ["AC-004", "AC-005"], "depends_on": ["B0"],
     "paths": {"allow": ["app/staff/", "tests/test_staff.py"], "shared": []},
     "tasks": [
         {"id": "B2-T1", "layer": "be", "title": "app/staff/desk.py: accept(role, booking) — role이 'staff'가 아니면 PermissionError, 맞으면 대기 번호(1부터 증가) 반환", "refs": ["SCR-201", "AC-004", "AC-005"]},
         {"id": "B2-T2", "layer": "test", "title": "tests/test_staff.py: [AC-004]·[AC-005] 테스트", "refs": ["AC-004", "AC-005"], "depends_on": ["B2-T1"]}]}]}

T.ENGINE = ENGINE
d = T.make_product(W, "pbx", T.CLINIC)
T.simulate_preview_approved(d)
for p in ("app/__init__.py", "app/patient/__init__.py", "app/me/__init__.py", "app/staff/__init__.py", "tests/__init__.py"):
    (d / p).parent.mkdir(parents=True, exist_ok=True); (d / p).write_text("")
(d / "tools").mkdir(); (d / "tools/run_tests.py").write_text(RUNNER)
(d / ".claude/skills").mkdir(parents=True)
for s in ("product-build", "product-design"):
    os.symlink(ENGINE / "skills" / s, d / ".claude/skills" / s)
with open(d / ".git/info/exclude", "a") as f:
    f.write(".claude/\n")
T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "code skeleton")
T.pb(d, "init")
(d / "docs/build/build-profile.toml").write_text(PROFILE)
T.save_plan(d, PLAN)
code, out = T.pb(d, "submit", "plan"); assert code == 0, out
T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "plan submitted (user)")
snap = T.protected_snapshot(d)
(W / "protected.json").write_text(json.dumps(snap))
print(d)
