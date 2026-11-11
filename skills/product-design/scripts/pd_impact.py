"""/product-design 디자인 변경 영향 분류(WF-D01)와 기획 변경 영향(impact). (product_design.py에서 함수 이동만 함)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from pd_core import *  # noqa: F401,F403
from pd_theme import *  # noqa: F401,F403


def id_blocks(text: str) -> dict[str, str]:
    """기획 문서에서 ID별 블록(헤딩 블록 또는 표 행)을 추출합니다."""
    out: dict[str, str] = {}
    for prefix, level in (("US", 3), ("AC", 3), ("FLOW", 2)):
        out.update(blocks_by_heading(text, level, prefix))
    for pat in (r"FR-\d{3}", r"NFR-\d{3}", CONFIRMED_RE):
        for k, cols in table_rows(text, pat).items():
            out[k] = " | ".join(cols)
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\|\s*|-\s*)(FLOW-\d{3}-S\d+[a-z]?)\b(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def refs_for(project: Path, ids: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not ids:
        return out
    docs = {UXP_FILE: [("UXD", 3), ("DQ", 3), ("PF", 3)], SCREENS_FILE: [("SCR", 2)], UISYS_FILE: [("CMP", 3)]}
    for rel, kinds in docs.items():
        text = strip_comments(read_text(project, rel))
        for prefix, level in kinds:
            for k, b in blocks_by_heading(text, level, prefix).items():
                hit = sorted(i for i in ids if re.search(rf"\b{re.escape(i)}\b(?!-)", b))
                if hit:
                    out[k] = hit
    for rel in (IA_FILE, FLOWS_FILE, TRACE_FILE):
        text = read_text(project, rel)
        for line in text.splitlines():
            for i in ids:
                if re.search(rf"\b{re.escape(i)}\b(?!-)", line):
                    out.setdefault(rel, [])
                    if i not in out[rel]:
                        out[rel].append(i)
    return out


# ---------------------------------------------------------------- 디자인 변경 영향 분류(WF-D01)
# 규칙 문서: reference/change-impact.md. 프로젝트 고유 정책(배치 규칙, 수치 성격 등)은 요청 JSON의 사실로 받고 엔진에 넣지 않습니다.
CHANGE_CATEGORIES = {
    "info_behavior":   {"no": "①", "label": "정보·행동",      "target": "ux_spec"},
    "token_semantics": {"no": "②", "label": "토큰 의미·이름", "target": "ux_spec"},
    "theme_value":     {"no": "③", "label": "테마 값",        "target": "theme"},
    "visual":          {"no": "④", "label": "시각 표현",      "target": "design_direction"},
    "implementation":  {"no": "⑤", "label": "구현 메모",      "target": "render"},
}
CATEGORY_ORDER = list(CHANGE_CATEGORIES)
# 로드맵의 목표 단계가 현재 엔진에 없을 때, 지금(v1) 실제로 적용되는 단계와 이유
V1_EFFECTIVE = {
    "theme_value": ("ux_spec", "v1에는 테마 게이트가 없고 토큰 값은 04(UX 설계)에 있습니다. v1 규칙 '토큰 변경 = UX 설계 변경'이 적용됩니다."),
    "visual": ("preview", "v1에는 Design Direction 단계가 없습니다. 시각 표현은 프리뷰 단계에서 반영합니다(reference/preview.md)."),
    "implementation": ("preview", "v1에는 렌더 결과만 다시 확인하는 단계가 없습니다. 프리뷰 파일이 바뀌면 트리 해시가 바뀌므로 프리뷰 승인이 영향을 받습니다."),
}
STYLE_DECORATIVE = {"radius", "border", "shadow", "elevation", "font_weight", "font_size", "font_family", "line_height",
                    "color_usage", "spacing", "opacity", "motion", "safe_area", "density"}
STYLE_STRUCTURAL = {"icon", "grouping", "layout", "alignment", "illustration"}
A11Y_SENSITIVE = {"border", "color_usage", "opacity", "font_size"}
NEW_VISUAL_POLICY = {"safe_area", "density"}
FACT_KINDS = ("info", "behavior", "placement", "token_name", "token_value", "style", "dimension", "notation",
              "implementation_note", "defect")


def classify_fact(fact: dict, ctx: dict) -> dict:
    """사실 하나를 분류합니다. confidence: auto | conditional | needs_review | excluded."""
    kind = fact.get("kind")
    r = {"kind": kind, "category": None, "confidence": "needs_review", "alternative": None, "condition": None,
         "reason": "", "flags": [], "evidence": {}, "checked_against": []}
    refs = [x for x in [fact.get("screen"), fact.get("component")] + list(fact.get("refs") or []) if x]
    if refs:
        unknown = [x for x in refs if not _ref_exists(ctx, x)]
        r["evidence"]["refs"] = refs
        r["checked_against"] += [SCREENS_FILE, UISYS_FILE, UXP_FILE]
        if unknown:
            r["evidence"]["unknown_refs"] = unknown
    def done(cat, conf, reason, alt=None, cond=None):
        r.update(category=cat, confidence=conf, reason=reason, alternative=alt, condition=cond)
        if r["evidence"].get("unknown_refs") and conf in ("auto", "conditional"):
            r["confidence"] = "needs_review"
            r["reason"] += f" — 승인 문서에서 찾을 수 없는 참조가 있어 확정하지 않습니다: {', '.join(r['evidence']['unknown_refs'])}"
        return r
    if kind == "defect":
        r.update(confidence="excluded", reason="결함 보고는 변경 요청이 아니므로 분류하지 않습니다(원인 판단은 사람).")
        return r
    if kind in ("info", "behavior"):
        return done("info_behavior", "auto", "화면의 정보 항목이나 행동·상태·흐름이 바뀝니다.")
    if kind == "placement":
        rule = fact.get("spec_rule")
        if rule == "fixed":
            return done("info_behavior", "auto", "명세가 위치를 정한 요소의 배치가 바뀝니다.")
        if rule == "free":
            return done("visual", "auto", "명세가 위치를 정하지 않았다고 명시한 요소의 배치 변경입니다.")
        return done("info_behavior", "conditional", "배치가 바뀌었지만 명세가 위치를 정하는지 기록되어 있지 않습니다.",
                    alt="visual", cond="명세의 배치 규칙이 위치를 고정하면 ①, 정하지 않으면 ④")
    if kind in ("token_name", "token_value"):
        tokens = fact.get("tokens") or ([fact["token"]] if fact.get("token") else [])
        r["checked_against"].append(f"{UISYS_FILE}#토큰")
        if not tokens:
            return done(None, "needs_review", "토큰 이름이 없습니다.")
        known = {t: (t in ctx["tokens"]) for t in tokens}
        r["evidence"]["tokens"] = {t: ("04에 있음" if k else "04에 없음") for t, k in known.items()}
        if kind == "token_name":
            op = fact.get("op", "add")
            if op == "add" and all(known.values()):
                return done(None, "needs_review", "추가한다는 토큰 이름이 이미 04에 있습니다.")
            if op in ("remove", "rename") and not all(known.values()):
                return done(None, "needs_review", "없애거나 바꾼다는 토큰 이름이 04에 없습니다.")
            return done("token_semantics", "auto", f"의미 토큰 이름 {op}: 04의 이름 목록과 대조했습니다.")
        if not all(known.values()):
            return done("token_semantics", "auto", "04에 없는 이름에 값을 정하므로 새 의미 토큰(이름 추가)입니다.")
        if fact.get("op") == "not_updated":
            r["flags"].append("theme_omission")
            return done("theme_value", "auto", "테마를 바꾸면서 같은 계열 토큰의 값이 이전 값으로 남았습니다(누락).")
        return done("theme_value", "auto", "04에 있는 의미 토큰 이름은 그대로이고 값만 바뀝니다.")
    if kind == "style":
        prop = fact.get("property")
        if fact.get("within_tokens") is False:
            r["flags"].append("outside_tokens")
        if prop in A11Y_SENSITIVE:
            r["flags"].append("accessibility_check")
        if prop in NEW_VISUAL_POLICY:
            r["flags"].append("new_visual_value")
        if prop in STYLE_DECORATIVE:
            return done("visual", "auto", f"같은 요소의 표현 속성({prop})만 바뀝니다.")
        if prop in STYLE_STRUCTURAL:
            return done("visual", "conditional", f"표현 요소({prop})가 바뀌거나 더해집니다.",
                        alt="info_behavior", cond="새 요소가 정보 의미를 전달하지 않으면 ④, 전달하면 ①")
        return done(None, "needs_review", f"알 수 없는 표현 속성입니다: {prop}")
    if kind == "dimension":
        spec = fact.get("spec") or {}
        bound, value = spec.get("bound"), fact.get("value")
        r["checked_against"].append(UISYS_FILE)
        if not isinstance(value, (int, float)):
            return done(None, "needs_review", "수치(value)가 없습니다.")
        if bound in ("min", "max") and isinstance(spec.get("value"), (int, float)):
            ok = value >= spec["value"] if bound == "min" else value <= spec["value"]
            if not ok:
                r["flags"].append("spec_conflict")
            return done("visual", "auto", f"명세 {bound} {spec['value']} 기준 {value}" + ("(명세 값 위반)" if not ok else ""))
        if bound in ("fixed", "enumerated"):
            allowed = spec.get("values") or ([spec["value"]] if "value" in spec else [])
            if value not in allowed:
                r["flags"].append("spec_conflict")
            return done("visual", "auto", f"명세 값 {allowed} 기준 {value}" + ("(명세 값 위반)" if value not in allowed else ""))
        return done("visual", "conditional", "명세 수치와 다르지만 그 수치가 최솟값인지 고정값인지 명세에 없습니다.",
                    alt="info_behavior", cond="명세 수치가 최솟값이면 ④, 고정값이면 명세 위반(되돌리거나 UX Spec 개정)")
    if kind == "notation":
        return done(None, "needs_review", "명세의 표기 규칙이 '보이는 글자'인지 '정보 순서'인지 사람이 판단해야 합니다.")
    if kind == "implementation_note":
        return done("implementation", "auto", "보이는 결과와 정보·행동에 영향이 없는 구현 메모입니다.")
    return done(None, "needs_review", f"알 수 없는 사실 종류입니다: {kind} (허용: {', '.join(FACT_KINDS)})")


def stage_impact(st: dict, category: str, stage_override: str | None = None, render_affecting: bool | None = None) -> dict:
    """유형별 영향. v1은 기존 규칙(V1_EFFECTIVE). v2는 무효화 규칙표(reference/change-impact.md §5)를 따릅니다."""
    wf = workflow_of(st)
    order = stage_list(st)
    meta = CHANGE_CATEGORIES[category]
    target = stage_override or meta["target"]
    available = target in IMPLEMENTED_STAGES and target in order
    preserved: list[str] = []
    if available:
        effective, why = target, ""
    elif wf == "v2" and category == "theme_value" and (st.get("config") or {}).get("theme_file"):
        effective, why = "preview", ("v2: 테마 값은 테마 파일에 있으므로 UX Spec·Design Direction 승인은 유지하고, "
                                     "프리뷰 렌더 결과만 다시 검증·승인합니다.")
        preserved = ["ux_spec", "design_direction"]
    elif wf == "v2" and category == "theme_value":
        effective, why = "ux_spec", "v2지만 config.theme_file이 없어 토큰 값이 04(UX 설계)에 있습니다. v1 규칙 '토큰 변경 = UX 설계 변경'이 적용됩니다."
    elif wf == "v2" and category == "implementation":
        effective, why = "preview", "v2: 프리뷰 의미 해시(주석·공백·문서 제외)가 바뀔 때만 프리뷰 재검증·재승인이 필요합니다."
    else:
        effective, why = V1_EFFECTIVE[category]
    s = st["stages"][effective]["status"]
    idx = order.index(effective)
    downstream = [k for k in dependents_of(st, effective) if st["stages"][k]["status"] in ("approved", "awaiting_approval")]
    if wf == "v2" and category == "implementation" and not available and render_affecting is not True:
        render_note = ("주석·공백·문서만 바뀌어 승인 산출물(의미 해시)에 영향이 없습니다." if render_affecting is False
                       else "의미 해시 영향을 알 수 없습니다. 코드·설정이 바뀌면 다시 분류하세요(그 경우 프리뷰 재승인).")
        return {"category": category, "target_stage": target, "target_available": False, "effective_stage": effective,
                "effective_reason": why, "effective_status": s, "action": "재승인 불필요(구현 메모). 필요하면 preview-verify로 빌드만 확인",
                "reapproval_required": False, "reapproval_stages": [], "invalidates": [], "preserved": ["ux_spec", "design_direction", "preview"],
                "render_note": render_note, "workflow": wf}
    if s == "approved":
        action, reapproval = f"reopen --stage {effective} (승인 해제 후 수정·재제출·재승인)", [effective] + downstream
    elif s == "awaiting_approval":
        action, reapproval = f"reopen --stage {effective} (수정 요청으로 처리 후 재제출)", [effective] + downstream
    elif s == "in_progress":
        action, reapproval = "현재 작성 중인 revision에서 반영 후 done·제출", []
    else:
        action, reapproval = f"{effective} 단계를 진행할 때 반영(현재 {s})", []
    out = {"category": category, "target_stage": target, "target_available": available,
           "effective_stage": effective, "effective_reason": why, "effective_status": s,
           "action": action, "reapproval_required": bool(reapproval), "reapproval_stages": reapproval,
           "invalidates": downstream if s in ("approved", "awaiting_approval") else []}
    if wf == "v2":
        out.update(preserved=preserved, workflow=wf)
    return out


def aggregate_item(item_id: str, summary: str, facts: list[dict], st: dict, doc_stage: str | None = None,
                   source: dict | None = None) -> dict:
    live = [f for f in facts if f["confidence"] != "excluded"]
    if not live:
        status = "excluded"
    elif any(f["confidence"] == "needs_review" for f in live):
        status = "needs_review"
    elif any(f["confidence"] == "conditional" for f in live):
        status = "conditional"
    else:
        status = "classified"
    cats = [c for c in CATEGORY_ORDER if any(f["category"] == c for f in live)]
    alts = [c for c in CATEGORY_ORDER if any(f.get("alternative") == c for f in live) and c not in cats]
    flags = sorted({fl for f in facts for fl in f["flags"]})
    flags_ra = [f["evidence"].get("affects_render_hash") for f in live if "affects_render_hash" in f["evidence"]]
    render_affecting = None if not flags_ra else any(flags_ra)
    impacts = [stage_impact(st, c, render_affecting=render_affecting) for c in cats]
    order = stage_list(st)
    if doc_stage:
        # 바뀐 파일이 분류상 단계보다 앞선 단계의 산출물이면(예: 00 → ux_planning) 그 단계부터 다시 엽니다.
        impacts = [stage_impact(st, i["category"], stage_override=doc_stage)
                   if order.index(doc_stage) < order.index(i["effective_stage"]) else i for i in impacts]
    possible = [stage_impact(st, c) for c in alts]
    if workflow_of(st) == "v2" and "visual" in cats and not any(i["effective_stage"] == "preview" for i in impacts):
        r = stage_impact(st, "visual", stage_override="preview")
        r["effective_reason"] = "시각 표현은 프리뷰 렌더 결과에도 반영됩니다(최종 시각 승인은 preview)."
        impacts.append(r)
    if doc_stage and not any(i["effective_stage"] == doc_stage for i in impacts) \
            and not (workflow_of(st) == "v2" and render_affecting is False and doc_stage == "preview"):
        # 파일이 속한 단계(승인 산출물)는 분류와 관계없이 영향을 받습니다.
        cat = cats[0] if cats else "info_behavior"
        d = stage_impact(st, cat, stage_override=doc_stage)
        d.update(category=None, effective_reason=f"바뀐 파일이 {doc_stage} 단계 산출물입니다.")
        impacts.append(d)
    reapproval = []
    for i in impacts:
        for s in i["reapproval_stages"]:
            if s not in reapproval:
                reapproval.append(s)
    notes = []
    if "spec_conflict" in flags:
        notes.append("명세 값과 다릅니다. 명세 값으로 되돌리거나, 값을 유지하려면 UX Spec 개정(①)으로 다시 요청하세요.")
    if "accessibility_check" in flags:
        notes.append("대비·경계 확인이 필요합니다(자동 검사는 M2 WF-D09·D10 예정, 지금은 review-checklist로 확인).")
    if "outside_tokens" in flags:
        notes.append("승인된 토큰 밖의 값입니다. 토큰을 추가하려면 ②(UX Spec)로, 아니면 토큰 값으로 바꾸세요.")
    if "theme_omission" in flags:
        notes.append("테마 누락: 같은 계열 토큰 값을 함께 바꿔야 합니다.")
    if any(r.startswith("UXD-") for f in facts for r in f["evidence"].get("refs", [])) and "info_behavior" in cats:
        notes.append("참조한 UXD 결정 자체를 바꾸는 변경이면 ux_planning 재검토가 필요할 수 있습니다(사람 판단).")
    if status == "needs_review":
        notes.append("자동으로 확정하지 않았습니다. 사람이 분류를 정한 뒤 진행하세요(영향은 확정 전 추정).")
    return {"id": item_id, "summary": summary, "status": status,
            "requires_user_decision": status in ("conditional", "needs_review"), "auto_apply": False,
            "categories": [{"key": c, **{k: CHANGE_CATEGORIES[c][k] for k in ("no", "label")}} for c in cats],
            "primary": cats[0] if cats and status != "needs_review" else None,
            "possible_categories": alts, "flags": flags, "facts": facts, "impact": impacts, "possible_impact": possible,
            "reapproval_required": bool(reapproval), "reapproval_stages": reapproval, "notes": notes,
            **({"source": source} if source else {})}


def load_change_request(path: Path) -> list[dict]:
    try:
        req = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        block("invalid_request", f"변경 요청 파일을 읽을 수 없습니다: {e}")
    if not isinstance(req, dict) or req.get("schema") != "design-change-request/v1" or not isinstance(req.get("items"), list):
        block("invalid_request", "형식: {\"schema\": \"design-change-request/v1\", \"items\": [{\"id\", \"summary\", \"facts\": [...]}]}")
    seen = set()
    for it in req["items"]:
        if not isinstance(it, dict) or not it.get("id") or not isinstance(it.get("facts"), list):
            block("invalid_request", "각 항목에는 id와 facts(목록)가 필요합니다.", item=it)
        if it["id"] in seen:
            block("invalid_request", f"항목 id 중복: {it['id']}")
        seen.add(it["id"])
    return req["items"]


def _git_old(project: Path, base: str, rel: str) -> str:
    try:
        return git(project, "show", f"{base}:{rel}")
    except RuntimeError:
        return ""


def file_change_items(project: Path, st: dict, base: str, ctx: dict) -> tuple[list[dict], list[str]]:
    """base 커밋과 작업 트리의 차이를 파일·토큰 이름 기준으로 분류합니다."""
    try:
        git(project, "rev-parse", "--verify", f"{base}^{{commit}}")
    except RuntimeError:
        block("invalid_base", f"기준 커밋을 찾을 수 없습니다: {base}")
    changed = [x for x in git(project, "diff", "--name-only", base, "--").splitlines() if x]
    changed += [x for x in git(project, "ls-files", "--others", "--exclude-standard").splitlines() if x]
    items, unrelated = [], []
    for rel in sorted(set(changed)):
        old, new = _git_old(project, base, rel), read_text(project, rel)
        stage = stage_of(rel)
        facts: list[dict] = []
        def fact(cat, conf, reason, **ev):
            return {"kind": "file_change", "category": cat, "confidence": conf, "alternative": None, "condition": None,
                    "reason": reason, "flags": [], "evidence": {"path": rel, **ev}, "checked_against": [rel]}
        if rel.startswith("docs/planning/") or rel == WORKFLOW_STATE_REL:
            f = fact(None, "excluded", "기획 변경은 디자인 분류 대상이 아닙니다. 기존 `impact`(기획 영향)와 `rebase`를 쓰세요.")
            facts.append(f)
        elif rel == UISYS_FILE:
            ot, nt = parse_tokens(old), parse_tokens(new)
            for n in sorted(set(nt) - set(ot)):
                facts.append(classify_fact({"kind": "token_name", "op": "add", "token": n}, {**ctx, "tokens": ot}) | {"evidence": {"path": rel, "tokens": {n: "추가"}}})
            for n in sorted(set(ot) - set(nt)):
                facts.append(classify_fact({"kind": "token_name", "op": "remove", "token": n}, {**ctx, "tokens": ot}) | {"evidence": {"path": rel, "tokens": {n: "삭제"}}})
            for n in sorted(k for k in set(ot) & set(nt) if ot[k] != nt[k]):
                facts.append(classify_fact({"kind": "token_value", "token": n}, {**ctx, "tokens": ot}) | {"evidence": {"path": rel, "tokens": {n: f"{ot[n]} → {nt[n]}"}}})
            def strip_tokens(text):
                return "\n".join(l for l in strip_fences(text).splitlines()
                                 if not (l.lstrip().startswith("|") and TOKEN_NAME_RE.match((l.strip().strip("|").split("|")[0].strip().split("/")[0].strip().strip("`")) or "")))
            if strip_tokens(old) != strip_tokens(new):
                ids = changed_ids(old, new)
                facts.append(fact(None, "needs_review", "토큰 표 밖(컴포넌트 등) 내용이 바뀌었습니다. 정보·행동인지 시각 표현인지 사람이 판단합니다.", ids=ids))
        elif rel in (UXP_FILE, IA_FILE, SCREENS_FILE, FLOWS_FILE, TRACE_FILE):
            ids = changed_ids(old, new)
            facts.append(fact("info_behavior", "auto", "승인 대상 UX 문서(정보·행동·흐름·추적성)가 바뀌었습니다.", ids=ids))
        elif rel == REVIEW_FILE:
            facts.append(fact("implementation", "auto", "프리뷰 검토 기록(06)이 바뀌었습니다."))
        elif rel.startswith(PREVIEW_DIR + "/"):
            name = Path(rel).name
            if name == "tokens.css" or rel.endswith("/tokens.css"):
                ov, nv = parse_css_vars(old), parse_css_vars(new)
                for v in sorted(set(nv) - set(ov)) + sorted(set(ov) - set(nv)):
                    facts.append(fact("token_semantics", "auto", "토큰 CSS 변수 이름이 추가·삭제되었습니다.", css_var=v))
                for v in sorted(k for k in set(ov) & set(nv) if ov[k] != nv[k]):
                    facts.append(fact("theme_value", "auto", "토큰 CSS 변수 이름은 그대로이고 값만 바뀌었습니다.", css_var=v, value=f"{ov[v]} → {nv[v]}"))
                if not facts:
                    facts.append(fact("implementation", "auto", "토큰 CSS의 주석·형식만 바뀌었습니다."))
            elif rel.endswith(".css"):
                facts.append(fact("visual", "auto", "프리뷰 스타일시트만 바뀌었습니다."))
            elif rel.endswith(JS_EXT):
                norm = lambda s: re.sub(r"\s+", "", strip_js_comments(s))
                if norm(old) == norm(new):
                    same = sem_normalize(rel, old.encode()) == sem_normalize(rel, new.encode())
                    facts.append(fact("implementation", "auto", "주석·공백만 바뀌었습니다."
                                      + ("" if same else " 다만 이 형식은 의미 해시에서 원본으로 비교하므로(JSX 등) 프리뷰 재승인이 필요합니다."),
                                      affects_render_hash=not same))
                else:
                    facts.append(fact(None, "needs_review", "프리뷰 코드가 바뀌었습니다. 정보·행동 변경인지 시각 표현인지 자동으로 판정할 수 없습니다."))
            elif name == "preview.manifest.json":
                facts.append(fact(None, "needs_review", "프리뷰 화면·상태 목록이 바뀌었습니다. 02 문서와의 관계를 사람이 판단합니다."))
            else:
                is_doc = rel.lower().endswith(".md") and sem_normalize(rel, b"", md_referenced=any(
                    Path(rel).name in read_text(project, r) for r in preview_files(project) if not r.lower().endswith(".md"))) is None
                facts.append(fact("implementation", "auto", "프리뷰 설정·의존성·문서 파일이 바뀌었습니다(화면 표현과 무관한 구현)."
                                  + (" 문서라 의미 해시에 들어가지 않습니다." if is_doc else " 빌드·렌더에 영향을 줄 수 있어 의미 해시에 들어갑니다."),
                                  affects_render_hash=not is_doc))
        elif workflow_of(st) == "v2" and rel == (st.get("config") or {}).get("theme_file"):
            ot, nt = read_theme(project, rel, old or "{}"), read_theme(project, rel, new or "{}")
            if ot["contract"] and nt["contract"]:
                for n in sorted(set(nt["resolved"]) - set(ot["resolved"])) + sorted(set(ot["resolved"]) - set(nt["resolved"])):
                    facts.append(fact("token_semantics", "auto", "테마의 의미 토큰 이름이 추가·삭제되었습니다(04 이름 개정 필요).", tokens={n: "이름 변경"}))
                for n in sorted(k for k in set(ot["resolved"]) & set(nt["resolved"]) if ot["resolved"][k] != nt["resolved"][k]):
                    facts.append(fact("theme_value", "auto", "테마 값만 바뀌었습니다.", tokens={n: f"{ot['resolved'][n]} → {nt['resolved'][n]}"}))
                if not facts:
                    facts.append(fact("implementation", "auto", "테마의 해석된 값은 그대로입니다(형식·메모·원시 이름 정리).", affects_render_hash=False))
            else:
                facts.append(fact("theme_value", "auto", "테마 계약 이전 형식 파일이 바뀌었습니다(해시 기준 테마 값 변경으로 봄)."))
            items.append(aggregate_item(f"file:{rel}", rel, facts, st, source={"path": rel, "base": base}))
            continue
        else:
            unrelated.append(rel)
            continue
        items.append(aggregate_item(f"file:{rel}", rel, facts, st, doc_stage=stage if stage else (
            "preview" if rel.startswith(PREVIEW_DIR + "/") else None), source={"path": rel, "base": base}))
    return items, unrelated


def _owner_blocks(text: str) -> dict[str, str]:
    """헤딩(##~####) 단위로 내용을 나눠, 각 줄을 가장 가까운 ID 헤딩(SCR·CMP·UXD·US·AC·FLOW 등)에 붙입니다."""
    owners: dict[str, list[str]] = {}
    stack: dict[int, str] = {}
    for line in strip_comments(text).splitlines():
        m = re.match(r"^(#{1,4}) (.*)$", line)
        if m:
            level = len(m.group(1))
            for k in [k for k in stack if k >= level]:
                del stack[k]
            ident = re.match(r"(" + DESIGN_ID_RE + "|" + ID_RE + r")", m.group(2).strip())
            if ident:
                stack[level] = ident.group(1)
        owner = stack[max(stack)] if stack else ""
        owners.setdefault(owner, []).append(line)
    return {k: "\n".join(v) for k, v in owners.items() if k}


def changed_ids(old: str, new: str) -> list[str]:
    """바뀐 헤딩 블록의 ID와, 바뀐 줄(표 행 등)에 직접 나오는 ID를 모읍니다."""
    ob, nb = _owner_blocks(old), _owner_blocks(new)
    ids = {k for k in set(ob) | set(nb) if ob.get(k) != nb.get(k)}
    ids |= set(re.findall(DESIGN_ID_RE + "|" + ID_RE, _diff_lines(old, new)))
    return sorted(ids)


def _diff_lines(old: str, new: str) -> str:
    import difflib
    return "\n".join(l for l in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
                     if l[:1] in "+-" and not l.startswith(("+++", "---")))


__all__ = [
    'A11Y_SENSITIVE',
    'CATEGORY_ORDER',
    'CHANGE_CATEGORIES',
    'FACT_KINDS',
    'NEW_VISUAL_POLICY',
    'STYLE_DECORATIVE',
    'STYLE_STRUCTURAL',
    'V1_EFFECTIVE',
    '_diff_lines',
    '_git_old',
    '_owner_blocks',
    'aggregate_item',
    'changed_ids',
    'classify_fact',
    'file_change_items',
    'id_blocks',
    'load_change_request',
    'refs_for',
    'stage_impact',
]
