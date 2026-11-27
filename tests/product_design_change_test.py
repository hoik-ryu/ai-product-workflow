#!/usr/bin/env python3
"""/product-design 변경 요청(CR)·승인 패치(Amendment) M1 테스트(자체 완결형).

범위(M1): A–E 분류(읽기 전용 change plan), Type B CR 실행(패치 체인·유효 승인 기준), 안전성(잠금·stale·체인 무결성·Worktree 충돌 감지).
Type C는 M1 CR로 실행하지 않고 /product-change 변경 패키지로 안내합니다(실행은 tests/product_change_test.py S2). Worktree 간 자동 병합(M3)은 구현 대상이 아니므로 차단·안내만 확인합니다.

- 승인 상태는 모두 실제 CLI로 만듭니다(tests/change_fixture.py). 모든 승인·확인 문장은 이 임시 프로젝트 안의 시뮬레이션입니다.
- design.json을 손으로 고치는 경우는 체인 조작·병합 충돌을 흉내 낼 때뿐입니다(그 자체가 시험 대상).
- 프리뷰 빌드(pnpm)가 안 되면 프리뷰가 필요한 항목은 SKIP으로 보고합니다(run_all이 INCOMPLETE로 표시).

실행: python3 tests/product_design_change_test.py
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _tmpdirs as TMP  # noqa: E402
import change_fixture as F  # noqa: E402
import product_design_test as T  # noqa: E402

ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
results: list[tuple[str, bool, str]] = []
DD = "docs/design/07-design-direction.md"
REVIEW = "docs/design/06-preview-review.md"
SCREENS = "docs/design/02-screens.md"
EVIDENCE: dict = {}


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:900]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:900]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


pd, state = F.pd, F.state


def req(root: Path, name: str, items: list) -> Path:
    p = root / f"{name}.json"  # 프로젝트 밖
    p.write_text(json.dumps({"schema": "design-change-request/v1", "items": items}, ensure_ascii=False))
    return p


def approvals(st: dict) -> dict:
    return {k: {x: copy.deepcopy(v.get(x)) for x in ("status", "revision", "approved", "submitted", "last_approved")} for k, v in st["stages"].items()}


def commit(d: Path, msg: str) -> None:
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", msg)


def mask_variant(edge_alpha: int):
    return F.png_rgba(48, 16, lambda x, y: F.banner_pixel(x, y)[:3] + ((edge_alpha,) if (x in (0, 47) or y in (0, 15)) else (255,)))


def successor(d: Path, root: Path, raw: bytes, name: str, refs: str = "SCR-001") -> str:
    up = root / f"up-{name}"
    up.mkdir()
    (up / "banner.png").write_bytes(raw)
    code, out = pd(d, "explore-asset", "add", "--file", up / "banner.png", "--kind", "image", "--role", "decorative",
                   "--source", "self_made", "--license", "own", "--refs", refs)
    assert code == 0, out
    aid = out["asset"]
    code, out = pd(d, "explore-asset", "confirm", "--id", aid, "--license", "own", "--note", f"{aid} 직접 만든 보정본(시뮬레이션)")
    assert code == 0, out
    return aid


def derived(d: Path, root: Path, raw: bytes, name: str, parent: str, refs: str = "SCR-001") -> tuple[str, dict]:
    """승인 자산의 파생본을 후속 자산으로 등록(--derived-from). 권리 상속 조건이면 사용자 확인 질문 없음."""
    up = root / f"up-{name}"
    up.mkdir()
    (up / "banner.png").write_bytes(raw)
    code, out = pd(d, "explore-asset", "add", "--file", up / "banner.png", "--kind", "image", "--role", "decorative",
                   "--source", "self_made", "--license", "own", "--refs", refs, "--derived-from", parent)
    assert code == 0, out
    return out["asset"], out


def swap_ref(d: Path, old: str, new: str) -> None:
    p = d / DD
    p.write_text(p.read_text().replace(old, new))
    (d / F.BANNER).write_bytes((d / f"design-profile/assets/{new}.png").read_bytes())


def mask_request(root: Path, name: str, asset: str) -> Path:
    return req(root, name, [{"id": "R1", "summary": f"{asset} 배너 가장자리 반투명 보정",
                             "facts": [{"kind": "asset_patch", "asset": asset, "op": "mask", "successor": True, "screen": "SCR-001"}]}])


def complete_b(d: Path, cid: str, note: str) -> dict:
    for act in ("verify", "submit"):
        code, out = pd(d, "change", act, "--id", cid)
        assert code == 0, (act, out)
    code, out = pd(d, "change", "approve", "--id", cid, "--note", note)
    assert code == 0, out
    return out


# ================================================================ 1. 분류(읽기 전용)
def classification(d: Path, root: Path) -> None:
    cases = json.loads((HERE / "fixtures/change-type-cases.json").read_text())
    items = [{k: v for k, v in it.items() if k != "expected"} for it in cases["items"]]
    raw0 = (d / ".ai-workflow/design.json").read_bytes()
    code, out = pd(d, "change", "plan", "--request", req(root, "cases", items))
    got = {i["id"]: (i["minimum"], i["status"]) for i in out.get("items", [])}
    bad = {it["id"]: (got.get(it["id"]), it["expected"]) for it in cases["items"]
           if got.get(it["id"]) != (it["expected"]["minimum"], it["expected"]["status"])}
    check(f"K1 분류 정답 사례 {len(cases['items'])}건(A–E, C/E 경계, 보수적 처리, SMAPSH SM1–SM5) 일치", code == 0 and not bad, bad or out)
    check("K2 change plan은 읽기 전용(상태 파일 불변, 기능이 꺼져 있어도 동작)", (d / ".ai-workflow/design.json").read_bytes() == raw0 and out.get("read_only"))
    EVIDENCE["smapsh_classification"] = {i: got.get(i) for i in ("SM1", "SM2", "SM3", "SM4", "SM5")}
    for cid, want in (("E1", "E"), ("C1", "C")):
        code, o = pd(d, "change", "plan", "--request", req(root, f"one-{cid}", [x for x in items if x["id"] == cid]))
        check(f"K3 단일 화면이라도 계약 성격으로 판정: {cid} → {want}", o["type"]["minimum"] == want, o.get("type"))
    code, o = pd(d, "change", "plan", "--request", req(root, "c-route", [x for x in items if x["id"] == "C5"]))
    rt = o["route"]
    check("K4 Type C는 M1 CR로 실행하지 않고 /product-change 변경 패키지 안내(단계 재승인·재탐색 없음, 승인 2회), reopen은 대체 경로로만",
          rt["type"] == "C" and rt["owner"] == "/product-change" and rt["path"] == "change_package"
          and "재승인 없음" in rt["design_approval"] and "필요 없음" in rt["exploration"]
          and any("approve-contract" in x for x in rt["steps"]) and any("approve-final" in x for x in rt["steps"])
          and any("change open --package" in x for x in rt["steps"]) and not any("reopen" in x for x in rt["steps"])
          and "reopen --stage design_direction" in rt["fallback"] and o["scope"]["screens"] == ["SCR-001"]
          and len(o["required"]["approvals"]) == 2 and any("contract_scope_exceeded" in v for v in o["required"]["verification"]), rt)


# ================================================================ 2. 꺼진 상태·v1 호환
def disabled(d: Path, root: Path) -> None:
    code, out = pd(d, "check")
    check("K5 기능을 켜지 않은 프로젝트: check 출력에 changes 없음(기존 동작)", code == 0 and "changes" not in out, out.get("changes"))
    code, out = pd(d, "change", "open", "--request", mask_request(root, "dis", "AST-001"), "--scope-note", "고쳐줘")
    check("K6 꺼진 상태에서 change open → changes_disabled", code == 2 and out["error"] == "changes_disabled", out)
    v1 = T.make_product(root, "v1proj")
    F.ok(v1, "start")
    code, out = pd(v1, "change", "enable")
    check("K7 v1 프로젝트는 변경 요청 비대상(changes_requires_v2), 상태 불변", code == 2 and out["error"] == "changes_requires_v2"
          and "changes" not in state(v1), out)


# ================================================================ 3. 활성화(dry-run·실패 복원)
def enable(d: Path) -> None:
    raw0 = (d / ".ai-workflow/design.json").read_bytes()
    code, out = pd(d, "change", "enable")
    check("K8 enable dry-run: 계획만 출력, 상태 파일 바이트 불변", code == 0 and out["status"] == "plan" and out["dry_run"]
          and (d / ".ai-workflow/design.json").read_bytes() == raw0, out)
    code, out = pd(d, "change", "enable", "--confirm", "--note", "켜 주세요(시뮬레이션)", "--simulate-failure")
    check("K9 enable 도중 실패 → 원래 바이트로 복원(부분 쓰기 없음)", code == 2 and (d / ".ai-workflow/design.json").read_bytes() == raw0, out)
    st0 = state(d)
    code, out = pd(d, "change", "enable", "--confirm", "--note", "변경 요청 기능을 켜 주세요(시뮬레이션)")
    st1 = state(d)
    check("K10 enable: 추가만(기존 승인·revision·해시·history 보존), Git clean이면 백업 생략", code == 0 and out["status"] == "enabled"
          and approvals(st0) == approvals(st1) and st1["history"][:len(st0["history"])] == st0["history"] and out["backup"] is None, out)
    commit(d, "enable changes (user)")


# ================================================================ 4. Type A
def type_a(d: Path, root: Path) -> None:
    (d / "web/src").mkdir(parents=True, exist_ok=True)
    (d / "web/src/login.ts").write_text("export const label = '로그인'\n")
    commit(d, "product code")
    before = approvals(state(d))
    (d / "web/src/login.ts").write_text("export const label = '로그인'  // 버그 수정: 승인 명세 문구\n")
    r = req(root, "a1", [{"id": "R1", "summary": "로그인 버튼 클릭 버그 수정", "facts": [{"kind": "render_fix", "target": "product", "screen": "SCR-001"}]}])
    code, out = pd(d, "change", "plan", "--request", r)
    check("T1a Type A: 승인 산출물 변경 없음 → 최소 유형 A, 경로 /product-build(guard·verify)", code == 0 and out["type"]["minimum"] == "A"
          and not out["changed_files"] and out["route"]["owner"] == "/product-build", out.get("type"))
    code, chk = pd(d, "check")
    check("T1b Type A: 디자인 승인 유지(check 일관, 승인 기록 불변)", code == 0 and approvals(state(d)) == before, chk.get("cross_verify"))
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "버튼 버그 고쳐줘")
    check("T1c Type A는 디자인 CR을 만들지 않음(change_type_not_executable + build 경로 안내)", code == 2 and out["error"] == "change_type_not_executable"
          and out["route"]["type"] == "A", out)
    p02 = d / "docs/design/02-screens.md"
    o02 = p02.read_text()
    p02.write_text(o02.replace("| SCR-001-ST3 | 오류 | 오류 안내 |", "| SCR-001-ST3 | 오류 | 재시도 버튼 |"))
    code, out = pd(d, "change", "plan", "--request", r)
    check("T5a 기능(상태·동작) 변경을 Implementation Fix로 위장 불가: 실제 차이 02 상태 표 → 최소 E", out["type"]["minimum"] == "E"
          and out["pre_confirmation_required"], out.get("type"))
    p02.write_text(o02)
    commit(d, "type A fix (user)")


# ================================================================ 5. Type B — SMAPSH 마스크 수정(AST-081 → AST-082 재현)
def type_b(d: Path, root: Path) -> None:
    st0 = state(d)
    before, hist0 = approvals(st0), list(st0["history"])
    r = mask_request(root, "b1", "AST-001")
    code, plan = pd(d, "change", "plan", "--request", r)
    check("T2a 명확한 마스크 요청 → 추천·최소 B, 작업 전 확인 불필요", plan["type"]["recommended"] == "B" and plan["type"]["minimum"] == "B"
          and not plan["pre_confirmation_required"], plan.get("type"))
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "배너 가장자리 1px 반투명 좀 고쳐줘(요청 원문)")
    check("T2b change open: 요청 원문을 작업 범위 동의로 기록(유형 선택 강요 없음)", code == 0 and out["id"] == "CR-001"
          and out["type"]["selected"] == "B" and out["type"]["selected_by"] == "recommended", out)
    code, out = pd(d, "explore-asset", "replace", "--id", "AST-002", "--file", root / "nope.png", "--note", "x")
    check("T7a 범위 밖 자산(AST-002, 미등록) 교체 시도 → 거부", code == 2, out)
    new, add_out = derived(d, root, F.BANNER_MASK(), "b1", "AST-001")
    st_mid = state(d)
    check("U1 파생본 권리 상속: 별도 권리 확인 질문 없이 승인 자산(AST-001)의 근거 연결(새 사용자 문장 생성 안 함)",
          add_out["rights"]["status"] == "inherited" and st_mid["exploration"]["asset_rights"][new]["statement"] is None
          and st_mid["exploration"]["asset_rights"][new]["inherited_from"]["asset"] == "AST-001"
          and not any(h["event"] == "asset_rights_confirmed" and new in (h.get("note") or "") for h in st_mid["history"]), add_out)
    swap_ref(d, "AST-001", new)
    code, out = pd(d, "check")
    pend = [p for p in out["cross_verify"]["problems"] if p["kind"] == "pending_change"]
    pd(d, "change", "scope", "--id", "CR-001")
    code_after, after = pd(d, "check")
    pend_after = [p for p in after["cross_verify"]["problems"] if p["kind"] == "pending_change"]
    check("T2c 진행 중 변경은 pending_change(승인된 디자인 아님, check 종료 2). 재평가 전 영향 화면은 '알 수 없음'(보수적), change scope 후 SCR-001",
          code == 2 and pend and pend[0]["screens"] is None and code_after == 2 and pend_after[0]["screens"] == ["SCR-001"]
          and not [p for p in out["cross_verify"]["problems"] if p["kind"] == "approved_modified"] and
          out["changes"]["effective_status"]["design_direction"] == "approved_with_pending", out["cross_verify"])
    import pd_guard as GD
    od = GD.official_design(d)
    check("T7b 승인 전 패치 자산은 공식 자산 아님(AST-002 official False). 07이 변경 중이라 공식 근거 전체를 보수적으로 인정하지 않음",
          od["assets"][new]["official"] is False and not od["design_direction_intact"], od["assets"])
    code, out = pd(d, "change", "verify", "--id", "CR-001")
    px = next((c for c in out.get("checks", []) if c["name"] == "asset_pixels"), {})
    pxr = (px.get("results") or [{}])[0].get("pixels") or {}
    check("T2d 부분 검증: 픽셀 비교 edge_only(내부 0, RGB Δ0, 알파만), 권리 재확인, 프리뷰 검사·빌드 통과, 영향 화면 SCR-001만",
          code == 0 and pxr.get("verdict") == "edge_only" and pxr.get("interior_changed") == 0 and pxr.get("rgb_max_delta") == 0
          and out["screens"] == ["SCR-001"] and all(c["ok"] for c in out["checks"]), out)
    EVIDENCE["type_b_pixels"] = pxr
    sv = next((c for c in out.get("checks", []) if c["name"] == "screen_verification"), {})
    check("T2d2 영향 화면 실제 브라우저 검증(전체 빌드와 별개): SCR-001 × 상태 2 × 뷰포트 2 = 4건 측정, 통과", sv.get("state") == "passed"
          and sv.get("measured") == 4 and sv.get("screens") == ["SCR-001"] and not sv.get("expanded_to_all")
          and any(c["name"] == "preview_build" for c in out["checks"]), sv)
    EVIDENCE["screen_verification"] = sv
    code, out = pd(d, "change", "submit", "--id", "CR-001")
    check("T2e submit: 전후 스냅샷(07 해시·자산 스냅샷·프리뷰 트리)·검증 digest·권리 상속 기록, 사용자에게 보여 줄 확인 묶음",
          code == 0 and set(out["submitted"]["stages"]) == {"design_direction", "preview"} and out["submitted"]["verification_digest"]
          and new in out["confirm_with_user"]["rights_inheritance"] and out["confirm_with_user"]["screen_verification"]["status"] == "completed", out)
    code, out = pd(d, "change", "approve", "--id", "CR-001")
    check("T8a 최종 패치 확인 문장 없이 승인 → final_confirmation_required", code == 2 and out["error"] == "final_confirmation_required", out)
    code, out = pd(d, "change", "approve", "--id", "CR-001", "--note", "배너 가장자리 1px 반투명 좀 고쳐줘(요청 원문)")
    check("T8b 최초 요청 원문을 최종 확인으로 재사용 → confirmation_reused", code == 2 and out["error"] == "confirmation_reused", out)
    code, out = pd(d, "change", "approve", "--id", "CR-001", "--note", "전후 비교 확인했고 이 패치를 승인합니다(시뮬레이션)")
    st1 = state(d)
    check("T2f 사용자 최종 확인 1회로 완료 → AMD-001", code == 0 and out["amendment"] == "AMD-001", out)
    cr1 = state(d)["changes"]["items"]["CR-001"]
    check("U2 실제 사용자 개입 1회: 작업 전 확인·범위 재확인·권리 확인 없음, 최종 확인이 패치+권리 상속을 함께 다룸(요청 원문과 별도 기록)",
          "pre_confirmation" not in cr1["consent"] and not cr1["scope"].get("accepted_expansions")
          and cr1["approval"]["covers"] == ["patch", "rights_inheritance"] and cr1["consent"]["scope"]["statement"] != cr1["approval"]["statement"], cr1.get("approval"))
    check("T3a 기존 승인 기록(approved·submitted·last_approved·revision) 바이트 수준 불변 — DD r1·Preview r1 유지", approvals(st1) == before
          and st1["stages"]["design_direction"]["approved"]["revision"] == 1 and st1["stages"]["preview"]["approved"]["revision"] == 1)
    new_events = [h["event"] for h in st1["history"][len(hist0):]]
    check("T3b history는 덧붙이기만, 재승인·무효화 이벤트 없음(전체 Preview 재승인 없음)", st1["history"][:len(hist0)] == hist0
          and not {"reopened", "invalidated", "approved", "submitted"} & set(new_events) and "change_approved" in new_events, new_events)
    code, out = pd(d, "check")
    check("T2g 승인 후 check 일관(유효 기준 = 승인 기록 + 패치), effective_status 모두 approved", code == 0
          and set(out["changes"]["effective_status"].values()) == {"approved"} and out["changes"]["applied"] == {"design_direction": ["AMD-001"], "preview": ["AMD-001"]},
          out.get("cross_verify"))
    od = GD.official_design(d)
    check("T2h 패치 승인 후 공식 자산 전환: AST-002 공식, AST-001은 유효 스냅샷에서 빠짐", od["assets"][new]["official"] and not od["assets"]["AST-001"]["official"], od["assets"])
    amd = st1["changes"]["chain"][0]
    check("T3c 패치 기록: 이전·이후 해시와 승인 원문·제출 digest·검증 digest·체인 digest", amd["stages"]["design_direction"]["files"][DD]["before"]
          == before["design_direction"]["approved"]["hashes"][DD] and amd["statement"].startswith("전후 비교") and amd["submitted_digest"] and amd["verification_digest"]
          and amd["prev"] is None and st1["changes"]["head"] == {"count": 1, "digest": amd["digest"]}, amd)
    check("T14a 영향받지 않은 승인(UX Planning·UX Spec)은 패치 대상 아님(유효 기준 = 원본)", "ux_spec" not in amd["stages"] and "ux_planning" not in amd["stages"])
    EVIDENCE["type_b"] = {"before_revisions": {k: v["revision"] for k, v in before.items()}, "after_revisions": {k: v["revision"] for k, v in approvals(st1).items()},
                          "approved_hashes_equal": approvals(st1) == before, "amendment": {k: amd[k] for k in ("id", "seq", "cr", "digest", "prev", "screens")},
                          "new_history_events": new_events}
    commit(d, "type B patch AMD-001 (user)")


# ================================================================ 5b. SMAPSH 사례 리허설(실제 파일 차이 기준, 실제 저장소 아님)
def smapsh(d: Path, root: Path) -> None:
    out_all = {}

    def plan_base(name: str, items: list) -> dict:
        code, out = pd(d, "change", "plan", "--request", req(root, f"sm-{name}", items), "--base", "HEAD")
        assert code == 0, out
        return out
    theme = d / F.THEME
    t0 = theme.read_text()
    theme.write_text('{"brand": {"primary": "#7FD1B9", "surface": "#F2FBF7"}}\n')
    o = plan_base("sm1", [{"id": "SM1", "summary": "Soft Mint 전역 변경", "facts": [{"kind": "token_value", "token": "color.action.primary", "to": "#7FD1B9"}]}])
    out_all["SM1"] = o["type"]["minimum"]
    check("SM1 Soft Mint 전역 변경(테마 파일 차이) → Type D, 기존 재승인 경로", o["type"]["minimum"] == "D" and o["route"]["type"] == "D", o.get("type"))
    theme.write_text(t0)
    asset_now = "AST-002"
    wide = DC_successor_plan(d, root, F.BANNER_WIDE(), "sm2")
    swap_ref(d, asset_now, wide)
    o = plan_base("sm2", [{"id": "SM2", "summary": "배너 원본 구도·비율 복원", "facts": [{"kind": "asset_patch", "asset": asset_now, "op": "ratio", "successor": True, "to": wide}]}])
    px = [x.get("pixels", {}).get("verdict") for x in o["diff"] if x.get("pixels")]
    out_all["SM2"] = o["type"]["minimum"]
    check("SM2 배너 구도·비율 변경(실제 이미지 48×16 → 64×16) → Type C, 영향 화면 SCR-001만, 변경 패키지 경로 안내", o["type"]["minimum"] == "C"
          and px == ["dimensions_changed"] and o["scope"]["screens"] == ["SCR-001"] and o["route"]["owner"] == "/product-change"
          and "reopen" in o["route"]["fallback"], o.get("type"))
    T.G(d, "checkout", "--", DD, F.BANNER, "design-profile/assets.json")
    (d / f"design-profile/assets/{wide}.png").unlink()
    T.G(d, "checkout", "--", ".ai-workflow/design.json")
    (d / "web/src/Banner.tsx").write_text("export const Banner = () => null  // object-fit 수정\n")
    o = plan_base("sm4", [{"id": "SM4", "summary": "제품 이미지 렌더링 결함 수정", "facts": [{"kind": "render_fix", "target": "product", "screen": "SCR-001"}]}])
    out_all["SM4"] = o["type"]["minimum"]
    check("SM4 제품 코드 이미지 렌더링 결함 수정 → Type A(승인 산출물 차이 없음)", o["type"]["minimum"] == "A" and not o["changed_files"], o.get("type"))
    (d / "web/src/Banner.tsx").unlink()
    (d / "e2e").mkdir(exist_ok=True)
    (d / "e2e/banner.spec.ts").write_text("// 오래된 선택자 수정\n")
    o = plan_base("sm5", [{"id": "SM5", "summary": "오래된 E2E 스크립트 수정", "facts": [{"kind": "test_fix"}]}])
    out_all["SM5"] = o["type"]["minimum"]
    check("SM5 오래된 E2E 스크립트 수정 → Type A", o["type"]["minimum"] == "A" and not o["changed_files"], o.get("type"))
    shutil.rmtree(d / "e2e")
    out_all["SM3"] = "B(T2: AMD-001로 완료)"
    EVIDENCE["smapsh_rehearsal"] = out_all
    check("SM0 리허설 후 프로젝트 원상태(check 일관)", pd(d, "check")[0] == 0)


def DC_successor_plan(d: Path, root: Path, raw: bytes, name: str) -> str:
    """CR 없이 후속 자산을 레지스트리에 추가(분류 리허설용 — 승인된 DD에서도 add는 허용, 공식 자산 아님)."""
    up = root / f"up-{name}"
    up.mkdir()
    (up / "banner.png").write_bytes(raw)
    code, out = pd(d, "explore-asset", "add", "--file", up / "banner.png", "--kind", "image", "--role", "decorative",
                   "--source", "self_made", "--license", "own", "--refs", "SCR-001")
    assert code == 0, out
    return out["asset"]


# ================================================================ 6. 낮은 유형 선택·재분류
def insufficient(d: Path, root: Path) -> None:
    r = req(root, "tok", [{"id": "R1", "summary": "주 색 변경", "facts": [{"kind": "token_value", "token": "color.action.primary", "to": "#0E6B4F"}]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "주 색 바꿔줘", "--type", "B")
    check("T4a 전역 토큰 변경을 Type B로 → change_type_insufficient(최소 D)", code == 2 and out["error"] == "change_type_insufficient" and out["minimum"] == "D", out)
    r = req(root, "perm", [{"id": "R1", "summary": "운영진만 보기", "facts": [{"kind": "permission", "screen": "SCR-002"}]}])
    for t in ("B", "C"):
        code, out = pd(d, "change", "open", "--request", r, "--scope-note", "권한 바꿔줘", "--type", t)
        check(f"T5b 권한 변경을 Type {t}로 → change_type_insufficient(최소 E)", code == 2 and out["error"] == "change_type_insufficient" and out["minimum"] == "E", out)
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "권한 바꿔줘")
    check("T5c Type E는 /product-start 재검토 경로 안내(디자인 CR 없음)", code == 2 and out["error"] == "change_type_not_executable" and out["route"]["owner"] == "/product-start", out)
    n_cr = len((F.state(d).get("changes") or {}).get("items") or {})
    code, out = pd(d, "change", "open", "--request", req(root, "c-layout", [{"id": "R1", "summary": "버튼 위치 변경", "facts": [{"kind": "placement", "screen": "SCR-001"}]}]), "--scope-note", "배치 바꿔줘")
    check("K4b Type C로 change open → change_type_not_executable(CR 미생성), 메시지·route가 변경 패키지를 안내",
          code == 2 and out["error"] == "change_type_not_executable" and "/product-change" in out["message"] and out["route"]["owner"] == "/product-change"
          and out.get("type") == "C" and n_cr == len((F.state(d).get("changes") or {}).get("items") or {}), out)
    # 실제 파일이 요청보다 큰 변경: 비율 변경(크기 다름)
    code, out = pd(d, "change", "open", "--request", mask_request(root, "ratio", "AST-002"), "--scope-note", "가장자리만 다듬어줘")
    cid = out["id"]
    wide = successor(d, root, F.BANNER_WIDE(), "wide")
    swap_ref(d, "AST-002", wide)
    code, out = pd(d, "change", "verify", "--id", cid)
    check("T6a 마스크라고 했지만 실제 이미지 크기·비율 변경 → change_escalated(최소 C), Type B로 완료 불가", code == 2 and out["error"] == "change_escalated"
          and state(d)["changes"]["items"][cid]["status"] == "escalated", out)
    restore_and_cancel(d, cid, f"design-profile/assets/{wide}.png")
    code, out = pd(d, "change", "open", "--request", mask_request(root, "comp", "AST-002"), "--scope-note", "가장자리만 다듬어줘")
    cid = out["id"]
    comp = successor(d, root, F.BANNER_RECOMPOSED(), "comp")
    swap_ref(d, "AST-002", comp)
    code, out = pd(d, "change", "scope", "--id", cid)
    check("T6b 같은 크기라도 내부 구도(픽셀) 변경 → 최소 C로 재분류(escalated)", code == 2 and out["escalated"] and out["type"]["minimum"] == "C"
          and any(x.get("pixels", {}).get("verdict") == "interior" for x in out["diff"]), out.get("type"))
    restore_and_cancel(d, cid, f"design-profile/assets/{comp}.png")
    code, out = pd(d, "check")
    check("T6c 취소 후 기준 상태 복원(check 일관, 진행 중 CR 없음)", code == 0 and not out["changes"]["pending"], out.get("cross_verify"))


def restore_and_cancel(d: Path, cid: str, extra: str | None) -> None:
    code, out = pd(d, "change", "cancel", "--id", cid, "--reason", "x")
    assert code == 2 and out["error"] == "restore_required", out
    T.G(d, "checkout", "--", DD, F.BANNER, "design-profile/assets.json")
    if extra:
        (d / extra).unlink()
    code, out = pd(d, "change", "cancel", "--id", cid, "--reason", "Type B 범위 밖이라 취소(시뮬레이션)")
    assert code == 0, out
    commit(d, f"cancel {cid}")


# ================================================================ 7. 승인되지 않은 교체·검증/제출 이후 변경·범위 확대
def staleness(d: Path, root: Path) -> None:
    code, out = pd(d, "explore-asset", "replace", "--id", "AST-002", "--file", d / "design-profile/assets/AST-001.png", "--note", "몰래 교체")
    check("T7c CR 없이 승인 자산 교체 → assets_locked_by_approval", code == 2 and out["error"] == "assets_locked_by_approval", out)
    orig = (d / F.BANNER).read_bytes()
    (d / F.BANNER).write_bytes(F.BANNER_RECOMPOSED())
    code, out = pd(d, "check")
    check("T7d CR 없이 프리뷰 이미지 교체 → approved_modified(차단, pending 아님)", code == 2 and any(p["kind"] == "approved_modified" for p in (out.get("cross_verify") or {}).get("problems", [])), out)
    (d / F.BANNER).write_bytes(orig)
    code, out = pd(d, "change", "open", "--request", mask_request(root, "b2", "AST-002"), "--scope-note", "가장자리 알파를 조금만 더 낮춰줘")
    cid = out["id"]
    new = successor(d, root, mask_variant(250), "b2")
    swap_ref(d, "AST-002", new)
    scr2 = d / "design-preview/src/screens/SCR-002.tsx"
    o2 = scr2.read_text()
    scr2.write_text(o2.replace("<h1>대진</h1>", "<h1>대진 결과</h1>"))
    code, out = pd(d, "change", "scope", "--id", cid)
    check("T13a 범위 밖 파일(SCR-002.tsx) 변경 감지 → expanded, 재확인 필요(종료 2)", code == 2 and out["expanded"] == ["design-preview/src/screens/SCR-002.tsx"], out)
    code, out = pd(d, "change", "verify", "--id", cid)
    check("T13b 재확인 전 verify → scope_expanded 차단", code == 2 and out["error"] == "scope_expanded", out)
    code, out = pd(d, "change", "scope", "--id", cid, "--accept", "--note", "SCR-002 제목도 같이 고치는 것 동의(시뮬레이션)")
    check("T13c 사용자 재확인 기록 후 범위 재계산(영향 화면 SCR-001·SCR-002로 확대)", code == 0 and not out["expanded"]
          and state(d)["changes"]["items"][cid]["scope"]["screens"] == ["SCR-001", "SCR-002"], out)
    scr2.write_text(o2)  # 이번 패치에서는 되돌림(받아들인 확대는 기록으로 남음)
    code, out = pd(d, "change", "verify", "--id", cid)
    check("T13d 범위 안 변경만 남으면 verify 통과", code == 0, out)
    (d / F.BANNER).write_bytes(orig)
    code, out = pd(d, "change", "submit", "--id", cid)
    check("T10a 검증 이후 파일 변경 → submit 거부(verification_stale)", code == 2 and out["error"] == "verification_stale", out)
    (d / F.BANNER).write_bytes((d / f"design-profile/assets/{new}.png").read_bytes())
    code, out = pd(d, "change", "submit", "--id", cid)
    check("T10b 검증 당시 내용으로 돌아오면 submit 가능(내용 기준 digest)", code == 0, out)
    p = d / DD
    o = p.read_text()
    p.write_text(o + "\n")
    code, out = pd(d, "change", "approve", "--id", cid, "--note", "확인했습니다(시뮬레이션)")
    check("T9 제출 이후 파일 변경 → approve 거부(changed_since_submit)", code == 2 and out["error"] == "changed_since_submit", out)
    p.write_text(o)
    code, out = pd(d, "change", "approve", "--id", cid, "--note", "두 번째 보정도 전후 비교 확인 후 승인(시뮬레이션)")
    check("T10c 되돌린 뒤 최종 확인 → AMD-002", code == 0 and out["amendment"] == "AMD-002", out)
    commit(d, "AMD-002 (user)")


# ================================================================ 8. 동시 CR·stale·rebase·충돌
def concurrency(d: Path, root: Path) -> None:
    typo = req(root, "typo", [{"id": "R1", "summary": "02 문장 오탈자", "facts": [{"kind": "typo", "doc": SCREENS}]}])
    code, out = pd(d, "change", "open", "--request", typo, "--scope-note", "06 오탈자 고쳐줘")
    check("T12a 모호한(conditional) 변경은 작업 전 사용자 확인 필요(pre_confirmation_required)", code == 2 and out["error"] == "pre_confirmation_required", out)
    code, out = pd(d, "change", "open", "--request", typo, "--scope-note", "06 오탈자 고쳐줘", "--pre-confirm", "문구만 고치는 Type B로 진행해(시뮬레이션)")
    ca = out["id"]
    code, out = pd(d, "change", "open", "--request", mask_request(root, "b3", "AST-003"), "--scope-note", "배너 가장자리 다시 보정")
    cb = out["id"]
    check("T12b 서로 겹치지 않는 CR 두 개 동시 진행 가능(02 문장 / 배너 자산)", code == 0, out)
    code, out = pd(d, "change", "open", "--request", mask_request(root, "b3x", "AST-003"), "--scope-note", "같은 배너 또 보정")
    check("T12c 같은 자산·화면을 다루는 CR 동시 진행 → cr_conflict", code == 2 and out["error"] == "cr_conflict", out)
    p2 = d / SCREENS
    p2.write_text(p2.read_text().replace("- **목적**: 대진 생성", "- **목적**: 대진을 생성"))
    code, out = pd(d, "change", "verify", "--id", ca)
    check("T12d 02 문장 CR 검증 통과(작업 전 확인 기록 있음, 다른 CR 파일과 간섭 없음)", code == 0, out)
    new = successor(d, root, mask_variant(240), "b3")
    swap_ref(d, "AST-003", new)
    complete_b(d, cb, "배너 세 번째 보정 확인(시뮬레이션)")
    code, out = pd(d, "change", "submit", "--id", ca)
    check("T12e 다른 패치가 승인돼 기준이 바뀐 CR → submit 거부(cr_stale)", code == 2 and out["error"] == "cr_stale", out)
    code, out = pd(d, "change", "rebase", "--id", ca)
    check("T12f 겹치지 않으면 rebase로 새 기준에 옮김(검증 기록 초기화)", code == 0 and out["status"] == "in_progress", out)
    complete_b(d, ca, "02 문장 수정 결과 확인했습니다(시뮬레이션)")
    st = state(d)
    check("T12g 결과: 체인 4개, 순서·digest 연결 정상, check 일관", len(st["changes"]["chain"]) == 4 and pd(d, "check")[0] == 0,
          [a["id"] for a in st["changes"]["chain"]])
    commit(d, "AMD-003/004 (user)")
    # 상태 파일 동시 변경(같은 컴퓨터)
    import pd_core as C
    st_mem = C.load_state(d)
    other = state(d)
    other["updated_at"] = "2099-01-01T00:00:00Z"
    (d / ".ai-workflow/design.json").write_text(json.dumps(other, ensure_ascii=False, indent=2) + "\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            C.save_state(d, st_mem)
            code = 0
        except SystemExit as e:
            code = e.code
    check("T19a 읽은 뒤 다른 명령이 상태를 바꿈 → state_conflict(덮어쓰지 않음)", code == 2 and "state_conflict" in buf.getvalue()
          and state(d)["updated_at"] == "2099-01-01T00:00:00Z", buf.getvalue()[:300])
    T.G(d, "checkout", "--", ".ai-workflow/design.json")
    lock = d / ".ai-workflow/.design.lock"
    lock.write_text(str(os.getpid()))
    raw0 = (d / ".ai-workflow/design.json").read_bytes()
    code, out = pd(d, "change", "open", "--request", typo, "--scope-note", "x", "--pre-confirm", "y")
    check("T19b 다른 살아 있는 프로세스의 쓰기 잠금 → state_locked(쓰지 않음, 잠금 유지)", code == 2 and out["error"] == "state_locked"
          and (d / ".ai-workflow/design.json").read_bytes() == raw0 and lock.exists(), out)
    lock.write_text("999999")
    code, out = pd(d, "change", "open", "--request", typo, "--scope-note", "x", "--pre-confirm", "y")
    check("T19c 끝난 프로세스가 남긴 잠금은 정리하고 진행", code == 0 and not lock.exists(), out)
    pd(d, "change", "cancel", "--id", out.get("id"), "--reason", "잠금 시험용")
    commit(d, "lock test")


# ================================================================ 9. 체인 무결성
def chain_tamper(d: Path) -> None:
    p = d / ".ai-workflow/design.json"
    raw0 = p.read_bytes()

    def tampered(fn) -> tuple[int, dict]:
        st = json.loads(raw0)
        fn(st)
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n")
        res = pd(d, "check")
        return res
    import pd_change as CH

    def edit(st):
        st["changes"]["chain"][0]["statement"] = "다른 문장"

    def forge(st):
        a = st["changes"]["chain"][1]
        a["statement"] = "위조"
        a["digest"] = CH.amendment_digest(a)

    def delete_last(st):
        st["changes"]["chain"].pop()
        c = st["changes"]["chain"]
        st["changes"]["head"] = {"count": len(c), "digest": c[-1]["digest"]}

    def delete_all(st):
        st["changes"]["chain"] = []
        st["changes"]["head"] = {"count": 0, "digest": None}

    def reorder(st):
        c = st["changes"]["chain"]
        c[1], c[2] = c[2], c[1]

    def snapshot_edit(st):
        st["stages"]["design_direction"]["approved"]["hashes"][DD] = "0" * 64
    for name, fn in (("내용 수정", edit), ("수정 후 digest 재계산(위조)", forge), ("마지막 패치 삭제", delete_last), ("체인 전체 삭제", delete_all), ("순서 변경", reorder)):
        code, out = tampered(fn)
        check(f"T11 체인 {name} → amendment_chain_broken으로 차단(이전 기준으로 조용히 되돌아가지 않음)", code == 2
              and any(x["kind"] == "amendment_chain_broken" for x in out["cross_verify"]["problems"]), out.get("cross_verify"))
    code, out = tampered(snapshot_edit)
    check("T11f 원본 승인 해시를 바꾸면 패치 이전 해시와 불일치 → 차단", code == 2 and any(x["kind"] == "amendment_chain_broken" for x in out["cross_verify"]["problems"]))
    def other_file(st):
        a = st["changes"]["chain"][0]
        f = a["stages"]["design_direction"]["files"]
        f["docs/design/00-ux-decisions.md"] = f.pop(DD)
        a["digest"] = CH.amendment_digest(a)
    code, out = tampered(other_file)
    check("T11i 패치가 승인 기록과 다른 파일을 가리킴(digest 재계산해도) → 이전 해시 불일치로 차단", code == 2
          and any(x["kind"] == "amendment_chain_broken" for x in out["cross_verify"]["problems"]))
    p.write_bytes(raw0)
    snap = CH.effective(state(d))["records"]["design_direction"]["assets"]
    asset_file = d / next(iter(snap.values()))["file"]
    check("T11j 전제: 유효 스냅샷의 패치 자산 파일 존재", asset_file.is_file(), asset_file)
    if asset_file.is_file():
        b0 = asset_file.read_bytes()
        asset_file.write_bytes(F.BANNER_RECOMPOSED())
        code, out = pd(d, "check")
        check("T11j CR 승인 이후 패치 자산 파일 변경 → approved_asset_modified(유효 스냅샷 기준 차단)", code == 2
              and any(x["kind"] == "approved_asset_modified" for x in out["cross_verify"]["problems"]), out.get("cross_verify"))
        asset_file.write_bytes(b0)
    tampered(edit)
    import pd_guard as GD
    code, out = pd(d, "change", "open", "--request", d.parent / "typo.json", "--scope-note", "x", "--pre-confirm", "y")
    check("T11g 체인 문제 상태에서는 새 CR·공식 자산 인정 모두 차단", code == 2 and out["error"] == "amendment_chain_broken"
          and not any(a["official"] for a in GD.official_design(d)["assets"].values()), out)
    p.write_bytes(raw0)
    check("T11h 복원 후 정상", pd(d, "check")[0] == 0)


# ================================================================ 10. Git Worktree 간 충돌(감지·차단만, 병합은 M3)
def worktrees(d: Path, root: Path) -> None:
    wt = root / "wt-alt"
    T.G(d, "worktree", "add", "-q", str(wt), "-b", "alt")
    typo6 = req(root, "wt6", [{"id": "R1", "summary": "02 문장(alt)", "facts": [{"kind": "typo", "doc": SCREENS}]}])
    typo0 = req(root, "wt0", [{"id": "R1", "summary": "00 오탈자(main)", "facts": [{"kind": "typo", "doc": T.UXP}]}])
    code, a = pd(wt, "change", "open", "--request", typo6, "--scope-note", "02 고쳐줘", "--pre-confirm", "문구만(시뮬레이션)")
    (wt / SCREENS).write_text((wt / SCREENS).read_text().replace("- **목적**: 내 정보", "- **목적**: 내 정보 확인"))
    complete_b(wt, a["id"], "alt 쪽 문구 확인(시뮬레이션)")
    commit(wt, "alt patch")
    code, b = pd(d, "change", "open", "--request", typo0, "--scope-note", "00 고쳐줘", "--pre-confirm", "문구만(시뮬레이션)")
    (d / T.UXP).write_text((d / T.UXP).read_text().replace("첫 화면에 카카오 버튼 하나만 둔다", "첫 화면에는 카카오 버튼 하나만 둔다"))
    complete_b(d, b["id"], "main 쪽 문구 확인(시뮬레이션)")
    commit(d, "main patch")
    check("T20a 서로 다른 Worktree가 같은 CR ID·같은 패치 번호를 만듦(로컬 잠금으로 막을 수 없음)", a["id"] == b["id"]
          and state(wt)["changes"]["chain"][-1]["id"] == state(d)["changes"]["chain"][-1]["id"], (a.get("id"), b.get("id")))
    m = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "alt", "--no-edit"], cwd=d, capture_output=True, text=True)
    code, out = pd(d, "check")
    check("T20b design.json 병합 충돌 표시 → state_unreadable로 차단(자동 해결 안 함)", m.returncode != 0 and code == 2 and out["error"] == "state_unreadable"
          and "병합 충돌" in out["message"], out)
    ours = json.loads(subprocess.run(["git", "show", "HEAD:.ai-workflow/design.json"], cwd=d, capture_output=True, text=True).stdout)
    theirs = json.loads(subprocess.run(["git", "show", "alt:.ai-workflow/design.json"], cwd=d, capture_output=True, text=True).stdout)
    cid = b["id"]
    text = json.dumps(ours, ensure_ascii=False, indent=2)
    dup = text.replace('"items": {', '"items": {\n' + json.dumps(cid) + ": " + json.dumps(theirs["changes"]["items"][cid], ensure_ascii=False) + ",", 1)
    (d / ".ai-workflow/design.json").write_text(dup)
    code, out = pd(d, "check")
    check("T20c 양쪽 CR을 같은 키로 손 병합 → state_duplicate_keys(어느 쪽도 고르지 않음)", code == 2 and out["error"] == "state_duplicate_keys", out)
    merged = copy.deepcopy(ours)
    t_cr = copy.deepcopy(theirs["changes"]["items"][cid])
    merged["changes"]["items"]["CR-999"] = t_cr
    merged["changes"]["chain"].append(copy.deepcopy(theirs["changes"]["chain"][-1]))
    (d / ".ai-workflow/design.json").write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    code, out = pd(d, "check")
    check("T20d 같은 기준에서 만든 독립 패치를 체인에 이어 붙임 → amendment_chain_broken(이미 바뀐 기준에서 만든 패치 인정 안 함)",
          code == 2 and any(x["kind"] == "amendment_chain_broken" for x in out["cross_verify"]["problems"]), out.get("cross_verify"))
    subprocess.run(["git", "merge", "--abort"], cwd=d, capture_output=True)
    T.G(d, "checkout", "--", ".")
    T.G(d, "worktree", "remove", "--force", str(wt))
    check("T20e 병합 취소 후 원래 상태로 정상(check 일관)", pd(d, "check")[0] == 0)


def main() -> int:
    root = TMP.mkdtemp("product-design-change-test-")
    d, preview_ok = F.approved_project(root)
    classification(d, root)
    disabled(d, root)
    if not preview_ok:
        for n in ("enable", "Type A", "Type B", "insufficient", "staleness", "concurrency", "chain", "worktree"):
            skip(f"M1 {n}", "프리뷰 빌드(pnpm)를 할 수 없어 프리뷰 승인 프로젝트를 만들지 못했습니다")
    else:
        enable(d)
        type_a(d, root)
        type_b(d, root)
        smapsh(d, root)
        insufficient(d, root)
        staleness(d, root)
        concurrency(d, root)
        chain_tamper(d)
        worktrees(d, root)
    out = os.environ.get("PW_CHANGE_EVIDENCE")
    if out:
        Path(out).write_text(json.dumps(EVIDENCE, ensure_ascii=False, indent=2))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(TMP.run(main))
