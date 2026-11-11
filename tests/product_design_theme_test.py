#!/usr/bin/env python3
"""/product-design 테마 계약(WF-D03)·렌더러 경로(WF-D04) 테스트(자체 완결형).

- 빠른 검증(기본): pnpm 빌드 없이 실행합니다. 픽스처에서 엔진 템플릿 복사(preview-scaffold)만 하고 실제 화면 생성·빌드는 하지 않습니다.
- 완료 검증(PD_FULL=1): 프리뷰 빌드·승인까지 진행해 승인 기록에 렌더러·테마 해시가 남는지 확인합니다.
- 승인은 스크립트 명령으로만 기록합니다. state.yaml·기획 문서는 테스트 픽스처입니다.

실행: python3 tests/product_design_theme_test.py   (완료 검증: PD_FULL=1 python3 tests/product_design_theme_test.py)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402
import product_design_impact_test as IT  # noqa: E402
import product_design_dd_test as DT  # noqa: E402

results: list[tuple[str, bool, str]] = []
FULL = os.environ.get("PD_FULL") == "1"
LEGACY = "design-profile/legacy.json"
THEME = "design-profile/theme.json"
DD = "docs/design/07-design-direction.md"
REVIEW = "docs/design/06-preview-review.md"


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:700]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


pi, state = T.pi, T.state


def P(d):
    return ("--project", str(d))


def raw(d):
    return (d / ".ai-workflow/design.json").read_text()


def errs(out):
    return " / ".join(out.get("errors", []))


def approvals(st):
    return {k: {"status": v["status"], "revision": v["revision"], "approved": v.get("approved")} for k, v in st["stages"].items()}


def theme(**over) -> str:
    data = {"schema": "design-theme/v1", "name": "t", "version": "1.0.0",
            "primitives": {"green": "#0E6B4F", "blue": "#1D5BD0"},
            "tokens": {"color.action.primary": "{green}", "color.focus.ring": "{green}", "font.weight.bold": "600", "radius.sm": "8px"}}
    for k, v in over.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def review_06(rev: int, used: str | None = "code", reason: str = "없음", figma_rows: str = "", comp_rows: str = "") -> str:
    ren = "" if used is None else f"## 렌더러\n- **사용 렌더러**: {used}\n- **전환 사유**: {reason}\n\n"
    return (f"---\ndoc: preview-review\nrevision: {rev}\nlanguage: ko\n---\n# 프리뷰 검토\n\n## 화면별 피드백\n| ID | 화면 | 피드백 | 조치 | 상태 |\n|---|---|---|---|---|\n\n"
            f"{ren}## 렌더러 비교\n| 화면 | 선택 | 근거 |\n|---|---|---|\n{comp_rows}\n"
            f"## 외부 디자인 참조\n| 화면 | 도구 | 링크 | 비고 |\n|---|---|---|---|\n{figma_rows}")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-theme-test-"))
    d, _ = IT.build_project(root, "theme", approve_preview=False)   # ux_planning·ux_spec 승인, 04에 토큰 표
    ui04 = T.sha(d / T.SPEC[3])
    code, out = pi("theme-check", *P(d))
    check("T0 v1 프로젝트: 테마 계약 적용 대상 아님(04 값이 렌더 기준)", code == 0 and out["applicable"] is False, out)

    # ---- 이전 형식 테마로 v2 전환(M1-2 방식) → 계약 미적용, 막지 않음
    (d / "design-profile").mkdir(); (d / LEGACY).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "legacy theme")
    pi("migrate", *P(d), "--to", "v2", "--theme-file", LEGACY, "--confirm")
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "v2")
    code, out = pi("theme-check", *P(d))
    check("T1 이전 형식 테마 파일: 계약 미적용 경고만(해시 추적), 오류 없음", code == 0 and out["contract"] is False
          and any("이전 형식" in w for w in out["warnings"]), out)

    # ---- 테마 경로 변경 정책
    (d / THEME).write_text(theme(name=None))
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME)
    check("P1 설정된 테마 경로를 그냥 바꾸면 거부(theme_file_conflict)", code == 2 and out.get("error") == "theme_file_conflict", out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--replace-theme-file")
    check("P2 새 테마 파일이 계약을 통과하지 못하면 경로 변경 거부", code == 2 and out.get("error") == "invalid_theme_file" and "name" in " ".join(out.get("errors", [])), out)
    (d / THEME).write_text(theme())
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "contract theme")
    before = raw(d); snap = approvals(state(d))
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--replace-theme-file")
    check("P3 경로 변경 계획(확인 없음): 파일 불변, 영향 안내", code == 0 and out.get("dry_run") and raw(d) == before
          and any(LEGACY in c and THEME in c for c in out["plan"]["changes"]), out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--replace-theme-file", "--confirm")
    st = state(d)
    check("P4 경로 변경(사용자 확인): theme_history(이전·새 경로와 해시), history 기록, 기존 승인·해시·revision 불변", code == 0
          and st["config"]["theme_file"] == THEME and st["theme_history"][-1]["from"] == LEGACY and st["theme_history"][-1]["to_hash"] == T.sha(d / THEME)
          and st["history"][-1]["event"] == "theme_file_changed" and approvals(st) == snap, out)
    after = raw(d)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--replace-theme-file", "--confirm")
    check("P5 같은 경로로 재실행 → already_v2(바이트 동일)", code == 0 and out.get("status") == "already_v2" and raw(d) == after, out)
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "theme path")

    # ---- 계약 검사
    code, out = pi("theme-check", *P(d), "--print-css")
    div = {x["token"]: x for x in out.get("divergence", [])}
    check("C1 올바른 테마: 통과, 04와 다른 값(출처·적용 기준 기록)", code == 0 and out["contract"] is True
          and div["color.action.primary"]["approved_04_value"] == "#1D5BD0" and div["color.action.primary"]["theme_value"] == "#0E6B4F"
          and div["color.action.primary"]["applied"] == "theme" and out["sources"]["04"]["ux_spec_revision"] == 1
          and out["sources"]["theme"]["hash"] == T.sha(d / THEME), out)
    check("C1a 묶음 행 토큰(font.weight.bold)도 04 값과 대조, 테마에 없는 04 토큰은 04 값으로(경고)", "font.weight.bold" in div
          and "font.weight.regular" in out["missing_in_theme"] and out["effective_tokens"]["font.weight.regular"] == "400", out)
    check("C1b 기대 CSS(--print-css): 테마 값 + 04 대체값, 변수 이름 규칙", "--color-action-primary: #0E6B4F;" in out.get("expected_css", "")
          and "--font-weight-regular: 400;" in out["expected_css"], out.get("expected_css"))
    check("C1c 프리뷰가 없으면 tokens.css 일치 검사는 건너뜀", out["sync"].get("skipped"), out["sync"])
    for over, expect, label in (
            ({"tokens": {"color.action.tint": "#E8F3EE"}}, "04에 없는 의미 토큰 이름", "새 토큰 이름(②)"),
            ({"tokens": {"color.action.primary": "{nope}"}}, "없는 원시 값 참조", "없는 원시 값 참조"),
            ({"tokens": {"color.action.primary": "green"}}, "색 값 형식", "색 값 형식"),
            ({"tokens": {"radius.sm": "big"}}, "길이 값 형식", "길이 값 형식"),
            ({"css": {"file": "../tokens.css"}}, "css.file", "css 파일 경로"),
            ({"css": {"var_pattern": "--x"}}, "var_pattern", "변수 이름 규칙")):
        (d / THEME).write_text(theme(**over))
        code, out = pi("theme-check", *P(d))
        check(f"C2 계약 오류: {label}", code == 2 and expect in errs(out), errs(out))
    (d / THEME).write_text(theme())

    # ---- 테마 값 변경의 승인 영향(UX Spec 보존, 04 불변)
    (d / THEME).write_text(theme(primitives={"green": "#15803D", "blue": "#1D5BD0"}))
    code, out = pi("check", *P(d))
    check("A1 테마 값만 변경: ux_spec 승인 문제 없음(UX Spec 승인 보존)", code == 0 and state(d)["stages"]["ux_spec"]["status"] == "approved", out.get("cross_verify"))
    code, out = pi("impact", *P(d), "--design")
    it = next((i for i in out["items"] if i["id"] == f"file:{THEME}"), {})
    th = (it.get("impact") or [{}])[0]
    check("A2 파일 분류: 원시 값 변경 → ③(해석된 토큰 값 변경), 실제 영향 preview, ux_spec·design_direction 보존",
          [c["key"] for c in it.get("categories", [])] == ["theme_value"] and th.get("effective_stage") == "preview"
          and th.get("preserved") == ["ux_spec", "design_direction"], it)
    (d / THEME).write_text(theme(tokens={"color.action.primary": "{green}", "color.focus.ring": "{green}", "font.weight.bold": "600",
                                         "radius.sm": "8px", "color.nav.active": "#0B4F2C"}))
    code, out = pi("impact", *P(d), "--design")
    it = next((i for i in out["items"] if i["id"] == f"file:{THEME}"), {})
    check("A3 파일 분류: 테마에 토큰 이름 추가 → ②(UX Spec 04 개정)", [c["key"] for c in it.get("categories", [])] == ["token_semantics"]
          and it["impact"][0]["effective_stage"] == "ux_spec", it)
    (d / THEME).write_text(json.dumps(json.loads(theme()), ensure_ascii=False) + "\n")   # 형식만(한 줄로)
    code, out = pi("impact", *P(d), "--design")
    it = next((i for i in out["items"] if i["id"] == f"file:{THEME}"), {})
    check("A4 파일 분류: 해석된 값이 같은 형식 변경 → ⑤, 재승인 없음", [c["key"] for c in it.get("categories", [])] == ["implementation"]
          and it["reapproval_stages"] == [], it)
    T.G(d, "checkout", "--", THEME)
    check("A5 모든 테마 명령 뒤 승인된 04 문서는 그대로(자동 수정 없음)", T.sha(d / T.SPEC[3]) == ui04)

    # ---- 렌더러 계약: Design Direction(figma) 승인 → 게이트 켜기 → 프리뷰
    pi("begin", *P(d), "--stage", "design_direction")
    def approve_dd(rev, renderer):
        DT.write_07(d, 1, rev=rev, renderer=renderer, scope="| SCR-211 | SCR-211-ST1 | VD-001 |\n",
                    vd1_rel="SCR-211, CMP-001, UXD-014, color.action.primary")
        pi("done", *P(d), "--path", DD); pi("submit", *P(d), "--stage", "design_direction")
        return pi("approve", *P(d), "--stage", "design_direction", "--revision", str(rev))
    code, out = approve_dd(1, "figma")
    check("R0 Design Direction 승인(렌더러 figma 기록)", code == 0 and state(d)["stages"]["design_direction"]["approved"]["renderer"] == "figma", out)
    pi("migrate", *P(d), "--to", "v2", "--enable-gate", "design_direction", "--confirm")
    pi("begin", *P(d), "--stage", "preview"); pi("preview-scaffold", *P(d))
    tc = pi("theme-check", *P(d), "--print-css")[1]
    (d / "design-preview/src/tokens.css").write_text(tc["expected_css"])
    def renderer_errors(content):
        (d / REVIEW).write_text(content)
        code, out = pi("preview-check", *P(d))
        return [e for e in out.get("errors", []) if e.startswith("렌더러")], [e for e in out.get("errors", []) if e.startswith("테마")]
    rer, ter = renderer_errors(review_06(1, used="figma"))
    check("R1 figma 경로인데 Figma 링크가 없으면 프리뷰 검사 실패", any("SCR-211" in e and "Figma 링크" in e for e in rer), rer)
    check("S1 tokens.css가 기대 CSS와 같으면 테마 일치 오류 없음", ter == [], ter)
    rer, _ = renderer_errors(review_06(1, used="figma", figma_rows="| SCR-211 | Figma | https://www.figma.com/design/x?node-id=1-2 | 검토용 |\n"))
    check("R2 figma 경로 + Figma 참조 링크 → 렌더러 오류 없음(최종 승인은 프리뷰)", rer == [], rer)
    rer, _ = renderer_errors(review_06(1, used="code", reason="Figma MCP 호출 한도 초과(사용자 확인)"))
    check("R3 Figma 한도 초과 → code로 전환(사유 기록) 시 Code-first로 정상 진행", rer == [], rer)
    rer, _ = renderer_errors(review_06(1, used="code", reason="없음"))
    check("R4 사유 없이 code로 전환 → 오류", any("전환 사유" in e for e in rer), rer)
    rer, _ = renderer_errors(review_06(1, used="both"))
    check("R5 07과 다른 비-code 경로로 전환 → 오류(Design Direction 재검토 필요)", any("다시 엽니다" in e for e in rer), rer)
    rer, _ = renderer_errors(review_06(1, used=None))
    check("R5a 06에 사용 렌더러가 없으면 07 렌더러(figma)로 보고 링크 요구", any("Figma 링크" in e for e in rer), rer)
    # 테마 ↔ tokens.css 불일치
    css = d / "design-preview/src/tokens.css"
    css.write_text(tc["expected_css"].replace("#0E6B4F", "#123456", 1))
    _, ter = renderer_errors(review_06(1, used="figma", figma_rows="| SCR-211 | Figma | https://figma.com/x | |\n"))
    check("S2 tokens.css 값이 테마와 다르면 프리뷰 검사 실패(변수·기대값 명시)", any("--color-action-primary" in e and "#0E6B4F" in e for e in ter), ter)
    css.write_text(tc["expected_css"].replace("  --color-focus-ring: #0E6B4F;\n", ""))
    code, out = pi("theme-check", *P(d))
    check("S3 tokens.css에 토큰 변수가 빠지면 오류", code == 2 and "--color-focus-ring" in errs(out), errs(out))
    css.write_text(tc["expected_css"])

    # both 경로: Design Direction 재검토(게이트 켜짐 → 프리뷰 무효) 후 both로 재승인
    pi("reopen", *P(d), "--stage", "design_direction", "--reason", "both 비교")
    code, out = approve_dd(2, "both")
    pi("begin", *P(d), "--stage", "preview")
    man = d / "design-preview/preview.manifest.json"; m = json.loads(man.read_text()); m["design_direction_revision"] = 2
    man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    rer, _ = renderer_errors(review_06(1, used="both"))
    check("R6 both 경로: 화면별 비교(선택·근거)가 없으면 오류", any("렌더러 비교" in e for e in rer), rer)
    rer, _ = renderer_errors(review_06(1, used="both", comp_rows="| SCR-211 | figma | 대비가 더 좋음 |\n"))
    check("R6a both: figma를 고르면 Figma 링크 필요", any("Figma 링크가 없습니다" in e for e in rer), rer)
    rer, _ = renderer_errors(review_06(1, used="both", comp_rows="| SCR-211 | code | 토큰 연결이 정확함 |\n"))
    check("R6b both: code 선택 + 근거 → 통과", rer == [], rer)
    pi("reopen", *P(d), "--stage", "design_direction", "--reason", "code로 결정")
    code, out = approve_dd(3, "code")
    pi("begin", *P(d), "--stage", "preview")
    m["design_direction_revision"] = 3; man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    rer, _ = renderer_errors(review_06(1, used=None))
    check("R7 code 경로: 06 렌더러 기록이 없어도 통과(Figma 불필요)", rer == [], rer)
    check("R8 렌더러 검사 전체에서 승인된 04·07 문서 불변, ux_spec 승인 유지", T.sha(d / T.SPEC[3]) == ui04
          and state(d)["stages"]["ux_spec"]["status"] == "approved")

    # ---- 완료 검증: 프리뷰 빌드·승인(렌더러·테마 기록)
    if not FULL:
        skip("F1–F3 프리뷰 승인 기록(렌더러·테마)", "빠른 검증 단계(PD_FULL=1에서 실행)")
    else:
        T.fill_preview(d, 1)
        m = json.loads(man.read_text()); m["screens"]["SCR-211"] = {"skip": "테스트"}; m["design_direction_revision"] = 3
        man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        (d / REVIEW).write_text(review_06(1, used="code", reason="없음"))
        pi("done", *P(d), "--path", REVIEW)
        code, out = pi("preview-verify", *P(d))
        code2, out2 = pi("submit", *P(d), "--stage", "preview")
        code3, out3 = pi("approve", *P(d), "--stage", "preview", "--revision", "1")
        rec = state(d)["stages"]["preview"].get("approved") or {}
        check("F1 Code-first로 프리뷰 승인: 렌더러(계획·사용)·테마 해시·DD revision 기록", code == 0 and code2 == 0 and code3 == 0
              and rec.get("renderer") == {"planned": "code", "used": "code", "switched": False, "reason": None}
              and rec.get("theme_hash") == T.sha(d / THEME) and rec.get("design_direction_revision") == 3,
              (code, out.get("result"), out.get("check", {}).get("errors"), out2, out3, {k: rec.get(k) for k in ("renderer", "design_direction_revision")}))
        (d / THEME).write_text(theme(primitives={"green": "#15803D", "blue": "#1D5BD0"}))
        code, out = pi("check", *P(d))
        kinds = [(p["stage"], p["kind"]) for p in out["cross_verify"]["problems"]]
        check("F2 승인 뒤 테마 값 변경 → preview만 theme_changed(UX Spec·Design Direction 승인 보존)", ("preview", "theme_changed") in kinds
              and all(s == "preview" for s, _ in kinds), kinds)
        check("F3 04·07 승인 문서 해시 불변", T.sha(d / T.SPEC[3]) == ui04 and state(d)["stages"]["design_direction"]["approved"]["hashes"][DD] == T.sha(d / DD))

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {root})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
