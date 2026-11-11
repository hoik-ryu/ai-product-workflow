"""/product-design 테마 계약(WF-D03)·렌더러 경로(WF-D04)·프리뷰 계약 검사(preview_check). (product_design.py에서 함수 이동만 함)
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


def preview_check(project: Path, st: dict) -> dict:
    errors, warnings = [], []
    root = project / PREVIEW_DIR
    if not root.exists():
        return {"ok": False, "errors": [f"{PREVIEW_DIR}/가 없습니다. preview-scaffold를 먼저 실행하세요."], "warnings": []}
    mp = project / PREVIEW_MANIFEST
    try:
        man = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"{PREVIEW_MANIFEST}을 읽을 수 없습니다: {e}"], "warnings": []}
    ux = st["stages"]["ux_spec"]
    appr_rev = (ux.get("approved") or {}).get("revision")
    if ux["status"] != "approved":
        errors.append("UX 설계가 승인되지 않았습니다. 프리뷰는 승인된 UX 설계를 기준으로만 만듭니다.")
    if man.get("ux_spec_revision") != appr_rev:
        errors.append(f"프리뷰 manifest의 ux_spec_revision({man.get('ux_spec_revision')})이 승인된 UX 설계 revision({appr_rev})과 다릅니다")
    scr = screen_info(project)
    screens = man.get("screens") or {}
    if gate_on(st):
        dd = st["stages"]["design_direction"]
        dd_rev = (dd.get("approved") or {}).get("revision") if dd["status"] == "approved" else None
        if man.get("design_direction_revision") != dd_rev or dd_rev is None:
            errors.append(f"프리뷰 manifest의 design_direction_revision({man.get('design_direction_revision')})이 승인된 Design Direction revision({dd_rev})과 다릅니다")
        approved_vds = set((dd.get("approved") or {}).get("approved_vds") or [])
        for sid, entry in screens.items():
            for v in (entry or {}).get("vd", []):
                if v not in approved_vds:
                    errors.append(f"{sid}: 승인되지 않은 시각 결정 {v}를 정식 렌더링에 쓸 수 없습니다")
    registry = read_text(project, f"{PREVIEW_DIR}/src/registry.tsx")
    for s in sorted(scr):
        entry = screens.get(s)
        if entry is None:
            errors.append(f"{s}가 프리뷰 manifest에 없습니다(제외하려면 \"skip\": \"사유\")")
            continue
        if entry.get("skip"):
            continue
        f = entry.get("file")
        if not f or not (root / f).exists():
            errors.append(f"{s}: 화면 파일이 없습니다 ({f})")
        if f'"{s}"' not in registry:
            errors.append(f"{s}: src/registry.tsx에 등록되어 있지 않습니다")
        for state_id in entry.get("states", []):
            if state_id not in scr[s]["states"]:
                errors.append(f"{s}: {SCREENS_FILE}에 없는 상태 {state_id}")
        if not entry.get("states"):
            warnings.append(f"{s}: 프리뷰에 표시할 상태가 지정되지 않았습니다")
    for s in screens:
        if s not in scr:
            errors.append(f"프리뷰 manifest의 {s}가 {SCREENS_FILE}에 없습니다")
    # 경계: 프리뷰는 실제 API·제품 코드·프리뷰 밖 경로를 쓰지 않고, 제품 코드도 프리뷰를 참조하지 않음
    errors += preview_isolation(project)
    if workflow_of(st) == "v2":
        tc = theme_check(project, st)
        if tc["applicable"] and tc["contract"]:
            errors += [f"테마: {e}" for e in tc["errors"]]
            warnings += [f"테마: {w}" for w in tc["warnings"]]
        rc = renderer_check(project, st)
        errors += [f"렌더러: {e}" for e in rc["errors"]]
    for probe in ("node_modules", "dist"):
        rc = subprocess.run(["git", "-C", str(project), "check-ignore", "-q", f"{PREVIEW_DIR}/{probe}/.probe"]).returncode
        if rc != 0:
            errors.append(f"{PREVIEW_DIR}/{probe}가 Git에서 무시되지 않습니다")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"screens_in_spec": len(scr), "screens_in_preview": len([s for s in screens if not (screens[s] or {}).get('skip')]),
                       "states_in_preview": sum(len((v or {}).get("states", [])) for v in screens.values())}}


# ---------------------------------------------------------------- 테마 계약(WF-D03)과 렌더러 경로(WF-D04)
# 우선순위(v2, 테마 계약 적용 시): 렌더링 값의 기준 = 테마 파일. 04 문서의 값 = 승인 당시 기준 기록(자동 수정하지 않음).
# 04는 의미 토큰 '이름'과 제약을 승인합니다. 테마에 없는 04 토큰은 04 값으로 렌더합니다(대체값).
THEME_SCHEMA = "design-theme/v1"
THEME_REF_RE = re.compile(r"^\{([A-Za-z0-9_.-]+)\}$")
COLOR_VALUE_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|(rgb|rgba|hsl|hsla)\(.+\)|transparent|currentColor)$")
LENGTH_VALUE_RE = re.compile(r"^-?\d+(\.\d+)?(px|rem|em|%|vh|vw|dvh|svh)?$")
LENGTH_PREFIXES = ("space.", "size.", "radius.", "font.size.")
DEFAULT_CSS_FILE = "design-preview/src/tokens.css"
DEFAULT_VAR_PATTERN = "--{dashed}"


def token_kind(name: str) -> str:
    head = name.split(".", 1)[0]
    return {"color": "color", "font": "typography", "space": "spacing", "size": "size", "radius": "shape"}.get(head, "component")


def _norm_value(v: str) -> str:
    return re.sub(r"\s+", " ", str(v).strip()).lower()


def css_var_name(name: str, pattern: str) -> str:
    return pattern.replace("{dashed}", name.replace(".", "-")).replace("{name}", name)


def read_theme(project: Path, rel: str, text: str | None = None) -> dict:
    """테마 파일을 읽어 계약(design-theme/v1) 여부, 원시 값, 의미 토큰, 해석된 값, 오류를 돌려줍니다."""
    out = {"path": rel, "exists": True, "contract": False, "errors": [], "data": None, "resolved": {}}
    if text is None:
        p = project / rel
        if not p.is_file():
            out.update(exists=False, errors=[f"테마 파일이 없습니다: {rel}"])
            return out
        text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        out["errors"].append(f"테마 파일 JSON 오류: {e}")
        return out
    out["data"] = data
    if not isinstance(data, dict) or data.get("schema") != THEME_SCHEMA:
        return out  # 이전 형식: 해시만 추적(계약 미적용)
    out["contract"] = True
    prims, toks = data.get("primitives", {}), data.get("tokens")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        out["errors"].append("name(테마 이름)이 필요합니다")
    if not isinstance(prims, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in prims.items()):
        out["errors"].append("primitives는 {이름: 값(문자열)} 이어야 합니다")
        prims = {}
    if not isinstance(toks, dict) or not toks:
        out["errors"].append("tokens는 {의미 토큰 이름: 값 또는 {원시 이름}} 이어야 합니다")
        toks = {}
    css = data.get("css", {}) or {}
    if not isinstance(css, dict):
        out["errors"].append("css는 {file, var_pattern} 이어야 합니다")
        css = {}
    for name, val in toks.items():
        if not isinstance(name, str) or not TOKEN_NAME_RE.match(name):
            out["errors"].append(f"토큰 이름 형식이 아닙니다: {name}")
            continue
        if not isinstance(val, str):
            out["errors"].append(f"{name}: 값은 문자열이어야 합니다")
            continue
        m = THEME_REF_RE.match(val.strip())
        if m:
            if m.group(1) not in prims:
                out["errors"].append(f"{name}: 없는 원시 값 참조 {val}")
                continue
            val = prims[m.group(1)]
        val = val.strip()
        kind = token_kind(name)
        if kind == "color" and not COLOR_VALUE_RE.match(val):
            out["errors"].append(f"{name}: 색 값 형식이 아닙니다 ({val})")
        elif name.startswith(LENGTH_PREFIXES) and not LENGTH_VALUE_RE.match(val):
            out["errors"].append(f"{name}: 길이 값 형식이 아닙니다 ({val})")
        out["resolved"][name] = val
    out["css_file"] = css.get("file", DEFAULT_CSS_FILE)
    out["var_pattern"] = css.get("var_pattern", DEFAULT_VAR_PATTERN)
    if not (isinstance(out["css_file"], str) and out["css_file"].startswith(PREVIEW_DIR + "/") and ".." not in Path(out["css_file"]).parts):
        out["errors"].append(f"css.file은 {PREVIEW_DIR}/ 안의 경로여야 합니다")
    if "{dashed}" not in str(out["var_pattern"]) and "{name}" not in str(out["var_pattern"]):
        out["errors"].append("css.var_pattern에는 {dashed} 또는 {name}이 있어야 합니다")
    return out


def theme_check(project: Path, st: dict) -> dict:
    """테마 계약 검사(읽기 전용): 스키마, 04 토큰 이름과 대조(새 이름은 ②), 값 형식, 04 값과의 차이(출처 추적), tokens.css 일치."""
    rel = (st.get("config") or {}).get("theme_file")
    res = {"applicable": workflow_of(st) == "v2" and bool(rel), "ok": True, "contract": False, "errors": [], "warnings": [],
           "divergence": [], "missing_in_theme": [], "sync": None, "sources": {}}
    if not res["applicable"]:
        res["warnings"].append("v2 테마 파일이 설정되지 않았습니다(04 값이 렌더 기준, v1 규칙).")
        return res
    th = read_theme(project, rel)
    res["contract"] = th["contract"]
    res["errors"] += th["errors"]
    ux = st["stages"]["ux_spec"]
    base = (ux.get("approved") or {})
    res["sources"] = {"04": {"path": UISYS_FILE, "ux_spec_revision": base.get("revision"), "hash": (base.get("hashes") or {}).get(UISYS_FILE)},
                      "theme": {"path": rel, "hash": theme_hash(project, st)}}
    if th["exists"] and not th["contract"] and not th["errors"]:
        res["warnings"].append(f"테마 계약({THEME_SCHEMA})이 적용되지 않은 이전 형식 파일입니다. 해시만 추적하고 값·tokens.css 일치는 검사하지 않습니다.")
    if th["contract"]:
        approved04 = parse_tokens(read_text(project, UISYS_FILE))
        for name in sorted(set(th["resolved"]) - set(approved04)):
            res["errors"].append(f"{name}: 04에 없는 의미 토큰 이름입니다. 새 이름·의미는 ②(UX Spec 04 개정)로 다루세요")
        res["missing_in_theme"] = sorted(set(approved04) - set(th["resolved"]))
        if res["missing_in_theme"]:
            res["warnings"].append(f"테마에 없는 04 토큰 {len(res['missing_in_theme'])}개는 04 값으로 렌더합니다: {', '.join(res['missing_in_theme'][:8])}")
        for name in sorted(set(th["resolved"]) & set(approved04)):
            if _norm_value(th["resolved"][name]) != _norm_value(approved04[name]):
                res["divergence"].append({"token": name, "approved_04_value": approved04[name], "theme_value": th["resolved"][name],
                                          "applied": "theme"})
        effective = {**{k: v for k, v in approved04.items() if k in res["missing_in_theme"]}, **{k: v for k, v in th["resolved"].items() if k in approved04}}
        res["effective_tokens"] = effective
        res["expected_css"] = ":root {\n" + "".join(f"  {css_var_name(k, th['var_pattern'])}: {v};\n" for k, v in sorted(effective.items())) + "}\n"
        css_path = project / th["css_file"]
        if css_path.is_file():
            cur = parse_css_vars(css_path.read_text(encoding="utf-8"))
            missing, mismatch = [], []
            for k, v in effective.items():
                var = css_var_name(k, th["var_pattern"])
                if var not in cur:
                    missing.append(var)
                elif _norm_value(cur[var]) != _norm_value(v):
                    mismatch.append({"var": var, "token": k, "css": cur[var], "expected": v})
            wanted = {css_var_name(k, th["var_pattern"]) for k in effective}
            extra = sorted(set(cur) - wanted)
            res["sync"] = {"file": th["css_file"], "missing": missing, "mismatch": mismatch, "extra": extra}
            for v in missing:
                res["errors"].append(f"{th['css_file']}: 토큰 변수 {v}가 없습니다(theme-check의 expected_css 참고)")
            for m in mismatch:
                res["errors"].append(f"{th['css_file']}: {m['var']} 값 {m['css']} ≠ 기준 {m['expected']}({m['token']})")
            if extra:
                res["warnings"].append(f"{th['css_file']}: 테마·04에 없는 변수 {len(extra)}개(프리뷰 셸 전용이면 무시): {', '.join(extra[:6])}")
        else:
            res["sync"] = {"file": th["css_file"], "skipped": "프리뷰가 아직 없습니다"}
    res["ok"] = not res["errors"]
    return res


def dd_render_scope(project: Path) -> list[str]:
    return list(table_rows(md_section(strip_fences(read_text(project, DD_FILE)), "렌더 범위"), r"SCR-\d{3}"))


def renderer_check(project: Path, st: dict) -> dict:
    """렌더러 경로 계약(WF-D04). 게이트가 켜진 v2에서 승인된 07의 렌더러와 06의 '사용 렌더러'·참조·비교 기록을 대조합니다.
    Figma는 검토용이며 최종 시각 승인은 경로와 관계없이 design-preview/ 트리 해시 + 06입니다."""
    dd = st["stages"].get("design_direction") or {}
    planned = ((dd.get("approved") or {}).get("renderer") or "code") if dd.get("status") == "approved" else "code"
    res = {"applicable": workflow_of(st) == "v2" and gate_on(st) and dd.get("status") == "approved",
           "planned": planned, "used": planned, "switched": False, "reason": None, "errors": [], "warnings": []}
    if not res["applicable"]:
        return res
    text = strip_fences(read_text(project, REVIEW_FILE))
    sec = md_section(text, "렌더러")
    used = _first_word(field_line(sec, "사용 렌더러")) or planned
    reason = field_line(sec, "전환 사유").strip()
    if reason.startswith("없음"):
        reason = ""
    res.update(used=used, reason=reason or None, switched=used != planned)
    if used not in RENDERERS:
        res["errors"].append(f"06 '사용 렌더러'는 {'/'.join(RENDERERS)} 중 하나여야 합니다 (현재: '{used}')")
        return res
    if used != planned:
        if used != "code":
            res["errors"].append(f"07 렌더러({planned})와 다른 경로({used})로 바꿀 수 없습니다. 경로를 바꾸려면 Design Direction을 다시 엽니다(code로 되돌아가는 것만 허용)")
        elif not reason:
            res["errors"].append(f"07 렌더러({planned})에서 code로 바꾼 이유(06 '전환 사유')가 필요합니다(예: Figma 호출 한도 초과)")
    scope = dd_render_scope(project)
    refs = table_rows(md_section(text, "외부 디자인 참조"), r"SCR-\d{3}")
    def has_figma(sid):
        cols = refs.get(sid) or []
        return bool(cols) and "figma" in cols[0].lower() and len(cols) > 1 and cols[1].strip() not in ("", "(선택)") and not cols[1].startswith("중단")
    if used == "figma":
        for sid in scope:
            if not has_figma(sid):
                res["errors"].append(f"{sid}: figma 경로인데 06 '외부 디자인 참조'에 Figma 링크가 없습니다(중단했다면 code로 전환하고 사유를 적으세요)")
    if used == "both":
        comp = table_rows(md_section(text, "렌더러 비교"), r"SCR-\d{3}")
        for sid in scope:
            cols = comp.get(sid)
            choice = _first_word(cols[0]) if cols else ""
            if choice not in ("code", "figma") or len(cols) < 2 or not cols[1].strip():
                res["errors"].append(f"{sid}: both 경로는 06 '렌더러 비교'에 선택(code|figma)과 근거가 필요합니다")
            elif choice == "figma" and not has_figma(sid):
                res["errors"].append(f"{sid}: figma 결과를 골랐지만 Figma 링크가 없습니다")
    return res


__all__ = [
    'COLOR_VALUE_RE',
    'DEFAULT_CSS_FILE',
    'DEFAULT_VAR_PATTERN',
    'LENGTH_PREFIXES',
    'LENGTH_VALUE_RE',
    'THEME_REF_RE',
    'THEME_SCHEMA',
    '_norm_value',
    'css_var_name',
    'dd_render_scope',
    'preview_check',
    'read_theme',
    'renderer_check',
    'theme_check',
    'token_kind',
]
