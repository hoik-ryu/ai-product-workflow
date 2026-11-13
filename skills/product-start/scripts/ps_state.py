#!/usr/bin/env python3
"""/product-start 상태 파일의 시각·승인 기록 도우미(표준 라이브러리만, `python3 -I`로 실행, JSON 출력).

D-001: LLM이 history·승인 시각을 추측해 쓰지 않도록, 시각이 들어가는 기록은 이 스크립트가 실제 시스템 UTC 시각으로 씁니다.
- `now`: 현재 UTC 시각(project.created_at 등에 그대로 씀)
- `event`: history에 전이 항목 하나 추가(시각은 스크립트가 정함)
- `approve`: 명시적 승인 전이(T4 discovery·T8 planning) — 산출물 해시 계산, approved.{revision, at, hashes}, 상태·잠금 해제, history `approved`
- `reopen`: 승인된 planning을 다시 엶(T9, `--confirm` 필수) — 승인 기록 검증, approved 초기화(이전 승인은 history에 보존), design 잠금, history `reopened`
- `check`: 읽기 전용. history·승인 시각이 형식에 맞고 미래가 아니며 순서가 맞는지 검사(기존 기록은 고치지 않음)

명시적 승인인지(사용자 문장) 판단은 Skill(LLM)이 합니다. 이 스크립트는 판단하지 않고 기록만 합니다.
기존 state.yaml(이 스크립트 이전 기록)과 호환됩니다: 새 history 항목에만 `src: engine`이 붙고, 기존 항목은 그대로 둡니다.
종료 코드: 0 성공, 2 차단(조건 불충족·형식 문제), 1 내부 오류.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_REL = ".ai-workflow/state.yaml"
ARTIFACTS = {
    "discovery": ["docs/planning/01-discovery.md"],
    "planning": ["docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md",
                 "docs/planning/05-acceptance-criteria.md"],
}
STAGES = ("discovery", "planning", "design")
EVENTS = ("started", "submitted", "changes_requested", "approved", "reopened", "outdated", "generated")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
FUTURE_TOLERANCE = timedelta(minutes=2)


class Blocked(Exception):
    def __init__(self, error: str, message: str, **extra):
        super().__init__(message)
        self.payload = {"ok": False, "error": error, "message": message, **extra}


def emit(obj: dict, code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    sys.exit(code)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> datetime | None:
    if not TS_RE.fullmatch(s or ""):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lock(project: Path):
    """state.yaml을 쓰는 명령은 프로젝트당 하나만(.ai-workflow 디렉터리 배타 잠금, /product-init과 같은 방식)."""
    try:
        import fcntl
    except ImportError:
        return None
    d = project / ".ai-workflow"
    fd = os.open(d, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Blocked("state_busy", "다른 명령이 같은 프로젝트의 상태 파일을 쓰는 중입니다. 끝난 뒤 다시 실행하세요.")
    return fd


def read_lines(project: Path) -> list[str]:
    p = project / STATE_REL
    if not p.is_file():
        raise Blocked("no_state", f"{STATE_REL}이 없습니다.")
    return p.read_text(encoding="utf-8").split("\n")


def write_lines(project: Path, lines: list[str]) -> None:
    p = project / STATE_REL
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text("\n".join(lines), encoding="utf-8")
        os.replace(tmp, p)
    except BaseException:
        tmp.unlink(missing_ok=True)  # 원본은 os.replace 전까지 그대로이므로 임시 파일만 지움
        raise


def stage_span(lines: list[str], stage: str) -> tuple[int, int]:
    start = next((i for i, l in enumerate(lines) if re.match(rf"^  {stage}:[ \t]*(#.*)?$", l)), None)
    if start is None:
        raise Blocked("state_format", f"state.yaml에서 stages.{stage}를 찾지 못했습니다.")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z_]+:", lines[j]) or re.match(r"^\S", lines[j]):
            end = j
            break
    return start, end


def get_scalar(lines: list[str], a: int, b: int, key: str, indent: int = 4) -> str | None:
    for l in lines[a:b]:
        m = re.match(rf"^{' ' * indent}{key}:[ \t]*\"?([^\"#\s]*)\"?", l)
        if m:
            return m.group(1)
    return None


def set_scalar(lines: list[str], a: int, b: int, key: str, value: str, indent: int = 4) -> None:
    for i in range(a, b):
        m = re.match(rf"^({' ' * indent}{key}:)([ \t]*)([^#]*?)([ \t]*#.*)?$", lines[i])
        if m:
            lines[i] = f"{m.group(1)} {value}" + (f"   {m.group(4).strip()}" if m.group(4) else "")
            return
    raise Blocked("state_format", f"state.yaml에서 {key} 항목을 찾지 못했습니다.")


def yq(s: str) -> str:
    return '"' + re.sub(r"\s+", " ", s or "").replace("\\", "\\\\").replace('"', '\\"').strip() + '"'


def history_entry(stage: str, event: str, revision: int, note: str, at: str) -> str:
    return f"  - {{ at: \"{at}\", stage: {stage}, event: {event}, revision: {revision}, note: {yq(note)}, src: engine }}"


def append_history(lines: list[str], entry: str) -> None:
    h = next((i for i, l in enumerate(lines) if re.match(r"^history:", l)), None)
    if h is None:
        if lines and lines[-1] == "":
            lines.insert(len(lines) - 1, "history:")
            h = len(lines) - 2
        else:
            lines.append("history:")
            h = len(lines) - 1
    if re.match(r"^history:[ \t]*\[\][ \t]*(#.*)?$", lines[h]):
        lines[h] = "history:"
    last = h
    for j in range(h + 1, len(lines)):
        if re.match(r"^  - ", lines[j]):
            last = j
        elif re.match(r"^\S", lines[j]):
            break
    lines.insert(last + 1, entry)


def history_items(lines: list[str]) -> list[dict]:
    out = []
    h = next((i for i, l in enumerate(lines) if re.match(r"^history:", l)), None)
    if h is None:
        return out
    for j in range(h + 1, len(lines)):
        l = lines[j]
        if re.match(r"^\S", l):
            break
        if re.match(r"^  - ", l):
            at = re.search(r"\bat:[ \t]*\"?([^\",}]*)\"?", l)
            out.append({"line": j + 1, "at": at.group(1).strip() if at else None, "engine": bool(re.search(r"\bsrc:[ \t]*engine\b", l)),
                        "event": (re.search(r"\bevent:[ \t]*([\w]+)", l) or [None, None])[1]})
    return out


def frontmatter_revision(p: Path) -> str | None:
    m = re.match(r"---\n(.*?)\n---", p.read_text(encoding="utf-8"), re.S)
    r = re.search(r"^revision:[ \t]*\"?(\w+)", m.group(1), re.M) if m else None
    return r.group(1) if r else None


# ---------------------------------------------------------------- 명령
def cmd_now(a) -> None:
    emit({"ok": True, "now": now()})


def cmd_event(a) -> None:
    project = Path(a.project).resolve()
    if a.stage not in STAGES or a.event not in EVENTS:
        raise Blocked("invalid_arguments", f"stage는 {'/'.join(STAGES)}, event는 {'/'.join(EVENTS)} 중 하나입니다.")
    if a.event == "approved":
        raise Blocked("use_approve", "승인은 approve 명령으로 기록합니다(해시·승인 시각을 함께 기록).")
    if a.stage == "planning" and a.event == "reopened":
        raise Blocked("use_reopen", "planning 재개(T9)는 reopen --confirm 명령으로 합니다(승인 기록 검증·초기화·design 잠금을 함께 처리).")
    fd = lock(project)
    try:
        lines = read_lines(project)
        at = now()
        append_history(lines, history_entry(a.stage, a.event, a.revision, a.note, at))
        write_lines(project, lines)
    finally:
        if fd is not None:
            os.close(fd)
    emit({"ok": True, "recorded": {"at": at, "stage": a.stage, "event": a.event, "revision": a.revision}})


def cmd_approve(a) -> None:
    project = Path(a.project).resolve()
    if a.stage not in ARTIFACTS:
        raise Blocked("invalid_arguments", "approve는 discovery 또는 planning만 합니다.")
    fd = lock(project)
    try:
        lines = read_lines(project)
        s, e = stage_span(lines, a.stage)
        status, rev = get_scalar(lines, s, e, "status"), get_scalar(lines, s, e, "revision")
        if status != "awaiting_approval":
            raise Blocked("not_awaiting_approval", f"{a.stage} 상태가 {status}입니다. 제출(awaiting_approval)된 revision만 승인합니다.")
        if str(a.revision) != rev:
            raise Blocked("revision_mismatch", f"제시된 revision({a.revision})이 현재 {a.stage} revision({rev})과 다릅니다. 현재 revision을 다시 제시하세요.")
        files = ARTIFACTS[a.stage]
        missing = [f for f in files if not (project / f).is_file()]
        if missing:
            raise Blocked("artifact_missing", "승인할 산출물이 없습니다.", files=missing)
        fm_bad = [f for f in files if frontmatter_revision(project / f) != rev]
        if fm_bad:
            raise Blocked("frontmatter_mismatch", f"front matter revision이 {rev}가 아닌 파일이 있습니다(수동 편집 의심).", files=fm_bad)
        if a.stage == "planning":
            ds, de = stage_span(lines, "discovery")
            d_status = get_scalar(lines, ds, de, "status")
            d_appr = next((get_scalar(lines, i + 1, i + 2, "revision", 6) for i in range(ds, de) if lines[i].strip() == "approved:"), None)
            based = get_scalar(lines, s, e, "based_on_discovery_revision")
            if d_status != "approved" or based != d_appr:
                raise Blocked("discovery_not_basis", f"planning이 승인된 discovery revision을 기준으로 하지 않습니다(discovery {d_status}, 승인 r{d_appr}, 기준 r{based}).")
        hashes = {f: sha256(project / f) for f in files}
        at = now()
        k = next((i for i in range(s, e) if re.match(r"^    approved:[ \t]*(#.*)?$", lines[i])), None)
        if k is None:
            raise Blocked("state_format", f"stages.{a.stage}.approved를 찾지 못했습니다.")
        end = k + 1
        while end < e and lines[end].startswith("      "):  # approved 아래(6칸 이상 들여쓰기) 줄만 교체
            end += 1
        block = ["    approved:", f"      revision: {rev}", f"      at: \"{at}\"", "      hashes:"] + [f"        {f}: {h}" for f, h in hashes.items()]
        lines[k:end] = block
        s, e = stage_span(lines, a.stage)
        set_scalar(lines, s, e, "status", "approved")
        unlocked = None
        if a.stage == "discovery":
            ps, pe = stage_span(lines, "planning")
            if get_scalar(lines, ps, pe, "status") == "locked":
                set_scalar(lines, ps, pe, "status", "not_started")
                unlocked = "planning"
        else:
            gs, ge = stage_span(lines, "design")
            if get_scalar(lines, gs, ge, "status") == "locked":
                set_scalar(lines, gs, ge, "status", "not_started")
                unlocked = "design"
            ci = next((i for i, l in enumerate(lines) if re.match(r"^current_stage:", l)), None)
            if ci is not None:
                set_scalar(lines, ci, ci + 1, "current_stage", "design", indent=0)
        append_history(lines, history_entry(a.stage, "approved", int(rev), a.note or "explicit approval", at))
        write_lines(project, lines)
    finally:
        if fd is not None:
            os.close(fd)
    emit({"ok": True, "stage": a.stage, "approved": {"revision": int(rev), "at": at, "hashes": hashes}, "unlocked": unlocked,
          "note": "시각과 해시는 스크립트가 실제 시스템 시각·파일 내용으로 기록했습니다."})


HASH_RE = re.compile(r"[0-9a-f]{64}")


def approved_block(lines: list[str], s: int, e: int) -> tuple[int, int]:
    """stages.<stage>.approved 블록의 [시작, 끝) 줄 범위(approved 아래 6칸 이상 들여쓴 줄까지)."""
    k = next((i for i in range(s, e) if re.match(r"^    approved:[ \t]*(#.*)?$", lines[i])), None)
    if k is None:
        raise Blocked("state_format", "stages.planning.approved를 찾지 못했습니다.")
    end = k + 1
    while end < e and lines[end].startswith("      "):
        end += 1
    return k, end


def approved_record(lines: list[str], k: int, end: int) -> dict:
    rev = get_scalar(lines, k + 1, end, "revision", 6)
    at = get_scalar(lines, k + 1, end, "at", 6)
    hashes = {}
    for l in lines[k + 1:end]:
        m = re.match(r"^ {8}\"?(docs/planning/[\w./-]+?)\"?[ \t]*:[ \t]*\"?([0-9a-fA-F]*)\"?[ \t]*(#.*)?$", l)
        if m:
            hashes[m.group(1)] = m.group(2)
    return {"revision": rev, "at": at, "hashes": hashes}


def design_json_info(project: Path) -> dict | None:
    """/product-design 상태(.ai-workflow/design.json)는 읽기만 합니다(이 스크립트는 쓰지 않음)."""
    p = project / ".ai-workflow/design.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        based = d.get("based_on") or {}
        approved = [k for k, v in (d.get("stages") or {}).items() if isinstance(v, dict) and v.get("status") == "approved"]
        return {"based_on_planning_revision": based.get("planning_revision"), "approved_stages": approved}
    except (ValueError, AttributeError):
        return {"unreadable": True}


def cmd_reopen(a) -> None:
    """T9: 승인된 planning을 다시 엽니다. 모든 검증과 변경을 메모리에서 끝낸 뒤 한 번에 원자적으로 씁니다."""
    project = Path(a.project).resolve()
    if a.stage != "planning":
        raise Blocked("unsupported_stage", "reopen은 planning(T9)만 지원합니다. discovery 재개(T7)는 state-machine.md의 기존 절차를 따릅니다.")
    if not a.confirm:
        raise Blocked("confirmation_required", "승인된 planning을 다시 열면 현재 승인과 design 잠금 해제가 무효가 됩니다. "
                      "사용자의 명시적 확인을 받은 뒤 --confirm으로 다시 실행하세요.")
    fd = lock(project)
    try:
        lines = read_lines(project)
        orig = list(lines)
        wf = get_scalar(lines, 0, len(lines), "workflow", 0)
        if wf != "ai-product-workflow":
            raise Blocked("not_workflow_state", f"{STATE_REL}의 workflow 값이 ai-product-workflow가 아닙니다({wf}). 다른 프로젝트의 상태 파일일 수 있어 바꾸지 않습니다.")
        s, e = stage_span(lines, "planning")
        status, rev = get_scalar(lines, s, e, "status"), get_scalar(lines, s, e, "revision")
        if status != "approved":
            raise Blocked("not_approved", f"planning 상태가 {status}입니다. 승인(approved)된 planning만 reopen으로 다시 엽니다.")
        if str(a.revision) != rev:
            raise Blocked("revision_mismatch", f"제시된 revision({a.revision})이 현재 planning revision({rev})과 다릅니다. 현재 승인 revision을 확인하세요.")
        k, end = approved_block(lines, s, e)
        rec = approved_record(lines, k, end)
        files = ARTIFACTS["planning"]
        problems = []
        if rec["revision"] != rev:
            problems.append(f"approved.revision({rec['revision']})이 planning revision({rev})과 다릅니다")
        if parse_ts(rec["at"] or "") is None:
            problems.append(f"approved.at이 UTC 시각 형식이 아닙니다({rec['at']})")
        for f in files:
            if not HASH_RE.fullmatch(rec["hashes"].get(f) or ""):
                problems.append(f"{f}의 승인 해시가 없거나 형식이 다릅니다")
        ds, de = stage_span(lines, "discovery")
        d_status = get_scalar(lines, ds, de, "status")
        d_appr = next((get_scalar(lines, i + 1, i + 2, "revision", 6) for i in range(ds, de) if lines[i].strip() == "approved:"), None)
        based = get_scalar(lines, s, e, "based_on_discovery_revision")
        if d_status != "approved" or based != d_appr:
            problems.append(f"planning이 승인된 discovery를 기준으로 하지 않습니다(discovery {d_status}, 승인 r{d_appr}, 기준 r{based})")
        gs, ge = stage_span(lines, "design")
        g_status = get_scalar(lines, gs, ge, "status")
        if g_status != "not_started":
            problems.append(f"planning 승인 상태인데 design이 {g_status}입니다(not_started여야 함)")
        if get_scalar(lines, s, e, "artifacts_done") != "[]":
            problems.append("approved 상태인데 artifacts_done이 비어 있지 않습니다")
        if problems:
            raise Blocked("approval_record_invalid", "planning 승인 기록이 정상 상태가 아니어서 다시 열지 않습니다. 기록을 고치지 않았습니다.", problems=problems)
        changed = [f for f in files if not (project / f).is_file() or sha256(project / f) != rec["hashes"][f]]

        # ---- 메모리에서 전이 적용(디스크는 아직 그대로)
        at = now()
        lines[k:end] = ["    approved:", "      revision: null", "      at: null", "      hashes: {}"]
        s, e = stage_span(lines, "planning")
        set_scalar(lines, s, e, "status", "in_progress")  # artifacts_done은 위에서 []임을 확인함
        gs, ge = stage_span(lines, "design")
        set_scalar(lines, gs, ge, "status", "locked")
        ci = next((i for i, l in enumerate(lines) if re.match(r"^current_stage:", l)), None)
        if ci is not None:
            set_scalar(lines, ci, ci + 1, "current_stage", "planning", indent=0)
        short = " ".join(f"{Path(f).name.split('-')[0]}={rec['hashes'][f][:8]}…" for f in files)
        note = (f"T9 재개: {a.note or '사용자 확인'}. r{rev} 승인({rec['at']}) 무효화, 이전 승인 해시 {short}. design locked"
                + (f". 승인 후 변경된 파일: {', '.join(Path(f).name for f in changed)}" if changed else ""))
        append_history(lines, history_entry("planning", "reopened", int(rev), note, at))

        # ---- 쓰기 전 사후 조건 확인: 다른 단계·프로젝트 정보는 바뀌지 않았고, 의도한 값만 바뀌었는지
        ns, ne = stage_span(lines, "planning")
        nk, nend = approved_block(lines, ns, ne)
        os_, oe = stage_span(orig, "discovery")
        post = [
            get_scalar(lines, ns, ne, "status") == "in_progress",
            get_scalar(lines, ns, ne, "revision") == rev,
            approved_record(lines, nk, nend) == {"revision": "null", "at": "null", "hashes": {}},
            get_scalar(lines, *stage_span(lines, "design"), "status") == "locked",
            lines[slice(*stage_span(lines, "discovery"))] == orig[os_:oe],
            [l for l in lines[:os_] if not l.startswith("current_stage:")] == [l for l in orig[:os_] if not l.startswith("current_stage:")],
            len(history_items(lines)) == len(history_items(orig)) + 1,
        ]
        if not all(post):
            raise Blocked("postcondition_failed", "전이 결과가 예상과 달라 쓰지 않았습니다(state.yaml 그대로). 상태 파일 형식을 확인하세요.", checks=post)
        write_lines(project, lines)
    finally:
        if fd is not None:
            os.close(fd)
    emit({"ok": True, "stage": "planning", "status": "in_progress", "revision": int(rev), "preparing_revision": int(rev) + 1,
          "invalidated": {"planning_approved": {"revision": int(rev), "at": rec["at"], "hashes": rec["hashes"]}, "design": "not_started → locked"},
          "changed_since_approval": changed, "design_json": design_json_info(project), "reopened_at": at,
          "note": "이전 승인 기록은 history의 approved·reopened 항목(해시 앞 8자)과 Git 이력에 남습니다. 해시를 다시 계산해 기록하지 않았습니다. "
                  "수정 후 T6(revision+1 제출)·T8(approve)로 다시 승인받아야 합니다. design.json은 이 스크립트가 바꾸지 않으며, "
                  "재승인 후 내용이 바뀌었으면 /product-design check가 outdated를 감지합니다(impact → rebase)."})


def cmd_check(a) -> None:
    project = Path(a.project).resolve()
    lines = read_lines(project)
    limit = datetime.now(timezone.utc) + FUTURE_TOLERANCE
    problems, items = [], history_items(lines)
    prev = None
    for it in items:
        t = parse_ts(it["at"] or "")
        if t is None:
            problems.append(f"history {it['line']}행: 시각 형식이 UTC ISO 8601(YYYY-MM-DDTHH:MM:SSZ)이 아닙니다: {it['at']!r}")
            continue
        if t > limit:
            problems.append(f"history {it['line']}행: 미래 시각입니다({it['at']})")
        if prev and t < prev:
            problems.append(f"history {it['line']}행: 앞 항목보다 이른 시각입니다({it['at']})")
        prev = t
    for st in ARTIFACTS:
        try:
            s, e = stage_span(lines, st)
        except Blocked:
            continue
        k = next((i for i in range(s, e) if lines[i].strip() == "approved:"), None)
        at = get_scalar(lines, k + 1, min(k + 4, e), "at", 6) if k is not None else None
        if at and at != "null":
            t = parse_ts(at)
            if t is None or t > limit:
                problems.append(f"stages.{st}.approved.at이 형식에 맞지 않거나 미래 시각입니다: {at}")
    legacy = sum(1 for it in items if not it["engine"])
    emit({"ok": not problems, "problems": problems, "history": len(items), "engine_recorded": len(items) - legacy, "legacy": legacy,
          "note": "읽기 전용 검사입니다. 기존 기록은 고치지 않습니다(legacy = 이 스크립트 이전 또는 직접 쓴 항목)."}, 0 if not problems else 2)


def main() -> None:
    ap = argparse.ArgumentParser(description="/product-start state helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("now"); s.set_defaults(fn=cmd_now)
    for name, fn in (("event", cmd_event), ("approve", cmd_approve), ("reopen", cmd_reopen), ("check", cmd_check)):
        s = sub.add_parser(name)
        s.add_argument("--project", required=True)
        s.set_defaults(fn=fn)
        if name in ("event", "approve", "reopen"):
            s.add_argument("--stage", required=True)
            s.add_argument("--note", default="")
        if name == "event":
            s.add_argument("--event", required=True)
            s.add_argument("--revision", type=int, required=True)
        if name in ("approve", "reopen"):
            s.add_argument("--revision", type=int, required=True)
        if name == "reopen":
            s.add_argument("--confirm", action="store_true", help="사용자가 재개(승인 무효화)를 명시적으로 확인했을 때만")
    a = ap.parse_args()
    try:
        a.fn(a)
    except Blocked as e:
        emit(e.payload, 2)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        emit({"ok": False, "error": "internal_error", "message": f"{type(e).__name__}: {e}"}, 1)


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
