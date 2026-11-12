#!/usr/bin/env python3
"""/product-build ui-guard 테스트(자체 완결형): 배치·계획·커밋 없이 쓰는 읽기 전용 UI 경량 검사(T0~T2).

사례 프로젝트와 무관한 독립 픽스처(product_build_ui_test의 도서관 좌석 예약 기획·디자인 L2)를 씁니다.
- 변경 감지(staged·unstaged·both·untracked·deleted·committed, 한글·공백 경로, rename)
- 전역 필수 검사(기획 승인·디자인 L2 이상·토큰 정본·대응표 무결성)와 변경 파일 검사(레거시 위반 분리)
- 읽기 전용(Git index·상태·승인 문서·대응표 불변), 동시 변경 중 스냅샷 재시도
실행: python3 tests/product_build_uiguard_test.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_build_ui_test as UT  # noqa: E402
import product_design_dd_test as DDT  # noqa: E402

results = T.results
check, pb, pd, G = T.check, T.pb, T.pd, T.G
w = UT.w

TOKENS_CSS = ":root {\n  --color-bg: #FFFFFF;\n  --color-text: #1A1A1A;\n  --color-primary: #0E6B4F;\n  --space-unit: 4px;\n  --radius-md: 8px;\n}\n"
LEGACY = "web/src/features/seats/SeatList.view"
LEGACY_TEXT = "// 좌석 목록(기존 화면)\nexport function SeatList(p) {\n  return box({ color: '#123456' }, Button(p))\n}\n"


def ug(d: Path, *args):
    return pb(d, "ui-guard", *args)


def codes(out: dict, key: str = "errors") -> set[str]:
    return {m.split("]")[0].lstrip("[") for m in out.get(key) or []}


def tree_state(d: Path) -> dict:
    """프로젝트 전체(.git 포함) 파일의 내용 해시·mtime. 읽기 전용 확인용."""
    out = {}
    for p in sorted(d.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[str(p.relative_to(d))] = (T.sha(p), p.stat().st_mtime_ns)
    return out


def reset(d: Path) -> None:
    G(d, "reset", "-q", "--hard")
    G(d, "clean", "-qfd")


def base_fixture(root: Path, name: str) -> Path:
    d = UT.make_ui_product(root, name)
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(props) { return render('button', props) }\n")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    w(d, "web/src/styles/tokens.css", TOKENS_CSS)
    w(d, LEGACY, LEGACY_TEXT)
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    code, out = pb(d, "init"); assert code == 0, out
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    G(d, "add", "-A"); G(d, "commit", "-qm", "profile")
    return d


def register(d: Path) -> None:
    for c, f, e in (("CMP-002", "SeatMap.view", "SeatMap"),):
        code, out = pb(d, "ui-map", "register", "--cmp", c, "--path", f"web/src/components/{f}", "--export", e, "--note", "사용자 확인: 기존 부품")
        assert code == 0, out
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "기존 tokens.css를 기준으로 합니다"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "ui-map")


# ---------------------------------------------------------------- 시나리오
def scenario_main(root: Path) -> None:
    d = base_fixture(root, "guard")

    code, out = ug(d)
    check("G23a 대응표 없음: no_ui_map(사전 조건)", code == 2 and out["error"] == "no_ui_map", out)
    pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Button", "--note", "확인")
    code, out = ug(d)
    check("G23b 토큰 출력 미설정: tokens_not_configured", code == 2 and out["error"] == "tokens_not_configured", out)
    G(d, "add", "-A"); G(d, "commit", "-qm", "partial map")
    register(d)

    # G1 깨끗한 트리
    code, out = ug(d)
    check("G1 배치·계획·build 승인 없이 깨끗한 트리: exit 0, 변경 파일 0, 디자인 L2", code == 0 and out["ok"] and out["counts"]["files"] == 0
          and out["design"]["level"] == "L2" and out["design"]["current"] and out["checks"]["tokens"]["ok"] and out["checks"]["map"]["ok"], out)
    check("G28 JSON 계약: 형식·필수 키·exit와 ok 일치·브라우저 not_run·read_only",
          out.get("format") == "pb-ui-guard/v1" and all(k in out for k in ("ok", "mode", "base", "snapshot", "design", "files", "checks", "errors",
                                                                             "warnings", "legacy", "route_hint", "counts", "browser", "read_only"))
          and set(out["checks"]) == {"protected", "tokens", "audit", "map", "components"} and out["browser"]["status"] == "not_run"
          and out["base"]["ref"] == "HEAD" and len(out["snapshot"]["digest"]) == 16, sorted(out))

    # G30 기존 token-audit 출력(추출 리팩터 후에도 같은 판정)
    code, out = pb(d, "token-audit")
    check("G30 기존 token-audit: 레거시 파일의 직접 값을 같은 형식으로 보고(리팩터 후 동작 유지)",
          code == 0 and out["findings"] == [{"file": LEGACY, "line": 3, "kind": "color", "value": "#123456"}] and out["mode"] == "warn", out)

    # G3 상태 구분
    w(d, "web/src/features/seats/A.view", "export const A = 1\n"); w(d, "web/src/features/seats/B.view", "export const B = 1\n")
    w(d, "web/src/features/seats/C.view", "export const C = 1\n"); w(d, "web/src/features/seats/E.view", "export const E = 1\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "abc")
    w(d, "web/src/features/seats/A.view", "export const A = 2\n"); G(d, "add", "web/src/features/seats/A.view")
    w(d, "web/src/features/seats/B.view", "export const B = 2\n")
    w(d, "web/src/features/seats/C.view", "export const C = 2\n"); G(d, "add", "web/src/features/seats/C.view")
    w(d, "web/src/features/seats/C.view", "export const C = 3\n")
    w(d, "web/src/features/seats/D.view", "export const D = 1\n")
    (d / "web/src/features/seats/E.view").unlink()
    before = tree_state(d)
    code, out = ug(d)
    st = {f["path"].rsplit("/", 1)[-1]: f["state"] for f in out.get("files", [])}
    check("G3 staged·unstaged·both·untracked·deleted 구분", code == 0 and st == {"A.view": "staged", "B.view": "unstaged", "C.view": "both",
                                                                              "D.view": "untracked", "E.view": "deleted"}, out.get("files"))
    check("G3b both(stage 뒤 재수정): 작업 트리 기준 검사 경고", "staged_differs" in codes(out, "warnings"), out.get("warnings"))
    ug(d, "--strict"); ug(d, "--all"); ug(d, "--path", "web/src/features/seats/B.view")
    after = tree_state(d)
    check("G24 읽기 전용: 여러 모드 실행 전후 프로젝트 전체(.git/index·상태·승인 문서·대응표 포함) 내용·mtime 불변, 새 파일 없음",
          before == after and ".git/index" in after, sorted(set(before) ^ set(after)) or [k for k in before if before[k] != after.get(k)])
    reset(d)

    # G4 한글·공백 경로
    rel = "web/src/features/좌석 목록/예약 화면.view"
    w(d, rel, "export const Reserve = () => box({ color: '#abcdef' })\n")
    code, out = ug(d)
    check("G4 한글·공백 경로: 그대로 인식(-z), 직접 값 위치도 같은 경로", code == 0 and [f["path"] for f in out["files"]] == [rel]
          and out["checks"]["audit"]["findings"][0]["file"] == rel, out.get("files"))
    reset(d)

    # G5 대응된 부품 rename
    G(d, "mv", "web/src/components/Button.view", "web/src/components/Btn.view")
    code, out = ug(d)
    st = {f["path"]: f["state"] for f in out.get("files", [])}
    check("G5 rename: 옛 경로 deleted + 새 경로(rename 감지 끔), 대응표 path_missing 오류", code == 2 and st.get("web/src/components/Button.view") == "deleted"
          and "web/src/components/Btn.view" in st and "path_missing" in codes(out) and out["error"] == "guard_failed", out.get("errors"))
    reset(d)

    # G7 잘못된 base / G8 모드
    code, out = ug(d, "--base", "no-such-ref")
    check("G7b 해석할 수 없는 --base: bad_base", code == 2 and out["error"] == "bad_base", out)
    code, out = ug(d, "--base", "HEAD", "--all")
    check("G8c 모드 옵션 동시 사용 거부", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = ug(d, "--path", "web/src/nope.view")
    check("G8d 없는 --path: path_not_found", code == 2 and out["error"] == "path_not_found", out)
    code, out = ug(d, "--path", LEGACY)
    check("G8a --path: 지정 파일만, 레거시 구분 없이 직접 값 보고(warn → 경고)", code == 0 and out["mode"] == "path" and [f["path"] for f in out["files"]] == [LEGACY]
          and out["checks"]["audit"]["counts"]["findings"] == 1 and out["base"] is None and out["legacy"] is None, out)
    code, out = ug(d, "--all")
    check("G8b --all: 소스 전체 감사(레거시 포함 전부 현재 위반으로)", code == 0 and out["mode"] == "all" and LEGACY in [f["path"] for f in out["files"]]
          and out["checks"]["audit"]["counts"]["findings"] == 1 and "raw_value" in codes(out, "warnings"), out.get("counts"))

    # G14 직접 값: 새 위반만, 레거시 분리
    w(d, LEGACY, LEGACY_TEXT.replace("// 좌석 목록(기존 화면)", "// 좌석 목록(문구 수정)"))
    code, out = ug(d)
    check("G14a 레거시 파일의 다른 줄만 수정: 기존 직접 값은 legacy(실패·경고 아님)", code == 0 and out["checks"]["audit"]["counts"] == {"findings": 0, "legacy": 1, "excepted": 0}
          and out["legacy"]["count"] == 1 and "raw_value" not in codes(out, "warnings"), out)
    w(d, LEGACY, LEGACY_TEXT + "export const Hint = () => box({ color: 'rgb(1, 2, 3)' })\n")
    w(d, "web/src/features/seats/New.view", "export const New = () => box({ background: '#fff' })\n")
    code, out = ug(d)
    vals = sorted(x["value"] for x in out["checks"]["audit"]["findings"])
    check("G14b 새로 추가한 직접 값만 경고(warn/color 기본), exit 0", code == 0 and vals == ["#fff", "rgb(1, 2, 3)"] and out["checks"]["audit"]["counts"]["legacy"] == 1
          and "raw_value" in codes(out, "warnings") and any(h["code"] == "raw_value" and h["type"] == "T0" for h in out["route_hint"]), out)
    code, out = ug(d, "--strict")
    check("G14c --strict: 경고도 실패", code == 2 and out["error"] == "guard_failed", out.get("error"))
    prof = d / "docs/build/build-profile.toml"
    prof.write_text(UT.PROFILE.replace("[ui.audit]\n", "[ui.audit]\nmode = \"block\"\n"))
    code, out = ug(d)
    check("G14d 프로필 audit.mode=block: 새 직접 값은 오류, 레거시는 여전히 실패 원인 아님", code == 2 and "raw_value" in codes(out)
          and len([m for m in out["errors"] if m.startswith("[raw_value]")]) == 2, out.get("errors"))
    reset(d)

    # G10·G11·G13 토큰 정본
    css = d / "web/src/styles/tokens.css"
    css.write_text(TOKENS_CSS.replace("#0E6B4F", "#FF0000"))
    code, out = ug(d)
    check("G10 토큰 CSS가 정본과 다름: token_mismatch 항상 오류(T0 되돌림 또는 T4)", code == 2 and "token_mismatch" in codes(out)
          and any(f["kind"] == "token_output" for f in out["files"]) and any(h["code"] == "token_mismatch" for h in out["route_hint"]), out.get("errors"))
    css.write_text("/* 정리 */\n" + TOKENS_CSS.replace("#0E6B4F", "#0e6b4f"))
    code, out = ug(d)
    check("G11 토큰 CSS를 바꿨지만 값은 정본과 같음: 통과", code == 0 and out["checks"]["tokens"]["ok"], out.get("errors"))
    css.write_text(TOKENS_CSS.replace("--radius-md: 8px", "--radius-md: 6px"))
    pb(d, "ui-map", "except", "--token", "radius.md", "--reason", "기존 브랜드 가이드", "--note", "사용자 확인: 6px 유지")
    code, out = ug(d)
    check("G13 예외로 등록된 토큰 불일치: excepted로 표시하고 통과", code == 0 and [x["token"] for x in out["checks"]["tokens"]["excepted"]] == ["radius.md"], out)
    reset(d)

    # G9 보호 경로
    w(d, "docs/design/99-scratch.md", "# 임시 메모\n")
    code, out = ug(d)
    check("G9a 승인 문서 폴더에 승인 기록과 다른 변경: protected_path_changed 오류(T3)", code == 2 and "protected_path_changed" in codes(out)
          and out["checks"]["protected"]["changed"] == ["docs/design/99-scratch.md"] and any(h["type"] == "T3" for h in out["route_hint"]), out.get("errors"))
    reset(d)
    w(d, "design-preview/src/Card.view", "export const Card = 1\n")
    code, out = ug(d)
    check("G9b 프리뷰 미승인 단계의 프리뷰 변경: 경고(preview_changed), 제품 코드 검사 아님", code == 0 and "preview_changed" in codes(out, "warnings"), out)
    reset(d)
    first = G(d, "rev-list", "--max-parents=0", "HEAD").strip()
    code, out = ug(d, "--base", first)
    ap = out.get("checks", {}).get("protected", {})
    check("G9c --base 과거 커밋: 이후 승인된 문서는 승인 해시와 같아 approved_change(오류 아님), 상태는 committed",
          code == 0 and "docs/design/02-screens.md" in ap.get("approved_change", []) and not ap.get("changed")
          and {f["state"] for f in out["files"]} == {"committed"} and ".ai-workflow/design.json" in ap.get("workflow_state", []), out.get("errors"))

    # G15~G20 부품
    w(d, "web/src/components/Card.view", "export function Card(p) { return p }\n")
    code, out = ug(d)
    check("G15a 대응표에 없는 새 부품: unregistered_component 경고, exit 0", code == 0 and "unregistered_component" in codes(out, "warnings")
          and out["checks"]["components"]["unregistered"] == [{"file": "web/src/components/Card.view", "exports": ["Card"]}], out)
    code, out = ug(d, "--strict")
    check("G15b --strict: 미등록 부품 경고로 실패", code == 2 and out["error"] == "guard_failed", out.get("error"))
    reset(d)
    w(d, "web/src/features/seats/MyButton.view", "// CMP-001 복사본\nexport function MyButton(p) { return p }\n")
    code, out = ug(d)
    check("G16 이미 대응된 CMP-001 표지를 다른 파일에 구현: duplicate_component 오류", code == 2 and "duplicate_component" in codes(out)
          and out["checks"]["components"]["duplicates"][0]["cmp"] == "CMP-001", out.get("errors"))
    reset(d)
    w(d, "web/src/features/seats/Button.view", "export function Button(p) { return p }\n")
    code, out = ug(d)
    check("G17 대응된 부품과 같은 이름의 새 파일: possible_duplicate 경고", code == 0 and "possible_duplicate" in codes(out, "warnings"), out.get("warnings"))
    reset(d)
    w(d, "web/src/features/seats/Fancy.view", "// CMP-099\nexport const Fancy = 1\n")
    code, out = ug(d)
    check("G18 04 문서에 없는 CMP 표지: unknown_cmp_marker 경고(T4 힌트)", code == 0 and "unknown_cmp_marker" in codes(out, "warnings")
          and any(h["code"] == "unknown_cmp_marker" and h["type"] == "T4" for h in out["route_hint"]), out)
    reset(d)
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function PrimaryButton(props) { return props }\n")
    code, out = ug(d)
    check("G19 대응된 부품의 export 이름이 사라짐: export_not_found 오류(대응표 무결성)", code == 2 and "export_not_found" in codes(out), out.get("errors"))
    reset(d)
    w(d, "web/src/features/seats/Pick.view", "export const Pick = (p) => Button(p)\n")
    code, out = ug(d)
    check("G20 화면 파일이 대응된 부품 사용: components.reuse에 기록", code == 0 and out["checks"]["components"]["reuse"] == {"web/src/features/seats/Pick.view": ["CMP-001"]}, out)
    reset(d)

    # G27 다른 프로세스가 index.lock을 잡은 상태
    w(d, "web/src/features/seats/B2.view", "export const B2 = 1\n")
    lock = d / ".git/index.lock"
    lock.write_text("")
    try:
        code, out = ug(d)
    finally:
        lock.unlink()
    check("G27 index.lock이 있어도 읽기 전용 조회는 실패하지 않음", code == 0 and [f["path"] for f in out["files"]] == ["web/src/features/seats/B2.view"], out)
    reset(d)

    # G2 프로필 없음
    (d / "docs/build/build-profile.toml").unlink()
    code, out = ug(d)
    check("G2 프로필 없음: 기본 프로필로 실행하고 경고", code == 0 and "profile_default" in codes(out, "warnings"), out.get("warnings"))
    reset(d)

    # G29 [ui] 없는 프로필(M2 형태): ui-guard는 기본값 경고, 다른 명령 결과는 ui-guard 실행 전후 동일
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE.split("[ui]")[0])
    G(d, "add", "-A"); G(d, "commit", "-qm", "m2 profile")
    seq = (("status",), ("token-audit",), ("ui-map", "check"), ("token-check",), ("guard", "--base", "HEAD"))
    pre = [pb(d, *s) for s in seq]
    code, out = ug(d)
    post = [pb(d, *s) for s in seq]
    check("G29 [ui] 없는 프로필: 기본값 경고, 기존 명령(status·token-audit·ui-map check·token-check·guard) 결과가 ui-guard 전후 동일",
          code == 0 and "ui_profile_default" in codes(out, "warnings") and pre == post, [s for s, a, b in zip(seq, pre, post) if a != b])
    G(d, "reset", "-q", "--hard", "HEAD~1")

    # G21·G22 승인 상태
    p = d / "docs/planning/02-prd.md"
    p.write_text(p.read_text() + "\n추가 요구\n")
    code, out = ug(d)
    check("G21 승인된 기획 문서 변경: 기존 require_planning 차단(planning_not_approved)", code == 2 and out["error"] == "planning_not_approved", out.get("error"))
    reset(d)
    p = d / "docs/design/02-screens.md"
    p.write_text(p.read_text() + "\n임의 수정\n")
    code, out = ug(d)
    check("G22a 승인된 UX Spec을 승인 없이 수정: 디자인 L1 → design_not_current(검사 결과는 참고로 포함)", code == 2 and out["error"] == "design_not_current"
          and out["design"]["level"] == "L1" and "protected_path_changed" in codes(out) and "checks" in out, out.get("design"))
    reset(d)
    (d / ".ai-workflow/design.json").unlink()
    code, out = ug(d)
    check("G22b design.json 없음(L0): design_not_current", code == 2 and out["error"] == "design_not_current" and out["design"]["level"] == "L0", out.get("design"))
    reset(d)

    # G25·G26 스냅샷(모듈 직접 호출, 판정과 재확인 사이에 파일 변경)
    w(d, "web/src/features/seats/Live.view", "export const Live = 1\n")
    sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    import pb_core  # noqa: E402
    import pb_ui  # noqa: E402
    import pb_uiguard  # noqa: E402
    prof_, _ = pb_core.load_profile(d)
    uprof, _ = pb_ui.ui_profile(prof_)
    umap = pb_ui.load_map(d)
    gate = pb_core.require_planning(d)
    live = d / "web/src/features/seats/Live.view"

    def once(attempt):
        if attempt == 1:
            live.write_text("export const Live = 2\n")
    out, code = pb_uiguard.run_guard(d, "changed", "HEAD", None, False, prof_, uprof, umap, gate, _between=once)
    check("G25 검사 중 파일이 한 번 바뀜: 다시 읽어 일관된 결과(attempts 2)", code == 0 and out["snapshot"]["attempts"] == 2, out["snapshot"])
    n = {"i": 0}

    def always(attempt):
        n["i"] += 1
        live.write_text(f"export const Live = {10 + n['i']}\n")
    try:
        pb_uiguard.run_guard(d, "changed", "HEAD", None, False, prof_, uprof, umap, gate, _between=always)
        check("G26 계속 바뀜: snapshot_unstable", False, "차단되지 않음")
    except pb_core.Blocked as e:
        check("G26 검사 중 파일이 계속 바뀜: snapshot_unstable(바뀐 경로 목록)", e.payload["error"] == "snapshot_unstable"
              and "web/src/features/seats/Live.view" in e.payload["paths"], e.payload)
    reset(d)


def scenario_edges(root: Path) -> None:
    e = root / "empty"
    e.mkdir()
    G(e, "init", "-q")
    code, out = ug(e)
    check("G6 커밋 없는 저장소: 기존 preflight no_commits 차단", code == 2 and out["error"] == "no_commits", out)
    n = root / "nogit"
    n.mkdir()
    code, out = ug(n)
    check("G7a Git 저장소 아님: not_git_repo(빈 목록으로 통과하지 않음)", code == 2 and out["error"] == "not_git_repo", out)


def scenario_theme(root: Path) -> None:
    """v2 테마 계약: 테마 파일이 정본. 승인 뒤 테마를 바꾸면 디자인 시스템 변경(T4)."""
    d = UT.make_ui_product(root, "guard-theme")
    w(d, UT.THEME, json.dumps({"schema": "design-theme/v1", "name": "lib-light", "version": "1.0.0",
                               "primitives": {"blue-700": "#1D5BD0", "white": "#FFFFFF"},
                               "tokens": {"color.primary": "{blue-700}", "color.bg": "{white}"},
                               "css": {"file": "design-preview/src/tokens.css", "var_pattern": "--{dashed}"}}, indent=2))
    G(d, "add", "-A"); G(d, "commit", "-qm", "theme (user)")
    code, out = pd(d, "migrate", "--to", "v2", "--theme-file", UT.THEME, "--confirm"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "v2 (user)")
    code, out = pd(d, "begin", "--stage", "design_direction"); assert code == 0, out
    DDT.write_07(d, 1, vd1_rel="SCR-001, CMP-002, UXD-001")
    for args in (("done", "--path", DDT.DD), ("submit", "--stage", "design_direction"), ("approve", "--stage", "design_direction", "--revision", "1")):
        code, out = pd(d, *args); assert code == 0, (args, out)
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(p) { return p }\n")
    w(d, "web/src/styles/tokens.css", TOKENS_CSS.replace("#0E6B4F", "#1D5BD0"))
    G(d, "add", "-A"); G(d, "commit", "-qm", "design direction + code (user)")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Button", "--note", "확인")
    pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "tokens.css 기준")
    G(d, "add", "-A"); G(d, "commit", "-qm", "map")
    code, out = ug(d)
    check("G12a 테마 정본 기준: 토큰 CSS가 테마 적용값과 같으면 통과", code == 0 and out["checks"]["tokens"]["source"] == f"theme:{UT.THEME}", out.get("errors"))
    t = d / UT.THEME
    t.write_text(t.read_text().replace("#1D5BD0", "#2255EE"))
    code, out = ug(d)
    # /product-design v2 규칙: 테마 값 변경은 프리뷰 재검증 대상이고 UX Spec·Design Direction 승인은 유지(디자인 L2 그대로).
    check("G12b 테마(정본) 변경: 디자인 L2 유지되어도 ui-guard가 theme_changed 오류(T4 힌트)", code == 2 and out["error"] == "guard_failed"
          and out["design"]["level"] == "L2" and "theme_changed" in codes(out) and any(f["kind"] == "theme" for f in out["files"])
          and any(h["code"] == "theme_changed" and h["type"] == "T4" for h in out["route_hint"]), out.get("errors"))


def static_checks() -> None:
    src = (T.ENGINE / "skills/product-build/scripts/pb_uiguard.py").read_text()
    writers = ("write_owned", "save_state", "save_map", "add_history", "write_json", "write_text", "write_bytes", "os.replace", "open(")
    check("S1 ui-guard 모듈에 쓰기 함수 없음(읽기 전용)", not [x for x in writers if x in src], [x for x in writers if x in src])
    code_only = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
    stacks = [x for x in ("react", "next.js", "vite", "tailwind", "playwright", "storybook", "angular", "mui") if re.search(rf"\b{re.escape(x)}\b", code_only, re.I)]
    check("S2 ui-guard 모듈에 프레임워크 이름 없음", not stacks, stacks)
    skill = (T.ENGINE / "skills/product-build/SKILL.md").read_text()
    check("S3 SKILL.md에 변경 유형별 경로(T0~T4)와 ui-guard", all(f"T{i}" in skill for i in range(5)) and "ui-guard" in skill)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-uiguard-test-"))
    try:
        static_checks()
        scenario_edges(root)
        scenario_main(root)
        scenario_theme(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
