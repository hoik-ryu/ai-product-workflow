#!/usr/bin/env python3
"""/product-build ↔ /product-design 변경 요청(CR)·승인 패치 M1 최소 연동 테스트(자체 완결형).

- 승인된 Type B 패치로 설명되는 디자인 변경은 구현 계획을 outdated로 만들지 않고, 영향 화면을 가진 배치만 재검증(stale)합니다.
- 진행 중인 CR(pending)의 영향 배치는 검증·최종 승인을 막고, 영향 없는 배치는 진행합니다.
- 체인 문제는 화면 배치 작업을 명시적으로 막습니다.
- Type A(제품 코드 수정)는 기존 guard·verify를 재사용합니다(디자인 승인 유지).

픽스처: tests/change_fixture.py(실제 CLI로 v2 + DD + 프리뷰 승인). 프리뷰 빌드를 할 수 없으면 SKIP.
실행: python3 tests/product_build_change_test.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _tmpdirs as TMP  # noqa: E402
import change_fixture as F  # noqa: E402
import product_design_test as T  # noqa: E402
import product_build_verify_test as VT  # noqa: E402
import product_design_change_test as DC  # noqa: E402

results: list[tuple[str, bool, str]] = []
pd, pb = F.pd, F.pb
EVIDENCE: dict = {}


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:900]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:900]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


def bst(d: Path) -> dict:
    return json.loads((d / ".ai-workflow/build.json").read_text())


PROFILE = VT.PROFILE + '\n[evidence]\nrisk = "E2"\n'  # 이 테스트는 디자인 연동 검사(증거 정책 아님): 위험 AC 목표를 E2로
PLAN = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
    {"id": "B1", "title": "로그인", "kind": "ui", "screens": ["SCR-001"], "acs": ["AC-001", "AC-002"],
     "components": {"reuse": [], "new": ["CMP-001"]}, "paths": {"allow": ["src/login/", "tests/test_login.py"], "shared": []},
     "tasks": [{"id": "B1-T1", "layer": "fe", "title": "로그인 화면", "refs": ["SCR-001", "AC-001"]}]},
    {"id": "B2", "title": "대진", "kind": "ui", "screens": ["SCR-002"], "acs": ["AC-003", "AC-004"],
     "components": {"reuse": [], "new": ["CMP-002"]}, "paths": {"allow": ["src/round/", "tests/test_round.py"], "shared": []},
     "tasks": [{"id": "B2-T1", "layer": "fe", "title": "대진 화면", "refs": ["SCR-002", "AC-003"]}]}]}
LOGIN = "def login(ok):\n    return 'home' if ok else 'error'\n"
ROUND = "def make(players):\n    return sorted(players)\n"
T_LOGIN = '''import unittest
from login.login import login
class L(unittest.TestCase):
    def test_home(self):
        """[AC-001] 로그인하면 홈으로 간다"""
        self.assertEqual(login(True), "home")
    def test_fail(self):
        """[AC-002] 인증 실패 시 안내"""
        self.assertEqual(login(False), "error")
'''
T_ROUND = '''import unittest
from round.round import make
class R(unittest.TestCase):
    def test_make(self):
        """[AC-003] 버튼 한 번으로 대진 생성"""
        self.assertEqual(make(["b", "a"]), ["a", "b"])
    def test_same(self):
        """[AC-004] 같은 입력이면 같은 결과"""
        self.assertEqual(make(["b", "a"]), make(["b", "a"]))
'''


def w(d: Path, rel: str, text: str) -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def run_batch(d: Path, bid: str, files: dict) -> None:
    code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t")
    if out.get("error") == "risk_confirmation_required":
        code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t", "--confirm-risk", "--note", "위험 범위 확인(시뮬레이션)")
    assert code == 0, out
    lock = out["lock_id"]
    for rel, text in files.items():
        w(d, rel, text)
    for t in [x for x, v in bst(d)["batches"][bid]["run"]["tasks"].items() if v["status"] != "done"]:
        code, out = pb(d, "task-done", "--batch", bid, "--task", t, "--lock", lock)
        assert code == 0, out
    code, out = pb(d, "batch-submit", "--batch", bid, "--lock", lock)
    assert code == 0, out
    code, out = pb(d, "verify", "--batch", bid)
    assert code == 0 and bst(d)["batches"][bid]["status"] == "verified", out


def setup(root: Path) -> tuple[Path, bool]:
    d, ok = F.approved_project(root, "club-build")
    if not ok:
        return d, False
    F.ok(d, "change", "enable", "--confirm", "--note", "변경 요청 기능 켜기(시뮬레이션)")
    w(d, "tools/run_tests.py", VT.RUNNER)
    for pkg in ("src/common/__init__.py", "src/login/__init__.py", "src/round/__init__.py", "tests/__init__.py"):
        w(d, pkg, "")
    DC.commit(d, "code + enable (user)")
    code, out = pb(d, "init"); assert code == 0, out
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    (d / "docs/build").mkdir(parents=True, exist_ok=True)
    (d / "docs/build/implementation-plan.json").write_text(json.dumps(PLAN, ensure_ascii=False, indent=2) + "\n")
    code, out = pb(d, "submit", "plan"); assert code == 0, out
    code, out = pb(d, "approve", "plan", "--revision", "1", "--note", "구현 계획 승인(시뮬레이션)"); assert code == 0, out
    DC.commit(d, "plan (user)")
    run_batch(d, "B1", {"src/login/login.py": LOGIN, "tests/test_login.py": T_LOGIN})
    run_batch(d, "B2", {"src/round/round.py": ROUND, "tests/test_round.py": T_ROUND})
    DC.commit(d, "batches verified (user)")
    return d, True


def flow(d: Path, root: Path) -> None:
    code, out = pb(d, "check")
    check("BC0 준비: 계획 승인, 디자인 L3, B1·B2 verified", code == 0 and out["design"]["level"] == "L3"
          and {k: v["status"] for k, v in out["batches"].items()} == {"B1": "verified", "B2": "verified"}, out)
    # ---- Type A: 제품 코드 버그 수정
    w(d, "src/round/round.py", ROUND.replace("sorted(players)", "sorted(players)  # 버그 수정"))
    code, g = pb(d, "guard", "--base", "HEAD")
    code2, chk = pd(d, "check")
    code3, out = pb(d, "check")
    check("T1 Type A: guard 통과(보호 경로 변경 없음), 디자인 승인 유지, 계획 유효, 바뀐 배치(B2)만 재검증 대상", code == 0 and code2 == 0
          and out["plan"]["status"] == "approved" and out["batches"]["B2"]["status"] == "stale" and out["batches"]["B1"]["status"] == "verified", (g, out))
    code, out = pb(d, "verify", "--batch", "B2")
    check("T1b Type A 회귀 검증(B2 재검증) 통과", code == 0 and bst(d)["batches"]["B2"]["status"] == "verified", out)
    p02 = d / "docs/design/02-screens.md"
    o02 = p02.read_text()
    p02.write_text(o02 + "\n")
    code, g = pb(d, "guard", "--base", "HEAD")
    check("T1c 구현 중 승인 문서 변경은 guard가 보호 경로로 차단(Type A 범위 밖)", code == 2 and "docs/design/02-screens.md" in g["protected_changed"], g)
    p02.write_text(o02)
    code, out = pb(d, "approve", "batch", "--batch", "B2", "--note", "B2 최종 승인(시뮬레이션)")
    assert code == 0, out
    DC.commit(d, "type A (user)")
    # ---- Pending CR
    code, out = pd(d, "change", "open", "--request", DC.mask_request(root, "pb1", "AST-001"), "--scope-note", "배너 가장자리 보정해줘")
    cid = out["id"]
    new = DC.successor(d, root, F.BANNER_MASK(), "pb1")
    DC.swap_ref(d, "AST-001", new)
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "B1 승인(시뮬레이션)")
    check("T16a 진행 중 CR이 영향 주는 배치(B1: SCR-001) 최종 승인 차단(design_change_pending)", code == 2 and out["error"] == "design_change_pending", out)
    code, out = pb(d, "verify", "--batch", "B1")
    check("T16b 영향 배치 검증도 차단(승인 전 디자인으로 증거를 만들지 않음)", code == 2 and out["error"] == "design_change_pending", out)
    code, out = pb(d, "execute-gate", "--batch", "B1")
    check("T16b2 영향 배치 실행 진입(execute-gate)도 차단", code == 2 and out["error"] == "design_change_pending", out)
    code, out = pb(d, "check")
    check("T16c 진행 중 CR은 계획을 outdated로 만들지 않음(차단은 영향 배치에만)", out["plan"]["status"] == "approved", out)
    b2 = bst(d)["batches"]["B2"]
    check("T14a 영향 없는 배치(B2: SCR-002) 승인 유지", b2["status"] == "approved" and b2["approvals"][-1]["valid"], b2.get("approvals"))
    code, out = pb(d, "verify", "--batch", "B2")
    check("T16d 수정 후 아직 범위 재평가 전 → 영향 범위를 알 수 없어 영향 없는 배치(B2)도 보수적으로 차단", code == 2 and out["error"] == "design_change_pending"
          and out["changes"][0]["screens"] is None, out)
    code, sc = pd(d, "change", "scope", "--id", cid)
    code, out = pb(d, "verify", "--batch", "B2")
    check("T16e 범위 재평가(SCR-001만 영향) 후에는 의존성이 분리된 B2 작업 허용", code == 0 and bst(d)["batches"]["B2"]["status"] in ("verified", "approved"), out)
    # ---- 승인
    DC.complete_b(d, cid, "배너 보정 결과 확인, 패치 승인(시뮬레이션)")
    code, out = pb(d, "check")
    st = bst(d)
    check("T15a 승인된 Type B 패치 후 구현 계획 유지(outdated 아님)", out["plan"]["status"] == "approved" and st["plan"]["status"] == "approved", out)
    check("T15b 영향 화면 배치(B1)만 stale, 사유에 패치 ID", st["batches"]["B1"]["status"] == "stale"
          and "AMD-001" in st["batches"]["B1"]["verification"]["stale_reason"], st["batches"]["B1"].get("verification", {}).get("stale_reason"))
    check("T14b 영향 없는 배치(B2) 최종 승인 유지(무효 표시 없음)", st["batches"]["B2"]["status"] == "approved" and st["batches"]["B2"]["approvals"][-1]["valid"])
    code, out = pb(d, "verify", "--batch", "B1")
    code2, out2 = pb(d, "check")
    check("T15c 영향 배치 재검증 후 verified, 다시 check해도 stale로 돌아가지 않음(패치 수 기록)", code == 0 and out2["batches"]["B1"]["status"] == "verified"
          and bst(d)["batches"]["B1"]["verification"]["design_amendments"] == 1, out2)
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "B1 최종 승인(시뮬레이션)")
    check("T15d 패치 반영 디자인 기준으로 B1 최종 승인", code == 0, out)
    EVIDENCE["build"] = {"plan_status": bst(d)["plan"]["status"], "batches": {k: v["status"] for k, v in bst(d)["batches"].items()}}
    DC.commit(d, "patched + B1 (user)")
    # ---- 체인 문제
    p = d / ".ai-workflow/design.json"
    raw0 = p.read_bytes()
    s = json.loads(raw0)
    s["changes"]["chain"][0]["statement"] = "위조"
    p.write_text(json.dumps(s, ensure_ascii=False, indent=2))
    w(d, "src/login/login.py", LOGIN + "\n")
    code, out = pb(d, "execute-gate", "--batch", "B1")
    code2, out2 = pb(d, "verify", "--batch", "B1")
    check("T11 체인 조작 시 Build도 화면 배치 진행 차단(명시적 오류)", code == 2 and code2 == 2 and out2["error"] in ("design_amendment_chain_broken", "inputs_changed"), (out, out2))
    p.write_bytes(raw0)
    w(d, "src/login/login.py", LOGIN)


def main() -> int:
    root = TMP.mkdtemp("product-build-change-test-")
    d, ok = setup(root)
    if not ok:
        skip("M1 build 연동", "프리뷰 빌드(pnpm)를 할 수 없어 프리뷰 승인 프로젝트를 만들지 못했습니다")
    else:
        flow(d, root)
    out = os.environ.get("PW_CHANGE_EVIDENCE_BUILD")
    if out:
        Path(out).write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=2))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(TMP.run(main))
