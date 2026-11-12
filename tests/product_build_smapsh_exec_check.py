#!/usr/bin/env python3
"""/product-build M2.2 배치 실행을 실제 프로젝트(SMAPSH) **복제본**에서 확인합니다(원본 경로는 거부).

복제본에는 원본의 미커밋 구현(B0–B4)과 다른 세션의 백엔드 작업이 그대로 있습니다. 그 조건에서
범위 안 미커밋 파일 확인, 다른 세션 파일 충돌 차단, 보호 경로 차단, 일시 중지·재개, 연속 배치를 봅니다.
코드는 테스트가 Claude 대신 작은 변경으로 씁니다. 검증 명령(pnpm·uv)은 복제본에 의존성이 없어 실행하지 않습니다.

실행: python3 tests/product_build_smapsh_exec_check.py <복제본 경로> [--original <원본 경로>]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

results = T.results
check, pb = T.check, T.pb


def main() -> int:
    clone = Path(sys.argv[1]).resolve()
    original = Path(sys.argv[sys.argv.index("--original") + 1]).resolve() if "--original" in sys.argv else (Path.home() / "Desktop/badminton-playbook").resolve()
    if clone == original or original in clone.parents:
        print("원본 저장소에서는 실행하지 않습니다.")
        return 2
    snap = T.protected_snapshot(clone)
    report = {}
    pb(clone, "init")
    plan = T.draft_of(clone)
    by_title = {b["title"]: b for b in plan["batches"]}
    b0 = plan["batches"][0]
    tut = next(b for b in plan["batches"] if set(b["screens"]) == {"SCR-102", "SCR-103"})
    b0["paths"] = {"allow": ["frontend/src/components/"], "shared": []}
    tut["paths"] = {"allow": ["frontend/src/features/tutorial/", "frontend/src/pages/Tutorial*.tsx"], "shared": ["frontend/src/routes/router.tsx"]}
    T.save_plan(clone, plan)
    pb(clone, "waiver", "add", "--reason", "복제본 검증: 배치 구현", "--all-ui", "--note", "복제본 검증용 승인", "--confirm")
    code, out = pb(clone, "submit", "plan")
    code2, out2 = pb(clone, "approve", "plan", "--revision", "1", "--note", "복제본 검증용: 계획 승인")
    check("X1 SMAPSH 복제본 계획 승인(실행 범위 paths는 B0·튜토리얼 배치만 채움)", code == 0 and code2 == 0, (out, out2))
    report["batches"] = {b["id"]: (b["title"], b["screens"]) for b in plan["batches"]}

    code, out = pb(clone, "batch-start", "--batch", b0["id"], "--owner", "clone-check")
    check("X2 실제 미커밋 구현(components) 위에서 시작 → uncommitted_in_scope로 멈춤", code == 2 and out.get("error") == "uncommitted_in_scope", out.get("error"))
    report["uncommitted_in_scope_B0"] = len(out.get("paths", []))
    code, out = pb(clone, "batch-start", "--batch", b0["id"], "--owner", "clone-check", "--allow-dirty-in-scope", "--note", "복제본 검증: 기존 미커밋 컴포넌트를 배치 작업 대상으로 확인")
    lock = out.get("lock_id")
    report["preserved_uncommitted"] = len(out.get("preserved_uncommitted", []))
    check("X3 확인 후 시작: 시작 때 미커밋 파일 전체를 기준선으로 기록, 브랜치 권장", code == 0 and lock and report["preserved_uncommitted"] > 50
          and "branch_recommendation" in out, {k: out.get(k) for k in ("error", "message")})
    badge = clone / "frontend/src/components/Badge.tsx"
    badge_orig = badge.read_text()
    badge.write_text(badge_orig + "\n// 복제본 검증: 배치 작업 변경\n")
    auth = clone / "backend/app/modules/auth/router.py"
    auth_orig = auth.read_text()
    auth.write_text(auth_orig + "\n# 다른 파일을 잘못 건드림\n")
    code, out = pb(clone, "task-done", "--batch", b0["id"], "--task", f"{b0['id']}-T1", "--lock", lock)
    check("X4 다른 세션의 미커밋 백엔드 작업(auth/router.py) 변경 → base_conflict 차단", code == 2 and out.get("error") == "base_conflict"
          and out["paths"] == ["backend/app/modules/auth/router.py"], out)
    auth.write_text(auth_orig)
    d02 = clone / "docs/design/02-screens.md"
    d02_orig = d02.read_text()
    d02.write_text(d02_orig + "\n")
    code, out = pb(clone, "task-done", "--batch", b0["id"], "--task", f"{b0['id']}-T1", "--lock", lock)
    check("X5 승인된 UX Spec 변경 → protected_path_changed 차단", code == 2 and out.get("error") == "protected_path_changed", out)
    d02.write_text(d02_orig)
    code, out = pb(clone, "task-done", "--batch", b0["id"], "--task", f"{b0['id']}-T1", "--lock", lock)
    check("X6 원상 복구 후 기록: 배치 변경 파일만 기록", code == 0 and out["files"] == ["frontend/src/components/Badge.tsx"], out)
    code, out = pb(clone, "batch-submit", "--batch", b0["id"], "--lock", lock)
    check("X7 B0 implemented, 다음 배치 제안", code == 0 and out["status"] == "implemented", out)
    report["next_batches_after_B0"] = out.get("next_batches")

    code, out = pb(clone, "batch-start", "--batch", tut["id"], "--owner", "clone-check")
    check("X8 튜토리얼 배치: 공유 파일(router.tsx, 미커밋 수정 상태) → uncommitted_in_scope", code == 2 and out.get("error") == "uncommitted_in_scope"
          and "frontend/src/routes/router.tsx" in out.get("paths", []), out)
    code, out = pb(clone, "batch-start", "--batch", tut["id"], "--owner", "clone-check", "--allow-dirty-in-scope", "--note", "복제본 검증: router.tsx 확인")
    lock = out.get("lock_id")
    tasks = [t["id"] for t in out.get("tasks", [])]
    stage = clone / "frontend/src/features/tutorial/stage.ts"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text("export const STAGE_COUNT = 0 // 복제본 검증\n")
    code1, out1 = pb(clone, "task-done", "--batch", tut["id"], "--task", tasks[0], "--lock", lock)
    code2, out2 = pb(clone, "pause", "--batch", tut["id"], "--lock", lock, "--note", "복제본 검증: 중단")
    (clone / "frontend/src/features/tutorial/extra.ts").write_text("export {}\n")
    code3, out3 = pb(clone, "resume", "--owner", "clone-check-2")
    check("X9 일시 중지 후 그 사이 생긴 파일 → resume이 external_changes로 보고(덮어쓰지 않음)", code == 0 and code1 == 0 and code2 == 0
          and code3 == 2 and out3.get("error") == "external_changes" and out3["changed"] == ["frontend/src/features/tutorial/extra.ts"], (out1, out2, out3))
    code, out = pb(clone, "resume", "--owner", "clone-check-2", "--accept-changes", "--note", "복제본 검증: 같은 작업으로 확인")
    lock = out.get("lock_id")
    ok = code == 0 and out["done"] == [tasks[0]]
    for t in tasks[1:]:
        c, o = pb(clone, "task-done", "--batch", tut["id"], "--task", t, "--lock", lock)
        ok = ok and c == 0
    c, o = pb(clone, "batch-submit", "--batch", tut["id"], "--lock", lock)
    check("X10 재개 후 남은 작업만 기록하고 제출(implemented)", ok and c == 0, o)
    code, st = pb(clone, "status")
    report["status"] = {k: v["status"] for k, v in st["build"]["batches"].items()}
    check("X11 승인 문서·상태 불변, 잠금 없음, 검증·승인 상태 없음", T.protected_snapshot(clone) == snap and st["build"]["lock"] is None
          and not any(v in ("verified", "approved") for v in report["status"].values()))
    print("\n=== 보고용 요약 ===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
