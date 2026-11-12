"""/product-build 배치 실행(M2.2): 잠금·시작 기준선·변경 분류·체크포인트·재시도 계산.

역할: Claude가 코드를 쓰고, 이 모듈은 상태·범위·잠금·체크포인트만 판정합니다. 검증 완료·승인은 기록하지 않습니다(M2.3·M2.4).

변경 판정의 기준은 배치 시작 때의 Git HEAD와 그때의 미커밋 파일 해시(base)입니다.
- 각 경로의 상태 = 'base HEAD와 같음'(BASE) 또는 현재 파일 해시(삭제면 None).
- base 이후 바뀐 경로 = 지금 상태가 시작 때 상태와 다른 경로. 체크포인트는 그 시점의 상태 묶음입니다.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import socket
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pb_core import BUILD_DIR_REL, STATE_REL, block, digest, is_protected, now, sha_file, write_owned
from pb_scan import is_test_path

LOCK_REL = f"{BUILD_DIR_REL}/lock.json"
RUNS_REL = f"{BUILD_DIR_REL}/runs"
EVIDENCE_REL = f"{BUILD_DIR_REL}/evidence"
BASE = "BASE"  # 시작 때 HEAD와 같은 내용
OWNED_PREFIXES = (STATE_REL, BUILD_DIR_REL + "/", "docs/build/")
GITIGNORE_LINES = ("evidence/", "*.log", "runs/", "lock.json")
DONE_LIKE = ("implemented", "verifying", "verified", "awaiting_approval", "approved")
DEP_LEVELS = {"implemented": DONE_LIKE + ("verify_failed", "stale"), "verified": ("verified", "awaiting_approval", "approved"), "approved": ("approved",)}
WEAKEN_RE = re.compile(r"\.(skip|only)\s*\(|\bx(it|describe|test)\s*\(|\b(it|test)\.todo\s*\(|@pytest\.mark\.(skip|xfail)|pytest\.skip\s*\(|"
                       r"\bt\.Skip\s*\(|@Disabled\b|@Ignore\b|\bskip\s*=\s*True|@unittest\.(skip\w*|expectedFailure)|\.skipTest\s*\(")


# ---------------------------------------------------------------- Git·파일
def git(project: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def head_sha(project: Path) -> str:
    return git(project, "rev-parse", "HEAD").strip()


def _ignored(rel: str, exclude: list[str]) -> bool:
    if rel == STATE_REL or any(rel.startswith(p) for p in OWNED_PREFIXES if p.endswith("/")):
        return True
    parts = rel.split("/")
    return any(x in parts for x in exclude)


def changed_vs(project: Path, base_head: str, exclude: list[str]) -> dict[str, str | None]:
    """base HEAD와 내용이 다른 경로 → 현재 해시(삭제면 None). 추적 파일 변경(커밋 포함)과 무시되지 않은 새 파일."""
    paths = set(x for x in git(project, "diff", "--name-only", base_head).splitlines() if x)
    paths |= set(x for x in git(project, "ls-files", "--others", "--exclude-standard").splitlines() if x)
    return {p: sha_file(project / p) for p in sorted(paths) if not _ignored(p, exclude)}


def states_now(project: Path, run: dict, exclude: list[str]) -> dict[str, str | None]:
    """시작 이후 상태가 달라진 경로 → 지금 상태(BASE 또는 해시/None)."""
    base = run["base"]["dirty"]
    cur = changed_vs(project, run["base"]["head"], exclude)
    out = {}
    for p in set(base) | set(cur):
        now_state = cur[p] if p in cur else BASE
        if now_state != base.get(p, BASE):
            out[p] = now_state
    return dict(sorted(out.items()))


def diff_states(old: dict, new: dict) -> list[str]:
    return sorted(p for p in set(old) | set(new) if old.get(p, "UNCHANGED") != new.get(p, "UNCHANGED"))


# ---------------------------------------------------------------- 범위
def glob_re(pat: str) -> re.Pattern:
    pat = pat.strip()
    if pat.startswith("./"):
        pat = pat[2:]
    if pat.endswith("/"):
        return re.compile(re.escape(pat) + ".*")
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile(out + "$")


def in_patterns(rel: str, pats: list[str]) -> bool:
    return any(glob_re(p).match(rel) for p in pats or [])


def pattern_problems(pats) -> list[str]:
    errs = []
    if not isinstance(pats, list):
        return ["목록이어야 합니다"]
    for p in pats:
        if not isinstance(p, str) or not p.strip():
            errs.append(f"빈 패턴: {p!r}")
            continue
        if p.startswith("/") or ".." in p.split("/"):
            errs.append(f"저장소 밖을 가리킴: {p}")
        probe = p.replace("**", "x").replace("*", "x").rstrip("/") + ("/x" if p.endswith("/") else "")
        if is_protected(probe) or is_protected(p.rstrip("/") + "/"):
            errs.append(f"보호 경로(다른 Skill의 상태·승인 문서·프리뷰)를 포함: {p}")
        if _ignored(probe, []):
            errs.append(f"/product-build 상태 경로를 포함: {p}")
        if p.strip() in ("**", "*", "**/*", "./"):
            errs.append(f"저장소 전체를 허용하는 패턴은 쓸 수 없음: {p}")
    return errs


# ---------------------------------------------------------------- 테스트 변경 분석
def _base_content(project: Path, run: dict, rel: str) -> str | None:
    base = run["base"]
    if rel in base["dirty"]:
        if base["dirty"][rel] is None:
            return None
        cp = project / RUNS_REL / run["batch"] / "base" / rel
        return cp.read_text(encoding="utf-8", errors="replace") if cp.exists() else None
    p = subprocess.run(["git", "-C", str(project), "show", f"{base['head']}:{rel}"], capture_output=True)
    return p.stdout.decode("utf-8", errors="replace") if p.returncode == 0 else None


def test_change(project: Path, run: dict, rel: str) -> dict | None:
    """시작 때 있던 테스트 파일의 변경 분류: deleted / weakened / modified(기존 줄 변경·삭제) / appended(추가만 → 확인 불필요)."""
    if not is_test_path(rel):
        return None
    old = _base_content(project, run, rel)
    if old is None:
        return None  # 새 테스트 파일
    p = project / rel
    if not p.exists():
        return {"path": rel, "kind": "deleted", "needs_confirmation": True}
    new = p.read_text(encoding="utf-8", errors="replace")
    removed, added = [], []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("-") and line[1:].strip():
            removed.append(line[1:].strip())
        elif line.startswith("+"):
            added.append(line[1:])
    weak = [a.strip() for a in added if WEAKEN_RE.search(a)]
    if weak:
        return {"path": rel, "kind": "weakened", "needs_confirmation": True, "evidence": weak[:5], "removed_lines": len(removed)}
    if removed:
        return {"path": rel, "kind": "modified", "needs_confirmation": True, "removed_lines": len(removed), "sample": removed[:3]}
    return {"path": rel, "kind": "appended", "needs_confirmation": False}


# ---------------------------------------------------------------- 분류
def classify(project: Path, run: dict, paths: list[str], allow: list[str], shared: list[str]) -> dict:
    out = {"protected": [], "base_conflict": [], "in_scope": [], "out_of_scope": [], "test_changes": []}
    for p in paths:
        if is_protected(p):
            out["protected"].append(p)
            continue
        if p in run["base"]["dirty"] and p not in run["base"].get("dirty_in_scope_accepted", []):
            out["base_conflict"].append(p)
        elif in_patterns(p, allow) or in_patterns(p, shared):
            out["in_scope"].append(p)
        else:
            out["out_of_scope"].append(p)
        tc = test_change(project, run, p)
        if tc and tc["kind"] != "appended":
            out["test_changes"].append(tc)
    return out


# ---------------------------------------------------------------- 잠금
def read_lock(project: Path):
    p = project / LOCK_REL
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("lock_id") else "corrupt"
    except (json.JSONDecodeError, OSError):
        return "corrupt"


def acquire_lock(project: Path, batch: str, owner: str) -> dict:
    p = project / LOCK_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    t = now()
    data = {"lock_id": uuid.uuid4().hex[:12], "batch": batch, "owner": owner or "unknown", "pid": os.getpid(),
            "host": socket.gethostname(), "created_at": t, "heartbeat_at": t}
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)  # 원자적 생성: 동시에 둘이 잡을 수 없음
    except FileExistsError:
        cur = read_lock(project)
        block("lock_held", "다른 배치 실행이 잠금을 갖고 있습니다(저장소당 활성 배치 1개). 덮어쓰지 않았습니다.", lock=cur)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return data


def heartbeat(project: Path, lock: dict) -> None:
    lock["heartbeat_at"] = now()
    write_owned(project, LOCK_REL, json.dumps(lock, ensure_ascii=False, indent=2) + "\n")


def release_lock(project: Path, lock_id: str) -> None:
    cur = read_lock(project)
    if isinstance(cur, dict) and cur.get("lock_id") == lock_id:
        (project / LOCK_REL).unlink()


def require_lock(project: Path, batch: str, lock_id: str | None) -> dict:
    cur = read_lock(project)
    if cur is None:
        block("lock_missing", "실행 잠금이 없습니다(중단됐거나 정리됨). resume으로 상태를 확인하고 다시 잡으세요.")
    if cur == "corrupt":
        block("lock_corrupt", "잠금 파일을 읽을 수 없습니다. 자동으로 지우지 않습니다. resume --take-over 절차로 복구하세요.")
    if not lock_id or cur["lock_id"] != lock_id or cur["batch"] != batch:
        block("lock_mismatch", "이 실행의 잠금이 아닙니다(다른 세션이 실행 중일 수 있음). 덮어쓰지 않았습니다.",
              lock={k: cur.get(k) for k in ("batch", "owner", "host", "created_at", "heartbeat_at")})
    return cur


def lock_age_minutes(lock: dict) -> float:
    try:
        t = datetime.strptime(lock["heartbeat_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60
    except (KeyError, ValueError):
        return float("inf")


# ---------------------------------------------------------------- 체크포인트
def cp_paths(project: Path, batch: str) -> tuple[Path, Path]:
    d = project / RUNS_REL / batch
    return d / "checkpoint.json", d / "checkpoint.prev.json"


def write_checkpoint(project: Path, run: dict, tasks: dict, states: dict, note: str = "") -> dict:
    cur, prev = cp_paths(project, run["batch"])
    seq = (run.get("checkpoint") or {}).get("seq", -1) + 1
    body = {"batch": run["batch"], "seq": seq, "at": now(), "tasks": {k: v["status"] for k, v in tasks.items()},
            "states": states, "note": note}
    body["digest"] = digest({k: v for k, v in body.items() if k != "digest"})
    if cur.exists():
        write_owned(project, str(prev.relative_to(project)), cur.read_text(encoding="utf-8"))
    write_owned(project, str(cur.relative_to(project)), json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    ptr = {"seq": seq, "at": body["at"], "digest": body["digest"]}
    run["checkpoint"] = ptr
    return body


def load_checkpoint(project: Path, run: dict, which: str = "current") -> tuple[dict | None, str | None]:
    """(체크포인트, 문제). 문제: missing / unreadable / digest_mismatch / pointer_mismatch."""
    cur, prev = cp_paths(project, run["batch"])
    p = cur if which == "current" else prev
    if not p.exists():
        return None, "missing"
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, "unreadable"
    if not isinstance(body, dict) or body.get("digest") != digest({k: v for k, v in body.items() if k != "digest"}):
        return None, "digest_mismatch"
    if which == "current" and (run.get("checkpoint") or {}).get("digest") != body["digest"]:
        return None, "pointer_mismatch"
    return body, None


def save_base_tests(project: Path, run: dict) -> None:
    """시작 때 미커밋 상태였던 테스트 파일의 내용을 보관(테스트 약화 판정 기준). Git 제외 경로(runs/)에 둡니다."""
    for rel, h in run["base"]["dirty"].items():
        if h and is_test_path(rel) and (project / rel).is_file():
            write_owned(project, f"{RUNS_REL}/{run['batch']}/base/{rel}", (project / rel).read_text(encoding="utf-8", errors="replace"))


def ensure_gitignore(project: Path) -> None:
    p = project / BUILD_DIR_REL / ".gitignore"
    text = p.read_text(encoding="utf-8") if p.exists() else "# /product-build 실행 산출물(Git 제외)\n"
    missing = [x for x in GITIGNORE_LINES if x not in text.split()]
    if missing:
        write_owned(project, f"{BUILD_DIR_REL}/.gitignore", text.rstrip("\n") + "\n" + "\n".join(missing) + "\n")


def task_order(plan_batch: dict) -> list[dict]:
    return [t for t in plan_batch.get("tasks") or [] if isinstance(t, dict)]


def next_task(tasks: dict, order: list[dict]) -> dict | None:
    for t in order:
        s = tasks.get(t["id"], {}).get("status")
        if s != "done" and all(tasks.get(d, {}).get("status") == "done" for d in t.get("depends_on") or [] if d in tasks):
            return {"id": t["id"], "layer": t.get("layer"), "title": t.get("title"), "refs": t.get("refs", []),
                    "depends_on": t.get("depends_on", []), "status": s}
    return None
