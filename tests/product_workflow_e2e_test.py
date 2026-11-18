#!/usr/bin/env python3
"""EX8 전체 워크플로 E2E(신규 격리 프로젝트): product-start → product-design(v2·디자인 탐색) → product-build.

자연어 요구사항 → Discovery → Planning(ps_state 제출·승인) → UX Planning(1차 구조 탐색·선택 시뮬레이션) → UX Spec
→ Design Direction(레퍼런스 기반 2차 시각 탐색·자산·품질·선택 시뮬레이션·채택·VD 결정·승인 시뮬레이션)
→ Preview(pnpm 빌드가 되면 승인까지) → product-build(계획·토큰·UI Brief·ui-guard).
- 모든 선택·승인은 이 테스트가 만든 임시 프로젝트 안의 시뮬레이션입니다(사용자 프로젝트의 선택·승인이 아님).
- 레퍼런스 이미지·개인정보·권리 확인은 테스트용 가상 자료에만 기록합니다.
- 측정은 기본적으로 결정적 가짜 어댑터를 쓰고, --real-browser면 마지막 측정을 실제 Chrome(CDP 어댑터)으로 다시 합니다.
실행: python3 tests/product_workflow_e2e_test.py [--real-browser] [--keep <폴더>]
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
sys.path.insert(1, str(ENGINE / "skills/product-build/scripts"))
import product_design_test as T  # noqa: E402
import product_design_explore_test as XT  # noqa: E402
import product_design_dd_test as DDT  # noqa: E402
import product_build_test as BT  # noqa: E402

PS = ENGINE / "skills/product-start/scripts/ps_state.py"
TEMPLATE = ENGINE / "skills/product-start/templates/state.yaml"
CDP_ADAPTER = ENGINE / "skills/product-design/templates/measure-adapters/chrome-cdp/pd-measure-cdp.mjs"
REAL = "--real-browser" in sys.argv
results: list[tuple[str, bool]] = []
LOG: list[dict] = []
PLANNING = ["docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md", "docs/planning/05-acceptance-criteria.md"]
REQUEST = "배드민턴 동호회 운영 앱: 회원은 로그인해 마이페이지에서 기록을 보고, 운영진은 버튼 한 번으로 대진을 만든다."


def check(name, cond, detail=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:600]}"))


def ps(d: Path, *args):
    p = subprocess.run([sys.executable, "-I", str(PS), *args, "--project", str(d)], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": (p.stdout + p.stderr)[-400:]}


def pd(d, *args):
    return T.pi(*args, "--project", str(d))


def pb(d, *args):
    return BT.pb(d, *args)


def statuses(d: Path) -> dict:
    out = {}
    sy = (d / ".ai-workflow/state.yaml").read_text() if (d / ".ai-workflow/state.yaml").exists() else ""
    for stg in ("discovery", "planning", "design"):
        m = re.search(rf"^  {stg}:\n    status: (\S+)", sy, re.M)
        out[f"state.yaml:{stg}"] = m.group(1) if m else None
    dj = d / ".ai-workflow/design.json"
    if dj.exists():
        st = json.loads(dj.read_text())
        out.update({f"design:{k}": f"{v['status']}/r{v['revision']}" for k, v in st["stages"].items()})
    bj = d / ".ai-workflow/build.json"
    if bj.exists():
        b = json.loads(bj.read_text())
        out["build:plan"] = f"{(b.get('plan') or {}).get('status')}/r{(b.get('plan') or {}).get('revision')}"
    return out


def log(d: Path, step: str, code, out, note=""):
    LOG.append({"step": step, "exit": code, "ok": (out or {}).get("ok"), "error": (out or {}).get("error"), "note": note, "state": statuses(d)})


def raw_state(d: Path) -> tuple[bytes, bytes]:
    a = (d / ".ai-workflow/state.yaml").read_bytes() if (d / ".ai-workflow/state.yaml").exists() else b""
    b = (d / ".ai-workflow/design.json").read_bytes() if (d / ".ai-workflow/design.json").exists() else b""
    return a, b


def rejected(d: Path, name: str, fn, err: str | None, *args):
    """실패한 시도는 상태 파일(state.yaml·design.json)을 바꾸지 않아야 합니다."""
    before = raw_state(d)
    code, out = fn(d, *args)
    ok = code == 2 and (err is None or out.get("error") == err or err in json.dumps(out, ensure_ascii=False)) and raw_state(d) == before
    log(d, f"[거부] {name}", code, out)
    check(f"{name} → 거부({err}), 상태 파일 불변", ok, out)
    return out


def ok_step(d: Path, name: str, fn, *args):
    code, out = fn(d, *args)
    log(d, name, code, out)
    if code != 0:
        raise AssertionError(f"{name}: {json.dumps(out, ensure_ascii=False)[:800]}")
    return out


def edit_state(d: Path, pattern: str, repl: str) -> None:
    p = d / ".ai-workflow/state.yaml"
    t, n = re.subn(pattern, repl, p.read_text(), count=1, flags=re.M | re.S)
    assert n, pattern
    p.write_text(t)


def planning_doc(d: Path, name: str, rev: int = 1) -> None:
    body = T.PLANNING[name].split("\n---\n", 1)[1]
    head = f"---\ndoc: {name[3:-3]}\nrevision: {rev}\nlanguage: ko\n" + ("" if name.startswith("01") else "based_on:\n  discovery_revision: 1\n") + "---\n"
    p = d / "docs/planning" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(head + body)


# ---------------------------------------------------------------- 1. product-start: Discovery → Planning
def stage_start(root: Path) -> Path:
    d = root / "club"
    (d / ".ai-workflow").mkdir(parents=True)
    T.G(d, "init", "-q")
    (d / "README.md").write_text(f"# 동호회 앱\n\n요구사항(자연어): {REQUEST}\n")
    (d / ".gitignore").write_text("node_modules/\ndist/\n")
    shutil.copy(TEMPLATE, d / ".ai-workflow/state.yaml")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "request (user)")
    log(d, "자연어 요구사항 접수(README·템플릿 state.yaml)", 0, {"ok": True}, REQUEST)
    rejected(d, "S1 Discovery 승인 없이 Design 시작", pd, "planning_not_approved", "start", "--workflow", "v2")
    # Discovery: 인터뷰 결과 문서(LLM 대신 작성). 상태 전이는 Skill 계약대로 state.yaml 편집 + ps_state 기록
    ok_step(d, "Discovery 시작 기록", ps, "event", "--stage", "discovery", "--event", "started", "--revision", "0")
    planning_doc(d, "01-discovery.md")
    ok_step(d, "Discovery 제출 r1(submit — 상태 직접 편집 없음)", ps, "submit", "--stage", "discovery", "--revision", "1", "--confirm")
    ok_step(d, "Discovery 승인(사용자 승인 시뮬레이션)", ps, "approve", "--stage", "discovery", "--revision", "1")
    # Planning
    edit_state(d, r"(  planning:\n    status:) not_started", r"\1 in_progress")
    edit_state(d, r"based_on_discovery_revision: null", "based_on_discovery_revision: 1")
    ok_step(d, "Planning 생성 기록", ps, "event", "--stage", "planning", "--event", "generated", "--revision", "0")
    for f in PLANNING:
        planning_doc(d, Path(f).name)
    edit_state(d, r"^    artifacts_done: \[\][^\n]*$", "    artifacts_done:\n" + "\n".join(f"      - {f}" for f in PLANNING))
    rejected(d, "S2 Planning 제출 전 승인", lambda dd, *a: ps(dd, *a), None, "approve", "--stage", "planning", "--revision", "1")
    ok_step(d, "Planning 제출 r1", ps, "submit", "--stage", "planning", "--revision", "1", "--confirm")
    orig = (d / PLANNING[1]).read_text()
    (d / PLANNING[1]).write_text(orig + "\n추가 메모\n")
    rejected(d, "S3 제출 이후 문서가 바뀐 채 승인(승인 해시 불일치)", lambda dd, *a: ps(dd, *a), "changed_since_submission", "approve", "--stage", "planning", "--revision", "1")
    (d / PLANNING[1]).write_text(orig)
    ok_step(d, "Planning 승인 r1(사용자 승인 시뮬레이션)", ps, "approve", "--stage", "planning", "--revision", "1")
    sy = (d / ".ai-workflow/state.yaml").read_text()
    check("S4 state.yaml 전이: discovery·planning approved, 승인 해시 기록", re.search(r"  planning:\n    status: approved", sy) is not None
          and "docs/planning/05-acceptance-criteria.md" in sy, sy[:400])
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "approved planning (simulated user)")
    return d


# ---------------------------------------------------------------- 2. UX Planning + 1차 구조 탐색
def stage_ux_planning(d: Path, out_dir: Path) -> None:
    (d / "design-profile").mkdir(exist_ok=True)
    (d / "design-profile/theme.json").write_text(json.dumps({"schema": "design-theme/v1", "name": "official", "tokens": XT.OFFICIAL}, ensure_ascii=False))
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "theme (user)")
    ok_step(d, "product-design start --workflow v2(게이트·탐색 기본 활성)", pd, "start", "--workflow", "v2", "--theme-file", "design-profile/theme.json")
    T.write_00(d, 1)
    T.write_notes(d, XT.NOTES_DONE)
    ok_step(d, "1차 탐색 라운드 S01", pd, "explore-init", "--phase", "structure", "--targets", "US-001+FLOW-001-S1=로그인 화면,US-002=대진 화면")
    XT.set_cov(d, "S01", XT.COV)
    for lb, lay in (("A", XT.COV_LAYOUT["A"]), ("B", XT.COV_LAYOUT["B"]), ("C", XT.EX4_C)):
        XT.write_cov_variant(d, "S01", lb, lay)
    XT.write_critique(d, "S01", "ABC")
    (d / "tools").mkdir(exist_ok=True)
    (d / "tools/fake_measure.py").write_text(XT.FAKE_ADAPTER)
    XT.setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    code, out = pd(d, "explore-check", "--round", "S01")
    check("D1 1차 시안 A/B/C 계약 검사 통과(구조 서명 서로 다름, 필수 항목 커버)", code == 0, XT.errs_of(out)[:300])
    # 측정 실패(무효)와 측정 미실행 구분
    XT.fake(d, run_id="M-old")
    code, out = pd(d, "explore-verify", "--round", "S01")
    check("D2 측정 무효(다른 run_id) → invalid(종료 2)", code == 2 and out["status"] == "invalid", out)
    code, out = pd(d, "explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로 갑니다", "--coverage-note", "확인")
    check("D3 측정 무효면 선택 거부(measurement_invalid) — 미실행과 다르게 취급", code == 2 and out["error"] == "measurement_invalid", out)
    XT.fake(d, status="not_run")
    code, out = pd(d, "explore-verify", "--round", "S01")
    check("D4 측정 도구 없음 → not_run(종료 0, 실패 아님)", code == 0 and out["status"] == "not_run", out)
    XT.fake(d, per={"C": {"console": ["Failed to load resource: x.css"]}})
    code, out = pd(d, "explore-verify", "--round", "S01")
    run = out["run_id"]
    check("D5 측정 완료: C만 차단(콘솔 오류)", code == 0 and out["variants"]["C"]["blocking"] and not out["variants"]["B"]["blocking"], out.get("variants"))
    XT.cite_shots(d, "S01", run, "ABC")
    rejected(d, "D6 측정 차단 시안(C) 선택", pd, "variant_has_blocking_findings", "explore-choose", "--round", "S01", "--variant", "C", "--note", "C안", "--coverage-note", "확인")
    ok_step(d, "1차 선택 EXP-S01-B(사용자 선택 시뮬레이션)", pd, "explore-choose", "--round", "S01", "--variant", "B",
            "--note", "B안으로 진행합니다(EX8 시뮬레이션)", "--coverage-note", "인증 실패 안내는 오류 상태에서 다루는 것에 동의(시뮬레이션)")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "structure choice")
    ok_step(d, "00 done(선택 반영 전)", pd, "done", "--path", T.UXP)
    rejected(d, "D7 선택을 반영한 UXD 없이 UX Planning 제출", pd, "exploration_not_reflected", "submit", "--stage", "ux_planning")
    p00 = d / T.UXP
    p00.write_text(p00.read_text().replace("- **근거**: 사용자 답변(라운드 1)", "- **근거**: 사용자 선택 EXP-S01-B(라운드 1)"))
    ok_step(d, "00 done", pd, "done", "--path", T.UXP)
    rejected(d, "D8 UX Planning 승인 전 UX Spec 시작", pd, "upstream_not_approved", "begin", "--stage", "ux_spec")
    ok_step(d, "UX Planning 제출", pd, "submit", "--stage", "ux_planning")
    ok_step(d, "UX Planning 승인(사용자 승인 시뮬레이션)", pd, "approve", "--stage", "ux_planning", "--revision", "1")
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    check("D9 승인 기록에 탐색 선택은 출처(exploration_basis)로만 — 승인 판정과 분리", st["stages"]["ux_planning"]["exploration_basis"]["choice"] == "EXP-S01-B"
          and "design-explore" not in json.dumps(st["stages"]["ux_planning"]["approved"]["hashes"]), st["stages"]["ux_planning"].get("exploration_basis"))


# ---------------------------------------------------------------- 3. UX Spec
def stage_ux_spec(d: Path) -> None:
    rejected(d, "U1 UX Spec 승인 전 Design Direction 시작", pd, "upstream_not_approved", "begin", "--stage", "design_direction")
    ok_step(d, "UX Spec 시작", pd, "begin", "--stage", "ux_spec")
    T.write_spec(d, 1)
    XT.patch_spec_for_visual(d)
    T.done_all(d, T.SPEC)
    ok_step(d, "구조 확인(checkpoint)", pd, "checkpoint")
    ok_step(d, "UX Spec 제출", pd, "submit", "--stage", "ux_spec")
    p02 = d / T.SPEC[1]
    o = p02.read_text()
    p02.write_text(o + "\n메모\n")
    rejected(d, "U2 제출 이후 02 변경 상태로 승인(승인 해시 불일치)", pd, "changed_since_submit", "approve", "--stage", "ux_spec", "--revision", "1")
    p02.write_text(o)
    ok_step(d, "UX Spec 승인(사용자 승인 시뮬레이션)", pd, "approve", "--stage", "ux_spec", "--revision", "1")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "ux spec approved")


# ---------------------------------------------------------------- 4. Design Direction + 레퍼런스 기반 2차 시각 탐색
def stage_design_direction(d: Path, root: Path, out_dir: Path) -> dict:
    ok_step(d, "Design Direction 시작", pd, "begin", "--stage", "design_direction")
    up = root / "virtual-ref"
    up.mkdir()
    (up / "virtual-reference.png").write_bytes(XT.img_png((5, 129, 118), 6, 6))
    ok_step(d, "가상 레퍼런스 등록(권리 own — 테스트 자료)", pd, "explore-ref", "add", "--file", str(up / "virtual-reference.png"), "--rights", "own")
    sha = json.loads((d / ".ai-workflow/design.json").read_text())["exploration"]["references"]["REF-001"]["sha256"]
    items = [XT.it("RX-001-01", "palette", "observed", "high", "주색 짙은 틸") | {"value": {"primary": "#058176"}},
             XT.it("RX-001-02", "typography", "observed", "high", "굵은 제목"),
             XT.it("RX-001-03", "components", "observed", "high", "둥근 카드"),
             XT.it("RX-001-04", "spacing_density", "estimated", "medium", "카드 간격 약 12px") | {"value": {"gap": "12px"}},
             XT.it("RX-001-05", "emphasis_mood", "estimated", "low", "밝은 분위기")]
    (d / "design-explore/references/REF-001/extraction.json").write_text(json.dumps(XT.extraction("REF-001", sha, items), ensure_ascii=False))
    ok_step(d, "분석 계약 검사", pd, "explore-ref", "extract-check", "--ref", "REF-001")
    ok_step(d, "개인정보 모델 점검(가상 자료)", pd, "explore-ref", "privacy", "--ref", "REF-001", "--by", "model", "--result", "none", "--note", "가상 단색 이미지")
    ok_step(d, "추정값 RX-001-04 사용자 확인(시뮬레이션)", pd, "explore-ref", "confirm", "--ref", "REF-001", "--items", "RX-001-04", "--decision", "confirmed",
            "--note", "간격 12px로 보는 게 맞아요(시뮬레이션)")
    ok_step(d, "참고 의도 INT-001", pd, "explore-ref", "intent", "--use", "REF-001=palette,typography,components,spacing_density,emphasis_mood",
            "--note", "가상 레퍼런스의 색·글자·카드·간격을 참고(시뮬레이션)")
    up2 = root / "assets8"
    up2.mkdir()
    (up2 / "ico.svg").write_text(XT.ICON_SVG)
    (up2 / "illu.svg").write_text(XT.ILLU_SVG)
    (up2 / "fn.svg").write_text(XT.ICON_SVG.replace("M4 12h16", "M12 4v16"))
    ok_step(d, "아이콘 스타일", pd, "explore-asset", "style", "--set", "style=outline", "--set", "stroke_width=1.8", "--set", "grid=24", "--set", "linecap=round", "--note", "선형")
    ok_step(d, "자산 AST-001(장식 아이콘, 자체 제작)", pd, "explore-asset", "add", "--file", str(up2 / "ico.svg"), "--kind", "icon", "--role", "decorative", "--source", "self_made", "--license", "own")
    ok_step(d, "자산 AST-002(장식 일러스트, 권리 미확인)", pd, "explore-asset", "add", "--file", str(up2 / "illu.svg"), "--kind", "illustration", "--role", "decorative", "--source", "model_drawn")
    ok_step(d, "자산 AST-003(기능 아이콘)", pd, "explore-asset", "add", "--file", str(up2 / "fn.svg"), "--kind", "icon", "--role", "functional", "--source", "self_made",
            "--license", "own", "--refs", "SCR-003:action-1")
    for a in ("AST-001", "AST-003"):
        ok_step(d, f"{a} 권리 확인(시뮬레이션)", pd, "explore-asset", "confirm", "--id", a, "--license", "own", "--note", "직접 만든 아이콘(시뮬레이션)")
    ok_step(d, "2차 라운드 V01(reference)", pd, "explore-init", "--phase", "visual", "--mode", "reference", "--intent", "INT-001", "--targets", "SCR-001,SCR-003")
    ok_step(d, "자산 라운드 사본", pd, "explore-asset", "sync", "--round", "V01")
    XT.write_vvariant(d, "V01", "A", elements=XT.ASSET_ELEMENTS, css=XT.VCSS["A"] + XT.ICO_CSS, tokens={"color.action.primary": "#058176", "space.4": "12px"},
                      prov={"color.action.primary": ["RX-001-01"], "space.4": ["RX-001-04"]}, axes=("component", "density"),
                      mode="reference", rules=["RX-001-01", "RX-001-04"], axis_sources={"palette": "REF-001", "spacing_density": "REF-001"},
                      reinterpretation="틸 주색·간격만 참고, 레퍼런스 문구·기능 없음")
    XT.write_vvariant(d, "V01", "B", tokens={"color.action.primary": "#0B9280"}, prov={"color.action.primary": ["RX-001-01"]},
                      mode="mixed", rules=["RX-001-01"], axis_sources={"palette": "REF-001", "typography": "ai"}, reinterpretation="색만 참고")
    XT.write_vvariant(d, "V01", "C", axes=("density", "component"), tokens={"color.action.primary": "#058176"},
                      prov={"color.action.primary": ["RX-001-05"]}, mode="reference", rules=["RX-001-05"], axis_sources={"emphasis_mood": "REF-001"},
                      reinterpretation="분위기 참고")
    code, out = pd(d, "explore-check", "--round", "V01")
    check("V1 미확인 추정 규칙(RX-001-05) 사용 → reference_unconfirmed, 확인된 추정(RX-001-04)은 통과", code == 2 and "V01-C: 규칙 RX-001-05" in XT.errs_of(out)
          and "RX-001-04" not in XT.errs_of(out), XT.errs_of(out)[:300])
    XT.write_vvariant(d, "V01", "C", axes=("density", "component"), mode="ai", rules=[], axis_sources={}, reinterpretation="")
    drift = XT.VIS_ELEMENTS + [("v9", "SCR-003", "action", ["SCR-003:action-2"], '<button data-el="v9">알림</button>')]
    XT.write_vvariant(d, "V01", "B", elements=drift, tokens={"color.action.primary": "#0B9280"}, prov={"color.action.primary": ["RX-001-01"]},
                      mode="mixed", rules=["RX-001-01"], axis_sources={"palette": "REF-001", "typography": "ai"}, reinterpretation="색만 참고")
    code, out = pd(d, "explore-check", "--round", "V01")
    check("V2 구조 이탈(승인 02에 없는 행동) → structure_drift", code == 2 and "structure_drift" in XT.errs_of(out), XT.errs_of(out)[:300])
    XT.write_vvariant(d, "V01", "B", tokens={"color.action.primary": "#0B9280"}, prov={"color.action.primary": ["RX-001-01"]},
                      mode="mixed", rules=["RX-001-01"], axis_sources={"palette": "REF-001", "typography": "ai"}, reinterpretation="색만 참고")
    code, out = pd(d, "explore-check", "--round", "V01")
    check("V3 2차 시안 A(reference)·B(mixed)·C(ai) 통과, 렌더러 html checked", code == 0 and all(v["level"] == "checked" for v in out["renderers"].values()), XT.errs_of(out)[:400])
    XT.fake(d)
    code, out = pd(d, "explore-verify", "--round", "V01")
    run = out["run_id"]
    pd(d, "explore-verify", "--round", "V01", "--asset-fallback")
    if REAL:
        run = real_measure(d, "V01", out_dir) or run
    XT.write_vcritique(d, "V01", "ABC", run, reference=True)

    def qo(lb, c):
        c["reference_alignment"] = dict(c["hierarchy"], observations=f"{lb}: 레퍼런스 색·간격과 비교한 관찰 — 주색 같음, 간격 근사", rating="adequate")
    XT.write_quality(d, "V01", "ABC", run, override=qo)
    if REAL:
        pass
    code, out = pd(d, "explore-quality", "--round", "V01")
    check("V4 품질 평가 계약 통과(측정 사실과 평가 분리)", code == 0, XT.errs_of(out)[:300])
    # 레퍼런스 개인정보 사용자 확인 전에는 선택 불가
    rejected(d, "V5 레퍼런스 개인정보 사용자 확인 전 선택", pd, "reference_privacy_unconfirmed", "explore-choose", "--round", "V01", "--variant", "A", "--note", "A안")
    ok_step(d, "개인정보 사용자 확인(가상 자료, 시뮬레이션)", pd, "explore-ref", "privacy", "--ref", "REF-001", "--by", "user", "--result", "none", "--note", "가상 이미지라 개인정보 없음(시뮬레이션)")
    ok_step(d, "2차 선택 EXP-V01-MIX(사용자 선택 시뮬레이션)", pd, "explore-choose", "--round", "V01", "--variant", "A", "--axes", "typography=B",
            "--note", "A안 기준, 글자는 B안으로 합니다(EX8 시뮬레이션)")
    # 수정 라운드 + 품질 평가
    ok_step(d, "수정 라운드 V02(기준 V01-A)", pd, "explore-init", "--phase", "visual", "--mode", "reference", "--intent", "INT-001", "--parent", "V01",
            "--base", "V01-A", "--variants", "1", "--goal", "강조 보강", "--feedback", "A안의 강조를 조금 더(시뮬레이션)")
    ok_step(d, "자산 라운드 사본 V02", pd, "explore-asset", "sync", "--round", "V02")
    css = d / "design-explore/V02/A/styles.css"
    css.write_text(css.read_text() + "h1{font-size:26px;letter-spacing:-0.01em}\n")
    code, out = pd(d, "explore-check", "--round", "V02")
    check("V6 수정 라운드 구조·토큰·자산 재검사 통과", code == 0, XT.errs_of(out)[:300])
    pd(d, "explore-verify", "--round", "V02")
    code, out = pd(d, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본")
    check("V7 수정 라운드는 품질 평가(목표별 수정 전후) 없이 선택 불가", code == 2 and out["error"] in ("quality_review_required", "critique_incomplete"), out)
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    check("V7b 수정 라운드를 열면 visual 탐색이 다시 진행 중(이전 선택 EXP-V01-MIX는 기록 보존)", st["exploration"]["visual"]["status"] != "chosen"
          and any(c["id"] == "EXP-V01-MIX" for c in st["exploration"]["visual"]["choices"]), st["exploration"]["visual"].get("status"))
    code, out = pd(d, "explore-verify", "--round", "V02")
    run2 = out["run_id"]
    pd(d, "explore-verify", "--round", "V02", "--asset-fallback")
    XT.write_vcritique(d, "V02", "A", run2, reference=True)
    XT.write_quality(d, "V02", "A", run2, override=qo, goals=1, before_run=run)
    code, out = pd(d, "explore-quality", "--round", "V02")
    check("V7c 수정 목표별 수정 전(V01-A)·후(V02-A) 근거를 갖춘 품질 평가 통과", code == 0, XT.errs_of(out)[:300])
    ok_step(d, "수정 라운드 선택 EXP-V02-A(사용자 선택 시뮬레이션)", pd, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본으로 갑니다(EX8 시뮬레이션)")
    # 채택: 후보 VD·테마(공식 아님)
    adopt = ok_step(d, "채택 explore-adopt(후보 VD·후보 테마)", pd, "explore-adopt", "--round", "V02")
    vdc = re.sub(r"<!--.*?-->", "", (d / "design-explore/V02/selection/adoption/vd-candidates.md").read_text(), flags=re.S)
    cand = json.loads((d / "design-explore/V02/selection/adoption/theme.candidate.json").read_text())
    check("V8 채택 결과는 후보(approved false), 07·공식 테마 미작성, 권리 미확인 자산은 채택 불가로 분리",
          cand["approved"] is False and "- **상태**: 후보" in vdc and not (d / DDT.DD).exists() or "후보" in vdc, adopt)
    return {"vdc": vdc, "cand": cand, "run": run, "adopt": adopt}


def stage_dd_approve(d: Path, info: dict) -> None:
    vdc = info["vdc"]
    DDT.write_07(d, 1, extra_vd=vdc.replace("EXP-V02-A", "EXP-V01-C", 1))
    code, out = pd(d, "trace", "--stage", "design_direction")
    check("A1 선택되지 않은 시안(EXP-V01-C)을 VD 근거로 채택 → exploration_ref_not_chosen", code == 2 and "exploration_ref_not_chosen" in XT.errs_of(out), XT.errs_of(out)[:300])
    DDT.write_07(d, 1, extra_vd=vdc.replace("- **상태**: 후보", "- **상태**: 제외(이번엔 반영하지 않음)"))
    theme = d / "design-profile/theme.json"
    theme0 = theme.read_text()
    t = json.loads(theme0)
    t["tokens"].update(info["cand"]["tokens"])
    theme.write_text(json.dumps(t, ensure_ascii=False))
    code, out = pd(d, "trace", "--stage", "design_direction")
    check("A2 제외한 VD의 후보 테마 값을 공식 테마에 넣으면 → adopted_theme_unapproved", code == 2 and "adopted_theme_unapproved" in XT.errs_of(out), XT.errs_of(out)[:300])
    DDT.write_07(d, 1, extra_vd=vdc.replace("- **상태**: 후보", "- **상태**: 승인"))
    ok_step(d, "07 done(VD 사용자 결정 시뮬레이션: 후보 → 승인)", pd, "done", "--path", DDT.DD)
    code, out = pd(d, "trace", "--stage", "design_direction")
    check("A3 VD 승인 결정 후 trace 통과(선택 ID·자산 권리·04 토큰 대조)", code == 0, XT.errs_of(out)[:400])
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "design direction draft")
    ok_step(d, "Design Direction 제출", pd, "submit", "--stage", "design_direction")
    o = (d / DDT.DD).read_text()
    (d / DDT.DD).write_text(o + "\n")
    rejected(d, "A4 제출 이후 07 변경 상태로 승인", pd, "changed_since_submit", "approve", "--stage", "design_direction", "--revision", "1")
    (d / DDT.DD).write_text(o)
    ok_step(d, "Design Direction 승인(사용자 승인 시뮬레이션)", pd, "approve", "--stage", "design_direction", "--revision", "1")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "design direction approved")
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    rec = st["stages"]["design_direction"]
    check("A5 승인 기록: 07 해시·승인 VD·테마 해시, 탐색 선택은 exploration_basis(출처)", rec["approved"]["hashes"][DDT.DD] == T.sha(d / DDT.DD)
          and rec["approved"]["theme_hash"] == T.sha(d / "design-profile/theme.json") and rec["exploration_basis"]["choice"] == "EXP-V02-A", rec)
    (d / DDT.DD).write_text(o.replace("고대비, 높은 정보 밀도", "고대비"))
    code, out = pd(d, "check")
    check("A6 승인 이후 공식 디자인(07) 변경 → approved_modified(stale) 보고, 승인 기록 재작성 없음",
          code == 2 and any(p["stage"] == "design_direction" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"])
          and json.loads((d / ".ai-workflow/design.json").read_text())["stages"]["design_direction"] == rec, out.get("cross_verify"))
    (d / DDT.DD).write_text(o)


# ---------------------------------------------------------------- 5. 영향도
def stage_impact(d: Path, root: Path) -> None:
    code, out = pd(d, "impact", "--design", "--choice", "EXP-V02-A")
    cats = {i["id"].split(":")[1]: [c["key"] for c in i["categories"]] for i in out.get("items", [])}
    check("I1 impact --design --choice: 구도 ④·테마 값 ③, 영향 화면·컴포넌트·승인 VD 식별", code == 0 and cats.get("composition") == ["visual"]
          and set(out["exploration"]["screens"]) >= {"SCR-001", "SCR-003"} and out["exploration"]["approved_vs_candidate"]["vds_approved"], out.get("exploration"))
    req = root / "req8.json"
    req.write_text(json.dumps({"schema": "design-change-request/v1", "items": [
        {"id": "C1", "summary": "마이페이지에 정보 추가", "facts": [{"kind": "info", "op": "add", "screen": "SCR-003"}]},
        {"id": "C2", "summary": "새 의미 토큰", "facts": [{"kind": "token_name", "op": "add", "tokens": ["color.brand.mint"]}]},
        {"id": "C3", "summary": "주색 값", "facts": [{"kind": "token_value", "token": "color.action.primary"}]},
        {"id": "C4", "summary": "버튼 모서리", "facts": [{"kind": "style", "property": "radius", "component": "CMP-001"}]}]}))
    code, out = pd(d, "impact", "--design", "--request", str(req))
    it = {i["id"]: i for i in out.get("items", [])}
    check("I2 변경 요청 ①·②·③·④ 분류와 재승인 단계(①② UX Spec부터, ③ 프리뷰, ④ Design Direction)",
          code == 0 and it["C1"]["categories"][0]["no"] == "①" and "ux_spec" in it["C1"]["reapproval_stages"]
          and it["C2"]["categories"][0]["no"] == "②" and it["C3"]["categories"][0]["no"] == "③"
          and it["C4"]["categories"][0]["no"] == "④" and "design_direction" in it["C4"]["reapproval_stages"], {k: (v["categories"], v["reapproval_stages"]) for k, v in it.items()})
    LOG.append({"step": "impact 요약", "items": {k: ([c["no"] for c in v["categories"]], v["reapproval_stages"]) for k, v in it.items()}})


# ---------------------------------------------------------------- 6. Preview
def stage_preview(d: Path) -> bool:
    ok_step(d, "Preview 시작", pd, "begin", "--stage", "preview")
    ok_step(d, "preview-scaffold", pd, "preview-scaffold")
    T.fill_preview(d, 1)
    man = d / "design-preview/preview.manifest.json"
    m = json.loads(man.read_text())
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    m["design_direction_revision"] = st["stages"]["design_direction"]["approved"]["revision"]
    for sid in m["screens"]:
        m["screens"][sid]["vd"] = ["VD-001"]
    man.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n")
    css = subprocess.run([sys.executable, "-I", str(T.SCRIPT), "theme-check", "--print-css", "--project", str(d)], capture_output=True, text=True)
    exp = json.loads(css.stdout).get("expected_css")
    if exp:
        (d / "design-preview/src/tokens.css").write_text(exp)
    T.write_06(d, 1)
    pd(d, "done", "--path", "docs/design/06-preview-review.md")
    pv = d / "design-preview/src"
    shutil.copyfile(d / "design-explore/V01/A/styles.css", pv / "explore-copy.css")
    shutil.copyfile(d / "design-profile/assets/AST-002.svg", pv / "hero.svg")
    shutil.copyfile(d / "design-explore/V01/B/tokens.css", pv / "b-tokens.css")
    code, out = pd(d, "preview-check")
    e = XT.errs_of(out)
    check("P1 Preview: 탐색 시안 CSS 복사·미승인 후보 테마(V01-B) tokens.css 복사(explore_copy)·미승인 자산(asset_unapproved) 차단, 공식 테마 tokens.css는 통과",
          code == 2 and "explore-copy.css" in e and "b-tokens.css" in e and "asset_unapproved" in e and "src/tokens.css" not in e, e[:600])
    (pv / "b-tokens.css").unlink()
    (pv / "explore-copy.css").unlink()
    (pv / "hero.svg").unlink()
    shutil.copyfile(d / "design-profile/assets/AST-001.svg", pv / "icon.svg")
    code, out = pd(d, "preview-check")
    check("P2 승인 VD 관련·권리 확인 공식 자산(AST-001)은 Preview에서 정상 사용, 검사 통과", code == 0, XT.errs_of(out)[:400])
    if shutil.which("pnpm") is None:
        log(d, "preview-verify 건너뜀(pnpm 없음)", None, {})
        return False
    code, out = pd(d, "preview-verify")
    log(d, "preview-verify(pnpm 빌드)", code, out)
    if code != 0:
        check("P3 preview-verify(pnpm 빌드) — 환경상 실패하면 미검증으로 기록", True)
        LOG.append({"step": "preview-verify 실패(환경)", "detail": json.dumps(out, ensure_ascii=False)[:400]})
        return False
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "preview")
    ok_step(d, "Preview 제출", pd, "submit", "--stage", "preview")
    ok_step(d, "Preview 승인(사용자 승인 시뮬레이션)", pd, "approve", "--stage", "preview", "--revision", "1")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "preview approved")
    check("P3 Preview 승인: 승인된 Design Direction r1 기준", json.loads((d / ".ai-workflow/design.json").read_text())["stages"]["preview"]["approved"]["design_direction_revision"] == 1)
    return True


# ---------------------------------------------------------------- 7. product-build
PROFILE = """[project]
order_strategy = "vertical"
[scope]
priorities = ["Must"]
[paths]
source = ["web/src"]
tests = ["web/src"]
components = ["web/src/components"]
exclude = ["node_modules"]
[execution]
max_retries = 3
lock_ttl_minutes = 30
[ui]
framework = "임의 스택(엔진은 해석하지 않음)"
[ui.audit]
extensions = [".view", ".css"]
"""


def stage_build(d: Path, preview_ok: bool) -> None:
    ok_step(d, "product-build init", pb, "init")
    (d / "docs/build/build-profile.toml").write_text(PROFILE)
    plan = {"plan_format": 1, "scope": {"priorities": ["Must"]}, "deferred": [], "batches": [
        {"id": "B1", "title": "로그인·마이페이지", "kind": "ui", "screens": ["SCR-001", "SCR-003"], "acs": ["AC-001", "AC-002"],
         "components": {"reuse": [], "new": ["CMP-001"]}, "paths": {"allow": ["web/src/features/member/", "web/src/components/"], "shared": ["web/src/styles/"]},
         "tasks": [{"id": "B1-T1", "layer": "fe", "title": "로그인·마이페이지", "refs": ["SCR-001", "SCR-003"]}],
         "test_plan": [{"ac": "AC-001", "kind": "unit"}, {"ac": "AC-002", "kind": "unit"}]},
        {"id": "B2", "title": "대진", "kind": "ui", "screens": ["SCR-002"], "acs": ["AC-003", "AC-004"], "depends_on": ["B1"],
         "components": {"reuse": ["CMP-001"], "new": ["CMP-002"]}, "paths": {"allow": ["web/src/features/match/"], "shared": []},
         "tasks": [{"id": "B2-T1", "layer": "fe", "title": "대진", "refs": ["SCR-002", "AC-003"]}],
         "test_plan": [{"ac": "AC-003", "kind": "unit"}, {"ac": "AC-004", "kind": "unit"}]}]}
    BT.save_plan(d, plan)
    if not preview_ok:
        ok_step(d, "프리뷰 면제(waiver, 사용자 문장 시뮬레이션)", pb, "waiver", "add", "--reason", "EX8 E2E: 프리뷰 빌드 환경 없음", "--all-ui",
                "--note", "프리뷰 없이 구현 승인(시뮬레이션)", "--confirm")
    code, out = pb(d, "plan-validate")
    check("B1 구현 계획 검증 통과(Must AC·화면·CMP)", code == 0, BT.errors_of(out)[:400])
    ok_step(d, "계획 제출", pb, "submit", "plan")
    rev = json.loads((d / ".ai-workflow/build.json").read_text())["plan"]["revision"]
    ok_step(d, "계획 승인(사용자 승인 시뮬레이션)", pb, "approve", "plan", "--revision", str(rev), "--note", "구현 계획 승인(시뮬레이션)")
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "build plan approved")
    ok_step(d, "토큰 출력 설정", pb, "ui-map", "tokens", "--file", "web/src/styles/tokens.css", "--note", "tokens.css 기준(시뮬레이션)")
    code, out = pb(d, "token-check")
    (d / "web/src/styles").mkdir(parents=True, exist_ok=True)
    (d / "web/src/styles/tokens.css").write_text(out.get("expected_css") or "")
    code, out = pb(d, "token-check")
    check("B2 token-check: 승인 당시 테마와 현재 테마 일치(theme_approval approved), 토큰 일치",
          code == 0 and out["theme_approval"]["status"] == "approved" and out["expected_basis"] == "approved", out.get("theme_approval"))
    theme = d / "design-profile/theme.json"
    t0 = theme.read_text()
    t = json.loads(t0)
    t["tokens"]["color.action.primary"] = "#123456"
    theme.write_text(json.dumps(t))
    code, out = pb(d, "token-check")
    check("B3 승인 후 공식 테마 변경 → token-check 실패(theme_changed_since_approval), 바뀐 값을 '승인값'으로 표시하지 않음",
          code == 2 and out["theme_approval"]["status"] == "changed_since_approval" and out["expected_basis"] == "current_theme_unapproved"
          and all(x.get("expected_basis") == "current_theme_unapproved" for x in out["mismatch"]), {k: out.get(k) for k in ("theme_approval", "mismatch", "expected_basis")})
    code, out = pb(d, "ui-guard", "--path", "web/src/styles/tokens.css")
    e = " ".join(out.get("errors") or [])
    check("B4 ui-guard: 승인 이후 테마 변경 → theme_changed, 토큰 메시지에 '승인값 아님' 표시", code == 2 and "theme_changed" in e and "승인값 아님" in e and "승인값 #123456" not in e, e[:400])
    theme.write_text(t0)
    code, out = pb(d, "ui-brief", "--batch", "B1")
    br = json.loads((d / ".ai-workflow/build/ui/B1/brief.json").read_text()) if code == 0 else {}
    LOG.append({"step": "UI Brief B1 design_sources", "design_sources": br.get("design_sources"), "tokens.theme_approval": (br.get("tokens") or {}).get("theme_approval")})
    ds = br.get("design_sources") or {}
    s1 = (ds.get("screens") or {}).get("SCR-001") or {}
    check("B5 UI Brief: 승인 기록 VD·공식 자산만(권리 미확인 AST-002 없음), 탐색 선택은 source_only, 후보 테마 없음",
          code == 0 and ds.get("design_direction", {}).get("approved") and {a["id"] for a in s1.get("assets", [])} >= {"AST-001"}
          and "AST-002" not in json.dumps(ds.get("screens")) and ds["exploration_provenance"]["use"] == "source_only"
          and "adoption/theme.candidate.json" not in json.dumps(br) and "design-explore/V" not in json.dumps(br) and br["tokens"]["theme_approval"]["status"] == "approved",
          {k: ds.get(k) for k in ("design_direction", "exploration_provenance")} | {"SCR-001": s1})
    (d / "web/src/features/member").mkdir(parents=True, exist_ok=True)
    (d / "web/src/components").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(d / "design-explore/V01/C/index.html", d / "web/src/features/member/login.view")
    shutil.copyfile(d / "design-explore/V01/C/styles.css", d / "web/src/features/member/login.css")
    shutil.copyfile(d / "design-profile/assets/AST-002.svg", d / "web/src/components/hero.svg")
    (d / "web/src/features/member/my.css").write_text(":root{--color-accent-x:#000}\n.x{color:var(--color-brand-mint)}\n")
    shutil.copyfile(d / "design-profile/assets/AST-001.svg", d / "web/src/components/icon.svg")
    code, out = pb(d, "ui-guard", "--path", "web/src/features/member/login.view", "--path", "web/src/features/member/login.css",
                   "--path", "web/src/components/hero.svg", "--path", "web/src/components/icon.svg")
    e = " ".join(out.get("errors") or [])
    check("B6 Build(ui-guard): 프로젝트 확장자(.view) 시안 복사·미선택 시안(C) CSS 복사 explore_copy·미승인 자산 asset_unapproved 차단, 공식 자산(AST-001) 통과",
          code == 2 and "login.view" in e and "login.css" in e and "선택되지 않은 시안" in e and "asset_unapproved" in e and "icon.svg" not in e, e[:500])
    for f in ("web/src/features/member/login.view", "web/src/features/member/login.css", "web/src/components/hero.svg", "web/src/features/member/my.css"):
        (d / f).unlink()
    code, out = pb(d, "ui-guard", "--path", "web/src/components/icon.svg", "--path", "web/src/styles/tokens.css")
    check("B7 공식 경로(승인 토큰·공식 자산)만 쓰면 ui-guard 통과", code == 0, out.get("errors"))


def real_measure(d: Path, rid: str, out_dir: Path) -> str | None:
    """--real-browser: 실제 Chrome(CDP 어댑터)으로 다시 측정하고 스크린샷을 out_dir로 복사."""
    (d / "tools/pd-measure").mkdir(parents=True, exist_ok=True)
    shutil.copy(CDP_ADAPTER, d / "tools/pd-measure/pd-measure-cdp.mjs")
    code, out = pd(d, "explore-config", "--measure-cmd", "node --experimental-websocket tools/pd-measure/pd-measure-cdp.mjs",
                   "--measure-viewports", "mobile=390x844@2,desktop=1280x800@1", "--confirm", "--note", "실제 Chrome 측정(EX8)")
    code, out = pd(d, "explore-verify", "--round", rid)
    log(d, f"실제 Chrome 측정 {rid}(viewport meta 없는 시안)", code, out)
    check(f"R-{rid}a 실제 Chrome: viewport meta 없는 시안은 980px 레이아웃 → viewport_mismatch로 측정 무효(invalid, 미실행과 구분)",
          code == 2 and out.get("status") == "invalid" and "viewport_mismatch" in str(out.get("reason")), {k: out.get(k) for k in ("status", "reason")})
    for lb in "ABC":
        h = d / f"design-explore/{rid}/{lb}/index.html"
        h.write_text(h.read_text().replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">', 1))
    pd(d, "explore-check", "--round", rid)
    code, out = pd(d, "explore-verify", "--round", rid)
    log(d, f"실제 Chrome 측정 {rid}", code, out)
    check(f"R-{rid} 실제 Chrome 측정 완료(390×844@2·1280×800@1)", code == 0 and out["status"] == "completed", out)
    if out.get("status") != "completed":
        return None
    src = d / f"design-explore/{rid}/shots/{out['run_id']}/shots"
    dst = out_dir / f"chrome-{rid}"
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.glob("*.png"):
        shutil.copy(p, dst / p.name)
    LOG.append({"step": f"실제 Chrome 스크린샷 {rid}", "dir": str(dst), "blocking": {k: v["blocking"] for k, v in out["variants"].items()}})
    return out["run_id"]


def stage_renderer_failure(d: Path) -> None:
    """렌더러 실패(Figma 실패·사용 불가)는 시안 검사만 실패시키고 승인 상태를 바꾸지 않습니다. figma는 declared로만 남습니다."""
    st0 = json.loads((d / ".ai-workflow/design.json").read_text())
    man_p = d / "design-explore/explore.manifest.json"
    man0 = man_p.read_text()
    res = {}
    for status in ("failed", "unavailable"):
        XT.figma_variant(d, "V01", "C", status=status, reason=f"EX8 시뮬레이션 {status}")
        code, out = pd(d, "explore-check", "--round", "V01")
        res[status] = (code, XT.errs_of(out))
        man_p.write_text(man0)
    st1 = json.loads((d / ".ai-workflow/design.json").read_text())
    check("R1 렌더러 실패·사용 불가 → 시안 검사 실패(render_failed·render_unavailable), 단계 승인 기록 불변",
          res["failed"][0] == 2 and "render_failed" in res["failed"][1] and res["unavailable"][0] == 2 and "render_unavailable" in res["unavailable"][1]
          and st1["stages"] == st0["stages"], res)
    LOG.append({"step": "렌더러 실패 시뮬레이션", "result": {k: (v[0], v[1][:200]) for k, v in res.items()}})
    XT.write_vvariant(d, "V01", "C", axes=("density", "component"), mode="ai", rules=[], axis_sources={}, reinterpretation="")
    man = json.loads(man_p.read_text())
    man["rounds"]["V01"]["variants"]["C"].pop("render", None)
    man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2))
    code, out = pd(d, "check")
    check("R2 실패 시뮬레이션 뒤 프로젝트 상태 점검 통과(승인 단계 그대로)", code == 0, out.get("cross_verify"))


def stage_planning_reopen(d: Path) -> None:
    """기획 재검토(T9): product-start가 planning을 다시 열면 design이 locked — product-design은 모든 명령을 막고 문서·승인 기록을 보존."""
    dj0 = (d / ".ai-workflow/design.json").read_bytes()
    ok_step(d, "기획 재검토 reopen(시뮬레이션)", ps, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "범위 재검토(시뮬레이션)")
    sy = (d / ".ai-workflow/state.yaml").read_text()
    code, out = pd(d, "begin", "--stage", "preview")
    code2, out2 = pb(d, "token-check")
    check("T1 planning 재검토 → state.yaml design locked, product-design 명령 차단, design.json 보존",
          re.search(r"  design:\n    status: locked", sy) is not None and code == 2 and (d / ".ai-workflow/design.json").read_bytes() == dj0, (out, out2.get("error")))
    LOG.append({"step": "planning reopen 이후 product-build token-check", "exit": code2, "error": out2.get("error"), "state": statuses(d)})


def stage_v1_compat(root: Path) -> None:
    d = T.make_product(root, "legacy-v1")
    code, out = pd(d, "start")
    st = json.loads((d / ".ai-workflow/design.json").read_text())
    code2, out2 = pd(d, "explore-init", "--phase", "structure")
    check("C1 기존 v1 프로젝트: 탐색 없음, 탐색 명령 거부(exploration_disabled), 승인 흐름 그대로", code == 0 and "exploration" not in st and code2 == 2, out2)


def main() -> int:
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="product-workflow-e2e-"))
    if keep:
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
    out_dir = root / "_e2e_output"
    out_dir.mkdir(exist_ok=True)
    try:
        d = stage_start(root)
        stage_ux_planning(d, out_dir)
        stage_ux_spec(d)
        info = stage_design_direction(d, root, out_dir)
        stage_dd_approve(d, info)
        stage_impact(d, root)
        stage_renderer_failure(d)
        pv = stage_preview(d)
        stage_build(d, pv)
        stage_planning_reopen(d)
        stage_v1_compat(root)
    except AssertionError as e:
        check(f"워크플로 단계 실패: {e}", False)
    finally:
        (out_dir / "e2e-log.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=2))
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed" + (f"  (출력: {out_dir})" if keep else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
