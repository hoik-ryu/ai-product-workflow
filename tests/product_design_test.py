#!/usr/bin/env python3
"""/product-design 스크립트 테스트(자체 완결형).

임시 디렉터리에 승인된 기획을 가진 가짜 제품 저장소를 만들고, LLM이 쓸 디자인 문서를 테스트 코드가 대신 작성해
게이트, 상태 전이, 승인, 해시, 추적성, 무효화, 프리뷰 경계·빌드를 검사합니다.

- state.yaml과 planning 문서는 테스트 픽스처입니다(실제 /product-start 승인 흐름이 아님).
- 프리뷰 빌드(P17)는 pnpm과 네트워크가 있을 때만 실행하고, 없으면 SKIP으로 표시합니다.

실행: python3 tests/product_design_test.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
SCRIPT = ENGINE / "skills/product-design/scripts/product_design.py"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail=None) -> None:
    results.append((name, bool(cond), "" if cond else str(detail)[:600]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:600]}"))


def skip(name: str, why: str) -> None:
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


def G(d, *args):
    return sh("git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args, cwd=d)


def pi(*args) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True,
                       env={"PATH": __import__("os").environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", "HOME": __import__("os").environ.get("HOME", "")})
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def state(d: Path) -> dict:
    return json.loads((d / ".ai-workflow/design.json").read_text())


def errs(out: dict) -> str:
    return " / ".join(out.get("errors", []))


# ---------------------------------------------------------------- 기획 픽스처
PLANNING = {
    "01-discovery.md": "---\ndoc: discovery\nrevision: 1\n---\n# Discovery\n- PRB-001 대진 오류\n",
    "02-prd.md": """---
doc: prd
revision: 1
---
# PRD
## 4. 기능 요구사항
| ID | 요구사항 | 우선순위 | 추적 |
|---|---|---|---|
| FR-001 | 로그인 | Must | GOAL-001 |
| FR-002 | 대진 생성 | Must | GOAL-001 |
| FR-003 | 마이페이지 | Should | GOAL-002 |
## 5. 비기능
| ID | 분류 | 요구사항 | 추적 |
|---|---|---|---|
| NFR-001 | 모바일 | 회원 화면은 모바일 전용 | PER-001 |
## 7. 가정
### 7.1 사용자가 확인한 사항
| 확정 ID | 내용 | 근거 | 반영 위치 |
|---|---|---|---|
| C-01 | 레벨별 방식은 3구간 | ASM-007 확인 | FR-002 |
| C-02 | 혼복을 먼저 만든다 | ASM-009 확인 | FR-002 |
""",
    "03-user-stories.md": """---
doc: user-stories
revision: 1
---
# 사용자 스토리
### US-001: 로그인
- **우선순위**: Must
- **추적 대상**: FR-001
### US-002: 대진 생성
- **우선순위**: Must
- **추적 대상**: FR-002
### US-003: 마이페이지
- **우선순위**: Should
- **추적 대상**: FR-003
""",
    "04-user-flows.md": """---
doc: user-flows
revision: 1
---
# 플로우
## FLOW-001: 로그인
| 단계 | 사용자 행동 | 시스템 반응 |
|---|---|---|
| FLOW-001-S1 | 로그인 버튼 | 인증 |
| FLOW-001-S2 | 홈 진입 | 홈 표시 |

- FLOW-001-S1a: 인증 실패 시 다시 시도
## FLOW-002: 대진
| 단계 | 사용자 행동 | 시스템 반응 |
|---|---|---|
| FLOW-002-S1 | 생성 버튼 | 대진 표시 |
""",
    "05-acceptance-criteria.md": """---
doc: acceptance-criteria
revision: 1
---
# AC
### AC-001: 로그인하면 홈으로 간다
- **추적 대상**: US-001, FR-001
### AC-002: 인증 실패 시 안내
- **추적 대상**: US-001, FR-001
### AC-003: 버튼 한 번으로 대진 생성
- **추적 대상**: US-002, FR-002
### AC-004: 같은 입력이면 같은 결과
- **추적 대상**: US-002, FR-002
""",
}


def write_state_yaml(d: Path, planning_status="approved", design_status="not_started") -> None:
    h = {f: sha(d / "docs/planning" / f) for f in PLANNING}
    plan_hashes = "\n".join(f'        docs/planning/{f}: "{h[f]}"' for f in list(PLANNING)[1:])
    (d / ".ai-workflow/state.yaml").write_text(f"""schema_version: 1
workflow: ai-product-workflow
current_stage: design
stages:
  discovery:
    status: approved
    revision: 1
    approved:
      revision: 1
      at: "2026-11-06T00:00:00Z"
      hashes:
        docs/planning/01-discovery.md: "{h['01-discovery.md']}"

  planning:
    status: {planning_status}
    revision: 1
    based_on_discovery_revision: 1
    artifacts_done: []
    approved:
      revision: 1
      at: "2026-11-06T00:00:00Z"
      hashes:
{plan_hashes}

  design:
    status: {design_status}

history: []
""")


def make_product(root: Path, name: str, planning_status="approved") -> Path:
    d = root / name
    (d / "docs/planning").mkdir(parents=True)
    (d / ".ai-workflow").mkdir()
    G(d, "init", "-q")
    (d / "README.md").write_text("# 제품\n")
    (d / ".gitignore").write_text("node_modules/\ndist/\n")
    for f, c in PLANNING.items():
        (d / "docs/planning" / f).write_text(c)
    write_state_yaml(d, planning_status)
    G(d, "add", "-A")
    G(d, "commit", "-qm", "approved planning")
    return d


# ---------------------------------------------------------------- 디자인 문서 픽스처(LLM 대신 작성)
def fm(doc: str, rev: int) -> str:
    return f"---\ndoc: {doc}\nrevision: {rev}\nlanguage: ko\n---\n"


def write_00(d: Path, rev: int, extra_rel: str = "") -> None:
    (d / "docs/design").mkdir(parents=True, exist_ok=True)
    (d / "docs/design/00-ux-decisions.md").write_text(fm("ux-decisions", rev) + f"""
# UX 결정 기록
<!-- ### UXD-900: 템플릿 예시(주석 안이라 무시되어야 함)
- **상태**: 이상한값 -->
## UX 결정
### UXD-001: 로그인은 카카오 버튼 하나
- **주제**: 로그인
- **결정**: 첫 화면에 카카오 버튼 하나만 둔다
- **근거**: 사용자 답변(라운드 1)
- **상태**: 확정
- **관련**: US-001, FLOW-001-S1{extra_rel}
### UXD-002: 대진 결과는 코트 카드 2열
- **주제**: 대진
- **결정**: 코트 카드를 2열로 배치
- **근거**: 권장안 수용 — 코트 4면 비교
- **상태**: 권장안 수용
- **관련**: US-002, AC-003, C-02
## 미결 디자인 질문
### DQ-001: 시드 표시 여부
- **질문**: 대진 시드를 보여 줄까
- **권장 기본값**: 숨김
- **상태**: 미결
- **관련**: AC-004
## 기획 재검토 대상
### PF-001: 회원 직접 참석 등록
- **내용**: 회원이 직접 참석 등록
- **이유**: PRD 범위 제외
- **상태**: 미결
- **관련**: FR-002
""")


def write_notes(d: Path, rounds: str) -> None:
    (d / ".ai-workflow/design-notes.md").write_text("# UX Planning 기록\n\n## 분석\n- 확정 사항: C-01, C-02\n\n" + rounds)


ROUND1_PENDING = """## 라운드 1 — 로그인
- **상태**: 답변 대기
### 질문
#### R01-Q1: 로그인 버튼 구성
- **선택지**: a) 카카오 버튼 하나 / b) 카카오 + 안내 문구
- **권장안**: a) — 진입 단계를 줄임
- **관련**: US-001, FLOW-001-S1
#### R01-Q2: 대진 카드 배치
- **선택지**: a) 1열 / b) 2열
- **권장안**: b) — 코트 비교(C-02 혼복 표시 포함)
- **관련**: US-002, AC-003, C-02
### 답변 원문
(대기 중)
"""


STATES_FULL = """### 상태
| 상태 ID | 상태 | 표시·동작 |
|---|---|---|
| {s}-ST1 | 기본 | 기본 |
| {s}-ST2 | 로딩 | 스피너 |
| - | 빈 상태 | 해당 없음 |
| {s}-ST3 | 오류 | 오류 안내 |
| - | 권한 없음 | 해당 없음 |
| - | 충돌 | 해당 없음 |
"""


def write_spec(d: Path, rev: int, variant: str = "ok") -> None:
    dd = d / "docs/design"
    dd.mkdir(parents=True, exist_ok=True)
    ia_rows = "| SCR-001 | 로그인 | /login | 비로그인 | mobile | 인증 |\n| SCR-002 | 대진 | /admin/round | 운영진 | responsive | 운영 |\n"
    if variant != "ia_missing":
        ia_rows += "| SCR-003 | 마이페이지 | /me | 회원 | mobile | 회원 |\n"
    (dd / "01-information-architecture.md").write_text(fm("information-architecture", rev) + f"""
# IA
## 라우트 표
| 화면 ID | 화면 이름 | 경로 | 접근 역할 | 플랫폼 | 셸 |
|---|---|---|---|---|---|
{ia_rows}""")
    s2_trace = "US-002, FLOW-002-S1, AC-003" if variant != "must_missing" else "FLOW-002-S1"
    s1_cmp = "CMP-001" if variant != "bad_cmp" else "CMP-001, CMP-009"
    s1_states = STATES_FULL.format(s="SCR-001")
    if variant == "missing_state":
        s1_states = s1_states.replace("| - | 충돌 | 해당 없음 |\n", "")
    platform3 = "mobile" if variant != "bad_platform" else "desktop"
    (dd / "02-screens.md").write_text(fm("screens", rev) + f"""
# 화면
<!-- ## SCR-999: 템플릿 예시(무시되어야 함) -->
## SCR-001: 로그인
- **목적**: 로그인
- **역할**: 비로그인
- **플랫폼**: mobile
- **경로**: /login
- **추적**: US-001, FLOW-001-S1, AC-001
- **UX 결정**: UXD-001
### 레이아웃(저충실도)
```
## SCR-777: 코드 블록 안 헤딩은 무시
```
{s1_states}
### 컴포넌트
{s1_cmp}

## SCR-002: 대진
- **목적**: 대진 생성
- **역할**: 운영진
- **플랫폼**: responsive
- **경로**: /admin/round
- **추적**: {s2_trace}
- **UX 결정**: UXD-002
{STATES_FULL.format(s="SCR-002")}
### 컴포넌트
CMP-002

## SCR-003: 마이페이지
- **목적**: 내 정보
- **역할**: 회원
- **플랫폼**: {platform3}
- **경로**: /me
- **추적**: US-003
{STATES_FULL.format(s="SCR-003")}
### 컴포넌트
CMP-001
""")
    step_rows = "| FLOW-001-S1 | SCR-001 | |\n| FLOW-001-S2 | SCR-003 | |\n| FLOW-002-S1 | SCR-002-ST1 | |\n"
    if variant != "flow_missing":
        step_rows += "| FLOW-001-S1a | SCR-001-ST3 | 실패 |\n"
    (dd / "03-screen-flows.md").write_text(fm("screen-flows", rev) + f"""
# 흐름
| FLOW 단계 | 화면·상태 | 비고 |
|---|---|---|
{step_rows}""")
    (dd / "04-ui-system.md").write_text(fm("ui-system", rev) + """
# UI
### CMP-001: 버튼
- **용도**: 주요 행동
### CMP-002: 코트 카드
- **용도**: 대진 표시
""")
    us3 = "| US-003 | Should | SCR-003 | |" if variant != "should_missing" else "| US-003 | Should | | |"
    ac4 = "| AC-004 | 비UI: 서버 알고리즘 결정성 | 백엔드 테스트 |" if variant != "nonui_noreason" else "| AC-004 | 비UI: | |"
    ac_rows = "| AC-001 | SCR-001-ST1 | |\n| AC-002 | SCR-001-ST3 | |\n| AC-003 | SCR-002 | |\n" + ac4 + "\n"
    if variant == "ac_missing":
        ac_rows = ac_rows.replace("| AC-002 | SCR-001-ST3 | |\n", "")
    if variant == "bad_state":
        ac_rows = ac_rows.replace("SCR-001-ST3 | |\n", "SCR-001-ST9 | |\n")
    (dd / "05-design-traceability.md").write_text(fm("design-traceability", rev) + f"""
# 추적성
| US | 우선순위 | 화면 | UX 결정 |
|---|---|---|---|
| US-001 | Must | SCR-001 | UXD-001 |
| US-002 | Must | SCR-002 | UXD-002 |
{us3}

| AC | 화면·상태 | 확인 |
|---|---|---|
{ac_rows}""")


def write_06(d: Path, rev: int, note: str = "") -> None:
    (d / "docs/design/06-preview-review.md").write_text(fm("preview-review", rev) + f"""
# 프리뷰 검토
| ID | 화면·상태 | 피드백 | 조치 | 상태 |
|---|---|---|---|---|
| FB-001 | SCR-002-ST1 | 카드 글씨가 작음 | 18px | 반영 {note} |
""")


SCREEN_TSX = """export function Screen{n}({{ state }}: {{ state: string }}) {{
  return <section><h1>{title}</h1><p>상태: {{state}}</p></section>
}}
"""


def fill_preview(d: Path, rev: int) -> None:
    root = d / "design-preview"
    entries = []
    man = json.loads((root / "preview.manifest.json").read_text())
    man["ux_spec_revision"] = rev
    for n, (sid, title) in enumerate((("SCR-001", "로그인"), ("SCR-002", "대진"), ("SCR-003", "마이페이지")), 1):
        (root / f"src/screens/{sid}.tsx").write_text(SCREEN_TSX.format(n=n, title=title))
        man["screens"][sid] = {"file": f"src/screens/{sid}.tsx", "states": [f"{sid}-ST1", f"{sid}-ST3"]}
        entries.append(f'  "{sid}": {{ id: "{sid}", title: "{title}", platform: "mobile", states: [{{ id: "{sid}-ST1", label: "기본" }}, {{ id: "{sid}-ST3", label: "오류" }}], render: (s) => <Screen{n} state={{s}} /> }},')
    imports = "\n".join(f'import {{ Screen{n} }} from "./screens/{sid}"' for n, sid in enumerate(("SCR-001", "SCR-002", "SCR-003"), 1))
    reg = (root / "src/registry.tsx").read_text()
    reg = reg.replace("import type { ReactElement } from 'react'", "import type { ReactElement } from 'react'\n" + imports)
    reg = reg.replace("export const screens: Record<string, ScreenDef> = {}", "export const screens: Record<string, ScreenDef> = {\n" + "\n".join(entries) + "\n}")
    (root / "src/registry.tsx").write_text(reg)
    (root / "preview.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")


def done_all(d: Path, files) -> list:
    return [pi("done", "--project", str(d), "--path", f) for f in files]


SPEC = ["docs/design/01-information-architecture.md", "docs/design/02-screens.md", "docs/design/03-screen-flows.md",
        "docs/design/04-ui-system.md", "docs/design/05-design-traceability.md"]
UXP = "docs/design/00-ux-decisions.md"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-test-"))
    P = lambda d: ("--project", str(d))

    # ---- 게이트
    d0 = root / "nostate"
    d0.mkdir()
    G(d0, "init", "-q"); (d0 / "a").write_text("a"); G(d0, "add", "-A"); G(d0, "commit", "-qm", "i")
    code, out = pi("check", *P(d0))
    check("P01 state.yaml 없음 → 차단", code == 2 and out.get("error") == "no_workflow_state", out)

    d = make_product(root, "awaiting", planning_status="awaiting_approval")
    code, out = pi("start", *P(d))
    check("P02 planning 미승인 → 시작 차단, design.json 미생성", code == 2 and out.get("error") == "planning_not_approved"
          and not (d / ".ai-workflow/design.json").exists(), out)

    d = make_product(root, "hashmismatch")
    p03 = d / "docs/planning/03-user-stories.md"
    p03.write_text(p03.read_text() + "\n- 수동 메모\n"); G(d, "commit", "-qam", "edit after approval")
    code, out = pi("check", *P(d))
    check("P03 승인 후 기획 수정(해시 불일치) → 차단, 원인 파일 명시", code == 2 and "03-user-stories.md" in out.get("message", ""), out)

    eng = root / "engine"
    (eng / "skills/product-start").mkdir(parents=True); (eng / "skills/product-start/SKILL.md").write_text("x")
    G(eng, "init", "-q"); G(eng, "add", "-A"); G(eng, "commit", "-qm", "i")
    code, out = pi("check", *P(eng))
    check("P04 엔진 저장소 안 실행 → 차단", code == 2 and out.get("error") == "engine_repo", out)

    d = make_product(root, "dirty")
    (d / "scratch.txt").write_text("x")
    code, out = pi("start", *P(d))
    check("P05 미커밋 변경 → 시작 차단", code == 2 and out.get("error") == "dirty_worktree", out)
    (d / "scratch.txt").unlink()
    (d / "docs/design").mkdir(); (d / "docs/design/old.md").write_text("사람이 쓴 문서\n"); G(d, "add", "-A"); G(d, "commit", "-qm", "old design")
    code, out = pi("start", *P(d))
    check("P05a 기존 docs/design 파일 → 시작 거부(덮어쓰지 않음)", code == 2 and out.get("error") == "existing_files"
          and (d / "docs/design/old.md").read_text() == "사람이 쓴 문서\n", out)

    # ---- 정상 흐름
    d = make_product(root, "main")
    sy_before = sha(d / ".ai-workflow/state.yaml")
    plan_before = {f: sha(d / "docs/planning" / f) for f in PLANNING}
    code, out = pi("start", *P(d))
    s = state(d)
    check("P06 시작 → design.json(based_on 해시·커밋), ux_planning in_progress", code == 0 and s["stages"]["ux_planning"]["status"] == "in_progress"
          and s["stages"]["ux_spec"]["status"] == "locked" and len(s["based_on"]["planning_hashes"]) == 5 and s["based_on"]["planning_commit"], out)
    check("P06a 표시 정책 안내(display_note) 포함", "design.json" in out.get("display_note", ""), out)
    code, out = pi("begin", *P(d), "--stage", "ux_spec")
    check("P07 UX Planning 확정 전 UX 설계 시작 → 거부", code == 2 and out.get("error") == "upstream_not_approved", out)
    code, out = pi("approve", *P(d), "--stage", "ux_planning", "--revision", "1")
    check("P07a 제출 없이 승인 → 거부", code == 2 and out.get("error") == "not_awaiting_approval", out)

    # UX Planning — 질문 라운드 영속화(M1)
    code, out = pi("pending", *P(d))
    check("M1 질문 기록 전: 대기 라운드 없음", code == 0 and out["pending"] is None, out)
    write_notes(d, ROUND1_PENDING)
    code, out = pi("pending", *P(d))
    pend = out.get("pending") or {}
    check("M1a 답변 대기 라운드 저장·조회(질문 ID·선택지·권장안·관련 ID)", code == 0 and pend.get("round") == 1
          and [q["id"] for q in pend.get("questions", [])] == ["R01-Q1", "R01-Q2"]
          and pend["questions"][1]["recommendation"].startswith("b)") and "C-02" in pend["questions"][1]["related"], out)
    raw_before = pend.get("raw")
    code, out = pi("check", *P(d))
    check("M1b 중단 후 재개: check가 기록된 대기 질문을 그대로 반환하고 먼저 보여 주라고 안내", code == 0
          and (out.get("pending_round") or {}).get("raw") == raw_before and "그대로" in out.get("next", ""), out)
    for bad, expect, label in (
            (ROUND1_PENDING.replace("- **권장안**: a) — 진입 단계를 줄임\n", ""), "권장안", "권장안 누락"),
            (ROUND1_PENDING.replace("R01-Q2", "R02-Q2"), "R01-Q#", "라운드와 다른 질문 ID"),
            (ROUND1_PENDING.replace("US-001, FLOW-001-S1", "US-077"), "US-077", "기획에 없는 관련 ID"),
            (ROUND1_PENDING + ROUND1_PENDING.replace("라운드 1", "라운드 2").replace("R01-", "R02-"), "답변 대기 라운드가 2개", "대기 라운드 2개")):
        write_notes(d, bad)
        code, out = pi("pending", *P(d))
        check(f"M1c 질문 기록 형식 오류 감지: {label}", code == 2 and expect in " / ".join(out.get("errors", [])), out)
    write_notes(d, ROUND1_PENDING)

    # UX Planning
    write_00(d, 2)
    code, out = pi("done", *P(d), "--path", UXP)
    check("P08 front matter revision 불일치 → done 거부", code == 2 and out.get("error") == "revision_mismatch", out)
    write_00(d, 1, extra_rel=", US-099")
    pi("done", *P(d), "--path", UXP)
    code, out = pi("trace", *P(d), "--stage", "ux_planning")
    check("P08a 기획에 없는 ID 참조 → 추적성 오류(제출 불가)", code == 2 and "US-099" in errs(out), out)
    check("P08b 주석 안 예시 UXD는 검사에서 무시", "UXD-900" not in errs(out), out)
    write_00(d, 1, extra_rel=", C-99")
    pi("done", *P(d), "--path", UXP)
    code, out = pi("trace", *P(d), "--stage", "ux_planning")
    check("M2 확정 사항: 기획에 없는 C-99 참조 → 오류(C-02는 유효)", code == 2 and "C-99" in errs(out) and "C-02" not in errs(out), out)
    write_00(d, 1)
    pi("done", *P(d), "--path", UXP)
    code, out = pi("submit", *P(d), "--stage", "ux_planning")
    check("M1d 답변 대기 질문이 있으면 UX Planning 제출 거부", code == 2 and out.get("error") == "pending_questions"
          and (out.get("pending") or {}).get("round") == 1, out)
    write_notes(d, ROUND1_PENDING.replace("답변 대기", "답변 완료").replace("(대기 중)", "> 1-a, 2-b"))
    code, out = pi("pending", *P(d))
    check("M1e 답변 기록 후 대기 질문 없음", code == 0 and out["pending"] is None and out["last_round"] == 1, out)
    code, out = pi("submit", *P(d), "--stage", "ux_planning")
    check("P08c 제출 → awaiting r1, 미결 DQ·PF 경고", code == 0 and out["revision"] == 1 and any("DQ-001" in w for w in out["warnings"])
          and any("PF-001" in w for w in out["warnings"]), out)
    orig00 = (d / UXP).read_text()
    (d / UXP).write_text(orig00 + "\n추가 메모\n")
    code, out = pi("approve", *P(d), "--stage", "ux_planning", "--revision", "1")
    check("P09 제시 후 파일 변경 → 승인 거부(changed_since_submit)", code == 2 and out.get("error") == "changed_since_submit", out)
    code, out = pi("check", *P(d))
    check("P09a check → state_mismatch(submitted_modified)", code == 2 and any(p["kind"] == "submitted_modified" for p in out["cross_verify"]["problems"]), out)
    (d / UXP).write_text(orig00)
    code, out = pi("approve", *P(d), "--stage", "ux_planning", "--revision", "2")
    check("P09b 다른 revision 승인 → 거부", code == 2 and out.get("error") == "revision_mismatch", out)
    code, out = pi("approve", *P(d), "--stage", "ux_planning", "--revision", "1")
    s = state(d)
    check("P09c UX 결정 확정 → ux_spec not_started", code == 0 and s["stages"]["ux_planning"]["status"] == "approved"
          and s["stages"]["ux_spec"]["status"] == "not_started", out)

    # H1: 승인된 UX Planning 문서 변경 → UX 설계 진행 차단(check 없이 각 명령 자체 검증)
    approved00 = (d / UXP).read_text()
    (d / UXP).write_text(approved00 + "\n승인 후 메모\n")
    code, out = pi("begin", *P(d), "--stage", "ux_spec")
    check("H1 승인된 00 변경 → UX 설계 begin 차단", code == 2 and out.get("error") == "upstream_modified"
          and any(p["stage"] == "ux_planning" and p["kind"] == "approved_modified" for p in out.get("problems", [])), out)
    (d / UXP).write_text(approved00)

    # UX Spec
    code, out = pi("begin", *P(d), "--stage", "ux_spec")
    check("P10 UX 설계 시작(based_on_ux_planning_revision=1)", code == 0 and state(d)["stages"]["ux_spec"]["based_on_ux_planning_revision"] == 1, out)
    write_spec(d, 1, "ia_missing")
    pi("done", *P(d), "--path", SPEC[0])
    code, out = pi("check", *P(d))
    check("P10a 중단 후 재개: check가 다음 행동(구조 확인) 안내", code == 0 and "구조" in out.get("next", ""), out)
    code, out = pi("trace", *P(d), "--stage", "structure")
    check("P11 구조 검사: 01 라우트 표에 없는 화면 감지", code == 2 and "SCR-003가" in errs(out), out)
    write_spec(d, 1, "must_missing")
    code, out = pi("trace", *P(d), "--stage", "structure")
    check("P11a 구조 검사: 화면 없는 Must US 감지", code == 2 and "US-002" in errs(out), out)
    write_spec(d, 1, "bad_platform")
    code, out = pi("trace", *P(d), "--stage", "structure")
    check("P11b 구조 검사: 잘못된 플랫폼 값", code == 2 and "플랫폼" in errs(out), out)
    write_spec(d, 1)
    code, out = pi("trace", *P(d), "--stage", "structure")
    check("P11c 구조 검사 통과(주석·코드 블록 속 예시 헤딩 무시)", code == 0 and out["counts"]["SCR"] == 3, out)
    done_all(d, SPEC)
    (d / UXP).write_text(approved00 + "\n승인 후 메모\n")
    for cmd_args, label in ((("checkpoint",), "checkpoint"), (("submit", "--stage", "ux_spec"), "submit"),
                            (("done", "--path", SPEC[0]), "done")):
        code, out = pi(cmd_args[0], *P(d), *cmd_args[1:])
        check(f"H1a 승인된 00 변경 → UX 설계 {label} 차단", code == 2 and out.get("error") == "upstream_modified", out)
    (d / UXP).write_text(approved00)
    code, out = pi("submit", *P(d), "--stage", "ux_spec")
    check("P11d 구조 확인 없이 제출 → 거부", code == 2 and out.get("error") == "structure_not_confirmed", out)
    code, out = pi("checkpoint", *P(d), "--note", "사용자 구조 확인")
    check("P11e 구조 확인 기록", code == 0 and out["structure_confirmed"]["revision"] == 1, out)

    for variant, expect, label in (("missing_state", "'충돌' 행", "상태 표 6종 누락"), ("bad_cmp", "CMP-009", "정의 안 된 컴포넌트"),
                                   ("flow_missing", "FLOW-001-S1a", "대응 없는 FLOW 대안 단계"), ("ac_missing", "AC-002 행이 없습니다", "AC 행 누락"),
                                   ("nonui_noreason", "AC-004", "비UI 사유 없음"), ("should_missing", "US-003", "Should US 화면·후속 없음"),
                                   ("bad_state", "SCR-001-ST9", "없는 화면 상태 참조")):
        write_spec(d, 1, variant)
        code, out = pi("trace", *P(d), "--stage", "ux_spec")
        check(f"P12 추적성 오류 감지: {label}", code == 2 and expect in errs(out), out)
    write_spec(d, 1)
    code, out = pi("trace", *P(d), "--stage", "ux_spec")
    check("P12a 추적성 통과(AC 비UI 1건 집계)", code == 0 and out["counts"]["AC_non_ui"] == 1 and out["counts"]["FLOW_steps_mapped"] == 4, out)
    code, out = pi("submit", *P(d), "--stage", "ux_spec")
    check("P13 UX 설계 제출 r1", code == 0 and out["revision"] == 1, out)
    (d / UXP).write_text(approved00 + "\n승인 후 메모\n")
    code, out = pi("approve", *P(d), "--stage", "ux_spec", "--revision", "1")
    check("H1b 승인된 00 변경 → UX 설계 approve 차단", code == 2 and out.get("error") == "upstream_modified", out)
    (d / UXP).write_text(approved00)
    code, out = pi("approve", *P(d), "--stage", "ux_spec", "--revision", "1")
    check("P13a UX 설계 승인 → preview not_started", code == 0 and state(d)["stages"]["preview"]["status"] == "not_started", out)

    G(d, "add", "-A"); G(d, "commit", "-qm", "design approved (user commit)")
    orig02 = (d / SPEC[1]).read_text()
    rec02 = state(d)["stages"]["ux_spec"]["approved"]["hashes"][SPEC[1]]
    (d / SPEC[1]).write_text(orig02.replace("내 정보", "내 정보와 전적"))
    code, out = pi("check", *P(d))
    check("P14 승인된 02 외부 변경 → state_mismatch(approved_modified)", code == 2 and any(p["kind"] == "approved_modified" and SPEC[1] in p["paths"] for p in out["cross_verify"]["problems"]), out)
    check("P14a 해시 자동 재기록 없음", state(d)["stages"]["ux_spec"]["approved"]["hashes"][SPEC[1]] == rec02)
    code, out = pi("begin", *P(d), "--stage", "preview")
    check("H1c 승인된 02 변경 → 프리뷰 begin 차단(check 없이)", code == 2 and out.get("error") == "upstream_modified"
          and state(d)["stages"]["preview"]["status"] == "not_started", out)
    code2, out2 = pi("check", *P(d))
    check("P14b 변경이 남아 있는 동안 check 계속 차단", code2 == 2, out2)
    (d / SPEC[1]).write_text(orig02)
    code, out = pi("check", *P(d))
    check("P14c 복원 후 일치", code == 0, out)

    # 백업
    code, out = pi("backup", *P(d), "--path", SPEC[1])
    check("P15 Git 추적·clean 파일은 백업 없음", code == 0 and out["backup"] is None, out)

    # ---- 프리뷰
    s = state(d)
    if s["stages"]["preview"]["status"] != "in_progress":
        pi("begin", *P(d), "--stage", "preview")
    code, out = pi("preview-scaffold", *P(d))
    check("P16 프리뷰 템플릿 복사", code == 0 and (d / "design-preview/.gitignore").exists()
          and json.loads((d / "design-preview/preview.manifest.json").read_text())["ux_spec_revision"] == 1, out)
    code, out = pi("preview-scaffold", *P(d))
    check("P16a 프리뷰 폴더가 있으면 다시 만들지 않음", code == 2 and out.get("error") == "existing_files", out)
    code, out = pi("preview-check", *P(d))
    check("P16b 화면 파일·등록 누락 감지", code == 2 and "화면 파일이 없습니다" in errs(out), out)
    fill_preview(d, 1)
    code, out = pi("preview-check", *P(d))
    check("P16c 프리뷰 검사 통과", code == 0 and out["counts"]["screens_in_preview"] == 3, out)
    scr2 = d / "design-preview/src/screens/SCR-002.tsx"
    good = scr2.read_text()
    scr2.write_text("const r = fetch('/api/rounds')\n" + good)
    code, out = pi("preview-check", *P(d))
    check("P16d 실제 API 호출(fetch) 금지", code == 2 and "fetch" in errs(out), out)
    scr2.write_text("import { x } from '../../../frontend/src/lib/api'\n" + good)
    code, out = pi("preview-check", *P(d))
    check("P16e 제품 코드 import 금지", code == 2 and "frontend" in errs(out), out)
    scr2.write_text(good)
    (d / "frontend/src").mkdir(parents=True)
    (d / "frontend/src/bad.ts").write_text("import x from '../../design-preview/src/registry'\n")
    code, out = pi("preview-check", *P(d))
    check("P16f 제품 코드가 프리뷰를 참조하면 감지", code == 2 and "frontend/src/bad.ts" in errs(out), out)
    shutil.rmtree(d / "frontend")
    man_p = d / "design-preview/preview.manifest.json"
    man = json.loads(man_p.read_text()); man["ux_spec_revision"] = 99; man_p.write_text(json.dumps(man))
    code, out = pi("preview-check", *P(d))
    check("P16g manifest revision ≠ 승인된 UX 설계 revision 감지", code == 2 and "ux_spec_revision" in errs(out), out)
    man["ux_spec_revision"] = 1; man["screens"]["SCR-003"]["states"].append("SCR-003-ST8"); man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    code, out = pi("preview-check", *P(d))
    check("P16h 문서에 없는 상태 감지", code == 2 and "SCR-003-ST8" in errs(out), out)
    man["screens"]["SCR-003"]["states"].remove("SCR-003-ST8"); man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")

    # M3: 우회 참조 감지와 주석 오탐 방지
    vite_p = d / "design-preview/vite.config.ts"; ts_p = d / "design-preview/tsconfig.json"
    vite_ok, ts_ok = vite_p.read_text(), ts_p.read_text()
    check("M3 템플릿 프리뷰 포트 strictPort: true", "strictPort: true" in vite_ok)
    cases = (
        (scr2, "import { api } from '@fe/lib/api'\n" + good, "package.json에 없는 모듈", "별칭 import(@fe)"),
        (scr2, "export async function f() { return import('../../../frontend/src/x') }\n" + good, "프리뷰 폴더 밖", "동적 import로 frontend"),
        (scr2, "export const n = 'x'\nexport async function g() { return import(`../../${n}`) }\n" + good, "동적 참조", "정적 확인 불가 동적 import"),
        (scr2, "const mods = import.meta.glob('../../../frontend/src/**/*.tsx')\nexport { mods }\n" + good, "프리뷰 폴더 밖", "import.meta.glob"),
        (scr2, "// @ts-ignore\nconst m = require('../../../frontend/src/x')\nexport { m }\n" + good, "프리뷰 폴더 밖", "require"),
        (vite_p, vite_ok.replace("plugins: [react()],", "plugins: [react()],\n  resolve: { alias: { '@fe': path.resolve(__dirname, '../frontend/src') } },")
         .replace("import react", "import path from 'node:path'\nimport react"), "frontend", "vite alias → frontend"),
        (vite_p, vite_ok.replace("server: {", "server: { fs: { allow: ['..'] },"), "프리뷰 폴더 밖", "server.fs.allow 상위 폴더"),
        (ts_p, ts_ok.replace('"noEmit": true,', '"noEmit": true,\n    "baseUrl": ".",\n    "paths": { "@fe/*": ["../frontend/src/*"] },'), "frontend", "tsconfig paths → frontend"),
        (ts_p, ts_ok.replace('"compilerOptions": {', '"extends": "../frontend/tsconfig.app.json",\n  "compilerOptions": {'), "frontend", "tsconfig extends → frontend"),
    )
    for path_, content, expect, label in cases:
        orig_c = path_.read_text()
        path_.write_text(content)
        code, out = pi("preview-check", *P(d))
        check(f"M3a 우회 참조 감지: {label}", code == 2 and expect in errs(out), out)
        path_.write_text(orig_c)
    scr2.write_text("// fetch('/api/rounds') 는 쓰지 않습니다\n/* import x from '../../../frontend/src/x' */\n"
                    "const docs = 'https://example.com/a//b' // 주석 속 axios\nexport { docs }\n" + good)
    code, out = pi("preview-check", *P(d))
    check("M3b 주석·문자열 속 패턴은 오탐하지 않음", code == 0, out)
    scr2.write_text(good)
    (d / "frontend/src").mkdir(parents=True)
    (d / "frontend/src/note.ts").write_text("// design-preview 는 참고만 합니다\nexport const a = 1\n")
    (d / "frontend/vite.config.ts").write_text("export default { resolve: { alias: { '@pv': '../design-preview/src' } } }\n")
    code, out = pi("preview-check", *P(d))
    check("M3c 제품 설정의 프리뷰 참조 감지, 주석 언급은 무시", code == 2 and "frontend/vite.config.ts" in errs(out) and "note.ts" not in errs(out), out)
    shutil.rmtree(d / "frontend")
    code, out = pi("preview-check", *P(d))
    check("M3d 격리 검사 후 원상태 통과", code == 0, out)

    write_06(d, 1)
    pi("done", *P(d), "--path", "docs/design/06-preview-review.md")
    code, out = pi("submit", *P(d), "--stage", "preview")
    check("P17 빌드 검증 없이 프리뷰 제출 → 거부", code == 2 and out.get("error") == "preview_not_verified", out)
    have_pnpm = shutil.which("pnpm") is not None
    built = False
    (d / SPEC[1]).write_text(orig02 + "\n승인 후 메모\n")
    for cmd_args, label in ((("preview-verify",), "preview-verify"), (("done", "--path", "docs/design/06-preview-review.md"), "done"),
                            (("submit", "--stage", "preview"), "submit")):
        code, out = pi(cmd_args[0], *P(d), *cmd_args[1:])
        check(f"H1d 승인된 02 변경 → 프리뷰 {label} 차단", code == 2 and out.get("error") == "upstream_modified", out)
    (d / SPEC[1]).write_text(orig02)
    if have_pnpm:
        code, out = pi("preview-verify", *P(d))
        built = code == 0
        check("P17a preview-verify(pnpm install + build) 통과", built, out.get("steps") or out)
    else:
        skip("P17a preview-verify", "pnpm 없음")
    if built:
        code, out = pi("submit", *P(d), "--stage", "preview")
        check("P17b 프리뷰 제출 r1", code == 0 and out["revision"] == 1, out)
        (d / SPEC[1]).write_text(orig02 + "\n승인 후 메모\n")
        code, out = pi("approve", *P(d), "--stage", "preview", "--revision", "1")
        check("H1e 승인된 02 변경 → 시각 디자인 approve 차단", code == 2 and out.get("error") == "upstream_modified", out)
        (d / SPEC[1]).write_text(orig02)
        code, out = pi("approve", *P(d), "--stage", "preview", "--revision", "1")
        check("P17c 시각 디자인 승인 → 전체 approved", code == 0 and out["overall"] == "approved", out)
        reg = d / "design-preview/src/registry.tsx"
        orig_reg = reg.read_text()
        reg.write_text(orig_reg + "\n// 수정\n")
        code, out = pi("check", *P(d))
        check("P18 승인 후 프리뷰 파일 변경 → approved_modified", code == 2 and any(p["stage"] == "preview" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"]), out)
        reg.write_text(orig_reg)
        code, out = pi("check", *P(d))
        check("P18a 복원 후 일치(node_modules·dist는 해시 제외)", code == 0, out)
        code, out = pi("status", *P(d))
        check("P18b status: 전체 approved + state.yaml design 표시 설명", out["overall"] == "approved" and out["state_yaml_design_status"] == "not_started"
              and "design.json" in out["display_note"], out)

        # UX 설계 재검토 → 프리뷰 승인 무효화
        code, out = pi("reopen", *P(d), "--stage", "ux_spec", "--reason", "SCR-003 정보 추가")
        s = state(d)
        check("P19 UX 설계 reopen → 프리뷰 승인 무효(locked)", code == 0 and out["invalidated"] == ["preview"]
              and s["stages"]["preview"]["status"] == "locked" and s["stages"]["preview"]["approved"] is None
              and s["stages"]["preview"]["last_approved"]["revision"] == 1, out)
        code, out = pi("check", *P(d))
        check("P19a reopen 후 교차 검증 일치", code == 0, out)
        write_spec(d, 2)
        ia_p = d / SPEC[0]
        ia_p.write_text(ia_p.read_text() + "| SCR-004 | 설정 | /settings | 회원 | mobile | 회원 |\n")
        done_all(d, SPEC)
        code, out = pi("submit", *P(d), "--stage", "ux_spec")
        check("P19b 화면 구성이 바뀐 새 revision → 구조 확인 다시 필요", code == 2 and out.get("error") == "structure_not_confirmed"
              and "달라졌습니다" in out.get("message", ""), out)
        write_spec(d, 2)
        done_all(d, SPEC)
        code, out = pi("submit", *P(d), "--stage", "ux_spec")
        check("P19b2 화면 구성이 같으면 구조 확인을 이어받아 제출", code == 0 and out["revision"] == 2
              and state(d)["history"][-2]["event"] == "structure_carried", out)
        pi("approve", *P(d), "--stage", "ux_spec", "--revision", "2")
        pi("begin", *P(d), "--stage", "preview")
        code, out = pi("preview-check", *P(d))
        check("P19c 프리뷰 manifest가 이전 UX 설계 revision → 불일치 감지", code == 2 and "ux_spec_revision" in errs(out), out)
    else:
        skip("P17b–P19c", "프리뷰 빌드 불가")

    # ---- 결정 참조
    code, out = pi("refs", *P(d), "--id", "UXD-002")
    check("P20 refs: UXD-002를 참조하는 화면", code == 0 and "SCR-002" in out["references"], out)

    check("P21 /product-design 실행 중 state.yaml·planning 불변", sha(d / ".ai-workflow/state.yaml") == sy_before
          and all(sha(d / "docs/planning" / f) == h for f, h in plan_before.items()))

    # ---- 기획 변경: /product-start T9 → 재승인 (픽스처로 재현)
    G(d, "add", "-A"); G(d, "commit", "-qm", "design work (user commit)")
    design_snapshot = {p: sha(p) for p in (d / "docs/design").glob("*.md")}
    write_state_yaml(d, planning_status="in_progress", design_status="locked")
    code, out = pi("check", *P(d))
    check("P22 기획 재검토 중(state.yaml design locked) → 차단", code == 2 and out.get("error") == "planning_not_approved"
          and "locked" in out.get("message", ""), out)
    check("P22a 차단 중 디자인 문서 보존", all(sha(p) == h for p, h in design_snapshot.items()))
    p03 = d / "docs/planning/03-user-stories.md"
    p03.write_text(p03.read_text().replace("### US-002: 대진 생성", "### US-002: 대진 생성과 재생성"))
    p02 = d / "docs/planning/02-prd.md"
    p02.write_text(p02.read_text().replace("| C-02 | 혼복을 먼저 만든다 |", "| C-02 | 혼복을 먼저 만들고 남복·여복 순서 |"))
    write_state_yaml(d)
    G(d, "add", "-A"); G(d, "commit", "-qm", "planning r2 approved (fixture)")
    code, out = pi("check", *P(d))
    check("P23 기획 재승인 후 → design_outdated", code == 2 and out.get("error") == "design_outdated"
          and "docs/planning/03-user-stories.md" in out.get("changed", []), out)
    code, out = pi("submit", *P(d), "--stage", "preview")
    check("P23a outdated 동안 진행 명령 차단", code == 2 and out.get("error") == "design_outdated", out)
    code, out = pi("impact", *P(d))
    check("P23b impact: 바뀐 US-002와 참조 화면·결정 식별", code == 0 and "US-002" in out["changed_ids"]["changed"]
          and "SCR-002" in out["affected"] and "UXD-002" in out["affected"], out)
    check("M2a impact: 바뀐 확정 사항 C-02와 이를 참조하는 UXD 식별(C-01은 불변)", "C-02" in out["changed_ids"]["changed"]
          and "C-01" not in out["changed_ids"]["changed"] and "C-02" in out["affected"].get("UXD-002", []), out)
    code, out = pi("rebase", *P(d))
    check("P23c rebase는 사용자 확인 필요", code == 2 and out.get("error") == "confirm_required", out)
    code, out = pi("rebase", *P(d), "--confirm")
    s = state(d)
    check("P23d rebase → UX Planning 재검토, 하위 단계 잠금, 새 기준", code == 0 and s["validity"]["status"] == "valid"
          and s["stages"]["ux_planning"]["status"] == "in_progress" and s["stages"]["ux_spec"]["status"] == "locked"
          and s["stages"]["preview"]["status"] == "locked" and s["based_on"]["planning_hashes"]["docs/planning/03-user-stories.md"] == sha(p03), out)
    code, out = pi("check", *P(d))
    check("P23e rebase 후 교차 검증 일치", code == 0, out)

    # 백업(미커밋 변경 파일)
    (d / UXP).write_text((d / UXP).read_text() + "\n수정 중\n")
    code, out = pi("backup", *P(d), "--path", UXP)
    check("P24 미커밋 변경 파일은 단일 슬롯 백업", code == 0 and out["backup"] and (d / out["backup"]).exists(), out)

    # ---- Low 개선 회귀
    dl = make_product(root, "low")
    (dl / ".ai-workflow/design-notes.md").write_text("이전에 남은 메모\n"); G(dl, "add", "-A"); G(dl, "commit", "-qm", "notes")
    code, out = pi("check", *P(dl))
    code2, out2 = pi("start", *P(dl))
    check("L3 check와 start의 기존 파일 판정 일치(design-notes.md)", code == 0 and ".ai-workflow/design-notes.md" in out.get("existing_paths", [])
          and code2 == 2 and out2.get("error") == "existing_files", (out, out2))
    (dl / ".ai-workflow/design-notes.md").unlink(); G(dl, "add", "-A"); G(dl, "commit", "-qm", "rm notes")
    pi("start", *P(dl))
    write_00(dl, 1)
    p03l = dl / "docs/planning/03-user-stories.md"
    p03l.write_text(p03l.read_text() + "\n- 승인 후 수정\n")
    code, out = pi("done", *P(dl), "--path", UXP)
    check("L4 done도 planning 유효성 검증(승인 후 기획 수정 → 차단)", code == 2 and out.get("error") == "planning_not_approved", out)
    G(dl, "checkout", "--", "docs/planning/03-user-stories.md")
    code, out = pi("done", *P(dl), "--path", UXP)
    check("L4a 기획 복원 후 done 통과", code == 0, out)
    outside = root / "outside.txt"; outside.write_text("밖")
    (dl / "docs/design/link.md").symlink_to(outside)
    for bad in ("../outside.txt", str(outside), "docs/design/../../README.md", "docs/design/link.md"):
        code, out = pi("backup", *P(dl), "--path", bad)
        check(f"L5 backup 경로 이탈 방지: {bad.replace(str(root), '<tmp>')}", code == 2 and out.get("error") in ("invalid_path", "not_design_path"), out)
    code, out = pi("backup", *P(dl), "--path", "docs/design/./00-ux-decisions.md")
    check("L5a backup 경로 정규화(./)", code == 0 and out["backup"] and out["backup"].endswith("docs__design__00-ux-decisions.md"), out)
    code, out = pi("begin", *P(dl))
    check("L2 인자 오류도 JSON 응답", code == 2 and out.get("error") == "invalid_arguments", out)
    dj = make_product(root, "broken")
    (dj / ".ai-workflow/design.json").write_text("{}\n")
    code, out = pi("status", *P(dj))
    check("L2a 예상하지 못한 예외도 JSON 응답(internal_error)", code == 2 and out.get("error") == "internal_error", out)
    s_main = state(d)
    check("L6 구조 확인 기록에 쓰지 않는 해시 필드 없음(서명만)", all("hashes" not in (s_main["stages"]["ux_spec"].get("structure_confirmed") or {}) for _ in [0]), s_main["stages"]["ux_spec"].get("structure_confirmed"))

    # ---- 같은 단계의 승인 후 변경은 reopen으로 해결 가능(상위 단계 게이트에 걸리지 않음)
    dr = make_product(root, "reopen")
    pi("start", *P(dr)); write_00(dr, 1); pi("done", *P(dr), "--path", UXP); pi("submit", *P(dr), "--stage", "ux_planning")
    pi("approve", *P(dr), "--stage", "ux_planning", "--revision", "1")
    (dr / UXP).write_text((dr / UXP).read_text() + "\n승인 후 메모\n")
    code, out = pi("reopen", *P(dr), "--stage", "ux_planning", "--reason", "승인 후 변경 반영")
    check("H1f 같은 단계 승인 후 변경은 reopen 허용", code == 0 and out["status"] == "in_progress", out)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {root})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
