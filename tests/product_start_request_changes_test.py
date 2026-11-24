#!/usr/bin/env python3
"""/product-start 수정 요청(T3) 전용 상태 전이 `ps_state.py request-changes` 테스트(자체 완결형).

state.yaml을 직접 고치지 않고 awaiting_approval → in_progress 전이와 history `changes_requested`(사용자 요청 원문)를
한 번에 원자적으로 기록하는지, 승인 기록·제출 스냅샷·revision을 보존하는지, 잘못된 상태·revision·중복·동시 실행·쓰기 실패에서
상태 파일을 바꾸지 않는지 검사합니다. 테스트 픽스처의 상태 편집은 '이전 단계까지 만들기'(planning 생성 T5)에만 씁니다.

실행: python3 tests/product_start_request_changes_test.py
"""
from __future__ import annotations

import fcntl
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
import product_start_approval_integrity_test as A  # noqa: E402  (픽스처·도우미 재사용)

results: list[tuple[str, bool]] = []
ps, sp, state, doc, sha, edit, unchanged_after, PLANNING = A.ps, A.sp, A.state, A.doc, A.sha, A.edit, A.unchanged_after, A.PLANNING
NOTE = "PRD에 회원 탈퇴 정책을 추가해 주세요(사용자 수정 요청 원문, 테스트 시뮬레이션)"


def check(name: str, ok: bool, detail=None) -> None:
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {str(detail)[:600]}"))


def block(text: str, stage: str) -> str:
    m = re.search(rf"^  {stage}:\n(.*?)(?=^  \w+:|^\S)", text, re.S | re.M)
    return m.group(1) if m else ""


def snap_and_approved(text: str, stage: str) -> tuple[str, str]:
    b = block(text, stage)
    sub = re.search(r"^    submitted:\n(?:^      .*\n)*", b, re.M)
    app = re.search(r"^    approved:\n(?:^      .*\n)*", b, re.M)
    return (sub.group(0) if sub else ""), (app.group(0) if app else "")


def events(text: str, stage: str) -> list[tuple[str, str]]:
    return re.findall(rf"stage: {stage}, event: (\w+), revision: (\d+)", text)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-start-rc-test-"))
    try:
        # ---- R1 정상: planning r1 승인 대기 → 수정 요청
        d = A.submitted_project(root, "normal")
        t0 = state(d)
        sub0, app0 = snap_and_approved(t0, "planning")
        d_block0 = block(t0, "discovery")
        code, out = ps(d, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        t1 = state(d)
        sub1, app1 = snap_and_approved(t1, "planning")
        check("R1 정상 수정 요청: awaiting_approval → in_progress, revision 1 유지(다음 제출 2)", code == 0 and A.status(t1, "planning") == "in_progress"
              and re.search(r"^    revision: 1$", block(t1, "planning"), re.M) and out["preparing_revision"] == 2, out)
        line = next(l for l in t1.splitlines() if "event: changes_requested" in l and not l.lstrip().startswith("#"))
        check("R1b history changes_requested 1줄(사용자 요청 원문·src engine·제출 해시 앞 8자)", events(t1, "planning")[-1] == ("changes_requested", "1")
              and "회원 탈퇴 정책" in line and "src: engine" in line and "02=" in line, line)
        check("R1c 제출 스냅샷·승인 블록·discovery 블록 보존(바뀐 것은 status 1줄 + history 1줄)", sub1 == sub0 and app1 == app0 and block(t1, "discovery") == d_block0
              and len(t1.splitlines()) == len(t0.splitlines()) + 1, (sub0, sub1))
        check("R1d design은 locked 그대로", A.status(t1, "design") == "locked")
        code, chk = ps(d, "check")
        check("R1e check 통과(이전 제출 스냅샷은 승인에 쓰이지 않는다는 경고만)", code == 0 and any("이전 제출 스냅샷(r1)" in w for w in chk["warnings"]), chk)

        # ---- R4 중복 요청
        code, out, same = unchanged_after(d, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        check("R4 같은 revision 중복 요청 → already_requested, 상태 파일 불변", code == 2 and out["error"] == "already_requested" and same, out)

        # ---- R9 다음 revision 정상 제출·승인
        for f in PLANNING:
            doc(d, f, 2, A.BODY[Path(f).name] + "\n## 회원 탈퇴 정책\n- 탈퇴 즉시 개인정보 삭제\n")
        code, sub = ps(d, "submit", "--stage", "planning", "--revision", "2", "--confirm", "--note", "r2 제출")
        check("R9 수정 후 r2 제출: 이전 스냅샷 교체(replaced r1)", code == 0 and sub["replaced_snapshot"]["revision"] == "1", sub)
        code, ap = ps(d, "approve", "--stage", "planning", "--revision", "2", "--note", "r2 승인")
        t9 = state(d)
        check("R9b r2 승인: 승인 해시 = r2 제출 해시, 이력 submitted r1 → changes_requested r1 → submitted r2 → approved r2", code == 0
              and ap["approved"]["hashes"] == {f: sha(d / f) for f in PLANNING}
              and events(t9, "planning") == [("submitted", "1"), ("changes_requested", "1"), ("submitted", "2"), ("approved", "2")], events(t9, "planning"))

        # ---- R2 잘못된 상태
        code, out, same = unchanged_after(d, "request-changes", "--stage", "planning", "--revision", "2", "--note", NOTE)
        check("R2 승인된 planning에 수정 요청 → not_awaiting_approval(재개는 reopen T9 안내), 불변", code == 2 and out["error"] == "not_awaiting_approval"
              and "reopen" in out["message"] and same, out)
        g = A.submitted_project(root, "gen")
        ps(g, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        code, out, same = unchanged_after(g, "request-changes", "--stage", "planning", "--revision", "0", "--note", NOTE)
        check("R2b 작성 중(in_progress)인데 다른 revision으로 요청 → not_awaiting_approval, 불변", code == 2 and out["error"] == "not_awaiting_approval" and same, out)
        code, out, same = unchanged_after(g, "request-changes", "--stage", "design", "--revision", "1", "--note", NOTE)
        check("R2c 지원하지 않는 단계(design) → unsupported_stage", code == 2 and out["error"] == "unsupported_stage" and same, out)

        # ---- R3 revision 불일치·R5 요청 원문 없음
        r = A.submitted_project(root, "rev")
        for bad in ("2", "0"):
            code, out, same = unchanged_after(r, "request-changes", "--stage", "planning", "--revision", bad, "--note", NOTE)
            check(f"R3 revision 불일치(요청 {bad}, 대기 r1) → revision_mismatch, 불변", code == 2 and out["error"] == "revision_mismatch" and same, out)
        code, out, same = unchanged_after(r, "request-changes", "--stage", "planning", "--revision", "1")
        check("R5 사용자 요청 원문 없음 → request_statement_required(사용자가 요청한 경우에만)", code == 2 and out["error"] == "request_statement_required" and same, out)

        # ---- R6 기록 실패 시 불일치 방지
        code, out, same = unchanged_after(r, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE, "--simulate-failure")
        check("R6 전이 준비 후 실패(쓰기 전) → 상태 파일 불변(상태만 바뀌고 이벤트가 빠지는 일 없음)", code == 1 and same, out)
        wf = r / ".ai-workflow"
        os.chmod(wf, 0o555)
        try:
            code, out, same = unchanged_after(r, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        finally:
            os.chmod(wf, 0o755)
        check("R6b 실제 쓰기 실패(폴더 쓰기 불가) → 오류, 상태 파일 불변, 임시 파일 없음", code != 0 and same
              and not any(p.name.endswith(".tmp") for p in wf.iterdir()), out)

        # ---- R7 동시 실행
        fd = os.open(wf, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            code, out, same = unchanged_after(r, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        finally:
            os.close(fd)
        check("R7 다른 명령이 상태 파일을 쓰는 중 → state_busy(기존 잠금 재사용), 불변", code == 2 and out["error"] == "state_busy" and same, out)
        procs = [subprocess.Popen([sys.executable, "-I", str(A.PS), "request-changes", "--project", str(r), "--stage", "planning", "--revision", "1",
                                   "--note", f"{NOTE} #{i}"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        outs = [p.communicate() for p in procs]
        codes = [p.returncode for p in procs]
        tr = state(r)
        check("R7b 동시 요청 4개 → 정확히 1개만 기록(나머지 state_busy·already_requested), changes_requested 1줄", codes.count(0) == 1
              and events(tr, "planning").count(("changes_requested", "1")) == 1 and A.status(tr, "planning") == "in_progress",
              (codes, [o[0][:120] for o in outs]))

        # ---- R8 승인 이력·해시 보존(T9 재개 후 재제출본에 수정 요청)
        h = A.submitted_project(root, "hist")
        assert ps(h, "approve", "--stage", "planning", "--revision", "1", "--note", "r1 승인")[0] == 0
        r1 = {f: sha(h / f) for f in PLANNING}
        assert ps(h, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "변경 원함")[0] == 0
        for f in PLANNING:
            doc(h, f, 2)
        assert ps(h, "submit", "--stage", "planning", "--revision", "2", "--confirm")[0] == 0
        before = state(h)
        code, out = ps(h, "request-changes", "--stage", "planning", "--revision", "2", "--note", NOTE)
        th = state(h)
        check("R8 이전 승인 이력(approved r1·reopened r1의 해시 앞 8자)·discovery 승인 해시 보존", code == 0
              and all(f"={r1[f][:8]}" in th for f in PLANNING) and block(th, "discovery") == block(before, "discovery")
              and events(th, "planning")[:3] == [("submitted", "1"), ("approved", "1"), ("reopened", "1")], events(th, "planning"))

        # ---- R10 discovery T3
        dd = root / "disc"
        (dd / ".ai-workflow").mkdir(parents=True)
        shutil.copy(A.TEMPLATE, sp(dd))
        ps(dd, "event", "--stage", "discovery", "--event", "started", "--revision", "0")
        doc(dd, "docs/planning/01-discovery.md", 1, "디스커버리")
        assert ps(dd, "submit", "--stage", "discovery", "--revision", "1", "--confirm")[0] == 0
        code, out = ps(dd, "request-changes", "--stage", "discovery", "--revision", "1", "--note", "타깃 사용자를 바꿔 주세요(원문)")
        doc(dd, "docs/planning/01-discovery.md", 2, "디스커버리 수정")
        code2, _ = ps(dd, "submit", "--stage", "discovery", "--revision", "2", "--confirm")
        code3, _ = ps(dd, "approve", "--stage", "discovery", "--revision", "2")
        check("R10 discovery 수정 요청(T3) → r2 제출 → 승인", code == 0 and code2 == 0 and code3 == 0
              and events(state(dd), "discovery") == [("started", "0"), ("submitted", "1"), ("changes_requested", "1"), ("submitted", "2"), ("approved", "2")],
              events(state(dd), "discovery"))

        # ---- R11 기존 프로젝트 호환(스냅샷 없는 이전 방식 제출)
        lg = A.legacy_project(root, "legacy")
        code, out = ps(lg, "request-changes", "--stage", "planning", "--revision", "1", "--note", NOTE)
        tl = state(lg)
        check("R11 스냅샷 없는 기존 승인 대기도 수정 요청 가능('스냅샷 없음' 기록, 기존 history 보존)", code == 0 and A.status(tl, "planning") == "in_progress"
              and "스냅샷 없음" in tl and out["preserved"]["submitted_snapshot"] is None, out)

        # ---- R12 이전 방식(event changes_requested) 차단
        p12 = A.submitted_project(root, "old")
        code, out, same = unchanged_after(p12, "event", "--stage", "planning", "--event", "changes_requested", "--revision", "1", "--note", "x")
        check("R12 event --event changes_requested(이전 T3 방식)는 request-changes 안내로 거부, 불변", code == 2 and out["error"] == "use_request_changes" and same, out)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
