"""/product-design EX5.1: 시각 자산 계약(아이콘·일러스트·이미지). 설계: docs/roadmap/design-exploration-design.md(EX5.1).

원칙
- 자산은 프로젝트가 소유·교체하는 파일입니다(`design-profile/assets.json` + `design-profile/assets/`). 엔진은 이미지를 만들지 않고
  특정 생성 도구·외부 서비스에 의존하지 않습니다. 출처·라이선스·해시·역할(장식/기능)·스타일만 기록하고 검사합니다.
- 아이콘은 프로젝트 아이콘 스타일 가이드(격자·선 굵기·채움 방식)를 따라야 합니다(`icon_style_mismatch`).
- 장식(decorative)은 대체 텍스트 없이(alt="") 정보·기능을 나타내지 않고, 단독으로 버튼이 되지 않습니다(`decorative_as_control`).
  기능(functional) 자산은 승인된 기획·구조 ID(`refs`)를 가져야 하고, 그 ID를 근거로 하는 요소 안에서만 씁니다(`asset_implies_unapproved`).
- 권리가 확인되지 않은 자산(출처·라이선스 미확인, 레퍼런스에서 따온 자산)은 탐색에만 쓰고 공식 채택하지 않습니다.
- 레퍼런스 원본(바이트 동일)은 자산으로 등록할 수 없습니다. 시안은 등록 자산의 라운드 사본(`<라운드>/_assets/`)만 씁니다.
"""
from __future__ import annotations

import json
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

from pd_core import add_history, block, emit, now, require_state, save_state, sha256_file

ASSETS_FORMAT = "design-assets/v1"
DEFAULT_REGISTRY = "design-profile/assets.json"
KINDS = ("icon", "illustration", "image")
ROLES = ("decorative", "functional")
SOURCES = ("self_made", "model_drawn", "licensed", "stock", "generated_tool", "reference_derived")
UNCLEAR_LICENSES = ("", "unknown", "unconfirmed")
EXTS = {".svg": "svg", ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
MAX_BYTES = 2 * 1024 * 1024
ROUND_ASSET_DIR = "_assets"
ASSET_ID_RE = re.compile(r"^AST-\d{3}$")
STYLE_KEYS = {"style": ("outline", "filled", "duotone"), "stroke_width": float, "grid": int, "linecap": ("round", "square", "butt"),
              "color": ("currentColor",)}


def _ex():
    import pd_explore as EX
    return EX


def registry_rel(st: dict) -> str:
    return ((_ex().exploration_config(st) or {}).get("assets_file")) or DEFAULT_REGISTRY


def load_registry(project: Path, st: dict) -> dict:
    p = project / registry_rel(st)
    if not p.is_file():
        return {"format": ASSETS_FORMAT, "icon_style": None, "assets": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("invalid_assets", f"{registry_rel(st)} JSON 오류: {e}")
    if not isinstance(data, dict) or data.get("format") != ASSETS_FORMAT or not isinstance(data.get("assets"), dict):
        block("invalid_assets", f"{registry_rel(st)}은 {ASSETS_FORMAT} 형식이어야 합니다.")
    bad = sorted(k for k, x in data["assets"].items() if not isinstance(x, dict))
    if bad:
        block("invalid_assets", f"{registry_rel(st)}의 자산 항목이 객체가 아닙니다: {', '.join(bad)}. 자동으로 고치지 않습니다(Git 이력에서 복원).")
    return data


def save_registry(project: Path, st: dict, reg: dict) -> None:
    p = project / registry_rel(st)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assets_dir(st: dict) -> str:
    return str(Path(registry_rel(st)).parent / "assets")


def rights_records(st: dict) -> dict:
    """사용자 권리 확인 기록(explore-asset confirm이 상태 파일에 남김): {AST-…: {sha256, license, statement, at}}."""
    return st.setdefault("exploration", {}).setdefault("asset_rights", {})


def _entry_sha(entry: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def rights_verified(project: Path, st: dict, reg: dict, aid: str) -> str | None:
    """공식 채택 가능한 권리 확인인지. 문제가 없으면 None, 있으면 사유 코드.
    레지스트리 표시(confirmed_by_user)만으로는 부족하고, 상태 파일의 확인 기록이 같은 파일 해시·라이선스여야 합니다(P0-2)."""
    a = (reg.get("assets") or {}).get(aid)
    if not isinstance(a, dict):
        return "asset_unregistered"
    if not official_ok(a):
        return "asset_rights_unconfirmed"
    f = project / str(a.get("file") or "")
    cur = sha256_file(f) if f.is_file() else None
    if cur is None or cur != a.get("sha256"):
        return "asset_modified"
    r = ((st.get("exploration") or {}).get("asset_rights") or {}).get(aid)
    if not isinstance(r, dict) or r.get("sha256") != cur or r.get("license") != (a.get("rights") or {}).get("license"):
        return "asset_rights_unverified"
    return None


def dd_asset_snapshot(project: Path, st: dict) -> tuple[dict, list[str]]:
    """Design Direction 승인 스냅샷: 07에서 '승인'인 VD의 관련 자산마다 {file, sha256, entry_sha256, rights{license, statement, confirmed_at}, vds}.
    권리 확인 근거가 없거나 파일이 바뀐 자산은 오류로 돌려줍니다(스냅샷에 넣지 않음)."""
    from pd_core import DD_FILE, blocks_by_heading, field_line, read_text, strip_fences
    text = strip_fences(re.sub(r"<!--.*?-->", "", read_text(project, DD_FILE), flags=re.S))
    uses: dict[str, list[str]] = {}
    for k, b in blocks_by_heading(text, 3, "VD").items():
        if (field_line(b, "상태").split() or [""])[0] != "승인":
            continue
        for aid in re.findall(r"AST-\d{3}", field_line(b, "관련")):
            uses.setdefault(aid, []).append(k)
    if not uses:
        return {}, []
    reg = load_registry(project, st)
    snap, errs = {}, []
    for aid in sorted(uses):
        why = rights_verified(project, st, reg, aid)
        if why:
            errs.append(f"{aid}({', '.join(uses[aid])}): {why}")
            continue
        a = reg["assets"][aid]
        r = st["exploration"]["asset_rights"][aid]
        snap[aid] = {"file": a["file"], "sha256": a["sha256"], "entry_sha256": _entry_sha(a), "vds": sorted(uses[aid]),
                     "rights": {"license": r["license"], "statement": r.get("statement"), "confirmed_at": r.get("at")}}
    return snap, errs


def snapshot_drift(project: Path, st: dict, snap: dict) -> list[str]:
    """승인 스냅샷과 현재 자산(파일·레지스트리 항목·권리 확인 기록)이 다른 자산 ID 목록."""
    reg = load_registry(project, st)
    out = []
    for aid, x in sorted((snap or {}).items()):
        a = (reg.get("assets") or {}).get(aid)
        f = project / str(x.get("file") or "")
        r = ((st.get("exploration") or {}).get("asset_rights") or {}).get(aid) or {}
        if not isinstance(a, dict) or _entry_sha(a) != x.get("entry_sha256") or not f.is_file() or sha256_file(f) != x.get("sha256") \
                or r.get("sha256") != x.get("sha256"):
            out.append(aid)
    return out


def official_ok(a: dict) -> bool:
    r = a.get("rights") or {}
    return bool(r.get("confirmed_by_user")) and str(r.get("license") or "").lower() not in UNCLEAR_LICENSES and a.get("source") != "reference_derived"


# ---------------------------------------------------------------- SVG 안전·스타일
def svg_problems(text: str, kind: str, style: dict | None) -> tuple[list[str], list[str]]:
    E, W = [], []
    low = text.lower()
    if "<script" in low or re.search(r"\son[a-z]+\s*=", low):
        E.append("SVG에 스크립트·이벤트 속성이 있습니다(svg_unsafe)")
    if "<foreignobject" in low:
        E.append("SVG에 foreignObject가 있습니다(svg_unsafe)")
    for u in re.findall(r"(?:href|src)\s*=\s*[\"']([^\"']+)", text) + re.findall(r"url\(\s*['\"]?([^'\")]+)", text):
        if not u.startswith("#"):
            E.append(f"SVG가 외부 리소스 {u[:60]}를 참조합니다(svg_external)")
    if re.search(r"<image\b", low):
        E.append("SVG 안에 비트맵 이미지를 넣지 않습니다(svg_embedded_image)")
    if kind == "icon" and style:
        vb = re.search(r"viewBox\s*=\s*[\"']([^\"']+)", text)
        g = int(style.get("grid") or 24)
        if not vb or [float(x) for x in vb.group(1).split()] != [0, 0, g, g]:
            E.append(f"아이콘 viewBox가 스타일 격자 0 0 {g} {g}가 아닙니다(icon_style_mismatch)")
        sw = {float(x) for x in re.findall(r"stroke-width\s*[=:]\s*[\"']?([\d.]+)", text)}
        if style.get("style") == "outline":
            if style.get("stroke_width") is not None and sw != {float(style["stroke_width"])}:
                E.append(f"아이콘 선 굵기 {sorted(sw) or '없음'}가 스타일 {style['stroke_width']}와 다릅니다(icon_style_mismatch)")
            fills = set(re.findall(r"fill\s*[=:]\s*[\"']?([#\w()]+)", text)) - {"none", "currentColor"}
            if fills:
                E.append(f"윤곽선(outline) 아이콘에 채움 {sorted(fills)}이 있습니다(icon_style_mismatch)")
            if style.get("linecap") and not re.search(rf"stroke-linecap\s*[=:]\s*[\"']?{style['linecap']}", text):
                E.append(f"아이콘 선 끝(linecap)이 스타일 {style['linecap']}가 아닙니다(icon_style_mismatch)")
        cols = set(re.findall(r"(?:stroke|fill)\s*[=:]\s*[\"']?(#[0-9a-fA-F]{3,8})", text))
        if cols:
            E.append(f"아이콘에 고정 색 {sorted(cols)} — currentColor로 테마 색을 따릅니다(icon_style_mismatch)")
    return E, W


def _dims(fmt: str, raw: bytes) -> tuple[int, int]:
    if fmt == "svg":
        m = re.search(rb"viewBox\s*=\s*[\"']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)", raw)
        return (int(float(m.group(1))), int(float(m.group(2)))) if m else (0, 0)
    import pd_reference as RF
    _, w, h = RF.sniff(raw[:65536])
    return w, h


def asset_problems(project: Path, st: dict, reg: dict, aid: str) -> tuple[list[str], list[str]]:
    a = reg["assets"][aid]
    E, W = [], []
    p = project / a["file"]
    if not p.is_file():
        return [f"{aid}: 파일 {a['file']}이 없습니다(asset_missing)"], W
    if sha256_file(p) != a["sha256"]:
        E.append(f"{aid}: 파일이 등록 이후 바뀌었습니다(asset_modified) — explore-asset replace로 다시 기록합니다")
    if a["format"] == "svg":
        e, w = svg_problems(p.read_text(encoding="utf-8", errors="replace"), a["kind"], reg.get("icon_style"))
        E += [f"{aid}: {x}" for x in e]
        W += [f"{aid}: {x}" for x in w]
    if a["kind"] == "icon" and not reg.get("icon_style"):
        W.append(f"{aid}: 프로젝트 아이콘 스타일 가이드가 없습니다(explore-asset style)")
    if a["kind"] == "icon" and a["format"] != "svg":
        W.append(f"{aid}: 아이콘은 SVG(currentColor)를 권장합니다 — 비트맵 아이콘은 테마 색을 따르지 않습니다")
    if not official_ok(a):
        W.append(f"{aid}: 권리 미확인({a.get('source')}·{(a.get('rights') or {}).get('license') or 'unknown'}) — 탐색에만 쓰고 공식 채택하지 않습니다(asset_rights_unconfirmed)")
    return E, W


# ---------------------------------------------------------------- explore-asset
def cmd_explore_asset(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    if EX.exploration_config(st) is None or EX.workflow_of(st) != "v2":
        block("exploration_disabled", "디자인 탐색(v2)이 켜진 프로젝트에서만 자산 계약을 씁니다.")
    reg = load_registry(project, st)
    act = a.action
    note = (a.note or "").strip()
    dd_status = ((st.get("stages") or {}).get("design_direction") or {}).get("status")
    if act in ("replace", "confirm") and dd_status in ("awaiting_approval", "approved"):
        block("assets_locked_by_approval",
              f"Design Direction이 {dd_status} 상태라 자산을 교체하거나 권리를 다시 확인할 수 없습니다. 승인 기록의 자산 스냅샷이 공식 기준입니다. "
              "자산을 바꾸려면 사용자 확인 후 reopen --stage design_direction으로 다시 열고, 수정 → 제출 → 재승인합니다(P0).",
              stage_status=dd_status)
    if act == "list" or act == "check":
        out, bad = {}, False
        for aid in sorted(reg["assets"]):
            e, w = asset_problems(project, st, reg, aid)
            bad = bad or bool(e)
            x = reg["assets"][aid]
            out[aid] = {k: x.get(k) for k in ("kind", "role", "file", "source", "refs", "depicts", "fallback")} | {
                "license": (x.get("rights") or {}).get("license"), "official_ok": official_ok(x), "errors": e, "warnings": w}
        emit({"ok": not bad, "registry": registry_rel(st), "icon_style": reg.get("icon_style"), "assets": out}, 2 if (bad and act == "check") else 0)
    if act == "style":
        if not note:
            block("statement_required", "아이콘 스타일 가이드는 프로젝트 결정입니다. 사용자 확인 문장(--note)이 필요합니다.")
        style = dict(reg.get("icon_style") or {})
        for x in a.set or []:
            k, _, v = x.partition("=")
            k, v = k.strip(), v.strip()
            spec = STYLE_KEYS.get(k)
            if spec is None:
                block("invalid_arguments", f"스타일 키는 {', '.join(STYLE_KEYS)}입니다.")
            if isinstance(spec, tuple):
                if v not in spec:
                    block("invalid_arguments", f"{k}는 {'/'.join(spec)} 중 하나입니다.")
                style[k] = v
            else:
                try:
                    style[k] = spec(v)
                except ValueError:
                    block("invalid_arguments", f"{k}는 숫자입니다.")
        style.setdefault("color", "currentColor")
        reg["icon_style"] = style | {"statement": note, "at": now()}
        save_registry(project, st, reg)
        add_history(st, "design_direction", "asset_style", st["stages"]["design_direction"]["revision"], f"{style}: {note[:80]}")
        save_state(project, st)
        emit({"ok": True, "icon_style": reg["icon_style"]})
    if act in ("add", "replace"):
        if not a.file:
            block("invalid_arguments", "--file이 필요합니다.")
        src = Path(a.file).expanduser()
        if not src.is_file():
            block("invalid_arguments", "자산 파일이 없습니다.")
        fmt = EXTS.get(src.suffix.lower())
        raw = src.read_bytes()
        if not fmt:
            block("unsupported_format", f"자산은 {', '.join(sorted(set(EXTS.values())))}만 받습니다.")
        if fmt != "svg":
            import pd_reference as RF
            sn = RF.sniff(raw[:65536])[0]
            if sn != fmt:
                block("unsupported_format", "파일 내용이 확장자와 다릅니다(매직 바이트).")
        if len(raw) > MAX_BYTES:
            block("asset_too_large", f"자산은 {MAX_BYTES} bytes 이하입니다.")
        import hashlib
        h = hashlib.sha256(raw).hexdigest()
        refs_sha = {r["sha256"]: rid for rid, r in ((st.get("exploration") or {}).get("references") or {}).items()}
        if h in refs_sha:
            block("reference_copy", f"레퍼런스 원본({refs_sha[h]})을 자산으로 등록할 수 없습니다. 형태를 다시 그린 자체 자산을 씁니다.")
        if any(x["sha256"] == h for k, x in reg["assets"].items() if k != a.id):
            block("duplicate_asset", "같은 파일이 이미 등록되어 있습니다.")
        if act == "replace":
            if a.id not in reg["assets"]:
                block("invalid_arguments", f"등록되지 않은 자산 {a.id}")
            if not note:
                block("statement_required", "자산 교체는 사유 문장(--note)이 필요합니다.")
            old = reg["assets"][a.id]
            kind, role = old["kind"], old["role"]
        else:
            kind, role = a.kind, a.role
            if kind not in KINDS or role not in ROLES:
                block("invalid_arguments", f"--kind {'/'.join(KINDS)}, --role {'/'.join(ROLES)}가 필요합니다.")
            if a.source not in SOURCES:
                block("invalid_arguments", f"--source는 {'/'.join(SOURCES)} 중 하나입니다.")
        if fmt == "svg":
            e, _ = svg_problems(raw.decode("utf-8", errors="replace"), kind, reg.get("icon_style"))
            if e:
                block("asset_invalid", "SVG 자산 검사 실패", errors=e)
        refs = [x.strip() for x in (a.refs or "").split(",") if x.strip()]
        if role == "functional" and act == "add" and not refs:
            block("asset_refs_required", "기능 자산(아이콘 버튼·의미 있는 이미지)은 무엇을 나타내는지 승인된 ID(--refs, 예: SCR-121:action-1, CMP-025)가 필요합니다.")
        if act == "add":
            n = max([int(k[4:]) for k in reg["assets"]] or [0]) + 1
            aid = f"AST-{n:03d}"
        else:
            aid = a.id
        rel = f"{assets_dir(st)}/{aid}{src.suffix.lower() if src.suffix.lower() != '.jpeg' else '.jpg'}"
        dst = project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        w, hh = _dims(fmt, raw)
        rec = reg["assets"].get(aid, {}) if act == "replace" else {
            "kind": kind, "role": role, "source": a.source, "refs": refs, "depicts": (a.depicts or "").strip(),
            "fallback": a.fallback or ("hide" if role == "decorative" else "label"),
            "rights": {"license": (a.license or "unknown").strip(), "confirmed_by_user": False, "statement": None}, "added_at": now()}
        rec.update(file=rel, sha256=h, format=fmt, width=w, height=hh, bytes=len(raw))
        if act == "replace":
            rec.setdefault("history", []).append({"at": now(), "statement": note, "sha256": h})
            rec["rights"] = dict(rec.get("rights") or {}, confirmed_by_user=False, statement=None)  # 새 파일은 권리 재확인
            rights_records(st).pop(aid, None)
        if rec["source"] == "reference_derived":
            rec["rights"]["license"] = rec["rights"].get("license") or "unknown"
        reg["assets"][aid] = rec
        save_registry(project, st, reg)
        add_history(st, "design_direction", f"asset_{act}", st["stages"]["design_direction"]["revision"], f"{aid} {kind}/{role} {rec['source']}: {note[:60]}")
        save_state(project, st)
        e, wn = asset_problems(project, st, reg, aid)
        emit({"ok": not e, "asset": aid, "file": rel, "sha256": h, "official_ok": official_ok(rec), "errors": e, "warnings": wn})
    if act == "confirm":
        if a.id not in reg["assets"]:
            block("invalid_arguments", f"등록되지 않은 자산 {a.id}")
        if not note or not (a.license or "").strip() or a.license.strip().lower() in UNCLEAR_LICENSES:
            block("statement_required", "권리 확인은 사용자 문장(--note)과 라이선스(--license, 예: own·CC0·MIT·상용 라이선스 이름)가 필요합니다.")
        rec = reg["assets"][a.id]
        if rec["source"] == "reference_derived":
            block("reference_derived_asset", "레퍼런스에서 따온 자산은 공식 채택할 수 없습니다. 자체 자산으로 다시 그립니다.")
        cur = sha256_file(project / rec["file"]) if (project / rec["file"]).is_file() else None
        if cur is None or cur != rec.get("sha256"):
            block("asset_invalid", f"{a.id} 파일이 없거나 등록 해시와 다릅니다. 파일을 고치거나 replace로 다시 등록한 뒤 확인합니다.")
        rec["rights"] = {"license": a.license.strip(), "confirmed_by_user": True, "statement": note, "at": now()}
        # 권리 확인의 근거는 상태 파일(design.json)에 둡니다. 레지스트리만 고친 확인은 공식 근거가 아닙니다(P0-2).
        rights_records(st)[a.id] = {"sha256": cur, "license": rec["rights"]["license"], "statement": note, "at": rec["rights"]["at"]}
        save_registry(project, st, reg)
        add_history(st, "design_direction", "asset_rights_confirmed", st["stages"]["design_direction"]["revision"], f"{a.id} {a.license}: {note[:80]}")
        save_state(project, st)
        emit({"ok": True, "asset": a.id, "official_ok": official_ok(rec)})
    if act == "sync":
        phase, r = EX._round(st, a.round)
        d = project / EX.round_rel(r["id"]) / ROUND_ASSET_DIR
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for aid, x in sorted(reg["assets"].items()):
            e, _ = asset_problems(project, st, reg, aid)
            if any("asset_missing" in y or "asset_modified" in y for y in e):
                block("asset_invalid", f"{aid}을 먼저 고칩니다.", errors=e)
            shutil.copyfile(project / x["file"], d / Path(x["file"]).name)
        emit({"ok": True, "round": r["id"], "dir": str(d.relative_to(project)), "assets": sorted(reg["assets"]),
              "note": "시안은 라운드 사본(../_assets/AST-xxx.svg)만 참조합니다. 원본 레지스트리 파일을 고치면 sync를 다시 실행합니다."})
    block("invalid_arguments", "알 수 없는 동작")


# ---------------------------------------------------------------- 시안 검사(pd_visual.variant_checks에서 호출)
class _AssetScan(HTMLParser):
    INTERACTIVE = {"button", "input", "select", "textarea"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.uses: list[dict] = []
        self.inline_svg = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        inter = tag in self.INTERACTIVE or (tag == "a" and "href" in a) or a.get("role") in ("button", "link", "tab")
        node = {"tag": tag, "a": a, "inter": inter, "text": "", "children_assets": 0}
        if tag == "svg":
            self.inline_svg += 1
        aid = a.get("data-asset")
        src = a.get("src") if tag == "img" else None
        if aid or src:
            ctrl = next((n for n in reversed(self.stack) if n["inter"]), None)
            el = next((n["a"].get("data-el") for n in reversed(self.stack + [node]) if n["a"].get("data-el")), None)
            self.uses.append({"id": aid, "src": src, "tag": tag, "alt": a.get("alt"), "aria_hidden": a.get("aria-hidden") == "true",
                              "aria_label": a.get("aria-label"), "el": el, "ctrl": ctrl})
            if ctrl is not None:
                ctrl["children_assets"] += 1
        if tag not in ("img", "br", "hr", "input", "meta", "link", "source", "wbr"):
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        for n in self.stack:
            n["text"] += data


def variant_asset_checks(project: Path, st: dict, r: dict, lb: str, decl: dict, html: str, css_texts: list[str]) -> tuple[list[str], list[str], dict]:
    EX = _ex()
    tag = f"{r['id']}-{lb}"
    E, W = [], []
    reg = load_registry(project, st)
    sc = _AssetScan()
    sc.feed(html)
    sc.close()
    if sc.inline_svg:
        E.append(f"{tag}: 인라인 <svg> {sc.inline_svg}개 — 아이콘·일러스트는 등록 자산(explore-asset)의 라운드 사본으로 씁니다(asset_inline_svg)")
    rdir = project / EX.round_rel(r["id"])
    by_name = {Path(x["file"]).name: aid for aid, x in reg["assets"].items()}
    used: dict[str, list[str]] = {}

    def resolve(u: str, base: Path) -> str | None:
        p = (base / u.split("#")[0].split("?")[0]).resolve()
        try:
            rel = p.relative_to((rdir / ROUND_ASSET_DIR).resolve())
        except ValueError:
            return None
        return str(rel)
    css_urls = [u for t in css_texts for u in re.findall(r"url\(\s*['\"]?([^'\")]+)", t) if not u.startswith(("data:", "#"))]
    for u in css_urls:
        name = resolve(u, rdir / lb)
        if name is None:
            E.append(f"{tag}: CSS 이미지 {u}는 등록 자산의 라운드 사본(../{ROUND_ASSET_DIR}/)이 아닙니다(asset_unregistered)")
            continue
        aid = by_name.get(name)
        if not aid:
            E.append(f"{tag}: {u}는 등록되지 않은 자산입니다(asset_unregistered)")
            continue
        used.setdefault(aid, []).append("css")
    for x in sc.uses:
        aid = x["id"]
        if x["src"]:
            name = resolve(x["src"], rdir / lb)
            sid = by_name.get(name) if name else None
            if not sid:
                E.append(f"{tag}: <img src=\"{x['src'][:60]}\">는 등록 자산의 라운드 사본이 아닙니다(asset_unregistered)")
                continue
            if aid and aid != sid:
                E.append(f"{tag}: data-asset {aid}와 이미지 파일({sid})이 다릅니다")
            aid = sid
        if not aid or aid not in reg["assets"]:
            E.append(f"{tag}: data-asset=\"{aid}\"는 등록되지 않은 자산입니다(asset_unregistered)")
            continue
        used.setdefault(aid, []).append(x["tag"])
        a = reg["assets"][aid]
        if a["role"] == "decorative":
            if x["tag"] == "img" and a["kind"] != "icon":
                W.append(f"{tag}: 장식 일러스트 {aid}를 <img>로 쓰면 자산이 없을 때 깨진 이미지 표시가 보일 수 있습니다 — CSS 배경 + 대체 면 색을 권장(decorative_img_fallback)")
            if x["tag"] == "img" and x["alt"] not in ("",):
                E.append(f"{tag}: 장식 자산 {aid}는 alt=\"\"(대체 텍스트 없음)로 씁니다 — 정보를 담지 않습니다(decorative_alt)")
            if x["tag"] != "img" and not x["aria_hidden"]:
                E.append(f"{tag}: 장식 자산 {aid} 요소에 aria-hidden=\"true\"가 필요합니다(decorative_alt)")
            ctrl = x["ctrl"]
            if ctrl is not None and not ctrl["text"].strip() and not ctrl["a"].get("aria-label"):
                E.append(f"{tag}: 장식 자산 {aid}만 들어 있는 누르는 요소 — 장식을 버튼·기능처럼 쓰지 않습니다(decorative_as_control)")
        else:
            if x["tag"] == "img" and not (x["alt"] or "").strip():
                E.append(f"{tag}: 기능 자산 {aid}는 무엇을 뜻하는지 alt가 필요합니다(functional_alt)")
            if x["tag"] != "img" and not x["aria_hidden"] and not (x["aria_label"] or "").strip():
                ctrl = x["ctrl"]
                if not (ctrl and (ctrl["text"].strip() or ctrl["a"].get("aria-label"))):
                    E.append(f"{tag}: 기능 자산 {aid}에 접근 가능한 이름(aria-label 또는 글자)이 필요합니다(functional_alt)")
            el = x["el"]
            refs = set((decl.get(el) or {}).get("refs") or []) if el else set()
            if not refs & set(a.get("refs") or []):
                E.append(f"{tag}: 기능 자산 {aid}({', '.join(a.get('refs') or [])})가 그 근거를 가진 요소 밖({el or '근거 없는 위치'})에 있습니다 — "
                         "승인되지 않은 기능을 암시하는 자산은 쓰지 않습니다(asset_implies_unapproved)")
    css_ids = {aid for aid, how in used.items() if "css" in how}
    for x in sc.uses:  # 표지만 있고 실제로 불러오지 않는 자산(빈 자리로 렌더됨)
        if x["id"] and not x["src"] and x["id"] in reg["assets"] and x["id"] not in css_ids:
            E.append(f"{tag}: data-asset=\"{x['id']}\" 요소가 있지만 CSS에서 그 자산을 불러오지 않습니다 — 빈 자리로 렌더됩니다(asset_marked_unused)")
    css_marked = {aid for aid, how in used.items() if "css" in how and any(h != "css" for h in how)}
    for aid, how in used.items():
        if "css" in how and aid not in css_marked:
            E.append(f"{tag}: CSS로 쓰는 자산 {aid}는 HTML 요소에 data-asset=\"{aid}\" 표지가 필요합니다(역할·대체 텍스트 검사, asset_unmarked)")
    for aid in sorted(used):
        e, w = asset_problems(project, st, reg, aid)
        E += [f"{tag}: {x}" for x in e]
        W += [f"{tag}: {x}" for x in w]
        cp = rdir / ROUND_ASSET_DIR / Path(reg["assets"][aid]["file"]).name
        if not cp.is_file() or sha256_file(cp) != reg["assets"][aid]["sha256"]:
            E.append(f"{tag}: 라운드 자산 사본 {aid}가 레지스트리와 다릅니다(asset_copy_stale) — explore-asset sync --round {r['id']}")
    icons = [aid for aid in used if reg["assets"][aid]["kind"] == "icon"]
    if icons and not reg.get("icon_style"):
        E.append(f"{tag}: 아이콘을 쓰지만 프로젝트 아이콘 스타일 가이드가 없습니다(icon_style_missing)")
    return E, W, {"assets_used": sorted(used), "icons": sorted(icons),
                  "rights_unconfirmed": sorted(aid for aid in used if not official_ok(reg["assets"][aid]))}
