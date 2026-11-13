"""/product-build ui-guard: 일상 개발(T0 스타일·문구, T1 버그 수정, T2 승인 명세 안 기능 추가)의 읽기 전용 UI 경량 검사.

원칙
- 배치·구현 계획·커밋이 없어도 실행합니다. 상태 파일·승인 문서·대응표를 쓰지 않습니다(Git index도 갱신하지 않도록 GIT_OPTIONAL_LOCKS=0).
- 전역 필수 검사(항상 오류): 기획 승인(require_planning), 디자인 수준 L2 이상, 토큰 정본 일치(token_check), 대응표 무결성(map_problems).
- 변경 파일 검사(기본): base(기본 HEAD) 이후 바뀐 파일만 봅니다. 이미 base에 있던 위반(레거시)은 따로 보고하고 실패시키지 않습니다.
  --path는 지정 파일, --all은 소스 전체를 봅니다(레거시 구분 없음).
- 일관된 스냅샷: 입력을 한 번 읽어 판정하고, 끝난 뒤 HEAD·변경 목록·내용 해시를 다시 읽어 같을 때만 결과를 냅니다(최대 3회).
- 브라우저 레이아웃 검증은 하지 않습니다(verify·프로젝트 브라우저 명령의 pb-ui-report/v1 몫).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from pathlib import Path

import pb_ui as U
from pb_core import (
    DESIGN_STATE_REL, PROFILE_REL, UISYS_FILE, WORKFLOW_STATE_REL, Blocked, block, design_info, digest, is_protected, sha256_bytes,
)
from pb_exec import in_patterns
from pb_scan import MAX_FILE_BYTES, is_test_path

GUARD_FORMAT = "pb-ui-guard/v1"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_ATTEMPTS = 3
UI_MAP_FILE = U.UI_MAP_REL
STATE_FILES = (WORKFLOW_STATE_REL, DESIGN_STATE_REL, ".ai-workflow/boilerplate.json", ".ai-workflow/discovery-notes.md",
               ".ai-workflow/design-notes.md", ".ai-workflow/backup/")
ENGINE_RECORDS = (".ai-workflow/build.json", ".ai-workflow/build/", "docs/build/")
EXPORT_RE = re.compile(r"\bexport\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Z][\w$]*)")
CMP_RE = re.compile(r"CMP-\d{3}")
# 컴포넌트처럼 보이는 내보내기: PascalCase 함수·클래스, 또는 함수·호출을 대입한 const(값·객체·문자열 상수는 제외)
COMPONENT_DECL_RE = re.compile(r"\bexport\s+(?:default\s+)?(?:function\s+([A-Z][A-Za-z0-9]*)\s*[(<]|class\s+([A-Z][A-Za-z0-9]*)\b"
                               r"|const\s+([A-Z][A-Za-z0-9]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(|function\b|[A-Za-z_$][\w$.]*\())")
# 화면·라우트·레이아웃 파일과 컴포넌트가 아닌 이름(오탐 줄이기). 이런 파일·이름은 component_outside_roots로 보지 않습니다.
PAGE_DIRS = {"pages", "page", "routes", "route", "app", "screens", "views", "layouts"}
PAGE_STEMS = {"page", "layout", "route", "index", "main", "app", "root"}
NON_COMPONENT_SUFFIX = ("Page", "Screen", "Route", "Routes", "Layout", "View", "Provider", "Context", "Store", "Service", "Client", "Api",
                        "Error", "Exception", "Schema", "Config", "Test", "Spec", "Mock", "Story", "Stories")
HINTS = {
    "protected_path_changed": ("T3", "승인 문서·프리뷰를 경량 경로에서 고치지 않습니다. 기획 변경은 /product-start, 디자인 변경은 /product-design impact로 재진입(T3·T4)"),
    "theme_changed": ("T4", "테마(정본) 변경은 디자인 시스템 변경입니다. /product-design impact --design → Design Direction 재승인"),
    "token_mismatch": ("T0", "토큰 CSS를 승인된 정본(expected_css)에 맞추거나, 값 자체를 바꾸려면 T4(/product-design impact --design)"),
    "token_check_failed": ("T4", "토큰 정본을 읽을 수 없습니다. /product-design·ui-map tokens 설정을 확인"),
    "design_not_current": ("T3", "디자인 승인이 현재 기준이 아닙니다. /product-design에서 rebase·재승인한 뒤 경량 개발을 계속합니다"),
    "map_integrity": ("T2", "대응표(ui-map)와 코드가 어긋났습니다. 부품을 되돌리거나 사용자 확인 후 ui-map register/remove"),
    "duplicate_component": ("T2", "이미 대응된 부품을 다시 만들지 말고 대응표의 부품을 재사용합니다"),
    "unregistered_component": ("T2", "기존 CMP 재사용을 먼저 검토하고, 새 부품이 맞으면 사용자 확인 후 ui-map register. 04에 없는 새 디자인 부품이면 T4"),
    "unknown_cmp_marker": ("T4", "승인된 04 문서에 없는 CMP입니다. 새 디자인 시스템 부품이면 /product-design 재진입"),
    "raw_value": ("T0", "직접 값 대신 승인된 토큰(CSS 변수 등)을 쓰거나, 프로젝트 허용 예외로 등록(ui-map except --audit-path)"),
    "possible_duplicate": ("T2", "대응된 부품과 이름이 같습니다. 재사용할 수 있는지 확인"),
    "component_outside_roots": ("T2", "공통으로 쓸 부품이면 기존 대응 부품 재사용을 먼저 검토하고, 새 공통 부품이면 component_roots에 두고 사용자 확인 후 ui-map register. 이 화면 전용 부품이면 그대로 두어도 됩니다"),
}


class GitError(Exception):
    pass


# ---------------------------------------------------------------- Git(읽기 전용, -z)
def git_z(project: Path, *args: str) -> list[str]:
    """NUL 구분 출력(한글·공백 경로 안전). 실패하면 GitError(빈 목록으로 통과시키지 않음). index를 갱신하지 않습니다."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    p = subprocess.run(["git", "-C", str(project), "-c", "core.quotepath=off", *args], capture_output=True, env=env)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return [x.decode("utf-8", "surrogateescape") for x in p.stdout.split(b"\0") if x]


def git_blob(project: Path, ref: str, rel: str) -> bytes | None:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    p = subprocess.run(["git", "-C", str(project), "cat-file", "blob", f"{ref}:./{rel}"], capture_output=True, env=env)
    return p.stdout if p.returncode == 0 else None


def resolve_base(project: Path, base: str) -> str:
    try:
        out = git_z(project, "rev-parse", "--verify", "-q", "--end-of-options", f"{base}^{{commit}}")
    except GitError:
        out = []
    if not out:
        block("bad_base", f"--base {base}를 커밋으로 해석할 수 없습니다.")
    return out[0].strip()


def git_changes(project: Path, base_sha: str) -> dict[str, dict]:
    """base 이후 바뀐 경로 → {status, state}. state: committed(base..HEAD 커밋) / staged / unstaged / both / untracked / deleted."""
    try:
        ns = git_z(project, "diff", "--name-status", "-z", "--no-renames", "--relative", base_sha)
        cached = set(git_z(project, "diff", "--cached", "--name-only", "-z", "--no-renames", "--relative", "HEAD"))
        work = set(git_z(project, "diff", "--name-only", "-z", "--no-renames", "--relative"))
        untracked = git_z(project, "ls-files", "-z", "--others", "--exclude-standard")
    except GitError as e:
        block("git_failed", f"Git 변경 목록을 읽지 못했습니다: {e}")
    out: dict[str, dict] = {}
    for i in range(0, len(ns) - 1, 2):
        st, rel = ns[i][:1], ns[i + 1]
        if st == "D":
            state = "deleted"
        elif rel in cached and rel in work:
            state = "both"
        elif rel in cached:
            state = "staged"
        elif rel in work:
            state = "unstaged"
        else:
            state = "committed"
        out[rel] = {"status": "added" if st == "A" else "deleted" if st == "D" else "modified", "state": state}
    for rel in untracked:
        out[rel] = {"status": "added", "state": "untracked"}
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- 분류
def _under(rel: str, prefixes) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in prefixes)


def roots_of(prof: dict, uprof: dict) -> list[str]:
    return [r.rstrip("/") + "/" for r in (uprof.get("component_roots") or prof["paths"].get("components") or [])]


def kind_of(rel: str, ctx: dict) -> str:
    if _under(rel, STATE_FILES):
        return "workflow_state"
    if rel == ctx["theme_file"]:
        return "theme"
    if is_protected(rel):
        return "protected"
    if _under(rel, ENGINE_RECORDS) or rel == PROFILE_REL:
        return "engine_record"
    if rel == ctx["token_file"]:
        return "token_output"
    parts = rel.split("/")
    if U.is_preview(rel) or any(x in parts for x in ctx["exclude"]) or not rel.endswith(ctx["exts"]) or is_test_path(rel):
        return "other"
    src = ctx["source"]
    if src and not in_patterns(rel, [s.rstrip("/") + "/" for s in src]):
        return "other"
    return "component" if any(rel.startswith(r) for r in ctx["roots"]) else "ui"


# ---------------------------------------------------------------- 스냅샷
def _read(project: Path, rel: str) -> tuple[str | None, str | None, str | None]:
    """(sha, text, skip_reason). 없음 → (None, None, None)."""
    p = project / rel
    if p.is_symlink():
        return "symlink", None, "심볼릭 링크"
    if not p.is_file():
        return None, None, None
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return f"size:{p.stat().st_size}", None, f"{MAX_FILE_BYTES}바이트 초과"
        data = p.read_bytes()
    except OSError as e:
        return "unreadable", None, f"읽기 실패({e})"
    return sha256_bytes(data), data.decode("utf-8", "replace"), None


def collect(project: Path, mode: str, base_sha: str | None, paths: list[str] | None, ctx: dict) -> dict:
    head = None
    if mode == "changed":
        try:
            head = git_z(project, "rev-parse", "--verify", "-q", "HEAD")[0]
        except (GitError, IndexError):
            block("git_failed", "HEAD를 읽지 못했습니다.")
        changes = git_changes(project, base_sha)
    elif mode == "path":
        changes = {}
        for rel in paths:
            rel = rel.replace("\\", "/")
            while rel.startswith("./"):
                rel = rel[2:]
            if U.bad_path(rel) or not (project / rel).is_file():
                block("path_not_found", f"--path {rel}: 저장소 안의 파일이 아닙니다.")
            changes[rel] = {"status": "specified", "state": "specified"}
    else:
        changes = {rel: {"status": "audit", "state": "all"} for rel in
                   U.walk(project, ctx["source"] or None, ctx["exclude"] + [U.PREVIEW_DIR], set(ctx["exts"]))}
    files, texts, skipped = {}, {}, []
    for rel, c in changes.items():
        sha, text, why = _read(project, rel)
        files[rel] = {**c, "kind": kind_of(rel, ctx), "sha": sha}
        if why:
            skipped.append({"path": rel, "reason": why})
        elif text is not None:
            texts[rel] = text
    inputs = {rel: _read(project, rel)[0] for rel in sorted({UI_MAP_FILE, ctx["token_file"] or "", ctx["theme_file"] or "",
                                                              DESIGN_STATE_REL, WORKFLOW_STATE_REL, UISYS_FILE, PROFILE_REL} - {""})}
    fp = digest({"head": head, "files": {k: [v["state"], v["sha"]] for k, v in files.items()}, "inputs": inputs})
    return {"head": head, "files": files, "texts": texts, "skipped": skipped, "inputs": inputs, "fingerprint": fp}



# ---------------------------------------------------------------- 판정
def component_decls(rel: str, text: str) -> set[str]:
    """컴포넌트 전용 폴더 밖 파일에서 새 컴포넌트로 보이는 내보내기 이름. 화면·라우트·레이아웃 파일, 상수·비컴포넌트 이름은 제외."""
    parts = rel.lower().split("/")
    if set(parts[:-1]) & PAGE_DIRS or Path(rel).stem.lower() in PAGE_STEMS or ".stories." in rel or ".story." in rel:
        return set()
    out = set()
    for m in COMPONENT_DECL_RE.finditer(text):
        name = next(g for g in m.groups() if g)
        if not name.isupper() and not name.endswith(NON_COMPONENT_SUFFIX):
            out.add(name)
    return out


def new_lines(base_text: str | None, text: str) -> set[int] | None:
    """base 대비 새로 생기거나 바뀐 줄 번호(1부터). base가 없으면 None(파일 전체가 새 것)."""
    if base_text is None:
        return None
    a, b = base_text.splitlines(), text.splitlines()
    out: set[int] = set()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out.update(range(j1 + 1, j2 + 1))
    return out


def evaluate(project: Path, snap: dict, mode: str, base_sha: str | None, ctx: dict, umap: dict, prof: dict, uprof: dict) -> dict:
    E: list[str] = []
    W: list[str] = []
    codes: set[str] = set()
    legacy: list[dict] = []
    info: list[str] = []

    def err(code, msg):
        E.append(f"[{code}] {msg}")
        codes.add(code)

    def warn(code, msg):
        W.append(f"[{code}] {msg}")
        codes.add(code)

    files, texts = snap["files"], snap["texts"]
    base_cache: dict[str, str | None] = {}

    def base_text(rel):
        if mode != "changed" or files[rel]["status"] == "added":
            return None
        if rel not in base_cache:
            b = git_blob(project, base_sha, rel)
            base_cache[rel] = b.decode("utf-8", "replace") if b is not None else None
        return base_cache[rel]

    # 1) 디자인 승인 수준(전역)
    dinfo = design_info(project)
    design = {"level": dinfo["level"], "current": dinfo["level"] in ("L2", "L3"), "reason": dinfo.get("reason"),
              "problems": dinfo.get("problems", [])}
    if not design["current"]:
        err("design_not_current", f"디자인 수준 {dinfo['level']}: {dinfo.get('reason')}. 경량 개발(T0~T2)은 L2 이상에서만 씁니다")
    for p in dinfo.get("problems", []):
        if p.get("kind") == "theme_changed":
            err("theme_changed", f"승인 이후 테마 파일이 바뀌었습니다: {', '.join(p.get('paths') or [])}")

    # 2) 보호 경로(변경 파일 모드만)
    approved = dict(ctx["approved_hashes"])
    protected = {"changed": [], "approved_change": [], "workflow_state": []}
    if mode == "changed":
        for rel, f in files.items():
            if f["kind"] == "theme" and "theme_changed" not in codes:
                # /product-design v2는 테마 값 변경을 프리뷰 재검증으로만 다룹니다(UX Spec·Design Direction 승인 유지).
                # 정본(theme)이 바뀌면 토큰 기준 자체가 바뀌므로 경량 경로에서는 허용하지 않습니다(T4).
                err("theme_changed", f"{rel}: 토큰 정본(테마)이 base 이후 바뀌었습니다({f['state']}). 디자인 시스템 변경은 /product-design 경로로 처리합니다")
            elif f["kind"] == "workflow_state":
                protected["workflow_state"].append(rel)
                warn("workflow_state_uncommitted", f"{rel}: 워크플로 상태 파일이 base 이후 바뀌었습니다(소유 Skill이 쓴 것인지 확인, 경량 경로에서 직접 고치지 않음)")
            elif f["kind"] == "protected":
                if f["sha"] and approved.get(rel) == f["sha"]:
                    protected["approved_change"].append(rel)
                    info.append(f"{rel}: 승인된 내용과 같습니다(승인 기록의 해시 일치)")
                elif U.is_preview(rel) and ctx["preview_status"] != "approved":
                    protected["changed"].append(rel)
                    warn("preview_changed", f"{rel}: 디자인 프리뷰는 /product-design 소유입니다(프리뷰 단계 {ctx['preview_status'] or '없음'}). 제품 코드에서 쓰지 않습니다")
                else:
                    protected["changed"].append(rel)
                    err("protected_path_changed", f"{rel}: 승인 문서·프리뷰가 승인 기록과 다르게 바뀌었습니다({f['state']})")

    # 3) 토큰 정본(전역, 항상 오류)
    try:
        tc = U.token_check(project, umap)
        for x in tc["missing"] + tc["mismatch"]:
            err("token_mismatch", f"{x['token']}: 승인값 {x['expected']}, 토큰 CSS {x.get('actual', '없음')}")
        for t in tc.get("stale_exceptions") or []:
            warn("stale_token_exception", f"{t}: 정본에 없는 토큰의 예외가 남아 있습니다")
        tokens = {k: tc.get(k) for k in ("ok", "source", "file", "counts", "missing", "mismatch", "excepted")}
    except Blocked as e:
        err("token_check_failed", f"{e.payload.get('error')}: {e.payload.get('message')}")
        tokens = {"ok": False, "error": e.payload.get("error")}

    # 4) 대응표 무결성(전역, 항상 오류)
    try:
        mp = U.map_problems(project, umap, None, None)
        for m in mp["errors"]:
            E.append(m)
        codes.update({"map_integrity"} if mp["errors"] else set())
        W += mp["warnings"]
        mapinfo = {"ok": mp["ok"], "counts": mp["counts"]}
    except Blocked as e:
        err("map_integrity", f"{e.payload.get('error')}: {e.payload.get('message')}")
        mapinfo = {"ok": False}

    # 5) 대상 파일: 직접 값·부품
    targets = [r for r, f in files.items() if f["kind"] in ("ui", "component") and r in texts]
    kinds, exc, amode = uprof["audit"]["kinds"], umap["exceptions"]["audit"], uprof["audit"]["mode"]
    aexts = tuple(uprof["audit"]["extensions"])
    audit = {"mode": amode, "kinds": kinds, "findings": [], "legacy": [], "excepted": []}
    for rel in targets:
        if not rel.endswith(aexts):
            continue
        found, excepted = U.audit_text(rel, texts[rel], kinds, exc)
        audit["excepted"] += excepted
        fresh = new_lines(base_text(rel), texts[rel])
        for x in found:
            (audit["findings"] if fresh is None or x["line"] in fresh else audit["legacy"]).append(x)
    for x in audit["findings"]:
        (err if amode == "block" else warn)("raw_value", f"{x['file']}:{x['line']} 직접 {x['kind']} 값 {x['value']}")
    legacy += [{"check": "raw_value", **x} for x in audit["legacy"]]

    comps = umap.get("components") or {}
    cmps04 = U.uisys_cmps(project)
    mapped_paths = {m.get("path") for m in comps.values() if m.get("path")}
    comp_out = {"unregistered": [], "reuse": {}, "duplicates": []}
    for rel in targets:
        bt = base_text(rel)
        if files[rel]["kind"] == "component" and rel not in mapped_paths:
            now_ex = set(EXPORT_RE.findall(texts[rel]))
            added = sorted(now_ex - set(EXPORT_RE.findall(bt or ""))) if mode == "changed" else sorted(now_ex)
            if mode != "changed" or files[rel]["status"] == "added" or added:
                comp_out["unregistered"].append({"file": rel, "exports": added or sorted(now_ex)})
                warn("unregistered_component", f"{rel}: 대응표에 없는 부품입니다(내보낸 이름: {', '.join(added or sorted(now_ex)) or '없음'})")
            else:
                legacy.append({"check": "unregistered_component", "file": rel})
        if files[rel]["kind"] == "ui" and ctx["roots"]:
            decl = component_decls(rel, texts[rel])
            fresh_decl = sorted(decl - (component_decls(rel, bt) if (mode == "changed" and bt) else set()))
            if fresh_decl:
                comp_out.setdefault("outside_roots", []).append({"file": rel, "exports": fresh_decl})
                warn("component_outside_roots", f"{rel}: 컴포넌트 전용 폴더({', '.join(ctx['roots'])}) 밖에서 새 컴포넌트로 보이는 내보내기({', '.join(fresh_decl)})")
        uses = sorted(c for c, m in comps.items() if m.get("export") and m.get("path") != rel
                      and re.search(rf"(?<![\w$]){re.escape(m['export'])}(?![\w$])", texts[rel]))
        if uses:
            comp_out["reuse"][rel] = uses
        markers_now = set(CMP_RE.findall(texts[rel]))
        markers_old = set(CMP_RE.findall(bt or "")) if mode == "changed" else set()
        for c in sorted(markers_now - set(cmps04)):
            if c in markers_old:
                legacy.append({"check": "unknown_cmp_marker", "file": rel, "cmp": c})
            else:
                warn("unknown_cmp_marker", f"{rel}: 승인된 04 문서에 없는 {c} 표지")
    dup, de, dw = U.duplicate_findings(project, targets, comps, texts)
    old_dup = set()
    if mode == "changed":
        old_texts = {r: base_text(r) for r in targets if base_text(r) is not None}
        od, _, odw = U.duplicate_findings(project, list(old_texts), comps, old_texts)
        old_dup = {(x["file"], x["cmp"]) for x in od}
        old_dw = set(odw)
    else:
        old_dw = set()
    for x, m in zip(dup, [e for e in de]):
        if (x["file"], x["cmp"]) in old_dup:
            legacy.append({"check": "duplicate_component", **x})
        else:
            comp_out["duplicates"].append(x)
            E.append(m)
            codes.add("duplicate_component")
    for m in dw:
        if m in old_dw:
            legacy.append({"check": "possible_duplicate", "message": m})
        else:
            W.append(m)
            codes.add("possible_duplicate")

    for rel, f in files.items():
        if f["state"] == "both" and f["kind"] in ("ui", "component", "token_output"):
            warn("staged_differs", f"{rel}: stage된 뒤 다시 수정되었습니다. 검사는 작업 트리 내용 기준입니다(커밋될 내용과 다를 수 있음)")
    for s in snap["skipped"]:
        warn("skipped_file", f"{s['path']}: 검사하지 않음({s['reason']})")
    return {"errors": E, "warnings": W, "codes": codes, "legacy": legacy, "info": info, "design": design, "protected": protected,
            "tokens": tokens, "audit": {**audit, "counts": {k: len(audit[k]) for k in ("findings", "legacy", "excepted")}},
            "map": mapinfo, "components": comp_out}


def context(project: Path, prof: dict, uprof: dict, umap: dict, gate: dict) -> dict:
    try:
        dst = json.loads((project / DESIGN_STATE_REL).read_text(encoding="utf-8")) if (project / DESIGN_STATE_REL).exists() else {}
    except json.JSONDecodeError:
        dst = {}
    approved = {k: v for k, v in (gate.get("planning_hashes") or {}).items() if v}
    for s in (dst.get("stages") or {}).values():
        if (s or {}).get("status") == "approved" and isinstance(s.get("approved"), dict):
            approved.update({k: v for k, v in (s["approved"].get("hashes") or {}).items() if isinstance(v, str)})
    return {"theme_file": (dst.get("config") or {}).get("theme_file"), "token_file": ((umap.get("tokens") or {}).get("file")),
            "preview_status": ((dst.get("stages") or {}).get("preview") or {}).get("status"), "approved_hashes": approved,
            "roots": roots_of(prof, uprof), "source": list(prof["paths"].get("source") or []),
            "exclude": list(prof["paths"].get("exclude") or []) + ["node_modules", "dist", ".git"],
            "exts": tuple(sorted(set(uprof["audit"]["extensions"])))}  # UI 파일 = 프로필 [ui.audit].extensions(기본: 스타일·스크립트·마크업)


def run_guard(project: Path, mode: str, base: str, paths: list[str] | None, strict: bool, prof: dict, uprof: dict, umap: dict,
              gate: dict, _between=None) -> tuple[dict, int]:
    """판정 + 일관된 스냅샷. _between(attempt)는 테스트용(판정과 재확인 사이에 호출)."""
    base_sha = None
    if mode == "changed":
        base_sha = resolve_base(project, base)
    ctx = context(project, prof, uprof, umap, gate)
    unstable: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        snap = collect(project, mode, base_sha, paths, ctx)
        res = evaluate(project, snap, mode, base_sha, ctx, umap, prof, uprof)
        if _between:
            _between(attempt)
        again = collect(project, mode, base_sha, paths, ctx)
        if again["fingerprint"] == snap["fingerprint"]:
            break
        a, b = snap["files"], again["files"]
        unstable = sorted({k for k in set(a) | set(b) if (a.get(k) or {}).get("sha") != (b.get(k) or {}).get("sha")}
                          | {k for k in set(snap["inputs"]) if snap["inputs"][k] != again["inputs"].get(k)}
                          | ({"HEAD"} if snap["head"] != again["head"] else set()))
    else:
        block("snapshot_unstable", f"검사하는 동안 파일이 계속 바뀌었습니다({MAX_ATTEMPTS}회). 다른 세션의 작업이 끝난 뒤 다시 실행하세요.",
              paths=unstable[:50])
    ok = not res["errors"] and not (strict and res["warnings"])
    error = None if ok else ("design_not_current" if "design_not_current" in res["codes"] else "guard_failed")
    hints = [{"code": c, "type": HINTS[c][0], "next": HINTS[c][1]} for c in sorted(res["codes"]) if c in HINTS]
    out = {"format": GUARD_FORMAT, "ok": ok, **({"error": error} if error else {}), "mode": mode, "strict": strict,
           "base": {"ref": base, "sha": base_sha, "head": snap["head"]} if mode == "changed" else None,
           "snapshot": {"digest": snap["fingerprint"][:16], "attempts": attempt},
           "design": res["design"],
           "files": [{"path": k, **{x: v[x] for x in ("state", "status", "kind")}} for k, v in snap["files"].items()],
           "checks": {"protected": res["protected"], "tokens": res["tokens"], "audit": res["audit"], "map": res["map"],
                      "components": res["components"]},
           "errors": res["errors"], "warnings": res["warnings"], "info": res["info"],
           "legacy": {"count": len(res["legacy"]), "items": res["legacy"][:200],
                      "note": "base에 이미 있던 위반입니다. 이번 변경을 실패시키지 않습니다(--all로 전체 감사)."} if mode == "changed" else None,
           "route_hint": hints,
           "counts": {"files": len(snap["files"]), "checked": sum(1 for v in snap["files"].values() if v["kind"] in ("ui", "component")),
                      "errors": len(res["errors"]), "warnings": len(res["warnings"]), "legacy": len(res["legacy"])},
           "browser": {"status": "not_run", "note": "모바일·PC 레이아웃(overflow·잘림·터치 영역·콘솔·접근성)은 verify 또는 프로젝트 브라우저 명령(pb-ui-report/v1)에서 확인합니다."},
           "read_only": True}
    return out, 0 if ok else 2
