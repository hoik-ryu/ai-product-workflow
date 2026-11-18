"""/product-design 디자인 탐색(design_exploration). 설계: docs/roadmap/design-exploration-design.md

- EX1: 설정(`config.exploration`)·활성화(`start --workflow v2`, `explore-config`)·경로 안전(`design-explore/`)
- EX2: 1차 구조 탐색(`explore-init/check/compare/choose/skip/status`), UX Planning 제출 조건, UXD 근거 추적
- EX4: 브라우저 측정(`explore-verify`, pd_measure.py)과 선택 게이트(D3: 미실행 경고·차단 시안 거부·측정 이후 변경 무효)
- EX5: 2차 시각 탐색(`--phase visual`, pd_visual.py): 구조 지문 고정·후보 테마·색만 다른 시안 금지·채택(후보 VD·테마)·Design Direction 제출 조건
- EX5.1: 시각 자산 계약(pd_assets.py)·시각 품질 평가 계약(pd_quality.py)·기준 시안 수정 라운드(목표·피드백·반복 상한·수정 전후 비교)

원칙
- 탐색 시안은 승인 대상이 아닙니다. 어떤 승인 해시에도 `design-explore/`를 넣지 않습니다.
- 기존 승인·해시·revision 필드는 바꾸지 않습니다(추가만, 쓰기 전 `_preserved`로 확인).
- 기존 프로젝트에는 자동으로 켜지 않습니다. 신규 v2(`start --workflow v2`)만 기본 활성, 그 밖은 `explore-config`(사용자 문장).
- 엔진은 시안을 만들지 않습니다. 계약·판정·기록만 합니다(시안 작성은 Claude, frontend-design 절차는 reference/exploration.md).
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path

from pd_core import (  # noqa: F401
    rollback_on_failure,
    strip_fences,
    DD_FILE, PLANNING_FILES, STATE_REL, UXP_FILE, WORKFLOWS, _preserved, add_history, block, blocks_by_heading, emit, field_line,
    gate_on, id_exists, load_state, now, planning_ids, read_text, require_state, require_valid, save_state, sha256_file, strip_comments,
    workflow_of,
)

EXPLORE_DIR = "design-explore"
EXPLORE_MANIFEST = f"{EXPLORE_DIR}/explore.manifest.json"
EXPLORE_GITIGNORE = f"{EXPLORE_DIR}/.gitignore"
EXPLORE_FORMAT = "design-explore/v1"
PHASES = ("structure", "visual")
PHASE_STAGE = {"structure": "ux_planning", "visual": "design_direction"}
PHASE_PREFIX = {"structure": "S", "visual": "V"}
# U3·D2 기본값. 프로젝트 정책(config.exploration.limits)으로 바꿀 수 있습니다.
DEFAULT_LIMITS = {
    "variants_ai": 3,                 # AI 신규 탐색 기본 시안 수
    "variants_min": 2,                # 신규 탐색 최소(단일 시안은 후속 수정 라운드에서만)
    "variants_max": 3,
    "targets_default": 2,             # 1차 대상 장면 수 기본값(권장 범위 2–3)
    "reference_max_bytes": 10 * 1024 * 1024,   # EX3에서 사용(U3)
    "references_per_round": 5,                  # EX3에서 사용(U3)
    "reference_formats": ["png", "jpeg", "webp"],
    "evidence_max_bytes": None,
    "revisions_max": 2,               # EX5.1: 같은 기준 시안에서 이어지는 수정 라운드 상한(기본 2회)
}
VARIANT_LABELS = ("A", "B", "C")
EXP_ID_RE = re.compile(r"\bEXP-([SV]\d{2})-([A-C]|MIX)\b")


# ---------------------------------------------------------------- 설정·활성화(EX1)
def exploration_config(st: dict) -> dict | None:
    cfg = (st.get("config") or {}).get("exploration")
    return cfg if isinstance(cfg, dict) else None


def exploration_enabled(st: dict, phase: str) -> bool:
    """탐색이 이 단계에 적용되는지. v2이고 config.exploration.<phase>.enabled가 true일 때만(없으면 꺼짐 = 기존 프로젝트)."""
    if workflow_of(st) != "v2":
        return False
    cfg = exploration_config(st)
    return bool(cfg and (cfg.get(phase) or {}).get("enabled"))


def limits_of(st: dict) -> dict:
    cfg = exploration_config(st) or {}
    out = dict(DEFAULT_LIMITS)
    out.update({k: v for k, v in (cfg.get("limits") or {}).items() if k in DEFAULT_LIMITS})
    return out


def new_exploration_config(structure: bool, visual: bool, source: str) -> dict:
    return {"structure": {"enabled": structure}, "visual": {"enabled": visual}, "renderer": "html", "measure_cmd": None,
            "keep_unselected": False, "limits": dict(DEFAULT_LIMITS), "source": source, "at": now()}


def new_exploration_state() -> dict:
    return {p: {"status": "not_started", "rounds": [], "choice": None, "choices": [], "skip": None} for p in PHASES} | {"activations": []}


def ensure_exploration_state(st: dict) -> dict:
    ex = st.get("exploration")
    if not isinstance(ex, dict):
        ex = st["exploration"] = new_exploration_state()
    for p in PHASES:
        ex.setdefault(p, {"status": "not_started", "rounds": [], "choice": None, "choices": [], "skip": None})
    ex.setdefault("activations", [])
    return ex


def exploration_summary(st: dict) -> dict | None:
    cfg = exploration_config(st)
    if cfg is None or workflow_of(st) != "v2":
        return None
    ex = st.get("exploration") or {}
    out = {}
    for p in PHASES:
        e = ex.get(p) or {}
        out[p] = {"enabled": bool((cfg.get(p) or {}).get("enabled")), "stage": PHASE_STAGE[p], "status": e.get("status", "not_started"),
                  "rounds": [r["id"] for r in e.get("rounds") or []], "choice": (e.get("choice") or {}).get("id"),
                  "skipped": bool(e.get("skip"))}
    return out


def cmd_explore_config(a) -> None:
    """탐색 켜기·끄기(프로젝트 정책). 기존 승인·해시·revision은 바꾸지 않습니다. 2차(visual)는 design_direction 게이트가 켜져 있어야 합니다(D7)."""
    project = Path(a.project).resolve()
    st = load_state(project)
    if st is None:
        block("no_design_state", f"{STATE_REL}이 없습니다.")
    if workflow_of(st) != "v2":
        block("exploration_unavailable", "디자인 탐색은 워크플로 v2에서만 씁니다(v1은 변화 없음). v2 전환은 사용자 승인 후 migrate --to v2.")
    measure_opts = any(getattr(a, k, None) is not None for k in ("measure_cmd", "measure_method", "measure_viewports"))
    if not (a.enable or a.disable):
        if not measure_opts:
            block("invalid_arguments", "--enable·--disable 또는 측정 설정(--measure-cmd·--measure-method·--measure-viewports)이 필요합니다.")
        _measure_config(project, st, a)
    if measure_opts:
        block("invalid_arguments", "켜기·끄기와 측정 설정은 따로 실행합니다.")
    action = "enable" if a.enable else "disable"
    target = a.enable or a.disable
    phases = list(PHASES) if target == "all" else [target]
    if action == "enable" and "visual" in phases and not gate_on(st):
        block("design_direction_gate_required",
              "2차(시각) 탐색은 Design Direction 승인 게이트가 켜진 프로젝트에서만 켤 수 있습니다(D7). "
              "먼저 사용자 동의를 받아 migrate --to v2 --enable-gate design_direction(계획) → --confirm을 실행하세요. 한 명령에서 함께 켜지 않습니다.")
    new = copy.deepcopy(st)
    cfg = new.setdefault("config", {}).get("exploration")
    if not isinstance(cfg, dict):
        cfg = new["config"]["exploration"] = new_exploration_config(False, False, "explore-config")
    ex = ensure_exploration_state(new)
    changes, effects = [], {}
    for p in phases:
        want = action == "enable"
        if bool((cfg.get(p) or {}).get("enabled")) == want:
            continue
        cfg.setdefault(p, {})["enabled"] = want
        stage_status = new["stages"][PHASE_STAGE[p]]["status"]
        applies = ("now" if stage_status in ("in_progress", "not_started", "locked") else "next_reopen") if want else "now"
        effects[p] = {"stage": PHASE_STAGE[p], "stage_status": stage_status, "applies_from": applies}
        changes.append(f"config.exploration.{p}.enabled = {str(want).lower()}")
    if not changes:
        emit({"ok": True, "changed": False, "message": "이미 그 상태입니다. 바꾼 것이 없습니다.", "exploration": exploration_summary(st)})
    plan = {"action": action, "phases": phases, "changes": changes, "effects": effects,
            "note": ("승인 상태는 바꾸지 않습니다. 이미 승인·제출된 단계는 다음 reopen(사용자 결정) 이후 제출부터 탐색 조건이 적용됩니다."
                     if action == "enable" else "이미 기록된 탐색·선택 기록은 지우지 않습니다. 이후 제출에 탐색 조건을 적용하지 않습니다.")}
    if not a.confirm:
        emit({"ok": True, "dry_run": True, "plan": plan, "next": "사용자 확인 문장을 받아 같은 명령에 --confirm --note \"<사용자 문장>\""})
    note = (a.note or "").strip()
    if not note:
        block("statement_required", "탐색 설정 변경은 사용자 확인 문장(--note)이 필요합니다(정책 결정은 사용자가 합니다).")
    for p in phases:
        if p in effects:
            ex["activations"].append({"phase": p, "action": action, "at": now(), "statement": note, **effects[p]})
            add_history(new, PHASE_STAGE[p], f"exploration_{action}d", new["stages"][PHASE_STAGE[p]]["revision"], f"{p}: {note}")
    bad = [x for x in _preserved(st, new) if x not in ("config.exploration", "exploration")]
    if bad:
        block("internal_error", "탐색 설정이 기존 필드를 바꾸려 했습니다. 쓰지 않았습니다.", fields=bad)
    save_state(project, new)
    emit({"ok": True, "changed": True, "plan": plan, "exploration": exploration_summary(new)})


def _measure_config(project: Path, st: dict, a) -> None:
    """EX4 측정 설정: 프로젝트 측정 명령(엔진은 설치하지 않고 실행만)·방식·뷰포트. 승인·해시·revision과 무관, 사용자 문장 필요."""
    import pd_measure as MS
    if exploration_config(st) is None:
        block("exploration_disabled", "디자인 탐색 설정이 없습니다(먼저 explore-config --enable).")
    new = copy.deepcopy(st)
    changes = MS.cmd_measure_config(new, a, project)
    if not changes:
        emit({"ok": True, "changed": False, "message": "이미 그 설정입니다. 바꾼 것이 없습니다."})
    plan = {"changes": changes, "note": "측정 명령은 이 프로젝트 폴더에서 실행됩니다(엔진은 도구를 설치하지 않음). 명령 내용을 검토한 뒤 확인합니다. 승인 상태는 바꾸지 않습니다."}
    if not a.confirm:
        emit({"ok": True, "dry_run": True, "plan": plan, "next": "사용자 확인 문장을 받아 같은 명령에 --confirm --note \"<사용자 문장>\""})
    note = (a.note or "").strip()
    if not note:
        block("statement_required", "측정 설정 변경은 사용자 확인 문장(--note)이 필요합니다.")
    mc = new["config"]["exploration"].get("measure_confirmed")
    if isinstance(mc, dict) and not mc.get("statement"):
        mc.update(statement=note, at=now())  # 사용자 확인 문장과 시각(지문과 함께, P1-5)
    add_history(new, "ux_planning", "exploration_measure_config", new["stages"]["ux_planning"]["revision"], f"{'; '.join(changes)[:160]}: {note[:80]}")
    bad = [x for x in _preserved(st, new) if x not in ("config.exploration", "exploration")]
    if bad:
        block("internal_error", "측정 설정이 기존 필드를 바꾸려 했습니다. 쓰지 않았습니다.", fields=bad)
    save_state(project, new)
    emit({"ok": True, "changed": True, "plan": plan})


def start_v2_fields(st: dict, theme_rel: str | None, theme_hash_value: str | None) -> None:
    """start --workflow v2: 신규 v2 상태(설계 §2.3). design_direction 게이트·1차·2차 탐색 기본 활성."""
    at = now()
    st["config"] = {"workflow": "v2", "theme_file": theme_rel, "gates": {"design_direction": True},
                    "exploration": new_exploration_config(True, True, "start_v2")}
    st["stages"]["design_direction"] = {"status": "locked", "revision": 0, "artifacts": [DD_FILE], "artifacts_done": {},
                                        "submitted": None, "approved": None, "based_on_ux_spec_revision": None}
    st["stages"]["preview"]["review"] = None
    st["theme"] = {"path": theme_rel, "baseline_hash": theme_hash_value, "recorded_at": at}
    st["gate_activations"] = [{"gate": "design_direction", "at": at, "preview_status": "locked", "preview_approved_revision": None,
                               "design_direction_status": "locked", "source": "start_v2"}]
    st["exploration"] = new_exploration_state()


# ---------------------------------------------------------------- 경로 안전(EX1): 시안은 프리뷰·제품 코드에 섞이지 않음
_EXPLORE_REF_RE = re.compile(r"design-explore/")
CODE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".css", ".scss", ".html", ".vue", ".svelte", ".json", ".svg")


def _norm_text(b: bytes) -> bytes:
    """동일 파일 판정용 정규화: 줄 끝(CRLF)과 줄 끝 공백만 정규화합니다(내용 유사성은 판정하지 않음, D4)."""
    try:
        t = b.decode("utf-8")
    except UnicodeDecodeError:
        return b
    return "\n".join(x.rstrip() for x in t.replace("\r\n", "\n").split("\n")).strip("\n").encode("utf-8")


def explore_file_hashes(project: Path) -> dict[str, str]:
    """design-explore/ 안 텍스트·이미지 파일의 정규화 해시(동일 파일 복사 판정용). selection/의 증거 이미지도 포함합니다."""
    import hashlib
    root = project / EXPLORE_DIR
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.name not in (".gitignore", ".DS_Store") and p.stat().st_size > 0:
            try:
                out[hashlib.sha256(_norm_text(p.read_bytes())).hexdigest()] = str(p.relative_to(project))
            except OSError:
                continue
    return out


def _strip_comment_lines(text: str) -> str:
    return "\n".join(x for x in text.splitlines() if not x.strip().startswith(("//", "/*", "*", "#", "<!--")))


def explore_contamination(project: Path, files: list[str]) -> list[dict]:
    """파일들에 디자인 탐색 산출물·미승인 디자인이 들어왔는지(EX6, pd_guard 공통 규칙: 동일·주석/공백만 다른 복사, 시안 CSS 부분 복사,
    경로 참조·심볼릭 링크, 탐색 후보 토큰, 레퍼런스 원본, 미승인 자산). 시각적으로 비슷한 것은 판정하지 않습니다."""
    import pd_guard as GD
    return GD.findings(project, files)


# ---------------------------------------------------------------- 1차 구조 탐색(EX2)
SCREEN_TYPES_FILE = "design-profile/screen-types.json"
SCREEN_TYPES_FORMAT = "design-screen-types/v1"
# D1: 엔진 기본 화면 유형(프로젝트가 확장·재정의). 키워드는 대상 선정의 참고 신호일 뿐 승인 판정에 쓰지 않습니다.
# 한국어 기획 문장에 자주 나오는 낱말을 포함합니다(EX2.1 P1). 프로젝트 고유 낱말은 design-profile/screen-types.json으로 더합니다.
DEFAULT_SCREEN_TYPES = {
    "hub": {"label": "허브·첫 화면", "keywords": ["홈", "메뉴", "마이페이지", "내 정보", "첫 화면", "대시보드", "탭", "home", "menu", "hub"]},
    "browse": {"label": "목록·탐색", "keywords": ["목록", "명단", "리스트", "조회", "보기", "찾", "검색", "필터", "정렬", "고르", "선택", "browse", "list", "search", "filter"]},
    "detail": {"label": "상세", "keywords": ["상세", "자세히", "내역", "기록", "결과", "detail", "history"]},
    "input": {"label": "입력·작성", "keywords": ["등록", "입력", "작성", "추가", "신청", "수정", "편집", "만들", "저장", "체크", "기록합", "create", "add", "edit", "submit", "form"]},
    "dashboard": {"label": "현황", "keywords": ["현황", "통계", "요약", "순위", "집계", "진행률", "전적", "dashboard", "summary", "stats"]},
    "guidance": {"label": "안내·상태", "keywords": ["안내", "완료", "오류", "실패", "시작", "로그인", "가입", "대기", "guide", "welcome", "error"]},
}
STRUCTURE_AXES = ("layout", "hierarchy", "navigation", "density", "action_placement")
ELEMENT_KINDS = ("info", "action", "input", "navigation", "decoration")
BACKED_INTERACTIVE_KINDS = ("action", "input", "navigation")
ID_REF_RE = re.compile(r"^(?:(?:US|AC|FR|NFR)-\d{3}|FLOW-\d{3}(?:-S\d+[a-z]?)?|C-\d{2})$")
INTERACTIVE_TAGS = {"button", "input", "select", "textarea"}
INTERACTIVE_ROLES = {"button", "link", "tab", "checkbox", "switch", "menuitem", "radio", "option"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
PLAN_HEADINGS = {"explore": ("구조 개념", "정보 우선순위", "주 행동 위치", "진부한 기본값 대조", "다른 시안과의 차이"),
                 "revision": ("구조 개념", "정보 우선순위", "주 행동 위치", "진부한 기본값 대조", "기준 시안 대비 변경"),
                 "visual": ("시각 개념", "색·토큰", "타이포그래피", "간격·밀도", "컴포넌트 표현", "시각 계층·강조", "진부한 기본값 대조", "다른 시안과의 차이")}
CRITIQUE_FIELDS = {"explore": ("계획 대비", "정보 계층", "강조", "밀도", "제품 정체성", "진부한 기본값", "결함 후보", "요구사항 밖 요소", "시안 간 차이"),
                   "revision": ("계획 대비", "정보 계층", "강조", "밀도", "제품 정체성", "진부한 기본값", "결함 후보", "요구사항 밖 요소", "기준 시안 대비 변경"),
                   "visual": ("계획 대비", "정보 계층", "강조", "밀도", "제품 정체성", "진부한 기본값", "결함 후보", "요구사항 밖 요소", "시안 간 차이", "화면 간 일관성"),
                   "visual_reference": ("계획 대비", "정보 계층", "강조", "밀도", "제품 정체성", "진부한 기본값", "결함 후보", "요구사항 밖 요소", "시안 간 차이",
                                        "화면 간 일관성", "레퍼런스 대비", "레퍼런스와 다른 점", "레퍼런스 자산 미사용")}
VISUAL_AXES = ("typography", "density", "component", "hierarchy", "layout_grid")


def plan_key(phase: str, kind: str) -> str:
    return "visual" if phase == "visual" else kind


def critique_key(r: dict) -> str:
    if r.get("phase") == "visual":
        return "visual_reference" if r.get("mode", "ai") != "ai" else "visual"
    return r["kind"]
EVIDENCE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def inside(base: Path, p: Path) -> bool:
    """p(심볼릭 링크를 따라 정규화)가 base 안인지."""
    try:
        b, q = base.resolve(), p.resolve()
    except (OSError, RuntimeError):
        return False
    return q == b or b in q.parents


def variant_path_problem(project: Path, rid: str, lb: str, rel) -> str | None:
    """manifest의 시안 산출물 경로(render.html·plan 등, design-explore 기준 상대 경로)가 그 시안 폴더 안인지(파일럿 안정화).
    절대 경로·역슬래시·'..'·URL 인코딩된 '..'·심볼릭 링크로 시안 폴더 밖을 가리키면 사유를 돌려줍니다."""
    from urllib.parse import unquote
    if not isinstance(rel, str) or not rel.strip():
        return "경로가 비어 있음"
    if rel.startswith(("/", "~")) or "\\" in rel or re.match(r"^[A-Za-z]:", rel):
        return f"상대 경로가 아님({rel})"
    dec = unquote(rel)
    if any(part == ".." for part in dec.replace("\\", "/").split("/")):
        return f"'..'로 시안 폴더 밖을 가리킴({rel})"
    if not rel.startswith(f"{rid}/{lb}/"):
        return f"시안 폴더({rid}/{lb}/) 밖 경로({rel})"
    if not inside(project / EXPLORE_DIR / rid / lb, project / EXPLORE_DIR / rel):
        return f"심볼릭 링크 등으로 시안 폴더 밖을 가리킴({rel})"
    return None
FLOWS_FILE_REL = "docs/planning/04-user-flows.md"


def round_rel(rid: str) -> str:
    return f"{EXPLORE_DIR}/{rid}"


def _phase_state(st: dict, phase: str) -> dict:
    return ensure_exploration_state(st)[phase]


def _round(st: dict, rid: str) -> tuple[str, dict]:
    for p in PHASES:
        for r in (st.get("exploration") or {}).get(p, {}).get("rounds") or []:
            if r["id"] == rid:
                return p, r
    block("unknown_round", f"탐색 라운드 {rid}가 없습니다(explore-status로 확인).")
    return "", {}


def load_manifest(project: Path) -> dict:
    p = project / EXPLORE_MANIFEST
    if not p.exists():
        return {"format": EXPLORE_FORMAT, "experimental": True, "renderer": {"kind": "html", "adapter": None}, "guidance": [], "rounds": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("explore_manifest_unreadable", f"{EXPLORE_MANIFEST}을 읽을 수 없습니다: {e}")
    return {}


def save_manifest(project: Path, man: dict) -> None:
    p = project / EXPLORE_MANIFEST
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---- 화면 유형(D1)과 대상 선정(§2.4)
def screen_types(project: Path) -> dict:
    """{types, assign, hash, errors}. 프로젝트 파일이 없으면 엔진 기본 목록."""
    p = project / SCREEN_TYPES_FILE
    if not p.exists():
        return {"types": DEFAULT_SCREEN_TYPES, "assign": {}, "hash": None, "source": "default", "errors": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"types": DEFAULT_SCREEN_TYPES, "assign": {}, "hash": sha256_file(p), "source": SCREEN_TYPES_FILE, "errors": [f"JSON 오류: {e}"]}
    errs = []
    if d.get("format") != SCREEN_TYPES_FORMAT:
        errs.append(f"format은 {SCREEN_TYPES_FORMAT}이어야 합니다")
    base = DEFAULT_SCREEN_TYPES if d.get("extends", "default") == "default" else {}
    types: dict = {}
    for k, v in (d.get("types") or {}).items():  # 프로젝트 유형을 먼저(동점이면 프로젝트 정의가 우선)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(k)) or not isinstance(v, dict) or not isinstance(v.get("keywords", []), list):
            errs.append(f"types.{k}: 이름은 영문 소문자, 값은 {{label, keywords: []}}")
            continue
        types[k] = {"label": v.get("label") or k, "keywords": [str(x) for x in v.get("keywords") or []], "project": True}
    for k, v in base.items():
        types.setdefault(k, dict(v))
    assign = {}
    for k, v in (d.get("assign") or {}).items():
        if v not in types:
            errs.append(f"assign.{k}: 정의되지 않은 유형 {v}")
        else:
            assign[k] = v
    if not types:
        errs.append("화면 유형이 하나도 없습니다(extends: null이면 types를 정의해야 함)")
    return {"types": types or DEFAULT_SCREEN_TYPES, "assign": assign, "hash": sha256_file(p), "source": SCREEN_TYPES_FILE, "errors": errs}


def classify(text: str, types: dict) -> str:
    """키워드 일치 수가 가장 많은 유형. 동점이면 문장에서 더 뒤에 나온 낱말의 유형(한국어는 끝의 서술어가 화면이 하는 일),
    그래도 같으면 앞선 유형(프로젝트 정의가 앞). 일치가 없으면 unclassified."""
    best, score = "unclassified", (0, -1)
    low = text.lower()
    for k, v in types.items():
        words = [w.lower() for w in v.get("keywords") or [] if w]
        n = sum(low.count(w) for w in words)
        last = max((low.rfind(w) for w in words), default=-1)
        if n and (n, last) > score:
            best, score = k, (n, last)
    return best


HUB_RE = re.compile(r"홈|메뉴|마이페이지|내 정보|첫 화면|대시보드|\b(?:home|menu|dashboard)\b", re.I)
ROLE_FIRST_RE = re.compile(r"(?:로그인|역할|권한).{0,40}(?:홈|메뉴|첫 화면|보내|이동)|(?:관리자|사용자|회원|역할)(?:이면|에게).{0,30}(?:메뉴|홈)", re.S)
TARGET_LABEL_MAX = 40


def parse_target_spec(spec: str) -> list[dict]:
    """--targets "FLOW-007-S1+US-019=마이페이지, US-003=운영 홈" → [{anchor: [...], label}]. 라벨은 표시용(EX2.1 P2)."""
    out = []
    for part in [x.strip() for x in spec.split(",") if x.strip()]:
        ids, _, label = part.partition("=")
        anchors = [x.strip() for x in ids.split("+") if x.strip()]
        label = label.strip()
        if not anchors:
            block("invalid_arguments", f"대상 '{part}'에 기획 ID가 없습니다. 라벨만으로 대상을 정할 수 없습니다(ID[+ID…]=라벨).")
        if label and (len(label) > TARGET_LABEL_MAX or re.search(r"\b(?:US|AC|FR|NFR|FLOW|SCR|CMP|UXD)-\d{3}|\bC-\d{2}\b", label)):
            block("invalid_target_label", f"대상 라벨 '{label}'은 {TARGET_LABEL_MAX}자 이하의 표시용 이름이어야 하며 요구사항 ID를 담지 않습니다(근거는 ID로만).")
        out.append({"anchor": anchors, "label": label or None})
    return out


def _step_lines(flows: str) -> dict[str, str]:
    out = {}
    for line in flows.splitlines():
        m = re.match(r"^\s*(?:\|\s*|-\s*)(FLOW-\d{3}-S\d+[a-z]?)\b(.*)$", line)
        if m and m.group(1) not in out:
            out[m.group(1)] = re.sub(r"\s*\|\s*", " · ", m.group(2)).strip(" ·")
    return out


def structure_targets(project: Path, n: int, explicit: list[dict] | None, sty: dict) -> list[dict]:
    """1차 대상 장면(기획 ID 앵커). explicit(parse_target_spec)이 있으면 그 ID만, 없으면 근거를 붙여 자동 선정(EX2.1 P1).
    각 대상: {id, anchor[], label(표시), source_label(기획 문장), type, basis[]}. 라벨은 표시 전용이며 추적·검사에 쓰지 않습니다."""
    pid = planning_ids(project)
    flows = read_text(project, FLOWS_FILE_REL)
    steps = _step_lines(flows)
    us_text = read_text(project, PLANNING_FILES[1])
    us_titles = {k: (b.splitlines()[0].split(":", 1)[-1].strip()) for k, b in blocks_by_heading(us_text, 3, "US").items()}
    out = []
    if explicit:
        for i, tgt in enumerate(explicit, 1):
            for ident in tgt["anchor"]:
                if not ID_REF_RE.match(ident) or not id_exists(pid, ident):
                    block("unknown_target", f"대상 {ident}가 기획에 없습니다(FLOW 단계·US·AC·FR ID).")
            src = " / ".join(steps.get(x) or us_titles.get(x) or x for x in tgt["anchor"])
            typ = next((sty["assign"][x] for x in tgt["anchor"] if x in sty["assign"]), None) or classify((tgt["label"] or "") + " " + src, sty["types"])
            out.append({"id": f"T{i}", "anchor": tgt["anchor"], "label": tgt["label"] or src[:60], "source_label": src, "type": typ,
                        "basis": ["사용자 지정(--targets)"] + ([f"화면 유형 지정({SCREEN_TYPES_FILE} assign)"] if any(x in sty["assign"] for x in tgt["anchor"]) else [])})
        return out
    cands = []
    for fid, b in blocks_by_heading(flows, 2, "FLOW").items():
        us = sorted(set(re.findall(r"US-\d{3}", b)))
        must = sum(1 for u in us if pid["US_priority"].get(u) == "Must")
        fsteps = sorted({s for s in re.findall(r"FLOW-\d{3}-S\d+[a-z]?", b) if s.startswith(fid + "-")})
        for j, s in enumerate(fsteps):
            text = steps.get(s, "")
            basis, score = [], 0
            if j == 0:
                basis.append("주요 진입점(흐름의 첫 단계)")
                score += 2
            if ROLE_FIRST_RE.search(text):
                basis.append("역할별 첫 화면(로그인·역할 뒤 이동하는 화면)")
                score += 4
            if HUB_RE.search(text) or HUB_RE.search(b.splitlines()[0]):
                basis.append("허브(홈·메뉴·마이페이지 등 여러 기능으로 가는 화면)")
                score += 3
            links = sorted(set(re.findall(r"FLOW-\d{3}", text)) - {fid})
            if links:
                basis.append(f"다른 흐름으로 연결({', '.join(links)})")
                score += len(links)
            if must:
                basis.append(f"Must 스토리 {must}개")
            if j > 0 and score == 0:
                continue  # 첫 단계가 아니고 허브·역할·연결 신호도 없으면 후보 아님
            typ = sty["assign"].get(s) or next((sty["assign"][u] for u in us if u in sty["assign"]), None) or classify(text + " " + b.splitlines()[0], sty["types"])
            cands.append((-(score * 10 + must), fid, s, us, typ, basis))
    cands.sort()
    chosen, seen_types = [], set()
    for prefer_new in (True, False):  # 유형이 다른 장면을 먼저(허브·진입점 점수 순)
        for _, fid, s, us, typ, basis in cands:
            if len(chosen) >= n or any(c[0] == s for c in chosen) or any(c[0].rsplit("-", 1)[0] == fid for c in chosen):
                continue
            if prefer_new and typ in seen_types and typ != "unclassified":
                continue
            chosen.append((s, us, typ, basis))
            seen_types.add(typ)
    for i, (s, us, typ, basis) in enumerate(chosen, 1):
        out.append({"id": f"T{i}", "anchor": [s] + us[:3], "label": steps.get(s, s)[:60], "source_label": steps.get(s, s), "type": typ, "basis": basis})
    if not out:
        block("no_targets", "기획 흐름(04-user-flows)에서 대상 장면을 찾지 못했습니다. --targets로 FLOW 단계·US ID를 지정하세요.")
    return out


# ---- 요구사항 커버리지(EX2.1 P0-2)
# 엔진은 대상과 관련된 AC "후보"만 계산합니다(대상 앵커 → US(FLOW '커버하는 스토리') → 그 US·FR을 추적하는 AC).
# 후보를 필수로 볼지는 Claude가 분류하고(required·delegated·not_ui·uncertain), 불확실·위임·범위 밖은 사용자 확인 대상입니다.
# 엔진은 요구사항을 새로 만들지 않고, 선언된 필수 항목과 실제 HTML 요소를 대조만 합니다.
COVERAGE_STATUSES = ("required", "delegated", "not_ui", "other_target", "uncertain")
# required: 이 장면의 필수 정보·행동 / delegated: 이 장면 대신 다른 화면·상태에서 다룸(사용자 확인) / not_ui: 화면 요소가 아닌 규칙·서버 동작
# other_target: 이 장면과 무관한 다른 화면·기능의 AC(FR을 거쳐 후보에 들어온 경우가 많음) / uncertain: 해석 불확실(사용자 확인)
ITEM_KINDS = ("info", "action", "input", "navigation")
COVER_COMPAT = {"info": {"info"}, "action": {"action", "navigation"}, "input": {"input"}, "navigation": {"navigation", "action"}}
ITEM_ID_RE = re.compile(r"^R\d{1,3}$")


def requirement_candidates(project: Path, anchors: list[str]) -> dict:
    """대상 앵커에서 관련 US·FR과 AC 후보. 모든 AC를 필수로 보지 않습니다(분류는 manifest coverage)."""
    flows = read_text(project, FLOWS_FILE_REL)
    fblocks = blocks_by_heading(flows, 2, "FLOW")
    us_blocks = blocks_by_heading(read_text(project, PLANNING_FILES[1]), 3, "US")
    ac_blocks = blocks_by_heading(read_text(project, PLANNING_FILES[3]), 3, "AC")
    us, fr, direct = set(), set(), set()
    for a in anchors:
        if a.startswith("US-"):
            us.add(a)
        elif a.startswith("FR-"):
            fr.add(a)
        elif a.startswith("AC-"):
            direct.add(a)
        elif a.startswith("FLOW-"):
            b = fblocks.get(a[:8], "")
            covered = re.findall(r"US-\d{3}", field_line(b, "커버하는 스토리"))
            us |= set(covered or re.findall(r"US-\d{3}", b))
    for u in sorted(us):
        fr |= set(re.findall(r"FR-\d{3}", field_line(us_blocks.get(u, ""), "추적 대상")))
    acs = []
    for k, b in sorted(ac_blocks.items()):
        trace = set(re.findall(r"(?:US|FR)-\d{3}", field_line(b, "추적 대상")))
        if k in direct or trace & (us | fr):
            via = "anchor" if k in direct else ("US" if trace & us else "FR")  # FR만 겹치면 간접(다른 화면의 AC일 가능성이 큼)
            acs.append({"id": k, "title": b.splitlines()[0].split(":", 1)[-1].strip()[:80], "trace": sorted(trace), "via": via})
    return {"us": sorted(us), "fr": sorted(fr), "acs": acs}


def coverage_skeleton(project: Path, targets: list[dict]) -> dict:
    return {t["id"]: {"acs": {a["id"]: {"status": "", "note": ""} for a in requirement_candidates(project, t["anchor"])["acs"]}, "items": []}
            for t in targets}


def check_coverage(project: Path, rid: str, targets: list[dict], cov) -> dict:
    """라운드 수준 커버리지 선언 검사 → {errors, confirmations, not_ui, items{target: {id: item}}, candidates}."""
    pid = planning_ids(project)
    errors, confirm, not_ui, items, cands = [], [], [], {}, {}
    for t in targets:
        tid = t["id"]
        rc = requirement_candidates(project, t["anchor"])
        cands[tid] = rc
        c = (cov or {}).get(tid) if isinstance(cov, dict) else None
        if not isinstance(c, dict):
            errors.append(f"{rid}/{tid}: 요구사항 커버리지(manifest rounds.{rid}.coverage.{tid})가 없습니다(coverage_missing)")
            items[tid] = {}
            continue
        acs = c.get("acs") if isinstance(c.get("acs"), dict) else {}
        cand_ids = [x["id"] for x in rc["acs"]]
        for ac in cand_ids:
            v = acs.get(ac)
            if not isinstance(v, dict) or v.get("status") not in COVERAGE_STATUSES:
                errors.append(f"{rid}/{tid}: 후보 {ac}를 {'/'.join(COVERAGE_STATUSES)} 중 하나로 분류해야 합니다(coverage_unclassified)")
            elif v["status"] != "required" and not str(v.get("note") or "").strip():
                errors.append(f"{rid}/{tid}: {ac}({v['status']})에는 사유(note)가 필요합니다(coverage_note_missing)")
        for ac, v in acs.items():
            st_ = (v or {}).get("status") if isinstance(v, dict) else None
            if ac not in cand_ids:
                if not id_exists(pid, ac):
                    errors.append(f"{rid}/{tid}: 커버리지의 {ac}가 승인된 기획에 없습니다")
                    continue
                confirm.append(f"{tid}: {ac}는 이 대상의 AC 후보가 아닌데 분류에 포함됨(범위 밖, 사용자 확인)")
            if st_ in ("delegated", "uncertain"):
                confirm.append(f"{tid}: {ac} {'다른 화면·상태로 위임' if st_ == 'delegated' else '해석 불확실'} — {str(v.get('note') or '').strip()}")
            elif st_ in ("not_ui", "other_target"):
                not_ui.append(f"{tid}: {ac} {'화면 요소 아님' if st_ == 'not_ui' else '이 장면과 무관(다른 화면·기능)'} — {str(v.get('note') or '').strip()}")
        scope = set(cand_ids) | set(rc["us"]) | set(rc["fr"]) | set(t["anchor"])
        its: dict[str, dict] = {}
        for i, it in enumerate(c.get("items") if isinstance(c.get("items"), list) else []):
            if not isinstance(it, dict) or not ITEM_ID_RE.match(str(it.get("id", ""))):
                errors.append(f"{rid}/{tid}: items[{i}]의 id는 R1·R2… 형식이어야 합니다")
                continue
            if it["id"] in its:
                errors.append(f"{rid}/{tid}: 필수 항목 id {it['id']} 중복")
            if not str(it.get("what") or "").strip() or it.get("kind") not in ITEM_KINDS:
                errors.append(f"{rid}/{tid}: {it['id']}에 what(무엇)과 kind({'/'.join(ITEM_KINDS)})가 필요합니다")
            refs = it.get("refs") if isinstance(it.get("refs"), list) else []
            if not refs or any(not ID_REF_RE.match(str(r)) or not id_exists(pid, str(r)) for r in refs):
                errors.append(f"{rid}/{tid}: {it['id']}의 근거 refs가 없거나 기획에 없는 ID입니다")
            elif not set(refs) & scope:
                confirm.append(f"{tid}: 필수 항목 {it['id']}({it.get('what')})의 근거 {', '.join(refs)}가 이 대상의 후보 밖(범위 밖 해석, 사용자 확인)")
            its[it["id"]] = it
        items[tid] = its
        for ac in cand_ids:
            if (acs.get(ac) or {}).get("status") == "required" and not any(ac in (x.get("refs") or []) for x in its.values()):
                errors.append(f"{rid}/{tid}: {ac}를 required로 분류했지만 이 AC를 근거로 하는 필수 항목(items)이 없습니다(coverage_item_missing)")
    return {"errors": errors, "confirmations": confirm, "not_ui": not_ui, "items": items, "candidates": cands}


# ---- 라운드 생성
def _skeleton_html(rid: str, label: str, targets: list[dict], visual: bool = False) -> str:
    secs = "\n".join(
        f'  <section data-target="{t["id"]}" id="{t["id"]}">\n'
        f'    <!-- {t["id"]}: {", ".join(t["anchor"])} — {t["label"]}. 요소마다 data-el(manifest elements의 id), 예시 데이터는 data-sample -->\n'
        f'  </section>' for t in targets)
    return (f"<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{rid}-{label}</title>\n" + ('<link rel="stylesheet" href="tokens.css">\n' if visual else "") + f"<link rel=\"stylesheet\" href=\"styles.css\">\n</head>\n<body data-explore=\"{rid}-{label}\">\n{secs}\n</body>\n</html>\n")


def _skeleton_plan(rid: str, label: str, kind: str) -> str:
    heads = "\n\n".join(f"## {h}\n- " for h in PLAN_HEADINGS[kind])
    return (f"# {rid}-{label} 디자인 계획(frontend-design 절차: 계획 → 진부한 기본값 대조 → 제작 → 스크린샷 자기 비평)\n\n{heads}\n")


def _skeleton_critique(rid: str, labels: list[str], kind: str) -> str:
    body = ""
    for lb in labels:
        body += f"\n## {rid}-{lb}\n" + "".join(f"- **{f}**: \n" for f in CRITIQUE_FIELDS[kind])
    return (f"# {rid} 시각 평가(모델 평가: visually_reviewed=model — 사람 평가가 아님)\n"
            "스크린샷을 직접 보고 씁니다. 자동 검사·측정 통과를 선택이나 승인으로 보지 않습니다.\n" + body)


def _brief(rid: str, kind: str, targets: list[dict], n: int, parent: str | None, base: str | None, sty: dict, project_root: Path) -> str:
    rows = "\n".join(f"| {t['id']} | {', '.join(t['anchor'])} | {t['label']} | {t['type']} | {'; '.join(t.get('basis') or [])} |" for t in targets)
    extra = (f"\n- 후속 수정 라운드: 기준 시안 **{base}**(부모 라운드 {parent})을 고친 시안 {n}개. 기준과 같은 산출물은 거부됩니다.\n"
             if kind == "revision" else f"\n- 시안 {n}개. 시안끼리 **구조**(정보 배치·우선순위·주 행동 위치·화면 분할)가 명확히 달라야 합니다(색만 다르면 같은 시안).\n")
    parts = [f"# 탐색 브리프 {rid} — 1차 구조 탐색(UX Planning)\n\n엔진이 만든 파일입니다. 시안은 승인 대상이 아니며 제품 코드·정식 프리뷰에 쓰지 않습니다.\n",
             f"\n## 대상 장면(기획 ID 앵커)\n| 대상 | 앵커 | 표시 이름 | 화면 유형(참고, {sty['source']}) | 선정 근거 |\n|---|---|---|---|---|\n{rows}\n",
             "\n표시 이름은 비교 화면용일 뿐 요구사항 근거가 아닙니다. 근거는 앵커 ID입니다.\n"]
    for t in targets:
        cand = requirement_candidates(project_root, t["anchor"])["acs"]
        parts.append(f"\n### {t['id']} 요구사항 후보(AC)\n"
                     f"엔진이 앵커에서 계산한 **후보**입니다. 모두 필수가 아닙니다. manifest `coverage.{t['id']}.acs`에 "
                     "required(이 장면의 필수 정보·행동) · delegated(다른 화면·상태에서 다룸, 사용자 확인) · not_ui(화면 요소 아님) · "
                     "other_target(이 장면과 무관) · uncertain(해석 불확실, 사용자 확인)로 분류하고(not_ui·other_target·delegated·uncertain은 사유 필수), "
                     "required는 `items`(R1·R2…: what·kind·refs)로 나눕니다. 시안 요소는 `covers`로 항목을 덮습니다.\n"
                     + ("\n".join(f"- {a['id']} ({'앵커' if a['via'] == 'anchor' else ('스토리 직접' if a['via'] == 'US' else 'FR 간접')}): {a['title']}" for a in cand)
                        or "- (후보 없음)") + "\n")
    parts.append(f"\n## 규칙\n{extra}"
                 "- 정보·행동 요소는 manifest `elements`에 근거 ID(승인된 기획의 US·AC·FR·NFR·FLOW·C)를 선언하고 HTML에 `data-el`로 표시합니다. 근거 없는 버튼·입력·링크는 오류입니다.\n"
                 "- 필수 항목(coverage items)은 시안마다 HTML에 실제로 있는 요소(`covers`)로 덮어야 합니다. 빠지면 그 시안은 선택할 수 없습니다(required_missing).\n"
                 "- 예시 데이터는 `sample: true` + HTML `data-sample`. 실제 개인정보·외부 리소스(http 링크·웹 글꼴 URL)·스크립트는 쓰지 않습니다.\n"
                 "- 색·글꼴·컴포넌트 표현은 1차의 대상이 아닙니다(2차 시각 탐색). 회색조 와이어프레임 수준이면 충분합니다.\n"
                 "- 절차: 커버리지 분류 → 각 시안 plan.md(계획·진부한 기본값 대조) → index.html·styles.css 제작 → explore-check → explore-compare → 스크린샷을 보고 critique.md → 사용자 선택.\n")
    return "".join(parts)


def revision_depth(st: dict, phase: str, base: str | None) -> int:
    """기준 시안에서 거슬러 올라간 수정 라운드 수(원본 탐색 라운드 = 0)."""
    rounds = {r["id"]: r for r in _phase_state(st, phase)["rounds"]}
    d, cur, seen = 0, base, set()
    while cur:
        rid_ = cur.rsplit("-", 1)[0]
        r_ = rounds.get(rid_)
        if not r_ or r_.get("kind") != "revision" or rid_ in seen:
            break
        seen.add(rid_)
        d += 1
        cur = r_.get("base")
    return d


def _copy_base_variant(project: Path, base: str, vd: Path) -> None:
    """2차 수정 라운드: 기준 시안의 렌더 산출물을 출발점으로 복사(기준 라운드 파일은 그대로 보존)."""
    brid, blb = base.rsplit("-", 1)
    src = project / round_rel(brid) / blb
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.name != ".DS_Store":
            dst = vd / p.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = None
            if p.suffix in (".html", ".md"):
                text = p.read_text(encoding="utf-8").replace(f"{brid}-{blb}", f"{vd.parent.name}-{vd.name}")
            dst.write_text(text, encoding="utf-8") if text is not None else shutil.copyfile(p, dst)


def _base_manifest_entry(man: dict, base: str, rid: str, lb: str) -> dict:
    brid, blb = base.rsplit("-", 1)
    v = copy.deepcopy(((man.get("rounds") or {}).get(brid) or {}).get("variants", {}).get(blb) or {})
    v.pop("plan", None)
    v.pop("render", None)
    v["theme_candidate"] = f"{rid}/{lb}/theme.json"
    v["revised_from"] = base
    return v


def require_visual_gate(st: dict) -> None:
    """D7: 2차 탐색은 Design Direction 게이트가 켜져 있어야 합니다. 상태 복원 등으로 꺼졌으면 2차 명령 거부."""
    if not gate_on(st):
        block("exploration_gate_mismatch", "2차(시각) 탐색이 켜져 있지만 Design Direction 게이트가 꺼져 있습니다. 게이트를 켠 상태(migrate --enable-gate design_direction)에서만 2차 탐색을 씁니다(D7).")


def _brief_visual(project: Path, st: dict, rid: str, kind: str, targets: list[dict], n: int, parent: str | None, base: str | None) -> str:
    import pd_visual as VS
    rows = "\n".join(f"| {t['id']} | {t['label']} | {t['type']} | {'; '.join(t.get('basis') or [])} |" for t in targets)
    parts = [f"# 탐색 브리프 {rid} — 2차 시각 탐색(Design Direction)\n\n엔진이 만든 파일입니다. 시안·후보 테마는 승인 대상이 아니며 제품 코드·정식 프리뷰·공식 테마에 쓰지 않습니다. "
             "선택 결과는 explore-adopt로 **후보 VD·후보 테마**가 되고, VD마다 사용자가 결정합니다.\n",
             f"\n## 대표 화면(승인된 02)\n| 화면 | 이름 | 유형 | 선정 근거 |\n|---|---|---|---|\n{rows}\n"]
    for t in targets:
        fp = VS.fingerprint(project, t["id"])
        parts.append(f"\n### {t['id']} 구조 지문(바꾸지 않음)\n"
                     + "".join(f"- `{t['id']}:info-{i}` {x}\n" for i, x in enumerate(fp["info"], 1))
                     + "".join(f"- `{t['id']}:action-{i}` {x}\n" for i, x in enumerate(fp["actions"], 1))
                     + "".join(f"- `{t['id']}:input-{i}` {x}\n" for i, x in enumerate(fp["inputs"], 1))
                     + f"- 컴포넌트: {', '.join(fp['cmps']) or '없음'} · 상태: {', '.join(fp['states'])}\n")
    parts.append(f"\n## 규칙\n- 시안 {n}개{'(기준 ' + base + ' 수정)' if kind == 'revision' else ''}. 같은 시안의 모든 화면은 같은 theme.json 토큰과 같은 컴포넌트 규칙을 씁니다.\n"
                 "- 구조 고정: 위 정보(순서 포함)·행동·입력을 모두 넣고, 없는 정보·행동·컴포넌트를 더하지 않습니다(structure_drift). 레퍼런스 이미지 속 기능·문구·데이터도 마찬가지입니다.\n"
                 "- 시안끼리 색만 달라서는 안 됩니다: distinct_axes(typography·density·component·hierarchy·layout_grid)의 실제 CSS 값이 달라야 합니다(variants_color_only).\n"
                 "- styles.css는 색을 var(--토큰)으로만 씁니다(raw_color_literal). theme.json 토큰 이름은 04 문서 이름을 쓰고, 없는 이름은 ② 변경 요청 후보로 표시됩니다.\n"
                 "- 컴포넌트에는 data-cmp=\"CMP-xxx\"(변형은 data-cmp-variant)를 붙입니다. 측정(explore-verify)이 화면 간 같은 컴포넌트의 계산된 스타일을 비교합니다(component_inconsistent).\n"
                 "- 레퍼런스 기반이면 theme.json provenance에 토큰별 출처 규칙(RX)을 적고, 확인 전 추정값은 쓰지 않습니다.\n"
                 "- 절차(frontend-design): plan.md(계획) → 진부한 기본값 대조 → 제작 → 측정 스크린샷으로 critique.md(모델 평가) → 사용자 선택.\n")
    return "".join(parts)


def cmd_explore_init(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    phase = a.phase
    stage = PHASE_STAGE[phase]
    if not exploration_enabled(st, phase):
        block("exploration_disabled", f"이 프로젝트는 {'구조' if phase == 'structure' else '시각'} 탐색이 꺼져 있습니다(신규 v2만 기본 활성, 기존 프로젝트는 explore-config --enable {phase}).")
    if phase == "visual":
        require_visual_gate(st)
        if st["stages"]["ux_spec"]["status"] != "approved":
            block("upstream_not_approved", "2차(시각) 탐색은 UX Spec 승인 이후 Design Direction 중에만 합니다(승인된 구조 위에서 시각만 탐색).")
    require_valid(project, st, stage)
    if st["stages"][stage]["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {st['stages'][stage]['status']}입니다. "
              + ("1차 탐색은 UX Planning 초안(in_progress) 중에만 합니다." if phase == "structure" else "2차 탐색은 Design Direction 작성 중(begin --stage design_direction 이후)에만 합니다."))
    mode = a.mode or "ai"
    ref_ctx = None
    if mode != "ai":
        import pd_reference as RF  # 순환 import 방지(레퍼런스 모듈이 이 모듈을 씀)
        ref_ctx = RF.round_reference_context(project, st, getattr(a, "intent", None), phase)
    elif getattr(a, "intent", None):
        block("invalid_arguments", "--intent는 --mode reference·mixed에서만 씁니다.")
    lim = limits_of(st)
    ps = _phase_state(st, phase)
    kind, parent_r, base = "explore", None, None
    if a.parent:
        pphase, parent_r = _round(st, a.parent)
        if pphase != phase:
            block("invalid_arguments", "부모 라운드는 같은 단계여야 합니다.")
    if a.base:
        if not parent_r:
            block("invalid_arguments", "--base(기준 시안)는 --parent와 함께 씁니다.")
        m = re.fullmatch(rf"{re.escape(parent_r['id'])}-([A-C])", a.base)
        if not m or m.group(1) not in parent_r["variants"]:
            block("invalid_arguments", f"--base는 부모 라운드의 시안이어야 합니다(예: {parent_r['id']}-B).")
        kind, base = "revision", a.base
        depth = revision_depth(st, phase, a.base) + 1
        if depth > lim["revisions_max"]:
            block("revision_limit", f"같은 기준에서 이어진 수정 라운드가 상한({lim['revisions_max']}회)에 도달했습니다. 사용자와 방향을 다시 정하거나 "
                  "프로젝트 정책(explore-ref policy --limit revisions_max=…)을 사용자 문장으로 바꿉니다.", depth=depth)
    n = a.variants or (1 if kind == "revision" else lim["variants_ai"])
    if kind == "explore" and not (lim["variants_min"] <= n <= lim["variants_max"]):
        block("variant_count", f"신규 탐색 시안은 {lim['variants_min']}–{lim['variants_max']}개입니다(요청 {n}). 단일 시안은 기존 시안을 기준으로 고치는 후속 라운드(--parent --base)에서만 씁니다.")
    if kind == "revision" and not (1 <= n <= lim["variants_max"]):
        block("variant_count", f"후속 수정 라운드 시안은 1–{lim['variants_max']}개입니다(요청 {n}).")
    sty = screen_types(project)
    if sty["errors"]:
        block("invalid_screen_types", f"{SCREEN_TYPES_FILE} 형식 오류", errors=sty["errors"])
    import pd_visual as VS
    explicit = parse_target_spec(a.targets or "") if phase == "structure" else [x.strip() for x in (a.targets or "").split(",") if x.strip()]
    if phase == "visual":
        targets = VS.visual_targets(project, st, len(explicit) or lim["targets_default"], explicit or None) if (explicit or not parent_r) \
            else copy.deepcopy(parent_r["targets"])
    elif explicit:
        targets = structure_targets(project, len(explicit), explicit, sty)
    elif parent_r:
        targets = copy.deepcopy(parent_r["targets"])
    else:
        targets = structure_targets(project, lim["targets_default"], None, sty)
    goals = [g.strip() for g in (getattr(a, "goal", None) or []) if g.strip()]
    rfb = (getattr(a, "feedback", None) or "").strip() if isinstance(getattr(a, "feedback", None), str) else ""
    if kind == "revision" and phase == "visual" and (not goals or not rfb):
        block("revision_goals_required", "2차 수정 라운드는 수정 목표(--goal, 여러 개 가능)와 사용자 피드백 문장(--feedback)이 필요합니다. 목표 없이 고치지 않습니다.")
    rid = f"{PHASE_PREFIX[phase]}{len(ps['rounds']) + 1:02d}"
    rdir = project / round_rel(rid)
    if rdir.exists():
        block("existing_files", f"{round_rel(rid)}가 이미 있습니다. 덮어쓰지 않습니다.")
    labels = list(VARIANT_LABELS[:n])
    with rollback_on_failure(project, files=[EXPLORE_MANIFEST, f"{EXPLORE_DIR}/.gitignore"], new_dirs=[round_rel(rid)]):  # 실패 시 라운드 폴더·manifest 되돌림
        rdir.mkdir(parents=True)
        brief = (_brief(rid, kind, targets, n, parent_r["id"] if parent_r else None, base, sty, project) if phase == "structure"
                 else _brief_visual(project, st, rid, kind, targets, n, parent_r["id"] if parent_r else None, base))
        if ref_ctx:
            brief += ref_ctx["brief"]
        if goals:
            brief += (f"\n## 수정 라운드(기준 {base}, {revision_depth(st, phase, base) + 1}회째 / 상한 {lim['revisions_max']})\n"
                      f"> 사용자 피드백: {rfb}\n\n" + "".join(f"- G{i}: {g}\n" for i, g in enumerate(goals, 1))
                      + "\n기준 시안을 복사해 고칩니다. 승인된 구조·요구사항(구조 지문)은 바꾸지 않고, 정보·기능을 더하지 않습니다. "
                        "고친 뒤 explore-check → explore-verify(필요하면 --asset-fallback) → quality.json(목표별 수정 전·후 스크린샷) → explore-quality.\n")
        (rdir / "brief.md").write_text(brief, encoding="utf-8")
        for lb in labels:
            vd = rdir / lb
            vd.mkdir()
            (vd / "plan.md").write_text(_skeleton_plan(rid, lb, plan_key(phase, kind)), encoding="utf-8")
            (vd / "index.html").write_text(_skeleton_html(rid, lb, targets, phase == "visual"), encoding="utf-8")
            if phase == "visual" and kind == "revision":
                _copy_base_variant(project, base, vd)
            elif phase == "structure":
                (vd / "styles.css").write_text(f"/* {rid}-{lb}: 1차 구조 시안. 외부 리소스(url(http…)·@import http) 금지 */\n", encoding="utf-8")
            else:
                seed = VS.seed_theme(project, st, f"{rid}-{lb}")
                (vd / "theme.json").write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (vd / "tokens.css").write_text(VS.tokens_css(VS.theme_of(project, rid, lb)["resolved"]), encoding="utf-8")
                (vd / "styles.css").write_text(f"/* {rid}-{lb}: 2차 시각 시안. 색은 var(--토큰)만(날 색 값 금지), 토큰은 theme.json → explore-tokens. 외부 리소스 금지 */\n", encoding="utf-8")
        (rdir / "critique.md").write_text(_skeleton_critique(rid, labels, critique_key({"phase": phase, "mode": mode, "kind": kind})), encoding="utf-8")
        man = load_manifest(project)
        man_before = copy.deepcopy(man)
        pcov = ((man.get("rounds") or {}).get(parent_r["id"]) or {}).get("coverage") if parent_r and not explicit else None
        man["rounds"][rid] = {"phase": phase, "mode": mode, "intent": ref_ctx["intent"] if ref_ctx else None, "kind": kind, "parent": parent_r["id"] if parent_r else None, "base": base,
                              "coverage": (copy.deepcopy(pcov) if isinstance(pcov, dict) else coverage_skeleton(project, targets)) if phase == "structure" else None,
                              "basis": {"planning_revision": st["based_on"].get("planning_revision"), "screen_types": sty["source"], "screen_types_hash": sty["hash"]}
                              | ({"ux_spec_revision": (st["stages"]["ux_spec"].get("approved") or {}).get("revision"),
                                  "fingerprints": {t["id"]: t["fingerprint"] for t in targets}} if phase == "visual" else {}),
                              "targets": targets,
                              "variants": {lb: {"title": "", "concept": "", "distinct_axes": [], "plan": f"{rid}/{lb}/plan.md",
                                                "render": {"html": f"{rid}/{lb}/index.html"}, "elements": []}
                                           | ({"theme_candidate": f"{rid}/{lb}/theme.json", "emphasis": []} if phase == "visual" else {})
                                           | ({"mode": mode, "axis_sources": {}, "rules": [], "reinterpretation": ""} if ref_ctx else {})
                                           | (_base_manifest_entry(man_before, base, rid, lb) if phase == "visual" and kind == "revision" else {}) for lb in labels}}
        man.setdefault("guidance", [])  # Claude가 쓴 절차 지침(frontend-design@버전 또는 engine-procedure)을 기록
        save_manifest(project, man)
        rec = {"id": rid, "phase": phase, "mode": mode, "intent": ref_ctx["intent"] if ref_ctx else None, "kind": kind, "parent": parent_r["id"] if parent_r else None, "base": base,
               "variants": labels, "targets": targets, "created_at": now(),
               "basis": {"ux_planning_revision": st["stages"]["ux_planning"]["revision"], "planning_revision": st["based_on"].get("planning_revision"),
                         "screen_types_hash": sty["hash"]} | ({"ux_spec_revision": (st["stages"]["ux_spec"].get("approved") or {}).get("revision"),
                                                             "design_direction_revision": st["stages"]["design_direction"]["revision"]} if phase == "visual" else {}),
               "check": None, "choice": None}
        if kind == "revision":
            rec["revision"] = {"base": base, "depth": revision_depth(st, phase, base) + 1, "goals": goals, "feedback": rfb or None, "at": now()}
        ps["rounds"].append(rec)
        ps["status"] = "in_progress"
        ps["skip"] = None
        add_history(st, stage, "exploration_round", st["stages"][stage]["revision"], f"{rid}({kind}·{mode}{' ' + ref_ctx['intent'] if ref_ctx else ''}, 시안 {n}개, 대상 {', '.join(t['id'] for t in targets)})")
        write_gitignore(project, st)
        save_state(project, st)
        emit({"ok": True, "round": rid, "kind": kind, "variants": labels, "targets": targets, "dir": round_rel(rid),
              "files": {"brief": f"{round_rel(rid)}/brief.md", "manifest": EXPLORE_MANIFEST, "critique": f"{round_rel(rid)}/critique.md"},
              "next": (f"시안마다 plan.md → index.html·styles.css, manifest의 title·concept·distinct_axes·elements 작성 → explore-check --round {rid} → explore-compare → 스크린샷 비평(critique.md) → 사용자 선택(explore-choose)"
                       if phase == "structure" else
                       f"시안마다 plan.md(시각 계획) → theme.json(후보 테마, 04 토큰 이름) → explore-tokens --round {rid} → index.html·styles.css(var(--토큰)만, data-cmp 표지) → "
                       f"manifest elements(근거 SCR-xxx:info-n·action-n·CMP-xxx) → explore-check → explore-verify(측정) → explore-compare → critique.md → 사용자 선택 → explore-adopt")})


    # ---- HTML 계약 검사(렌더러 html)
class _HtmlScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.targets: list[str] = []
        self.elements: list[dict] = []      # {id, target, sample}
        self.unbacked: list[str] = []
        self.scripts = 0
        self.urls: list[str] = []
        self.interactive_refs: list[str] = []   # 상호작용 요소의 근거 data-el

    def _ctx(self, key: str):
        for n in reversed(self.stack):
            if n["attrs"].get(key) is not None:
                return n["attrs"][key]
        return None

    def _open(self, tag: str, attrs: list, push: bool) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "script":
            self.scripts += 1
        for k in ("src", "href", "srcset", "poster", "data", "action"):
            if a.get(k):
                self.urls.append(a[k])
        if a.get("style"):
            self.urls += re.findall(r"url\(\s*['\"]?([^'\")]+)", a["style"])
        if a.get("data-target") is not None:
            self.targets.append(a["data-target"])
        node = {"tag": tag, "attrs": a}
        if a.get("data-el") is not None:
            self.elements.append({"id": a["data-el"], "target": a.get("data-target") or self._ctx("data-target"),
                                  "sample": "data-sample" in a or self._ctx("data-sample") is not None})
        interactive = tag in INTERACTIVE_TAGS or (tag == "a" and "href" in a) or a.get("role") in INTERACTIVE_ROLES
        if interactive and a.get("type") != "hidden":
            el = a.get("data-el") or self._ctx("data-el")
            node["interactive_el"] = el
            if not el:
                self.unbacked.append(f"<{tag}{' role=' + a['role'] if a.get('role') else ''}>")
            else:
                self.interactive_refs.append(el)
        if push and tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, True)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break


def _scan_html(text: str) -> _HtmlScan:
    s = _HtmlScan()
    s.feed(text)
    s.close()
    return s


def _url_problem(u: str, base_dir: Path, round_dir: Path) -> str | None:
    u = u.strip()
    if not u or u.startswith(("#", "data:")):
        return None
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//", u, re.I) or re.match(r"^[a-z][a-z0-9+.-]*:", u, re.I):
        return f"외부·절대 리소스 {u}(external_resource)"
    target = (base_dir / u.split("#")[0].split("?")[0]).resolve()
    try:
        target.relative_to(round_dir.resolve())
    except ValueError:
        return f"라운드 폴더 밖 경로 {u}(path_escape)"
    return None


def _variant_files(project: Path, rid: str, label: str) -> dict[str, str]:
    root = project / round_rel(rid) / label
    out = {}
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.name != ".DS_Store":
                out[str(p.relative_to(project))] = sha256_file(p)
    return out


def check_round(project: Path, st: dict, rid: str) -> dict:
    phase, r = _round(st, rid)
    lim = limits_of(st)
    man = load_manifest(project)
    errors, warnings = [], []
    if man.get("format") != EXPLORE_FORMAT or man.get("experimental") is not True:
        errors.append(f"manifest: format은 {EXPLORE_FORMAT}, experimental은 true여야 합니다(explore_not_experimental)")
    import pd_render as RD  # EX7: 렌더러 공통 계약·렌더러별 검증
    if (man.get("renderer") or {}).get("kind") not in RD.RENDERER_KINDS:
        errors.append(f"manifest: renderer.kind는 {'/'.join(RD.RENDERER_KINDS)} 중 하나입니다(renderer_contract)")
    rinfo: dict[str, dict] = {}
    mr = (man.get("rounds") or {}).get(rid)
    if not isinstance(mr, dict):
        return {"ok": False, "round": rid, "errors": [f"manifest에 라운드 {rid}가 없습니다"], "warnings": [], "variants": {}}
    pid = planning_ids(project)
    tids = [t["id"] for t in r["targets"]]
    rdir = (project / round_rel(rid))
    per, sigs, cover_rep, ref_prov, vinfo = {}, {}, {}, {}, {}
    visual = phase == "visual"
    if visual:
        import pd_visual as VS
        cov = {"errors": [], "items": {}, "confirmations": [], "not_ui": [], "candidates": {}}  # 2차: 필수 항목 = 승인된 02 구조 지문
    else:
        cov = check_coverage(project, rid, r["targets"], mr.get("coverage"))  # EX2.1 P0-2: 라운드 공통 필수 항목
    for lb in r["variants"]:
        E, W = [], []
        v = (mr.get("variants") or {}).get(lb)
        if not isinstance(v, dict):
            per[lb] = {"errors": [f"{rid}-{lb}: manifest에 시안이 없습니다"], "warnings": []}
            continue
        tag = f"{rid}-{lb}"
        if not str(v.get("title") or "").strip() or not str(v.get("concept") or "").strip():
            E.append(f"{tag}: title·concept이 필요합니다(manifest_incomplete)")
        axes = v.get("distinct_axes") or []
        allowed_axes = VISUAL_AXES if visual else STRUCTURE_AXES
        if r["kind"] == "explore" and (not axes or any(x not in allowed_axes for x in axes)):
            E.append(f"{tag}: distinct_axes는 {'/'.join(allowed_axes)} 중 1개 이상({'2차는 시각 축(색만은 불가)' if visual else '1차는 구조 축'})")
        plan = project / EXPLORE_DIR / str(v.get("plan") or "")
        pp = variant_path_problem(project, rid, lb, v.get("plan")) if v.get("plan") else None
        if pp:
            E.append(f"{tag}: plan 경로 거부 — {pp}(variant_path_invalid)")
        elif not v.get("plan") or not plan.is_file():
            E.append(f"{tag}: 디자인 계획 plan.md가 없습니다")
        else:
            ptext = plan.read_text(encoding="utf-8")
            for h in PLAN_HEADINGS[plan_key(phase, r["kind"])]:
                m = re.search(rf"^##\s+{re.escape(h)}\s*\n(.*?)(?=^##\s|\Z)", ptext, re.M | re.S)
                if not m or not re.sub(r"[-\s]", "", m.group(1)):
                    E.append(f"{tag}: plan.md의 '{h}'가 비어 있습니다(plan_incomplete)")
        html_rel = (v.get("render") or {}).get("html")
        hpp = variant_path_problem(project, rid, lb, html_rel) if html_rel else None
        if hpp:
            E.append(f"{tag}: render.html 경로 거부 — {hpp}(variant_path_invalid)")
            html_rel = None
        hp = project / EXPLORE_DIR / str(html_rel or "")
        els = v.get("elements") if isinstance(v.get("elements"), list) else []
        decl: dict[str, dict] = {}
        for i, e in enumerate(els):
            if not isinstance(e, dict) or not e.get("id"):
                E.append(f"{tag}: elements[{i}]에 id가 필요합니다")
                continue
            if e["id"] in decl:
                E.append(f"{tag}: 요소 id {e['id']} 중복")
            decl[e["id"]] = e
            if e.get("target") not in tids:
                E.append(f"{tag}: 요소 {e['id']}의 target {e.get('target')}이 라운드 대상이 아닙니다")
            if e.get("kind") not in ELEMENT_KINDS:
                E.append(f"{tag}: 요소 {e['id']}의 kind는 {'/'.join(ELEMENT_KINDS)} 중 하나")
            refs = e.get("refs") if isinstance(e.get("refs"), list) else []
            if e.get("kind") != "decoration" and not refs:
                E.append(f"{tag}: 요소 {e['id']}({e.get('kind')})에 근거 ID가 없습니다(unbacked_element)")
            for ref in refs:
                if visual:
                    continue  # 2차 근거(SCR-xxx:info-n·CMP-xxx)는 구조 지문 검사(pd_visual)에서
                if not ID_REF_RE.match(str(ref)) or not id_exists(pid, str(ref)):
                    E.append(f"{tag}: 요소 {e['id']}의 근거 {ref}가 승인된 기획에 없습니다")
            if e.get("fold") not in (None, "above", "below"):
                E.append(f"{tag}: 요소 {e['id']}의 fold는 above/below")
        order: list[str] = []
        html_text = ""
        rk = RD.render_kind(v)
        rinfo[lb] = {"renderer": RD.renderer_label(v), "kind": rk, "level": RD.LEVEL[rk], "evidence": []}
        if rk == "adapter":
            E += RD.adapter_problems(project, r, lb, v, st)
        if rk == "figma":
            fE, fW, order, finfo = RD.figma_checks(project, st, r, lb, v, decl)
            E += fE
            W += fW
            rinfo[lb].update(evidence=finfo["evidence"], status=finfo["status"], frames=finfo["frames"])
        elif not html_rel or not hp.is_file():
            E.append(f"{tag}: 렌더 산출물 render.html이 없습니다(render_incomplete)")
        else:
            html_text = hp.read_text(encoding="utf-8")
            sc = _scan_html(html_text)
            if sc.scripts:
                E.append(f"{tag}: 스크립트는 쓰지 않습니다(정적 HTML/CSS, script_not_allowed)")
            for t in tids:
                if t not in sc.targets:
                    E.append(f"{tag}: 대상 {t}의 영역(data-target=\"{t}\")이 없습니다(target_missing)")
            for x in sc.unbacked:
                E.append(f"{tag}: 근거(data-el) 없는 상호작용 요소 {x}(unbacked_element) — 요구사항에 없는 기능을 추가하지 않습니다")
            seen = set()
            for el in sc.elements:
                if el["id"] not in decl:
                    E.append(f"{tag}: HTML의 data-el=\"{el['id']}\"가 manifest에 없습니다(undeclared_element)")
                    continue
                seen.add(el["id"])
                order.append(el["id"])
                if el["target"] != decl[el["id"]].get("target"):
                    E.append(f"{tag}: 요소 {el['id']}가 선언한 대상({decl[el['id']].get('target')})이 아닌 영역에 있습니다")
                if decl[el["id"]].get("sample") and not el["sample"]:
                    E.append(f"{tag}: 예시 데이터 요소 {el['id']}에 data-sample 표시가 없습니다(sample_unmarked)")
            for eid, e in decl.items():
                if eid not in seen:
                    E.append(f"{tag}: 선언한 요소 {eid}가 HTML에 없습니다(element_missing)")
            for ref in sc.interactive_refs:
                if ref in decl and decl[ref].get("kind") not in BACKED_INTERACTIVE_KINDS:
                    E.append(f"{tag}: 상호작용 요소의 근거 {ref}가 {decl[ref].get('kind')}입니다(action·input·navigation이어야 함, unbacked_element)")
            for u in sc.urls:
                prob = _url_problem(u, hp.parent, rdir)
                if prob:
                    E.append(f"{tag}: {prob}")
            for css in sorted((rdir / lb).rglob("*.css")):
                ctext = css.read_text(encoding="utf-8", errors="replace")
                for u in re.findall(r"url\(\s*['\"]?([^'\")]+)", ctext) + re.findall(r"@import\s+['\"]([^'\"]+)", ctext):
                    prob = _url_problem(u, css.parent, rdir)
                    if prob:
                        E.append(f"{tag}: {css.name}: {prob}")
        # 필수 요구사항 커버리지: HTML에 실제로 있는 요소(order: 표지 추출 ∩ 선언)만 셉니다. manifest에만 있는 선언은 덮은 것으로 보지 않음.
        present = set(order)
        covered: dict[str, set] = {x: set() for x in tids}
        for eid, e in decl.items():
            cv = e.get("covers")
            if cv is None:
                continue
            if not isinstance(cv, list):
                E.append(f"{tag}: 요소 {eid}의 covers는 필수 항목 id 목록이어야 합니다")
                continue
            for iid in cv:
                it = cov["items"].get(e.get("target"), {}).get(iid)
                if not it:
                    E.append(f"{tag}: 요소 {eid}의 covers {iid}가 {e.get('target')}의 필수 항목이 아닙니다(cover_unknown)")
                elif e.get("kind") not in COVER_COMPAT.get(it.get("kind"), set()):
                    E.append(f"{tag}: 요소 {eid}({e.get('kind')})는 {iid}({it.get('kind')})를 덮을 수 없습니다(cover_kind_mismatch)")
                elif not set(e.get("refs") or []) & set(it.get("refs") or []):
                    E.append(f"{tag}: 요소 {eid}의 근거가 {iid}의 근거({', '.join(it.get('refs') or [])})와 겹치지 않습니다(cover_ref_mismatch)")
                elif eid in present:
                    covered[e["target"]].add(iid)
        cover_rep[lb] = {}
        for x in tids:
            missing = sorted(set(cov["items"].get(x, {})) - covered[x], key=lambda k: int(k[1:]))
            cover_rep[lb][x] = {"covered": sorted(covered[x], key=lambda k: int(k[1:])), "missing": missing, "total": len(cov["items"].get(x, {}))}
            for iid in missing:
                it = cov["items"][x][iid]
                E.append(f"{tag}: {x} 필수 항목 {iid}({it.get('what')} · {', '.join(it.get('refs') or [])})이 시안 HTML에 없습니다(required_missing)")
        if r.get("mode", "ai") != "ai" or v.get("mode") not in (None, "ai") or v.get("rules"):
            import pd_reference as RF
            rE, rW, prov = RF.reference_variant_errors(project, st, r, lb, v, phase)
            E += rE
            W += rW
            ref_prov[lb] = prov
        E += __import__("pd_measure").check_layouts(v, tids, tag)
        if visual:
            vE, vW, vinfo[lb] = VS.variant_checks(project, st, r, lb, v, decl, order, html_text, renderer=rk)
            E += vE
            W += vW
        emb = __import__("pd_reference").reference_assets_in(project, st, rdir / lb)
        E += [f"{tag}: 레퍼런스 원본을 시안에 넣지 않습니다({x}, reference_asset_embedded)" for x in emb]
        sigs[lb] = tuple((t, tuple((decl[i].get("kind"), tuple(sorted(decl[i].get("refs") or [])), decl[i].get("region"), decl[i].get("fold"))
                                   for i in order if decl.get(i, {}).get("target") == t)) for t in tids)
        per[lb] = {"errors": E, "warnings": W}
    errors += cov["errors"]
    n = len(r["variants"])
    if r["kind"] == "explore" and not (lim["variants_min"] <= n <= lim["variants_max"]):
        errors.append(f"{rid}: 신규 탐색 시안은 {lim['variants_min']}–{lim['variants_max']}개입니다(현재 {n}, variant_count)")
    labels = list(r["variants"])
    if visual:
        cE, cW = VS.round_checks(r, vinfo, {lb: ((mr.get("variants") or {}).get(lb) or {}).get("distinct_axes") for lb in labels})
        errors += cE
        warnings += cW
    elif r["kind"] == "explore" or n > 1:
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                a_, b_ = labels[i], labels[j]
                if sigs.get(a_) is not None and sigs.get(a_) == sigs.get(b_) and not per[a_]["errors"] and not per[b_]["errors"]:
                    errors.append(f"{rid}: {a_}와 {b_}의 구조 서명(요소 순서·영역·첫 화면 노출)이 같습니다(variants_not_distinct). 색·장식만 다른 시안은 같은 시안입니다")
    if r["kind"] == "revision" and r.get("base"):
        bround, blabel = r["base"].rsplit("-", 1)
        base_files = _variant_files(project, bround, blabel)
        if not base_files:
            errors.append(f"{rid}: 기준 시안 {r['base']}의 파일이 없습니다(로컬 파일이 지워졌으면 비교할 수 없음)")
        for lb in labels:
            mine = {k.split("/", 3)[-1]: h for k, h in _variant_files(project, rid, lb).items() if not k.endswith("plan.md")}
            theirs = {k.split("/", 3)[-1]: h for k, h in base_files.items() if not k.endswith("plan.md")}
            if base_files and mine == theirs:
                errors.append(f"{rid}-{lb}: 기준 시안 {r['base']}와 렌더 산출물이 같습니다(revision_identical_to_base)")
    crit = rdir / "critique.md"
    missing_crit = critique_gaps(crit, rid, labels, critique_key(r))
    if missing_crit:
        warnings.append(f"{rid}: critique.md 미완성 — {', '.join(missing_crit[:6])}{' …' if len(missing_crit) > 6 else ''}(선택 전에 채워야 함)")
    all_err = errors + [e for lb in labels for e in per.get(lb, {}).get("errors", [])]
    warnings += [w for lb in labels for w in per.get(lb, {}).get("warnings", [])]
    return {"ok": not all_err, "round": rid, "kind": r["kind"], "errors": all_err, "round_errors": errors, "warnings": warnings,
            "variants": {lb: {"ok": not per[lb]["errors"], "errors": per[lb]["errors"], "warnings": per[lb]["warnings"],
                              "coverage": cover_rep.get(lb, {}), "reference": ref_prov.get(lb)} for lb in labels},
            "mode": r.get("mode", "ai"), "intent": r.get("intent"), "phase": phase, "renderers": rinfo,
            "visual": ({lb: {"tokens_needing_cr": (vinfo.get(lb) or {}).get("tokens_needing_cr", []),
                             "assets_used": (vinfo.get(lb) or {}).get("assets_used", []), "icons": (vinfo.get(lb) or {}).get("icons", []),
                             "rights_unconfirmed": (vinfo.get(lb) or {}).get("rights_unconfirmed", []),
                             "alignment": VS.alignment(project, st, vinfo.get(lb) or {}) if r.get("mode", "ai") != "ai" else []} for lb in labels}
                       if visual else None),
            "critique_missing": missing_crit, "measurement": __import__("pd_measure").round_measure_summary(project, st, r),
            "coverage": {"confirmations": cov["confirmations"], "not_ui": cov["not_ui"],
                         "candidates": {x: [a["id"] for a in v["acs"]] for x, v in cov["candidates"].items()},
                         "note": "엔진은 후보 계산과 선언 대조만 합니다. AC를 어떤 화면 요소로 볼지는 분류(Claude)와 사용자 확인의 몫이며, 의미가 맞는지는 판정하지 않습니다."}}


_FIELD_LINE_RE = re.compile(r"^[ \t]*-[ \t]*\*\*([^*\n]+)\*\*[ \t]*:[ \t]*(.*)$", re.M)
_PLACEHOLDER_RE = re.compile(r"^[\s\-–—…·.]*(?:TODO|TBD|작성 예정|미정)?[\s\-–—…·.]*$", re.I)


def critique_fields(section: str) -> dict[str, str]:
    """`- **항목**: 값` 블록을 {항목: 값}으로. 값 = 같은 줄의 나머지 + 다음 항목(또는 절 끝) 전까지 이어지는 줄.
    줄바꿈을 넘어 다음 항목 줄을 값으로 읽지 않습니다(EX2.1 P0-1: 빈 항목이 다음 항목 텍스트로 채워진 것처럼 보이던 우회 수정)."""
    marks = list(_FIELD_LINE_RE.finditer(section))
    out: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(section)
        cont = section[m.end():end]
        out[m.group(1).strip()] = (m.group(2) + "\n" + cont).strip()
    return out


def critique_gaps(path: Path, rid: str, labels: list[str], kind: str) -> list[str]:
    """시안별 평가 절에서 필수 항목이 없거나 비어 있으면(자리 표시만 있어도) 누락. 여러 줄 값은 허용합니다."""
    if not path.is_file():
        return [f"{rid}-{lb}" for lb in labels]
    text = path.read_text(encoding="utf-8")
    gaps = []
    for lb in labels:
        m = re.search(rf"^##[ \t]+{re.escape(rid)}-{lb}[ \t]*$(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)
        if not m:
            gaps.append(f"{rid}-{lb}")
            continue
        fields = critique_fields(m.group(1))
        for f in CRITIQUE_FIELDS[kind]:
            v = fields.get(f)
            if v is None or _PLACEHOLDER_RE.match(v):
                gaps.append(f"{rid}-{lb}.{f}")
    return gaps


def cmd_explore_check(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    _, r = _round(st, a.round)
    res = check_round(project, st, a.round)
    r["check"] = {"at": now(), "ok": res["ok"], "errors": len(res["errors"]), "warnings": len(res["warnings"])}
    save_state(project, st)
    emit(res, 0 if res["ok"] else 2)


# ---- 비교 페이지
def cmd_explore_compare(a) -> None:
    """compare.html(엔진 생성, 재생성 가능·Git 제외): 대상 × 뷰포트 × 시안을 나란히 봅니다. 외부 리소스 없음."""
    import html as H
    project = Path(a.project).resolve()
    st = require_state(project)
    _, r = _round(st, a.round)
    rid = r["id"]
    man = load_manifest(project)
    mr = (man.get("rounds") or {}).get(rid) or {}
    res = check_round(project, st, rid)
    vps = [("mobile", 390, 780, 1.0), ("desktop", 1280, 800, 0.5)]
    # 대상별 보기: 시안 원본은 그대로 두고, 다른 대상 영역을 숨긴 파생 페이지를 compare/에 만듭니다(재생성 가능·Git 제외·해시 제외).
    # iframe 주소의 #앵커는 브라우저가 부모 페이지까지 스크롤해 비교 화면이 밀리므로 쓰지 않습니다(실제 브라우저 검증에서 확인).
    cdir = project / round_rel(rid) / "compare"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir()
    import pd_measure as MS
    for lb in r["variants"]:
        src = project / round_rel(rid) / lb / "index.html"
        text = src.read_text(encoding="utf-8") if src.is_file() else "<p>render.html 없음</p>"
        for t in r["targets"]:
            (cdir / f"{lb}-{t['id']}.html").write_text(MS.target_view(text, f"../{lb}/", t["id"]), encoding="utf-8")
    meas = res["measurement"]
    MLABEL = {"passed": "측정 통과", "blocked": "측정 차단", "not_run": "측정 미실행", "pending": "측정 전", "invalid": "측정 무효", "stale": "측정 이후 변경"}
    cards = []
    for t in r["targets"]:
        rows = []
        for vname, w, h, sc in vps:
            cells = []
            for lb in r["variants"]:
                v = (mr.get("variants") or {}).get(lb) or {}
                st_ok = "검사 통과" if res["variants"].get(lb, {}).get("ok") else "검사 오류"
                cv = (res["variants"].get(lb, {}).get("coverage") or {}).get(t["id"]) or {}
                cov_txt = (f' · 필수 {len(cv.get("covered", []))}/{cv.get("total", 0)}' + (f' <span class="ok-False">누락 {", ".join(cv["missing"])}</span>' if cv.get("missing") else "")) if cv.get("total") else ""
                ms = meas.get(lb) or {}
                m_txt = f' · <span class="ok-{ms.get("status") == "passed"}" title="{H.escape("; ".join(ms.get("blocking") or [])[:400])}">{MLABEL.get(ms.get("status"), "측정 미실행")}</span>'
                rlab = (res.get("renderers") or {}).get(lb) or {}
                m_txt += f' · <small>렌더러 {H.escape(rlab.get("renderer", "html"))}({rlab.get("level", "checked")})</small>'
                figs = [x for x in rlab.get("evidence") or [] if x["target"] == t["id"]]
                if rlab.get("kind") == "figma":
                    shot = next((x for x in figs if x["viewport"] == vname), figs[0] if figs else None)
                    cells.append(f'<figure class="cell"><figcaption><b>{rid}-{lb}</b> {H.escape(str(v.get("title") or ""))} <span class="ok-{st_ok == "검사 통과"}">{st_ok}</span>{cov_txt}{m_txt}'
                                 f'<br><small>{H.escape(str(v.get("concept") or ""))}</small></figcaption>'
                                 + (f'<img src="{H.escape(shot["path"])}" style="width:{int(w * sc)}px;border:1px solid var(--line);border-radius:6px" alt="{rid}-{lb} {t["id"]} Figma 스크린샷">'
                                    if shot else "<p>Figma 스크린샷 없음</p>") + "</figure>")
                    continue
                cells.append(
                    f'<figure class="cell"><figcaption><b>{rid}-{lb}</b> {H.escape(str(v.get("title") or ""))} <span class="ok-{st_ok == "검사 통과"}">{st_ok}</span>{cov_txt}{m_txt}'
                    f'<br><small>{H.escape(str(v.get("concept") or ""))}</small></figcaption>'
                    f'<div class="frame" style="width:{int(w * sc)}px;height:{int(h * sc)}px"><iframe src="compare/{lb}-{t["id"]}.html" '
                    f'style="width:{w}px;height:{h}px;transform:scale({sc})" title="{rid}-{lb} {t["id"]} {vname}" loading="lazy"></iframe></div></figure>')
            rows.append(f'<h3>{vname} ({w}px{" · 50% 축소" if sc != 1 else ""})</h3><div class="row">{"".join(cells)}</div>')
        cards.append(f'<section class="target" id="cmp-{t["id"]}"><h2>{t["id"]} · {H.escape(t["label"])} '
                     f'<small>(근거 {", ".join(t["anchor"])} · 유형 {t["type"]})</small></h2>'
                     + (f'<p><small>기획 문장: {H.escape(t.get("source_label") or "")}</small></p>' if t.get("source_label") and t.get("source_label") != t["label"] else "")
                     + f'{"".join(rows)}</section>')
    nav = " · ".join(f'<a href="#cmp-{t["id"]}">{t["id"]}</a>' for t in r["targets"])
    vis_html = ""
    if res.get("phase") == "visual":
        vis_html = _visual_compare_section(project, st, r, res, H)
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{rid} 시안 비교</title><style>
:root{{color-scheme:light dark;--bg:#fff;--fg:#1b1b1b;--muted:#666;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#aaa;--line:#333}}}}
body{{margin:0;padding:16px;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
header{{border-bottom:1px solid var(--line);margin-bottom:16px}} .row{{display:flex;gap:16px;overflow-x:auto;padding-bottom:8px}}
.cell{{margin:0}} figcaption{{max-width:390px;margin-bottom:6px}} small{{color:var(--muted)}}
.frame{{overflow:hidden;border:1px solid var(--line);border-radius:6px;background:#fff}} iframe{{border:0;transform-origin:0 0;display:block}}
.ok-True{{color:#1a7f37}} .ok-False{{color:#c62828}}
.refimg{{max-width:390px;width:100%;border:1px solid var(--line);border-radius:6px}} table{{border-collapse:collapse;font-size:13px}} td,th{{border:1px solid var(--line);padding:3px 6px;text-align:left}}
</style></head><body><header><h1>{rid} 시안 비교 — {"1차 구조 탐색" if res.get("phase") != "visual" else "2차 시각 탐색(구조 고정)"}</h1>
<p>엔진이 만든 비교 페이지입니다(재생성 가능). 시안은 승인 대상이 아니며 제품 코드·정식 프리뷰에 쓰지 않습니다. 선택은 사용자 문장으로만 기록합니다(explore-choose).</p>
<p>정적 검사(checked): {"통과" if res["ok"] else f"오류 {len(res['errors'])}건(explore-check)"} · 자동 측정(measured, explore-verify): {H.escape(", ".join(f"{lb} {MLABEL.get(m.get('status'), '-')}" for lb, m in meas.items()))} · 모델 시각 평가(visually_reviewed: model)는 critique.md · 대상: {nav}</p>
{("<p><b>사용자 확인이 필요한 요구사항 해석</b></p><ul>" + "".join(f"<li>{H.escape(c)}</li>" for c in res["coverage"]["confirmations"]) + "</ul>") if res["coverage"]["confirmations"] else ""}
{("<details><summary>필수에서 제외한 후보(화면 요소 아님·다른 화면) " + str(len(res["coverage"]["not_ui"])) + "건 — 분류가 맞는지 확인</summary><ul>" + "".join(f"<li>{H.escape(c)}</li>" for c in res["coverage"]["not_ui"]) + "</ul></details>") if res["coverage"]["not_ui"] else ""}</header>
{vis_html}{"".join(cards)}</body></html>
"""
    out = project / round_rel(rid) / "compare.html"
    out.write_text(page, encoding="utf-8")
    emit({"ok": True, "round": rid, "compare": str(out.relative_to(project)), "check_ok": res["ok"], "check_errors": res["errors"][:10],
          "open": f"브라우저에서 {out.relative_to(project)}을 엽니다(파일 경로 그대로, 서버 불필요)"})


def _visual_compare_section(project: Path, st: dict, r: dict, res: dict, H) -> str:
    """2차: 레퍼런스 원본(로컬 파일, 외부 전송 없음)과 시안을 나란히, 토큰 ↔ 규칙 대조(엔진 계산 사실), ② 후보 토큰, 수정 전후."""
    out = []
    rv = r.get("revision") or {}
    if rv.get("base"):
        import pd_quality as QL
        brid, blb = rv["base"].rsplit("-", 1)
        _, br = _round(st, brid)
        before, after = QL._shots_of(br, blb), {lb: QL._shots_of(r, lb) for lb in r["variants"]}
        rows = []
        for t in r["targets"]:
            def pick(shots, rel):
                c = [k for k, x in shots.items() if x["target"] == t["id"] and x["viewport"].startswith("mobile")]
                return (rel + c[-1]) if c else None
            cells = [("수정 전 " + rv["base"], pick(before, f"../{brid}/"))] + [(f"수정 후 {r['id']}-{lb}", pick(after[lb], "")) for lb in r["variants"]]
            rows.append(f'<h3>{t["id"]} · {H.escape(t["label"])}</h3><div class="row">' + "".join(
                f'<figure class="cell"><figcaption><b>{H.escape(c)}</b></figcaption>'
                + (f'<img class="refimg" src="{H.escape(src)}" alt="{H.escape(c)} 측정 스크린샷">' if src else "<p>측정 스크린샷 없음(explore-verify)</p>") + "</figure>"
                for c, src in cells) + "</div>")
        out.append(f'<section class="target"><h2>수정 전후(측정 스크린샷, 모바일 첫 화면)</h2><p>피드백: {H.escape(rv.get("feedback") or "")}</p><ul>'
                   + "".join(f"<li>G{i}: {H.escape(g)}</li>" for i, g in enumerate(rv.get("goals") or [], 1)) + "</ul>" + "".join(rows) + "</section>")
    if r.get("mode", "ai") != "ai":
        import pd_reference as RF
        intent = RF.intent_of(st, r.get("intent")) or {}
        imgs = []
        for u in intent.get("uses") or []:
            ref = RF.refs_state(st).get(u["ref"]) or {}
            if ref.get("path"):
                rel = "../" + ref["path"].split(EXPLORE_DIR + "/", 1)[1]
                imgs.append(f'<figure class="cell"><figcaption><b>{u["ref"]}</b> 참고 축: {H.escape(", ".join(u.get("axes") or []))}'
                            f'<br><small>레퍼런스 원본(로컬, Git 제외). 이미지 속 기능·문구·데이터는 요구사항이 아닙니다.</small></figcaption>'
                            f'<img class="refimg" src="{H.escape(rel)}" alt="{u["ref"]} 레퍼런스 원본"></figure>')
        if imgs:
            out.append(f'<section class="target"><h2>레퍼런스 원본</h2><div class="row">{"".join(imgs)}</div></section>')
    rows = []
    for lb, v in (res.get("visual") or {}).items():
        for x in v.get("alignment") or []:
            rows.append(f"<tr><td>{r['id']}-{lb}</td><td>{H.escape(x['token'])}</td><td>{H.escape(str(x['value']))}</td><td>{x['rule']} ({x.get('basis') or '-'})</td>"
                        f"<td>{H.escape(json.dumps(x['reference_value'], ensure_ascii=False)[:80])}</td><td>{x['result']}{'' if x.get('distance') is None else ' · ' + str(x['distance'])}</td></tr>")
        if v.get("tokens_needing_cr"):
            rows.append(f"<tr><td>{r['id']}-{lb}</td><td colspan=5>04에 없는 토큰(② 변경 요청 후보, 공식 반영 불가): {H.escape(', '.join(v['tokens_needing_cr']))}</td></tr>")
    if rows:
        out.append('<section class="target"><h2>후보 테마 ↔ 레퍼런스 규칙 대조</h2><p><small>엔진이 계산한 사실입니다(색: RGB 거리 0 같음·24 이하 가까움, 길이: ±2). '
                   '자동 측정(measured)이나 모델 평가가 아닙니다. 레퍼런스와 다른 이유는 critique.md(모델 평가)에 적습니다.</small></p>'
                   '<table><tr><th>시안</th><th>토큰</th><th>값</th><th>규칙</th><th>레퍼런스 기록 값</th><th>대조</th></tr>' + "".join(rows) + "</table></section>")
    return "".join(out)


# ---- 보존 집합·.gitignore(D6)
def write_gitignore(project: Path, st: dict) -> None:
    keep_all = bool((exploration_config(st) or {}).get("keep_unselected"))
    lines = ["# /product-design이 관리합니다(직접 고치지 마세요). 디자인 탐색 산출물 중 보존 집합 밖을 Git에서 제외합니다(설계 D6).",
             "*/compare.html", "*/compare/", "*/shots/", "references/*/original.*"]
    for p in PHASES:
        for r in (st.get("exploration") or {}).get(p, {}).get("rounds") or []:
            ch = r.get("choice")
            if ch and not keep_all:
                chosen = set(ch["variants"])
                lines += [f"{r['id']}/{lb}/" for lb in r["variants"] if lb not in chosen]
    # 레퍼런스 원본은 기본 제외(U1). 권리·개인정보 조건을 갖춰 사용자가 추적을 결정한 원본만 예외.
    for rid, ref in sorted(((st.get("exploration") or {}).get("references") or {}).items()):
        if ref.get("tracked") and not ref.get("withdrawn"):
            lines.append("!" + ref["path"].split(EXPLORE_DIR + "/", 1)[1])
    p = project / EXPLORE_GITIGNORE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _round_files(project: Path, rid: str) -> dict[str, str]:
    root = project / round_rel(rid)
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(project))
        if p.is_file() and p.name not in (".DS_Store", "compare.html") and "/selection/" not in rel and "/shots/" not in rel and "/compare/" not in rel \
                and "/.selection." not in rel:
            out[rel] = sha256_file(p)
    return out


def _parse_selection(arg_variant: str | None, arg_per: str | None, r: dict) -> dict[str, str]:
    tids = [t["id"] for t in r["targets"]]
    if arg_variant and arg_per:
        block("invalid_arguments", "--variant와 --per-target 중 하나만 씁니다.")
    if arg_variant:
        if arg_variant not in r["variants"]:
            block("invalid_arguments", f"{r['id']}의 시안은 {', '.join(r['variants'])}입니다.")
        return {t: arg_variant for t in tids}
    if arg_per:
        sel = {}
        for part in arg_per.split(","):
            k, _, v = part.strip().partition("=")
            if k not in tids or v not in r["variants"]:
                block("invalid_arguments", f"--per-target 형식: T1=A,T2=B (대상 {', '.join(tids)}, 시안 {', '.join(r['variants'])})")
            sel[k] = v
        if set(sel) != set(tids):
            block("invalid_arguments", f"모든 대상({', '.join(tids)})의 선택이 필요합니다.")
        return sel
    block("invalid_arguments", "--variant 또는 --per-target이 필요합니다.")
    return {}


def cmd_explore_choose(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    phase, r = _round(st, a.round)
    if not exploration_enabled(st, phase):
        block("exploration_disabled", f"{phase} 탐색이 꺼져 있습니다.")
    stage = PHASE_STAGE[phase]
    if st["stages"][stage]["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {st['stages'][stage]['status']}입니다. 선택은 작성 중(in_progress)에만 기록합니다(승인 후 변경은 reopen).")
    if phase == "visual":
        require_visual_gate(st)
    sel = _parse_selection(a.variant, a.per_target, r)
    axes = {}
    for part in [x.strip() for x in (getattr(a, "axes", None) or "").split(",") if x.strip()]:
        k, _, v_ = part.partition("=")
        if phase != "visual" or k not in VISUAL_AXES + ("color",) or v_ not in r["variants"]:
            block("invalid_arguments", "--axes는 2차 탐색에서 축=시안 형식입니다(예: typography=A,density=C; 축: "
                  + ", ".join(VISUAL_AXES + ("color",)) + "). 나머지 축은 --variant 시안을 따릅니다.")
        axes[k] = v_
    if axes and (not a.variant or len(set(sel.values())) != 1):
        block("invalid_arguments", "--axes는 기준 시안(--variant)과 함께 씁니다.")
    chosen = sorted(set(sel.values()) | set(axes.values()))
    note = (a.note or "").strip()
    if not note:
        block("choice_statement_required", "사용자 선택 문장(--note)이 필요합니다. Claude가 대신 고르지 않습니다.")
    missing = [lb for lb in chosen if not re.search(rf"(?<![A-Za-z]){lb}(?![A-Za-z])", note)]
    if missing:
        block("choice_statement_unclear", f"선택 문장에 고른 시안({', '.join(missing)})이 드러나지 않습니다. '좋네요' 같은 응답은 선택이 아닙니다. 어떤 시안인지 다시 확인하세요.")
    res = check_round(project, st, r["id"])
    bad = res["round_errors"] + [e for lb in chosen for e in res["variants"][lb]["errors"]]
    if bad:
        block("exploration_check_failed", "검사를 통과하지 못한 라운드·시안은 선택할 수 없습니다.", errors=bad[:30])
    import pd_measure as MS  # EX4·D3: 측정 차단·무효는 객관적 거부이므로 사용자 확인 항목보다 먼저 판정
    waiver = (getattr(a, "measurement_waiver", None) or "").strip()
    meas = MS.choice_measurement(project, st, r, chosen, sel, waiver)
    conf = res["coverage"]["confirmations"]
    cnote = (getattr(a, "coverage_note", None) or "").strip()
    if conf and not cnote:
        block("coverage_confirmation_required", "요구사항 해석이 불확실하거나 다른 화면에 위임한 항목이 있습니다. 사용자에게 보여 주고 확인 문장을 --coverage-note로 기록한 뒤 선택합니다.",
              confirmations=conf)
    if res["critique_missing"]:
        block("critique_incomplete", "모든 시안의 시각 평가(critique.md)가 채워져야 선택할 수 있습니다(단일 시안도 검토 필요).", missing=res["critique_missing"][:20])
    provenance = None
    if r.get("mode", "ai") != "ai":
        import pd_reference as RF
        provenance = RF.choice_provenance(project, st, r, {lb: res["variants"][lb]["reference"] for lb in chosen})
    if phase == "visual":
        import pd_quality as QL
        qs = QL.review_state(project, st, r, res)
        if (r["kind"] == "revision" or qs["present"]) and not qs["valid"]:
            block("quality_review_required" if not qs["present"] else "quality_review_invalid",
                  "2차 수정 라운드는 시각 품질 평가(quality.json, 목표별 수정 전후 근거)가 필요하고, 있는 평가는 계약을 지켜야 합니다(explore-quality).",
                  errors=qs["errors"][:20])
        for lb in chosen:
            if (res["visual"] or {}).get(lb, {}).get("assets_used"):
                fb = MS.fallback_state(project, st, r, lb)
                if fb == "failed":
                    block("asset_fallback_failed", f"{r['id']}-{lb}: 자산 없이 렌더한 측정(explore-verify --asset-fallback)에서 차단 결과가 있습니다. 자산이 없어도 레이아웃이 무너지지 않게 고칩니다.")
                if fb in ("none", "stale"):
                    meas["warnings"].append(f"{r['id']}-{lb}: 자산 대체 표시 측정 {'없음' if fb == 'none' else '이후 변경'}(asset_fallback_unverified) — explore-verify --asset-fallback 권장")
    if meas["status"] == "passed":
        gaps = MS.critique_screenshot_gaps(project, r, chosen)
        if gaps:
            block("critique_unsupported", "측정한 시안의 시각 평가는 실제 측정 스크린샷을 근거로 씁니다. critique.md 시안 절에 "
                  "'- **근거 스크린샷**: shots/<run_id>/shots/<파일>.png'를 적으세요(모델 평가와 자동 측정을 구분, visually_reviewed: model).", missing=gaps)
    warnings = [f"다른 시안 오류(선택 대상 아님): {e}" for lb in r["variants"] if lb not in chosen for e in res["variants"][lb]["errors"]][:10]
    warnings += meas["warnings"]
    lim = limits_of(st)
    evid = [Path(x) for x in (a.evidence or [])]
    import pd_render as RD  # EX7: 측정 없는 렌더러(figma)는 렌더러 스크린샷을 핵심 증거로(선택한 대상만)
    mr_now = (load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
    rend_ev = [x for lb in chosen for x in RD.renderer_evidence(r, mr_now, lb) if sel.get(x["target"]) == lb]
    if not evid and not meas["evidence"] and rend_ev:
        meas["warnings"].append("렌더러 스크린샷(figma, declared)을 핵심 증거로 씁니다 — 브라우저 측정 사실이 아닙니다")
    if not evid and not meas["evidence"] and not rend_ev:
        why = "측정 스크린샷이 없거나 바뀌었으므로" if meas["status"] == "passed" else "측정이 없으므로"
        block("retention_incomplete", f"핵심 시각 증거가 없습니다. {why} 선택 시안의 화면 캡처(png·jpg·webp)를 --evidence로 1개 이상 등록하세요(D6).",
              missing=meas["evidence_missing"][:10])
    for e in evid:
        ep = e if e.is_absolute() else (project / e)
        if not inside(project, ep):
            block("invalid_evidence", f"증거 파일 {e}이 프로젝트 폴더 밖(심볼릭 링크 포함)에 있습니다. 화면 캡처를 프로젝트 안에 두고 등록합니다.")
        if not ep.is_file() or ep.suffix.lower() not in EVIDENCE_EXTS:
            block("invalid_evidence", f"증거 파일 {e}은 있는 png·jpg·jpeg·webp 파일이어야 합니다.")
        import pd_reference as RF
        if RF.sniff(ep.read_bytes()[:65536])[0] not in ("png", "jpeg", "webp"):
            block("invalid_evidence", f"증거 파일 {e}의 내용이 이미지(png·jpeg·webp)가 아닙니다(파일 앞부분으로 판정).")
        if lim.get("evidence_max_bytes") and ep.stat().st_size > lim["evidence_max_bytes"]:
            block("invalid_evidence", f"증거 파일 {e}이 정책 상한({lim['evidence_max_bytes']} bytes)보다 큽니다.")
    files_all = _round_files(project, r["id"])
    sdir = project / round_rel(r["id"]) / "selection"
    # 원자적 교체(파일럿 안정화): 새 선택 기록은 임시 폴더에 모두 만든 뒤 마지막에 바꿉니다. 이전 선택 기록(재선택)은
    # 교체·상태 저장이 끝날 때까지 그대로 두고, 실패하면 이전 기록과 상태 파일을 바이트 그대로 남깁니다.
    for old_tmp in (project / round_rel(r["id"])).glob(".selection.tmp-*"):  # 이전에 중단된 시도의 임시 폴더
        shutil.rmtree(old_tmp, ignore_errors=True)
    tdir = project / round_rel(r["id"]) / f".selection.tmp-{os.getpid()}"
    edir = tdir / "evidence"
    edir.mkdir(parents=True)
    final_rel = lambda q: str((sdir / q.relative_to(tdir)).relative_to(project))  # noqa: E731  (기록 경로는 교체 후 경로)
    ev_rec = []
    for i, e in enumerate(evid, 1):
        ep = e if e.is_absolute() else (project / e)
        dst = edir / f"{i:02d}-{re.sub(r'[^A-Za-z0-9._-]', '_', ep.name)}"
        shutil.copyfile(ep, dst)
        ev_rec.append({"path": final_rel(dst), "sha256": sha256_file(dst), "bytes": dst.stat().st_size, "source": "user_capture"})
    for x in (rend_ev if not evid and not meas["evidence"] else []):
        src = project / round_rel(r["id"]) / x["path"]
        dst = edir / f"r-{x['path'].replace('/', '-')}"
        shutil.copyfile(src, dst)
        ev_rec.append({"path": final_rel(dst), "sha256": sha256_file(dst), "bytes": dst.stat().st_size, "source": "renderer_screenshot",
                       "target": x["target"], "viewport": x["viewport"], "renderer_sha256": x["sha256"]})
    for x in meas["evidence"]:
        dst = edir / f"m-{x['variant']}-{x['target']}-{x['viewport']}.png"
        shutil.copyfile(x["file"], dst)
        ev_rec.append({"path": final_rel(dst), "sha256": sha256_file(dst), "bytes": dst.stat().st_size, "source": "measurement",
                       "variant": x["variant"], "target": x["target"], "viewport": x["viewport"], "measured_sha256": x["sha256"]})
    cid = f"EXP-{r['id']}-{chosen[0] if len(chosen) == 1 else 'MIX'}"
    if axes and phase == "visual":
        import pd_visual as VS
        merged_axes = {ax: axes.get(ax, a.variant) for ax in VISUAL_AXES + ("color",)}
    else:
        merged_axes = None
    retention = {k: v for k, v in files_all.items()
                 if k in (f"{round_rel(r['id'])}/brief.md", f"{round_rel(r['id'])}/critique.md")
                 or any(k.startswith(f"{round_rel(r['id'])}/{lb}/") for lb in chosen)}
    man_hash = sha256_file(project / EXPLORE_MANIFEST)
    rec = {"id": cid, "round": r["id"], "phase": phase, "kind": r["kind"], "base": r.get("base"), "variants": chosen, "per_target": sel,
           "axes": merged_axes,
           "statement": note, "feedback": [x for x in (a.feedback or []) if x.strip()], "at": now(),
           "measurement": meas["status"], "measurement_detail": meas["detail"], "visually_reviewed": "model",
           "renderers": {lb: RD.renderer_label((mr_now.get("variants") or {}).get(lb) or {}) for lb in chosen},
           "check": {"ok": True, "warnings": res["warnings"]},
           "coverage": {"variants": {lb: res["variants"][lb]["coverage"] for lb in chosen}, "confirmations": conf,
                        "confirmation_statement": cnote or None, "not_ui": res["coverage"]["not_ui"]},
           "files": files_all, "retention": retention | {EXPLORE_MANIFEST: man_hash}, "evidence": ev_rec,
           "guidance": (load_manifest(project).get("guidance") or []), "mode": r.get("mode", "ai"), "reference": provenance,
           "basis": current_choice_basis(project, st, phase, r)}
    if provenance:
        rec["retention"].update(provenance["retention"])
    (tdir / "selection.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rec["selection_sha256"] = sha256_file(tdir / "selection.json")
    ps = _phase_state(st, phase)
    for old in ps["rounds"]:
        if old["id"] != r["id"] and old.get("choice") and not old.get("superseded_by"):
            old["superseded_by"] = r["id"]
    r["choice"] = {"id": cid, "variants": chosen, "at": rec["at"]}
    ps["choice"] = rec
    ps["choices"].append({"id": cid, "round": r["id"], "at": rec["at"], "statement": note})
    ps["status"] = "chosen"
    ps["skip"] = None
    add_history(st, stage, "exploration_chosen", st["stages"][stage]["revision"], f"{cid}: {note[:120]}")
    bak = project / round_rel(r["id"]) / f".selection.bak-{os.getpid()}"
    with rollback_on_failure(project, files=[f"{EXPLORE_DIR}/.gitignore"]):
        try:
            if sdir.exists():
                os.replace(sdir, bak)
            os.replace(tdir, sdir)
            write_gitignore(project, st)
            save_state(project, st)
        except BaseException:
            if bak.exists():  # 교체 실패: 새 기록을 치우고 이전 선택 기록을 되돌림(상태 파일은 save_state가 원자적으로 쓰므로 그대로)
                if sdir.exists():
                    shutil.rmtree(sdir, ignore_errors=True)
                os.replace(bak, sdir)
            elif sdir.exists() and not tdir.exists():
                shutil.rmtree(sdir, ignore_errors=True)
            shutil.rmtree(tdir, ignore_errors=True)
            raise
    if bak.exists():
        shutil.rmtree(bak, ignore_errors=True)
    emit({"ok": True, "choice": cid, "variants": chosen, "per_target": sel, "warnings": warnings,
          "retention": sorted(rec["retention"]) + [str((sdir / 'selection.json').relative_to(project))] + [x["path"] for x in ev_rec],
          "excluded_from_git": [f"{round_rel(r['id'])}/{lb}/" for lb in r["variants"] if lb not in chosen] if not (exploration_config(st) or {}).get("keep_unselected") else [],
          "next": (f"선택을 반영한 UXD를 00 문서에 쓰고 근거에 {cid}를 적습니다(예: '근거: 사용자 선택 {cid}') → done → trace → submit" if phase == "structure"
                   else f"explore-adopt --round {r['id']}로 후보 VD·후보 테마를 만듭니다(승인 아님) → 07에 '후보'로 옮김 → VD마다 사용자 결정 → done → trace --stage design_direction → submit")})


def cmd_explore_skip(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    phase = a.phase
    if not exploration_enabled(st, phase):
        block("exploration_disabled", f"{phase} 탐색이 꺼져 있습니다(건너뛸 필요 없음).")
    stage = PHASE_STAGE[phase]
    if st["stages"][stage]["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {st['stages'][stage]['status']}입니다. 작성 중에만 건너뜁니다.")
    note = (a.note or "").strip()
    if not note:
        block("statement_required", "건너뛰기는 사용자 문장과 사유(--note)가 필요합니다. 엔진이 대신 건너뛰지 않습니다.")
    ps = _phase_state(st, phase)
    ps["status"] = "skipped"
    ps["skip"] = {"at": now(), "statement": note}
    add_history(st, stage, "exploration_skipped", st["stages"][stage]["revision"], f"{phase}: {note[:160]}")
    save_state(project, st)
    emit({"ok": True, "phase": phase, "status": "skipped", "next": f"{stage}를 탐색 없이 진행합니다(제출 조건 충족)."})


def choice_integrity(project: Path, st: dict, phase: str) -> dict:
    ch = ((st.get("exploration") or {}).get(phase) or {}).get("choice")
    if not ch:
        return {"choice": None, "changed": [], "missing": []}
    changed, missing = [], []
    items = dict(ch.get("retention") or {})
    items.update({e["path"]: e["sha256"] for e in ch.get("evidence") or []})
    sel = f"{round_rel(ch['round'])}/selection/selection.json"
    if ch.get("selection_sha256"):
        items[sel] = ch["selection_sha256"]
    for rel, h in items.items():
        if rel == EXPLORE_MANIFEST:
            continue  # manifest는 이후 라운드가 추가되며 바뀜(선택 라운드 항목은 selection.json 사본으로 보존)
        p = project / rel
        if not p.is_file():
            missing.append(rel)
        elif sha256_file(p) != h:
            changed.append(rel)
    return {"choice": ch["id"], "changed": changed, "missing": missing}


def cmd_explore_status(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    out = {"ok": True, "exploration": exploration_summary(st)}
    if out["exploration"] is None:
        emit({"ok": True, "exploration": None, "note": "이 프로젝트는 디자인 탐색을 쓰지 않습니다(v1이거나 꺼짐)."})
    integ = {p: choice_integrity(project, st, p) for p in PHASES}
    out["integrity"] = integ
    probs = [f"{p}: 선택({v['choice']}) 이후 보존 파일이 바뀜(changed_since_choice): {', '.join(v['changed'])}" for p, v in integ.items() if v["changed"]] + \
            [f"{p}: 선택({v['choice']})의 보존 파일이 없음(retention_missing): {', '.join(v['missing'])}" for p, v in integ.items() if v["missing"]]
    stale = {p: choice_staleness(project, st, p) for p in PHASES}
    out["stale"] = {p: v for p, v in stale.items() if v}
    probs += [f"{p}: 선택이 현재 승인 기준과 맞지 않음(stale): {'; '.join(v)}" for p, v in stale.items() if v]
    out["warnings"] = probs
    out["rounds"] = {p: [{k: r.get(k) for k in ("id", "kind", "variants", "base", "choice", "superseded_by", "check")}
                         for r in (st.get("exploration") or {}).get(p, {}).get("rounds") or []] for p in PHASES}
    emit(out)


# ---- 제출 조건·추적(UX Planning)
def uxd_exp_refs(project: Path) -> dict[str, list[str]]:
    text = strip_comments(read_text(project, UXP_FILE))
    out = {}
    for k, b in blocks_by_heading(text, 3, "UXD").items():
        refs = [m.group(0) for m in EXP_ID_RE.finditer(field_line(b, "근거"))]
        if refs:
            out[k] = refs
    return out


def vd_exp_refs(project: Path) -> dict[str, list[str]]:
    """07 VD의 근거에 적힌 2차 선택 ID."""
    text = strip_fences(read_text(project, DD_FILE))
    out = {}
    for k, b in blocks_by_heading(text, 3, "VD").items():
        refs = [m.group(0) for m in EXP_ID_RE.finditer(field_line(b, "근거"))]
        if refs:
            out[k] = refs
    return out


def exp_refs(project: Path, phase: str) -> dict[str, list[str]]:
    src = uxd_exp_refs(project) if phase == "structure" else vd_exp_refs(project)
    pre = f"EXP-{PHASE_PREFIX[phase]}"
    return {k: [x for x in v if x.startswith(pre)] for k, v in src.items() if any(x.startswith(pre) for x in v)}


def exploration_trace_errors(project: Path, st: dict, phase: str = "structure") -> list[str]:
    """UXD(1차)·VD(2차) 근거의 EXP-… 가 기록된 선택과 맞는지(exploration_ref_unknown·exploration_ref_not_chosen)."""
    ex = st.get("exploration") or {}
    ps = ex.get(phase) or {}
    chosen = {c["id"] for c in ps.get("choices") or []}
    rounds = {r["id"]: r for r in ps.get("rounds") or []}
    errs = []
    for uxd, refs in exp_refs(project, phase).items():
        for ref in refs:
            if ref in chosen:
                continue
            rid, lab = ref.split("-")[1], ref.split("-")[2]
            if rid in rounds and (lab in rounds[rid]["variants"] or lab == "MIX"):
                errs.append(f"{uxd}: 근거 {ref}는 사용자가 선택하지 않은 시안입니다(exploration_ref_not_chosen). 선택한 결과만 UXD에 반영합니다")
            else:
                errs.append(f"{uxd}: 근거 {ref}는 기록된 탐색 선택이 아닙니다(exploration_ref_unknown)")
    ch = ps.get("choice") or {}
    if ch.get("reference"):
        import pd_reference as RF
        errs += RF.provenance_trace_errors(project, st, ch, used=any(ch["id"] in v for v in exp_refs(project, phase).values()))
    if phase == "visual":
        import pd_visual as VS
        errs += VS.adoption_theme_errors(project, st) + VS.vd_asset_errors(project, st)
    return errs


def exploration_submit_check(project: Path, st: dict, stage: str) -> None:
    """탐색이 켜진 단계의 제출 조건(설계 §2.2). 꺼진 프로젝트에는 아무 영향이 없습니다."""
    phase = {v: k for k, v in PHASE_STAGE.items()}.get(stage)
    if not phase or not exploration_enabled(st, phase):
        return
    ps = (st.get("exploration") or {}).get(phase) or {}
    if ps.get("status") not in ("chosen", "skipped"):
        block("exploration_required", f"{phase} 탐색이 켜진 프로젝트입니다. 시안을 비교해 사용자가 선택(explore-choose)하거나, 사용자 문장으로 건너뛴(explore-skip) 뒤 제출합니다.",
              status=ps.get("status", "not_started"))
    if ps["status"] == "chosen":
        require_choice_current(project, st, phase)
        cid = ps["choice"]["id"]
        used = {r for refs in exp_refs(project, phase).values() for r in refs}
        doc = "UXD" if phase == "structure" else "VD(07, 승인 또는 제외로 결정)"
        if cid not in used:
            block("exploration_not_reflected", f"선택 {cid}를 근거로 하는 {doc}가 없습니다. 선택 결과를 {doc}로 기록하고 근거에 {cid}를 적으세요."
                  + (" 후보 VD는 explore-adopt로 만듭니다." if phase == "visual" else ""))
        integ = choice_integrity(project, st, phase)
        if integ["changed"] or integ["missing"]:
            block("changed_since_choice", f"선택({cid}) 이후 보존 파일이 바뀌었거나 없습니다. 선택한 산출물이 그대로여야 근거가 됩니다(다시 선택하거나 복원).",
                  changed=integ["changed"], missing=integ["missing"])


def current_choice_basis(project: Path, st: dict, phase: str, r: dict) -> dict:
    """선택이 근거로 삼는 상위 승인 기준(P1-1): planning revision, 2차는 승인된 UX Spec revision과 대상 화면 구조 지문."""
    import hashlib
    bo = st.get("based_on") or {}
    out = {"planning_revision": bo.get("planning_revision"),
           "planning_hashes_sha256": hashlib.sha256(json.dumps(bo.get("planning_hashes") or {}, sort_keys=True).encode("utf-8")).hexdigest()}
    if phase == "visual":
        import pd_visual as VS
        ux = st["stages"]["ux_spec"]
        out["ux_spec_revision"] = (ux.get("approved") or {}).get("revision") if ux.get("status") == "approved" else None
        out["fingerprints"] = {t["id"]: VS.fingerprint(project, t["id"]) for t in r.get("targets") or []}
    return out


def choice_staleness(project: Path, st: dict, phase: str) -> list[str]:
    """현재 선택이 지금의 상위 승인 기준과 다른 이유 목록(비어 있으면 최신). 기준 기록이 없는 이전 선택은 라운드 기준으로 비교합니다."""
    ps = (st.get("exploration") or {}).get(phase) or {}
    ch = ps.get("choice")
    if ps.get("status") != "chosen" or not ch:
        return []
    r = next((x for x in ps.get("rounds") or [] if x["id"] == ch["round"]), None)
    if r is None:
        return [f"선택 라운드 {ch['round']} 기록 없음"]
    basis = ch.get("basis")
    if basis is None:  # 기준 기록 도입 이전 선택: 라운드를 만들 때의 기준(상태·manifest)으로 비교
        mr = (load_manifest(project).get("rounds") or {}).get(r["id"]) or {}
        basis = {"planning_revision": (r.get("basis") or {}).get("planning_revision")}
        if phase == "visual":
            basis |= {"ux_spec_revision": (r.get("basis") or {}).get("ux_spec_revision"), "fingerprints": (mr.get("basis") or {}).get("fingerprints")}
    now_b = current_choice_basis(project, st, phase, r)
    why = []
    if basis.get("planning_revision") != now_b["planning_revision"]:
        why.append(f"planning revision r{basis.get('planning_revision')} → r{now_b['planning_revision']}")
    elif "planning_hashes_sha256" in basis and basis["planning_hashes_sha256"] != now_b["planning_hashes_sha256"]:
        why.append("승인된 planning 문서(01–05) 해시가 선택 당시와 다름")
    if phase == "visual":
        if now_b["ux_spec_revision"] is None:
            why.append("ux_spec이 승인 상태가 아님(재검토 중)")
        elif basis.get("ux_spec_revision") != now_b["ux_spec_revision"]:
            why.append(f"ux_spec 승인 revision r{basis.get('ux_spec_revision')} → r{now_b['ux_spec_revision']}")
        if basis.get("fingerprints") is not None and basis["fingerprints"] != now_b["fingerprints"]:
            changed = sorted(k for k in set(basis["fingerprints"]) | set(now_b["fingerprints"])
                             if (basis["fingerprints"] or {}).get(k) != now_b["fingerprints"].get(k))
            why.append(f"대상 화면 구조 지문 변경: {', '.join(changed)}")
    return why


def require_choice_current(project: Path, st: dict, phase: str) -> None:
    """선택을 제출·채택·승인 근거로 쓰기 전: 상위 기준이 그대로인지(stale), 선택 시안이 지금 검사를 통과하는지 재검증(P1-1)."""
    why = choice_staleness(project, st, phase)
    ch = ((st.get("exploration") or {}).get(phase) or {}).get("choice") or {}
    if why:
        block("exploration_choice_stale",
              f"선택 {ch.get('id')}은 지금의 승인 기준과 다른 기준에서 이루어졌습니다({'; '.join(why)}). 승인 근거로 쓰지 않습니다. "
              f"현재 승인 기준으로 시안을 다시 검사해 사용자에게 보여 주고 다시 선택(explore-choose)하거나, 새 라운드를 엽니다.", reasons=why)
    if ch:
        res = check_round(project, st, ch["round"])
        bad = res["round_errors"] + [e for lb in ch.get("variants") or [] for e in (res["variants"].get(lb) or {}).get("errors", [])]
        if bad:
            block("exploration_choice_invalid", f"선택 {ch['id']}의 시안이 지금 검사를 통과하지 못합니다. 고치거나 다시 선택합니다.", errors=bad[:30])


def exploration_basis(st: dict, stage: str) -> dict | None:
    phase = {v: k for k, v in PHASE_STAGE.items()}.get(stage)
    if not phase or not exploration_enabled(st, phase):
        return None
    ps = (st.get("exploration") or {}).get(phase) or {}
    if ps.get("status") == "skipped":
        return {"skipped": True, "statement": ps["skip"]["statement"], "at": ps["skip"]["at"]}
    ch = ps.get("choice")
    return {"choice": ch["id"], "selection_sha256": ch.get("selection_sha256"), "at": ch["at"]} if ch else None
