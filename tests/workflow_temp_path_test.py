#!/usr/bin/env python3
"""TEMP 산출물 경로(temp-dir)·권장 .gitignore 규칙 테스트(자체 완결형, docs/policies/artifact-retention.md).

- product-design·product-build의 temp-dir이 같은 저장소 밖 경로를 만들고, 제품 저장소의 Git 변경 파일·상태 파일을 늘리지 않는지 확인합니다.
- 권장 .gitignore 블록이 임시 결과만 제외하고 제품 자산·승인 근거는 제외하지 않는지 `git check-ignore`로 확인합니다.

실행: python3 tests/workflow_temp_path_test.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _tmpdirs as TMP  # noqa: E402

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
PD = ENGINE / "skills/product-design/scripts/product_design.py"
PB = ENGINE / "skills/product-build/scripts/product_build.py"
RECOMMENDED = ENGINE / "docs/policies/gitignore.recommended"
results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:600]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:600]}"))


def git(repo: Path, *args) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def mkrepo(prefix: str) -> Path:
    p = TMP.mkdtemp(prefix)
    git(p, "init", "-q")
    git(p, "config", "user.email", "t@example.com"); git(p, "config", "user.name", "t")
    (p / ".ai-workflow").mkdir()
    (p / ".ai-workflow/state.yaml").write_text("fixture: true\n", encoding="utf-8")
    (p / "README.md").write_text("x\n", encoding="utf-8")
    git(p, "add", "-A"); git(p, "commit", "-qm", "init")
    return p


def run(script: Path, project: Path, *args, root: Path | None = None) -> tuple[int, dict]:
    env = dict(os.environ)
    env.pop("XDG_CACHE_HOME", None)
    if root is not None:
        env["AI_WORKFLOW_TEMP_ROOT"] = str(root)
    p = subprocess.run([sys.executable, "-I", str(script), "temp-dir", "--project", str(project), *args], capture_output=True, text=True, env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def snapshot(repo: Path) -> dict:
    return {str(f.relative_to(repo)): f.read_bytes() for f in repo.rglob("*") if f.is_file() and ".git" not in f.relative_to(repo).parts}


def main() -> None:
    root = TMP.mkdtemp("pw-temp-root-")
    proj = mkrepo("pw-temp-proj-")
    before = snapshot(proj)

    # 1) 저장소 밖 실행 폴더
    code, o = run(PD, proj, "--purpose", "preview-review", root=root)
    d = Path(o.get("temp_dir", "/nonexistent"))
    check("design: temp-dir 성공", code == 0 and o.get("ok"), o)
    check("design: 저장소 밖 + 루트 아래", not o.get("inside_repo") and str(d).startswith(str(root)) and d.is_dir(), o)
    check("design: 프로젝트·용도·실행 단위 구조", d.parent.name == "preview-review" and d.parent.parent.name == "runs"
          and d.parent.parent.parent.name == o.get("project_key"), d)
    meta = json.loads((d / "RUN.json").read_text(encoding="utf-8"))
    check("design: RUN.json 메타(TEMP·보관 기간 미설정)", meta.get("class") == "TEMP" and meta.get("retention_days") is None
          and meta.get("format") == "ai-workflow-temp-run/v1", meta)
    (d / "shot.png").write_bytes(b"\x89PNG fake")
    check("design: 저장소 Git 변경 없음", git(proj, "status", "--porcelain", "--untracked-files=all") == "", git(proj, "status", "--porcelain"))
    check("design: 저장소 파일·상태 파일 불변", snapshot(proj) == before, set(snapshot(proj)) ^ set(before))

    # 2) product-build도 같은 루트·같은 프로젝트 키, 실행마다 다른 폴더
    code, o2 = run(PB, proj, "--purpose", "e2e", root=root)
    check("build: temp-dir 성공·같은 프로젝트 키", code == 0 and o2.get("project_key") == o.get("project_key") and o2.get("root") == o.get("root"), o2)
    _, o3 = run(PD, proj, "--purpose", "preview-review", root=root)
    check("실행마다 다른 폴더", o3.get("temp_dir") and o3["temp_dir"] != o["temp_dir"], (o3, o))

    # 3) 같은 폴더 이름의 다른 저장소는 다른 키
    other_parent = TMP.mkdtemp("pw-temp-other-")
    other = other_parent / proj.name
    other.mkdir()
    _, o4 = run(PD, other, "--purpose", "debug", root=root)
    check("다른 경로 같은 이름 → 다른 프로젝트 키", o4.get("project_key") and o4["project_key"] != o["project_key"], (o4, o))

    # 4) 루트가 저장소 안이면 거부
    code, o5 = run(PD, proj, "--purpose", "debug", root=proj / "tmp-inside")
    check("저장소 안 루트 거부", code == 2 and o5.get("error") == "temp_root_inside_project" and not (proj / "tmp-inside").exists(), o5)

    # 5) 입력 검사
    code, o6 = run(PD, proj, "--purpose", "Bad Name", root=root)
    check("잘못된 용도 거부", code == 2 and o6.get("error") == "invalid_purpose", o6)
    code, o7 = run(PB, proj, "--purpose", "debug", "--keep", root=root)
    check("--keep에 이유 필수", code == 2 and o7.get("error") == "keep_note_required", o7)
    code, o8 = run(PD, proj, root=root)
    check("--purpose/--mark-keep 없으면 거부", code == 2, o8)

    # 6) 오류 재현 자료 보관
    code, k = run(PD, proj, "--purpose", "debug", "--keep", "--note", "SCR-101 렌더 실패 재현", root=root)
    kd = Path(k.get("temp_dir", "/nonexistent"))
    check("--keep → kept/ + KEEP.json", code == 0 and kd.parent.parent.name == "kept" and (kd / "KEEP.json").is_file(), k)
    code, m = run(PB, proj, "--mark-keep", o["temp_dir"], "--note", "회귀 비교용", root=root)
    check("--mark-keep: 기존 폴더 표시(이동 없음)", code == 0 and (d / "KEEP.json").is_file() and (d / "shot.png").is_file(), m)
    code, m2 = run(PD, proj, "--mark-keep", str(proj), "--note", "x", root=root)
    check("--mark-keep: TEMP 폴더가 아니면 거부", code == 2 and m2.get("error") == "not_temp_run" and not (proj / "KEEP.json").exists(), m2)
    code, m3 = run(PD, other, "--mark-keep", o["temp_dir"], "--note", "x", root=root)
    check("--mark-keep: 다른 프로젝트의 폴더 거부", code == 2 and m3.get("error") == "not_temp_run", m3)

    # 7) 저장소 밖에 쓸 수 없으면 저장소 안 폴백(자체 .gitignore로 Git 변경 없음)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        check("폴백 검사(root 권한이라 생략)", True)
    else:
        ro = TMP.mkdtemp("pw-temp-ro-")
        os.chmod(ro, 0o500)
        try:
            code, f = run(PD, proj, "--purpose", "visual", root=ro / "temp")
            fd = Path(f.get("temp_dir", "/nonexistent"))
            check("쓸 수 없는 루트 → .ai-workflow/tmp 폴백", code == 0 and f.get("location") == "repo_fallback" and f.get("fallback_reason")
                  and fd.is_dir() and str(fd).startswith(str((proj / ".ai-workflow/tmp").resolve())), f)
            (fd / "frame-001.png").write_bytes(b"x")
            check("폴백: Git 변경 없음(자체 .gitignore)", git(proj, "status", "--porcelain", "--untracked-files=all") == "",
                  git(proj, "status", "--porcelain", "--untracked-files=all"))
            check("폴백: state.yaml 불변", (proj / ".ai-workflow/state.yaml").read_bytes() == before[".ai-workflow/state.yaml"])
            code, f2 = run(PB, proj, "--purpose", "visual", "--location", "outside", root=ro / "temp")
            check("--location outside: 폴백하지 않고 거부", code == 2 and f2.get("error") == "temp_root_unwritable", f2)
        finally:
            os.chmod(ro, 0o700)

    # 8) 두 Skill의 구현 일치(Skill 간 import 없이 복사본 유지)
    a = (ENGINE / "skills/product-design/scripts/pd_temp.py").read_text(encoding="utf-8").splitlines()
    b = (ENGINE / "skills/product-build/scripts/pb_temp.py").read_text(encoding="utf-8").splitlines()
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    check("pd_temp.py·pb_temp.py 구현 일치(교차 참조 주석 1줄만 다름)", len(a) == len(b) and len(diff) == 1, diff[:3])

    # 9) 권장 .gitignore: 임시 결과만 제외, 제품 자산·승인 근거·기준 스냅샷은 추적
    text = RECOMMENDED.read_text(encoding="utf-8")
    rules = [x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")]
    check("권장 규칙: 시작·끝 표식", text.startswith("# >>> ai-product-workflow recommended") and "# <<< ai-product-workflow recommended" in text)
    check("권장 규칙: 이미지·JSON·로그 확장자 전체 무시 없음", not any(r.lstrip("*/").lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".json", ".log")
                                                       or r.lower() in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.svg", "*.json", "*.log") for r in rules), rules)
    g = mkrepo("pw-temp-gi-")
    (g / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    with (g / ".gitignore").open("a", encoding="utf-8") as fh:
        fh.write(text)
    ignored = ["test-results/run-1/shot.png", "playwright-report/index.html", ".ai-workflow/tmp/runs/x.png", "npm-debug.log", "pnpm-debug.log",
               "node_modules/a.js"]
    kept = ["design-profile/assets/logo.png", "frontend/public/assets/icon.svg", "design-preview/src/screens/SCR-101.tsx",
            "design-explore/V05/selection/evidence/SCR-101-mobile.png", "design-explore/V05/selection/selection.json",
            "docs/design/06-preview-review.md", ".ai-workflow/design.json", "e2e/home.spec.ts-snapshots/home-chromium.png",
            "frontend/src/data/tutorial.json", "docs/build/manual-evidence/EM-001-console.log", "qa/manual/session.log"]

    def is_ignored(rel: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=g).returncode == 0
    check("권장 규칙: 임시 결과 제외", all(is_ignored(r) for r in ignored), [r for r in ignored if not is_ignored(r)])
    check("권장 규칙: 제품 자산·승인 근거·기준 스냅샷은 추적", not any(is_ignored(r) for r in kept), [r for r in kept if is_ignored(r)])
    check("권장 규칙: 기존 규칙 유지(덮어쓰지 않음)", (g / ".gitignore").read_text(encoding="utf-8").startswith("node_modules/\n"))

    fails = [r for r in results if not r[1]]
    print(f"RESULT {len(results) - len(fails)}/{len(results)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    TMP.run(main)
