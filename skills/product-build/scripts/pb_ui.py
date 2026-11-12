"""/product-build M3.1·M3.2: UI 대응표(CMP ↔ 코드 부품), 토큰 대응 검사, UI Brief 생성, UI Plan 검증.

- 엔진은 프레임워크·UI 라이브러리를 모릅니다. 파일 경로, 내보낸 이름(문자열), ID, CSS 변수, 프로젝트 명령의 JSON 출력만 다룹니다.
- 대응표 `docs/build/ui-map.json`은 프로젝트 소유 기록입니다. 이 Skill의 명령(`ui-map ...`)으로만 바꿉니다.
- UI Brief(`.ai-workflow/build/ui/<배치>/brief.json`)는 엔진이 승인 문서에서 파생합니다. 직접 고치지 않습니다.
- UI Plan(`.ai-workflow/build/ui/<배치>/plan.json`)은 Claude가 작성하고 `ui-plan-validate`가 검사합니다.
- 디자인 프리뷰(`design-preview/`)는 시각 참고만 합니다. 제품 코드·대응표·토큰 출력·UI Plan이 프리뷰 경로를 쓰면 거부합니다.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path

from pb_core import (
    DD_FILE, DESIGN_STATE_REL, PLAN_JSON_REL, SCREENS_FILE, TRACE_FILE, UISYS_FILE, blocks_by_heading, block, digest, field_line,
    is_protected, now, read_text, screen_info, sha_file, strip_fences, write_owned,
)
from pb_exec import in_patterns
from pb_scan import DEFAULT_EXCLUDE, MAX_FILE_BYTES, NON_SOURCE_TOP, TEXT_EXT, is_test_path

# /product-design의 읽기 전용 함수(토큰 표·CSS 변수·테마 계약 해석). 상태를 쓰는 함수는 가져오지 않습니다(tests가 검사).
from pd_theme import css_var_name, parse_css_vars, parse_tokens, read_theme, theme_check  # noqa: E402

PD_THEME_IMPORTS = ("css_var_name", "parse_css_vars", "parse_tokens", "read_theme", "theme_check")

UI_MAP_REL = "docs/build/ui-map.json"
UI_MAP_FORMAT = "pb-ui-map/v1"
UI_DIR_REL = ".ai-workflow/build/ui"
BRIEF_FORMAT = "pb-ui-brief/v1"
PLAN_FORMAT = "pb-ui-plan/v1"
PREVIEW_DIR = "design-preview"
SOURCES = ("existing", "library", "built")
STATE_HOW = ("route", "query", "prop", "story", "test", "other")
DATA_SOURCES = ("api", "mock", "local", "props")
TOKEN_FORMATS = ("css-vars", "command")
AUDIT_KINDS = ("color", "length")
STARTED = ("in_progress", "paused", "failed", "implemented", "verifying", "verified", "verify_failed", "stale", "awaiting_approval",
           "approved", "imported")
DONE = ("implemented", "verified", "verify_failed", "stale", "approved", "imported")

# 프로필 [ui] 기본값(엔진 기본값은 형식만 정합니다. 프레임워크·값 기준 없음)
UI_PROFILE_DEFAULT = {
    "framework": "",            # 자유 텍스트(기록용). 엔진은 해석하지 않습니다.
    "component_roots": [],      # 비어 있으면 paths.components
    "api_contract": "",         # 선택: 계약 파일 경로(OpenAPI·타입 파일 등). 있으면 UI Plan의 contract 문자열을 이 파일에서 찾습니다.
    "audit": {"mode": "warn", "kinds": ["color"],
              "extensions": [".css", ".scss", ".sass", ".less", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte", ".html"]},
}

COLOR_RE = re.compile(r"(#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|\b(?:rgb|rgba|hsl|hsla)\([^)]*\))")
LENGTH_RE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?px)\b")


# ---------------------------------------------------------------- 공통
def walk(project: Path, roots: list[str] | None, exclude: list[str] | None, exts) -> list[str]:
    """소스 파일 목록. 확장자는 호출자가 정합니다(프로필 [ui.audit].extensions ∪ scan 기본). 문서·상태·프리뷰 최상위는 제외."""
    ex = DEFAULT_EXCLUDE | set(exclude or [])
    exts = set(exts)
    out, seen = [], set()
    for start in ([project / r for r in roots] if roots else [project]):
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
                if e.name in ex or e.is_symlink() or rel.split("/")[0] in NON_SOURCE_TOP:
                    continue
                if e.is_dir():
                    stack.append(e)
                elif e.suffix in exts and rel not in seen:
                    try:
                        if e.stat().st_size <= MAX_FILE_BYTES:
                            out.append(rel)
                            seen.add(rel)
                    except OSError:
                        pass
    return sorted(out)


def code_exts(uprof: dict) -> set[str]:
    return set(TEXT_EXT) | set(uprof["audit"].get("extensions") or [])


def ui_profile(prof: dict) -> tuple[dict, list[str]]:
    raw = prof.get("ui") or {}
    out = json.loads(json.dumps(UI_PROFILE_DEFAULT))
    errs = []
    if not isinstance(raw, dict):
        return out, ["ui는 표(table)여야 합니다"]
    for k, v in raw.items():
        if k == "audit" and isinstance(v, dict):
            out["audit"].update(v)
        else:
            out[k] = v
    if not isinstance(out["component_roots"], list):
        errs.append("ui.component_roots는 목록이어야 합니다")
    if not isinstance(out["api_contract"], str):
        errs.append("ui.api_contract는 문자열(경로)이어야 합니다")
    au = out["audit"]
    if au.get("mode") not in ("warn", "block"):
        errs.append("ui.audit.mode는 warn 또는 block이어야 합니다")
    if not isinstance(au.get("kinds"), list) or any(k not in AUDIT_KINDS for k in au.get("kinds", [])):
        errs.append(f"ui.audit.kinds는 {'/'.join(AUDIT_KINDS)}의 목록이어야 합니다")
    if not isinstance(au.get("extensions"), list):
        errs.append("ui.audit.extensions는 목록이어야 합니다")
    return out, errs


def norm(v: str) -> str:
    v = re.sub(r"\s+", " ", str(v).strip()).lower()
    m = re.fullmatch(r"#([0-9a-f])([0-9a-f])([0-9a-f])", v)
    return f"#{m.group(1) * 2}{m.group(2) * 2}{m.group(3) * 2}" if m else v


def bad_path(rel: str) -> bool:
    return not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts


def is_preview(rel: str) -> bool:
    rel = (rel or "").replace("\\", "/").lstrip("./")
    return rel == PREVIEW_DIR or rel.startswith(PREVIEW_DIR + "/")


def export_found(project: Path, rel: str, name: str) -> bool:
    p = project / rel
    if not p.is_file():
        return False
    try:
        return re.search(rf"(?<![\w$]){re.escape(name)}(?![\w$])", p.read_text(encoding="utf-8", errors="replace")) is not None
    except OSError:
        return False


def uisys_cmps(project: Path) -> dict[str, dict]:
    text = strip_fences(read_text(project, UISYS_FILE))
    out = {}
    for k, b in blocks_by_heading(text, 3, "CMP").items():
        out[k] = {"name": re.sub(r"^###\s+CMP-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip(),
                  **{key: field_line(b, label) for key, label in (("purpose", "용도"), ("variants", "변형"), ("states", "상태"),
                                                                 ("used_in", "사용 화면"), ("a11y", "접근성"))}}
    return out


# ---------------------------------------------------------------- 대응표(M3.1)
def empty_map() -> dict:
    return {"format": UI_MAP_FORMAT, "components": {}, "tokens": None, "exceptions": {"tokens": [], "audit": [], "log": []}, "history": []}


def load_map(project: Path) -> dict | None:
    p = project / UI_MAP_REL
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("ui_map_invalid", f"{UI_MAP_REL}을 JSON으로 읽을 수 없습니다: {e}. 자동으로 고치지 않습니다.")
    if not isinstance(d, dict) or d.get("format") != UI_MAP_FORMAT:
        block("ui_map_invalid", f"{UI_MAP_REL}의 format이 {UI_MAP_FORMAT}가 아닙니다. 자동으로 고치지 않습니다.")
    d.setdefault("components", {}); d.setdefault("tokens", None); d.setdefault("history", [])
    ex = d.setdefault("exceptions", {}); ex.setdefault("tokens", []); ex.setdefault("audit", []); ex.setdefault("log", [])
    return d


def save_map(project: Path, d: dict, event: str, note: str = "") -> None:
    d["history"].append({"at": now(), "event": event, "note": note[:300]})
    write_owned(project, UI_MAP_REL, json.dumps(d, ensure_ascii=False, indent=2) + "\n")


def batches_by_id(plan: dict | None) -> dict:
    return {b["id"]: b for b in (plan or {}).get("batches", []) if isinstance(b, dict) and b.get("id")}


def dep_closure(plan: dict, bid: str) -> list[str]:
    bs, seen, stack = batches_by_id(plan), [], list(batches_by_id(plan).get(bid, {}).get("depends_on") or [])
    while stack:
        x = stack.pop()
        if x in seen or x not in bs:
            continue
        seen.append(x)
        stack += bs[x].get("depends_on") or []
    return seen


def comp_list(b: dict, key: str) -> list[str]:
    return [c for c in ((b.get("components") or {}).get(key) or []) if isinstance(c, str)]


def plan_conflicts(umap: dict | None, plan: dict | None) -> list[str]:
    """계획 검증에 더하는 대응표 대조 오류(대응표가 있을 때만). 이미 대응된 부품을 다시 새로 만드는 계획을 막습니다."""
    if not umap or not plan:
        return []
    errs = []
    comps = umap.get("components") or {}
    for b in batches_by_id(plan).values():
        for c in comp_list(b, "new"):
            m = comps.get(c)
            if not m:
                continue
            if m.get("source") in ("existing", "library"):
                errs.append(f"[cmp_already_mapped] {b['id']}이 {c}를 새로 만들려 하지만 대응표에 기존 부품({m.get('path') or m.get('package')} · {m.get('export')})이 있습니다. components.reuse로 옮기세요")
            elif m.get("source") == "built" and m.get("built_by") != b["id"]:
                errs.append(f"[cmp_already_mapped] {c}는 {m.get('built_by')}가 이미 만들었습니다({m.get('path')}). {b['id']}는 재사용해야 합니다")
    return errs


def map_problems(project: Path, umap: dict, plan: dict | None, st: dict | None, batch: str | None = None, exts=None) -> dict:
    """대응표 자체 검사 + 계획·배치 상태 대조 + (배치 지정 시) 코드 중복 탐지."""
    E, W = [], []
    cmps04 = uisys_cmps(project)
    comps = umap.get("components") or {}
    by_part: dict[tuple, list[str]] = {}
    for c, m in sorted(comps.items()):
        if c not in cmps04:
            E.append(f"[unknown_cmp] {c}: 승인된 04 문서에 없는 컴포넌트입니다(폐기되었거나 오타)")
        src = m.get("source")
        if src not in SOURCES:
            E.append(f"[map_format] {c}: source는 {'/'.join(SOURCES)} 중 하나여야 합니다")
            continue
        if not m.get("export"):
            E.append(f"[map_format] {c}: export(코드에서 쓰는 이름)가 필요합니다")
        path = m.get("path")
        if src == "library":
            if not m.get("package"):
                E.append(f"[map_format] {c}: library 부품은 package가 필요합니다")
        elif bad_path(path):
            E.append(f"[map_format] {c}: path는 저장소 안 상대 경로여야 합니다")
            continue
        if path:
            if is_preview(path):
                E.append(f"[preview_reuse] {c}: {path}는 디자인 프리뷰입니다. 프리뷰 코드는 제품 코드로 재사용하지 않습니다(시각 참고만)")
            elif is_protected(path):
                E.append(f"[protected_path] {c}: {path}는 다른 Skill의 보호 경로입니다")
            elif not (project / path).is_file():
                E.append(f"[path_missing] {c}: {path}가 없습니다")
            elif m.get("export") and not export_found(project, path, m["export"]):
                E.append(f"[export_not_found] {c}: {path}에서 {m['export']}를 찾을 수 없습니다")
            by_part.setdefault((path, m.get("export")), []).append(c)
        if src == "built" and not m.get("built_by"):
            E.append(f"[map_format] {c}: built 부품은 built_by(만든 배치)가 필요합니다")
    for (path, exp), cs in by_part.items():
        if len(cs) > 1:
            W.append(f"[shared_part] {', '.join(cs)}가 같은 부품({path} · {exp})에 대응됩니다(의도한 것이면 무시)")
    E += plan_conflicts(umap, plan)
    bs = batches_by_id(plan)
    stb = (st or {}).get("batches") or {}
    new_anywhere = {c for b in bs.values() for c in comp_list(b, "new")}
    for b in bs.values():
        if stb.get(b["id"], {}).get("status") in DONE:
            for c in comp_list(b, "new"):
                if c not in comps:
                    E.append(f"[new_not_registered] {b['id']}가 끝났는데 새로 만든 {c}가 대응표에 없습니다(ui-map register --source built)")
        for c in comp_list(b, "reuse"):
            if c not in comps and c not in new_anywhere:
                W.append(f"[reuse_unmapped] {b['id']}가 재사용하는 {c}가 대응표에도 다른 배치의 신규 목록에도 없습니다")
    dup = []
    if batch:
        b = bs.get(batch)
        if not b:
            block("unknown_batch", f"계획에 {batch} 배치가 없습니다.")
        allow = (b.get("paths") or {}).get("allow") or []
        mapped_paths = {m.get("path"): c for c, m in comps.items() if m.get("path")}
        exports = {m.get("export"): c for c, m in comps.items() if m.get("export")}
        for rel in walk(project, None, ["node_modules", "dist", ".git", PREVIEW_DIR], exts or TEXT_EXT):
            if not in_patterns(rel, allow) or is_test_path(rel) or rel in mapped_paths:
                continue
            try:
                txt = (project / rel).read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            for c in sorted(set(re.findall(r"CMP-\d{3}", txt))):
                if c in comps and comps[c].get("path") != rel:
                    dup.append({"file": rel, "cmp": c, "mapped": comps[c].get("path") or comps[c].get("package")})
                    E.append(f"[duplicate_component] {rel}가 {c} 표지를 갖고 있지만 {c}는 이미 {comps[c].get('path') or comps[c].get('package')}에 대응됩니다")
            stem = Path(rel).stem
            if stem in exports and comps[exports[stem]].get("path") != rel:
                W.append(f"[possible_duplicate] {rel}의 이름이 대응된 부품 {exports[stem]}({comps[exports[stem]].get('path')})과 같습니다")
    return {"ok": not E, "errors": E, "warnings": W, "duplicates": dup,
            "counts": {"mapped": len(comps), "cmp_04": len(cmps04), "unmapped": sorted(c for c in cmps04 if c not in comps)}}


def candidates(project: Path, prof: dict, uprof: dict, umap: dict | None) -> dict:
    """기존 부품 → CMP 대응 후보(읽기 전용). 파일의 'CMP-xxx' 표지 또는 파일 이름과 CMP 이름 일치. 프리뷰는 제외."""
    from pb_scan import component_inventory  # 지역 import(순환 방지)
    roots = uprof.get("component_roots") or prof["paths"].get("components") or []
    src = [f for f in walk(project, prof["paths"].get("source") or None, (prof["paths"].get("exclude") or []) + [PREVIEW_DIR], code_exts(uprof))
           if not is_preview(f)]
    cmps04 = uisys_cmps(project)
    inv = component_inventory(project, roots, src, {k: v["name"] for k, v in cmps04.items()})
    mapped = (umap or {}).get("components") or {}
    out = []
    for c in sorted(cmps04):
        if c in mapped:
            continue
        files = [f for f in inv["cmp_candidates"].get(c, []) if not is_preview(f)]
        out.append({"cmp": c, "name": cmps04[c]["name"], "candidates": [
            {"path": f, "export_guess": Path(f).stem,
             "why": "CMP 표지" if c in next((x["cmp_markers"] for x in inv["files"] if x["file"] == f), []) else "이름 일치"} for f in files]})
    return {"roots": roots, "unmapped": out, "files_scanned": len(inv["files"]),
            "note": "후보일 뿐입니다. 사용자 확인을 받은 뒤 ui-map register --source existing --note로 등록합니다."}


# ---------------------------------------------------------------- 토큰(M3.1)
def approved_tokens(project: Path) -> tuple[dict[str, str], str]:
    """승인된 토큰 이름·값. v2 테마 계약이 있으면 테마 적용값(+테마에 없는 04 값), 아니면 04 표."""
    p = project / DESIGN_STATE_REL
    if p.exists():
        try:
            dst = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dst = {}
        rel = (dst.get("config") or {}).get("theme_file")
        if rel and (dst.get("config") or {}).get("workflow") == "v2" and read_theme(project, rel)["contract"]:
            tc = theme_check(project, dst)
            if tc.get("effective_tokens") is not None:
                return dict(tc["effective_tokens"]), f"theme:{rel}"
    return parse_tokens(read_text(project, UISYS_FILE)), UISYS_FILE


def resolve_vars(vars_: dict[str, str]) -> dict[str, str]:
    """같은 파일 안의 var(--x) 참조를 풉니다(최대 5단계). 외부 참조는 그대로 둡니다."""
    out = {}
    for k, v in vars_.items():
        cur = v
        for _ in range(5):
            m = re.fullmatch(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,[^)]*)?\)", cur.strip())
            if not m or m.group(1) not in vars_:
                break
            cur = vars_[m.group(1)]
        out[k] = cur
    return out


def token_check(project: Path, umap: dict) -> dict:
    cfg = umap.get("tokens")
    if not cfg:
        block("tokens_not_configured", "대응표에 토큰 출력이 설정되지 않았습니다. ui-map tokens --file <CSS 파일> --note로 설정하세요.")
    approved, source = approved_tokens(project)
    if not approved:
        block("no_approved_tokens", f"승인된 토큰이 없습니다({UISYS_FILE}의 토큰 표 또는 v2 테마 계약).")
    fmt = cfg.get("format", "css-vars")
    exc = {e["token"]: e for e in umap["exceptions"]["tokens"]}
    res = {"source": source, "format": fmt, "file": cfg.get("file"), "missing": [], "mismatch": [], "excepted": [], "extra": [],
           "stale_exceptions": sorted(t for t in exc if t not in approved)}
    pattern = cfg.get("var_pattern") or "--{dashed}"
    aliases = cfg.get("aliases") or {}
    if fmt == "css-vars":
        rel = cfg.get("file")
        if bad_path(rel) or is_preview(rel) or is_protected(rel):
            block("token_output_invalid", f"토큰 출력 파일 {rel}은 제품 코드 안 상대 경로여야 합니다(프리뷰·보호 경로 불가).")
        f = project / rel
        cur = resolve_vars(parse_css_vars(f.read_text(encoding="utf-8"))) if f.is_file() else {}
        res["file_exists"] = f.is_file()
        name_of = {t: aliases.get(t) or css_var_name(t, pattern) for t in approved}
        got = {t: cur.get(name_of[t]) for t in approved}
        res["extra"] = sorted(set(cur) - set(name_of.values()))
        res["expected_css"] = ":root {\n" + "".join(f"  {name_of[t]}: {approved[t]};\n" for t in sorted(approved)) + "}\n"
    elif fmt == "command":
        cmd = cfg.get("export")
        if not cmd:
            block("token_output_invalid", "format=command에는 export(토큰 이름→값 JSON을 출력하는 프로젝트 명령)가 필요합니다.")
        try:
            p = subprocess.run(cmd, shell=True, cwd=project, capture_output=True, text=True, timeout=int(cfg.get("timeout", 120)))
        except subprocess.TimeoutExpired:
            block("token_export_failed", "토큰 내보내기 명령이 시간 안에 끝나지 않았습니다.", command=cmd)
        try:
            data = json.loads(p.stdout)
            assert isinstance(data, dict)
        except (json.JSONDecodeError, AssertionError):
            block("token_export_failed", "토큰 내보내기 명령의 출력이 {토큰 이름: 값} JSON이 아닙니다.", command=cmd, exit=p.returncode,
                  tail=(p.stdout + p.stderr)[-600:])
        got = {t: (str(data[aliases.get(t, t)]) if aliases.get(t, t) in data else None) for t in approved}
        res["extra"] = sorted(set(data) - {aliases.get(t, t) for t in approved})
    else:
        block("token_output_invalid", f"tokens.format은 {'/'.join(TOKEN_FORMATS)} 중 하나여야 합니다.")
    for t in sorted(approved):
        v = got.get(t)
        prob = None
        if v is None:
            prob = {"token": t, "kind": "missing", "expected": approved[t]}
        elif norm(v) != norm(approved[t]):
            prob = {"token": t, "kind": "mismatch", "expected": approved[t], "actual": v}
        if prob and t in exc:
            res["excepted"].append({**prob, "reason": exc[t]["reason"]})
        elif prob:
            res["missing" if prob["kind"] == "missing" else "mismatch"].append(prob)
    res["counts"] = {"approved": len(approved), "matched": len(approved) - len(res["missing"]) - len(res["mismatch"]) - len(res["excepted"]),
                     "missing": len(res["missing"]), "mismatch": len(res["mismatch"]), "excepted": len(res["excepted"])}
    res["ok"] = not res["missing"] and not res["mismatch"]
    return res


def audit_files(project: Path, prof: dict, uprof: dict, plan: dict | None, batch: str | None, umap: dict) -> list[str]:
    exts = tuple(uprof["audit"]["extensions"])
    tok_file = (umap.get("tokens") or {}).get("file")
    exclude = (prof["paths"].get("exclude") or []) + ["node_modules", "dist", ".git", PREVIEW_DIR]
    if batch:
        b = batches_by_id(plan).get(batch)
        if not b:
            block("unknown_batch", f"계획에 {batch} 배치가 없습니다.")
        pats = ((b.get("paths") or {}).get("allow") or []) + ((b.get("paths") or {}).get("shared") or [])
        files = [f for f in walk(project, None, exclude, exts) if in_patterns(f, pats)]
    else:
        files = walk(project, prof["paths"].get("source") or None, exclude, exts)
    return [f for f in files if f.endswith(exts) and not is_test_path(f) and f != tok_file and not is_preview(f) and not is_protected(f)]


def token_audit(project: Path, prof: dict, uprof: dict, plan: dict | None, batch: str | None, umap: dict) -> dict:
    kinds = uprof["audit"]["kinds"]
    exc = umap["exceptions"]["audit"]
    findings, excepted = [], []
    for rel in audit_files(project, prof, uprof, plan, batch, umap):
        try:
            lines = (project / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith(("//", "/*", "*", "<!--")):
                continue
            hits = []
            if "color" in kinds:
                hits += [("color", m.group(1)) for m in COLOR_RE.finditer(line)]
            if "length" in kinds:
                hits += [("length", m.group(1)) for m in LENGTH_RE.finditer(line)]
            for kind, val in hits:
                rec = {"file": rel, "line": n, "kind": kind, "value": val}
                hit = next((e for e in exc if fnmatch.fnmatch(rel, e["path"]) and (not e.get("value") or norm(e["value"]) == norm(val))), None)
                (excepted if hit else findings).append({**rec, **({"reason": hit["reason"]} if hit else {})})
    mode = uprof["audit"]["mode"]
    return {"ok": mode == "warn" or not findings, "mode": mode, "kinds": kinds, "findings": findings, "excepted": excepted,
            "counts": {"findings": len(findings), "excepted": len(excepted)},
            "note": "직접 값은 승인된 토큰(CSS 변수 등)으로 바꾸거나, 프로젝트가 허용한 예외로 등록합니다(ui-map except --audit-path)."}


# ---------------------------------------------------------------- UI Brief(M3.2)
def section_table(block_text: str, keyword: str) -> list[list[str]]:
    """`### <keyword>…` 아래 첫 표의 데이터 행(머리·구분선 제외)."""
    lines = block_text.splitlines()
    rows, in_sec, seen_head = [], False, False
    for line in lines:
        if re.match(r"^#{3,4}\s", line):
            if in_sec and (rows or seen_head):
                break
            in_sec = keyword in line
            seen_head = False
            continue
        if not in_sec or not line.lstrip().startswith("|"):
            if in_sec and rows and not line.strip():
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.match(r"^:?-{2,}", cells[0] or ""):
            continue
        if not seen_head:
            seen_head = True
            continue
        rows.append(cells)
    return rows


def dd_vd_blocks(project: Path) -> dict[str, dict]:
    text = strip_fences(re.sub(r"<!--.*?-->", "", read_text(project, DD_FILE), flags=re.S))
    out = {}
    for k, b in blocks_by_heading(text, 3, "VD").items():
        out[k] = {"title": re.sub(r"^###\s+VD-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip(), "decision": field_line(b, "결정"),
                  "status": (field_line(b, "상태").split() or [""])[0], "related": field_line(b, "관련")}
    return out


def ac_states(project: Path) -> dict[str, list[str]]:
    from pb_core import table_rows  # 지역 import(이름 충돌 방지)
    doc = strip_fences(read_text(project, TRACE_FILE))
    return {a: sorted(set(re.findall(r"SCR-\d{3}-ST\d+", cells[0] if cells else ""))) for a, cells in table_rows(doc, r"AC-\d{3}").items()}


def screen_brief(sid: str, info: dict, acs_here: list[dict], prio: str | None) -> dict:
    b = info["block"]
    states = []
    for cells in section_table(b, "상태"):
        sid_cell = cells[0] if cells else ""
        label = cells[1] if len(cells) > 1 else ""
        behavior = cells[2] if len(cells) > 2 else ""
        defined = bool(re.fullmatch(rf"{sid}-ST\d+", sid_cell)) and "해당 없음" not in behavior
        states.append({"id": sid_cell if defined else None, "label": label, "behavior": behavior, "defined": defined,
                       "required": defined and prio == "Must"})
    actions = [{"action": c[0], "result": c[1] if len(c) > 1 else "", "refs": sorted(set(re.findall(r"(?:AC|SCR|UXD|FR)-\d{3}(?:-ST\d+)?", " ".join(c))))}
               for c in section_table(b, "행동") if c and c[0] and c[0] not in ("...", "…")]
    inputs = [{"input": c[0], "rule": c[1] if len(c) > 1 else "", "error": c[2] if len(c) > 2 else ""}
              for c in section_table(b, "입력") if c and c[0] and c[0] not in ("...", "…")]
    info_rows = [{"order": c[0], "info": c[1] if len(c) > 1 else "", "source": c[2] if len(c) > 2 else "", "visibility": c[3] if len(c) > 3 else ""}
                 for c in section_table(b, "정보") if len(c) > 1 and c[1] not in ("...", "…")]
    return {
        "name": re.sub(r"^##\s+SCR-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip(),
        "purpose": field_line(b, "목적"), "role": field_line(b, "역할"), "platform": info["platform"], "route": field_line(b, "경로"),
        "trace": sorted(info["trace"]), "uxd": sorted(info["uxd"]), "entry_exit": field_line(b, "진입 / 이탈"), "priority": prio,
        "states": states, "actions": actions, "inputs": inputs, "info": info_rows, "components": sorted(info["cmp"]), "acs": acs_here,
    }


def build_brief(project: Path, st: dict, plan: dict, bid: str, prof: dict, uprof: dict, dinfo: dict, model: dict, umap: dict | None) -> dict:
    bs = batches_by_id(plan)
    b = bs[bid]
    sinfo = screen_info(project)
    acst = ac_states(project)
    cmps04 = uisys_cmps(project)
    vds = {k: v for k, v in dd_vd_blocks(project).items() if v["status"] == "승인"}
    comps_map = (umap or {}).get("components") or {}
    deps = dep_closure(plan, bid)
    warnings = []
    targets = (st.get("batches", {}).get(bid) or {}).get("ac_targets") or {}
    batch_acs = [a for a in b.get("acs") or [] if a in model["AC"]]
    screens, touches = {}, {}
    pv_manifest = {}
    mp = project / PREVIEW_DIR / "preview.manifest.json"
    if mp.is_file():
        try:
            pv_manifest = (json.loads(mp.read_text(encoding="utf-8")).get("screens") or {})
        except json.JSONDecodeError:
            pv_manifest = {}
    for s in b.get("screens") or []:
        if s not in sinfo:
            warnings.append(f"{s}: {SCREENS_FILE}에 화면 블록이 없습니다")
            continue
        here = []
        for a in batch_acs:
            sts = [x for x in acst.get(a, []) if x.startswith(s + "-")]
            if sts or s in model["ac_screens"].get(a, []):
                here.append({"id": a, "title": model["AC"][a]["title"], "priority": model["AC"][a]["priority"], "states": sts,
                             "target_level": targets.get(a)})
        prios = [x["priority"] for x in here] + [model["US"].get(u, {}).get("priority") for u in sinfo[s]["trace"] if u.startswith("US-")]
        prio = "Must" if "Must" in prios else ("Should" if "Should" in prios else ("Could" if "Could" in prios else None))
        sb = screen_brief(s, sinfo[s], here, prio)
        rel_cmps = set(sb["components"])
        sb["vd"] = [{"id": k, "title": v["title"], "decision": v["decision"]} for k, v in sorted(vds.items())
                    if s in v["related"] or rel_cmps & set(re.findall(r"CMP-\d{3}", v["related"]))]
        pv = pv_manifest.get(s) if isinstance(pv_manifest.get(s), dict) else None
        sb["preview_reference"] = ({"file": f"{PREVIEW_DIR}/{pv['file']}" if pv.get("file") else None, "states": pv.get("states"),
                                    "use": "visual_reference_only"} if pv and not pv.get("skip") else None)
        if not any(x["defined"] for x in sb["states"]):
            warnings.append(f"{s}: 상태 표에서 정의된 상태(ID)를 찾지 못했습니다")
        screens[s] = sb
    for s in b.get("touches") or []:
        if s in sinfo:
            touches[s] = {"name": re.sub(r"^##\s+SCR-\d{3}\s*:?\s*", "", sinfo[s]["block"].splitlines()[0]).strip(),
                          "states": sorted(sinfo[s]["states"])}
    cmp_ids = sorted(set(comp_list(b, "reuse")) | set(comp_list(b, "new")) | {c for sb in screens.values() for c in sb["components"]})
    components = {}
    for c in cmp_ids:
        if c in comps_map:
            role = "reuse_mapped"
        elif c in comp_list(b, "new"):
            role = "new_here"
        else:
            owner = next((d for d in deps if c in comp_list(bs[d], "new")), None)
            role = f"new_in:{owner}" if owner else "unplanned"
        if role == "unplanned":
            warnings.append(f"{c}: 대응표에도 이 배치·선행 배치의 신규 목록에도 없습니다(계획 보완 필요)")
        components[c] = {**(cmps04.get(c) or {"name": "", "missing_in_04": True}), "role": role, "mapping": comps_map.get(c)}
    approved, tsource = approved_tokens(project)
    gvds = [{"id": k, "title": v["title"], "decision": v["decision"]} for k, v in sorted(vds.items())
            if not re.search(r"(?:SCR|CMP)-\d{3}", v["related"])]
    data_tasks = [t for t in b.get("tasks") or [] if t.get("layer") in ("api", "be", "db")]
    providers = [{"batch": d, "tasks": [t for t in bs[d].get("tasks") or [] if t.get("layer") in ("api", "be")]} for d in deps]
    contract = uprof.get("api_contract") or ""
    sources = {rel: sha_file(project / rel) for rel in (SCREENS_FILE, UISYS_FILE, TRACE_FILE, DD_FILE, PLAN_JSON_REL, UI_MAP_REL)}
    if tsource.startswith("theme:"):
        sources[tsource[6:]] = sha_file(project / tsource[6:])
    brief = {
        "format": BRIEF_FORMAT, "batch": bid, "title": b.get("title"), "kind": b.get("kind"), "goal": b.get("goal"),
        "plan_revision": st["plan"].get("revision"),
        "design": {"level": dinfo.get("level"), "workflow": dinfo.get("workflow"), "basis": dinfo.get("basis"),
                   "waiver": (st.get("batches", {}).get(bid) or {}).get("waiver")},
        "screens": screens, "touches": touches, "components": components,
        "tokens": {"source": tsource, "approved": approved, "output": (umap or {}).get("tokens")},
        "visual_decisions_global": gvds,
        "data": {"tasks": data_tasks, "providers": providers, "api_contract": {"path": contract, "exists": bool(contract) and (project / contract).is_file()}},
        "acs": batch_acs, "test_plan": b.get("test_plan") or [], "paths": b.get("paths") or {}, "depends_on": b.get("depends_on") or [],
        "rules": [
            "승인된 UX Spec·Design Direction·토큰만 따릅니다. 명세에 없는 정보·행동·정책은 구현하지 않고 원장(ledger)에 올립니다.",
            "대응표에 있는 컴포넌트는 반드시 재사용합니다. 같은 컴포넌트를 새로 만들지 않습니다.",
            "색·간격 등은 승인된 토큰(토큰 출력 파일의 변수)으로 씁니다. 직접 값은 프로젝트가 허용한 예외만.",
            "design-preview/는 시각 참고만 합니다. import·복사하지 않습니다.",
            "UI Plan(.ai-workflow/build/ui/<배치>/plan.json)을 쓰고 ui-plan-validate가 통과한 뒤 구현합니다.",
        ],
        "sources": sources, "warnings": warnings,
    }
    brief["digest"] = digest({k: v for k, v in brief.items() if k != "digest"})
    return brief


def plan_skeleton(brief: dict) -> dict:
    return {
        "format": PLAN_FORMAT, "batch": brief["batch"], "brief_digest": brief["digest"],
        "screens": {s: {"tree": [], "states": {x["id"]: {"how": "", "ref": ""} for x in sb["states"] if x["defined"]},
                        "interactions": [{"action": a["action"], "trigger": "", "result": a["result"], "to_state": "", "acs": [r for r in a["refs"] if r.startswith("AC-")]}
                                         for a in sb["actions"]],
                        "data": [], "acs": {x["id"]: {"states": x["states"], "tests": []} for x in sb["acs"]}}
                    for s, sb in brief["screens"].items()},
        "components": {c: {"action": "reuse" if v["role"] == "reuse_mapped" or v["role"].startswith("new_in:") else ("new" if v["role"] == "new_here" else ""),
                           "part": (v.get("mapping") or {}).get("export", ""), "file": (v.get("mapping") or {}).get("path", "")}
                       for c, v in brief["components"].items()},
        "notes": [],
    }


def ui_rel(bid: str, name: str) -> str:
    return f"{UI_DIR_REL}/{bid}/{name}"


def write_json(project: Path, rel: str, obj: dict) -> None:
    write_owned(project, rel, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_json(project: Path, rel: str) -> dict | None:
    p = project / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_invalid": True}


# ---------------------------------------------------------------- UI Plan 검증(M3.2)
def _walk(nodes, path="tree"):
    for i, n in enumerate(nodes or []):
        yield f"{path}[{i}]", n
        if isinstance(n, dict):
            yield from _walk(n.get("children"), f"{path}[{i}].children")


def _preview_refs(obj, where="") -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "visual_ref":  # 시각 참고 표시는 허용(프리뷰 화면 위치를 적을 수 있음)
                continue
            hits += _preview_refs(v, f"{where}.{k}" if where else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _preview_refs(v, f"{where}[{i}]")
    elif isinstance(obj, str) and PREVIEW_DIR in obj:
        hits.append(where)
    return hits


def validate_ui_plan(project: Path, uplan: dict, brief_now: dict, plan: dict, bid: str, umap: dict | None, uprof: dict,
                     ledger_ids: set[str]) -> dict:
    E, W = [], []

    def err(code, msg):
        E.append(f"[{code}] {msg}")

    def warn(code, msg):
        W.append(f"[{code}] {msg}")

    if not isinstance(uplan, dict) or uplan.get("_invalid"):
        return {"ok": False, "errors": ["[ui_plan_format] UI Plan이 JSON 객체가 아닙니다"], "warnings": []}
    if uplan.get("format") != PLAN_FORMAT:
        err("ui_plan_format", f"format은 {PLAN_FORMAT}이어야 합니다")
    if uplan.get("batch") != bid:
        err("ui_plan_format", f"batch가 {bid}가 아닙니다")
    if uplan.get("brief_digest") != brief_now["digest"]:
        err("brief_stale", "UI Plan이 현재 UI Brief(승인 문서·계획·대응표 기준)와 다른 Brief를 기준으로 합니다. ui-brief를 다시 받고 계획을 확인하세요")
    for where in _preview_refs(uplan):
        err("preview_reuse", f"{where}: design-preview/ 경로를 제품 코드 입력으로 쓸 수 없습니다(시각 참고는 visual_ref에만)")
    b = batches_by_id(plan)[bid]
    allow = ((b.get("paths") or {}).get("allow") or []) + ((b.get("paths") or {}).get("shared") or [])
    comps_map = (umap or {}).get("components") or {}
    mapped_exports = {m.get("export"): c for c, m in comps_map.items() if m.get("export")}
    bcomps = brief_now["components"]
    cmps04 = set(uisys_cmps(project))
    scr_plan = uplan.get("screens") if isinstance(uplan.get("screens"), dict) else {}
    if not isinstance(uplan.get("screens"), dict):
        err("ui_plan_format", "screens는 {화면 ID: {...}} 객체여야 합니다")
    for s in brief_now["screens"]:
        if s not in scr_plan:
            err("screen_missing", f"{s}: 배치가 소유한 화면의 계획이 없습니다")
    for s in scr_plan:
        if s not in brief_now["screens"]:
            err("screen_unknown", f"{s}: 이 배치가 소유한 화면이 아닙니다")
    used_cmps = set()
    contract_text = None
    if uprof.get("api_contract") and (project / uprof["api_contract"]).is_file():
        contract_text = (project / uprof["api_contract"]).read_text(encoding="utf-8", errors="replace")
    elif uprof.get("api_contract"):
        warn("contract_file_missing", f"ui.api_contract 파일 {uprof['api_contract']}이 없습니다")
    for s, sp in scr_plan.items():
        sb = brief_now["screens"].get(s)
        if not sb or not isinstance(sp, dict):
            continue
        # 상태
        defined = {x["id"] for x in sb["states"] if x["defined"]}
        sts = sp.get("states") if isinstance(sp.get("states"), dict) else {}
        for x in sorted(defined - set(sts)):
            err("state_missing", f"{s}: 정의된 상태 {x}의 렌더 경로가 없습니다")
        for x, v in sts.items():
            if x not in defined:
                err("state_unknown", f"{s}: {x}는 02 문서에 정의된 상태가 아닙니다")
            elif not isinstance(v, dict) or v.get("how") not in STATE_HOW or not str(v.get("ref", "")).strip():
                err("state_how", f"{s}/{x}: how({'/'.join(STATE_HOW)})와 ref(재현 방법)가 필요합니다")
        # 컴포넌트 트리
        tree = sp.get("tree")
        if not isinstance(tree, list) or not tree:
            err("tree_missing", f"{s}: 컴포넌트 트리(tree)가 비어 있습니다")
            tree = []
        for where, n in _walk(tree, f"{s}.tree"):
            if not isinstance(n, dict) or not n.get("part"):
                err("tree_format", f"{where}: 각 노드에는 part(코드 부품 이름)가 필요합니다")
                continue
            c = n.get("cmp")
            if c:
                used_cmps.add(c)
                if c not in cmps04:
                    err("unknown_cmp", f"{where}: {c}는 승인된 04 문서에 없습니다")
                elif c in comps_map:
                    m = comps_map[c]
                    if n.get("local"):
                        err("cmp_mapped_rebuilt", f"{where}: {c}는 대응표의 기존 부품({m.get('path') or m.get('package')} · {m.get('export')})이 있어 새로 만들 수 없습니다")
                    elif n["part"] != m.get("export"):
                        err("cmp_part_mismatch", f"{where}: {c}의 부품은 대응표대로 {m.get('export')}이어야 합니다(현재 {n['part']})")
                elif bcomps.get(c, {}).get("role") not in ("new_here",) and not str(bcomps.get(c, {}).get("role", "")).startswith("new_in:"):
                    err("cmp_unplanned", f"{where}: {c}는 대응표에 없고 이 배치·선행 배치의 신규 목록(components.new)에도 없습니다(계획 수정 필요)")
            elif n["part"] in mapped_exports:
                err("duplicate_of_mapped", f"{where}: 로컬 부품 {n['part']}이 대응된 {mapped_exports[n['part']]}과 이름이 같습니다(재사용하거나 이름을 구분하세요)")
            f = n.get("file")
            if f and (n.get("local") or (c and bcomps.get(c, {}).get("role") == "new_here")):
                if bad_path(f) or not in_patterns(f, allow):
                    err("out_of_scope_file", f"{where}: {f}는 배치 paths.allow/shared 밖입니다")
        # 상호작용
        ints = sp.get("interactions") if isinstance(sp.get("interactions"), list) else []
        spec_actions = [a["action"] for a in sb["actions"]]
        got_actions = {i.get("action") for i in ints if isinstance(i, dict)}
        for a in spec_actions:
            if a not in got_actions:
                err("action_missing", f"{s}: 02 행동 '{a}'의 구현 계획이 없습니다")
        all_states = {x for sbb in brief_now["screens"].values() for x in (y["id"] for y in sbb["states"] if y["defined"])}
        for i in ints:
            if not isinstance(i, dict):
                err("interaction_format", f"{s}: interactions 항목은 객체여야 합니다")
                continue
            if i.get("action") not in spec_actions:
                if not i.get("ledger"):
                    err("action_unspecified", f"{s}: '{i.get('action')}'는 02에 없는 행동입니다. 명세에 없는 행동은 원장에 등록하고 ledger에 ID를 적으세요")
                elif i["ledger"] not in ledger_ids:
                    err("action_unspecified", f"{s}: '{i.get('action')}'의 원장 항목 {i['ledger']}이 없습니다")
            ts = i.get("to_state")
            if ts and ts not in all_states and not re.fullmatch(r"SCR-\d{3}", str(ts)):
                err("interaction_state", f"{s}: '{i.get('action')}'의 to_state {ts}가 정의된 상태(또는 이동할 화면 ID)가 아닙니다")
        # 데이터·API 계약
        for j, dsrc in enumerate(sp.get("data") or []):
            if not isinstance(dsrc, dict) or dsrc.get("source") not in DATA_SOURCES:
                err("data_format", f"{s}.data[{j}]: source는 {'/'.join(DATA_SOURCES)} 중 하나여야 합니다")
                continue
            if dsrc["source"] in ("api", "mock") and not str(dsrc.get("contract", "")).strip():
                err("data_contract_missing", f"{s}.data[{j}]({dsrc.get('name')}): API·Mock 데이터는 contract(계약 식별자)가 필요합니다")
            elif contract_text is not None and dsrc["source"] in ("api", "mock") and dsrc["contract"] not in contract_text:
                warn("contract_not_found", f"{s}.data[{j}]: contract '{dsrc['contract']}'를 {uprof['api_contract']}에서 찾지 못했습니다")
            if dsrc["source"] == "mock":
                mf = dsrc.get("mock_file")
                if not mf or bad_path(mf) or not in_patterns(mf, allow):
                    err("mock_out_of_scope", f"{s}.data[{j}]: Mock 파일(mock_file)은 배치 paths.allow/shared 안의 제품 코드여야 합니다")
            if dsrc.get("task") and dsrc["task"] not in {t.get("id") for t in brief_now["data"]["tasks"]} | {
                    t.get("id") for p in brief_now["data"]["providers"] for t in p["tasks"]}:
                err("data_task_unknown", f"{s}.data[{j}]: task {dsrc['task']}는 이 배치나 선행 배치의 api·be·db 작업이 아닙니다")
        # AC 연결
        acp = sp.get("acs") if isinstance(sp.get("acs"), dict) else {}
        for x in sb["acs"]:
            if x["id"] not in acp:
                err("ac_unlinked", f"{s}: {x['id']}가 이 화면에 연결되어 있는데 UI Plan의 acs에 없습니다")
        tp = {t.get("ac") for t in brief_now["test_plan"] if isinstance(t, dict)}
        for a, v in acp.items():
            if a not in brief_now["acs"]:
                err("ac_not_in_batch", f"{s}: {a}는 이 배치의 AC가 아닙니다")
                continue
            for x in (v or {}).get("states", []) if isinstance(v, dict) else []:
                if x not in defined:
                    err("ac_state_unknown", f"{s}/{a}: {x}는 이 화면의 정의된 상태가 아닙니다")
            if a not in tp:
                warn("ac_no_test_plan", f"{s}/{a}: 구현 계획 test_plan에 없습니다")
    # 배치 컴포넌트 목록과의 정합
    cdecl = uplan.get("components") if isinstance(uplan.get("components"), dict) else {}
    for c, v in cdecl.items():
        role = bcomps.get(c, {}).get("role")
        act = (v or {}).get("action") if isinstance(v, dict) else None
        if act == "new" and role != "new_here":
            err("cmp_new_not_planned", f"components.{c}: 이 배치의 components.new가 아닌데 새로 만든다고 적었습니다({role})")
        if act == "reuse" and role in ("unplanned", None):
            err("cmp_unplanned", f"components.{c}: 대응표나 선행 배치의 신규 목록에 없는데 재사용한다고 적었습니다")
        if isinstance(v, dict) and v.get("file") and is_preview(v["file"]):
            err("preview_reuse", f"components.{c}: 프리뷰 파일은 제품 부품이 될 수 없습니다")
    for c in comp_list(b, "new"):
        if c not in used_cmps and c not in cdecl:
            warn("new_unused", f"{c}: 이 배치가 새로 만드는 컴포넌트가 UI Plan 어디에도 없습니다")
    return {"ok": not E, "errors": E, "warnings": W,
            "counts": {"screens": len(scr_plan), "states": sum(len((v or {}).get("states") or {}) for v in scr_plan.values() if isinstance(v, dict)),
                       "cmps_used": len(used_cmps)}}
