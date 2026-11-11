#!/usr/bin/env python3
"""/product-design Design Direction 단계(WF-D02)·게이트 활성화·의미 해시(sem-2) 테스트(자체 완결형).

- 승인은 스크립트 명령으로만 기록합니다. state.yaml·기획 문서는 테스트 픽스처입니다.
- design.json을 손으로 고치는 경우는 '이전 형식(M1-2) 기록을 다시 계산하지 않는지' 확인할 때뿐입니다(S10).
- 프리뷰가 승인된 프로젝트가 필요한 항목은 pnpm 빌드가 가능할 때만 실행합니다.

실행: python3 tests/product_design_dd_test.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402
import product_design_impact_test as IT  # noqa: E402

ENGINE = HERE.parent
spec = importlib.util.spec_from_file_location("pd", ENGINE / "skills/product-design/scripts/product_design.py")
PD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PD)

results: list[tuple[str, bool, str]] = []
THEME = "design-profile/theme.json"
DD = "docs/design/07-design-direction.md"


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
    return {k: {"status": v["status"], "revision": v["revision"], "approved": v.get("approved"), "submitted": v.get("submitted")}
            for k, v in st["stages"].items()}


def write_07(d: Path, ux_rev: int, rev: int = 1, vd2: str = "제외(시안 비교 후 제외)", extra_vd: str = "", scope: str | None = None,
             renderer: str = "code", crs: str = "", drop: str = "", policies: str | None = None, fm_rev: int | None = None,
             vd1_rel: str = "SCR-001, CMP-001, UXD-001") -> None:
    scope = scope if scope is not None else "| SCR-001 | SCR-001-ST1, SCR-001-ST3 | VD-001 |\n| SCR-002 | SCR-002-ST1 | VD-001 |\n"
    policies = policies if policies is not None else "| density | 첫 화면 8행 | 운영진 요청 |\n| touch.min | 44px | WCAG 2.5.8 |\n| safe_area | 하단 34px 가정 | iOS |\n"
    sections = {
        "입력": f"""## 1. 입력
- **UX 설계 기준**: ux_spec r{ux_rev}(승인됨)
- **디자인 프로필**: design-profile/README.md
- **브랜드·시각 방향**: 차분한 초록 계열, 현장 가독성 우선
- **컴포넌트·토큰 매핑**: 04 문서 토큰 사용
- **규칙 출처**: 없음
""",
        "디자인 방향": "## 2. 디자인 방향과 스타일 원칙\n- 고대비, 높은 정보 밀도\n",
        "시각 결정": f"""## 3. 시각 결정 (VD)
<!-- ### VD-900: 예시(주석이라 무시)
- **상태**: 이상한값 -->
### VD-001: 코트 카드 2열
- **결정**: 넓은 화면에서 2열
- **상태**: 승인
- **근거**: 사용자 결정
- **관련**: {vd1_rel}
- **토큰 밖 값**: 없음
### VD-002: 둥근 버튼
- **결정**: 반경 24
- **상태**: {vd2}
- **근거**: A/B 실험
- **관련**: CMP-001
- **토큰 밖 값**: 있음(반경 24)
{extra_vd}""",
        "정책 값": f"## 4. 정책 값\n| 정책 | 값 | 근거 |\n|---|---|---|\n{policies}",
        "렌더링 경로": f"## 5. 렌더링 경로\n- **렌더러**: {renderer}\n- **최종 시각 승인**: design-preview/ + 06\n",
        "렌더 범위": f"## 6. 렌더 범위(화면·상태)\n| 화면 | 상태 | 적용 VD |\n|---|---|---|\n{scope}",
        "UX Spec과의 차이": f"## 7. UX Spec과의 차이와 변경 요청\n{crs}",
        "실험": "## 8. 실험 허용 목록\n| 항목 | 범위 | 근거 |\n|---|---|---|\n",
        "검증 기준": "## 9. 검증 기준과 도구 제약\n- **검증 기준**: 대비 4.5:1\n- **도구 제약**: Figma 미사용\n",
    }
    body = "".join(v for k, v in sections.items() if k != drop)
    (d / DD).write_text(f"---\ndoc: design-direction\nrevision: {rev}\nlanguage: ko\nbased_on:\n  ux_spec_revision: {fm_rev if fm_rev is not None else ux_rev}\n---\n\n# 디자인 방향\n\n{body}")


def approved_v2_project(root: Path, name: str, approve_spec: bool = True) -> Path:
    d = T.make_product(root, name)
    pi("start", *P(d)); T.write_00(d, 1); pi("done", *P(d), "--path", T.UXP); pi("submit", *P(d), "--stage", "ux_planning")
    pi("approve", *P(d), "--stage", "ux_planning", "--revision", "1"); pi("begin", *P(d), "--stage", "ux_spec")
    T.write_spec(d, 1); T.done_all(d, T.SPEC); pi("checkpoint", *P(d))
    if approve_spec:
        pi("submit", *P(d), "--stage", "ux_spec"); pi("approve", *P(d), "--stage", "ux_spec", "--revision", "1")
    (d / "design-profile").mkdir(); (d / THEME).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "design (user commit)")
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--confirm")
    assert code == 0, out
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "v2 (user commit)")
    return d


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-dd-test-"))

    # ---------------------------------------------------------------- 의미 해시 sem-2(형식별 안전성)
    N = PD.sem_normalize
    ts = b"import { a } from './a'\nexport const x = a + 1\n"
    check("S1 .ts: 줄 전체 주석·빈 줄·들여쓰기만 다름 → 같은 의미 해시",
          N("src/a.ts", ts) == N("src/a.ts", b"// \xeb\xa9\x94\xeb\xaa\xa8\n\nimport { a } from './a'\n  /* \xec\xa3\xbc\xec\x84\x9d */\n    export const x = a + 1   \n"))
    check("S1a .ts: 코드 공백 변경(토큰 사이)은 다르게 봄", N("src/a.ts", ts) != N("src/a.ts", b"import { a } from './a'\nexport const x = a +1\n"))
    tl = b"export const s = `a\n// not a comment\n  b`\n"
    check("S2 .ts 템플릿 리터럴 → 원본 비교(줄 앞 // 가 문자열일 수 있음)", N("src/t.ts", tl) == tl and N("src/t.ts", tl) != N("src/t.ts", tl.replace(b"not", b"NOT")))
    lc = b"export const s = 'a\\\n  b'\n"
    check("S3 .ts 줄 이음 문자열 → 원본 비교", N("src/l.ts", lc) == lc)
    mb = b"const a = 1\n/* start */ const b = 2\n"
    check("S4 .ts 주석 뒤 같은 줄 코드 → 원본 비교", N("src/m.ts", mb) == mb)
    tsx = b"export const A = () => <p>\n  // hi\n</p>\n"
    check("S5 .tsx: JSX 안 // 는 화면 글자 → 원본 비교(주석 변경도 다르게 봄)", N("src/A.tsx", tsx) == tsx
          and N("src/A.tsx", tsx) != N("src/A.tsx", tsx.replace(b"hi", b"HI")))
    check("S6 .tsx: 인라인 요소 사이 공백·줄바꿈 차이(렌더 차이)를 놓치지 않음",
          N("src/B.tsx", b"<b>a</b> <i>b</i>") != N("src/B.tsx", b"<b>a</b>\n<i>b</i>"))
    css = b".a {\n  color: red; /* note */\n  content: \"x  y\";\n}\n"
    check("S7 .css: 주석·공백만 다름 → 같음", N("s.css", css) == N("s.css", b".a { color: red;\n content: \"x  y\"; }\n"))
    check("S7a .css: 문자열 안 공백 변경은 다르게 봄", N("s.css", css) != N("s.css", css.replace(b"x  y", b"x y")))
    check("S7b .css: a/**/b ≠ ab ≠ a b", len({N("s.css", b"div/**/.x{}"), N("s.css", b"div.x{}"), N("s.css", b"div .x{}")}) == 3)
    check("S7c .css: 따옴표 없는 url(…) → 원본 비교", N("s.css", b"a{background:url(data:x/*y*/)}") == b"a{background:url(data:x/*y*/)}")
    check("S8 참조되지 않는 .md → 의미 해시 제외, 참조되면 원본", N("README.md", b"x") is None and N("README.md", b"x", md_referenced=True) == b"x")
    check("S9 .json·.html·.svg → 원본", all(N(f, b" a  b ") == b" a  b " for f in ("a.json", "index.html", "i.svg")))

    # ---------------------------------------------------------------- 단계 명령(게이트 없이도 동작)
    d = approved_v2_project(root, "dd")
    v1d = T.make_product(root, "v1only"); pi("start", *P(v1d))
    code, out = pi("begin", *P(v1d), "--stage", "design_direction")
    check("D01 v1 프로젝트 → stage_not_in_workflow", code == 2 and out.get("error") == "stage_not_in_workflow", out)
    du = approved_v2_project(root, "dd_unapproved", approve_spec=False)
    code, out = pi("begin", *P(du), "--stage", "design_direction")
    check("D02 UX 설계 미승인 → 시작 거부", code == 2 and out.get("error") == "upstream_not_approved", out)
    code, out = pi("begin", *P(d), "--stage", "design_direction")
    check("D03 UX 설계 승인 후 시작(based_on_ux_spec_revision 기록)", code == 0 and out.get("based_on_ux_spec_revision") == 1, out)

    for kw, expect, label in (
            ({"drop": "렌더링 경로"}, "'렌더링 경로' 섹션", "필수 섹션 누락"),
            ({"fm_rev": 9}, "based_on.ux_spec_revision", "front matter 기준 revision 불일치"),
            ({"vd2": "후보"}, "VD-002: 승인되지 않은 VD(후보)", "후보 VD"),
            ({"vd2": "미결정"}, "VD-002: 승인되지 않은 VD(미결정)", "미결정 VD"),
            ({"scope": "| SCR-001 | SCR-001-ST1 | VD-001, VD-002 |\n"}, "승인되지 않은 VD-002(제외)", "제외한 VD를 렌더에 사용"),
            ({"scope": "| SCR-999 | SCR-999-ST1 | VD-001 |\n"}, "없는 화면 SCR-999", "없는 화면"),
            ({"scope": "| SCR-001 | SCR-001-ST9 | VD-001 |\n"}, "없는 상태 SCR-001-ST9", "없는 상태"),
            ({"scope": ""}, "렌더 범위(화면·상태 표)가 없습니다", "렌더 범위 없음"),
            ({"vd1_rel": "SCR-001, color.brand.new"}, "04에 없는 토큰 color.brand.new", "04에 없는 토큰(②)"),
            ({"vd1_rel": "CMP-777"}, "없는 참조 CMP-777", "없는 컴포넌트"),
            ({"renderer": "sketch"}, "렌더러는", "잘못된 렌더러"),
            ({"policies": "| density | 8행 | - |\n| touch.min | 44px | - |\n"}, "정책 값 'safe_area'", "정책 값 누락"),
            ({"crs": "### CR-001: 안내 줄 삭제\n- **분류**: ①\n- **상태**: 미결\n"}, "CR-001: ①·②(UX Spec) 변경 요청", "남은 ① 변경 요청"),
            ({"crs": "### CR-002: 새 의미 색\n- **분류**: ②\n- **상태**: UX Spec 개정 요청\n"}, "CR-002: ①·②", "남은 ② 변경 요청"),
            ({"crs": "### CR-003: 점수 열\n- **분류**: needs_review\n- **상태**: 미결\n"}, "CR-003: 분류가 확정되지 않은", "판단 필요 변경 요청")):
        write_07(d, 1, **kw)
        code, out = pi("trace", *P(d), "--stage", "design_direction")
        check(f"D04 07 검증 오류: {label}", code == 2 and expect in errs(out), errs(out))
    write_07(d, 1, crs="### CR-001: 안내 줄 삭제\n- **분류**: ①\n- **상태**: 기각(UX 유지)\n### CR-002: 반경\n- **분류**: ④\n- **상태**: 반영(VD-002 제외)\n")
    code, out = pi("trace", *P(d), "--stage", "design_direction")
    check("D05 올바른 07: 통과(기각한 ①, 반영한 ④는 허용, 주석 속 예시 VD 무시)", code == 0 and out["counts"]["VD"] == 2 and out["counts"]["VD_approved"] == 1
          and out["counts"]["renderer"] == "code" and out["counts"]["render_states"] == 3 and any("토큰 밖" in w for w in out["warnings"]), out)
    good07 = (d / DD).read_text()
    write_07(d, 1, rev=2)
    code, out = pi("done", *P(d), "--path", DD)
    check("D06 front matter revision 불일치 → done 거부", code == 2 and out.get("error") == "revision_mismatch", out)
    write_07(d, 1, vd2="후보")
    pi("done", *P(d), "--path", DD)
    code, out = pi("submit", *P(d), "--stage", "design_direction")
    check("D07 VD 미승인(후보) 상태에서 제출 거부", code == 2 and out.get("error") == "trace_failed" and "VD-002" in errs(out), out)
    (d / DD).write_text(good07); pi("done", *P(d), "--path", DD)
    code, out = pi("submit", *P(d), "--stage", "design_direction")
    check("D08 제출 r1", code == 0 and out["revision"] == 1, out)
    (d / DD).write_text(good07 + "\n추가\n")
    code, out = pi("approve", *P(d), "--stage", "design_direction", "--revision", "1")
    check("D08a 제출 뒤 07 변경 → 승인 거부", code == 2 and out.get("error") == "changed_since_submit", out)
    (d / DD).write_text(good07)
    code, out = pi("approve", *P(d), "--stage", "design_direction", "--revision", "2")
    check("D08b 다른 revision 승인 거부", code == 2 and out.get("error") == "revision_mismatch", out)
    code, out = pi("approve", *P(d), "--stage", "design_direction", "--revision", "1")
    rec = state(d)["stages"]["design_direction"]["approved"]
    check("D08c 승인: 07 해시·UX 설계 기준 해시·승인 VD·렌더러·테마 해시 기록", code == 0 and rec["hashes"][DD] == T.sha(d / DD)
          and rec["ux_spec_revision"] == 1 and rec["ux_spec_hashes"] == state(d)["stages"]["ux_spec"]["approved"]["hashes"]
          and rec["approved_vds"] == ["VD-001"] and rec["renderer"] == "code" and rec["theme_hash"] == T.sha(d / THEME), rec)
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "dd approved (user commit)")
    snap = approvals(state(d))
    (d / DD).write_text(good07.replace("현장 가독성", "현장 가독성과 브랜드"))
    code, out = pi("check", *P(d))
    check("D09 승인된 07 외부 변경 → approved_modified, 해시 재기록 없음", code == 2 and any(p["stage"] == "design_direction" and p["kind"] == "approved_modified"
          for p in out["cross_verify"]["problems"]) and approvals(state(d)) == snap, out)
    code, out = pi("begin", *P(d), "--stage", "preview")
    check("D09a 게이트 꺼짐: 07 변경은 프리뷰 진행을 막지 않음(의존 아님)", code == 0, out)
    (d / DD).write_text(good07)
    # 상위(UX 설계) 승인 문서 변경 → design_direction 명령 차단
    ia = d / T.SPEC[0]; ia_o = ia.read_text(); ia.write_text(ia_o + "\n메모\n")
    code, out = pi("reopen", *P(d), "--stage", "design_direction", "--reason", "x")
    check("D12 승인된 UX 설계 변경 → design_direction 명령 차단(upstream_modified)", code == 2 and out.get("error") == "upstream_modified", out)
    ia.write_text(ia_o)
    # UX 설계 재검토 → design_direction·preview 무효
    code, out = pi("reopen", *P(d), "--stage", "ux_spec", "--reason", "정보 추가")
    st = state(d)
    check("D11 ux_spec reopen → design_direction(승인 해제, last_approved 보존)·preview 무효", code == 0 and set(out["invalidated"]) == {"design_direction", "preview"}
          and st["stages"]["design_direction"]["status"] == "locked" and st["stages"]["design_direction"]["approved"] is None
          and st["stages"]["design_direction"]["last_approved"]["revision"] == 1, out)
    T.write_spec(d, 2); T.done_all(d, T.SPEC); pi("submit", *P(d), "--stage", "ux_spec")
    code, out = pi("approve", *P(d), "--stage", "ux_spec", "--revision", "2")
    st = state(d)
    check("D11a ux_spec 재승인 → design_direction·preview 잠금 해제(게이트 꺼짐: preview는 ux_spec만 기준)",
          st["stages"]["design_direction"]["status"] == "not_started" and st["stages"]["preview"]["status"] == "not_started", st["stages"])
    pi("begin", *P(d), "--stage", "design_direction")
    write_07(d, 1, rev=2)
    code, out = pi("trace", *P(d), "--stage", "design_direction")
    check("D11b 재검토 후 07은 새 UX 설계 기준(r2)을 적어야 함", code == 2 and "r2" in errs(out), errs(out))

    # ---------------------------------------------------------------- 게이트: 프리뷰가 승인된 기존 v2 프로젝트
    dp, ok = IT.build_project(root, "gate")
    if not ok:
        skip("G1–G12", "pnpm 빌드 불가")
    else:
        (dp / "design-profile").mkdir(); (dp / THEME).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
        (dp / "design-profile/README.md").write_text("# 프로필\n")
        T.G(dp, "add", "-A"); T.G(dp, "commit", "-qm", "theme")
        pi("migrate", *P(dp), "--to", "v2", "--theme-file", THEME, "--confirm")
        T.G(dp, "add", "-A"); T.G(dp, "commit", "-qm", "v2")
        pv0 = approvals(state(dp))["preview"]
        code, out = pi("check", *P(dp))
        check("G1 M1-2 방식 v2 프로젝트: 승인된 프리뷰 그대로, 게이트 꺼짐", code == 0 and state(dp)["stages"]["preview"]["status"] == "approved"
              and out["workflow"]["gates"] == {"design_direction": False}, out)
        pi("begin", *P(dp), "--stage", "design_direction")
        write_07(dp, 1, scope="| SCR-211 | SCR-211-ST1 | VD-001 |\n", vd1_rel="SCR-211, CMP-001, UXD-014, color.action.primary")
        pi("done", *P(dp), "--path", DD); pi("submit", *P(dp), "--stage", "design_direction")
        code, out = pi("approve", *P(dp), "--stage", "design_direction", "--revision", "1")
        check("G2 게이트 꺼짐: Design Direction 승인해도 프리뷰 승인·해시 불변", code == 0 and approvals(state(dp))["preview"] == pv0, out)
        code, out = pi("reopen", *P(dp), "--stage", "design_direction", "--reason", "색 재검토")
        check("G3 게이트 꺼짐: Design Direction reopen이 프리뷰를 무효화하지 않음", code == 0 and out["invalidated"] == []
              and approvals(state(dp))["preview"] == pv0, out)
        before = raw(dp)
        code, out = pi("migrate", *P(dp), "--to", "v2", "--enable-gate", "design_direction")
        check("G4 게이트 활성화 계획(확인 없음): 파일 불변, 승인된 프리뷰 유지 안내", code == 0 and out.get("dry_run") and raw(dp) == before
              and "유지" in out["plan"]["gate_effect"], out)
        code, out = pi("migrate", *P(dp), "--to", "v2", "--enable-gate", "design_direction", "--confirm")
        st = state(dp)
        check("G5 게이트 활성화(명시적 동의): config.gates, 기존 승인·해시·revision 불변", code == 0 and st["config"]["gates"] == {"design_direction": True}
              and approvals(st)["preview"] == pv0 and approvals(st)["ux_spec"] == approvals(json.loads(before))["ux_spec"]
              and st["history"][-1]["event"] == "gate_enabled" and st["gate_activations"][0]["preview_status"] == "approved", out)
        after = raw(dp)
        code, out = pi("migrate", *P(dp), "--to", "v2", "--enable-gate", "design_direction", "--confirm")
        check("G5a 활성화 재실행 멱등(already_v2, 바이트 동일)", code == 0 and out["status"] == "already_v2" and raw(dp) == after, out)
        code, out = pi("check", *P(dp))
        check("G6 활성화 직후 기존 프리뷰 승인은 차단·무효화되지 않음(게이트 이전 승인 표시)", code == 0
              and out["workflow"]["preview_pre_gate_approval"] is True and state(dp)["stages"]["preview"]["status"] == "approved", out)
        code, out = pi("reopen", *P(dp), "--stage", "preview", "--reason", "개정")
        T.write_06(dp, 2); pi("done", *P(dp), "--path", "docs/design/06-preview-review.md")
        code, out = pi("submit", *P(dp), "--stage", "preview")
        check("G7 게이트 켜짐 + Design Direction 미승인 → 프리뷰 제출 차단", code == 2 and out.get("error") == "design_direction_not_approved", out)
        # Design Direction 다시 승인
        write_07(dp, 1, rev=2, scope="| SCR-211 | SCR-211-ST1 | VD-001 |\n", vd1_rel="SCR-211, CMP-001, UXD-014, color.action.primary")
        pi("done", *P(dp), "--path", DD); pi("submit", *P(dp), "--stage", "design_direction")
        code, out = pi("approve", *P(dp), "--stage", "design_direction", "--revision", "2")
        check("G8 게이트 켜짐에서도 진행 중인 프리뷰는 Design Direction 승인으로 무효화되지 않음", code == 0
              and state(dp)["stages"]["preview"]["status"] == "in_progress", out)
        code, out = pi("preview-check", *P(dp))
        check("G9 게이트 켜짐: manifest에 승인된 Design Direction revision이 없으면 프리뷰 검사 실패", code == 2 and "design_direction_revision" in errs(out), out)
        man = dp / "design-preview/preview.manifest.json"; m = json.loads(man.read_text())
        m["design_direction_revision"] = 2; m["screens"]["SCR-001"]["vd"] = ["VD-002"]
        man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        code, out = pi("preview-check", *P(dp))
        check("G9a 승인되지 않은 VD(제외)를 정식 렌더에 쓰면 프리뷰 검사 실패", code == 2 and "VD-002" in errs(out), out)
        m["screens"]["SCR-001"]["vd"] = ["VD-001"]; man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
        code, out = pi("preview-verify", *P(dp))
        code, out = pi("submit", *P(dp), "--stage", "preview")
        check("G10 Design Direction 승인 후 프리뷰 제출(기준 revision 기록)", code == 0
              and state(dp)["stages"]["preview"]["submitted"]["design_direction_revision"] == 2, out)
        code, out = pi("approve", *P(dp), "--stage", "preview", "--revision", "2")
        rec = state(dp)["stages"]["preview"]["approved"]
        check("G10a 프리뷰 승인: Design Direction revision·해시와 sem-2 의미 해시 기록", code == 0 and rec["design_direction_revision"] == 2
              and rec["semantic_algo"] == "sem-2", rec)
        code, out = pi("check", *P(dp))
        check("G10b 승인 후 check 일치(게이트 이전 승인 표시 해제)", code == 0 and out["workflow"]["preview_pre_gate_approval"] is False, out)
        code, out = pi("reopen", *P(dp), "--stage", "design_direction", "--reason", "브랜드 재검토")
        st = state(dp)
        check("G11 게이트 켜짐: Design Direction reopen → 프리뷰 무효(사용자 재검토 시에만)", code == 0 and out["invalidated"] == ["preview"]
              and st["stages"]["preview"]["status"] == "locked", out)
        code, out = pi("begin", *P(dp), "--stage", "preview")
        check("G12 게이트 켜짐: Design Direction 미승인 → 프리뷰 시작 거부", code == 2 and out.get("error") == "upstream_not_approved", out)

        # S10: 이전 형식(M1-2, 알고리즘 표시 없음) 의미 해시 기록은 다시 계산하지 않고 원본 비교
        dl, ok2 = IT.build_project(root, "legacy")
        if ok2:
            (dl / "design-profile").mkdir(); (dl / THEME).write_text("{}\n"); T.G(dl, "add", "-A"); T.G(dl, "commit", "-qm", "t")
            pi("migrate", *P(dl), "--to", "v2", "--theme-file", THEME, "--confirm")
            stl = json.loads(raw(dl)); stl["stages"]["preview"]["v2_baseline"].pop("semantic_algo")
            (dl / ".ai-workflow/design.json").write_text(json.dumps(stl, ensure_ascii=False, indent=2) + "\n")
            legacy = raw(dl)
            mock = dl / "design-preview/src/mock/data.ts"; mock.write_text("// 주석만\n" + mock.read_text())
            code, out = pi("check", *P(dl))
            check("S10 이전 형식 의미 해시 기록은 쓰지 않고 원본 비교(보수적) → approved_modified, 기록 교체 없음", code == 2
                  and any(p["stage"] == "preview" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"]) and raw(dl) == legacy, out)
        else:
            skip("S10", "pnpm 빌드 불가")

    passed = sum(1 for _, ok_, _ in results if ok_)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {root})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
