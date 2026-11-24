"""/product-design EX6: 디자인 탐색 산출물 격리와 공식 디자인 근거(읽기 전용). 설계 §2.9·EX6.

product-design `preview-check`와 product-build `verify`·`ui-guard`·UI Brief가 같은 규칙을 쓰도록 한 곳에 둡니다.
이 모듈은 **상태·파일을 쓰지 않습니다**(product-build가 읽기 전용으로 가져옴, tests가 검사).

판정(시각적 유사성은 판정하지 않음 — D4)
- explore_copy: 탐색 파일과 같은 파일(줄 끝·끝 공백 정규화) 또는 주석·공백·대소문자만 다른 파일(이름을 바꾸거나 다시 들여 써도 같음)
- explore_copy_partial: 탐색 시안 CSS 규칙 블록(선택자+선언)을 여러 개 그대로 옮김
- explore_reuse: design-explore 경로 참조(대소문자·역슬래시·URL 인코딩 포함), design-explore 안을 가리키는 심볼릭 링크
- explore_token: 탐색 후보 테마에만 있는 토큰 이름(04·공식 테마에 없음)을 CSS 변수로 정의·사용
- reference_asset_embedded: 레퍼런스 원본과 바이트가 같은 파일
- asset_unapproved: 등록 자산과 같은 파일(또는 자산 경로 참조)인데 권리 미확인이거나 승인된 VD(승인 기록과 일치하는 07)의 관련에 없음
정당한 경로: 승인된 07 VD의 관련에 들어가고 권리가 확인된 자산, 승인 기록과 일치하는 공식 테마·04 토큰만.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pd_core import DD_FILE, UISYS_FILE, blocks_by_heading, field_line, read_text, sha256_file, strip_fences

EXPLORE_DIR = "design-explore"
REGISTRY_DEFAULT = "design-profile/assets.json"
STATE_REL = ".ai-workflow/design.json"
IMAGE_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif")
TEXT_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".css", ".scss", ".sass", ".less", ".html", ".htm", ".vue",
             ".svelte", ".json", ".svg", ".md", ".mdx")
PARTIAL_MIN_RULES = 4          # 시안 CSS 규칙 블록을 이만큼 이상 그대로 옮기면 부분 복사
PARTIAL_MIN_DECLS = 2          # 규칙 블록 비교 대상: 선언 2개 이상(짧은 리셋 규칙 제외)
REF_RE = re.compile(r"design[-_]?explore(?:[/\\]|%2f|%5c)", re.I)


# ---------------------------------------------------------------- 정규화
def _norm_exact(b: bytes) -> bytes:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return b
    return "\n".join(x.rstrip() for x in s.replace("\r\n", "\n").split("\n")).strip("\n").encode("utf-8")


def _norm_loose(rel: str, b: bytes) -> bytes | None:
    """주석·공백·대소문자를 무시한 내용(텍스트 코드만). 이름 바꾸기·다시 들여 쓰기·주석 추가로 우회하지 못하게."""
    if not rel.lower().endswith(TEXT_EXTS):
        return None
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"(?m)^\s*//.*$", "", s)
    s = re.sub(r"\s+", "", s).lower()
    return s.encode("utf-8") if len(s) >= 40 else None


LINE_SLASH_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".scss", ".sass", ".less")
LINE_HASH_EXTS = (".py", ".rb", ".sh", ".yaml", ".yml", ".toml")


def strip_comments(rel: str, text: str) -> str:
    """실제 주석만 지웁니다(문맥 판정용). 블록 주석(/* */)·HTML 주석(<!-- -->)은 위치와 관계없이, 줄 주석(//·#)은 그 언어의
    파일에서 줄 전체가 주석일 때만 지웁니다. CSS의 #id·*·:before 선택자, 마크다운 제목은 주석이 아닙니다(P0-3).
    줄 수는 유지합니다(위치 보고용)."""
    keep_lines = lambda m: "\n" * m.group(0).count("\n")
    t = re.sub(r"/\*.*?\*/", keep_lines, text, flags=re.S)
    t = re.sub(r"<!--.*?-->", keep_lines, t, flags=re.S)
    low = rel.lower()
    if low.endswith(LINE_SLASH_EXTS):
        t = re.sub(r"(?m)^[ \t]*//.*$", "", t)
    if low.endswith(LINE_HASH_EXTS):
        t = re.sub(r"(?m)^[ \t]*#.*$", "", t)
    return t


def _css_rules(text: str) -> set[str]:
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", code):
        sel = " ".join(m.group(1).split()).lower()
        decls = sorted(" ".join(d.split()).lower() for d in m.group(2).split(";") if ":" in d)
        if len(decls) >= PARTIAL_MIN_DECLS and not sel.startswith("@"):
            out.add(sel + "{" + ";".join(decls) + "}")
    return out


def _style_text(rel: str, text: str) -> str:
    if rel.lower().endswith((".css", ".scss", ".sass", ".less")):
        return text
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I))


# ---------------------------------------------------------------- 탐색 산출물 색인
def explore_index(project: Path) -> dict:
    root = project / EXPLORE_DIR
    idx = {"exact": {}, "loose": {}, "rules": {}, "tokens": set()}
    if not root.is_dir():
        return idx
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name in (".gitignore", ".DS_Store") or p.is_symlink():
            continue
        rel = str(p.relative_to(project))
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if not raw.strip():
            continue
        idx["exact"].setdefault(hashlib.sha256(_norm_exact(raw)).hexdigest(), rel)
        lo = _norm_loose(rel, raw)
        if lo:
            idx["loose"].setdefault(hashlib.sha256(lo).hexdigest(), rel)
        if p.suffix == ".css" and "/shots/" not in rel and "/compare/" not in rel:
            for r in _css_rules(raw.decode("utf-8", "replace")):
                idx["rules"].setdefault(r, rel)
        if p.name in ("theme.json", "theme.candidate.json"):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue  # data_problems가 차단 판정으로 보고
            idx["tokens"] |= set(x for k in ("tokens", "cr_tokens") if isinstance(data.get(k), dict) for x in data[k])
    return idx


def _read_json(p: Path):
    """(값, 문제) — 읽을 수 없거나 JSON이 아니면 (None, 사유)."""
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"{type(e).__name__}: {e}"


def _state(project: Path) -> dict:
    p = project / STATE_REL
    if not p.is_file():
        return {}
    v, _ = _read_json(p)
    return v if isinstance(v, dict) else {}  # 형식 오류는 data_problems가 차단 판정으로 보고(승인 없음으로 취급 — 공식 디자인 없음)


def data_problems(project: Path) -> list[dict]:
    """판정 근거가 되는 JSON(상태·자산 레지스트리·공식 테마·탐색 후보 테마)의 최상위 형식 오류. 차단 판정(design_data_invalid)입니다."""
    out = []

    def bad(rel, why):
        out.append({"file": rel, "kind": "design_data_invalid", "detail": why})
    p = project / STATE_REL
    st = {}
    if p.is_file():
        v, why = _read_json(p)
        if why or not isinstance(v, dict) or not isinstance(v.get("stages", {}), dict):
            bad(STATE_REL, why or "최상위가 객체가 아니거나 stages가 객체가 아님")
        else:
            st = v
    theme_rel = (st.get("config") or {}).get("theme_file") if isinstance(st.get("config"), dict) else None
    if theme_rel and (project / theme_rel).is_file():
        v, why = _read_json(project / theme_rel)
        if why or not isinstance(v, dict) or not isinstance(v.get("tokens", {}), dict):
            bad(theme_rel, why or "공식 테마의 최상위·tokens가 객체가 아님")
    cfg = st.get("config") if isinstance(st.get("config"), dict) else {}
    reg_rel = ((cfg.get("exploration") or {}) if isinstance(cfg.get("exploration"), dict) else {}).get("assets_file") or REGISTRY_DEFAULT
    if (project / reg_rel).is_file():
        v, why = _read_json(project / reg_rel)
        if why or not isinstance(v, dict) or not isinstance(v.get("assets", {}), dict):
            bad(reg_rel, why or "자산 레지스트리의 최상위·assets가 객체가 아님")
        else:
            nd = sorted(k for k, x in (v.get("assets") or {}).items() if not isinstance(x, dict))
            if nd:
                bad(reg_rel, f"자산 항목이 객체가 아님: {', '.join(nd)}")
    root = project / EXPLORE_DIR
    if root.is_dir():
        for q in sorted(root.rglob("theme*.json")):
            if q.is_symlink() or not q.is_file() or "/shots/" in str(q):
                continue
            v, why = _read_json(q)
            if why or not isinstance(v, dict) or not isinstance(v.get("tokens", {}), dict):
                bad(str(q.relative_to(project)), why or "탐색 후보 테마의 최상위·tokens가 객체가 아님")
    return out


def explore_status(st: dict, rel: str) -> str:
    """탐색 파일의 지위(메시지용): 미선택 시안 · 선택됐지만 공식 문서가 아님 · 탐색 작업 파일."""
    m = re.match(rf"{EXPLORE_DIR}/([SV]\d{{2}})/([A-C])/", rel)
    if not m:
        return "exploration_artifact"
    for ph in ("structure", "visual"):
        for r in ((st.get("exploration") or {}).get(ph) or {}).get("rounds") or []:
            if r["id"] == m.group(1):
                ch = r.get("choice")
                return "chosen_not_official" if ch and m.group(2) in ch.get("variants", []) else "unselected_variant"
    return "unselected_variant"


# ---------------------------------------------------------------- 공식 디자인 근거
def official_design(project: Path, st: dict | None = None) -> dict:
    """승인 기록과 일치하는 공식 디자인: 승인 VD(07 해시가 승인 기록과 같을 때만), 공식 토큰 이름, 자산 레지스트리, 탐색 선택 출처."""
    st = st if st is not None else _state(project)
    stages = st.get("stages") or {}
    dd = stages.get("design_direction") or {}
    rec = dd.get("approved") if dd.get("status") == "approved" else None
    if rec is not None:
        import pd_change as CH  # 유효 승인 기준(승인 기록 + 승인 패치)의 단일 구현. 체인이 깨지면 공식 디자인을 인정하지 않음
        eff = CH.effective(st)
        rec = eff["records"].get("design_direction") if eff["ok"] else None
    intact = bool(rec) and (rec.get("hashes") or {}).get(DD_FILE) == (sha256_file(project / DD_FILE) if (project / DD_FILE).is_file() else None)
    text = strip_fences(re.sub(r"<!--.*?-->", "", read_text(project, DD_FILE), flags=re.S))
    blocks = blocks_by_heading(text, 3, "VD")
    approved_ids = set((rec or {}).get("approved_vds") or []) if intact else set()
    vds = {k: {"related": field_line(b, "관련"), "status": (field_line(b, "상태").split() or [""])[0]} for k, b in blocks.items() if k in approved_ids}
    from pd_core import parse_tokens
    names = set(parse_tokens(read_text(project, UISYS_FILE)))
    theme_rel = (st.get("config") or {}).get("theme_file")
    if theme_rel and (project / theme_rel).is_file():
        tv, _ = _read_json(project / theme_rel)
        if isinstance(tv, dict) and isinstance(tv.get("tokens"), dict):
            names |= set(tv["tokens"])
    reg_rel = (((st.get("config") or {}).get("exploration") or {}).get("assets_file")) or REGISTRY_DEFAULT
    reg = {}
    if (project / reg_rel).is_file():
        rv, _ = _read_json(project / reg_rel)
        reg = rv.get("assets") if isinstance(rv, dict) and isinstance(rv.get("assets"), dict) else {}
    in_vd = {}
    for k, v in vds.items():
        for aid in re.findall(r"AST-\d{3}", v["related"]):
            in_vd.setdefault(aid, []).append(k)
    snap = (rec or {}).get("assets") if intact else None  # P0-1: 승인 스냅샷이 공식 자산의 유일한 근거
    assets = {}
    for aid, a in reg.items():
        if not isinstance(a, dict):
            continue
        r = a.get("rights") or {}
        rights_ok = (bool(r.get("confirmed_by_user")) or bool(r.get("inherited_from"))) and str(r.get("license") or "").lower() not in ("", "unknown", "unconfirmed") \
            and a.get("source") != "reference_derived"
        f = project / str(a.get("file") or "")
        intact_a = f.is_file() and sha256_file(f) == a.get("sha256")
        cur_sha = sha256_file(f) if f.is_file() else None
        if not rec or not in_vd.get(aid):
            snap_state = "not_applicable"
        elif snap is None:
            snap_state = "missing"        # 스냅샷 도입 이전 승인 기록: 자동으로 신뢰하지 않음
        elif aid not in snap:
            snap_state = "absent"
        elif snap[aid].get("sha256") != cur_sha or snap[aid].get("sha256") != a.get("sha256") or snap[aid].get("entry_sha256") != _entry_sha(a):
            snap_state = "drift"
        else:
            snap_state = "ok"
        assets[aid] = {"sha256": a.get("sha256"), "file": a.get("file"), "kind": a.get("kind"), "role": a.get("role"), "rights_ok": rights_ok,
                       "file_intact": intact_a, "vds": in_vd.get(aid, []), "snapshot": snap_state,
                       "official": rights_ok and intact_a and bool(in_vd.get(aid)) and snap_state == "ok"}
    refs_sha = {r.get("sha256"): rid for rid, r in ((st.get("exploration") or {}).get("references") or {}).items() if r.get("sha256")}
    prov = {s: (stages.get(s) or {}).get("exploration_basis") for s in ("ux_planning", "design_direction") if (stages.get(s) or {}).get("exploration_basis")}
    return {"design_direction_approved": bool(rec), "design_direction_intact": intact,
            "design_direction_revision": (rec or {}).get("revision"), "approved_vds": vds, "token_names": names,
            "theme_file": theme_rel, "theme_hash_approved": (rec or {}).get("theme_hash"), "assets": assets, "registry": reg_rel,
            "reference_shas": refs_sha, "exploration_provenance": prov}


def _entry_sha(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _official_theme_css(project: Path, st: dict, od: dict) -> set[bytes]:
    """승인 기록과 일치하는 공식 테마에서 엔진이 만드는 tokens.css(정규화). 후보 테마를 공식 테마로 승인하면
    탐색 시안의 엔진 생성 tokens.css와 내용이 같아지므로, 이 내용은 탐색 복사가 아니라 공식 테마 출력으로 봅니다."""
    rel = od.get("theme_file")
    if not rel or not od.get("theme_hash_approved") or not od.get("design_direction_intact"):
        return set()
    p = project / rel
    if not p.is_file() or sha256_file(p) != od["theme_hash_approved"]:
        return set()
    import pd_theme as TH
    import pd_visual as VS
    out = set()
    th = TH.read_theme(project, rel)
    if th.get("contract") and not th.get("errors"):
        out.add(VS.tokens_css(th["resolved"]))
        exp = TH.theme_check(project, st).get("expected_css")
        if exp:
            out.add(exp)
    return {x for x in (_norm_loose("tokens.css", c.encode()) for c in out) if x}


# ---------------------------------------------------------------- 판정
def findings(project: Path, files: list[str], st: dict | None = None) -> list[dict]:
    """파일들(프리뷰·제품 코드)에 탐색 산출물·미승인 디자인이 들어왔는지. design-explore/ 안 파일은 대상이 아닙니다."""
    st = st if st is not None else _state(project)
    idx = explore_index(project)
    od = official_design(project, st)
    by_sha = {a["sha256"]: aid for aid, a in od["assets"].items() if a.get("sha256")}
    cand_tokens = {t for t in idx["tokens"] if t not in od["token_names"]}
    cand_vars = {"--" + t.replace(".", "-"): t for t in cand_tokens}
    official_css = None
    out = data_problems(project) if files else []
    for rel in files:
        if rel == EXPLORE_DIR or rel.startswith(EXPLORE_DIR + "/"):
            continue
        p = project / rel
        try:
            if p.is_symlink():
                tgt = str(p.resolve())
                if f"/{EXPLORE_DIR}/" in tgt + "/" or tgt.endswith("/" + EXPLORE_DIR):
                    out.append({"file": rel, "kind": "explore_reuse", "detail": f"design-explore를 가리키는 심볼릭 링크({tgt})"})
                    continue
            raw = p.read_bytes()
        except OSError:
            continue
        if not raw.strip():
            continue
        h_raw = hashlib.sha256(raw).hexdigest()
        if h_raw in od["reference_shas"]:
            out.append({"file": rel, "kind": "reference_asset_embedded", "detail": f"레퍼런스 원본 {od['reference_shas'][h_raw]}과 같은 파일"})
            continue
        if h_raw in by_sha:  # 등록 자산(탐색 라운드 사본 _assets와 같은 바이트여도 자산 기준으로 판정 — 공식 자산은 통과)
            aid = by_sha[h_raw]
            a = od["assets"][aid]
            if not a["official"]:
                why = ("권리 미확인" if not a["rights_ok"] else "") + ("" if a["vds"] else (" · " if not a["rights_ok"] else "") + "승인된 VD 관련에 없음")
                if a["rights_ok"] and a["vds"] and not a["file_intact"]:
                    why = "레지스트리 파일이 등록 해시와 다름"
                elif a["rights_ok"] and a["vds"] and a["snapshot"] != "ok":
                    why = {"missing": "승인 기록에 자산 스냅샷이 없음(이전 승인 — reopen --stage design_direction 후 재승인)",
                           "absent": "승인 스냅샷에 없는 자산",
                           "drift": "승인 스냅샷과 파일·레지스트리 항목이 다름(승인 이후 변경)"}.get(a["snapshot"], "승인 스냅샷 불일치")
                out.append({"file": rel, "kind": "asset_unapproved", "asset": aid, "detail": why.strip(" ·")})
            continue
        h = hashlib.sha256(_norm_exact(raw)).hexdigest()
        if rel.endswith(".css") and (h in idx["exact"] or (_norm_loose(rel, raw) and hashlib.sha256(_norm_loose(rel, raw)).hexdigest() in idx["loose"])):
            if official_css is None:
                official_css = _official_theme_css(project, st, od)
            if _norm_loose(rel, raw) in official_css:
                continue  # 승인된 공식 테마의 엔진 출력(탐색 후보 테마와 값이 같아도 공식 경로)
        if h in idx["exact"]:
            src = idx["exact"][h]
            out.append({"file": rel, "kind": "explore_copy", "same_as": src, "status": explore_status(st, src)})
            continue
        lo = _norm_loose(rel, raw)
        if lo and hashlib.sha256(lo).hexdigest() in idx["loose"]:
            src = idx["loose"][hashlib.sha256(lo).hexdigest()]
            out.append({"file": rel, "kind": "explore_copy", "same_as": src, "status": explore_status(st, src), "detail": "주석·공백·대소문자만 다름"})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        body = strip_comments(rel, text)
        if REF_RE.search(body):
            out.append({"file": rel, "kind": "explore_reuse"})
            continue
        for aid in sorted(set(re.findall(r"assets/(AST-\d{3})\.\w+", body))):
            a = od["assets"].get(aid)
            if a and not a["official"]:
                out.append({"file": rel, "kind": "asset_unapproved", "asset": aid, "detail": "자산 레지스트리 경로 참조(권리 미확인 또는 승인 VD 밖)"})
        css = _style_text(rel, text)
        if css:
            same = sorted({idx["rules"][r] for r in _css_rules(css) if r in idx["rules"]})
            n = sum(1 for r in _css_rules(css) if r in idx["rules"])
            if n >= PARTIAL_MIN_RULES:
                out.append({"file": rel, "kind": "explore_copy_partial", "same_as": same[0], "status": explore_status(st, same[0]),
                            "detail": f"시안 CSS 규칙 {n}개를 그대로 옮김"})
        used = sorted({cand_vars[v] for v in re.findall(r"(--[A-Za-z0-9_-]+)", body) if v in cand_vars})
        if used:
            out.append({"file": rel, "kind": "explore_token", "tokens": used,
                        "detail": "탐색 후보 테마에만 있는 토큰(04·공식 테마에 없음, ② 변경 요청 전)"})
    return out


MESSAGES = {
    "explore_copy": "디자인 탐색 파일({same_as}, {status})과 같은 내용입니다(explore_copy). 승인된 VD·테마로 새로 작성합니다",
    "design_data_invalid": "판정 근거 파일 {file}의 형식이 올바르지 않습니다(design_data_invalid — {detail}). 공식 디자인을 확인할 수 없어 차단합니다. 자동으로 고치지 않습니다(Git 이력에서 복원)",
    "explore_copy_partial": "디자인 탐색 시안 CSS({same_as}, {status})를 부분 복사했습니다(explore_copy_partial — {detail})",
    "explore_reuse": "design-explore를 참조합니다(explore_reuse{detail_sep}{detail}). 시안은 시각 참고만 합니다",
    "explore_token": "탐색 후보 토큰 {tokens}을 씁니다(explore_token). 공식 반영은 ② 변경 요청 → 04·테마 승인 후",
    "reference_asset_embedded": "레퍼런스 원본을 넣었습니다(reference_asset_embedded — {detail})",
    "asset_unapproved": "자산 {asset}은 공식 디자인이 아닙니다(asset_unapproved — {detail}). 권리 확인(explore-asset confirm) + 승인된 VD의 관련에 넣은 뒤 씁니다",
}
STATUS_LABEL = {"unselected_variant": "선택되지 않은 시안", "chosen_not_official": "선택됐지만 공식 디자인 아님 — 채택·승인 필요",
                "exploration_artifact": "탐색 작업 파일"}


def message(x: dict) -> str:
    d = dict(x)
    d["status"] = STATUS_LABEL.get(x.get("status"), x.get("status") or "")
    d["tokens"] = ", ".join(x.get("tokens") or [])
    d["detail"] = x.get("detail") or ""
    d["detail_sep"] = " — " if x.get("detail") else ""
    d.setdefault("same_as", "")
    d.setdefault("asset", "")
    return f"{x['file']}: " + MESSAGES[x["kind"]].format(**d)


def symlink_findings(project: Path, roots: list[str]) -> list[dict]:
    """root 아래 심볼릭 링크(파일·폴더)가 design-explore 안을 가리키면 explore_reuse(파일 목록에 폴더 링크가 빠지는 우회 방지)."""
    import os
    out = []
    ex = (project / EXPLORE_DIR).resolve()
    for r in roots:
        base = project / r
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "dist")]
            for name in dirnames + filenames:
                q = Path(dirpath) / name
                if q.is_symlink():
                    t = q.resolve()
                    if t == ex or ex in t.parents:
                        out.append({"file": str(q.relative_to(project)), "kind": "explore_reuse", "detail": f"design-explore를 가리키는 심볼릭 링크"})
    return out


# ---------------------------------------------------------------- UI Brief 근거(product-build)
def brief_sources(project: Path, screens: list[str]) -> dict:
    """UI Brief가 읽는 공식 디자인 근거. 승인 기록과 일치하는 VD·권리 확인된 자산만, 탐색 선택은 출처로만."""
    od = official_design(project)
    per = {}
    for s in screens:
        vds = [k for k, v in od["approved_vds"].items() if s in v["related"]]
        per[s] = {"assets": [{"id": aid, "file": a["file"], "sha256": a["sha256"], "kind": a["kind"], "role": a["role"], "vds": a["vds"]}
                             for aid, a in sorted(od["assets"].items()) if a["official"] and set(a["vds"]) & set(vds)]}
    return {"design_direction": {"approved": od["design_direction_approved"], "intact": od["design_direction_intact"],
                                 "revision": od["design_direction_revision"], "approved_vds": sorted(od["approved_vds"])},
            "screens": per,
            "exploration_provenance": {"use": "source_only", "records": od["exploration_provenance"],
                                       "note": "탐색 선택은 출처 기록입니다. 구현 근거는 승인된 VD·테마·자산뿐이며 후보(theme.candidate·vd-candidates)는 쓰지 않습니다."}}
