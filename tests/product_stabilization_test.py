#!/usr/bin/env python3
"""v1.0 안정화 회귀 테스트(P0·파일럿 차단 P1). 각 항목은 수정 전 실패하고 수정 후 통과해야 합니다.

- P0-1·P0-2 승인 자산 불변성: Design Direction 승인 스냅샷(자산 ID·SHA-256·권리 확인 근거), 승인 후 replace·confirm 차단,
  레지스트리 직접 수정(파일·해시·권리 위조) 차단, 스냅샷 없는 이전 승인 기록은 신뢰하지 않음
- P0-3 CSS 검사 누락: #id·*·:before로 시작하는 줄을 주석으로 오인하지 않음(압축·여러 줄 CSS, URL 경로, 후보 토큰)
- P1-1 reopen 이후 탐색 선택 stale: 상위 승인 기준(UX Spec revision·구조 지문)이 바뀌면 제출·채택·승인 차단, 다시 선택하면 해소
- P1-2 verify 검사 일치: 심볼릭 링크·대문자 확장자·프로젝트 확장자(ui-guard와 같은 판정)
- P1-4 Discovery 제출 스냅샷: submit --stage discovery, 제출 이후 변경 시 승인 거부, 스냅샷 없는 제출은 승인 거부
- P1-5 측정 명령 신뢰성: 사용자 확인 시 명령 지문 기록, 명령·스크립트가 바뀌면 재확인 전 실행 거부, 측정 기록에 실행 출처
모든 승인·선택은 이 테스트가 만든 임시 프로젝트 안의 시뮬레이션입니다.
실행: python3 tests/product_stabilization_test.py [--keep <폴더>]
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
import product_workflow_e2e_test as W  # noqa: E402  (E2E 단계 함수로 승인된 프로젝트를 만듦)

T, XT, DDT, BT = W.T, W.XT, W.DDT, W.BT
results: list[tuple[str, bool]] = []
NEW_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l16 16"/></svg>\n'


def check(name, cond, detail=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def quiet(*_a, **_k):
    return None


W.check = quiet  # 픽스처를 만드는 E2E 단계의 판정은 이 테스트 집계에 넣지 않음(단계 실패는 예외로 드러남)
pd, pb, ps = W.pd, W.pb, W.ps


def raw(d: Path) -> tuple[bytes, bytes, bytes]:
    f = lambda rel: (d / rel).read_bytes() if (d / rel).exists() else b""
    return f(".ai-workflow/state.yaml"), f(".ai-workflow/design.json"), f("design-profile/assets.json")


def errs(out) -> str:
    return json.dumps(out, ensure_ascii=False)


def build_projects(root: Path) -> tuple[Path, Path]:
    """approved: Design Direction·Preview·Build 계획까지 승인된 프로젝트. mid: Design Direction 작성 중(채택까지) 프로젝트."""
    out = root / "_out"
    out.mkdir()
    (root / "a").mkdir()
    d = W.stage_start(root / "a")
    W.stage_ux_planning(d, out)
    W.stage_ux_spec(d)
    info = W.stage_design_direction(d, root / "a", out)
    W.stage_dd_approve(d, info)
    pv = W.stage_preview(d)
    W.stage_build(d, pv)
    (root / "m").mkdir()
    m = W.stage_start(root / "m")
    W.stage_ux_planning(m, out)
    W.stage_ux_spec(m)
    minfo = W.stage_design_direction(m, root / "m", out)
    (m / "_vdc.md").write_text(minfo["vdc"])
    return d, m


def copy_project(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, symlinks=True)
    return dst


# ---------------------------------------------------------------- P0-1·P0-2
def p0_assets(approved: Path, mid: Path, root: Path) -> None:
    d = copy_project(approved, root / "p0a")
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    snap = (st["stages"]["design_direction"]["approved"] or {}).get("assets")
    check("P0-1a DD 승인 기록에 자산 스냅샷(ID·SHA-256·권리 확인 근거) 고정, 권리 미확인 자산(AST-002)은 없음",
          isinstance(snap, dict) and set(snap) >= {"AST-001"} and "AST-002" not in snap
          and snap["AST-001"]["sha256"] == T.sha(d / "design-profile/assets/AST-001.svg") and snap["AST-001"].get("rights", {}).get("license") == "own"
          and snap["AST-001"]["rights"].get("confirmed_at"), snap)
    (root / "new.svg").write_text(NEW_SVG)
    before = raw(d)
    code, out = pd(d, "explore-asset", "replace", "--id", "AST-001", "--file", str(root / "new.svg"), "--note", "교체(시뮬레이션)")
    code2, out2 = pd(d, "explore-asset", "confirm", "--id", "AST-002", "--license", "own", "--note", "확인(시뮬레이션)")
    check("P0-1b 승인 이후 자산 replace·confirm 차단(reopen·재승인 안내), 상태·레지스트리 불변",
          code == 2 and code2 == 2 and out.get("error") == "assets_locked_by_approval" and out2.get("error") == "assets_locked_by_approval"
          and "reopen" in out.get("message", "") and raw(d) == before, (out, out2))
    # 명령을 거치지 않은 직접 수정: 파일 교체 + 레지스트리 해시 위조
    (d / "design-profile/assets/AST-001.svg").write_text(NEW_SVG)
    reg = json.loads((d / "design-profile/assets.json").read_text())
    reg["assets"]["AST-001"]["sha256"] = T.sha(d / "design-profile/assets/AST-001.svg")
    (d / "design-profile/assets.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2))
    (d / "web/src/components/forged.svg").write_text(NEW_SVG)
    code, out = pb(d, "ui-guard", "--path", "web/src/components/forged.svg")
    e = " ".join(out.get("errors") or [])
    code2, out2 = pd(d, "check")
    probs = (out2.get("cross_verify") or {}).get("problems") or []
    check("P0-1c 승인 자산 파일·레지스트리 해시 직접 위조 → Build 차단(asset_unapproved), check가 승인 자산 변경 보고",
          code == 2 and "asset_unapproved" in e and "forged.svg" in e and code2 == 2
          and any(p["stage"] == "design_direction" and p["kind"] == "approved_asset_modified" for p in probs), (e[:400], probs))
    code, out = pb(d, "ui-brief", "--batch", "B1")
    br = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text()) if code == 0 else {}
    ids = {a["id"] for s in ((br.get("design_sources") or {}).get("screens") or {}).values() for a in s.get("assets", [])}
    check("P0-1d 위조된 자산은 UI Brief 근거가 되지 않음(Brief 거부 또는 공식 자산에서 빠짐)",
          (code == 2 and out.get("error")) or (code == 0 and "AST-001" not in ids), (code, out.get("error"), ids))

    # 이전 승인 기록(스냅샷 없음)은 신뢰하지 않음
    d2 = copy_project(approved, root / "p0legacy")
    st = json.loads((d2 / ".ai-workflow/design.json").read_text())
    st["stages"]["design_direction"]["approved"].pop("assets", None)
    (d2 / ".ai-workflow/design.json").write_text(json.dumps(st, ensure_ascii=False, indent=2))
    shutil.copyfile(d2 / "design-profile/assets/AST-001.svg", d2 / "web/src/components/legacy.svg")
    code, out = pb(d2, "ui-guard", "--path", "web/src/components/legacy.svg")
    e = " ".join(out.get("errors") or [])
    code2, out2 = pd(d2, "check")
    check("P0-1e 자산 스냅샷 없는 이전 승인 기록 → 자산을 공식으로 자동 신뢰하지 않음(재승인 안내), check 경고, 승인 상태는 그대로",
          code == 2 and "asset_unapproved" in e and "스냅샷" in e and "asset_snapshot_missing" in errs(out2)
          and json.loads((d2 / ".ai-workflow/design.json").read_text())["stages"]["design_direction"]["status"] == "approved", (e[:400], out2.get("warnings")))

    # P0-2 승인 전: 레지스트리 권리 위조(명령 없이 confirmed_by_user)로 VD 채택
    m = copy_project(mid, root / "p0b")
    vdc = (m / "_vdc.md").read_text()
    forged_vd = ("\n### VD-009: 히어로 일러스트\n- **결정**: 로그인 화면 히어로에 AST-002\n- **상태**: 승인\n- **근거**: 사용자 결정\n"
                 "- **관련**: SCR-001, AST-002\n- **토큰 밖 값**: 없음\n")
    DDT.write_07(m, 1, extra_vd=vdc.replace("- **상태**: 후보", "- **상태**: 승인") + forged_vd)
    code0, out0 = pd(m, "trace", "--stage", "design_direction")
    reg = json.loads((m / "design-profile/assets.json").read_text())
    reg["assets"]["AST-002"]["rights"] = {"license": "own", "confirmed_by_user": True, "statement": "직접 만든 그림", "at": "2026-11-18T00:00:00Z"}
    (m / "design-profile/assets.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2))
    code, out = pd(m, "trace", "--stage", "design_direction")
    e = XT.errs_of(out)
    check("P0-2a 레지스트리만 고친 권리 확인(상태 기록 없음) → trace 거부(asset_rights_unverified), 명령으로 확인한 AST-001·003은 통과",
          code0 == 2 and code == 2 and "AST-002" in e and "asset_rights_unverified" in e and "AST-001" not in e and "AST-003" not in e, e[:500])
    before = raw(m)
    T.done_all(m, [DDT.DD])
    code, out = pd(m, "submit", "--stage", "design_direction")
    check("P0-2b 위조 권리 자산을 쓴 VD로 제출 거부, 상태 불변(done 기록 외)", code == 2 and json.loads((m / ".ai-workflow/design.json").read_text())["stages"]["design_direction"]["status"] == "in_progress",
          out)


# ---------------------------------------------------------------- P0-3
def p0_css(approved: Path, root: Path) -> None:
    import pd_guard as GD
    d = copy_project(approved, root / "p0css")
    tp = d / "design-explore/V01/B/theme.json"
    th = json.loads(tp.read_text())
    th["tokens"]["color.brand.mint"] = "#3EB489"  # 탐색 후보 테마에만 있는 토큰
    tp.write_text(json.dumps(th, ensure_ascii=False))
    src = d / "web/src/features/member"
    src.mkdir(parents=True, exist_ok=True)
    files = {
        "a.css": "#hero{background:url(../design-explore/V01/A/x.png)}\n",
        "b.css": "#app{color:var(--color-brand-mint)}\n",
        "c.css": "*,:before{box-sizing:border-box}.x{background:url(/design-explore/V01/A/y.png)}",
        "d.css": ".y{\n  margin:0;\n}\n*{outline-color:var(--color-brand-mint)}\n",
        "e.ts": "/**\n * 문서 주석\n */\nimport s from '../design-explore/V01/A/styles.css';\n",
        "ok.css": "#app{color:var(--color-action-primary)}\n*{margin:0}\n:before{content:''}\n/* 참고: design-explore/V01 시안을 보고 새로 작성 */\n/*\n * design-explore/V02 메모\n */\n",
        "ok.ts": "// design-explore/는 참고만 했습니다\nexport const x = 1;\n",
    }
    for n, t in files.items():
        (src / n).write_text(t)
    got = {}
    for x in GD.findings(d, [f"web/src/features/member/{n}" for n in files]):
        got.setdefault(Path(x["file"]).name, set()).add(x["kind"])
    check("P0-3a #id로 시작하는 CSS의 탐색 경로 참조 → explore_reuse", "explore_reuse" in got.get("a.css", set()), got)
    check("P0-3b #id로 시작하는 CSS의 후보 토큰 → explore_token", "explore_token" in got.get("b.css", set()), got)
    check("P0-3c *,:before로 시작하는 압축 CSS의 URL 경로 → explore_reuse", "explore_reuse" in got.get("c.css", set()), got)
    check("P0-3d 여러 줄 CSS의 *{…} 규칙 후보 토큰 → explore_token", "explore_token" in got.get("d.css", set()), got)
    check("P0-3e 기존 차단 유지: 문서 주석 뒤 import 경로 → explore_reuse", "explore_reuse" in got.get("e.ts", set()), got)
    check("P0-3f 정상 CSS(#id·*·:before, 승인 토큰)와 실제 주석 속 경로는 오탐 없음", "ok.css" not in got and "ok.ts" not in got, got)
    code, out = pb(d, "ui-guard", "--path", "web/src/features/member/a.css", "--path", "web/src/features/member/ok.css")
    e = " ".join(out.get("errors") or [])
    check("P0-3g ui-guard도 같은 판정(a.css 차단, ok.css 통과)", code == 2 and "a.css" in e and "ok.css" not in e, e[:400])


# ---------------------------------------------------------------- P1-1
def p1_stale(approved: Path, root: Path) -> None:
    d = copy_project(approved, root / "p1stale")
    code, out = pd(d, "reopen", "--stage", "ux_spec", "--reason", "02 문구 수정(시뮬레이션)")
    assert code == 0, out
    T.write_spec(d, 2)
    XT.patch_spec_for_visual(d)
    T.done_all(d, T.SPEC)
    for args in (("checkpoint",), ("submit", "--stage", "ux_spec"), ("approve", "--stage", "ux_spec", "--revision", "2")):
        code, out = pd(d, *args)
        assert code == 0, (args, out)
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    dd = st["stages"]["design_direction"]["status"]
    if dd != "in_progress":
        code, out = pd(d, "begin", "--stage", "design_direction")
        assert code == 0, out
    p07 = d / DDT.DD
    p07.write_text(re.sub(r"^revision: \d+", "revision: 2", p07.read_text(), count=1, flags=re.M))
    code, out = pd(d, "done", "--path", DDT.DD)
    assert code == 0, out
    before = raw(d)
    code, out = pd(d, "submit", "--stage", "design_direction")
    check("P1-1a UX Spec 재승인(r2) 뒤 이전 기준(r1)의 시각 선택으로 Design Direction 제출 → exploration_choice_stale, 상태 불변",
          code == 2 and out.get("error") == "exploration_choice_stale" and raw(d) == before, out)
    code, out = pd(d, "explore-adopt", "--round", "V02")
    check("P1-1b stale 선택은 채택(explore-adopt)도 거부", code == 2 and out.get("error") == "exploration_choice_stale" and raw(d) == before, out)
    code, out = pd(d, "explore-status")
    check("P1-1c explore-status가 선택을 stale로 표시(사유: UX Spec revision)", "stale" in errs(out) and "ux_spec" in errs(out), errs(out)[:400])
    code, out = pd(d, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본을 r2 기준으로 다시 확인했어요(시뮬레이션)")
    code2, out2 = pd(d, "submit", "--stage", "design_direction")
    check("P1-1d 현재 승인 기준으로 시안을 재검증해 다시 선택하면 stale 해소(제출이 stale로 막히지 않음)",
          code == 0 and out2.get("error") != "exploration_choice_stale", (out, out2))


# ---------------------------------------------------------------- P1-2
def p1_verify(approved: Path, root: Path) -> None:
    sys.path.insert(1, str(W.ENGINE / "skills/product-build/scripts"))
    import product_build as PBM
    d = copy_project(approved, root / "p1verify")
    mem = d / "web/src/features/member"
    mem.mkdir(parents=True, exist_ok=True)
    os.symlink(os.path.relpath(d / "design-explore/V01/A/styles.css", mem), mem / "link.css")
    shutil.copyfile(d / "design-explore/V01/C/styles.css", mem / "Copy.CSS")
    shutil.copyfile(d / "design-explore/V01/C/index.html", mem / "page.VIEW")
    (mem / "ok.view").write_text("<main>로그인</main>\n")
    plan = json.loads((d / "docs/build/implementation-plan.json").read_text())
    b1 = next(b for b in plan["batches"] if b["id"] == "B1")
    fn = getattr(PBM, "batch_exploration_findings", None)
    got = {}
    if fn:
        for x in fn(d, b1, PBM.profile_or_block(d)):
            got.setdefault(Path(x["file"]).name, set()).add(x["kind"])
    check("P1-2a verify 범위 판정: 심볼릭 링크(explore_reuse)·대문자 확장자(.CSS)·프로젝트 확장자 대문자(.VIEW) 복사 차단, 정상 파일 통과",
          fn is not None and "explore_reuse" in got.get("link.css", set()) and "explore_copy" in got.get("Copy.CSS", set())
          and "explore_copy" in got.get("page.VIEW", set()) and "ok.view" not in got, got)
    code, out = pb(d, "ui-guard", "--path", "web/src/features/member/link.css", "--path", "web/src/features/member/Copy.CSS",
                   "--path", "web/src/features/member/page.VIEW", "--path", "web/src/features/member/ok.view")
    e = " ".join(out.get("errors") or [])
    check("P1-2b ui-guard도 같은 파일을 같은 종류로 차단(검사 일치)", code == 2 and all(n in e for n in ("link.css", "Copy.CSS", "page.VIEW")) and "ok.view" not in e, e[:500])


# ---------------------------------------------------------------- P1-4
def p1_discovery(root: Path) -> None:
    d = root / "disc"
    (d / ".ai-workflow").mkdir(parents=True)
    T.G(d, "init", "-q")
    shutil.copy(W.TEMPLATE, d / ".ai-workflow/state.yaml")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "init")
    ps(d, "event", "--stage", "discovery", "--event", "started", "--revision", "0")
    W.planning_doc(d, "01-discovery.md")
    code, out = ps(d, "event", "--stage", "discovery", "--event", "submitted", "--revision", "1")
    check("P1-4a discovery 제출은 event가 아니라 submit 명령으로만(use_submit)", code == 2 and out.get("error") == "use_submit", out)
    before = raw(d)
    code, out = ps(d, "submit", "--stage", "discovery", "--revision", "1")
    check("P1-4b submit에는 --confirm 필요, 상태 불변", code == 2 and out.get("error") == "confirmation_required" and raw(d) == before, out)
    code, out = ps(d, "submit", "--stage", "discovery", "--revision", "1", "--confirm", "--note", "Discovery r1 제출(시뮬레이션)")
    sy = (d / ".ai-workflow/state.yaml").read_text()
    check("P1-4c submit --stage discovery: awaiting_approval·revision 1·제출 스냅샷(01 해시)·history submitted", code == 0
          and re.search(r"  discovery:\n    status: awaiting_approval", sy) and re.search(r"  discovery:\n(?:.*\n)*?    submitted:[^\n]*\n      revision: 1", sy)
          and T.sha(d / "docs/planning/01-discovery.md") in sy, (out, sy[:600]))
    p = d / "docs/planning/01-discovery.md"
    o = p.read_text()
    p.write_text(o + "\n제출 이후 추가\n")
    before = raw(d)
    code, out = ps(d, "approve", "--stage", "discovery", "--revision", "1")
    check("P1-4d 제출 이후 01 변경 → 승인 거부(changed_since_submission), 상태 불변", code == 2 and out.get("error") == "changed_since_submission" and raw(d) == before, out)
    p.write_text(o)
    code, out = ps(d, "approve", "--stage", "discovery", "--revision", "1", "--note", "승인(시뮬레이션)")
    check("P1-4e 제출 시점 내용이면 승인(스냅샷과 일치 확인)", code == 0 and (out.get("verified_against_submission") or {}).get("submitted_revision") == 1, out)
    # 이전 방식(상태 직접 편집, 스냅샷 없음) 제출은 승인하지 않음
    e = root / "disc-legacy"
    (e / ".ai-workflow").mkdir(parents=True)
    T.G(e, "init", "-q")
    shutil.copy(W.TEMPLATE, e / ".ai-workflow/state.yaml")
    W.planning_doc(e, "01-discovery.md")
    W.edit_state(e, r"(  discovery:\n    status:) in_progress", r"\1 awaiting_approval")
    W.edit_state(e, r"(  discovery:\n.*?\n    revision:) 0", r"\1 1")
    before = raw(e)
    code, out = ps(e, "approve", "--stage", "discovery", "--revision", "1")
    check("P1-4f 스냅샷 없는 discovery 제출(직접 편집) → 승인 거부(submission_snapshot_missing, 재제출 안내), 상태 불변",
          code == 2 and out.get("error") == "submission_snapshot_missing" and raw(e) == before, out)
    code, out = ps(e, "check")
    check("P1-4g check: 스냅샷 없는 discovery 승인 대기는 보고(이미 승인된 기록은 그대로 인정)", "discovery" in errs(out) and "snapshot" in errs(out).lower(), out)


# ---------------------------------------------------------------- P1-5
def p1_measure(mid: Path, root: Path) -> None:
    m = copy_project(mid, root / "p1meas")
    st = json.loads((m / ".ai-workflow/design.json").read_text())
    conf = (st["config"]["exploration"] or {}).get("measure_confirmed") or {}
    check("P1-5a 사용자 확인 시 측정 명령 지문 기록(명령 SHA-256·프로젝트 안 스크립트 파일 해시·확인 문장)",
          conf.get("cmd_sha256") and "tools/fake_measure.py" in (conf.get("files") or {}) and conf.get("statement"), conf)
    runs = [x for r in st["exploration"]["visual"]["rounds"] for x in r.get("measurements") or [] if x.get("status") == "completed"]
    check("P1-5b 측정 기록에 실행 출처(확인된 명령 지문·리포트·명세 해시) 연결", runs and all((x.get("provenance") or {}).get("cmd_sha256") == conf.get("cmd_sha256")
                                                                         and (x.get("provenance") or {}).get("report_sha256") for x in runs), [x.get("provenance") for x in runs][:2])
    sp = m / "tools/fake_measure.py"
    sp.write_text(sp.read_text() + "\n# 변경\n")
    before = raw(m)
    code, out = pd(m, "explore-verify", "--round", "V01")
    check("P1-5c 측정 스크립트가 확인 이후 바뀜 → 실행하지 않고 거부(measure_cmd_unconfirmed), 상태 불변",
          code == 2 and out.get("error") == "measure_cmd_unconfirmed" and raw(m) == before, out)
    code, out = pd(m, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안(시뮬레이션)")
    check("P1-5d 바뀐 측정 명령으로는 이전 측정 결과도 선택 근거로 쓰지 않음(measurement_unconfirmed 계열 거부)",
          code == 2 and out.get("error") in ("measure_cmd_unconfirmed", "measurement_invalid", "measurement_pending"), out)
    code, out = pd(m, "explore-config", "--measure-cmd", f"{sys.executable} tools/fake_measure.py", "--confirm", "--note", "바뀐 어댑터를 검토했어요(시뮬레이션)")
    code2, out2 = pd(m, "explore-verify", "--round", "V01")
    check("P1-5e 사용자 재확인 뒤 측정 실행", code == 0 and out.get("changed") and code2 == 0 and out2.get("status") == "completed", (out, out2))
    st = json.loads((m / ".ai-workflow/design.json").read_text())
    st["config"]["exploration"]["measure_cmd"] = f"{sys.executable} tools/other.py"
    (m / ".ai-workflow/design.json").write_text(json.dumps(st, ensure_ascii=False, indent=2))
    (m / "tools/other.py").write_text(XT.FAKE_ADAPTER)
    before = raw(m)
    code, out = pd(m, "explore-verify", "--round", "V01")
    check("P1-5f 상태 파일에서 측정 명령을 직접 바꿈 → 실행 거부(measure_cmd_unconfirmed)", code == 2 and out.get("error") == "measure_cmd_unconfirmed" and raw(m) == before, out)
    st["config"]["exploration"]["measure_cmd"] = f"{sys.executable} tools/fake_measure.py"
    st["config"]["exploration"].pop("measure_confirmed", None)
    (m / ".ai-workflow/design.json").write_text(json.dumps(st, ensure_ascii=False, indent=2))
    code, out = pd(m, "explore-verify", "--round", "V01")
    check("P1-5g 지문 기록이 없는 이전 설정 → 재확인 전 실행 거부(자동 신뢰 안 함)", code == 2 and out.get("error") == "measure_cmd_unconfirmed", out)


# ---------------------------------------------------------------- 승인 문장(파일럿 전 정리)
def p1_approval_note(mid: Path, root: Path) -> None:
    """product_design approve는 사용자 승인 문장(--note)이 필수 — 엔진이 승인 기록 문장을 지어내지 않음."""
    m = copy_project(mid, root / "pnote")
    vdc = (m / "_vdc.md").read_text()
    DDT.write_07(m, 1, extra_vd=vdc.replace("- **상태**: 후보", "- **상태**: 승인"))
    T.done_all(m, [DDT.DD])
    T.G(m, "add", "-A")
    T.G(m, "commit", "-qm", "dd draft")
    code, out = pd(m, "submit", "--stage", "design_direction")
    assert code == 0, out
    hist0 = json.loads((m / ".ai-workflow/design.json").read_text())["history"]
    res = {}
    for name, extra in (("--note 없음", []), ("빈 문자열", ["--note", ""]), ("공백만", ["--note", "   "])):
        before = raw(m)
        c, o = T.pi_raw("approve", "--stage", "design_direction", "--revision", "1", *extra, "--project", str(m))
        res[name] = (c, o.get("error"), raw(m) == before)
    check("N1 approve에 --note가 없거나 비어 있으면 거부(approval_statement_required), 상태 파일 바이트 불변",
          all(v == (2, "approval_statement_required", True) for v in res.values()), res)
    c, o = T.pi_raw("approve", "--stage", "design_direction", "--revision", "1", "--note", "네, 이 방향으로 승인합니다(시뮬레이션)", "--project", str(m))
    st = json.loads((m / ".ai-workflow/design.json").read_text())
    last = [h for h in st["history"] if h["event"] == "approved" and h["stage"] == "design_direction"][-1:]
    check("N2 사용자 문장을 주면 승인, history에는 그 문장 그대로(엔진 기본 문장 없음)",
          c == 0 and st["stages"]["design_direction"]["status"] == "approved" and last and last[0]["note"] == "네, 이 방향으로 승인합니다(시뮬레이션)"
          and "사용자 명시적 승인" not in json.dumps(st["history"], ensure_ascii=False), (o.get("error"), last))
    check("N3 기존 승인 기록(이전 history 항목)은 그대로", st["history"][:len(hist0)] == hist0, len(hist0))


def main() -> int:
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="product-stabilization-"))
    if keep:
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
    try:
        approved, mid = build_projects(root)
        for name, fn, args in (("P0 자산", p0_assets, (approved, mid, root)), ("P0 CSS", p0_css, (approved, root)),
                               ("P1-1", p1_stale, (approved, root)), ("P1-2", p1_verify, (approved, root)),
                               ("P1-4", p1_discovery, (root,)), ("P1-5", p1_measure, (mid, root)),
                               ("승인 문장", p1_approval_note, (mid, root))):
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001 — 한 그룹의 예외가 다른 그룹 판정을 막지 않게
                check(f"{name} 그룹 실행 중 예외", False, f"{type(e).__name__}: {e}")
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
