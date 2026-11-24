#!/usr/bin/env python3
"""/product-design 변경 요청 M1 — Type B 범용성·화면 검증·사용자 개입 횟수 테스트(독립 픽스처, 자체 완결형).

사례(각각 실제 실행)
 G1 동일 PNG 가장자리 알파 마스크(제자리 교체, 권리 자동 상속)        → B, 사용자 개입 1회
 G2 계약 유지 Preview CSS 렌더링 결함 수정(image-rendering)          → B(자동 판정), 사용자 개입 1회, 영향 화면 실측
 G2b 공통 CSS(preview.css) 렌더링 보정                              → B, 검증 범위 전체 화면으로 확대
 G3 레이아웃 계약 안 경미한 시각 보정(padding)                         → B(작업 전 확인 1회 + 최종 확인 1회)
 G4 의미 불변 문서 오탈자(요청 치환과 실제 차이 일치)                    → B(자동 판정), 사용자 개입 1회
 G5 동일 크기 이미지 내부 구도 변경                                   → C(escalated, 차단)
 G6 CSS로 실제 레이아웃 계약 변경(flex-direction)                     → C(차단)
 G7 오탈자로 위장한 역할·정책 변경                                     → E(차단)
 S* 화면 검증: 측정 미실행·콘솔 오류·이미지 비율 왜곡은 통과로 기록하지 않음, 사용자 면제는 waived로 따로 기록
 R* 권리 상속 불가(라이선스 다름) → 별도 권리 확인 필요
 F* 지원하지 않는 이미지 형식 → 보수적 처리(C)

'사용자 개입'은 엔진이 사용자 문장을 요구하는 지점(작업 전 확인 --pre-confirm, 범위 재확인 --accept --note, 권리 확인 confirm, 최종 확인 approve --note)을
센 값입니다. 최초 요청 원문(--scope-note)은 사용자가 이미 한 말이라 개입으로 세지 않습니다.
실제 Chrome·pnpm이 없으면 SKIP합니다. 실행: python3 tests/product_design_change_generality_test.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _tmpdirs as TMP  # noqa: E402
import change_fixture as F  # noqa: E402
import product_design_test as T  # noqa: E402
import product_design_change_test as DC  # noqa: E402

ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
results: list[tuple[str, bool, str]] = []
pd, state = F.pd, F.state
CSS1 = "design-preview/src/screens/SCR-001.css"
SHARED = "design-preview/src/preview.css"
SCREENS = "docs/design/02-screens.md"
FAKE = r'''import json, os, pathlib
spec = json.load(open(os.environ["PD_MEASURE_SPEC"]))
rd = pathlib.Path(os.environ["PD_REPORT_DIR"])
mode = (pathlib.Path(__file__).parent / "mode.txt").read_text().strip()
out = {"format": "design-explore-report/v1", "run_id": os.environ["PD_RUN_ID"], "tool": "fake"}
if mode == "not_run":
    out.update(status="not_run", reason="브라우저 없음(가짜)", results=[])
else:
    res = []
    for p in spec["pages"]:
        for v in spec["viewports"]:
            img = {"src": "banner-x.png", "complete": True, "natural": [48, 16], "box": [12, 12, 96, 32 if mode != "distorted" else 60], "visible": True,
                   "object_fit": "fill", "clipped_by": None}
            res.append({"variant": p["variant"], "target": p["target"], "viewport": v["name"], "method": "emulation",
                        "viewport_actual": {"width": v["width"], "height": v["height"], "dpr": v["dpr"]}, "rendered": True,
                        "console_errors": ["TypeError: x is undefined"] if mode == "console" else [], "a11y": {"critical": 0, "serious": 0},
                        "interactions": [], "overflow": False, "clipped": False,
                        "layout": {"scroll_width": v["width"], "client_width": v["width"], "elements": []}, "images": [img] if p["target"] == "SCR-001" else []})
    out.update(status="completed", results=res)
(rd / "report.json").write_text(json.dumps(out, ensure_ascii=False))
'''


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:900]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:900]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


class Asks:
    """엔진이 사용자 문장을 요구한 횟수(작업을 멈추고 묻는 지점)."""

    def __init__(self):
        self.n = 0

    def user(self, text: str) -> str:
        self.n += 1
        return text


def req(root: Path, name: str, facts: list) -> Path:
    return DC.req(root, name, [{"id": "R1", "summary": name, "facts": facts}])


def finish(d: Path, cid: str, asks: Asks) -> dict:
    for act in ("verify", "submit"):
        code, out = pd(d, "change", act, "--id", cid)
        assert code == 0, (act, out)
    code, out = pd(d, "change", "approve", "--id", cid, "--note", asks.user(f"{cid} 결과를 확인했고 승인합니다(시뮬레이션)"))
    assert code == 0, out
    DC.commit(d, f"{cid} (user)")
    return out


def revert(d: Path, cid: str, *paths: str, remove: tuple = ()) -> None:
    T.G(d, "checkout", "--", *paths)
    for r in remove:
        (d / r).unlink()
    code, out = pd(d, "change", "cancel", "--id", cid, "--reason", "범위 밖 — 정식 경로로 진행(시뮬레이션)")
    assert code == 0, out
    DC.commit(d, f"cancel {cid}")


def g1(d, root):
    asks = Asks()
    code, out = pd(d, "change", "open", "--request", req(root, "g1", [{"kind": "asset_patch", "asset": "AST-001", "op": "mask"}]),
                   "--scope-note", "배너 가장자리 반투명 고쳐줘(원문)")
    cid = out["id"]
    up = root / "g1"
    up.mkdir()
    (up / "b.png").write_bytes(F.BANNER_MASK())
    code, rep = pd(d, "explore-asset", "replace", "--id", "AST-001", "--file", up / "b.png", "--note", "가장자리 알파 보정")
    (d / F.BANNER).write_bytes((d / "design-profile/assets/AST-001.png").read_bytes())
    out = finish(d, cid, asks)
    st = state(d)
    cr = st["changes"]["items"][cid]
    check("G1 동일 PNG 가장자리 마스크(제자리 교체) → Type B 완료, 권리 자동 상속(별도 확인 없음), 사용자 개입 1회",
          code == 0 and rep["rights"]["status"] == "inherited" and asks.n == 1 and cr["approval"]["covers"] == ["patch", "rights_inheritance"]
          and st["stages"]["design_direction"]["approved"]["revision"] == 1 and st["stages"]["preview"]["approved"]["revision"] == 1, (rep, cr.get("approval")))


def g2(d, root):
    asks = Asks()
    css = d / CSS1
    r = req(root, "g2", [{"kind": "render_fix", "target": "preview", "screen": "SCR-001", "files": [CSS1]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "로그인 배너가 계단처럼 깨져 보여요, 고쳐줘")
    if out.get("error") == "pre_confirmation_required":  # 요청만으로는 conditional — 실제 차이가 렌더링 품질 속성뿐이면 아래 scope에서 확정
        code, out = pd(d, "change", "open", "--request", r, "--scope-note", "로그인 배너가 계단처럼 깨져 보여요, 고쳐줘",
                       "--pre-confirm", asks.user("렌더링 결함만 고치는 걸로 진행해(시뮬레이션)"))
    cid = out["id"]
    css.write_text(css.read_text().replace("image-rendering: pixelated;", "image-rendering: auto;"))
    code, sc = pd(d, "change", "scope", "--id", cid)
    diff = next(x for x in sc["diff"] if x["path"] == CSS1)
    check("G2a 계약 유지 CSS 렌더링 보정(image-rendering만) → 실제 차이 판정 B classified(레이아웃·시각 결정 속성 변경 없음)",
          diff["minimum"] == "B" and diff["status"] == "classified" and sc["type"]["minimum"] == "B", diff)
    code, v = pd(d, "change", "verify", "--id", cid)
    sv = next(c for c in v["checks"] if c["name"] == "screen_verification")
    check("G2b 영향 화면(SCR-001)만 실제 브라우저 측정·통과(전체 빌드와 별도 기록)", code == 0 and sv["state"] == "passed" and sv["screens"] == ["SCR-001"]
          and sv["measured"] == 4, sv)
    finish(d, cid, asks)
    check("G2c 대상이 구체적인 렌더링 보정은 작업 전 질문 없이 실제 차이로 판정 → 사용자 개입 1회", asks.n == 1, asks.n)
    EV["g2_asks"] = asks.n


def g2_shared(d, root):
    asks = Asks()
    sh = d / SHARED
    r = req(root, "g2s", [{"kind": "render_fix", "target": "preview", "files": [SHARED]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "전체 글자 렌더링이 흐려요", "--pre-confirm", asks.user("렌더링만 고쳐(시뮬레이션)"))
    cid = out["id"]
    sh.write_text(sh.read_text() + "\nbody { -webkit-font-smoothing: antialiased; }\n")
    code, v = pd(d, "change", "verify", "--id", cid)
    sv = next((c for c in v.get("checks", []) if c["name"] == "screen_verification"), {})
    check("G2d 공통 파일(preview.css) 변경 → 영향 화면 '알 수 없음'으로 확대해 manifest 전 화면 측정", code == 0 and sv.get("expanded_to_all")
          and sv.get("screens") == ["SCR-001", "SCR-002", "SCR-003"], sv or v)
    finish(d, cid, asks)


def g3(d, root):
    asks = Asks()
    css = d / CSS1
    r = req(root, "g3", [{"kind": "render_fix", "target": "preview", "screen": "SCR-001", "files": [CSS1]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "배너 주변 여백 살짝만 넓혀줘")
    cid = out["id"]
    css.write_text(css.read_text().replace("padding: 12px;", "padding: 14px;"))
    code, sc = pd(d, "change", "scope", "--id", cid)
    diff = next(x for x in sc["diff"] if x["path"] == CSS1)
    code_v, v = pd(d, "change", "verify", "--id", cid)
    check("G3a 경미한 시각 보정(padding) → B conditional: 계약 안인지 자동 판정 불가 → 제출 전에 사용자 확인 요구(pre_confirmation_required)",
          diff["minimum"] == "B" and diff["status"] == "conditional" and code_v == 2 and v["error"] == "pre_confirmation_required", (diff, v.get("error")))
    code, out = pd(d, "change", "scope", "--id", cid, "--accept", "--note", asks.user("여백 2px만 늘린 거 맞고 기존 레이아웃 안이야(시뮬레이션)"))
    assert code == 0, out
    finish(d, cid, asks)
    check("G3b 자동 판정 불가한 B는 사용자 확인 1 + 최종 확인 1 = 2회(명확한 B와 구분)", asks.n == 2, asks.n)


def g4(d, root):
    asks = Asks()
    r = req(root, "g4", [{"kind": "typo", "doc": SCREENS, "from": "대진 생성", "to": "대진을 생성"}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "02 문서 '대진 생성'을 '대진을 생성'으로 고쳐줘")
    check("G4a 오탈자 요청(정확한 치환 명시)은 작업 전 확인 없이 열림", code == 0, out)
    cid = out["id"]
    p = d / SCREENS
    p.write_text(p.read_text().replace("대진 생성", "대진을 생성"))
    code, sc = pd(d, "change", "scope", "--id", cid)
    diff = next(x for x in sc["diff"] if x["path"] == SCREENS)
    check("G4b 실제 차이 = 요청 치환(정책·권한·숫자 변경 없음) → B classified(typo_verified)", diff["status"] == "classified" and diff.get("typo_verified")
          and not sc["pre_confirmation_required"], diff)
    finish(d, cid, asks)
    check("G4c 오탈자 수정 사용자 개입 1회", asks.n == 1, asks.n)


def g5(d, root):
    code, out = pd(d, "change", "open", "--request", req(root, "g5", [{"kind": "asset_patch", "asset": "AST-001", "op": "mask", "successor": True}]),
                   "--scope-note", "가장자리만 다듬어줘")
    cid = out["id"]
    new, add = DC.derived(d, root, F.BANNER_RECOMPOSED(), "g5", "AST-001")
    DC.swap_ref(d, "AST-001", new)
    code, v = pd(d, "change", "verify", "--id", cid)
    check("G5 동일 크기 내부 구도 변경 → 권리 상속 거부(파생 보정 아님) + change_escalated(최소 C)", add["rights"]["status"] == "confirmation_required"
          and code == 2 and v["error"] == "change_escalated", (add.get("rights"), v.get("error")))
    revert(d, cid, DC.DD, F.BANNER, "design-profile/assets.json", remove=(f"design-profile/assets/{new}.png",))


def g6(d, root):
    css = d / CSS1
    r = req(root, "g6", [{"kind": "render_fix", "target": "preview", "screen": "SCR-001", "files": [CSS1]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "배너 렌더링 고쳐줘", "--pre-confirm", "렌더링 수정(시뮬레이션)")
    cid = out["id"]
    css.write_text(css.read_text().replace("flex-direction: column;", "flex-direction: row;"))
    code, v = pd(d, "change", "verify", "--id", cid)
    check("G6 CSS로 레이아웃 계약 변경(flex-direction) → C로 재분류, Type B 완료 차단", code == 2 and v["error"] == "change_escalated"
          and any("flex-direction" in r_ for r_ in v["reasons"]), v)
    revert(d, cid, CSS1)


def g7(d, root):
    p = d / SCREENS
    o = p.read_text()
    r = req(root, "g7", [{"kind": "typo", "doc": SCREENS, "from": "내 정보", "to": "내 정보"}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "02 오탈자 하나 고쳐줘", "--pre-confirm", "오탈자만(시뮬레이션)")
    cid = out["id"]
    p.write_text(o.replace("- **역할**: 운영진", "- **역할**: 회원"))
    code, sc = pd(d, "change", "scope", "--id", cid)
    check("G7a 오탈자로 위장한 역할(권한) 변경 → 최소 E, 차단", code == 2 and sc["escalated"] and sc["type"]["minimum"] == "E", sc.get("type"))
    p.write_text(o.replace("- **목적**: 대진을 생성", "- **목적**: 대진을 삭제"))
    code, sc = pd(d, "change", "scope", "--id", cid)
    check("G7b 오탈자로 위장한 정책 단어 변경(생성→삭제) → 최소 E(needs_review), 차단", code == 2 and sc["type"]["minimum"] == "E", sc.get("type"))
    p.write_text(o)
    pd(d, "change", "cancel", "--id", cid, "--reason", "위장 변경 — 정식 경로")
    DC.commit(d, "g7 cancel")


def screen_negative(d, root):
    (d / "tools/fake").mkdir(parents=True, exist_ok=True)
    (d / "tools/fake/measure.py").write_text(FAKE)
    mode = d / "tools/fake/mode.txt"
    mode.write_text("ok")
    code, out = pd(d, "explore-config", "--measure-cmd", f"{sys.executable} tools/fake/measure.py", "--confirm", "--note", "가짜 측정 명령 확인(시뮬레이션)")
    assert code == 0, out
    DC.commit(d, "fake measure")
    css = d / CSS1
    r = req(root, "sneg", [{"kind": "render_fix", "target": "preview", "screen": "SCR-001", "files": [CSS1]}])
    code, out = pd(d, "change", "open", "--request", r, "--scope-note", "렌더링 고쳐줘")
    cid = out.get("id") or pd(d, "change", "open", "--request", r, "--scope-note", "렌더링 고쳐줘", "--pre-confirm", "네(시뮬레이션)")[1]["id"]
    css.write_text(css.read_text().replace("image-rendering: auto;", "image-rendering: -webkit-optimize-contrast;"))
    for m, name in (("not_run", "측정 미실행"), ("console", "콘솔 오류"), ("distorted", "이미지 비율 왜곡")):
        mode.write_text(m)
        code, v = pd(d, "change", "verify", "--id", cid)
        sv = next((c for c in v.get("checks", []) if c["name"] == "screen_verification"), {})
        check(f"S1 {name} → 화면 검증 통과로 기록하지 않음(verify 실패, state {sv.get('state')})", code == 2 and sv.get("state") in ("not_run", "failed")
              and state(d)["changes"]["items"][cid]["status"] != "verified", sv)
    mode.write_text("not_run")
    code, v = pd(d, "change", "verify", "--id", cid, "--screen-waiver", "측정 환경이 없으니 이번만 화면 측정 없이 진행(시뮬레이션)")
    vr = state(d)["changes"]["items"][cid]["verification"]["screen_verification"]
    check("S2 측정 불가 시 사용자 면제는 'waived'로 따로 기록(completed·passed 아님)", code == 0 and vr["status"] == "not_run" and vr["passed"] is False
          and vr["waiver"]["statement"].startswith("측정 환경"), vr)
    mode.write_text("ok")
    code, v = pd(d, "change", "verify", "--id", cid)
    code2, s = pd(d, "change", "submit", "--id", cid)
    check("S3 정상 측정 후 submit 스냅샷에 화면 검증 결과(run_id·리포트 digest)와 검증 digest 연결", code == 0 and code2 == 0
          and s["submitted"]["screen_verification"]["status"] == "completed" and s["submitted"]["screen_verification"]["report_sha256"]
          and s["submitted"]["verification_digest"], s.get("submitted", {}).get("screen_verification"))
    code, a = pd(d, "change", "approve", "--id", cid, "--note", "확인했습니다(시뮬레이션)")
    amd = state(d)["changes"]["chain"][-1]
    check("S4 Amendment에 검증 digest·화면 검증 결과 연결", code == 0 and amd["verification_digest"] == DC_digest(state(d)["changes"]["items"][cid]["verification"])
          and amd["screen_verification"]["status"] == "completed", amd.get("screen_verification"))
    DC.commit(d, "sneg")


def DC_digest(obj):
    import pd_change as CH
    return CH.digest(obj)


def rights_negative(d, root):
    code, out = pd(d, "change", "open", "--request", req(root, "rn", [{"kind": "asset_patch", "asset": "AST-001", "op": "mask", "successor": True}]),
                   "--scope-note", "가장자리 다듬어줘")
    cid = out["id"]
    up = root / "rn"
    up.mkdir()
    (up / "b.png").write_bytes(DC.mask_variant(200))
    code, add = pd(d, "explore-asset", "add", "--file", up / "b.png", "--kind", "image", "--role", "decorative", "--source", "licensed",
                   "--license", "Stock-X", "--refs", "SCR-001", "--derived-from", "AST-001")
    check("R1 출처·라이선스가 다른 자산(외부 라이선스) → 권리 상속 안 함, 별도 권리 확인 필요", code == 0 and add["rights"]["status"] == "confirmation_required"
          and any("라이선스" in x or "출처" in x for x in add["rights"]["reasons"]) and not add["official_ok"], add.get("rights"))
    T.G(d, "checkout", "--", "design-profile/assets.json")
    (d / add["file"]).unlink()
    pd(d, "change", "cancel", "--id", cid, "--reason", "권리 확인 필요 사례")
    DC.commit(d, "rn cancel")


def formats():
    import pd_change as CH
    import pd_pixel as PX
    r = PX.compare(b"\xff\xd8\xff\xe0jpeg", b"\xff\xd8\xff\xe0jpeg2")
    a = CH.asset_analysis({"kind": "image"}, {"kind": "image"}, b"<svg/>", b"<svg></svg>")
    check("F1 JPEG·SVG 등 지원하지 않는 형식 → 픽셀 판정 불가, Type B로 확정하지 않음(C, 사유 안내)", r["analyzable"] is False and a["minimum"] == "C"
          and "확정하지 않습니다" in a["reasons"][0], (r, a))


EV: dict = {}


def main() -> int:
    formats()
    if shutil.which("pnpm") is None or not any(Path(p).exists() for p in ("/Applications/Google Chrome.app", "/usr/bin/google-chrome", "/usr/bin/chromium")):
        skip("G1–G7·S·R", "pnpm 또는 Chrome이 없어 실제 프리뷰 빌드·화면 측정을 할 수 없습니다")
    else:
        root = TMP.mkdtemp("product-design-change-gen-")
        d, ok = F.approved_project(root, "gen")
        if not ok:
            skip("G1–G7·S·R", "프리뷰 빌드 실패(환경)")
        else:
            F.ok(d, "change", "enable", "--confirm", "--note", "변경 요청 기능 켜기(시뮬레이션)")
            DC.commit(d, "enable")
            for fn in (g1, g2, g2_shared, g3, g4, g5, g6, g7, rights_negative, screen_negative):
                fn(d, root)
            code, out = pd(d, "check")
            st = state(d)
            check("G0 전체 사례 후: 승인 revision 유지(DD r1·Preview r1), 체인 정상, check 일관", code == 0
                  and st["stages"]["design_direction"]["approved"]["revision"] == 1 and st["stages"]["preview"]["approved"]["revision"] == 1
                  and out["changes"]["chain_ok"], out.get("cross_verify"))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(TMP.run(main))
