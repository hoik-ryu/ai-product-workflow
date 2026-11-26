#!/usr/bin/env python3
"""AC-164(취소 경기 복원 제거) 축소 재현: 기존 승인 경로 vs 변경 패키지 경로 생산성 비교(실제 실행).

같은 픽스처 두 벌에서 AC-002(인증 실패 안내)를 폐기합니다.
- 기존 경로: T9 reopen → 기획 r2 제출·승인 → 디자인 rebase(모든 디자인 승인 해제) → UX Planning·UX Spec(구조 확인)·DD·Preview 재제출·재승인
  → 구현 계획 reopen·submit·approve → B1 재작업(테스트 변경 확인)·최종 승인
- 패키지 경로: 계약 승인 1회 → 단계 엔진 검증 연속 → 최종 통합 승인 1회
측정: 사용자 개입 수, 단계별 별도 승인 수, 변경된 산출물 수, 내용 변경 없이 revision만 바뀐 파일·단계 수.
기존 경로에서 엔진이 막는 지점이 있으면 그대로 기록합니다(우회하지 않음).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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
DOCS = ["docs/design/00-ux-decisions.md", *T.SPEC, "docs/design/06-preview-review.md", "docs/design/07-design-direction.md"]


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:900]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:900]}"))


def bump(d: Path, rel: str, rev: int) -> None:
    p = d / rel
    p.write_text(re.sub(r"^revision: \d+$", f"revision: {rev}", p.read_text(), count=1, flags=re.M))


def changed_files(d: Path, base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", base], cwd=d, capture_output=True, text=True).stdout.split()
    return sorted(f for f in out if not f.startswith((".ai-workflow/", "docs/changes/")))


def revision_only(d: Path, base: str, files: list[str]) -> list[str]:
    """front matter revision·기준 revision 줄만 바뀐 파일(내용 변경 없음)."""
    out = []
    for f in files:
        diff = subprocess.run(["git", "diff", "-U0", base, "--", f], cwd=d, capture_output=True, text=True).stdout
        lines = [x for x in diff.splitlines() if x[:1] in "+-" and not x.startswith(("+++", "---"))]
        if lines and all(re.match(r"^[+-]\s*(revision|ux_spec_revision|design_direction_revision|\"ux_spec_revision\"|\"design_direction_revision\")\b", x)
                         or re.match(r"^[+-]\s*\"(ux_spec_revision|design_direction_revision)\":", x) for x in lines):
            out.append(f)
    return out


def old_path(d: Path, root: Path) -> dict:
    asks = P.Asks()
    stage_approvals = 0
    blocked = []
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()

    def must(fn, *a):
        code, out = fn(d, *a)
        if code != 0:
            blocked.append({"cmd": " ".join(map(str, a[:3])), "error": out.get("error"), "message": (out.get("message") or "")[:160]})
        return code, out
    # 기획 T9
    must(ps, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", asks.user("T9 재개 확인", "기획 재개 확인(시뮬레이션)"))
    P.retire_planning(d)
    must(ps, "submit", "--stage", "planning", "--revision", "2", "--confirm")
    must(ps, "approve", "--stage", "planning", "--revision", "2", "--note", asks.user("Planning r2 승인", "Planning r2 승인(시뮬레이션)"))
    stage_approvals += 1
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "planning r2 (user)")
    # 디자인 rebase → 모든 단계 재승인
    pd(d, "check")
    must(pd, "rebase", "--confirm") if asks.user("디자인 rebase 확인(모든 디자인 승인 해제)", "ok") else None
    bump(d, DOCS[0], 2)
    must(pd, "done", "--path", DOCS[0])
    must(pd, "submit", "--stage", "ux_planning")
    must(pd, "approve", "--stage", "ux_planning", "--revision", "2", "--note", asks.user("UX Planning r2 승인", "UX Planning 승인(시뮬레이션)"))
    stage_approvals += 1
    must(pd, "begin", "--stage", "ux_spec")
    P.retire_design(d)
    T.G(d, "checkout", "--", "design-preview/src/screens/SCR-001.tsx")  # 프리뷰는 프리뷰 단계에서
    for f in T.SPEC:
        bump(d, f, 2)
        must(pd, "done", "--path", f)
    must(pd, "checkpoint", "--note", asks.user("UX Spec 구조 확인", "구조 확인(시뮬레이션)"))
    must(pd, "submit", "--stage", "ux_spec")
    must(pd, "approve", "--stage", "ux_spec", "--revision", "2", "--note", asks.user("UX Spec r2 승인", "UX Spec 승인(시뮬레이션)"))
    stage_approvals += 1
    must(pd, "begin", "--stage", "design_direction")
    p7 = d / DOCS[-1]
    p7.write_text(re.sub(r"ux_spec_revision: \d+", "ux_spec_revision: 2", p7.read_text()).replace("ux_spec r1(승인됨)", "ux_spec r2(승인됨)"))
    bump(d, DOCS[-1], 2)
    must(pd, "done", "--path", DOCS[-1])
    must(pd, "submit", "--stage", "design_direction")
    must(pd, "approve", "--stage", "design_direction", "--revision", "2", "--note", asks.user("Design Direction r2 승인", "DD 승인(시뮬레이션)"))
    stage_approvals += 1
    must(pd, "begin", "--stage", "preview")
    man = d / "design-preview/preview.manifest.json"
    m = json.loads(man.read_text())
    m["ux_spec_revision"], m["design_direction_revision"] = 2, 2
    man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    s1 = d / "design-preview/src/screens/SCR-001.tsx"
    s1.write_text(s1.read_text().replace("<p>상태: {state}</p>", "<p>상태: {state === 'SCR-001-ST3' ? '오류' : state}</p>"))
    bump(d, DOCS[-2], 2)
    must(pd, "done", "--path", DOCS[-2])
    must(pd, "preview-verify")
    must(pd, "submit", "--stage", "preview")
    must(pd, "approve", "--stage", "preview", "--revision", "2", "--note", asks.user("Preview r2 승인", "Preview 승인(시뮬레이션)"))
    stage_approvals += 1
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "design r2 (user)")
    # 구현 계획
    pb(d, "check")
    must(pb, "reopen", "plan", "--reason", "AC-002 폐기")
    P.retire_build(d)
    must(pb, "submit", "plan")
    rev = json.loads((d / ".ai-workflow/build.json").read_text())["plan"]["revision"]
    must(pb, "approve", "plan", "--revision", rev, "--note", asks.user("Build Plan 재승인", "계획 승인(시뮬레이션)"))
    stage_approvals += 1
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "plan (user)")
    # B1 재작업: 기존 엔진은 검증·승인된 배치를 다시 여는 길이 stale·실패뿐
    (d / "tests/test_login.py").write_text(P.T_LOGIN_RETIRED)
    pb(d, "check")
    code, out = must(pb, "resume", "--batch", "B1")
    b1 = json.loads((d / ".ai-workflow/build.json").read_text())["batches"]["B1"]["status"]
    rework = {"status_after_check": b1, "resume": out.get("error") or out.get("status")}
    if code == 0:
        lock = out.get("lock_id") or json.loads((d / ".ai-workflow/build.json").read_text())["batches"]["B1"]["run"].get("lock_id")
        must(pb, "batch-submit", "--batch", "B1", "--lock", lock, "--confirm-test-changes", "--note", asks.user("테스트 변경 확인", "테스트 삭제 확인"))
        must(pb, "verify", "--batch", "B1")
        must(pb, "approve", "batch", "--batch", "B1", "--note", asks.user("B1 최종 승인", "B1 승인"))
    else:
        asks.user("(기존 경로 막힘) B1 재작업을 진행하려면 사용자 결정 필요", "-")
    files = changed_files(d, base)
    return {"asks": asks.n, "ask_log": asks.log, "stage_approvals": stage_approvals, "changed_files": files, "revision_only_files": revision_only(d, base, files),
            "design_stage_revisions": {k: v["revision"] for k, v in F.state(d)["stages"].items()}, "blocked": blocked, "b1_rework": rework}


def new_path(d: Path, root: Path) -> dict:
    asks = P.Asks()
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    P.ok(pc, d, "enable", "--confirm", "--note", "변경 패키지 기능 켬(설정, 1회)")
    P.BCcommit(d, "enable (user)")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
    P.ok(pc, d, "open", "--contract", P.contract(root, "cn"))
    P.ok(pc, d, "approve-contract", "--id", "CP-001", "--note", asks.user("변경 계약 승인", "이 계약대로 진행(시뮬레이션)"))
    P.retire_planning(d)
    P.ok(pc, d, "snapshot-planning", "--id", "CP-001")
    P.ok(pd, d, "change", "open", "--package", "CP-001")
    P.retire_design(d)
    P.ok(pd, d, "change", "verify", "--id", "CR-001")
    P.ok(pd, d, "change", "submit", "--id", "CR-001")
    P.ok(pc, d, "review", "--id", "CP-001", "--unit", "VD-001", "--reason", "인증 실패 안내와 무관")
    P.retire_build(d)
    P.ok(pc, d, "snapshot-plan", "--id", "CP-001")
    code, out = pb(d, "batch-start", "--batch", "B1", "--owner", "t")
    lock = out["lock_id"]
    (d / "tests/test_login.py").write_text(P.T_LOGIN_RETIRED)
    for t in [x for x, v in json.loads((d / ".ai-workflow/build.json").read_text())["batches"]["B1"]["run"]["tasks"].items() if v["status"] != "done"]:
        P.ok(pb, d, "task-done", "--batch", "B1", "--task", t, "--lock", lock)
    P.ok(pb, d, "batch-submit", "--batch", "B1", "--lock", lock)
    P.ok(pb, d, "verify", "--batch", "B1")
    P.ok(pb, d, "verify", "--batch", "B2")
    P.ok(pc, d, "regression", "--id", "CP-001")
    P.ok(pc, d, "submit-final", "--id", "CP-001")
    P.ok(pc, d, "approve-final", "--id", "CP-001", "--note", asks.user("최종 통합 승인", "결과 확인, 최종 승인(시뮬레이션)"))
    files = changed_files(d, base)
    return {"asks": asks.n, "ask_log": asks.log, "stage_approvals": 0, "changed_files": files, "revision_only_files": revision_only(d, base, files),
            "design_stage_revisions": {k: v["revision"] for k, v in F.state(d)["stages"].items()}, "blocked": []}


def main() -> int:
    if shutil.which("pnpm") is None:
        print("SKIP 리허설  -- pnpm 없음")
        results.append(("리허설", True, "SKIP"))
        return 0
    root = TMP.mkdtemp("product-change-rehearsal-")
    d_old, ok1 = P.setup(root / "old")
    d_new, ok2 = P.setup(root / "new")
    if not (ok1 and ok2):
        print("SKIP 리허설  -- 픽스처 실패")
        return 0
    o = old_path(d_old, root / "old")
    n = new_path(d_new, root / "new")
    report = {"old": o, "new": n}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    check("R1 사용자 개입: 패키지 경로 2회, 기존 경로보다 적음", n["asks"] == 2 and o["asks"] > n["asks"], (o["asks"], n["asks"]))
    check("R2 단계별 별도 승인: 패키지 0회(통합 승인 2회로 대체), 기존 6회(기획·디자인 4·계획)", n["stage_approvals"] == 0 and o["stage_approvals"] == 6, o["stage_approvals"])
    check("R3 디자인 단계 revision 변경 없음(패키지) vs 모두 r2(기존)", set(n["design_stage_revisions"].values()) == {1}
          and set(o["design_stage_revisions"].values()) == {2}, (o["design_stage_revisions"], n["design_stage_revisions"]))
    shared = {"docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md", "docs/planning/05-acceptance-criteria.md"}
    n_design = [f for f in n["revision_only_files"] if f not in shared]
    check("R4 revision만 바뀐 파일: 패키지는 디자인·프리뷰 0개(기획 4문서 revision 공유 규칙분만 남음), 기존 경로보다 적음",
          not n_design and len(n["revision_only_files"]) < len(o["revision_only_files"]) and set(n["revision_only_files"]) <= shared,
          (o["revision_only_files"], n["revision_only_files"]))
    out = os.environ.get("PW_REHEARSAL_EVIDENCE")
    if out:
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(TMP.run(main))
