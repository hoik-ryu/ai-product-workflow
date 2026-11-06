#!/usr/bin/env python3
"""/product-init 결정적 보조 스크립트 (Python 3.11+, 표준 라이브러리만 사용).

하위 명령:
  check     사전 점검(엔진 저장소 여부, Git, 미커밋 변경, planning 승인·해시) + 상태 교차 검증
  resolve   태그 → 커밋 SHA 확인 (git ls-remote)
  snapshot  태그를 프로젝트 밖 임시 디렉터리로 얕은 클론하고 SHA 대조
  plan      파일 분류(add / identical / conflict / excluded / protected) → 상태 파일 기록
  approve   사용자가 명시적으로 승인한 plan id 기록
  branch    승인 후 전용 브랜치 생성 (git switch -c)
  apply     승인된 plan의 add 파일만 복사 (재개 가능, 파일마다 SHA-256 기록)
  merge     사용자가 승인한 충돌 파일 하나를 manifest 전략으로 병합
  verify    manifest의 fe / be / db / smoke 검증 실행 및 결과 기록
  cleanup   검증용 Compose 프로젝트 정리 (볼륨 삭제는 검증 전용 볼륨 + 명시 확인 시에만)
  status    상태 파일과 실제 파일 시스템 교차 검증 (+ 원격 태그 SHA 재확인)

모든 출력은 JSON이며, 차단·실패 시 종료 코드 2를 반환합니다.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

STATE_REL = ".ai-workflow/boilerplate.json"
WORKFLOW_STATE_REL = ".ai-workflow/state.yaml"
MANIFEST_NAME = "boilerplate.manifest.toml"
PROTECTED_PREFIXES = (".git/", ".ai-workflow/", "docs/planning/", ".claude/", "skills/product-start/")
CLEAN_CHECK_IGNORED_PREFIXES = (".claude/",)  # 도구 설정(심볼릭 링크 등)은 미커밋 변경 판정에서 제외
VERIFY_SUFFIX = "-init-verify"
STAGES = ("fe", "be", "db", "smoke")
MERGE_STRATEGIES = ("append-missing-lines", "append-section")
FORBIDDEN_STEP_PATTERNS = (
    r"\bdown\b[^\n]*(\s-v\b|--volumes)",
    r"\bvolume\s+(rm|prune)\b",
    r"\bsystem\s+prune\b",
    r"\brm\s+-[a-zA-Z]*r",
    r"\bgit\s+(push|commit|reset|checkout|clean)\b",
)
PLANNING_FILES = (
    "docs/planning/02-prd.md",
    "docs/planning/03-user-stories.md",
    "docs/planning/04-user-flows.md",
    "docs/planning/05-acceptance-criteria.md",
)


# ---------------------------------------------------------------- 공통 유틸
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def block(error: str, message: str, **extra) -> None:
    emit({"ok": False, "error": error, "message": message, **extra}, 2)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(cwd), *args], check=check)


def is_relative_safe(p: str) -> bool:
    return bool(p) and not p.startswith("/") and ".." not in Path(p).parts


def is_secret_env(path: str) -> bool:
    name = Path(path).name
    return (name == ".env" or name.startswith(".env.")) and not name.endswith(".example")


def is_protected(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PROTECTED_PREFIXES)


def matches_any(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or path == pat.rstrip("/") or (pat.endswith("/**") and path.startswith(pat[:-2])):
            return True
    return False


# ---------------------------------------------------------------- 상태 파일
def state_path(project: Path) -> Path:
    return project / STATE_REL


def load_state(project: Path) -> dict | None:
    p = state_path(project)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("state_unreadable", f"{STATE_REL}을 읽을 수 없습니다: {e}")
    return None


def save_state(project: Path, st: dict) -> None:
    st["updated_at"] = now()
    p = state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".boilerplate.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def add_history(st: dict, event: str, note: str = "") -> None:
    st.setdefault("history", []).append({"at": now(), "event": event, "note": note})


# ---------------------------------------------------------------- /product-start 상태 (읽기 전용)
def _stage_block(text: str, stage: str) -> str:
    m = re.search(rf"^  {stage}:[ \t]*\n(.*?)(?=^  [A-Za-z_]+:[ \t]*\n|^\S|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def _field(block_text: str, key: str) -> str | None:
    m = re.search(rf"^    {key}:[ \t]*\"?([A-Za-z0-9_]+)", block_text, re.M)
    return m.group(1) if m else None


def read_gate(project: Path) -> dict:
    """planning 승인과 승인 해시를 읽기 전용으로 확인합니다. /product-start 상태는 절대 쓰지 않습니다."""
    p = project / WORKFLOW_STATE_REL
    if not p.exists():
        return {"ok": False, "error": "no_workflow_state", "message": "`.ai-workflow/state.yaml`이 없습니다. 먼저 /product-start로 기획을 승인받아야 합니다."}
    text = p.read_text(encoding="utf-8")
    problems: list[str] = []
    info: dict = {}
    for stage in ("discovery", "planning"):
        b = _stage_block(text, stage)
        status = _field(b, "status")
        info[f"{stage}_status"] = status
        if status != "approved":
            problems.append(f"{stage} 상태가 approved가 아닙니다 (현재: {status})")
        appr = re.search(r"^    approved:[ \t]*\n[ \t]+revision:[ \t]*\"?(\w+)", b, re.M)
        info[f"{stage}_approved_revision"] = appr.group(1) if appr else None
        hashes = dict(re.findall(r"(docs/planning/[\w./-]+?)\"?[ \t]*:[ \t]*\"?([0-9a-f]{64})", b))
        expected = ("docs/planning/01-discovery.md",) if stage == "discovery" else PLANNING_FILES
        for f in expected:
            fp = project / f
            if f not in hashes:
                problems.append(f"{f}의 승인 해시가 기록되어 있지 않습니다")
            elif not fp.exists():
                problems.append(f"{f} 파일이 없습니다")
            elif sha256_file(fp) != hashes[f]:
                problems.append(f"{f}가 승인 이후 변경되었습니다 (해시 불일치)")
        info[f"{stage}_hashes"] = {f: hashes.get(f) for f in expected}
    based_on = _field(_stage_block(text, "planning"), "based_on_discovery_revision")
    if based_on and info.get("discovery_approved_revision") and based_on != info["discovery_approved_revision"]:
        problems.append("planning이 최신 승인 discovery revision을 기준으로 하지 않습니다 (outdated)")
    if problems:
        return {"ok": False, "error": "planning_not_approved", "message": "; ".join(problems), **info}
    return {"ok": True, **info}


# ---------------------------------------------------------------- 사전 점검
def git_dirty_paths(project: Path) -> list[str]:
    out = git(project, "status", "--porcelain", "--untracked-files=all")
    paths = []
    for line in out.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if not path.startswith(CLEAN_CHECK_IGNORED_PREFIXES):
            paths.append(path)
    return paths


def preflight(project: Path) -> dict:
    if (project / "skills/product-start/SKILL.md").exists():
        return {"ok": False, "error": "engine_repo", "message": "워크플로 엔진 저장소 안입니다. 제품 저장소에서 실행하세요."}
    try:
        top = git(project, "rev-parse", "--show-toplevel").strip()
    except RuntimeError:
        return {"ok": False, "error": "not_git_repo", "message": "Git 저장소가 아닙니다."}
    if Path(top).resolve() != project.resolve():
        return {"ok": False, "error": "not_repo_root", "message": f"Git 저장소 루트({top})에서 실행하세요."}
    if git(project, "rev-parse", "--verify", "HEAD", check=False) == "":
        return {"ok": False, "error": "no_commits", "message": "커밋이 하나 이상 있어야 합니다."}
    branch = git(project, "branch", "--show-current").strip()
    return {"ok": True, "branch": branch, "dirty": git_dirty_paths(project)}


def allowed_dirty(st: dict | None) -> set[str]:
    allowed = {STATE_REL}
    if st:
        allowed |= {f["path"] for f in st.get("files_done", [])}
        allowed |= {f["path"] for f in st.get("plan", {}).get("add", [])}
        allowed |= {m["path"] for m in st.get("merges", [])}
        allowed |= {m["backup"] for m in st.get("merges", []) if m.get("backup")}
    return allowed


def cross_verify(project: Path, st: dict) -> dict:
    """files_done / merges에 기록된 SHA-256과 실제 파일을 대조합니다. 아무것도 고치지 않습니다."""
    modified, missing = [], []
    for f in st.get("files_done", []):
        fp = project / f["path"]
        if not fp.exists():
            missing.append(f["path"])
        elif sha256_file(fp) != f["sha256"]:
            modified.append(f["path"])
    for m in st.get("merges", []):
        fp = project / m["path"]
        if not fp.exists():
            missing.append(m["path"])
        elif sha256_file(fp) != m["after_sha256"]:
            modified.append(m["path"])
    unexpected = [p for p in git_dirty_paths(project) if p not in allowed_dirty(st)]
    return {"user_modified": modified, "missing": missing, "unexpected_changes": unexpected,
            "consistent": not (modified or missing or unexpected)}


# ---------------------------------------------------------------- manifest
def validate_manifest(m: dict) -> list[str]:
    errs: list[str] = []
    if m.get("schema_version") != 1:
        errs.append("schema_version은 1이어야 합니다")
    for key in ("name", "version"):
        if not isinstance(m.get(key), str) or not m.get(key):
            errs.append(f"{key}는 비어 있지 않은 문자열이어야 합니다")
    if isinstance(m.get("version"), str) and not re.fullmatch(r"\d+\.\d+\.\d+([-.+][0-9A-Za-z.-]+)?", m["version"]):
        errs.append("version은 SemVer 형식이어야 합니다 (예: 1.0.0)")
    apply = m.get("apply", {})
    for pat in apply.get("exclude", []):
        if not isinstance(pat, str) or not is_relative_safe(pat.replace("*", "x")):
            errs.append(f"apply.exclude 항목이 잘못되었습니다: {pat!r}")
    for i, s in enumerate(m.get("substitutions", [])):
        if not isinstance(s.get("from"), str) or not s.get("from"):
            errs.append(f"substitutions[{i}].from이 비어 있습니다")
        if not isinstance(s.get("to"), str) or s.get("to") not in ("{project_slug}", "{project_title}"):
            errs.append(f"substitutions[{i}].to는 {{project_slug}} 또는 {{project_title}}이어야 합니다")
        files = s.get("files", [])
        if not files or not all(isinstance(f, str) and is_relative_safe(f) for f in files):
            errs.append(f"substitutions[{i}].files는 상대 경로 목록이어야 합니다")
    for i, r in enumerate(m.get("merge", [])):
        if not isinstance(r.get("path"), str) or not is_relative_safe(r.get("path", "")):
            errs.append(f"merge[{i}].path가 잘못되었습니다")
        if r.get("strategy") not in MERGE_STRATEGIES:
            errs.append(f"merge[{i}].strategy는 {MERGE_STRATEGIES} 중 하나여야 합니다")
        if r.get("strategy") == "append-section" and not r.get("section_title"):
            errs.append(f"merge[{i}]: append-section에는 section_title이 필요합니다")
        if not isinstance(r.get("required", []), list):
            errs.append(f"merge[{i}].required는 목록이어야 합니다")
    v = m.get("verify", {})
    if not isinstance(v.get("env_file", ".env.example"), str):
        errs.append("verify.env_file은 문자열이어야 합니다")
    ports = v.get("ports", {})
    if not all(isinstance(k, str) and isinstance(p, int) and 1024 <= p <= 65535 for k, p in ports.items()):
        errs.append("verify.ports는 {이름 = 1024–65535 정수}여야 합니다")
    if not all(isinstance(k, str) and isinstance(val, (str, int)) for k, val in v.get("env", {}).items()):
        errs.append("verify.env는 {이름 = 문자열}이어야 합니다")
    stages = v.get("stages", {})
    for stage, steps in stages.items():
        if stage not in STAGES:
            errs.append(f"verify.stages에 알 수 없는 단계: {stage}")
            continue
        for j, step in enumerate(steps):
            cmd = step.get("run")
            if not isinstance(cmd, str) or not cmd.strip():
                errs.append(f"verify.stages.{stage}[{j}].run이 비어 있습니다")
                continue
            if step.get("cwd") and not is_relative_safe(step["cwd"]):
                errs.append(f"verify.stages.{stage}[{j}].cwd가 잘못되었습니다")
            uses_docker = re.search(r"\bdocker\b", cmd) is not None
            if uses_docker and not cmd.startswith("{compose} "):
                errs.append(f"verify.stages.{stage}[{j}]: Docker 명령은 '{{compose}} '로 시작해야 합니다 (프로젝트명 격리)")
            if "{compose}" in cmd and stage in ("fe", "be"):
                errs.append(f"verify.stages.{stage}[{j}]: fe/be 단계는 호스트 명령만 허용됩니다")
            for pat in FORBIDDEN_STEP_PATTERNS:
                if re.search(pat, cmd):
                    errs.append(f"verify.stages.{stage}[{j}]: 금지된 명령 패턴입니다 ({cmd!r})")
    for k, h in enumerate(v.get("http", [])):
        if not isinstance(h.get("url"), str) or not h["url"].startswith("http://localhost:"):
            errs.append(f"verify.http[{k}].url은 http://localhost: 로 시작해야 합니다")
        if not isinstance(h.get("expect_status", 200), int):
            errs.append(f"verify.http[{k}].expect_status는 정수여야 합니다")
    return errs


def load_manifest(snapshot: Path) -> dict:
    p = snapshot / MANIFEST_NAME
    if not p.exists():
        block("manifest_missing", f"보일러플레이트에 {MANIFEST_NAME}가 없습니다.")
    try:
        m = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        block("manifest_invalid", f"manifest를 파싱할 수 없습니다: {e}")
    errs = validate_manifest(m)
    if errs:
        block("manifest_invalid", "manifest 검증 실패", errors=errs)
    return m


def substituted(path: str, data: bytes, manifest: dict, slug: str, title: str) -> bytes:
    values = {"{project_slug}": slug, "{project_title}": title}
    for s in manifest.get("substitutions", []):
        if path in s["files"]:
            data = data.replace(s["from"].encode(), values[s["to"]].encode())
    return data


def compose_project(st: dict) -> str:
    base = re.sub(r"[^a-z0-9_-]", "-", st["project_slug"].lower()).strip("-") or "product"
    return base + VERIFY_SUFFIX


# ---------------------------------------------------------------- 하위 명령
def cmd_check(a) -> None:
    project = Path(a.project).resolve()
    pf = preflight(project)
    if not pf["ok"]:
        emit(pf, 2)
    gate = read_gate(project)
    st = load_state(project)
    result = {"ok": gate["ok"], "preflight": pf, "gate": gate, "state_status": st.get("status") if st else None}
    if st:
        result["cross_verify"] = cross_verify(project, st)
        result["ok"] = result["ok"] and result["cross_verify"]["consistent"]
    elif pf["dirty"]:
        result["ok"] = False
        result["error"] = "dirty_worktree"
        result["message"] = "커밋되지 않은 변경이 있습니다. 먼저 커밋하거나 정리하세요."
    emit(result, 0 if result["ok"] else 2)


def ls_remote_tag(source: str, ref: str) -> str | None:
    out = run(["git", "ls-remote", "--tags", source, f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}"])
    shas = dict(reversed(line.split("\t")) for line in out.splitlines() if "\t" in line)
    return shas.get(f"refs/tags/{ref}^{{}}") or shas.get(f"refs/tags/{ref}")


def cmd_resolve(a) -> None:
    sha = ls_remote_tag(a.source, a.ref)
    if not sha:
        block("tag_not_found", f"태그 {a.ref}를 찾을 수 없습니다. 브랜치명은 허용되지 않고 태그만 허용됩니다.")
    emit({"ok": True, "source": a.source, "ref": a.ref, "commit": sha})


def cmd_snapshot(a) -> None:
    dest = Path(a.dest).resolve()
    if a.project and str(dest).startswith(str(Path(a.project).resolve()) + os.sep):
        block("snapshot_inside_project", "스냅샷은 제품 프로젝트 밖에 받아야 합니다.")
    if dest.exists() and any(dest.iterdir()):
        head = git(dest, "rev-parse", "HEAD", check=False).strip()
        if head != a.sha:
            block("sha_mismatch", f"기존 스냅샷 커밋({head})이 기대값({a.sha})과 다릅니다.", expected=a.sha, actual=head)
        emit({"ok": True, "snapshot": str(dest), "commit": head, "reused": True})
    src = a.source
    if Path(src).exists() and not src.startswith("file://"):
        src = "file://" + str(Path(src).resolve())
    run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", a.ref, "--single-branch", src, str(dest)])
    head = git(dest, "rev-parse", "HEAD").strip()
    if head != a.sha:
        block("sha_mismatch", f"태그 {a.ref}가 기록된 커밋과 다른 커밋을 가리킵니다 (태그가 옮겨졌을 수 있음).", expected=a.sha, actual=head)
    emit({"ok": True, "snapshot": str(dest), "commit": head, "reused": False})


def cmd_plan(a) -> None:
    project, snapshot = Path(a.project).resolve(), Path(a.snapshot).resolve()
    pf = preflight(project)
    if not pf["ok"]:
        emit(pf, 2)
    st = load_state(project)
    if st and st.get("status") not in ("planned",):
        block("already_started", f"이미 적용이 시작된 상태입니다 (status={st.get('status')}). 재개는 apply/status를 사용하세요.")
    if pf["dirty"] and [p for p in pf["dirty"] if p != STATE_REL]:
        block("dirty_worktree", "커밋되지 않은 변경이 있습니다. 먼저 커밋하거나 정리하세요.", dirty=pf["dirty"])
    gate = read_gate(project)
    if not gate["ok"]:
        emit(gate, 2)
    head = git(snapshot, "rev-parse", "HEAD").strip()
    if head != a.sha:
        block("sha_mismatch", "스냅샷 커밋이 확인한 태그 SHA와 다릅니다.", expected=a.sha, actual=head)
    manifest = load_manifest(snapshot)
    if a.ref.lstrip("v") != manifest["version"]:
        block("version_mismatch", f"태그({a.ref})와 manifest version({manifest['version']})이 다릅니다.")
    slug = a.slug or project.name.lower()
    title = a.title or slug
    modes = {}
    for line in git(snapshot, "ls-files", "-s").splitlines():
        meta, path = line.split("\t", 1)
        modes[path] = meta.split()[0]
    excludes = manifest.get("apply", {}).get("exclude", [])
    merge_rules = {r["path"]: r for r in manifest.get("merge", [])}
    add, identical, conflicts, excluded, protected = [], [], [], [], []
    for path in sorted(modes):
        if path == MANIFEST_NAME:
            excluded.append({"path": path, "reason": "manifest"})
            continue
        if modes[path] == "120000":
            excluded.append({"path": path, "reason": "symlink_unsupported"})
            continue
        if is_secret_env(path):
            excluded.append({"path": path, "reason": "secret_env"})
            continue
        if matches_any(path, excludes):
            excluded.append({"path": path, "reason": "manifest_exclude"})
            continue
        if is_protected(path):
            protected.append(path)
            continue
        data = substituted(path, (snapshot / path).read_bytes(), manifest, slug, title)
        digest = sha256_bytes(data)
        target = project / path
        parent_conflict = next((str(p.relative_to(project)) for p in target.parents
                                if p != project and project in p.parents and p.exists() and not p.is_dir()), None)
        if parent_conflict or target.is_dir() or target.is_symlink():
            conflicts.append({"path": path, "reason": "type_conflict", "strategy": None, "boilerplate_sha256": digest})
        elif not target.exists():
            add.append({"path": path, "sha256": digest, "mode": modes[path]})
        elif sha256_file(target) == digest:
            identical.append(path)
        else:
            rule = merge_rules.get(path)
            entry = {"path": path, "reason": "content_differs", "strategy": rule["strategy"] if rule else None,
                     "project_sha256": sha256_file(target), "boilerplate_sha256": digest}
            if rule:
                have = {l.strip() for l in target.read_text(encoding="utf-8", errors="replace").splitlines()}
                entry["missing_required"] = [r for r in rule.get("required", []) if r.strip() not in have]
            conflicts.append(entry)
    plan_core = {"commit": a.sha, "slug": slug, "title": title, "add": add, "conflicts": [c["path"] for c in conflicts]}
    plan_id = sha256_bytes(json.dumps(plan_core, sort_keys=True).encode())[:16]
    st = {
        "schema_version": 1,
        "status": "planned",
        "source": {"repo": a.source, "ref": a.ref, "commit": a.sha, "manifest_name": manifest["name"], "manifest_version": manifest["version"]},
        "project_slug": slug,
        "project_title": title,
        "based_on": {k: gate[k] for k in ("planning_approved_revision", "discovery_approved_revision", "planning_hashes")},
        "snapshot_dir": str(snapshot),
        "manifest": manifest,
        "plan": {"id": plan_id, "created_at": now(), "add": add, "identical": identical, "conflicts": conflicts,
                 "excluded": excluded, "protected": protected},
        "approval": {"approved": False, "plan_id": None, "at": None},
        "branch": None,
        "files_done": [],
        "runtime_conflicts": [],
        "merges": [],
        "verification": {},
        "history": (st or {}).get("history", []),
        "created_at": (st or {}).get("created_at", now()),
    }
    add_history(st, "planned", f"plan {plan_id}: add {len(add)}, identical {len(identical)}, conflicts {len(conflicts)}")
    save_state(project, st)
    emit({"ok": True, "plan_id": plan_id, "counts": {"add": len(add), "identical": len(identical), "conflicts": len(conflicts),
          "excluded": len(excluded), "protected": len(protected)}, "conflicts": conflicts, "excluded": excluded,
          "protected": protected, "state": STATE_REL})


def require_state(project: Path) -> dict:
    st = load_state(project)
    if not st:
        block("no_state", f"{STATE_REL}이 없습니다. 먼저 plan을 실행하세요.")
    return st


def cmd_approve(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    if st["status"] != "planned":
        block("not_planned", f"승인은 planned 상태에서만 가능합니다 (현재 {st['status']}).")
    if a.plan_id != st["plan"]["id"]:
        block("plan_id_mismatch", "승인한 plan id가 현재 계획과 다릅니다. 계획을 다시 제시하세요.", current=st["plan"]["id"])
    st["approval"] = {"approved": True, "plan_id": a.plan_id, "at": now()}
    add_history(st, "approved", f"plan {a.plan_id}")
    save_state(project, st)
    emit({"ok": True, "approved_plan": a.plan_id})


def cmd_branch(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    if not st["approval"]["approved"]:
        block("not_approved", "적용 계획이 승인되지 않아 브랜치를 만들 수 없습니다.")
    if st["files_done"]:
        block("already_applying", "이미 적용이 시작되어 브랜치를 바꿀 수 없습니다.")
    if git(project, "rev-parse", "--verify", f"refs/heads/{a.name}", check=False).strip():
        block("branch_exists", f"브랜치 {a.name}가 이미 있습니다.")
    git(project, "switch", "-c", a.name)
    st["branch"] = a.name
    add_history(st, "branch_created", a.name)
    save_state(project, st)
    emit({"ok": True, "branch": a.name})


def cmd_apply(a) -> None:
    project, snapshot = Path(a.project).resolve(), Path(a.snapshot).resolve()
    st = require_state(project)
    if not (st["approval"]["approved"] and st["approval"]["plan_id"] == st["plan"]["id"]):
        block("not_approved", "사용자가 승인한 적용 계획이 없습니다. 계획을 제시하고 명시적 승인을 받으세요.")
    if st["status"] not in ("planned", "applying"):
        block("not_applicable", f"apply는 planned/applying 상태에서만 실행합니다 (현재 {st['status']}).")
    pf = preflight(project)
    if not pf["ok"]:
        emit(pf, 2)
    gate = read_gate(project)
    if not gate["ok"]:
        emit(gate, 2)
    head = git(snapshot, "rev-parse", "HEAD").strip()
    if head != st["source"]["commit"]:
        block("sha_mismatch", "스냅샷 커밋이 계획한 커밋과 다릅니다.", expected=st["source"]["commit"], actual=head)
    cv = cross_verify(project, st)
    if not cv["consistent"]:
        block("state_mismatch", "기록된 적용 파일과 실제 파일이 일치하지 않거나 예상하지 못한 변경이 있습니다. 덮어쓰거나 복구하지 않았습니다.", **cv)
    manifest = st["manifest"]
    done = {f["path"] for f in st["files_done"]}
    runtime = {c["path"] for c in st["runtime_conflicts"]}
    if st["status"] == "planned":
        st["status"] = "applying"
        add_history(st, "applying")
        save_state(project, st)
    written = 0
    for item in st["plan"]["add"]:
        path = item["path"]
        if path in done or path in runtime:
            continue
        target = project / path
        data = substituted(path, (snapshot / path).read_bytes(), manifest, st["project_slug"], st["project_title"])
        if sha256_bytes(data) != item["sha256"]:
            block("snapshot_changed", f"스냅샷 파일 내용이 계획과 다릅니다: {path}")
        if target.exists() or target.is_symlink():
            if target.is_file() and sha256_file(target) == item["sha256"]:
                st["files_done"].append({"path": path, "sha256": item["sha256"], "note": "adopted_identical"})
            else:
                st["runtime_conflicts"].append({"path": path, "reason": "appeared_after_plan", "at": now()})
            save_state(project, st)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".pi.", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o755 if item.get("mode") == "100755" else 0o644)
        os.replace(tmp, target)
        st["files_done"].append({"path": path, "sha256": sha256_file(target)})
        save_state(project, st)
        written += 1
        if a.stop_after and written >= a.stop_after:
            emit({"ok": False, "error": "interrupted", "message": f"테스트용 중단: {written}개 파일 기록 후 중단", "files_done": len(st["files_done"])}, 3)
    leftovers = []
    for s in manifest.get("substitutions", []):
        for f in s["files"]:
            fp = project / f
            if f in {d["path"] for d in st["files_done"]} and fp.exists() and s["from"].encode() in fp.read_bytes():
                leftovers.append({"path": f, "token": s["from"]})
    st["status"] = "applied"
    add_history(st, "applied", f"files {len(st['files_done'])}, runtime conflicts {len(st['runtime_conflicts'])}")
    save_state(project, st)
    emit({"ok": True, "status": "applied", "files_done": len(st["files_done"]), "runtime_conflicts": st["runtime_conflicts"],
          "planned_conflicts": [c["path"] for c in st["plan"]["conflicts"]], "substitution_leftovers": leftovers})


def cmd_merge(a) -> None:
    project, snapshot = Path(a.project).resolve(), Path(a.snapshot).resolve()
    st = require_state(project)
    if st["status"] not in ("applied", "verified", "verify_failed"):
        block("not_applied", "병합은 적용(apply)이 끝난 뒤에만 할 수 있습니다.")
    if a.confirm_plan_id != st["plan"]["id"]:
        block("not_confirmed", "병합에는 사용자의 명시적 승인과 현재 plan id가 필요합니다.")
    conflict = next((c for c in st["plan"]["conflicts"] if c["path"] == a.path), None)
    if not conflict or not conflict.get("strategy"):
        block("no_merge_rule", f"{a.path}에는 manifest 병합 전략이 없습니다. 수동으로 처리하세요.")
    if any(m["path"] == a.path for m in st["merges"]):
        block("already_merged", f"{a.path}는 이미 병합되었습니다.")
    target = project / a.path
    current = target.read_bytes()
    if sha256_bytes(current) != conflict["project_sha256"]:
        block("changed_since_plan", f"{a.path}가 계획 이후 변경되었습니다. 계획을 다시 확인하세요.")
    rule = next(r for r in st["manifest"]["merge"] if r["path"] == a.path)
    bp = substituted(a.path, (snapshot / a.path).read_bytes(), st["manifest"], st["project_slug"], st["project_title"]).decode("utf-8")
    text = current.decode("utf-8")
    label = f"{st['source']['manifest_name']} {st['source']['ref']} (product-init)"
    if rule["strategy"] == "append-missing-lines":
        have = {l.strip() for l in text.splitlines()}
        missing = [l for l in bp.splitlines() if l.strip() and not l.strip().startswith("#") and l.strip() not in have]
        if not missing:
            block("nothing_to_merge", "추가할 줄이 없습니다.")
        addition = ("" if text.endswith("\n") or not text else "\n") + f"\n# --- {label} ---\n" + "\n".join(missing) + "\n"
    else:
        addition = ("" if text.endswith("\n") or not text else "\n") + f"\n<!-- {label} -->\n## {rule['section_title']}\n\n" + bp.rstrip("\n") + "\n"
    backup = None
    tracked = git(project, "ls-files", "--error-unmatch", a.path, check=False).strip() != ""
    modified = git(project, "status", "--porcelain", "--", a.path).strip() != ""
    if not tracked or modified:
        backup = ".ai-workflow/backup/product-init__" + a.path.replace("/", "__") + ".bak"
        (project / backup).parent.mkdir(parents=True, exist_ok=True)
        (project / backup).write_bytes(current)
    target.write_text(text + addition, encoding="utf-8")
    st["merges"].append({"path": a.path, "strategy": rule["strategy"], "before_sha256": sha256_bytes(current),
                         "after_sha256": sha256_file(target), "backup": backup, "at": now()})
    add_history(st, "merged", a.path)
    save_state(project, st)
    emit({"ok": True, "path": a.path, "strategy": rule["strategy"], "backup": backup, "appended": addition})


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def expand(text: str, compose: str, ports: dict) -> str:
    text = text.replace("{compose}", compose)
    for k, v in ports.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def compose_cmd(st: dict) -> str:
    env_file = st["manifest"].get("verify", {}).get("env_file", ".env.example")
    return f"docker compose -p {compose_project(st)} --env-file {env_file}"


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def cmd_verify(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    if st["status"] not in ("applied", "verified", "verify_failed"):
        block("not_applied", "검증은 적용이 끝난 뒤에 실행합니다.")
    v = st["manifest"].get("verify", {})
    steps = v.get("stages", {}).get(a.stage, [])
    ports = v.get("ports", {})
    compose = compose_cmd(st)
    uses_docker = a.stage in ("db", "smoke")
    expanded = [{"run": expand(s["run"], compose, ports), "cwd": s.get("cwd", "."), "timeout": s.get("timeout", 900)} for s in steps]
    http = [{**h, "url": expand(h["url"], compose, ports)} for h in (v.get("http", []) if a.stage == "smoke" else [])]
    cleanup = f"{compose} down --remove-orphans" if uses_docker else None
    if a.dry_run:
        emit({"ok": True, "dry_run": True, "stage": a.stage, "compose_project": compose_project(st), "steps": expanded,
              "http": http, "cleanup": cleanup, "env": {**{k: str(p) for k, p in ports.items()}, **{k: str(x) for k, x in v.get("env", {}).items()}}})
    if not steps:
        block("no_steps", f"manifest에 {a.stage} 단계 검증 명령이 없습니다.")
    cv = cross_verify(project, st)
    if cv["user_modified"] or cv["missing"]:
        block("state_mismatch", "적용 파일이 기록과 다릅니다. 검증 전에 확인하세요.", **cv)
    if a.stage in ("fe", "be") and not a.allow_unignored:
        # 디렉터리 규칙(`node_modules/`)은 아직 없는 경로에 매칭되지 않으므로, 경로 아래 가상 파일로 확인합니다.
        not_ignored = [p for p in v.get("ignored_paths", [])
                       if subprocess.run(["git", "-C", str(project), "check-ignore", "-q", p.rstrip("/") + "/.product-init-probe"]).returncode != 0]
        if not_ignored:
            block("gitignore_missing", "검증 산출물이 Git에서 무시되지 않습니다. .gitignore 병합 후 다시 실행하세요.", paths=not_ignored)
    env = os.environ.copy()
    env.update({k: str(p) for k, p in ports.items()})
    env.update({k: str(x) for k, x in v.get("env", {}).items()})
    result = {"stage": a.stage, "at": now(), "steps": [], "result": "pass"}
    if uses_docker:
        if not docker_available():
            result.update(result="error", reason="docker_unavailable")
        else:
            busy = [p for p in ports.values() if not port_free(p)]
            if busy:
                result.update(result="error", reason=f"ports_in_use {busy}")
        if result["result"] != "pass":
            return finish_verify(project, st, result)
        st.setdefault("verification", {})["compose_project"] = compose_project(st)
        save_state(project, st)
    log_dir = Path(tempfile.mkdtemp(prefix=f"product-init-verify-{a.stage}-"))
    try:
        for i, s in enumerate(expanded):
            t0 = time.time()
            log = log_dir / f"{i:02d}.log"
            try:
                proc = subprocess.run(s["run"], shell=True, cwd=project / s["cwd"], env=env, capture_output=True, text=True, timeout=s["timeout"])
                code, output = proc.returncode, proc.stdout + proc.stderr
            except subprocess.TimeoutExpired as e:
                code, output = 124, f"timeout after {s['timeout']}s\n{e.stdout or ''}"
            log.write_text(output, encoding="utf-8")
            result["steps"].append({"run": s["run"], "cwd": s["cwd"], "exit": code, "seconds": round(time.time() - t0, 1), "log": str(log)})
            if code != 0:
                result.update(result="fail", failed_step=s["run"], tail=output.strip().splitlines()[-30:])
                break
        if result["result"] == "pass":
            for h in http:
                ok, detail = http_check(h)
                result["steps"].append({"http": h["url"], "ok": ok, "detail": detail})
                if not ok:
                    result.update(result="fail", failed_step=h["url"], tail=[detail])
                    break
    finally:
        if cleanup and not a.keep_running:
            proc = subprocess.run(cleanup, shell=True, cwd=project, env=env, capture_output=True, text=True)
            result["cleanup"] = {"run": cleanup, "exit": proc.returncode}
    finish_verify(project, st, result)


def http_check(h: dict, attempts: int = 30) -> tuple[bool, str]:
    last = ""
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(h["url"], timeout=5) as r:
                body = r.read().decode("utf-8", errors="replace")
                if r.status == h.get("expect_status", 200) and h.get("contains", "") in body:
                    return True, f"{r.status}"
                last = f"status {r.status}, body {body[:200]}"
        except (urllib.error.URLError, OSError) as e:
            last = str(e)
        time.sleep(2)
    return False, last


def finish_verify(project: Path, st: dict, result: dict) -> None:
    ver = st.setdefault("verification", {})
    ver[result["stage"]] = result
    defined = [s for s in STAGES if st["manifest"].get("verify", {}).get("stages", {}).get(s)]
    stage_results = [ver.get(s, {}).get("result") for s in defined]
    if all(r == "pass" for r in stage_results):
        st["status"] = "verified"
    elif any(r in ("fail", "error") for r in stage_results):
        st["status"] = "verify_failed"
    add_history(st, f"verify_{result['stage']}", result["result"] + (f": {result.get('reason') or result.get('failed_step', '')}" if result["result"] != "pass" else ""))
    save_state(project, st)
    emit({"ok": result["result"] == "pass", "status": st["status"], "verification": result}, 0 if result["result"] == "pass" else 2)


def cmd_cleanup(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    vp = compose_project(st)
    recorded = st.get("verification", {}).get("compose_project")
    compose = compose_cmd(st)
    plan = {"down": f"{compose} down --remove-orphans",
            "list_volumes": f"docker volume ls -q --filter label=com.docker.compose.project={vp}"}
    if a.dry_run:
        emit({"ok": True, "dry_run": True, "compose_project": vp, **plan,
              "volume_removal_allowed": bool(recorded == vp and vp.endswith(VERIFY_SUFFIX))})
    if not docker_available():
        block("docker_unavailable", "Docker 데몬에 연결할 수 없습니다.")
    down = subprocess.run(plan["down"], shell=True, cwd=project, capture_output=True, text=True)
    vols = run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={vp}"], check=False).split()
    removed = []
    if a.remove_volumes:
        if not (recorded == vp and vp.endswith(VERIFY_SUFFIX)):
            block("volume_removal_refused", "이 Skill이 만든 검증 전용 Compose 프로젝트로 확인되지 않아 볼륨을 삭제하지 않습니다.", volumes=vols)
        if not a.confirm:
            block("confirm_required", "볼륨 삭제에는 사용자 확인(--confirm)이 필요합니다.", volumes=vols)
        for vol in vols:
            labels = run(["docker", "volume", "inspect", "-f", "{{json .Labels}}", vol], check=False)
            if f'"com.docker.compose.project":"{vp}"' in labels:
                subprocess.run(["docker", "volume", "rm", vol], capture_output=True)
                removed.append(vol)
    add_history(st, "cleanup", f"down exit {down.returncode}, removed volumes {removed}")
    save_state(project, st)
    emit({"ok": down.returncode == 0, "compose_project": vp, "volumes": vols, "removed": removed})


def cmd_status(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    cv = cross_verify(project, st)
    gate = read_gate(project)
    out = {"ok": cv["consistent"] and gate["ok"], "status": st["status"], "source": st["source"], "branch": st.get("branch"),
           "approval": st["approval"], "counts": {"planned_add": len(st["plan"]["add"]), "files_done": len(st["files_done"]),
           "planned_conflicts": len(st["plan"]["conflicts"]), "runtime_conflicts": len(st["runtime_conflicts"]), "merges": len(st["merges"])},
           "cross_verify": cv, "gate": gate, "verification": {k: v.get("result") for k, v in st.get("verification", {}).items() if isinstance(v, dict)}}
    if a.check_remote:
        try:
            remote = ls_remote_tag(st["source"]["repo"], st["source"]["ref"])
        except RuntimeError as e:
            remote = None
            out["remote_error"] = str(e)
        out["remote_commit"] = remote
        if remote != st["source"]["commit"]:
            out["ok"] = False
            out["tag_moved"] = True
            out["message"] = "원격 태그가 기록된 커밋과 다른 커밋을 가리킵니다. 공급망 변경 가능성이 있으니 확인하세요."
    emit(out, 0 if out["ok"] else 2)


def main() -> None:
    p = argparse.ArgumentParser(description="/product-init helper")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check"); s.add_argument("--project", required=True); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("resolve"); s.add_argument("--source", required=True); s.add_argument("--ref", required=True); s.set_defaults(fn=cmd_resolve)
    s = sub.add_parser("snapshot"); s.add_argument("--source", required=True); s.add_argument("--ref", required=True)
    s.add_argument("--sha", required=True); s.add_argument("--dest", required=True); s.add_argument("--project"); s.set_defaults(fn=cmd_snapshot)
    s = sub.add_parser("plan"); s.add_argument("--project", required=True); s.add_argument("--snapshot", required=True)
    s.add_argument("--source", required=True); s.add_argument("--ref", required=True); s.add_argument("--sha", required=True)
    s.add_argument("--slug"); s.add_argument("--title"); s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("approve"); s.add_argument("--project", required=True); s.add_argument("--plan-id", required=True); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("branch"); s.add_argument("--project", required=True); s.add_argument("--name", required=True); s.set_defaults(fn=cmd_branch)
    s = sub.add_parser("apply"); s.add_argument("--project", required=True); s.add_argument("--snapshot", required=True)
    s.add_argument("--stop-after", type=int, default=0, help=argparse.SUPPRESS); s.set_defaults(fn=cmd_apply)
    s = sub.add_parser("merge"); s.add_argument("--project", required=True); s.add_argument("--snapshot", required=True)
    s.add_argument("--path", required=True); s.add_argument("--confirm-plan-id", required=True); s.set_defaults(fn=cmd_merge)
    s = sub.add_parser("verify"); s.add_argument("--project", required=True); s.add_argument("--stage", required=True, choices=STAGES)
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--keep-running", action="store_true")
    s.add_argument("--allow-unignored", action="store_true"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("cleanup"); s.add_argument("--project", required=True); s.add_argument("--remove-volumes", action="store_true")
    s.add_argument("--confirm", action="store_true"); s.add_argument("--dry-run", action="store_true"); s.set_defaults(fn=cmd_cleanup)
    s = sub.add_parser("status"); s.add_argument("--project", required=True); s.add_argument("--check-remote", action="store_true"); s.set_defaults(fn=cmd_status)
    a = p.parse_args()
    try:
        a.fn(a)
    except RuntimeError as e:
        block("command_failed", str(e))


if __name__ == "__main__":
    main()
