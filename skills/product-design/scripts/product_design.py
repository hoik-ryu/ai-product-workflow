#!/usr/bin/env python3
"""/product-design 결정적 보조 스크립트 (Python 3.11+, 표준 라이브러리만 사용).

LLM은 인터뷰, 문서 작성, 프리뷰 화면 작성만 맡습니다. 게이트, 상태 전이, 승인, 해시, 추적성, 프리뷰 경계 판정은
모두 이 스크립트가 수행합니다. `.ai-workflow/design.json`은 이 스크립트만 씁니다.

하위 명령:
  check      사전 점검 + planning 게이트 + 상태·파일 교차 검증 + 다음 행동 안내
  start      design.json 생성(planning 승인·해시 기준 기록). 문서는 만들지 않음
  begin      단계 시작(ux_spec / preview). 앞 단계가 승인되어 있어야 함
  done       작성을 마친 산출물의 해시 기록(front matter revision 검사)
  trace      ID 존재·커버리지·구조 검사 (--stage ux_planning | structure | ux_spec | design_direction)
  checkpoint UX 설계 구조 확인 기록(IA + 화면 목록)
  submit     단계 제출(revision +1, 제시한 해시 기록)
  approve    사용자가 명시적으로 승인한 revision 기록(제출 후 변경되었으면 거부)
  pending    design-notes.md의 답변 대기 질문 라운드와 형식 오류
  reopen     승인·제출된 단계를 다시 엶(하위 단계 승인 무효화)
  impact     planning 변경 영향(바뀐 ID와 이를 참조하는 UXD/SCR)
             --design: 디자인 변경 영향 분류(WF-D01, 읽기 전용). --request <요청 JSON> 또는 --base <커밋>(파일 차이)
  rebase     planning 재승인 후 새 기준으로 디자인 재검토 시작
  refs       ID를 참조하는 디자인 문서 위치
  backup     기존 디자인 파일 수정 전 백업 필요 여부 판단·백업
  preview-scaffold  프리뷰 템플릿 복사(design-preview/)
  preview-check     프리뷰 manifest·경계 검사(빌드 없음)
  preview-verify    preview-check + pnpm install + pnpm build, 결과 기록
  status     상태 요약(/product-start 상태 표시와의 관계 포함)
  theme-check 테마 계약 검사(읽기 전용): 스키마·04 이름 대조·값 형식·04와 값 차이·tokens.css 일치(--print-css로 기대 CSS 출력)
  migrate    v1 → v2 전환(--to v2 [--theme-file] [--enable-gate design_direction] [--confirm]). 기본은 계획만 출력, 추가만 하고 기존 승인·해시 유지, 멱등

모든 출력은 JSON이며, 차단·실패 시 종료 코드 2를 반환합니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# 같은 폴더의 모듈(pd_core·pd_theme·pd_impact)을 불러옵니다. python3 -I(격리 모드)는 스크립트 폴더를 import 경로에 넣지 않으므로
# 이 파일의 폴더만 명시적으로 추가합니다. -I에서는 PYTHONDONTWRITEBYTECODE가 무시되므로 바이트코드 생성도 직접 끕니다.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pd_core import *  # noqa: E402,F401,F403
from pd_theme import *  # noqa: E402,F401,F403
from pd_impact import *  # noqa: E402,F401,F403


def annotate_problems(project: Path, st: dict, cv: dict) -> None:
    """v2: 승인·제출 후 바뀐 파일에 변경 영향 분류(기준 HEAD)를 붙입니다. 판단이 필요한 분류면 자동 처리하지 않음을 표시합니다."""
    targets = [p for p in cv["problems"] if p["kind"] in ("approved_modified", "submitted_modified")]
    if not targets:
        return
    try:
        items, _ = file_change_items(project, st, "HEAD", design_context(project))
    except SystemExit:
        return
    by_path = {i["source"]["path"]: i for i in items}
    for p in targets:
        cls = []
        for path in p["paths"]:
            if path == PREVIEW_TREE_KEY:
                hits = [i for i in items if i["source"]["path"].startswith(PREVIEW_DIR + "/")]
            else:
                hits = [by_path[path]] if path in by_path else []
            cls += [{"path": i["source"]["path"], "status": i["status"], "categories": [c["key"] for c in i["categories"]],
                     "reapproval_stages": i["reapproval_stages"]} for i in hits]
        p["classification"] = cls
        p["requires_user_decision"] = (not cls) or any(c["status"] in ("conditional", "needs_review") for c in cls)
        p["resolution"] = ("분류가 확정되지 않았습니다. 사용자 판단 후 reopen 또는 복원하세요(자동 처리 안 함)."
                           if p["requires_user_decision"] else "분류 결과를 보여 주고 사용자 확인 후 reopen 또는 복원하세요(자동 처리 안 함).")


def cmd_check(a) -> None:
    project = Path(a.project).resolve()
    ctx = gate_or_block(project)
    st = load_state(project)
    if st is None:
        conflicts = existing_design_paths(project)
        emit({"ok": True, "status": "not_started", "preflight": ctx["preflight"], "gate": ctx["gate"],
              "existing_paths": conflicts, "next": "start" if not conflicts else "기존 파일이 있어 시작할 수 없습니다. 보고 후 사용자 결정을 기다립니다.",
              "display_note": DISPLAY_NOTE})
    probs = state_shape_problems(st)
    if probs:
        block("invalid_state", "상태 파일 구조가 올바르지 않습니다. 자동으로 고치지 않습니다.", problems=probs,
              hint="v2 전환이 중간에 멈췄다면 migrate --to v2 --confirm으로 누락 필드만 복구할 수 있습니다. 그 밖에는 백업(.ai-workflow/backup/design/)이나 Git 이력으로 복원하세요.")
    changed = detect_outdated(project, st, ctx["gate"])
    if changed:
        block("design_outdated", "planning이 디자인 기준 이후 다시 승인되었습니다. 디자인 승인은 모두 무효입니다.", changed=changed,
              next="impact로 영향 범위를 확인하고, 사용자 확인 후 rebase --confirm")
    cv = cross_verify(project, st)
    out = {"ok": cv["consistent"], "status": overall_status(st), "stages": {k: {"status": v["status"], "revision": v["revision"]} for k, v in st["stages"].items()},
           "cross_verify": cv, "preflight": ctx["preflight"], "next": next_action(st), "display_note": DISPLAY_NOTE}
    if workflow_of(st) == "v2":
        out["workflow"] = workflow_info(st)
        annotate_problems(project, st, cv)
    if st["stages"]["ux_planning"]["status"] == "in_progress":
        pr = pending_round(project)
        out["pending_round"] = pr["pending"]
        out["last_round"] = pr["last_round"]
        if pr["errors"]:
            out["pending_errors"] = pr["errors"]
        if pr["pending"]:
            out["next"] = f"답변 대기 중인 라운드 {pr['pending']['round']}의 질문을 기록된 그대로 다시 보여 주고 답을 기다립니다(새로 만들지 않음)."
    if not cv["consistent"]:
        out.update(error="state_mismatch", message="상태 파일과 실제 파일이 다릅니다. 자동으로 고치거나 다시 승인하지 않습니다.")
        emit(out, 2)
    emit(out)


def cmd_start(a) -> None:
    project = Path(a.project).resolve()
    ctx = gate_or_block(project)
    if load_state(project) is not None:
        block("already_started", f"{STATE_REL}이 이미 있습니다. check로 현재 상태를 확인하세요.")
    existing = existing_design_paths(project)
    if existing:
        block("existing_files", f"{', '.join(existing)}가 이미 있습니다. 덮어쓰지 않습니다. 옮기거나 정리한 뒤 다시 실행하세요.", paths=existing)
    dirty = ctx["preflight"]["dirty"]
    if dirty:
        block("dirty_worktree", "커밋되지 않은 변경이 있습니다. 기획 승인 문서를 커밋한 뒤 시작하세요.", dirty=dirty)
    gate = ctx["gate"]
    st = {
        "schema_version": 1, "workflow": "ai-product-workflow", "skill": "product-design", "created_at": now(),
        "based_on": {"discovery_revision": gate.get("discovery_approved_revision"), "planning_revision": gate.get("planning_approved_revision"),
                     "planning_hashes": gate["planning_hashes"], "planning_commit": git(project, "rev-parse", "HEAD").strip()},
        "validity": {"status": "valid"},
        "stages": {"ux_planning": new_stage("in_progress", [UXP_FILE]),
                   "ux_spec": new_stage("locked", list(SPEC_FILES)),
                   "preview": new_stage("locked", [REVIEW_FILE])},
        "history": [],
    }
    st["stages"]["ux_spec"].update(structure_confirmed=None, based_on_ux_planning_revision=None)
    st["stages"]["preview"].update(based_on_ux_spec_revision=None, verification=None)
    add_history(st, "ux_planning", "started", 0, f"planning r{gate.get('planning_approved_revision')} 기준으로 시작")
    save_state(project, st)
    emit({"ok": True, "status": overall_status(st), "based_on": st["based_on"], "next": "UX Planning 인터뷰", "display_note": DISPLAY_NOTE})


def cmd_begin(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_stage_usable(st, a.stage)
    require_valid(project, st, a.stage)
    stage = a.stage
    if stage == "ux_planning":
        block("invalid_stage", "ux_planning은 start 또는 reopen으로 시작합니다.")
    s = st["stages"][stage]
    prev = "ux_planning" if stage == "ux_spec" else "ux_spec"
    for dep in implemented_deps(st, stage):
        if st["stages"][dep]["status"] != "approved":
            block("upstream_not_approved", f"{STAGE_LABEL[dep]}가 승인되지 않아 {STAGE_LABEL[stage]}를 시작할 수 없습니다.")
    if s["status"] != "not_started":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. not_started에서만 시작합니다.")
    s["status"] = "in_progress"
    key = "based_on_ux_planning_revision" if stage == "ux_spec" else "based_on_ux_spec_revision"
    s[key] = st["stages"][prev]["approved"]["revision"]
    if stage == "preview" and gate_on(st):
        s["based_on_design_direction_revision"] = st["stages"]["design_direction"]["approved"]["revision"]
    add_history(st, stage, "started", s["revision"], f"{prev} r{s[key]} 기준")
    save_state(project, st)
    out = {"ok": True, "stage": stage, "status": "in_progress", key: s[key], "next": next_action(st)}
    if deferred_deps(st, stage):
        out["deferred_dependencies"] = list(deferred_deps(st, stage))
        out["note"] = ("design_direction 게이트가 꺼져 있어 이 단계 승인을 확인하지 않았습니다. "
                       "켜려면 사용자 동의 후 migrate --to v2 --enable-gate design_direction --confirm.")
    emit(out)


def cmd_done(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    rel = a.path
    stage = stage_of(rel, st)
    if stage is None:
        block("unknown_artifact", f"{rel}은 /product-design 산출물이 아닙니다.", artifacts=STAGE_ARTIFACTS)
    require_stage_usable(st, stage)
    require_valid(project, st, stage)
    s = st["stages"][stage]
    if s["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. in_progress에서만 산출물을 기록합니다.")
    p = project / rel
    if not p.exists():
        block("missing_file", f"{rel}이 없습니다.")
    fm = front_matter_revision(p.read_text(encoding="utf-8"))
    if fm != s["revision"] + 1:
        block("revision_mismatch", f"{rel}의 front matter revision({fm})은 준비 중인 revision {s['revision'] + 1}이어야 합니다.")
    s["artifacts_done"][rel] = sha256_file(p)
    save_state(project, st)
    remaining = [x for x in s["artifacts"] if x not in s["artifacts_done"]]
    emit({"ok": True, "stage": stage, "recorded": rel, "remaining": remaining})


def cmd_pending(a) -> None:
    project = Path(a.project).resolve()
    require_state(project)
    pr = pending_round(project)
    emit({"ok": not pr["errors"], **pr}, 0 if not pr["errors"] else 2)


def cmd_trace(a) -> None:
    project = Path(a.project).resolve()
    if a.stage == "design_direction":
        st = require_state(project)
        require_stage_usable(st, "design_direction")
        res = trace_design_direction(project, st)
        emit({"stage": a.stage, **res}, 0 if res["ok"] else 2)
    fn = {"ux_planning": trace_ux_planning, "structure": trace_structure, "ux_spec": trace_ux_spec}[a.stage]
    res = fn(project)
    emit({"stage": a.stage, **res}, 0 if res["ok"] else 2)


def cmd_checkpoint(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "ux_spec")
    s = st["stages"]["ux_spec"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"ux_spec 상태가 {s['status']}입니다.")
    for rel in (IA_FILE, SCREENS_FILE):
        if rel not in s["artifacts_done"]:
            block("not_done", f"{rel}을 작성한 뒤 done으로 기록하세요.")
        if sha256_file(project / rel) != s["artifacts_done"][rel]:
            block("changed_since_done", f"{rel}이 done 기록 이후 바뀌었습니다. 다시 제시하고 done을 실행하세요.")
    res = trace_structure(project)
    if not res["ok"]:
        block("trace_failed", "구조 검사를 통과하지 못했습니다.", **res)
    s["structure_confirmed"] = {"revision": s["revision"] + 1, "at": now(), "signature": structure_signature(project)}
    add_history(st, "ux_spec", "structure_confirmed", s["revision"] + 1, a.note or "IA·화면 목록 구조 확인")
    save_state(project, st)
    emit({"ok": True, "structure_confirmed": s["structure_confirmed"], "counts": res["counts"], "warnings": res["warnings"]})


def cmd_submit(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_stage_usable(st, a.stage)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] != "in_progress":
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. in_progress에서만 제출합니다.")
    missing = [x for x in s["artifacts"] if x not in s["artifacts_done"]]
    if missing:
        block("not_done", "done으로 기록되지 않은 산출물이 있습니다.", missing=missing)
    cur = stage_current_hashes(project, stage)
    changed = [rel for rel in s["artifacts"] if cur.get(rel) != s["artifacts_done"].get(rel)]
    if changed:
        block("changed_since_done", "done 기록 이후 바뀐 파일이 있습니다. 확인 후 done을 다시 실행하세요.", paths=changed)
    target = s["revision"] + 1
    for rel in s["artifacts"]:
        fm = front_matter_revision((project / rel).read_text(encoding="utf-8"))
        if fm != target:
            block("revision_mismatch", f"{rel}의 front matter revision({fm})이 제출할 revision {target}과 다릅니다.")
    trace = None
    if stage == "ux_planning":
        pr = pending_round(project)
        if pr["pending"] or pr["errors"]:
            block("pending_questions", "답변을 기다리는 질문이 있거나 질문 기록 형식이 맞지 않아 제출할 수 없습니다.",
                  pending=pr["pending"], errors=pr["errors"])
        trace = trace_ux_planning(project)
    elif stage == "ux_spec":
        sc = s.get("structure_confirmed")
        carried = bool(sc) and sc.get("revision") != target and sc.get("signature") == structure_signature(project)
        if not sc or (sc.get("revision") != target and not carried):
            block("structure_not_confirmed", "이번 revision의 구조 확인(checkpoint)이 없습니다. IA·화면 목록을 먼저 확인받으세요."
                  + (" 이전에 확인받은 화면 구성과 달라졌습니다." if sc else ""))
        if carried:
            add_history(st, "ux_spec", "structure_carried", target, f"r{sc['revision']}에서 확인받은 화면 구성과 같아 구조 확인을 이어받음")
        trace = trace_ux_spec(project)
    elif stage == "design_direction":
        trace = trace_design_direction(project, st)
    else:
        require_dd_gate(st, "제출")
        pc = preview_check(project, st)
        if not pc["ok"]:
            block("preview_check_failed", "프리뷰 검사를 통과하지 못했습니다.", **pc)
        ver = s.get("verification") or {}
        fresh = ver.get("tree_hash") == cur[PREVIEW_TREE_KEY]
        if workflow_of(st) == "v2":
            v2h = preview_v2_hashes(project, st)
            fresh = (fresh or (ver.get("semantic_algo") == SEM_ALGO and ver.get("semantic_tree_hash") == v2h["semantic_tree_hash"])) \
                and ver.get("theme_hash") == v2h["theme_hash"]
        if ver.get("result") != "pass" or not fresh:
            block("preview_not_verified", "현재 프리뷰 파일로 preview-verify가 통과한 기록이 없습니다. preview-verify를 실행하세요.")
    if trace is not None and not trace["ok"]:
        block("trace_failed", "추적성 검사를 통과하지 못했습니다.", **trace)
    s["revision"] = target
    s["status"] = "awaiting_approval"
    s["submitted"] = {"revision": target, "at": now(), "hashes": cur}
    if stage == "preview" and workflow_of(st) == "v2":
        s["submitted"].update(preview_v2_hashes(project, st))
        if gate_on(st):
            s["submitted"].update(dd_binding(st))
    add_history(st, stage, "submitted", target)
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "awaiting_approval", "revision": target,
          "trace": trace, "warnings": (trace or {}).get("warnings", []),
          "next": f"r{target}을 제시하고 명시적 승인을 받습니다."})


def cmd_approve(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_stage_usable(st, a.stage)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] != "awaiting_approval":
        block("not_awaiting_approval", f"{stage} 상태가 {s['status']}입니다. 제출(submit)된 revision만 승인할 수 있습니다.")
    if a.revision != s["revision"]:
        block("revision_mismatch", f"승인 대상 revision은 r{s['revision']}입니다(요청: r{a.revision}).")
    cur = stage_current_hashes(project, stage)
    changed = diff_hashes(s["submitted"]["hashes"], cur)
    if stage == "preview" and workflow_of(st) == "v2":
        changed, theme_changed, _ = preview_record_changes(project, st, s["submitted"], "submitted")
        if theme_changed:
            block("theme_changed", "제출한 뒤 테마 파일이 바뀌었습니다. 프리뷰를 다시 검증·제출해야 합니다(reopen --stage preview).")
    if changed:
        block("changed_since_submit", "제시한 뒤 파일이 바뀌었습니다. 다시 제시(reopen → 수정 → submit)해야 합니다.", paths=changed)
    if stage == "preview" and gate_on(st):
        require_dd_gate(st, "승인")
        if (s["submitted"] or {}).get("design_direction_revision") != st["stages"]["design_direction"]["approved"]["revision"]:
            block("stale_preview", "제출한 프리뷰가 현재 승인된 Design Direction revision을 기준으로 하지 않습니다. 다시 검증·제출하세요.")
    if stage == "preview":
        ux = st["stages"]["ux_spec"]
        if ux["status"] != "approved" or s.get("based_on_ux_spec_revision") != ux["approved"]["revision"]:
            block("stale_preview", "프리뷰가 현재 승인된 UX 설계 revision을 기준으로 하지 않습니다.")
    s["status"] = "approved"
    s["approved"] = {"revision": s["revision"], "at": now(), "hashes": cur}
    if stage == "preview":
        s["approved"]["ux_spec_hashes"] = st["stages"]["ux_spec"]["approved"]["hashes"]
        if workflow_of(st) == "v2":
            s["approved"].update(preview_v2_hashes(project, st))
            if gate_on(st):
                s["approved"].update(dd_binding(st))
                rc = renderer_check(project, st)
                s["approved"]["renderer"] = {k: rc[k] for k in ("planned", "used", "switched", "reason")}
    if stage == "design_direction":
        ux = st["stages"]["ux_spec"]["approved"]
        s["approved"].update(ux_spec_revision=ux["revision"], ux_spec_hashes=ux["hashes"],
                             approved_vds=sorted(k for k, v in dd_vds(project).items() if v == "승인"),
                             renderer=_first_word(field_line(md_section(strip_fences(read_text(project, DD_FILE)), "렌더링 경로"), "렌더러")),
                             theme_hash=theme_hash(project, st))
    add_history(st, stage, "approved", s["revision"], a.note or "사용자 명시적 승인")
    if workflow_of(st) == "v1":
        nxt = NEXT_STAGE.get(stage)
        if nxt and st["stages"][nxt]["status"] == "locked":
            st["stages"][nxt]["status"] = "not_started"
            add_history(st, nxt, "unlocked", st["stages"][nxt]["revision"], f"{stage} r{s['revision']} 승인")
    else:
        # v2: 적용 중인 의존 단계가 모두 승인된 잠금 단계를 엽니다(design_direction 게이트가 꺼져 있으면 preview는 ux_spec만 봄).
        for k in stage_list(st):
            d = st["stages"][k]
            if d["status"] == "locked" and stage in active_deps(st, k) \
                    and all(st["stages"][x]["status"] == "approved" for x in active_deps(st, k)):
                d["status"] = "not_started"
                add_history(st, k, "unlocked", d["revision"], f"{stage} r{s['revision']} 승인")
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "approved", "revision": s["revision"], "overall": overall_status(st), "next": next_action(st)})


def cmd_reopen(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_stage_usable(st, a.stage)
    require_valid(project, st, a.stage)
    stage = a.stage
    s = st["stages"][stage]
    if s["status"] not in ("approved", "awaiting_approval"):
        block("invalid_transition", f"{stage} 상태가 {s['status']}입니다. approved/awaiting_approval만 다시 열 수 있습니다.")
    event = "reopened" if s["status"] == "approved" else "changes_requested"
    if s.get("approved"):
        s["last_approved"] = s["approved"]
    s["approved"] = None
    s["submitted"] = None
    s["status"] = "in_progress"
    s["artifacts_done"] = {}
    affected = invalidate_downstream(st, stage, f"{stage} 재검토로 승인 무효화")
    add_history(st, stage, event, s["revision"], a.reason)
    save_state(project, st)
    emit({"ok": True, "stage": stage, "status": "in_progress", "preparing_revision": s["revision"] + 1,
          "invalidated": affected, "next": "수정할 파일의 front matter revision을 준비 중인 revision으로 올리고, 수정 후 done을 다시 실행합니다."})


def cmd_impact(a) -> None:
    if getattr(a, "design", False):
        return cmd_impact_design(a)
    if getattr(a, "request", None) or getattr(a, "base", None):
        block("invalid_arguments", "--request와 --base는 --design과 함께만 씁니다.")
    project = Path(a.project).resolve()
    st = require_state(project)
    commit = st["based_on"].get("planning_commit")
    changed_files = [f for f, h in st["based_on"]["planning_hashes"].items()
                     if not (project / f).exists() or sha256_file(project / f) != h]
    changed_ids: dict[str, list[str]] = {"added": [], "removed": [], "changed": []}
    full_review = False
    for f in changed_files:
        old = None
        if commit:
            try:
                old = git(project, "show", f"{commit}:{f}")
            except RuntimeError:
                old = None
        if old is None or sha256_bytes(old.encode("utf-8")) != st["based_on"]["planning_hashes"].get(f):
            full_review = True
            continue
        ob, nb = id_blocks(old), id_blocks(read_text(project, f))
        changed_ids["added"] += sorted(set(nb) - set(ob))
        changed_ids["removed"] += sorted(set(ob) - set(nb))
        changed_ids["changed"] += sorted(k for k in set(ob) & set(nb) if ob[k] != nb[k])
    targets = set(changed_ids["removed"] + changed_ids["changed"])
    prd_changed = any(f.endswith("02-prd.md") for f in changed_files)
    affected = refs_for(project, targets)
    emit({"ok": True, "changed_files": changed_files, "changed_ids": changed_ids, "full_review_required": full_review,
          "prd_changed": prd_changed, "affected": affected,
          "note": "기준 커밋에서 이전 기획을 읽을 수 없으면 전체 재검토가 필요합니다." if full_review else ""})


def cmd_theme_check(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    res = theme_check(project, st)
    if not a.print_css:
        res.pop("expected_css", None)
    emit({"ok": res["ok"], **res}, 0 if res["ok"] else 2)


def cmd_impact_design(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    declared = (st.get("config") or {}).get("workflow")
    applied = workflow_of(st)
    ctx = design_context(project)
    if a.request:
        req_path = Path(a.request)
        req_path = req_path if req_path.is_absolute() else (Path.cwd() / req_path)
        items = []
        for it in load_change_request(req_path):
            facts = [classify_fact(f if isinstance(f, dict) else {"kind": None}, ctx) for f in it["facts"]]
            if not facts:
                facts = [classify_fact({"kind": None}, ctx)]
            items.append(aggregate_item(it["id"], it.get("summary", ""), facts, st))
        unrelated: list[str] = []
        source = {"mode": "request", "request": str(req_path)}
    else:
        base = a.base or "HEAD"
        items, unrelated = file_change_items(project, st, base, ctx)
        source = {"mode": "files", "base": base}
    counts = {k: sum(1 for i in items if i["status"] == k) for k in ("classified", "conditional", "needs_review", "excluded")}
    by_cat = {c: sum(1 for i in items if any(x["key"] == c for x in i["categories"])) for c in CATEGORY_ORDER}
    reapproval = []
    for i in items:
        for s in i["reapproval_stages"]:
            if s not in reapproval:
                reapproval.append(s)
    notes = []
    order = stage_list(st)
    if applied == "v2":
        if not gate_on(st):
            notes.append("design_direction 게이트가 꺼져 있습니다: ④는 Design Direction에 기록하되, 프리뷰 승인 조건과는 연결되지 않습니다.")
        if not (st.get("config") or {}).get("theme_file"):
            notes.append("config.theme_file이 없어 ③ 테마 값 변경도 UX 설계 영향(v1 규칙)으로 계산했습니다.")
    notes.append("분류 결과로 승인 상태를 자동으로 바꾸지 않습니다. conditional·needs_review 항목은 사용자 판단이 필요합니다.")
    emit({"ok": True, "mode": "design", "workflow": {"declared": declared, "applied": applied},
          "engine_stages": [k for k in order if k in IMPLEMENTED_STAGES],
          "not_implemented_stages": [k for k in order if k not in IMPLEMENTED_STAGES],
          "source": source, "items": items, "unrelated_paths": unrelated,
          "summary": {**counts, "by_category": by_cat, "reapproval_stages": reapproval,
                      "requires_user_decision": [i["id"] for i in items if i["requires_user_decision"]]},
          "categories": {k: {**v, "target_available": v["target"] in IMPLEMENTED_STAGES and v["target"] in order} for k, v in CHANGE_CATEGORIES.items()},
          "rules_ref": "skills/product-design/reference/change-impact.md", "read_only": True, "notes": notes})


def cmd_refs(a) -> None:
    project = Path(a.project).resolve()
    ids = set(a.id)
    emit({"ok": True, "ids": sorted(ids), "references": refs_for(project, ids)})


def cmd_rebase(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    ctx = gate_or_block(project)
    detect_outdated(project, st, ctx["gate"])
    if st.get("validity", {}).get("status") != "outdated":
        block("not_outdated", "디자인 기준이 현재 planning 승인과 같습니다. rebase할 필요가 없습니다.")
    if not a.confirm:
        block("confirm_required", "사용자 확인 후 --confirm으로 실행합니다. 모든 디자인 승인이 해제되고 UX Planning부터 재검토합니다.")
    # 새 기준 커밋(planning_commit)이 재승인된 기획을 가리키도록, 기획 파일과 state.yaml만 커밋 여부를 봅니다.
    planning_dirty = [p for p in git_dirty_paths(project) if p.startswith("docs/planning/") or p == WORKFLOW_STATE_REL]
    if planning_dirty:
        block("dirty_worktree", "재승인된 기획이 커밋되지 않았습니다. 기획 문서와 state.yaml을 커밋한 뒤 실행하세요.", dirty=planning_dirty)
    old = st["based_on"]
    gate = ctx["gate"]
    st["based_on"] = {"discovery_revision": gate.get("discovery_approved_revision"), "planning_revision": gate.get("planning_approved_revision"),
                      "planning_hashes": gate["planning_hashes"], "planning_commit": git(project, "rev-parse", "HEAD").strip(),
                      "previous": {k: old[k] for k in ("planning_revision", "planning_commit")}}
    up = st["stages"]["ux_planning"]
    if up.get("approved"):
        up["last_approved"] = up["approved"]
    up.update(status="in_progress", approved=None, submitted=None, artifacts_done={})
    invalidate_downstream(st, "ux_planning", "planning 변경으로 디자인 재검토")
    st["validity"] = {"status": "valid"}
    add_history(st, "design", "rebased", None, f"planning r{old.get('planning_revision')} → r{gate.get('planning_approved_revision')}")
    save_state(project, st)
    emit({"ok": True, "status": overall_status(st), "based_on": st["based_on"], "next": "바뀐 기획 항목에 대해 UX Planning을 재검토합니다."})


def cmd_backup(a) -> None:
    project = Path(a.project).resolve()
    raw = a.path
    if not raw or Path(raw).is_absolute() or ".." in Path(raw).parts:
        block("invalid_path", "프로젝트 기준 상대 경로만 허용합니다(절대 경로, '..' 불가).", path=raw)
    p = (project / raw).resolve()
    try:
        rel = str(p.relative_to(project))
    except ValueError:
        block("invalid_path", "프로젝트 밖을 가리키는 경로입니다(심볼릭 링크 포함).", path=raw)
    if not (rel.startswith(DESIGN_DIR + "/") or rel.startswith(PREVIEW_DIR + "/")):
        block("not_design_path", "디자인 산출물만 백업합니다.", path=rel)
    if p.exists() and not p.is_file():
        block("invalid_path", "파일만 백업합니다.", path=rel)
    if not p.exists():
        emit({"ok": True, "backup": None, "reason": "파일이 없습니다(새 파일)."})
    tracked = git(project, "ls-files", "--error-unmatch", rel, check=False).strip() != ""
    dirty = bool(git(project, "status", "--porcelain", "--", rel).strip())
    if tracked and not dirty:
        emit({"ok": True, "backup": None, "reason": "Git으로 추적되고 미커밋 변경이 없어 Git 이력으로 복원할 수 있습니다."})
    dest = project / ".ai-workflow/backup/design" / rel.replace("/", "__")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    emit({"ok": True, "backup": str(dest.relative_to(project)), "reason": "Git으로 보호되지 않아 단일 슬롯에 백업했습니다(같은 파일의 이전 백업은 덮어씀)."})


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def cmd_preview_scaffold(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "preview")
    s = st["stages"]["preview"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"preview 상태가 {s['status']}입니다. begin --stage preview 후 실행하세요.")
    dest = project / PREVIEW_DIR
    if dest.exists():
        block("existing_files", f"{PREVIEW_DIR}/가 이미 있습니다. 덮어쓰지 않습니다.")
    shutil.copytree(skill_dir() / "templates" / "preview", dest)
    gi = dest / "gitignore"
    if gi.exists():
        gi.rename(dest / ".gitignore")
    man = dest / "preview.manifest.json"
    data = json.loads(man.read_text(encoding="utf-8"))
    data["ux_spec_revision"] = st["stages"]["ux_spec"]["approved"]["revision"]
    if gate_on(st) and st["stages"]["design_direction"]["status"] == "approved":
        data["design_direction_revision"] = st["stages"]["design_direction"]["approved"]["revision"]
    data["screens"] = {k: {"file": "", "states": []} for k in sorted(screen_info(project))}
    man.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    emit({"ok": True, "created": PREVIEW_DIR, "files": preview_files(project), "next": "화면·mock·registry를 작성하고 preview-verify를 실행합니다."})


def cmd_preview_check(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    res = preview_check(project, st)
    emit({"ok": res["ok"], **res}, 0 if res["ok"] else 2)


def cmd_preview_verify(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    require_valid(project, st, "preview")
    s = st["stages"]["preview"]
    if s["status"] != "in_progress":
        block("invalid_transition", f"preview 상태가 {s['status']}입니다.")
    pc = preview_check(project, st)
    steps = []
    result = "fail"
    if pc["ok"]:
        root = project / PREVIEW_DIR
        lock = (root / "pnpm-lock.yaml").exists()
        cmds = [["pnpm", "install", "--frozen-lockfile"] if lock else ["pnpm", "install"], ["pnpm", "run", "build"]]
        result = "pass"
        for cmd in cmds:
            try:
                p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=a.timeout)
                rc, out = p.returncode, (p.stdout + p.stderr)
            except FileNotFoundError:
                rc, out = 127, "pnpm을 찾을 수 없습니다."
            except subprocess.TimeoutExpired:
                rc, out = 124, "시간 초과"
            steps.append({"run": " ".join(cmd), "exit": rc, "tail": out.strip().splitlines()[-15:]})
            if rc != 0:
                result = "fail"
                break
    s["verification"] = {"result": result, "at": now(), "tree_hash": preview_tree_hash(project), "check": pc, "steps": steps}
    if workflow_of(st) == "v2":
        s["verification"].update(preview_v2_hashes(project, st))
    add_history(st, "preview", "verified" if result == "pass" else "verify_failed", s["revision"])
    save_state(project, st)
    out = {"ok": result == "pass", "result": result, "check": pc, "steps": steps,
           "run_command": f"pnpm --dir {PREVIEW_DIR} dev", "url": "http://localhost:55180/"}
    emit(out, 0 if result == "pass" else 2)


def cmd_migrate(a) -> None:
    import copy
    project = Path(a.project).resolve()
    if a.to != "v2":
        block("invalid_arguments", "지원하는 전환은 --to v2뿐입니다.")
    st = load_state(project)
    if st is None:
        block("no_design_state", f"{STATE_REL}이 없습니다.")
    path = project / STATE_REL
    original_text = path.read_text(encoding="utf-8")
    wf = (st.get("config") or {}).get("workflow") or "v1"
    if wf not in WORKFLOWS or not isinstance(st.get("stages"), dict) or any(k not in st["stages"] for k in STAGES):
        block("invalid_state", "기본 단계(ux_planning·ux_spec·preview)가 없거나 워크플로 값이 잘못되어 전환할 수 없습니다. 백업이나 Git 이력으로 복원하세요.")
    new = copy.deepcopy(st)
    cfg = new.setdefault("config", {})
    changes: list[str] = []
    theme_rel = _theme_path_ok(project, a.theme_file) if a.theme_file else None
    theme_change = None
    if cfg.get("theme_file") and theme_rel and cfg["theme_file"] != theme_rel:
        if not a.replace_theme_file:
            block("theme_file_conflict", f"이미 테마 파일이 {cfg['theme_file']}로 설정되어 있습니다. 바꾸려면 --replace-theme-file(사용자 확인)을 함께 씁니다.")
        nt = read_theme(project, theme_rel)
        if nt["errors"]:
            block("invalid_theme_file", "새 테마 파일이 계약 검사를 통과하지 못했습니다.", errors=nt["errors"])
        old_rel = cfg["theme_file"]
        theme_change = {"from": old_rel, "to": theme_rel, "from_hash": theme_hash(project, new), "to_hash": sha256_file(project / theme_rel),
                        "at": now(), "contract": nt["contract"]}
        cfg["theme_file"] = theme_rel
        new.setdefault("theme_history", []).append(theme_change)
        changes.append(f"config.theme_file: {old_rel} → {theme_rel}" + ("(내용 같음: 프리뷰 영향 없음)" if theme_change["from_hash"] == theme_change["to_hash"]
                                                                       else "(내용 다름: 승인된 프리뷰는 theme_changed → 다시 검증·승인, UX Spec·Design Direction 승인 유지)"))
    if cfg.get("workflow") != "v2":
        cfg["workflow"] = "v2"
        changes.append("config.workflow = v2")
    if "theme_file" not in cfg or (theme_rel and not cfg.get("theme_file")):
        cfg["theme_file"] = theme_rel or cfg.get("theme_file")
        changes.append(f"config.theme_file = {cfg['theme_file']}")
    dd = new["stages"].get("design_direction")
    if dd is None:
        status = "not_started" if new["stages"]["ux_spec"]["status"] == "approved" else "locked"
        new["stages"]["design_direction"] = {"status": status, "revision": 0, "artifacts": [DD_FILE], "artifacts_done": {},
                                             "submitted": None, "approved": None, "based_on_ux_spec_revision": None}
        changes.append(f"stages.design_direction 추가(status: {status}, 승인 없음)")
    elif wf == "v1" and (dd.get("status") not in ("locked", "not_started") or dd.get("approved") or dd.get("submitted")):
        # v1 상태에 진행·승인된 design_direction이 끼어 있으면 받아들이지 않습니다(승격 금지). v2에서는 정상 기록입니다.
        block("invalid_state", "기존 design_direction 기록이 진행·승인 상태입니다. 자동으로 받아들이지 않습니다(이전 승인을 새 단계 승인으로 승격하지 않음).")
    if "theme" not in new:
        new["theme"] = {"path": cfg.get("theme_file"), "baseline_hash": theme_hash(project, new), "recorded_at": now()}
        changes.append("theme 기준 해시 기록")
    pv = new["stages"]["preview"]
    if "review" not in pv:
        pv["review"] = None
        changes.append("stages.preview.review = null(M2 검토 기록 자리)")
    if pv["status"] in ("approved", "awaiting_approval") and "v2_baseline" not in pv:
        kind = "approved" if pv["status"] == "approved" else "submitted"
        pv["v2_baseline"] = {"record": kind, "revision": pv[kind]["revision"], "semantic_tree_hash": preview_semantic_hash(project), "semantic_algo": SEM_ALGO,
                             "theme_hash": theme_hash(project, new), "source": "migration", "at": now()}
        changes.append(f"stages.preview.v2_baseline 기록({kind} r{pv[kind]['revision']}의 의미 해시·테마 해시, 기존 승인 기록은 그대로)")
    gate_changes: list[str] = []
    gate_effect = None
    if a.enable_gate:
        gates = cfg.setdefault("gates", {})
        if not gates.get(a.enable_gate):
            gates[a.enable_gate] = True
            pst = pv["status"]
            dds = new["stages"]["design_direction"]["status"]
            gate_effect = {
                "approved": "프리뷰 승인과 해시는 그대로 유지됩니다(게이트 이전 승인으로 표시). 다음 프리뷰 개정(reopen 후 제출·승인)부터 Design Direction 승인이 필요합니다.",
                "awaiting_approval": "프리뷰 제출 기록은 그대로입니다. 승인하기 전에 Design Direction 승인이 필요합니다.",
                "in_progress": "프리뷰 작업은 계속할 수 있습니다. 제출 전에 Design Direction 승인이 필요합니다.",
            }.get(pst, "프리뷰를 시작(begin)하기 전에 Design Direction 승인이 필요합니다.")
            new.setdefault("gate_activations", []).append({"gate": a.enable_gate, "at": now(), "preview_status": pst,
                                                          "preview_approved_revision": (pv.get("approved") or {}).get("revision"),
                                                          "design_direction_status": dds})
            gate_changes.append(f"config.gates.{a.enable_gate} = true (프리뷰 현재 상태: {pst}, Design Direction: {dds})")
    if not changes and not gate_changes:
        emit({"ok": True, "status": "already_v2", "changed": False, "message": "이미 v2이고 필요한 필드가 모두 있습니다. 바꾼 것이 없습니다.",
              "workflow": workflow_info(new)})
    # 전환 전 점검: 기획 게이트, outdated 아님, 교차 검증 일치(손상된 상태를 옮기지 않음)
    gate = read_gate(project)
    if not gate["ok"]:
        block("migrate_precheck_failed", "planning 게이트를 통과하지 못해 전환하지 않습니다.", gate=gate)
    if st.get("validity", {}).get("status") == "outdated" or [f for f, h in st["based_on"]["planning_hashes"].items() if gate["planning_hashes"].get(f) != h]:
        block("migrate_precheck_failed", "디자인 기준이 현재 planning과 다릅니다(outdated). impact → rebase 후 전환하세요.")
    cv = cross_verify(project, st if wf == "v1" and "design_direction" not in st["stages"] else new)
    if not cv["consistent"]:
        block("migrate_precheck_failed", "상태와 파일이 일치하지 않아 전환하지 않습니다. 먼저 check의 문제를 해결하세요.", problems=cv["problems"])
    allowed = {"config.theme_file"} if theme_change else set()
    bad = [x for x in _preserved(st, new) if x not in allowed]
    if bad:
        block("migrate_precheck_failed", "전환 계획이 기존 필드를 바꿉니다. 쓰지 않았습니다.", fields=bad)
    plan = {"from": wf, "to": "v2", "changes": changes + gate_changes,
            **({"gate_effect": gate_effect} if gate_effect else {}),
            "preserved": {k: {"status": v["status"], "revision": v["revision"],
                              "approved_revision": (v.get("approved") or {}).get("revision")} for k, v in st["stages"].items()},
            "not_promoted": "기존 승인(ux_spec·preview 등)을 design_direction 승인으로 옮기지 않습니다.",
            "after": {"design_direction": new["stages"]["design_direction"]["status"], "theme_file": cfg.get("theme_file")}}
    if not a.confirm:
        emit({"ok": True, "dry_run": True, "plan": plan,
              "next": "사용자 확인 후 같은 명령에 --confirm" + ("(게이트 활성화는 명시적 동의가 필요합니다)" if gate_changes else "")})
    # 백업(파일 안전 규칙): Git 추적·clean이면 생략, 아니면 단일 슬롯
    backup = None
    tracked = git(project, "ls-files", "--error-unmatch", STATE_REL, check=False).strip() != ""
    dirty = bool(git(project, "status", "--porcelain", "--", STATE_REL).strip())
    if not tracked or dirty:
        bdir = project / ".ai-workflow/backup/design"
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "design.json.pre-v2").write_text(original_text, encoding="utf-8")
        backup = ".ai-workflow/backup/design/design.json.pre-v2"
    if changes and "migration" in new:  # 중간에 멈춘 전환 복구: 처음 전환 기록은 그대로 두고 history에만 남깁니다
        add_history(new, "design", "migration_repaired", None, f"누락 필드 복구: {', '.join(changes)}")
    elif changes:
        add_history(new, "design", "migrated", None, f"{wf} → v2 ({len(changes)}개 항목 추가, 기존 승인·해시·revision 유지)")
        new["migration"] = {"from": wf, "to": "v2", "at": now(), "backup": backup}
    for g in gate_changes:
        add_history(new, "design", "gate_enabled", None, f"{g} — 사용자 동의. 기존 승인·해시·revision 유지")
    if theme_change:
        add_history(new, "design", "theme_file_changed", None, f"{theme_change['from']} → {theme_change['to']} — 사용자 확인. 기존 승인·해시·revision 유지")
    try:
        save_state(project, new)
        if a.simulate_failure:
            raise RuntimeError("시험용 실패(--simulate-failure)")
        written = json.loads(path.read_text(encoding="utf-8"))
        bad = [x for x in _preserved(st, written) if x not in allowed] + state_shape_problems(written)
        if bad:
            raise RuntimeError(f"전환 후 검증 실패: {bad}")
    except Exception as e:  # 부분 실패: 원래 파일로 되돌림
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".design.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(original_text)
        os.replace(tmp, path)
        block("migrate_failed", f"전환을 되돌렸습니다: {e}", restored=True)
    emit({"ok": True, "status": "migrated" if changes and wf == "v1" else "updated", "plan": plan, "backup": backup, "workflow": workflow_info(new)})


def cmd_status(a) -> None:
    project = Path(a.project).resolve()
    st = require_state(project)
    gate = read_gate(project)
    cv = cross_verify(project, st)
    emit({"ok": cv["consistent"] and gate["ok"], "overall": overall_status(st),
          "stages": {k: {"status": v["status"], "revision": v["revision"],
                         "approved_revision": (v.get("approved") or {}).get("revision")} for k, v in st["stages"].items()},
          "based_on": {k: st["based_on"].get(k) for k in ("discovery_revision", "planning_revision", "planning_commit")},
          "validity": st.get("validity"), "gate_ok": gate["ok"], "state_yaml_design_status": gate.get("state_yaml_design_status"),
          "cross_verify": cv, "next": next_action(st), "display_note": DISPLAY_NOTE,
          **({"workflow": workflow_info(st)} if workflow_of(st) == "v2" else {})})


class JsonArgParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # 인자 오류도 JSON으로
        block("invalid_arguments", message)


def main() -> None:
    ap = JsonArgParser(description="/product-design helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args):
        s = sub.add_parser(name)  # 하위 파서도 JsonArgParser(add_subparsers 기본값: 부모 클래스)
        s.add_argument("--project", required=True)
        s.set_defaults(fn=fn)
        return s

    add("check", cmd_check)
    add("start", cmd_start)
    s = add("begin", cmd_begin); s.add_argument("--stage", required=True, choices=ALL_STAGES)
    s = add("done", cmd_done); s.add_argument("--path", required=True)
    s = add("trace", cmd_trace); s.add_argument("--stage", required=True, choices=("ux_planning", "structure", "ux_spec", "design_direction"))
    s = add("checkpoint", cmd_checkpoint); s.add_argument("--note", default="")
    s = add("submit", cmd_submit); s.add_argument("--stage", required=True, choices=ALL_STAGES)
    s = add("approve", cmd_approve); s.add_argument("--stage", required=True, choices=ALL_STAGES)
    s.add_argument("--revision", required=True, type=int); s.add_argument("--note", default="")
    s = add("reopen", cmd_reopen); s.add_argument("--stage", required=True, choices=ALL_STAGES); s.add_argument("--reason", required=True)
    s = add("impact", cmd_impact); s.add_argument("--design", action="store_true")
    s.add_argument("--request"); s.add_argument("--base")
    add("pending", cmd_pending)
    s = add("rebase", cmd_rebase); s.add_argument("--confirm", action="store_true")
    s = add("refs", cmd_refs); s.add_argument("--id", required=True, action="append")
    s = add("backup", cmd_backup); s.add_argument("--path", required=True)
    add("preview-scaffold", cmd_preview_scaffold)
    add("preview-check", cmd_preview_check)
    s = add("preview-verify", cmd_preview_verify); s.add_argument("--timeout", type=int, default=600)
    add("status", cmd_status)
    s = add("migrate", cmd_migrate); s.add_argument("--to", required=True); s.add_argument("--theme-file")
    s.add_argument("--confirm", action="store_true"); s.add_argument("--simulate-failure", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--enable-gate", choices=GATES)
    s.add_argument("--replace-theme-file", action="store_true")
    s = add("theme-check", cmd_theme_check); s.add_argument("--print-css", action="store_true")
    a = ap.parse_args()
    try:
        a.fn(a)
    except SystemExit:
        raise
    except Exception as e:  # 예상하지 못한 오류도 JSON으로 보고(상태 파일은 원자적으로만 씀)
        block("internal_error", f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
