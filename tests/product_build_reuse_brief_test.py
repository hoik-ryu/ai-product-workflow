#!/usr/bin/env python3
"""/product-build 구현 전 품질 개선 테스트(자체 완결형): 기존 컴포넌트 재사용 탐색(P1)과 UI Brief 레이아웃 정보 전달(P4).

사례 프로젝트와 무관한 독립 픽스처(product_build_ui_test의 도서관 좌석 예약 기획·디자인 L2)를 씁니다.
- P1: scope --draft가 대응표의 CMP를 재사용으로 제안, 계획의 신규 CMP에 대응표 밖 기존 후보가 있으면 unmapped_candidate_exists,
      결정된 원장 항목(components.new_reasons)으로만 신규 유지, 후보가 없으면 정상 신규, 이름 일치를 자동 등록하지 않음
- P4: 02 '레이아웃' 원문, 04 '공통 패턴' 원문, 간격·글자·브레이크포인트 토큰 전달, 기존 Brief digest·무결성 호환
실행: python3 tests/product_build_reuse_brief_test.py
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
import product_build_ui_test as UT  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G
w = UT.w

LAYOUT_SCR1 = "```\n┌──────────────┐\n│ 좌석 지도      │\n│ [예약하기]     │\n└──────────────┘\n```\n- 모바일: 한 열, 지도 아래에 주요 버튼"
PATTERNS = "- 빈 상태: 안내 문구와 주요 행동 1개\n- 오류: 화면 상단 배너, 다시 시도 버튼\n\n### 확인 창\n- 되돌릴 수 없는 행동만 확인 창"
EXTRA_TOKENS = ("| font.size.body | 16px | 본문 |\n| line.height.body | 1.5 | 본문 줄 높이 |\n"
                "| breakpoint.mobile | 480px | 회원 화면 최대 폭 |\n| gap.section | 24px | 구역 간격 |\n")
_orig_enrich = UT.enrich_design


def enrich_with_layout(d: Path) -> None:
    """기존 픽스처 보강 + SCR-001에만 레이아웃 절(코드 펜스·주석 포함), 04에 공통 패턴 절과 글자·브레이크포인트 토큰(승인 전)."""
    _orig_enrich(d)
    p = d / "docs/design/02-screens.md"
    t = p.read_text()
    t = re.sub(r"(^## SCR-001:.*?)(^### 정보와 우선순위)",
               lambda m: m.group(1) + "### 레이아웃(저충실도)\n" + LAYOUT_SCR1.replace("- 모바일", "<!-- 작성 메모 -->\n- 모바일") + "\n\n" + m.group(2),
               t, count=1, flags=re.M | re.S)
    p.write_text(t)
    u = d / "docs/design/04-ui-system.md"
    u.write_text(u.read_text().replace("| radius.md | 8px | 모서리 |\n", "| radius.md | 8px | 모서리 |\n" + EXTRA_TOKENS)
                 + "\n## 3. 공통 패턴\n<!-- 형식 안내 -->\n" + PATTERNS + "\n")


def errs(out: dict, code: str) -> list[str]:
    return [e for e in out.get("errors") or [] if e.startswith(f"[{code}]")]


def item_status(d: Path, iid: str) -> str:
    return next(i["status"] for i in json.loads((d / ".ai-workflow/build/ledger.json").read_text())["items"] if i["id"] == iid)


# ---------------------------------------------------------------- P1
def scenario_reuse(root: Path) -> None:
    d = UT.make_ui_product(root, "reuse")
    w(d, "web/src/components/Button.view", "export function Button(props) { return render('button', props) }\n")  # 이름 일치(CMP-001 Button)
    w(d, "web/src/components/SeatMap.view", "// CMP-002 좌석 지도(사내 기존 부품)\nexport const SeatMap = (p) => p\n")  # 표지
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    G(d, "add", "-A"); G(d, "commit", "-qm", "profile")
    snap = T.protected_snapshot(d)

    code, out = pb(d, "scope", "--draft")
    news = {c for b in out["draft"]["batches"] for c in b["components"]["new"]}
    cc = {x["cmp"]: [y["path"] for y in x["candidates"]] for x in out.get("component_candidates", {}).get("items", [])}
    check("R1 대응표 없음: 초안은 기존과 같이 CMP를 신규로 제안하고, 후보 파일을 안내(후보일 뿐)",
          code == 0 and {"CMP-001", "CMP-002"} <= news and cc == {"CMP-001": ["web/src/components/Button.view"], "CMP-002": ["web/src/components/SeatMap.view"]}
          and "후보일 뿐" in out["component_candidates"]["note"] and "reused_from_ui_map" not in out, out.get("component_candidates"))
    check("R2 초안·후보 탐색은 대응표를 만들거나 등록하지 않음(이름 일치를 같은 부품으로 확정하지 않음)",
          not (d / "docs/build/ui-map.json").exists(), "ui-map.json 생성됨")

    plan = UT.plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"])  # B0가 CMP-001·002 신규, B2가 CMP-003 신규
    T.save_plan(d, plan)
    code, out = pb(d, "plan-validate")
    e = errs(out, "unmapped_candidate_exists")
    check("R3 신규 CMP에 대응표 밖 기존 후보(이름 일치·표지): unmapped_candidate_exists로 차단, 근거 종류와 파일 표시",
          code == 2 and len(e) == 2 and any("CMP-001" in x and "Button.view(이름 일치)" in x for x in e)
          and any("CMP-002" in x and "SeatMap.view(CMP 표지)" in x for x in e), out.get("errors"))
    check("R4 차단 메시지가 기존 ui-map register 경로와 원장 결정 경로를 안내", e and all("ui-map register --cmp" in x and "components.reuse" in x
                                                                           and "decide" in x and "new_reasons" in x for x in e), e)
    check("R5 후보가 없는 신규 CMP(CMP-003)는 차단하지 않음", not [x for x in e if "CMP-003" in x], e)
    code, out = pb(d, "submit", "plan")
    check("R6 계획 제출(승인 경로)도 같은 검사로 차단", code == 2 and errs(out, "unmapped_candidate_exists"), out)

    # 다른 부품이라는 근거: 결정되지 않은 원장 항목은 인정하지 않음
    code, out = pb(d, "ledger", "add", "--type", "policy", "--title", "CMP-001 Button을 기존 Button.view와 별도로 만듦",
                   "--desc", "기존 Button.view는 관리 화면 전용 동작이 있어 회원 화면 버튼과 다름", "--rationale", "부품 재사용 판단")
    pol = out["item"]["id"]
    plan["batches"][0]["components"]["new_reasons"] = {"CMP-001": pol}
    T.save_plan(d, plan)
    code, out = pb(d, "plan-validate")
    e = errs(out, "unmapped_candidate_exists")
    check("R7 new_reasons의 원장 항목이 결정 전(open)이면 여전히 차단하고 이유를 표시", code == 2 and any("CMP-001" in x and "결정된" in x for x in e), e)
    plan["batches"][0]["components"]["new_reasons"] = {"CMP-001": "POL-999"}
    T.save_plan(d, plan)
    code, out = pb(d, "plan-validate")
    check("R8 없는 원장 ID는 근거로 인정하지 않음", code == 2 and any("CMP-001" in x for x in errs(out, "unmapped_candidate_exists")), out.get("errors"))
    code, out = pb(d, "decide", "--id", pol, "--decision", "Button.view와 별도로 회원용 Button을 새로 만듦",
                   "--note", "관리 화면 버튼과 회원 버튼은 다른 부품으로 둡니다", "--confirm")
    plan["batches"][0]["components"]["new_reasons"] = {"CMP-001": pol}
    T.save_plan(d, plan)
    code, out = pb(d, "plan-validate")
    check("R9 사용자 결정(decided)된 원장 항목이면 CMP-001 신규 허용(경고로 기록), CMP-002는 여전히 차단",
          item_status(d, pol) == "decided" and not any("CMP-001" in x for x in errs(out, "unmapped_candidate_exists"))
          and any(x.startswith("[new_despite_candidate]") and "CMP-001" in x for x in out.get("warnings", []))
          and any("CMP-002" in x for x in errs(out, "unmapped_candidate_exists")), out)

    # 같은 부품이라고 사용자가 확인 → 기존 등록 경로 → 재사용
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-002", "--path", "web/src/components/SeatMap.view", "--export", "SeatMap",
                   "--note", "사용자 확인: SeatMap.view가 CMP-002 좌석 지도입니다")
    code, out = pb(d, "plan-validate")
    check("R10 등록 뒤 CMP-002를 신규로 두면 기존 cmp_already_mapped로 차단(이중 오류 없음)", code == 2 and errs(out, "cmp_already_mapped")
          and not any("CMP-002" in x for x in errs(out, "unmapped_candidate_exists")), out.get("errors"))
    plan["batches"][0]["components"]["new"] = ["CMP-001"]
    T.save_plan(d, plan)
    pb(d, "waiver", "add", "--reason", "배치 구현으로 시각 확인", "--all-ui", "--note", "프리뷰 없이 구현을 승인합니다", "--confirm")
    code, out = pb(d, "plan-validate")
    check("R11 CMP-002 재사용 + CMP-001 결정 근거 + CMP-003 후보 없음: 정상 신규 계획 통과", code == 0 and out["ok"], out.get("errors"))
    code, out = pb(d, "scope", "--draft")
    news = {c for b in out["draft"]["batches"] for c in b["components"]["new"]}
    reuse = {c for b in out["draft"]["batches"] for c in b["components"]["reuse"]}
    check("R12 대응표에 등록된 CMP-002는 초안에서 신규가 아니라 재사용으로 제안", code == 0 and "CMP-002" not in news and "CMP-002" in reuse
          and "CMP-002" in out.get("reused_from_ui_map", []) and "CMP-002" not in [x["cmp"] for x in out.get("component_candidates", {}).get("items", [])], out["draft"]["batches"])
    check("R13 승인 문서·state.yaml·design.json 불변", T.protected_snapshot(d) == snap)
    sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
    import pb_core  # noqa: E402
    import pb_ui  # noqa: E402
    prof_ = pb_core.load_profile(d)[0]
    p2 = UT.plan_for(["CMP-001"], ["CMP-001"])
    e_all, _ = pb_ui.candidate_conflicts(d, p2, prof_, pb_ui.ui_profile(prof_)[0], None, [])
    e_started, _ = pb_ui.candidate_conflicts(d, p2, prof_, pb_ui.ui_profile(prof_)[0], None, [], started={"B0"})
    check("R15 이미 시작·완료된 배치(B0)의 신규 CMP는 다시 검사하지 않음(그 배치가 만든 파일, 계획 재제출 호환)",
          any("B0" in x and "CMP-001" in x for x in e_all) and not e_started, (e_all, e_started))

    # 부품 경로가 없는 프로필(M2 형태): 후보 검사 없음(기존 동작)
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE.split("[ui]")[0].replace('components = ["web/src/components"]\n', ""))
    (d / "docs/build/ui-map.json").unlink()
    plan["batches"][0]["components"].pop("new_reasons")
    plan["batches"][0]["components"]["new"] = ["CMP-001", "CMP-002"]
    T.save_plan(d, plan)
    code, out = pb(d, "plan-validate")
    check("R14 부품 경로가 없는 프로젝트: 후보 검사를 하지 않아 기존과 같이 통과", code == 0 and not errs(out, "unmapped_candidate_exists"), out.get("errors"))


# ---------------------------------------------------------------- P4
def scenario_brief(root: Path) -> None:
    UT.enrich_design = enrich_with_layout
    try:
        d = UT.make_ui_product(root, "brief")
    finally:
        UT.enrich_design = _orig_enrich
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    w(d, "api/contract.txt", "GET /api/seats\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "profile")
    UT.approve_plan(d, UT.plan_for(["CMP-001", "CMP-002"], ["CMP-001", "CMP-002"]))
    snap = T.protected_snapshot(d)
    code, out = pb(d, "ui-brief", "--batch", "B1")
    brief = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())
    lay = brief.get("layout") or {}
    check("P1 02 '레이아웃' 원문을 화면별로 전달(코드 펜스 그림 포함, HTML 주석 제외)", code == 0 and lay.get("screens") == {"SCR-001": LAYOUT_SCR1}, lay.get("screens"))
    check("P2 레이아웃 절이 없는 화면은 missing으로 표시(임의 생성 없음)", lay.get("missing") == ["SCR-002"], lay.get("missing"))
    check("P3 04 '공통 패턴' 원문 전달(하위 제목 포함, 주석 제외)", lay.get("patterns") == {"source": "docs/design/04-ui-system.md", "text": PATTERNS}, lay.get("patterns"))
    toks = lay.get("tokens") or {}
    check("P4 승인 토큰 중 간격·글자·브레이크포인트만 승인값 그대로(색·모서리 제외)",
          toks == {"spacing": {"gap.section": "24px", "space.unit": "4px"}, "typography": {"font.size.body": "16px", "line.height.body": "1.5"},
                   "breakpoint": {"breakpoint.mobile": "480px"}}
          and all(brief["tokens"]["approved"][k] == v for g in toks.values() for k, v in g.items()), toks)
    src02 = re.sub(r"^[ \t]*<!--.*?-->[ \t]*\n", "", (d / "docs/design/02-screens.md").read_text(), flags=re.M | re.S)
    check("P5 전달 내용은 승인 문서의 원문 일부(엔진이 규칙을 만들지 않음)", all(t in src02 for t in lay.get("screens", {}).values())
          and PATTERNS in (d / "docs/design/04-ui-system.md").read_text() and "해석·보완하지 않습니다" in lay.get("note", ""), lay.get("note"))
    check("P6 ui-brief 요약에 레이아웃 전달 현황", out["summary"].get("layout") == {"screens": ["SCR-001"], "missing": ["SCR-002"], "patterns": True,
                                                                   "tokens": {"spacing": 2, "typography": 2, "breakpoint": 1}}, out["summary"].get("layout"))
    check("P7 Brief digest는 layout을 제외한 기존 계산과 같음(기존 Brief·UI Plan 검증 기록 유지)",
          brief["digest"] == T.hashlib.sha256(json.dumps({k: v for k, v in brief.items() if k not in ("digest", "layout")},
                                                         ensure_ascii=False, sort_keys=True).encode()).hexdigest(), brief["digest"])
    check("P8 기존 규칙(rules) 문구 유지", brief["rules"][1] == "대응표에 있는 컴포넌트는 반드시 재사용합니다. 같은 컴포넌트를 새로 만들지 않습니다.", brief["rules"])

    p = d / ".ai-workflow/build/ui/B1/brief.json"
    good = p.read_text()
    tampered = json.loads(good)
    tampered["layout"]["screens"]["SCR-001"] = "엔진 밖에서 덧붙인 규칙"
    p.write_text(json.dumps(tampered, ensure_ascii=False))
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("P9 저장된 Brief의 layout을 고치면 brief_modified(layout.digest)", code == 2 and out["error"] == "brief_modified", out)
    legacy = json.loads(good)
    legacy.pop("layout")
    p.write_text(json.dumps(legacy, ensure_ascii=False))
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("P10 layout이 없는 이전 Brief도 무결성 인정(다음 단계 no_ui_plan으로 진행)", code == 2 and out["error"] == "no_ui_plan", out)
    p.write_text(good)
    check("P11 승인 문서·state.yaml·design.json 불변", T.protected_snapshot(d) == snap)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-reuse-brief-test-"))
    try:
        scenario_reuse(root)
        scenario_brief(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
