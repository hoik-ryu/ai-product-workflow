"""/product-design 공통 모듈: 상태 파일, 승인·해시, 워크플로 모델(v1/v2·의존성·게이트), 기획 게이트, Markdown 파싱,
추적성·Design Direction 검사, 프리뷰 해시·격리, 교차 검증. (product_design.py에서 함수 이동만 함)
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


STATE_REL = ".ai-workflow/design.json"
WORKFLOW_STATE_REL = ".ai-workflow/state.yaml"
NOTES_REL = ".ai-workflow/design-notes.md"
DESIGN_DIR = "docs/design"
UXP_FILE = "docs/design/00-ux-decisions.md"
IA_FILE = "docs/design/01-information-architecture.md"
SCREENS_FILE = "docs/design/02-screens.md"
FLOWS_FILE = "docs/design/03-screen-flows.md"
UISYS_FILE = "docs/design/04-ui-system.md"
TRACE_FILE = "docs/design/05-design-traceability.md"
REVIEW_FILE = "docs/design/06-preview-review.md"
SPEC_FILES = (IA_FILE, SCREENS_FILE, FLOWS_FILE, UISYS_FILE, TRACE_FILE)
PREVIEW_DIR = "design-preview"
PREVIEW_MANIFEST = "design-preview/preview.manifest.json"
PREVIEW_TREE_KEY = "design-preview/"
PREVIEW_EXCLUDE_DIRS = {"node_modules", "dist", ".vite"}
PREVIEW_EXCLUDE_SUFFIX = (".tsbuildinfo",)
DISCOVERY_FILE = "docs/planning/01-discovery.md"
PLANNING_FILES = (
    "docs/planning/02-prd.md",
    "docs/planning/03-user-stories.md",
    "docs/planning/04-user-flows.md",
    "docs/planning/05-acceptance-criteria.md",
)
CLEAN_CHECK_IGNORED_PREFIXES = (".claude/",)
STAGES = ("ux_planning", "ux_spec", "preview")
STAGE_ARTIFACTS = {"ux_planning": [UXP_FILE], "ux_spec": list(SPEC_FILES), "preview": [REVIEW_FILE]}
STAGE_LABEL = {"ux_planning": "UX Planning(화면 상세 기획)", "ux_spec": "UX Specification(화면 설계)", "preview": "UI Preview(시각 디자인)"}
NEXT_STAGE = {"ux_planning": "ux_spec", "ux_spec": "preview"}

# ---------------------------------------------------------------- 워크플로 모델(v1 / v2, WF-D05)
# v1: config.workflow가 없거나 "v1". 기존 단계·승인·무효화 그대로.
# v2: design_direction 단계(WF-D02)와 테마 파일 해시가 더해짐.
#     design_direction → preview 의존은 게이트(config.gates.design_direction)가 켜진 프로젝트에서만 적용합니다(명시적 동의로 켬).
WORKFLOWS = ("v1", "v2")
DD_FILE = "docs/design/07-design-direction.md"
STAGES_BY_WORKFLOW = {"v1": STAGES, "v2": ("ux_planning", "ux_spec", "design_direction", "preview")}
ALL_STAGES = STAGES_BY_WORKFLOW["v2"]
IMPLEMENTED_STAGES = ("ux_planning", "ux_spec", "design_direction", "preview")
GATES = ("design_direction",)  # 켜면 preview begin·submit·approve에 design_direction 승인이 필요
STAGE_DEPS = {  # 앞 단계 승인 의존성(게이트·잠금 해제·무효화의 기준)
    "v1": {"ux_planning": (), "ux_spec": ("ux_planning",), "preview": ("ux_spec",)},
    "v2": {"ux_planning": (), "ux_spec": ("ux_planning",), "design_direction": ("ux_spec",), "preview": ("ux_spec", "design_direction")},
}
STAGE_LABEL["design_direction"] = "Design Direction(디자인 방향)"
PREVIEW_SEMANTIC_KEY = "design-preview/#semantic"
THEME_KEY = "theme"


def workflow_of(st: dict) -> str:
    wf = (st.get("config") or {}).get("workflow") or "v1"
    if wf not in WORKFLOWS:
        block("invalid_state", f"config.workflow 값이 올바르지 않습니다: {wf} (허용: {', '.join(WORKFLOWS)})")
    return wf


def stage_list(st: dict) -> tuple:
    return STAGES_BY_WORKFLOW[workflow_of(st)]


def stage_artifacts(st: dict, stage: str) -> list[str]:
    return [DD_FILE] if stage == "design_direction" else STAGE_ARTIFACTS[stage]


def gate_on(st: dict, gate: str = "design_direction") -> bool:
    return workflow_of(st) == "v2" and bool(((st.get("config") or {}).get("gates") or {}).get(gate))


def active_deps(st: dict, stage: str) -> tuple:
    """지금 실제로 적용되는 의존 단계. preview의 design_direction 의존은 게이트가 켜졌을 때만 적용합니다."""
    deps = STAGE_DEPS[workflow_of(st)][stage]
    if stage == "preview" and not gate_on(st):
        deps = tuple(d for d in deps if d != "design_direction")
    return tuple(d for d in deps if d in IMPLEMENTED_STAGES)


implemented_deps = active_deps  # 이전 이름(M1-2) 호환


def deferred_deps(st: dict, stage: str) -> tuple:
    """정의상 의존이지만 지금 적용하지 않는 단계(design_direction 게이트가 꺼짐)."""
    return tuple(d for d in STAGE_DEPS[workflow_of(st)][stage] if d not in active_deps(st, stage))


def upstream_of(st: dict, stage: str) -> set:
    """적용 중인 의존을 따라 올라간 모든 상위 단계. v1은 앞선 모든 단계와 같습니다."""
    seen, todo = set(), list(active_deps(st, stage))
    while todo:
        d = todo.pop()
        if d not in seen:
            seen.add(d)
            todo += list(active_deps(st, d))
    return seen


def dependents_of(st: dict, stage: str) -> list:
    """적용 중인 의존으로 이 단계에 기대는 하위 단계(워크플로 순서). v1은 뒤의 모든 단계와 같습니다."""
    return [k for k in stage_list(st) if stage in upstream_of(st, k)]


def require_stage_usable(st: dict, stage: str) -> None:
    if stage not in stage_list(st):
        block("stage_not_in_workflow", f"{stage}는 {workflow_of(st)} 워크플로에 없는 단계입니다.")
    if stage not in IMPLEMENTED_STAGES:
        block("stage_not_implemented", f"{STAGE_LABEL[stage]}는 아직 구현되지 않았습니다. 이 단계는 승인할 수 없습니다(상태만 기록).")


def state_shape_problems(st: dict) -> list[str]:
    """상태 파일 구조 점검. v2 필수 필드가 빠졌으면 migrate --to v2 --confirm으로 복구할 수 있습니다."""
    probs = []
    if not isinstance(st.get("stages"), dict):
        return ["stages가 없습니다"]
    wf = (st.get("config") or {}).get("workflow") or "v1"
    if wf not in WORKFLOWS:
        return [f"config.workflow 값이 올바르지 않습니다: {wf}"]
    for k in STAGES_BY_WORKFLOW[wf]:
        if not isinstance(st["stages"].get(k), dict) or "status" not in st["stages"][k]:
            probs.append(f"stages.{k}가 없습니다")
    if wf == "v1" and "design_direction" in st["stages"]:
        probs.append("v1 상태에 design_direction이 있습니다(v2 전환이 중간에 멈췄을 수 있음)")
    if wf == "v2" and "theme" not in st:
        probs.append("v2 필드 theme이 없습니다")
    return probs
STANDARD_STATES = ("기본", "로딩", "빈 상태", "오류", "권한 없음", "충돌")
PLATFORMS = ("mobile", "responsive", "공통")
UXD_STATUSES = ("확정", "권장안 수용")
FORBIDDEN_PREVIEW_PATTERNS = (
    (r"\bfetch\s*\(", "실제 네트워크 호출(fetch)"),
    (r"\baxios\b", "HTTP 클라이언트(axios)"),
    (r"\bXMLHttpRequest\b", "실제 네트워크 호출(XMLHttpRequest)"),
    (r"\bWebSocket\b", "실제 네트워크 연결(WebSocket)"),
    (r"\bEventSource\b", "실제 네트워크 연결(EventSource)"),
    (r"import\.meta\.env\.VITE_API", "실제 API 주소 환경변수"),
    (r"from\s+['\"][^'\"]*\bfrontend/", "제품 코드(frontend/) import"),
    (r"from\s+['\"](\.\./)+frontend\b", "제품 코드(frontend/) import"),
)
ID_RE = r"(?:US|AC|FR|NFR)-\d{3}|FLOW-\d{3}(?:-S\d+[a-z]?)?|\bC-\d{2}\b"
CONFIRMED_RE = r"C-\d{2}"  # PRD의 "사용자가 확인한 사항" 표(확정 사항) ID


# ---------------------------------------------------------------- 공통 유틸
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def block(error: str, message: str, **extra) -> None:
    emit({"ok": False, "error": error, "message": message, **extra}, 2)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 실패: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def git(cwd: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(cwd), *args], check=check)


def read_text(project: Path, rel: str) -> str:
    p = project / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def front_matter_revision(text: str) -> int | None:
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return None
    r = re.search(r"^revision:[ \t]*(\d+)", m.group(1), re.M)
    return int(r.group(1)) if r else None


# ---------------------------------------------------------------- 상태 파일
def load_state(project: Path) -> dict | None:
    p = project / STATE_REL
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("state_unreadable", f"{STATE_REL}을 읽을 수 없습니다: {e}")
    return None


def require_state(project: Path) -> dict:
    st = load_state(project)
    if st is None:
        block("no_design_state", f"{STATE_REL}이 없습니다. 먼저 start를 실행하세요.")
    probs = state_shape_problems(st)
    if probs:
        block("invalid_state", "상태 파일 구조가 올바르지 않습니다. 자동으로 고치지 않습니다.", problems=probs,
              hint="v2 전환이 중간에 멈췄다면 migrate --to v2 --confirm으로 누락 필드만 복구할 수 있습니다. 그 밖에는 백업(.ai-workflow/backup/design/)이나 Git 이력으로 복원하세요.")
    return st


def save_state(project: Path, st: dict) -> None:
    st["updated_at"] = now()
    p = project / STATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".design.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def add_history(st: dict, stage: str, event: str, revision: int | None = None, note: str = "") -> None:
    st.setdefault("history", []).append({"at": now(), "stage": stage, "event": event, "revision": revision, "note": note})


# ---------------------------------------------------------------- /product-start 상태 (읽기 전용)
def _stage_block(text: str, stage: str) -> str:
    m = re.search(rf"^  {stage}:[ \t]*\n(.*?)(?=^  [A-Za-z_]+:[ \t]*\n|^\S|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def _field(block_text: str, key: str) -> str | None:
    m = re.search(rf"^    {key}:[ \t]*\"?([A-Za-z0-9_]+)", block_text, re.M)
    return m.group(1) if m else None


def read_gate(project: Path) -> dict:
    """planning 승인과 승인 해시를 읽기 전용으로 확인합니다. state.yaml은 절대 쓰지 않습니다."""
    p = project / WORKFLOW_STATE_REL
    if not p.exists():
        return {"ok": False, "error": "no_workflow_state", "message": "`.ai-workflow/state.yaml`이 없습니다. 먼저 /product-start로 기획을 승인받아야 합니다."}
    text = p.read_text(encoding="utf-8")
    problems: list[str] = []
    info: dict = {}
    hashes_all: dict = {}
    for stage in ("discovery", "planning"):
        b = _stage_block(text, stage)
        status = _field(b, "status")
        info[f"{stage}_status"] = status
        if status != "approved":
            problems.append(f"{stage} 상태가 approved가 아닙니다 (현재: {status})")
        appr = re.search(r"^    approved:[ \t]*\n[ \t]+revision:[ \t]*\"?(\w+)", b, re.M)
        info[f"{stage}_approved_revision"] = appr.group(1) if appr else None
        hashes = dict(re.findall(r"(docs/planning/[\w./-]+?)\"?[ \t]*:[ \t]*\"?([0-9a-f]{64})", b))
        expected = (DISCOVERY_FILE,) if stage == "discovery" else PLANNING_FILES
        for f in expected:
            fp = project / f
            if f not in hashes:
                problems.append(f"{f}의 승인 해시가 기록되어 있지 않습니다")
            elif not fp.exists():
                problems.append(f"{f} 파일이 없습니다")
            elif sha256_file(fp) != hashes[f]:
                problems.append(f"{f}가 승인 이후 변경되었습니다 (해시 불일치)")
            hashes_all[f] = hashes.get(f)
    based_on = _field(_stage_block(text, "planning"), "based_on_discovery_revision")
    if based_on and info.get("discovery_approved_revision") and based_on != info["discovery_approved_revision"]:
        problems.append("planning이 최신 승인 discovery revision을 기준으로 하지 않습니다 (outdated)")
    design_status = _field(_stage_block(text, "design"), "status")
    info["state_yaml_design_status"] = design_status
    if design_status == "locked":
        problems.append("state.yaml의 design 단계가 locked입니다 (/product-start에서 기획을 재검토 중)")
    info["planning_hashes"] = hashes_all
    if problems:
        return {"ok": False, "error": "planning_not_approved", "message": "; ".join(problems), **info}
    return {"ok": True, **info}


# ---------------------------------------------------------------- 사전 점검
def git_dirty_paths(project: Path) -> list[str]:
    out = git(project, "status", "--porcelain", "--untracked-files=all")
    paths = []
    for line in out.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if not path.startswith(CLEAN_CHECK_IGNORED_PREFIXES):
            paths.append(path)
    return paths


def preflight(project: Path) -> dict:
    if (project / "skills/product-start/SKILL.md").exists() or (project / "skills/product-design/SKILL.md").exists():
        return {"ok": False, "error": "engine_repo", "message": "워크플로 엔진 저장소 안입니다. 제품 저장소에서 실행하세요."}
    try:
        top = git(project, "rev-parse", "--show-toplevel").strip()
    except RuntimeError:
        return {"ok": False, "error": "not_git_repo", "message": "Git 저장소가 아닙니다."}
    if Path(top).resolve() != project.resolve():
        return {"ok": False, "error": "not_repo_root", "message": f"Git 저장소 루트({top})에서 실행하세요."}
    if git(project, "rev-parse", "--verify", "HEAD", check=False) == "":
        return {"ok": False, "error": "no_commits", "message": "커밋이 하나 이상 있어야 합니다."}
    return {"ok": True, "branch": git(project, "branch", "--show-current").strip(), "dirty": git_dirty_paths(project)}


# ---------------------------------------------------------------- Markdown 파싱
def blocks_by_heading(text: str, level: int, prefix: str) -> dict[str, str]:
    """`## SCR-001: ...` 같은 헤딩 블록을 {ID: 본문}으로 반환합니다. 취소선(~~ID~~) 헤딩은 폐기로 보고 제외합니다."""
    hashes = "#" * level
    pat = re.compile(rf"^{hashes} ({prefix}-\d{{3}})\b.*$", re.M)
    out: dict[str, str] = {}
    matches = list(pat.finditer(text))
    for i, m in enumerate(matches):
        end_pat = re.compile(rf"^#{{1,{level}}} ", re.M)
        nxt = end_pat.search(text, m.end())
        end = nxt.start() if nxt else len(text)
        out[m.group(1)] = text[m.start():end]
    return out


def table_rows(text: str, first_col_re: str) -> dict[str, list[str]]:
    """첫 열이 ID인 표의 행을 {ID: [나머지 열...]}로 반환합니다."""
    out: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = re.match(rf"^\|\s*({first_col_re})\s*\|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return out


def planning_ids(project: Path) -> dict:
    prd = read_text(project, PLANNING_FILES[0])
    us = read_text(project, PLANNING_FILES[1])
    flows = read_text(project, PLANNING_FILES[2])
    ac = read_text(project, PLANNING_FILES[3])
    us_blocks = blocks_by_heading(us, 3, "US")
    priority = {}
    for k, b in us_blocks.items():
        m = re.search(r"\*\*우선순위[^*]*\*\*[^:\n]*:\s*(Must|Should|Could)", b)
        priority[k] = m.group(1) if m else None
    steps: set[str] = set()
    for line in flows.splitlines():
        m = re.match(r"^\s*(?:\|\s*|-\s*)(FLOW-\d{3}-S\d+[a-z]?)\b", line)
        if m:
            steps.add(m.group(1))
    return {
        "FR": set(table_rows(prd, r"FR-\d{3}")),
        "C": set(table_rows(prd, CONFIRMED_RE)),
        "NFR": set(table_rows(prd, r"NFR-\d{3}")),
        "US": set(us_blocks),
        "US_priority": priority,
        "FLOW": set(blocks_by_heading(flows, 2, "FLOW")),
        "STEP": steps,
        "AC": set(blocks_by_heading(ac, 3, "AC")),
    }


def id_exists(pid: dict, ident: str) -> bool:
    if ident.startswith("FLOW-") and "-S" in ident:
        return ident in pid["STEP"]
    kind = ident.split("-")[0]
    return ident in pid.get(kind, set())


def strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def strip_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", strip_comments(text), flags=re.S)


def field_line(block_text: str, label: str) -> str:
    m = re.search(rf"^\s*-\s*\*\*{label}\*\*\s*:\s*(.+)$", block_text, re.M)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- UX Planning 질문 라운드(design-notes.md)
RQ_RE = r"R\d{2}-Q\d+"
ROUND_STATUSES = ("답변 대기", "답변 완료", "취소")


def parse_rounds(project: Path) -> list[dict]:
    """design-notes.md의 `## 라운드 N — 주제` 블록과 `#### R03-Q1: 제목` 질문을 읽습니다."""
    text = strip_comments(read_text(project, NOTES_REL))
    rounds = []
    for m in re.finditer(r"^## 라운드 (\d+)\b[^\n]*$", text, re.M):
        nxt = re.compile(r"^## ", re.M).search(text, m.end())
        body = text[m.start(): nxt.start() if nxt else len(text)]
        qs = []
        for q in re.finditer(rf"^#### ({RQ_RE}):[ \t]*(.*)$", body, re.M):
            e = re.compile(r"^#{1,4} ", re.M).search(body, q.end())
            qb = body[q.start(): e.start() if e else len(body)]
            qs.append({"id": q.group(1), "title": q.group(2).strip(), "options": field_line(qb, "선택지"),
                       "recommendation": field_line(qb, "권장안"), "related": field_line(qb, "관련"), "text": qb.strip()})
        rounds.append({"round": int(m.group(1)), "heading": m.group(0)[3:].strip(), "status": field_line(body, "상태"),
                       "questions": qs, "raw": body.strip()})
    return rounds


def pending_round(project: Path) -> dict:
    """답변 대기 중인 라운드(최대 1개)와 형식 오류를 반환합니다."""
    rounds = parse_rounds(project)
    pid = planning_ids(project)
    errors: list[str] = []
    seen: set[str] = set()
    for r in rounds:
        if r["status"] and not r["status"].startswith(ROUND_STATUSES):
            errors.append(f"라운드 {r['round']}: 상태는 {'/'.join(ROUND_STATUSES)} 중 하나여야 합니다 (현재: '{r['status']}')")
        for q in r["questions"]:
            if q["id"] in seen:
                errors.append(f"질문 ID 중복: {q['id']}")
            seen.add(q["id"])
    pend = [r for r in rounds if r["status"].startswith("답변 대기")]
    if len(pend) > 1:
        errors.append(f"답변 대기 라운드가 {len(pend)}개입니다: {', '.join(str(r['round']) for r in pend)} (1개만 허용)")
    for r in pend:
        if not 1 <= len(r["questions"]) <= 4:
            errors.append(f"라운드 {r['round']}: 질문은 1–4개여야 합니다 (현재 {len(r['questions'])}개)")
        for q in r["questions"]:
            if not q["id"].startswith(f"R{r['round']:02d}-"):
                errors.append(f"{q['id']}: 라운드 {r['round']}의 질문 ID는 R{r['round']:02d}-Q#이어야 합니다")
            for f, label in (("options", "선택지"), ("recommendation", "권장안"), ("related", "관련")):
                if not q[f]:
                    errors.append(f"{q['id']}: {label}가 없습니다")
            rel = re.findall(ID_RE, q["related"])
            if q["related"] and not rel:
                errors.append(f"{q['id']}: 관련 기획 ID가 없습니다")
            for x in rel:
                if not id_exists(pid, x):
                    errors.append(f"{q['id']}: 기획에 없는 ID를 참조합니다: {x}")
    p = pend[-1] if pend else None
    if p:
        p = {k: p[k] for k in ("round", "heading", "status", "questions", "raw")}
    return {"pending": p, "errors": errors, "rounds": len(rounds),
            "last_round": max((r["round"] for r in rounds), default=0)}


# ---------------------------------------------------------------- 추적성 검사
def trace_ux_planning(project: Path) -> dict:
    pid = planning_ids(project)
    text = strip_comments(read_text(project, UXP_FILE))
    errors, warnings = [], []
    if not text.strip():
        return {"ok": False, "errors": [f"{UXP_FILE}이 없습니다"], "warnings": []}
    uxd = blocks_by_heading(text, 3, "UXD")
    dq = blocks_by_heading(text, 3, "DQ")
    pf = blocks_by_heading(text, 3, "PF")
    if not uxd:
        errors.append("확정된 UX 결정(UXD)이 하나도 없습니다")
    for k, b in uxd.items():
        status = field_line(b, "상태")
        if status not in UXD_STATUSES:
            errors.append(f"{k}: 상태는 {'/'.join(UXD_STATUSES)} 중 하나여야 합니다 (현재: '{status}')")
        rel = re.findall(ID_RE, field_line(b, "관련"))
        if not rel:
            errors.append(f"{k}: 관련 US/AC/FLOW/FR/NFR ID가 없습니다")
        for r in rel:
            if not id_exists(pid, r):
                errors.append(f"{k}: 기획에 없는 ID를 참조합니다: {r}")
    open_dq = [k for k, b in dq.items() if field_line(b, "상태").startswith("미결")]
    open_pf = [k for k, b in pf.items() if not field_line(b, "상태").startswith("해결")]
    if open_dq:
        warnings.append(f"미결 디자인 질문: {', '.join(open_dq)}")
    if open_pf:
        warnings.append(f"기획 재검토 대상(PF) {len(open_pf)}건: {', '.join(open_pf)} — /product-start에서 검토가 필요할 수 있습니다")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"UXD": len(uxd), "DQ_open": len(open_dq), "DQ": len(dq), "PF_open": len(open_pf)}}


def screen_info(project: Path) -> dict:
    text = strip_fences(read_text(project, SCREENS_FILE))
    scr = blocks_by_heading(text, 2, "SCR")
    info = {}
    for k, b in scr.items():
        states = set(re.findall(rf"\b({k}-ST\d+)\b", b))
        info[k] = {"block": b, "states": states,
                   "platform": field_line(b, "플랫폼"),
                   "trace": set(re.findall(ID_RE, field_line(b, "추적"))),
                   "uxd": set(re.findall(r"UXD-\d{3}", b)),
                   "cmp": set(re.findall(r"CMP-\d{3}", b))}
    return info


def structure_signature(project: Path) -> str:
    """IA 라우트 표 행과 화면 ID 목록의 해시. 화면 구성이 같으면 같은 값입니다."""
    ia = strip_fences(read_text(project, IA_FILE))
    rows = table_rows(ia, r"SCR-\d{3}")
    data = json.dumps({"routes": {k: rows[k] for k in sorted(rows)}, "screens": sorted(screen_info(project))}, ensure_ascii=False)
    return sha256_bytes(data.encode("utf-8"))


def trace_structure(project: Path) -> dict:
    pid = planning_ids(project)
    errors, warnings = [], []
    ia = strip_fences(read_text(project, IA_FILE))
    if not ia:
        errors.append(f"{IA_FILE}이 없습니다")
    scr = screen_info(project)
    if not scr:
        errors.append(f"{SCREENS_FILE}에 화면(## SCR-###)이 없습니다")
    ia_scr = set(table_rows(ia, r"SCR-\d{3}"))
    for s in sorted(ia_scr - set(scr)):
        errors.append(f"{IA_FILE} 라우트 표의 {s}가 {SCREENS_FILE}에 없습니다")
    for s in sorted(set(scr) - ia_scr):
        errors.append(f"{s}가 {IA_FILE} 라우트 표에 없습니다")
    covered: set[str] = set()
    for s, i in scr.items():
        if i["platform"] not in PLATFORMS:
            errors.append(f"{s}: 플랫폼은 {'/'.join(PLATFORMS)} 중 하나여야 합니다 (현재: '{i['platform']}')")
        if not i["trace"]:
            warnings.append(f"{s}: 추적 ID가 없습니다(공통 화면이면 사유를 적으세요)")
        for r in i["trace"]:
            if not id_exists(pid, r):
                errors.append(f"{s}: 기획에 없는 ID를 참조합니다: {r}")
            if r.startswith("US-"):
                covered.add(r)
    must = sorted(u for u, p in pid["US_priority"].items() if p == "Must")
    missing = [u for u in must if u not in covered]
    if missing:
        errors.append(f"화면이 없는 Must US: {', '.join(missing)}")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"SCR": len(scr), "Must_US": len(must), "Must_US_covered": len(must) - len(missing)}}


def trace_ux_spec(project: Path) -> dict:
    base = trace_structure(project)
    errors, warnings = list(base["errors"]), list(base["warnings"])
    pid = planning_ids(project)
    scr = screen_info(project)
    all_states = {st for i in scr.values() for st in i["states"]}
    uxp = strip_comments(read_text(project, UXP_FILE))
    uxd_defined = set(blocks_by_heading(uxp, 3, "UXD"))
    uisys = strip_fences(read_text(project, UISYS_FILE))
    cmp_defined = set(blocks_by_heading(uisys, 3, "CMP"))
    flows_doc = strip_fences(read_text(project, FLOWS_FILE))
    trace_doc = strip_fences(read_text(project, TRACE_FILE))
    for rel, txt in ((FLOWS_FILE, flows_doc), (UISYS_FILE, uisys), (TRACE_FILE, trace_doc)):
        if not txt:
            errors.append(f"{rel}이 없습니다")
    # 화면 상태
    for s, i in scr.items():
        for label in STANDARD_STATES:
            if not re.search(rf"^\|\s*(?:{s}-ST\d+|-|—)\s*\|\s*{re.escape(label)}\s*\|", i["block"], re.M):
                errors.append(f"{s}: 상태 표에 '{label}' 행이 없습니다(해당 없으면 '해당 없음'으로 적으세요)")
        for c in i["cmp"]:
            if c not in cmp_defined:
                errors.append(f"{s}: {UISYS_FILE}에 정의되지 않은 컴포넌트 {c}")
        for u in i["uxd"]:
            if u not in uxd_defined:
                errors.append(f"{s}: {UXP_FILE}에 없는 UX 결정 {u}")
    used_cmp = {c for i in scr.values() for c in i["cmp"]}
    for c in sorted(cmp_defined - used_cmp):
        warnings.append(f"{c}: 어떤 화면에서도 쓰이지 않습니다")
    used_uxd = {u for i in scr.values() for u in i["uxd"]} | set(re.findall(r"UXD-\d{3}", trace_doc))
    for u in sorted(uxd_defined - used_uxd):
        warnings.append(f"{u}: 어떤 화면에도 반영 표시가 없습니다")

    def check_refs(where: str, cell: str) -> list[str]:
        refs = re.findall(r"SCR-\d{3}(?:-ST\d+)?", cell)
        for r in refs:
            if "-ST" in r:
                if r not in all_states:
                    errors.append(f"{where}: {SCREENS_FILE}에 없는 화면 상태 {r}")
            elif r not in scr:
                errors.append(f"{where}: {SCREENS_FILE}에 없는 화면 {r}")
        return refs

    # FLOW 단계 → 화면 (03)
    step_rows = table_rows(flows_doc, r"FLOW-\d{3}-S\d+[a-z]?")
    for step in sorted(pid["STEP"]):
        if step not in step_rows:
            errors.append(f"FLOW 단계 {step}의 화면 대응이 {FLOWS_FILE}에 없습니다")
        elif not check_refs(f"{FLOWS_FILE} {step}", " ".join(step_rows[step])):
            errors.append(f"{FLOWS_FILE} {step}: 대응 화면(SCR)이 없습니다")
    for step in step_rows:
        if step not in pid["STEP"]:
            errors.append(f"{FLOWS_FILE}: 기획에 없는 FLOW 단계 {step}")
    # US → 화면 (05)
    us_rows = table_rows(trace_doc, r"US-\d{3}")
    scr_with_us: set[str] = set()
    for u, prio in sorted(pid["US_priority"].items()):
        if prio not in ("Must", "Should"):
            continue
        if u not in us_rows:
            errors.append(f"{TRACE_FILE}: {u}({prio}) 행이 없습니다")
            continue
        cell = " ".join(us_rows[u])
        refs = check_refs(f"{TRACE_FILE} {u}", cell)
        scr_with_us.update(r.split("-ST")[0] for r in refs)
        if not refs and (prio == "Must" or "후속" not in cell):
            errors.append(f"{TRACE_FILE} {u}({prio}): 화면이 없습니다" + ("" if prio == "Must" else "(후속이면 '후속: 사유'를 적으세요)"))
    for u in us_rows:
        if u not in pid["US"]:
            errors.append(f"{TRACE_FILE}: 기획에 없는 {u}")
    # AC → 화면/상태 또는 비UI (05)
    ac_rows = table_rows(trace_doc, r"AC-\d{3}")
    for a in sorted(pid["AC"]):
        if a not in ac_rows:
            errors.append(f"{TRACE_FILE}: {a} 행이 없습니다")
            continue
        cell = " | ".join(ac_rows[a])
        refs = check_refs(f"{TRACE_FILE} {a}", cell)
        if not refs:
            m = re.search(r"비UI\s*:\s*(\S.*)", cell)
            reason = m.group(1).strip(" |") if m else ""
            if not reason:
                errors.append(f"{TRACE_FILE} {a}: 화면(SCR) 또는 '비UI: 사유'가 필요합니다")
    for a in ac_rows:
        if a not in pid["AC"]:
            errors.append(f"{TRACE_FILE}: 기획에 없는 {a}")
    for s, i in scr.items():
        if s not in scr_with_us and not any(r.startswith("US-") for r in i["trace"]):
            warnings.append(f"{s}: 연결된 US가 없습니다(범위 확장 여부 확인)")
    counts = dict(base.get("counts", {}))
    counts.update({"CMP": len(cmp_defined), "UXD": len(uxd_defined), "FLOW_steps": len(pid["STEP"]),
                   "FLOW_steps_mapped": len([s for s in pid["STEP"] if s in step_rows]),
                   "AC": len(pid["AC"]), "AC_rows": len([a for a in pid["AC"] if a in ac_rows]),
                   "AC_non_ui": len([a for a in ac_rows if "비UI" in " ".join(ac_rows[a])])})
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts}


# ---------------------------------------------------------------- 프리뷰
def preview_files(project: Path) -> list[str]:
    root = project / PREVIEW_DIR
    out = []
    if not root.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in PREVIEW_EXCLUDE_DIRS)
        for f in sorted(filenames):
            if f.endswith(PREVIEW_EXCLUDE_SUFFIX) or f == ".DS_Store":
                continue
            out.append(str((Path(dirpath) / f).relative_to(project)))
    return sorted(out)


def preview_tree_hash(project: Path) -> str | None:
    files = preview_files(project)
    if not files:
        return None
    h = hashlib.sha256()
    for rel in files:
        h.update(rel.encode() + b"\0" + sha256_file(project / rel).encode() + b"\n")
    return h.hexdigest()


# ---------------------------------------------------------------- 프리뷰 격리(제품 코드와 분리)
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
NODE_BUILTINS = {"path", "url", "fs", "os", "process", "module"}


def strip_js_comments(src: str) -> str:
    """문자열·템플릿 리터럴은 보존하고 // 와 /* */ 주석만 지웁니다."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            out.append(" ")
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


STRING_LIT = r"""(['"`])((?:\\.|(?!\1).)*?)\1"""


def module_specifiers(code: str) -> tuple[list[str], list[str]]:
    """정적·동적 import, require, import.meta.glob, new URL의 경로 문자열과, 정적으로 확인할 수 없는 동적 참조를 반환합니다."""
    specs: list[str] = []
    dynamic: list[str] = []
    for pat in (rf"\bfrom\s*{STRING_LIT}", rf"\bimport\s*{STRING_LIT}", rf"\bexport\s*\*\s*from\s*{STRING_LIT}"):
        specs += [m.group(2) for m in re.finditer(pat, code)]
    for kw in (r"\bimport\s*\(", r"\brequire\s*\(", r"\bimport\.meta\.glob(?:Eager)?\s*\(", r"\bnew\s+URL\s*\("):
        for m in re.finditer(kw, code):
            rest = code[m.end():]
            lit = re.match(rf"\s*\[?\s*{STRING_LIT}", rest)
            if lit and "${" not in lit.group(2):
                specs.append(lit.group(2))
                if "glob" in kw:
                    close = rest.find(")")
                    specs += [x.group(2) for x in re.finditer(STRING_LIT, rest[:close if close > 0 else 200])][1:]
            else:
                dynamic.append(code[m.start(): m.end() + 40].split("\n")[0])
    return specs, dynamic


def _escapes(base: Path, root: Path, spec: str) -> bool:
    try:
        (base / spec).resolve().relative_to(root.resolve())
        return False
    except ValueError:
        return True


def preview_isolation(project: Path) -> list[str]:
    """프리뷰 코드가 제품 코드·외부 경로를 참조하지 않는지, 제품 코드가 프리뷰를 참조하지 않는지 검사합니다."""
    errors: list[str] = []
    root = project / PREVIEW_DIR
    pkg_text = read_text(project, f"{PREVIEW_DIR}/package.json")
    try:
        pkg = json.loads(pkg_text) if pkg_text else {}
    except json.JSONDecodeError as e:
        errors.append(f"{PREVIEW_DIR}/package.json을 읽을 수 없습니다: {e}")
        pkg = {}
    deps = set((pkg.get("dependencies") or {})) | set((pkg.get("devDependencies") or {}))
    for sect in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        for name, ver in (pkg.get(sect) or {}).items():
            if isinstance(ver, str) and re.match(r"(file|link|workspace|portal):", ver):
                errors.append(f"{PREVIEW_DIR}/package.json: 로컬 경로 의존성은 금지됩니다 ({name}: {ver})")
    for name, cmd in (pkg.get("scripts") or {}).items():
        if isinstance(cmd, str) and ("../" in cmd or "frontend" in cmd):
            errors.append(f"{PREVIEW_DIR}/package.json scripts.{name}: 프리뷰 폴더 밖 경로를 참조합니다")
    for rel in preview_files(project):
        p = project / rel
        name = p.name
        is_config = name.startswith(("vite.config.", "vitest.config.")) or (name.startswith("tsconfig") and name.endswith(".json"))
        if not (rel.endswith(JS_EXT) or is_config or name == "index.html"):
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        code = raw if name == "index.html" else strip_js_comments(raw)
        if name == "index.html":
            code = re.sub(r"<!--.*?-->", "", code, flags=re.S)
            for m in re.finditer(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", code):
                v = m.group(1)
                if not re.match(r"(https?:|data:|#|mailto:)", v) and _escapes(root if v.startswith("/") else p.parent, root, v.lstrip("/")):
                    errors.append(f"{rel}: 프리뷰 폴더 밖을 참조합니다 ({v})")
            continue
        if is_config:
            # 설정 파일: 경로처럼 보이는 모든 문자열(alias, paths, baseUrl, extends, fs.allow, envDir 등)이 프리뷰 폴더 안에 있어야 함
            for m in re.finditer(STRING_LIT, code):
                v = m.group(2)
                if "frontend" in v:
                    errors.append(f"{rel}: 제품 코드(frontend) 경로를 참조합니다 ({v})")
                elif v.startswith("/@fs"):
                    errors.append(f"{rel}: 파일 시스템 직접 참조는 금지됩니다 ({v})")
                elif (v == ".." or v.startswith("../") or "/../" in v) and _escapes(p.parent, root, v):
                    errors.append(f"{rel}: 프리뷰 폴더 밖 경로를 참조합니다 ({v})")
                elif v.startswith("/") and len(v) > 1 and Path(v).exists() and _escapes(Path("/"), root, v):
                    errors.append(f"{rel}: 프리뷰 폴더 밖 절대 경로를 참조합니다 ({v})")
            if not rel.endswith(JS_EXT):
                continue
        for pat, why in FORBIDDEN_PREVIEW_PATTERNS:
            if re.search(pat, code):
                errors.append(f"{rel}: {why}는 프리뷰에서 금지됩니다")
        specs, dynamic = module_specifiers(code)
        for d in dynamic:
            errors.append(f"{rel}: 정적으로 확인할 수 없는 동적 참조입니다 ({d.strip()})")
        for s in specs:
            if re.match(r"(https?:|data:|blob:)", s):
                continue
            if s.startswith("/@fs") or s.startswith("file:"):
                errors.append(f"{rel}: 파일 시스템 직접 참조는 금지됩니다 ({s})")
            elif s.startswith("."):
                if _escapes(p.parent, root, s):
                    errors.append(f"{rel}: 프리뷰 폴더 밖 모듈을 참조합니다 ({s})")
            elif s.startswith("/"):
                if _escapes(root, root, s.lstrip("/")):
                    errors.append(f"{rel}: 프리뷰 폴더 밖 모듈을 참조합니다 ({s})")
            else:
                pkgname = "/".join(s.split("/")[:2]) if s.startswith("@") else s.split("/")[0]
                if s.startswith("node:") or (is_config and pkgname in NODE_BUILTINS):
                    continue
                if pkgname not in deps:
                    errors.append(f"{rel}: package.json에 없는 모듈입니다 ({s}). 별칭(alias) 대신 상대 경로를 쓰세요")
    # 제품 코드 → 프리뷰 참조
    fe = project / "frontend"
    if fe.exists():
        for dirpath, dirnames, filenames in os.walk(fe):
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", "dist")]
            for fn in filenames:
                if fn.endswith(JS_EXT) or fn.startswith(("vite.config.", "tsconfig")) or fn in ("package.json", "index.html"):
                    fp = Path(dirpath) / fn
                    txt = fp.read_text(encoding="utf-8", errors="replace")
                    if fn.endswith(JS_EXT) or fn.startswith(("vite.config.", "tsconfig")):
                        txt = strip_js_comments(txt)
                    lits = [m.group(2) for m in re.finditer(STRING_LIT, txt)]
                    if any(PREVIEW_DIR in v for v in lits):
                        errors.append(f"{fp.relative_to(project)}: 제품 코드가 {PREVIEW_DIR}를 참조합니다")
    return errors


# ---------------------------------------------------------------- 해시·교차 검증
def stage_current_hashes(project: Path, stage: str) -> dict:
    out = {}
    for rel in ([DD_FILE] if stage == "design_direction" else STAGE_ARTIFACTS[stage]):
        p = project / rel
        out[rel] = sha256_file(p) if p.exists() else None
    if stage == "preview":
        out[PREVIEW_TREE_KEY] = preview_tree_hash(project)
    return out


def diff_hashes(recorded: dict, current: dict) -> list[str]:
    return [k for k, v in recorded.items() if current.get(k) != v]


# ---- v2 전용 해시: 프리뷰 의미 해시(구현 메모 제외)와 테마 파일 해시
SEM_ALGO = "sem-2"  # 의미 해시 알고리즘. 표시가 없거나 다른 기록은 의미 비교에 쓰지 않고 원본 해시로 비교합니다(보수적).
SEM_SAFE_SCRIPT = (".ts", ".js", ".mjs", ".cjs", ".mts", ".cts")


def _sem_script(text: str) -> str | None:
    """JSX가 없는 스크립트: 줄 전체 주석·빈 줄·줄 앞뒤 공백만 뺍니다. 템플릿 리터럴·줄 이음이 있으면 None(원본 사용)."""
    if "`" in text or re.search(r"\\[ \t]*$", text, re.M):
        return None
    out, in_block = [], False
    for line in text.splitlines():
        s = line.strip()
        if in_block:
            if "*/" in s:
                if s.endswith("*/") and s.count("*/") == 1:
                    in_block = False
                    continue
                return None  # 주석 뒤에 같은 줄 코드가 이어짐 → 원본
            continue
        if not s or s.startswith("//"):
            continue
        if s.startswith("/*"):
            if "*/" in s:
                if s.endswith("*/") and s.count("*/") == 1:
                    continue
                return None
            in_block = True
            continue
        out.append(s)
    return None if in_block else "\n".join(out)


def _sem_css(text: str) -> str | None:
    """CSS: 문자열은 그대로, 주석은 제거, 문자열 밖 공백은 한 칸. 따옴표 없는 url(…)이 있으면 None(원본 사용)."""
    if re.search(r"url\(\s*[^'\"\s)]", text, re.I):
        return None
    out: list[str] = []
    i, n, space = 0, len(text), False
    while i < n:
        c = text[i]
        if c in "'\"":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\n":
                    return None
                j += 2 if text[j] == "\\" else 1
            if space and out:
                out.append(" ")
            space = False
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                return None
            before = out[-1][-1:] if out else ""
            after = text[j + 2: j + 3]
            if not space and before and not before.isspace() and after and not after.isspace():
                out.append("\0")  # 주석이 두 토큰을 붙여 놓은 자리(a/**/b ≠ ab ≠ a b)
            i = j + 2
        elif c.isspace():
            space = True
            i += 1
        else:
            if space and out:
                out.append(" ")
            space = False
            out.append(c)
            i += 1
    return "".join(out)


def sem_normalize(rel: str, raw: bytes, md_referenced: bool = False) -> bytes | None:
    """의미 해시용 정규화(sem-2). None이면 의미 해시에서 제외(참조되지 않는 .md). 안전성이 입증되지 않은 형식은 원본 그대로."""
    low = rel.lower()
    if low.endswith(".md"):
        return raw if md_referenced else None
    if low.endswith(SEM_SAFE_SCRIPT) or low.endswith(".css"):
        text = raw.decode("utf-8", errors="strict") if raw else ""
        norm = _sem_css(text) if low.endswith(".css") else _sem_script(text)
        return raw if norm is None else norm.encode("utf-8")
    return raw  # .tsx·.jsx(JSX 글자·공백이 렌더에 영향), .html·.json·.svg 등


def preview_semantic_hash(project: Path) -> str | None:
    """의미 해시(sem-2): 렌더 결과에 영향이 없다고 입증된 차이(스크립트·CSS의 주석·공백, 참조되지 않는 .md)만 무시합니다."""
    files = preview_files(project)
    if not files:
        return None
    code_text = "\n".join((project / r).read_text(encoding="utf-8", errors="replace") for r in files if not r.lower().endswith(".md"))
    h = hashlib.sha256()
    for rel in files:
        try:
            norm = sem_normalize(rel, (project / rel).read_bytes(), Path(rel).name in code_text)
        except UnicodeDecodeError:
            norm = (project / rel).read_bytes()
        if norm is None:
            continue
        h.update(rel.encode() + b"\0" + sha256_bytes(norm).encode() + b"\n")
    return h.hexdigest()


def theme_hash(project: Path, st: dict) -> str | None:
    rel = (st.get("config") or {}).get("theme_file")
    if not rel:
        return None
    p = project / rel
    return sha256_file(p) if p.is_file() else "missing"


def preview_v2_hashes(project: Path, st: dict) -> dict:
    return {"semantic_tree_hash": preview_semantic_hash(project), "semantic_algo": SEM_ALGO, "theme_hash": theme_hash(project, st)}


def preview_record_changes(project: Path, st: dict, record: dict, kind: str) -> tuple[list[str], bool, list[str]]:
    """프리뷰 승인·제출 기록과 현재 파일 비교. 반환: (바뀐 키, 테마 변경 여부, 구현 메모만 바뀐 키).
    v1은 원본 해시 비교만 합니다(기존 동작)."""
    changed = diff_hashes(record["hashes"], stage_current_hashes(project, "preview"))
    if workflow_of(st) != "v2":
        return changed, False, []
    base = dict((st["stages"]["preview"].get("v2_baseline") or {}))
    if base.get("record") != kind or base.get("revision") != record.get("revision"):
        base = {}
    # 같은 알고리즘(sem-2)으로 기록된 의미 해시만 씁니다. 이전 기록은 다시 계산하지 않고 원본 해시로 비교합니다.
    sem = record.get("semantic_tree_hash") if record.get("semantic_algo") == SEM_ALGO else None
    if sem is None and base.get("semantic_algo") == SEM_ALGO:
        sem = base.get("semantic_tree_hash")
    impl_only = []
    if PREVIEW_TREE_KEY in changed and sem and preview_semantic_hash(project) == sem:
        changed.remove(PREVIEW_TREE_KEY)
        impl_only.append(PREVIEW_TREE_KEY)
    rec_theme = record["theme_hash"] if "theme_hash" in record else base.get("theme_hash")
    theme_changed = bool((st.get("config") or {}).get("theme_file")) and rec_theme != theme_hash(project, st)
    return changed, theme_changed, impl_only


def cross_verify(project: Path, st: dict) -> dict:
    problems: list[dict] = []
    warnings: list[str] = []
    v2 = workflow_of(st) == "v2"
    for stage in stage_list(st):
        s = st["stages"][stage]
        if stage not in IMPLEMENTED_STAGES:
            if s["status"] in ("in_progress", "awaiting_approval", "approved"):
                problems.append({"stage": stage, "kind": "unimplemented_stage_progressed", "paths": [],
                                 "message": "구현되지 않은 단계가 진행·승인 상태입니다(수동 편집 의심). 이 상태를 승인으로 인정하지 않습니다."})
            continue
        rec_key = {"approved": "approved", "awaiting_approval": "submitted"}.get(s["status"])
        if rec_key and not isinstance(s.get(rec_key), dict):
            problems.append({"stage": stage, "kind": "missing_record", "paths": [],
                             "message": f"{s['status']} 상태인데 {rec_key} 기록이 없습니다(수동 편집 의심). 승인으로 인정하지 않습니다."})
            continue
        cur = stage_current_hashes(project, stage)
        if v2 and stage == "preview" and s["status"] in ("approved", "awaiting_approval"):
            kind = "approved" if s["status"] == "approved" else "submitted"
            changed, theme_changed, impl_only = preview_record_changes(project, st, s[kind], kind)
            if changed:
                problems.append({"stage": stage, "kind": f"{kind}_modified", "paths": changed})
            if theme_changed:
                problems.append({"stage": stage, "kind": "theme_changed", "paths": [st["config"]["theme_file"]],
                                 "message": "테마 값이 바뀌어 프리뷰 렌더 결과가 승인 때와 다릅니다. UX Spec·Design Direction 승인은 유지되고, 프리뷰만 다시 검증·승인합니다(reopen --stage preview)."})
            if impl_only:
                warnings.append("프리뷰에서 주석·공백·문서만 바뀌었습니다(구현 메모). v2 규칙상 재승인이 필요하지 않습니다.")
            continue
        if s["status"] == "approved":
            changed = diff_hashes(s["approved"]["hashes"], cur)
            if changed:
                problems.append({"stage": stage, "kind": "approved_modified", "paths": changed})
        elif s["status"] == "awaiting_approval":
            changed = diff_hashes(s["submitted"]["hashes"], cur)
            if changed:
                problems.append({"stage": stage, "kind": "submitted_modified", "paths": changed})
        elif s["status"] == "in_progress":
            for rel, h in s.get("artifacts_done", {}).items():
                if cur.get(rel) is None:
                    problems.append({"stage": stage, "kind": "missing", "paths": [rel]})
                elif cur.get(rel) != h:
                    warnings.append(f"{rel}: done 기록 이후 변경되었습니다(작성 중 수정이면 done을 다시 실행)")
    pv = st["stages"]["preview"]
    ux = st["stages"]["ux_spec"]
    # 구조 의존(ux_spec)만 봅니다. design_direction 게이트는 begin·submit·approve에서 확인합니다(진행 중인 작업을 갑자기 막지 않음).
    if pv["status"] in ("in_progress", "awaiting_approval", "approved") and any(st["stages"][d]["status"] != "approved" for d in active_deps(st, "preview") if d != "design_direction"):
        problems.append({"stage": "preview", "kind": "upstream_not_approved", "paths": []})
    if pv["status"] == "approved" and (pv.get("based_on_ux_spec_revision") != (ux.get("approved") or {}).get("revision")
                                       or pv["approved"].get("ux_spec_hashes") != (ux.get("approved") or {}).get("hashes")):
        problems.append({"stage": "preview", "kind": "stale_preview", "paths": [PREVIEW_MANIFEST]})
    if v2 and gate_on(st) and pv["status"] == "approved" and isinstance(pv.get("approved"), dict) \
            and "design_direction_revision" in pv["approved"] \
            and pv["approved"]["design_direction_revision"] != (st["stages"]["design_direction"].get("approved") or {}).get("revision"):
        problems.append({"stage": "preview", "kind": "stale_preview", "paths": [DD_FILE],
                         "message": "승인된 프리뷰가 현재 승인된 Design Direction revision을 기준으로 하지 않습니다."})
    if v2:
        dd = st["stages"]["design_direction"]
        if dd["status"] == "approved" and isinstance(dd.get("approved"), dict) and \
                dd["approved"].get("ux_spec_hashes") != (ux.get("approved") or {}).get("hashes"):
            problems.append({"stage": "design_direction", "kind": "stale_design_direction", "paths": [DD_FILE],
                             "message": "승인된 Design Direction이 현재 승인된 UX 설계를 기준으로 하지 않습니다."})
    known = set(STAGE_ARTIFACTS["ux_planning"]) | set(SPEC_FILES) | {REVIEW_FILE}
    if v2:
        known.add(DD_FILE)
    ddir = project / DESIGN_DIR
    if ddir.exists():
        for p in sorted(ddir.rglob("*")):
            rel = str(p.relative_to(project))
            if p.is_file() and rel not in known and p.name != ".DS_Store":
                warnings.append(f"{rel}: /product-design이 관리하지 않는 파일입니다")
    return {"consistent": not problems, "problems": problems, "warnings": warnings}


def counted_stages(st: dict) -> list:
    """전체 상태·다음 행동에 넣는 단계. 게이트가 꺼진 v2에서 design_direction은 시작했을 때만 셉니다(선택 단계)."""
    out = []
    for k in stage_list(st):
        if k == "design_direction" and not gate_on(st) and st["stages"][k]["status"] in ("locked", "not_started"):
            continue
        out.append(k)
    return out


def overall_status(st: dict) -> str:
    if st.get("validity", {}).get("status") == "outdated":
        return "outdated"
    order = counted_stages(st)
    s = {k: st["stages"][k]["status"] for k in order}
    if all(v == "approved" for v in s.values()):
        return "approved"
    for k in order:
        if s[k] != "approved":
            return f"{k}:{s[k]}"
    return "unknown"


def next_action(st: dict) -> str:
    if st.get("validity", {}).get("status") == "outdated":
        return "planning이 바뀌었습니다. impact로 영향을 확인하고, 사용자 확인 후 rebase로 재검토를 시작합니다."
    for k in counted_stages(st):
        s = st["stages"][k]["status"]
        if s == "approved":
            continue
        if s == "not_started":
            return f"{STAGE_LABEL[k]} 시작(begin --stage {k})"
        if s == "in_progress":
            if k == "ux_planning":
                return "UX Planning 인터뷰를 이어서 진행합니다(design-notes.md의 마지막 라운드 확인)."
            if k == "ux_spec":
                st_ = st["stages"][k]
                if not st_.get("structure_confirmed"):
                    return "IA·화면 목록 작성 → trace --stage structure → 구조 확인 요청"
                if st_["structure_confirmed"].get("revision") != st_["revision"] + 1:
                    return "수정 반영 중. 화면 구성(IA 라우트·화면 ID)이 이전 구조 확인과 같으면 구조 확인을 이어받고, 달라지면 다시 구조 확인을 받습니다."
                return "상세 명세·흐름·컴포넌트·추적성 작성 → trace --stage ux_spec → submit"
            if k == "design_direction":
                return "07 디자인 방향 작성(VD·정책·렌더 범위·변경 요청) → trace --stage design_direction → done → submit"
            return "프리뷰 작성·수정 → preview-verify → 화면별 피드백 → submit"
        if s == "awaiting_approval":
            return f"{STAGE_LABEL[k]} r{st['stages'][k]['revision']}에 대한 명시적 승인을 기다립니다."
        if s == "locked":
            return f"{STAGE_LABEL[k]}는 앞 단계 승인 전까지 잠겨 있습니다."
    return "디자인 단계가 모두 승인되었습니다. 결과를 검토한 뒤 커밋하세요."


DISPLAY_NOTE = ("state.yaml의 design 항목(not_started)은 /product-start가 기록한 '기획 승인으로 디자인 단계가 열림' 표시입니다. "
                "디자인 진행·승인 상태의 기준은 .ai-workflow/design.json입니다. /product-start는 이 파일을 쓰지 않습니다.")


# ---------------------------------------------------------------- 명령
def gate_or_block(project: Path) -> dict:
    pf = preflight(project)
    if not pf["ok"]:
        block(pf["error"], pf["message"])
    gate = read_gate(project)
    if not gate["ok"]:
        block(gate["error"], gate["message"], gate=gate,
              hint="기획 문서와 state.yaml은 수정하지 않았습니다. /product-start로 기획 승인 상태를 먼저 정리하세요. 디자인 문서는 보존됩니다.")
    return {"preflight": pf, "gate": gate}


def detect_outdated(project: Path, st: dict, gate: dict) -> list[str]:
    changed = [f for f, h in st["based_on"]["planning_hashes"].items() if gate["planning_hashes"].get(f) != h]
    if changed and st.get("validity", {}).get("status") != "outdated":
        st["validity"] = {"status": "outdated", "reason": "planning 승인 해시가 디자인 기준과 다릅니다", "changed": changed, "detected_at": now()}
        add_history(st, "design", "outdated", None, f"planning 변경 감지: {', '.join(changed)}")
        save_state(project, st)
    return changed


def existing_design_paths(project: Path) -> list[str]:
    """start 전에 이미 있으면 안 되는 경로(파일이거나 비어 있지 않은 디렉터리)."""
    out = []
    for p in (DESIGN_DIR, PREVIEW_DIR, NOTES_REL):
        pp = project / p
        if pp.exists() and (pp.is_file() or any(pp.iterdir())):
            out.append(p)
    return out


def new_stage(status: str, artifacts: list[str]) -> dict:
    return {"status": status, "revision": 0, "artifacts": artifacts, "artifacts_done": {}, "submitted": None, "approved": None}


def require_dd_gate(st: dict, action: str) -> None:
    """design_direction 게이트가 켜진 프로젝트에서 preview 제출·승인 전에 Design Direction 승인을 확인합니다."""
    if not gate_on(st):
        return
    dd = st["stages"]["design_direction"]
    if dd["status"] != "approved":
        block("design_direction_not_approved", f"design_direction 게이트가 켜져 있어 프리뷰 {action} 전에 Design Direction 승인이 필요합니다 "
              f"(현재: {dd['status']}). 기존 프리뷰 기록은 그대로 둡니다.")


def dd_binding(st: dict) -> dict:
    dd = st["stages"]["design_direction"]["approved"]
    return {"design_direction_revision": dd["revision"], "design_direction_hashes": dd["hashes"]}


def require_valid(project: Path, st: dict, stage: str) -> dict:
    """상태를 바꾸는 모든 명령의 공통 게이트입니다(check 실행 여부와 무관).

    1) planning 승인·해시(state.yaml) 2) 디자인 기준(based_on)과 planning 일치
    3) 대상 단계보다 앞선 단계의 교차 검증(승인·제출 후 변경, 누락, 프리뷰 기준 불일치)
    같은 단계의 문제는 reopen으로 풀어야 하므로 여기서 막지 않고, 각 명령이 자체 검사합니다.
    """
    ctx = gate_or_block(project)
    changed = detect_outdated(project, st, ctx["gate"])
    if changed:
        block("design_outdated", "planning이 바뀌어 진행할 수 없습니다. impact → rebase 순서로 진행하세요.", changed=changed)
    cv = cross_verify(project, st)
    ups = upstream_of(st, stage)
    upstream = [p for p in cv["problems"] if p["stage"] in ups
                or (p["stage"] == "preview" and p["kind"] in ("upstream_not_approved", "stale_preview") and stage == "preview")]
    if upstream:
        block("upstream_modified", f"{STAGE_LABEL[stage]}보다 앞선 단계의 승인 산출물이 바뀌었거나 상태가 맞지 않습니다. "
              "자동으로 다시 승인하지 않습니다. 앞 단계를 재검토(reopen)하거나 파일을 복원하세요.", problems=upstream)
    return ctx


def stage_of(rel: str, st: dict | None = None) -> str | None:
    if st is not None and workflow_of(st) == "v2" and rel == DD_FILE:
        return "design_direction"
    for k, arts in STAGE_ARTIFACTS.items():
        if rel in arts:
            return k
    return None


def invalidate_downstream(st: dict, stage: str, reason: str) -> list[str]:
    affected = []
    for k in dependents_of(st, stage):
        d = st["stages"][k]
        if d["status"] == "locked":
            continue
        if d.get("approved"):
            d["last_approved"] = d["approved"]
        d["approved"] = None
        d["submitted"] = None
        d["status"] = "locked"
        d["artifacts_done"] = {}
        if k == "ux_spec":
            d["structure_confirmed"] = None
        affected.append(k)
        add_history(st, k, "invalidated", d["revision"], reason)
    return affected


# ---------------------------------------------------------------- Design Direction(07) 검증(WF-D02)
VD_STATUSES = ("승인", "후보", "미결정", "제외")
CR_CATEGORIES = {"①": "info_behavior", "②": "token_semantics", "③": "theme_value", "④": "visual", "⑤": "implementation",
                 "info_behavior": "info_behavior", "token_semantics": "token_semantics", "theme_value": "theme_value",
                 "visual": "visual", "implementation": "implementation", "conditional": "conditional", "needs_review": "needs_review"}
CR_STATUSES = ("미결", "반영", "기각", "UX Spec 개정 요청")
RENDERERS = ("code", "figma", "both")
DD_POLICIES = ("density", "touch.min", "safe_area")
DD_SECTIONS = ("입력", "디자인 방향", "시각 결정", "정책 값", "렌더링 경로", "렌더 범위", "UX Spec과의 차이", "검증 기준")


def md_section(text: str, keyword: str) -> str:
    m = re.search(rf"^## [^\n]*{re.escape(keyword)}[^\n]*$", text, re.M)
    if not m:
        return ""
    nxt = re.compile(r"^## ", re.M).search(text, m.end())
    return text[m.end(): nxt.start() if nxt else len(text)]


def _first_word(v: str) -> str:
    return re.split(r"[\s(]", v.strip(), 1)[0] if v.strip() else ""


def dd_vds(project: Path) -> dict[str, str]:
    """07 문서의 VD와 상태(첫 낱말)."""
    text = strip_fences(read_text(project, DD_FILE))
    return {k: _first_word(field_line(b, "상태")) for k, b in blocks_by_heading(text, 3, "VD").items()}


def trace_design_direction(project: Path, st: dict) -> dict:
    errors, warnings = [], []
    raw_text = read_text(project, DD_FILE)
    text = strip_fences(raw_text)
    if not text.strip():
        return {"ok": False, "errors": [f"{DD_FILE}이 없습니다"], "warnings": []}
    ux = st["stages"]["ux_spec"]
    ux_rev = (ux.get("approved") or {}).get("revision")
    if ux["status"] != "approved":
        errors.append("UX 설계가 승인되지 않았습니다. Design Direction은 승인된 UX 설계를 기준으로만 씁니다.")
    heads = re.findall(r"^## (.+)$", text, re.M)
    for sec in DD_SECTIONS:
        if not any(sec in h for h in heads):
            errors.append(f"'{sec}' 섹션(## …{sec}…)이 없습니다")
    m = re.search(r"^\s*ux_spec_revision:\s*(\d+)", raw_text.split("\n---", 1)[0] if raw_text.startswith("---") else "", re.M)
    if not m or int(m.group(1)) != ux_rev:
        errors.append(f"front matter based_on.ux_spec_revision이 승인된 UX 설계 r{ux_rev}와 다릅니다")
    inp = md_section(text, "입력")
    if f"r{ux_rev}" not in field_line(inp, "UX 설계 기준"):
        errors.append(f"입력의 'UX 설계 기준'에 승인된 r{ux_rev}를 적어야 합니다")
    for label in ("디자인 프로필", "브랜드·시각 방향", "컴포넌트·토큰 매핑", "규칙 출처"):
        if not field_line(inp, label):
            errors.append(f"입력의 '{label}'이 비어 있습니다(없으면 '없음(사유)')")
    renderer = _first_word(field_line(md_section(text, "렌더링 경로"), "렌더러"))
    if renderer not in RENDERERS:
        errors.append(f"렌더러는 {'/'.join(RENDERERS)} 중 하나여야 합니다 (현재: '{renderer}')")
    ctx = design_context(project)
    scr = screen_info(project)
    vds = blocks_by_heading(md_section(text, "시각 결정"), 3, "VD")
    status: dict[str, str] = {}
    if not vds:
        errors.append("시각 결정(### VD-###)이 없습니다")
    for k, b in vds.items():
        s = _first_word(field_line(b, "상태"))
        status[k] = s
        if s not in VD_STATUSES:
            errors.append(f"{k}: 상태는 {'/'.join(VD_STATUSES)} 중 하나여야 합니다 (현재: '{s}')")
        elif s in ("후보", "미결정"):
            errors.append(f"{k}: 승인되지 않은 VD({s})가 남아 있습니다. 제출 전에 승인 또는 제외로 결정하세요")
        for ref in [x.strip().strip("`") for x in field_line(b, "관련").split(",") if x.strip()]:
            if re.fullmatch(DESIGN_ID_RE.replace(r"\b", ""), ref) or re.fullmatch(ID_RE, ref):
                if not _ref_exists(ctx, ref):
                    errors.append(f"{k}: 승인 문서에 없는 참조 {ref}")
            elif TOKEN_NAME_RE.match(ref):
                if ref not in ctx["tokens"]:
                    errors.append(f"{k}: 04에 없는 토큰 {ref} — 새 의미 토큰은 변경 요청(②, UX Spec)으로 다루세요")
        if field_line(b, "토큰 밖 값").startswith("있음"):
            warnings.append(f"{k}: 승인 토큰 밖 값이 있습니다(토큰 추가는 ②, 값은 테마로)")
    pol = table_rows(md_section(text, "정책 값"), r"density|touch\.min|safe_area")
    for key in DD_POLICIES:
        if key not in pol or not (pol[key][0] if pol[key] else ""):
            errors.append(f"정책 값 '{key}'가 없습니다(프로젝트가 정한 값, 해당 없으면 '해당 없음(사유)')")
    rows = table_rows(md_section(text, "렌더 범위"), r"SCR-\d{3}")
    if not rows:
        errors.append("렌더 범위(화면·상태 표)가 없습니다")
    render_states = 0
    for sid, cols in rows.items():
        if sid not in scr:
            errors.append(f"렌더 범위: {SCREENS_FILE}에 없는 화면 {sid}")
            continue
        sts = re.findall(r"SCR-\d{3}-ST\d+", cols[0] if cols else "")
        render_states += len(sts)
        for x in sts:
            if x not in scr[sid]["states"]:
                errors.append(f"렌더 범위 {sid}: {SCREENS_FILE}에 없는 상태 {x}")
        for v in re.findall(r"VD-\d{3}", " ".join(cols[1:])):
            if v not in status:
                errors.append(f"렌더 범위 {sid}: 정의되지 않은 {v}")
            elif status[v] != "승인":
                errors.append(f"렌더 범위 {sid}: 승인되지 않은 {v}({status[v]})를 렌더에 쓸 수 없습니다")
    missing_scr = sorted(set(scr) - set(rows))
    if missing_scr:
        warnings.append(f"렌더 범위에 없는 화면 {len(missing_scr)}개: {', '.join(missing_scr[:8])}")
    crs = blocks_by_heading(md_section(text, "UX Spec과의 차이"), 3, "CR")
    for k, b in crs.items():
        cat = CR_CATEGORIES.get(_first_word(field_line(b, "분류")))
        s = field_line(b, "상태").strip()
        s0 = next((x for x in CR_STATUSES if s.startswith(x)), None)
        if cat is None:
            errors.append(f"{k}: 분류는 ①–⑤, conditional, needs_review 중 하나여야 합니다")
        if s0 is None:
            errors.append(f"{k}: 상태는 {'/'.join(CR_STATUSES)} 중 하나여야 합니다")
        if cat in ("info_behavior", "token_semantics") and s0 != "기각":
            errors.append(f"{k}: ①·②(UX Spec) 변경 요청이 남아 있습니다. reopen --stage ux_spec으로 UX 설계를 개정한 뒤 반영하거나 기각하세요")
        if cat in ("conditional", "needs_review") and s0 == "미결":
            errors.append(f"{k}: 분류가 확정되지 않은 변경 요청입니다. 사용자 판단으로 분류를 정하세요")
    counts = {"VD": len(vds), "VD_approved": sum(1 for s in status.values() if s == "승인"),
              "VD_excluded": sum(1 for s in status.values() if s == "제외"), "render_screens": len(rows),
              "render_states": render_states, "CR": len(crs), "renderer": renderer}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts}
TOKEN_NAME_RE = re.compile(r"^[a-z][A-Za-z]*(?:\.[A-Za-z0-9]+)+$")
DESIGN_ID_RE = r"\b(?:SCR-\d{3}(?:-ST\d+)?|CMP-\d{3}|UXD-\d{3})\b"


def parse_tokens(text: str) -> dict[str, str]:
    """04 문서의 토큰 표(첫 열 머리글 '토큰')를 {이름: 값}으로 읽습니다. `a.b.c / d / e` 묶음 행은 펼칩니다."""
    out: dict[str, str] = {}
    in_table = False
    for line in strip_fences(text).splitlines():
        if not line.lstrip().startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        if cells[0].lower() in ("토큰", "token"):
            in_table = True
            continue
        if not in_table or set(cells[0]) <= set("-: "):
            continue
        names = [n.strip().strip("`") for n in cells[0].split("/")]
        if not TOKEN_NAME_RE.match(names[0]):
            continue
        prefix = names[0].rsplit(".", 1)[0]
        full = [names[0]] + [f"{prefix}.{n}" for n in names[1:] if n]
        value = cells[1] if len(cells) > 1 else ""
        vals = [v.strip() for v in value.split(" / ")]
        unit = re.fullmatch(r"-?\d+(?:\.\d+)?([a-z%]+)", vals[-1]) if vals else None
        if unit and len(vals) > 1:  # '13 / 16 / 32px'처럼 마지막 값에만 단위가 있으면 앞 값에도 붙여 해석
            vals = [v + unit.group(1) if re.fullmatch(r"-?\d+(?:\.\d+)?", v) else v for v in vals]
        if len(vals) == len(full):
            out.update(zip(full, vals))
        else:
            out.update({n: value for n in full})
    return out


def parse_css_vars(text: str) -> dict[str, str]:
    code = strip_js_comments(text)
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}]+)", code)}


def design_context(project: Path) -> dict:
    uxp = strip_comments(read_text(project, UXP_FILE))
    uisys = read_text(project, UISYS_FILE)
    return {"tokens": parse_tokens(uisys), "screens": set(screen_info(project)),
            "cmps": set(blocks_by_heading(strip_fences(uisys), 3, "CMP")),
            "uxds": set(blocks_by_heading(uxp, 3, "UXD")), "pid": planning_ids(project)}


def _ref_exists(ctx: dict, ref: str) -> bool:
    if re.fullmatch(r"SCR-\d{3}-ST\d+", ref):
        return ref.rsplit("-ST", 1)[0] in ctx["screens"]
    if ref.startswith("SCR-"):
        return ref in ctx["screens"]
    if ref.startswith("CMP-"):
        return ref in ctx["cmps"]
    if ref.startswith("UXD-"):
        return ref in ctx["uxds"]
    if re.fullmatch(ID_RE, ref):
        return id_exists(ctx["pid"], ref)
    return False


def workflow_info(st: dict) -> dict:
    wf = workflow_of(st)
    order = stage_list(st)
    return {"version": wf, "stages": list(order), "implemented": [k for k in order if k in IMPLEMENTED_STAGES],
            "not_implemented": [k for k in order if k not in IMPLEMENTED_STAGES],
            "dependencies": {k: list(v) for k, v in STAGE_DEPS[wf].items()},
            "deferred_dependencies": {k: list(deferred_deps(st, k)) for k in order if deferred_deps(st, k)},
            "gates": {g: gate_on(st, g) for g in GATES} if wf == "v2" else {},
            "preview_pre_gate_approval": bool(wf == "v2" and gate_on(st) and st["stages"]["preview"]["status"] == "approved"
                                              and "design_direction_revision" not in (st["stages"]["preview"].get("approved") or {})),
            "theme_file": (st.get("config") or {}).get("theme_file")}


def _theme_path_ok(project: Path, rel: str) -> str:
    if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        block("invalid_theme_file", "테마 파일은 프로젝트 기준 상대 경로여야 합니다('..', 절대 경로 불가).", path=rel)
    p = (project / rel).resolve()
    try:
        norm = str(p.relative_to(project))
    except ValueError:
        block("invalid_theme_file", "테마 파일이 프로젝트 밖을 가리킵니다.", path=rel)
    protected = set(STAGE_ARTIFACTS["ux_planning"]) | set(SPEC_FILES) | {REVIEW_FILE, DD_FILE}
    if norm in protected or norm.startswith(("docs/planning/", ".ai-workflow/", ".git/")):
        block("invalid_theme_file", "승인 산출물·기획 문서·상태 폴더는 테마 파일로 쓸 수 없습니다.", path=norm)
    if not p.is_file():
        block("invalid_theme_file", "테마 파일이 없습니다. 파일을 만든 뒤 다시 실행하세요.", path=norm)
    return norm


def _preserved(orig: dict, new: dict) -> list[str]:
    """v1에서 있던 필드가 전환 뒤에도 그대로인지 확인합니다(추가만 허용). 달라진 경로 목록을 반환합니다."""
    diffs = []
    for k, v in orig.items():
        if k in ("updated_at", "history", "config", "stages"):
            continue
        if new.get(k) != v:
            diffs.append(k)
    for sk, sv in (orig.get("stages") or {}).items():
        ns = (new.get("stages") or {}).get(sk) or {}
        for kk, vv in sv.items():
            if ns.get(kk) != vv:
                diffs.append(f"stages.{sk}.{kk}")
    oh = orig.get("history") or []
    if (new.get("history") or [])[:len(oh)] != oh:
        diffs.append("history")
    for kk, vv in (orig.get("config") or {}).items():
        if kk != "workflow" and (new.get("config") or {}).get(kk) != vv:
            diffs.append(f"config.{kk}")
    return diffs


__all__ = [
    'ALL_STAGES',
    'CLEAN_CHECK_IGNORED_PREFIXES',
    'CONFIRMED_RE',
    'CR_CATEGORIES',
    'CR_STATUSES',
    'DD_FILE',
    'DD_POLICIES',
    'DD_SECTIONS',
    'DESIGN_DIR',
    'DESIGN_ID_RE',
    'DISCOVERY_FILE',
    'DISPLAY_NOTE',
    'FLOWS_FILE',
    'FORBIDDEN_PREVIEW_PATTERNS',
    'GATES',
    'IA_FILE',
    'ID_RE',
    'IMPLEMENTED_STAGES',
    'JS_EXT',
    'NEXT_STAGE',
    'NODE_BUILTINS',
    'NOTES_REL',
    'PLANNING_FILES',
    'PLATFORMS',
    'PREVIEW_DIR',
    'PREVIEW_EXCLUDE_DIRS',
    'PREVIEW_EXCLUDE_SUFFIX',
    'PREVIEW_MANIFEST',
    'PREVIEW_SEMANTIC_KEY',
    'PREVIEW_TREE_KEY',
    'RENDERERS',
    'REVIEW_FILE',
    'ROUND_STATUSES',
    'RQ_RE',
    'SCREENS_FILE',
    'SEM_ALGO',
    'SEM_SAFE_SCRIPT',
    'SPEC_FILES',
    'STAGES',
    'STAGES_BY_WORKFLOW',
    'STAGE_ARTIFACTS',
    'STAGE_DEPS',
    'STAGE_LABEL',
    'STANDARD_STATES',
    'STATE_REL',
    'STRING_LIT',
    'THEME_KEY',
    'TOKEN_NAME_RE',
    'TRACE_FILE',
    'UISYS_FILE',
    'UXD_STATUSES',
    'UXP_FILE',
    'VD_STATUSES',
    'WORKFLOWS',
    'WORKFLOW_STATE_REL',
    '_escapes',
    '_field',
    '_first_word',
    '_preserved',
    '_ref_exists',
    '_sem_css',
    '_sem_script',
    '_stage_block',
    '_theme_path_ok',
    'active_deps',
    'add_history',
    'block',
    'blocks_by_heading',
    'counted_stages',
    'cross_verify',
    'dd_binding',
    'dd_vds',
    'deferred_deps',
    'dependents_of',
    'design_context',
    'detect_outdated',
    'diff_hashes',
    'emit',
    'existing_design_paths',
    'field_line',
    'front_matter_revision',
    'gate_on',
    'gate_or_block',
    'git',
    'git_dirty_paths',
    'id_exists',
    'implemented_deps',
    'invalidate_downstream',
    'load_state',
    'md_section',
    'module_specifiers',
    'new_stage',
    'next_action',
    'now',
    'overall_status',
    'parse_css_vars',
    'parse_rounds',
    'parse_tokens',
    'pending_round',
    'planning_ids',
    'preflight',
    'preview_files',
    'preview_isolation',
    'preview_record_changes',
    'preview_semantic_hash',
    'preview_tree_hash',
    'preview_v2_hashes',
    'read_gate',
    'read_text',
    'require_dd_gate',
    'require_stage_usable',
    'require_state',
    'require_valid',
    'run',
    'save_state',
    'screen_info',
    'sem_normalize',
    'sha256_bytes',
    'sha256_file',
    'stage_artifacts',
    'stage_current_hashes',
    'stage_list',
    'stage_of',
    'state_shape_problems',
    'strip_comments',
    'strip_fences',
    'strip_js_comments',
    'structure_signature',
    'table_rows',
    'theme_hash',
    'trace_design_direction',
    'trace_structure',
    'trace_ux_planning',
    'trace_ux_spec',
    'upstream_of',
    'workflow_info',
    'workflow_of',
]
