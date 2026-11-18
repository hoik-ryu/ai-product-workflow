"""/product-design EX5: 2차 시각 탐색(Design Direction 중). 설계 §2.4·§2.5·§2.7.1·§2.8·§2.12.

원칙
- 2차 시안은 **승인된 UX 구조를 바꾸지 않습니다.** 승인된 02의 화면별 정보·행동·입력·컴포넌트(CMP) 집합과 정보 순서가
  구조 지문이고, 시안 요소의 근거(`SCR-xxx:info-n`·`:action-n`·`:input-n`·`CMP-xxx`)가 지문과 맞지 않으면 `structure_drift`.
  이미지에만 있는 기능·정보는 근거가 없으므로 들어올 수 없습니다(의도한 구조 변경은 CR ①로 UX Spec reopen).
- 시안마다 후보 테마(`theme.json`, design-theme/v1)를 두고, 같은 시안의 모든 화면이 그 테마의 토큰(`tokens.css`, 엔진 생성)과
  같은 컴포넌트 규칙을 씁니다. CSS의 날 색 값은 오류(토큰 우회), 04에 없는 토큰 이름은 ② 변경 요청 후보로 표시합니다.
- 시안끼리는 색만 달라서는 안 됩니다(`variants_color_only`): 타이포그래피·밀도·컴포넌트 표현·시각 계층·격자 축의 실제 CSS 값을 비교.
- 선택 결과는 **후보 VD·후보 테마**로만 나갑니다(`explore-adopt`, 07·공식 테마 파일은 쓰지 않음). VD별 사용자 결정과
  기존 Design Direction 승인 절차를 그대로 씁니다. 승인되지 않은 후보 테마 값이 공식 테마에 들어가면 trace 오류.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from pd_core import (
    DD_FILE, add_history, block, blocks_by_heading, design_context, emit, field_line, now, read_text, require_state, save_state,
    screen_info, sha256_file, strip_fences,
)

VISUAL_AXES = ("typography", "density", "component", "hierarchy", "layout_grid")
PLAN_HEADINGS_VISUAL = ("시각 개념", "색·토큰", "타이포그래피", "간격·밀도", "컴포넌트 표현", "시각 계층·강조", "진부한 기본값 대조", "다른 시안과의 차이")
CRITIQUE_VISUAL = ("계획 대비", "정보 계층", "강조", "밀도", "제품 정체성", "진부한 기본값", "결함 후보", "요구사항 밖 요소", "시안 간 차이", "화면 간 일관성")
CRITIQUE_REFERENCE = ("레퍼런스 대비", "레퍼런스와 다른 점", "레퍼런스 자산 미사용")
VREF_RE = re.compile(r"^(SCR-\d{3}):(info|action|input)-(\d+)$")
CMP_RE = re.compile(r"^CMP-\d{3}$")
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RAW_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
ADOPT_FORMAT = "design-explore-adoption/v1"
TOKENS_HEADER = "/* explore-tokens가 theme.json에서 생성합니다. 직접 고치지 않습니다. */\n"
# CSS 속성 → 시각 축(색은 별도). 같은 속성이라도 값에 그라데이션이 있으면 컴포넌트 표현(채움 방식)으로도 봅니다.
PROP_AXIS = {
    "font-family": "typography", "font-size": "typography", "font-weight": "typography", "letter-spacing": "typography",
    "text-transform": "typography", "line-height": "density", "min-height": "density", "height": "density",
    "border-radius": "component", "box-shadow": "component", "border-width": "component", "border-style": "component",
    "outline": "component", "background-image": "component",
    "grid-template-columns": "layout_grid", "max-width": "layout_grid", "display": "layout_grid", "flex-direction": "layout_grid",
    "columns": "layout_grid", "width": "layout_grid",
    "color": "color", "background-color": "color", "border-color": "color", "fill": "color", "stroke": "color",
}
DENSITY_PREFIX = ("padding", "margin", "gap", "row-gap", "column-gap")


def _ex():
    import pd_explore as EX
    return EX


# ---------------------------------------------------------------- 승인된 02 구조 지문
def _rows(block_text: str, keyword: str) -> list[list[str]]:
    m = re.search(rf"^###\s*[^\n]*{re.escape(keyword)}[^\n]*$", block_text, re.M)
    if not m:
        return []
    nxt = re.compile(r"^#{2,3} ", re.M).search(block_text, m.end())
    sec = block_text[m.end(): nxt.start() if nxt else len(block_text)]
    rows = []
    for line in sec.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows[1:]


def fingerprint(project: Path, sid: str, scr: dict | None = None) -> dict | None:
    """승인된 02의 화면 구조 지문: 정보(순서)·행동·입력·상태·컴포넌트."""
    scr = scr if scr is not None else screen_info(project)
    info = scr.get(sid)
    if not info:
        return None
    b = info["block"]
    skip = ("...", "…", "")
    fp = {"screen": sid, "name": re.sub(r"^##\s+SCR-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip(),
          "info": [c[1] for c in _rows(b, "정보") if len(c) > 1 and c[1] not in skip],
          "actions": [c[0] for c in _rows(b, "행동") if c and c[0] not in skip],
          "inputs": [c[0] for c in _rows(b, "입력") if c and c[0] not in skip and "해당 없음" not in c[0]],
          "states": sorted(info["states"]), "cmps": sorted(info["cmp"]), "uxd": sorted(info["uxd"])}
    fp["hash"] = hashlib.sha256(json.dumps({k: fp[k] for k in ("info", "actions", "inputs", "states", "cmps")}, ensure_ascii=False).encode()).hexdigest()
    return fp


def ref_label(fp: dict, ref: str) -> str | None:
    m = VREF_RE.match(ref)
    if m:
        lst = {"info": fp["info"], "action": fp["actions"], "input": fp["inputs"]}[m.group(2)]
        i = int(m.group(3))
        return lst[i - 1] if 1 <= i <= len(lst) else None
    if CMP_RE.match(ref):
        return ref if ref in fp["cmps"] else None
    if re.fullmatch(r"SCR-\d{3}-ST\d+", ref):
        return ref if ref in fp["states"] else None
    if re.fullmatch(r"UXD-\d{3}", ref):
        return ref if ref in fp["uxd"] else None
    return None


# ---------------------------------------------------------------- 대표 화면 선정(2차)
def visual_targets(project: Path, st: dict, n: int, explicit: list[str] | None) -> list[dict]:
    EX = _ex()
    scr = screen_info(project)
    ctx = design_context(project)
    sty = EX.screen_types(project)
    prio = ctx["pid"].get("US_priority", {})
    chosen_uxd = set()
    sch = ((st.get("exploration") or {}).get("structure") or {}).get("choice")
    if sch:
        chosen_uxd = {u for u, refs in EX.uxd_exp_refs(project).items() if sch["id"] in refs}

    def target(sid, basis):
        fp = fingerprint(project, sid, scr)
        stype = (sty.get("assign") or {}).get(sid) or EX.classify(scr[sid]["block"], sty["types"])
        return {"id": sid, "label": fp["name"], "anchor": [sid], "type": stype, "states": fp["states"][:1], "basis": basis,
                "fingerprint": fp["hash"], "source_label": fp["name"]}
    if explicit:
        bad = [x for x in explicit if x not in scr]
        if bad:
            block("invalid_arguments", f"승인된 02에 없는 화면: {', '.join(bad)}")
        return [target(s, ["사용자 지정"]) for s in explicit]
    must = [s for s, i in sorted(scr.items()) if any(prio.get(u) == "Must" for u in i["trace"] if u.startswith("US-"))]
    if not must:
        must = sorted(scr)

    def sig(sid):
        fp = fingerprint(project, sid, scr)
        return (min(len(fp["info"]), 5), bool(fp["inputs"]), min(len(fp["actions"]), 4))
    ordered = sorted(must, key=lambda s: (0 if scr[s]["uxd"] & chosen_uxd else 1, -len(fingerprint(project, s, scr)["info"]), s))
    out, seen = [], set()
    for s in ordered:
        if len(out) >= n:
            break
        if sig(s) in seen:
            continue
        seen.add(sig(s))
        basis = ["Must 화면", f"구성 서명(정보 {sig(s)[0]}·입력 {'있음' if sig(s)[1] else '없음'}·행동 {sig(s)[2]})이 다른 화면과 다름"]
        if scr[s]["uxd"] & chosen_uxd:
            basis.insert(0, "1차 선택을 반영한 UXD를 참조")
        out.append(target(s, basis))
    for s in ordered:  # 구성이 모두 같으면 순서대로 채움
        if len(out) >= n:
            break
        if s not in [t["id"] for t in out]:
            out.append(target(s, ["Must 화면(구성 서명 중복)"]))
    return out


# ---------------------------------------------------------------- 후보 테마·토큰 CSS
def theme_of(project: Path, rid: str, lb: str) -> dict:
    import pd_theme as TH
    rel = f"{_ex().round_rel(rid)}/{lb}/theme.json"
    th = TH.read_theme(project, rel)
    if th.get("data") is not None and not isinstance(th["data"], dict):  # 최상위가 객체가 아닌 후보 테마: 계약 오류로 취급(충돌 방지)
        th["errors"] = list(th.get("errors") or []) + ["theme.json 최상위가 객체가 아닙니다(theme_invalid)"]
        th["data"] = None
    return th


def seed_theme(project: Path, st: dict, name: str) -> dict:
    """후보 테마 골격: 04 토큰 값(형식이 맞는 것) 위에 공식 테마 값을 얹은 출발점. 승인 아님."""
    import pd_theme as TH
    toks = {}
    for k, v in design_context(project)["tokens"].items():
        v = v.strip().strip("`")
        if TH.token_kind(k) == "color" and TH.COLOR_VALUE_RE.match(v):
            toks[k] = v
        elif k.startswith(TH.LENGTH_PREFIXES) and TH.LENGTH_VALUE_RE.match(v):
            toks[k] = v
        elif re.fullmatch(r"font\.weight\.[A-Za-z]+", k) and re.fullmatch(r"\d{3}", v):
            toks[k] = v
    toks.update(_official_theme(project, st))
    return {"schema": "design-theme/v1", "name": f"candidate-{name}", "version": "0.0.0-candidate", "approved": False,
            "note": "2차 탐색 후보 테마(승인 아님). 토큰 이름은 04 문서 이름, 값만 바꿉니다. 레퍼런스 출처는 provenance {토큰: [RX-…]}.",
            "tokens": toks, "provenance": {}}


def tokens_css(resolved: dict) -> str:
    return TOKENS_HEADER + ":root {\n" + "".join(f"  --{k.replace('.', '-')}: {v};\n" for k, v in sorted(resolved.items())) + "}\n"


def css_decls(text: str) -> list[tuple[str, str, str]]:
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", code):
        sel = " ".join(m.group(1).split())
        for d in m.group(2).split(";"):
            if ":" in d:
                p, _, v = d.partition(":")
                p = p.strip().lower()
                if p:
                    out.append((sel, p, " ".join(v.split())))
    return out


def resolve(v: str, vars_: dict, depth: int = 0) -> str:
    if depth > 8:
        return v
    def rep(m):
        name, fb = m.group(1), m.group(2)
        if name in vars_:
            return resolve(vars_[name], vars_, depth + 1)
        return resolve(fb.strip(), vars_, depth + 1) if fb else f"var({name})"
    return re.sub(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,\s*([^()]*))?\)", rep, v)


def axis_signature(decls: list[tuple[str, str, str]], vars_: dict, emphasis) -> dict:
    sig = {a: set() for a in VISUAL_AXES + ("color",)}
    sizes, weights = set(), set()
    for _sel, p, v in decls:
        if p.startswith("--"):
            continue
        rv = resolve(v, vars_).lower()
        ax = PROP_AXIS.get(p)
        if p.startswith(DENSITY_PREFIX):
            ax = "density"
        elif p.startswith("border") and p not in PROP_AXIS:
            ax = "component"
            cols = HEX_RE.findall(rv)
            if cols:
                sig["color"].add((p, " ".join(cols)))
                rv = HEX_RE.sub("#", rv)
        elif p == "background":
            ax = "component" if "gradient" in rv else "color"
            if "gradient" in rv:
                sig["color"].add((p, " ".join(HEX_RE.findall(rv))))
                rv = HEX_RE.sub("#", rv)
        elif p == "box-shadow":
            cols = HEX_RE.findall(rv) + re.findall(r"rgba?\([^)]*\)", rv)
            sig["color"].add((p, " ".join(cols)))
            rv = re.sub(r"rgba?\([^)]*\)", "c", HEX_RE.sub("c", rv))
        if ax:
            sig[ax].add((p, rv))
        if p == "font-size":
            sizes.add(rv)
        if p == "font-weight":
            weights.add(rv)
    sig["hierarchy"] = {("sizes", len(sizes)), ("weights", len(weights)), ("size_values", " ".join(sorted(sizes))),
                        ("emphasis", " ".join(sorted(emphasis or [])))}
    return {k: sorted(v) for k, v in sig.items()}


# ---------------------------------------------------------------- 정적 검사(check_round에서 호출)
def variant_checks(project: Path, st: dict, r: dict, lb: str, v: dict, decl: dict, order: list[str], html: str,
                   renderer: str = "html") -> tuple[list[str], list[str], dict]:
    """시안 하나: 구조 지문(structure_drift)·후보 테마·토큰 CSS·날 색 값·컴포넌트 표지. → (오류, 경고, 정보)."""
    EX = _ex()
    tag = f"{r['id']}-{lb}"
    E, W = [], []
    scr = screen_info(project)
    fps = {t["id"]: fingerprint(project, t["id"], scr) for t in r["targets"]}
    # 1) 요소 근거 ↔ 승인된 구조
    present = set(order)
    used: dict[str, dict[str, list[int]]] = {t: {"info": [], "action": [], "input": []} for t in fps}
    for eid, e in decl.items():
        tgt = e.get("target")
        fp = fps.get(tgt)
        if not fp:
            continue
        for ref in e.get("refs") or []:
            ref = str(ref)
            m = VREF_RE.match(ref)
            if m and m.group(1) != tgt:
                E.append(f"{tag}: 요소 {eid}의 근거 {ref}는 대상 화면 {tgt}의 항목이 아닙니다(structure_drift)")
                continue
            if ref_label(fp, ref) is None:
                E.append(f"{tag}: 요소 {eid}의 근거 {ref}가 승인된 02의 {tgt}에 없습니다(structure_drift) — 승인 구조에 없는 정보·행동·컴포넌트는 "
                         "넣지 않습니다(이미지 속 기능 포함). 구조를 바꾸려면 CR ①로 UX Spec을 다시 엽니다")
                continue
            if m:
                kind = m.group(2)
                ek = e.get("kind")
                if kind in ("action", "input") and ek not in ("action", "input", "navigation"):
                    E.append(f"{tag}: 요소 {eid}({ek})의 근거 {ref}는 {kind} 항목입니다(structure_drift: 승인된 행동을 누를 수 없는 정보로 바꾸지 않음)")
                if eid in present:
                    used[tgt][kind].append(int(m.group(3)))
    for t, fp in fps.items():
        for kind, lst in (("info", fp["info"]), ("action", fp["actions"]), ("input", fp["inputs"])):
            for i, label in enumerate(lst, 1):
                if i not in used[t][kind]:
                    E.append(f"{tag}: {t}의 승인된 {kind}-{i}({label[:40]})이 시안에 없습니다(structure_drift)")
    # 정보 순서(승인된 우선순위) — HTML에 나타나는 순서
    for t in fps:
        seq = []
        for eid in order:
            e = decl.get(eid) or {}
            if e.get("target") != t:
                continue
            for ref in e.get("refs") or []:
                m = VREF_RE.match(str(ref))
                if m and m.group(2) == "info" and int(m.group(3)) not in seq:
                    seq.append(int(m.group(3)))
        if seq != sorted(seq):
            E.append(f"{tag}: {t}의 정보 순서 {seq}가 승인된 우선순위와 다릅니다(structure_drift)")
    # 컴포넌트 표지(data-cmp): 승인된 화면 컴포넌트만(figma는 프레임 components로 pd_render에서 검사)
    cmp_marks = re.findall(r"data-cmp\s*=\s*\"(CMP-\d{3})\"", html)
    allowed = set().union(*[set(fp["cmps"]) for fp in fps.values()]) if fps else set()
    for c in sorted(set(cmp_marks) - allowed):
        E.append(f"{tag}: data-cmp=\"{c}\"는 대상 화면의 승인된 컴포넌트가 아닙니다(structure_drift)")
    if not cmp_marks and renderer != "figma":
        W.append(f"{tag}: data-cmp 표지가 없습니다 — 화면 간 컴포넌트 일관성을 측정할 수 없습니다(component_unmarked)")
    # 2) 후보 테마
    th = theme_of(project, r["id"], lb)
    info = {"theme": None, "tokens_needing_cr": [], "raw_colors": 0, "signature": None, "provenance": {}}
    if not th["exists"]:
        E.append(f"{tag}: 후보 테마 theme.json이 없습니다(theme_missing)")
        return E, W, info
    if not th["contract"]:
        E.append(f"{tag}: theme.json은 design-theme/v1 형식이어야 합니다(theme_invalid)")
        return E, W, info
    E += [f"{tag}: theme.json: {x}(theme_invalid)" for x in th["errors"]]
    names04 = set(design_context(project)["tokens"])
    info["tokens_needing_cr"] = sorted(set(th["resolved"]) - names04)
    for x in info["tokens_needing_cr"]:
        W.append(f"{tag}: 토큰 {x}는 04에 없습니다 — 후보로 쓰되 공식 반영은 ② 변경 요청(UX Spec)으로만(token_needs_cr)")
    info["theme"] = th["resolved"]
    prov = (th["data"] or {}).get("provenance") or {}
    if not isinstance(prov, dict):
        E.append(f"{tag}: theme.json provenance는 {{토큰: [RX-…]}}이어야 합니다")
        prov = {}
    info["provenance"] = prov
    rules = set(v.get("rules") or [])
    for tok, rxs in prov.items():
        if tok not in th["resolved"]:
            E.append(f"{tag}: provenance의 {tok}가 테마 토큰이 아닙니다")
        for rx in (rxs if isinstance(rxs, list) else [rxs]):
            if rx not in rules:
                E.append(f"{tag}: 토큰 {tok}의 출처 {rx}가 시안 rules에 없습니다(provenance_rule_missing — 규칙 확인·범위 검사를 거친 것만 출처로 씀)")
    if r.get("mode", "ai") == "ai" and prov:
        E.append(f"{tag}: AI 라운드 테마에는 레퍼런스 출처(provenance)를 쓰지 않습니다")
    if renderer == "figma":  # CSS·HTML 자산 검사는 html 렌더러용. Figma는 프레임 토큰·자산 선언(pd_render)으로 대체, 색만 다른 시안 판정은 할 수 없음
        info["signature"] = None
        W.append(f"{tag}: figma 렌더러는 CSS 값이 없어 '색만 다른 시안' 자동 판정을 하지 않습니다 — 시안 간 차이는 critique에서 확인(distinctness_declared_only)")
        info["assets_used"] = sorted({a for f in (((v.get("render") or {}).get("figma") or {}).get("frames") or {}).values() for a in f.get("assets") or []})
        info["icons"] = []
        info["rights_unconfirmed"] = []
        return E, W, info
    # 3) tokens.css(엔진 생성)와 styles.css
    vdir = project / EX.round_rel(r["id"]) / lb
    tc = vdir / "tokens.css"
    if not tc.is_file() or tc.read_text(encoding="utf-8") != tokens_css(th["resolved"]):
        E.append(f"{tag}: tokens.css가 theme.json과 다릅니다(tokens_css_stale) — explore-tokens --round {r['id']}로 다시 만듭니다")
    if not re.search(r"""<link[^>]+href=["']tokens\.css["']""", html):
        E.append(f"{tag}: index.html이 tokens.css를 불러오지 않습니다(tokens_not_linked)")
    vars_ = {f"--{k.replace('.', '-')}": v_ for k, v_ in th["resolved"].items()}
    # HTML 인라인 style의 지역 변수(예: 진행률 --p:66%)는 데이터 값이지 토큰이 아님. 색 값이면 아래에서 raw_color_literal
    local_vars = set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", " ".join(re.findall(r"style\s*=\s*\"([^\"]*)\"", html))))
    decls = []
    for css in sorted(vdir.rglob("*.css")):
        if css.name == "tokens.css":
            continue
        for sel, p, val in css_decls(css.read_text(encoding="utf-8", errors="replace")):
            decls.append((sel, p, val))
            if p.startswith("--"):
                E.append(f"{tag}: {css.name} {sel}: CSS 변수 {p}를 새로 정의하지 않습니다(토큰은 theme.json에서, token_redefined)")
            if RAW_COLOR_RE.search(val):
                info["raw_colors"] += 1
                E.append(f"{tag}: {css.name} {sel} {{{p}: {val[:60]}}} — 날 색 값 대신 테마 토큰(var(--…))을 씁니다(raw_color_literal)")
            for vn in re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", val):
                if vn not in vars_ and vn not in local_vars:
                    E.append(f"{tag}: {css.name} {sel}: 테마에 없는 토큰 변수 {vn}(token_var_unknown)")
    for sel, p, val in [x for x in css_decls(re.sub(r"<[^>]+>", "", "".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))))]:
        if RAW_COLOR_RE.search(val):
            E.append(f"{tag}: index.html <style> {sel}: 날 색 값(raw_color_literal)")
    if re.search(r"style\s*=\s*\"[^\"]*(#[0-9a-fA-F]{3,8}\b|rgba?\()", html):
        E.append(f"{tag}: index.html 인라인 style에 날 색 값(raw_color_literal)")
    info["signature"] = axis_signature(decls, vars_, v.get("emphasis"))
    import pd_assets as PA  # EX5.1: 시각 자산(등록·역할·대체 텍스트·권리·스타일)
    css_texts = [c.read_text(encoding="utf-8", errors="replace") for c in sorted(vdir.rglob("*.css")) if c.name != "tokens.css"]
    aE, aW, ainfo = PA.variant_asset_checks(project, st, r, lb, decl, html, css_texts)
    E += aE
    W += aW
    info.update(ainfo)
    return E, W, info


def round_checks(r: dict, per_info: dict, declared: dict) -> tuple[list[str], list[str]]:
    """시안 간: 색만 다른 시안(variants_color_only), 선언한 축이 실제로 다른지."""
    E, W = [], []
    labels = [lb for lb in r["variants"] if (per_info.get(lb) or {}).get("signature")]
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a, b = labels[i], labels[j]
            sa, sb = per_info[a]["signature"], per_info[b]["signature"]
            if all(sa[x] == sb[x] for x in VISUAL_AXES):
                what = "색까지 같습니다" if sa["color"] == sb["color"] else "색 값만 다릅니다"
                E.append(f"{r['id']}: {a}와 {b}는 타이포그래피·밀도·컴포넌트 표현·시각 계층·격자가 모두 같고 {what}(variants_color_only)")
    for lb in labels if len(labels) > 1 else []:  # 시안 1개(수정 라운드)는 비교 대상 없음
        for ax in declared.get(lb) or []:
            if ax in VISUAL_AXES and all(per_info[lb]["signature"][ax] == per_info[o]["signature"][ax] for o in labels if o != lb):
                W.append(f"{r['id']}-{lb}: 선언한 축 {ax}가 다른 시안과 실제 CSS 값이 같습니다(axis_not_different)")
    return E, W


# ---------------------------------------------------------------- 레퍼런스 대비 사실(엔진 계산, measured 아님·모델 평가 아님)
def _hexes(obj) -> list[str]:
    out = []
    if isinstance(obj, str):
        out += HEX_RE.findall(obj)
    elif isinstance(obj, dict):
        for x in obj.values():
            out += _hexes(x)
    elif isinstance(obj, list):
        for x in obj:
            out += _hexes(x)
    return out


def _rgb(h: str):
    h = h.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def alignment(project: Path, st: dict, info: dict) -> list[dict]:
    """토큰 값 ↔ 출처 규칙(RX)의 기록 값 대조: 색은 RGB 거리(같음 0·가까움 ≤24·다름), 길이는 숫자(±2). 결정적 사실입니다."""
    import pd_reference as RF
    out = []
    for tok, rxs in (info.get("provenance") or {}).items():
        val = (info.get("theme") or {}).get(tok)
        if val is None:
            continue
        for rx in (rxs if isinstance(rxs, list) else [rxs]):
            m = RF.RX_ID_RE.match(str(rx))
            if not m:
                continue
            ex = RF.check_extraction(project, st, f"REF-{m.group(1)}")
            item = (ex.get("items") or {}).get(rx) or {}
            ref_vals = item.get("value")
            th_hex, rf_hex = _hexes(val), _hexes(ref_vals)
            res = "unknown"
            if th_hex and rf_hex:
                d = min(sum((a - b) ** 2 for a, b in zip(_rgb(x), _rgb(y))) ** 0.5 for x in th_hex for y in rf_hex)
                res = "same" if d == 0 else ("near" if d <= 24 else "different")
                detail = round(d, 1)
            else:
                tn = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", str(val))]
                rn = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", json.dumps(ref_vals))] if ref_vals is not None else []
                detail = None
                if tn and rn:
                    dd = min(abs(a - b) for a in tn for b in rn)
                    res = "same" if dd == 0 else ("near" if dd <= 2 else "different")
                    detail = dd
            out.append({"token": tok, "value": val, "rule": rx, "basis": item.get("basis"), "reference_value": ref_vals, "result": res, "distance": detail})
    return out


# ---------------------------------------------------------------- 측정 연계: 컴포넌트 일관성(화면 간)
COMPONENT_PROPS = ("background-color", "background-image", "color", "border-radius", "border-top-width", "border-top-style", "border-top-color",
                   "box-shadow", "font-family", "font-size", "font-weight", "padding-top", "padding-left")


def component_findings(results: list[dict]) -> tuple[list[str], dict]:
    """같은 시안·뷰포트에서 같은 CMP·같은 변형(data-cmp-variant)·같은 상태의 계산된 스타일이 화면·인스턴스마다 다르면 component_inconsistent(차단).
    허용(비교 그룹을 나눔): 뷰포트별 반응형 표현, 명시적 변형, 선언된 상태(disabled·selected·pressed·expanded·data-cmp-state).
    hover·focus는 쉬는 상태에서 재므로 비교에 들어오지 않습니다."""
    groups: dict[tuple, dict[str, list[str]]] = {}
    for x in results:
        for c in ((x.get("layout") or {}).get("components") or []):
            if not isinstance(c, dict) or not CMP_RE.match(str(c.get("cmp") or "")):
                continue
            style = c.get("style") if isinstance(c.get("style"), dict) else {}
            sig = json.dumps({k: str(style.get(k, "")) for k in COMPONENT_PROPS}, sort_keys=True)
            state = " ".join(sorted(str(c.get("state") or "").split()))
            groups.setdefault((x["viewport"], c["cmp"], str(c.get("variant") or ""), state), {}).setdefault(sig, []).append(f"{x['target']}:{c.get('el') or '?'}")
    B, detail = [], {}
    for (vp, cmp, var, state), sigs in sorted(groups.items()):
        var = var + (f"[{state}]" if state else "")
        if len(sigs) > 1:
            where = [", ".join(sorted(set(w))[:4]) for w in sigs.values()]
            diff = sorted({k for s in sigs for k, v in json.loads(s).items() if len({json.loads(t)[k] for t in sigs}) > 1})
            B.append(f"{vp}: component_inconsistent:{cmp}{'/' + var if var else ''}({len(sigs)}가지 스타일 — {'; '.join(where)} · 다른 속성 {', '.join(diff[:5])})")
            detail[f"{vp}:{cmp}:{var}"] = {"styles": len(sigs), "differs": diff}
    return B, detail


# ---------------------------------------------------------------- explore-tokens
def cmd_explore_tokens(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    phase, r = EX._round(st, a.round)
    if phase != "visual":
        block("invalid_arguments", "explore-tokens는 2차(시각) 라운드에서만 씁니다.")
    out = {}
    labels = [x.strip() for x in (a.variants or "").split(",") if x.strip()] or list(r["variants"])
    bad = [x for x in labels if x not in r["variants"]]
    if bad:  # 경로 안전성: 라운드의 시안 이름만(../ 등으로 시안 폴더 밖에 쓰지 않음)
        block("invalid_arguments", f"{r['id']}의 시안은 {', '.join(r['variants'])}입니다(받은 값 {', '.join(bad)}).")
    for lb in labels:
        if EX.variant_path_problem(project, r["id"], lb, f"{r['id']}/{lb}/tokens.css"):
            block("invalid_arguments", f"{r['id']}-{lb} 시안 폴더가 design-explore 밖을 가리킵니다(심볼릭 링크). 쓰지 않습니다.")
        th = theme_of(project, r["id"], lb)
        if not th["contract"] or th["errors"]:
            block("theme_invalid", f"{r['id']}-{lb}/theme.json을 먼저 고칩니다.", errors=th["errors"] or ["design-theme/v1 형식이 아님"])
        p = project / EX.round_rel(r["id"]) / lb / "tokens.css"
        p.write_text(tokens_css(th["resolved"]), encoding="utf-8")
        out[lb] = {"file": str(p.relative_to(project)), "tokens": len(th["resolved"])}
    emit({"ok": True, "round": r["id"], "generated": out})


# ---------------------------------------------------------------- explore-adopt: 선택 → 후보 VD·후보 테마(공식 아님)
TOKEN_GROUP_AXIS = {"color": "color", "font": "typography", "space": "density", "size": "density", "radius": "component",
                    "elevation": "component", "shadow": "component", "border": "component"}


def token_axis(name: str) -> str:
    return TOKEN_GROUP_AXIS.get(name.split(".", 1)[0], "component")


def _next_vd(project: Path) -> int:
    text = re.sub(r"<!--.*?-->", "", strip_fences(read_text(project, DD_FILE)), flags=re.S)
    nums = [int(x) for x in re.findall(r"^###\s+VD-(\d{3})", text, re.M)]
    return (max(nums) if nums else 0) + 1


def _official_theme(project: Path, st: dict) -> dict:
    import pd_theme as TH
    rel = (st.get("config") or {}).get("theme_file")
    if not rel:
        return {}
    th = TH.read_theme(project, rel)
    return th["resolved"] if th["contract"] else {}


def cmd_explore_adopt(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    phase, r = EX._round(st, a.round)
    if phase != "visual":
        block("invalid_arguments", "explore-adopt는 2차(시각) 라운드의 선택을 후보 VD·테마로 바꿉니다(1차는 UXD에 직접 반영).")
    ps = EX._phase_state(st, "visual")
    ch = ps.get("choice")
    if not ch or ch["round"] != r["id"]:
        block("no_choice", f"{r['id']}의 사용자 선택이 없습니다. 선택(explore-choose)은 사용자만 합니다.")
    integ = EX.choice_integrity(project, st, "visual")
    if integ["changed"] or integ["missing"]:
        block("changed_since_choice", "선택 이후 보존 파일이 바뀌었거나 없습니다. 선택한 산출물 그대로여야 채택합니다.", changed=integ["changed"], missing=integ["missing"])
    EX.require_choice_current(project, st, "visual")  # P1-1: stale 선택·재검사 실패 선택은 채택하지 않음
    dd = st["stages"]["design_direction"]["status"]
    if dd != "in_progress":
        block("invalid_transition", f"design_direction 상태가 {dd}입니다. 채택은 작성 중(in_progress)에만 합니다(승인 후 변경은 reopen).")
    base = ch["per_target"][next(iter(ch["per_target"]))] if len(set(ch["per_target"].values())) == 1 else None
    axes = ch.get("axes") or {}
    themes = {lb: theme_of(project, r["id"], lb)["resolved"] for lb in ch["variants"]}
    provs = {lb: (theme_of(project, r["id"], lb)["data"] or {}).get("provenance") or {} for lb in ch["variants"]}
    base_lb = base or sorted(ch["variants"])[0]
    merged, src, prov = {}, {}, {}
    for tok, val in themes[base_lb].items():
        lb = axes.get(token_axis(tok), base_lb)
        val = themes.get(lb, {}).get(tok, val)
        merged[tok], src[tok] = val, lb
        if provs.get(lb, {}).get(tok):
            prov[tok] = provs[lb][tok]
    for ax, lb in axes.items():  # 축 시안에만 있는 토큰
        for tok, val in themes.get(lb, {}).items():
            if token_axis(tok) == ax and tok not in merged:
                merged[tok], src[tok] = val, lb
                if provs.get(lb, {}).get(tok):
                    prov[tok] = provs[lb][tok]
    names04 = set(design_context(project)["tokens"])
    official = _official_theme(project, st)
    cr_tokens = sorted(t for t in merged if t not in names04)
    diff = {"changed": {t: {"official": official.get(t), "candidate": v} for t, v in merged.items() if t in names04 and t in official and official[t] != v},
            "added": {t: v for t, v in merged.items() if t in names04 and t not in official},
            "same": sorted(t for t, v in merged.items() if official.get(t) == v)}
    refs_txt = ""
    rp = ch.get("reference") or {}
    if rp:
        parts = []
        for rid, x in (rp.get("refs") or {}).items():
            rules = sorted({rx for lst in prov.values() for rx in (lst if isinstance(lst, list) else [lst]) if rx.startswith(rid.replace("REF", "RX"))})
            parts.append(f"{rid}: {' · '.join(rules) if rules else '규칙 ' + str(len(rp.get('rules') or []))}")
        refs_txt = f" ({'; '.join(parts)})" if parts else ""
    man = EX.load_manifest(project)
    mr = (man.get("rounds") or {}).get(r["id"]) or {}
    cmps = sorted({ref for lb in ch["variants"] for e in ((mr.get("variants") or {}).get(lb) or {}).get("elements") or [] for ref in e.get("refs") or [] if CMP_RE.match(str(ref))})
    scr_ids = [t["id"] for t in r["targets"]]
    n = _next_vd(project)
    groups = {"color": "색·팔레트", "typography": "타이포그래피", "density": "간격·밀도", "component": "컴포넌트 표현(모서리·테두리·그림자·채움)"}
    vds, vd_of_token = [], {}
    for ax, title in groups.items():
        toks = sorted(t for t in merged if token_axis(t) == ax and t in names04 and t not in diff["same"])
        if not toks:
            continue
        vid = f"VD-{n:03d}"
        n += 1
        for t in toks:
            vd_of_token[t] = vid
        lb_used = sorted({src[t] for t in toks})
        vds.append({"id": vid, "axis": ax, "title": f"{title} — {r['id']}-{'/'.join(lb_used)} 후보 테마", "tokens": toks,
                    "decision": "; ".join(f"{t} = {merged[t]}" for t in toks[:12]) + (" …" if len(toks) > 12 else ""),
                    "related": scr_ids + (cmps if ax == "component" else []) + toks})
    ast = _adoption_assets(project, st, r, ch)
    if ast["adoptable"] or ast["blocked"]:
        vid = f"VD-{n:03d}"
        n += 1
        style = ast.get("icon_style") or {}
        vds.append({"id": vid, "axis": "assets", "title": f"아이콘·일러스트 — {r['id']} 선택({ch['id']})", "tokens": [],
                    "decision": (f"아이콘 스타일 {style.get('style')}·선 {style.get('stroke_width')}·격자 {style.get('grid')}. " if style else "")
                                + f"공식 후보 자산 {', '.join(ast['adoptable']) or '없음'}"
                                + (f" · 채택 불가(권리 미확인 등): {', '.join(ast['blocked'])}" if ast["blocked"] else ""),
                    "related": scr_ids + ast["adoptable"]})
    vid = f"VD-{n:03d}"
    vds.append({"id": vid, "axis": "hierarchy", "title": f"화면 구성·시각 계층 — {r['id']} 선택({ch['id']})", "tokens": [],
                "decision": "선택 시안의 화면별 계층·강조 위치(구조는 승인된 02 그대로). 대상 화면 유형: " + ", ".join(f"{t['id']}({t['type']})" for t in r["targets"]),
                "related": scr_ids + cmps})
    lines = [f"<!-- explore-adopt {r['id']} {ch['id']}: 후보 VD입니다. 07 '시각 결정'에 옮긴 뒤 VD마다 사용자가 승인 또는 제외로 결정합니다. 엔진은 07을 쓰지 않습니다. -->"]
    for x in vds:
        lines += [f"### {x['id']}: {x['title']}", f"- **결정**: {x['decision']}", "- **상태**: 후보",
                  f"- **근거**: 사용자 선택 {ch['id']}{refs_txt}", f"- **관련**: {', '.join(dict.fromkeys(x['related']))}",
                  "- **토큰 밖 값**: 없음", ""]
    if cr_tokens:
        lines += ["<!-- 04에 없는 토큰: 공식 반영은 ② 변경 요청(UX Spec reopen)으로만. 아래는 07 '7. UX Spec과의 차이'에 옮길 후보입니다. -->",
                  "### CR-후보: 새 의미 토큰", "- **분류**: ②", "- **상태**: 미결", f"- **관련**: {', '.join(scr_ids)}",
                  f"- **내용**: {', '.join(f'{t} = {merged[t]}' for t in cr_tokens)}", ""]
    adir = project / EX.round_rel(r["id"]) / "selection" / "adoption"
    adir.mkdir(parents=True, exist_ok=True)
    cand_theme = {"schema": "design-theme/v1", "name": f"candidate-{r['id']}-{ch['id']}", "version": "0.0.0-candidate",
                  "note": "후보 테마(승인 아님). VD가 승인된 토큰만 공식 테마 파일에 옮깁니다. 04에 없는 토큰은 제외(② 변경 요청 후보).",
                  "approved": False, "tokens": {t: v for t, v in sorted(merged.items()) if t in names04}, "source_variants": src,
                  "provenance": prov, "cr_tokens": {t: merged[t] for t in cr_tokens}}
    hints = {"format": "design-explore-ui-brief-hints/v1", "choice": ch["id"], "approved": False,
             "note": "Build UI Brief 근거 후보. VD가 승인되면 VD의 '관련' SCR·CMP·토큰으로 UI Brief에 연결됩니다(product-build 기존 규칙).",
             "screens": {t["id"]: {"type": t["type"], "variant": ch["per_target"].get(t["id"]),
                                   "vds": [x["id"] for x in vds], "components": cmps,
                                   "tokens": sorted(t2 for t2 in merged if t2 in names04)} for t in r["targets"]},
             "component_rules": _component_rules(project, r, ch), "assets": _adoption_assets(project, st, r, ch)}
    files = {"vd-candidates.md": "\n".join(lines) + "\n", "theme.candidate.json": json.dumps(cand_theme, ensure_ascii=False, indent=2) + "\n",
             "theme.diff.json": json.dumps(diff, ensure_ascii=False, indent=2) + "\n", "ui-brief-hints.json": json.dumps(hints, ensure_ascii=False, indent=2) + "\n"}
    rec_files = {}
    for name, body in files.items():
        (adir / name).write_text(body, encoding="utf-8")
        rec_files[str((adir / name).relative_to(project))] = sha256_file(adir / name)
    rec = {"format": ADOPT_FORMAT, "round": r["id"], "choice": ch["id"], "selection_sha256": ch.get("selection_sha256"), "at": now(),
           "vds": [{k: x[k] for k in ("id", "axis", "tokens")} for x in vds], "token_vd": vd_of_token,
           "candidate_tokens": {t: v for t, v in merged.items() if t in names04}, "official_before": {t: official.get(t) for t in merged if t in names04},
           "cr_tokens": cr_tokens, "files": rec_files, "approved": False}
    ps["adoption"] = rec
    add_history(st, "design_direction", "exploration_adopted", st["stages"]["design_direction"]["revision"], f"{ch['id']} → 후보 VD {', '.join(x['id'] for x in vds)}")
    save_state(project, st)
    emit({"ok": True, "choice": ch["id"], "candidate_vds": [x["id"] for x in vds], "theme_diff": {k: (len(v) if not isinstance(v, list) else len(v)) for k, v in diff.items()},
          "cr_tokens": cr_tokens, "files": sorted(rec_files), "approved": False,
          "next": "vd-candidates.md의 VD를 07 '시각 결정'에 '후보'로 옮김 → VD마다 사용자 결정(승인·제외) → 승인된 VD의 토큰 값만 공식 테마에 반영 → "
                  "done → trace --stage design_direction → submit. 엔진은 07·공식 테마를 쓰지 않습니다."})


def _adoption_assets(project: Path, st: dict, r: dict, ch: dict) -> dict:
    """선택 시안이 쓴 자산: 권리가 확인된 것만 공식 후보, 나머지는 채택 불가로 표시."""
    import pd_assets as PA
    reg = PA.load_registry(project, st)
    res = _ex().check_round(project, st, r["id"])
    used = sorted({aid for lb in ch["variants"] for aid in ((res.get("visual") or {}).get(lb) or {}).get("assets_used") or []})
    return {"adoptable": [a for a in used if PA.official_ok(reg["assets"][a])],
            "blocked": {a: "권리 미확인(explore-asset confirm 필요)" if reg["assets"][a].get("source") != "reference_derived" else "레퍼런스 파생 자산(공식 채택 불가)"
                        for a in used if not PA.official_ok(reg["assets"][a])},
            "icon_style": reg.get("icon_style")}


def _component_rules(project: Path, r: dict, ch: dict) -> dict:
    """선택 시안의 측정(있으면)에서 CMP별 계산된 스타일(화면 간 같음이 확인된 것)."""
    out = {}
    for run in reversed(r.get("measurements") or []):
        if run.get("status") != "completed":
            continue
        for lb in ch["variants"]:
            for x in ((run.get("variants") or {}).get(lb) or {}).get("results") or []:
                for c in x.get("components") or []:
                    out.setdefault(c["cmp"] + (f"/{c['variant']}" if c.get("variant") else ""), {"variant": lb, "style": c.get("style"), "run_id": run["run_id"]})
        break
    return out


# ---------------------------------------------------------------- 추적: 후보 테마가 승인 없이 공식 테마에 들어갔는지
def vd_asset_errors(project: Path, st: dict) -> list[str]:
    """07 VD의 '관련'에 적힌 자산(AST-…)은 등록되어 있고 파일이 그대로이며 권리가 확인되어야 공식 디자인에 들어갑니다."""
    import pd_assets as PA
    text = strip_fences(read_text(project, DD_FILE))
    ids = {(k, x) for k, b in blocks_by_heading(text, 3, "VD").items() for x in re.findall(r"AST-\d{3}", field_line(b, "관련"))}
    if not ids:
        return []
    reg = PA.load_registry(project, st)
    errs = []
    for k, aid in sorted(ids):
        a = reg["assets"].get(aid)
        if not a:
            errs.append(f"{k}: 등록되지 않은 자산 {aid}(asset_unregistered)")
            continue
        e, _ = PA.asset_problems(project, st, reg, aid)
        errs += [f"{k}: {x}" for x in e]
        if not PA.official_ok(a):
            errs.append(f"{k}: 자산 {aid}의 출처·권리가 확인되지 않았습니다 — 공식 채택 불가(asset_rights_unconfirmed). explore-asset confirm(사용자 문장)")
        elif PA.rights_verified(project, st, reg, aid) == "asset_rights_unverified":
            errs.append(f"{k}: 자산 {aid}의 권리 확인이 상태 기록(explore-asset confirm)과 맞지 않습니다 — 레지스트리만 고친 확인은 공식 근거가 아닙니다"
                        "(asset_rights_unverified). 사용자 확인 후 explore-asset confirm으로 다시 기록합니다")
    return errs


def adoption_theme_errors(project: Path, st: dict) -> list[str]:
    ad = ((st.get("exploration") or {}).get("visual") or {}).get("adoption")
    if not ad:
        return []
    from pd_core import dd_vds
    status = dd_vds(project)
    official = _official_theme(project, st)
    errs = []
    for tok, cand in (ad.get("candidate_tokens") or {}).items():
        before = (ad.get("official_before") or {}).get(tok)
        if cand == before or official.get(tok) != cand:
            continue
        vid = (ad.get("token_vd") or {}).get(tok)
        stt = status.get(vid) if vid else None
        if stt != "승인":
            errs.append(f"공식 테마의 {tok} = {cand}는 탐색 후보 값인데 해당 VD({vid or '없음'})가 승인되지 않았습니다({stt or '07에 없음'}, "
                        "adopted_theme_unapproved) — 승인되지 않은 디자인 시스템을 공식 테마로 쓰지 않습니다")
    for tok in ad.get("cr_tokens") or []:
        if tok in official:
            errs.append(f"공식 테마에 04에 없는 탐색 토큰 {tok}가 있습니다(② 변경 요청 전 반영, adopted_token_not_in_ui_system)")
    return errs


# ---------------------------------------------------------------- explore-impact: 후보·레퍼런스 변경의 영향
def cmd_explore_impact(a) -> None:
    """읽기 전용. 레퍼런스 분석(규칙)이 바뀌었거나 바뀔 때 영향받는 라운드·시안·선택·후보 VD·화면을 보여 줍니다."""
    EX = _ex()
    import pd_reference as RF
    project = Path(a.project).resolve()
    st = require_state(project)
    want_items = {x.strip() for x in (a.items or "").split(",") if x.strip()}
    want_ref = a.ref
    man = EX.load_manifest(project)
    vds07 = blocks_by_heading(strip_fences(read_text(project, DD_FILE)), 3, "VD")
    changed_refs = {}
    for rid, ref in RF.refs_state(st).items():
        ex = RF.check_extraction(project, st, rid)
        changed_refs[rid] = (ref.get("extraction") or {}).get("hash") != ex.get("hash")
    hits = []
    for phase in EX.PHASES:
        ps = (st.get("exploration") or {}).get(phase) or {}
        for r in ps.get("rounds") or []:
            mr = (man.get("rounds") or {}).get(r["id"]) or {}
            for lb, v in (mr.get("variants") or {}).items():
                rules = set(v.get("rules") or [])
                th = theme_of(project, r["id"], lb) if phase == "visual" else {"data": None}
                prov = ((th.get("data") or {}).get("provenance") or {}) if th.get("data") else {}
                rules |= {rx for lst in prov.values() for rx in (lst if isinstance(lst, list) else [lst])}
                sel = {rx for rx in rules if (not want_items or rx in want_items) and (not want_ref or rx.startswith(want_ref.replace("REF", "RX")))}
                if not sel and not (want_ref is None and not want_items and any(changed_refs.get(f"REF-{rx[3:6]}") for rx in rules)):
                    continue
                if not sel:
                    sel = {rx for rx in rules if changed_refs.get(f"REF-{rx[3:6]}")}
                toks = sorted(t for t, lst in prov.items() if set(lst if isinstance(lst, list) else [lst]) & sel)
                hits.append({"phase": phase, "round": r["id"], "variant": lb, "rules": sorted(sel), "tokens": toks,
                             "screens": [t["id"] for t in r["targets"]], "chosen": bool(r.get("choice") and lb in r["choice"]["variants"]),
                             "choice": (r.get("choice") or {}).get("id")})
    choices = sorted({h["choice"] for h in hits if h["chosen"] and h["choice"]})
    vd_hits = {k: {"status": field_line(b, "상태").split()[0] if field_line(b, "상태") else "", "related": field_line(b, "관련")}
               for k, b in vds07.items() if any(c in field_line(b, "근거") for c in choices)
               or any(rx in field_line(b, "근거") for h in hits for rx in h["rules"])}
    uxd_hits = {u: refs for u, refs in EX.uxd_exp_refs(project).items() if set(refs) & set(choices)}
    ad = ((st.get("exploration") or {}).get("visual") or {}).get("adoption") or {}
    ad_hit = {t: ad.get("token_vd", {}).get(t) for h in hits for t in h["tokens"] if t in (ad.get("candidate_tokens") or {})}
    emit({"ok": True, "read_only": True, "filter": {"ref": want_ref, "items": sorted(want_items)}, "extraction_changed": changed_refs,
          "variants": hits, "choices": choices, "uxd": uxd_hits, "vds": vd_hits, "adoption_tokens": ad_hit,
          "screens": sorted({s for h in hits for s in h["screens"]} | {s for v in vd_hits.values() for s in re.findall(r"SCR-\d{3}", v["related"])}),
          "note": "영향 보고만 합니다. 재선택·VD 개정·reopen은 사용자 결정입니다(승인 상태를 바꾸지 않음)."})


# ---------------------------------------------------------------- EX6: 탐색 선택의 영향(impact --design --choice)
def choice_impact(project: Path, st: dict, cid: str) -> dict:
    """선택 하나가 영향을 주는 화면·VD·테마·컴포넌트·자산과, 승인된 디자인과 후보의 차이. 사실 목록(exploration_choice)을 만듭니다."""
    EX = _ex()
    from pd_core import dd_vds
    m = EX.EXP_ID_RE.fullmatch(cid or "")
    if not m:
        block("invalid_arguments", "--choice는 EXP-S01-B·EXP-V02-A 같은 선택 ID입니다.")
    phase, r = EX._round(st, m.group(1))
    if not r.get("choice") or r["choice"]["id"] != cid:
        if cid not in {c["id"] for c in EX._phase_state(st, phase).get("choices") or []}:
            block("unknown_choice", f"{cid}는 기록된 탐색 선택이 아닙니다.")
    variants = (r.get("choice") or {}).get("variants") or ([m.group(2)] if m.group(2) != "MIX" else r["variants"])
    man = EX.load_manifest(project)
    mr = (man.get("rounds") or {}).get(r["id"]) or {}
    scr = screen_info(project)
    items, out = [], {"choice": cid, "phase": phase, "round": r["id"], "variants": variants}
    if phase == "structure":
        uxds = sorted(u for u, refs in EX.uxd_exp_refs(project).items() if cid in refs)
        screens = sorted(s for s, i in scr.items() if set(i["uxd"]) & set(uxds))
        out.update(uxd=uxds, screens=screens, components=sorted({c for s in screens for c in scr[s]["cmp"]}))
        items.append({"id": f"{cid}:structure", "summary": f"1차 선택 {cid} 변경 — UXD {', '.join(uxds) or '없음'}",
                      "facts": [{"kind": "exploration_choice", "choice": cid, "aspect": "structure", "refs": uxds + screens}]})
        return out | {"items": items}
    screens = [t["id"] for t in r["targets"]]
    cmps = sorted({ref for lb in variants for e in ((mr.get("variants") or {}).get(lb) or {}).get("elements") or []
                   for ref in e.get("refs") or [] if CMP_RE.match(str(ref))})
    text = strip_fences(read_text(project, DD_FILE))
    status = dd_vds(project)
    dd = st["stages"].get("design_direction") or {}
    approved_vds = set(((dd.get("approved") or {}).get("approved_vds")) or []) if dd.get("status") == "approved" else set()
    vds = {k: {"status": status.get(k), "approved_record": k in approved_vds, "related": field_line(b, "관련")}
           for k, b in blocks_by_heading(text, 3, "VD").items() if cid in field_line(b, "근거")}
    vd_screens = sorted({x for v in vds.values() for x in re.findall(r"SCR-\d{3}", v["related"])})
    official = _official_theme(project, st)
    ad = (EX._phase_state(st, "visual").get("adoption") or {})
    if ad.get("choice") == cid:
        cand = dict(ad.get("candidate_tokens") or {}) | {t: None for t in ad.get("cr_tokens") or []}
    else:
        cand = {}
        for lb in variants:
            cand.update(theme_of(project, r["id"], lb)["resolved"])
    names04 = set(design_context(project)["tokens"])
    changed = sorted(t for t, v in cand.items() if t in names04 and v is not None and official.get(t) != v)
    new = sorted(t for t in cand if t not in names04)
    res = EX.check_round(project, st, r["id"])
    assets = sorted({a for lb in variants for a in ((res.get("visual") or {}).get(lb) or {}).get("assets_used") or []})
    import pd_assets as PA
    reg = PA.load_registry(project, st)
    out.update(screens=sorted(set(screens) | set(vd_screens)), components=cmps, vds=vds,
               theme={"changed_vs_official": {t: {"official": official.get(t), "candidate": cand[t]} for t in changed},
                      "new_tokens_needing_cr": new, "official_file": (st.get("config") or {}).get("theme_file")},
               assets={a: {"role": reg["assets"].get(a, {}).get("role"), "official_ok": PA.official_ok(reg["assets"][a]) if a in reg["assets"] else False}
                       for a in assets},
               approved_vs_candidate={"vds_approved": sorted(k for k, v in vds.items() if v["approved_record"]),
                                      "vds_not_approved": sorted(k for k, v in vds.items() if not v["approved_record"]),
                                      "theme_tokens_pending": changed, "assets_not_official": [a for a in assets if not PA.official_ok(reg["assets"].get(a, {}))]})
    items.append({"id": f"{cid}:composition", "summary": f"화면 구성·시각 계층({', '.join(screens)})",
                  "facts": [{"kind": "exploration_choice", "choice": cid, "aspect": "composition", "refs": screens + cmps}]})
    if changed:
        items.append({"id": f"{cid}:theme", "summary": f"후보 테마 값 {len(changed)}개(공식 테마와 다름)",
                      "facts": [{"kind": "exploration_choice", "choice": cid, "aspect": "theme_value", "tokens": changed}]})
    if new:
        items.append({"id": f"{cid}:new-tokens", "summary": f"04에 없는 후보 토큰 {len(new)}개",
                      "facts": [{"kind": "exploration_choice", "choice": cid, "aspect": "theme_value", "tokens": new}]})
    for a in assets:
        items.append({"id": f"{cid}:{a}", "summary": f"자산 {a}({reg['assets'].get(a, {}).get('depicts') or ''})",
                      "facts": [{"kind": "exploration_choice", "choice": cid, "aspect": "asset", "role": reg["assets"].get(a, {}).get("role"),
                                 "refs": screens}]})
    return out | {"items": items}
