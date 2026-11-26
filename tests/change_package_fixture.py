"""변경 패키지(/product-change) 테스트 공용 픽스처·도우미(import 전용).

AC-164(취소 경기 복원 제거) 사례를 축소 재현합니다: 승인된 기획·디자인(v2, DD, 프리뷰)·구현 계획·배치(B1 로그인, B2 대진)가 있는 제품에서
AC-002(인증 실패 시 안내, SCR-001-ST3)를 폐기합니다. AC-002는 07 Design Direction과 프리뷰 화면 파일에 **직접 적혀 있지 않지만**
SCR-001을 통해 간접 영향을 받습니다(AC-002 → 05 추적 행 → SCR-001-ST3 → SCR-001 → VD-001·프리뷰 SCR-001.tsx·B1·test_login.py).
모든 승인 문장은 임시 프로젝트 안의 테스트 시뮬레이션입니다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(HERE))
import change_fixture as F  # noqa: E402
import product_build_change_test as BC  # noqa: E402
import product_design_test as T  # noqa: E402

PC = ENGINE / "skills/product-change/scripts/product_change.py"
PS = ENGINE / "skills/product-start/scripts/ps_state.py"
PLANNING = ["docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md", "docs/planning/05-acceptance-criteria.md"]


class Asks:
    """사용자 개입(엔진이 사용자 문장을 요구해 작업을 멈춘 지점) 계수."""

    def __init__(self):
        self.n = 0
        self.log: list[str] = []

    def user(self, what: str, text: str) -> str:
        self.n += 1
        self.log.append(what)
        return text


def _run(script: Path, *args):
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PC_SIMULATE_FAIL_AT")}
    p = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True, env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": (p.stdout + p.stderr)[-3000:]}


def pc(d: Path, *args):
    return _run(PC, *args, "--project", d)


def ps(d: Path, *args):
    return _run(PS, *args, "--project", d)


def ok(fn, d, *args):
    code, out = fn(d, *args)
    assert code == 0, (args, out)
    return out


def setup(root: Path, name: str = "club-pkg", approve_batches: bool = True) -> tuple[Path, bool]:
    d, ok_ = BC.setup(root)
    if not ok_:
        return d, False
    if approve_batches:
        for bid in ("B1", "B2"):
            code, out = F.pb(d, "approve", "batch", "--batch", bid, "--note", f"{bid} 최종 승인(픽스처 시뮬레이션)")
            assert code == 0, out
    BCcommit(d, "batches approved (user)")
    return d, True


def BCcommit(d: Path, msg: str) -> None:
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", msg)


def contract(root: Path, name: str, **over) -> Path:
    c = {"schema": "change-contract/v1", "purpose": "인증 실패 안내(AC-002)를 폐기한다", "policy": "로그인 실패 시 별도 안내 문구를 보여 주지 않고 일반 오류 상태만 둔다",
         "ids": {"add": [], "modify": [], "remove": ["AC-002", "FLOW-001-S1a"]},
         "keep": ["AC-001 로그인 성공 시 홈 이동", "SCR-001 레이아웃·버튼 위치", "VD-001 시각 결정"],
         "design": {"units": ["VD-001"], "screens": ["SCR-001"], "files": []},
         "build": {"rework": ["B1"], "regression": ["B2"]},
         "files": ["src/login/**", "tests/test_login.py"],
         "db_api": {"migrations": [], "api": {"add": [], "modify": [], "remove": []}},
         "tests": {"remove": [{"ac": "AC-002", "paths": ["tests/test_login.py"]}], "modify": [], "add": []},
         "risky_ops": ["security"], "verification": ["B1·B2 회귀", "SCR-001 화면 실측"]}
    for k, v in over.items():
        c[k] = v
    p = root / f"{name}.json"   # 프로젝트 밖
    p.write_text(json.dumps(c, ensure_ascii=False, indent=2))
    return p


def retire_planning(d: Path, rev: int = 2) -> None:
    """기획 개정: AC-002·FLOW-001-S1a를 취소선으로 폐기(ID 재사용 없음), 4개 문서 front matter revision 공유."""
    for f in PLANNING:
        p = d / f
        t = re.sub(r"^revision: \d+$", f"revision: {rev}", p.read_text(), count=1, flags=re.M)
        if f.endswith("05-acceptance-criteria.md"):
            t = t.replace("### AC-002: 인증 실패 시 안내", f"### ~~AC-002~~: ~~인증 실패 시 안내~~ *(r{rev}에서 폐기)*")
        if f.endswith("04-user-flows.md"):
            t = t.replace("- FLOW-001-S1a: 인증 실패 시 다시 시도", f"- ~~FLOW-001-S1a~~: ~~인증 실패 시 다시 시도~~ *(r{rev}에서 폐기)*")
        p.write_text(t)


def retire_design(d: Path) -> None:
    """디자인 개정(계약 범위): 05 추적·03 흐름 행을 이력 표기로, 02 SCR-001 오류 상태 설명 변경, 프리뷰 SCR-001에서 안내 문구 제거."""
    p = d / "docs/design/05-design-traceability.md"
    p.write_text(p.read_text().replace("| AC-002 | SCR-001-ST3 | |", "| ~~AC-002~~ | ~~SCR-001-ST3~~ | (r2 폐기) |"))
    p = d / "docs/design/03-screen-flows.md"
    p.write_text(p.read_text().replace("| FLOW-001-S1a | SCR-001-ST3 | 실패 |", "| ~~FLOW-001-S1a~~ | ~~SCR-001-ST3~~ | (r2 폐기) |"))
    p = d / "docs/design/02-screens.md"
    t = p.read_text()
    i = t.index("## SCR-001")
    j = t.index("## SCR-002")
    blk = t[i:j].replace("| SCR-001-ST3 | 오류 | 오류 안내 |", "| SCR-001-ST3 | 오류 | 일반 오류 표시 |")
    p.write_text(t[:i] + blk + t[j:])
    p = d / "design-preview/src/screens/SCR-001.tsx"
    p.write_text(p.read_text().replace("<p>상태: {state}</p>", "<p>상태: {state === 'SCR-001-ST3' ? '오류' : state}</p>"))


def retire_build(d: Path) -> None:
    plan = json.loads((d / "docs/build/implementation-plan.json").read_text())
    for b in plan["batches"]:
        if b["id"] == "B1":
            b["acs"] = ["AC-001"]
    (d / "docs/build/implementation-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


T_LOGIN_RETIRED = """import unittest
from login.login import login
class L(unittest.TestCase):
    def test_home(self):
        \"\"\"[AC-001] 로그인하면 홈으로 간다\"\"\"
        self.assertEqual(login(True), "home")
"""
