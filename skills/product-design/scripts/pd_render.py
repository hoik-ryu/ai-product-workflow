"""/product-design EX7: 렌더러 공통 계약과 렌더러별 검증(설계 §2.5·§2.6·D5).

원칙
- 탐색·측정·선택·승인 계약은 렌더러와 무관합니다. 시안의 근거는 manifest `elements`(렌더러 무관)이고, 렌더러별로
  "선언이 실제 산출물과 맞는지"를 다르게 확인해 확인 수준을 기록합니다.
    html(기본)    : HTML 표지를 추출해 대조 — `checked`, 브라우저 측정(EX4) 가능
    adapter       : 프로젝트 코드 어댑터(React 등)가 낸 정적 HTML 산출물을 html과 같게 대조 — `checked`, 측정 가능
    figma(선택)   : Figma 파일·페이지·프레임과 화면 ID 연결, 요소별 노드, 대상×뷰포트 스크린샷·해시 — `declared`
                    (엔진은 Figma를 호출하지 않으므로 노드와 선언의 일치는 확인하지 않음 → 모델 평가에서 대조), 브라우저 측정 불가(not_run)
- 엔진은 렌더러를 실행하지 않습니다. Figma MCP 사용 가능 여부 확인·호출은 Claude가 하고, 쓸 수 없거나 호출이 제한되면 html로 진행합니다.
- Figma는 외부 서비스입니다. 사용하려면 사용자의 명시적 선택(`explore-renderer enable figma --note`)과 전송 범위(`--data-scope`)가
  기록되어야 하고, 레퍼런스 원본·개인정보 전송은 별도 사용자 확인 없이는 오류입니다.
- 렌더러 출력은 비신뢰 산출물입니다: 형식(파일 키·노드 ID·URL), 스크린샷(PNG 매직 바이트·크기), 경로(시안 폴더 안)만 믿습니다.
- 렌더러 결과는 자동으로 공식 디자인이 되지 않습니다(선택·채택·승인 절차 그대로).
"""
from __future__ import annotations

import re
from pathlib import Path

from pd_core import add_history, block, emit, now, require_state, save_state, sha256_file

RENDERER_KINDS = ("html", "adapter", "figma")
LEVEL = {"html": "checked", "adapter": "checked", "figma": "declared"}
FIGMA_KEY_RE = re.compile(r"^[0-9a-zA-Z]{22,128}$")
FIGMA_NODE_RE = re.compile(r"^\d+[:-]\d+$")
FIGMA_URL_RE = re.compile(r"^https://(?:www\.)?figma\.com/(?:design|file)/[0-9a-zA-Z]{22,128}(?:/[^\s?#]*)?(?:\?[^\s#]*)?$")
DATA_SCOPES = ("structure_only", "sample_data", "sample_data_and_tokens")
TRANSFER_KEYS = ("layout", "sample_text", "tokens", "assets", "reference_images", "personal_data")
RENDER_STATUS = ("complete", "incomplete", "failed", "unavailable")


def _ex():
    import pd_explore as EX
    return EX


def renderer_config(st: dict) -> dict:
    cfg = (_ex().exploration_config(st) or {})
    r = cfg.get("renderers") if isinstance(cfg.get("renderers"), dict) else {}
    return {"default": cfg.get("renderer") or "html", "figma": r.get("figma") or {"enabled": False}, "adapters": r.get("adapters") or {}}


def render_kind(v: dict) -> str:
    """시안의 렌더러: render에 figma가 있으면 figma, adapter가 있으면 adapter, 아니면 html."""
    rd = v.get("render") if isinstance(v.get("render"), dict) else {}
    if isinstance(rd.get("figma"), dict):
        return "figma"
    if isinstance(rd.get("adapter"), dict):
        return "adapter"
    return "html"


def renderer_label(v: dict) -> str:
    k = render_kind(v)
    rd = v.get("render") or {}
    if k == "adapter":
        a = rd["adapter"]
        return f"adapter:{a.get('name')}@{a.get('version') or '?'}"
    if k == "figma":
        return f"figma@{(rd['figma'].get('tool') or 'mcp')}"
    return "html"


# ---------------------------------------------------------------- 코드 어댑터: 정적 HTML 산출물(html과 같은 대조)
def adapter_problems(project: Path, r: dict, lb: str, v: dict, st: dict) -> list[str]:
    EX = _ex()
    tag = f"{r['id']}-{lb}"
    a = (v.get("render") or {}).get("adapter") or {}
    E = []
    name = a.get("name")
    known = renderer_config(st)["adapters"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,40}", name or ""):
        E.append(f"{tag}: render.adapter.name이 필요합니다(renderer_contract)")
    elif name not in known:
        E.append(f"{tag}: 어댑터 {name}가 프로젝트 렌더러 설정에 없습니다(explore-renderer enable adapter --name {name}, renderer_not_enabled)")
    if not str(a.get("version") or "").strip():
        E.append(f"{tag}: render.adapter.version(렌더러 버전)이 필요합니다(renderer_contract)")
    vdir = (project / EX.round_rel(r["id"]) / lb).resolve()
    for key in ("source",):
        src = a.get(key)
        if src:
            p = (project / EX.EXPLORE_DIR / str(src)).resolve()
            if vdir not in p.parents and p != vdir:
                E.append(f"{tag}: 어댑터 소스 {src}는 시안 폴더 안에 있어야 합니다(design-explore 밖 코드 금지)")
    html = (v.get("render") or {}).get("html")
    if not html:
        E.append(f"{tag}: 코드 어댑터는 정적 HTML 산출물(render.html)을 내야 합니다(renderer_contract)")
    if a.get("status") in ("failed", "incomplete"):
        E.append(f"{tag}: 어댑터 렌더링 {a['status']}: {str(a.get('reason') or '')[:120]}(render_{a['status']})")
    return E


# ---------------------------------------------------------------- Figma: 선언 검사(declared)
def figma_checks(project: Path, st: dict, r: dict, lb: str, v: dict, decl: dict) -> tuple[list[str], list[str], list[str], dict]:
    """→ (오류, 경고, 요소 순서(선언 순서, 노드가 있는 것만), 정보). 렌더러 출력은 비신뢰 입력으로 형식만 믿습니다."""
    import pd_reference as RF
    EX = _ex()
    tag = f"{r['id']}-{lb}"
    E, W = [], []
    fg = (v.get("render") or {}).get("figma") or {}
    cfg = renderer_config(st)["figma"]
    info = {"level": "declared", "renderer": renderer_label(v), "evidence": [], "status": fg.get("status") or "complete", "frames": {}}
    if not cfg.get("enabled"):
        E.append(f"{tag}: Figma 렌더러를 쓰려면 사용자의 명시적 선택이 필요합니다(explore-renderer enable figma --data-scope … --note, renderer_not_enabled)")
    st_ = fg.get("status") or "complete"
    if st_ not in RENDER_STATUS:
        E.append(f"{tag}: render.figma.status는 {'/'.join(RENDER_STATUS)} 중 하나")
    if st_ in ("failed", "unavailable"):
        E.append(f"{tag}: Figma 렌더링 {st_}: {str(fg.get('reason') or '')[:160]}(render_{st_}) — html 렌더러로 진행하거나 다시 시도합니다")
        info["status"] = st_
        return E, W, list(decl), info  # 렌더링 자체가 없으므로 구조 검사는 하지 않음(실패 사유 하나만 보고)
    if not FIGMA_KEY_RE.match(str(fg.get("file_key") or "")):
        E.append(f"{tag}: render.figma.file_key 형식이 아닙니다(renderer_contract)")
    if fg.get("url") and not FIGMA_URL_RE.match(str(fg["url"])):
        E.append(f"{tag}: render.figma.url은 figma.com 디자인 파일 주소여야 합니다(비신뢰 출력)")
    if not FIGMA_NODE_RE.match(str(fg.get("page_id") or "")):
        E.append(f"{tag}: render.figma.page_id(페이지 노드 ID)가 필요합니다(renderer_contract)")
    if not str(fg.get("tool_version") or fg.get("tool") or "").strip():
        W.append(f"{tag}: Figma 렌더러 도구·버전 기록이 없습니다(render.figma.tool)")
    # 외부 전송 범위
    tr = fg.get("transfer") if isinstance(fg.get("transfer"), dict) else None
    if tr is None:
        E.append(f"{tag}: Figma로 보낸 데이터 범위(render.figma.transfer: {', '.join(TRANSFER_KEYS)})가 필요합니다(external_transfer_unrecorded)")
        tr = {}
    for k in tr:
        if k not in TRANSFER_KEYS:
            E.append(f"{tag}: transfer 키 {k}는 {', '.join(TRANSFER_KEYS)} 중 하나")
    if tr.get("reference_images") and not cfg.get("allow_reference_transfer"):
        E.append(f"{tag}: 레퍼런스 원본 이미지를 Figma로 보냈다고 기록되어 있습니다 — 별도 사용자 확인 없이는 금지(external_transfer_unconfirmed)")
    if tr.get("personal_data") and not cfg.get("allow_personal_data"):
        E.append(f"{tag}: 개인정보를 Figma로 보냈다고 기록되어 있습니다 — 별도 사용자 확인 없이는 금지(external_transfer_unconfirmed)")
    scope = cfg.get("data_scope")
    if scope == "structure_only" and (tr.get("sample_text") or tr.get("tokens")):
        E.append(f"{tag}: 사용자가 허용한 전송 범위(structure_only)를 넘었습니다(external_transfer_out_of_scope)")
    if scope == "sample_data" and tr.get("tokens"):
        E.append(f"{tag}: 사용자가 허용한 전송 범위(sample_data)에 토큰 값은 없습니다(external_transfer_out_of_scope)")
    # 프레임 ↔ 화면 ID, 스크린샷 증거
    frames = fg.get("frames") if isinstance(fg.get("frames"), dict) else {}
    tids = [t["id"] for t in r["targets"]]
    vdir = project / EX.round_rel(r["id"]) / lb
    ref_shas = {x.get("sha256") for x in RF.refs_state(st).values()}
    theme_tokens = None
    if r.get("phase") == "visual":
        import pd_visual as VS
        th = VS.theme_of(project, r["id"], lb)
        theme_tokens = set(th["resolved"]) if th["contract"] else set()
    import pd_assets as PA
    reg = PA.load_registry(project, st)
    missing = []
    for t in tids:
        f = frames.get(t)
        if not isinstance(f, dict):
            missing.append(t)
            E.append(f"{tag}: 대상 {t}의 Figma 프레임이 없습니다(render_incomplete)")
            continue
        if not FIGMA_NODE_RE.match(str(f.get("node_id") or "")):
            E.append(f"{tag}: {t} 프레임 node_id 형식이 아닙니다(renderer_contract)")
        shots = f.get("screenshots") if isinstance(f.get("screenshots"), list) else []
        if not shots:
            missing.append(t)
            E.append(f"{tag}: {t} 프레임 스크린샷 증거가 없습니다(render_incomplete)")
        for s in shots:
            rel = str((s or {}).get("path") or "")
            p = (vdir / rel).resolve()
            if not rel or rel.startswith("/") or ".." in Path(rel).parts or vdir.resolve() not in p.parents or not p.is_file():
                E.append(f"{tag}: {t} 스크린샷 {rel}은 시안 폴더 안의 파일이어야 합니다(render_evidence_invalid)")
                continue
            raw = p.read_bytes()
            fmt, w, h = RF.sniff(raw[:65536])
            if fmt != "png" or w <= 0 or h <= 0:
                E.append(f"{tag}: {t} 스크린샷 {rel}은 PNG가 아닙니다(render_evidence_invalid)")
                continue
            sha = sha256_file(p)
            if s.get("sha256") and s["sha256"] != sha:
                E.append(f"{tag}: {t} 스크린샷 {rel}이 기록 해시와 다릅니다(render_evidence_modified)")
            if sha in ref_shas:
                E.append(f"{tag}: {t} 스크린샷이 레퍼런스 원본과 같습니다(reference_asset_embedded)")
            vp = str(s.get("viewport") or "")
            if not vp:
                E.append(f"{tag}: {t} 스크린샷 {rel}에 viewport 이름이 필요합니다")
            info["evidence"].append({"target": t, "viewport": vp, "path": f"{lb}/{rel}", "sha256": sha, "width": w, "height": h})
        toks = f.get("tokens") or []
        if theme_tokens is not None:
            bad = sorted(set(toks) - theme_tokens)
            if bad:
                E.append(f"{tag}: {t} 프레임이 후보 테마에 없는 토큰 {bad}를 씁니다(token_var_unknown)")
            if not toks:
                W.append(f"{tag}: {t} 프레임의 토큰 근거(tokens)가 없습니다 — Figma 변수와 테마 토큰 연결을 기록합니다")
        for a in f.get("assets") or []:
            if a not in reg["assets"]:
                E.append(f"{tag}: {t} 프레임 자산 {a}가 등록되지 않았습니다(asset_unregistered)")
            elif not PA.official_ok(reg["assets"][a]):
                W.append(f"{tag}: {t} 프레임 자산 {a} 권리 미확인 — 탐색에만(asset_rights_unconfirmed)")
        info["frames"][t] = {"node_id": f.get("node_id"), "tokens": toks, "components": f.get("components") or [], "assets": f.get("assets") or []}
    if missing:
        info["status"] = "incomplete"
    # 요소별 노드(선언). 노드가 없는 요소는 렌더되지 않은 것으로 봅니다(element_missing)
    order = []
    for eid, e in decl.items():
        if not FIGMA_NODE_RE.match(str(e.get("node") or "")):
            E.append(f"{tag}: 요소 {eid}의 Figma 노드(node)가 없습니다(element_missing — figma 렌더러는 요소마다 노드 ID 필수)")
        else:
            order.append(eid)
    for t in tids:
        cm = set((info["frames"].get(t) or {}).get("components") or [])
        if r.get("phase") == "visual":
            import pd_visual as VS
            fp = VS.fingerprint(project, t)
            extra = sorted(cm - set(fp["cmps"]))
            if extra:
                E.append(f"{tag}: {t} 프레임 컴포넌트 {extra}는 승인된 화면 컴포넌트가 아닙니다(structure_drift)")
    W.append(f"{tag}: Figma 렌더러는 선언 검사(declared)입니다 — 노드와 선언의 일치·시각 품질은 스크린샷으로 모델이 대조합니다(critique 필수)")
    return E, W, order, info


def renderer_evidence(r: dict, mr: dict, lb: str) -> list[dict]:
    """측정이 없는 렌더러(figma)의 스크린샷 증거(라운드 폴더 기준 경로)."""
    v = (mr.get("variants") or {}).get(lb) or {}
    if render_kind(v) != "figma":
        return []
    out = []
    for t, f in ((v.get("render") or {}).get("figma") or {}).get("frames", {}).items():
        for s in f.get("screenshots") or []:
            out.append({"target": t, "viewport": s.get("viewport"), "path": f"{lb}/{s.get('path')}", "sha256": s.get("sha256")})
    return out


# ---------------------------------------------------------------- explore-renderer: 렌더러 설정(사용자 선택)
def cmd_explore_renderer(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    cfg = EX.exploration_config(st)
    if cfg is None or EX.workflow_of(st) != "v2":
        block("exploration_disabled", "디자인 탐색(v2)이 켜진 프로젝트에서만 렌더러를 설정합니다.")
    rc = renderer_config(st)
    if a.action == "status":
        emit({"ok": True, "default": rc["default"], "renderers": {"html": {"enabled": True, "level": "checked", "measurable": True},
                                                                  "figma": rc["figma"] | {"level": "declared", "measurable": False},
                                                                  "adapters": rc["adapters"]},
              "note": "Figma MCP 사용 가능 여부는 Claude가 확인합니다. 쓸 수 없거나 호출이 제한되면 html로 진행합니다(엔진은 렌더러를 호출하지 않음)."})
    note = (a.note or "").strip()
    if not note:
        block("statement_required", "렌더러 설정은 사용자의 명시적 선택 문장(--note)이 필요합니다.")
    regs = cfg.setdefault("renderers", {})
    if a.action == "enable" and a.kind == "figma":
        if a.data_scope not in DATA_SCOPES:
            block("invalid_arguments", f"--data-scope는 {'/'.join(DATA_SCOPES)} 중 하나입니다(Figma로 보낼 데이터 범위).")
        regs["figma"] = {"enabled": True, "data_scope": a.data_scope, "statement": note, "at": now(),
                         "allow_reference_transfer": False, "allow_personal_data": False}
    elif a.action == "enable" and a.kind == "adapter":
        if not a.name or not re.fullmatch(r"[a-z][a-z0-9_-]{1,40}", a.name):
            block("invalid_arguments", "--name(어댑터 이름)이 필요합니다.")
        regs.setdefault("adapters", {})[a.name] = {"enabled": True, "statement": note, "at": now(), "output": "static_html"}
    elif a.action == "disable" and a.kind == "figma":
        regs["figma"] = dict(regs.get("figma") or {}, enabled=False, disabled_statement=note, disabled_at=now())
    elif a.action == "allow-transfer":
        if not (regs.get("figma") or {}).get("enabled"):
            block("renderer_not_enabled", "Figma 렌더러를 먼저 사용자 선택으로 켭니다.")
        if a.what not in ("reference_images", "personal_data"):
            block("invalid_arguments", "--what reference_images 또는 personal_data")
        regs["figma"]["allow_reference_transfer" if a.what == "reference_images" else "allow_personal_data"] = {"statement": note, "at": now()}
    else:
        block("invalid_arguments", "동작: status | enable figma --data-scope … | enable adapter --name … | disable figma | allow-transfer --what …")
    add_history(st, "design_direction" if "design_direction" in st["stages"] else "ux_planning", "exploration_renderer",
                (st["stages"].get("design_direction") or st["stages"]["ux_planning"])["revision"], f"{a.action} {a.kind or ''} {a.name or ''}: {note[:80]}")
    save_state(project, st)
    emit({"ok": True, "renderers": renderer_config(st)})
