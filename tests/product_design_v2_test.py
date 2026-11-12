#!/usr/bin/env python3
"""/product-design 워크플로 v2 상태·마이그레이션·무효화(WF-D05) 테스트(자체 완결형).

- v1 불변: 같은 v1 명령 순서를 고정된 v1 엔진(engine_baseline.V1_ENGINE, scripts 디렉터리 전체)과 현재 엔진으로 각각 실행해
  출력·최종 상태를 비교합니다(시각·커밋 해시·임시 경로만 정규화). HEAD는 커밋마다 움직이므로 기준으로 쓰지 않습니다.
- 디자인 승인은 스크립트 명령으로만 기록합니다. state.yaml·기획 문서는 테스트 픽스처입니다.
- design.json을 손으로 고치는 경우는 '손상·조작 상태를 엔진이 거부하는지' 확인할 때뿐입니다(V5·V7).
- 프리뷰 승인이 필요한 항목은 pnpm 빌드가 가능할 때만 실행합니다.

실행: python3 tests/product_design_v2_test.py
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402
import product_design_impact_test as IT  # noqa: E402
import engine_baseline  # noqa: E402  (고정 기준 엔진: scripts 디렉터리 전체)

ENGINE = HERE.parent
results: list[tuple[str, bool, str]] = []
THEME = "design-profile/theme.json"


def check(name, cond, detail=None):
    results.append((name, bool(cond), "" if cond else str(detail)[:700]))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def skip(name, why):
    results.append((name, True, "SKIP"))
    print(f"SKIP {name}  -- {why}")


pi = T.pi
state = T.state


def P(d):
    return ("--project", str(d))


def cats(it):
    return [c["key"] for c in it.get("categories", [])]


def raw(d):
    return (d / ".ai-workflow/design.json").read_text()


def approvals(st: dict) -> dict:
    """승인·제출 기록과 revision만 뽑습니다(해시·revision 불변 확인용)."""
    return {k: {"status": v["status"], "revision": v["revision"], "approved": v.get("approved"), "submitted": v.get("submitted")}
            for k, v in st["stages"].items() if k in ("ux_planning", "ux_spec", "preview")}


VOLATILE = {"at", "created_at", "updated_at", "recorded_at", "detected_at", "planning_commit"}


def norm(obj, paths):
    if isinstance(obj, dict):
        return {k: ("<V>" if k in VOLATILE else norm(v, paths)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [norm(x, paths) for x in obj]
    if isinstance(obj, str):
        for p in paths:
            obj = obj.replace(p, "<P>")
        return re.sub(r"[0-9a-f]{40}", "<SHA>", obj)
    return obj


def run_engine(script, *args):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def v1_sequence(d: Path, script) -> list:
    """v1 승인·재검토·무효화 흐름(프리뷰 빌드 제외)."""
    R = lambda *a: run_engine(script, *a)
    outs = [R("check", *P(d)), R("start", *P(d))]
    T.write_00(d, 1); outs.append(R("done", *P(d), "--path", T.UXP))
    outs += [R("submit", *P(d), "--stage", "ux_planning"), R("approve", *P(d), "--stage", "ux_planning", "--revision", "2"),
             R("approve", *P(d), "--stage", "ux_planning", "--revision", "1"), R("begin", *P(d), "--stage", "preview"),
             R("begin", *P(d), "--stage", "ux_spec")]
    T.write_spec(d, 1); outs += [R("done", *P(d), "--path", f) for f in T.SPEC]
    outs += [R("submit", *P(d), "--stage", "ux_spec"), R("checkpoint", *P(d)), R("submit", *P(d), "--stage", "ux_spec"),
             R("approve", *P(d), "--stage", "ux_spec", "--revision", "1"), R("status", *P(d)), R("check", *P(d))]
    p00 = d / T.UXP; orig = p00.read_text(); p00.write_text(orig + "\n메모\n")
    outs += [R("begin", *P(d), "--stage", "preview"), R("check", *P(d))]
    p00.write_text(orig)
    outs += [R("begin", *P(d), "--stage", "preview"), R("preview-scaffold", *P(d)), R("preview-check", *P(d)),
             R("reopen", *P(d), "--stage", "ux_spec", "--reason", "변경"), R("check", *P(d)), R("status", *P(d)),
             R("impact", *P(d)), R("backup", *P(d), "--path", T.SPEC[1])]
    return outs


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-v2-test-"))

    # ---------------------------------------------------------------- v1 불변(고정된 v1 엔진과 비교)
    # 기준 엔진도 같은 템플릿을 쓰도록 현재 templates를 링크합니다(비교 대상은 스크립트 동작).
    head = engine_baseline.extract_skill(engine_baseline.V1_ENGINE, root / "head_skill")
    da, db = T.make_product(root, "v1_head"), T.make_product(root, "v1_new")
    oa, ob = v1_sequence(da, head), v1_sequence(db, T.SCRIPT)
    paths = [str(da), str(db)]
    diffs = [i for i, (x, y) in enumerate(zip(oa, ob)) if norm(x, paths) != norm(y, paths)]
    check(f"V0 v1 명령 {len(oa)}개의 종료 코드·출력이 v1 엔진({engine_baseline.V1_ENGINE[:7]})과 같음", not diffs and len(oa) == len(ob),
          [(i, norm(oa[i], paths), norm(ob[i], paths)) for i in diffs[:2]])
    sa, sb = norm(json.loads(raw(da)), paths), norm(json.loads(raw(db)), paths)
    check("V0a v1 최종 design.json(승인·해시·revision·무효화·history)이 v1 엔진과 같음", sa == sb,
          [k for k in sa if sa.get(k) != sb.get(k)])
    check("V0b v1 상태에는 config·design_direction·theme이 생기지 않음", "config" not in sb and "design_direction" not in sb["stages"] and "theme" not in sb)

    # ---------------------------------------------------------------- 마이그레이션(프리뷰 없는 프로젝트)
    d = T.make_product(root, "mig")
    pi("start", *P(d)); T.write_00(d, 1); pi("done", *P(d), "--path", T.UXP); pi("submit", *P(d), "--stage", "ux_planning")
    pi("approve", *P(d), "--stage", "ux_planning", "--revision", "1"); pi("begin", *P(d), "--stage", "ux_spec")
    T.write_spec(d, 1); T.done_all(d, T.SPEC); pi("checkpoint", *P(d)); pi("submit", *P(d), "--stage", "ux_spec")
    pi("approve", *P(d), "--stage", "ux_spec", "--revision", "1")
    (d / "design-profile").mkdir(); (d / THEME).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
    T.G(d, "add", "-A"); T.G(d, "commit", "-qm", "design + theme (user commit)")
    v1_text, v1_st = raw(d), state(d)

    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--confirm", "--simulate-failure")
    check("V4 전환 중 실패 → 원래 파일로 복원(바이트 동일), JSON 오류", code == 2 and out.get("error") == "migrate_failed"
          and out.get("restored") is True and raw(d) == v1_text, out)
    for bad, label in (("/etc/hosts", "절대 경로"), ("../x.json", "상위 경로"), (T.SPEC[3], "승인 산출물"), ("docs/planning/02-prd.md", "기획 문서"), ("nope.json", "없는 파일")):
        code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", bad)
        check(f"V15 테마 파일 경로 거부: {label}", code == 2 and out.get("error") == "invalid_theme_file" and raw(d) == v1_text, out)
    code, out = pi("migrate", *P(d), "--to", "v3")
    check("V15a 지원하지 않는 대상 버전 → JSON 오류", code == 2 and out.get("error") == "invalid_arguments", out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME)
    check("V1 확인 없이 실행 → 계획만 출력, 파일 불변", code == 0 and out.get("dry_run") and raw(d) == v1_text
          and out["plan"]["after"]["design_direction"] == "not_started" and "옮기지 않습니다" in out["plan"]["not_promoted"], out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--confirm")
    st = state(d)
    check("V2 전환: config.workflow=v2, theme_file, design_direction 추가(not_started, 승인 없음)", code == 0 and st["config"] == {"workflow": "v2", "theme_file": THEME}
          and st["stages"]["design_direction"]["status"] == "not_started" and st["stages"]["design_direction"]["approved"] is None
          and st["theme"]["baseline_hash"] == T.sha(d / THEME), out)
    check("V2a 기존 승인·제출 기록·revision·해시 불변", approvals(st) == approvals(v1_st), (approvals(st), approvals(v1_st)))
    check("V2b 기존 history 보존 + migrated 1건 추가", st["history"][:len(v1_st["history"])] == v1_st["history"]
          and st["history"][-1]["event"] == "migrated" and len(st["history"]) == len(v1_st["history"]) + 1)
    check("V2c Git 추적·clean 상태 파일이라 백업 생략(파일 안전 규칙)", out.get("backup") is None, out)
    code, out = pi("check", *P(d))
    check("V2d 전환 후 check 일치 + 워크플로 정보(M1-3: design_direction 구현, 게이트 기본 꺼짐)", code == 0 and out["workflow"]["version"] == "v2"
          and out["workflow"]["not_implemented"] == [] and out["workflow"]["gates"] == {"design_direction": False}
          and out["workflow"]["deferred_dependencies"] == {"preview": ["design_direction"]}, out)
    after = raw(d)
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", THEME, "--confirm")
    check("V3 재실행 멱등: already_v2, design.json 바이트 동일", code == 0 and out.get("status") == "already_v2" and raw(d) == after, out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--confirm")
    check("V3a 테마 인자 없이 재실행해도 기존 설정 유지·변경 없음", code == 0 and out.get("status") == "already_v2" and raw(d) == after, out)
    (d / "other.json").write_text("{}\n")
    code, out = pi("migrate", *P(d), "--to", "v2", "--theme-file", "other.json", "--confirm")
    check("V3b 다른 테마 파일로 재설정 시도 → 거부(변경 없음)", code == 2 and out.get("error") == "theme_file_conflict" and raw(d) == after, out)
    (d / "other.json").unlink()

    # M1-3: design_direction은 구현된 단계(게이트가 꺼진 v2에서는 선택 단계). 자세한 검사는 product_design_dd_test.py
    code, out = pi("begin", *P(d), "--stage", "design_direction")
    check("V6 (M1-3 변경) v2 design_direction begin 가능(ux_spec 승인 기준)", code == 0 and out.get("based_on_ux_spec_revision") == 1, out)
    code, out = pi("approve", *P(d), "--stage", "design_direction", "--revision", "1")
    check("V6a (M1-3 변경) 제출 없이 design_direction 승인 → 거부", code == 2 and out.get("error") == "not_awaiting_approval", out)
    (d / ".ai-workflow/design.json").write_text(after)  # 이후 시나리오를 위해 시작 전 상태로 되돌림
    code, out = pi("begin", *P(da), "--stage", "design_direction")
    check("V6c v1 프로젝트에서 design_direction → stage_not_in_workflow", code == 2 and out.get("error") == "stage_not_in_workflow", out)

    # 손상·조작 상태
    good = after
    st_bad = json.loads(good); st_bad["stages"]["design_direction"]["status"] = "approved"
    (d / ".ai-workflow/design.json").write_text(json.dumps(st_bad, ensure_ascii=False))
    code, out = pi("check", *P(d))
    check("V7 수동으로 approved가 된 design_direction(승인 기록 없음) → 승인으로 인정하지 않고 문제 보고", code == 2
          and any(p["stage"] == "design_direction" and p["kind"] == "missing_record" for p in out["cross_verify"]["problems"]), out)
    tampered = raw(d)
    code, out = pi("migrate", *P(d), "--to", "v2", "--confirm")
    code2, out2 = pi("check", *P(d))
    check("V7a (M1-3 변경) v2의 조작된 design_direction: migrate는 아무것도 바꾸지 않고(승격 없음) check는 계속 문제 보고",
          code == 0 and out.get("status") == "already_v2" and raw(d) == tampered and code2 == 2, (out, out2.get("cross_verify")))
    st_v1bad = json.loads(good); st_v1bad["config"] = {}; del st_v1bad["theme"]
    st_v1bad["stages"]["design_direction"]["status"] = "in_progress"
    (d / ".ai-workflow/design.json").write_text(json.dumps(st_v1bad, ensure_ascii=False))
    code, out = pi("migrate", *P(d), "--to", "v2", "--confirm")
    check("V7b v1 상태에 진행 중인 design_direction이 끼어 있으면 전환 거부(승격 금지)", code == 2 and out.get("error") == "invalid_state", out)
    st_bad = json.loads(good); st_bad["config"]["workflow"] = "v3"
    (d / ".ai-workflow/design.json").write_text(json.dumps(st_bad, ensure_ascii=False))
    code, out = pi("status", *P(d))
    check("V5 잘못된 workflow 값 → invalid_state", code == 2 and out.get("error") == "invalid_state", out)
    st_bad = json.loads(good); del st_bad["stages"]["design_direction"]; del st_bad["theme"]
    (d / ".ai-workflow/design.json").write_text(json.dumps(st_bad, ensure_ascii=False))
    code, out = pi("check", *P(d))
    check("V5a v2 필드 누락(중간에 멈춘 전환) → invalid_state + 복구 안내", code == 2 and out.get("error") == "invalid_state" and "migrate" in out.get("hint", ""), out)
    code, out = pi("migrate", *P(d), "--to", "v2", "--confirm")
    st = state(d)
    check("V5b migrate --confirm으로 누락 필드만 복구(기존 승인·처음 전환 기록 불변)", code == 0 and "design_direction" in st["stages"] and "theme" in st
          and approvals(st) == approvals(v1_st) and st["migration"] == json.loads(good)["migration"]
          and st["history"][-1]["event"] == "migration_repaired", out)
    code, out = pi("check", *P(d))
    check("V5c 복구 후 check 일치", code == 0, out)

    # 상위 승인 변경 → 하위 단계 무효화(v2 순서)
    code, out = pi("reopen", *P(d), "--stage", "ux_spec", "--reason", "정보 추가")
    st = state(d)
    check("V10 v2에서 ux_spec reopen → design_direction·preview 잠금", code == 0 and st["stages"]["design_direction"]["status"] == "locked"
          and st["stages"]["preview"]["status"] == "locked", (out, st["stages"]["design_direction"]))
    T.write_spec(d, 2); T.done_all(d, T.SPEC)
    pi("submit", *P(d), "--stage", "ux_spec")
    code, out = pi("approve", *P(d), "--stage", "ux_spec", "--revision", "2")
    st = state(d)
    check("V10a ux_spec 재승인 → design_direction(상태만)·preview 잠금 해제", code == 0 and st["stages"]["design_direction"]["status"] == "not_started"
          and st["stages"]["preview"]["status"] == "not_started" and st["stages"]["design_direction"]["approved"] is None, st["stages"])
    code, out = pi("begin", *P(d), "--stage", "preview")
    check("V10b v2 preview 시작: 미구현 의존성(design_direction)은 게이트에서 제외하고 그 사실을 표시", code == 0
          and out.get("deferred_dependencies") == ["design_direction"], out)

    # 사전 점검: 손상된 v1 상태는 전환하지 않음
    d2 = T.make_product(root, "mig_bad")
    pi("start", *P(d2)); T.write_00(d2, 1); pi("done", *P(d2), "--path", T.UXP); pi("submit", *P(d2), "--stage", "ux_planning")
    pi("approve", *P(d2), "--stage", "ux_planning", "--revision", "1")
    (d2 / T.UXP).write_text((d2 / T.UXP).read_text() + "\n승인 후 메모\n")
    before = raw(d2)
    code, out = pi("migrate", *P(d2), "--to", "v2", "--confirm")
    check("V14 승인 산출물이 바뀐 상태 → 전환 거부(파일 불변)", code == 2 and out.get("error") == "migrate_precheck_failed" and raw(d2) == before, out)

    # ---------------------------------------------------------------- 프리뷰가 승인된 프로젝트(테마·구현 메모)
    dp, ok = IT.build_project(root, "pv")
    if not ok:
        skip("V8–V13", "pnpm 빌드 불가로 프리뷰를 승인하지 못함")
    else:
        (dp / "design-profile").mkdir(); (dp / THEME).write_text('{"brand": {"primary": "#1D5BD0"}}\n')
        T.G(dp, "add", "-A"); T.G(dp, "commit", "-qm", "theme (user commit)")
        tsx = dp / "design-preview/src/screens/SCR-002.tsx"; tsx_orig = tsx.read_text()
        # v1 기준 동작(바뀌지 않아야 함)
        tsx.write_text("// 구현 메모\n" + tsx_orig)
        code, out = pi("check", *P(dp))
        check("V9 v1: 프리뷰 주석만 바꿔도 approved_modified(기존 동작 유지)", code == 2
              and any(p["stage"] == "preview" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"]) and "workflow" not in out, out)
        tsx.write_text(tsx_orig)
        (dp / THEME).write_text('{"brand": {"primary": "#0E6B4F"}}\n')
        code, out = pi("check", *P(dp))
        check("V8 v1: 테마 파일은 승인 대상이 아님(기존 동작, check 일치)", code == 0, out)
        T.G(dp, "checkout", "--", THEME)
        st_v1 = state(dp)
        code, out = pi("migrate", *P(dp), "--to", "v2", "--theme-file", THEME, "--confirm")
        st = state(dp)
        check("V2e 프리뷰 승인 프로젝트 전환: 승인 기록 불변, 의미·테마 기준은 별도 필드(v2_baseline)", code == 0
              and approvals(st) == approvals(st_v1) and st["stages"]["preview"]["v2_baseline"]["record"] == "approved"
              and st["stages"]["preview"]["review"] is None, out)
        snap = approvals(st)
        # ⑤ 구현 메모: .ts 주석만 → 재승인 없음 / .tsx는 의미 해시를 쓰지 않으므로(M1-3 보수화) 재승인
        mock = dp / "design-preview/src/mock/data.ts"; mock_orig = mock.read_text()
        mock.write_text("// 구현 메모: 화면별 mock은 여기에 둡니다\n" + mock_orig + "\n// 끝\n")
        code, out = pi("check", *P(dp))
        check("V9a v2: 프리뷰 .ts 주석만 변경 → 문제 없음, 구현 메모 경고, 프리뷰 승인 유지", code == 0
              and any("구현 메모" in w for w in out["cross_verify"]["warnings"]) and state(dp)["stages"]["preview"]["status"] == "approved", out)
        code, out = pi("impact", *P(dp), "--design")
        it = next(i for i in out["items"] if i["id"].endswith("mock/data.ts"))
        check("V11 v2 파일 분류: .ts 주석만 → ⑤, 재승인 불필요(의미 해시 불변)", it["status"] == "classified" and it["reapproval_stages"] == []
              and it["impact"][0]["reapproval_required"] is False, it)
        mock.write_text(mock_orig)
        tsx.write_text("// 구현 메모: 카드 순서는 mock 순서\n" + tsx_orig)
        code, out = pi("check", *P(dp))
        check("V9a2 (M1-3 변경) v2: .tsx 주석은 JSX 글자일 수 있어 원본 비교 → approved_modified", code == 2
              and any(p["stage"] == "preview" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"]), out)
        code, out = pi("impact", *P(dp), "--design")
        it = next(i for i in out["items"] if i["id"].endswith("SCR-002.tsx"))
        check("V11e (M1-3 변경) v2 파일 분류: .tsx 주석 → ⑤이지만 의미 해시 미적용이라 프리뷰 재승인 필요", cats(it) == ["implementation"]
              and it["reapproval_stages"] == ["preview"], it)
        # 코드 변경 → 승인 변경 + 분류(사용자 판단 필요), 자동 처리 없음
        tsx.write_text(tsx_orig.replace("<h1>", "<h1 className='big'>"))
        before = raw(dp)
        code, out = pi("check", *P(dp))
        prob = next((p for p in out["cross_verify"]["problems"] if p["kind"] == "approved_modified"), {})
        check("V9b v2: 프리뷰 코드 변경 → approved_modified + 분류(needs_review) + 사용자 판단 필요", code == 2
              and prob.get("requires_user_decision") is True and any(c["status"] == "needs_review" for c in prob.get("classification", [])), prob)
        check("V9c 판단이 필요한 분류에서 상태 자동 변경 없음", raw(dp) == before and approvals(state(dp)) == snap)
        tsx.write_text(tsx_orig)
        # ③ 테마 값: UX Spec 보존, 프리뷰만 무효
        (dp / THEME).write_text('{"brand": {"primary": "#0E6B4F"}}\n')
        code, out = pi("check", *P(dp))
        kinds = [(p["stage"], p["kind"]) for p in out["cross_verify"]["problems"]]
        check("V8a v2: 테마 값만 변경 → preview만 theme_changed, ux_spec 문제 없음", code == 2 and kinds == [("preview", "theme_changed")], kinds)
        req = root / "theme-req.json"
        req.write_text(json.dumps({"schema": "design-change-request/v1", "items": [
            {"id": "TH", "summary": "브랜드 색 값", "facts": [{"kind": "token_value", "token": "color.action.primary"}]},
            {"id": "VS", "summary": "버튼 반경", "facts": [{"kind": "style", "component": "CMP-001", "property": "radius"}]},
            {"id": "IM", "summary": "구현 메모", "facts": [{"kind": "implementation_note", "detail": "주석"}]},
            {"id": "CD", "summary": "배치(정책 미기록)", "facts": [{"kind": "placement", "component": "CMP-001"}]}]}, ensure_ascii=False))
        code, out = pi("impact", *P(dp), "--design", "--request", str(req))
        get = lambda i: next(x for x in out["items"] if x["id"] == i)
        th = get("TH")["impact"][0]
        check("V11a v2 ③ 테마 값(theme_file 있음) → 프리뷰만 재승인, ux_spec·design_direction 보존", out["workflow"]["applied"] == "v2"
              and th["effective_stage"] == "preview" and th["reapproval_stages"] == ["preview"] and th["preserved"] == ["ux_spec", "design_direction"], th)
        vs = get("VS")["impact"][0]
        vimp = get("VS")["impact"]
        check("V11b (M1-3 변경) v2 ④ 시각 표현 → design_direction(구현됨) + 프리뷰 렌더 영향", vs["target_stage"] == "design_direction"
              and vs["target_available"] is True and vs["effective_stage"] == "design_direction" and out["not_implemented_stages"] == []
              and any(x["effective_stage"] == "preview" for x in vimp), vimp)
        im = get("IM")["impact"][0]
        check("V11c v2 ⑤ 구현 메모(요청) → 재승인 불필요, 의미 해시 확인 안내", im["reapproval_required"] is False and im.get("render_note"), im)
        cd = get("CD")
        check("V11d conditional → requires_user_decision, auto_apply 없음", cd["requires_user_decision"] is True and cd["auto_apply"] is False
              and "CD" in out["summary"]["requires_user_decision"], cd)
        check("V12 분류·check 호출 후 승인 기록·해시·revision 불변", approvals(state(dp)) == snap)
        code, out = pi("reopen", *P(dp), "--stage", "preview", "--reason", "테마 변경 반영")
        st = state(dp)
        check("V8b 테마 변경 → preview reopen 허용, ux_spec 승인 유지", code == 0 and st["stages"]["ux_spec"]["status"] == "approved"
              and st["stages"]["ux_spec"]["approved"] == snap["ux_spec"]["approved"], out)
        T.write_06(dp, 2); pi("done", *P(dp), "--path", "docs/design/06-preview-review.md")
        code, out = pi("preview-verify", *P(dp))
        ver = state(dp)["stages"]["preview"]["verification"]
        check("V13 v2 preview-verify가 의미 해시·테마 해시를 기록", code == 0 and ver.get("semantic_tree_hash") and ver.get("theme_hash") == T.sha(dp / THEME), ver)
        tsx.write_text("// 검증 뒤 주석만 추가\n" + tsx_orig)
        code, out = pi("submit", *P(dp), "--stage", "preview")
        check("V13a0 (M1-3 변경) 검증 뒤 .tsx 주석 변경 → 다시 검증 필요(원본 비교)", code == 2 and out.get("error") == "preview_not_verified", out)
        tsx.write_text(tsx_orig)
        mock.write_text("// 검증 뒤 주석만 추가\n" + mock_orig)
        code, out = pi("submit", *P(dp), "--stage", "preview")
        check("V13a 검증 뒤 .ts 주석만 바뀌어도 제출 가능(sem-2 의미 해시 일치)", code == 0, out)
        (dp / THEME).write_text('{"brand": {"primary": "#15803D"}}\n')
        code, out = pi("approve", *P(dp), "--stage", "preview", "--revision", "2")
        check("V13b 제출 뒤 테마 변경 → 승인 거부(theme_changed)", code == 2 and out.get("error") == "theme_changed", out)
        (dp / THEME).write_text('{"brand": {"primary": "#0E6B4F"}}\n')
        code, out = pi("approve", *P(dp), "--stage", "preview", "--revision", "2")
        st = state(dp)
        check("V8c 테마 반영 후 프리뷰 재승인(테마·의미 해시 기록), ux_spec은 처음 승인 그대로", code == 0
              and st["stages"]["preview"]["approved"]["theme_hash"] == T.sha(dp / THEME)
              and st["stages"]["ux_spec"]["approved"] == snap["ux_spec"]["approved"] and st["stages"]["ux_planning"]["approved"] == snap["ux_planning"]["approved"], out)
        code, out = pi("check", *P(dp))
        check("V8d 재승인 후 check 일치", code == 0, out.get("cross_verify"))
        # 04 토큰 값 변경(테마 파일이 아닌 승인 문서) → UX Spec 영향(정직하게 보고)
        ui = dp / T.SPEC[3]; ui_orig = ui.read_text()
        ui.write_text(ui_orig.replace("| color.action.primary | #1D5BD0 |", "| color.action.primary | #0E6B4F |"))
        code, out = pi("check", *P(dp))
        check("V16 v2라도 04(승인 문서)의 토큰 값 변경은 ux_spec approved_modified", code == 2
              and any(p["stage"] == "ux_spec" and p["kind"] == "approved_modified" for p in out["cross_verify"]["problems"]), out)
        ui.write_text(ui_orig)

    passed = sum(1 for _, ok_, _ in results if ok_)
    print(f"\nRESULT {passed}/{len(results)} passed  (임시 디렉터리: {root})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
