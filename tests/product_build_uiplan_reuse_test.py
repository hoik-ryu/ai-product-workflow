#!/usr/bin/env python3
"""/product-build P2·P3 테스트(자체 완결형): UI Plan 명세 검증 보강과 구현 코드–계획 정적 대조.

사례 프로젝트와 무관한 독립 픽스처(product_build_ui_test의 도서관 좌석 예약 기획·디자인 L2, 기존 부품 등록)를 씁니다.
- P2: 02가 화면에 지정한 CMP가 UI Plan 트리에 없으면 screen_cmp_unused(결정된 원장 근거만 제외 허용),
      대응 부품과 이름이 비슷한 로컬 부품은 similar_to_mapped 경고(확정·자동 수정 없음)
- P3: verify의 부품 검사(배치 범위 중복은 차단, 재사용 미이행 planned_reuse_not_used는 보고), ui-guard의 부품 폴더 밖 새 컴포넌트 경고
실행: python3 tests/product_build_uiplan_reuse_test.py
"""
from __future__ import annotations

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
import product_build_uiguard_test as GT  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G
w = UT.w
sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
import pb_core  # noqa: E402
import pb_ui  # noqa: E402
import pb_ledger  # noqa: E402
import product_build  # noqa: E402

TOKENS_CSS = GT.TOKENS_CSS


def codes(out: dict, key: str = "errors") -> list[str]:
    return [m.split("]")[0].lstrip("[") for m in out.get(key) or []]


def fixture(root: Path) -> tuple[Path, dict]:
    d = UT.make_ui_product(root, "uiplan")
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(props) { return render('button', props) }\n")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    w(d, "web/src/styles/tokens.css", TOKENS_CSS)
    w(d, "api/contract.txt", "GET /api/seats\nPOST /api/reservations\n")
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE)
    for c, f, e in (("CMP-001", "Button.view", "Button"), ("CMP-002", "SeatMap.view", "SeatMap")):
        code, out = pb(d, "ui-map", "register", "--cmp", c, "--path", f"web/src/components/{f}", "--export", e, "--note", "사용자 확인: 기존 부품")
        assert code == 0, out
    pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "기존 tokens.css 기준")
    G(d, "add", "-A"); G(d, "commit", "-qm", "map")
    plan = UT.plan_for(["CMP-003"], ["CMP-001", "CMP-002"])  # B0가 CMP-003(후보 파일 없음)을 새로 만들고 B1은 대응 부품 재사용
    plan["batches"][2]["components"] = {"reuse": ["CMP-001", "CMP-003"], "new": []}
    plan["batches"][2]["depends_on"] = ["B0", "B1"]
    UT.approve_plan(d, plan)
    code, out = pb(d, "ui-brief", "--batch", "B1")
    assert code == 0, out
    return d, out


# ---------------------------------------------------------------- P2
def scenario_p2(d: Path, brief_out: dict) -> None:
    snap = T.protected_snapshot(d)
    good = UT.good_ui_plan(brief_out["digest"])
    UT.write_ui_plan(d, good)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("V1 02가 지정한 CMP를 모두 대응 부품으로 쓰는 정상 UI Plan은 통과(재사용 차단 없음)", code == 0 and out["ok"]
          and "screen_cmp_unused" not in codes(out) and "similar_to_mapped" not in codes(out, "warnings"), out.get("errors"))

    bad = json.loads(json.dumps(good))
    bad["screens"]["SCR-001"]["tree"][0]["children"] = [{"part": "Button", "cmp": "CMP-001"}]  # SeatMap(CMP-002) 누락
    UT.write_ui_plan(d, bad)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    e = [m for m in out.get("errors", []) if m.startswith("[screen_cmp_unused]")]
    check("V2 02가 SCR-001에 지정한 CMP-002가 트리에 없음: screen_cmp_unused 오류", code == 2 and len(e) == 1 and "SCR-001" in e[0] and "CMP-002" in e[0]
          and "cmp_exclusions" in e[0], out.get("errors"))

    code, out = pb(d, "ledger", "add", "--type", "policy", "--title", "SCR-001 첫 버전은 좌석 지도 대신 목록",
                   "--desc", "지도 데이터 준비 전까지 목록으로 표시", "--rationale", "명세 부품 제외")
    pol = out["item"]["id"]
    bad["screens"]["SCR-001"]["cmp_exclusions"] = {"CMP-002": pol}
    UT.write_ui_plan(d, bad)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("V3 제외 근거가 결정 전(open) 원장 항목이면 여전히 오류", code == 2 and any(m.startswith("[screen_cmp_unused]") and "결정된" in m for m in out["errors"]), out.get("errors"))
    bad["screens"]["SCR-001"]["cmp_exclusions"] = {"CMP-002": "POL-999"}
    UT.write_ui_plan(d, bad)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("V4 없는 원장 ID는 제외 근거로 인정하지 않음", code == 2 and "screen_cmp_unused" in codes(out), out.get("errors"))
    pb(d, "decide", "--id", pol, "--decision", "SCR-001 첫 버전은 목록으로", "--note", "지도는 다음 버전에서 넣습니다", "--confirm")
    bad["screens"]["SCR-001"]["cmp_exclusions"] = {"CMP-002": pol}
    UT.write_ui_plan(d, bad)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("V5 결정된(decided) 원장 항목으로만 의도적 제외 허용(경고 screen_cmp_excluded로 기록)", code == 0 and out["ok"]
          and "screen_cmp_excluded" in codes(out, "warnings"), out.get("errors"))

    sim = json.loads(json.dumps(good))
    sim["screens"]["SCR-002"]["tree"][0]["children"].append({"part": "ConfirmButton", "local": True, "file": "web/src/features/seats/ConfirmButton.view"})
    sim["screens"]["SCR-001"]["tree"][0]["children"].append({"part": "SeatMapper", "local": True, "file": "web/src/features/seats/SeatMapper.view"})
    UT.write_ui_plan(d, sim)
    raw = (d / ".ai-workflow/build/ui/B1/plan.json").read_bytes()
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    sw = [m for m in out.get("warnings", []) if m.startswith("[similar_to_mapped]")]
    check("V6 대응 부품 이름(Button)을 단어로 포함한 로컬 부품: similar_to_mapped 경고만(오류·차단 아님)", code == 0 and out["ok"]
          and len(sw) == 1 and "ConfirmButton" in sw[0] and "같은 부품이라는 뜻은 아닙니다" in sw[0], out.get("warnings"))
    check("V7 단어 경계가 아닌 포함(SeatMapper ⊅ SeatMap 단어)은 경고하지 않음", not any("SeatMapper" in m for m in sw), sw)
    check("V8 경고만 하고 UI Plan을 자동으로 고치지 않음", (d / ".ai-workflow/build/ui/B1/plan.json").read_bytes() == raw)
    check("V9 단위: similar_mapped 판정(대문자 경계, 3자 이상, 같은 이름 제외)",
          pb_ui.similar_mapped("ReservationCard", {"Card": "CMP-9"}) == ["Card"] and pb_ui.similar_mapped("Cardinal", {"Card": "CMP-9"}) == []
          and pb_ui.similar_mapped("Card", {"Card": "CMP-9"}) == [] and pb_ui.similar_mapped("TabBar", {"Ta": "CMP-9"}) == [])
    UT.write_ui_plan(d, good)
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("V10 승인 문서·state.yaml·design.json 불변", code == 0 and T.protected_snapshot(d) == snap)


# ---------------------------------------------------------------- P3 verify 부품 검사(verify가 호출하는 함수)
def scenario_p3_verify(d: Path) -> None:
    st = json.loads((d / ".ai-workflow/build.json").read_text())
    plan = json.loads((d / "docs/build/implementation-plan.json").read_text())
    prof = pb_core.load_profile(d)[0]
    uprof = pb_ui.ui_profile(prof)[0]
    umap = pb_ui.load_map(d)
    uplan = json.loads((d / ".ai-workflow/build/ui/B1/plan.json").read_text())
    brief = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())

    def run():
        R, W = [], []
        res = product_build._ui_component_checks(d, st, plan, "B1", uprof, uplan, umap, brief, R, W)
        return res, R, W

    w(d, "web/src/features/seats/SeatStatusPage.view", "import { SeatMap } from '../../components/SeatMap'\nexport const SeatStatusPage = (p) => SeatMap(p)\n")
    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = (p) => Button({ label: '확정' })\n")
    res, R, W = run()
    used = res["reuse"]["used"]
    check("C1 재사용 계획 이행: import(SeatMap)·식별자 사용(Button) 모두 참조로 인정, 차단·경고 없음",
          not R and not [m for m in W if m.startswith("[planned_reuse_not_used]")]
          and used["CMP-002"] == [{"file": "web/src/features/seats/SeatStatusPage.view", "how": "import"}]
          and used["CMP-001"] == [{"file": "web/src/features/seats/ReserveConfirm.view", "how": "identifier"}], (R, W, used))
    check("C2 결과에 정적 참조의 한계(렌더링 증거 아님) 명시", "렌더링" in res["reuse"]["note"], res["reuse"]["note"])

    w(d, "web/src/features/seats/ReserveConfirm.view", "// Button을 쓰려 했지만 직접 그림\nexport const ReserveConfirm = (p) => box('button', p)\n")
    res, R, W = run()
    nu = [m for m in W if m.startswith("[planned_reuse_not_used]")]
    check("C3 재사용 미이행(주석 속 이름은 참조 아님): planned_reuse_not_used 보고(경고, verify 차단 아님)",
          not R and len(nu) == 1 and "CMP-001" in nu[0] and res["reuse"]["unused"][0]["screens"] == ["SCR-001", "SCR-002"], (R, W))

    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = (p) => Button(p)\n")
    w(d, "web/src/features/seats/MySeatMap.view", "// CMP-002 복사본\nexport const MySeatMap = (p) => p\n")
    res, R, W = run()
    check("C4 배치 범위의 중복 부품(이미 대응된 CMP-002 표지를 다른 파일에 구현): verify 차단 사유([ui_map] duplicate_component)",
          any(m.startswith("[ui_map] [duplicate_component]") and "MySeatMap.view" in m for m in R) and res["map"]["duplicates"][0]["cmp"] == "CMP-002", R)
    (d / "web/src/features/seats/MySeatMap.view").unlink()
    w(d, "web/src/features/admin/Button.view", "export const Button = (p) => p\n")  # B3 범위(이 배치 밖)
    res, R, W = run()
    check("C5 이 배치 범위 밖 파일은 이 배치의 중복 검사 대상 아님", not R, R)
    (d / "web/src/features/admin/Button.view").unlink()

    umap2 = json.loads(json.dumps(umap))
    umap2["components"]["CMP-003"] = {"source": "existing", "path": "web/src/components/Gone.view", "export": "DataTable"}
    R, W = [], []
    product_build._ui_component_checks(d, st, plan, "B1", uprof, uplan, umap2, brief, R, W)
    check("C6 이 배치와 관계없는 대응표 오류(CMP-003 파일 없음)는 경고로만 보고", not R and any("CMP-003" in m and "path_missing" in m for m in W), (R, W))
    R, W = [], []
    res = product_build._ui_component_checks(d, st, plan, "B1", uprof, uplan, None, brief, R, W)
    check("C7 대응표가 없는 프로젝트: 부품 검사 건너뜀(기존 동작)", res == {"status": "no_ui_map"} and not R and not W, res)
    refs = pb_ui.planned_reuse_refs(d, None, umap, ["web/src/features/seats/ReserveConfirm.view"])
    check("C8 UI Plan이 없으면 재사용 대조 대상 없음(오류 없이 빈 결과)", refs["checked"] == [] and refs["unused"] == [], refs)
    lib = {"components": {"CMP-003": {"source": "library", "package": "some-ui-kit@2", "export": "DataTable"}}}
    w(d, "web/src/features/reservations/List.view", "import { Grid } from 'some-ui-kit'\n")
    up = {"screens": {"SCR-003": {"tree": [{"part": "DataTable", "cmp": "CMP-003"}]}}}
    refs = pb_ui.planned_reuse_refs(d, up, lib, ["web/src/features/reservations/List.view"])
    check("C9 라이브러리 부품: 패키지 import도 참조로 인정", refs["used"].get("CMP-003") == [{"file": "web/src/features/reservations/List.view", "how": "import"}], refs)


# ---------------------------------------------------------------- P3 ui-guard
def scenario_guard(root: Path) -> None:
    d = GT.base_fixture(root, "guard-outside")
    GT.register(d)
    pb(d, "ui-map", "register", "--cmp", "CMP-001", "--path", "web/src/components/Button.view", "--export", "Button", "--note", "확인")
    G(d, "add", "-A"); G(d, "commit", "-qm", "map")
    w(d, "web/src/features/seats/SeatBadge.view", "export const SeatBadge = (p) => box(p)\n")
    code, out = GT.ug(d)
    oc = out["checks"]["components"].get("outside_roots")
    check("G1 부품 폴더 밖 새 컴포넌트(PascalCase 함수형 const): component_outside_roots 경고, exit 0",
          code == 0 and oc == [{"file": "web/src/features/seats/SeatBadge.view", "exports": ["SeatBadge"]}]
          and any(h["code"] == "component_outside_roots" and h["type"] == "T2" for h in out["route_hint"]), out.get("warnings"))
    GT.reset(d)
    w(d, "web/src/pages/Home.view", "export default function Home(p) { return p }\n")
    w(d, "web/src/features/seats/SeatListPage.view", "export function SeatListPage(p) { return p }\n")
    w(d, "web/src/features/seats/index.view", "export const Widget = () => 1\n")
    w(d, "web/src/features/seats/SeatBadge.test.view", "export const FakeBadge = () => 1\n")
    w(d, "web/src/features/seats/util.view", "export const Colors = { a: 1 }\nexport const MAX_SEATS = 3\nexport const LIMIT = 10\n"
      "export function formatSeat(s) { return s }\nexport const SeatContext = createContext(null)\nexport const API_URL = '/x'\n")
    code, out = GT.ug(d)
    check("G2 오탐 줄이기: 페이지 폴더·Page 접미사·index 파일·테스트·상수·객체·소문자 함수·Context는 경고하지 않음",
          code == 0 and "component_outside_roots" not in codes(out, "warnings"), out["checks"]["components"].get("outside_roots"))
    GT.reset(d)
    w(d, GT.LEGACY, GT.LEGACY_TEXT.replace("기존 화면", "문구만 수정"))
    code, out = GT.ug(d)
    check("G3 base에 이미 있던 부품 폴더 밖 선언(SeatList)은 새 경고 아님", code == 0 and "component_outside_roots" not in codes(out, "warnings"), out.get("warnings"))
    GT.reset(d)
    (d / "docs/build/build-profile.toml").write_text(UT.PROFILE.split("[ui]")[0].replace('components = ["web/src/components"]\n', ""))
    G(d, "add", "-A"); G(d, "commit", "-qm", "no roots")
    w(d, "web/src/features/seats/SeatBadge.view", "export const SeatBadge = (p) => box(p)\n")
    code, out = GT.ug(d)
    check("G4 부품 폴더가 정해지지 않은 프로젝트: 이 경고를 하지 않음", code == 0 and "component_outside_roots" not in codes(out, "warnings"), out.get("warnings"))


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-uiplan-reuse-test-"))
    try:
        d, brief_out = fixture(root)
        scenario_p2(d, brief_out)
        scenario_p3_verify(d)
        scenario_guard(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
