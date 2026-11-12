#!/usr/bin/env python3
"""/product-build M3.3·M3.4 테스트(자체 완결형): 화면 상태 증거, 수동 증거(EM), 브라우저 검증 리포트(pb-ui-report/v1).

사례 프로젝트와 무관한 독립 픽스처(도서관 좌석 예약)를 씁니다. 실제 브라우저·Node 없이 검사합니다.
- 테스트 실행기(tools/run_ui_tests.py): 테스트 파일(*.test.view)의 `case <결과> <이름>` 줄을 pb-test-report/v1로 냅니다.
- 브라우저 어댑터 대역(tools/fake_browser.py): tools/browser-scenario.json대로 pb-ui-report/v1을 냅니다
  (정상·미실행·잘못된 JSON·다른 실행의 리포트·시간 초과·리포트 없음·스크린샷만).
실행: python3 tests/product_build_uiev_test.py
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

sys.path.insert(0, str(T.ENGINE / "skills/product-build/scripts"))
import pb_core as C  # noqa: E402
import pb_uiev as UV  # noqa: E402
import pb_verify as V  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G
w = UT.w

PROFILE = UT.PROFILE.replace("max_retries = 3", "max_retries = 5") + """[browser]
enabled = true
viewports = ["mobile", "desktop"]
[[verify.steps]]
name = "unit"
stage = "test"
run = "python3 -B tools/run_ui_tests.py"
report = { format = "pb-json", file = "unit.json" }
[[verify.steps]]
name = "browser"
stage = "browser"
run = "python3 -B tools/fake_browser.py"
requires = ["browser"]
timeout = 4
report = { format = "pb-ui", file = "ui.json" }
"""

RUNNER = r'''import json, os, pathlib, sys
cases = []
for f in sorted(pathlib.Path("web/src").rglob("*.test.view")):
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.startswith("case "):
            _, status, name = line.split(" ", 2)
            cases.append({"id": f"{f}::{name}", "name": name, "file": str(f), "status": status})
out = pathlib.Path(os.environ["PB_REPORT_DIR"]) / "unit.json"
out.write_text(json.dumps({"format": "pb-test-report/v1", "tool": "fixture", "cases": cases}, ensure_ascii=False))
sys.exit(0 if all(c["status"] in ("passed", "skipped") for c in cases) else 1)
'''

FAKE_BROWSER = r'''import json, os, pathlib, sys, time
sc = json.loads(pathlib.Path("tools/browser-scenario.json").read_text(encoding="utf-8"))
rd = pathlib.Path(os.environ["PB_REPORT_DIR"])
mode = sc.get("mode", "ok")
if mode == "sleep":
    time.sleep(10)
if mode == "noreport":
    sys.exit(1)
for r in sc.get("results", []):
    if r.get("screenshot"):
        p = rd / r["screenshot"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG fixture")
rep = {"format": "pb-ui-report/v1", "run_id": os.environ["PB_RUN_ID"] if mode != "stale" else "20200101-000000-old000",
       "tool": "fake-browser@0", "base_url": "http://127.0.0.1:0", "status": "not_run" if mode == "not_run" else "completed",
       "reason": sc.get("reason"), "results": sc.get("results", [])}
(rd / "ui.json").write_text("{ 깨진 JSON" if mode == "bad_json" else json.dumps(rep, ensure_ascii=False))
sys.exit(sc.get("exit", 0))
'''

STATES_ALL = ["SCR-001-ST1", "SCR-001-ST2", "SCR-001-ST3", "SCR-002-ST1", "SCR-002-ST2", "SCR-002-ST3"]


def res(state, vp="mobile", **kw):
    r = {"screen": state[:7], "state": state, "viewport": vp, "rendered": True, "console_errors": 0,
         "a11y": {"critical": 0, "serious": 0}, "overflow": False, "touch_target_violations": 0, "acs": [],
         "interactions": [], "screenshot": f"shots/{state}-{vp}.png"}
    r.update(kw)
    return r


def scenario(d: Path, mode: str = "ok", results_=None, **kw) -> None:
    w(d, "tools/browser-scenario.json", json.dumps({"mode": mode, "results": results_ or [], **kw}, ensure_ascii=False))


def tests_file(d: Path, lines: list[str]) -> None:
    w(d, "web/src/features/seats/seats.test.view", "\n".join(lines) + "\n")


def st(d: Path) -> dict:
    return json.loads((d / ".ai-workflow/build.json").read_text())


def start(d, bid):
    code, out = pb(d, "batch-start", "--batch", bid, "--owner", "t")
    assert code == 0, out
    return out["lock_id"]


def finish(d, bid, lock):
    for t in [x for x, v in st(d)["batches"][bid]["run"]["tasks"].items() if v["status"] != "done"]:
        code, out = pb(d, "task-done", "--batch", bid, "--task", t, "--lock", lock)
        assert code == 0, out
    code, out = pb(d, "batch-submit", "--batch", bid, "--lock", lock)
    assert code == 0, out


def verify(d, bid="B1", avail=True):
    return pb(d, "verify", "--batch", bid, *(("--available", "browser") if avail else ()))


def reasons(out) -> str:
    return " / ".join(out.get("reasons") or []) or out.get("message", "") or str(out)[:300]


# ---------------------------------------------------------------- 단위 검사(브라우저·Node 없이)
def unit_checks(root: Path) -> None:
    check("U1 상태 태그: [SCR-001-ST2], 묶음 [SCR-001-ST1, SCR-001-ST3], 명시 필드, prefix 머리",
          UV.state_tags("[SCR-001-ST2] 로딩", None, "bracket") == ["SCR-001-ST2"]
          and UV.state_tags("[SCR-001-ST1, SCR-001-ST3] x", None, "bracket") == ["SCR-001-ST1", "SCR-001-ST3"]
          and UV.state_tags("x", ["SCR-002-ST1", "bad"], "bracket") == ["SCR-002-ST1"]
          and UV.state_tags("SCR-001-ST2 / AC-001: 로딩", None, "prefix") == ["SCR-001-ST2"]
          and UV.state_tags("SCR-001-ST2 언급만", None, "bracket") == [])
    jd = root / "junit"
    jd.mkdir()
    (jd / "r.xml").write_text('<testsuite><testcase classname="a" name="[AC-001] 표시"><properties><property name="state" value="SCR-001-ST1"/>'
                              '</properties></testcase></testsuite>')
    cs = V.parse_report(jd / "r.xml", "junit-xml", "bracket")
    check("U2 JUnit property state → 상태 태그, AC 태그는 그대로", cs[0]["states"] == ["SCR-001-ST1"] and cs[0]["acs"] == ["AC-001"], cs)

    rd = root / "rep"
    (rd / "shots").mkdir(parents=True)
    (rd / "shots/a.png").write_bytes(b"x")

    def parse(body, run_id="RUN"):
        (rd / "ui.json").write_text(json.dumps(body) if not isinstance(body, str) else body)
        try:
            return UV.parse_ui_report(rd / "ui.json", run_id, rd)
        except UV.UIReportError as e:
            return str(e)

    base = {"format": "pb-ui-report/v1", "run_id": "RUN", "status": "completed"}
    ok = parse({**base, "results": [res("SCR-001-ST1", screenshot="shots/a.png", acs=["AC-001"],
                                        interactions=[{"name": "좌석 선택", "passed": True}])]})
    check("U3 정상 결과 → 통과 케이스(상태·AC·스크린샷 해시 연결)", isinstance(ok, dict) and ok["cases"][0]["status"] == "passed"
          and ok["cases"][0]["states"] == ["SCR-001-ST1"] and ok["cases"][0]["acs"] == ["AC-001"] and ok["results"][0]["screenshot"]["sha256"], ok)
    blk = parse({**base, "results": [res("SCR-001-ST1", screenshot=None, rendered=False), res("SCR-001-ST2", screenshot=None, console_errors=["TypeError"]),
                                     res("SCR-001-ST3", screenshot=None, a11y={"critical": 1}),
                                     res("SCR-002-ST1", screenshot=None, interactions=[{"name": "예약 확정", "passed": False}])]})
    check("U4 차단 4종: 렌더 실패·콘솔 오류·critical 접근성·핵심 상호작용 실패",
          isinstance(blk, dict) and [r["blocking"] for r in blk["results"]] ==
          [["render_failed"], ["console_errors:1"], ["a11y_critical:1"], ["interaction_failed:예약 확정"]]
          and all(c["status"] == "failed" for c in blk["cases"]), blk)
    rep_ = parse({**base, "results": [res("SCR-001-ST1", screenshot=None, a11y={"critical": 0, "serious": 2}, overflow=True, touch_target_violations=1,
                                          interactions=[{"name": "툴팁", "passed": False, "core": False}])]})
    check("U5 보고만(차단 아님): serious 접근성·넘침·터치 영역·핵심 아닌 상호작용 실패",
          isinstance(rep_, dict) and rep_["cases"][0]["status"] == "passed" and set(rep_["results"][0]["warnings"]) ==
          {"a11y_serious:2", "overflow", "touch_target:1", "interaction_failed:툴팁"}, rep_)
    shot_only = parse({**base, "results": [{"screen": "SCR-001", "state": "SCR-001-ST1", "viewport": "mobile", "screenshot": "shots/a.png"}]})
    check("U6 스크린샷만 있는 결과는 검증 결과가 아님(리포트 거부)", isinstance(shot_only, str) and "스크린샷만" in shot_only, shot_only)
    check("U7 run_id가 이번 실행과 다르면 거부(오래된 결과)", "run_id" in str(parse({**base, "run_id": "OLD", "results": [res("SCR-001-ST1", screenshot=None)]})))
    check("U8 잘못된 JSON·다른 형식·빈 결과 거부", "JSON" in str(parse("{bad")) and "형식" in str(parse({"format": "x"}))
          and "비어" in str(parse({**base, "results": []})))
    check("U9 스크린샷 경로가 리포트 폴더 밖·없는 파일이면 거부", "상대 경로" in str(parse({**base, "results": [res("SCR-001-ST1", screenshot="../x.png")]}))
          and "없습니다" in str(parse({**base, "results": [res("SCR-001-ST1", screenshot="shots/none.png")]})))
    check("U10 상태 ID가 화면과 맞지 않으면 거부", "형식" in str(parse({**base, "results": [res("SCR-001-ST1", screen="SCR-002", screenshot=None)]})))
    nr = parse({**base, "status": "not_run", "reason": "브라우저 없음"})
    check("U11 도구가 not_run을 보고 → 미실행(결과 없음)", isinstance(nr, dict) and nr["status"] == "not_run" and nr["cases"] == [], nr)

    brief = {"screens": {"SCR-001": {"actions": [{"action": "좌석 선택"}], "states": [
        {"id": "SCR-001-ST1", "label": "기본", "defined": True, "required": True},
        {"id": "SCR-001-ST2", "label": "빈", "defined": True, "required": False}], "acs": []}}}
    steps = [{"name": "unit", "run": "x"}, {"name": "browser", "run": "y", "stage": "browser", "optional": True, "report": {"format": "pb-ui", "file": "u.json"}}]
    run_nr = {"run_id": "R", "at": "t", "valid": True, "steps": [{"name": "unit", "status": "passed", "cases": []},
                                                                 {"name": "browser", "status": "not_run", "optional": True, "reason": "필요한 환경 없음: browser"}]}
    bs = UV.browser_summary(run_nr, steps, brief, [])
    check("U12 선택 단계 미실행: not_run 기록, 최종 승인 차단 목록에는 없음(필수만 차단 대상)",
          bs["status"] == "not_run" and not bs["final_approval_blockers"] and bs["steps"]["browser"]["required"] is False, bs)
    steps_req = [dict(steps[0]), dict(steps[1], optional=False)]
    run_req = json.loads(json.dumps(run_nr))
    run_req["steps"][1]["optional"] = False
    bs2 = UV.browser_summary(run_req, steps_req, brief, [])
    check("U13 필수 단계 미실행: final_approval_blockers에 남김", bs2["status"] == "not_run" and bs2["final_approval_blockers"], bs2)
    bs3 = UV.browser_summary(run_nr, steps[:1], brief, [])
    check("U14 브라우저 단계가 프로필에 없으면 not_configured(경고)", bs3["status"] == "not_configured" and bs3["warnings"], bs3)
    run_dn = {"run_id": "R", "at": "t", "valid": True, "steps": [{"name": "browser", "status": "passed", "optional": False, "ui_report": {"results": [
        {"screen": "SCR-001", "state": "SCR-001-ST1", "viewport": "tablet", "blocking": [], "warnings": [], "acs": [], "screenshot": None,
         "interactions": [{"name": "좌석 선택", "passed": True, "core": False}]}]}}]}
    bs4 = UV.browser_summary(run_dn, steps_req, brief, ["mobile"])
    check("U15 02 행동을 core=false로 낮추면 차단, 프로필에 없는 뷰포트는 경고",
          any("핵심 상호작용" in x for x in bs4["blocking"]) and any("browser.viewports" in x for x in bs4["warnings"]), bs4)

    prof = json.loads(json.dumps(C.DEFAULT_PROFILE))
    prof["verify"]["steps"] = [{"name": "b", "run": "x", "stage": "browser", "report": {"format": "pb-ui", "path": "out/ui.json"}}]
    p1 = C.profile_problems(prof)
    prof["verify"]["steps"] = [{"name": "b", "run": "x", "stage": "test", "report": {"format": "pb-ui", "file": "ui.json"}}]
    p2 = C.profile_problems(prof)
    prof["verify"]["steps"] = [{"name": "b", "run": "x", "stage": "browser", "report": {"format": "pb-ui", "file": "ui.json"}}]
    p3 = C.profile_problems(prof)
    check("U16 프로필: pb-ui는 고정 경로(path) 불가·stage는 browser/e2e만, 올바르면 통과", p1 and p2 and not p3, (p1, p2, p3))


# ---------------------------------------------------------------- 흐름(실제 verify 실행)
def setup(root: Path) -> Path:
    d = UT.make_ui_product(root, "lib-uiev")
    w(d, "web/src/components/Button.view", "// CMP-001\nexport function Button(props) { return render('button', props) }\n")
    w(d, "web/src/styles/tokens.css", ":root {\n  --color-bg: #FFFFFF;\n  --color-text: #1A1A1A;\n  --color-primary: #0E6B4F;\n"
      "  --space-unit: 4px;\n  --radius-md: 8px;\n}\n")
    w(d, "api/contract.txt", "GET /api/seats\nPOST /api/reservations\n")
    w(d, "tools/run_ui_tests.py", RUNNER)
    w(d, "web/src/components/Button.test.view", "case passed Button이 그려진다\n")
    w(d, "tools/fake_browser.py", FAKE_BROWSER)
    scenario(d, "ok", [res("SCR-001-ST1")])
    (d / ".gitignore").write_text("node_modules/\ntools/browser-scenario.json\n")  # 테스트가 바꾸는 대역 설정(작업 파일 아님)
    G(d, "add", "-A"); G(d, "commit", "-qm", "existing code")
    pb(d, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    UT.approve_plan(d, UT.plan_for(["CMP-002"], ["CMP-001", "CMP-002"]))
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-001", "--source", "existing", "--path", "web/src/components/Button.view",
                   "--export", "Button", "--note", "기존 Button을 재사용합니다")
    assert code == 0, out
    code, out = pb(d, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "이 파일을 토큰 출력으로 씁니다")
    assert code == 0, out
    return d


def flow(root: Path) -> None:
    d = setup(root)
    snap = T.protected_snapshot(d)

    # B0(UI Brief 없음): M2 판정 그대로
    lock = start(d, "B0")
    w(d, "web/src/components/SeatMap.view", "// CMP-002\nexport function SeatMap(p) { return p }\n")
    finish(d, "B0", lock)
    code, out = pb(d, "ui-map", "register", "--cmp", "CMP-002", "--source", "built", "--batch", "B0",
                   "--path", "web/src/components/SeatMap.view", "--export", "SeatMap")
    assert code == 0, out
    code, out = verify(d, "B0")
    check("F1 UI Brief를 만들지 않은 배치는 M2 판정 그대로(ui 판정 없음) → verified", code == 0 and out["status"] == "verified" and "ui" not in out
          and "ui" not in st(d)["batches"]["B0"]["verification"], reasons(out))

    # B1: Brief → UI Plan → 검증 → 구현
    code, out = pb(d, "ui-brief", "--batch", "B1")
    assert code == 0, out
    UT.write_ui_plan(d, UT.good_ui_plan(out["digest"]))
    code, out = pb(d, "ui-plan-validate", "--batch", "B1")
    check("F2 UI Plan 검증 통과(전제)", code == 0, out.get("errors"))
    brief = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text())
    req = sorted(x["id"] for sb in brief["screens"].values() for x in sb["states"] if x["required"])
    check("F3 Must 화면의 정의된 상태가 필수(required) 6개", req == STATES_ALL, req)

    lock = start(d, "B1")
    w(d, "web/src/features/seats/SeatStatusPage.view", "import { Button } from '../../components/Button.view'\nexport const SeatStatusPage = 1\n")
    w(d, "web/src/features/seats/ReserveConfirm.view", "export const ReserveConfirm = 1\n")
    w(d, "web/src/mocks/seats.data", "A1 free\n")
    tests_file(d, ["case passed [SCR-001-ST1] [AC-001] 빈 좌석이 보인다",
                   "case passed [AC-002] 빈 좌석이 없으면 대기 안내",
                   "case passed [AC-003] 좌석을 고르면 예약이 확정된다",
                   "case passed [AC-004] 중복 예약 거부",
                   "// SCR-001-ST3 오류 화면은 아직(언급만)"])
    finish(d, "B1", lock)

    # V1: 필수 상태 누락 + 브라우저 차단 결과 → 실패
    scenario(d, "ok", [res("SCR-001-ST1", acs=["AC-001"]), res("SCR-002-ST1", interactions=[{"name": "예약 확정", "passed": False}]),
                       res("SCR-002-ST2", console_errors=2)])
    code, out = verify(d)
    ui = out.get("ui") or {}
    s = ui.get("states") or {}
    check("V1 필수 상태 증거 부족 → verify_failed, 상태별 판정(E2·E1 언급·E0·실패)", code == 2 and out["status"] == "verify_failed"
          and s["SCR-001-ST1"]["status"] == "verified" and s["SCR-001-ST1"]["level"] == "E2"
          and s["SCR-001-ST3"]["status"] == "untested" and s["SCR-001-ST3"]["level"] == "E1"
          and s["SCR-001-ST2"]["level"] == "E0" and s["SCR-002-ST1"]["status"] == "failing" and s["SCR-002-ST2"]["status"] == "failing", s)
    check("V2 브라우저 차단(핵심 상호작용 실패·콘솔 오류)이 사유에 들어감, AC 판정은 M2 그대로",
          any("interaction_failed:예약 확정" in r for r in out["reasons"]) and any("console_errors:2" in r for r in out["reasons"])
          and out["acs"]["AC-002"]["status"] == "verified" and out["acs"]["AC-001"]["level"] == "E2", reasons(out))
    v = st(d)["batches"]["B1"]["verification"]["ui"]
    ev0 = v["states"]["SCR-001-ST1"]["evidence"]
    check("V3 증거 기록: 출처(test·browser)·실행 ID·시각·코드 버전·결과",
          {e["source"] for e in ev0} == {"test", "browser"} and all(e["run_id"] == v["code"]["run_id"] and e["at"] and e["code_tree"] and e["status"] == "passed" for e in ev0)
          and v["code"]["head"] and v["code"]["code_tree"], ev0)
    check("V4 AC ↔ 상태 연결 기록(05의 AC→상태, UI Plan acs)", "SCR-001-ST1" in (v["ac_links"].get("AC-001") or {}).get("states", {}), v["ac_links"])

    # EM: 사용자 문장 없으면 거부, 잘못된 대상 거부, 필수 상태 E2를 대신하지 않음
    code, out = pb(d, "evidence-manual", "add", "--batch", "B1", "--state", "SCR-002-ST3", "--check", "키보드로 409 오류 안내 확인",
                   "--method", "keyboard", "--result", "passed")
    check("M1 EM: 사용자 확인 문장 없으면 거부", code == 2 and out["error"] == "approval_statement_required", out)
    code, out = pb(d, "evidence-manual", "add", "--batch", "B1", "--state", "SCR-009-ST1", "--check", "x", "--method", "visual",
                   "--result", "passed", "--note", "확인했습니다")
    check("M2 EM: 이 배치에 정의되지 않은 상태는 거부", code == 2 and out["error"] == "unknown_state", out)
    w(d, ".ai-workflow/build/evidence/manual/scr-002-st3.png", "PNG")
    code, out = pb(d, "evidence-manual", "add", "--batch", "B1", "--state", "SCR-002-ST3", "--ac", "AC-003", "--check", "키보드로 409 오류 안내 확인",
                   "--method", "keyboard", "--result", "passed", "--file", ".ai-workflow/build/evidence/manual/scr-002-st3.png",
                   "--by", "검수자", "--note", "직접 키보드로 확인했습니다")
    check("M3 EM 기록: ID·스크린샷은 첨부일 뿐 E2 아님 안내", code == 0 and out["evidence"]["id"] == "EM-001"
          and out["evidence"]["files"][0]["kind"] == "screenshot" and "E2 근거가 아닙니다" in out["note"], out)
    em = st(d)["batches"]["B1"]["manual_evidence"][0]
    check("M4 EM 기록 내용: 사용자 문장·방법·대상·코드 버전·화면 입력 기준", em["statement"] and em["method"] == "keyboard"
          and em["code"]["scope_tree"] and em["code"]["head"] and set(em["basis"]) == {"SCR-002"}, em)

    # V5: 브라우저 미실행(도구가 not_run 보고) → 필수 단계라 실패(M2 규칙) + 최종 승인 차단 판정 남김
    scenario(d, "not_run", reason="Playwright가 설치되지 않음")
    code, out = verify(d)
    ui = out.get("ui") or {}
    check("V5 필수 브라우저 not_run: 단계 not_run, ui.browser not_run, final_approval_blockers 기록",
          code == 2 and out["run"]["steps"]["browser"]["status"] == "not_run" and ui["browser"]["status"] == "not_run"
          and any("not_run" in x for x in ui["browser"]["final_approval_blockers"])
          and any("Playwright" in x for x in ui["final_approval_blockers"]), ui.get("browser"))
    check("V6 EM만 있는 필수 상태는 manual_only(E2 대신 안 됨)", ui["states"]["SCR-002-ST3"]["status"] == "manual_only"
          and ui["states"]["SCR-002-ST3"]["level"] == "EM", ui["states"]["SCR-002-ST3"])
    code, out = verify(d, avail=False)
    check("V7 환경 없음(requires 미충족)도 not_run으로 기록", code == 2 and out["run"]["steps"]["browser"]["status"] == "not_run"
          and "browser" in (out["run"]["steps"]["browser"].get("reason") or ""), out["run"]["steps"].get("browser"))

    # 리포트 출처 문제: 실행 단계 단위(run_steps)로 확인(상태 변화 없음)
    prof, _ = C.load_profile(d)
    bstep = [s for s in prof["verify"]["steps"] if s["name"] == "browser"]
    for mode, want, label in (("bad_json", "report_invalid", "잘못된 JSON"), ("stale", "report_invalid", "다른 실행의 리포트(run_id)"),
                              ("noreport", "report_invalid", "실패하고 리포트 없음"), ("sleep", "timeout", "시간 초과")):
        scenario(d, mode, [res("SCR-001-ST1")])
        r = V.run_steps(d, prof, "B1", bstep, {"browser"}, 60)["steps"][0]
        check(f"R {label} → {want}", r["status"] == want, {k: r.get(k) for k in ("status", "reason", "exit")})
    scenario(d, "ok", [{"screen": "SCR-001", "state": "SCR-001-ST1", "viewport": "mobile", "screenshot": "shots/x.png"}])
    r = V.run_steps(d, prof, "B1", bstep, {"browser"}, 60)["steps"][0]
    check("R 스크린샷만 있는 결과 → report_invalid(증거 아님)", r["status"] == "report_invalid" and "스크린샷만" in r["reason"], r.get("reason"))

    # 성공: 모든 필수 상태 E2(테스트 태그 + 브라우저 결과), 보고 항목은 경고만
    code, out = pb(d, "resume", "--batch", "B1", "--owner", "t2")
    lock = out.get("lock_id")
    assert lock, out
    tests_file(d, ["case passed [SCR-001-ST1] [AC-001] 빈 좌석이 보인다",
                   "case passed [SCR-001-ST3] [AC-002] 오류 시 다시 시도 안내",
                   "case passed [AC-002] 빈 좌석이 없으면 대기 안내",
                   "case passed [SCR-002-ST1] [AC-003] 좌석을 고르면 예약이 확정된다",
                   "case passed [SCR-002-ST3] [AC-004] 중복 예약 거부(409)"])
    pb(d, "checkpoint", "--batch", "B1", "--lock", lock)
    code, out = pb(d, "batch-submit", "--batch", "B1", "--lock", lock)
    assert code == 0, out
    scenario(d, "ok", [res("SCR-001-ST1", acs=["AC-001"], interactions=[{"name": "좌석 선택", "passed": True}]),
                       res("SCR-001-ST2", a11y={"critical": 0, "serious": 1}), res("SCR-002-ST2", "desktop", overflow=True),
                       res("SCR-002-ST1", interactions=[{"name": "예약 확정", "passed": True, "acs": ["AC-003"]}])])
    code, out = verify(d)
    ui = out.get("ui") or {}
    check("S1 필수 상태 6개 모두 verified(E2) → 배치 verified", code == 0 and out["status"] == "verified"
          and all(ui["states"][x]["status"] == "verified" and ui["states"][x]["level"] == "E2" for x in STATES_ALL), reasons(out))
    check("S2 브라우저 passed, 보고 항목(serious·넘침)은 경고, 최종 승인 차단 없음", ui["browser"]["status"] == "passed"
          and not ui["final_approval_blockers"] and any("a11y_serious" in x for x in ui["warnings"]) and any("overflow" in x for x in ui["warnings"]), ui)
    check("S3 토큰 검사 결과가 UI 검증에 기록(일치)", ui["tokens"]["check"]["ok"] is True and ui["tokens"]["check"]["counts"]["matched"] == 5, ui["tokens"])
    check("S4 EM은 코드가 바뀌어 stale(재확인 필요)로 표시", pb(d, "evidence-manual", "list", "--batch", "B1")[1]["manual_evidence"]["B1"][0]["status_now"] == "stale")
    code, rep = pb(d, "ac-report", "--batch", "B1")
    check("S5 ac-report: AC 판정 그대로 + UI 요약·EM(AC 판정 미반영) 표시", code == 0 and rep["batches"]["B1"]["acs"]["AC-001"]["status"] == "verified"
          and rep["batches"]["B1"]["ui"]["states"]["verified"] == 6 and rep["batches"]["B1"]["manual"][0]["id"] == "EM-001", rep["batches"]["B1"].get("ui"))
    code, ue = pb(d, "ui-evidence", "--batch", "B1")
    check("S6 ui-evidence: 상태별 증거 출처·영향 없음", code == 0 and ue["affected_now"] == {"screens": [], "states": [], "tokens": False,
                                                                                    "ui_plan_components": False} and ue["freshness_problem"] is None, ue.get("affected_now"))

    # 무효화 1: 토큰 예외 추가·변경·삭제
    code, out = pb(d, "ui-map", "except", "--token", "radius.md", "--reason", "카드 모서리 6px 유지", "--note", "예외를 승인합니다")
    check("I1 토큰 예외 추가 → 그 기준으로 검증된 B1 무효 대상 안내", code == 0 and out["op"] == "add" and out["invalidated_batches"] == ["B1"], out)
    code, out = pb(d, "status")
    check("I2 status가 재검증 필요로 표시(토큰 기준 변경)", "토큰 기준" in str(out.get("needs_reverify", {}).get("B1")), out.get("needs_reverify"))
    pb(d, "check")
    check("I3 check가 stale로 기록", st(d)["batches"]["B1"]["status"] == "stale")
    code, out = pb(d, "ui-brief", "--batch", "B1")
    up = UT.good_ui_plan(out["digest"])
    UT.write_ui_plan(d, up)
    pb(d, "ui-plan-validate", "--batch", "B1")
    code, out = verify(d)
    check("I4 다시 검사 → verified", code == 0 and out["status"] == "verified", reasons(out))
    code, out = pb(d, "ui-map", "except", "--token", "radius.md", "--reason", "카드 모서리 7px로 변경", "--note", "변경을 승인합니다")
    code2, out2 = pb(d, "ui-map", "unexcept", "--token", "radius.md", "--note", "예외를 없앱니다")
    code3, out3 = pb(d, "ui-map", "unexcept", "--token", "radius.md", "--reason", "예외 불필요", "--note", "예외를 없앱니다")
    log = json.loads((d / "docs/build/ui-map.json").read_text())["exceptions"]["log"]
    check("I5 예외 변경·삭제도 무효화, 삭제에는 사유·사용자 문장 필수", out["op"] == "replace" and out["invalidated_batches"] == ["B1"]
          and code2 == 2 and out2["error"] == "approval_statement_required" and code3 == 0 and out3["op"] == "remove", (out, out2, out3))
    check("I6 예외 이력 유지: 추가·변경(이전 기록 포함)·삭제 모두 사유·사용자 문장과 함께",
          [x["op"] for x in log] == ["add", "replace", "remove"] and log[1]["previous"]["reason"] == "카드 모서리 6px 유지"
          and log[2]["previous"]["reason"] == "카드 모서리 7px로 변경" and all(x["note"] and x["reason"] for x in log), log)

    # 다시 맞춘 뒤: UI Plan 변경 → 영향 화면만 표시
    pb(d, "check")
    code, out = pb(d, "ui-brief", "--batch", "B1")
    up = UT.good_ui_plan(out["digest"])
    UT.write_ui_plan(d, up)
    pb(d, "ui-plan-validate", "--batch", "B1")
    code, out = verify(d)
    check("I7 재검증 → verified", code == 0 and out["status"] == "verified", reasons(out))
    up["screens"]["SCR-002"]["states"]["SCR-002-ST3"]["ref"] = "409 응답(문구 변경)"
    UT.write_ui_plan(d, up)
    code, ue = pb(d, "ui-evidence", "--batch", "B1")
    check("I8 UI Plan의 SCR-002 변경 → 영향 화면 SCR-002·그 상태만(SCR-001은 영향 없음)",
          ue["affected_now"]["screens"] == ["SCR-002"] and ue["affected_now"]["states"] == ["SCR-002-ST1", "SCR-002-ST2", "SCR-002-ST3"]
          and "SCR-002" in (ue["freshness_problem"] or ""), ue.get("affected_now"))
    code, out = pb(d, "approve", "batch", "--batch", "B1", "--note", "승인합니다")
    check("I9 영향받은 증거가 있으면 최종 승인 차단(verification_stale)", code == 2 and out["error"] == "verification_stale", out)
    code, out = verify(d)
    check("I10 UI Plan이 바뀐 뒤 재검증: 검증되지 않은 UI Plan이면 실패", code == 2 and any("ui_plan_not_validated" in r for r in out["reasons"]), reasons(out))
    pb(d, "ui-plan-validate", "--batch", "B1")
    code, out = verify(d)
    check("I11 UI Plan 재검증 후 verified", code == 0 and out["status"] == "verified", reasons(out))

    # EM: verified 배치에 추가 → 재검증 대상, 철회 기록
    code, out = pb(d, "evidence-manual", "add", "--batch", "B1", "--state", "SCR-001-ST2", "--check", "스크린리더로 로딩 안내 확인",
                   "--method", "screen_reader", "--result", "failed", "--note", "로딩 안내가 읽히지 않습니다")
    check("M5 verified 배치에 EM 추가 → stale(재검증)", code == 0 and out["status"] == "stale", out)
    code, out = verify(d)
    check("M6 수동 확인 실패(EM failed)는 테스트가 통과해도 그 상태를 failing으로", code == 2
          and out["ui"]["states"]["SCR-001-ST2"]["status"] == "failing", out.get("ui", {}).get("states", {}).get("SCR-001-ST2"))
    code, out = pb(d, "evidence-manual", "revoke", "--batch", "B1", "--id", "EM-002", "--reason", "잘못된 화면에서 확인", "--note", "철회합니다")
    code2, out2 = verify(d)
    em2 = st(d)["batches"]["B1"]["manual_evidence"][1]
    check("M7 EM 철회(사유·문장 기록, 기록은 남음) 후 재검증 verified", code == 0 and em2["revoked"]["reason"] and code2 == 0
          and out2["status"] == "verified", reasons(out2))

    # 토큰: 승인 값과 다르면 UI 검증 차단, 사유·사용자 문장이 있는 예외로 통과(예외 내역 기록)
    tp = d / "web/src/styles/tokens.css"
    tp.write_text(tp.read_text().replace("--radius-md: 8px", "--radius-md: 6px"))
    code, out = verify(d)
    check("T1 토큰 불일치(radius.md 6px≠8px) → verify 실패(token_mismatch)", code == 2 and any("token_mismatch" in r and "radius.md" in r for r in out["reasons"]),
          reasons(out))
    pb(d, "ui-map", "except", "--token", "radius.md", "--reason", "카드 모서리 6px 유지(브랜드 가이드)", "--note", "예외를 승인합니다")
    code, out = pb(d, "ui-brief", "--batch", "B1")
    up["brief_digest"] = out["digest"]
    UT.write_ui_plan(d, up)
    pb(d, "ui-plan-validate", "--batch", "B1")
    code, out = verify(d)
    tk = st(d)["batches"]["B1"]["verification"]["ui"]["tokens"]["check"]
    check("T2 예외 등록 후 verified, 예외 적용 항목은 사유와 함께 기록", code == 0 and tk["ok"] and tk["excepted"][0]["token"] == "radius.md"
          and tk["excepted"][0]["reason"].startswith("카드 모서리"), (reasons(out), tk))

    check("P1 승인 문서·state.yaml·design.json·프리뷰 불변", T.protected_snapshot(d) == snap)

    # 무효화 2: 승인된 화면 명세(02) 변경 → 영향 화면만(픽스처 문서이므로 여기서만 바꿉니다)
    p = d / "docs/design/02-screens.md"
    p.write_text(p.read_text().replace("| 예약 확정 | 확정 안내 후 내 예약 |", "| 예약 확정 | 확정 안내 후 내 예약 목록 |"))
    code, ue = pb(d, "ui-evidence", "--batch", "B1")
    check("I12 02의 SCR-002 변경 → SCR-002만 영향(재검증 대상)", ue["affected_now"]["screens"] == ["SCR-002"], ue.get("affected_now"))
    code, out = pb(d, "check")
    code2, out2 = verify(d)
    check("I13 승인된 디자인 입력 변경은 M2 규칙대로 계획 전체 outdated → 재검증·승인 불가",
          code == 2 and out["error"] == "plan_outdated" and code2 == 2 and out2["error"] == "plan_not_approved", (out.get("error"), out2.get("error")))


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-uiev-test-"))
    try:
        unit_checks(root)
        flow(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
