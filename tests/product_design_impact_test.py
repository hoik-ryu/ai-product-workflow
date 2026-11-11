#!/usr/bin/env python3
"""/product-design 디자인 변경 영향 분류(WF-D01, `impact --design`) 테스트(자체 완결형).

- 기존 `tests/product_design_test.py`의 픽스처 헬퍼로 승인 흐름을 실제 명령으로 진행해, 세 단계가 모두 승인된 저장소를 만듭니다.
  (state.yaml과 기획 문서는 테스트 픽스처이며, 디자인 승인은 스크립트 명령으로만 기록합니다.)
- 고정 사례: tests/fixtures/design-change-cases.json (시험 프로젝트 A/B 실험 D1–D15).
  사례 파일의 `expected`는 테스트만 읽고, 엔진은 프로젝트 고유 정책을 갖지 않습니다.
- 프리뷰 승인에는 pnpm 빌드가 필요합니다. pnpm이 없으면 프리뷰를 승인하지 않은 상태로 검사합니다.

실행: python3 tests/product_design_impact_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402  (픽스처 헬퍼 재사용)

ENGINE = HERE.parent
CASES = HERE / "fixtures/design-change-cases.json"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail=None) -> None:
    results.append((name, bool(cond), "" if cond else str(detail)[:700]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def skip(name: str, why: str) -> None:
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


def pi(*args):
    return T.pi(*args)


def item(out: dict, iid: str) -> dict:
    return next((i for i in out.get("items", []) if i["id"] == iid), {})


def cats(it: dict) -> list[str]:
    return [c["key"] for c in it.get("categories", [])]


def impact_of(it: dict, cat: str) -> dict:
    return next((x for x in it.get("impact", []) if x["category"] == cat), {})


EXTRA_UXD = """### UXD-014: 가입 안내 줄을 명단 상단에 둔다
- **주제**: 명단
- **결정**: 카카오 가입 안내 줄을 명단 위에 둔다
- **근거**: 사용자 답변(라운드 2)
- **상태**: 확정
- **관련**: US-002
### UXD-026: 게스트 추가는 오른쪽 아래 떠 있는 버튼
- **주제**: 명단
- **결정**: 게스트 추가 버튼을 오른쪽 아래에 띄운다
- **근거**: 권장안 수용
- **상태**: 권장안 수용
- **관련**: US-002
### UXD-074: 명단 행 표기
- **주제**: 명단
- **결정**: '이름 · 성별 · 조 · 점수' 순서로 한 줄 표기
- **근거**: 사용자 답변(라운드 3)
- **상태**: 확정
- **관련**: US-002
"""

SCR_211 = """
## SCR-211: 명단
- **목적**: 회원·게스트 명단 관리
- **역할**: 운영진
- **플랫폼**: responsive
- **경로**: /admin/roster
- **추적**: US-002
- **UX 결정**: UXD-014, UXD-026, UXD-074
{states}
### 컴포넌트
CMP-001, CMP-004, CMP-006, CMP-023, CMP-024, CMP-025
"""

TOKENS_AND_CMPS = """
## 1. 디자인 토큰
| 토큰 | 값 | 용도 |
|---|---|---|
| color.action.primary | #1D5BD0 | 주 버튼 배경 |
| color.focus.ring | #1D5BD0 | 키보드 포커스 링 |
| font.weight.regular / bold | 400 / 700 | 글자 굵기 |
| radius.sm | 6px | 칩 |

### CMP-004: FilterChip
- **용도**: 조 필터
### CMP-006: TextField
- **용도**: 이름 검색
### CMP-023: NoticeBox
- **용도**: 가입 안내
### CMP-024: PersonRow
- **용도**: 이름·성별·조·점수
### CMP-025: AppNav
- **용도**: 탭 높이 56
"""


def build_project(root: Path, name: str, approve_spec: bool = True, approve_preview: bool = True) -> tuple[Path, bool]:
    d = T.make_product(root, name)
    P = ("--project", str(d))
    assert pi("start", *P)[0] == 0
    T.write_00(d, 1)
    p00 = d / T.UXP
    p00.write_text(p00.read_text().replace("## 미결 디자인 질문", EXTRA_UXD + "## 미결 디자인 질문"))
    pi("done", *P, "--path", T.UXP)
    assert pi("submit", *P, "--stage", "ux_planning")[0] == 0, "ux_planning submit"
    assert pi("approve", *P, "--stage", "ux_planning", "--revision", "1")[0] == 0
    pi("begin", *P, "--stage", "ux_spec")
    T.write_spec(d, 1)
    ia, scr, ui = (d / T.SPEC[0]), (d / T.SPEC[1]), (d / T.SPEC[3])
    ia.write_text(ia.read_text() + "| SCR-211 | 명단 | /admin/roster | 운영진 | responsive | 운영 |\n")
    scr.write_text(scr.read_text() + SCR_211.format(states=T.STATES_FULL.format(s="SCR-211")))
    ui.write_text(ui.read_text() + TOKENS_AND_CMPS)
    T.done_all(d, T.SPEC)
    assert pi("checkpoint", *P)[0] == 0
    code, out = pi("submit", *P, "--stage", "ux_spec")
    assert code == 0, out
    if not approve_spec:
        return d, False
    assert pi("approve", *P, "--stage", "ux_spec", "--revision", "1")[0] == 0
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "design approved (user commit)")
    if not approve_preview or shutil.which("pnpm") is None:
        return d, False
    pi("begin", *P, "--stage", "preview")
    pi("preview-scaffold", *P)
    T.fill_preview(d, 1)
    man = d / "design-preview/preview.manifest.json"
    m = json.loads(man.read_text()); m["screens"]["SCR-211"] = {"skip": "영향 분류 테스트용 화면"}
    man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    T.write_06(d, 1)
    pi("done", *P, "--path", T.REVIEW if hasattr(T, "REVIEW") else "docs/design/06-preview-review.md")
    code, out = pi("preview-verify", *P)
    if code != 0:
        return d, False
    assert pi("submit", *P, "--stage", "preview")[0] == 0
    assert pi("approve", *P, "--stage", "preview", "--revision", "1")[0] == 0
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "preview approved (user commit)")
    return d, True


def snapshot(d: Path) -> dict:
    files = [d / ".ai-workflow/design.json", d / ".ai-workflow/state.yaml"] + sorted((d / "docs").rglob("*.md"))
    return {str(p.relative_to(d)): T.sha(p) for p in files if p.exists()}


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-impact-test-"))
    d, preview_ok = build_project(root, "impact")
    P = ("--project", str(d))
    s = T.state(d)
    check("I00 픽스처: ux_planning·ux_spec 승인" + (", preview 승인" if preview_ok else "(preview 미승인: pnpm 없음/빌드 실패)"),
          s["stages"]["ux_planning"]["status"] == "approved" and s["stages"]["ux_spec"]["status"] == "approved", s["stages"])
    before = snapshot(d)
    git_before = T.G(d, "status", "--porcelain")

    # ---- 기존 impact 호환: --design 없이 출력이 커밋된(이전) 엔진과 같음
    old_script = root / "product_design_head.py"
    old_script.write_text(subprocess.run(["git", "-C", str(ENGINE), "show", "HEAD:skills/product-design/scripts/product_design.py"],
                                         capture_output=True, text=True, check=True).stdout)
    def run_script(script, *args):
        p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")})
        return p.returncode, p.stdout
    check("I01 기존 impact(--design 없음) 출력이 이전 엔진과 동일", run_script(old_script, "impact", *P) == run_script(T.SCRIPT, "impact", *P))
    code, out = pi("impact", *P, "--request", str(CASES))
    check("I01a --request는 --design 없이 쓰면 JSON 오류", code == 2 and out.get("error") == "invalid_arguments", out)

    # ---- 고정 사례 D1–D15
    code, out = pi("impact", *P, "--design", "--request", str(CASES))
    check("I02 고정 사례 분류 실행(읽기 전용 표시, v1 적용)", code == 0 and out.get("read_only") is True and out["workflow"]["applied"] == "v1"
          and out["workflow"]["declared"] is None, out)
    expected = {c["id"]: c["expected"] for c in json.loads(CASES.read_text())["items"]}
    for iid, exp in expected.items():
        it = item(out, iid)
        ok = it.get("status") == exp["status"] and cats(it) == exp["categories"]
        if "possible" in exp:
            ok = ok and it.get("possible_categories") == exp["possible"]
        for fl in exp.get("flags", []):
            ok = ok and fl in it.get("flags", [])
        check(f"I03 {iid} {it.get('summary', '')} → {exp['status']} {exp['categories']}", ok,
              {k: it.get(k) for k in ("status", "categories", "possible_categories", "flags")})
    sm = out.get("summary", {})
    check("I03a 집계: 자동 9 · 조건부 4 · 사람 판단 1 · 제외 1", (sm.get("classified"), sm.get("conditional"), sm.get("needs_review"), sm.get("excluded")) == (9, 4, 1, 1), sm)
    check("I03b 모든 사례에 분류 근거(reason)와 참조 확인 기록", all(f.get("reason") for i in out["items"] for f in i["facts"])
          and all(f.get("checked_against") for i in out["items"] for f in i["facts"] if f["kind"] in ("token_name", "token_value", "info", "style", "dimension")), out["items"][0]["facts"])

    # ---- 유형별 영향(현재 승인 상태 기준)
    i1, i4, i3, i13 = item(out, "D1"), item(out, "D3"), item(out, "D4"), item(out, "D13")
    up = ["ux_spec", "preview"] if preview_ok else ["ux_spec"]
    m1 = impact_of(i1, "info_behavior")
    check("I04 ① 정보·행동 → UX Spec(구현됨), reopen ux_spec, 재승인 " + "+".join(up),
          m1.get("target_stage") == "ux_spec" and m1.get("target_available") and m1.get("effective_stage") == "ux_spec"
          and m1.get("reapproval_stages") == up and "reopen --stage ux_spec" in m1.get("action", ""), m1)
    check("I04a ① UXD 참조 시 ux_planning 재검토 가능성 안내", any("ux_planning" in n for n in i1.get("notes", [])), i1.get("notes"))
    m2 = impact_of(item(out, "D5"), "token_semantics")
    check("I05 ② 토큰 의미·이름 → UX Spec", m2.get("effective_stage") == "ux_spec" and m2.get("target_available") is True, m2)
    m3 = impact_of(i3, "theme_value")
    check("I06 ③ 테마 값 → 목표 '테마 게이트'는 미구현으로 표시, v1에서는 ux_spec 적용(이유 기록)",
          m3.get("target_stage") == "theme" and m3.get("target_available") is False and m3.get("effective_stage") == "ux_spec"
          and "토큰 변경 = UX 설계 변경" in m3.get("effective_reason", ""), m3)
    m4 = impact_of(i4, "visual")
    check("I07 ④ 시각 표현 → 목표 Design Direction 미구현 표시, v1에서는 preview", m4.get("target_stage") == "design_direction"
          and m4.get("target_available") is False and m4.get("effective_stage") == "preview"
          and m4.get("reapproval_required") == preview_ok, m4)
    m5 = impact_of(i13, "implementation")
    check("I08 ⑤ 구현 메모 → 목표 렌더 단계 미구현 표시, v1에서는 preview(트리 해시)", m5.get("target_stage") == "render"
          and m5.get("target_available") is False and m5.get("effective_stage") == "preview", m5)
    check("I08a 응답에 유형별 목표 단계와 구현 여부 목록", out["categories"]["visual"]["target_available"] is False
          and out["categories"]["info_behavior"]["target_available"] is True, out.get("categories"))
    check("I08b 명세 값 위반·접근성·토큰 밖 안내 문구", any("명세 값" in n for n in item(out, "D11")["notes"])
          and any("대비" in n for n in item(out, "D12")["notes"]) and any("토큰 밖" in n for n in item(out, "D7")["notes"]))

    # ---- 복합·분류 불가 사례
    req = root / "extra-request.json"
    req.write_text(json.dumps({"schema": "design-change-request/v1", "items": [
        {"id": "C1", "summary": "정보 항목 추가 + 주 색 값 변경", "facts": [
            {"kind": "info", "op": "add", "screen": "SCR-211"}, {"kind": "token_value", "token": "color.action.primary"}]},
        {"id": "C2", "summary": "확정 가능 + 판단 필요", "facts": [
            {"kind": "style", "component": "CMP-001", "property": "radius"}, {"kind": "notation", "screen": "SCR-211"}]},
        {"id": "U1", "summary": "알 수 없는 사실 종류", "facts": [{"kind": "mood", "detail": "더 산뜻하게"}]},
        {"id": "U2", "summary": "사실 없음", "facts": []},
        {"id": "U3", "summary": "없는 화면 참조", "facts": [{"kind": "info", "op": "remove", "screen": "SCR-999"}]},
        {"id": "U4", "summary": "알 수 없는 표현 속성", "facts": [{"kind": "style", "component": "CMP-001", "property": "vibe"}]},
        {"id": "T1", "summary": "04에 없는 토큰에 값", "facts": [{"kind": "token_value", "token": "color.brand.new"}]},
        {"id": "T2", "summary": "이미 있는 토큰을 추가", "facts": [{"kind": "token_name", "op": "add", "token": "color.focus.ring"}]},
        {"id": "T3", "summary": "묶음 행 토큰 이름(font.weight.bold) 값 변경", "facts": [{"kind": "token_value", "token": "font.weight.bold"}]},
        {"id": "P1", "summary": "명세가 위치를 고정한 요소 이동", "facts": [{"kind": "placement", "component": "CMP-001", "spec_rule": "fixed"}]},
        {"id": "P2", "summary": "최솟값 이상 치수", "facts": [{"kind": "dimension", "component": "CMP-025", "value": 60, "spec": {"value": 56, "bound": "min"}}]},
    ]}, ensure_ascii=False))
    code, out = pi("impact", *P, "--design", "--request", str(req))
    c1 = item(out, "C1")
    check("I09 복합 변경 ①+③: 두 유형 모두, 대표 유형은 상위(①)", c1.get("status") == "classified" and cats(c1) == ["info_behavior", "theme_value"]
          and c1.get("primary") == "info_behavior", c1)
    check("I09a 복합 변경 재승인 단계 합집합(중복 없음)", c1.get("reapproval_stages") == up, c1.get("reapproval_stages"))
    c2 = item(out, "C2")
    check("I10 판단 필요 사실이 섞이면 항목 전체 needs_review(부분 분류·추정 영향 유지, 대표 유형 없음)",
          c2.get("status") == "needs_review" and cats(c2) == ["visual"] and c2.get("primary") is None
          and any("자동으로 확정하지 않았습니다" in n for n in c2.get("notes", [])), c2)
    for iid, label in (("U1", "알 수 없는 사실 종류"), ("U2", "사실 없음"), ("U3", "승인 문서에 없는 참조"), ("U4", "알 수 없는 표현 속성"), ("T2", "이미 있는 토큰 추가")):
        check(f"I11 분류 불가 → needs_review: {label}", item(out, iid).get("status") == "needs_review", item(out, iid))
    check("I12 04에 없는 토큰에 값 → ②(새 의미 토큰)", cats(item(out, "T1")) == ["token_semantics"], item(out, "T1"))
    check("I12a 묶음 행 토큰(font.weight.regular / bold)도 인식 → ③", cats(item(out, "T3")) == ["theme_value"], item(out, "T3"))
    check("I12b 위치 고정 명세 → ① 확정, 최솟값 이상 → ④ 확정", cats(item(out, "P1")) == ["info_behavior"] and item(out, "P1")["status"] == "classified"
          and cats(item(out, "P2")) == ["visual"] and "spec_conflict" not in item(out, "P2")["flags"], (item(out, "P1"), item(out, "P2")))
    bad = root / "bad.json"; bad.write_text('{"items": []}')
    code, out = pi("impact", *P, "--design", "--request", str(bad))
    check("I13 요청 형식 오류 → JSON 오류(invalid_request)", code == 2 and out.get("error") == "invalid_request", out)

    # ---- 파일·토큰 이름 기준 자동 분류(git 차이)
    code, out = pi("impact", *P, "--design")
    check("I14 변경 없음 → 항목 0", code == 0 and out["items"] == [] and out["source"]["mode"] == "files", out)

    def file_case(label, mutate, path_key, expect_status, expect_cats, extra=None):
        mutate()
        code, out = pi("impact", *P, "--design")
        it = next((i for i in out.get("items", []) if i["id"] == f"file:{path_key}"), {})
        ok = code == 0 and it.get("status") == expect_status and cats(it) == expect_cats and (extra is None or extra(it, out))
        check(f"I15 파일 분류: {label}", ok, {k: it.get(k) for k in ("status", "categories", "impact", "facts")} if it else out)
        T.G(d, "checkout", "--", ".")
        T.G(d, "clean", "-fdq", "--", "docs", "design-preview/src")

    ui = d / T.SPEC[3]
    file_case("04 토큰 값만 변경 → ③(v1 실제 영향 ux_spec)",
              lambda: ui.write_text(ui.read_text().replace("| color.action.primary | #1D5BD0 |", "| color.action.primary | #0E6B4F |")),
              T.SPEC[3], "classified", ["theme_value"],
              lambda it, o: it["facts"][0]["evidence"]["tokens"] == {"color.action.primary": "#1D5BD0 → #0E6B4F"}
              and any(x["effective_stage"] == "ux_spec" for x in it["impact"]))
    file_case("04 토큰 이름 추가 → ②",
              lambda: ui.write_text(ui.read_text().replace("| radius.sm | 6px | 칩 |", "| radius.sm | 6px | 칩 |\n| color.nav.active | #0B4F2C | 현재 탭 |")),
              T.SPEC[3], "classified", ["token_semantics"])
    file_case("04 묶음 행 값 변경 → ③ (font.weight.bold만)",
              lambda: ui.write_text(ui.read_text().replace("| 400 / 700 |", "| 400 / 600 |")),
              T.SPEC[3], "classified", ["theme_value"], lambda it, o: list(it["facts"][0]["evidence"]["tokens"]) == ["font.weight.bold"])
    file_case("04 컴포넌트 정의 변경 → needs_review(변경 CMP 근거, 문서 소속 ux_spec)",
              lambda: ui.write_text(ui.read_text().replace("- **용도**: 탭 높이 56", "- **용도**: 탭 높이 64")),
              T.SPEC[3], "needs_review", [], lambda it, o: "CMP-025" in it["facts"][0]["evidence"]["ids"]
              and any(x["effective_stage"] == "ux_spec" for x in it["impact"]))
    scr = d / T.SPEC[1]
    file_case("02 화면 명세 변경 → ①(변경 SCR 근거)",
              lambda: scr.write_text(scr.read_text().replace("- **목적**: 회원·게스트 명단 관리", "- **목적**: 회원·게스트 명단과 출석 관리")),
              T.SPEC[1], "classified", ["info_behavior"], lambda it, o: "SCR-211" in it["facts"][0]["evidence"]["ids"])
    p00 = d / T.UXP
    file_case("00 UX 결정 변경 → ①, 실제 영향 ux_planning부터(하위 재승인 포함)",
              lambda: p00.write_text(p00.read_text().replace("오른쪽 아래에 띄운다", "헤더에 둔다")),
              T.UXP, "classified", ["info_behavior"],
              lambda it, o: it["impact"][0]["effective_stage"] == "ux_planning" and it["reapproval_stages"][:2] == ["ux_planning", "ux_spec"])
    pl = d / "docs/planning/03-user-stories.md"
    file_case("기획 문서 변경 → 제외(기존 impact·rebase 안내)", lambda: pl.write_text(pl.read_text() + "\n- 메모\n"),
              "docs/planning/03-user-stories.md", "excluded", [])
    readme = d / "README.md"
    readme.write_text(readme.read_text() + "\n메모\n")
    code, out = pi("impact", *P, "--design")
    check("I15a 디자인과 무관한 파일 → unrelated_paths", out.get("unrelated_paths") == ["README.md"] and out["items"] == [], out)
    T.G(d, "checkout", "--", ".")
    if preview_ok:
        tok = d / "design-preview/src/tokens.css"
        file_case("프리뷰 tokens.css 값 변경 → ③", lambda: tok.write_text(tok.read_text().replace("--color-primary: #1f5eff;", "--color-primary: #0e6b4f;")),
                  "design-preview/src/tokens.css", "classified", ["theme_value"])
        file_case("프리뷰 tokens.css 변수 추가 → ②", lambda: tok.write_text(tok.read_text().replace("--radius-md: 8px;", "--radius-md: 8px;\n  --color-nav-active: #0b4f2c;")),
                  "design-preview/src/tokens.css", "classified", ["token_semantics"])
        css = d / "design-preview/src/preview.css"
        file_case("프리뷰 CSS 변경 → ④(실제 영향 preview 재승인)", lambda: css.write_text(css.read_text() + "\n.pv-badge { font-size: 13px; }\n"),
                  "design-preview/src/preview.css", "classified", ["visual"],
                  lambda it, o: it["reapproval_stages"] == ["preview"])
        tsx = d / "design-preview/src/screens/SCR-002.tsx"
        file_case("프리뷰 코드 주석만 변경 → ⑤", lambda: tsx.write_text("// 구현 메모: 코트 카드 순서는 mock 순서\n" + tsx.read_text()),
                  "design-preview/src/screens/SCR-002.tsx", "classified", ["implementation"])
        file_case("프리뷰 코드 변경 → needs_review", lambda: tsx.write_text(tsx.read_text().replace("<h1>", "<h1 className='big'>")),
                  "design-preview/src/screens/SCR-002.tsx", "needs_review", [])
        pkg = d / "design-preview/package.json"
        file_case("프리뷰 package.json 변경 → ⑤", lambda: pkg.write_text(pkg.read_text().replace('"version": "0.0.0"', '"version": "0.0.1"')),
                  "design-preview/package.json", "classified", ["implementation"])
    else:
        skip("I15 프리뷰 파일 분류", "프리뷰 미승인(pnpm 없음)")
    code, out = pi("impact", *P, "--design", "--base", "no-such-ref")
    check("I16 잘못된 기준 커밋 → JSON 오류(invalid_base)", code == 2 and out.get("error") == "invalid_base", out)

    # ---- 읽기 전용: 승인 문서·해시·상태 불변
    check("I17 모든 분류 호출 후 design.json·state.yaml·승인 문서 해시 불변", snapshot(d) == before)
    check("I17a 작업 트리 상태 불변", T.G(d, "status", "--porcelain") == git_before, T.G(d, "status", "--porcelain"))
    code, out = pi("check", *P)
    check("I17b 분류 후에도 check 일치", code == 0, out.get("cross_verify"))

    # ---- 작성 중(in_progress·awaiting) 상태에서는 재승인이 필요 없거나 수정 요청으로 처리
    d2, _ = build_project(root, "awaiting", approve_spec=False)
    code, out = pi("impact", "--project", str(d2), "--design", "--request", str(CASES))
    m = impact_of(item(out, "D1"), "info_behavior")
    check("I18 UX 설계 제출(승인 대기) 상태의 ①: 수정 요청(reopen)으로 처리, 재제출 대상 ux_spec만", m.get("effective_status") == "awaiting_approval"
          and m.get("reapproval_stages") == ["ux_spec"] and "수정 요청" in m.get("action", ""), m)
    m = impact_of(item(out, "D3"), "visual")
    check("I18a 프리뷰가 잠긴 상태의 ④: 재승인 없음, 해당 단계 진행 시 반영", m.get("effective_status") == "locked" and m.get("reapproval_required") is False, m)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {root})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
