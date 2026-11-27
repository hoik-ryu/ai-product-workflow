#!/usr/bin/env python3
"""/product-change 결정적 보조 스크립트 — 승인된 제품의 변경 패키지(Change Package) 조정(Python 3.11+, 표준 라이브러리만).

신규 제품의 단계별 승인 경로는 그대로 두고, 이미 승인된 제품의 변경을 사용자 승인 2회(변경 계약 → 최종 통합)로 처리합니다.
- 이 스크립트는 `.ai-workflow/change.json`과 `docs/changes/`만 씁니다. 다른 Skill의 상태(state.yaml·design.json·build.json)는
  각 Skill의 CLI(`--package` 옵션)로만 바뀝니다. 승인 문장은 사용자 원문만 기록하고, 단계별 문장을 만들지 않습니다.
- 각 단계의 엔진 검증(추적성·프리뷰 검사·빌드·화면 실측·배치 검증·회귀)은 생략하지 않습니다.

하위 명령:
  enable          기능 켜기(계획 → --confirm --note). design 변경 요청(M1)도 함께 켬(같은 동의 문장, 계획에 표시)
  plan            읽기 전용 ID 단위 영향 분석(기본: 승인 기획 대비 현재 차이, --ids: 지정 ID JSON)
  open            변경 계약 등록(--contract <프로젝트 밖 JSON>) → docs/changes/CP-###.json·.md, 기준·작업 트리 스냅샷, 영향·커버리지
  amend-contract  계약 개정(새 revision, 이전 계약 승인은 재사용하지 않음)
  approve-contract 1차 사용자 승인(--note 원문). 계약·기준·영향 digest에 결합
  snapshot-planning 개정한 기획을 패키지 제안으로 기록(계약 ID 범위·front matter 검증) — 이후 디자인·구현은 이 제안을 임시 기준으로 진행
  snapshot-plan   개정한 구현 계획을 패키지 제안으로 기록(plan-validate·계약 배치 범위)
  review          영향받았지만 바꾸지 않은 단위를 근거와 함께 기록(최종 승인 때 사용자에게 보여 줌)
  check           범위 검사(계약 밖 파일·위험 작업) — 벗어나면 escalated
  regression      전체 회귀(구현이 있는 모든 배치 verify)
  submit-final    최종 통합 승인 묶음(전후·산출물·화면·검증·영향/유지 승인) digest
  approve-final   2차 사용자 승인(--note 원문). 묶음 digest가 그대로일 때만
  finalize        각 Skill에 공식 기록(멱등, 중단 후 다시 실행 = resume)
  resume          다음 할 일 안내 또는 finalize 이어서
  abandon         패키지 취소(--restore: 안전할 때만 범위 파일 복원, 기존 미커밋 작업 보존)
  status / gate   상태 / 공식 빌드·배포 게이트(진행 중·finalize 중 패키지가 있으면 종료 2)

모든 출력은 JSON, 차단 시 종료 코드 2.
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pc_graph as G  # noqa: E402
from pd_core import PLANNING_FILES, DISCOVERY_FILE, sha256_bytes, sha256_file, workflow_of  # noqa: E402

ENGINE_SKILLS = HERE.parent.parent
PS = ENGINE_SKILLS / "product-start/scripts/ps_state.py"
PD = ENGINE_SKILLS / "product-design/scripts/product_design.py"
PB = ENGINE_SKILLS / "product-build/scripts/product_build.py"
STATE_REL = ".ai-workflow/change.json"
LOCK_REL = ".ai-workflow/.change.lock"
CHANGES_DIR = "docs/changes"
WORK_DIR = ".ai-workflow/changes"
PLAN_FILES = ("docs/build/implementation-plan.json", "docs/build/00-implementation-plan.md", "docs/build/build-profile.toml")
ACTIVE = ("draft", "awaiting_contract_approval", "executing", "escalated", "awaiting_final_approval", "finalizing")
RISKY_PATTERNS = ("**/migrations/**", "**/alembic/versions/**", "**/*.sql", "**/prisma/migrations/**", "**/db/migrate/**")
ALWAYS_ALLOWED = (".ai-workflow/*", ".ai-workflow/**", "docs/changes/*")
CONTRACT_KEYS = ("purpose", "policy", "ids", "keep", "design", "build", "files", "db_api", "tests", "risky_ops", "verification")


# ================================================================ 공통
class Blocked(Exception):
    def __init__(self, error: str, message: str, **extra):
        super().__init__(message)
        self.payload = {"ok": False, "error": error, "message": message, **extra}


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def run(script: Path, *args) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": (p.stdout + p.stderr)[-2000:]}


def git(project: Path, *args, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=project, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Blocked("git_failed", f"git {' '.join(args)}: {p.stderr.strip()[:200]}")
    return p.stdout


def git_bytes(project: Path, rev: str, rel: str) -> bytes | None:
    p = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=project, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def match(rel: str, pats) -> bool:
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip("/") + "/**") or rel.startswith(pat.rstrip("*").rstrip("/") + "/")
               and pat.endswith(("/", "/**")) for pat in pats)


# ================================================================ 상태 파일(잠금·원자적·동시 변경 감지)
_LOADED: dict[int, str] = {}


def load(project: Path) -> dict:
    p = project / STATE_REL
    if not p.is_file():
        return {}
    raw = p.read_bytes()

    def nodup(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise Blocked("state_duplicate_keys", f"{STATE_REL}에 같은 키({k})가 두 번 있습니다(병합 흔적). 자동으로 고르지 않습니다.")
            out[k] = v
        return out
    try:
        st = json.loads(raw.decode("utf-8"), object_pairs_hook=nodup)
    except (ValueError, UnicodeDecodeError) as e:
        raise Blocked("state_unreadable", f"{STATE_REL}을 읽을 수 없습니다: {e}" + (" 병합 충돌 표시가 있습니다." if b"<<<<<<<" in raw else ""))
    _LOADED[id(st)] = sha256_bytes(raw)
    return st


def save(project: Path, st: dict) -> None:
    p = project / STATE_REL
    lock = project / LOCK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        try:
            pid = int(lock.read_text().strip() or 0)
            os.kill(pid, 0)
            raise Blocked("state_locked", f"다른 프로세스(pid {pid})가 {STATE_REL}을 쓰는 중입니다.")
        except (ValueError, ProcessLookupError):
            lock.unlink(missing_ok=True)
            return save(project, st)
    try:
        seen = _LOADED.get(id(st))
        cur = sha256_bytes(p.read_bytes()) if p.exists() else None
        if seen is not None and cur != seen:
            raise Blocked("state_conflict", f"이 명령이 {STATE_REL}을 읽은 뒤 다른 명령이 바꿨습니다. 덮어쓰지 않았습니다.")
        if seen is None and cur is not None and id(st) not in _LOADED:
            raise Blocked("state_conflict", f"{STATE_REL}이 이미 있습니다(읽지 않고 쓰려 함).")
        st["updated_at"] = now()
        data = (json.dumps(st, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".change.", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, p)
        _LOADED[id(st)] = sha256_bytes(data)
    finally:
        lock.unlink(missing_ok=True)


def require_enabled(project: Path) -> dict:
    st = load(project)
    if not st.get("enabled"):
        raise Blocked("change_disabled", "변경 패키지 기능이 꺼져 있습니다. 사용자 동의 후 enable(계획) → --confirm --note로 켭니다.")
    return st


def get_pkg(st: dict, pid: str) -> dict:
    pk = (st.get("packages") or {}).get(pid or "")
    if not pk:
        raise Blocked("unknown_package", f"{pid} 패키지가 없습니다.")
    return pk


def log(pk: dict, event: str, **kw) -> None:
    pk.setdefault("history", []).append({"at": now(), "event": event, **kw})


# ================================================================ 프로젝트 사실
def planning_state(project: Path) -> dict:
    """state.yaml의 planning 상태·revision·승인 해시·제출 스냅샷(읽기 전용)."""
    y = (project / ".ai-workflow/state.yaml").read_text(encoding="utf-8") if (project / ".ai-workflow/state.yaml").is_file() else ""
    m = re.search(r"^  planning:\n(.*?)(?=^  \w+:|^\S)", y, re.S | re.M)
    b = m.group(1) if m else ""
    status = (re.search(r"^    status:\s*(\S+)", b, re.M) or [None, None])[1]
    rev = (re.search(r"^    revision:\s*(\d+)", b, re.M) or [None, None])[1]

    def block(name):
        bm = re.search(rf"^    {name}:\n((?:^      .*\n)*)", b, re.M)
        if not bm:
            return {}
        r = (re.search(r"^      revision:\s*\"?(\w+)", bm.group(1), re.M) or [None, None])[1]
        return {"revision": r, "hashes": dict(re.findall(r"(docs/planning/[\w./-]+?)\"?\s*:\s*\"?([0-9a-f]{64})", bm.group(1)))}
    return {"status": status, "revision": int(rev) if rev else None, "approved": block("approved"), "submitted": block("submitted")}


def design_digest(project: Path) -> str | None:
    if not (project / ".ai-workflow/design.json").is_file():
        return None
    code, out = run(PD, "status", "--project", project)
    return ((out.get("changes") or {}).get("effective_digest")) or digest({k: (v or {}).get("approved_revision") for k, v in (out.get("stages") or {}).items()})


def plan_approved(project: Path) -> dict:
    p = project / ".ai-workflow/build.json"
    if not p.is_file():
        return {}
    b = json.loads(p.read_text(encoding="utf-8"))
    return {"status": b["plan"]["status"], "revision": b["plan"].get("revision"), "hashes": ((b["plan"].get("approved") or {}).get("hashes")) or {}}


def worktree_snapshot(project: Path) -> dict:
    """작업 트리의 미커밋 파일(수정·추가·삭제)과 해시. 패키지 시작 전 사용자 작업을 구분하는 기준."""
    out = {}
    for line in git(project, "status", "--porcelain", "--untracked-files=all").splitlines():
        rel = line[3:].split(" -> ")[-1].strip('"')
        if rel.startswith((".ai-workflow/", ".claude/")):
            continue
        out[rel] = sha256_file(project / rel) if (project / rel).is_file() else None
    return out


def open_sha(project: Path, pk: dict, rel: str) -> str | None:
    """패키지 시작 시점의 파일 해시(미커밋이면 그 시점 작업 트리, 아니면 시작 커밋)."""
    dirty = pk["base"]["dirty"]
    if rel in dirty:
        return dirty[rel]
    b = git_bytes(project, pk["base"]["commit"], rel)
    return sha256_bytes(b) if b is not None else None


def changed_since_open(project: Path, pk: dict) -> dict[str, tuple]:
    rels = set(pk["base"]["dirty"]) | set(git(project, "diff", "--name-only", pk["base"]["commit"]).split()) | set(worktree_snapshot(project))
    out = {}
    for rel in sorted(rels):
        if rel.startswith((".ai-workflow/", ".claude/")):
            continue
        cur = sha256_file(project / rel) if (project / rel).is_file() else None
        o = open_sha(project, pk, rel)
        if cur != o:
            out[rel] = (o, cur)
    return out


# ================================================================ 계약
def load_contract(path: Path) -> dict:
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Blocked("invalid_contract", f"계약 JSON을 읽을 수 없습니다: {e}")
    missing = [k for k in CONTRACT_KEYS if k not in c]
    if missing or c.get("schema") != "change-contract/v1":
        raise Blocked("invalid_contract", "계약은 schema change-contract/v1과 필수 항목이 필요합니다.", missing=missing,
                      template={"schema": "change-contract/v1", "purpose": "", "policy": "", "ids": {"add": [], "modify": [], "remove": []},
                                "keep": [], "design": {"units": [], "screens": [], "files": []}, "build": {"rework": [], "regression": []},
                                "files": [], "db_api": {"migrations": [], "api": {"add": [], "modify": [], "remove": []}},
                                "tests": {"remove": [], "modify": [], "add": []}, "risky_ops": [], "verification": []})
    if not str(c.get("purpose") or "").strip():
        raise Blocked("invalid_contract", "변경 목적(purpose)이 비어 있습니다.")
    return c


def render_contract(pid: str, c: dict, rev: int, imp: dict, gaps: dict) -> str:
    ids = c["ids"]
    lines = [f"# 변경 계약 {pid} (revision {rev})", "", "> 엔진이 생성한 문서입니다. 직접 수정하지 말고 amend-contract로 개정합니다.", "",
             "## 목적", c["purpose"], "", "## 정책", c["policy"] or "-", "",
             "## 요구사항 ID", f"- 추가: {', '.join(ids.get('add') or []) or '없음'}", f"- 수정: {', '.join(ids.get('modify') or []) or '없음'}",
             f"- 폐기: {', '.join(ids.get('remove') or []) or '없음'}", "", "## 유지해야 할 기존 계약", *[f"- {x}" for x in c["keep"] or ["(명시 없음)"]], "",
             "## 영향 범위(엔진 분석)", f"- 영향 화면: {', '.join(imp['screens']) or '없음'}", f"- 영향 디자인 단위: {', '.join(imp['design_units']) or '없음'}",
             f"- 영향 단계: {', '.join(imp['stages_affected']) or '없음'} / 승계(영향 없음): {', '.join(imp['stages_inherited']) or '없음'}",
             f"- 영향 배치: {', '.join(imp['batches']) or '없음'}", f"- 프리뷰 파일: {', '.join(imp['preview_files']) or '없음'}",
             *[f"- 범위 확대: {w}" for w in imp["widened"]], "",
             "## 디자인 변경 범위", f"- 단위: {', '.join(c['design'].get('units') or []) or '없음'}", f"- 화면: {', '.join(c['design'].get('screens') or []) or '없음'}", "",
             "## 구현 범위", f"- 재작업 배치: {', '.join(c['build'].get('rework') or []) or '없음'}", f"- 회귀만: {', '.join(c['build'].get('regression') or []) or '없음'}",
             f"- 허용 파일: {', '.join(c['files']) or '없음'}", "", "## DB·API", f"- 마이그레이션: {', '.join(c['db_api'].get('migrations') or []) or '없음'}",
             f"- API: {json.dumps(c['db_api'].get('api') or {}, ensure_ascii=False)}", "",
             "## 테스트", *[f"- 삭제: {t.get('ac')} {', '.join(t.get('paths') or [])} {', '.join(t.get('cases') or [])}" for t in c["tests"].get("remove") or []],
             *[f"- 수정: {t}" for t in c["tests"].get("modify") or []], *[f"- 추가: {t}" for t in c["tests"].get("add") or []], "",
             "## 위험 작업 허용", *[f"- {x}" for x in c["risky_ops"] or ["없음"]], "", "## 검증 기준", *[f"- {x}" for x in c["verification"] or ["(엔진 기본 검증)"]]]
    if any(gaps.values()):
        lines += ["", "## ⚠ 계약이 덮지 못한 영향(승인 불가)", *[f"- {k}: {', '.join(v)}" for k, v in gaps.items() if v]]
    return "\n".join(lines) + "\n"


def coverage(c: dict, imp: dict, pdiff: dict | None) -> dict:
    ids = c["ids"]
    declared = set(ids.get("add") or []) | set(ids.get("modify") or []) | set(ids.get("remove") or [])
    d_units = set(c["design"].get("units") or []) | set(c["design"].get("screens") or [])
    gaps = {"design_units": sorted(u for u in set(imp["design_units"]) | set(imp["screens"]) if u not in d_units and G.norm(u) not in d_units),
            "batches": sorted(set(imp["batches"]) - set(c["build"].get("rework") or []) - set(c["build"].get("regression") or [])),
            "code_files": sorted(f for f in imp["code_mentions"] if not match(f, c["files"]) and not any(f in (t.get("paths") or []) for t in c["tests"].get("remove") or [])),
            "planning_ids": []}
    if pdiff and pdiff.get("known"):
        actual = set(pdiff["added"]) | set(pdiff["modified"]) | set(pdiff["removed"])
        gaps["planning_ids"] = sorted(actual - declared)
    return gaps


def contract_impact(project: Path, c: dict, pdiff: dict | None) -> dict:
    ids = c["ids"]
    changed = {"known": True, "added": list(ids.get("add") or []), "modified": list(ids.get("modify") or []), "removed": list(ids.get("remove") or []),
               "tokens": "tokens" in (c.get("design") or {}).get("units", [])}
    if pdiff:
        if not pdiff.get("known"):
            changed["known"] = False
            changed["reason"] = pdiff.get("reason")
        for k in ("added", "modified", "removed"):
            changed[k] = sorted(set(changed[k]) | set(pdiff.get(k) or []))
    return G.impact(project, changed)


def current_planning_diff(project: Path, approved_hashes: dict) -> dict:
    old = G.approved_planning_texts(project, approved_hashes)
    return G.planning_diff(old, G.current_planning_texts(project))


# ================================================================ 명령
def transition_problems(project: Path) -> list[str]:
    """중간 상태(기획 작성 중, 디자인 불일치, 구현 배치 진행 중, 디자인 변경 요청 진행 중)에서는 켜기·패키지 시작을 막습니다."""
    out = []
    ps = planning_state(project)
    if ps["status"] not in ("approved", "awaiting_approval"):
        out.append(f"planning이 {ps['status']}입니다(승인 또는 제출 상태에서만)")
    if (project / ".ai-workflow/design.json").is_file():
        code, ds = run(PD, "status", "--project", project)
        probs = [p for p in ((ds.get("cross_verify") or {}).get("problems") or [])]
        if probs:
            out.append(f"디자인 상태가 승인 기준과 다릅니다({', '.join(sorted({p.get('kind') for p in probs}))})")
        if any(x.get("package") is None for x in ((ds.get("changes") or {}).get("pending") or [])):
            out.append("진행 중인 디자인 변경 요청(CR)이 있습니다")
        if any(v.get("status") in ("in_progress", "awaiting_approval") for v in (ds.get("stages") or {}).values()):
            out.append("디자인 단계가 작성·승인 대기 중입니다")
    b = build_state(project)
    act = [k for k, x in (b.get("batches") or {}).items() if x.get("status") in ("in_progress", "paused", "failed")]
    if act:
        out.append(f"구현 배치가 진행 중입니다({', '.join(act)})")
    if b and (b.get("plan") or {}).get("status") not in ("approved", None):
        out.append(f"구현 계획이 {(b.get('plan') or {}).get('status')}입니다")
    return out


def design_support(project: Path) -> tuple[bool, bool]:
    """(디자인 v2인가, 디자인 변경 요청이 켜졌는가) — design.json을 읽기만 합니다(쓰기는 product-design CLI만)."""
    p = project / ".ai-workflow/design.json"
    try:
        st = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return False, False
    return workflow_of(st) == "v2", bool(((st.get("config") or {}).get("changes") or {}).get("enabled"))


def cmd_enable(project: Path, a) -> None:
    st = load(project)
    if st.get("enabled"):
        emit({"ok": True, "status": "already_enabled"})
    tp = transition_problems(project)
    if tp:
        raise Blocked("transition_in_progress", "작업이 중간 상태라 변경 패키지 기능을 켜지 않습니다(기존 상태 그대로).", problems=tp)
    design_v2, design_on = design_support(project)
    plan = {"add": [STATE_REL], "design_change_requests": ("이미 켜짐" if design_on else "함께 켬(product_design.py change enable, 같은 동의 문장)" if design_v2
                                                           else "디자인 v2가 아니어서 디자인 영향 패키지는 실행 불가(기획·구현 전용)"),
            "note": "기존 승인 기록·상태는 바꾸지 않습니다. 켜지 않은 프로젝트는 기존 승인 경로 그대로입니다."}
    if not (a.confirm and (a.note or "").strip()):
        emit({"ok": True, "status": "plan", "dry_run": True, "plan": plan, "next": "사용자 동의 문장을 받아 enable --confirm --note"})
    if design_v2 and not design_on:
        c, o = run(PD, "change", "enable", "--project", project, "--confirm", "--note", a.note.strip())
        if c != 0:
            hint = ("기획 문서가 승인본과 달라 디자인 쪽 기능을 켤 수 없습니다. 기획 수정 전에 켜거나, 수정본을 /product-start로 제출(awaiting_approval)한 뒤 "
                    "디자인을 쓰지 않는 패키지로 진행하세요. 기획 문서는 건드리지 않았습니다.") if o.get("error") == "planning_not_approved" else None
            raise Blocked("design_enable_failed", "디자인 변경 요청 기능을 켜지 못했습니다(아무것도 쓰지 않음).", design=o, hint=hint)
    st = {"schema": "product-change/v1", "enabled": True, "enabled_at": now(), "statement": a.note.strip(), "seq": 0, "packages": {}}
    _LOADED[id(st)] = None
    save(project, st)
    emit({"ok": True, "status": "enabled", "plan": plan})


def cmd_plan(project: Path, a) -> None:
    ps = planning_state(project)
    if a.ids:
        req = json.loads(Path(a.ids).read_text(encoding="utf-8"))
        changed = {"known": True, "added": req.get("add", []), "modified": req.get("modify", []), "removed": req.get("remove", []),
                   "tokens": bool(req.get("tokens"))}
    else:
        base = ps["approved"].get("hashes") or {}
        changed = current_planning_diff(project, base)
    imp = G.impact(project, changed)
    emit({"ok": True, "read_only": True, "planning": {"status": ps["status"], "revision": ps["revision"]}, "changed": changed, "impact": imp,
          "summary": {"direct": len(imp["direct"]), "indirect": len(imp["indirect"]), "stages_affected": imp["stages_affected"],
                      "stages_inherited": imp["stages_inherited"], "batches": imp["batches"], "widened": len(imp["widened"]),
                      "dangling_refs": len(imp["dangling_refs"])}})


def cmd_open(project: Path, a) -> None:
    st = require_enabled(project)
    act = [k for k, v in st["packages"].items() if v["status"] in ACTIVE]
    if act:
        raise Blocked("package_active", f"진행 중인 패키지({', '.join(act)})가 있습니다. 동시에 하나만 진행합니다.", active=act)
    c = load_contract(Path(a.contract))
    tp = [x for x in transition_problems(project) if not x.startswith("planning")]
    if tp:
        raise Blocked("transition_in_progress", "작업이 중간 상태라 변경 패키지를 시작하지 않습니다.", problems=tp)
    ps = planning_state(project)
    if ps["status"] == "approved":
        mode, base_hashes = "approved", ps["approved"]["hashes"]
    elif ps["status"] == "awaiting_approval" and ps["submitted"].get("hashes"):
        mode, base_hashes = "adopt", ps["approved"].get("hashes") or {}  # T9 후 제출된 기획을 패키지가 받아들임
    else:
        raise Blocked("planning_not_ready", f"planning 상태가 {ps['status']}입니다. 승인되었거나(approved) 제출된(awaiting_approval) 기획에서만 시작합니다.")
    approved_texts = G.approved_planning_texts(project, base_hashes) if base_hashes else None
    pdiff = G.planning_diff(approved_texts, G.current_planning_texts(project)) if approved_texts is not None else \
        {"known": False, "reason": "승인된 기획 내용을 Git·작업 트리에서 찾지 못했습니다", "added": [], "modified": [], "removed": []}
    imp = contract_impact(project, c, pdiff if (mode == "adopt" or any(pdiff.get(k) for k in ("added", "modified", "removed")) or not pdiff["known"]) else None)
    design_hit = bool(imp.get("stages_affected") or imp.get("design_units") or (c.get("design") or {}).get("units") or (c.get("design") or {}).get("screens"))
    if design_hit:
        v2, on = design_support(project)
        if not (v2 and on):
            raise Blocked("design_package_unsupported",
                          "이 변경은 디자인에 영향이 있지만 디자인이 v2 변경 요청을 쓸 수 없는 상태입니다(v1 또는 변경 요청 꺼짐). "
                          "디자인 범위 승계를 보장할 수 없어 패키지를 열지 않습니다(아무것도 쓰지 않음). 기존 재개정 경로를 쓰거나 디자인을 v2로 옮긴 뒤 다시 시도하세요.",
                          design_stages=imp.get("stages_affected"), design_v2=v2)
    gaps = coverage(c, imp, pdiff)
    st["seq"] = int(st.get("seq") or 0) + 1
    pid = f"CP-{st['seq']:03d}"
    if pid in st["packages"]:
        raise Blocked("package_id_conflict", f"{pid}가 이미 있습니다(다른 Worktree 병합 흔적일 수 있음).")
    cdir = project / CHANGES_DIR
    cdir.mkdir(parents=True, exist_ok=True)
    cjson = cdir / f"{pid}.json"
    cjson.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (cdir / f"{pid}.md").write_text(render_contract(pid, c, 1, imp, gaps), encoding="utf-8")
    dirty = worktree_snapshot(project)
    for rel in (f"{CHANGES_DIR}/{pid}.json", f"{CHANGES_DIR}/{pid}.md"):
        dirty.pop(rel, None)
    wdir = project / WORK_DIR / pid / "pre"
    wdir.mkdir(parents=True, exist_ok=True)
    (project / WORK_DIR / pid / ".gitignore").write_text("*\n")
    backed = []
    for rel, h in dirty.items():  # 패키지 시작 전 미커밋 작업 보관(abandon --restore 기준)
        if h and (project / rel).stat().st_size <= 5 * 1024 * 1024:
            dst = wdir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / rel, dst)
            backed.append(rel)
    pk = {"id": pid, "uid": uuid.uuid4().hex, "status": "awaiting_contract_approval", "opened_at": now(),
          "base": {"commit": git(project, "rev-parse", "HEAD").strip(), "dirty": dirty, "backed_up": backed, "backup_dir": str(wdir.relative_to(project)),
                   "planning": {"mode": mode, "revision": ps["revision"], "approved_revision": ps["approved"].get("revision"), "approved_hashes": base_hashes,
                                "submitted": ps["submitted"] if mode == "adopt" else None},
                   "design_digest": design_digest(project), "plan": plan_approved(project)},
          "contract": {"revision": 1, "file": f"{CHANGES_DIR}/{pid}.json", "md": f"{CHANGES_DIR}/{pid}.md", "sha256": sha256_file(cjson), "scope": c},
          "contract_approvals": [], "impact": imp, "planning_diff": pdiff, "gaps": gaps,
          "planning": {}, "design": {"reviewed_unchanged": []}, "build": {}, "final": None, "finalize": {}, "escalations": []}
    log(pk, "opened", mode=mode)
    st["packages"][pid] = pk
    save(project, st)
    emit({"ok": True, "id": pid, "status": pk["status"], "mode": mode, "contract": pk["contract"]["md"], "impact": {k: imp[k] for k in (
        "screens", "design_units", "stages_affected", "stages_inherited", "batches", "preview_files", "widened")},
          "gaps": gaps, "approvable": not any(gaps.values()), "preexisting_uncommitted": sorted(dirty),
          "next": ("계약이 덮지 못한 영향이 있습니다. 계약에 넣어 amend-contract 후 승인 요청" if any(gaps.values())
                   else f"{pk['contract']['md']}를 사용자에게 보여 주고 1차 승인 문장을 받아 approve-contract --id {pid} --note")})


def cmd_amend(project: Path, a) -> None:
    st = require_enabled(project)
    pk = get_pkg(st, a.id)
    if pk["status"] not in ("awaiting_contract_approval", "executing", "escalated"):
        raise Blocked("invalid_transition", f"{pk['id']} 상태가 {pk['status']}입니다.")
    c = load_contract(Path(a.contract))
    rev = pk["contract"]["revision"] + 1
    pdiff = pk.get("planning_diff")
    if (pk.get("planning") or {}).get("proposal") or pk["base"]["planning"]["mode"] == "adopt":
        pdiff = current_planning_diff(project, pk["base"]["planning"]["approved_hashes"])
    imp = contract_impact(project, c, pdiff)
    gaps = coverage(c, imp, pdiff)
    cjson = project / pk["contract"]["file"]
    cjson.write_text(json.dumps(c, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (project / pk["contract"]["md"]).write_text(render_contract(pk["id"], c, rev, imp, gaps), encoding="utf-8")
    pk["contract"].update(revision=rev, sha256=sha256_file(cjson), scope=c)
    pk.update(impact=imp, gaps=gaps, status="awaiting_contract_approval")  # 확대된 계약은 이전 승인을 재사용하지 않음
    log(pk, "contract_amended", revision=rev, reason=(a.reason or "").strip()[:200])
    save(project, st)
    emit({"ok": True, "id": pk["id"], "status": pk["status"], "revision": rev, "gaps": gaps, "approvable": not any(gaps.values()),
          "next": "개정된 계약을 사용자에게 보여 주고 새 승인 문장을 받아 approve-contract(이전 승인 재사용 불가)"})


def base_digest(project: Path, pk: dict) -> dict:
    ps = planning_state(project)
    return {"planning_approved": ps["approved"].get("hashes"), "design": design_digest(project), "plan": (plan_approved(project) or {}).get("hashes")}


def cmd_approve_contract(project: Path, a) -> None:
    note = (a.note or "").strip()
    if not note:
        raise Blocked("approval_statement_required", "1차 변경 계약 승인은 사용자의 승인 문장 원문(--note)이 필요합니다.")
    st = require_enabled(project)
    pk = get_pkg(st, a.id)
    if pk["status"] != "awaiting_contract_approval":
        raise Blocked("invalid_transition", f"{pk['id']} 상태가 {pk['status']}입니다.")
    if any(pk["gaps"].values()):
        raise Blocked("contract_gaps", "계약이 덮지 못한 영향이 있어 승인할 수 없습니다.", gaps=pk["gaps"])
    cfile = project / pk["contract"]["file"]
    if not cfile.is_file() or sha256_file(cfile) != pk["contract"]["sha256"]:
        raise Blocked("contract_modified", "계약 파일이 등록 이후 바뀌었습니다. amend-contract로 다시 등록합니다.")
    if any(norm_text(note) == norm_text(x["statement"]) for x in pk["contract_approvals"]):
        raise Blocked("approval_reused", "이전 계약 승인 문장을 재사용할 수 없습니다(계약이 바뀌면 새로 승인).")
    bd = base_digest(project, pk)
    rec = {"revision": pk["contract"]["revision"], "contract_sha256": pk["contract"]["sha256"], "impact_digest": pk["impact"]["digest"],
           "base": bd, "statement": note, "at": now()}
    rec["digest"] = digest({k: v for k, v in rec.items() if k not in ("statement", "at")})
    pk["contract_approvals"].append(rec)
    pk["status"] = "executing"
    log(pk, "contract_approved", revision=rec["revision"], digest=rec["digest"][:12])
    save(project, st)
    emit({"ok": True, "id": pk["id"], "status": "executing", "approval": {k: rec[k] for k in ("revision", "digest", "at")},
          "next": "기획 개정 → snapshot-planning → (디자인 영향 시) product_design.py change open --package → … → snapshot-plan → 구현·검증 → regression → submit-final"})


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def require_executing(project: Path, st: dict, pid: str) -> dict:
    pk = get_pkg(st, pid)
    if pk["status"] != "executing":
        raise Blocked("not_executing", f"{pk['id']} 상태가 {pk['status']}입니다(executing에서만).")
    from pd_core import package_contract_valid
    if not package_contract_valid(project, dict(pk, id=pk["id"])):
        raise Blocked("contract_modified", "계약 파일이 승인 이후 바뀌었거나 현재 계약 revision의 승인이 없습니다.")
    return pk


def escalate(project: Path, st: dict, pk: dict, kind: str, items) -> None:
    pk["status"] = "escalated"
    pk["escalations"].append({"at": now(), "kind": kind, "items": items})
    log(pk, "escalated", kind=kind)
    save(project, st)
    raise Blocked("contract_scope_exceeded", f"승인된 변경 계약 범위를 벗어났습니다({kind}). 실행을 멈췄습니다. 계약을 개정해 사용자 승인을 다시 받거나 되돌립니다.",
                  items=items, next="amend-contract --contract <개정 계약> → approve-contract(새 승인)")


def cmd_snapshot_planning(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    ps = planning_state(project)
    base = pk["base"]["planning"]
    cur = G.file_hashes(project, PLANNING_FILES)
    if base["mode"] == "adopt":
        sub = (ps.get("submitted") or {}).get("hashes") or {}
        if ps["status"] != "awaiting_approval" or sub != cur:
            raise Blocked("planning_not_submitted", "받아들인 제출본(awaiting_approval)과 현재 기획 문서가 다릅니다.")
        rev = ps["revision"]
    else:
        if ps["status"] != "approved":
            raise Blocked("planning_state", f"planning 상태가 {ps['status']}입니다(패키지 모드에서는 승인 상태 그대로 두고 문서만 개정).")
        if cur == base["approved_hashes"]:
            raise Blocked("planning_unchanged", "기획 문서가 승인본과 같습니다(기획 변경이 없는 패키지는 이 단계를 건너뜁니다).")
        rev = int(base["revision"]) + 1
        bad = [f for f in PLANNING_FILES if G.frontmatter_revision(project / f) != str(rev)]
        if bad:
            raise Blocked("frontmatter_mismatch", f"기획 4개 문서의 front matter revision을 {rev}로 맞춥니다(단계 revision 공유).", files=bad)
    pdiff = current_planning_diff(project, base["approved_hashes"])
    c = pk["contract"]["scope"]
    imp = contract_impact(project, c, pdiff)
    gaps = coverage(c, imp, pdiff)
    if any(gaps.values()):
        escalate(project, st, pk, "planning_or_impact", gaps)
    pk["planning"]["proposal"] = {"revision": rev, "hashes": cur, "mode": base["mode"], "at": now()}
    pk["planning_diff"], pk["impact"] = pdiff, imp
    log(pk, "planning_snapshot", revision=rev)
    save(project, st)
    emit({"ok": True, "id": pk["id"], "planning_proposal": pk["planning"]["proposal"], "diff": pdiff,
          "impact": {k: imp[k] for k in ("screens", "stages_affected", "stages_inherited", "batches", "dangling_refs")},
          "next": "디자인 영향이 있으면 product_design.py change open --package " + pk["id"]})


def cmd_snapshot_plan(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    code, out = run(PB, "plan-validate", "--project", project)
    if code != 0:
        raise Blocked("plan_invalid", "개정한 구현 계획이 plan-validate를 통과하지 못했습니다.", errors=out.get("errors"))
    old = git_bytes(project, pk["base"]["commit"], PLAN_FILES[0])
    pre = project / pk["base"]["backup_dir"] / PLAN_FILES[0]
    if PLAN_FILES[0] in pk["base"]["dirty"] and pre.is_file():
        old = pre.read_bytes()
    oldp = json.loads(old.decode()) if old else {"batches": []}
    newp = json.loads((project / PLAN_FILES[0]).read_text(encoding="utf-8"))
    ob = {b["id"]: b for b in oldp.get("batches") or []}
    nb = {b["id"]: b for b in newp.get("batches") or []}
    changed = sorted(k for k in set(ob) | set(nb) if ob.get(k) != nb.get(k))
    allowed = set(pk["contract"]["scope"]["build"].get("rework") or []) | set(pk["contract"]["scope"]["build"].get("regression") or [])
    out_of = [k for k in changed if k not in allowed]
    if out_of:
        escalate(project, st, pk, "plan_batches", out_of)
    pk["build"]["plan_proposal"] = {"hashes": G.file_hashes(project, PLAN_FILES), "changed_batches": changed, "at": now()}
    log(pk, "plan_snapshot", changed=changed)
    save(project, st)
    emit({"ok": True, "id": pk["id"], "plan_proposal": pk["build"]["plan_proposal"]})


def cmd_review(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    if not (a.reason or "").strip():
        raise Blocked("reason_required", "바꾸지 않은 근거(--reason)가 필요합니다(최종 승인 때 사용자에게 보여 줌).")
    known = set(pk["impact"]["design_units"]) | set(pk["impact"]["screens"]) | set(pk["impact"]["preview_files"]) | set(pk["impact"]["batches"])
    if a.unit not in known:
        raise Blocked("unknown_unit", f"{a.unit}은 이 패키지의 영향 단위가 아닙니다.", known=sorted(known))
    pk["design"]["reviewed_unchanged"] = [x for x in pk["design"]["reviewed_unchanged"] if x["unit"] != a.unit] + [
        {"unit": a.unit, "reason": a.reason.strip(), "at": now()}]
    save(project, st)
    emit({"ok": True, "id": pk["id"], "reviewed_unchanged": pk["design"]["reviewed_unchanged"]})


def scope_violations(project: Path, pk: dict) -> dict:
    c = pk["contract"]["scope"]
    ch = changed_since_open(project, pk)
    allowed = list(ALWAYS_ALLOWED) + list(PLANNING_FILES) + list(PLAN_FILES) + list(c.get("files") or []) + list(c["design"].get("files") or [])
    allowed += [p for t in c["tests"].get("remove") or [] for p in t.get("paths") or []]
    allowed += [p for t in (c["tests"].get("modify") or []) + (c["tests"].get("add") or []) if isinstance(t, dict) for p in t.get("paths") or []]
    if pk["impact"]["stages_affected"] or c["design"].get("units") or c["design"].get("screens"):
        allowed += ["docs/design/*", "design-preview/**", "design-profile/**"]
    out = sorted(f for f in ch if not match(f, allowed))
    risky = sorted(f for f in ch if match(f, RISKY_PATTERNS) and not match(f, c["db_api"].get("migrations") or []))
    return {"out_of_scope": out, "risky": risky, "changed": sorted(ch)}


def cmd_check(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    v = scope_violations(project, pk)
    if v["out_of_scope"] or v["risky"]:
        escalate(project, st, pk, "files", {"out_of_scope": v["out_of_scope"], "risky_not_allowed": v["risky"]})
    emit({"ok": True, "id": pk["id"], "changed": v["changed"], "preexisting_uncommitted": sorted(pk["base"]["dirty"])})


def build_state(project: Path) -> dict:
    p = project / ".ai-workflow/build.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def cmd_regression(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    b = build_state(project)
    res = {}
    for bid, x in sorted((b.get("batches") or {}).items()):
        if not ((x.get("run") or {}).get("submitted")) or x["status"] in ("in_progress", "paused", "failed"):
            continue
        extra = ["--available", a.available] if getattr(a, "available", "") else []
        code, out = run(PB, "verify", "--project", project, "--batch", bid, *extra)
        res[bid] = {"code": code, "status": build_state(project)["batches"][bid]["status"],
                    "run_id": ((build_state(project)["batches"][bid].get("verification")) or {}).get("run_id"), "error": out.get("error")}
    ok = all(v["status"] in ("verified", "approved") and v["code"] == 0 for v in res.values())
    pk["regression"] = {"at": now(), "ok": ok, "results": res, "artifacts": digest(changed_since_open(project, pk))}
    log(pk, "regression", ok=ok)
    save(project, st)
    emit({"ok": ok, "id": pk["id"], "results": res}, 0 if ok else 2)


def design_package_cr(project: Path, pid: str) -> dict | None:
    p = project / ".ai-workflow/design.json"
    if not p.is_file():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    crs = [c for c in ((d.get("changes") or {}).get("items") or {}).values() if c.get("package") == pid and c["status"] not in ("cancelled",)]
    return crs[-1] if crs else None


def final_bundle(project: Path, pk: dict) -> dict:
    """최종 통합 승인 묶음. 산출물·검증 결과 digest에 결합합니다. 조건이 안 되면 Blocked."""
    problems = []
    c = pk["contract"]["scope"]
    prop = (pk.get("planning") or {}).get("proposal")
    cur_planning = G.file_hashes(project, PLANNING_FILES)
    if prop and cur_planning != prop["hashes"]:
        problems.append("기획 문서가 snapshot-planning 이후 바뀌었습니다(다시 snapshot-planning)")
    if not prop and cur_planning != pk["base"]["planning"]["approved_hashes"] and pk["base"]["planning"]["mode"] != "adopt":
        problems.append("기획 문서가 바뀌었는데 패키지 제안으로 기록되지 않았습니다(snapshot-planning)")
    if pk["base"]["planning"]["mode"] == "adopt" and not prop:
        problems.append("받아들인 기획 제출본을 snapshot-planning으로 기록하지 않았습니다")
    v = scope_violations(project, pk)
    if v["out_of_scope"] or v["risky"]:
        problems.append(f"범위 밖 변경: {v['out_of_scope'] + v['risky']}")
    imp = pk["impact"]
    cr = design_package_cr(project, pk["id"])
    reviewed = {x["unit"] for x in pk["design"]["reviewed_unchanged"]}
    design = {"cr": None}
    changed_units: set[str] = set()
    if cr:
        if cr["status"] != "awaiting_confirmation":
            problems.append(f"디자인 변경({cr['id']})이 검증·제출(submit) 상태가 아닙니다(현재 {cr['status']})")
        design = {"cr": cr["id"], "cr_uid": cr["uid"], "submitted_digest": (cr.get("submitted") or {}).get("digest"),
                  "verification_digest": digest(cr.get("verification")) if cr.get("verification") else None,
                  "screen_verification": ((cr.get("verification") or {}).get("screen_verification") or {}).get("status")}
        for rel, (o, n) in ((cr.get("submitted") or {}).get("file_transitions") or {}).items():
            changed_units.add(rel)
            if rel.startswith("docs/design/"):
                old = git_bytes(project, pk["base"]["commit"], rel)
                pre = project / pk["base"]["backup_dir"] / rel
                if rel in pk["base"]["dirty"] and pre.is_file():
                    old = pre.read_bytes()
                from pd_impact import changed_ids
                from pd_core import strip_fences as _sf
                changed_units |= set(changed_ids(_sf(old.decode("utf-8", "replace")) if old else "", _sf((project / rel).read_text(encoding="utf-8"))))
    elif imp["stages_affected"]:
        problems.append(f"디자인 영향({', '.join(imp['stages_affected'])})이 있는데 패키지 디자인 변경이 없습니다(product_design.py change open --package)")
    # 영향 단위는 바뀌었거나, 바꾸지 않은 근거가 기록돼야 함(직접 참조 없음 ≠ 영향 없음)
    unresolved = []
    for u in sorted(set(imp["design_units"]) | set(imp["screens"])):
        if u in reviewed or u in changed_units or any(x.startswith(u) for x in changed_units):
            continue
        unresolved.append(u)
    for f in imp["preview_files"]:
        if f not in changed_units and f not in reviewed and "design-preview/" not in changed_units:
            pass
    if unresolved:
        problems.append(f"영향 단위가 바뀌지도, 바꾸지 않은 근거(review)도 없습니다: {unresolved}")
    dangling = G.impact(project, {"known": True, "added": [], "modified": [], "removed": imp["removed"]})["dangling_refs"]
    if dangling:
        problems.append(f"폐기된 ID의 유효 참조가 남아 있습니다(이력 표기로 바꾸거나 지움): {[(d['file'], d['line'], d['ids']) for d in dangling][:8]}")
    b = build_state(project)
    batches = {}
    for bid in sorted(set(c["build"].get("rework") or []) | set(c["build"].get("regression") or [])):
        x = (b.get("batches") or {}).get(bid)
        if not x:
            problems.append(f"계약의 배치 {bid}가 구현 상태에 없습니다")
            continue
        ver = x.get("verification") or {}
        # 한 번도 구현하지 않은(planned, 제출 기록 없음) 배치는 검증할 코드가 없음: 바꾸지 않은 근거(review)가 있을 때만 '미구현'으로 기록.
        # regression도 제출되지 않은 배치는 건너뜀(같은 기준). 근거가 없으면 기존처럼 막음
        if x["status"] == "planned" and not (x.get("run") or {}).get("submitted") and bid not in set(c["build"].get("rework") or []):
            if bid in reviewed:
                batches[bid] = {"status": "planned", "not_implemented": True, "review": reviewed[bid] if isinstance(reviewed, dict) else True}
                continue
            problems.append(f"{bid}는 구현되지 않은 배치입니다. 바꾸지 않는 근거를 review --unit {bid}로 남기거나 계약에서 뺍니다")
            continue
        if x["status"] not in ("verified", "approved") or ver.get("package") != pk["id"]:
            problems.append(f"{bid}가 패키지 기준으로 검증되지 않았습니다(상태 {x['status']}, 기준 {ver.get('package')})")
        batches[bid] = {"status": x["status"], "run_id": ver.get("run_id"), "digest": ver.get("digest"), "package": ver.get("package"),
                        "ui_evidence": (ver.get("ui") or {}).get("evidence_digest")}
    reg = pk.get("regression") or {}
    if not reg.get("ok"):
        problems.append("전체 회귀(regression)가 통과한 기록이 없습니다")
    elif reg.get("artifacts") != digest(changed_since_open(project, pk)):
        problems.append("회귀 이후 파일이 바뀌었습니다(regression 다시 실행)")
    plan_prop = (pk.get("build") or {}).get("plan_proposal")
    if plan_prop and G.file_hashes(project, PLAN_FILES) != plan_prop["hashes"]:
        problems.append("구현 계획이 snapshot-plan 이후 바뀌었습니다")
    if problems:
        raise Blocked("final_not_ready", "최종 통합 승인 조건을 충족하지 않았습니다.", problems=problems)
    artifacts = {rel: n for rel, (o, n) in changed_since_open(project, pk).items()}
    before = {rel: o for rel, (o, n) in changed_since_open(project, pk).items()}
    return {"package": pk["id"], "uid": pk["uid"], "contract": {"revision": pk["contract"]["revision"], "sha256": pk["contract"]["sha256"],
                                                                "approval_digest": pk["contract_approvals"][-1]["digest"]},
            "planning": prop, "design": design, "reviewed_unchanged": sorted(reviewed), "plan": plan_prop, "batches": batches,
            "regression": {"at": reg.get("at"), "results": {k: v["status"] for k, v in reg.get("results", {}).items()}},
            "impact_digest": imp["digest"], "stages_affected": imp["stages_affected"], "stages_inherited": imp["stages_inherited"],
            "artifacts_after": artifacts, "artifacts_before": before, "preexisting_uncommitted": sorted(pk["base"]["dirty"])}


def cmd_submit_final(project: Path, a) -> None:
    st = require_enabled(project)
    pk = require_executing(project, st, a.id)
    run(PB, "check", "--project", project)  # 검증 이후 변경을 stale로 반영(Build 소유 파일만 씀)
    bundle = final_bundle(project, pk)
    pk["final"] = {"bundle": bundle, "digest": digest(bundle), "submitted_at": now(), "statement": None}
    pk["status"] = "awaiting_final_approval"
    log(pk, "final_submitted", digest=pk["final"]["digest"][:12])
    save(project, st)
    emit({"ok": True, "id": pk["id"], "status": pk["status"], "digest": pk["final"]["digest"], "show_user": {
        "changed_artifacts": sorted(bundle["artifacts_after"]), "stages_affected": bundle["stages_affected"], "stages_inherited": bundle["stages_inherited"],
        "reviewed_unchanged": bundle["reviewed_unchanged"], "design": bundle["design"], "batches": bundle["batches"], "regression": bundle["regression"],
        "preexisting_uncommitted": bundle["preexisting_uncommitted"]},
          "next": "변경 전후·화면 검증·구현/회귀 결과·영향/유지 승인을 사용자에게 보여 주고 2차 승인 문장을 받아 approve-final --note"})


def cmd_approve_final(project: Path, a) -> None:
    note = (a.note or "").strip()
    if not note:
        raise Blocked("approval_statement_required", "최종 통합 승인은 사용자의 승인 문장 원문(--note)이 필요합니다.")
    st = require_enabled(project)
    pk = get_pkg(st, a.id)
    if pk["status"] != "awaiting_final_approval":
        raise Blocked("invalid_transition", f"{pk['id']} 상태가 {pk['status']}입니다.")
    if any(norm_text(note) == norm_text(x["statement"]) for x in pk["contract_approvals"]):
        raise Blocked("approval_reused", "1차 계약 승인 문장을 최종 승인으로 재사용할 수 없습니다.")
    from pd_core import package_contract_valid
    if not package_contract_valid(project, dict(pk, id=pk["id"])):
        raise Blocked("contract_modified", "계약 파일이 승인 이후 바뀌었습니다.")
    try:
        fresh = final_bundle(project, dict(pk, status="executing"))
    except Blocked as e:
        raise Blocked("changed_since_final_submit", "제출 이후 조건이 바뀌었습니다. 다시 submit-final 합니다.", detail=e.payload)
    if digest(fresh) != pk["final"]["digest"]:
        raise Blocked("changed_since_final_submit", "최종 승인 묶음을 제출한 뒤 산출물·검증 결과가 바뀌었습니다. 다시 submit-final 합니다.")
    pk["final"].update(statement=note, at=now())
    pk["status"] = "finalizing"
    log(pk, "final_approved", digest=pk["final"]["digest"][:12])
    save(project, st)
    finalize(project, pk["id"])


def finalize(project: Path, pid: str) -> None:
    """각 Skill에 공식 기록. 모든 단계는 멱등이며 중간에 멈추면 다시 실행해 이어갑니다(finalizing 동안 공식 게이트 차단)."""
    st = require_enabled(project)
    pk = get_pkg(st, pid)
    if pk["status"] == "approved":
        emit({"ok": True, "id": pid, "status": "approved", "finalize": pk["finalize"]})
    if pk["status"] != "finalizing":
        raise Blocked("invalid_transition", f"{pid} 상태가 {pk['status']}입니다(최종 승인 후에만 finalize).")
    steps = []
    prop = (pk.get("planning") or {}).get("proposal")
    if prop and not (pk["finalize"].get("planning") or {}).get("done"):
        for _ in range(4):
            ps = planning_state(project)
            if ps["status"] == "approved" and ps["approved"].get("hashes") == prop["hashes"]:
                break
            sub_step = {"approved": "reopen", "in_progress": "submit", "awaiting_approval": "approve"}.get(ps["status"])
            if os.environ.get("PC_SIMULATE_FAIL_AT") == f"planning:{sub_step}":  # 테스트 전용: 이 하위 단계 직전에 중단된 것처럼
                save_step(project, pid, "planning", False, {"simulated_stop_before": sub_step})
                raise Blocked("finalize_failed", f"(시뮬레이션) 기획 {sub_step} 직전에 멈췄습니다. finalize를 다시 실행합니다.", step=f"planning:{sub_step}")
            if ps["status"] == "approved":
                code, out = run(PS, "reopen", "--project", project, "--stage", "planning", "--revision", ps["revision"], "--package", pid)
            elif ps["status"] == "in_progress":
                code, out = run(PS, "submit", "--project", project, "--stage", "planning", "--revision", prop["revision"], "--package", pid)
            elif ps["status"] == "awaiting_approval":
                code, out = run(PS, "approve", "--project", project, "--stage", "planning", "--revision", ps["revision"], "--package", pid)
            else:
                code, out = 2, {"error": "planning_state", "message": f"planning {ps['status']}"}
            steps.append({"planning": out.get("status") or out.get("error"), "code": code})
            if code != 0:
                save_step(project, pid, "planning", False, out)
                raise Blocked("finalize_failed", "기획 공식 기록 단계에서 멈췄습니다. 원인을 고친 뒤 finalize를 다시 실행합니다(이미 끝난 단계는 건너뜀).",
                              step="planning", detail=out)
        save_step(project, pid, "planning", True, None)
    for name, script, args in (("design", PD, ["change", "package-finalize", "--project", project, "--package", pid]),
                               ("build", PB, ["package-finalize", "--project", project, "--package", pid])):
        if (load(project)["packages"][pid]["finalize"].get(name) or {}).get("done"):
            continue
        if name == "design" and not (project / ".ai-workflow/design.json").is_file():
            save_step(project, pid, name, True, {"skipped": "design.json 없음"})
            continue
        if name == "build" and not (project / ".ai-workflow/build.json").is_file():
            save_step(project, pid, name, True, {"skipped": "build.json 없음"})
            continue
        if os.environ.get("PC_SIMULATE_FAIL_AT") == name:  # 테스트 전용 중단 주입
            save_step(project, pid, name, False, {"simulated_stop_before": name})
            raise Blocked("finalize_failed", f"(시뮬레이션) {name} 단계 직전에 멈췄습니다. finalize를 다시 실행합니다.", step=name)
        code, out = run(script, *args)
        steps.append({name: out.get("status") or out.get("error"), "code": code})
        if code != 0:
            save_step(project, pid, name, False, out)
            raise Blocked("finalize_failed", f"{name} 공식 기록 단계에서 멈췄습니다. 원인을 고친 뒤 finalize를 다시 실행합니다.", step=name, detail=out)
        save_step(project, pid, name, True, None)
    st = load(project)
    pk = st["packages"][pid]
    pk["status"] = "approved"
    pk["finalized_at"] = now()
    log(pk, "finalized")
    save(project, st)
    emit({"ok": True, "id": pid, "status": "approved", "steps": steps, "finalize": pk["finalize"],
          "next": "결과를 검토한 뒤 사용자가 커밋합니다(엔진은 커밋하지 않음)."})


def save_step(project: Path, pid: str, name: str, done: bool, detail) -> None:
    st = load(project)
    pk = st["packages"][pid]
    pk["finalize"][name] = {"done": done, "at": now(), **({"detail": detail} if detail else {})}
    save(project, st)


def cmd_finalize(project: Path, a) -> None:
    finalize(project, a.id)


def cmd_resume(project: Path, a) -> None:
    st = require_enabled(project)
    pk = get_pkg(st, a.id)
    if pk["status"] == "finalizing":
        return finalize(project, pk["id"])
    nxt = {"awaiting_contract_approval": "계약을 사용자에게 보여 주고 approve-contract", "escalated": "amend-contract → approve-contract",
           "awaiting_final_approval": "묶음을 보여 주고 approve-final", "approved": "완료", "abandoned": "취소됨"}.get(pk["status"])
    if pk["status"] == "executing":
        done = []
        if (pk.get("planning") or {}).get("proposal"):
            done.append("snapshot-planning")
        if design_package_cr(project, pk["id"]):
            done.append("design CR " + design_package_cr(project, pk["id"])["status"])
        if (pk.get("build") or {}).get("plan_proposal"):
            done.append("snapshot-plan")
        if (pk.get("regression") or {}).get("ok"):
            done.append("regression")
        nxt = {"done": done, "next": "남은 단계: " + ", ".join(x for x in ("snapshot-planning", "design", "snapshot-plan", "구현·verify", "regression", "submit-final")
                                                              if not any(x.split()[0] in d for d in done))}
    emit({"ok": True, "id": pk["id"], "status": pk["status"], "next": nxt})


def cmd_abandon(project: Path, a) -> None:
    st = require_enabled(project)
    pk = get_pkg(st, a.id)
    if pk["status"] in ("approved", "abandoned"):
        raise Blocked("invalid_transition", f"{pk['id']} 상태가 {pk['status']}입니다.")
    if pk["status"] == "finalizing":
        raise Blocked("finalizing", "finalize가 시작된 패키지는 취소하지 않습니다(일부 공식 기록이 있음). finalize를 다시 실행해 마무리합니다.")
    if not (a.reason or "").strip():
        raise Blocked("reason_required", "취소 사유(--reason)가 필요합니다.")
    ch = changed_since_open(project, pk)
    scope = scope_violations(project, pk)
    restored, skipped, conflicts = [], [], []
    if a.restore:
        for rel, (o, n) in ch.items():
            if rel.startswith(CHANGES_DIR + "/"):
                continue
            if rel in scope["out_of_scope"]:
                skipped.append({"file": rel, "why": "계약 범위 밖 변경(사용자 작업일 수 있음) — 복원하지 않음"})
                continue
            if rel in pk["base"]["dirty"]:
                pre = project / pk["base"]["backup_dir"] / rel
                if pk["base"]["dirty"][rel] is None:
                    skipped.append({"file": rel, "why": "패키지 시작 전 삭제돼 있던 파일 — 그대로 둠"})
                    continue
                if not pre.is_file() or sha256_file(pre) != pk["base"]["dirty"][rel]:
                    conflicts.append({"file": rel, "why": "시작 전 미커밋 내용의 보관본이 없거나 달라 안전하게 복원할 수 없음"})
                    continue
                data = pre.read_bytes()
            else:
                data = git_bytes(project, pk["base"]["commit"], rel)
                if data is None:
                    skipped.append({"file": rel, "why": "패키지가 새로 만든 파일 — 지우지 않음(사용자가 확인 후 정리)"})
                    continue
            restored.append(rel)
            p = project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".pc-restore.", suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        if conflicts:
            emit({"ok": False, "error": "restore_conflict", "message": "일부 파일을 안전하게 복원할 수 없어 패키지를 취소 상태로 바꾸지 않았습니다. 복원된 파일과 충돌 목록을 확인합니다.",
                  "restored": restored, "conflicts": conflicts, "skipped": skipped}, 2)
    cr = design_package_cr(project, pk["id"])
    design_cancel = None
    if cr and cr["status"] not in ("approved", "cancelled"):
        code, out = run(PD, "change", "cancel", "--project", project, "--id", cr["id"], "--reason", f"{pk['id']} 취소: {a.reason.strip()[:100]}")
        design_cancel = {"code": code, "result": out.get("status") or out.get("error")}
    st = load(project)
    pk = st["packages"][a.id]
    pk["status"] = "abandoned"
    log(pk, "abandoned", reason=a.reason.strip()[:200], restored=restored)
    save(project, st)
    emit({"ok": True, "id": pk["id"], "status": "abandoned", "restored": restored, "skipped": skipped, "design_cr_cancel": design_cancel,
          "kept_preexisting_uncommitted": sorted(pk["base"]["dirty"]),
          "note": "기존 승인 기록은 바뀐 적이 없습니다. 패키지 기준으로 한 Build 검증은 stale이 됩니다. 남은 파일 차이는 사용자가 검토합니다."})


def cmd_status(project: Path, a) -> None:
    st = load(project)
    if a.id:
        pk = get_pkg(st, a.id)
        emit({"ok": True, "package": pk})
    emit({"ok": True, "enabled": bool(st.get("enabled")), "packages": {k: {"status": v["status"], "purpose": v["contract"]["scope"].get("purpose")}
                                                                       for k, v in (st.get("packages") or {}).items()}})


def cmd_gate(project: Path, a) -> None:
    """공식 빌드·배포 게이트: 최종 승인·finalize가 끝나지 않은 패키지가 있으면 종료 2(미승인 산출물이 작업 트리에 있음)."""
    st = load(project) if (project / STATE_REL).is_file() else {}
    act = {k: v["status"] for k, v in (st.get("packages") or {}).items() if v["status"] in ACTIVE}
    if act:
        emit({"ok": False, "error": "package_pending", "message": "최종 승인·finalize가 끝나지 않은 변경 패키지가 있어 공식 빌드·배포를 막습니다.", "packages": act}, 2)
    emit({"ok": True, "message": "진행 중인 변경 패키지가 없습니다."})


def main() -> None:
    ap = argparse.ArgumentParser(description="/product-change helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cmds = {"enable": cmd_enable, "plan": cmd_plan, "open": cmd_open, "amend-contract": cmd_amend, "approve-contract": cmd_approve_contract,
            "snapshot-planning": cmd_snapshot_planning, "snapshot-plan": cmd_snapshot_plan, "review": cmd_review, "check": cmd_check,
            "regression": cmd_regression, "submit-final": cmd_submit_final, "approve-final": cmd_approve_final, "finalize": cmd_finalize,
            "resume": cmd_resume, "abandon": cmd_abandon, "status": cmd_status, "gate": cmd_gate}
    for name, fn in cmds.items():
        s = sub.add_parser(name)
        s.add_argument("--project", required=True)
        s.set_defaults(fn=fn)
        if name not in ("enable", "plan", "open", "gate"):
            s.add_argument("--id", required=name != "status")
        if name in ("enable",):
            s.add_argument("--confirm", action="store_true")
        if name in ("enable", "approve-contract", "approve-final"):
            s.add_argument("--note", default="")
        if name in ("open", "amend-contract"):
            s.add_argument("--contract", required=True)
        if name in ("amend-contract", "review", "abandon"):
            s.add_argument("--reason", default="")
        if name == "plan":
            s.add_argument("--ids")
        if name == "review":
            s.add_argument("--unit", required=True)
        if name == "abandon":
            s.add_argument("--restore", action="store_true")
        if name == "regression":  # 검증 단계가 요구하는 환경(예: test-pg)을 /product-build verify에 그대로 전달
            s.add_argument("--available", default="")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    try:
        a.fn(project, a)
    except Blocked as e:
        emit(e.payload, 2)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "error": "internal_error", "message": f"{type(e).__name__}: {e}"}, 1)


if __name__ == "__main__":
    main()
