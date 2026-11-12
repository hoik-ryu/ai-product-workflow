#!/usr/bin/env python3
"""/product-build M2.2 배치 실행 테스트(자체 완결형).

product_build_test.py의 가상 제품 픽스처(도서관 좌석 예약·의원 진료 예약)에 작은 Python 코드와 테스트를 두고,
승인된 계획으로 batch-start → (Claude 대신 테스트가 코드 작성) → task-done → batch-submit 흐름과
잠금·체크포인트·중단 복구·보호 경로·범위·테스트 약화·재시도 한도를 검사합니다.

실행: python3 tests/product_build_exec_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["src"]
tests = ["tests"]
components = ["src/common"]
exclude = ["node_modules", "__pycache__"]
[approval]
default = "auto"
waived_ui = "auto"
[execution]
max_retries = 3
lock_ttl_minutes = 30
dependency_min = "implemented"
[[verify.steps]]
name = "unit"
stage = "test"
run = "python3 -B -m unittest discover -s tests -q"
cwd = "."
requires = []
[[verify.steps]]
name = "flag"
stage = "test"
run = "python3 -B -c \\"import pathlib,sys; sys.exit(0 if pathlib.Path('src/seats/flag.txt').exists() else 1)\\""
cwd = "."
requires = []
[[verify.steps]]
name = "db"
stage = "db"
run = "echo db"
cwd = "."
requires = ["docker"]
"""

LIB_PLAN = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
    {"id": "B0", "title": "공통 기반", "kind": "foundation", "components": {"new": ["CMP-001"], "reuse": []},
     "paths": {"allow": ["src/common/"], "shared": []},
     "tasks": [{"id": "B0-T1", "layer": "fe", "title": "공통 버튼", "refs": ["CMP-001"]}]},
    {"id": "B1", "title": "좌석 현황·예약", "kind": "ui", "screens": ["SCR-001", "SCR-002"], "acs": ["AC-001", "AC-002", "AC-003", "AC-004"],
     "components": {"reuse": ["CMP-001"], "new": ["CMP-002"]}, "depends_on": ["B0"],
     "paths": {"allow": ["src/seats/", "tests/test_seats.py"], "shared": ["src/common/util.py"]},
     "tasks": [{"id": "B1-T1", "layer": "fe", "title": "좌석 화면", "refs": ["SCR-001", "SCR-002"]},
               {"id": "B1-T2", "layer": "be", "title": "중복 예약 규칙", "refs": ["AC-004"], "depends_on": ["B1-T1"]},
               {"id": "B1-T3", "layer": "test", "title": "AC 테스트", "refs": ["AC-001", "AC-003"], "depends_on": ["B1-T2"]}]},
    {"id": "B2", "title": "예약 취소", "kind": "ui", "screens": ["SCR-003"], "acs": ["AC-005"], "depends_on": ["B1"],
     "components": {"reuse": ["CMP-001"], "new": ["CMP-003"]},
     "paths": {"allow": ["src/reservations/", "tests/test_reservations.py"], "shared": []},
     "tasks": [{"id": "B2-T1", "layer": "fe", "title": "내 예약·취소", "refs": ["SCR-003", "AC-005"]}]},
    {"id": "B3", "title": "좌석 관리", "kind": "ui", "screens": ["SCR-004"], "acs": ["AC-006", "AC-007"], "depends_on": ["B0"],
     "components": {"reuse": ["CMP-001"], "new": []},
     "paths": {"allow": ["src/admin/"], "shared": []},
     "tasks": [{"id": "B3-T1", "layer": "fe", "title": "관리 화면", "refs": ["SCR-004"]}]},
]}


def setup_library(root: Path, name: str = "lib-exec") -> Path:
    d = T.make_product(root, name, T.LIBRARY)
    (d / "src/common").mkdir(parents=True)
    (d / "src/common/util.py").write_text("def clamp(x, lo, hi):\n    return max(lo, min(hi, x))\n")
    (d / "tests").mkdir()
    (d / "tests/test_existing.py").write_text("import unittest\nimport sys\nsys.path.insert(0, 'src')\nfrom common.util import clamp\n\n"
                                              "class T(unittest.TestCase):\n    def test_clamp(self):\n        self.assertEqual(clamp(5, 0, 3), 3)\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    T.save_plan(d, LIB_PLAN)
    pb(d, "waiver", "add", "--reason", "배치 구현으로 시각 확인", "--all-ui", "--note", "프리뷰 없이 구현을 승인합니다", "--confirm")
    code, out = pb(d, "submit", "plan"); assert code == 0, out
    code, out = pb(d, "approve", "plan", "--revision", "1", "--note", "구현 계획을 승인합니다"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "approved build plan (user)")
    return d


def st(d: Path) -> dict:
    return json.loads((d / ".ai-workflow/build.json").read_text())


def write(d: Path, rel: str, text: str) -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def run_batch(d: Path, batch: str, files: dict[str, dict[str, str]], extra=()) -> dict:
    """batch-start → 작업별로 파일을 쓰고 task-done → batch-submit. files: {task: {path: text}}"""
    code, out = pb(d, "batch-start", "--batch", batch, "--owner", "test", *extra)
    assert code == 0, out
    lock = out["lock_id"]
    for task, fs in files.items():
        for rel, text in fs.items():
            write(d, rel, text)
        code, o = pb(d, "task-done", "--batch", batch, "--task", task, "--lock", lock)
        assert code == 0, o
    code, o = pb(d, "batch-submit", "--batch", batch, "--lock", lock)
    assert code == 0, o
    return o


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-exec-test-"))
    try:
        tests(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


def tests(root: Path) -> None:
    # ---- 2. 계획 미승인 상태 실행 차단
    U = T.make_product(root, "unapproved", T.LIBRARY)
    pb(U, "init")
    T.save_plan(U, LIB_PLAN)
    code, out = pb(U, "batch-start", "--batch", "B0")
    check("E2 [2] 계획 미승인 → batch-start 차단(상태·잠금 생성 없음)", code == 2 and out.get("error") == "plan_not_approved"
          and not (U / ".ai-workflow/build/lock.json").exists(), out)

    # ---- 계획 검증: 수정 범위
    bad = json.loads(json.dumps(LIB_PLAN)); bad["batches"][1]["paths"]["allow"] = ["docs/design/", "**"]
    T.save_plan(U, bad)
    code, v = pb(U, "plan-validate")
    check("E2a 수정 범위에 보호 경로·저장소 전체 패턴 → 계획 오류", T.has(v, "paths_invalid") and "보호 경로" in T.errors_of(v), T.errors_of(v))

    A = setup_library(root)
    snap = T.protected_snapshot(A)
    # 사용자의 기존 미커밋 변경(보존 대상)
    write(A, "notes/user-draft.md", "사용자가 쓰던 메모\n")
    write(A, "scripts/user_tool.py", "# 사용자 미커밋 도구\n")

    # ---- 3. 의존 배치 미완료
    code, out = pb(A, "batch-start", "--batch", "B1")
    check("E3 [3] 선행 배치(B0) 미완료 → 차단", code == 2 and out.get("error") == "dependencies_not_ready" and out["pending"] == {"B0": "planned"}, out)

    # ---- 1. 정상 시작·작업 완료
    code, out = pb(A, "batch-start", "--batch", "B0", "--owner", "s1")
    lock0 = out.get("lock_id")
    check("E1 [1] batch-start: 잠금·기준선(HEAD·기존 미커밋 파일)·작업 목록·브랜치 권장(자동 생성 없음)", code == 0 and lock0
          and set(out["preserved_uncommitted"]) == {"notes/user-draft.md", "scripts/user_tool.py"} and out["next_task"]["id"] == "B0-T1"
          and "branch_recommendation" in out and G(A, "branch", "--show-current").strip() == "main", out)
    check("E1a 실행 산출물(runs/·lock.json·evidence/)은 Git 제외", all(x in (A / ".ai-workflow/build/.gitignore").read_text() for x in ("runs/", "lock.json", "evidence/")))
    write(A, "src/common/button.py", "def button(label):\n    return f'[{label}]'\n")
    code, out = pb(A, "task-done", "--batch", "B0", "--task", "B0-T1", "--lock", lock0)
    check("E1b task-done: 변경 파일 기록·체크포인트", code == 0 and out["files"] == ["src/common/button.py"] and out["next_task"] is None, out)
    code, out = pb(A, "task-done", "--batch", "B0", "--task", "B0-T1", "--lock", lock0)
    check("E1c 같은 작업 다시 완료 → already_done(중복 기록 없음)", code == 0 and out["status"] == "already_done", out)
    code, out = pb(A, "batch-submit", "--batch", "B0", "--lock", lock0)
    s = st(A)
    check("E1d batch-submit: implemented(검증·승인 아님), 잠금 해제, 다음 배치 제안", code == 0 and s["batches"]["B0"]["status"] == "implemented"
          and not (A / ".ai-workflow/build/lock.json").exists() and {x["batch"] for x in out["next_batches"]} == {"B1", "B3"}
          and "검증" in s["batches"]["B0"]["run"]["submitted"]["meaning"], out)
    check("E1e 사용자 기존 미커밋 변경 보존(내용 그대로)", (A / "notes/user-draft.md").read_text() == "사용자가 쓰던 메모\n"
          and (A / "scripts/user_tool.py").read_text() == "# 사용자 미커밋 도구\n")
    check("E1f git add/commit 없음(HEAD·인덱스 그대로)", G(A, "diff", "--cached", "--name-only").strip() == "" and len(G(A, "log", "--oneline").splitlines()) == 4)

    # ---- 4. 동시 실행 충돌
    code, out = pb(A, "batch-start", "--batch", "B1", "--owner", "s1")
    lock1 = out.get("lock_id")
    check("E4 B1 시작(선행 B0 implemented → 허용)", code == 0 and lock1, out)
    code, out = pb(A, "batch-start", "--batch", "B3", "--owner", "s2")
    check("E4a [4] 다른 세션의 두 번째 batch-start → 차단(활성 배치 1개)", code == 2 and out.get("error") in ("active_batch_exists", "lock_held"), out)
    write(A, "src/seats/view.py", "def seats():\n    return []\n")
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T1", "--lock", "deadbeef0000")
    check("E4b [4] 다른 잠금 ID로 task-done → lock_mismatch(기록 없음)", code == 2 and out.get("error") == "lock_mismatch"
          and st(A)["batches"]["B1"]["run"]["tasks"]["B1-T1"]["status"] == "pending", out)

    # ---- 7. 보호 경로 수정 차단
    orig = (A / "docs/design/02-screens.md").read_text()
    (A / "docs/design/02-screens.md").write_text(orig + "\n구현 중 실수\n")
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T1", "--lock", lock1)
    check("E7 [7] 승인 문서 변경 → task-done 차단(작업 미기록)", code == 2 and out.get("error") == "protected_path_changed"
          and out["paths"] == ["docs/design/02-screens.md"] and st(A)["batches"]["B1"]["run"]["tasks"]["B1-T1"]["status"] == "pending", out)
    (A / "docs/design/02-screens.md").write_text(orig)

    # ---- 8. 범위 밖 변경 탐지 + 기존 미커밋 파일 충돌
    write(A, "src/other/misc.py", "X = 1\n")
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T1", "--lock", lock1)
    check("E8 [8] 범위 밖 파일 → 보고(기록은 진행)", code == 0 and out["out_of_scope"] == ["src/other/misc.py"] and "src/seats/view.py" in out["files"], out)
    with open(A / "notes/user-draft.md", "a") as f:
        f.write("다른 세션이 덧붙임\n")
    write(A, "src/seats/rules.py", "def ok():\n    return True\n")
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T2", "--lock", lock1)
    check("E8a 시작 때 미커밋이던 사용자 파일이 바뀜 → base_conflict 차단(사용자 확인 필요)", code == 2 and out.get("error") == "base_conflict"
          and out["paths"] == ["notes/user-draft.md"], out)
    (A / "notes/user-draft.md").write_text("사용자가 쓰던 메모\n")

    # ---- 5. 중단 후 resume(작업 중복·누락 없음)
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T2", "--lock", lock1)
    code2, out2 = pb(A, "pause", "--batch", "B1", "--lock", lock1, "--note", "퇴근")
    check("E5 [5] pause: paused·잠금 해제·다음 작업 표시", code == 0 and code2 == 0 and st(A)["batches"]["B1"]["status"] == "paused"
          and not (A / ".ai-workflow/build/lock.json").exists() and out2["next_task"]["id"] == "B1-T3", out2)
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T3", "--lock", lock1)
    check("E5a paused 상태에서 이전 잠금으로 기록 불가", code == 2 and out.get("error") == "not_running", out)
    code, out = pb(A, "resume", "--owner", "s3")
    lock1b = out.get("lock_id")
    check("E5b resume: 끝난 작업(T1·T2) 유지, 다음은 T3(중복·누락 없음), 새 잠금", code == 0 and out["done"] == ["B1-T1", "B1-T2"]
          and out["next_task"]["id"] == "B1-T3" and lock1b and lock1b != lock1, out)

    # ---- 6. 외부 파일 변경 감지(크래시: pause 없이 세션 종료 후 다른 변경)
    write(A, "src/seats/view.py", "def seats():\n    return ['다른 세션이 수정']\n")
    code, out = pb(A, "resume", "--owner", "s4")
    check("E6 [6] 잠금이 남은 상태(크래시) resume → lock_active(자동 삭제 없음)", code == 2 and out.get("error") == "lock_active"
          and (A / ".ai-workflow/build/lock.json").exists(), out)
    lk = json.loads((A / ".ai-workflow/build/lock.json").read_text()); lk["heartbeat_at"] = "2026-01-01T00:00:00Z"
    (A / ".ai-workflow/build/lock.json").write_text(json.dumps(lk))
    code, out = pb(A, "resume", "--owner", "s4")
    check("E6a 오래된 잠금도 --take-over 없이는 넘겨받지 않음(lock_stale)", code == 2 and out.get("error") == "lock_stale", out)
    code, out = pb(A, "resume", "--owner", "s4", "--take-over")
    check("E6b [6] 넘겨받기 시 체크포인트 이후 외부 변경 → 덮어쓰지 않고 보고(external_changes)", code == 2 and out.get("error") == "external_changes"
          and out["changed"] == ["src/seats/view.py"] and "다른 세션이 수정" in (A / "src/seats/view.py").read_text(), out)
    check("E6b2 검사에서 멈춘 넘겨받기는 기존 잠금을 지우지 않음", json.loads((A / ".ai-workflow/build/lock.json").read_text())["lock_id"] == lk["lock_id"])
    code, out = pb(A, "resume", "--owner", "s4", "--take-over", "--accept-changes", "--note", "사용자 확인: 다른 세션 수정 반영")
    lock1c = out.get("lock_id")
    s = st(A)["batches"]["B1"]["run"]
    check("E6c 사용자 확인 후 받아들임: 넘겨받기·수용 기록", code == 0 and out["took_over"] and s["takeovers"] and s["confirmations"][-1]["kind"] == "accepted_changes", out)

    # ---- 9. 기존 테스트 삭제·약화
    t_old = (A / "tests/test_existing.py").read_text()
    (A / "tests/test_existing.py").write_text(t_old.replace("    def test_clamp", "    @unittest.skip('임시')\n    def test_clamp"))
    write(A, "tests/test_seats.py", "import unittest\n\nclass S(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
    code, out = pb(A, "task-done", "--batch", "B1", "--task", "B1-T3", "--lock", lock1c)
    check("E9 [9] 기존 테스트 skip 추가 → task-done에서 확인 필요로 표시", code == 0 and out["test_changes_need_confirmation"]
          and out["test_changes_need_confirmation"][0]["kind"] == "weakened", out)
    code, out = pb(A, "batch-submit", "--batch", "B1", "--lock", lock1c)
    check("E9a [9] 약화된 테스트가 있으면 batch-submit 차단", code == 2 and out.get("error") == "test_changes_need_confirmation", out)
    (A / "tests/test_existing.py").write_text(t_old.replace("self.assertEqual(clamp(5, 0, 3), 3)", "self.assertTrue(True)"))
    code, out = pb(A, "guard", "--batch", "B1")
    check("E9b 기대값 변경(줄 교체)도 modified로 확인 필요", any(x["kind"] == "modified" for x in out["since_base"]["test_changes"]), out)
    (A / "tests/test_existing.py").unlink()
    code, out = pb(A, "guard", "--batch", "B1")
    check("E9c 기존 테스트 삭제 → deleted", any(x["kind"] == "deleted" for x in out["since_base"]["test_changes"]), out)
    (A / "tests/test_existing.py").write_text(t_old + "\n    def test_more(self):\n        self.assertEqual(clamp(-1, 0, 3), 0)\n")
    code, out = pb(A, "guard", "--batch", "B1")
    check("E9d 기존 테스트에 추가만 → 확인 불필요", not out["since_base"]["test_changes"], out)
    (A / "tests/test_existing.py").write_text(t_old.replace("    def test_clamp", "    @unittest.skip('임시')\n    def test_clamp"))
    code, out = pb(A, "batch-submit", "--batch", "B1", "--lock", lock1c, "--confirm-test-changes", "--note", "사용자 확인: 외부 의존 테스트 임시 제외")
    s = st(A)
    check("E9e 사용자 확인 후 제출: 확인 기록·범위 밖 보고·implemented", code == 0 and s["batches"]["B1"]["status"] == "implemented"
          and any(c["kind"] == "test_changes" for c in s["batches"]["B1"]["run"]["confirmations"])
          and "src/other/misc.py" in s["batches"]["B1"]["run"]["submitted"]["out_of_scope"], out)
    (A / "tests/test_existing.py").write_text(t_old)

    # ---- 위험 배치는 시작 전 사용자 확인
    code, out = pb(A, "batch-start", "--batch", "B2")
    check("E12 위험 배치(삭제) → 사용자 확인 없이 시작 안 함", code == 2 and out.get("error") == "risk_confirmation_required" and out["reasons"], out)

    # ---- 10. 재시도 한도
    code, out = pb(A, "batch-start", "--batch", "B2", "--confirm-risk", "--note", "사용자 확인: 예약 삭제 기능 구현 진행")
    lock2 = out.get("lock_id")
    check("E12a 확인 문장과 함께 위험 배치 시작", code == 0 and st(A)["batches"]["B2"]["run"]["confirmations"][0]["kind"] == "risk", out)
    code, out = pb(A, "check-run", "--batch", "B2", "--lock", lock2, "--step", "db")
    check("E10a 필요한 환경(docker) 없음 → not_run(통과로 세지 않음, 재시도 미포함)", code == 0 and out["status"] == "not_run"
          and "flag" not in st(A)["batches"]["B2"]["run"]["attempts"], out)
    code, out = pb(A, "check-run", "--batch", "B2", "--lock", lock2, "--step", "rm -rf /")
    check("E10b 프로필에 없는 명령은 실행하지 않음", code == 2 and out.get("error") == "unknown_step", out)
    outs = [pb(A, "check-run", "--batch", "B2", "--lock", lock2, "--step", "flag", "--task", "B2-T1") for _ in range(3)]
    s = st(A)["batches"]["B2"]
    check("E10 [10] 같은 단계 연속 3회 실패 → failed, 원인·마지막 상태 기록, 잠금 해제", [o[0] for o in outs] == [0, 0, 2]
          and outs[2][1].get("error") == "retry_limit_exceeded" and s["status"] == "failed" and s["run"]["failure"]["attempts"] == 3
          and s["run"]["failure"]["log"].startswith(".ai-workflow/build/evidence/") and not (A / ".ai-workflow/build/lock.json").exists(), outs[2][1])
    code, out = pb(A, "check-run", "--batch", "B2", "--lock", lock2, "--step", "flag")
    check("E10c 한도 초과 후 추가 시도 불가(무한 재시도 없음)", code == 2 and out.get("error") == "not_running", out)
    code, out = pb(A, "resume")
    check("E10d 사용자 결정 없이 재시도 재개 불가", code == 2 and out.get("error") == "failed_needs_decision", out)
    code, out = pb(A, "resume", "--retry-failed", "--note", "사용자 결정: 플래그 파일 경로를 고쳐 다시 시도")
    lock2b = out.get("lock_id")
    write(A, "src/reservations/cancel.py", "def cancel(r):\n    return None\n")
    write(A, "src/seats/flag.txt", "ok\n")  # 범위 밖(B2는 src/reservations만) → 보고
    code2, out2 = pb(A, "check-run", "--batch", "B2", "--lock", lock2b, "--step", "flag")
    check("E10e 실패 작업부터 재개 → 통과 시 연속 실패 0으로", code == 0 and code2 == 0 and out2["status"] == "passed"
          and st(A)["batches"]["B2"]["run"]["attempts"]["flag"]["consecutive_failures"] == 0, (out, out2))
    code, out = pb(A, "check-run", "--batch", "B2", "--lock", lock2b, "--step", "unit")
    check("E10f 실제 단위 테스트 단계 실행(통과 기록은 검증 증거가 아님)", code == 0 and out["status"] == "passed" and "검증 완료 기록이 아닙니다" in out["note"], out)

    # ---- 11. 체크포인트 손상·복구
    cp = A / ".ai-workflow/build/runs/B2/checkpoint.json"
    cp.write_text("{ 깨진 파일")
    code, out = pb(A, "task-done", "--batch", "B2", "--task", "B2-T1", "--lock", lock2b)
    check("E11 [11] 체크포인트 손상 → 진행 기록 차단", code == 2 and out.get("error") == "checkpoint_corrupt", out)
    code, out = pb(A, "resume", "--take-over", "--note", "사용자 확인: 같은 세션 재시작")
    check("E11a resume: 손상 보고 + 복구 선택지(자동 수정 없음)", code == 2 and out.get("error") == "checkpoint_corrupt" and out["options"], out)
    code, out = pb(A, "resume", "--take-over", "--note", "사용자 확인: 같은 세션 재시작", "--restore-checkpoint", "prev")
    check("E11b 직전 체크포인트로 복구 → 그 이후 변경은 외부 변경으로 보고", code == 2 and out.get("error") == "external_changes"
          and "src/reservations/cancel.py" in out["changed"], out)
    code, out = pb(A, "resume", "--take-over", "--note", "사용자 확인: 이 배치 작업임", "--restore-checkpoint", "prev", "--accept-changes")
    lock2c = out.get("lock_id")
    code2, out2 = pb(A, "task-done", "--batch", "B2", "--task", "B2-T1", "--lock", lock2c)
    check("E11c 복구 후 정상 진행", code == 0 and code2 == 0, (out, out2))
    (A / ".ai-workflow/build/runs/B2/checkpoint.json").write_text("{}")
    (A / ".ai-workflow/build/runs/B2/checkpoint.prev.json").write_text("{}")
    code, out = pb(A, "resume", "--take-over", "--note", "x", "--restore-checkpoint", "prev")
    check("E11d 두 체크포인트 모두 손상 → rebuild만 가능", code == 2 and out.get("error") == "checkpoint_unrecoverable", out)
    code, out = pb(A, "resume", "--take-over", "--restore-checkpoint", "rebuild")
    check("E11e rebuild는 사용자 확인 문장 필요", code == 2 and out.get("error") in ("confirmation_required", "lock_active_confirmation_required"), out)
    code, out = pb(A, "resume", "--take-over", "--restore-checkpoint", "rebuild", "--note", "사용자 확인: 현재 파일 기준으로 재구성")
    lock2d = out.get("lock_id")
    code2, out2 = pb(A, "batch-submit", "--batch", "B2", "--lock", lock2d)
    check("E11f rebuild 후 제출 가능, 재구성 확인 기록", code == 0 and code2 == 0 and any(c["kind"] == "checkpoint_rebuild" for c in st(A)["batches"]["B2"]["run"]["confirmations"]), (out, out2))

    # ---- 상태 파일 쓰기 원자성·보호 경로·상태 표시
    check("E13 상태 파일 임시 파일 잔여 없음(원자적 쓰기)", not list((A / ".ai-workflow").rglob("*.tmp")))
    code, out = pb(A, "status")
    check("E14 status: 배치별 진행·체크포인트·잠금 표시, verified 없음", code == 0 and out["build"]["batches"]["B2"]["status"] == "implemented"
          and out["build"]["batches"]["B1"]["tasks_done"] == "3/3" and out["build"]["lock"] is None
          and not any(b["status"] in ("verified", "approved") for b in out["build"]["batches"].values()), out["build"]["batches"])
    check("E15 기획·디자인 승인 문서·상태 불변", T.protected_snapshot(A) == snap)

    # ---- 배치 범위 안의 미커밋 파일
    D = setup_library(root, "dirty-scope")
    write(D, "src/common/wip.py", "# 사용자 작업 중\n")
    code, out = pb(D, "batch-start", "--batch", "B0")
    check("E16 범위 안 미커밋 파일 → 시작 차단(커밋 권장)", code == 2 and out.get("error") == "uncommitted_in_scope" and out["paths"] == ["src/common/wip.py"], out)
    code, out = pb(D, "batch-start", "--batch", "B0", "--allow-dirty-in-scope", "--note", "사용자 확인: wip.py는 이 배치에서 이어서 작성")
    lk = out.get("lock_id")
    write(D, "src/common/wip.py", "# 배치에서 완성\n")
    code2, out2 = pb(D, "task-done", "--batch", "B0", "--task", "B0-T1", "--lock", lk)
    check("E16a 사용자 확인 후에는 그 파일을 배치 작업으로 기록", code == 0 and code2 == 0 and "src/common/wip.py" in out2["files"], (out, out2))

    # ---- 동시 시작 경쟁(두 프로세스가 동시에 batch-start)
    R = setup_library(root, "race")
    run_batch(R, "B0", {"B0-T1": {"src/common/button.py": "x = 1\n"}})
    res = []

    def go(owner):
        res.append(pb(R, "batch-start", "--batch", "B3" if owner == "a" else "B1", "--owner", owner, "--confirm-risk", "--note", "확인"))
    th = [threading.Thread(target=go, args=(o,)) for o in ("a", "b")]
    [x.start() for x in th]; [x.join() for x in th]
    oks = [r for r in res if r[0] == 0]
    check("E4c [4] 두 세션이 동시에 시작 → 정확히 하나만 성공", len(oks) == 1 and sum(1 for b in st(R)["batches"].values() if b["status"] == "in_progress") == 1, res)

    # ---- 다른 도메인(의원 진료 예약, L3): 연속 실행
    B = T.make_product(root, "clinic-exec", T.CLINIC)
    T.simulate_preview_approved(B)
    (B / "app").mkdir(); (B / "app/__init__.py").write_text("")
    G(B, "add", "-A"); G(B, "commit", "-qm", "code")
    pb(B, "init")
    prof = PROFILE.replace('source = ["src"]', 'source = ["app"]').replace('components = ["src/common"]', 'components = ["app/ui"]')
    (B / "docs/build/build-profile.toml").write_text(prof)
    plan = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
        {"id": "B0", "title": "환자 예약", "kind": "ui", "screens": ["SCR-101", "SCR-102"], "acs": ["AC-001", "AC-002", "AC-003", "AC-006"],
         "paths": {"allow": ["app/patient/"], "shared": ["app/__init__.py"]},
         "tasks": [{"id": "B0-T1", "layer": "fe", "title": "진료 시간·예약"}, {"id": "B0-T2", "layer": "be", "title": "알림", "depends_on": ["B0-T1"]}]},
        {"id": "B1", "title": "내 정보", "kind": "ui", "screens": ["SCR-103"], "acs": ["AC-007"], "depends_on": ["B0"],
         "paths": {"allow": ["app/me/"]}, "tasks": [{"id": "B1-T1", "layer": "fe", "title": "연락처 수정"}]},
        {"id": "B2", "title": "접수", "kind": "ui", "screens": ["SCR-201"], "acs": ["AC-004", "AC-005"], "depends_on": ["B0"],
         "paths": {"allow": ["app/staff/"]}, "tasks": [{"id": "B2-T1", "layer": "fe", "title": "접수 대시보드"}]}]}
    T.save_plan(B, plan)
    code, out = pb(B, "submit", "plan"); code2, out2 = pb(B, "approve", "plan", "--revision", "1", "--note", "승인합니다")
    check("C0 다른 도메인 계획 승인(L3, waiver 없음)", code == 0 and code2 == 0, (out, out2))
    o0 = run_batch(B, "B0", {"B0-T1": {"app/patient/book.py": "def book():\n    return 'ok'\n"}, "B0-T2": {"app/patient/notify.py": "def notify():\n    pass\n"}})
    nxt = {x["batch"]: x["needs_user_confirmation"] for x in o0["next_batches"]}
    check("C1 B0 구현 완료 → 다음 배치 B1·B2 제안(B1 개인정보·B2 권한은 사용자 확인 필요 표시)", nxt == {"B1": True, "B2": True}, o0)
    run_batch(B, "B1", {"B1-T1": {"app/me/profile.py": "def save():\n    pass\n"}}, ("--confirm-risk", "--note", "사용자 확인: 연락처 수정 구현"))
    run_batch(B, "B2", {"B2-T1": {"app/staff/desk.py": "def accept():\n    pass\n"}}, ("--confirm-risk", "--note", "사용자 확인: 직원 권한 구현"))
    s = st(B)
    check("C2 다른 도메인 3개 배치 연속 실행 → 모두 implemented(검증·승인 아님)", all(b["status"] == "implemented" for b in s["batches"].values()), s["batches"])
    code, out = pb(B, "check")
    check("C3 실행 후에도 계획 승인·입력 기준선 유지", code == 0 and out["plan"]["status"] == "approved", out)
    check("C4 바이트코드·임시 파일 없음", not list((T.ENGINE / "skills/product-build").rglob("__pycache__")) and not list(B.rglob("*.tmp")))


if __name__ == "__main__":
    sys.exit(main())
