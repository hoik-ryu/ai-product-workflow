#!/usr/bin/env python3
"""/product-build M3.1·M3.2 테스트(자체 완결형): UI 대응표, 토큰 대응 검사·예외, UI Brief 생성, UI Plan 검증.

사례 프로젝트와 무관한 독립 픽스처(도서관 좌석 예약)를 씁니다. 화면 명세에 행동·입력·정보 표, 04에 토큰 표와 CMP 필드를 더해 만듭니다.
- 시나리오 A(기존 프로젝트): 기존 부품·토큰 파일이 있는 저장소 → 후보 탐색 → 사용자 확인 등록 → 계획의 중복 생성 차단 → 토큰 불일치·예외
- 시나리오 B(신규 프로젝트, v2 테마·Design Direction): 빈 대응표 → B0가 부품 생성·built 등록 → 코드 중복 탐지 → 테마 기준 토큰 비교
실행: python3 tests/product_build_ui_test.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_design_dd_test as DDT  # noqa: E402

results = T.results
check, pb, pd, G = T.check, T.pb, T.pd, T.G

PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["web/src"]
tests = ["web/src"]
components = ["web/src/components"]
exclude = ["node_modules"]
[execution]
max_retries = 3
lock_ttl_minutes = 30
[ui]
framework = "임의 스택(엔진은 해석하지 않음)"
api_contract = "api/contract.txt"
[ui.audit]
extensions = [".view", ".css"]
"""

ACTIONS = {
    "SCR-001": "| 좌석 선택 | 예약 확인으로 이동(SCR-002) | AC-003 |\n| 새로 고침 | 좌석 현황 다시 불러오기 | AC-001 |\n",
    "SCR-002": "| 예약 확정 | 확정 안내 후 내 예약 | AC-003 |\n",
}
TOKENS = ("| 토큰 | 값 | 용도 |\n|---|---|---|\n| color.bg | #FFFFFF | 배경 |\n| color.text | #1A1A1A | 본문 |\n"
          "| color.primary | #0E6B4F | 주요 행동 |\n| space.unit | 4px | 간격 |\n| radius.md | 8px | 모서리 |\n")


def enrich_design(d: Path) -> None:
    """픽스처 02·04에 화면 행동·입력·정보 표, 토큰 표, CMP 필드를 더합니다(승인 전)."""
    p = d / "docs/design/02-screens.md"
    text = p.read_text()

    def add(m):
        sid = m.group(1)
        acts = ACTIONS.get(sid, "| 목록 보기 | 목록 표시 | |\n")
        extra = ("### 정보와 우선순위\n| 순서 | 정보 | 출처(데이터) | 권한별 노출 |\n|---|---|---|---|\n| 1 | 좌석 번호·상태 | GET /api/seats | 이용자: 표시 |\n\n"
                 f"### 행동\n| 행동 | 결과 | 관련 |\n|---|---|---|\n{acts}\n")
        if sid == "SCR-002":
            extra += "### 입력과 검증\n| 입력 | 형식·제약 | 오류 메시지 |\n|---|---|---|\n| 이용 시간 | 1–4시간 | 이용 시간은 1–4시간입니다 |\n\n"
        return m.group(0) + extra
    text = re.sub(r"^## (SCR-\d{3}):.*?(?=^### 컴포넌트)", add, text, flags=re.M | re.S)
    p.write_text(text)
    u = d / "docs/design/04-ui-system.md"
    body = "# UI\n## 1. 디자인 토큰\n" + TOKENS + "\n## 2. 컴포넌트\n"
    for c, n, used in (("CMP-001", "Button", "SCR-001, SCR-002, SCR-003"), ("CMP-002", "SeatMap", "SCR-001, SCR-004"),
                       ("CMP-003", "DataTable", "SCR-003, SCR-004, SCR-005")):
        body += (f"### {c}: {n}\n- **용도**: {n}\n- **변형**: primary / secondary\n- **상태**: 기본, 비활성, 로딩\n"
                 f"- **사용 화면**: {used}\n- **접근성**: 레이블, 포커스, 터치 영역\n")
    u.write_text(T.fm("ui-system") + body)


def make_ui_product(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    G(d, "init", "-q")
    (d / "README.md").write_text("# 도서관 좌석 예약\n")
    (d / ".gitignore").write_text("node_modules/\n")
    T.write_planning(d, T.LIBRARY)
    G(d, "add", "-A"); G(d, "commit", "-qm", "approved planning")
    code, out = pd(d, "start"); assert code == 0, out
    T.write_design(d, T.LIBRARY)
    enrich_design(d)
    for args in (("done", "--path", "docs/design/00-ux-decisions.md"), ("submit", "--stage", "ux_planning"),
                 ("approve", "--stage", "ux_planning", "--revision", "1"), ("begin", "--stage", "ux_spec")):
        code, out = pd(d, *args); assert code == 0, (args, out)
    for f in T.SPEC:
        code, out = pd(d, "done", "--path", f); assert code == 0, (f, out)
    code, out = pd(d, "checkpoint"); assert code == 0, out
    code, out = pd(d, "submit", "--stage", "ux_spec"); assert code == 0, out
    code, out = pd(d, "approve", "--stage", "ux_spec", "--revision", "1"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "design (user commit)")
    return d


def w(d: Path, rel: str, text: str) -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def plan_for(b0_new: list[str], b1_reuse: list[str]) -> dict:
    return {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
        {"id": "B0", "title": "공통 부품", "kind": "foundation", "components": {"new": b0_new, "reuse": []},
         "paths": {"allow": ["web/src/components/"], "shared": ["web/src/styles/"]},
         "tasks": [{"id": "B0-T1", "layer": "fe", "title": "공통 부품", "refs": b0_new or ["CMP-002"]}]},
        {"id": "B1", "title": "좌석 현황·예약", "kind": "ui", "screens": ["SCR-001", "SCR-002"], "acs": ["AC-001", "AC-002", "AC-003", "AC-004"],
         "components": {"reuse": b1_reuse, "new": []}, "depends_on": ["B0"],
         "paths": {"allow": ["web/src/features/seats/", "web/src/mocks/"], "shared": []},
         "tasks": [{"id": "B1-T1", "layer": "api", "title": "좌석 조회 API 연결", "refs": ["AC-001"]},
                   {"id": "B1-T2", "layer": "fe", "title": "좌석 화면", "refs": ["SCR-001", "SCR-002"], "depends_on": ["B1-T1"]},
                   {"id": "B1-T3", "layer": "be", "title": "중복 예약 규칙", "refs": ["AC-004"]},
                   {"id": "B1-T4", "layer": "test", "title": "AC 테스트", "refs": ["AC-001", "AC-003"], "depends_on": ["B1-T2"]}],
         "test_plan": [{"ac": "AC-001", "kind": "unit"}, {"ac": "AC-002", "kind": "unit"}, {"ac": "AC-003", "kind": "integration"}]},
        {"id": "B2", "title": "예약 취소", "kind": "ui", "screens": ["SCR-003"], "acs": ["AC-005"], "depends_on": ["B1"],
         "components": {"reuse": ["CMP-001"], "new": ["CMP-003"]},
         "paths": {"allow": ["web/src/features/reservations/"], "shared": []},
         "tasks": [{"id": "B2-T1", "layer": "fe", "title": "내 예약·취소", "refs": ["SCR-003", "AC-005"]}]},
        {"id": "B3", "title": "좌석 관리", "kind": "ui", "screens": ["SCR-004"], "acs": ["AC-006", "AC-007"], "depends_on": ["B0"],
         "components": {"reuse": ["CMP-001", "CMP-002"], "new": []},
         "paths": {"allow": ["web/src/features/admin/"], "shared": []},
         "tasks": [{"id": "B3-T1", "layer": "fe", "title": "관리 화면", "refs": ["SCR-004"]}]},
    ]}


def approve_plan(d: Path, plan: dict) -> None:
    T.save_plan(d, plan)
    pb(d, "waiver", "add", "--reason", "배치 구현으로 시각 확인", "--all-ui", "--note", "프리뷰 없이 구현을 승인합니다", "--confirm")
    code, out = pb(d, "submit", "plan"); assert code == 0, out
    code, out = pb(d, "approve", "plan", "--revision", str(json.loads((d / ".ai-workflow/build.json").read_text())["plan"]["revision"]),
                   "--note", "구현 계획을 승인합니다"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "approved build plan (user)")


def good_ui_plan(brief_digest: str, button_part: str = "Button") -> dict:
    return {
        "format": "pb-ui-plan/v1", "batch": "B1", "brief_digest": brief_digest,
        "screens": {
            "SCR-001": {
                "tree": [{"part": "SeatStatusPage", "local": True, "file": "web/src/features/seats/SeatStatusPage.view", "children": [
                    {"part": "SeatMap", "cmp": "CMP-002"},
                    {"part": button_part, "cmp": "CMP-001"}]}],
                "states": {"SCR-001-ST1": {"how": "route", "ref": "/seats"}, "SCR-001-ST2": {"how": "prop", "ref": "loading=true"},
                           "SCR-001-ST3": {"how": "test", "ref": "seats 오류 응답 Mock"}},
                "interactions": [{"action": "좌석 선택", "trigger": "빈 좌석 누름", "result": "예약 확인으로 이동", "to_state": "SCR-002", "acs": ["AC-003"]},
                                 {"action": "새로 고침", "trigger": "당겨서 새로 고침", "result": "다시 불러오기", "to_state": "SCR-001-ST2", "acs": ["AC-001"]}],
                "data": [{"name": "seats", "source": "mock", "contract": "GET /api/seats", "task": "B1-T1", "mock_file": "web/src/mocks/seats.data"}],
                "acs": {"AC-001": {"states": ["SCR-001-ST1"], "tests": ["unit"]}, "AC-002": {"states": ["SCR-001-ST3"], "tests": ["unit"]}},
                "visual_ref": "design-preview/src/screens/SCR-001.tsx",
            },
            "SCR-002": {
                "tree": [{"part": "ReserveConfirm", "local": True, "file": "web/src/features/seats/ReserveConfirm.view", "children": [
                    {"part": button_part, "cmp": "CMP-001"}]}],
                "states": {"SCR-002-ST1": {"how": "route", "ref": "/seats/A1/reserve"}, "SCR-002-ST2": {"how": "prop", "ref": "submitting"},
                           "SCR-002-ST3": {"how": "test", "ref": "409 응답"}},
                "interactions": [{"action": "예약 확정", "trigger": "확정 버튼", "result": "확정 안내", "to_state": "SCR-003", "acs": ["AC-003"]}],
                "data": [{"name": "reserve", "source": "api", "contract": "POST /api/reservations", "task": "B1-T1"}],
                "acs": {"AC-003": {"states": ["SCR-002-ST1"], "tests": ["integration"]}},
            },
        },
        "components": {"CMP-001": {"action": "reuse", "part": button_part}, "CMP-002": {"action": "reuse", "part": "SeatMap"}},
        "notes": [],
    }


def errs(out: dict) -> str:
    return " / ".join(out.get("errors", [])) or out.get("error", "") or str(out)[:300]


def has(out: dict, code: str) -> bool:
    return any(e.startswith(f"[{code}]") for e in out.get("errors", []))


def write_ui_plan(d: Path, plan: dict) -> None:
    w(d, ".ai-workflow/build/ui/B1/plan.json", json.dumps(plan, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 시나리오 A: 기존 프로젝트(기존 부품·토큰)
def scenario_existing(root: Path) -> None:
    d = make_ui_product(root, "lib-existing")
    w(d, "web/src/components/Button.view", "export function Button(props) { return render('button', props) }\n")
    w(d, "web/src/components/Badge.view", "// CMP-003 데이터 표(사내 기존 부품)\nexport const DataGrid = (p) => p\n")
    w(d, "web/src/styles/tokens.css", ":root {\n  --brand-green: #0E6B4F;\n  --color-bg: #fff;\n  --color-text: #1a1a1a;\n"
      "  --color-primary: var(--brand-green);\n  --space-unit: 4px;\n  --radius-md: 6px;\n}\n")
    w(d, "api/contract.txt", "GET /api/seats\nPOST /api/reservations\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    snap = T.protected_snapshot(d)

    code, out = pb(d, "ui-map", "show")
    check("A1 대응표 없음: 안내만(기존 동작 그대로)", code == 0 and out["exists"] is False, out)
    code, out = pb(d, "ui-map", "candidates")
    c = {x["cmp"]: x for x in out.get("unmapped", [])}
    check("A2 기존 부품 탐색: 이름 일치(Button→CMP-001)·CMP 표지(CMP-003) 후보, 후보일 뿐이라는 안내",
          code == 0 and [y["path"] for y in c["CMP-001"]["candidates"]] == ["web/src/components/Button.view"]
          and c["CMP-003"]["candidates"][0]["why"] == "CMP 표지" and not c["CMP-002"]["candidates"] and "사용자 확인" in out["note"], out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Button")
    check("A3 기존 부품 등록은 사용자 확인 문장 필요", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Btn", "--note", "확인")
    check("A4 내보낸 이름이 파일에 없으면 거부", code == 2 and out.get("error") == "export_not_found", out)
    w(d, "design-preview/src/Button.view", "export function Button() {}\n")
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "design-preview/src/Button.view", "--export", "Button", "--note", "확인")
    check("A5 디자인 프리뷰 코드는 제품 부품으로 등록 불가(시각 참고만)", code == 2 and out.get("error") == "preview_reuse", out)
    shutil.rmtree(d / "design-preview")
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-009", "--path", "web/src/components/Button.view", "--export", "Button", "--note", "확인")
    check("A6 04에 없는 CMP 등록 거부", code == 2 and out.get("error") == "unknown_cmp", out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Button",
                   "--note", "기존 Button을 CMP-001로 재사용합니다")
    check("A7 기존 부품 등록(사용자 확인 문장 기록)", code == 0 and out["entry"]["source"] == "existing" and out["entry"]["note"], out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Badge.view", "--export", "DataGrid", "--note", "x")
    check("A8 이미 대응된 CMP는 --replace 없이 바꿀 수 없음", code == 2 and out.get("error") == "already_mapped", out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-003", "--source", "library", "--export", "DataTable", "--note", "x")
    check("A9 라이브러리 부품은 package 필요", code == 2 and out.get("error") == "invalid_arguments", out)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-003", "--source", "library", "--package", "some-ui-kit@2", "--export", "DataTable",
                   "--note", "사내 UI 키트의 DataTable을 씁니다")
    check("A10 라이브러리 부품 등록(프레임워크·라이브러리 이름은 프로젝트 기록일 뿐)", code == 0 and out["entry"]["package"] == "some-ui-kit@2", out)

    # 계획: 이미 대응된 CMP-001을 B0가 새로 만들려 함 → 차단
    T.save_plan(d, plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"]))
    code, out = pb(d, "plan-validate")
    check("A11 계획 검증: 대응표의 기존 부품을 새로 만드는 계획 → cmp_already_mapped", code == 2 and has(out, "cmp_already_mapped")
          and "CMP-001" in errs(out), errs(out))
    bad = plan_for(["CMP-002"], ["CMP-001", "CMP-002"])
    bad["batches"][2]["components"]["new"] = ["CMP-003"]
    T.save_plan(d, bad)
    code, out = pb(d, "plan-validate")
    check("A12 라이브러리로 대응된 CMP-003을 B2가 새로 만들려 함 → 차단", code == 2 and has(out, "cmp_already_mapped") and "CMP-003" in errs(out), errs(out))
    good = plan_for(["CMP-002"], ["CMP-001", "CMP-002"])
    good["batches"][2]["components"] = {"reuse": ["CMP-001", "CMP-003"], "new": []}
    approve_plan(d, good)
    code, out = pb(d, "ui-map", "check")
    check("A13 수정한 계획 승인 후 대응표 검사 통과", code == 0 and out["counts"]["unmapped"] == ["CMP-002"], out)

    # 토큰
    code, out = pb(d, "token-check")
    check("A14 토큰 출력 미설정 → 안내와 함께 차단", code == 2 and out.get("error") == "tokens_not_configured", out)
    code, out = pb(d, "ui-map", "tokens", "--file", "design-preview/src/tokens.css", "--note", "x")
    check("A15 토큰 출력을 프리뷰 파일로 설정 불가", code == 2 and out.get("error") == "token_output_invalid", out)
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--alias", "color.brand=--x", "--note", "x")
    check("A16 승인되지 않은 토큰 이름에 별칭 불가", code == 2 and out.get("error") == "unknown_token", out)
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "기존 tokens.css를 기준으로 합니다")
    check("A17 토큰 출력 설정(css-vars, 기본 변수 규칙 --{dashed})", code == 0 and out["tokens"]["var_pattern"] == "--{dashed}", out)
    code, out = pb(d, "token-check")
    mm = {m["token"]: m for m in out.get("mismatch", [])}
    check("A18 토큰 비교: var() 참조 해석·#fff 정규화로 일치, radius.md 값 불일치 보고", code == 2 and list(mm) == ["radius.md"]
          and mm["radius.md"]["actual"] == "6px" and out["counts"]["matched"] == 4 and "--brand-green" in out["extra"]
          and out["source"] == "docs/design/04-ui-system.md", out)
    code, out = pb(d, "ui-map", "except", "--token", "radius.md", "--note", "허용")
    check("A19 예외는 사유 필요", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(d, "ui-map", "except", "--token", "radius.md", "--reason", "기존 브랜드 가이드 6px 유지(다음 개편 때 맞춤)",
                   "--note", "radius.md는 6px로 두는 것을 허용합니다")
    code, out = pb(d, "token-check")
    check("A20 프로젝트 허용 예외 → 통과, 예외 항목과 사유는 따로 보고", code == 0 and out["excepted"][0]["token"] == "radius.md"
          and out["excepted"][0]["reason"].startswith("기존 브랜드"), out)
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--alias", "color.primary=--brand-green",
                   "--note", "primary는 브랜드 변수명을 씁니다")
    code, out = pb(d, "token-check")
    check("A21 별칭(토큰 → 프로젝트 변수명) 대응", code == 0 and out["counts"]["matched"] == 4, out)
    w(d, "web/src/styles/tokens.css", (d / "web/src/styles/tokens.css").read_text().replace("  --space-unit: 4px;\n", ""))
    code, out = pb(d, "token-check")
    check("A22 승인 토큰 변수 누락 → missing", code == 2 and [m["token"] for m in out["missing"]] == ["space.unit"], out)
    w(d, "tools/tokens.sh", 'echo \'{"color.bg": "#FFFFFF", "color.text": "#1A1A1A", "color.primary": "#0E6B4F", "space.unit": "4px", "radius.md": "8px"}\'\n')
    code, out = pb(d, "ui-map", "tokens", "--format", "command", "--export-cmd", "sh tools/tokens.sh", "--note", "토큰은 내보내기 명령으로 확인")
    code, out = pb(d, "token-check")
    check("A23 다른 형식은 프로젝트 어댑터 명령(JSON 출력)으로 비교", code == 0 and out["format"] == "command" and out["counts"]["matched"] == 5
          and out["stale_exceptions"] == [], out)
    w(d, "tools/tokens.sh", "echo not-json\n")
    code, out = pb(d, "token-check")
    check("A24 어댑터 출력이 JSON이 아니면 차단(통과로 보지 않음)", code == 2 and out.get("error") == "token_export_failed", out)
    pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "다시 CSS 기준")

    # 직접 값 감사
    w(d, "web/src/features/seats/SeatStatusPage.view", "const s = { color: '#ff0000', gap: 'var(--space-unit)' }\n// 주석 속 #123456은 무시\n")
    w(d, "web/src/features/admin/Admin.view", "const c = 'rgb(1, 2, 3)'\n")
    code, out = pb(d, "token-audit", "--batch", "B1")
    check("A25 직접 색 값 감사(배치 범위만, 주석 제외, 기본 경고)", code == 0 and [f["value"] for f in out["findings"]] == ["#ff0000"]
          and out["mode"] == "warn", out)
    code, out = pb(d, "ui-map", "except", "--audit-path", "web/src/features/seats/*", "--value", "#FF0000",
                   "--reason", "경고 색은 법적 표시 규정", "--note", "허용합니다")
    code, out = pb(d, "token-audit")
    check("A26 감사 예외(경로·값) 적용, 전체 범위에선 다른 파일 직접 값 보고", code == 0 and out["counts"] == {"findings": 1, "excepted": 1}
          and out["findings"][0]["file"] == "web/src/features/admin/Admin.view", out)
    (d / "docs/build/build-profile.toml").write_text(PROFILE + 'mode = "block"\n')
    code, out = pb(d, "token-audit")
    check("A27 프로필에서 차단 모드 선택 가능", code == 2 and not out["ok"], out)
    (d / "docs/build/build-profile.toml").write_text(PROFILE + 'mode = "strict"\n')
    code, out = pb(d, "token-audit")
    check("A28 [ui] 프로필 값 검증", code == 2 and out.get("error") == "profile_invalid", out)
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    check("A29 프로필 [ui] 추가는 계획 승인 해시 대상 파일이 그대로면 계획 상태 불변", pb(d, "check")[0] == 0)

    # ---- M3.2 UI Brief / UI Plan
    code, out = pb(d, "ui-brief", "--batch", "B1")
    s1 = out.get("summary", {}).get("screens", {}).get("SCR-001", {})
    check("A30 UI Brief 생성(엔진): 화면별 정의 상태·행동·AC, 컴포넌트 역할(대응표 재사용·선행 배치 신규)",
          code == 0 and s1 == {"states_defined": 3, "actions": 2, "acs": ["AC-001", "AC-002"], "vd": []}
          and out["summary"]["components"] == {"CMP-001": "reuse_mapped", "CMP-002": "new_in:B0"} and "skeleton" in out, out)
    brief = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())
    sb2 = brief["screens"]["SCR-002"]
    check("A31 Brief 내용: 입력·정보·필수 상태(Must 화면), 데이터 작업·계약 파일, 토큰 출처, 규칙",
          sb2["inputs"][0]["input"] == "이용 시간" and brief["screens"]["SCR-001"]["info"][0]["source"] == "GET /api/seats"
          and all(x["required"] for x in sb2["states"] if x["defined"]) and [t["id"] for t in brief["data"]["tasks"]] == ["B1-T1", "B1-T3"]
          and brief["data"]["api_contract"]["exists"] and brief["tokens"]["source"] == "docs/design/04-ui-system.md"
          and any("design-preview" in r for r in brief["rules"]), brief.get("warnings"))
    check("A32 화면별 문서를 새로 만들지 않음(UI 기록은 .ai-workflow/build/ui/만)",
          not (d / "docs/build/ui").exists() and sorted(p.name for p in (d / ".ai-workflow/build/ui/B1").iterdir()) == ["brief.json"])
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A33 UI Plan 없음 → Claude 작성 안내", code == 2 and out.get("error") == "no_ui_plan", out)
    good = good_ui_plan(brief["digest"])
    write_ui_plan(d, good)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A34 올바른 UI Plan 통과(시각 참고 visual_ref는 허용), 검증 기록 저장", code == 0 and out["ok"]
          and (d / ".ai-workflow/build/ui/B1/validation.json").exists(), errs(out))

    def bad_case(label, mutate, code_):
        p = json.loads(json.dumps(good))
        mutate(p)
        write_ui_plan(d, p)
        c2, o2 = pb(d, "ui-plan-validate", "--batch", "B1")
        check(f"A35 UI Plan 오류 검출: {label}", c2 == 2 and has(o2, code_), errs(o2))

    bad_case("정의된 상태 누락", lambda p: p["screens"]["SCR-001"]["states"].pop("SCR-001-ST3"), "state_missing")
    bad_case("없는 상태", lambda p: p["screens"]["SCR-001"]["states"].update({"SCR-001-ST9": {"how": "route", "ref": "x"}}), "state_unknown")
    bad_case("상태 재현 방법 없음", lambda p: p["screens"]["SCR-001"]["states"]["SCR-001-ST2"].update(how=""), "state_how")
    bad_case("대응된 부품을 로컬로 새로 만듦", lambda p: p["screens"]["SCR-001"]["tree"][0]["children"][1].update(local=True), "cmp_mapped_rebuilt")
    bad_case("대응표와 다른 부품 이름", lambda p: p["screens"]["SCR-002"]["tree"][0]["children"][0].update(part="MyButton"), "cmp_part_mismatch")
    bad_case("계획에 없는 CMP", lambda p: p["screens"]["SCR-001"]["tree"][0]["children"].append({"part": "Grid", "cmp": "CMP-003"}) or
             p["components"].update({"CMP-003": {"action": "reuse"}}), "cmp_unplanned")
    bad_case("대응된 부품과 같은 이름의 로컬 부품", lambda p: p["screens"]["SCR-001"]["tree"][0]["children"].append({"part": "Button", "local": True}),
             "duplicate_of_mapped")
    bad_case("배치 범위 밖 파일", lambda p: p["screens"]["SCR-001"]["tree"][0].update(file="web/src/other/Page.view"), "out_of_scope_file")
    bad_case("프리뷰 코드를 입력으로 사용", lambda p: p["screens"]["SCR-001"]["tree"][0].update(file="design-preview/src/screens/SCR-001.tsx"),
             "preview_reuse")
    bad_case("02 행동 누락", lambda p: p["screens"]["SCR-001"]["interactions"].pop(1), "action_missing")
    bad_case("명세에 없는 행동(원장 없음)", lambda p: p["screens"]["SCR-002"]["interactions"].append({"action": "공유하기"}), "action_unspecified")
    bad_case("없는 상태로 전이", lambda p: p["screens"]["SCR-001"]["interactions"][1].update(to_state="SCR-001-ST7"), "interaction_state")
    bad_case("API 데이터 계약 없음", lambda p: p["screens"]["SCR-002"]["data"][0].update(contract=""), "data_contract_missing")
    bad_case("Mock 파일이 배치 밖", lambda p: p["screens"]["SCR-001"]["data"][0].update(mock_file="web/mock/seats.data"), "mock_out_of_scope")
    bad_case("관련 없는 작업 참조", lambda p: p["screens"]["SCR-001"]["data"][0].update(task="B3-T1"), "data_task_unknown")
    bad_case("화면에 연결된 AC 누락", lambda p: p["screens"]["SCR-001"]["acs"].pop("AC-002"), "ac_unlinked")
    bad_case("배치 밖 AC", lambda p: p["screens"]["SCR-001"]["acs"].update({"AC-005": {"states": []}}), "ac_not_in_batch")
    bad_case("소유 화면 계획 누락", lambda p: p["screens"].pop("SCR-002"), "screen_missing")
    bad_case("다른 Brief 기준", lambda p: p.update(brief_digest="0" * 64), "brief_stale")
    bad_case("계획에 없는 신규 부품", lambda p: p["components"].update({"CMP-001": {"action": "new"}}), "cmp_new_not_planned")
    p = json.loads(json.dumps(good))
    p["screens"]["SCR-002"]["interactions"].append({"action": "공유하기", "ledger": "POL-001"})
    write_ui_plan(d, p)
    code, out = pb(d, "ledger", "add", "--type", "policy", "--title", "공유 기능 여부", "--batches", "B1", "--rationale", "명세에 없음", "--by", "claude")
    c2, o2 = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A36 명세에 없는 행동은 원장 등록 후에만 계획에 둘 수 있음", code == 0 and c2 == 0, errs(o2))
    p["screens"]["SCR-001"]["data"][0]["contract"] = "GET /api/unknown"
    write_ui_plan(d, p)
    c2, o2 = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A37 계약 파일에 없는 contract는 경고", c2 == 0 and any(x.startswith("[contract_not_found]") for x in o2["warnings"]), o2)
    write_ui_plan(d, good)
    braw = (d / ".ai-workflow/build/ui/B1/brief.json").read_text()
    (d / ".ai-workflow/build/ui/B1/brief.json").write_text(braw.replace('"좌석 현황"', '"좌석 현황(수정)"', 1))
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A38 엔진이 만든 Brief를 직접 고치면 거부(brief_modified)", code == 2 and out.get("error") == "brief_modified", out)
    (d / ".ai-workflow/build/ui/B1/brief.json").write_text(braw)
    pb(d, "ui-map", "register", "--cmp", "CMP-002", "--path", "web/src/components/Button.view", "--export", "Button",
       "--note", "임시로 같은 부품(대응표 변경 → Brief 변경)")
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("A39 대응표가 바뀌면 Brief가 낡음(brief_stale) → ui-brief 재생성 필요", code == 2 and has(out, "brief_stale"), errs(out))
    pb(d, "ui-map", "remove", "--cmp", "CMP-002", "--note", "되돌림")
    code, out = pb(d, "ui-brief", "--batch", "B0")
    check("A40 화면 없는 foundation 배치도 컴포넌트 Brief 생성", code == 0 and out["summary"]["components"] == {"CMP-002": "new_here"}, out)
    code, out = pb(d, "ui-brief", "--batch", "B9")
    check("A41 계획에 없는 배치 → 차단", code == 2 and out.get("error") == "unknown_batch", out)
    check("A42 승인 문서·state.yaml·design.json 불변", T.protected_snapshot(d) == snap)


# ---------------------------------------------------------------- 시나리오 B: 신규 프로젝트(v2 테마·Design Direction)
THEME = "design-profile/theme.json"


def scenario_new(root: Path) -> None:
    d = make_ui_product(root, "lib-new")
    w(d, THEME, json.dumps({"schema": "design-theme/v1", "name": "lib-light", "version": "1.0.0",
                            "primitives": {"blue-700": "#1D5BD0", "white": "#FFFFFF"},
                            "tokens": {"color.primary": "{blue-700}", "color.bg": "{white}"},
                            "css": {"file": "design-preview/src/tokens.css", "var_pattern": "--{dashed}"}}, indent=2))
    G(d, "add", "-A"); G(d, "commit", "-qm", "theme (user)")
    code, out = pd(d, "migrate", "--to", "v2", "--theme-file", THEME, "--confirm"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "v2 (user)")
    code, out = pd(d, "begin", "--stage", "design_direction"); assert code == 0, out
    DDT.write_07(d, 1, vd1_rel="SCR-001, CMP-002, UXD-001")
    for args in (("done", "--path", DDT.DD), ("submit", "--stage", "design_direction"), ("approve", "--stage", "design_direction", "--revision", "1")):
        code, out = pd(d, *args); assert code == 0, (args, out)
    G(d, "add", "-A"); G(d, "commit", "-qm", "design direction (user)")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    w(d, "api/contract.txt", "GET /api/seats\nPOST /api/reservations\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "profile")
    snap = T.protected_snapshot(d)
    code, out = pb(d, "ui-map", "candidates")
    check("B1 신규 프로젝트: 기존 부품 후보 없음", code == 0 and all(not x["candidates"] for x in out["unmapped"]) and len(out["unmapped"]) == 3, out)
    approve_plan(d, plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"]))
    code, out = pb(d, "ui-brief", "--batch", "B1")
    brief = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())
    check("B2 Brief: 승인된 VD(Design Direction)를 화면에 연결, 제외 VD 제외, 테마 기준 토큰",
          code == 0 and [v["id"] for v in brief["screens"]["SCR-001"]["vd"]] == ["VD-001"] and brief["screens"]["SCR-002"]["vd"] == []
          and brief["tokens"]["source"] == f"theme:{THEME}" and brief["tokens"]["approved"]["color.primary"] == "#1D5BD0"
          and brief["components"]["CMP-001"]["role"] == "new_in:B0", brief.get("screens", {}).get("SCR-001", {}).get("vd"))
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "brief")
    lock = DDT_start(d, "B0")
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(p) { return p }\n")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    w(d, "web/src/styles/tokens.css", ":root {\n  --color-bg: #FFFFFF;\n  --color-text: #1A1A1A;\n  --color-primary: #0E6B4F;\n  --space-unit: 4px;\n  --radius-md: 8px;\n}\n")
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-003", "--source", "built", "--batch", "B0", "--path", "web/src/components/Button.view",
                   "--export", "Button")
    check("B3 계획에 없는 신규 부품은 built 등록 불가", code == 2 and out.get("error") == "not_planned_new", out)
    w(d, "web/src/features/seats/Button.view", "export function Button() {}\n")
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--source", "built", "--batch", "B0", "--path", "web/src/features/seats/Button.view",
                   "--export", "Button")
    check("B4 배치 범위 밖 파일은 built 등록 불가", code == 2 and out.get("error") == "out_of_scope", out)
    (d / "web/src/features/seats/Button.view").unlink()
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--source", "built", "--batch", "B0", "--path", "web/src/components/Button.view",
                   "--export", "Button")
    check("B5 B0가 만든 부품을 built로 등록(배치 기록)", code == 0 and out["entry"]["built_by"] == "B0", out)
    for t in [x for x, v in json.loads((d / ".ai-workflow/build.json").read_text())["batches"]["B0"]["run"]["tasks"].items() if v["status"] != "done"]:
        pb(d, "task-done", "--batch", "B0", "--task", t, "--lock", lock)
    code, out = pb(d, "batch-submit", "--batch", "B0", "--lock", lock); assert code == 0, out
    code, out = pb(d, "ui-map", "check")
    check("B6 배치 완료 후 신규 부품 미등록 → new_not_registered", code == 2 and has(out, "new_not_registered") and "CMP-002" in errs(out), errs(out))
    pb(d, "ui-map", "register", "--cmp", "CMP-002", "--source", "built", "--batch", "B0", "--path", "web/src/components/SeatMap.view", "--export", "SeatMap")
    code, out = pb(d, "ui-map", "check")
    check("B7 등록 후 대응표 검사 통과", code == 0, errs(out))
    code, out = pb(d, "plan-validate")
    check("B8 B0 자신이 만든(built_by) 부품은 계획 재검증에서 중복으로 보지 않음", code == 0, errs(out))
    p2 = plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"])
    p2["batches"][3]["components"] = {"reuse": [], "new": ["CMP-002"]}
    T.save_plan(d, p2)
    code, out = pb(d, "plan-validate")
    check("B9 다른 배치가 B0의 부품을 다시 새로 만들려 함 → 차단(계획 단계)", code == 2 and has(out, "cmp_already_mapped") and "B0가 이미" in errs(out), errs(out))
    T.save_plan(d, plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"]))
    w(d, "web/src/features/seats/MySeatMap.view", "// CMP-002 화면 전용 좌석 지도\nexport const MySeatMap = 1\n")
    w(d, "web/src/features/seats/SeatMap.view", "export const SeatMap = 2\n")
    code, out = pb(d, "ui-map", "check", "--batch", "B1")
    check("B10 코드 단계 중복 탐지: 대응된 CMP 표지를 가진 다른 파일(오류)·같은 이름 파일(경고)", code == 2 and has(out, "duplicate_component")
          and out["duplicates"][0]["file"] == "web/src/features/seats/MySeatMap.view"
          and any(x.startswith("[possible_duplicate]") for x in out["warnings"]), out)
    for f in ("MySeatMap.view", "SeatMap.view"):
        (d / "web/src/features/seats" / f).unlink()
    pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "B0의 tokens.css를 기준으로 합니다")
    code, out = pb(d, "token-check")
    check("B11 v2 테마 기준 비교: 테마가 바꾼 color.primary 불일치 보고, 기대 CSS 제공", code == 2 and out["source"] == f"theme:{THEME}"
          and [m["token"] for m in out["mismatch"]] == ["color.primary"] and "--color-primary: #1D5BD0;" in out["expected_css"], out)
    w(d, "web/src/styles/tokens.css", out["expected_css"])
    code, out = pb(d, "token-check")
    check("B12 기대 CSS로 맞추면 통과(신규 프로젝트 토큰 구성)", code == 0 and out["counts"]["matched"] == 5, out)
    code, out = pb(d, "ui-brief", "--batch", "B1")
    write_ui_plan(d, good_ui_plan(out["digest"]))
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("B13 신규 프로젝트: 등록된 부품(built) 기준으로 UI Plan 통과", code == 0, errs(out))
    check("B14 승인 문서·state.yaml·design.json·테마 불변", T.protected_snapshot(d) == snap)


def DDT_start(d: Path, bid: str) -> str:
    code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t")
    assert code == 0, out
    return out["lock_id"]


# ---------------------------------------------------------------- 정적 검사
def static_checks() -> None:
    sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
    import pb_ui  # noqa: E402
    writers = {"save_state", "add_history", "detect_outdated", "write_owned", "backup_file", "invalidate_downstream"}
    check("S1 product-design에서 가져오는 테마 함수는 읽기 전용뿐", not (set(pb_ui.PD_THEME_IMPORTS) & writers), pb_ui.PD_THEME_IMPORTS)
    src = (T.ENGINE / "skills/product-build/scripts/pb_ui.py").read_text()
    code_only = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    stacks = [x for x in ("react", "next.js", "nextjs", "vite", "tailwind", "playwright", "storybook", "angular", "mui", "chakra")
              if re.search(rf"\b{re.escape(x)}\b", code_only, re.I)]
    check("S2 UI 모듈에 프레임워크·UI 라이브러리 이름 없음(파일 확장자 기본 목록 제외)", not stacks, stacks)
    check("S3 정규화: #fff = #FFFFFF, 공백·대소문자", pb_ui.norm("#fff") == pb_ui.norm("#FFFFFF") and pb_ui.norm(" 4PX ") == "4px")
    check("S4 같은 파일 var() 참조 해석", pb_ui.resolve_vars({"--a": "#111", "--b": "var(--a)", "--c": "var(--b)", "--d": "var(--zz)"})
          == {"--a": "#111", "--b": "#111", "--c": "#111", "--d": "var(--zz)"})


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-ui-test-"))
    try:
        static_checks()
        scenario_existing(root)
        scenario_new(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
