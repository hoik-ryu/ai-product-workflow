"""/product-build 스캔: 기술 스택·검증 명령 후보·공통 컴포넌트·기존 코드의 ID 언급·라우트를 읽기 전용으로 탐지합니다.

프레임워크별 분기는 '파일이 있으면 그 이름을 보고한다' 수준만 둡니다. 판정(구현 완료·검증 통과)은 하지 않습니다.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from pb_core import BOILERPLATE_REL

TEXT_EXT = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".py", ".go", ".rs", ".rb", ".java", ".kt",
            ".cs", ".php", ".swift", ".dart", ".html", ".css", ".scss", ".sql", ".graphql"}
TEST_PATTERNS = (re.compile(r"\.(test|spec)\.[a-z]+$"), re.compile(r"(^|/)test_[^/]+\.py$"), re.compile(r"_test\.(py|go)$"),
                 re.compile(r"(^|/)(tests?|__tests__|e2e|spec)/"))
ID_PATTERN = re.compile(r"\b(?:FR|US|AC|SCR|CMP|UXD|VD)-\d{3}\b")
MAX_FILE_BYTES = 1_000_000
DEFAULT_EXCLUDE = {"node_modules", "dist", "build", ".venv", "venv", "__pycache__", ".git", "coverage", ".next", "target",
                   ".pytest_cache", ".mypy_cache", ".ruff_cache", ".turbo", ".cache", "vendor"}
NON_SOURCE_TOP = ("docs", ".ai-workflow", "design-preview", ".claude", ".github")

STACK_MARKERS = {
    "package.json": "node", "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "package-lock.json": "npm",
    "pyproject.toml": "python", "requirements.txt": "python", "go.mod": "go", "Cargo.toml": "rust",
    "Gemfile": "ruby", "pom.xml": "java-maven", "build.gradle": "jvm-gradle", "build.gradle.kts": "jvm-gradle",
    "composer.json": "php", "docker-compose.yml": "docker-compose", "compose.yaml": "docker-compose", "Dockerfile": "docker",
    "alembic.ini": "alembic", "Makefile": "make",
}
JS_LIBS = ("react", "vue", "svelte", "next", "nuxt", "@angular/core", "solid-js", "vite", "vitest", "jest", "@playwright/test",
           "playwright", "cypress", "react-router", "@tanstack/react-query", "tailwindcss", "msw", "storybook", "eslint", "typescript")
PY_LIBS = ("fastapi", "django", "flask", "sqlalchemy", "alembic", "pytest", "pydantic", "mypy", "ruff", "celery")


def is_test_path(rel: str) -> bool:
    return any(p.search(rel) for p in TEST_PATTERNS)


def iter_source(project: Path, roots: list[str] | None, exclude: list[str] | None) -> list[str]:
    """프로필의 source·tests 경로(없으면 저장소 전체에서 문서·상태·프리뷰 제외)의 텍스트 소스 파일."""
    ex = DEFAULT_EXCLUDE | set(exclude or [])
    starts = [project / r for r in roots] if roots else [project]
    out: list[str] = []
    seen = set()
    for start in starts:
        if not start.exists():
            continue
        stack = [start]
        while stack:
            d = stack.pop()
            try:
                entries = sorted(d.iterdir())
            except OSError:
                continue
            for e in entries:
                rel = str(e.relative_to(project))
                if e.name in ex or e.is_symlink():
                    continue
                if not roots and rel.split("/")[0] in NON_SOURCE_TOP:
                    continue
                if e.is_dir():
                    stack.append(e)
                elif e.suffix in TEXT_EXT and rel not in seen:
                    try:
                        if e.stat().st_size <= MAX_FILE_BYTES:
                            out.append(rel)
                            seen.add(rel)
                    except OSError:
                        pass
    return sorted(out)


def _read(project: Path, rel: str) -> str:
    try:
        return (project / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def detect_stack(project: Path) -> dict:
    found = []
    dirs = [project] + [d for d in sorted(project.iterdir()) if d.is_dir() and d.name not in DEFAULT_EXCLUDE
                        and not d.name.startswith(".") and d.name not in ("docs", "design-preview")]
    libs: dict[str, list[str]] = {}
    for d in dirs:
        rel_d = "." if d == project else d.name
        for marker, kind in STACK_MARKERS.items():
            if (d / marker).exists():
                found.append({"dir": rel_d, "marker": marker, "kind": kind})
        pj = d / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                libs[rel_d] = sorted(k for k in deps if k in JS_LIBS)
            except (json.JSONDecodeError, OSError):
                libs[rel_d] = ["(package.json 해석 실패)"]
        pp = d / "pyproject.toml"
        if pp.exists():
            try:
                txt = pp.read_text(encoding="utf-8")
                tomllib.loads(txt)
                libs.setdefault(rel_d, [])
                libs[rel_d] += sorted(n for n in PY_LIBS if re.search(rf"[\"']{re.escape(n)}\b", txt))
            except (tomllib.TOMLDecodeError, OSError):
                libs.setdefault(rel_d, []).append("(pyproject.toml 해석 실패)")
    migrations = [str(p.relative_to(project)) for p in project.glob("*/**/migrations") if "node_modules" not in p.parts][:5]
    migrations += [str(p.relative_to(project)) for p in project.glob("*/alembic") if p.is_dir()]
    ci = [str(p.relative_to(project)) for p in sorted((project / ".github/workflows").glob("*.y*ml"))] if (project / ".github/workflows").exists() else []
    return {"markers": found, "libraries": libs, "migrations": sorted(set(migrations)), "ci": ci}


def makefile_targets(project: Path) -> dict[str, str]:
    mf = project / "Makefile"
    if not mf.exists():
        return {}
    out = {}
    for m in re.finditer(r"^([A-Za-z][\w-]*):(?!=)[^\n#]*?(?:##\s*(.*))?$", _read(project, "Makefile"), re.M):
        out[m.group(1)] = (m.group(2) or "").strip()
    return out


STAGE_GUESS = (("typecheck", "typecheck"), ("type", "typecheck"), ("lint", "lint"), ("format", "lint"), ("build", "build"),
               ("e2e", "e2e"), ("test-db", "db"), ("migrate", "db"), ("test", "test"), ("check", "other"))


def _guess_stage(name: str) -> str:
    for key, st in STAGE_GUESS:
        if key in name:
            return st
    return "other"


def detect_commands(project: Path) -> list[dict]:
    """검증 명령 후보. 우선순위: ① product-init 기록(boilerplate manifest의 verify) ② Makefile ③ 패키지 스크립트."""
    cands: list[dict] = []
    bp = project / BOILERPLATE_REL
    if bp.exists():
        try:
            data = json.loads(bp.read_text(encoding="utf-8"))
            for stage, rec in (data.get("verification") or {}).items():
                if not isinstance(rec, dict):
                    continue
                for step in rec.get("steps", []):
                    if not isinstance(step, dict):
                        continue
                    run = step.get("run", "")
                    if run and not run.startswith(("pnpm install", "npm install", "uv sync", "yarn install")):
                        cands.append({"source": f"{BOILERPLATE_REL} verification.{stage}", "name": f"{stage}:{run.split()[-1]}",
                                      "run": run, "cwd": step.get("cwd", "."), "stage": _guess_stage(run),
                                      "requires": ["docker"] if "{compose}" in run or "docker" in run else []})
        except (json.JSONDecodeError, OSError):
            pass
    targets = makefile_targets(project)
    for t, desc in targets.items():
        parent = t.rsplit("-", 1)[0] if "-" in t else None
        if parent in targets and _guess_stage(parent) == _guess_stage(t):
            continue  # 묶음 대상(test)이 있으면 같은 단계의 하위 대상(test-fe·test-be)은 후보에서 뺌
        if any(k in t for k in ("lint", "typecheck", "test", "build", "check", "e2e")):
            cands.append({"source": "Makefile", "name": f"make-{t}", "run": f"make {t}", "cwd": ".", "stage": _guess_stage(t),
                          "requires": ["docker"] if "docker" in desc.lower() or t in ("test-db",) else [], "note": desc})
    for pj in [project / "package.json"] + sorted(project.glob("*/package.json")):
        if "node_modules" in pj.parts or not pj.exists():
            continue
        try:
            scripts = json.loads(pj.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            continue
        cwd = str(pj.parent.relative_to(project)) or "."
        for name, cmd in scripts.items():
            if any(k in name for k in ("lint", "typecheck", "test", "build", "e2e")):
                cands.append({"source": f"{cwd}/package.json", "name": f"{cwd}:{name}", "run": f"<패키지 매니저> run {name}",
                              "cwd": cwd, "stage": _guess_stage(name), "requires": [], "note": cmd})
    return cands


def id_mentions(project: Path, files: list[str]) -> dict:
    """{ID: {"code": [file:line], "test": [file:line]}}. 언급일 뿐 구현·검증 근거가 아닙니다."""
    out: dict[str, dict] = {}
    for rel in files:
        kind = "test" if is_test_path(rel) else "code"
        for n, line in enumerate(_read(project, rel).splitlines(), 1):
            for m in ID_PATTERN.finditer(line):
                out.setdefault(m.group(0), {"code": [], "test": []})[kind].append(f"{rel}:{n}")
            for m in re.finditer(r"\b(AC|SCR|US|FR)-(\d{3})\s*[–~-]\s*(?:\1-)?(\d{3})\b", line):  # 범위 표기 AC-024–033
                lo, hi = int(m.group(2)), int(m.group(3))
                if 0 < hi - lo <= 30:
                    for x in range(lo, hi + 1):
                        rec = out.setdefault(f"{m.group(1)}-{x:03d}", {"code": [], "test": []})
                        loc = f"{rel}:{n}"
                        if loc not in rec[kind]:
                            rec[kind].append(loc + " (범위)")
    return out


def route_regex(route: str) -> re.Pattern | None:
    """'/club-matches/:matchId' → 정적 구간은 그대로, 매개변수 구간은 아무 식별자. 정적 구간이 없으면 None."""
    segs = [s for s in route.strip("/").split("/") if s]
    if not segs or any("*" in s for s in segs) or all(s.startswith((":", "[", "{", "$")) for s in segs):
        return None
    parts = []
    for s in segs:
        # 매개변수 구간: :id, [id], {id}, ${expr}(템플릿 문자열) 모두 허용
        parts.append(r"(?:\$\{[^}`]+\}|[:\[{]?[\w.-]+[\]}]?)" if s.startswith((":", "[", "{", "$")) else re.escape(s))
    return re.compile(r"[\"'`]/?" + "/".join(parts) + r"(?:/)?[\"'`?#]")


def route_hits(project: Path, files: list[str], screens: dict) -> dict:
    """화면 경로 문자열이 코드에 있는지(라우트 정의·링크 후보). 테스트 파일은 따로 셉니다."""
    texts = {rel: _read(project, rel) for rel in files}
    out = {}
    for sid, s in screens.items():
        hits = {"code": [], "test": []}
        for r in s.get("routes", []):
            rx = route_regex(r)
            if rx is None:
                continue
            for rel, t in texts.items():
                if rx.search(t):
                    hits["test" if is_test_path(rel) else "code"].append(rel)
        out[sid] = {"routes": s.get("routes", []), "overlay": s.get("overlay", False),
                    "code": sorted(set(hits["code"])), "test": sorted(set(hits["test"]))}
    return out


def component_inventory(project: Path, comp_roots: list[str], src_files: list[str], cmps: dict) -> dict:
    """프로필 components 경로의 파일 → 대응 CMP(파일 안 'CMP-xxx' 표지 또는 이름 일치)와 사용처 수."""
    files = [f for f in src_files if any(f.startswith(r.rstrip("/") + "/") for r in comp_roots) and not is_test_path(f)]
    name_to_cmp = {re.sub(r"[^a-z0-9]", "", v.lower()): k for k, v in cmps.items()}
    texts = {f: _read(project, f) for f in src_files if not is_test_path(f)}
    items = []
    for rel in files:
        txt = texts.get(rel, "")
        stem = Path(rel).stem
        markers = sorted(set(re.findall(r"CMP-\d{3}", txt[:2000])))
        by_name = name_to_cmp.get(re.sub(r"[^a-z0-9]", "", stem.lower()))
        rx = re.compile(rf"""from\s+['"][^'"]*/{re.escape(stem)}['"]|import\s+['"][^'"]*/{re.escape(stem)}['"]""")
        used_by = [f for f, t in texts.items() if f != rel and rx.search(t)]
        items.append({"file": rel, "name": stem, "cmp_markers": markers, "cmp_by_name": by_name, "used_by_count": len(used_by)})
    mapped = {}
    for it in items:
        for c in it["cmp_markers"] or ([it["cmp_by_name"]] if it["cmp_by_name"] else []):
            mapped.setdefault(c, []).append(it["file"])
    return {"roots": comp_roots, "files": items, "cmp_candidates": {c: mapped.get(c, []) for c in sorted(cmps)},
            "unmapped_cmp": sorted(c for c in cmps if c not in mapped)}


def guess_paths(project: Path) -> dict:
    """프로필 기본값 제안: src·tests·components 폴더 후보."""
    src, tests, comps = [], [], []
    for d in sorted(project.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in DEFAULT_EXCLUDE or d.name in ("docs", "design-preview"):
            continue
        for cand in ("src", "app", "lib"):
            if (d / cand).is_dir():
                src.append(f"{d.name}/{cand}")
        if (d / "tests").is_dir():
            tests.append(f"{d.name}/tests")
        for c in d.glob("src/components"):
            comps.append(str(c.relative_to(project)))
    if (project / "src").is_dir():
        src.append("src")
        if (project / "src/components").is_dir():
            comps.append("src/components")
    if (project / "tests").is_dir():
        tests.append("tests")
    return {"source": src, "tests": tests or src, "components": comps}
