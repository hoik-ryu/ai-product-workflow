"""/product-design 변경 요청(Change Request)과 승인 패치(Amendment) — M1 (reference/change-request.md).

- 변경 유형 A–E를 분류하고(읽기 전용 `change plan`), Type B(경미한 패치)만 CR로 실행합니다.
- 기존 승인 기록(approved·submitted·last_approved·history)은 바꾸지 않습니다. 승인된 패치는 `changes.chain`에 덧붙이고,
  **유효 승인 기준(effective baseline)** = 단계 승인 기록 + 그 승인 revision을 기준으로 한 패치 체인 입니다.
- 유효 승인 기준 계산은 이 모듈의 `effective()` 하나뿐입니다. cross_verify·require_valid·official_design·check·status와
  /product-build(status 출력의 `changes`)가 모두 이 결과를 씁니다.
- 체인이 깨지면(삭제·순서 변경·위조·기준 불일치) 조용히 이전 기준으로 돌아가지 않고 `amendment_chain_broken`으로 차단합니다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import uuid
from pathlib import Path

from pd_core import (
    DD_FILE, DESIGN_ID_RE, ID_RE, IA_FILE, FLOWS_FILE, PLANNING_FILES, PREVIEW_DIR, PREVIEW_MANIFEST, PREVIEW_TREE_KEY, REVIEW_FILE,
    SCREENS_FILE, SEM_ALGO, SPEC_FILES, STAGE_ARTIFACTS, TRACE_FILE, UISYS_FILE, UXP_FILE, WORKFLOW_STATE_REL,
    add_history, block, blocks_by_heading, design_context, emit, field_line, gate_or_block, detect_outdated, git, module_specifiers,
    now, parse_css_vars, parse_tokens, preview_files, preview_semantic_hash, preview_tree_hash, read_text, rollback_on_failure,
    save_state, screen_info, sem_normalize, sha256_bytes, sha256_file, strip_comments, strip_fences, table_rows, workflow_of, require_state,
    STATE_REL,
)
import pd_pixel as PX
from pd_assets import _entry_sha as entry_sha, registry_rel  # 자산 레지스트리 경로·항목 지문은 pd_assets 정의를 그대로 씀

TYPES = ("A", "B", "C", "D", "E")
RANK = {t: i for i, t in enumerate(TYPES)}
TYPE_LABEL = {"A": "Implementation Fix(구현 수정)", "B": "Minor Patch(경미한 패치)", "C": "Scoped Design Change(범위 한정 디자인 변경)",
              "D": "Design System Change(디자인 시스템 변경)", "E": "Requirement / Functional Change(요구사항·기능 변경)"}
ACTIVE = ("open", "in_progress", "verified", "awaiting_confirmation", "escalated")
M1_EXECUTABLE = ("B",)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")
CODE_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".css", ".html", ".json")
ASSET_META_KEYS = ("kind", "role", "source", "refs", "depicts", "fallback", "format")
PLANNING_REF_RE = r"\b(?:US|AC|FR|NFR)-\d{3}\b|\bFLOW-\d{3}|\bC-\d{2}\b"
E_KINDS = ("permission", "flow", "acceptance", "data_policy", "feature", "behavior")
D_KINDS = ("component_contract", "navigation", "token_name", "token_value")
C_KINDS = ("layout", "placement", "dimension", "style")
ASSET_B_OPS = ("mask", "edge", "matte")
ASSET_C_OPS = ("ratio", "composition", "crop", "replace", "new")


def enabled(st: dict) -> bool:
    return bool(((st.get("config") or {}).get("changes") or {}).get("enabled"))


def max_type(*ts) -> str:
    ts = [t for t in ts if t]
    return max(ts, key=lambda t: RANK[t]) if ts else "A"


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(obj) -> str:
    return hashlib.sha256(canon(obj)).hexdigest()


def amendment_digest(a: dict) -> str:
    return digest({k: v for k, v in a.items() if k != "digest"})


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# ================================================================ 체인·유효 승인 기준(단일 구현)
def chain_errors(st: dict) -> list[str]:
    ch = st.get("changes")
    if ch is None:
        return []
    if not isinstance(ch, dict):
        return ["changes가 객체가 아닙니다"]
    chain = ch.get("chain")
    items = ch.get("items")
    head = ch.get("head")
    if not isinstance(chain, list) or not isinstance(items, dict) or not isinstance(head, dict):
        return ["changes.chain·items·head 형식이 올바르지 않습니다"]
    errs, prev, seen = [], None, set()
    for i, a in enumerate(chain):
        if not isinstance(a, dict):
            errs.append(f"chain[{i}]가 객체가 아닙니다")
            continue
        aid = a.get("id")
        if a.get("seq") != i + 1:
            errs.append(f"{aid}: 순서 번호(seq {a.get('seq')})가 위치({i + 1})와 다릅니다(순서 변경·삭제 의심)")
        if a.get("prev") != prev:
            errs.append(f"{aid}: 이전 digest가 직전 패치와 이어지지 않습니다(삭제·순서 변경·병합 충돌 의심)")
        if amendment_digest(a) != a.get("digest"):
            errs.append(f"{aid}: 내용이 digest와 다릅니다(수정·위조 의심)")
        if aid in seen:
            errs.append(f"{aid}: 같은 패치 ID가 두 번 있습니다")
        seen.add(aid)
        cr = items.get(a.get("cr") or "")
        if not isinstance(cr, dict) or cr.get("uid") != a.get("cr_uid") or cr.get("status") != "approved" \
                or cr.get("amendment") != aid or cr.get("amendment_digest") != a.get("digest"):
            errs.append(f"{aid}: 연결된 변경 요청({a.get('cr')})의 승인 기록과 맞지 않습니다")
        prev = a.get("digest")
    if head.get("count") != len(chain) or head.get("digest") != prev:
        errs.append(f"changes.head(count {head.get('count')})가 체인({len(chain)}개)과 맞지 않습니다(패치 삭제·추가 의심)")
    for cid, cr in items.items():
        if isinstance(cr, dict) and cr.get("status") == "approved" and cr.get("amendment") not in seen:
            errs.append(f"{cid}: 승인된 변경 요청의 패치({cr.get('amendment')})가 체인에 없습니다(삭제 의심)")
    hist_digests = {m.group(1) for h in st.get("history") or [] if h.get("event") == "change_approved"
                    for m in [re.search(r"digest ([0-9a-f]{12})", h.get("note") or "")] if m}
    for a in chain:
        if isinstance(a, dict) and str(a.get("digest") or "")[:12] not in hist_digests:
            errs.append(f"{a.get('id')}: history에 승인 기록(change_approved)이 없습니다")
    return errs


def effective(st: dict) -> dict:
    """유효 승인 기준. records[stage]는 승인 기록에 같은 승인 revision을 기준으로 한 패치를 순서대로 적용한 가상 기록입니다(원본 불변).
    체인에 문제가 있으면 ok False와 errors를 돌려주고, records는 원본 승인 기록 그대로입니다(호출자가 차단)."""
    errs = chain_errors(st)
    chain = ((st.get("changes") or {}).get("chain") or []) if not errs else []
    records, applied = {}, {}
    for stage, s in (st.get("stages") or {}).items():
        rec = s.get("approved") if s.get("status") == "approved" and isinstance(s.get("approved"), dict) else None
        if rec is None:
            continue
        r = None
        for a in chain:
            sd = (a.get("stages") or {}).get(stage)
            if not sd or sd.get("base_revision") != rec.get("revision"):
                continue
            r = r if r is not None else copy.deepcopy(rec)
            for rel, t in (sd.get("files") or {}).items():
                if r["hashes"].get(rel) != t.get("before"):
                    errs.append(f"{a['id']}: {stage}의 {rel} 이전 해시가 유효 기준과 다릅니다(기준 불일치)")
                r["hashes"][rel] = t.get("after")
            if sd.get("semantic"):
                r["semantic_tree_hash"] = sd["semantic"].get("after")
                r["semantic_algo"] = SEM_ALGO
            for aid, t in (sd.get("assets") or {}).items():
                snap = r.setdefault("assets", {})
                if snap.get(aid) != t.get("before"):
                    errs.append(f"{a['id']}: {stage}의 자산 {aid} 이전 스냅샷이 유효 기준과 다릅니다(기준 불일치)")
                if t.get("after") is None:
                    snap.pop(aid, None)
                else:
                    snap[aid] = t["after"]
            applied.setdefault(stage, []).append(a["id"])
        records[stage] = r if r is not None else rec
    if errs:
        records = {k: s["approved"] for k, s in (st.get("stages") or {}).items()
                   if s.get("status") == "approved" and isinstance(s.get("approved"), dict)}
        applied = {}
    return {"ok": not errs, "errors": errs, "records": records, "applied": applied,
            "digest": digest(records), "head": copy.deepcopy((st.get("changes") or {}).get("head") or {"count": 0, "digest": None})}


def effective_record(st: dict, stage: str, eff: dict | None = None) -> dict | None:
    eff = eff or effective(st)
    return eff["records"].get(stage)


# ================================================================ 산출물 스냅샷·파일 차이
def load_registry(project: Path, st: dict) -> dict:
    p = project / registry_rel(st)
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return d.get("assets") if isinstance(d, dict) and isinstance(d.get("assets"), dict) else {}


def artifact_files(project: Path, st: dict) -> dict:
    """승인 산출물 파일과 현재 해시: 디자인 문서 00–07, 프리뷰 트리 파일, 테마, 자산 레지스트리·자산 파일, 기획 문서·state.yaml."""
    rels = set(STAGE_ARTIFACTS["ux_planning"]) | set(SPEC_FILES) | {REVIEW_FILE, DD_FILE} | set(PLANNING_FILES) | {WORKFLOW_STATE_REL}
    rels |= set(preview_files(project))
    theme = (st.get("config") or {}).get("theme_file")
    if theme:
        rels.add(theme)
    rels.add(registry_rel(st))
    for a in load_registry(project, st).values():
        if isinstance(a, dict) and a.get("file"):
            rels.add(str(a["file"]))
    return {rel: (sha256_file(project / rel) if (project / rel).is_file() else None) for rel in sorted(rels)}


def registry_entries(project: Path, st: dict) -> dict:
    return {aid: entry_sha(a) for aid, a in load_registry(project, st).items() if isinstance(a, dict)}


def git_bytes(project: Path, rev: str, rel: str) -> bytes | None:
    p = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=project, capture_output=True)
    return p.stdout if p.returncode == 0 else None


def old_bytes_fn(project: Path, rev: str, base_files: dict):
    """기준 시점 파일 내용(git rev에서 읽고 기록된 sha256과 같을 때만). 확인할 수 없으면 None."""
    cache: dict[str, bytes | None] = {}

    def get(rel: str) -> bytes | None:
        if rel not in cache:
            b = git_bytes(project, rev, rel) if rev else None
            want = base_files.get(rel) if base_files is not None else None
            if b is not None and want is not None and sha256_bytes(b) != want:
                b = None
            if b is None and want is not None and (project / rel).is_file() and sha256_file(project / rel) == want:
                b = (project / rel).read_bytes()  # 바뀌지 않은 파일은 작업 트리에서
            cache[rel] = b
        return cache[rel]
    return get


# ================================================================ 프리뷰 의존 그래프(화면 영향)
def _resolve(project: Path, base_rel: str, spec: str) -> str | None:
    if not spec.startswith("."):
        return None
    base = (project / base_rel).parent
    cand = (base / spec)
    for c in [cand] + [Path(str(cand) + e) for e in (".tsx", ".ts", ".jsx", ".js", ".css")] + [cand / f"index{e}" for e in (".tsx", ".ts", ".js")]:
        try:
            if c.is_file():
                return str(c.resolve().relative_to(project.resolve()))
        except ValueError:
            return None
    return None


def preview_screen_closures(project: Path) -> dict[str, set[str]]:
    """manifest의 화면별 파일에서 따라간 정적 import 파일 집합."""
    try:
        man = json.loads(read_text(project, PREVIEW_MANIFEST) or "{}")
    except json.JSONDecodeError:
        return {}
    out = {}
    for sid, m in (man.get("screens") or {}).items():
        if not isinstance(m, dict) or not m.get("file"):
            continue
        root = f"{PREVIEW_DIR}/{m['file']}"
        seen, todo = set(), [root]
        while todo:
            rel = todo.pop()
            if rel in seen or not (project / rel).is_file():
                continue
            seen.add(rel)
            if rel.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".css")):
                specs, _ = module_specifiers((project / rel).read_text(encoding="utf-8", errors="replace"))
                specs += re.findall(r"url\(\s*['\"]?(\.[^'\")]+)['\"]?\s*\)", (project / rel).read_text(encoding="utf-8", errors="replace"))
                for sp in specs:
                    r = _resolve(project, rel, sp)
                    if r:
                        todo.append(r)
        out[sid] = seen
    return out


def screens_for_preview_file(project: Path, rel: str, closures: dict) -> list[str] | None:
    hits = sorted(s for s, files in closures.items() if rel in files)
    return hits or None  # 어느 화면 closure에도 없으면 공통(전체 화면 영향)으로 취급 → None


# ================================================================ 문서 차이 판정
def _headings(t: str) -> list[str]:
    return [ln for ln in t.splitlines() if re.match(r"^#{1,6} ", ln)]


def _tables(t: str) -> list[str]:
    return [ln.strip() for ln in t.splitlines() if ln.lstrip().startswith("|")]


def _ids(t: str) -> list[str]:
    return sorted(set(re.findall(DESIGN_ID_RE + "|" + ID_RE + r"|AST-\d{3}|VD-\d{3}", t)))


def _front(t: str) -> str:
    m = re.match(r"^---\n.*?\n---\n", t, re.S)
    return m.group(0) if m else ""


def prose_only(old: str, new: str) -> bool:
    """제목·표·ID·front matter가 같고 문장만 바뀜(오탈자 후보). 의미 변경 여부는 사람이 확인해야 합니다."""
    o, n = strip_comments(old), strip_comments(new)
    return _front(old) == _front(new) and _headings(o) == _headings(n) and _tables(o) == _tables(n) and _ids(o) == _ids(n)


def classify_doc(rel: str, old: str | None, new: str | None, ctx: dict) -> dict:
    it = {"path": rel, "kind": "doc"}
    if old is None or new is None:
        return it | _r("D", "needs_review", "기준 시점 내용을 확인할 수 없거나 문서가 추가·삭제되었습니다(보수적 처리).")
    if rel in PLANNING_FILES or rel == WORKFLOW_STATE_REL:
        return it | _r("E", "classified", "기획 문서·state.yaml 변경은 요구사항 변경입니다(/product-start 재검토).")
    o, n = strip_fences(strip_comments(old)), strip_fences(strip_comments(new))
    if rel == UISYS_FILE:
        if parse_tokens(old) != parse_tokens(new):
            return it | _r("D", "classified", "04 토큰 표(이름·값)가 바뀝니다(전역 디자인 토큰).")
        if blocks_by_heading(o, 3, "CMP") != blocks_by_heading(n, 3, "CMP"):
            return it | _r("D", "classified", "04 공통 컴포넌트 계약(CMP 블록)이 바뀝니다.")
    if rel == IA_FILE and table_rows(o, r"SCR-\d{3}") != table_rows(n, r"SCR-\d{3}"):
        return it | _r("D", "classified", "01 IA 라우트 표(내비게이션 구조)가 바뀝니다.")
    if rel == FLOWS_FILE and _tables(o) != _tables(n):
        return it | _r("E", "classified", "03 화면 흐름(사용자 흐름)이 바뀝니다.")
    if rel == TRACE_FILE and _tables(o) != _tables(n):
        return it | _r("E", "classified", "05 추적성(US·AC ↔ 화면) 대응이 바뀝니다(AC 계약).")
    if rel == UXP_FILE and blocks_by_heading(o, 3, "UXD") != blocks_by_heading(n, 3, "UXD") and not prose_only(old, new):
        return it | _r("D", "conditional", "00 UX 결정이 바뀝니다(UX Planning부터 재검토).", alt=["E"])
    if rel == SCREENS_FILE:
        ob, nb = blocks_by_heading(o, 2, "SCR"), blocks_by_heading(n, 2, "SCR")
        if set(ob) != set(nb):
            return it | _r("E", "classified", "02 화면이 추가·삭제됩니다.")
        changed = sorted(k for k in ob if ob[k] != nb[k])
        it["screens"] = changed
        for k in changed:
            if _tables(ob[k]) != _tables(nb[k]):
                return it | _r("E", "classified", f"{k}의 상태 표(화면 상태·동작)가 바뀝니다(행동 계약).")
            if field_line(ob[k], "추적") != field_line(nb[k], "추적"):
                return it | _r("E", "classified", f"{k}의 추적(US·AC·FLOW)이 바뀝니다.")
            if field_line(ob[k], "경로") != field_line(nb[k], "경로"):
                return it | _r("D", "classified", f"{k}의 경로(내비게이션)가 바뀝니다.")
        if changed and not prose_only(old, new):
            return it | _r("C", "conditional", f"{', '.join(changed)} 화면 명세의 표현·배치가 바뀝니다. 동작·정보가 바뀌면 E입니다.", alt=["E"])
    if rel == DD_FILE:
        succ = ctx.get("successors") or {}
        sub = new
        for x, y in succ.items():
            sub = sub.replace(y, x)
        if succ and sub == old:
            return it | _r("B", "classified", f"07에서 자산 참조만 후속 자산으로 바뀝니다({', '.join(f'{x}→{y}' for x, y in succ.items())}).",
                           extra={"successor_ref": dict(succ)})
        osec = re.search(r"## 4\..*?(?=\n## )", o, re.S)
        nsec = re.search(r"## 4\..*?(?=\n## )", n, re.S)
        if (osec and osec.group(0)) != (nsec and nsec.group(0)):
            return it | _r("D", "classified", "07 정책 값(density·touch·safe_area)이 바뀝니다(전역 시각 정책).")
        ov, nv = blocks_by_heading(o, 3, "VD"), blocks_by_heading(n, 3, "VD")
        cv = sorted(k for k in set(ov) | set(nv) if ov.get(k) != nv.get(k))
        if cv and not prose_only(old, new):
            scr = sorted({s for k in cv for s in re.findall(r"SCR-\d{3}", field_line(nv.get(k) or ov.get(k) or "", "관련"))})
            it["screens"] = scr or None
            return it | _r("C", "classified", f"07 시각 결정({', '.join(cv)})이 바뀝니다.")
    sem = text_semantics(rel, old, new, ctx)
    if sem:
        return it | sem
    if prose_only(old, new):
        return it | _r("B", "conditional", "제목·표·ID가 같고 문장만 바뀝니다(오탈자 후보). 의미가 바뀌지 않았는지 사람이 확인해야 합니다.", alt=["C"])
    return it | _r("D", "needs_review", "문서 구조가 바뀌었지만 규칙으로 판정하지 못했습니다(보수적 처리).")


# 정책·권한·범위를 바꾸는 단어(오탈자 수정으로 위장한 기능·정책 변경 감지). 바뀐 단어에 하나라도 있으면 E(needs_review).
POLICY_WORDS = ("필수", "선택", "금지", "허용", "가능", "불가", "않", "없", "만", "모든", "전체", "권한", "관리자", "회원", "비회원",
                "로그인", "인증", "삭제", "공개", "비공개", "승인", "거부", "차단", "결제", "환불", "개인정보", "저장", "보관",
                "must", "should", "not", "only", "all", "never", "admin", "allow", "deny", "required", "optional", "delete", "public", "private")
ROLE_FIELDS = ("역할", "권한", "접근")


def _word_diff(old: str, new: str) -> tuple[list[str], list[str]]:
    import difflib
    ow, nw = re.findall(r"\w+|[^\w\s]", old), re.findall(r"\w+|[^\w\s]", new)
    rem, add = [], []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=ow, b=nw, autojunk=False).get_opcodes():
        if op != "equal":
            rem += ow[a1:a2]
            add += nw[b1:b2]
    return rem, add


def text_semantics(rel: str, old: str, new: str, ctx: dict) -> dict | None:
    """본문 문장 변경의 의미 판정: (1) 역할·권한 필드 변경 → E, (2) 정책 단어 변경 → E, (3) 숫자 변경 → C,
    (4) 요청이 적은 오탈자(from → to) 치환과 실제 차이가 정확히 같고 위 항목이 없으면 B(작업 범위 동의로 충분, 사전 확인 불필요)."""
    o, n = strip_comments(old), strip_comments(new)
    ol, nl = o.splitlines(), n.splitlines()
    if len(ol) == len(nl):
        for a, b in zip(ol, nl):
            if a != b and any(re.match(rf"^\s*-\s*\*\*{f}", a) for f in ROLE_FIELDS):
                return _r("E", "classified", f"역할·권한 필드가 바뀝니다: '{a.strip()[:60]}' → '{b.strip()[:60]}'(접근 제어 변경)")
    rem, add = _word_diff(o, n)
    if not rem and not add:
        return None
    hit = sorted({w for w in rem + add for pw in POLICY_WORDS if pw in w.lower()} )
    if hit:
        return _r("E", "needs_review", f"정책·권한·범위 단어가 바뀝니다({', '.join(hit[:6])}). 오탈자가 아니라 기능·정책 변경일 수 있습니다(보수적 처리).")
    if any(re.search(r"\d", w) for w in rem + add):
        return _r("C", "conditional", "숫자(명세 값)가 바뀝니다. 오탈자가 아니라 명세 변경일 수 있습니다.", alt=["B"])
    for doc, frm, to in ctx.get("typos") or []:
        if doc in (None, rel) and old.count(frm) == 1 and old.replace(frm, to) == new:
            import difflib
            ratio = difflib.SequenceMatcher(a=frm, b=to).ratio()
            if ratio >= 0.6 and len(frm) <= 80:
                return _r("B", "classified", f"요청한 오탈자 치환('{frm}' → '{to}')과 실제 차이가 정확히 같습니다(정책·권한·숫자 변경 없음).",
                          extra={"typo_verified": {"from": frm, "to": to, "similarity": round(ratio, 2)}})
    return None


def _r(t: str, status: str, reason: str, alt=None, extra=None) -> dict:
    d = {"minimum": t, "status": status, "reasons": [reason], "alternatives": list(alt or [])}
    if extra:
        d.update(extra)
    return d


# ================================================================ 자산 판정
def asset_analysis(old_entry: dict | None, new_entry: dict | None, old_raw: bytes | None, new_raw: bytes | None) -> dict:
    meta_changed = sorted(k for k in ASSET_META_KEYS if (old_entry or {}).get(k) != (new_entry or {}).get(k))
    lic_old = ((old_entry or {}).get("rights") or {}).get("license")
    lic_new = ((new_entry or {}).get("rights") or {}).get("license")
    if lic_old != lic_new:
        meta_changed.append("rights.license")
    out = {"meta_changed": meta_changed}
    if old_raw is None or new_raw is None:
        return out | _r("C", "needs_review", "전후 이미지 내용을 확인할 수 없습니다(기계적 판정 불가 → 상위 유형).")
    px = PX.compare(old_raw, new_raw)
    out["pixels"] = px
    if meta_changed:
        return out | _r("C", "classified", f"자산 계약(역할·출처·권리·참조 등)이 바뀝니다: {', '.join(meta_changed)}")
    if not px["analyzable"]:
        return out | _r("C", "needs_review", f"픽셀 비교를 할 수 없습니다({px['reason']}). 계약 불변을 확인할 수 없어 Type B로 확정하지 않습니다.")
    if px["verdict"] == "dimensions_changed":
        return out | _r("C", "classified", "이미지 크기·비율이 바뀝니다(구도·비율 변경).")
    if px["verdict"] == "interior":
        return out | _r("C", "classified", f"가장자리 띠({px['edge_band_px']}px) 밖 내부 픽셀 {px['interior_changed']}개가 바뀝니다(구도·내용 변경 가능성).")
    if px["verdict"] == "identical":
        return out | _r("B", "classified", "픽셀이 같습니다(인코딩만 다름).")
    return out | _r("B", "classified", f"가장자리 띠({px['edge_band_px']}px) 안 픽셀 {px['pixels_changed']}개만 바뀝니다"
                                        f"(RGB 최대 {px['rgb_max_delta']}, 알파 최대 {px['alpha_max_delta']}). 크기·비율·내부 구도 동일.")


def vd_screens_for_asset(project: Path, aid: str) -> set[str]:
    text = strip_fences(strip_comments(read_text(project, DD_FILE)))
    out = set()
    for b in blocks_by_heading(text, 3, "VD").values():
        rel = field_line(b, "관련")
        if aid in rel:
            out |= set(re.findall(r"SCR-\d{3}", rel))
    return out


def asset_screens(project: Path, aid: str, entry: dict | None, preview_hits: list[str], closures: dict) -> list[str] | None:
    s = vd_screens_for_asset(project, aid)
    s |= {x.split(":")[0] for x in ((entry or {}).get("refs") or []) if re.match(r"SCR-\d{3}", x)}
    for rel in preview_hits:
        hs = screens_for_preview_file(project, rel, closures)
        if hs is None:
            return None
        s |= set(hs)
    return sorted(s) if s else None


# ================================================================ 요청(사실) 판정
def classify_fact_type(f: dict, ctx: dict) -> dict:
    kind = f.get("kind")
    refs = [x for x in [f.get("screen"), f.get("component")] + list(f.get("refs") or []) if x]
    planning_refs = [r for r in refs if re.match(r"(?:US|AC|FR|NFR)-\d{3}|FLOW-\d{3}|C-\d{2}", r)]
    out = {"kind": kind, "refs": refs, "asset": f.get("asset"), "tokens": f.get("tokens") or ([f["token"]] if f.get("token") else [])}
    unknown = [r for r in refs if not _ref_known(ctx, r)]
    if unknown:
        return out | _r("E" if planning_refs else "D", "needs_review", f"승인 문서에서 찾을 수 없는 참조가 있습니다: {', '.join(unknown)} (보수적 처리)")
    if kind in E_KINDS:
        return out | _r("E", "classified", "기능·권한·흐름·데이터 정책·버튼 동작 등 행동 계약 변경은 화면 수와 관계없이 Type E입니다.")
    if kind == "info":
        op = f.get("op")
        if op in ("reorder", "relocate", "restyle"):
            return out | _r("C", "classified", "기존 정보의 표시 위치·시각 표현 변경입니다.")
        if op == "relabel":
            return out | _r("C", "conditional", "표시 문구 변경입니다. 의미(정보)가 바뀌면 E입니다.", alt=["E"])
        return out | _r("E", "classified", f"정보 항목 {op or '변경'}은 비즈니스 정보 계약 변경입니다.")
    if kind in D_KINDS:
        return out | _r("D", "classified", "디자인 토큰·공통 컴포넌트 계약·공통 내비게이션 변경입니다.")
    if kind in C_KINDS:
        return out | _r("C", "classified", "기존 기능을 유지하는 특정 화면·컴포넌트의 배치·크기·시각 표현 변경입니다.")
    if kind == "asset_patch":
        op = f.get("op")
        if op in ASSET_B_OPS:
            return out | _r("B", "classified", "같은 이미지의 가장자리·마스크 보정 요청입니다(실제 픽셀 비교로 다시 확인).")
        if op in ASSET_C_OPS:
            return out | _r("C", "classified", "이미지 비율·구도·교체는 디자인 계약 변경입니다.")
        return out | _r("C", "conditional", "자산 변경 내용이 불명확합니다(retouch 등). 픽셀 비교로 가장자리만 바뀐 것이 확인되면 B입니다.", alt=["B"])
    if kind == "typo":
        if f.get("from") and f.get("to") is not None:  # 정확한 치환을 적은 요청: 실제 차이로 판정(일치하면 확정, 아니면 그때 확인)
            return out | _r("B", "conditional", "오탈자 치환 요청입니다. 실제 차이가 요청 치환과 같은지 엔진이 확인합니다.", alt=["C"], extra={"deferrable": True})
        return out | _r("B", "conditional", "오탈자 수정 요청입니다. 의미가 바뀌지 않는지 사람이 확인해야 합니다.", alt=["C"])
    if kind in ("render_fix", "defect", "implementation_note", "test_fix"):
        if f.get("target") == "preview":
            return out | _r("B", "conditional", "승인된 프리뷰의 렌더링 결함 수정입니다. 실제 차이(CSS 속성 분류)로 계약 유지 여부를 판정하고, "
                                                "판정이 안 되면 그때 사용자 확인을 받습니다.", alt=["C"], extra={"deferrable": bool(f.get("files") or f.get("screen"))})
        return out | _r("A", "classified", "승인된 명세·디자인에 맞추는 제품 코드·테스트 수정입니다(승인 산출물 불변이어야 함).")
    if kind == "notation":
        return out | _r("E", "needs_review", "표기 변경은 보이는 글자인지 정보 순서인지 규칙으로 정할 수 없습니다(보수적 처리).")
    if kind == "exploration_choice":
        asp = f.get("aspect")
        return out | _r({"structure": "D", "composition": "C", "theme_value": "D", "asset": "C"}.get(asp, "D"),
                        "classified" if asp in ("structure", "composition", "theme_value", "asset") else "needs_review", f"탐색 선택({asp}) 반영")
    return out | _r("E" if planning_refs else "D", "needs_review", f"알 수 없는 사실 종류입니다: {kind} (보수적 처리)")


def _ref_known(ctx: dict, ref: str) -> bool:
    if re.fullmatch(r"AST-\d{3}", ref):
        return ref in ctx.get("assets", {})
    if re.fullmatch(r"VD-\d{3}", ref):
        return ref in ctx.get("vds", set())
    from pd_core import _ref_exists
    return _ref_exists(ctx, ref)


def load_request(path: Path) -> dict:
    try:
        req = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        block("invalid_request", f"변경 요청 파일을 읽을 수 없습니다: {e}")
    if not isinstance(req, dict) or not isinstance(req.get("items"), list) or not req["items"]:
        block("invalid_request", "변경 요청은 {\"schema\": \"design-change-request/v1\", \"items\": [{\"id\", \"summary\", \"facts\": [...]}]} 형식입니다.")
    return req


# ================================================================ 종합 판정(plan)
def context(project: Path, st: dict) -> dict:
    ctx = design_context(project)
    ctx["assets"] = load_registry(project, st)
    ctx["vds"] = set(blocks_by_heading(strip_fences(strip_comments(read_text(project, DD_FILE))), 3, "VD"))
    return ctx


def successors_from(req_items: list, base_reg: dict | None, cur_reg: dict, declared: dict | None = None) -> tuple[dict, list[str]]:
    """후속 자산 연결 {이전 ID: 새 ID}. 요청의 to가 없으면 기준 이후 새로 등록된 자산이 하나일 때만 연결합니다."""
    succ = dict(declared or {})
    notes = []
    want = [f for it in req_items for f in it.get("facts") or [] if f.get("kind") == "asset_patch" and f.get("successor")]
    new_ids = sorted(set(cur_reg) - set(base_reg)) if base_reg is not None else []
    for f in want:
        x = f.get("asset")
        if x in succ or base_reg is None:
            continue
        if f.get("to"):
            succ[x] = f["to"]
        elif len(new_ids) == 1:
            succ[x] = new_ids[0]
            notes.append(f"{x}의 후속 자산을 기준 이후 새로 등록된 {new_ids[0]}로 연결했습니다.")
        elif new_ids:
            notes.append(f"{x}의 후속 자산 후보가 여러 개입니다({', '.join(new_ids)}). 요청 파일의 to로 지정하세요.")
    return succ, notes


def plan(project: Path, st: dict, req_items: list, base_files: dict | None, base_reg: dict | None, rev: str | None,
         declared_succ: dict | None = None, scope: dict | None = None, exclude: tuple[set, set] = (set(), set())) -> dict:
    """요청 사실 + (있으면) 기준 대비 실제 파일 차이로 유형·영향 범위·필요 승인·검증을 계산합니다(읽기 전용)."""
    ctx = context(project, st)
    cur_reg_entries = load_registry(project, st)
    succ, notes = successors_from(req_items, base_reg, cur_reg_entries, declared_succ)
    ctx["successors"] = succ
    ctx["typos"] = [(f.get("doc"), f.get("from"), f.get("to")) for it in req_items for f in it.get("facts") or []
                    if isinstance(f, dict) and f.get("kind") == "typo" and f.get("from") and f.get("to") is not None]
    items = []
    for it in req_items:
        facts = [classify_fact_type(f if isinstance(f, dict) else {"kind": None}, ctx) for f in (it.get("facts") or [{"kind": None}])]
        items.append({"id": it.get("id"), "summary": it.get("summary", ""), "facts": facts, "minimum": max_type(*[f["minimum"] for f in facts]),
                      "status": _worst([f["status"] for f in facts])})
    diff = diff_items(project, st, base_files, base_reg, rev, ctx, succ, exclude) if base_files is not None else {"items": [], "files": [], "outside": []}
    req_min = max_type(*[i["minimum"] for i in items]) if items else "A"
    diff_min = max_type(*[i["minimum"] for i in diff["items"]]) if diff["items"] else None
    minimum = max_type(req_min, diff_min)
    # 요청만으로는 결과를 알 수 없지만 대상이 구체적인 사실(파일·화면을 지정한 렌더링 보정, 정확한 오탈자 치환)은 작업 전에 묻지 않고
    # 실제 차이로 판정합니다(deferrable). 실제 차이가 여전히 판정 불가면 그때(제출 전) 확인을 받습니다.
    statuses = [f["status"] for i in items for f in i["facts"] if not f.get("deferrable")] + [i["status"] for i in diff["items"]]
    alts = sorted({a for i in items for f in i["facts"] for a in f["alternatives"]} | {a for i in diff["items"] for a in i["alternatives"]},
                  key=lambda t: RANK[t])
    possible = sorted({minimum} | {a for a in alts if RANK[a] > RANK[minimum]} | {t for t in TYPES if RANK[t] > RANK[minimum]}, key=lambda t: RANK[t])
    pre_reasons = []
    if any(s in ("conditional", "needs_review") for s in statuses):
        pre_reasons.append("판정이 확정되지 않은 사실·변경이 있습니다(conditional·needs_review).")
    if diff_min and RANK[diff_min] > RANK[req_min]:
        pre_reasons.append(f"실제 파일 차이가 요청보다 높은 유형({diff_min})을 요구합니다.")
    sc = impact_scope(project, st, items, diff, succ, scope)
    reasons = [r for i in items for f in i["facts"] for r in f["reasons"]] + [f"{d['path']}: {r}" for d in diff["items"] for r in d["reasons"]]
    out = {"type": {"recommended": minimum, "minimum": minimum, "possible": possible, "labels": {t: TYPE_LABEL[t] for t in possible},
                    "reasons": reasons},
           "pre_confirmation_required": bool(pre_reasons), "pre_confirmation_reasons": pre_reasons,
           "items": items, "diff": diff["items"], "changed_files": diff["files"], "outside_artifacts": diff["outside"],
           "successors": succ, "scope": sc, "notes": notes}
    out["route"] = route(minimum, sc)
    out["required"] = required(minimum, sc, diff)
    return out


def _worst(statuses: list[str]) -> str:
    for s in ("needs_review", "conditional"):
        if s in statuses:
            return s
    return "classified"


def diff_items(project: Path, st: dict, base_files: dict, base_reg: dict | None, rev: str | None, ctx: dict, succ: dict,
               exclude: tuple[set, set] = (set(), set())) -> dict:
    cur = artifact_files(project, st)
    changed = sorted(r for r in set(base_files) | set(cur) if base_files.get(r) != cur.get(r) and r not in exclude[0])
    get_old = old_bytes_fn(project, rev or "", base_files)
    reg_now = load_registry(project, st)
    reg_old = {}
    raw_old_reg = get_old(registry_rel(st))
    if raw_old_reg is not None:
        try:
            reg_old = (json.loads(raw_old_reg.decode("utf-8")).get("assets") or {})
        except (ValueError, AttributeError):
            reg_old = {}
    elif base_reg:
        reg_old = None  # 이전 레지스트리 내용 확인 불가
    asset_files = {str(a.get("file")): aid for aid, a in list((reg_old or {}).items()) + list(reg_now.items()) if isinstance(a, dict) and a.get("file")}
    closures = preview_screen_closures(project)
    items = []
    # 자산 항목(레지스트리 기준)
    reg_changed = sorted(aid for aid in set(reg_old or {}) | set(reg_now)
                         if entry_sha((reg_old or {}).get(aid) or {}) != entry_sha(reg_now.get(aid) or {})) if reg_old is not None else sorted(reg_now)
    reg_changed = [a for a in reg_changed if a not in exclude[1]]
    inv = {y: x for x, y in succ.items()}
    asset_items = {}
    for aid in reg_changed:
        old_e, new_e = (reg_old or {}).get(aid), reg_now.get(aid)
        if aid in succ.values() and old_e is None:  # 후속 자산: 이전 자산과 비교
            x = inv[aid]
            prev_e = (reg_old or {}).get(x) or reg_now.get(x)
            o_raw = get_old(str(prev_e.get("file"))) if prev_e else None
            n_raw = (project / str(new_e["file"])).read_bytes() if new_e and (project / str(new_e.get("file") or "")).is_file() else None
            res = asset_analysis(prev_e, new_e, o_raw, n_raw)
            res["reasons"] = [f"{x}의 후속 자산 {aid}: " + res["reasons"][0]]
            asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_successor", "asset": aid, "successor_of": x} | res
        elif aid in succ and new_e is not None and old_e is not None and entry_sha(old_e) == entry_sha(new_e):
            continue
        elif old_e is None:
            asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_new", "asset": aid} | _r("C", "classified", f"새 자산 {aid} 추가(후속 자산 연결 없음).")
        elif new_e is None:
            asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_removed", "asset": aid} | _r("C", "classified", f"자산 {aid} 삭제.")
        else:
            o_raw = get_old(str(old_e.get("file")))
            n_raw = (project / str(new_e["file"])).read_bytes() if (project / str(new_e.get("file") or "")).is_file() else None
            if old_e.get("sha256") == new_e.get("sha256") and not [k for k in ASSET_META_KEYS if old_e.get(k) != new_e.get(k)]:
                asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_rights", "asset": aid} | _r(
                    "B", "classified", f"{aid} 파일은 같고 레지스트리 기록(권리 재확인 등)만 바뀝니다.")
                continue
            asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_replace", "asset": aid} | asset_analysis(old_e, new_e, o_raw, n_raw)
    old_raw_by_sha = {}
    for aid, e in list((reg_old or {}).items()) + list(reg_now.items()):
        if isinstance(e, dict) and e.get("sha256"):
            old_raw_by_sha[e["sha256"]] = aid
    outside = []
    for rel in changed:
        if rel == registry_rel(st):
            if reg_old is None:
                items.append({"path": rel, "kind": "registry"} | _r("D", "needs_review", "이전 자산 레지스트리를 확인할 수 없습니다."))
            else:
                o = json.loads(raw_old_reg.decode("utf-8")) if raw_old_reg else {}
                n = json.loads((project / rel).read_text(encoding="utf-8")) if (project / rel).is_file() else {}
                if {k: v for k, v in o.items() if k != "assets"} != {k: v for k, v in n.items() if k != "assets"}:
                    items.append({"path": rel, "kind": "registry"} | _r("D", "classified", "자산 레지스트리의 공통 규칙(아이콘 스타일 등)이 바뀝니다."))
            continue
        if rel in asset_files:
            aid = asset_files[rel]
            if aid not in asset_items and aid not in succ:
                asset_items[aid] = {"path": f"asset:{aid}", "kind": "asset_file", "asset": aid} | _r(
                    "C", "needs_review", f"{aid} 파일이 레지스트리 기록 없이 바뀌었습니다.")
            continue
        if rel.startswith(PREVIEW_DIR + "/"):
            items.append(classify_preview_file(project, rel, get_old(rel), cur.get(rel), ctx, closures, old_raw_by_sha, reg_now, succ))
            continue
        if rel == (st.get("config") or {}).get("theme_file"):
            items.append({"path": rel, "kind": "theme"} | _r("D", "classified", "테마 파일(전역 렌더링 값)이 바뀝니다."))
            continue
        ob, nb = get_old(rel), ((project / rel).read_bytes() if (project / rel).is_file() else None)
        items.append(classify_doc(rel, ob.decode("utf-8", "replace") if ob is not None else None,
                                  nb.decode("utf-8", "replace") if nb is not None else None, ctx))
    for aid, ai in asset_items.items():
        e = reg_now.get(aid) or (reg_old or {}).get(aid)
        hits = [r for r in changed if r.startswith(PREVIEW_DIR + "/") and r.lower().endswith(IMAGE_EXT)]
        ai["screens"] = asset_screens(project, ai.get("successor_of") or aid, e, hits, closures)
        items.append(ai)
    return {"items": items, "files": changed, "outside": outside, "cur": cur}


def classify_preview_file(project, rel, old, cur_sha, ctx, closures, by_sha, reg_now, succ) -> dict:
    it = {"path": rel, "kind": "preview"}
    new = (project / rel).read_bytes() if (project / rel).is_file() else None
    it["screens"] = screens_for_preview_file(project, rel, closures)
    if rel.endswith("tokens.css"):
        if old is not None and new is not None and parse_css_vars(old.decode("utf-8", "replace")) == parse_css_vars(new.decode("utf-8", "replace")):
            return it | _r("A", "classified", "tokens.css 주석·공백만 바뀝니다.")
        return it | _r("D", "classified", "프리뷰 토큰(tokens.css) 이름·값이 바뀝니다.")
    if rel == PREVIEW_MANIFEST:
        return it | _r("C", "classified", "프리뷰 manifest(화면·상태·VD)가 바뀝니다.")
    if rel.lower().endswith(IMAGE_EXT):
        if new is None or old is None:
            return it | _r("C", "classified", "프리뷰 이미지가 추가·삭제됩니다.")
        o_aid, n_aid = by_sha.get(sha256_bytes(old)), by_sha.get(sha256_bytes(new))
        if o_aid and n_aid and (n_aid == o_aid or succ.get(o_aid) == n_aid):
            return it | _r("B", "classified", f"프리뷰의 같은 경로 이미지가 {o_aid}에서 {n_aid}(패치된 자산)로 바뀝니다(참조 관계 유지).",
                           extra={"asset_copy": {"from": o_aid, "to": n_aid}})
        return it | _r("C", "classified", "승인 자산과 연결되지 않은 프리뷰 이미지 변경입니다.")
    if old is None or new is None:
        return it | _r("C", "conditional", "프리뷰 파일이 추가·삭제됩니다.", alt=["B"])
    try:
        so, sn = sem_normalize(rel, old), sem_normalize(rel, new)
    except UnicodeDecodeError:
        so = sn = None
    if so is not None and so == sn:
        return it | _r("A", "classified", "주석·공백만 바뀝니다(의미 해시 동일, 재승인 불필요).")
    if rel.endswith(".css"):
        return it | css_contract(old.decode("utf-8", "replace"), new.decode("utf-8", "replace"))
    return it | _r("B", "conditional", "승인된 프리뷰 코드가 바뀝니다. 승인 디자인을 바꾸지 않는 렌더링 보정인지 사람이 확인해야 합니다.", alt=["C"])


# CSS 속성 분류(change-request.md §2.5)
CSS_LAYOUT = ("display", "flex-direction", "flex-wrap", "flex-flow", "flex", "flex-grow", "flex-shrink", "flex-basis", "order", "grid",
              "grid-template", "grid-template-columns", "grid-template-rows", "grid-template-areas", "grid-area", "grid-column", "grid-row",
              "grid-auto-flow", "position", "float", "clear", "top", "right", "bottom", "left", "inset", "width", "height", "min-width",
              "max-width", "min-height", "max-height", "aspect-ratio", "columns", "column-count", "visibility", "content", "direction",
              "writing-mode", "justify-content", "align-items", "align-content", "justify-items", "align-self", "justify-self", "place-items",
              "place-content", "overflow", "overflow-x", "overflow-y", "z-index", "text-align", "vertical-align", "white-space")
CSS_VISUAL_DECISION = ("color", "background", "background-color", "background-image", "border-color", "fill", "stroke", "font-family",
                       "font-weight", "font-style", "text-transform", "opacity", "filter", "box-shadow", "text-decoration")
CSS_MINOR = ("padding", "padding-top", "padding-right", "padding-bottom", "padding-left", "margin", "margin-top", "margin-right",
             "margin-bottom", "margin-left", "gap", "row-gap", "column-gap", "border-radius", "border-width", "font-size", "line-height",
             "letter-spacing", "word-spacing", "outline-offset")
CSS_RENDER_FIX = ("image-rendering", "-webkit-font-smoothing", "-moz-osx-font-smoothing", "text-rendering", "backface-visibility",
                  "-webkit-backface-visibility", "will-change", "isolation", "transform-style", "mask", "mask-image", "-webkit-mask",
                  "-webkit-mask-image", "mask-size", "-webkit-mask-size", "mask-repeat", "-webkit-mask-repeat", "mask-position",
                  "-webkit-mask-position", "object-position", "contain", "content-visibility", "image-orientation", "color-scheme")


def css_decls(text: str) -> dict:
    """{(@규칙 경로, 선택자): {속성: 값}}. 주석 제거, 공백 정규화."""
    t = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, stack, buf = {}, [], ""
    for ch in t:
        if ch == "{":
            stack.append(" ".join(buf.split()))
            buf = ""
        elif ch == "}":
            if stack:
                sel = stack.pop()
                decls = {}
                for part in buf.split(";"):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        if k.strip():
                            decls[k.strip().lower()] = " ".join(v.split())
                if decls:  # 같은 선택자 블록이 여러 번이면 캐스케이드처럼 합침(뒤가 우선)
                    key = (tuple(stack), sel)
                    out[key] = {**out.get(key, {}), **decls}
            buf = ""
        else:
            buf += ch
    return out


def css_contract(old: str, new: str) -> dict:
    """CSS 차이의 계약 판정. 레이아웃 속성·선택자 구조 변경 → C, 색·글꼴 등 시각 결정 → C, 간격·크기 미세 보정 → B(사전 확인),
    렌더링 품질 속성만 → B(확정). 분류되지 않은 속성 → B(사전 확인, 대안 C)."""
    od, nd = css_decls(old), css_decls(new)
    changed: dict[str, list[str]] = {}
    sel_changes = sorted(str(k[1]) for k in set(od) ^ set(nd))
    for k in set(od) | set(nd):
        a, b = od.get(k, {}), nd.get(k, {})
        for prop in set(a) | set(b):
            if a.get(prop) != b.get(prop):
                changed.setdefault(prop, []).append(f"{k[1]} {{{prop}: {a.get(prop)} → {b.get(prop)}}}")
    props = set(changed)
    ev = {"css_changed": {p: v[:3] for p, v in sorted(changed.items())}, "selectors_added_removed": sel_changes[:10]}
    lay = sorted(props & set(CSS_LAYOUT))
    if lay:
        return _r("C", "classified", f"레이아웃 계약 속성이 바뀝니다({', '.join(lay)}).", extra=ev)
    vis = sorted(props & set(CSS_VISUAL_DECISION))
    if vis:
        return _r("C", "classified", f"색·글꼴 등 시각 결정 속성이 바뀝니다({', '.join(vis)}).", extra=ev)
    if any(not set(nd.get(k, {})) <= set(CSS_RENDER_FIX) for k in set(nd) - set(od)) or any(
            not set(od.get(k, {})) <= set(CSS_RENDER_FIX) for k in set(od) - set(nd)):
        return _r("C", "conditional", f"선택자가 추가·삭제됩니다({', '.join(sel_changes[:4])}).", alt=["B"], extra=ev)
    minor = sorted(props & set(CSS_MINOR))
    unknown = sorted(props - set(CSS_MINOR) - set(CSS_RENDER_FIX))
    if not minor and not unknown:
        return _r("B", "classified", f"렌더링 품질 속성만 바뀝니다({', '.join(sorted(props))}). 레이아웃·시각 결정 속성 변경 없음.", extra=ev)
    if unknown:
        return _r("B", "conditional", f"분류되지 않은 CSS 속성이 바뀝니다({', '.join(unknown)}). 승인 디자인을 바꾸지 않는지 사람이 확인해야 합니다.",
                  alt=["C"], extra=ev)
    return _r("B", "conditional", f"간격·크기 미세 보정입니다({', '.join(minor)}). 기존 레이아웃 계약 안인지 사람이 확인해야 합니다.", alt=["C"], extra=ev)


def impact_scope(project: Path, st: dict, items: list, diff: dict, succ: dict, scope: dict | None) -> dict:
    si = screen_info(project)
    screens: set[str] | None = set()
    reg = load_registry(project, st)
    closures = preview_screen_closures(project)
    pv = {rel: sha256_file(project / rel) for rel in preview_files(project)}
    for it in items:
        for f in it["facts"]:
            for r in f["refs"]:
                if re.fullmatch(r"SCR-\d{3}(?:-ST\d+)?", r):
                    screens.add(r.split("-ST")[0])
            if f.get("asset") and screens is not None:  # 자산이 쓰이는 화면(VD 관련·레지스트리 refs·프리뷰 사본)
                e = reg.get(f["asset"]) or {}
                sc = asset_screens(project, f["asset"], e, [r for r, h in pv.items() if h and h == e.get("sha256")], closures)
                screens = None if sc is None else screens | set(sc)
    for d in diff["items"]:
        if d.get("screens") is None and d["kind"] in ("preview", "asset_replace", "asset_successor", "asset_file"):
            screens = None
            break
        screens |= set(d.get("screens") or [])
    if screens is not None and scope and scope.get("screens") is None:
        screens = None
    elif screens is not None and scope:
        screens |= set(scope.get("screens") or [])
    assets = sorted({f["asset"] for it in items for f in it["facts"] if f.get("asset")} |
                    {d["asset"] for d in diff["items"] if d.get("asset")} | set((scope or {}).get("assets") or []) | set(succ) | set(succ.values()))
    cmps = sorted({c for s in (screens or si.keys()) for c in si.get(s, {}).get("cmp", set())}) if screens is not None else None
    states = sorted({x for s in (screens or []) for x in si.get(s, {}).get("states", set())}) if screens is not None else None
    trace = strip_fences(read_text(project, TRACE_FILE))
    acs = sorted({a for a, cells in table_rows(trace, r"AC-\d{3}").items()
                  if screens is None or any(s in " ".join(cells) for s in screens)})
    tokens = sorted({t for it in items for f in it["facts"] for t in (f.get("tokens") or [])})
    docs = sorted({d["path"] for d in diff["items"] if d["kind"] == "doc"})
    return {"screens": sorted(screens) if screens is not None else None, "screens_known": screens is not None,
            "states": states, "components": cmps, "assets": assets, "tokens": tokens, "acs": acs, "docs": docs,
            "files": sorted(diff.get("files") or [])}


def route(t: str, sc: dict) -> dict:
    if t == "A":
        return {"type": "A", "owner": "/product-build", "design_approval": "유지(승인 산출물 불변이어야 함)",
                "steps": ["product_build.py guard(보호 경로 변경 없음 확인)", "필요하면 ledger add --type deviation --category ⑤ --title … --desc …",
                          "product_build.py impact → verify --batch <영향 배치>(회귀 검증)"]}
    if t == "B":
        return {"type": "B", "owner": "/product-design change",
                "steps": ["change open(요청 원문 = 작업 범위 동의)", "파일·자산 수정(범위 안에서만)", "change verify(영향 화면 부분 검증)",
                          "change submit", "사용자에게 전후 비교를 보여 주고 최종 확인 문장 받기", "change approve --note \"<최종 확인 문장>\""]}
    if t == "C":
        st_ = "design_direction" if (sc.get("assets") or any(d.endswith("07-design-direction.md") for d in sc.get("docs") or [])) else "ux_spec"
        return {"type": "C", "owner": "/product-design", "m1": "M1은 분류·영향 표시만 합니다. 부분 승인은 M2 예정입니다.",
                "steps": [f"기존 정식 경로: reopen --stage {st_} → 수정 → submit → 재승인(하위 단계 재승인 포함)"],
                "affected_screens": sc.get("screens")}
    if t == "D":
        return {"type": "D", "owner": "/product-design", "steps": ["기존 경로: reopen --stage ux_spec(토큰·공통 컴포넌트·IA) 또는 v2 테마 규칙(테마 값만이면 프리뷰만)",
                                                                   "영향 화면 전체 프리뷰 재검증·재승인"]}
    return {"type": "E", "owner": "/product-start", "steps": ["/product-start에서 planning 재검토(T9: ps_state.py reopen --stage planning --confirm)",
                                                              "재승인 후 /product-design impact → rebase --confirm"]}


def required(t: str, sc: dict, diff: dict) -> dict:
    if t == "A":
        return {"approvals": [], "verification": ["product-build guard", "영향 배치 verify(회귀)"]}
    if t == "B":
        ver = ["변경 범위 재계산(change scope)", "자산 픽셀 비교·권리 재확인"]
        if any(f.startswith(PREVIEW_DIR + "/") for f in sc.get("files") or []):
            ver.append(f"프리뷰 검사·빌드(영향 화면: {', '.join(sc['screens']) if sc.get('screens') else '알 수 없음 → 전체'})")
        ver.append("/product-build: 영향 화면을 가진 배치만 재검증(stale)")
        return {"approvals": ["사용자 최종 패치 확인 1회(change approve --note)"], "verification": ver}
    if t == "C":
        return {"approvals": ["(M2) 영향 단위 부분 승인 — M1에서는 기존 단계 재승인"], "verification": ["영향 화면·상태 프리뷰"]}
    if t == "D":
        return {"approvals": ["변경된 계약이 있는 단계부터 재승인"], "verification": ["영향 화면 전체 프리뷰"]}
    return {"approvals": ["영향받는 최초 상위 단계(planning)부터 재승인"], "verification": ["하위 문서·구현 재검증"]}


# ================================================================ CR 저장소
def changes_block(st: dict) -> dict:
    ch = st.get("changes")
    if not enabled(st) or not isinstance(ch, dict):
        block("changes_disabled", "변경 요청 기능이 꺼져 있습니다. 사용자 동의 후 change enable(계획) → --confirm --note로 켭니다(v2 전용).")
    return ch


def require_chain_ok(st: dict) -> dict:
    eff = effective(st)
    if not eff["ok"]:
        block("amendment_chain_broken", "승인 패치 체인에 문제가 있어 진행할 수 없습니다. 이전 기준으로 조용히 되돌아가지 않습니다. "
              "Git 이력에서 design.json을 복원하거나 원인을 확인하세요.", errors=eff["errors"])
    return eff


def active_crs(st: dict) -> dict:
    return {k: v for k, v in (((st.get("changes") or {}).get("items")) or {}).items() if isinstance(v, dict) and v.get("status") in ACTIVE}


def scope_paths(project: Path, st: dict, cr: dict) -> set[str]:
    sc = cr.get("scope") or {}
    paths = set(sc.get("files") or [])
    reg = load_registry(project, st)
    for aid in set(sc.get("assets") or []) | set((sc.get("successors") or {}).values()):
        if isinstance(reg.get(aid), dict) and reg[aid].get("file"):
            paths.add(str(reg[aid]["file"]))
    if sc.get("assets"):
        paths.add(registry_rel(st))
    if sc.get("successors"):
        paths.add(DD_FILE)
    return paths


def other_scopes(project: Path, st: dict, cr: dict) -> tuple[set[str], set[str]]:
    """다른 진행 중 CR이 맡은 파일·자산. 한 CR의 차이·검증 digest에서 빼서 서로 간섭하지 않게 합니다(범위는 open 때 겹치지 않음을 확인)."""
    files, assets = set(), set()
    for cid, o in active_crs(st).items():
        if cid == cr.get("id"):
            continue
        files |= scope_paths(project, st, o)
        sc = o.get("scope") or {}
        assets |= set(sc.get("assets") or []) | set((sc.get("successors") or {}).values())
        assets |= {a for a in registry_entries(project, st) if a not in (o["base"].get("registry") or {}) and (sc.get("successor_pending") or sc.get("successors"))}
    return files, assets


def cr_diff(project: Path, st: dict, cr: dict) -> dict:
    cur = artifact_files(project, st)
    base = cr["base"]["files"]
    ofiles, oassets = other_scopes(project, st, cr)
    changed = sorted(r for r in set(base) | set(cur) if base.get(r) != cur.get(r) and r not in ofiles)
    reg = registry_entries(project, st)
    breg = cr["base"].get("registry") or {}
    assets = sorted(a for a in set(reg) | set(breg) if reg.get(a) != breg.get(a) and a not in oassets)
    return {"files": changed, "assets": assets, "cur": cur, "registry": reg,
            "digest": digest({"files": {r: cur.get(r) for r in changed}, "assets": {a: reg.get(a) for a in assets}})}


def pending_problems(project: Path, st: dict, problems: list) -> list:
    """활성 CR 범위 안의 승인 산출물 변경을 pending_change로 바꿉니다. 범위 밖 변경은 그대로(approved_modified 등) 둡니다.
    pending_change도 문제(consistent False)입니다: 승인된 기준이 아니며 영향 Build 작업을 막습니다."""
    crs = active_crs(st)
    if not crs:
        return problems
    covered: dict[str, str] = {}
    pend = []
    for cid, cr in crs.items():
        d = cr_diff(project, st, cr)
        sp = scope_paths(project, st, cr)
        inside = [f for f in d["files"] if f in sp]
        outside = [f for f in d["files"] if f not in sp]
        for f in inside:
            covered[f] = cid
        for f in outside:
            covered.setdefault(f, "")
        if inside or d["assets"]:
            pend.append({"stage": "design", "kind": "pending_change", "cr": cid, "paths": inside, "assets": d["assets"],
                         "screens": pending_screens(project, st, cr, d),
                         "outside_scope": outside,
                         "message": f"{cid}(Type {cr['type']['selected']}) 진행 중 변경입니다. 승인 전에는 승인된 디자인이 아니며, 영향 화면의 Build 작업·승인을 막습니다."})
    out = []
    for p in problems:
        if p.get("kind") not in ("approved_modified", "approved_asset_modified", "theme_changed"):
            out.append(p)
            continue
        paths = list(p.get("paths") or [])
        if p["kind"] == "approved_modified" and PREVIEW_TREE_KEY in paths:
            pv_changed = [f for f in covered if f.startswith(PREVIEW_DIR + "/")]
            if pv_changed and all(covered[f] for f in pv_changed):
                paths.remove(PREVIEW_TREE_KEY)
        rest = [x for x in paths if x != PREVIEW_TREE_KEY and not covered.get(x)] + ([PREVIEW_TREE_KEY] if PREVIEW_TREE_KEY in paths else [])
        if rest:
            out.append(dict(p, paths=rest))
    return out + pend


INHERITABLE_SOURCES = ("self_made", "model_drawn")  # 프로젝트가 직접 만든 자산만 파생본 권리 상속 대상(외부·라이선스·스톡·생성 도구·레퍼런스는 별도 확인)


def rights_inheritance(project: Path, st: dict, parent: str, child: dict, child_raw: bytes, parent_raw: bytes | None = None,
                       in_place: bool = False) -> dict:
    """승인된 자산의 파생본이 부모 권리를 그대로 이어받을 수 있는지(사용자 확인 질문 없이). 새 확인 문장을 만들지 않고 부모 근거를 연결만 합니다.
    조건: 진행 중 Type B CR이 부모를 선언, 부모가 유효 승인 스냅샷에 있음(권리 근거 포함), 종류·역할·출처·형식·라이선스 동일,
    출처가 직접 제작(self_made·model_drawn), 픽셀 비교가 가장자리 보정(edge_only)·동일(identical). 하나라도 아니면 별도 권리 확인."""
    reasons = []
    eff = effective(st)
    snap = ((eff["records"].get("design_direction") or {}).get("assets") or {}) if eff["ok"] else {}
    p_snap = snap.get(parent)
    reg = load_registry(project, st)
    p_entry = reg.get(parent) or {}
    crs = [c for c in active_crs(st).values() if c["type"]["selected"] == "B" and parent in ((c.get("scope") or {}).get("assets") or [])
           and (in_place or (c.get("scope") or {}).get("successor_pending") or (c.get("scope") or {}).get("successors"))]
    if not crs:
        reasons.append(f"{parent}를 선언한 진행 중 Type B 변경 요청이 없습니다")
    if not p_snap or not (p_snap.get("rights") or {}).get("license"):
        reasons.append(f"{parent}가 유효 승인 스냅샷(권리 근거 포함)에 없습니다")
    lic = ((child.get("rights") or {}).get("license") or "").strip()
    for k in ("kind", "role", "source", "format"):
        if child.get(k) != p_entry.get(k):
            reasons.append(f"{k}가 부모와 다릅니다({p_entry.get(k)} → {child.get(k)})")
    if p_snap and lic != (p_snap.get("rights") or {}).get("license"):
        reasons.append(f"라이선스가 승인 근거와 다릅니다({(p_snap.get('rights') or {}).get('license')} → {lic or '없음'})")
    if child.get("source") not in INHERITABLE_SOURCES:
        reasons.append(f"출처 {child.get('source')}는 파생본 권리가 자동으로 이어진다고 볼 수 없습니다(별도 확인)")
    if parent_raw is None and p_entry.get("file") and (project / str(p_entry["file"])).is_file():
        parent_raw = (project / str(p_entry["file"])).read_bytes()
    px = PX.compare(parent_raw, child_raw) if parent_raw is not None else {"analyzable": False, "reason": "부모 파일 없음", "verdict": None}
    if px.get("verdict") not in ("edge_only", "identical"):
        reasons.append(f"부모에서 파생된 경미한 보정임을 픽셀로 확인하지 못했습니다({px.get('verdict') or px.get('reason')})")
    ok = not reasons
    return {"ok": ok, "reasons": reasons, "cr": crs[0]["id"] if crs else None, "pixels": px,
            "parent_rights": (p_snap or {}).get("rights"), "license": lic}


def note_rights_backup(st: dict, aid: str) -> None:
    """explore-asset replace·confirm이 CR 범위 자산의 권리 기록을 바꾸기 전에, CR에 처음 한 번만 이전 기록을 보관합니다(취소 시 복원)."""
    rights = ((st.get("exploration") or {}).get("asset_rights") or {})
    for cr in active_crs(st).values():
        sc = cr.get("scope") or {}
        if aid in (sc.get("assets") or []) or aid not in (cr["base"].get("registry") or {}):
            bk = cr.setdefault("rights_backup", {})
            if aid not in bk:
                bk[aid] = copy.deepcopy(rights.get(aid))
            return


def pending_screens(project: Path, st: dict, cr: dict, d: dict | None = None) -> list[str] | None:
    """진행 중 CR의 영향 화면. 마지막 평가(scope·verify) 이후 파일이 더 바뀌었거나, 범위 확대·유형 상승이 있으면
    실제 범위를 확정할 수 없으므로 None(알 수 없음 → 모든 화면 배치를 보수적으로 막음)."""
    d = d or cr_diff(project, st, cr)
    sc = cr.get("scope") or {}
    if sc.get("screens") is None:
        return None
    if not d["files"] and not d["assets"]:
        return list(sc["screens"])
    le = cr.get("last_evaluation") or {}
    if cr.get("status") == "escalated" or le.get("expanded") or le.get("diff_digest") != d["digest"]:
        return None
    return list(sc["screens"])


def cr_stages(cr: dict) -> list[str]:
    s = set()
    for f in (cr.get("scope") or {}).get("files") or []:
        if f.startswith(PREVIEW_DIR + "/") or f == REVIEW_FILE:
            s.add("preview")
        elif f == DD_FILE:
            s.add("design_direction")
        elif f == UXP_FILE:
            s.add("ux_planning")
        elif f in SPEC_FILES:
            s.add("ux_spec")
    if (cr.get("scope") or {}).get("assets"):
        s.add("design_direction")
    return sorted(s)


def summary(project: Path, st: dict, eff: dict | None = None) -> dict | None:
    """check·status·/product-build가 쓰는 변경 요청 요약(유효 기준·패치·진행 중 CR). 기능이 꺼져 있으면 None."""
    if st.get("changes") is None and not enabled(st):
        return None
    eff = eff or effective(st)
    ch = st.get("changes") or {}
    chain = (ch.get("chain") or []) if eff["ok"] else []
    active = active_crs(st)
    eff_status = {}
    for k, s in (st.get("stages") or {}).items():
        if s.get("status") != "approved":
            continue
        eff_status[k] = "approved_with_pending" if any(k in cr_stages(c) for c in active.values()) else "approved"
    return {"enabled": enabled(st), "chain_ok": eff["ok"], "chain_errors": eff["errors"], "head": eff["head"], "effective_digest": eff["digest"],
            "applied": eff["applied"], "effective_status": eff_status,
            "amendments": [{"id": a["id"], "seq": a["seq"], "digest": a["digest"], "cr": a["cr"], "type": a["type"], "at": a["at"],
                            "files": a.get("file_transitions") or {}, "screens": a.get("screens"), "screens_known": a.get("screens") is not None,
                            "assets": sorted({x for sd in (a.get("stages") or {}).values() for x in (sd.get("assets") or {})})}
                           for a in chain],
            "pending": [{"cr": cid, "status": c["status"], "type": c["type"]["selected"], "screens": (ps := pending_screens(project, st, c)),
                         "screens_known": ps is not None, "files": sorted(scope_paths(project, st, c)),
                         "stages": cr_stages(c)} for cid, c in active.items()]}


# ================================================================ 명령
def _gate(project: Path, st: dict) -> None:
    ctx = gate_or_block(project)
    changed = detect_outdated(project, st, ctx["gate"])
    if changed:
        block("design_outdated", "planning이 바뀌어 진행할 수 없습니다(Type E 경로: impact → rebase).", changed=changed)
    if workflow_of(st) != "v2":
        block("changes_requires_v2", "변경 요청(CR)은 워크플로 v2 전용입니다. v1은 기존 reopen 경로를 씁니다(필요하면 사용자 승인 후 migrate --to v2).")


def _req_items(a) -> list:
    if not getattr(a, "request", None):
        block("invalid_arguments", "--request <프로젝트 밖 변경 요청 JSON>이 필요합니다.")
    p = Path(a.request)
    p = p if p.is_absolute() else Path.cwd() / p
    return load_request(p)["items"], p


def _cross_ok(project: Path, st: dict) -> dict:
    from pd_core import cross_verify
    return cross_verify(project, st)


def cmd_change(a) -> None:
    project = Path(a.project).resolve()
    act = a.action
    if act == "plan":
        return _plan_cmd(project, a)
    st = require_state(project)
    if act == "status":
        return _status_cmd(project, st, a)
    _gate(project, st)
    if act in ("enable", "disable"):
        return _enable_cmd(project, st, a)
    changes_block(st)
    {"open": _open_cmd, "scope": _scope_cmd, "verify": _verify_cmd, "submit": _submit_cmd, "approve": _approve_cmd,
     "cancel": _cancel_cmd, "rebase": _rebase_cmd}[act](project, st, a)


def _plan_cmd(project: Path, a) -> None:
    st = require_state(project)
    items, p = _req_items(a)
    base_files, base_reg, rev, scope, succ = None, None, None, None, None
    if getattr(a, "id", None):
        cr = (((st.get("changes") or {}).get("items")) or {}).get(a.id)
        if not cr:
            block("unknown_change", f"{a.id} 변경 요청이 없습니다.")
        base_files, base_reg, rev, scope, succ = cr["base"]["files"], cr["base"].get("registry"), cr["base"].get("head_commit"), cr.get("scope"), (cr.get("scope") or {}).get("successors")
    else:
        rev = a.base or "HEAD"
        base_files = {}
        for rel in artifact_files(project, st):
            b = git_bytes(project, rev, rel)
            base_files[rel] = sha256_bytes(b) if b is not None else None
        base_files = {k: v for k, v in base_files.items() if v is not None or (project / k).exists()}
        raw = git_bytes(project, rev, registry_rel(st))
        try:
            base_reg = {aid: entry_sha(e) for aid, e in (json.loads(raw.decode("utf-8")).get("assets") or {}).items()} if raw else {}
        except (ValueError, AttributeError):
            base_reg = None
    res = plan(project, st, items, base_files, base_reg, rev, succ, scope)
    eff = effective(st)
    res.update(ok=True, read_only=True, request=str(p), workflow=workflow_of(st), changes_enabled=enabled(st), chain_ok=eff["ok"],
               m1_executable=res["type"]["minimum"] in M1_EXECUTABLE or res["type"]["minimum"] == "A",
               rules_ref="skills/product-design/reference/change-request.md")
    emit(res)


def _status_cmd(project: Path, st: dict, a) -> None:
    sm = summary(project, st)
    items = ((st.get("changes") or {}).get("items")) or {}
    out = {"ok": True, "changes": sm}
    if getattr(a, "id", None):
        cr = items.get(a.id)
        if not cr:
            block("unknown_change", f"{a.id} 변경 요청이 없습니다.")
        d = cr_diff(project, st, cr)
        ver = cr.get("verification") or {}
        out["cr"] = cr
        out["live"] = {"changed_files": d["files"], "changed_assets": d["assets"], "diff_digest": d["digest"],
                       "verification_fresh": bool(ver) and ver.get("diff_digest") == d["digest"] and ver.get("result") == "pass"}
    else:
        out["items"] = {k: {"status": v["status"], "type": v["type"]["selected"], "purpose": v.get("purpose")} for k, v in items.items()}
    emit(out)


def _enable_cmd(project: Path, st: dict, a) -> None:
    import pd_core as C
    if a.action == "disable":
        ch = st.get("changes") or {}
        if not enabled(st):
            emit({"ok": True, "status": "already_disabled"})
        if ch.get("chain") or active_crs(st):
            block("changes_in_use", "승인된 패치나 진행 중인 변경 요청이 있어 끌 수 없습니다(유효 승인 기준이 깨짐). 되돌리려면 백업·Git 이력으로 design.json을 복원합니다.")
        if not (a.confirm and (a.note or "").strip()):
            emit({"ok": True, "status": "plan", "would_remove": ["config.changes", "changes"], "next": "사용자 확인 후 --confirm --note"})
        with rollback_on_failure(project, files=[STATE_REL]):
            st["config"].pop("changes", None)
            st.pop("changes", None)
            add_history(st, "design", "changes_disabled", None, a.note.strip()[:200])
            save_state(project, st)
        emit({"ok": True, "status": "disabled"})
    if enabled(st):
        emit({"ok": True, "status": "already_enabled", "config": st["config"]["changes"]})
    cv = _cross_ok(project, st)
    if not cv["consistent"]:
        block("changes_precheck_failed", "check에 문제가 있어 켤 수 없습니다(기존 상태를 바꾸지 않음).", problems=cv["problems"])
    plan_ = {"add": ["config.changes {enabled, at, statement}", "changes {items: {}, chain: [], head: {count: 0, digest: null}}"],
             "preserved": "기존 승인·제출·revision·해시·history는 그대로(추가만)", "backup": None, "default_off_projects": "켜지 않은 프로젝트는 기존 동작 그대로"}
    clean = not [p for p in C.git_dirty_paths(project) if p == STATE_REL]
    tracked = C.git(project, "ls-files", STATE_REL, check=False).strip() == STATE_REL
    backup_rel = None if (clean and tracked) else ".ai-workflow/backup/design/design.json.pre-changes"
    plan_["backup"] = backup_rel or "생략(Git 추적·clean)"
    if not (a.confirm and (a.note or "").strip()):
        emit({"ok": True, "status": "plan", "dry_run": True, "plan": plan_, "next": "사용자 동의 문장을 받아 change enable --confirm --note \"<문장>\""})
    orig = copy.deepcopy(st)
    raw0 = (project / STATE_REL).read_bytes()
    with rollback_on_failure(project, files=[STATE_REL] + ([backup_rel] if backup_rel else [])):
        if backup_rel:
            bp = project / backup_rel
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_bytes(raw0)
        st.setdefault("config", {})["changes"] = {"enabled": True, "at": now(), "statement": a.note.strip()}
        st["changes"] = {"items": {}, "chain": [], "head": {"count": 0, "digest": None}, "seq": 0}
        add_history(st, "design", "changes_enabled", None, a.note.strip()[:200])
        if getattr(a, "simulate_failure", False):
            raise RuntimeError("simulated failure")
        save_state(project, st)
        re_ = json.loads((project / STATE_REL).read_text(encoding="utf-8"))
        diffs = C._preserved(orig, re_)
        if diffs:
            raise RuntimeError(f"기존 필드가 바뀜: {diffs}")
    emit({"ok": True, "status": "enabled", "backup": backup_rel, "plan": plan_})


def _snapshot_base(project: Path, st: dict, eff: dict) -> dict:
    files = artifact_files(project, st)
    head = git(project, "rev-parse", "HEAD").strip()
    return {"files": files, "registry": registry_entries(project, st), "head_commit": head, "effective_digest": eff["digest"],
            "chain_head": eff["head"], "stage_revisions": {k: (s.get("approved") or {}).get("revision") for k, s in st["stages"].items()},
            "at": now()}


def _declared_scope(project: Path, st: dict, items: list, ctx_plan: dict) -> dict:
    reg = load_registry(project, st)
    files, assets, succ_pending = set(), set(), []
    pv = {rel: sha256_file(project / rel) for rel in preview_files(project)}
    closures = preview_screen_closures(project)
    screens: set | None = set()
    for it in items:
        for f in it.get("facts") or []:
            k = f.get("kind")
            if k == "asset_patch" and f.get("asset"):
                aid = f["asset"]
                assets.add(aid)
                e = reg.get(aid) or {}
                if e.get("file"):
                    files.add(str(e["file"]))
                    hits = [r for r, h in pv.items() if h == e.get("sha256")]
                    files |= set(hits)
                    sc = asset_screens(project, aid, e, hits, closures)
                    screens = None if (sc is None or screens is None) else screens | set(sc)
                if f.get("successor"):
                    succ_pending.append(aid)
                    files.add(DD_FILE)
                files.add(registry_rel(st))
            elif k == "typo" and f.get("doc"):
                files.add(f["doc"])
            elif k == "render_fix" and f.get("target") == "preview":
                for s in [f.get("screen")] if f.get("screen") else []:
                    files |= closures.get(s, set())
                    if screens is not None:
                        screens.add(s)
                for rel in f.get("files") or []:
                    files.add(rel)
                    hs = screens_for_preview_file(project, rel, closures)
                    screens = None if (hs is None or screens is None) else screens | set(hs)
            if f.get("screen") and screens is not None and re.fullmatch(r"SCR-\d{3}", f["screen"]):
                screens.add(f["screen"])
    succ = {f["asset"]: f["to"] for it in items for f in it.get("facts") or [] if f.get("kind") == "asset_patch" and f.get("successor") and f.get("to")}
    return {"files": sorted(files), "assets": sorted(assets), "successors": succ, "successor_pending": sorted(set(succ_pending) - set(succ)),
            "screens": sorted(screens) if screens is not None else None, "screens_known": screens is not None, "accepted_expansions": []}


def _open_cmd(project: Path, st: dict, a) -> None:
    eff = require_chain_ok(st)
    items, p = _req_items(a)
    scope_note = (a.scope_note or "").strip()
    if not scope_note:
        block("scope_consent_required", "작업 범위 동의 근거가 필요합니다. 사용자의 최초 요청 원문을 --scope-note로 그대로 전달하세요(최종 승인과 별개).")
    res = plan(project, st, items, None, None, None)
    t = res["type"]
    selected = a.type or t["recommended"]
    if selected not in TYPES:
        block("invalid_arguments", "--type은 A–E 중 하나입니다.")
    if RANK[selected] < RANK[t["minimum"]]:
        block("change_type_insufficient", f"선택한 유형 {selected}는 최소 요구 유형 {t['minimum']}보다 낮습니다. 사용자 선택만으로 승인 범위를 줄일 수 없습니다.",
              minimum=t["minimum"], reasons=t["reasons"])
    if selected not in M1_EXECUTABLE:
        msg = {"A": "Type A는 디자인 변경 요청 없이 /product-build로 진행합니다(승인 산출물 불변).",
               "C": "Type C 부분 승인은 M2 예정입니다. 지금은 기존 정식 승인 경로를 씁니다.",
               "D": "Type D는 기존 reopen·재승인 경로를 씁니다.", "E": "Type E는 /product-start 재검토(T9)부터 진행합니다."}[selected]
        block("change_type_not_executable", msg, type=selected, route=route(selected, res["scope"]))
    pre = (a.pre_confirm or "").strip()
    if res["pre_confirmation_required"] and not pre:
        block("pre_confirmation_required", "유형 판정이 모호합니다. 작업 전에 사용자에게 유형·범위를 확인받고 그 문장을 --pre-confirm으로 전달하세요.",
              reasons=res["pre_confirmation_reasons"], type=t)
    cv = _cross_ok(project, st)
    if [x for x in cv["problems"] if x.get("kind") != "pending_change"]:  # 다른 CR의 진행 중 변경은 범위 겹침 검사(cr_conflict)로 따로 확인
        block("baseline_not_clean", "현재 파일이 유효 승인 기준과 다릅니다. 변경 요청은 수정 전에 엽니다(승인 기준과 같은 상태에서). "
              "이미 수정했다면 사용자가 변경을 잠시 되돌린 뒤 엽니다.", problems=cv["problems"])
    targets = {"design_direction"} if any(f.get("kind") == "asset_patch" for it in items for f in it.get("facts") or []) else set()
    for stg in targets:
        if st["stages"].get(stg, {}).get("status") != "approved":
            block("stage_not_approved", f"패치는 승인된 단계에만 적용합니다({stg}: {st['stages'].get(stg, {}).get('status')}).")
    scope = _declared_scope(project, st, items, res)
    dirty = set(__import__("pd_core").git_dirty_paths(project))
    for cid_, o in active_crs(st).items():  # 다른 CR이 이미 바꾼 파일을 이 CR 기준으로 삼지 않음
        if set(scope["files"]) & set(cr_diff(project, st, o)["files"]):
            block("cr_conflict", f"진행 중인 {cid_}가 이미 바꾼 파일을 다룹니다.")
    unc = sorted(f for f in scope["files"] if f in dirty)
    if unc:
        block("uncommitted_scope_files", "범위 파일에 커밋되지 않은 변경이 있어 기준 내용을 확정할 수 없습니다. 사용자가 승인 상태를 먼저 커밋한 뒤 엽니다.", paths=unc)
    for cid, other in active_crs(st).items():
        osp = scope_paths(project, st, other)
        overlap = sorted((set(scope["files"]) & osp) | (set(scope["assets"]) & set((other.get("scope") or {}).get("assets") or [])))
        osc, nsc = (other.get("scope") or {}).get("screens"), scope["screens"]
        if overlap or osc is None or nsc is None or set(osc) & set(nsc):
            block("cr_conflict", f"진행 중인 {cid}와 같은 변경 단위(파일·자산·화면)를 다룹니다(또는 범위를 알 수 없음). 동시에 진행하지 않습니다.",
                  overlap=overlap, other_screens=osc, screens=nsc)
    ch = st["changes"]
    ch["seq"] = int(ch.get("seq") or 0) + 1
    cid = f"CR-{ch['seq']:03d}"
    if cid in ch["items"]:
        block("cr_id_conflict", f"{cid}가 이미 있습니다(다른 Worktree 병합 흔적일 수 있음).")
    cr = {"id": cid, "uid": uuid.uuid4().hex, "status": "open", "purpose": " / ".join(i.get("summary", "") for i in items),
          "request": {"path": str(p), "sha256": sha256_bytes(p.read_bytes()), "items": items},
          "type": {"recommended": t["recommended"], "minimum": t["minimum"], "selected": selected, "possible": t["possible"],
                   "selected_by": "user" if a.type else "recommended", "reasons": t["reasons"]},
          "consent": {"scope": {"statement": scope_note, "at": now(), "kind": "initial_request"},
                      **({"pre_confirmation": {"statement": pre, "at": now()}} if pre else {})},
          "base": _snapshot_base(project, st, eff), "scope": scope,
          "verification": None, "submitted": None, "approval": None, "history": [{"at": now(), "event": "opened"}]}
    ch["items"][cid] = cr
    add_history(st, "design", "change_opened", None, f"{cid} Type {selected}: {cr['purpose'][:120]}")
    save_state(project, st)
    emit({"ok": True, "id": cid, "status": "open", "type": cr["type"], "scope": scope, "plan": res,
          "next": "범위 안에서 수정한 뒤 change verify --id " + cid + " (범위 밖 변경은 change scope로 재확인)"})


def _get_cr(st: dict, cid: str) -> dict:
    cr = (st["changes"].get("items") or {}).get(cid or "")
    if not cr:
        block("unknown_change", f"{cid} 변경 요청이 없습니다.")
    return cr


def _evaluate(project: Path, st: dict, cr: dict) -> dict:
    """현재 차이로 다시 판정: 최소 유형, 범위 밖 파일, 후속 자산 연결."""
    sc = cr["scope"]
    res = plan(project, st, cr["request"]["items"], cr["base"]["files"], cr["base"].get("registry"), cr["base"].get("head_commit"),
               sc.get("successors"), sc, other_scopes(project, st, cr))
    succ = res["successors"]
    sp = scope_paths(project, st, dict(cr, scope=dict(sc, successors=succ)))
    accepted = {f for x in sc.get("accepted_expansions") or [] for f in x["files"]}
    expanded = sorted(f for f in res["changed_files"] if f not in sp and f not in accepted)
    d = cr_diff(project, st, cr)
    return {"plan": res, "successors": succ, "expanded": expanded, "diff": d,
            "escalated": RANK[res["type"]["minimum"]] > RANK[cr["type"]["selected"]]}


def _apply_eval(st: dict, cr: dict, ev: dict, event: str) -> None:
    if ev["successors"] != (cr["scope"].get("successors") or {}):
        cr["scope"]["successors"] = ev["successors"]
        cr["scope"]["successor_pending"] = sorted(set(cr["scope"].get("successor_pending") or []) - set(ev["successors"]))
    new_sc = ev["plan"]["scope"]["screens"]
    if new_sc is None:
        cr["scope"]["screens"], cr["scope"]["screens_known"] = None, False
    elif cr["scope"].get("screens") is not None:
        cr["scope"]["screens"] = sorted(set(cr["scope"]["screens"]) | set(new_sc))
    if ev["escalated"]:
        if cr["status"] != "escalated":
            cr["history"].append({"at": now(), "event": "escalated", "minimum": ev["plan"]["type"]["minimum"]})
            add_history(st, "design", "change_escalated", None, f"{cr['id']}: 최소 유형 {ev['plan']['type']['minimum']} > 선택 {cr['type']['selected']}")
        cr["status"] = "escalated"
    elif cr["status"] in ("open", "escalated") and ev["diff"]["files"]:
        cr["status"] = "in_progress"
    cr["last_evaluation"] = {"at": now(), "event": event, "minimum": ev["plan"]["type"]["minimum"], "expanded": ev["expanded"],
                             "changed_files": ev["plan"]["changed_files"], "diff_digest": ev["diff"]["digest"]}


def _require_not_stale(st: dict, cr: dict, eff: dict) -> None:
    if cr["base"]["chain_head"] != eff["head"] or cr["base"]["effective_digest"] != eff["digest"]:
        block("cr_stale", f"{cr['id']}를 연 뒤 유효 승인 기준이 바뀌었습니다(다른 패치 승인 등). 오래된 기준으로 승인하지 않습니다. "
              "겹치지 않는 변경이면 change rebase, 아니면 cancel 후 다시 엽니다.", base_head=cr["base"]["chain_head"], current_head=eff["head"])
    for k, rev in (cr["base"].get("stage_revisions") or {}).items():
        if (st["stages"].get(k, {}).get("approved") or {}).get("revision") != rev:
            block("cr_stale", f"{cr['id']}를 연 뒤 {k} 승인 revision이 바뀌었습니다.")


def _scope_cmd(project: Path, st: dict, a) -> None:
    cr = _get_cr(st, a.id)
    if cr["status"] not in ACTIVE:
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다.")
    ev = _evaluate(project, st, cr)
    if a.accept:
        note = (a.note or "").strip()
        if not note:
            block("statement_required", "범위 확대 재확인은 사용자 문장(--note)이 필요합니다.")
        if ev["escalated"]:
            block("change_type_insufficient", f"범위 확대로 최소 유형이 {ev['plan']['type']['minimum']}가 되었습니다. Type B로 진행할 수 없습니다. "
                  "cancel 후 해당 유형의 정식 경로로 진행합니다.", route=ev["plan"]["route"])
        if ev["expanded"]:
            cr["scope"].setdefault("accepted_expansions", []).append({"at": now(), "statement": note, "files": ev["expanded"]})
            cr["history"].append({"at": now(), "event": "scope_expanded_accepted", "files": ev["expanded"]})
            ev["expanded"] = []
        if ev["plan"]["pre_confirmation_required"]:  # 자동 판정 불가한 실제 차이에 대한 사용자 확인 — 이 차이(digest)에만 유효
            cr["consent"]["diff_confirmation"] = {"statement": note, "at": now(), "diff_digest": ev["diff"]["digest"],
                                                  "reasons": ev["plan"]["pre_confirmation_reasons"]}
            cr["history"].append({"at": now(), "event": "diff_confirmed"})
    _apply_eval(st, cr, ev, "scope")
    if cr.get("verification") and cr["verification"].get("diff_digest") != ev["diff"]["digest"]:
        cr["verification"]["stale"] = True
    save_state(project, st)
    emit({"ok": not ev["expanded"] and not ev["escalated"], "id": cr["id"], "status": cr["status"], "type": ev["plan"]["type"],
          "expanded": ev["expanded"], "escalated": ev["escalated"], "scope": ev["plan"]["scope"], "diff": ev["plan"]["diff"],
          "pre_confirmation_required": ev["plan"]["pre_confirmation_required"],
          "next": ("범위 밖 변경이 있습니다. 사용자에게 보여 주고 확인 문장을 받아 change scope --accept --note, 또는 되돌립니다." if ev["expanded"]
                   else "최소 유형이 올라갔습니다. cancel 후 정식 경로로 진행합니다." if ev["escalated"] else f"change verify --id {cr['id']}")},
         0 if not ev["expanded"] and not ev["escalated"] else 2)


def _blocking_eval(project: Path, st: dict, cr: dict, ev: dict) -> None:
    if ev["escalated"]:
        _apply_eval(st, cr, ev, "check")
        save_state(project, st)
        block("change_escalated", f"실제 변경이 최소 유형 {ev['plan']['type']['minimum']}를 요구합니다(선택 {cr['type']['selected']}). 재분류가 필요합니다.",
              reasons=ev["plan"]["type"]["reasons"], route=ev["plan"]["route"])
    if ev["expanded"]:
        block("scope_expanded", "선언한 범위 밖 파일이 바뀌었습니다. 사용자 재확인(change scope --accept --note) 또는 되돌리기가 필요합니다.", files=ev["expanded"])
    dc = cr["consent"].get("diff_confirmation") or {}
    if ev["plan"]["pre_confirmation_required"] and not (cr["consent"].get("pre_confirmation") or cr["scope"].get("accepted_expansions")
                                                         or dc.get("diff_digest") == ev["diff"]["digest"]):
        block("pre_confirmation_required", "실제 변경에 판정이 확정되지 않은 항목이 있습니다. 사용자 확인 후 change scope --accept --note로 기록하세요.",
              reasons=ev["plan"]["pre_confirmation_reasons"])
    if not ev["diff"]["files"] and not ev["diff"]["assets"]:
        block("no_changes", "기준 대비 바뀐 것이 없습니다.")


def _asset_rights_errors(project: Path, st: dict, cr: dict, succ: dict) -> list[str]:
    import pd_assets as PA
    reg = PA.load_registry(project, st)
    errs = []
    targets = (set(cr["scope"].get("assets") or []) - set(succ)) | set(succ.values())
    for aid in sorted(targets):
        why = PA.rights_verified(project, st, reg, aid)
        if why:
            errs.append(f"{aid}: {why}(explore-asset confirm으로 권리 재확인 필요)")
    return errs


def _verify_cmd(project: Path, st: dict, a) -> None:
    from pd_core import preview_build
    from pd_theme import preview_check
    cr = _get_cr(st, a.id)
    if cr["status"] not in ("open", "in_progress", "verified", "escalated"):
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다.")
    require_chain_ok(st)
    ev = _evaluate(project, st, cr)
    _blocking_eval(project, st, cr, ev)
    _apply_eval(st, cr, ev, "verify")
    checks, steps, result = [], [], "pass"
    screen_rec = None
    rights = _asset_rights_errors(project, st, cr, ev["successors"])
    checks.append({"name": "asset_rights", "ok": not rights, "errors": rights})
    px = [{"asset": d.get("asset"), "pixels": d.get("pixels"), "minimum": d["minimum"]} for d in ev["plan"]["diff"] if d.get("pixels")]
    checks.append({"name": "asset_pixels", "ok": all(x["minimum"] == "B" for x in px), "results": px})
    preview_touched = any(f.startswith(PREVIEW_DIR + "/") for f in ev["diff"]["files"])
    if preview_touched:
        eff = effective(st)
        hyp = hypothetical_state(project, st, cr, ev, eff) if not rights else st
        if not effective(hyp)["ok"]:
            block("amendment_chain_broken", "가정 패치 적용 결과가 유효 기준과 맞지 않습니다.", errors=effective(hyp)["errors"])
        pc = preview_check(project, hyp)
        checks.append({"name": "preview_check", "ok": pc["ok"], "errors": pc.get("errors", [])})
        if pc["ok"]:
            b = preview_build(project, a.timeout)
            steps = b["steps"]
            checks.append({"name": "preview_build", "ok": b["result"] == "pass", "scope": "전체 앱 빌드(화면 시각 검증 아님)"})
            if b["result"] == "pass":
                screen_rec = _screen_check(project, st, cr, ev, a)
                checks.append(screen_rec["check"])
                screen_rec = screen_rec["record"]
    if not all(c["ok"] for c in checks):
        result = "fail"
    d2 = cr_diff(project, st, cr)  # 빌드가 파일을 바꾸지 않았는지(lock 파일 등)
    cr["last_evaluation"]["diff_digest"] = d2["digest"]
    cr["verification"] = {"result": result, "at": now(), "diff_digest": d2["digest"], "screens": cr["scope"].get("screens"),
                          "screens_known": cr["scope"].get("screens") is not None, "checks": checks, "steps": steps,
                          "preview_touched": preview_touched, "minimum": ev["plan"]["type"]["minimum"],
                          "screen_verification": screen_rec if preview_touched else {"status": "not_applicable", "reason": "프리뷰 파일 변경 없음"}}
    cr["status"] = "verified" if result == "pass" else "in_progress"
    cr["history"].append({"at": now(), "event": "verified" if result == "pass" else "verify_failed"})
    save_state(project, st)
    emit({"ok": result == "pass", "id": cr["id"], "result": result, "checks": checks, "steps": steps,
          "screens": cr["scope"].get("screens"), "next": f"change submit --id {cr['id']}" if result == "pass" else "실패 항목을 고친 뒤 다시 verify"},
         0 if result == "pass" else 2)


def _screen_check(project: Path, st: dict, cr: dict, ev: dict, a) -> dict:
    """영향 화면·상태 실제 브라우저 검증. 측정이 실제로 끝나지 않으면 통과로 기록하지 않습니다(사용자 면제는 waived로 따로 기록)."""
    import pd_screens as SCR
    reg = load_registry(project, st)
    expected: dict[str, list] = {}
    all_screens = sorted(SCR.manifest_states(project))
    for d in ev["plan"]["diff"]:
        cp = d.get("asset_copy")
        if not cp:
            continue
        e = reg.get(cp["to"]) or {}
        for sid in (d.get("screens") or all_screens):
            expected.setdefault(sid, []).append({"stem": Path(d["path"]).stem, "width": e.get("width"), "height": e.get("height"), "asset": cp["to"]})
    sv = SCR.verify_screens(project, st, cr["id"], cr["scope"].get("screens"), expected, a.timeout)
    waiver = (getattr(a, "screen_waiver", "") or "").strip()
    ok = sv["status"] in ("completed", "not_applicable") and sv["passed"]
    if not ok and waiver and sv["status"] in ("not_run", "invalid"):
        sv["waiver"] = {"statement": waiver, "at": now(), "status_at_waiver": sv["status"]}
        ok = True  # 측정 완료가 아니라 사용자 면제(waived)로 따로 기록
    state = "passed" if sv["status"] == "completed" and sv["passed"] else ("waived" if sv.get("waiver") else sv["status"] if sv["status"] != "completed" else "failed")
    return {"record": sv, "check": {"name": "screen_verification", "ok": ok, "state": state, "screens": sv.get("screens"),
                                    "expanded_to_all": sv.get("expanded_to_all"), "measured": sv.get("measured"), "reason": sv.get("reason"),
                                    "blocking": (sv.get("blocking") or [])[:20], "run_id": sv.get("run_id")}}


def _require_fresh_verification(cr: dict, d: dict) -> None:
    ver = cr.get("verification") or {}
    if ver.get("result") != "pass":
        block("not_verified", f"{cr['id']}의 검증(change verify) 통과 기록이 없습니다.")
    if ver.get("diff_digest") != d["digest"]:
        block("verification_stale", "검증 이후 파일이 바뀌었습니다. change verify를 다시 실행하세요.")


def _submit_cmd(project: Path, st: dict, a) -> None:
    cr = _get_cr(st, a.id)
    if cr["status"] != "verified":
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다. 검증(verified)된 변경만 제출합니다.")
    eff = require_chain_ok(st)
    _require_not_stale(st, cr, eff)
    ev = _evaluate(project, st, cr)
    _blocking_eval(project, st, cr, ev)
    _require_fresh_verification(cr, ev["diff"])
    snap = _change_snapshot(project, st, cr, ev, eff)
    cr["submitted"] = snap | {"at": now(), "diff_digest": ev["diff"]["digest"], "digest": digest(snap)}
    cr["status"] = "awaiting_confirmation"
    cr["history"].append({"at": now(), "event": "submitted"})
    add_history(st, "design", "change_submitted", None, f"{cr['id']} digest {cr['submitted']['digest'][:12]}")
    save_state(project, st)
    emit({"ok": True, "id": cr["id"], "status": "awaiting_confirmation", "submitted": cr["submitted"],
          "confirm_with_user": {"changed_files": sorted(cr["submitted"]["file_transitions"]), "screens": cr["submitted"]["screens"],
                                "pixels": cr["submitted"]["pixels"], "rights_inheritance": cr["submitted"]["rights_inheritance"],
                                "screen_verification": cr["submitted"]["screen_verification"]},
          "next": "사용자에게 전후 비교(자산·화면·화면 검증 결과)와 권리 상속(있으면)을 함께 보여 주고 최종 확인 한 번을 받아 change approve --note"})


def _change_snapshot(project: Path, st: dict, cr: dict, ev: dict, eff: dict) -> dict:
    """제출 스냅샷: 단계별 파일 전후 해시, 프리뷰 트리·의미 해시, DD 자산 스냅샷 전후. 승인 시 그대로 패치가 됩니다."""
    import pd_assets as PA
    from pd_core import stage_of
    base = cr["base"]["files"]
    stages: dict = {}
    transitions = {}
    for rel in ev["diff"]["files"]:
        transitions[rel] = [base.get(rel), ev["diff"]["cur"].get(rel)]
        stg = stage_of(rel, st)
        if stg:
            rec = eff["records"].get(stg)
            if not rec:
                block("stage_not_approved", f"{rel}가 속한 {stg}가 승인 상태가 아닙니다.")
            sd = stages.setdefault(stg, {"base_revision": rec["revision"], "files": {}})
            if rec["hashes"].get(rel) != base.get(rel):
                block("baseline_mismatch", f"{rel}의 기준 해시가 유효 승인 기준과 다릅니다.")
            sd["files"][rel] = {"before": base.get(rel), "after": ev["diff"]["cur"].get(rel)}
    if any(f.startswith(PREVIEW_DIR + "/") for f in ev["diff"]["files"]):
        rec = eff["records"].get("preview")
        if not rec:
            block("stage_not_approved", "프리뷰가 승인 상태가 아닙니다.")
        sd = stages.setdefault("preview", {"base_revision": rec["revision"], "files": {}})
        sd["files"][PREVIEW_TREE_KEY] = {"before": rec["hashes"].get(PREVIEW_TREE_KEY), "after": preview_tree_hash(project)}
        if rec.get("semantic_algo") == SEM_ALGO and rec.get("semantic_tree_hash"):
            sd["semantic"] = {"before": rec["semantic_tree_hash"], "after": preview_semantic_hash(project)}
    dd = eff["records"].get("design_direction")
    if dd is not None and "assets" in dd:
        new_snap, errs = PA.dd_asset_snapshot(project, st)
        if errs:
            block("asset_rights_unverified", "승인 VD 자산 중 권리 확인 근거가 없거나 바뀐 자산이 있습니다.", assets=errs)
        old_snap = dd.get("assets") or {}
        ta = {}
        allowed = set(cr["scope"].get("assets") or []) | set(ev["successors"].values())
        for aid in sorted(set(old_snap) | set(new_snap)):
            if old_snap.get(aid) != new_snap.get(aid):
                if aid not in allowed:
                    block("asset_outside_scope", f"범위 밖 자산 {aid}의 승인 스냅샷이 바뀝니다.")
                ta[aid] = {"before": old_snap.get(aid), "after": new_snap.get(aid)}
        if ta:
            stages.setdefault("design_direction", {"base_revision": dd["revision"], "files": {}})["assets"] = ta
    for k in [k for k, v in stages.items() if not v.get("files") and not v.get("assets") and not v.get("semantic")]:
        stages.pop(k)
    rights = {aid: t["after"]["rights"] for aid, t in ((stages.get("design_direction") or {}).get("assets") or {}).items()
              if t.get("after") and (t["after"].get("rights") or {}).get("inherited_from")}
    ver = cr.get("verification") or {}
    return {"stages": stages, "file_transitions": transitions, "screens": cr["scope"].get("screens"),
            "pixels": [{"asset": d.get("asset"), "pixels": d.get("pixels")} for d in ev["plan"]["diff"] if d.get("pixels")],
            "rights_inheritance": rights, "verification_digest": digest(ver) if ver else None,
            "screen_verification": {k: (ver.get("screen_verification") or {}).get(k) for k in ("status", "passed", "run_id", "report_sha256", "screens", "waiver")}}


def append_amendment(st: dict, cr: dict, snap: dict, note: str, submitted_digest: str, verification_digest: str | None) -> dict:
    """패치를 체인 끝에 붙이고 CR을 승인 상태로 바꿉니다(st를 직접 바꿈). approve는 실제 상태에, verify는 복사본(가정 상태)에 씁니다."""
    ch = st["changes"]
    chain = ch["chain"]
    amd = {"id": f"AMD-{len(chain) + 1:03d}", "seq": len(chain) + 1, "uid": uuid.uuid4().hex, "cr": cr["id"], "cr_uid": cr["uid"],
           "type": cr["type"]["selected"], "kind": "patch", "base_head": cr["base"]["chain_head"],
           "stages": snap["stages"], "file_transitions": snap["file_transitions"], "screens": snap["screens"],
           "rights_inheritance": snap.get("rights_inheritance") or {}, "screen_verification": snap.get("screen_verification"),
           "submitted_digest": submitted_digest, "verification_digest": verification_digest,
           "consent_digest": digest(cr["consent"]), "statement": note, "at": now(), "prev": ch["head"].get("digest")}
    amd["digest"] = amendment_digest(amd)
    chain.append(amd)
    ch["head"] = {"count": len(chain), "digest": amd["digest"]}
    cr.update(status="approved", amendment=amd["id"], amendment_digest=amd["digest"],
              approval={"statement": note, "at": amd["at"], "kind": "final_patch_confirmation",
                        "covers": ["patch"] + (["rights_inheritance"] if snap.get("rights_inheritance") else [])})
    cr["history"].append({"at": now(), "event": "approved", "amendment": amd["id"]})
    add_history(st, "design", "change_approved", None, f"{cr['id']} → {amd['id']} digest {amd['digest'][:12]}: {note[:120]}")
    return amd


def hypothetical_state(project: Path, st: dict, cr: dict, ev: dict, eff: dict) -> dict:
    """패치가 승인됐다고 가정한 상태 복사본(검증 전용, 저장하지 않음). 프리뷰 검사가 패치 자산을 공식 자산으로 보고 검사하게 합니다."""
    hyp = copy.deepcopy(st)
    hcr = hyp["changes"]["items"][cr["id"]]
    snap = _change_snapshot(project, hyp, hcr, ev, eff)
    append_amendment(hyp, hcr, snap, "(검증용 가정 — 기록되지 않음)", digest(snap), None)
    return hyp


def _approve_cmd(project: Path, st: dict, a) -> None:
    note = (a.note or "").strip()
    if not note:
        block("final_confirmation_required", "Type B 완료에는 사용자의 최종 패치 확인 문장이 필요합니다(--note). 최초 요청을 대신 쓸 수 없습니다.")
    cr = _get_cr(st, a.id)
    if cr["status"] != "awaiting_confirmation":
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다. 제출(submit)된 변경만 확인할 수 있습니다.")
    reused = [k for k, v in cr["consent"].items() if norm_text(v.get("statement")) == norm_text(note)]
    reused += ["accepted_expansion" for x in cr["scope"].get("accepted_expansions") or [] if norm_text(x["statement"]) == norm_text(note)]
    if reused or norm_text(note) == norm_text(cr["purpose"]):
        block("confirmation_reused", "최종 확인 문장이 작업 전 동의(요청 원문·사전 확인)와 같습니다. 결과를 본 뒤의 새 확인 문장이 필요합니다.", reused=reused)
    eff = require_chain_ok(st)
    _require_not_stale(st, cr, eff)
    ev = _evaluate(project, st, cr)
    sub = cr["submitted"] or {}
    if ev["diff"]["digest"] != sub.get("diff_digest"):
        block("changed_since_submit", "제출한 뒤 파일·자산이 바뀌었습니다. 다시 verify → submit 하세요.")
    _blocking_eval(project, st, cr, ev)
    _require_fresh_verification(cr, ev["diff"])
    snap = _change_snapshot(project, st, cr, ev, eff)
    if digest(snap) != sub.get("digest"):
        block("changed_since_submit", "제출한 뒤 승인 기준 스냅샷(자산·권리 기록 등)이 바뀌었습니다. 다시 verify → submit 하세요.")
    ch = st["changes"]
    with rollback_on_failure(project, files=[STATE_REL]):
        amd = append_amendment(st, cr, snap, note, sub["digest"], digest(cr["verification"]))
        chk = effective(st)
        if not chk["ok"]:
            raise RuntimeError(f"패치 적용 후 체인 검사 실패: {chk['errors']}")
        save_state(project, st)
    emit({"ok": True, "id": cr["id"], "status": "approved", "amendment": amd["id"], "digest": amd["digest"],
          "preserved": "기존 단계 승인 기록(approved·revision·해시)은 그대로입니다. 유효 승인 기준 = 승인 기록 + 패치 체인.",
          "effective_head": ch["head"], "screens": snap["screens"],
          "next": "/product-build check: 영향 화면을 가진 배치만 재검증(stale) 대상이 됩니다. 결과를 검토한 뒤 사용자가 커밋합니다."})


def _cancel_cmd(project: Path, st: dict, a) -> None:
    cr = _get_cr(st, a.id)
    if cr["status"] not in ACTIVE:
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다.")
    if not (a.reason or "").strip():
        block("reason_required", "취소 사유(--reason)가 필요합니다.")
    d = cr_diff(project, st, cr)
    if d["files"] or d["assets"]:
        block("restore_required", "범위 파일이 기준과 다릅니다. 기준 상태로 되돌린 뒤 취소합니다(엔진은 파일을 되돌리지 않음).", files=d["files"], assets=d["assets"])
    rights = (st.setdefault("exploration", {})).setdefault("asset_rights", {})
    restored = []
    for aid, rec in (cr.get("rights_backup") or {}).items():  # 제자리 교체·재확인으로 바뀐 권리 기록을 CR 이전으로 되돌림
        if rec is None:
            rights.pop(aid, None)
        else:
            rights[aid] = rec
        restored.append(aid)
    base_reg = cr["base"].get("registry") or {}
    for aid in [x for x in list(rights) if x not in base_reg and x not in registry_entries(project, st)]:
        rights.pop(aid, None)  # 취소된 후속 자산의 권리 기록(레지스트리에서 이미 제거됨)
        restored.append(aid)
    cr["status"] = "cancelled"
    cr["history"].append({"at": now(), "event": "cancelled", "reason": a.reason.strip(), "rights_restored": sorted(set(restored))})
    add_history(st, "design", "change_cancelled", None, f"{cr['id']}: {a.reason.strip()[:120]}")
    save_state(project, st)
    emit({"ok": True, "id": cr["id"], "status": "cancelled"})


def _rebase_cmd(project: Path, st: dict, a) -> None:
    """다른 패치가 승인돼 기준이 바뀐 CR을, 그 사이 패치와 겹치지 않을 때만 새 기준으로 옮깁니다(겹치면 차단)."""
    cr = _get_cr(st, a.id)
    if cr["status"] not in ACTIVE:
        block("invalid_transition", f"{cr['id']} 상태가 {cr['status']}입니다.")
    eff = require_chain_ok(st)
    if cr["base"]["chain_head"] == eff["head"]:
        emit({"ok": True, "id": cr["id"], "status": "up_to_date"})
    chain = st["changes"]["chain"]
    since = chain[int(cr["base"]["chain_head"].get("count") or 0):]
    sp = scope_paths(project, st, cr)
    touched = {f for x in since for f in (x.get("file_transitions") or {})}
    t_assets = {aid for x in since for sd in (x.get("stages") or {}).values() for aid in (sd.get("assets") or {})}
    t_screens = [x.get("screens") for x in since]
    overlap = sorted((touched & sp) | (t_assets & set(cr["scope"].get("assets") or [])))
    my_sc = cr["scope"].get("screens")
    if overlap or my_sc is None or any(s is None or set(s) & set(my_sc) for s in t_screens):
        block("cr_rebase_conflict", "그 사이 승인된 패치와 같은 파일·자산·화면을 다룹니다(또는 범위를 알 수 없음). cancel 후 새 기준에서 다시 엽니다.",
              overlap=overlap, since=[x["id"] for x in since])
    pv_touched = any(f.startswith(PREVIEW_DIR + "/") for f in touched)
    if pv_touched and any(f.startswith(PREVIEW_DIR + "/") for f in sp):
        block("cr_rebase_conflict", "그 사이 패치와 이 CR이 모두 프리뷰 트리를 바꿉니다(트리 해시가 하나라 자동으로 합치지 않음, M3).")
    for x in since:
        for rel, (b, aft) in (x.get("file_transitions") or {}).items():
            cr["base"]["files"][rel] = aft
    cr["base"].update(effective_digest=eff["digest"], chain_head=eff["head"], registry=registry_entries(project, st) if not cr["scope"].get("assets") else cr["base"]["registry"],
                      stage_revisions={k: (s.get("approved") or {}).get("revision") for k, s in st["stages"].items()})
    for aid in t_assets:
        if aid in registry_entries(project, st):
            cr["base"]["registry"][aid] = registry_entries(project, st)[aid]
    cr["verification"] = None
    cr["submitted"] = None
    if cr["status"] in ("verified", "awaiting_confirmation"):
        cr["status"] = "in_progress"
    cr["history"].append({"at": now(), "event": "rebased", "onto": eff["head"]})
    add_history(st, "design", "change_rebased", None, f"{cr['id']} → head {eff['head'].get('count')}")
    save_state(project, st)
    emit({"ok": True, "id": cr["id"], "status": cr["status"], "rebased_onto": eff["head"], "next": f"change verify --id {cr['id']}"})
