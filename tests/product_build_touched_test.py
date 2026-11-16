#!/usr/bin/env python3
"""/product-build M3 P1: 화면을 소유하지 않는(touches) UI 배치의 Brief·UI Plan·증거·검토 회귀 테스트.

독립 픽스처(도서관 좌석 예약)만 씁니다. 실제 브라우저·Node 없이 검사합니다(테스트 실행기·브라우저 대역은 product_build_uiev_test).
설계: docs/roadmap/m3-p1-touched-screens-design.md
실행: python3 tests/product_build_touched_test.py
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402
import product_build_ui_test as UT  # noqa: E402
import product_build_uiev_test as UE  # noqa: E402
import product_design_dd_test as DDT  # noqa: E402

sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
import pb_ui as U  # noqa: E402
import pb_uiev as UV  # noqa: E402
import pb_uireview as UR  # noqa: E402

results = T.results
check, pb, pd, G = T.check, T.pb, T.pd, T.G
w = UT.w


def codes(items) -> list[str]:
    return [x.split("]")[0].lstrip("[") for x in items]


# ---------------------------------------------------------------- 계획: B4 = touches만 있는 UI 정비 배치, B3 = 소유 + touches
def touch_plan() -> dict:
    p = UT.plan_for(["CMP-002"], ["CMP-001", "CMP-002"])
    bs = {b["id"]: b for b in p["batches"]}
    bs["B1"]["acs"] = [a for a in bs["B1"]["acs"] if a != "AC-002"]
    bs["B1"]["test_plan"] = [x for x in bs["B1"]["test_plan"] if x["ac"] != "AC-002"]
    bs["B3"]["touches"] = ["SCR-001"]
    p["batches"].append({
        "id": "B4", "title": "공통 버튼 정비", "kind": "ui", "screens": [], "touches": ["SCR-001", "SCR-002", "SCR-003"], "acs": ["AC-002"],
        "components": {"reuse": ["CMP-001"], "new": []}, "depends_on": ["B0"],
        "paths": {"allow": ["web/src/features/common/"], "shared": []},
        "tasks": [{"id": "B4-T1", "layer": "fe", "title": "공통 버튼 높이 정비", "refs": ["CMP-001", "AC-002"]}],
        "test_plan": [{"ac": "AC-002", "kind": "unit"}]})
    return p


def good_touched_plan(digest: str) -> dict:
    """CLI 흐름용(B4): SCR-001 대표(AC-002 → ST3), SCR-002 위임, SCR-003 대표(AC 없음)."""
    return {"format": "pb-ui-plan/v1", "batch": "B4", "brief_digest": digest, "screens": {},
            "components": {"CMP-001": {"action": "reuse", "part": "Button"}}, "notes": [],
            "touched": {
                "SCR-001": {"changes": "공통 버튼 높이 44→48, 대기 안내 버튼", "via": ["CMP-001"],
                            "states": {"SCR-001-ST1": {"how": "route", "ref": "/seats"}, "SCR-001-ST3": {"how": "test", "ref": "빈 좌석 0 Mock"}},
                            "acs": {"AC-002": {"states": ["SCR-001-ST3"]}}},
                "SCR-002": {"changes": "공통 버튼 높이", "via": ["CMP-001"], "covered_by": "SCR-001"},
                "SCR-003": {"changes": "공통 버튼 높이(내 예약 버튼)", "via": ["CMP-001"],
                            "states": {"SCR-003-ST1": {"how": "route", "ref": "/me/reservations"}}}}}


def unit_good_plan() -> dict:
    """단위 검사용(fake_brief): SCR-001 대표, SCR-002 위임, SCR-003 대표 + AC-005 연결."""
    return {"touched": {
        "SCR-001": {"changes": "공통 버튼 높이", "via": ["CMP-001"], "states": {"SCR-001-ST1": {"how": "route", "ref": "/seats"}}},
        "SCR-002": {"changes": "공통 버튼 높이", "via": ["CMP-001"], "covered_by": "SCR-001"},
        "SCR-003": {"changes": "공통 버튼 높이", "via": ["CMP-001"], "states": {"SCR-003-ST1": {"how": "route", "ref": "/me"}},
                    "acs": {"AC-005": {"states": ["SCR-003-ST1"]}}}}}


# ---------------------------------------------------------------- 단위: validate_touched·touched_targets(규칙)
def fake_brief(owned: dict | None = None) -> dict:
    def st(s):
        return [{"id": f"{s}-ST{i}", "label": f"상태{i}", "behavior": "", "defined": True} for i in (1, 2)]
    return {"kind": "ui", "screens": owned or {}, "acs": ["AC-005"],
            "components": {"CMP-001": {"role": "reuse_mapped"}, "CMP-002": {"role": "reuse_mapped"}},
            "touched": {"screens": {
                "SCR-001": {"states": st("SCR-001"), "acs": [], "affected_via": ["CMP-001"]},
                "SCR-002": {"states": st("SCR-002"), "acs": [], "affected_via": ["CMP-001"]},
                "SCR-003": {"states": st("SCR-003"), "acs": [{"id": "AC-005", "states": ["SCR-003-ST1"]}], "affected_via": ["CMP-001"]}}}}


def vt(plan: dict, brief: dict | None = None, ledger=None) -> tuple[list[str], list[str]]:
    r = U.validate_touched(plan, brief or fake_brief(), ledger or {})
    return [c for c, _ in r["errors"]], [c for c, _ in r["warnings"]]


def unit_checks() -> None:
    good = unit_good_plan()
    e, wr = vt(good)
    r = U.validate_touched(good, fake_brief(), {})
    check("U1 대표(SCR-001)·위임(SCR-002 → SCR-001, 같은 via)·AC 연결 대표(SCR-003): 통과",
          not e and r["counts"] == {"screens": 3, "representative": 2, "covered": 1, "exempt": 0}, (e, r["counts"]))
    e, _ = vt({"screens": {}})
    check("U2 touches 계획 누락(touched 없음) → 화면마다 touched_missing", e.count("touched_missing") == 3, e)
    p = copy.deepcopy(good)
    p["touched"]["SCR-001"]["changes"] = ""
    p["touched"]["SCR-001"]["via"] = ["CMP-009", "layout"]
    e, _ = vt(p)
    check("U3 changes 없음·배치 밖 via → touched_changes·touched_via", {"touched_changes", "touched_via"} <= set(e), e)
    p = copy.deepcopy(good)
    p["touched"]["SCR-002"] = {"changes": "x", "via": ["CMP-001"]}
    e, _ = vt(p)
    check("U4 대표 상태·위임·예외가 모두 없음 → touched_states", "touched_states" in e, e)
    p = copy.deepcopy(good)
    p["touched"]["SCR-002"]["covered_by"] = "SCR-009"
    e, _ = vt(p)
    p2 = copy.deepcopy(good)
    p2["touched"]["SCR-002"]["via"] = ["layout"]
    e2, _ = vt(p2)
    check("U5 위임 대상이 대표 화면이 아님 / 겹치는 via 없음 → touched_covered_by", "touched_covered_by" in e and "touched_covered_by" in e2, (e, e2))
    p = copy.deepcopy(good)
    p["touched"]["SCR-003"] = {"changes": "x", "via": ["CMP-001"], "covered_by": "SCR-001", "acs": {"AC-005": {"states": ["SCR-003-ST1"]}}}
    e, _ = vt(p)
    check("U6 이 배치 AC가 가리키는 화면은 위임 불가(touched_must_represent)", "touched_must_represent" in e, e)
    p = copy.deepcopy(good)
    p["touched"]["SCR-002"] = {"changes": "화면 고유 정렬 변경", "via": ["CMP-001", "screen"], "covered_by": "SCR-001"}
    e, _ = vt(p)
    check("U7 via에 screen(그 화면 고유 변경)이면 위임 불가", "touched_must_represent" in e, e)
    p = copy.deepcopy(good)
    del p["touched"]["SCR-003"]["acs"]
    e, _ = vt(p)
    p2 = copy.deepcopy(good)
    p2["touched"]["SCR-003"]["acs"] = {"AC-005": {"states": ["SCR-003-ST2"]}}
    e2, _ = vt(p2)
    check("U8 touches 화면 AC 미연결 → touched_ac_unlinked, 대표 상태 밖 상태 연결 → touched_ac_state",
          "touched_ac_unlinked" in e and "touched_ac_state" in e2, (e, e2))
    p = copy.deepcopy(good)
    p["touched"]["SCR-001"]["states"] = {"SCR-001-ST9": {"how": "route", "ref": "/x"}, "SCR-001-ST2": {"how": "?", "ref": ""}}
    p["touched"]["SCR-004"] = {"changes": "x", "via": ["CMP-001"]}
    e, _ = vt(p)
    check("U9 정의되지 않은 상태·how 없음·touches 아닌 화면 → touched_state_unknown·touched_state_how·touched_unknown",
          {"touched_state_unknown", "touched_state_how", "touched_unknown"} <= set(e), e)
    led = {"POL-001": {"type": "policy", "status": "decided"}, "POL-002": {"type": "policy", "status": "open"}}
    p = copy.deepcopy(good)
    p["touched"]["SCR-002"] = {"changes": "x", "via": ["CMP-001"], "exempt": "POL-001"}
    e, wr = vt(p, ledger=led)
    p2 = copy.deepcopy(good)
    p2["touched"]["SCR-002"] = {"changes": "x", "via": ["CMP-001"], "exempt": "POL-002"}
    e2, _ = vt(p2, ledger=led)
    p3 = copy.deepcopy(good)
    p3["touched"]["SCR-003"]["exempt"] = "POL-001"
    e3, _ = vt(p3, ledger=led)
    check("U10 공식 예외: 결정된 원장 항목만 인정(경고 touched_exempted), 미결정은 오류, AC가 가리키는 화면은 예외 불가",
          not e and "touched_exempted" in wr and "touched_exempt_invalid" in e2 and "touched_must_represent" in e3, (e, wr, e2, e3))
    allx = {"touched": {s: {"changes": "x", "via": ["CMP-001"], "exempt": "POL-001"} for s in ("SCR-001", "SCR-002")}}
    bx = fake_brief()
    del bx["touched"]["screens"]["SCR-003"]
    e, wr = vt(allx, bx, led)
    check("U10b 소유 화면 없이 touches가 모두 예외면 경고 no_representative(증거 없는 배치임을 알림)", not e and "no_representative" in wr, (e, wr))
    owned = {"SCR-004": {"components": ["CMP-002", "CMP-003"], "states": []}}
    b = fake_brief(owned)
    b["touched"]["screens"] = {"SCR-001": {"states": fake_brief()["touched"]["screens"]["SCR-001"]["states"], "acs": [], "affected_via": ["CMP-002"]}}
    p = {"touched": {"SCR-001": {"changes": "지도 범례", "via": ["CMP-002"], "covered_by": "SCR-004"}}}
    e, _ = vt(p, b)
    p2 = {"touched": {"SCR-001": {"changes": "버튼", "via": ["CMP-001"], "covered_by": "SCR-004"}}}
    e2, _ = vt(p2, b)
    check("U11 소유+touches 혼합: 소유 화면에 위임(공유 CMP)은 통과, 공유 경로 없으면 오류", not e and "touched_covered_by" in e2, (e, e2))
    tt = UV.touched_targets(fake_brief(), good)
    check("U12 증거 대상: 대표 화면의 계획 상태만(위임 화면은 상태 없음)",
          sorted(tt["states"]) == ["SCR-001-ST1", "SCR-003-ST1"] and tt["screens"]["SCR-002"]["mode"] == "covered", tt)
    tt0 = UV.touched_targets(fake_brief(), {"screens": {}})
    check("U13 UI Plan에 touched가 없으면 모두 unplanned(대상 상태 없음)", all(x["mode"] == "unplanned" for x in tt0["screens"].values())
          and not tt0["states"], tt0)
    run = {"run_id": "r", "at": "t", "valid": True, "steps": [{"name": "unit", "status": "passed", "cases": [
        {"id": "c1", "status": "passed", "states": ["SCR-001-ST1"]}]}]}
    em = [{"id": "EM-001", "result": "passed", "method": "visual", "at": "t", "targets": {"states": ["SCR-003-ST1"], "acs": []}}]
    s = UV.evaluate_states(fake_brief(), run, set(), em, tt)
    s0 = UV.evaluate_states(fake_brief(), run, set(), [], tt)
    check("U14 touches 대표 상태: E2(태그된 통과) 또는 EM이면 verified, 없으면 untested(scope touched)",
          s["SCR-001-ST1"]["status"] == "verified" and s["SCR-001-ST1"]["level"] == "E2" and s["SCR-003-ST1"]["status"] == "verified"
          and s["SCR-003-ST1"]["level"] == "EM" and s0["SCR-003-ST1"]["status"] == "untested" and s["SCR-003-ST1"]["scope"] == "touched", s)
    links = UV.ac_links(fake_brief(), good, {"AC-005": {"status": "verified"}}, s0)
    check("U15 AC 연결에 touches 화면 상태 포함(AC verified인데 상태 증거 없음 → mismatch)",
          links["AC-005"]["states"] == {"SCR-003-ST1": "untested"} and links["AC-005"]["mismatch"], links)
    old = {"screens": {"SCR-004": "a"}, "tokens": "t", "ui_plan_components": "c"}
    new = {"screens": {"SCR-004": "a"}, "tokens": "t", "ui_plan_components": "c", "touched": {"SCR-001": "z"}}
    check("U16 이전 검증 기준(touched 키 없음)은 touches 변화를 비교하지 않음(기존 verified 보존)",
          UV.describe_changes(UV.basis_changes(old, new)) is None and UV.basis_touched(old) is None
          and UV.describe_changes(UV.basis_changes({**old, "touched": {"SCR-001": "y"}}, new)) is not None)
    ui = {"states": {"SCR-001-ST1": {"screen": "SCR-001", "required": False, "status": "untested"}}, "ui_plan_validated": True}
    rv = UR.build_review("B9", {"status": "verified", "verification": {"ui": ui}}, {"kind": "ui", "touches": ["SCR-001"]}, None, None, [], None)
    check("U17 검토: 화면 증거 0건이면 evidence_empty 경고, touches 판정 이전 검증이면 touched_not_evaluated 경고(차단 아님)",
          rv["ready"] and "evidence_empty" in codes(rv["warnings"]) and "touched_not_evaluated" in codes(rv["warnings"]), rv["warnings"])


# ---------------------------------------------------------------- CLI 흐름: Brief·Plan·시작 게이트·verify·EM·검토·호환
def setup(root: Path) -> Path:
    d = UT.make_ui_product(root, "lib-touched")
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(props) { return render('button', props) }\n")
    w(d, "web/src/styles/tokens.css", ":root {\n  --color-bg: #FFFFFF;\n  --color-text: #1A1A1A;\n  --color-primary: #0E6B4F;\n"
      "  --space-unit: 4px;\n  --radius-md: 8px;\n}\n")
    w(d, "api/contract.txt", "GET /api/seats\nPOST /api/reservations\n")
    w(d, "tools/run_ui_tests.py", UE.RUNNER)
    w(d, "web/src/components/Button.test.view", "case passed Button이 그려진다\n")
    w(d, "tools/fake_browser.py", UE.FAKE_BROWSER)
    UE.scenario(d, "ok", [UE.res("SCR-001-ST1")])
    (d / ".gitignore").write_text("node_modules/\ntools/browser-scenario.json\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UE.PROFILE)
    UT.approve_plan(d, touch_plan())
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--source", "existing", "--path", "web/src/components/Button.view",
                   "--export", "Button", "--note", "기존 Button을 재사용합니다")
    assert code == 0, out
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "이 파일을 토큰 출력으로 씁니다")
    assert code == 0, out
    return d


def flow(root: Path) -> None:
    d = setup(root)
    snap = T.protected_snapshot(d)
    code, out = pb(d, "plan-validate")
    check("C0 touches만 있는 UI 배치(B4)·소유+touches 배치(B3)가 계획 검증 통과(소유권 규칙 유지)", code == 0, out.get("errors"))

    # 소유 화면만 있는 기존 배치: 이전과 같음
    code, out = pb(d, "ui-brief", "--batch", "B1")
    b1 = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())
    check("C1 소유 화면만 있는 배치(B1): Brief·skeleton에 touched 없음(이전 형식)", code == 0 and "touched" not in b1 and "touched" not in out.get("skeleton", {}), out)
    p1 = UT.good_ui_plan(out["digest"])
    del p1["screens"]["SCR-001"]["acs"]["AC-002"]  # 이 픽스처에서 AC-002는 B4 소유
    UT.write_ui_plan(d, p1)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("C2 기존 형식 UI Plan(소유 화면) 그대로 통과, touches 관련 경고 없음", code == 0 and not any("touched" in x for x in out["warnings"]), out)

    # B0 완료(선행)
    lock = UE.start(d, "B0")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    UE.finish(d, "B0", lock)
    pb(d, "ui-map", "register", "--cmp", "CMP-002", "--source", "built", "--batch", "B0", "--path", "web/src/components/SeatMap.view", "--export", "SeatMap")
    code, out = UE.verify(d, "B0")
    assert code == 0, out

    # touches-only 배치 Brief
    code, out = pb(d, "ui-brief", "--batch", "B4")
    brief = json.loads((d / ".ai-workflow/build/ui/B4/brief.json").read_text())
    tb = brief.get("touched", {}).get("screens", {})
    check("C3 touches-only Brief: 소유 화면 없음, touched에 화면 3개·소유 배치·영향/참조 CMP 구분·이 배치 AC",
          code == 0 and brief["screens"] == {} and sorted(tb) == ["SCR-001", "SCR-002", "SCR-003"] and tb["SCR-003"]["owner"] == "B2"
          and tb["SCR-001"]["affected_via"] == ["CMP-001"] and tb["SCR-001"]["referenced"] == ["CMP-002"]
          and [a["id"] for a in tb["SCR-001"]["acs"]] == ["AC-002"] and tb["SCR-001"]["acs"][0]["states"] == ["SCR-001-ST3"] and not tb["SCR-003"]["acs"], tb)
    check("C4 touched는 Brief digest 밖(자체 digest), skeleton에 touched 항목(via·AC)",
          brief["digest"] == U.brief_digest(brief) and U.brief_intact(brief)
          and out["skeleton"]["touched"]["SCR-001"] == {"changes": "", "via": ["CMP-001"], "states": {}, "acs": {"AC-002": {"states": ["SCR-001-ST3"]}}}
          and out["summary"]["touched"]["SCR-001"]["acs"] == ["AC-002"], out.get("skeleton", {}).get("touched"))
    digest = out["digest"]

    # 계획 누락 → 차단, 올바른 계획 → 통과
    plan_rel = d / ".ai-workflow/build/ui/B4/plan.json"
    empty = {"format": "pb-ui-plan/v1", "batch": "B4", "brief_digest": digest, "screens": {}, "components": {"CMP-001": {"action": "reuse", "part": "Button"}}, "notes": []}
    plan_rel.write_text(json.dumps(empty, ensure_ascii=False))
    code, out = pb(d, "ui-plan-validate", "--batch", "B4")
    check("C5 빈 screens만 있는 touches-only UI Plan은 통과하지 않음(touched_missing ×3)",
          code == 2 and codes(out["errors"]).count("touched_missing") == 3, out.get("errors"))
    code, out = pb(d, "batch-start", "--batch", "B4", "--owner", "t")
    check("C6 계획 누락 상태로는 batch-start 거부(ui_plan_required)", code == 2 and out["error"] == "ui_plan_required", out)
    plan_rel.write_text(json.dumps(good_touched_plan(digest), ensure_ascii=False))
    code, out = pb(d, "ui-plan-validate", "--batch", "B4")
    val = json.loads((d / ".ai-workflow/build/ui/B4/validation.json").read_text())
    check("C7 대표·위임·AC 연결을 갖춘 touched 계획 통과, 검증 기록에 규칙 버전", code == 0 and val["rules"] == U.TOUCHED_RULES
          and out["counts"]["touched"] == {"screens": 3, "representative": 2, "covered": 1, "exempt": 0}, out)

    # 이전 엔진 검증 기록(규칙 버전 없음)으로는 시작 불가
    val_raw = (d / ".ai-workflow/build/ui/B4/validation.json").read_text()
    v0 = json.loads(val_raw); v0.pop("rules")
    (d / ".ai-workflow/build/ui/B4/validation.json").write_text(json.dumps(v0, ensure_ascii=False))
    code, out = pb(d, "batch-start", "--batch", "B4", "--owner", "t")
    check("C8 이전 규칙으로 검증된 touches 배치는 시작 전 재검증 필요(ui_plan_revalidate)", code == 2 and "ui_plan_revalidate" in str(out.get("problems")), out)
    (d / ".ai-workflow/build/ui/B4/validation.json").write_text(val_raw)

    # 혼합 배치(B3) Brief·계획
    code, out = pb(d, "ui-brief", "--batch", "B3")
    b3 = json.loads((d / ".ai-workflow/build/ui/B3/brief.json").read_text())
    check("C9 소유+touches 배치(B3): 소유 화면 SCR-004는 screens, SCR-001은 touched(영향 CMP-001·CMP-002)",
          list(b3["screens"]) == ["SCR-004"] and b3["touched"]["screens"]["SCR-001"]["affected_via"] == ["CMP-001", "CMP-002"], b3.get("touched"))

    # 구현·검증
    lock = UE.start(d, "B4")
    w(d, "web/src/features/common/ButtonSpacing.view", "import { Button } from '../../components/Button.view'\nexport const ButtonSpacing = Button\n")
    w(d, "web/src/features/common/common.test.view", "case passed [SCR-001-ST1] 버튼 높이 48\ncase passed [SCR-001-ST3] [AC-002] 대기 안내 버튼\n")
    UE.finish(d, "B4", lock)
    UE.scenario(d, "ok", [UE.res("SCR-001-ST1")])
    code, out = UE.verify(d, "B4")
    ui = out.get("ui") or {}
    stb = UE.st(d)["batches"]["B4"]["verification"]["ui"]
    check("C10 verify: 소유 화면이 없어도 touches 대표 상태를 판정(SCR-001-ST1 E2, SCR-003-ST1 untested), verify 자체는 통과",
          code == 0 and out["status"] == "verified" and stb["states"]["SCR-001-ST1"]["status"] == "verified"
          and stb["states"]["SCR-003-ST1"]["status"] == "untested" and stb["states"]["SCR-003-ST1"]["scope"] == "touched", UE.reasons(out))
    check("C11 대표 증거 누락은 이유와 함께 최종 UI 승인 차단(touched_evidence), 위임 화면은 상태 증거 요구 없음",
          any("touched_evidence" in x and "SCR-003-ST1" in x for x in stb["final_approval_blockers"])
          and stb["touched"]["screens"]["SCR-002"]["mode"] == "covered" and "states" not in stb["touched"]["screens"]["SCR-002"], stb.get("touched"))
    check("C12 브라우저 결과의 touches 화면은 '소유 화면 아님'으로 버리지 않음, AC 연결에 touches 상태 포함",
          not any("SCR-001-ST1@" in x and "화면이 아닙니다" in x for x in stb["browser"]["warnings"])
          and "SCR-001-ST3" in stb["ac_links"]["AC-002"]["states"], (stb["browser"]["warnings"], stb["ac_links"]))
    code, rv = pb(d, "ui-review", "--batch", "B4")
    check("C13 ui-review: 대표 증거 누락 → ready false(차단 이유 표시), 검토 묶음에 대표·위임 화면 모두 표시",
          not rv["ready"] and any("SCR-003-ST1" in b for b in rv["blockers"]) and rv["screens"]["SCR-002"]["touched"]["mode"] == "covered"
          and rv["screens"]["SCR-001"]["states"]["SCR-001-ST1"]["scope"] == "touched", rv)

    # 공통 부품 변경이라도 모든 화면 증거를 강제하지 않음: EM 1건(대표 SCR-003)으로 충족
    code, out = pb(d, "evidence-manual", "add", "--batch", "B4", "--state", "SCR-003-ST1", "--check", "내 예약 화면에서 버튼 높이 확인",
                   "--method", "visual", "--result", "passed", "--note", "내 예약 화면 버튼 높이가 48로 보입니다")
    check("C14 EM을 touches 화면 상태에도 기록 가능(검증 입력이 바뀌어 stale)", code == 0 and out["status"] == "stale", out)
    code, out = UE.verify(d, "B4")
    code2, rv = pb(d, "ui-review", "--batch", "B4")
    check("C15 대표 상태 증거 충족(E2 + EM) → 위임 화면(SCR-002) 증거 없이도 ready", code == 0 and rv["ready"], rv.get("blockers"))

    # 무효화: UI Plan touched 변경 → touches 입력 변경으로 재검증 필요
    tp = json.loads(plan_rel.read_text())
    tp_raw = plan_rel.read_text()
    tp["touched"]["SCR-002"]["changes"] = "공통 버튼 높이와 색"
    plan_rel.write_text(json.dumps(tp, ensure_ascii=False))
    code, out = pb(d, "ui-evidence", "--batch", "B4")
    check("C16 verify 이후 UI Plan touched가 바뀌면 증거 무효(touches 화면 입력 변경)", "touches 화면 입력" in str(out.get("freshness_problem"))
          and "SCR-002" in out["affected_now"]["screens"], out.get("freshness_problem"))
    plan_rel.write_text(tp_raw)

    # 이미 시작된 배치의 이전 UI Plan(touched 없음): 경고만(legacy)
    plan_rel.write_text(json.dumps(empty, ensure_ascii=False))
    code, out = pb(d, "ui-plan-validate", "--batch", "B4")
    check("C17 이미 시작된 배치의 touched 없는 UI Plan은 차단하지 않고 touched_plan_legacy 경고", code == 0
          and "touched_plan_legacy" in codes(out["warnings"]), out)
    plan_rel.write_text(tp_raw)
    pb(d, "ui-plan-validate", "--batch", "B4")

    # 이전 엔진으로 검증된 verified 배치 재현: verification.ui에 touched·basis.touched 없음
    sp = d / ".ai-workflow/build.json"
    raw_state = sp.read_text()
    s = json.loads(raw_state)
    v = s["batches"]["B4"]["verification"]["ui"]
    v.pop("touched", None); v["basis"].pop("touched", None)
    v["states"] = {k: r for k, r in v["states"].items() if r.get("scope") != "touched"}
    v["final_approval_blockers"] = []
    sp.write_text(json.dumps(s, ensure_ascii=False, indent=2))
    code, ev = pb(d, "ui-evidence", "--batch", "B4")
    code2, rv = pb(d, "ui-review", "--batch", "B4")
    check("C18 이전 검증 기록의 verified 배치: 상태 유지·무효화 없음, 검토는 차단 대신 touched_not_evaluated 경고",
          ev["status"] == "verified" and ev["freshness_problem"] is None and UE.st(d)["batches"]["B4"]["status"] == "verified"
          and "touched_not_evaluated" in codes(rv["warnings"]) and not any("touched" in b for b in rv["blockers"]), (ev.get("freshness_problem"), rv.get("blockers")))
    sp.write_text(raw_state)
    check("C19 승인 문서·state.yaml·design.json 불변", T.protected_snapshot(d) == snap)


# ---------------------------------------------------------------- VD: touches 화면·배치 부품에 연결된 VD(v2 Design Direction)
THEME = "design-profile/theme.json"


def vd_brief(root: Path) -> None:
    d = UT.make_ui_product(root, "lib-touched-vd")
    w(d, THEME, json.dumps({"schema": "design-theme/v1", "name": "lib", "version": "1.0.0", "primitives": {"g": "#0E6B4F", "white": "#FFFFFF"},
                            "tokens": {"color.primary": "{g}", "color.bg": "{white}"},
                            "css": {"file": "design-preview/src/tokens.css", "var_pattern": "--{dashed}"}}, indent=2))
    G(d, "add", "-A"); G(d, "commit", "-qm", "theme (user)")
    code, out = pd(d, "migrate", "--to", "v2", "--theme-file", THEME, "--confirm"); assert code == 0, out
    G(d, "add", "-A"); G(d, "commit", "-qm", "v2 (user)")
    code, out = pd(d, "begin", "--stage", "design_direction"); assert code == 0, out
    extra = ("### VD-003: 화면 공통 여백\n- **결정**: 좌우 16\n- **상태**: 승인\n- **근거**: 사용자 결정\n- **관련**: UXD-001\n- **토큰 밖 값**: 없음\n"
             "### VD-004: 버튼 높이 48\n- **결정**: 모든 주요 버튼 48\n- **상태**: 승인\n- **근거**: 현장 장갑 사용\n- **관련**: CMP-001\n- **토큰 밖 값**: 없음\n")
    DDT.write_07(d, 1, vd1_rel="SCR-001, CMP-002, UXD-001", extra_vd=extra)
    for args in (("done", "--path", DDT.DD), ("submit", "--stage", "design_direction"), ("approve", "--stage", "design_direction", "--revision", "1")):
        code, out = pd(d, *args); assert code == 0, (args, out)
    G(d, "add", "-A"); G(d, "commit", "-qm", "design direction (user)")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    G(d, "add", "-A"); G(d, "commit", "-qm", "profile")
    UT.approve_plan(d, touch_plan())
    code, out = pb(d, "ui-brief", "--batch", "B4")
    br = json.loads((d / ".ai-workflow/build/ui/B4/brief.json").read_text())
    t1 = {x["id"]: x["via"] for x in br["touched"]["screens"]["SCR-001"]["vd"]}
    t3 = {x["id"]: x["via"] for x in br["touched"]["screens"]["SCR-003"]["vd"]}
    check("V1 touches 화면 VD: 화면 직접 관련(via screen)과 부품 경유(via CMP) 구분",
          code == 0 and t1 == {"VD-001": "screen", "VD-004": "CMP-001"} and t3 == {"VD-004": "CMP-001"}, (t1, t3))
    check("V2 배치 부품에 연결된 VD(component_vd)와 전역 VD(관련 SCR·CMP 없음) 구분, 제외 VD(VD-002) 없음",
          [x["id"] for x in br["touched"]["component_vd"]] == ["VD-004"] and [x["id"] for x in br["visual_decisions_global"]] == ["VD-003"]
          and "VD-002" not in json.dumps(br["touched"]), (br["touched"]["component_vd"], br["visual_decisions_global"]))


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-touched-"))
    try:
        unit_checks()
        flow(root)
        vd_brief(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
