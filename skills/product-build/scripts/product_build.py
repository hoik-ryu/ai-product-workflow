#!/usr/bin/env python3
"""/product-build 결정적 보조 스크립트(CLI 진입점). Python 3.11+, 표준 라이브러리만.

모든 출력은 JSON입니다. 종료 코드: 0 성공 / 2 차단(사용자 조치 필요, 상태 변경 없음) / 1 내부 오류(상태 변경 없음).
상태 파일(.ai-workflow/build.json)과 docs/build/만 씁니다. 다른 Skill의 상태·승인 문서는 읽기만 합니다.

M2.1 범위: init, check, scan, scope, plan-validate, submit plan, approve plan, reopen plan, waiver, status, adopt, execute-gate, guard.
배치 실행(M2.2)·자동 검증(M2.3)·정책 원장(M2.4)은 아직 없습니다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# python3 -I(격리 모드)는 스크립트 폴더를 import 경로에 넣지 않으므로 이 폴더만 명시적으로 추가합니다. 바이트코드도 만들지 않습니다.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pb_core import (  # noqa: E402
    BOILERPLATE_REL, BUILD_DIR_REL, DESIGN_STATE_REL, GENERATED_MARK, PLAN_FILES, PLAN_JSON_REL, PLAN_MD_REL, PROFILE_REL,
    STATE_REL, Blocked, add_history, baseline_changes, block, design_info, emit, engine_ref, git_lines, input_baseline,
    is_protected, load_profile, load_state, new_state, now, planning_gate, preflight, require_planning, require_state,
    save_state, sha_file, write_owned,
)
from pb_inputs import compute_scope, load_model  # noqa: E402
from pb_plan import draft, render_md, suggest_groups, validate, waiver_valid  # noqa: E402
from pb_scan import (  # noqa: E402
    component_inventory, detect_commands, detect_stack, guess_paths, id_mentions, is_test_path, iter_source,
)
from pb_adopt import analyze  # noqa: E402
import pb_ledger as L  # noqa: E402
import pb_ui as U  # noqa: E402
from pb_exec import (  # noqa: E402
    DEP_LEVELS, EVIDENCE_REL, LOCK_REL, acquire_lock, changed_vs, classify, diff_states, ensure_gitignore, head_sha, heartbeat,
    in_patterns, load_checkpoint, lock_age_minutes, next_task, read_lock, release_lock, require_lock, save_base_tests, states_now, task_order,
    write_checkpoint,
)
from pb_verify import (  # noqa: E402
    batch_scope_files, batch_verdict, deps_affecting, deps_tree, evaluate, load_run, mentions_in_tests, run_steps, step_summary,
    tracked_files, tree_hash, update_history,
)

SKILL_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- 공통
def project_of(a) -> Path:
    p = Path(a.project).resolve()
    pf = preflight(p)
    if not pf["ok"]:
        block(pf["error"], pf["message"])
    return p


def read_plan(project: Path, required: bool = True) -> dict | None:
    p = project / PLAN_JSON_REL
    if not p.exists():
        if required:
            block("no_plan", f"{PLAN_JSON_REL}이 없습니다. scope --draft로 골격을 받아 계획을 작성하세요.")
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("plan_json_invalid", f"{PLAN_JSON_REL}을 JSON으로 읽을 수 없습니다: {e}")


def plan_hashes(project: Path) -> dict:
    return {rel: sha_file(project / rel) for rel in PLAN_FILES}


def profile_or_block(project: Path, required: bool = True) -> dict:
    prof, probs = load_profile(project, required=required)
    if probs:
        block("profile_invalid", f"{PROFILE_REL}에 문제가 있습니다.", problems=probs)
    return prof


def run_validate(project: Path, st: dict | None, plan: dict, profile: dict, dinfo: dict) -> dict:
    model = load_model(project)
    v = validate(plan, model, profile, dinfo, (st or {}).get("waivers", [])) | {"_model": model}
    ui_errs = U.plan_conflicts(U.load_map(project), plan)  # M3.1: 대응표가 있을 때만(없으면 기존 동작 그대로)
    if ui_errs:
        v["errors"] = v["errors"] + ui_errs
        v["ok"] = False
    return v


def waiver_status(st: dict, dinfo: dict) -> list[dict]:
    return [{"id": w["id"], "status": w["status"], "valid": waiver_valid(w, dinfo), "scope": w["scope"], "reason": w["reason"]}
            for w in st.get("waivers", [])]


def next_action(st: dict | None, project: Path) -> str:
    if st is None:
        return "init으로 상태 파일과 프로필을 만듭니다."
    s = st["plan"]["status"]
    if s == "drafting":
        if not (project / PLAN_JSON_REL).exists():
            return "scope --draft로 골격을 받아 Claude가 implementation-plan.json을 작성 → plan-validate"
        return "plan-validate로 검사 → (프리뷰 미승인 + 화면 배치면 사용자 승인 후 waiver add) → submit plan"
    if s == "awaiting_approval":
        return f"00-implementation-plan.md를 사용자에게 보여 주고 명시적 승인을 받으면 approve plan --revision {st['plan']['revision']} --note '<사용자 승인 문장>'"
    if s == "approved":
        act = [k for k, b in st["batches"].items() if b["status"] in ("in_progress", "paused", "failed")]
        if act:
            return f"{act[0]}가 {st['batches'][act[0]]['status']} 상태입니다. resume으로 이어서 합니다(새 배치를 시작하지 않음)."
        unv = [k for k, b in st["batches"].items() if b["status"] in ("implemented", "verify_failed", "stale", "imported")]
        if unv:
            return f"검증이 필요한 배치가 있습니다: {', '.join(unv)} → verify --batch <ID>(실패하면 resume --batch로 고친 뒤 다시 검증)."
        nxt = [k for k, b in st["batches"].items() if b["status"] == "planned"]
        if not nxt:
            pend = [k for k, b in st["batches"].items() if b["status"] == "verified" and b.get("approval") == "user"]
            return ("모든 배치가 검증되었습니다. 사용자 최종 승인이 필요한 배치: " + ", ".join(pend) + " → approve batch --batch <ID> --note") if pend \
                else "모든 배치가 검증되었습니다(최종 승인은 approve batch로 선택적으로 기록)."
        return f"다음 배치를 batch-start로 시작합니다(후보: {', '.join(nxt[:3])}). 선행 배치 조건은 execute-gate로 확인합니다."
    return "입력 문서가 바뀌어 계획이 outdated입니다. 영향(changed)을 사용자에게 설명하고 reopen plan --reason → 계획 수정 → submit plan"


# ---------------------------------------------------------------- 명령
def cmd_init(a) -> None:
    project = project_of(a)
    gate = require_planning(project)
    st = load_state(project)
    if st is not None:
        emit({"ok": True, "status": "already_initialized", "plan": {"status": st["plan"]["status"], "revision": st["plan"]["revision"]},
              "next": next_action(st, project)})
    created = []
    if not (project / PROFILE_REL).exists():
        write_owned(project, PROFILE_REL, render_profile(project))
        created.append(PROFILE_REL)
    if not (project / BUILD_DIR_REL / ".gitignore").exists():
        write_owned(project, f"{BUILD_DIR_REL}/.gitignore", "# 증거 원본 로그·스크린샷은 Git에서 제외합니다(요약은 build.json에 기록).\nevidence/\n*.log\n")
        created.append(f"{BUILD_DIR_REL}/.gitignore")
    st = new_state(engine_ref())
    add_history(st, "plan", "initialized", 0, f"planning r{gate.get('planning_approved_revision')}")
    save_state(project, st)
    created.insert(0, STATE_REL)
    emit({"ok": True, "status": "initialized", "created": created,
          "next": "프로필(docs/build/build-profile.toml)의 경로·검증 명령을 확인한 뒤 scope --draft"})


def render_profile(project: Path) -> str:
    gp = guess_paths(project)
    steps = []
    chosen = set()
    cmds = detect_commands(project)
    for c in cmds:
        if c["source"] == "Makefile" and c["stage"] in ("lint", "typecheck", "test", "build", "db", "e2e") and c["stage"] + c["run"] not in chosen:
            chosen.add(c["stage"] + c["run"])
            steps.append(c)
    if not steps:
        steps = [c for c in cmds if c["source"].startswith(BOILERPLATE_REL)]
    lines = []
    for c in steps:
        lines += ["[[verify.steps]]", f'name = "{c["name"]}"', f'stage = "{c["stage"]}"', f'run = "{c["run"]}"', f'cwd = "{c["cwd"]}"',
                  "requires = [" + ", ".join(f'"{r}"' for r in c.get("requires", [])) + "]", f"# 출처: {c['source']}" + (f" — {c['note']}" if c.get("note") else ""), ""]
    for c in cmds:
        if c not in steps and c["source"].endswith("package.json"):
            lines.append(f"# 후보(패키지 스크립트): {c['cwd']} {c['name'].split(':')[-1]} → {c.get('note', '')}")
    if not lines:
        lines = ["# 검증 명령을 찾지 못했습니다. 예:", "# [[verify.steps]]", '# name = "test"', '# stage = "test"', '# run = "make test"', '# cwd = "."', "# requires = []"]
    tpl = (SKILL_DIR / "templates/build-profile.toml").read_text(encoding="utf-8")
    js = lambda xs: json.dumps(xs, ensure_ascii=False)  # noqa: E731
    return (tpl.replace("{source}", js(gp["source"])).replace("{tests}", js(gp["tests"]))
            .replace("{components}", js(gp["components"])).replace("{steps}", "\n".join(lines)))


def cmd_check(a) -> None:
    project = project_of(a)
    gate = planning_gate(project)
    st = load_state(project)
    if not gate["ok"]:
        block(gate["error"], gate["message"], hint="기획 문서와 state.yaml은 수정하지 않았습니다. /product-start로 기획 승인 상태를 먼저 정리하세요.",
              build_state=bool(st))
    dinfo = design_info(project)
    prof, prof_probs = load_profile(project)
    out = {"ok": True, "design": {k: dinfo.get(k) for k in ("level", "reason", "workflow", "basis")}, "profile_problems": prof_probs}
    if st is None:
        emit(out | {"status": "not_initialized", "next": next_action(None, project)})
    plan = st["plan"]
    out["plan"] = {"status": plan["status"], "revision": plan["revision"]}
    base = input_baseline(project, gate, dinfo)
    cur = plan_hashes(project)
    if plan["status"] == "approved":
        changes = baseline_changes(plan["approved"]["inputs"], base)
        if changes:
            plan["status"] = "outdated"
            plan["validity"] = {"status": "outdated", "reason": "입력 문서(기획·디자인 승인)가 계획 승인 이후 바뀌었습니다", "changed": changes, "detected_at": now()}
            add_history(st, "plan", "outdated", plan["revision"], "; ".join(changes)[:500])
            save_state(project, st)
            emit(out | {"ok": False, "error": "plan_outdated", "message": "계획 승인 이후 입력 문서가 바뀌어 계획이 무효(outdated)가 되었습니다. 실행할 수 없습니다.",
                        "changed": changes, "plan": {"status": "outdated", "revision": plan["revision"]}, "next": next_action(st, project)}, 2)
        modified = [k for k, v in plan["approved"]["hashes"].items() if cur.get(k) != v]
        if modified:
            emit(out | {"ok": False, "error": "plan_modified", "message": "승인된 계획 파일이 승인 이후 바뀌었습니다. 승인으로 인정하지 않습니다(자동으로 다시 승인하지 않음).",
                        "paths": modified, "next": "변경이 의도한 것이면 reopen plan → submit plan → 사용자 승인. 아니면 파일을 승인 때 내용으로 되돌리세요."}, 2)
    elif plan["status"] == "outdated":
        out.update(ok=False, error="plan_outdated", changed=plan.get("validity", {}).get("changed", []))
    elif plan["status"] == "awaiting_approval":
        modified = [k for k, v in plan["submitted"]["hashes"].items() if cur.get(k) != v]
        changes = baseline_changes(plan["submitted"]["inputs"], base)
        if modified or changes:
            out["warnings"] = ([f"제출 이후 계획 파일 변경: {', '.join(modified)}"] if modified else []) + \
                              ([f"제출 이후 입력 변경: {'; '.join(changes)}"] if changes else [])
            out["next"] = "제출한 내용과 다릅니다. 다시 submit plan 한 뒤 사용자 승인을 받습니다."
    if plan["status"] == "approved":
        changed = mark_stale(project, st, prof)
        if changed:
            save_state(project, st)
            out.setdefault("warnings", []).append("검증 이후 코드가 바뀌어 재검증이 필요한 배치: " + ", ".join(f"{k}({v})" for k, v in changed.items()))
    out["waivers"] = waiver_status(st, dinfo)
    out["batches"] = {k: {"status": v["status"], "approval": v.get("approval")} for k, v in st["batches"].items()}
    out.setdefault("next", next_action(st, project))
    emit(out, 0 if out["ok"] else 2)


def cmd_scan(a) -> None:
    project = project_of(a)
    prof = profile_or_block(project, required=False)
    paths = prof["paths"]
    roots = sorted(set((paths.get("source") or []) + (paths.get("tests") or []))) or None
    files = iter_source(project, roots, paths.get("exclude"))
    mentions = id_mentions(project, files)
    kinds: dict[str, dict] = {}
    for i, m in mentions.items():
        k = i.split("-")[0]
        kinds.setdefault(k, {"ids": 0, "in_tests": 0, "in_code": 0})
        kinds[k]["ids"] += 1
        kinds[k]["in_tests"] += bool(m["test"])
        kinds[k]["in_code"] += bool(m["code"])
    out = {"ok": True, "stack": detect_stack(project), "commands": detect_commands(project),
           "paths_used": roots or "(프로필 없음: 저장소 전체에서 docs·.ai-workflow·design-preview 제외)", "path_suggestions": guess_paths(project),
           "files": {"source": len(files), "tests": sum(1 for f in files if is_test_path(f))},
           "id_mentions": kinds, "note": "ID 언급은 구현·검증 근거가 아닙니다(adopt에서 후보로만 씀)."}
    if paths.get("components"):
        model = load_model(project)
        inv = component_inventory(project, paths["components"], files, model["CMP"])
        out["components"] = {"files": len(inv["files"]), "cmp_mapped": sum(1 for v in inv["cmp_candidates"].values() if v),
                             "cmp_total": len(model["CMP"]), "unmapped_cmp": inv["unmapped_cmp"],
                             "most_used": sorted(({"file": x["file"], "used_by": x["used_by_count"]} for x in inv["files"]), key=lambda x: -x["used_by"])[:10]}
    emit(out)


def cmd_scope(a) -> None:
    project = project_of(a)
    require_planning(project)
    prof = profile_or_block(project, required=False)
    model = load_model(project)
    plan = read_plan(project, required=False)
    sc = (plan or {}).get("scope") or {}
    prios = a.priorities.split(",") if a.priorities else (sc.get("priorities") or prof["scope"]["priorities"])
    include = sc.get("include") if plan else []
    scope = compute_scope(model, prios, include, (plan or {}).get("deferred"))
    out = {"ok": True, "has_design": model["has_design"],
           "counts": {"FR": len(model["FR"]), "US": len(model["US"]), "AC": len(model["AC"]), "SCR": len(model["SCR"]), "CMP": len(model["CMP"]),
                      "deleted": len(model["deleted"]), "US_in_scope": len(scope["US"]), "AC_in_scope": len(scope["AC"]),
                      "AC_active": len(scope["AC_active"]), "AC_non_ui": len(scope["AC_non_ui"]), "AC_unmapped": len(scope["AC_unmapped"]),
                      "SCR_required": len(scope["SCR_required"]), "SCR_related_optional": len(scope["SCR_related_optional"])},
           "scope": scope, "deleted": model["deleted"],
           "priorities": {p: sorted(u for u, s in model["US"].items() if s["priority"] == p) for p in ("Must", "Should", "Could")}}
    dlevel = design_info(project)["level"]
    out["design_level"] = dlevel
    ui_allowed = dlevel in ("L2", "L3")
    if not model["has_design"]:
        out["note"] = "UX Spec 문서가 없어 화면 범위를 계산하지 않았습니다. 화면 없는 DB/API 배치만 계획할 수 있습니다."
    elif not ui_allowed:
        out["note"] = "UX Spec이 승인되지 않아 화면 범위는 참고용입니다. 화면 없는 DB/API 배치만 계획할 수 있습니다(초안도 화면 없이 만듦)."
    if a.suggest or a.draft:
        b = prof["batching"]
        scr = sorted(set(scope["SCR_required"]) | set(scope["SCR_related_optional"]))
        out["groups"] = [{"key": g["key"], "screens": g["screens"]} for g in suggest_groups(model, scr, int(b["max_screens"]), int(b["min_screens"]))] if scr else []
    if a.draft:
        out["draft"] = draft(model, scope, prof, ui_allowed)
        out["next"] = f"draft를 {PLAN_JSON_REL}로 저장해 제목·목표·작업·의존성·위험 태그를 다듬고 plan-validate"
    emit(out)


def cmd_plan_validate(a) -> None:
    project = project_of(a)
    require_planning(project)
    st = load_state(project)
    prof = profile_or_block(project, required=False)
    plan = read_plan(project)
    dinfo = design_info(project)
    v = run_validate(project, st, plan, prof, dinfo)
    v.pop("_model")
    v["design"] = {k: dinfo.get(k) for k in ("level", "reason", "basis")}
    emit(v, 0 if v["ok"] else 2)


def cmd_submit(a) -> None:
    project = project_of(a)
    gate = require_planning(project)
    st = require_state(project)
    plan_st = st["plan"]
    if plan_st["status"] in ("approved", "outdated"):
        block("plan_not_editable", f"계획이 {plan_st['status']} 상태입니다. 바꾸려면 먼저 reopen plan --reason으로 다시 엽니다.")
    prof = profile_or_block(project, required=True)
    plan = read_plan(project)
    dinfo = design_info(project)
    v = run_validate(project, st, plan, prof, dinfo)
    model = v.pop("_model")
    if not v["ok"]:
        block("plan_invalid", "계획 검증에 실패했습니다. 제출하지 않았습니다.", errors=v["errors"], warnings=v["warnings"])
    md = project / PLAN_MD_REL
    if md.exists() and GENERATED_MARK not in md.read_text(encoding="utf-8"):
        block("plan_md_conflict", f"{PLAN_MD_REL}이 이미 있고 이 Skill이 만든 파일이 아닙니다. 덮어쓰지 않았습니다.")
    base = input_baseline(project, gate, dinfo)
    before = {PLAN_JSON_REL: sha_file(project / PLAN_JSON_REL), PROFILE_REL: sha_file(project / PROFILE_REL)}
    if plan_st["status"] == "awaiting_approval":
        sub = plan_st["submitted"]
        if {k: sub["hashes"].get(k) for k in before} == before and not baseline_changes(sub["inputs"], base):
            emit({"ok": True, "status": "already_submitted", "revision": plan_st["revision"], "next": next_action(st, project)})
    revision = plan_st["revision"] + 1
    write_owned(project, PLAN_MD_REL, render_md(plan, v, model, revision, base, st["waivers"], prof))
    hashes = plan_hashes(project)
    plan_st.update(status="awaiting_approval", revision=revision)
    plan_st["submitted"] = {"revision": revision, "at": now(), "hashes": hashes, "inputs": base,
                            "summary": v["derived"]["counts"], "warnings": v["warnings"]}
    add_history(st, "plan", "submitted", revision, f"배치 {v['derived']['counts']['batches']}개(자동 {v['derived']['counts']['auto']}, 사용자 {v['derived']['counts']['user']})")
    save_state(project, st)
    emit({"ok": True, "status": "awaiting_approval", "revision": revision, "document": PLAN_MD_REL, "summary": v["derived"]["counts"],
          "user_approval_batches": {k: x["approval_reasons"] for k, x in v["derived"]["batches"].items() if x["approval"] == "user"},
          "warnings": v["warnings"], "next": next_action(st, project)})


def cmd_approve(a) -> None:
    project = project_of(a)
    gate = require_planning(project)
    st = require_state(project)
    if a.target == "batch":
        return cmd_approve_batch(a, project, st)
    if a.revision is None:
        block("invalid_arguments", "approve plan에는 --revision이 필요합니다.")
    p = st["plan"]
    if p["status"] != "awaiting_approval":
        block("not_awaiting_approval", f"계획 상태가 {p['status']}입니다. 제출(submit plan)된 revision만 승인할 수 있습니다.")
    if a.revision != p["revision"]:
        block("revision_mismatch", f"승인 대상 revision은 r{p['revision']}입니다(요청: r{a.revision}).")
    if not (a.note or "").strip():
        block("approval_statement_required", "사용자의 명시적 승인 문장을 --note로 기록해야 합니다(애매한 응답은 승인이 아님).")
    cur = plan_hashes(project)
    changed = [k for k, v in p["submitted"]["hashes"].items() if cur.get(k) != v]
    if changed:
        block("changed_since_submit", "제출한 뒤 계획 파일이 바뀌었습니다. 다시 submit plan 한 뒤 승인받으세요.", paths=changed)
    dinfo = design_info(project)
    base = input_baseline(project, gate, dinfo)
    changes = baseline_changes(p["submitted"]["inputs"], base)
    if changes:
        block("inputs_changed_since_submit", "제출 이후 입력 문서(기획·디자인 승인)가 바뀌었습니다. 다시 제출해야 합니다.", changed=changes)
    prof = profile_or_block(project)
    plan = read_plan(project)
    v = run_validate(project, st, plan, prof, dinfo)
    v.pop("_model")
    if not v["ok"]:
        block("plan_invalid", "승인 시점 검증에 실패했습니다(waiver 철회 등). 승인하지 않았습니다.", errors=v["errors"])
    old = st["batches"]
    new_ids = [b["id"] for b in plan["batches"]]
    progressed = [k for k, b in old.items() if k not in new_ids and b["status"] != "planned"]
    if progressed:
        block("batch_removed_with_progress", "진행 기록이 있는 배치가 새 계획에서 빠졌습니다.", batches=progressed)
    batches = {}
    for bid in new_ids:
        x = v["derived"]["batches"][bid]
        prev = old.get(bid, {})
        # 기존 배치의 실행·검증·승인·목표 변경 기록은 보존하고, 계획에서 오는 항목만 갱신(계획 재승인으로 이력을 잃지 않음)
        batches[bid] = {**prev, "status": prev.get("status", "planned"),
                        "approval": x["approval"], "approval_reasons": x["approval_reasons"], "requires_design": x["requires_design"],
                        "design_path": x["design_path"], "waiver": x["waiver"], "depends_on": x["depends_on"],
                        "ac_targets": x["ac_targets"], "plan_revision": p["revision"]}
        if prev and prev.get("ac_targets") not in (None, x["ac_targets"]):
            batches[bid].setdefault("target_history", []).append({"at": now(), "plan_revision": p["revision"], "previous": prev["ac_targets"]})
    if p.get("approved"):
        p["last_approved"] = p["approved"]
    p["approved"] = {"revision": p["revision"], "at": now(), "hashes": cur, "inputs": base, "statement": a.note.strip(),
                     "summary": v["derived"]["counts"]}
    p["status"] = "approved"
    p["validity"] = {"status": "valid"}
    st["batches"] = batches
    add_history(st, "plan", "approved", p["revision"], a.note.strip()[:200])
    save_state(project, st)
    emit({"ok": True, "status": "approved", "revision": p["revision"], "batches": {k: {"approval": b["approval"]} for k, b in batches.items()},
          "next": next_action(st, project)})


def cmd_reopen(a) -> None:
    project = project_of(a)
    st = require_state(project)
    p = st["plan"]
    if p["status"] not in ("approved", "outdated", "awaiting_approval"):
        block("not_reopenable", f"계획 상태가 {p['status']}입니다.")
    if not a.reason.strip():
        block("reason_required", "다시 여는 사유가 필요합니다.")
    active = [k for k, b in st["batches"].items() if b["status"] in ("in_progress", "paused", "failed")]  # 실제로 진행 중인 배치만
    if active:
        block("batch_in_progress", "진행 중인 배치가 있어 계획을 다시 열 수 없습니다.", batches=active)
    prev = p["status"]
    if p.get("approved"):
        p["last_approved"] = p["approved"]
    p["approved"] = None
    p["status"] = "drafting"
    add_history(st, "plan", "reopened", p["revision"], f"{prev} → drafting: {a.reason.strip()[:200]}")
    save_state(project, st)
    emit({"ok": True, "status": "drafting", "from": prev, "next": next_action(st, project)})


def cmd_waiver(a) -> None:
    project = project_of(a)
    require_planning(project)
    st = require_state(project)
    dinfo = design_info(project)
    if a.action == "revoke":
        w = next((w for w in st["waivers"] if w["id"] == a.id), None)
        if not w:
            block("unknown_waiver", f"{a.id} waiver가 없습니다.")
        if w["status"] != "active":
            emit({"ok": True, "status": "already_revoked", "id": a.id})
        if not (a.reason or "").strip():
            block("reason_required", "철회 사유가 필요합니다.")
        w["status"] = "revoked"
        w["revoked"] = {"at": now(), "reason": a.reason.strip()}
        add_history(st, "waiver", "revoked", None, f"{a.id}: {a.reason.strip()[:200]}")
        save_state(project, st)
        emit({"ok": True, "status": "revoked", "id": a.id,
              "note": "이 waiver로 계획된 화면 배치는 execute-gate에서 차단됩니다. 계획을 다시 제출·승인해야 합니다."})
    if a.kind != "preview":
        block("unsupported_waiver", "M2.1에서 지원하는 예외는 preview(프리뷰 미승인 구현 진입)뿐입니다.")
    if dinfo["level"] == "L3":
        block("waiver_not_needed", "프리뷰가 이미 승인되어 waiver가 필요하지 않습니다.")
    if dinfo["level"] != "L2":
        block("waiver_not_allowed", f"preview waiver는 프리뷰 승인만 대신합니다. UX Spec(게이트가 켜졌으면 Design Direction 포함)이 승인되어야 합니다: {dinfo.get('reason')}",
              hint="화면 없는 DB/API 배치(non_ui)는 기획 승인만으로 계획할 수 있습니다.")
    if not (a.reason or "").strip():
        block("reason_required", "waiver 사유가 필요합니다.")
    batches = [b.strip() for b in (a.batches or "").split(",") if b.strip()]
    if not a.all_ui and not batches:
        block("scope_required", "적용 범위가 필요합니다: --batches B1,B2 또는 --all-ui")
    warnings = []
    plan = read_plan(project, required=False)
    if plan and batches:
        ids = {b.get("id") for b in plan.get("batches", []) if isinstance(b, dict)}
        unknown = [b for b in batches if b not in ids]
        if unknown:
            block("unknown_batch", f"계획에 없는 배치: {', '.join(unknown)}")
    if st["plan"]["status"] == "approved":
        warnings.append("계획이 이미 승인되었습니다. 이 waiver를 계획에 반영하려면 reopen plan → submit plan → 승인이 필요합니다.")
    record = {"id": f"WVR-{len(st['waivers']) + 1:03d}", "kind": "preview", "status": "active", "reason": a.reason.strip(),
              "statement": (a.note or "").strip(), "scope": {"all_ui": bool(a.all_ui), "batches": batches},
              "basis": {"level": dinfo["level"], **dinfo.get("basis", {})}, "approved_at": now()}
    if not a.confirm or not record["statement"]:
        emit({"ok": True, "status": "confirmation_required", "would_record": record,
              "message": "사용자에게 사유·범위·영향(시각 확인을 배치 검토로 대신, design.json의 프리뷰 상태는 그대로)을 설명하고 명시적 승인을 받은 뒤 "
                         "--note '<사용자 승인 문장>' --confirm으로 다시 실행하세요."})
    st["waivers"].append(record)
    add_history(st, "waiver", "approved", None, f"{record['id']} preview: {record['reason'][:120]} / 범위: {'모든 화면 배치' if a.all_ui else ', '.join(batches)}")
    save_state(project, st)
    emit({"ok": True, "status": "recorded", "waiver": record, "warnings": warnings,
          "note": "design.json의 프리뷰 상태는 바꾸지 않았습니다(in_progress 그대로)."})


def cmd_status(a) -> None:
    project = Path(a.project).resolve()
    st = load_state(project)
    gate = planning_gate(project)
    dinfo = design_info(project) if gate["ok"] or (project / DESIGN_STATE_REL).exists() else {"level": "L0"}
    out = {"ok": True, "build": None, "design_level": dinfo.get("level"), "design_reason": dinfo.get("reason")}
    if st:
        p = st["plan"]
        prof_ro, _ = load_profile(project)
        pbs = _plan_batches(project)
        out["needs_reverify"] = {k: w for k, b in st["batches"].items() if (w := freshness(project, prof_ro, k, b, pbs.get(k)))}
        led = L.load(project)
        out["ledger"] = {"open": {t: sum(1 for i in led["items"] if i["type"] == t and i["status"] == "open") for t in L.TYPES},
                         "blocking_open": {i["id"]: L.affected_batches(i, pbs) for i in led["items"] if i["blocking"] and i["status"] == "open"},
                         "proposals_pending": [p["id"] for p in led["proposals"] if p["status"] in ("proposed", "approved")]}
        out["build"] = {"plan": {"status": p["status"], "revision": p["revision"],
                                 "approved_revision": (p.get("approved") or {}).get("revision"),
                                 "validity": p.get("validity")},
                        "batches": {k: {"status": b["status"], "approval": b.get("approval"), "design_path": b.get("design_path"),
                                        **({"tasks_done": f"{sum(1 for x in b['run']['tasks'].values() if x['status'] == 'done')}/{len(b['run']['tasks'])}",
                                            "checkpoint": b["run"].get("checkpoint"), "failure": b["run"].get("failure"),
                                            "findings": b["run"].get("findings")} if b.get("run") else {}),
                                        **({"verification": {"run_id": b["verification"]["run_id"], "counts": b["verification"]["counts"],
                                                             "stale_reason": b["verification"].get("stale_reason")}} if b.get("verification") else {})}
                                    for k, b in st["batches"].items()},
                        "lock": read_lock(project),
                        "waivers": waiver_status(st, dinfo), "history_count": len(st["history"])}
    out["next"] = next_action(st, project)
    if a.all:
        out["planning"] = {"ok": gate["ok"], "discovery_status": gate.get("discovery_status"), "planning_status": gate.get("planning_status"),
                           "planning_approved_revision": gate.get("planning_approved_revision"), "message": gate.get("message")}
        out["design"] = {"stages": dinfo.get("stages"), "workflow": dinfo.get("workflow"), "problems": dinfo.get("problems", [])}
        bp = project / BOILERPLATE_REL
        if bp.exists():
            try:
                d = json.loads(bp.read_text(encoding="utf-8"))
                out["init"] = {"status": d.get("status"), "source": {k: (d.get("source") or {}).get(k) for k in ("ref", "commit")},
                               "verification": {k: v.get("result") for k, v in (d.get("verification") or {}).items()
                                                if isinstance(v, dict) and "result" in v}}  # product-init이 기록한 단계 결과 그대로
            except (json.JSONDecodeError, OSError):
                out["init"] = {"status": "unreadable"}
        else:
            out["init"] = None
        notes = []
        if gate.get("state_yaml_design_status") == "not_started" and any(v.get("status") == "approved" for v in (dinfo.get("stages") or {}).values()):
            notes.append("state.yaml의 design: not_started는 '기획 승인으로 디자인 단계가 열림' 표시입니다. 디자인 진행 상태는 design.json 기준입니다(이 Skill은 고치지 않음).")
        out["notes"] = notes
    emit(out)


def cmd_adopt(a) -> None:
    project = project_of(a)
    require_planning(project)
    prof = profile_or_block(project, required=False)
    model = load_model(project)
    plan = read_plan(project, required=False)
    sc = (plan or {}).get("scope") or {}
    scope = compute_scope(model, sc.get("priorities") or prof["scope"]["priorities"], sc.get("include"), (plan or {}).get("deferred"))
    out = analyze(project, model, scope, prof, plan)
    if a.save:
        write_owned(project, f"{BUILD_DIR_REL}/adopt-analysis.json", json.dumps(out | {"at": now()}, ensure_ascii=False, indent=2) + "\n")
        out["saved"] = f"{BUILD_DIR_REL}/adopt-analysis.json"
    if not a.full:
        out["screens"] = {k: {"signal": v["signal"], "candidate": v["candidate"]} for k, v in out["screens"].items()}
        out["acs"] = {k: v["evidence_level"] for k, v in out["acs"].items()}
        if out.get("components"):
            out["components"] = {"unmapped_cmp": out["components"]["unmapped_cmp"], "files": len(out["components"]["files"])}
    emit(out)


def entry_checks(project: Path, st: dict, batch_id: str, prof: dict) -> tuple[dict, dict, dict]:
    """실행 진입 공통 검사: 계획 승인·계획 파일 해시·입력 기준선·배치 존재·선행 배치·디자인 기준(waiver). (배치 상태, 계획 배치, dinfo)"""
    gate = require_planning(project)
    p = st["plan"]
    if p["status"] != "approved":
        block("plan_not_approved", f"계획이 승인되지 않았습니다(현재: {p['status']}). 승인되지 않은 계획으로는 실행 단계에 들어갈 수 없습니다.")
    cur = plan_hashes(project)
    modified = [k for k, v in p["approved"]["hashes"].items() if cur.get(k) != v]
    if modified:
        block("plan_modified", "승인된 계획 파일이 바뀌었습니다.", paths=modified)
    dinfo = design_info(project)
    changes = baseline_changes(p["approved"]["inputs"], input_baseline(project, gate, dinfo))
    if changes:
        block("inputs_changed", "계획 승인 이후 입력 문서가 바뀌었습니다. check로 outdated를 기록한 뒤 계획을 갱신하세요.", changed=changes)
    b = st["batches"].get(batch_id)
    if not b:
        block("unknown_batch", f"승인된 계획에 {batch_id} 배치가 없습니다.")
    need = DEP_LEVELS[prof["execution"]["dependency_min"]]
    pending = [d for d in b.get("depends_on", []) if st["batches"].get(d, {}).get("status") not in need]
    if not pending:
        up = upstream_problems(project, st, prof, batch_id)  # 직접·간접 선행 배치 모두(재검증 전에는 후속 배치 차단)
        if up:
            block("dependencies_not_ready", f"{batch_id}의 선행 배치 검증이 유효하지 않습니다(재검증 필요): {', '.join(up)}", pending=up)
    if not pending:
        policy_block(project, batch_id, "시작")
    if pending:
        block("dependencies_not_ready", f"{batch_id}의 선행 배치가 아직 끝나지 않았습니다({prof['execution']['dependency_min']} 이상 필요): {', '.join(pending)}",
              pending={d: st["batches"].get(d, {}).get("status") for d in pending})
    if b.get("requires_design"):
        if b.get("design_path") == "preview_approved" and dinfo["level"] != "L3":
            block("design_not_ready", "계획은 승인된 프리뷰를 기준으로 했지만 지금은 프리뷰 승인이 유효하지 않습니다.")
        if b.get("design_path") == "preview_waiver":
            w = next((w for w in st["waivers"] if w["id"] == b.get("waiver")), None)
            if not w or not waiver_valid(w, dinfo):
                block("waiver_invalid", f"{batch_id}가 기대는 preview waiver({b.get('waiver')})가 철회됐거나 기준(UX Spec·DD revision)이 바뀌었습니다.")
    plan = read_plan(project)
    pb_ = next((x for x in plan["batches"] if x.get("id") == batch_id), None)
    return b, pb_, dinfo


def waiting_policy(b: dict) -> bool:
    """차단 정책 때문에 체크포인트에서 멈춘 배치(사용자 결정 대기). 활성 배치로 세지 않아 관련 없는 독립 배치는 진행할 수 있음."""
    return b["status"] == "paused" and bool((b.get("run") or {}).get("paused_by_policy"))


def cmd_execute_gate(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, _, _ = entry_checks(project, st, a.batch, prof)
    active = [k for k, x in st["batches"].items() if x["status"] in ("in_progress", "paused", "failed") and k != a.batch and not waiting_policy(x)]
    if active:
        block("active_batch_exists", f"끝나지 않은 배치가 있습니다(활성 배치는 하나): {', '.join(active)}")
    emit({"ok": True, "batch": a.batch, "status": b["status"], "approval": b["approval"], "approval_reasons": b.get("approval_reasons"),
          "design_path": b.get("design_path"), "ac_targets": b.get("ac_targets"), "dependency_min": prof["execution"]["dependency_min"]})


def _exclude(prof: dict) -> list[str]:
    return list(prof["paths"].get("exclude") or [])


def _scope_of(pb_: dict) -> tuple[list[str], list[str]]:
    paths = pb_.get("paths") or {}
    return list(paths.get("allow") or []), list(paths.get("shared") or [])


def _require_running(project: Path, st: dict, batch: str, lock_id: str | None) -> tuple[dict, dict]:
    b = st["batches"].get(batch)
    if not b or not b.get("run"):
        block("not_running", f"{batch}는 실행 중이 아닙니다. batch-start 또는 resume을 먼저 실행하세요.")
    if b["status"] != "in_progress":
        block("not_running", f"{batch} 상태가 {b['status']}입니다. resume으로 다시 시작하세요.")
    lock = require_lock(project, batch, lock_id)
    return b, lock


def _guard_now(project: Path, st: dict, b: dict, pb_: dict, prof: dict, since: dict | None = None) -> dict:
    """시작 이후 변경과 마지막 체크포인트 이후 변경을 분류합니다."""
    run = b["run"]
    allow, shared = _scope_of(pb_)
    states = states_now(project, run, _exclude(prof))
    base_cls = classify(project, run, sorted(states), allow, shared)
    cp, prob = load_checkpoint(project, run)
    last = (cp or {}).get("states", {}) if since is None else since
    delta = diff_states(last, states)
    return {"states": states, "since_base": base_cls, "delta": delta, "checkpoint_problem": prob}


def _block_on_hard(g: dict, acted: str) -> None:
    c = g["since_base"]
    if c["protected"]:
        block("protected_path_changed", f"보호 경로(다른 Skill의 상태·승인 문서·프리뷰)가 바뀌어 {acted}하지 않았습니다. 그 변경을 되돌려야 합니다(자동으로 되돌리지 않음).",
              paths=c["protected"])
    if c["base_conflict"]:
        block("base_conflict", f"배치 시작 때 이미 미커밋 상태였던 파일(사용자·다른 세션의 작업)이 바뀌어 {acted}하지 않았습니다. 사용자 확인이 필요합니다.",
              paths=c["base_conflict"], hint="의도한 변경이면 사용자 확인 후 resume --accept-changes --note로 기록하세요. 아니면 사용자가 원래대로 되돌립니다.")


def _findings(g: dict) -> dict:
    c = g["since_base"]
    return {"out_of_scope": c["out_of_scope"], "test_changes": c["test_changes"], "files_changed": len(g["states"])}


def cmd_batch_start(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, pb_, _ = entry_checks(project, st, a.batch, prof)
    if b["status"] in ("in_progress", "paused", "failed"):
        block("already_started", f"{a.batch}는 이미 시작됐습니다({b['status']}). resume으로 이어서 합니다(작업 중복 방지).")
    if b["status"] != "planned":
        block("not_startable", f"{a.batch} 상태가 {b['status']}입니다. planned 배치만 시작할 수 있습니다.")
    active = [k for k, x in st["batches"].items() if x["status"] in ("in_progress", "paused", "failed") and not waiting_policy(x)]
    if active:
        block("active_batch_exists", f"끝나지 않은 배치가 있습니다(저장소당 활성 배치 1개): {', '.join(active)}. resume으로 마무리하세요.")
    allow, shared = _scope_of(pb_)
    if not allow:
        block("batch_paths_missing", f"{a.batch}에 수정 가능 경로(paths.allow)가 없습니다. reopen plan으로 계획에 추가하고 다시 승인받으세요.")
    if b.get("approval") == "user" and not (a.confirm_risk and (a.note or "").strip()):
        block("risk_confirmation_required", f"{a.batch}는 사용자 확인이 필요한 배치입니다. 시작 전에 범위와 위험을 설명하고 명시적 확인을 받으세요.",
              reasons=b.get("approval_reasons"), hint="확인을 받으면 batch-start --confirm-risk --note '<사용자 확인 문장>'")
    if read_lock(project) is not None:
        block("lock_held", "다른 실행의 잠금이 있습니다. 덮어쓰지 않았습니다.", lock=read_lock(project))
    head = head_sha(project)
    exclude = _exclude(prof)
    run = {"batch": a.batch, "started_at": now(), "owner": a.owner or "", "plan_revision": st["plan"]["revision"],
           "base": {"head": head, "branch": (git_lines(project, "branch", "--show-current") or [""])[0],
                    "dirty": changed_vs(project, head, exclude)},
           "tasks": {t["id"]: {"status": "pending", "files": [], "at": None, "note": ""} for t in task_order(pb_)},
           "attempts": {}, "failure": None, "confirmations": [], "findings": {}, "checkpoint": None, "submitted": None}
    if b.get("approval") == "user":
        run["confirmations"].append({"kind": "risk", "note": a.note.strip(), "at": now(), "reasons": b.get("approval_reasons")})
    overlap = sorted(x for x in run["base"]["dirty"] if in_patterns(x, allow) or in_patterns(x, shared))
    if overlap:
        if not (a.allow_dirty_in_scope and (a.note or "").strip()):
            block("uncommitted_in_scope", f"배치 수정 범위 안에 커밋되지 않은 파일이 {len(overlap)}개 있습니다. 이 파일들을 고치면 사용자·다른 세션의 작업과 구분할 수 없습니다.",
                  paths=overlap[:50], hint="먼저 커밋하는 것을 권장합니다. 사용자가 이 파일들을 배치 작업 대상으로 확인하면 batch-start --allow-dirty-in-scope --note '<사용자 확인 문장>'")
        run["base"]["dirty_in_scope_accepted"] = overlap
        run["confirmations"].append({"kind": "dirty_in_scope", "note": a.note.strip(), "at": now(), "count": len(overlap)})
    lock = acquire_lock(project, a.batch, a.owner or "")
    try:
        ensure_gitignore(project)
        save_base_tests(project, run)
        write_checkpoint(project, run, run["tasks"], {}, "시작")
        b["status"] = "in_progress"
        b["run"] = run
        add_history(st, "batch", "started", st["plan"]["revision"], f"{a.batch} (잠금 {lock['lock_id']}, base {head[:7]}, 미커밋 {len(run['base']['dirty'])}개)")
        save_state(project, st)
    except Exception:
        release_lock(project, lock["lock_id"])
        raise
    branch = run["base"]["branch"]
    out = {"ok": True, "status": "in_progress", "batch": a.batch, "lock_id": lock["lock_id"], "base_head": head[:7],
           "preserved_uncommitted": sorted(run["base"]["dirty"]), "allowed_paths": {"allow": allow, "shared": shared},
           "tasks": [{"id": t["id"], "layer": t.get("layer"), "title": t.get("title"), "refs": t.get("refs", []), "depends_on": t.get("depends_on", [])} for t in task_order(pb_)],
           "next_task": next_task(run["tasks"], task_order(pb_)), "components": pb_.get("components"), "acs": pb_.get("acs"),
           "note": "구현 완료는 검증·승인 완료가 아닙니다(M2.3·M2.4). git add/commit/push는 하지 않습니다."}
    if branch in ("main", "master", "develop", ""):
        out["branch_recommendation"] = f"현재 브랜치({branch or '분리된 HEAD'})에서 작업합니다. 배치별 브랜치를 권장합니다(예: git switch -c build/{a.batch.lower()}) — 자동으로 만들지 않습니다."
    emit(out)


def _complete_step(project: Path, st: dict, b: dict, pb_: dict, prof: dict, lock: dict, note: str, task: str | None) -> dict:
    run = b["run"]
    g = _guard_now(project, st, b, pb_, prof)
    if g["checkpoint_problem"]:
        block("checkpoint_corrupt", f"체크포인트를 믿을 수 없습니다({g['checkpoint_problem']}). 진행을 기록하지 않았습니다. resume --restore-checkpoint로 복구하세요.")
    _block_on_hard(g, "기록")
    if task:
        run["tasks"][task].update(status="done", files=g["delta"], at=now(), note=note)
    run["findings"] = _findings(g)
    write_checkpoint(project, run, run["tasks"], g["states"], note or (f"{task} 완료" if task else "체크포인트"))
    items = L.blocking_for(L.load(project), b["run"]["batch"], _plan_batches(project))
    if items:  # 실행 중에 새 차단 정책이 생기면, 방금 남긴 체크포인트에서 안전하게 멈춤
        b["status"] = "paused"
        run["paused_by_policy"] = [i["id"] for i in items]
        release_lock(project, lock["lock_id"])
        add_history(st, "batch", "paused_by_policy", None, f"{run['batch']}: {', '.join(run['paused_by_policy'])}")
        g["paused_by_policy"] = run["paused_by_policy"]
        return g
    heartbeat(project, lock)
    return g


def cmd_task_done(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, lock = _require_running(project, st, a.batch, a.lock)
    pb_ = next(x for x in read_plan(project)["batches"] if x.get("id") == a.batch)
    run = b["run"]
    t = run["tasks"].get(a.task)
    if t is None:
        block("unknown_task", f"{a.batch}에 {a.task} 작업이 없습니다.")
    if t["status"] == "done":
        emit({"ok": True, "status": "already_done", "task": a.task, "next_task": next_task(run["tasks"], task_order(pb_)),
              "note": "이미 완료로 기록된 작업입니다(다시 하지 않음)."})
    deps = [d for d in next(x for x in task_order(pb_) if x["id"] == a.task).get("depends_on") or [] if d in run["tasks"] and run["tasks"][d]["status"] != "done"]
    if deps:
        block("task_deps_pending", f"{a.task}의 선행 작업이 끝나지 않았습니다: {', '.join(deps)}")
    g = _complete_step(project, st, b, pb_, prof, lock, a.note or "", a.task)
    add_history(st, "batch", "task_done", None, f"{a.batch}/{a.task}: 파일 {len(g['delta'])}개")
    save_state(project, st)
    f = run["findings"]
    if g.get("paused_by_policy"):
        emit({"ok": True, "task": a.task, "status": "paused", "paused_by_policy": g["paused_by_policy"],
              "message": "작업은 기록했고, 이 배치에 영향을 주는 차단 정책이 생겨 체크포인트에서 멈췄습니다(잠금 해제). 사용자 결정(decide) 후 resume합니다."})
    emit({"ok": True, "task": a.task, "files": g["delta"], "out_of_scope": f["out_of_scope"],
          "test_changes_need_confirmation": [x for x in f["test_changes"] if x["needs_confirmation"]],
          "done": sum(1 for x in run["tasks"].values() if x["status"] == "done"), "total": len(run["tasks"]),
          "next_task": next_task(run["tasks"], task_order(pb_))})


def cmd_checkpoint(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, lock = _require_running(project, st, a.batch, a.lock)
    pb_ = next(x for x in read_plan(project)["batches"] if x.get("id") == a.batch)
    g = _complete_step(project, st, b, pb_, prof, lock, a.note or "", None)
    save_state(project, st)
    emit({"ok": True, "checkpoint": b["run"]["checkpoint"], "files_since_previous": g["delta"], "findings": b["run"]["findings"]}
         | ({"status": "paused", "paused_by_policy": g["paused_by_policy"]} if g.get("paused_by_policy") else {}))


def cmd_check_run(a) -> None:
    """프로필의 검증 단계를 실행해 재시도 횟수만 셉니다(같은 단계 연속 실패 max_retries회면 중단). 검증 증거(M2.3)로 쓰지 않습니다."""
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, lock = _require_running(project, st, a.batch, a.lock)
    cur = plan_hashes(project)
    if any(cur.get(k) != v for k, v in st["plan"]["approved"]["hashes"].items()):
        block("plan_modified", "승인된 계획·프로필이 바뀌었습니다. 승인된 프로필의 명령만 실행합니다.")
    step = next((s for s in prof["verify"]["steps"] if s.get("name") == a.step), None)
    if not step:
        block("unknown_step", f"프로필 verify.steps에 {a.step}이 없습니다(임의 명령은 실행하지 않음).")
    avail = {x.strip() for x in (a.available or "").split(",") if x.strip()}
    missing = [r for r in step.get("requires", []) if r not in avail]
    run = b["run"]
    if missing:
        emit({"ok": True, "status": "not_run", "step": a.step, "missing_environment": missing,
              "note": "필요한 환경이 없어 실행하지 않았습니다(통과로 세지 않음, 재시도 횟수에도 넣지 않음)."})
    rec = run["attempts"].setdefault(a.step, {"consecutive_failures": 0, "total": 0, "last": None})
    n = rec["total"] + 1
    log_rel = f"{EVIDENCE_REL}/{a.batch}/attempts/{a.step}-{n:02d}.log"
    timeout = int(step.get("timeout") or prof["execution"]["step_timeout_seconds"])
    rep_dir = project / EVIDENCE_REL / a.batch / "attempts" / f"{a.step}-{n:02d}-reports"
    rep_dir.mkdir(parents=True, exist_ok=True)  # 리포트를 쓰는 단계가 저장소에 파일을 남기지 않도록(Git 제외 경로)
    env = dict(__import__("os").environ, PB_REPORT_DIR=str(rep_dir), PB_RUN_ID=f"attempt-{a.step}-{n:02d}", PB_BATCH=a.batch)
    try:
        p = subprocess.run(step["run"], shell=True, cwd=project / step.get("cwd", "."), capture_output=True, text=True, timeout=timeout, env=env)
        code, text = p.returncode, (p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        code, text = 124, f"timeout {timeout}s\n{(e.stdout or '')}{(e.stderr or '')}"
    write_owned(project, log_rel, text if isinstance(text, str) else str(text))
    tail = "\n".join(str(text).splitlines()[-40:])
    rec["total"] = n
    rec["last"] = {"at": now(), "exit": code, "log": log_rel, "task": a.task}
    out = {"ok": True, "step": a.step, "exit": code, "log": log_rel, "tail": tail,
           "note": "재시도 계산용 실행입니다. 검증 완료 기록이 아닙니다(M2.3)."}
    if code == 0:
        rec["consecutive_failures"] = 0
        out["status"] = "passed"
    else:
        rec["consecutive_failures"] += 1
        limit = prof["execution"]["max_retries"]
        out.update(status="failed", consecutive_failures=rec["consecutive_failures"], limit=limit)
        if rec["consecutive_failures"] >= limit:
            g = _guard_now(project, st, b, read_plan_batch(project, a.batch), prof)
            run["failure"] = {"at": now(), "step": a.step, "task": a.task, "attempts": rec["consecutive_failures"], "exit": code,
                              "log": log_rel, "tail": tail[-2000:], "reason": a.reason or "같은 검증 단계 연속 실패 한도 초과"}
            write_checkpoint(project, run, run["tasks"], g["states"], f"실패 한도 초과: {a.step}")
            b["status"] = "failed"
            release_lock(project, lock["lock_id"])
            add_history(st, "batch", "failed", None, f"{a.batch}: {a.step} 연속 {rec['consecutive_failures']}회 실패")
            save_state(project, st)
            emit(out | {"ok": False, "error": "retry_limit_exceeded", "status": "failed",
                        "message": f"{a.step}이 연속 {rec['consecutive_failures']}회 실패해 배치를 멈췄습니다. 원인과 마지막 상태를 기록했습니다. 더 고치지 말고 사용자에게 보고하세요.",
                        "next": "사용자 결정 후 resume --retry-failed --note '<사용자 결정>'"}, 2)
    heartbeat(project, lock)
    save_state(project, st)
    emit(out)


def read_plan_batch(project: Path, batch: str) -> dict:
    return next(x for x in read_plan(project)["batches"] if x.get("id") == batch)


def cmd_batch_submit(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, lock = _require_running(project, st, a.batch, a.lock)
    pb_ = read_plan_batch(project, a.batch)
    run = b["run"]
    pend = [k for k, v in run["tasks"].items() if v["status"] != "done"]
    if pend:
        block("tasks_pending", f"끝나지 않은 작업이 있습니다: {', '.join(pend)}")
    g = _guard_now(project, st, b, pb_, prof)
    if g["checkpoint_problem"]:
        block("checkpoint_corrupt", f"체크포인트를 믿을 수 없습니다({g['checkpoint_problem']}). resume --restore-checkpoint로 복구하세요.")
    _block_on_hard(g, "제출")
    tests = [x for x in g["since_base"]["test_changes"] if x["needs_confirmation"]]
    if tests and not (a.confirm_test_changes and (a.note or "").strip()):
        block("test_changes_need_confirmation", "기존 테스트가 삭제·약화·수정되었습니다. 사용자 확인 없이 제출하지 않습니다.", test_changes=tests,
              hint="변경 이유를 사용자에게 설명하고 확인을 받으면 batch-submit --confirm-test-changes --note '<사용자 확인 문장>'")
    if tests:
        run["confirmations"].append({"kind": "test_changes", "note": a.note.strip(), "at": now(), "paths": [x["path"] for x in tests]})
    run["findings"] = _findings(g)
    write_checkpoint(project, run, run["tasks"], g["states"], "구현 완료 제출")
    run["submitted"] = {"at": now(), "files": g["states"], "out_of_scope": g["since_base"]["out_of_scope"], "test_changes": g["since_base"]["test_changes"],
                        "meaning": "구현 완료(implemented). 검증 완료·승인 완료가 아닙니다."}
    b["status"] = "implemented"
    release_lock(project, lock["lock_id"])
    add_history(st, "batch", "implemented", None, f"{a.batch}: 파일 {len(g['states'])}개, 범위 밖 {len(g['since_base']['out_of_scope'])}개")
    save_state(project, st)
    need = DEP_LEVELS[prof["execution"]["dependency_min"]]
    ready = [k for k, x in st["batches"].items() if x["status"] == "planned" and all(st["batches"].get(d, {}).get("status") in need for d in x.get("depends_on", []))]
    emit({"ok": True, "status": "implemented", "batch": a.batch, "files_changed": len(g["states"]), "out_of_scope": g["since_base"]["out_of_scope"],
          "next_batches": [{"batch": k, "needs_user_confirmation": st["batches"][k]["approval"] == "user", "reasons": st["batches"][k].get("approval_reasons")} for k in ready],
          "next": f"verify --batch {a.batch}로 AC 검증(선행 조건이 verified면 검증 뒤에 의존 배치를 시작할 수 있음)",
          "note": "구현 완료로만 기록했습니다(검증·승인 아님). 커밋은 사용자가 합니다."})


def cmd_pause(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    b, lock = _require_running(project, st, a.batch, a.lock)
    pb_ = read_plan_batch(project, a.batch)
    g = _guard_now(project, st, b, pb_, prof)
    b["run"]["findings"] = _findings(g)
    write_checkpoint(project, b["run"], b["run"]["tasks"], g["states"], a.note or "일시 중지")
    b["status"] = "paused"
    release_lock(project, lock["lock_id"])
    add_history(st, "batch", "paused", None, f"{a.batch}: {a.note or ''}")
    save_state(project, st)
    emit({"ok": True, "status": "paused", "batch": a.batch, "protected_changed": g["since_base"]["protected"],
          "next_task": next_task(b["run"]["tasks"], task_order(pb_)), "next": "/product-build resume"})


def cmd_resume(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    cands = [k for k, x in st["batches"].items() if x["status"] in ("in_progress", "paused", "failed")]
    if a.batch and not cands and st["batches"].get(a.batch, {}).get("status") in ("verify_failed", "stale"):
        cands = [a.batch]  # 검증 실패·재검증 필요 배치를 고치러 다시 엶(배치를 지정할 때만)
    if a.batch:
        cands = [k for k in cands if k == a.batch]
    if not cands:
        block("nothing_to_resume", "이어서 할 배치가 없습니다(in_progress·paused·failed 없음). 다음 배치는 batch-start로 시작합니다.")
    bid = cands[0]
    b = st["batches"][bid]
    run = b["run"]
    pb_ = read_plan_batch(project, bid)
    entry_checks(project, st, bid, prof)  # 계획·입력 기준선이 그대로인지(바뀌었으면 재개하지 않음), 차단 정책 포함
    note = (a.note or "").strip()
    # 1) 잠금
    lock = read_lock(project)
    takeover = None
    if isinstance(lock, dict) and lock.get("batch") != bid and st["batches"].get(lock.get("batch"), {}).get("status") == "in_progress":
        block("active_batch_exists", f"다른 배치({lock.get('batch')})가 실행 중입니다. 그 배치를 끝내거나 멈춘 뒤 재개하세요(동시 실행은 한 배치).", lock=lock)
    if lock is not None:
        if True:  # 남은 잠금은 상태와 관계없이 넘겨받기 절차로만 처리(자동 삭제 없음)
            age = lock_age_minutes(lock) if isinstance(lock, dict) else float("inf")
            info = lock if isinstance(lock, dict) else {"corrupt": True}
            if not a.take_over:
                block("lock_active" if age < prof["execution"]["lock_ttl_minutes"] else "lock_stale",
                      "잠금이 남아 있습니다. 다른 세션이 실행 중일 수 있어 자동으로 지우지 않았습니다.", lock=info, age_minutes=round(age, 1),
                      ttl_minutes=prof["execution"]["lock_ttl_minutes"],
                      hint="다른 세션이 없음을 확인하면 resume --take-over. 갱신이 최근(TTL 이내)이면 사용자 확인 문장(--note)도 필요합니다.")
            if age < prof["execution"]["lock_ttl_minutes"] and not note:
                block("lock_active_confirmation_required", "최근에 갱신된 잠금입니다. 다른 세션이 실행 중이 아님을 사용자가 확인해야 넘겨받을 수 있습니다.", lock=info)
            takeover = {"from": info, "age_minutes": round(age, 1), "note": note, "at": now()}
            # 잠금은 아래 검사(체크포인트·외부 변경)를 모두 통과한 뒤에만 넘겨받습니다(검사에서 멈추면 잠금은 그대로)
    # 2) 체크포인트
    cp, prob = load_checkpoint(project, run)
    if prob:
        if a.restore_checkpoint == "prev":
            cp, p2 = load_checkpoint(project, run, "prev")
            if p2:
                block("checkpoint_unrecoverable", f"이전 체크포인트도 쓸 수 없습니다({p2}). --restore-checkpoint rebuild로 복구하세요.")
        elif a.restore_checkpoint == "rebuild":
            if not note:
                block("confirmation_required", "체크포인트 재구성은 시작 이후 모든 변경을 배치 작업으로 받아들입니다. 사용자 확인 문장(--note)이 필요합니다.")
            cp = {"states": states_now(project, run, _exclude(prof)), "tasks": {k: v["status"] for k, v in run["tasks"].items()}}
            run["confirmations"].append({"kind": "checkpoint_rebuild", "note": note, "at": now(), "problem": prob})
        else:
            _, p2 = load_checkpoint(project, run, "prev")
            block("checkpoint_corrupt", f"체크포인트를 믿을 수 없습니다({prob}). 자동으로 고치지 않았습니다.",
                  options=(["--restore-checkpoint prev(직전 체크포인트, 그 이후 변경은 외부 변경으로 보고)"] if not p2 else [])
                  + ["--restore-checkpoint rebuild --note '<사용자 확인>'(현재 파일을 기준으로 다시 만듦)"])
        # 작업 상태는 build.json이 기준. 체크포인트와 다르면 보고
        mism = {k: (v, run["tasks"].get(k, {}).get("status")) for k, v in (cp.get("tasks") or {}).items() if run["tasks"].get(k, {}).get("status") != v}
        if mism and a.restore_checkpoint == "prev":
            run.setdefault("notes", []).append(f"이전 체크포인트와 작업 상태 차이(상태 파일 기준 유지): {mism}")
    # 3) 실패 배치
    if b["status"] == "failed":
        if not (a.retry_failed and note):
            block("failed_needs_decision", "재시도 한도를 넘어 멈춘 배치입니다. 사용자 결정 없이 다시 시도하지 않습니다.", failure=run.get("failure"),
                  hint="사용자가 원인과 방향을 정하면 resume --retry-failed --note '<사용자 결정>'")
        step = (run.get("failure") or {}).get("step")
        if step and step in run["attempts"]:
            run["attempts"][step]["consecutive_failures"] = 0
        run["confirmations"].append({"kind": "retry_failed", "note": note, "at": now(), "failure": run.get("failure")})
        run["failure"] = None
    # 4) 마지막 체크포인트 이후 변경(외부 변경) 확인
    states = states_now(project, run, _exclude(prof))
    delta = diff_states(cp.get("states", {}), states)
    cls = classify(project, run, delta, *_scope_of(pb_))
    if cls["protected"]:
        block("protected_path_changed", "마지막 체크포인트 이후 보호 경로가 바뀌었습니다. 되돌린 뒤 재개하세요(받아들일 수 없음).", paths=cls["protected"])
    if delta and a.restore_checkpoint != "rebuild":
        if not (a.accept_changes and note):
            block("external_changes", "마지막 체크포인트 이후 파일이 바뀌었습니다(다른 세션·사용자·중단 직전 작업). 덮어쓰지 않았습니다.",
                  changed=delta, classification={k: v for k, v in cls.items() if v},
                  hint="내용을 확인해 이 배치 작업으로 받아들이려면 사용자 확인 후 resume --accept-changes --note '<확인 문장>'. 아니면 사용자가 정리합니다.")
        run["confirmations"].append({"kind": "accepted_changes", "note": note, "at": now(), "paths": delta})
    # 5) 잠금 다시 잡기·재개
    if takeover:
        cur = read_lock(project)
        if cur != takeover["from"] and not (isinstance(cur, dict) and isinstance(takeover["from"], dict) and cur.get("lock_id") == takeover["from"].get("lock_id")):
            block("lock_changed", "확인하는 동안 잠금이 바뀌었습니다(다른 세션이 움직이는 중). 넘겨받지 않았습니다.", lock=cur)
        (project / LOCK_REL).unlink()
    new_lock = acquire_lock(project, bid, a.owner or "")
    try:
        if takeover:
            run.setdefault("takeovers", []).append(takeover)
        b["status"] = "in_progress"
        if run.get("paused_by_policy"):
            run.setdefault("policy_pauses", []).append({"items": run.pop("paused_by_policy"), "resumed_at": now()})
        write_checkpoint(project, run, run["tasks"], states, "재개")
        add_history(st, "batch", "resumed", None, f"{bid}" + (" (잠금 넘겨받음)" if takeover else ""))
        save_state(project, st)
    except Exception:
        release_lock(project, new_lock["lock_id"])
        raise
    emit({"ok": True, "status": "in_progress", "batch": bid, "lock_id": new_lock["lock_id"],
          "done": [k for k, v in run["tasks"].items() if v["status"] == "done"],
          "next_task": next_task(run["tasks"], task_order(pb_)), "took_over": bool(takeover),
          "allowed_paths": dict(zip(("allow", "shared"), _scope_of(pb_)))})


def cmd_guard(a) -> None:
    project = project_of(a)
    if a.batch:
        st = require_state(project)
        prof = profile_or_block(project)
        b = st["batches"].get(a.batch)
        if not b or not b.get("run"):
            block("not_running", f"{a.batch}는 시작된 적이 없습니다.")
        g = _guard_now(project, st, b, read_plan_batch(project, a.batch), prof)
        c = g["since_base"]
        ok = not c["protected"] and not c["base_conflict"]
        emit({"ok": ok, "batch": a.batch, "since_base": c, "since_checkpoint": g["delta"], "checkpoint_problem": g["checkpoint_problem"],
              **({} if ok else {"error": "guard_violation"})}, 0 if ok else 2)
    paths = list(a.path or [])
    if a.base:
        paths += git_lines(project, "diff", "--name-only", a.base)
        paths += git_lines(project, "ls-files", "--others", "--exclude-standard")
    violations = sorted({x for x in paths if is_protected(x)})
    out = {"ok": not violations, "checked": len(set(paths)), "protected_changed": violations}
    if violations:
        out.update(error="protected_path_changed", message="다른 Skill 소유의 상태·승인 문서·프리뷰가 바뀌었습니다. 구현 배치에서 이 경로를 바꾸면 안 됩니다.")
    emit(out, 0 if out["ok"] else 2)


DONE_STATES = ("verified", "approved")


def effective_targets(b: dict) -> dict:
    """계획 승인 때의 AC 목표(ac_targets)에 사용자 승인된 변경(target_overrides)을 순서대로 적용한 값. 원래 기록은 바꾸지 않습니다."""
    t = dict(b.get("ac_targets") or {})
    for o in b.get("target_overrides", []):
        t[o["ac"]] = o["to"]
    return t


def freshness(project: Path, prof: dict, bid: str, b: dict, plan_batch: dict | None) -> str | None:
    """verified·approved 배치의 증거가 아직 유효한지. 무효화 사유를 돌려줍니다(None이면 유효)."""
    v = b.get("verification") or {}
    if b["status"] not in DONE_STATES:
        return None
    if load_run(project, v) is None:
        return "검증 실행 원본(run.json)이 없거나 digest가 맞지 않습니다(증거 유실·조작 의심)"
    if plan_batch is None:
        return "계획에서 배치를 찾을 수 없습니다"
    case_files = v.get("case_files", [])
    scope = batch_scope_files(project, prof, plan_batch, b, case_files)
    if tree_hash(project, scope) != v.get("scope_tree"):
        return "검증 이후 배치 범위의 코드·테스트가 바뀌었습니다"
    if "deps" in v and deps_affecting(deps_tree(project, prof), scope) != v["deps"]:
        return "검증 이후 이 배치에 영향을 주는 의존성 파일(lockfile 등)이 바뀌었습니다"
    return None


def ancestors(st: dict, bid: str) -> list[str]:
    seen, stack = [], list(st["batches"].get(bid, {}).get("depends_on", []))
    while stack:
        x = stack.pop()
        if x not in seen and x in st["batches"]:
            seen.append(x)
            stack.extend(st["batches"][x].get("depends_on", []))
    return seen


def upstream_problems(project: Path, st: dict, prof: dict, bid: str, pbs: dict | None = None) -> dict:
    """선행(전이) 배치 중 검증이 유효하지 않은 것 → 사유."""
    pbs = pbs if pbs is not None else _plan_batches(project)
    need = DEP_LEVELS[prof["execution"]["dependency_min"]]
    out = {}
    for d in ancestors(st, bid):
        x = st["batches"][d]
        if x["status"] not in need:
            out[d] = f"상태 {x['status']}"
        elif prof["execution"]["dependency_min"] != "implemented":
            w = freshness(project, prof, d, x, pbs.get(d))
            if w:
                out[d] = w
    return out


def _plan_batches(project: Path) -> dict:
    plan = read_plan(project, required=False) or {}
    return {x.get("id"): x for x in plan.get("batches", []) if isinstance(x, dict)}


def _invalidate_approval(b: dict, why: str) -> None:
    for ap in b.get("approvals", []):
        if ap.get("valid"):
            ap["valid"] = False
            ap.setdefault("invalidations", []).append({"at": now(), "reason": why})  # 이력은 지우지 않고 무효 표시만 덧붙임


def mark_stale(project: Path, st: dict, prof: dict) -> dict:
    """verified·approved 배치 중 증거가 무효가 된 것을 stale로 기록합니다(이 Skill의 상태 파일만 씀). 승인 기록은 무효 표시만."""
    pbs = _plan_batches(project)
    changed = {}
    for bid, b in st["batches"].items():
        why = freshness(project, prof, bid, b, pbs.get(bid))
        if why:
            if b["status"] == "approved":
                _invalidate_approval(b, why)
            b["status"] = "stale"
            b["verification"]["stale_reason"] = why
            b["verification"]["stale_at"] = now()
            add_history(st, "batch", "stale", None, f"{bid}: {why}")
            changed[bid] = why
    return changed


def cmd_impact(a) -> None:
    """변경 영향(읽기 전용): 증거가 무효가 된 배치(직접 영향)와, 그 배치에 기대는 후속 배치(차단)."""
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    pbs = _plan_batches(project)
    direct = {}
    for bid, b in st["batches"].items():
        w = freshness(project, prof, bid, b, pbs.get(bid))
        if w:
            direct[bid] = w
        elif b["status"] == "stale":
            direct[bid] = (b.get("verification") or {}).get("stale_reason", "재검증 필요")
    blocked = {}
    for bid in st["batches"]:
        up = [x for x in ancestors(st, bid) if x in direct]
        if up and bid not in direct:
            blocked[bid] = up
    unaffected = [k for k, b in st["batches"].items() if b["status"] in DONE_STATES and k not in direct and k not in blocked]
    emit({"ok": True, "reverify": direct, "downstream_blocked": blocked, "unaffected_verified": unaffected,
          "next": ("verify --batch로 직접 영향 배치만 다시 검증합니다(후속 배치는 그 뒤 진행). 영향 없는 배치는 다시 검증하지 않습니다."
                   if direct else "재검증이 필요한 배치가 없습니다.")})


def cmd_approve_batch(a, project: Path, st: dict) -> None:
    prof = profile_or_block(project)
    b = st["batches"].get(a.batch or "")
    if not b:
        block("unknown_batch", "승인할 배치(--batch)가 없습니다.")
    if not (a.note or "").strip():
        block("approval_statement_required", "사용자의 명시적 승인 문장을 --note로 기록해야 합니다.")
    if b["status"] == "approved":
        emit({"ok": True, "status": "already_approved", "batch": a.batch})
    if b["status"] != "verified":
        block("not_verified", f"{a.batch} 상태가 {b['status']}입니다. 자동 검증(verified)을 통과한 배치만 최종 승인할 수 있습니다(검증과 승인은 별개).")
    pbs = _plan_batches(project)
    w = freshness(project, prof, a.batch, b, pbs.get(a.batch))
    if w:
        block("verification_stale", f"검증 이후 바뀐 것이 있어 승인할 수 없습니다: {w}. 다시 검증하세요.")
    policy_block(project, a.batch, "최종 승인")
    up = upstream_problems(project, st, prof, a.batch, pbs)
    if up:
        block("upstream_not_verified", "선행 배치의 검증이 유효하지 않아 승인할 수 없습니다.", upstream=up)
    v = b["verification"]
    b.setdefault("approvals", []).append({"at": now(), "statement": a.note.strip(), "run_id": v["run_id"], "scope_tree": v["scope_tree"],
                                         "targets": effective_targets(b), "valid": True})
    b["status"] = "approved"
    add_history(st, "batch", "approved", None, f"{a.batch}: {a.note.strip()[:200]}")
    save_state(project, st)
    emit({"ok": True, "status": "approved", "batch": a.batch, "run_id": v["run_id"],
          "note": "최종 사용자 승인으로 기록했습니다(자동 검증과 별개). 이후 범위 코드가 바뀌면 승인 기록은 남기고 무효로 표시합니다."})


def cmd_adopt_register(a) -> None:
    """기존 구현을 배치 결과로 등록(imported). 구현 이력이 아니라 '이미 있는 코드'로 기록하고, 그 뒤 E2부터 검증합니다."""
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    if st["plan"]["status"] != "approved":
        block("plan_not_approved", "승인된 계획이 필요합니다.")
    b = st["batches"].get(a.batch)
    if not b:
        block("unknown_batch", f"{a.batch}가 없습니다.")
    if b["status"] != "planned":
        block("not_registerable", f"{a.batch} 상태가 {b['status']}입니다. 시작하지 않은 배치만 기존 구현으로 등록합니다.")
    if not (a.note or "").strip():
        block("confirmation_required", "기존 구현이 이 배치를 충족한다는 사용자 확인 문장(--note)이 필요합니다.")
    if read_lock(project) is not None:
        block("active_batch_exists", "실행 중인 배치가 있어 등록하지 않았습니다.", lock=read_lock(project))
    pb_ = read_plan_batch(project, a.batch)
    pats = list((pb_.get("paths") or {}).get("allow") or []) + list((pb_.get("paths") or {}).get("shared") or [])
    if not pats:
        block("batch_paths_missing", "계획에 이 배치의 수정 범위(paths)가 없습니다.")
    files = {f: sha_file(project / f) for f in tracked_files(project, list(prof["paths"].get("exclude") or [])) if in_patterns(f, pats)}
    if not files:
        block("no_existing_code", "배치 범위에 기존 파일이 없습니다. 기존 구현이 아니면 batch-start로 구현합니다.")
    head = head_sha(project)
    dirty = changed_vs(project, head, list(prof["paths"].get("exclude") or []))
    run = {"batch": a.batch, "started_at": now(), "owner": a.owner or "", "plan_revision": st["plan"]["revision"],
           "base": {"head": head, "branch": (git_lines(project, "branch", "--show-current") or [""])[0], "dirty": dirty,
                    "dirty_in_scope_accepted": sorted(x for x in dirty if in_patterns(x, pats))},  # 등록 확인 문장으로 기존 파일을 배치 대상에 포함
           "tasks": {}, "attempts": {}, "failure": None,
           "confirmations": [{"kind": "adopt", "note": a.note.strip(), "at": now(), "files": len(files)}], "findings": {}, "checkpoint": None,
           "submitted": {"at": now(), "files": files, "kind": "adopt", "meaning": "기존 구현 등록(구현 이력·검증·승인 아님)"}}
    ensure_gitignore(project)
    save_base_tests(project, run)
    write_checkpoint(project, run, run["tasks"], {}, "기존 구현 등록")
    b["run"] = run
    b["status"] = "imported"
    add_history(st, "batch", "imported", None, f"{a.batch}: 기존 파일 {len(files)}개 등록 — {a.note.strip()[:120]}")
    save_state(project, st)
    emit({"ok": True, "status": "imported", "batch": a.batch, "files": len(files),
          "next": f"verify --batch {a.batch}로 E2 증거부터 확보합니다. 목표 E3 AC는 실제 결함 수정 이력이 없으면 insufficient로 남습니다."})


def cmd_target(a) -> None:
    """AC 목표 증거 수준 변경(사용자 승인 필수). 자동으로 낮추지 않습니다. 원래 목표와 변경 이력은 남습니다."""
    project = project_of(a)
    st = require_state(project)
    b = st["batches"].get(a.batch)
    if not b or a.ac not in (b.get("ac_targets") or {}):
        block("unknown_ac", f"{a.batch}의 AC 목표에 {a.ac}가 없습니다.")
    if a.level not in ("E1", "E2", "E3"):
        block("invalid_level", "목표는 E1·E2·E3 중 하나입니다.")
    if not (a.note or "").strip() or not (a.reason or "").strip():
        block("approval_statement_required", "목표 변경은 사유(--reason)와 사용자 승인 문장(--note)이 필요합니다(자동 변경 없음).")
    cur = effective_targets(b)[a.ac]
    if cur == a.level:
        emit({"ok": True, "status": "unchanged", "ac": a.ac, "target": cur})
    b.setdefault("target_overrides", []).append({"ac": a.ac, "from": cur, "to": a.level, "reason": a.reason.strip(), "statement": a.note.strip(), "at": now()})
    if b["status"] in DONE_STATES:
        if b["status"] == "approved":
            _invalidate_approval(b, f"{a.ac} 목표 변경 {cur}→{a.level}")
        b["status"] = "stale"
        b["verification"].update(stale_reason=f"{a.ac} 목표 변경({cur}→{a.level})", stale_at=now())
    add_history(st, "batch", "target_changed", None, f"{a.batch}/{a.ac}: {cur}→{a.level} — {a.reason.strip()[:120]}")
    save_state(project, st)
    emit({"ok": True, "ac": a.ac, "from": cur, "to": a.level, "status": b["status"], "next": f"verify --batch {a.batch}"})


def cmd_accept_fi(a) -> None:
    """특정 AC에 한해 결함 주입 증거를 목표 E3 충족으로 인정(사용자 승인 필수). 실제 결함 수정 이력과는 계속 구분해 기록합니다."""
    project = project_of(a)
    st = require_state(project)
    b = st["batches"].get(a.batch)
    if not b or a.ac not in (b.get("ac_targets") or {}):
        block("unknown_ac", f"{a.batch}의 AC 목표에 {a.ac}가 없습니다.")
    if not (a.note or "").strip():
        block("approval_statement_required", "결함 주입 증거 인정은 사용자 승인 문장(--note)이 필요합니다.")
    b.setdefault("fi_accepted", {})[a.ac] = {"statement": a.note.strip(), "at": now()}
    if b["status"] in DONE_STATES:
        if b["status"] == "approved":
            _invalidate_approval(b, f"{a.ac} 증거 기준 변경")
        b["status"] = "stale"
        b["verification"].update(stale_reason=f"{a.ac} 증거 기준 변경(결함 주입 인정)", stale_at=now())
    add_history(st, "batch", "fault_injection_accepted", None, f"{a.batch}/{a.ac}: {a.note.strip()[:120]}")
    save_state(project, st)
    emit({"ok": True, "ac": a.ac, "status": b["status"], "next": f"verify --batch {a.batch}",
          "note": "결함 주입 증거는 '실제 결함 수정'과 별도 유형으로 계속 기록됩니다."})


def cmd_verify(a) -> None:
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    p = st["plan"]
    if p["status"] != "approved":
        block("plan_not_approved", "승인된 계획이 없습니다.")
    cur = plan_hashes(project)
    if any(cur.get(k) != v for k, v in p["approved"]["hashes"].items()):
        block("plan_modified", "승인된 계획·프로필이 바뀌었습니다. 승인된 프로필의 명령만 실행합니다.")
    b = st["batches"].get(a.batch)
    if not b:
        block("unknown_batch", f"승인된 계획에 {a.batch}가 없습니다.")
    plan_batch = read_plan_batch(project, a.batch)
    probe = b["status"] == "in_progress"
    lock = None
    if probe:
        lock = require_lock(project, a.batch, a.lock)
    elif b["status"] in ("implemented", "verify_failed", "stale", "verified", "approved", "imported"):
        if not (b.get("run") or {}).get("submitted"):
            block("not_implemented", f"{a.batch}에 구현 제출 기록이 없습니다. 구현 없이 검증 상태를 만들 수 없습니다.")
        held = read_lock(project)
        if held is not None:
            block("active_batch_exists", "다른 배치가 실행 중(잠금)입니다. 작업 중인 파일이 섞이지 않도록 끝난 뒤 검증합니다.", lock=held)
    else:
        block("not_verifiable", f"{a.batch} 상태가 {b['status']}입니다. 구현 중(in_progress)이거나 구현 완료 이후만 검증합니다.")
    steps = prof["verify"]["steps"]
    if a.steps:
        names = [x.strip() for x in a.steps.split(",") if x.strip()]
        unknown = [n for n in names if n not in {s["name"] for s in steps}]
        if unknown:
            block("unknown_step", f"프로필에 없는 단계: {', '.join(unknown)}")
        steps = [s for s in steps if s["name"] in names]
        if not probe:
            block("partial_final_verify", "최종 검증은 프로필의 모든 단계를 실행합니다(--steps는 구현 중 확인용).")
    if not steps:
        block("no_steps", "프로필에 검증 단계(verify.steps)가 없습니다.")
    avail = {x.strip() for x in (a.available or "").split(",") if x.strip()}
    run = run_steps(project, prof, a.batch, steps, avail, int(prof["execution"]["step_timeout_seconds"]))
    hist = st.setdefault("case_history", {})
    update_history(hist, run, run["tree_after"], "probe" if probe else "final")
    mentioned = mentions_in_tests(project, prof)
    acs = list(plan_batch.get("acs") or [])
    legacy = ((b.get("run") or {}).get("submitted") or {}).get("kind") == "adopt"
    ev = evaluate(acs, effective_targets(b), run, hist, mentioned, run["tree_after"], set(b.get("fi_accepted", {})), legacy, project)
    ok, reasons = batch_verdict(run, ev)
    summary = {"run_id": run["run_id"], "dir": run["dir"], "digest": run["digest"], "at": run["at"], "valid": run["valid"],
               "steps": step_summary(run), "counts": {k: sum(1 for e in ev.values() if e["status"] == k) for k in
                                                     ("verified", "insufficient", "failing", "not_run", "untested", "invalid_run")}}
    # 다른 검증된 배치의 태그 테스트가 이번 실행에서 실패하면 회귀로 표시
    regressed = {}
    if run["valid"]:
        failed_acs = {x for s in run["steps"] for c in s.get("cases", []) if c["status"] in ("failed", "error") for x in c["acs"]}
        for oid, ob in st["batches"].items():
            if oid != a.batch and ob["status"] in DONE_STATES:
                hit = sorted(failed_acs & set(_plan_batches(project).get(oid, {}).get("acs") or []))
                if hit:
                    if ob["status"] == "approved":
                        _invalidate_approval(ob, f"회귀: {a.batch} 실행에서 {', '.join(hit)} 실패")
                    ob["status"] = "stale"
                    ob["verification"].update(stale_reason=f"회귀: {a.batch} 검증 실행에서 {', '.join(hit)} 테스트 실패", stale_at=now())
                    add_history(st, "batch", "regressed", None, f"{oid}: {', '.join(hit)}")
                    regressed[oid] = hit
    out = {"ok": True, "batch": a.batch, "mode": "probe" if probe else "final", "run": {k: summary[k] for k in ("run_id", "valid", "steps")},
           "acs": ev, "counts": summary["counts"], "regressed_batches": regressed}
    limit = prof["execution"]["max_retries"]
    att = b["run"]["attempts"].setdefault("verify", {"consecutive_failures": 0, "total": 0, "last": None})
    att["total"] += 1
    att["last"] = {"at": now(), "run_id": run["run_id"], "ok": ok}
    att["consecutive_failures"] = 0 if ok else att["consecutive_failures"] + 1
    if probe:
        b["run"].setdefault("probes", []).append({k: summary[k] for k in ("run_id", "dir", "digest", "at", "valid", "counts")} | {"ok": ok})
        out["note"] = "구현 중 확인 실행입니다(배치 상태는 바뀌지 않음). 결과는 실패→통과(E3) 이력에 쓰입니다."
        if not ok and att["consecutive_failures"] >= limit:
            g = _guard_now(project, st, b, plan_batch, prof)
            b["run"]["failure"] = {"at": now(), "step": "verify", "attempts": att["consecutive_failures"], "reason": "검증 연속 실패 한도 초과",
                                   "reasons": reasons[:10], "run_id": run["run_id"]}
            write_checkpoint(project, b["run"], b["run"]["tasks"], g["states"], "검증 실패 한도 초과")
            b["status"] = "failed"
            release_lock(project, lock["lock_id"])
            add_history(st, "batch", "failed", None, f"{a.batch}: 검증 연속 {att['consecutive_failures']}회 실패")
            save_state(project, st)
            emit(out | {"ok": False, "error": "retry_limit_exceeded", "status": "failed", "reasons": reasons[:20],
                        "next": "사용자 결정 후 resume --retry-failed --note"}, 2)
        heartbeat(project, lock)
    else:
        pbm = plan_batch
        case_files = sorted({c.get("file") for s in run["steps"] for c in s.get("cases", []) if c.get("file") and set(c["acs"]) & set(acs)
                             and (project / c["file"]).is_file()})
        scope = batch_scope_files(project, prof, pbm, b, case_files)
        prev_status, prev_scope = b["status"], (b.get("verification") or {}).get("scope_tree")
        b["verification"] = summary | {"evaluation": ev, "reasons": reasons, "code_tree": run["tree_after"], "case_files": case_files,
                                       "scope_tree": tree_hash(project, scope), "deps": deps_affecting(run["deps_tree"], scope),
                                       "targets": effective_targets(b)}
        if ok and prev_status == "approved" and prev_scope == b["verification"]["scope_tree"]:
            b["status"] = "approved"  # 같은 코드로 다시 검증: 최종 승인 유지
        elif ok:
            if prev_status == "approved":
                _invalidate_approval(b, "재검증 결과 기준이 바뀜(다시 승인 필요)")
            b["status"] = "verified"
        elif att["consecutive_failures"] >= limit:
            b["status"] = "failed"
            b["run"]["failure"] = {"at": now(), "step": "verify", "attempts": att["consecutive_failures"], "reason": "최종 검증 연속 실패 한도 초과",
                                   "reasons": reasons[:10], "run_id": run["run_id"]}
        else:
            if prev_status == "approved":
                _invalidate_approval(b, "재검증 실패")
            b["status"] = "verify_failed"
        add_history(st, "batch", "verified" if ok else "verify_failed", None, f"{a.batch}: " + ("필수 AC 검증 완료" if ok else "; ".join(reasons)[:300]))
        out.update(status=b["status"], reasons=reasons)
        if not ok:
            out["next"] = ("재시도 한도 초과: 사용자 결정 후 resume --retry-failed --note" if b["status"] == "failed"
                           else "원인을 고치려면 resume --batch로 다시 열어 수정 → batch-submit → verify")
    save_state(project, st)
    emit(out, 0 if (ok or probe) else 2)


def cmd_ac_report(a) -> None:
    """검증 결과를 AC별로 보고(읽기 전용). 증거가 무효가 되었으면 함께 표시합니다."""
    project = project_of(a)
    st = require_state(project)
    prof = profile_or_block(project)
    pbs = _plan_batches(project)
    targets = [a.batch] if a.batch else list(st["batches"])
    out = {"ok": True, "batches": {}}
    for bid in targets:
        b = st["batches"].get(bid)
        if not b:
            block("unknown_batch", f"{bid}가 없습니다.")
        v = b.get("verification")
        rec = {"status": b["status"], "freshness_problem": freshness(project, prof, bid, b, pbs.get(bid))}
        if v:
            rec.update(run_id=v["run_id"], at=v["at"], valid=v["valid"], counts=v["counts"], reasons=v.get("reasons"),
                       stale_reason=v.get("stale_reason"),
                       acs={k: {x: e.get(x) for x in ("status", "level", "target", "reason", "evidence")} for k, e in v["evaluation"].items()})
        else:
            rec["acs"] = {k: {"status": "not_verified", "target": t, "reason": "검증 실행 없음"} for k, t in effective_targets(b).items()}
        if b.get("target_overrides"):
            rec["target_overrides"] = b["target_overrides"]
        if b.get("approvals"):
            rec["approvals"] = [{k: x.get(k) for k in ("at", "statement", "run_id", "valid")} for x in b["approvals"]]
        out["batches"][bid] = rec
    emit(out)


def _csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def policy_block(project: Path, bid: str, action: str) -> None:
    items = L.blocking_for(L.load(project), bid, _plan_batches(project))
    if items:
        block("blocked_by_policy", f"{bid}에 영향을 주는 미해결 차단 정책이 있어 {action}할 수 없습니다. 사용자 결정(decide) 후 진행합니다.",
              items=[{"id": i["id"], "type": i["type"], "title": i["title"]} for i in items])


def cmd_ledger(a) -> None:
    project = project_of(a)
    st = require_state(project)
    d = L.load(project)
    pbs = _plan_batches(project)
    if a.action == "add":
        if not a.title:
            block("invalid_arguments", "--title이 필요합니다.")
        docs = _csv(a.docs)
        for doc in docs:
            if not (project / doc).exists():
                block("invalid_doc", f"관련 문서가 없습니다: {doc}")
        unknown = [b for b in _csv(a.batches) if b not in st["batches"]]
        if unknown:
            block("unknown_batch", f"승인된 계획에 없는 배치: {', '.join(unknown)}")
        it = L.add_item(d, a.type, a.title, a.desc or "", blocking=a.blocking, batches=_csv(a.batches), acs=_csv(a.acs), docs=docs,
                        category=a.category or None, provisional=a.provisional or None, rationale=a.rationale or "", classified_by=a.by or "claude",
                        source={"kind": "manual"})
        L.save(project, d)
        emit({"ok": True, "item": it, "affected_batches": L.affected_batches(it, pbs),
              "note": "차단 정책이면 영향 배치의 시작·최종 승인이 막히고, 실행 중 배치는 다음 체크포인트에서 멈춥니다." if it["blocking"] else "차단 정책이 아닙니다(기록·추적용)."})
    if a.action == "dismiss":
        it = L.find(d, a.id)
        if not (a.note or "").strip() or not (a.reason or "").strip():
            block("approval_statement_required", "항목 기각은 사유(--reason)와 사용자 확인 문장(--note)이 필요합니다.")
        it["history"].append({"at": now(), "event": "dismissed", "from": it["status"], "reason": a.reason.strip(), "statement": a.note.strip()})
        it["status"] = "dismissed"
        L.save(project, d)
        emit({"ok": True, "id": it["id"], "status": "dismissed"})
    if a.action == "sync":
        emit(ledger_sync(project, st, d, pbs))
    items = d["items"]
    if a.type:
        items = [i for i in items if i["type"] == a.type]
    if a.status:
        items = [i for i in items if i["status"] == a.status]
    if a.batch:
        items = [i for i in items if a.batch in L.affected_batches(i, pbs)]
    emit({"ok": True, "counts": {t: sum(1 for i in d["items"] if i["type"] == t and i["status"] == "open") for t in L.TYPES},
          "blocking_open": [i["id"] for i in d["items"] if i["blocking"] and i["status"] == "open"],
          "items": [{k: i.get(k) for k in ("id", "type", "status", "blocking", "title", "related", "provisional")}
                    | {"affected_batches": L.affected_batches(i, pbs), "decisions": len(i["decisions"])} for i in items],
          "proposals": [{k: p[k] for k in ("id", "item", "doc", "status")} for p in d["proposals"]]})


def ledger_sync(project: Path, st: dict, d: dict, pbs: dict) -> dict:
    """검증 결과의 증거 부족(evidence_gap), 사용자 승인된 목표 변경·결함 주입 인정(target_change), 코드의 TODO(POL)을 원장으로 가져옵니다.
    이미 있는 항목은 다시 만들지 않고, 증거가 채워진 evidence_gap은 닫습니다(이력 남김)."""
    added, closed = [], []
    prof, _ = load_profile(project)
    for bid, b in st["batches"].items():
        ev = (b.get("verification") or {}).get("evaluation") or {}
        for ac, e in ev.items():
            key = {"kind": "verification", "batch": bid, "ac": ac}
            existing = next((i for i in d["items"] if i["type"] == "evidence_gap" and i["source"] == key and i["status"] == "open"), None)
            if e["status"] == "verified":
                if existing:
                    existing["history"].append({"at": now(), "event": "closed", "reason": f"검증 충족({e.get('level')}) — run {b['verification']['run_id']}"})
                    existing["status"] = "closed"
                    closed.append(existing["id"])
                continue
            if existing:
                continue
            it = L.add_item(d, "evidence_gap", f"{ac} 검증 증거 부족({e['status']}, {e.get('level')}/{e.get('target')})", e.get("reason") or "",
                            batches=[bid], acs=[ac], source=key, classified_by="product-build verify",
                            rationale="검증 상태(verify_failed 등)가 이미 진행을 막으므로 차단 정책이 아님")
            added.append(it["id"])
        for i, o in enumerate(b.get("target_overrides", [])):
            key = {"kind": "target_override", "batch": bid, "index": i}
            if not any(x["source"] == key for x in d["items"]):
                it = L.add_item(d, "target_change", f"{o['ac']} 목표 변경 {o['from']}→{o['to']}", o["reason"], batches=[bid], acs=[o["ac"]], source=key,
                                status="decided", classified_by="product-build target",
                                decided={"seq": 1, "decision": f"목표 {o['from']}→{o['to']}", "statement": o["statement"], "decided_by": "user", "at": o["at"]})
                added.append(it["id"])
        for ac, f in (b.get("fi_accepted") or {}).items():
            key = {"kind": "fault_injection_accepted", "batch": bid, "ac": ac}
            if not any(x["source"] == key for x in d["items"]):
                it = L.add_item(d, "target_change", f"{ac} 결함 주입 증거 인정", "실제 결함 수정 이력이 아닌 결함 주입 증거로 목표 E3 충족을 인정",
                                batches=[bid], acs=[ac], source=key, status="decided", classified_by="product-build accept-fault-injection",
                                decided={"seq": 1, "decision": "결함 주입 증거 인정", "statement": f["statement"], "decided_by": "user", "at": f["at"]})
                added.append(it["id"])
    roots = sorted(set((prof["paths"].get("source") or []) + (prof["paths"].get("tests") or [])))
    files = iter_source(project, roots or None, prof["paths"].get("exclude"))
    for m in L.scan_todo_pol(project, files):
        if m["ref"]:
            it = next((x for x in d["items"] if x["id"] == m["ref"]), None)
            if it and not any(h.get("event") == "code_marker" and h.get("file") == m["file"] for h in it["history"]):
                it["history"].append({"at": now(), "event": "code_marker", "file": m["file"], "line": m["line"]})
            continue
        key = {"kind": "todo_pol", "file": m["file"], "text": m["text"]}
        if not any(x["source"] == key for x in d["items"]):
            owner = [bid for bid, pb in pbs.items() if in_patterns(m["file"], list((pb.get("paths") or {}).get("allow") or []))]
            it = L.add_item(d, "policy", f"코드 임시값: {m['text'][:60] or m['file']}", f"{m['file']}:{m['line']} TODO(POL)", batches=owner,
                            provisional=m["text"], source=key, classified_by="product-build sync",
                            rationale="구현 중 남긴 임시값 표시(되돌리기 쉬운 값) → 기본은 비차단, 사용자 결정 대상")
            added.append(it["id"])
    L.save(project, d)
    return {"ok": True, "added": added, "closed": closed, "open": {t: sum(1 for i in d["items"] if i["type"] == t and i["status"] == "open") for t in L.TYPES}}


def decision_preview(project: Path, st: dict, it: dict, pbs: dict) -> dict:
    bs = L.affected_batches(it, pbs)
    return {"id": it["id"], "type": it["type"], "title": it["title"], "description": it["description"], "blocking": it["blocking"],
            "provisional": it.get("provisional"), "previous_decisions": it["decisions"],
            "affected_batches": {x: {"status": st["batches"].get(x, {}).get("status"),
                                     "after_decision": ("재검증 필요(stale)·최종 승인 무효 표시" if st["batches"].get(x, {}).get("status") in DONE_STATES
                                                        else "변화 없음(검증 때 반영)")} for x in bs},
            "acs": it["related"]["acs"], "docs": it["related"]["docs"],
            "doc_proposal_hint": "결정이 기획·UX Spec·AC·구현 계획을 바꿔야 하면 --propose '<문서경로>::<변경 내용>'으로 변경 제안을 만듭니다(원본은 바로 고치지 않음)."}


def cmd_decide(a) -> None:
    """미결정 항목 조회·영향 미리보기·사용자 결정 기록. 결정은 사용자 원문(--note)과 --confirm이 있어야 기록합니다(추측 승인 없음)."""
    project = project_of(a)
    st = require_state(project)
    d = L.load(project)
    pbs = _plan_batches(project)
    if not a.id:
        need = [i for i in d["items"] if i["type"] in ("policy", "deviation") and i["status"] == "open"]
        emit({"ok": True, "open": [decision_preview(project, st, i, pbs) for i in need],
              "note": "결정이 필요한 항목입니다(정책 미결정·구현 편차). 검증 증거 부족은 결정 대상이 아니라 테스트·구현으로 해결합니다."})
    it = L.find(d, a.id)
    if it["type"] not in ("policy", "deviation"):
        block("not_decidable", f"{it['id']}는 {it['type']} 항목입니다. 사용자 결정 대상은 정책 미결정·구현 편차입니다"
              + ("(검증 증거 부족은 테스트·구현으로 해결)" if it["type"] == "evidence_gap" else ""))
    preview = decision_preview(project, st, it, pbs)
    if not (a.decision and (a.note or "").strip() and a.confirm):
        emit({"ok": True, "status": "preview", "item": preview,
              "message": "영향을 사용자에게 보여 주고 명시적 결정을 받은 뒤 --decision '<결정 내용>' --note '<사용자 원문>' --confirm으로 기록합니다."})
    if it["status"] == "dismissed":
        block("dismissed", f"{it['id']}는 기각된 항목입니다.")
    seq = len(it["decisions"]) + 1
    effects = {"stale": [], "proposals": []}
    for x in L.affected_batches(it, pbs):
        b = st["batches"].get(x)
        if b and b["status"] in DONE_STATES:
            if b["status"] == "approved":
                _invalidate_approval(b, f"{it['id']} 결정 반영")
            b["status"] = "stale"
            b["verification"].update(stale_reason=f"{it['id']} 결정 반영 — 관련 AC 재검증 필요", stale_at=now())
            effects["stale"].append(x)
    for spec in a.propose or []:
        doc, sep, change = spec.partition("::")
        if not sep or not change.strip():
            block("invalid_arguments", "--propose는 '<문서경로>::<변경 내용>' 형식입니다.")
        pr = L.add_proposal(d, project, it["id"], doc.strip(), change, {"plan_revision": st["plan"]["revision"]})
        effects["proposals"].append(pr["id"])
    rec = {"seq": seq, "decision": a.decision.strip(), "statement": a.note.strip(), "decided_by": "user", "at": now(), "effects": effects}
    if it["decisions"]:
        rec["supersedes"] = it["decisions"][-1]["seq"]
    it["decisions"].append(rec)
    it["history"].append({"at": now(), "event": "decided" if seq == 1 else "decision_changed", "seq": seq})
    it["status"] = "decided"
    d["history"].append({"at": now(), "event": "decided", "id": it["id"], "note": a.decision.strip()[:120]})
    for x in effects["stale"]:
        add_history(st, "batch", "stale", None, f"{x}: {it['id']} 결정 반영")
    L.save(project, d)
    save_state(project, st)
    emit({"ok": True, "id": it["id"], "status": "decided", "decision": rec, "reverify": effects["stale"], "proposals": effects["proposals"],
          "note": "결정으로 차단이 풀려도 영향 배치의 재검증·최종 승인은 다시 거칩니다. 문서 변경은 제안으로만 만들었습니다(원본 미수정)."})


def cmd_doc_proposal(a) -> None:
    project = project_of(a)
    st = require_state(project)
    d = L.load(project)
    if a.action == "list":
        emit({"ok": True, "proposals": d["proposals"]})
    pr = next((p for p in d["proposals"] if p["id"] == a.id), None)
    if not pr:
        block("unknown_proposal", f"{a.id} 문서 변경 제안이 없습니다.")
    if a.action in ("approve", "reject"):
        if not (a.note or "").strip():
            block("approval_statement_required", "문서 변경 승인·거절은 사용자 문장(--note)이 필요합니다.")
        if pr["status"] != "proposed":
            block("invalid_state", f"{pr['id']} 상태가 {pr['status']}입니다.")
        pr["approvals"].append({"at": now(), "statement": a.note.strip(), "action": a.action})
        pr["status"] = "approved" if a.action == "approve" else "rejected"
        pr["history"].append({"at": now(), "event": pr["status"]})
        L.save(project, d)
        how = {"planning": "/product-start 재검토(T9)로 기획 문서를 개정·재승인", "ux_spec": "/product-design reopen --stage ux_spec으로 개정·재승인",
               "build_plan": "reopen plan → 계획 수정 → submit plan → 사용자 승인"}[pr["kind"]]
        emit({"ok": True, "id": pr["id"], "status": pr["status"],
              "next": (f"승인된 변경은 소유 Skill이 적용합니다: {how}. 적용 뒤 doc-proposal apply-check --id {pr['id']}") if pr["status"] == "approved" else "거절 기록"})
    if a.action == "apply-check":
        if pr["status"] != "approved":
            block("not_approved", f"{pr['id']}는 사용자 승인된 제안이 아닙니다(현재: {pr['status']}). 승인과 적용은 별개입니다.")
        cur = sha_file(project / pr["doc"])
        if cur == pr["base"]["sha256"]:
            block("not_applied", f"{pr['doc']}가 아직 바뀌지 않았습니다.")
        if pr["kind"] == "planning":
            g = planning_gate(project)
            ok, why = g["ok"], g.get("message")
        elif pr["kind"] == "ux_spec":
            di = design_info(project)
            ok, why = di["level"] in ("L2", "L3"), di.get("reason")
        else:
            ok = st["plan"]["status"] == "approved" and st["plan"]["revision"] > pr["base"].get("plan_revision", 0)
            why = "계획이 다시 제출·승인되지 않았습니다"
        if not ok:
            block("not_reapproved", f"{pr['doc']}가 바뀌었지만 소유 Skill의 재승인이 확인되지 않았습니다: {why}")
        pr["status"] = "applied"
        pr["applied"] = {"at": now(), "sha256": cur}
        pr["history"].append({"at": now(), "event": "applied"})
        L.save(project, d)
        emit({"ok": True, "id": pr["id"], "status": "applied",
              "note": "적용 확인. 기획·UX Spec이 바뀌었으면 check가 구현 계획을 outdated로 표시하고, 관련 배치는 재검증·재승인을 거칩니다."})


# ---------------------------------------------------------------- M3.1 UI 대응표·토큰 / M3.2 UI Brief·UI Plan
def _ui_ctx(project: Path, plan_required: bool = False):
    prof = profile_or_block(project, required=False)
    uprof, probs = U.ui_profile(prof)
    if probs:
        block("profile_invalid", f"{PROFILE_REL}의 [ui]에 문제가 있습니다.", problems=probs)
    return prof, uprof, read_plan(project, required=plan_required)


def cmd_ui_map(a) -> None:
    project = project_of(a)
    require_planning(project)
    st = load_state(project)
    prof, uprof, plan = _ui_ctx(project)
    umap = U.load_map(project)
    if a.action == "candidates":
        emit({"ok": True, **U.candidates(project, prof, uprof, umap)})
    if a.action in ("show", "check"):
        if umap is None:
            emit({"ok": True, "exists": False, "path": U.UI_MAP_REL,
                  "note": "대응표가 없습니다. 기존 부품이 있으면 ui-map candidates → 사용자 확인 → ui-map register, 새 프로젝트는 B0 배치가 만든 뒤 register --source built"})
        r = U.map_problems(project, umap, plan, st, a.batch, U.code_exts(uprof))
        emit({"ok": r["ok"], "path": U.UI_MAP_REL, **r, **({"map": umap} if a.action == "show" else {})}, 0 if r["ok"] else 2)
    umap = umap or U.empty_map()
    cmps04 = U.uisys_cmps(project)
    note = (a.note or "").strip()
    if a.action == "register":
        if not a.cmp or a.cmp not in cmps04:
            block("unknown_cmp", f"{a.cmp}는 승인된 04 문서의 컴포넌트가 아닙니다.")
        if a.source not in U.SOURCES:
            block("invalid_arguments", f"--source는 {'/'.join(U.SOURCES)} 중 하나입니다.")
        if not a.export:
            block("invalid_arguments", "--export(코드에서 쓰는 이름)가 필요합니다.")
        if a.cmp in umap["components"] and not a.replace:
            block("already_mapped", f"{a.cmp}는 이미 대응되어 있습니다. 바꾸려면 --replace --note(사용자 문장)를 씁니다.", current=umap["components"][a.cmp])
        if a.replace and not note:
            block("approval_statement_required", "기존 대응을 바꾸려면 사용자 문장(--note)이 필요합니다.")
        entry = {"source": a.source, "export": a.export, "registered_at": now()}
        if a.source == "library":
            if not a.package:
                block("invalid_arguments", "library 부품은 --package(라이브러리 이름)가 필요합니다.")
            entry["package"] = a.package
            if a.path:
                entry["path"] = a.path
        else:
            if not a.path or U.bad_path(a.path):
                block("invalid_arguments", "--path(저장소 안 상대 경로)가 필요합니다.")
            entry["path"] = a.path
        if a.path and U.is_preview(a.path):
            block("preview_reuse", "디자인 프리뷰 코드는 제품 부품으로 등록할 수 없습니다(시각 참고만).")
        if a.path and is_protected(a.path):
            block("protected_path", f"{a.path}는 다른 Skill의 보호 경로입니다.")
        if a.path and not (project / a.path).is_file():
            block("path_missing", f"{a.path}가 없습니다. 부품을 만든 뒤 등록합니다.")
        if a.path and not U.export_found(project, a.path, a.export):
            block("export_not_found", f"{a.path}에서 {a.export}를 찾을 수 없습니다.")
        if a.source in ("existing", "library"):
            if not note:
                block("approval_statement_required", "기존·라이브러리 부품 재사용 등록은 사용자 확인 문장(--note)이 필요합니다(scan 후보는 후보일 뿐).")
        else:
            if not plan or not (st and st["plan"]["status"] == "approved"):
                block("plan_not_approved", "built 등록은 승인된 계획의 배치가 만든 부품만 할 수 있습니다.")
            b = U.batches_by_id(plan).get(a.batch or "")
            if not b:
                block("invalid_arguments", "--batch(부품을 만든 배치)가 필요합니다.")
            if a.cmp not in U.comp_list(b, "new"):
                block("not_planned_new", f"{a.cmp}는 {b['id']}의 components.new가 아닙니다. 계획에 없는 부품은 등록하지 않습니다.")
            if st["batches"].get(b["id"], {}).get("status") not in U.STARTED:
                block("batch_not_started", f"{b['id']}가 시작되지 않았습니다.")
            pats = ((b.get("paths") or {}).get("allow") or []) + ((b.get("paths") or {}).get("shared") or [])
            if not U.in_patterns(a.path, pats):
                block("out_of_scope", f"{a.path}는 {b['id']}의 paths.allow/shared 밖입니다.")
            entry["built_by"] = b["id"]
        if note:
            entry["note"] = note
        prev = umap["components"].get(a.cmp)
        umap["components"][a.cmp] = entry
        U.save_map(project, umap, f"register {a.cmp} ({a.source})" + (" replace" if prev else ""), note)
        r = U.map_problems(project, umap, plan, st)
        emit({"ok": True, "cmp": a.cmp, "entry": entry, "replaced": prev, "map_check": {"ok": r["ok"], "errors": r["errors"], "warnings": r["warnings"]}})
    if a.action == "remove":
        if a.cmp not in umap["components"]:
            block("not_mapped", f"{a.cmp}는 대응표에 없습니다.")
        if not note:
            block("approval_statement_required", "대응 삭제는 사용자 문장(--note)이 필요합니다.")
        prev = umap["components"].pop(a.cmp)
        U.save_map(project, umap, f"remove {a.cmp}", note)
        emit({"ok": True, "removed": a.cmp, "previous": prev})
    if a.action == "tokens":
        fmt = a.format or "css-vars"
        if fmt not in U.TOKEN_FORMATS:
            block("invalid_arguments", f"--format은 {'/'.join(U.TOKEN_FORMATS)} 중 하나입니다.")
        if not note:
            block("approval_statement_required", "토큰 출력 설정은 사용자 확인 문장(--note)이 필요합니다.")
        cfg = {"format": fmt}
        if fmt == "css-vars":
            if not a.file or U.bad_path(a.file) or U.is_preview(a.file) or is_protected(a.file):
                block("token_output_invalid", "--file은 제품 코드 안 상대 경로여야 합니다(프리뷰·보호 경로 불가).")
            cfg.update(file=a.file, var_pattern=a.var_pattern or "--{dashed}")
            if "{dashed}" not in cfg["var_pattern"] and "{name}" not in cfg["var_pattern"]:
                block("invalid_arguments", "--var-pattern에는 {dashed} 또는 {name}이 있어야 합니다.")
        else:
            if not a.export_cmd:
                block("invalid_arguments", "--export-cmd(토큰 이름→값 JSON을 출력하는 프로젝트 명령)가 필요합니다.")
            cfg.update(export=a.export_cmd, file=a.file)
        aliases = {}
        for x in a.alias or []:
            if "=" not in x:
                block("invalid_arguments", f"--alias는 토큰=이름 형식입니다: {x}")
            k, v = x.split("=", 1)
            aliases[k.strip()] = v.strip()
        approved, _src = U.approved_tokens(project)
        unknown = sorted(k for k in aliases if k not in approved)
        if unknown:
            block("unknown_token", "승인된 토큰이 아닌 이름에 별칭을 걸 수 없습니다.", tokens=unknown)
        if aliases:
            cfg["aliases"] = aliases
        umap["tokens"] = cfg
        U.save_map(project, umap, f"tokens {fmt}", note)
        emit({"ok": True, "tokens": cfg})
    if a.action == "except":
        if not (a.reason or "").strip() or not note:
            block("approval_statement_required", "예외는 사유(--reason)와 사용자 승인 문장(--note)이 모두 필요합니다.")
        if a.token:
            approved, _src = U.approved_tokens(project)
            if a.token not in approved:
                block("unknown_token", f"{a.token}는 승인된 토큰이 아닙니다.")
            umap["exceptions"]["tokens"] = [e for e in umap["exceptions"]["tokens"] if e["token"] != a.token]
            umap["exceptions"]["tokens"].append({"token": a.token, "reason": a.reason.strip(), "note": note, "at": now()})
            U.save_map(project, umap, f"except token {a.token}", note)
            emit({"ok": True, "exception": umap["exceptions"]["tokens"][-1]})
        if a.audit_path:
            if U.bad_path(a.audit_path.replace("*", "x")):
                block("invalid_arguments", "--audit-path는 저장소 안 경로 패턴이어야 합니다.")
            e = {"path": a.audit_path, "value": a.value or "", "reason": a.reason.strip(), "note": note, "at": now()}
            umap["exceptions"]["audit"].append(e)
            U.save_map(project, umap, f"except audit {a.audit_path} {a.value or '*'}", note)
            emit({"ok": True, "exception": e})
        block("invalid_arguments", "--token 또는 --audit-path가 필요합니다.")
    block("invalid_arguments", f"알 수 없는 동작: {a.action}")


def cmd_token_check(a) -> None:
    project = project_of(a)
    require_planning(project)
    umap = U.load_map(project)
    if umap is None:
        block("no_ui_map", f"{U.UI_MAP_REL}이 없습니다. ui-map tokens --file <CSS 파일> --note로 토큰 출력을 먼저 설정하세요.")
    r = U.token_check(project, umap)
    emit({"ok": r["ok"], **r}, 0 if r["ok"] else 2)


def cmd_token_audit(a) -> None:
    project = project_of(a)
    require_planning(project)
    prof, uprof, plan = _ui_ctx(project, plan_required=bool(a.batch))
    umap = U.load_map(project) or U.empty_map()
    r = U.token_audit(project, prof, uprof, plan, a.batch, umap)
    emit({**r, "batch": a.batch}, 0 if r["ok"] else 2)


def _ui_batch(project: Path, bid: str):
    require_planning(project)
    st = require_state(project)
    if st["plan"]["status"] != "approved":
        block("plan_not_approved", "UI Brief는 승인된 구현 계획의 배치에만 만듭니다.")
    prof, uprof, plan = _ui_ctx(project, plan_required=True)
    b = U.batches_by_id(plan).get(bid)
    if not b or bid not in st["batches"]:
        block("unknown_batch", f"승인된 계획에 {bid} 배치가 없습니다.")
    if b.get("kind") == "non_ui" or not (b.get("screens") or U.comp_list(b, "new") or U.comp_list(b, "reuse")):
        block("not_ui_batch", f"{bid}는 화면·컴포넌트가 없는 배치입니다(UI Brief 대상 아님).")
    if sha_file(project / PLAN_JSON_REL) != st["plan"]["approved"]["hashes"].get(PLAN_JSON_REL):
        block("plan_modified", "승인 이후 계획 파일이 바뀌었습니다. UI Brief를 만들지 않았습니다.")
    dinfo = design_info(project)
    if dinfo["level"] not in ("L2", "L3"):
        block("design_not_ready", f"디자인 준비 수준이 {dinfo['level']}입니다({dinfo.get('reason')}). UI Brief에는 승인된 UX Spec이 필요합니다.")
    changes = baseline_changes(st["plan"]["approved"]["inputs"], input_baseline(project, planning_gate(project), dinfo))
    if changes:
        block("plan_outdated", "계획 승인 이후 입력 문서가 바뀌었습니다. check로 상태를 확인하세요.", changed=changes)
    return st, prof, uprof, plan, dinfo


def cmd_ui_brief(a) -> None:
    project = project_of(a)
    st, prof, uprof, plan, dinfo = _ui_batch(project, a.batch)
    umap = U.load_map(project)
    brief = U.build_brief(project, st, plan, a.batch, prof, uprof, dinfo, load_model(project), umap)
    rel = U.ui_rel(a.batch, "brief.json")
    old = U.read_json(project, rel)
    U.write_json(project, rel, brief)
    skel = U.plan_skeleton(brief)
    out = {"ok": True, "brief": rel, "digest": brief["digest"], "changed": (old or {}).get("digest") != brief["digest"],
           "summary": {"screens": {s: {"states_defined": sum(1 for x in v["states"] if x["defined"]), "actions": len(v["actions"]),
                                       "acs": [x["id"] for x in v["acs"]], "vd": [x["id"] for x in v["vd"]]} for s, v in brief["screens"].items()},
                       "components": {c: v["role"] for c, v in brief["components"].items()}, "token_source": brief["tokens"]["source"]},
           "warnings": brief["warnings"], "ui_plan": U.ui_rel(a.batch, "plan.json"),
           "next": f"Claude가 {U.ui_rel(a.batch, 'plan.json')}을 작성(아래 skeleton에서 시작)한 뒤 ui-plan-validate --batch {a.batch}"}
    if a.full:
        out["brief_data"] = brief
    if not (project / U.ui_rel(a.batch, "plan.json")).exists():
        out["skeleton"] = skel
    emit(out)


def cmd_ui_plan_validate(a) -> None:
    project = project_of(a)
    st, prof, uprof, plan, dinfo = _ui_batch(project, a.batch)
    umap = U.load_map(project)
    stored = U.read_json(project, U.ui_rel(a.batch, "brief.json"))
    if not stored or stored.get("_invalid"):
        block("no_ui_brief", f"UI Brief가 없습니다. ui-brief --batch {a.batch}을 먼저 실행하세요.")
    if stored.get("digest") != U.digest({k: v for k, v in stored.items() if k != "digest"}):
        block("brief_modified", "UI Brief 파일이 엔진 밖에서 바뀌었습니다. 직접 고치지 않습니다. ui-brief로 다시 만드세요.")
    now_brief = U.build_brief(project, st, plan, a.batch, prof, uprof, dinfo, load_model(project), umap)
    uplan = U.read_json(project, U.ui_rel(a.batch, "plan.json"))
    if uplan is None:
        block("no_ui_plan", f"UI Plan이 없습니다. {U.ui_rel(a.batch, 'plan.json')}을 작성하세요(ui-brief의 skeleton에서 시작).")
    ledger_ids = {i["id"] for i in L.load(project)["items"]}
    r = U.validate_ui_plan(project, uplan, now_brief, plan, a.batch, umap, uprof, ledger_ids)
    if stored.get("digest") != now_brief["digest"]:
        r["errors"].insert(0, "[brief_stale] 저장된 UI Brief가 현재 승인 문서·계획·대응표와 다릅니다. ui-brief를 다시 실행하세요")
        r["ok"] = False
    rec = {"at": now(), "ok": r["ok"], "brief_digest": now_brief["digest"], "plan_sha256": sha_file(project / U.ui_rel(a.batch, "plan.json")),
           "errors": r["errors"], "warnings": r["warnings"], "counts": r["counts"]}
    U.write_json(project, U.ui_rel(a.batch, "validation.json"), rec)
    emit({"batch": a.batch, **r, "record": U.ui_rel(a.batch, "validation.json")}, 0 if r["ok"] else 2)


# ---------------------------------------------------------------- 진입점
class JsonArgParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        emit({"ok": False, "error": "invalid_arguments", "message": message}, 2)


def main() -> None:
    ap = JsonArgParser(description="/product-build helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn):
        s = sub.add_parser(name)
        s.add_argument("--project", required=True)
        s.set_defaults(fn=fn)
        return s

    add("init", cmd_init)
    add("check", cmd_check)
    add("scan", cmd_scan)
    s = add("scope", cmd_scope); s.add_argument("--suggest", action="store_true"); s.add_argument("--draft", action="store_true")
    s.add_argument("--priorities")
    add("plan-validate", cmd_plan_validate)
    s = add("submit", cmd_submit); s.add_argument("target", choices=("plan",))
    s = add("approve", cmd_approve); s.add_argument("target", choices=("plan", "batch")); s.add_argument("--revision", type=int); s.add_argument("--batch")
    s.add_argument("--note", default="")
    s = add("reopen", cmd_reopen); s.add_argument("target", choices=("plan",)); s.add_argument("--reason", required=True)
    s = add("waiver", cmd_waiver); s.add_argument("action", choices=("add", "revoke")); s.add_argument("--kind", default="preview")
    s.add_argument("--reason", default=""); s.add_argument("--batches", default=""); s.add_argument("--all-ui", action="store_true")
    s.add_argument("--note", default=""); s.add_argument("--confirm", action="store_true"); s.add_argument("--id")
    s = add("status", cmd_status); s.add_argument("--all", action="store_true")
    s = add("adopt", cmd_adopt); s.add_argument("--save", action="store_true"); s.add_argument("--full", action="store_true")
    s = add("execute-gate", cmd_execute_gate); s.add_argument("--batch", required=True)
    s = add("batch-start", cmd_batch_start); s.add_argument("--batch", required=True); s.add_argument("--owner", default="")
    s.add_argument("--confirm-risk", action="store_true"); s.add_argument("--allow-dirty-in-scope", action="store_true"); s.add_argument("--note", default="")
    s = add("task-done", cmd_task_done); s.add_argument("--batch", required=True); s.add_argument("--task", required=True)
    s.add_argument("--lock", required=True); s.add_argument("--note", default="")
    s = add("checkpoint", cmd_checkpoint); s.add_argument("--batch", required=True); s.add_argument("--lock", required=True); s.add_argument("--note", default="")
    s = add("check-run", cmd_check_run); s.add_argument("--batch", required=True); s.add_argument("--lock", required=True)
    s.add_argument("--step", required=True); s.add_argument("--task"); s.add_argument("--available", default=""); s.add_argument("--reason", default="")
    s = add("batch-submit", cmd_batch_submit); s.add_argument("--batch", required=True); s.add_argument("--lock", required=True)
    s.add_argument("--confirm-test-changes", action="store_true"); s.add_argument("--note", default="")
    s = add("pause", cmd_pause); s.add_argument("--batch", required=True); s.add_argument("--lock", required=True); s.add_argument("--note", default="")
    s = add("resume", cmd_resume); s.add_argument("--batch"); s.add_argument("--owner", default=""); s.add_argument("--take-over", action="store_true")
    s.add_argument("--accept-changes", action="store_true"); s.add_argument("--retry-failed", action="store_true")
    s.add_argument("--restore-checkpoint", choices=("prev", "rebuild")); s.add_argument("--note", default="")
    s = add("verify", cmd_verify); s.add_argument("--batch", required=True); s.add_argument("--lock"); s.add_argument("--available", default="")
    s.add_argument("--steps", default="")
    s = add("ac-report", cmd_ac_report); s.add_argument("--batch")
    add("impact", cmd_impact)
    s = add("ledger", cmd_ledger); s.add_argument("action", choices=("list", "add", "sync", "dismiss")); s.add_argument("--type", choices=tuple(L.TYPES))
    s.add_argument("--status"); s.add_argument("--batch"); s.add_argument("--title", default=""); s.add_argument("--desc", default="")
    s.add_argument("--blocking", action="store_true"); s.add_argument("--batches", default=""); s.add_argument("--acs", default=""); s.add_argument("--docs", default="")
    s.add_argument("--category"); s.add_argument("--provisional"); s.add_argument("--rationale", default=""); s.add_argument("--by", default="")
    s.add_argument("--id"); s.add_argument("--reason", default=""); s.add_argument("--note", default="")
    s = add("decide", cmd_decide); s.add_argument("--id"); s.add_argument("--decision", default=""); s.add_argument("--note", default="")
    s.add_argument("--confirm", action="store_true"); s.add_argument("--propose", action="append")
    s = add("doc-proposal", cmd_doc_proposal); s.add_argument("action", choices=("list", "approve", "reject", "apply-check")); s.add_argument("--id")
    s.add_argument("--note", default="")
    s = add("adopt-register", cmd_adopt_register); s.add_argument("--batch", required=True); s.add_argument("--note", default=""); s.add_argument("--owner", default="")
    s = add("target", cmd_target); s.add_argument("--batch", required=True); s.add_argument("--ac", required=True); s.add_argument("--level", required=True)
    s.add_argument("--reason", default=""); s.add_argument("--note", default="")
    s = add("accept-fault-injection", cmd_accept_fi); s.add_argument("--batch", required=True); s.add_argument("--ac", required=True); s.add_argument("--note", default="")
    s = add("guard", cmd_guard); s.add_argument("--path", action="append"); s.add_argument("--base"); s.add_argument("--batch")
    s = add("ui-map", cmd_ui_map); s.add_argument("action", choices=("show", "check", "candidates", "register", "remove", "tokens", "except"))
    s.add_argument("--batch"); s.add_argument("--cmp"); s.add_argument("--source", default="existing"); s.add_argument("--path"); s.add_argument("--export")
    s.add_argument("--package"); s.add_argument("--replace", action="store_true"); s.add_argument("--note", default="")
    s.add_argument("--file"); s.add_argument("--format"); s.add_argument("--var-pattern"); s.add_argument("--export-cmd"); s.add_argument("--alias", action="append")
    s.add_argument("--token"); s.add_argument("--audit-path"); s.add_argument("--value"); s.add_argument("--reason", default="")
    add("token-check", cmd_token_check)
    s = add("token-audit", cmd_token_audit); s.add_argument("--batch")
    s = add("ui-brief", cmd_ui_brief); s.add_argument("--batch", required=True); s.add_argument("--full", action="store_true")
    s = add("ui-plan-validate", cmd_ui_plan_validate); s.add_argument("--batch", required=True)
    a = ap.parse_args()
    try:
        a.fn(a)
    except Blocked as e:
        emit(e.payload, 2)
    except SystemExit:
        raise
    except Exception as e:  # 예상하지 못한 오류도 JSON으로(상태 파일은 원자적으로만 쓰므로 부분 기록 없음)
        emit({"ok": False, "error": "internal_error", "message": f"{type(e).__name__}: {e}"}, 1)


if __name__ == "__main__":
    main()
