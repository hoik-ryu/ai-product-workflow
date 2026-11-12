#!/usr/bin/env python3
"""/product-build M2.1 스크립트 테스트(자체 완결형).

임시 디렉터리에 도메인이 다른 가상 제품 2종을 만들고, 기획 승인은 픽스처(state.yaml)로, UX 설계 승인은
실제 /product-design CLI(start → done → submit → approve)로 기록한 뒤 /product-build를 검사합니다.

- 도메인 A(도서관 좌석 예약): v1, UX Spec 승인 + 프리뷰 미승인(L2) → preview waiver 경로
- 도메인 B(동네 의원 진료 예약): IA에 셸 열 없음, 프리뷰 승인(L3)을 픽스처로 기록(product-design status가 일관성을 확인)
- 도메인 A' (UX Spec 미승인, L1): 화면 없는 DB/API 배치만 허용
- LLM이 쓸 계획 JSON은 테스트가 scope --draft 골격을 다듬어 대신 작성합니다.

실행: python3 tests/product_build_test.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # 엔진 모듈을 직접 import해도 __pycache__를 만들지 않음
HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
PB = ENGINE / "skills/product-build/scripts/product_build.py"
PD = ENGINE / "skills/product-design/scripts/product_design.py"
results: list[tuple[str, bool, str]] = []


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:700]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def run(script, *args):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")})
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def pb(d, *args):
    return run(PB, *args, "--project", str(d))


def pd(d, *args):
    return run(PD, *args, "--project", str(d))


def G(d, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=d,
                          capture_output=True, text=True, check=True).stdout


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fm(doc, rev=1):
    return f"---\ndoc: {doc}\nrevision: {rev}\nlanguage: ko\n---\n"


# ---------------------------------------------------------------- 도메인 명세(픽스처 생성기 입력)
LIBRARY = {
    "frs": [("FR-001", "좌석 현황 조회", "Must"), ("FR-002", "좌석 예약", "Must"), ("FR-003", "예약 취소", "Must"),
            ("FR-004", "관리자 좌석 관리", "Must"), ("FR-005", "이용 통계", "Should"), ("FR-006", "예약 규칙 서버 검증", "Must")],
    "us": [("US-001", "좌석 현황 보기", "Must", ["FR-001"]), ("US-002", "좌석 예약", "Must", ["FR-002", "FR-006"]),
           ("US-003", "예약 취소", "Must", ["FR-003"]), ("US-004", "좌석 관리", "Must", ["FR-004"]),
           ("US-005", "이용 통계 보기", "Should", ["FR-005"])],
    "acs": [("AC-001", "US-001", "좌석 지도에 빈 좌석이 표시된다", "SCR-001-ST1"),
            ("AC-002", "US-001", "빈 좌석이 없으면 대기 안내가 보인다", "SCR-001-ST3"),
            ("AC-003", "US-002", "좌석을 고르면 예약이 확정된다", "SCR-002-ST1"),
            ("AC-004", "US-002", "같은 시간 중복 예약은 서버가 거부한다", "비UI: 서버 예약 규칙"),
            ("AC-005", "US-003", "내 예약을 삭제하면 좌석이 다시 비어 보인다", "SCR-003-ST1"),
            ("AC-006", "US-004", "관리자 권한이 없는 사용자는 좌석 관리에 들어갈 수 없다", "SCR-004-ST3"),
            ("AC-007", "US-004", "관리자는 좌석을 추가할 수 있다", "SCR-004-ST1"),
            ("AC-008", "US-005", "월별 이용률이 표시된다", "SCR-005-ST1")],
    "flows": [("FLOW-001", [("FLOW-001-S1", "SCR-001"), ("FLOW-001-S2", "SCR-002")]), ("FLOW-002", [("FLOW-002-S1", "SCR-003")]),
              ("FLOW-003", [("FLOW-003-S1", "SCR-004")])],
    "screens": [("SCR-001", "좌석 현황", "/seats", "이용자", "mobile", ["US-001"], ["CMP-001", "CMP-002"]),
                ("SCR-002", "예약 확인", "/seats/:seatId/reserve", "이용자", "mobile", ["US-002"], ["CMP-001"]),
                ("SCR-003", "내 예약", "/me/reservations", "이용자", "mobile", ["US-003"], ["CMP-001", "CMP-003"]),
                ("SCR-004", "좌석 관리", "/admin/seats", "관리", "responsive", ["US-004"], ["CMP-002", "CMP-003"]),
                ("SCR-005", "이용 통계", "/admin/stats", "관리", "responsive", ["US-005"], ["CMP-003"])],
    "cmps": [("CMP-001", "Button"), ("CMP-002", "SeatMap"), ("CMP-003", "DataTable")],
    "shell_col": True,
}
CLINIC = {
    "frs": [("FR-001", "진료 시간 조회", "Must"), ("FR-002", "예약 신청", "Must"), ("FR-003", "접수 처리", "Must"),
            ("FR-004", "예약 알림", "Must"), ("FR-005", "환자 정보 수정", "Must"), ("FR-006", "대기열 현황", "Could")],
    "us": [("US-001", "진료 가능 시간 보기", "Must", ["FR-001"]), ("US-002", "예약 신청", "Must", ["FR-002"]),
           ("US-003", "예약 접수", "Must", ["FR-003"]), ("US-004", "예약 알림 받기", "Must", ["FR-004"]),
           ("US-005", "내 정보 수정", "Must", ["FR-005"]), ("US-006", "대기열 보기", "Could", ["FR-006"])],
    "acs": [("AC-001", "US-001", "날짜별 진료 가능 시간이 보인다", "SCR-101-ST1"),
            ("AC-002", "US-002", "시간을 고르면 예약 신청이 접수된다", "SCR-102-ST1"),
            ("AC-003", "US-002", "이미 찬 시간이면 다른 시간을 안내한다", "SCR-102-ST3"),
            ("AC-004", "US-003", "직원 역할만 접수 처리 버튼을 볼 수 있다", "SCR-201-ST1"),
            ("AC-005", "US-003", "접수하면 대기 번호가 발급된다", "SCR-201-ST1"),
            ("AC-006", "US-004", "예약 하루 전 알림이 발송된다", "비UI: 서버 알림 작업"),
            ("AC-007", "US-005", "연락처를 수정하면 다음 알림부터 반영된다", "SCR-103-ST1"),
            ("AC-008", "US-006", "대기 인원이 실시간으로 보인다", "SCR-202-ST1")],
    "flows": [("FLOW-001", [("FLOW-001-S1", "SCR-101"), ("FLOW-001-S2", "SCR-102")]), ("FLOW-002", [("FLOW-002-S1", "SCR-201")])],
    "screens": [("SCR-101", "진료 시간", "/schedule", "", "mobile", ["US-001"], ["CMP-001"]),
                ("SCR-102", "예약 신청", "/book", "", "mobile", ["US-002", "US-004"], ["CMP-001", "CMP-002"]),
                ("SCR-103", "내 정보", "/me", "", "mobile", ["US-005"], ["CMP-002"]),
                ("SCR-201", "접수 대시보드", "/staff/desk", "", "responsive", ["US-003"], ["CMP-001", "CMP-003"]),
                ("SCR-202", "대기열", "/staff/queue", "", "responsive", ["US-006"], ["CMP-003"])],
    "cmps": [("CMP-001", "Button"), ("CMP-002", "FormField"), ("CMP-003", "QueueList")],
    "shell_col": False,
}


def write_planning(d: Path, dom: dict) -> dict:
    p = d / "docs/planning"
    p.mkdir(parents=True, exist_ok=True)
    files = {
        "01-discovery.md": fm("discovery") + "# Discovery\n- PRB-001 문제\n",
        "02-prd.md": fm("prd") + "# PRD\n## 4. 기능 요구사항\n| ID | 요구사항 | 우선순위 | 추적 |\n|---|---|---|---|\n"
        + "".join(f"| {i} | {t} | {pr} | GOAL-001 |\n" for i, t, pr in dom["frs"]),
        "03-user-stories.md": fm("user-stories") + "# 사용자 스토리\n"
        + "".join(f"### {i}: {t}\n- **우선순위**: {pr}\n- **추적 대상**: {', '.join(frs)}\n" for i, t, pr, frs in dom["us"]),
        "04-user-flows.md": fm("user-flows") + "# 플로우\n" + "".join(
            f"## {f}: 흐름\n| 단계 | 사용자 행동 | 시스템 반응 |\n|---|---|---|\n" + "".join(f"| {s} | 행동 | 반응 |\n" for s, _ in steps)
            for f, steps in dom["flows"]),
        "05-acceptance-criteria.md": fm("acceptance-criteria") + "# AC\n",
    }
    us_fr = {u: frs for u, _, _, frs in dom["us"]}
    for u, t, _, _ in dom["us"]:
        files["05-acceptance-criteria.md"] += f"## {u}: {t}\n"
        for a, au, at, _ in dom["acs"]:
            if au == u:
                files["05-acceptance-criteria.md"] += (f"### {a}: {at}\n- **추적 대상**: {u}, {', '.join(us_fr[u])}\n"
                                                       f"- **Given(전제)**: 전제\n- **When(행동)**: 행동\n- **Then(결과)**: {at}\n")
    for f, c in files.items():
        (p / f).write_text(c)
    h = {f: sha(p / f) for f in files}
    plan_hashes = "\n".join(f'        docs/planning/{f}: "{h[f]}"' for f in list(files)[1:])
    (d / ".ai-workflow").mkdir(exist_ok=True)
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
    status: approved
    revision: 1
    based_on_discovery_revision: 1
    artifacts_done: []
    approved:
      revision: 1
      at: "2026-11-06T00:00:00Z"
      hashes:
{plan_hashes}

  design:
    status: not_started

history: []
""")
    return h


STATE_ROWS = "| {s}-ST1 | 기본 | 기본 |\n| {s}-ST2 | 로딩 | 스피너 |\n| - | 빈 상태 | 해당 없음 |\n| {s}-ST3 | 오류 | 오류 안내 |\n| - | 권한 없음 | 해당 없음 |\n| - | 충돌 | 해당 없음 |\n"


def write_design(d: Path, dom: dict, rev: int = 1, extra: str = "") -> None:
    dd = d / "docs/design"
    dd.mkdir(parents=True, exist_ok=True)
    first_us = dom["us"][0][0]
    (dd / "00-ux-decisions.md").write_text(fm("ux-decisions", rev) + f"# UX 결정\n## UX 결정\n### UXD-001: 첫 화면 구성\n- **주제**: 첫 화면\n"
                                           f"- **결정**: 핵심 정보 먼저\n- **근거**: 사용자 답변\n- **상태**: 확정\n- **관련**: {first_us}\n")
    if dom["shell_col"]:
        ia = "| 화면 ID | 화면 이름 | 경로 | 접근 역할 | 플랫폼 | 셸 |\n|---|---|---|---|---|---|\n" + "".join(
            f"| {s} | {n} | {r} | 역할 | {pf} | {sh} |\n" for s, n, r, sh, pf, _, _ in dom["screens"])
    else:
        ia = "| 화면 ID | 화면 이름 | 경로 | 접근 역할 | 플랫폼 |\n|---|---|---|---|---|\n" + "".join(
            f"| {s} | {n} | {r} | 역할 | {pf} |\n" for s, n, r, sh, pf, _, _ in dom["screens"])
    (dd / "01-information-architecture.md").write_text(fm("information-architecture", rev) + "# IA\n## 라우트 표\n" + ia)
    scr = fm("screens", rev) + "# 화면\n"
    for s, n, r, sh, pf, us, cm in dom["screens"]:
        acs = [a for a, _, _, t in dom["acs"] if t.startswith(s)]
        scr += (f"## {s}: {n}\n- **목적**: {n}\n- **역할**: 역할\n- **플랫폼**: {pf}\n- **경로**: {r}\n"
                f"- **추적**: {', '.join(us + acs)}\n- **UX 결정**: UXD-001\n### 상태\n| 상태 ID | 상태 | 표시·동작 |\n|---|---|---|\n"
                + STATE_ROWS.format(s=s) + f"### 컴포넌트\n{', '.join(cm)}\n\n")
    (dd / "02-screens.md").write_text(scr + extra)
    (dd / "03-screen-flows.md").write_text(fm("screen-flows", rev) + "# 흐름\n| FLOW 단계 | 화면·상태 | 비고 |\n|---|---|---|\n"
                                           + "".join(f"| {st} | {sc} | |\n" for _, steps in dom["flows"] for st, sc in steps))
    (dd / "04-ui-system.md").write_text(fm("ui-system", rev) + "# UI\n" + "".join(f"### {c}: {n}\n- **용도**: {n}\n" for c, n in dom["cmps"]))
    us_rows = ""
    for u, _, pr, _ in dom["us"]:
        if pr in ("Must", "Should"):
            scrs = [s for s, *_rest in dom["screens"] if u in _rest[4]]
            us_rows += f"| {u} | {pr} | {', '.join(scrs)} | UXD-001 |\n"
    ac_rows = "".join(f"| {a} | {t} | 확인 |\n" for a, _, _, t in dom["acs"])
    (dd / "05-design-traceability.md").write_text(fm("design-traceability", rev) + "# 추적성\n| US | 우선순위 | 화면 | UX 결정 |\n|---|---|---|---|\n"
                                                  + us_rows + "\n| AC | 화면·상태 | 확인 방법 |\n|---|---|---|\n" + ac_rows)


SPEC = ["docs/design/01-information-architecture.md", "docs/design/02-screens.md", "docs/design/03-screen-flows.md",
        "docs/design/04-ui-system.md", "docs/design/05-design-traceability.md"]


def make_product(root: Path, name: str, dom: dict, approve_spec: bool = True, with_design: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    G(d, "init", "-q")
    (d / "README.md").write_text("# 제품\n")
    (d / ".gitignore").write_text("node_modules/\n")
    write_planning(d, dom)
    G(d, "add", "-A"); G(d, "commit", "-qm", "approved planning")
    if not with_design:
        return d
    code, out = pd(d, "start"); assert code == 0, out
    write_design(d, dom)
    for args in (("done", "--path", "docs/design/00-ux-decisions.md"), ("submit", "--stage", "ux_planning"),
                 ("approve", "--stage", "ux_planning", "--revision", "1"), ("begin", "--stage", "ux_spec")):
        code, out = pd(d, *args); assert code == 0, (args, out)
    for f in SPEC:
        code, out = pd(d, "done", "--path", f); assert code == 0, (f, out)
    code, out = pd(d, "checkpoint"); assert code == 0, out
    if approve_spec:
        code, out = pd(d, "submit", "--stage", "ux_spec"); assert code == 0, out
        code, out = pd(d, "approve", "--stage", "ux_spec", "--revision", "1"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "design (user commit)")
    return d


def simulate_preview_approved(d: Path) -> None:
    """픽스처: 프리뷰 승인 기록을 product-design 해시 함수로 계산해 씁니다(pnpm 빌드 없이 L3 상태를 만들기 위함).
    product-design status의 cross_verify가 일관성을 다시 확인합니다."""
    sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
    import pd_core  # noqa: E402
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    (d / "design-preview").mkdir(exist_ok=True)
    (d / "design-preview/preview.manifest.json").write_text('{"ux_spec_revision": 1, "screens": {}}\n')
    (d / "docs/design/06-preview-review.md").write_text(fm("preview-review") + "# 프리뷰 검토\n")
    cur = pd_core.stage_current_hashes(d, "preview")
    pv = st["stages"]["preview"]
    pv.update(status="approved", revision=1, based_on_ux_spec_revision=1)
    pv["approved"] = {"revision": 1, "at": "2026-11-10T00:00:00Z", "hashes": cur, "ux_spec_hashes": st["stages"]["ux_spec"]["approved"]["hashes"]}
    pv["submitted"] = dict(pv["approved"])
    (d / ".ai-workflow/design.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "preview approved (fixture)")


PROTECTED_GLOBS = (".ai-workflow/state.yaml", ".ai-workflow/design.json", ".ai-workflow/design-notes.md", "docs/planning", "docs/design", "design-preview")


def protected_snapshot(d: Path) -> dict:
    out = {}
    for g in PROTECTED_GLOBS:
        p = d / g
        if p.is_file():
            out[g] = sha(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    out[str(f.relative_to(d))] = sha(f)
    return out


def save_plan(d: Path, plan: dict) -> None:
    (d / "docs/build").mkdir(parents=True, exist_ok=True)
    (d / "docs/build/implementation-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")


def draft_of(d: Path) -> dict:
    code, out = pb(d, "scope", "--draft")
    assert code == 0, out
    return out["draft"]


def errors_of(out: dict) -> str:
    return " / ".join(out.get("errors", [])) or out.get("message", "") or str(out)[:300]


def has(out: dict, code: str) -> bool:
    return any(e.startswith(f"[{code}]") for e in out.get("errors", []))


# ---------------------------------------------------------------- 테스트
def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-test-"))
    try:
        run_tests(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


def run_tests(root: Path) -> None:
    # ---- 정적: 엔진 경계
    sys.path.insert(0, str(ENGINE / "skills/product-build/scripts"))
    import pb_core  # noqa: E402
    writers = {"save_state", "add_history", "detect_outdated", "write_owned", "backup_file", "invalidate_downstream"}
    check("X1 product-design에서 가져오는 함수는 읽기 전용뿐", not (set(pb_core.PD_IMPORTS) & writers), pb_core.PD_IMPORTS)
    src = (ENGINE / "skills/product-build/scripts/pb_core.py").read_text()
    check("X2 product-design check(상태 기록 가능)를 호출하지 않음", '"check"' not in src and "'check'" not in src)
    for rel in (".ai-workflow/state.yaml", ".ai-workflow/design.json", "docs/planning/02-prd.md", "docs/design/02-screens.md",
                "design-preview/src/x.tsx", ".ai-workflow/boilerplate.json", "../x", "/etc/passwd", "frontend/src/a.ts"):
        try:
            pb_core.write_owned(root, rel, "x")
            check(f"X3 write_owned 거부: {rel}", False, "썼음")
        except RuntimeError:
            check(f"X3 write_owned 거부: {rel}", True)
    old = {"planning": {"planning_revision": "1", "hashes": {}}, "design": {"level": "L2", "approved_digests": {"ux_spec": "a"}}, "design_files": {}}
    new = copy.deepcopy(old); new["design"]["level"] = "L3"; new["design"]["approved_digests"]["preview"] = "p"
    check("X4 프리뷰가 새로 승인되는 것(L2→L3)은 계획 무효화가 아님", pb_core.baseline_changes(old, new) == [], pb_core.baseline_changes(old, new))
    lower = copy.deepcopy(old); lower["design"]["level"] = "L1"
    check("X5 디자인 수준 하락(L2→L1)은 무효화", any("level" in c for c in pb_core.baseline_changes(old, lower)))
    import pb_scan  # noqa: E402
    rx = pb_scan.route_regex("/club-matches/:matchId")
    check("X6 경로 매칭: :param·${템플릿}·정적 경로, 다른 경로는 불일치",
          bool(rx.search("navigate(`/club-matches/${m.id}`)")) and bool(rx.search("{ path: '/club-matches/:matchId' }"))
          and not rx.search("'/club-matches'") and pb_scan.route_regex("/*") is None and pb_scan.route_regex("/:id") is None)

    # ---- 도메인 A: L2(UX Spec 승인, 프리뷰 미승인)
    A = make_product(root, "library", LIBRARY)
    snapA = protected_snapshot(A)
    code, out = pb(A, "check")
    check("A1 check: 초기화 전 안내 + 디자인 L2 판정", code == 0 and out.get("status") == "not_initialized" and out["design"]["level"] == "L2", out)
    code, out = pb(A, "plan-validate")
    check("A2 init 전 계획 없음 차단", code == 2 and out.get("error") == "no_plan", out)
    code, out = pb(A, "init")
    check("A3 init: build.json·프로필·증거 gitignore 생성", code == 0 and (A / ".ai-workflow/build.json").exists()
          and (A / "docs/build/build-profile.toml").exists() and (A / ".ai-workflow/build/.gitignore").read_text().count("evidence/") == 1, out)
    code, out2 = pb(A, "init")
    check("A4 init 재실행은 멱등(덮어쓰지 않음)", code == 0 and out2.get("status") == "already_initialized", out2)
    code, sc = pb(A, "scope")
    s = sc.get("scope", {})
    check("A5 범위 추출: Must US 4, AC 7(Should AC-008 제외), 필수 화면 4, 비UI 1",
          code == 0 and len(s["US"]) == 4 and len(s["AC_active"]) == 7 and "AC-008" not in s["AC"]
          and s["SCR_required"] == ["SCR-001", "SCR-002", "SCR-003", "SCR-004"] and s["AC_non_ui"] == ["AC-004"], sc)
    check("A6 FR/US/AC/SCR/CMP 추출 수", sc["counts"]["FR"] == 6 and sc["counts"]["US"] == 5 and sc["counts"]["AC"] == 8
          and sc["counts"]["SCR"] == 5 and sc["counts"]["CMP"] == 3, sc["counts"])
    dr = draft_of(A)
    save_plan(A, dr)
    code, v = pb(A, "plan-validate")
    check("A7 [검증 6] waiver 없이 미승인 프리뷰 → 화면 배치 차단(design_not_ready)", code == 2 and has(v, "design_not_ready")
          and not has(v, "ac_missing") and not has(v, "ac_duplicate"), errors_of(v))
    code, out = pb(A, "submit", "plan")
    check("A8 검증 실패 계획은 제출되지 않음", code == 2 and out.get("error") == "plan_invalid"
          and json.loads((A / ".ai-workflow/build.json").read_text())["plan"]["status"] == "drafting", out)
    code, out = pb(A, "execute-gate", "--batch", "B0")
    check("A9 승인되지 않은 계획으로 실행 진입 불가", code == 2 and out.get("error") == "plan_not_approved", out)
    before = (A / ".ai-workflow/build.json").read_text()
    code, out = pb(A, "waiver", "add", "--reason", "화면별 프리뷰 승인 없이 배치 단위 구현", "--all-ui")
    check("A10 waiver: --confirm·승인 문장 없으면 기록하지 않고 확인 요청", code == 0 and out.get("status") == "confirmation_required"
          and (A / ".ai-workflow/build.json").read_text() == before, out)
    code, out = pb(A, "waiver", "add", "--reason", "x", "--batches", "B9", "--note", "승인", "--confirm")
    check("A11 waiver: 계획에 없는 배치는 거부", code == 2 and out.get("error") == "unknown_batch", out)
    code, out = pb(A, "waiver", "add", "--reason", "화면별 프리뷰 승인 없이 배치 단위 구현", "--all-ui",
                   "--note", "프리뷰 승인 없이 UX Spec r1 기준 구현을 승인합니다", "--confirm")
    w = out.get("waiver", {})
    check("A12 waiver 기록: 사유·범위·승인 문장·기준 revision", code == 0 and w.get("id") == "WVR-001" and w["scope"]["all_ui"]
          and w["basis"]["ux_spec_revision"] == 1 and w["statement"].startswith("프리뷰"), out)
    design_before = (A / ".ai-workflow/design.json").read_text()
    code, v = pb(A, "plan-validate")
    check("A13 [검증 7] waiver 승인 후 계획 검증 통과(design_path=preview_waiver)", code == 0
          and all(x["design_path"] == "preview_waiver" for x in v["derived"]["batches"].values() if x["requires_design"]), errors_of(v))
    bat = v["derived"]["batches"]
    ac_batch = {a: b["id"] for b in dr["batches"] for a in b["acs"]}
    check("A14 위험 감지: 삭제(AC-005)·권한(AC-006) 배치는 사용자 승인, 위험 AC는 E3",
          bat[ac_batch["AC-005"]]["approval"] == "user" and bat[ac_batch["AC-006"]]["approval"] == "user"
          and bat[ac_batch["AC-006"]]["ac_targets"]["AC-006"] == "E3" and bat[ac_batch["AC-001"]]["ac_targets"]["AC-001"] == "E2", bat)
    check("A15 위험 없는 배치는 자동 진행(waiver 배치 기본 auto)", any(x["approval"] == "auto" for x in bat.values()), bat)
    code, out = pb(A, "submit", "plan")
    check("A16 제출: awaiting_approval r1, 문서 생성", code == 0 and out.get("revision") == 1 and (A / "docs/build/00-implementation-plan.md").exists(), out)
    code, out = pb(A, "submit", "plan")
    check("A17 같은 내용 재제출은 멱등", code == 0 and out.get("status") == "already_submitted", out)
    code, out = pb(A, "approve", "plan", "--revision", "1")
    check("A18 승인 문장 없는 승인 거부", code == 2 and out.get("error") == "approval_statement_required", out)
    code, out = pb(A, "approve", "plan", "--revision", "2", "--note", "승인합니다")
    check("A19 다른 revision 승인 거부", code == 2 and out.get("error") == "revision_mismatch", out)
    plan_path = A / "docs/build/implementation-plan.json"
    orig_plan = plan_path.read_text()
    plan_path.write_text(orig_plan.replace('"공통 기반"', '"공통 기반(수정)"'))
    code, out = pb(A, "approve", "plan", "--revision", "1", "--note", "구현 계획 r1을 승인합니다")
    check("A20 제출 후 바뀐 계획은 승인 거부", code == 2 and out.get("error") == "changed_since_submit", out)
    plan_path.write_text(orig_plan)
    code, out = pb(A, "approve", "plan", "--revision", "1", "--note", "구현 계획 r1을 승인합니다")
    st = json.loads((A / ".ai-workflow/build.json").read_text())
    check("A21 계획 승인: 해시·입력 기준선·승인 문장·배치 planned", code == 0 and st["plan"]["status"] == "approved"
          and set(st["plan"]["approved"]["hashes"]) == {"docs/build/implementation-plan.json", "docs/build/00-implementation-plan.md", "docs/build/build-profile.toml"}
          and st["plan"]["approved"]["inputs"]["design"]["level"] == "L2" and st["plan"]["approved"]["statement"].startswith("구현 계획")
          and all(b["status"] == "planned" for b in st["batches"].values()), out)
    check("A22 design.json은 waiver·승인 후에도 그대로(프리뷰 상태 불변)", (A / ".ai-workflow/design.json").read_text() == design_before)
    first = dr["batches"][0]["id"]
    code, out = pb(A, "execute-gate", "--batch", first)
    check("A23 승인된 계획 + 유효 waiver → 첫 배치 진입 허용", code == 0 and out.get("ok") and out.get("design_path") == "preview_waiver", out)
    code, out = pb(A, "execute-gate", "--batch", dr["batches"][1]["id"])
    # M2.2부터 선행 조건은 프로필 execution.dependency_min(기본 implemented) 기준. 차단 동작은 같고 오류 코드 이름만 바뀜
    check("A24 선행 배치가 끝나지 않으면(planned) 진입 불가", code == 2 and out.get("error") == "dependencies_not_ready"
          and out.get("pending") == {"B0": "planned"}, out)
    code, out = pb(A, "status", "--all")
    check("A25 status --all: 기획·디자인·구현 통합, state.yaml 표시 안내", code == 0 and out["planning"]["ok"] and out["build"]["plan"]["status"] == "approved"
          and out["design"]["stages"]["ux_spec"]["status"] == "approved" and out["notes"], out)
    # 승인 후 계획 파일 변경
    plan_path.write_text(orig_plan.replace('"공통 기반"', '"공통 기반(무단 수정)"'))
    code, out = pb(A, "check")
    check("A26 승인 후 계획 파일 변경 → plan_modified로 멈춤(자동 재승인 없음)", code == 2 and out.get("error") == "plan_modified", out)
    code, out = pb(A, "execute-gate", "--batch", first)
    check("A27 계획 변경 시 실행 진입 불가", code == 2 and out.get("error") == "plan_modified", out)
    plan_path.write_text(orig_plan)
    code, out = pb(A, "check")
    check("A28 되돌리면 정상", code == 0 and out["plan"]["status"] == "approved", out)
    # [검증 9] 보호 경로: build 명령 전후 해시 동일, guard
    check("A29 [검증 9] build 명령 전후로 기획·디자인 승인 문서·상태 불변", protected_snapshot(A) == snapA)
    G(A, "add", "-A"); G(A, "commit", "-qm", "build plan (user commit)")
    code, out = pb(A, "guard", "--base", "HEAD")
    check("A30 guard: 변경 없음 → 통과", code == 0 and out["ok"], out)
    (A / "src").mkdir(exist_ok=True); (A / "src/app.ts").write_text("export {}\n")
    with open(A / "docs/design/02-screens.md", "a") as f:
        f.write("\n<!-- 구현 중 실수로 고친 승인 문서 -->\n")
    code, out = pb(A, "guard", "--base", "HEAD")
    check("A31 guard: 구현 중 승인 문서 변경 → 보호 경로 위반(코드 파일은 허용)", code == 2 and out["protected_changed"] == ["docs/design/02-screens.md"], out)
    G(A, "checkout", "--", "docs/design/02-screens.md")
    (A / "src/app.ts").unlink()
    # [검증 8] 입력 문서 변경(UX Spec 재승인) → 계획 outdated, waiver 무효
    code, out = pd(A, "reopen", "--stage", "ux_spec", "--reason", "화면 문구 보완"); assert code == 0, out
    for f in SPEC:
        txt = (A / f).read_text().replace("revision: 1", "revision: 2", 1)
        (A / f).write_text(txt)
    with open(A / "docs/design/02-screens.md", "a") as f:
        f.write("\n")
    for f in SPEC:
        code, out = pd(A, "done", "--path", f); assert code == 0, out
    code, out = pd(A, "submit", "--stage", "ux_spec"); assert code == 0, out
    code, out = pd(A, "approve", "--stage", "ux_spec", "--revision", "2"); assert code == 0, out
    code, out = pb(A, "execute-gate", "--batch", first)
    check("A32 [검증 8] UX Spec 재승인 후 실행 진입 불가(inputs_changed)", code == 2 and out.get("error") == "inputs_changed", out)
    code, out = pb(A, "check")
    st = json.loads((A / ".ai-workflow/build.json").read_text())
    check("A33 [검증 8] check가 계획을 outdated로 기록(변경 입력 보고)", code == 2 and out.get("error") == "plan_outdated"
          and st["plan"]["status"] == "outdated" and any("ux_spec" in c for c in out.get("changed", [])), out)
    code, out = pb(A, "status")
    check("A34 waiver 기준(ux_spec r1)이 바뀌어 waiver 무효 표시", code == 0 and out["build"]["waivers"][0]["valid"] is False, out)
    code, out = pb(A, "submit", "plan")
    check("A35 outdated 계획은 reopen 없이 제출 불가", code == 2 and out.get("error") == "plan_not_editable", out)
    code, out = pb(A, "reopen", "plan", "--reason", "UX Spec r2 반영")
    code2, v = pb(A, "plan-validate")
    check("A36 reopen 후 재검증: 무효 waiver로는 화면 배치 불가", code == 0 and code2 == 2 and has(v, "design_not_ready"), errors_of(v))
    code, out = pb(A, "waiver", "add", "--reason", "r2 기준 계속 진행", "--all-ui", "--note", "UX Spec r2 기준 구현을 승인합니다", "--confirm")
    code2, out2 = pb(A, "submit", "plan")
    code3, out3 = pb(A, "approve", "plan", "--revision", "2", "--note", "구현 계획 r2를 승인합니다")
    st = json.loads((A / ".ai-workflow/build.json").read_text())
    check("A37 새 waiver → r2 제출·승인, last_approved 보존", code == 0 and code2 == 0 and code3 == 0 and st["plan"]["revision"] == 2
          and st["plan"]["last_approved"]["revision"] == 1, (out, out2, out3))
    code, out = pb(A, "waiver", "revoke", "--id", "WVR-002", "--reason", "프리뷰를 먼저 승인하기로 함")
    code2, out2 = pb(A, "execute-gate", "--batch", first)
    check("A38 waiver 철회 → 그 waiver에 기댄 배치 진입 불가", code == 0 and code2 == 2 and out2.get("error") == "waiver_invalid", out2)
    st = json.loads((A / ".ai-workflow/build.json").read_text())
    check("A39 기존 승인 기록(ux_planning·ux_spec)은 build가 바꾸지 않음",
          json.loads((A / ".ai-workflow/design.json").read_text())["stages"]["ux_spec"]["approved"]["revision"] == 2)

    # ---- 계획 검증 오류(도메인 A 복제본에서 계획 JSON만 바꿔 봄)
    A2 = root / "library-errors"
    shutil.copytree(A, A2)
    G(A2, "add", "-A"); G(A2, "commit", "-qm", "copy", "--allow-empty")
    base = json.loads((A2 / "docs/build/implementation-plan.json").read_text())

    def v_of(mut) -> dict:
        p = copy.deepcopy(base)
        mut(p)
        save_plan(A2, p)
        return pb(A2, "plan-validate")[1]

    ui = [b for b in base["batches"] if b["acs"]]
    b1, b2 = ui[0]["id"], ui[1]["id"]

    def dup(p):
        x = [b for b in p["batches"] if b["id"] == b2][0]
        x["acs"].append([b for b in p["batches"] if b["id"] == b1][0]["acs"][0])
    check("E1 [검증 4] AC 중복 배정 차단", has(v_of(dup), "ac_duplicate"))

    def miss(p):
        [b for b in p["batches"] if b["id"] == b1][0]["acs"].pop(0)
    out = v_of(miss)
    check("E2 [검증 4] AC 누락 배정 차단(ac_missing)", has(out, "ac_missing"), errors_of(out))

    def oos(p):
        p["batches"][-1]["acs"].append("AC-008")
    check("E3 범위 밖(Should) AC 배정 차단", has(v_of(oos), "ac_out_of_scope"))

    def incl(p):
        p["scope"]["include"] = ["US-005"]
        p["deferred"] = [{"id": "AC-008", "reason": "통계는 다음 릴리스"}]
    out = v_of(incl)
    check("E4 Should를 include하고 사유와 함께 미루면 통과", not has(out, "ac_missing") and not has(out, "ac_out_of_scope"), errors_of(out))

    def defer_noreason(p):
        p["deferred"] = [{"id": "AC-001", "reason": ""}]
    check("E5 사유 없는 deferred 차단", has(v_of(defer_noreason), "deferred_no_reason"))

    def scr_dup(p):
        [b for b in p["batches"] if b["id"] == b2][0]["screens"].append([b for b in p["batches"] if b["id"] == b1][0]["screens"][0])
    check("E6 화면 소유 중복 차단", has(v_of(scr_dup), "scr_duplicate"))

    def cyc(p):
        x = [b for b in p["batches"] if b["id"] == b1][0]
        y = [b for b in p["batches"] if b["id"] == b2][0]
        x["depends_on"] = x["depends_on"] + [b2]
        y["depends_on"] = y["depends_on"] + [b1]
    out = v_of(cyc)
    check("E7 [검증 5] 배치 순환 의존성 차단", has(out, "dep_cycle"), errors_of(out))

    def tcyc(p):
        x = [b for b in p["batches"] if b["id"] == b1][0]
        x["tasks"][0]["depends_on"] = [x["tasks"][-1]["id"]]
        x["tasks"][-1]["depends_on"] = [x["tasks"][0]["id"]]
    check("E8 [검증 5] 작업 순환 의존성 차단", has(v_of(tcyc), "task_dep_cycle"))

    def tcross(p):
        x = [b for b in p["batches"] if b["id"] == b1][0]
        y = [b for b in p["batches"] if b["id"] == b2][0]
        x["tasks"][0]["depends_on"] = [y["tasks"][0]["id"]]
    check("E9 다른 배치 작업 의존 시 배치 의존 필요", has(v_of(tcross), "task_dep_cross") or has(v_of(tcross), "order_violation"))

    def unknown(p):
        p["batches"][-1]["acs"].append("AC-999")
    check("E10 없는 ID 참조 차단", has(v_of(unknown), "unknown_ref"))

    def cmpdep(p):
        x = [b for b in p["batches"] if b["id"] == b1][0]
        x["components"]["new"] = ["CMP-003"]
        for b in p["batches"]:
            if b["id"] != b1:
                b["components"]["new"] = [c for c in b["components"]["new"] if c != "CMP-003"]
        last = p["batches"][-1]
        last["components"]["reuse"] = ["CMP-003"]
        last["depends_on"] = [d for d in last["depends_on"] if d != b1]
    out = v_of(cmpdep)
    check("E11 다른 배치가 만드는 컴포넌트를 의존 없이 재사용하면 차단", has(out, "cmp_dep_missing") or ui[-1]["id"] == b1, errors_of(out))

    def autoreq(p):
        for b in p["batches"]:
            if "AC-006" in b["acs"]:
                b["approval"] = "auto"
    out = v_of(autoreq)
    check("E12 위험 배치의 approval=auto 요청은 낮추지 않음(경고)", any("낮출 수 없습니다" in w for w in out["warnings"]), out.get("warnings"))

    # ---- 도메인 B: 셸 열 없음 + L3(프리뷰 승인)
    B = make_product(root, "clinic", CLINIC)
    simulate_preview_approved(B)
    code, ds = pd(B, "status")
    check("B1 픽스처 프리뷰 승인 기록이 product-design 검사와 일관됨", ds.get("cross_verify", {}).get("consistent") is True, ds.get("cross_verify"))
    snapB = protected_snapshot(B)
    pb(B, "init")
    code, sc = pb(B, "scope", "--suggest")
    groups = {tuple(g["screens"]) for g in sc.get("groups", [])}
    check("B2 셸 열이 없으면 경로 접두사로 묶음(Could 화면 SCR-202 제외)", code == 0 and "SCR-202" not in sc["scope"]["SCR_required"]
          and any(set(g) == {"SCR-201"} or "SCR-201" in g for g in groups), sc.get("groups"))
    dr = draft_of(B)
    save_plan(B, dr)
    code, v = pb(B, "plan-validate")
    check("B3 [검증 1] 다른 도메인(진료 예약)에서도 초안이 검증 통과(L3: waiver 불필요)", code == 0
          and all(x["design_path"] in ("preview_approved", "planning_only") for x in v["derived"]["batches"].values()), errors_of(v))
    ab = {a: b["id"] for b in dr["batches"] for a in b["acs"]}
    check("B4 권한(AC-004)·개인정보(AC-007) 배치는 사용자 승인", v["derived"]["batches"][ab["AC-004"]]["approval"] == "user"
          and "privacy" in v["derived"]["batches"][ab["AC-007"]]["risk_tags_detected"], v["derived"]["batches"])
    check("B5 비UI AC(알림)는 그 US 화면의 배치에 배정(세로 슬라이스)", ab.get("AC-006") == ab.get("AC-002"), ab)
    p2 = copy.deepcopy(dr); p2["scope"]["include"] = ["US-006"]; save_plan(B, p2)
    code, v = pb(B, "plan-validate")
    check("B6 Could를 include하면 그 AC·화면이 필수가 됨", code == 2 and has(v, "ac_missing") and has(v, "scr_missing"), errors_of(v))
    save_plan(B, dr)
    code, out = pb(B, "submit", "plan")
    code2, out2 = pb(B, "approve", "plan", "--revision", "1", "--note", "진료 예약 구현 계획을 승인합니다")
    code3, out3 = pb(B, "execute-gate", "--batch", dr["batches"][0]["id"])
    check("B7 L3 경로: 제출·승인·진입(design_path=preview_approved)", code == 0 and code2 == 0 and code3 == 0
          and out3.get("design_path") in ("preview_approved", "planning_only"), (out, out2, out3))
    code, out = pb(B, "waiver", "add", "--reason", "x", "--all-ui", "--note", "y", "--confirm")
    check("B8 프리뷰가 승인된 프로젝트는 waiver가 필요 없음", code == 2 and out.get("error") == "waiver_not_needed", out)
    code, ad = pb(B, "adopt")
    check("B9 adopt: 코드가 없으면 모든 화면 신호 none, AC E0, 기록 없음", code == 0 and all(v["signal"] == "none" for v in ad["screens"].values())
          and set(ad["acs"].values()) == {"E0"} and ad["writes"].startswith("없음"), ad.get("counts"))
    # adopt: 코드에 ID만 언급 → 후보 아님, 라우트 + 테스트 언급 → 후보지만 verified=false, E1
    (B / "web/src/pages").mkdir(parents=True)
    (B / "web/src/pages/Schedule.tsx").write_text("// SCR-101 진료 시간\nexport const routes = [{ path: '/schedule' }]\n")
    (B / "web/src/pages/Book.tsx").write_text("// SCR-102 예약 신청(아직 라우트 없음)\n")
    (B / "web/src/pages/schedule.test.tsx").write_text("it('[AC-001] 날짜별 진료 가능 시간', () => {})\n")
    code, ad = pb(B, "adopt", "--full")
    check("B10 adopt: 라우트+ID → 후보, ID만 → 후보 아님, 테스트 언급 AC는 E1(검증 아님)",
          ad["screens"]["SCR-101"]["signal"] == "route_and_id" and ad["screens"]["SCR-101"]["candidate"]
          and ad["screens"]["SCR-102"]["signal"] == "id_only" and not ad["screens"]["SCR-102"]["candidate"]
          and ad["acs"]["AC-001"]["evidence_level"] == "E1" and all(v["verified"] is False for v in ad["acs"].values())
          and all(v["verified"] is False for v in ad["screens"].values()), ad["screens"])
    (B / "web/src/router.tsx").write_text("export const r = [{ path: '/me', element: pending('SCR-103', '내 정보') }]\n")
    code, ad = pb(B, "adopt", "--full")
    check("B10b adopt: 자리표시자 라우트(pending)만 있으면 placeholder(후보 아님)", ad["screens"]["SCR-103"]["signal"] == "placeholder"
          and not ad["screens"]["SCR-103"]["candidate"], ad["screens"]["SCR-103"])
    stB = (B / ".ai-workflow/build.json").read_text()
    code, ad = pb(B, "adopt", "--save")
    check("B11 adopt --save는 분석 파일만 쓰고 build.json(승인·검증 이력)은 그대로", code == 0 and (B / ".ai-workflow/build/adopt-analysis.json").exists()
          and (B / ".ai-workflow/build.json").read_text() == stB, ad.get("saved"))
    check("B12 [검증 9] 도메인 B 보호 경로 불변", protected_snapshot(B) == snapB)

    # ---- 도메인 A': UX Spec 미승인(L1) → 화면 없는 배치만
    C = make_product(root, "library-l1", LIBRARY, approve_spec=False)
    pb(C, "init")
    code, out = pb(C, "check")
    check("C1 UX Spec 미승인은 L1", out["design"]["level"] == "L1", out)
    dc = draft_of(C)
    check("C2a L1 초안은 화면 없는 배치만 만듦", all(b["kind"] == "non_ui" and not b["screens"] for b in dc["batches"]), dc["batches"])
    ui_plan = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
        {"id": "B0", "title": "좌석 화면", "kind": "ui", "screens": ["SCR-001"], "acs": ["AC-001"],
         "tasks": [{"id": "B0-T1", "layer": "fe", "title": "좌석 화면"}]}]}
    save_plan(C, ui_plan)
    code, v = pb(C, "plan-validate")
    check("C2 L1에서 화면 배치는 차단", code == 2 and has(v, "design_not_ready") and "UX Spec 승인" in errors_of(v), errors_of(v))
    code, out = pb(C, "waiver", "add", "--reason", "x", "--all-ui", "--note", "y", "--confirm")
    check("C3 L1에서 preview waiver 불가(waiver는 프리뷰만 대신함)", code == 2 and out.get("error") == "waiver_not_allowed", out)
    code, sc = pb(C, "scope")
    nonui = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "batches": [
        {"id": "B0", "title": "예약 데이터·API", "goal": "화면 없이 먼저 만드는 데이터 모델과 API", "kind": "non_ui",
         "acs": sc["scope"]["AC_active"], "depends_on": [],
         "tasks": [{"id": "B0-T1", "layer": "db", "title": "좌석·예약 테이블"}, {"id": "B0-T2", "layer": "api", "title": "예약 API", "depends_on": ["B0-T1"]},
                   {"id": "B0-T3", "layer": "test", "title": "API 테스트", "depends_on": ["B0-T2"]}]}], "deferred": []}
    save_plan(C, nonui)
    code, v = pb(C, "plan-validate")
    check("C4 [검증] UX Spec 미승인이어도 승인된 기획 기반 DB/API 배치는 허용(design_path=planning_only)", code == 0
          and v["derived"]["batches"]["B0"]["design_path"] == "planning_only", errors_of(v))
    check("C5 db 작업 → schema_migration → 사용자 승인", "schema_migration" in v["derived"]["batches"]["B0"]["risk_tags_detected"]
          and v["derived"]["batches"]["B0"]["approval"] == "user", v["derived"]["batches"]["B0"])
    code, out = pb(C, "submit", "plan")
    code2, out2 = pb(C, "approve", "plan", "--revision", "1", "--note", "API 먼저 구현하는 계획을 승인합니다")
    code3, out3 = pb(C, "execute-gate", "--batch", "B0")
    check("C6 화면 없는 배치 계획 승인·진입", code == 0 and code2 == 0 and code3 == 0 and out3["approval"] == "user", (out, out2, out3))

    # ---- 기획 미승인
    D = root / "no-planning"
    D.mkdir(); G(D, "init", "-q"); (D / "README.md").write_text("x\n"); G(D, "add", "-A"); G(D, "commit", "-qm", "init")
    code, out = pb(D, "init")
    check("D1 기획 승인 전에는 init 거부(상태 파일 안 만듦)", code == 2 and out.get("error") in ("no_workflow_state", "planning_not_approved")
          and not (D / ".ai-workflow/build.json").exists(), out)
    code, out = pb(ENGINE, "check")
    check("D2 엔진 저장소 안에서는 실행 거부", code == 2 and out.get("error") == "engine_repo", out)
    code, out = run(PB, "nope")
    check("D3 잘못된 인자도 JSON 오류", code == 2 and out.get("error") == "invalid_arguments", out)
    (A / ".ai-workflow/build.json").write_text("{broken")
    code, out = pb(A, "status")
    check("D4 손상된 상태 파일은 자동으로 고치지 않고 차단", code == 2 and out.get("error") == "invalid_state"
          and (A / ".ai-workflow/build.json").read_text() == "{broken", out)
    check("D5 바이트코드 파일을 만들지 않음", not list((ENGINE / "skills/product-build").rglob("__pycache__")))


if __name__ == "__main__":
    sys.exit(main())
