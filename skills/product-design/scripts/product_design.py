#!/usr/bin/env python3
"""/product-design 결정적 보조 스크립트 (Python 3.11+, 표준 라이브러리만 사용).

LLM은 인터뷰, 문서 작성, 프리뷰 화면 작성만 맡습니다. 게이트, 상태 전이, 승인, 해시, 추적성, 프리뷰 경계 판정은
모두 이 스크립트가 수행합니다. `.ai-workflow/design.json`은 이 스크립트만 씁니다.

하위 명령:
  check      사전 점검 + planning 게이트 + 상태·파일 교차 검증 + 다음 행동 안내
  start      design.json 생성(planning 승인·해시 기준 기록). 문서는 만들지 않음
  begin      단계 시작(ux_spec / preview). 앞 단계가 승인되어 있어야 함
  done       작성을 마친 산출물의 해시 기록(front matter revision 검사)
  trace      ID 존재·커버리지·구조 검사 (--stage ux_planning | structure | ux_spec)
  checkpoint UX 설계 구조 확인 기록(IA + 화면 목록)
  submit     단계 제출(revision +1, 제시한 해시 기록)
  approve    사용자가 명시적으로 승인한 revision 기록(제출 후 변경되었으면 거부)
  pending    design-notes.md의 답변 대기 질문 라운드와 형식 오류
  reopen     승인·제출된 단계를 다시 엶(하위 단계 승인 무효화)
  impact     planning 변경 영향(바뀐 ID와 이를 참조하는 UXD/SCR)
  rebase     planning 재승인 후 새 기준으로 디자인 재검토 시작
  refs       ID를 참조하는 디자인 문서 위치
  backup     기존 디자인 파일 수정 전 백업 필요 여부 판단·백업
  preview-scaffold  프리뷰 템플릿 복사(design-preview/)
  preview-check     프리뷰 manifest·경계 검사(빌드 없음)
  preview-verify    preview-check + pnpm install + pnpm build, 결과 기록
  status     상태 요약(/product-start 상태 표시와의 관계 포함)

모든 출력은 JSON이며, 차단·실패 시 종료 코드 2를 반환합니다.
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
    for probe in ("node_modules", "dist"):
        rc = subprocess.run(["git", "-C", str(project), "check-ignore", "-q", f"{PREVIEW_DIR}/{probe}/.probe"]).returncode
        if rc != 0:
            errors.append(f"{PREVIEW_DIR}/{probe}가 Git에서 무시되지 않습니다")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "counts": {"screens_in_spec": len(scr), "screens_in_preview": len([s for s in screens if not (screens[s] or {}).get('skip')]),
                       "states_in_preview": sum(len((v or {}).get("states", [])) for v in screens.values())}}


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
    for rel in STAGE_ARTIFACTS[stage]:
        p = project / rel
        out[rel] = sha256_file(p) if p.exists() else None
    if stage == "preview":
        out[PREVIEW_TREE_KEY] = preview_tree_hash(project)
    return out


def diff_hashes(recorded: dict, current: dict) -> list[str]:
    return [k for k, v in recorded.items() if current.get(k) != v]


def cross_verify(project: Path, st: dict) -> dict:
    problems: list[dict] = []
    warnings: list[str] = []
    for stage in STAGES:
        s = st["stages"][stage]
        cur = stage_current_hashes(project, stage)
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
    if pv["status"] in ("in_progress", "awaiting_approval", "approved") and ux["status"] != "approved":
        problems.append({"stage": "preview", "kind": "upstream_not_approved", "paths": []})
    if pv["status"] == "approved" and (pv.get("based_on_ux_spec_revision") != (ux.get("approved") or {}).get("revision")
                                       or pv["approved"].get("ux_spec_hashes") != (ux.get("approved") or {}).get("hashes")):
        problems.append({"stage": "preview", "kind": "stale_preview", "paths": [PREVIEW_MANIFEST]})
    known = set(STAGE_ARTIFACTS["ux_planning"]) | set(SPEC_FILES) | {REVIEW_FILE}
    ddir = project / DESIGN_DIR
    if ddir.exists():
        for p in sorted(ddir.rglob("*")):
            rel = str(p.relative_to(project))
            if p.is_file() and rel not in known and p.name != ".DS_Store":
                warnings.append(f"{rel}: /product-design이 관리하지 않는 파일입니다")
    return {"consistent": not problems, "problems": problems, "warnings": warnings}


def overall_status(st: dict) -> str:
    if st.get("validity", {}).get("status") == "outdated":
        return "outdated"
    s = {k: st["stages"][k]["status"] for k in STAGES}
    if all(v == "approved" for v in s.values()):
        return "approved"
    for k in STAGES:
        if s[k] != "approved":
            return f"{k}:{s[k]}"
    return "unknown"


def next_action(st: dict) -> str:
    if st.get("validity", {}).get("status") == "outdated":
        return "planning이 바뀌었습니다. impact로 영향을 확인하고, 사용자 확인 후 rebase로 재검토를 시작합니다."
    for k in STAGES:
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


def cmd_check(a) -> None:
    project = Path(a.project).resolve()
    ctx = gate_or_block(project)
    st = load_state(project)
    if st is None:
        conflicts = existing_design_paths(project)
        emit({"ok": True, "status": "not_started", "preflight": ctx["preflight"], "gate": ctx["gate"],
              "existing_paths": conflicts, "next": "start" if not conflicts else "기존 파일이 있어 시작할 수 없습니다. 보고 후 사용자 결정을 기다립니다.",
              "display_note": DISPLAY_NOTE})
    changed = detect_outdated(project, st, ctx["gate"])
    if changed:
        block("design_outdated", "planning이 디자인 기준 이후 다시 승인되었습니다. 디자인 승인은 모두 무효입니다.", changed=changed,
              next="impact로 영향 범위를 확인하고, 사용자 확인 후 rebase --confirm")
    cv = cross_verify(project, st)
    out = {"ok": cv["consistent"], "status": overall_status(st), "stages": {k: {"status": v["status"], "revision": v["revision"]} for k, v in st["stages"].items()},
           "cross_verify": cv, "preflight": ctx["preflight"], "next": next_action(st), "display_note": DISPLAY_NOTE}
    if st["stages"]["ux_planning"]["status"] == "in_progress":
        pr = pending_round(project)
        out["pending_round"] = pr["pending"]
        out["last_round"] = pr["last_round"]
        if pr["errors"]:
            out["pending_errors"] = pr["errors"]
        if pr["pending"]:
            out["next"] = f"답변 대기 중인 라운드 {pr['pending']['round']}의 질문을 기록된 그대로 다시 보여 주고 답을 기다립니다(새로 만들지 않음)."
    if not cv["consistent"]:
        out.update(error="state_mismatch", message="상태 파일과 실제 파일이 다릅니다. 자동으로 고치거나 다시 승인하지 않습니다.")
        emit(out, 2)
    emit(out)


def new_stage(status: str, artifacts: list[str]) -> dict:
    return {"status": status, "revision": 0, "artifacts": artifacts, "artifacts_done": {}, "submitted": None, "approved": None}


def cmd_start(a) -> None:
    project = Path(a.project).resolve()
    ctx = gate_or_block(project)
    if load_state(project) is not None:
        block("already_started", f"{STATE_REL}이 이미 있습니다. check로 현재 상태를 확인하세요.")
    existing = existing_design_paths(project)
    if existing:
        block("existing_files", f"{', '.join(existing)}가 이미 있습니다. 덮어쓰지 않습니다. 옮기거나 정리한 뒤 다시 실행하세요.", paths=existing)
    dirty = ctx["preflight"]["dirty"]
    if dirty:
        block("dirty_worktree", "커밋되지 않은 변경이 있습니다. 기획 승인 문서를 커밋한 뒤 시작하세요.", dirty=dirty)
    gate = ctx["gate"]
    st = {
        "schema_version": 1, "workflow": "ai-product-workflow", "skill": "product-design", "created_at": now(),
        "based_on": {"discovery_revision": gate.get("discovery_approved_revision"), "planning_revision": gate.get("planning_approved_revision"),
                     "planning_hashes": gate["planning_hashes"], "planning_commit": git(project, "rev-parse", "HEAD").strip()},
        "validity": {"status": "valid"},
        "stages": {"ux_planning": new_stage("in_progress", [UXP_FILE]),
                   "ux_spec": new_stage("locked", list(SPEC_FILES)),
                   "preview": new_stage("locked", [REVIEW_FILE])},
        "history": [],
    }
    st["stages"]["ux_spec"].update(structure_confirmed=None, based_on_ux_planning_revision=None)
    st["stages"]["preview"].update(based_on_ux_spec_revision=None, verification=None)
    add_history(st, "ux_planning", "started", 0, f"planning r{gate.get('planning_approved_revision')} 기준으로 시작")
    save_state(project, st)
    emit({"ok": True, "status": overall_status(st), "based_on": st["based_on"], "next": "UX Planning 인터뷰", "display_note": DISPLAY_NOTE})


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
    idx = STAGES.index(stage)
    upstream = [p for p in cv["problems"] if STAGES.index(p["stage"]) < idx
                or (p["stage"] == "preview" and p["kind"] in ("upstream_not_approved", "stale_preview") and stage == "preview")]
    if upstream:
        block("upstream_modified", f"{STAGE_LABEL[stage]}보다 앞선 단계의 승인 산출물이 바뀌었거나 상태가 맞지 않습니다. "
              "자동으로 다시 승인하지 않습니다. 앞 단계를 재검토(reopen)하거나 파일을 복원하세요.", problems=upstream)
    return ctx


def cmd_begin(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, a.stage)
    stage = a.stage
    if stage == "ux_planning":
        block("invalid_stage", "ux_planning은 start 또는 reopen으로 시작합니다.")
    s = st["stages"][stage]
    prev = "ux_planning" if stage == "ux_spec" else "ux_spec"
    if st["stages"][prev]["status"] != "approved":
        block("upstream_not_approved", f"{STAGE_LABEL[prev]}가 승인되지 않아 {STAGE_LABEL[stage]}를 시작할 수 없습니다.")
    if s["status"] != "not_started":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. not_started에서만 시작합니다.")
    s["status"] = "in_progress"
    key = "based_on_ux_planning_revision" if stage == "ux_spec" else "based_on_ux_spec_revision"
    s[key] = st["stages"][prev]["approved"]["revision"]
    add_history(st, stage, "started", s["revision"], f"{prev} r{s[key]} 기준")
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "in_progress", key: s[key], "next": next_action(st)})


def stage_of(rel: str) -> str | None:
    for k, arts in STAGE_ARTIFACTS.items():
        if rel in arts:
            return k
    return None


def cmd_done(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    rel = a.path
    stage = stage_of(rel)
    if stage is None:
        block("unknown_artifact", f"{rel}은 /product-design 산출물이 아닙니다.", artifacts=STAGE_ARTIFACTS)
    require_valid(project, st, stage)
    s = st["stages"][stage]
    if s["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. in_progress에서만 산출물을 기록합니다.")
    p = project / rel
    if not p.exists():
        block("missing_file", f"{rel}이 없습니다.")
    fm = front_matter_revision(p.read_text(encoding="utf-8"))
    if fm != s["revision"] + 1:
        block("revision_mismatch", f"{rel}의 front matter revision({fm})은 준비 중인 revision {s['revision'] + 1}이어야 합니다.")
    s["artifacts_done"][rel] = sha256_file(p)
    save_state(project, st)
    remaining = [x for x in s["artifacts"] if x not in s["artifacts_done"]]
    emit({"ok": True, "stage": stage, "recorded": rel, "remaining": remaining})


def cmd_pending(a) -> None:
    project = Path(a.project).resolve()
    require_state(project)
    pr = pending_round(project)
    emit({"ok": not pr["errors"], **pr}, 0 if not pr["errors"] else 2)


def cmd_trace(a) -> None:
    project = Path(a.project).resolve()
    fn = {"ux_planning": trace_ux_planning, "structure": trace_structure, "ux_spec": trace_ux_spec}[a.stage]
    res = fn(project)
    emit({"stage": a.stage, **res}, 0 if res["ok"] else 2)


def cmd_checkpoint(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "ux_spec")
    s = st["stages"]["ux_spec"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"ux_spec 상태가 {s['status']}입니다.")
    for rel in (IA_FILE, SCREENS_FILE):
        if rel not in s["artifacts_done"]:
            block("not_done", f"{rel}을 작성한 뒤 done으로 기록하세요.")
        if sha256_file(project / rel) != s["artifacts_done"][rel]:
            block("changed_since_done", f"{rel}이 done 기록 이후 바뀌었습니다. 다시 제시하고 done을 실행하세요.")
    res = trace_structure(project)
    if not res["ok"]:
        block("trace_failed", "구조 검사를 통과하지 못했습니다.", **res)
    s["structure_confirmed"] = {"revision": s["revision"] + 1, "at": now(), "signature": structure_signature(project)}
    add_history(st, "ux_spec", "structure_confirmed", s["revision"] + 1, a.note or "IA·화면 목록 구조 확인")
    save_state(project, st)
    emit({"ok": True, "structure_confirmed": s["structure_confirmed"], "counts": res["counts"], "warnings": res["warnings"]})


def cmd_submit(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. in_progress에서만 제출합니다.")
    missing = [x for x in s["artifacts"] if x not in s["artifacts_done"]]
    if missing:
        block("not_done", "done으로 기록되지 않은 산출물이 있습니다.", missing=missing)
    cur = stage_current_hashes(project, stage)
    changed = [rel for rel in s["artifacts"] if cur.get(rel) != s["artifacts_done"].get(rel)]
    if changed:
        block("changed_since_done", "done 기록 이후 바뀐 파일이 있습니다. 확인 후 done을 다시 실행하세요.", paths=changed)
    target = s["revision"] + 1
    for rel in s["artifacts"]:
        fm = front_matter_revision((project / rel).read_text(encoding="utf-8"))
        if fm != target:
            block("revision_mismatch", f"{rel}의 front matter revision({fm})이 제출할 revision {target}과 다릅니다.")
    trace = None
    if stage == "ux_planning":
        pr = pending_round(project)
        if pr["pending"] or pr["errors"]:
            block("pending_questions", "답변을 기다리는 질문이 있거나 질문 기록 형식이 맞지 않아 제출할 수 없습니다.",
                  pending=pr["pending"], errors=pr["errors"])
        trace = trace_ux_planning(project)
    elif stage == "ux_spec":
        sc = s.get("structure_confirmed")
        carried = bool(sc) and sc.get("revision") != target and sc.get("signature") == structure_signature(project)
        if not sc or (sc.get("revision") != target and not carried):
            block("structure_not_confirmed", "이번 revision의 구조 확인(checkpoint)이 없습니다. IA·화면 목록을 먼저 확인받으세요."
                  + (" 이전에 확인받은 화면 구성과 달라졌습니다." if sc else ""))
        if carried:
            add_history(st, "ux_spec", "structure_carried", target, f"r{sc['revision']}에서 확인받은 화면 구성과 같아 구조 확인을 이어받음")
        trace = trace_ux_spec(project)
    else:
        pc = preview_check(project, st)
        if not pc["ok"]:
            block("preview_check_failed", "프리뷰 검사를 통과하지 못했습니다.", **pc)
        ver = s.get("verification") or {}
        if ver.get("result") != "pass" or ver.get("tree_hash") != cur[PREVIEW_TREE_KEY]:
            block("preview_not_verified", "현재 프리뷰 파일로 preview-verify가 통과한 기록이 없습니다. preview-verify를 실행하세요.")
    if trace is not None and not trace["ok"]:
        block("trace_failed", "추적성 검사를 통과하지 못했습니다.", **trace)
    s["revision"] = target
    s["status"] = "awaiting_approval"
    s["submitted"] = {"revision": target, "at": now(), "hashes": cur}
    add_history(st, stage, "submitted", target)
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "awaiting_approval", "revision": target,
          "trace": trace, "warnings": (trace or {}).get("warnings", []),
          "next": f"r{target}을 제시하고 명시적 승인을 받습니다."})


def cmd_approve(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] != "awaiting_approval":
        block("not_awaiting_approval", f"{stage} 상태가 {s['status']}입니다. 제출(submit)된 revision만 승인할 수 있습니다.")
    if a.revision != s["revision"]:
        block("revision_mismatch", f"승인 대상 revision은 r{s['revision']}입니다(요청: r{a.revision}).")
    cur = stage_current_hashes(project, stage)
    changed = diff_hashes(s["submitted"]["hashes"], cur)
    if changed:
        block("changed_since_submit", "제시한 뒤 파일이 바뀌었습니다. 다시 제시(reopen → 수정 → submit)해야 합니다.", paths=changed)
    if stage == "preview":
        ux = st["stages"]["ux_spec"]
        if ux["status"] != "approved" or s.get("based_on_ux_spec_revision") != ux["approved"]["revision"]:
            block("stale_preview", "프리뷰가 현재 승인된 UX 설계 revision을 기준으로 하지 않습니다.")
    s["status"] = "approved"
    s["approved"] = {"revision": s["revision"], "at": now(), "hashes": cur}
    if stage == "preview":
        s["approved"]["ux_spec_hashes"] = st["stages"]["ux_spec"]["approved"]["hashes"]
    add_history(st, stage, "approved", s["revision"], a.note or "사용자 명시적 승인")
    nxt = NEXT_STAGE.get(stage)
    if nxt and st["stages"][nxt]["status"] == "locked":
        st["stages"][nxt]["status"] = "not_started"
        add_history(st, nxt, "unlocked", st["stages"][nxt]["revision"], f"{stage} r{s['revision']} 승인")
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "approved", "revision": s["revision"], "overall": overall_status(st), "next": next_action(st)})


def invalidate_downstream(st: dict, stage: str, reason: str) -> list[str]:
    affected = []
    idx = STAGES.index(stage)
    for k in STAGES[idx + 1:]:
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


def cmd_reopen(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] not in ("approved", "awaiting_approval"):
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. approved/awaiting_approval만 다시 열 수 있습니다.")
    event = "reopened" if s["status"] == "approved" else "changes_requested"
    if s.get("approved"):
        s["last_approved"] = s["approved"]
    s["approved"] = None
    s["submitted"] = None
    s["status"] = "in_progress"
    s["artifacts_done"] = {}
    affected = invalidate_downstream(st, stage, f"{stage} 재검토로 승인 무효화")
    add_history(st, stage, event, s["revision"], a.reason)
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "in_progress", "preparing_revision": s["revision"] + 1,
          "invalidated": affected, "next": "수정할 파일의 front matter revision을 준비 중인 revision으로 올리고, 수정 후 done을 다시 실행합니다."})


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


def cmd_impact(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    commit = st["based_on"].get("planning_commit")
    changed_files = [f for f, h in st["based_on"]["planning_hashes"].items()
                     if not (project / f).exists() or sha256_file(project / f) != h]
    changed_ids: dict[str, list[str]] = {"added": [], "removed": [], "changed": []}
    full_review = False
    for f in changed_files:
        old = None
        if commit:
            try:
                old = git(project, "show", f"{commit}:{f}")
            except RuntimeError:
                old = None
        if old is None or sha256_bytes(old.encode("utf-8")) != st["based_on"]["planning_hashes"].get(f):
            full_review = True
            continue
        ob, nb = id_blocks(old), id_blocks(read_text(project, f))
        changed_ids["added"] += sorted(set(nb) - set(ob))
        changed_ids["removed"] += sorted(set(ob) - set(nb))
        changed_ids["changed"] += sorted(k for k in set(ob) & set(nb) if ob[k] != nb[k])
    targets = set(changed_ids["removed"] + changed_ids["changed"])
    prd_changed = any(f.endswith("02-prd.md") for f in changed_files)
    affected = refs_for(project, targets)
    emit({"ok": True, "changed_files": changed_files, "changed_ids": changed_ids, "full_review_required": full_review,
          "prd_changed": prd_changed, "affected": affected,
          "note": "기준 커밋에서 이전 기획을 읽을 수 없으면 전체 재검토가 필요합니다." if full_review else ""})


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


def cmd_refs(a) -> None:
    project = Path(a.project).resolve()
    ids = set(a.id)
    emit({"ok": True, "ids": sorted(ids), "references": refs_for(project, ids)})


def cmd_rebase(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    ctx = gate_or_block(project)
    detect_outdated(project, st, ctx["gate"])
    if st.get("validity", {}).get("status") != "outdated":
        block("not_outdated", "디자인 기준이 현재 planning 승인과 같습니다. rebase할 필요가 없습니다.")
    if not a.confirm:
        block("confirm_required", "사용자 확인 후 --confirm으로 실행합니다. 모든 디자인 승인이 해제되고 UX Planning부터 재검토합니다.")
    # 새 기준 커밋(planning_commit)이 재승인된 기획을 가리키도록, 기획 파일과 state.yaml만 커밋 여부를 봅니다.
    planning_dirty = [p for p in git_dirty_paths(project) if p.startswith("docs/planning/") or p == WORKFLOW_STATE_REL]
    if planning_dirty:
        block("dirty_worktree", "재승인된 기획이 커밋되지 않았습니다. 기획 문서와 state.yaml을 커밋한 뒤 실행하세요.", dirty=planning_dirty)
    old = st["based_on"]
    gate = ctx["gate"]
    st["based_on"] = {"discovery_revision": gate.get("discovery_approved_revision"), "planning_revision": gate.get("planning_approved_revision"),
                      "planning_hashes": gate["planning_hashes"], "planning_commit": git(project, "rev-parse", "HEAD").strip(),
                      "previous": {k: old[k] for k in ("planning_revision", "planning_commit")}}
    up = st["stages"]["ux_planning"]
    if up.get("approved"):
        up["last_approved"] = up["approved"]
    up.update(status="in_progress", approved=None, submitted=None, artifacts_done={})
    invalidate_downstream(st, "ux_planning", "planning 변경으로 디자인 재검토")
    st["validity"] = {"status": "valid"}
    add_history(st, "design", "rebased", None, f"planning r{old.get('planning_revision')} → r{gate.get('planning_approved_revision')}")
    save_state(project, st)
    emit({"ok": True, "status": overall_status(st), "based_on": st["based_on"], "next": "바뀐 기획 항목에 대해 UX Planning을 재검토합니다."})


def cmd_backup(a) -> None:
    project = Path(a.project).resolve()
    raw = a.path
    if not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        block("invalid_path", "프로젝트 기준 상대 경로만 허용합니다(절대 경로, '..' 불가).", path=raw)
    p = (project / raw).resolve()
    try:
        rel = str(p.relative_to(project))
    except ValueError:
        block("invalid_path", "프로젝트 밖을 가리키는 경로입니다(심볼릭 링크 포함).", path=raw)
    if not (rel.startswith(DESIGN_DIR + "/") or rel.startswith(PREVIEW_DIR + "/")):
        block("not_design_path", "디자인 산출물만 백업합니다.", path=rel)
    if p.exists() and not p.is_file():
        block("invalid_path", "파일만 백업합니다.", path=rel)
    if not p.exists():
        emit({"ok": True, "backup": None, "reason": "파일이 없습니다(새 파일)."})
    tracked = git(project, "ls-files", "--error-unmatch", rel, check=False).strip() != ""
    dirty = bool(git(project, "status", "--porcelain", "--", rel).strip())
    if tracked and not dirty:
        emit({"ok": True, "backup": None, "reason": "Git으로 추적되고 미커밋 변경이 없어 Git 이력으로 복원할 수 있습니다."})
    dest = project / ".ai-workflow/backup/design" / rel.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    emit({"ok": True, "backup": str(dest.relative_to(project)), "reason": "Git으로 보호되지 않아 단일 슬롯에 백업했습니다(같은 파일의 이전 백업은 덮어씀)."})


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def cmd_preview_scaffold(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "preview")
    s = st["stages"]["preview"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"preview 상태가 {s['status']}입니다. begin --stage preview 후 실행하세요.")
    dest = project / PREVIEW_DIR
    if dest.exists():
        block("existing_files", f"{PREVIEW_DIR}/가 이미 있습니다. 덮어쓰지 않습니다.")
    shutil.copytree(skill_dir() / "templates" / "preview", dest)
    gi = dest / "gitignore"
    if gi.exists():
        gi.rename(dest / ".gitignore")
    man = dest / "preview.manifest.json"
    data = json.loads(man.read_text(encoding="utf-8"))
    data["ux_spec_revision"] = st["stages"]["ux_spec"]["approved"]["revision"]
    data["screens"] = {k: {"file": "", "states": []} for k in sorted(screen_info(project))}
    man.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit({"ok": True, "created": PREVIEW_DIR, "files": preview_files(project), "next": "화면·mock·registry를 작성하고 preview-verify를 실행합니다."})


def cmd_preview_check(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    res = preview_check(project, st)
    emit({"ok": res["ok"], **res}, 0 if res["ok"] else 2)


def cmd_preview_verify(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "preview")
    s = st["stages"]["preview"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"preview 상태가 {s['status']}입니다.")
    pc = preview_check(project, st)
    steps = []
    result = "fail"
    if pc["ok"]:
        root = project / PREVIEW_DIR
        lock = (root / "pnpm-lock.yaml").exists()
        cmds = [["pnpm", "install", "--frozen-lockfile"] if lock else ["pnpm", "install"], ["pnpm", "run", "build"]]
        result = "pass"
        for cmd in cmds:
            try:
                p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=a.timeout)
                rc, out = p.returncode, (p.stdout + p.stderr)
            except FileNotFoundError:
                rc, out = 127, "pnpm을 찾을 수 없습니다."
            except subprocess.TimeoutExpired:
                rc, out = 124, "시간 초과"
            steps.append({"run": " ".join(cmd), "exit": rc, "tail": out.strip().splitlines()[-15:]})
            if rc != 0:
                result = "fail"
                break
    s["verification"] = {"result": result, "at": now(), "tree_hash": preview_tree_hash(project), "check": pc, "steps": steps}
    add_history(st, "preview", "verified" if result == "pass" else "verify_failed", s["revision"])
    save_state(project, st)
    out = {"ok": result == "pass", "result": result, "check": pc, "steps": steps,
           "run_command": f"pnpm --dir {PREVIEW_DIR} dev", "url": "http://localhost:55180/"}
    emit(out, 0 if result == "pass" else 2)


def cmd_status(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    gate = read_gate(project)
    cv = cross_verify(project, st)
    emit({"ok": cv["consistent"] and gate["ok"], "overall": overall_status(st),
          "stages": {k: {"status": v["status"], "revision": v["revision"],
                         "approved_revision": (v.get("approved") or {}).get("revision")} for k, v in st["stages"].items()},
          "based_on": {k: st["based_on"].get(k) for k in ("discovery_revision", "planning_revision", "planning_commit")},
          "validity": st.get("validity"), "gate_ok": gate["ok"], "state_yaml_design_status": gate.get("state_yaml_design_status"),
          "cross_verify": cv, "next": next_action(st), "display_note": DISPLAY_NOTE})


class JsonArgParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # 인자 오류도 JSON으로
        block("invalid_arguments", message)


def main() -> None:
    ap = JsonArgParser(description="/product-design helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args):
        s = sub.add_parser(name)  # 하위 파서도 JsonArgParser(add_subparsers 기본값: 부모 클래스)
        s.add_argument("--project", required=True)
        s.set_defaults(fn=fn)
        return s

    add("check", cmd_check)
    add("start", cmd_start)
    s = add("begin", cmd_begin); s.add_argument("--stage", required=True, choices=STAGES)
    s = add("done", cmd_done); s.add_argument("--path", required=True)
    s = add("trace", cmd_trace); s.add_argument("--stage", required=True, choices=("ux_planning", "structure", "ux_spec"))
    s = add("checkpoint", cmd_checkpoint); s.add_argument("--note", default="")
    s = add("submit", cmd_submit); s.add_argument("--stage", required=True, choices=STAGES)
    s = add("approve", cmd_approve); s.add_argument("--stage", required=True, choices=STAGES)
    s.add_argument("--revision", required=True, type=int); s.add_argument("--note", default="")
    s = add("reopen", cmd_reopen); s.add_argument("--stage", required=True, choices=STAGES); s.add_argument("--reason", required=True)
    add("impact", cmd_impact)
    add("pending", cmd_pending)
    s = add("rebase", cmd_rebase); s.add_argument("--confirm", action="store_true")
    s = add("refs", cmd_refs); s.add_argument("--id", required=True, action="append")
    s = add("backup", cmd_backup); s.add_argument("--path", required=True)
    add("preview-scaffold", cmd_preview_scaffold)
    add("preview-check", cmd_preview_check)
    s = add("preview-verify", cmd_preview_verify); s.add_argument("--timeout", type=int, default=600)
    add("status", cmd_status)
    a = ap.parse_args()
    try:
        a.fn(a)
    except SystemExit:
        raise
    except Exception as e:  # 예상하지 못한 오류도 JSON으로 보고(상태 파일은 원자적으로만 씀)
        block("internal_error", f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
