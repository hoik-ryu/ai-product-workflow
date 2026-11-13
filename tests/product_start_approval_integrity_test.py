#!/usr/bin/env python3
"""/product-start 승인 무결성: 제출 스냅샷(stages.<stage>.submitted)과 approve·check·migrate-snapshot 회귀 테스트.

임시 디렉터리만 씁니다(검증 대상 실제 프로젝트는 건드리지 않음). 실행: python3 tests/product_start_approval_integrity_test.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parents[1]
PS = ENGINE / "skills/product-start/scripts/ps_state.py"
TEMPLATE = ENGINE / "skills/product-start/templates/state.yaml"
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
import pd_core  # noqa: E402  (읽기 전용 판독기)

PLANNING = ["docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md",
            "docs/planning/05-acceptance-criteria.md"]
BODY = {
    "02-prd.md": "## 기능 요구사항\n\n| ID | 내용 | 우선순위 |\n|---|---|---|\n| FR-001 | 기능 A | Must |\n",
    "03-user-stories.md": "### US-001: 스토리 A\n\n- **우선순위**: Must\n- **추적 대상**: FR-001\n",
    "04-user-flows.md": "## FLOW-001: 흐름 A\n\n| 단계 | 내용 |\n|---|---|\n| FLOW-001-S1 | US-001 |\n",
    "05-acceptance-criteria.md": "## US-001\n\n### AC-001: 조건 A\n\n- 추적: US-001, FR-001\n",
}
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail=None) -> None:
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {str(detail)[:500]}"))


def ps(d: Path, *args) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, "-I", str(PS), *args, "--project", str(d)], capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def sp(d: Path) -> Path:
    return d / ".ai-workflow/state.yaml"


def state(d: Path) -> str:
    return sp(d).read_text(encoding="utf-8")


def edit(d: Path, pattern: str, repl: str) -> None:
    t, n = re.subn(pattern, repl, state(d), count=1, flags=re.M | re.S)
    assert n, pattern
    sp(d).write_text(t, encoding="utf-8")


def doc(d: Path, rel: str, rev: int, body: str | None = None, lang: str = "ko") -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = BODY.get(p.name, "본문") if body is None else body
    p.write_text(f"---\ndoc: x\nrevision: {rev}\nlanguage: {lang}\nbased_on:\n  discovery_revision: 1\n---\n# 문서\n\n{body}", encoding="utf-8")


def status(text: str, stage: str) -> str | None:
    return pd_core._field(pd_core._stage_block(text, stage), "status")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def planning_block(text: str) -> str:
    return text.split("  planning:")[1].split("  design:")[0]


def snapshot_text(text: str) -> str:
    return planning_block(text).split("    submitted:")[1].split("    approved:")[0]


def unchanged_after(d: Path, *args) -> tuple[int, dict, bool]:
    raw = sp(d).read_bytes()
    code, out = ps(d, *args)
    return code, out, sp(d).read_bytes() == raw


def submitted_project(root: Path, name: str) -> Path:
    """discovery r1 승인, planning r1을 submit으로 제출한 상태(awaiting_approval, 제출 스냅샷 있음)."""
    d = root / name
    (d / ".ai-workflow").mkdir(parents=True)
    shutil.copy(TEMPLATE, sp(d))
    ps(d, "event", "--stage", "discovery", "--event", "started", "--revision", "0")
    doc(d, "docs/planning/01-discovery.md", 1, "디스커버리")
    edit(d, r"(  discovery:\n    status:) in_progress", r"\1 awaiting_approval")
    edit(d, r"(  discovery:\n.*?\n    revision:) 0", r"\1 1")
    assert ps(d, "approve", "--stage", "discovery", "--revision", "1")[0] == 0
    edit(d, r"(  planning:\n    status:) not_started", r"\1 in_progress")
    edit(d, r"based_on_discovery_revision: null", "based_on_discovery_revision: 1")
    for f in PLANNING:
        doc(d, f, 1)
    code, out = ps(d, "submit", "--stage", "planning", "--revision", "1", "--confirm", "--note", "r1 제출")
    assert code == 0, out
    return d


def legacy_project(root: Path, name: str, keep_empty_block: bool = False) -> Path:
    """스냅샷 도입 이전 submit으로 제출된 상태 재현: 스냅샷 블록이 없음(또는 비어 있음), history에는 제출 해시 앞 8자."""
    d = submitted_project(root, name)
    repl = "    submitted:\n      revision: null\n      at: null\n      hashes: {}\n" if keep_empty_block else ""
    edit(d, r"^    submitted:[^\n]*\n(?:      [^\n]*\n)*", repl)
    return d


def load_module():
    spec = importlib.util.spec_from_file_location("ps_state_under_test", PS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


APPROVE1 = ("approve", "--stage", "planning", "--revision", "1", "--note", "사용자 승인")
MIGRATE1 = ("migrate-snapshot", "--stage", "planning", "--revision", "1", "--confirm")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-start-integrity-test-"))
    try:
        # ---- 제출 스냅샷 기록
        d = submitted_project(root, "p")
        text = state(d)
        hashes = {f: sha(d / f) for f in PLANNING}
        snap = snapshot_text(text)
        check("V1 submit이 제출 스냅샷(submitted.revision·at·전체 SHA-256 4개)을 approved 블록 앞에 기록",
              re.search(r"^      revision: 1$", snap, re.M) and re.search(r'^      at: "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"$', snap, re.M)
              and all(f"        {f}: {h}" in snap for f, h in hashes.items()), snap)
        g = pd_core.read_gate(d)
        check("V2 승인 대기 중 기존 판독기(read_gate)는 스냅샷을 승인으로 보지 않음", not g["ok"] and "approved가 아닙니다" in g["message"], g)
        code, chk = ps(d, "check")
        check("V3 check: 제출 이후 변경 없음 → 통과(result unchanged)", code == 0 and chk["ok"]
              and chk["submission"]["planning"]["result"] == "unchanged", chk)

        # ---- 제출 후 변경 → 승인 거부
        prd = d / PLANNING[0]
        orig_prd = prd.read_bytes()
        doc(d, PLANNING[0], 1, BODY["02-prd.md"] + "| FR-002 | 몰래 추가 | Must |\n")
        code, out, same = unchanged_after(d, *APPROVE1)
        check("V4 제출 후 본문 변경 → approve 거부(changed_since_submission, 파일·modified 표시), state.yaml 그대로",
              code == 2 and out["error"] == "changed_since_submission" and same
              and [(c["file"], c["change"]) for c in out["files"]] == [(PLANNING[0], "modified")], out)
        code, chk = ps(d, "check")
        check("V5 check도 제출 이후 변경을 감지(종료 2, problems·changed_since_submission)",
              code == 2 and not chk["ok"] and chk["submission"]["planning"]["result"] == "changed_since_submission"
              and any("changed_since_submission" in p for p in chk["problems"]), chk)
        prd.write_bytes(orig_prd)
        doc(d, PLANNING[1], 1, lang="en")
        code, out, same = unchanged_after(d, *APPROVE1)
        check("V6 제출 후 front matter만 변경(language) → 승인 거부", code == 2 and out["error"] == "changed_since_submission" and same, out)
        doc(d, PLANNING[1], 2)
        code, out, same = unchanged_after(d, *APPROVE1)
        check("V7 제출 후 front matter revision 변경 → changed_since_submission으로 거부(front matter 검사보다 먼저)",
              code == 2 and out["error"] == "changed_since_submission" and same, out)
        doc(d, PLANNING[1], 1)
        (d / PLANNING[3]).unlink()
        code, out, same = unchanged_after(d, *APPROVE1)
        check("V8 제출 후 문서 삭제 → 승인 거부(change deleted)", code == 2 and out["error"] == "changed_since_submission" and same
              and {"file": PLANNING[3], "change": "deleted"} in out["files"], out)
        code, chk = ps(d, "check")
        check("V9 check가 삭제도 감지", code == 2 and any(PLANNING[3] + "(deleted)" in p for p in chk["problems"]), chk)
        doc(d, PLANNING[3], 1)
        check("V10 제출 시점 내용으로 복원하면 해시가 다시 일치", all(sha(d / f) == h for f, h in hashes.items()))

        # ---- 변경 없이 승인
        code, ap = ps(d, *APPROVE1)
        text = state(d)
        hist = re.findall(r"^  - \{.*\}$", text, re.M)
        check("V11 제출 후 변경 없으면 승인 성공: approved.hashes = 제출 스냅샷, verified_against_submission 표시",
              code == 0 and ap["approved"]["hashes"] == hashes and ap["verified_against_submission"]["submitted_revision"] == 1, ap)
        check("V12 승인 시 스냅샷은 비움(전체 해시는 approved.hashes에 보존), history approved에 스냅샷 일치 기록",
              re.search(r"^    submitted:[^\n]*\n      revision: null\n      at: null\n      hashes: \{\}$", planning_block(text), re.M)
              and "제출 스냅샷(r1," in hist[-1] and "일치 확인" in hist[-1], planning_block(text))
        g = pd_core.read_gate(d)
        hm = re.findall(r'(docs/planning/[\w.-]+): "?([0-9a-f]{64})"?', text)
        check("V13 승인 후 read_gate 통과·하네스 형식 해시 줄 5개(스냅샷 해시가 중복으로 남지 않음)",
              g["ok"] and all(g["planning_hashes"][f] == h for f, h in hashes.items()) and len(hm) == 5, (g, hm))
        code, chk = ps(d, "check")
        check("V14 승인 후 check 통과", code == 0 and chk["ok"] and not chk["warnings"], chk)

        # ---- reopen → 재제출: 새 스냅샷 사용, 이전 승인 이력 보존
        assert ps(d, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "변경")[0] == 0
        for f in PLANNING:
            doc(d, f, 2, BODY[Path(f).name] + "\n개정\n")
        code, sub2 = ps(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")
        snap2 = snapshot_text(state(d))
        new = {f: sha(d / f) for f in PLANNING}
        check("V15 재제출 시 새 스냅샷(r2·새 해시)만 남고 r1 해시는 스냅샷에 없음",
              code == 0 and re.search(r"^      revision: 2$", snap2, re.M) and all(f"{f}: {h}" in snap2 for f, h in new.items())
              and not any(h in snap2 for h in hashes.values()), snap2)
        code, ap2 = ps(d, "approve", "--stage", "planning", "--revision", "2", "--note", "r2 승인")
        text = state(d)
        events = re.findall(r"stage: planning, event: (\w+), revision: (\d+)", text)
        check("V16 r2 승인 해시 = r2 스냅샷, 승인 이력(r1 submitted·approved·reopened, r2 submitted·approved)과 r1 해시 앞 8자 보존",
              code == 0 and ap2["approved"]["hashes"] == new
              and events == [("submitted", "1"), ("approved", "1"), ("reopened", "1"), ("submitted", "2"), ("approved", "2")]
              and all(f"={hashes[f][:8]}" in text for f in PLANNING), events)
        check("V17 discovery 승인 블록·해시는 그대로", f"docs/planning/01-discovery.md: {sha(d / 'docs/planning/01-discovery.md')}" in text)

        # ---- 수정 요청(T3) 뒤 남은 이전 스냅샷: 재사용 금지·재제출 시 교체
        t3 = submitted_project(root, "t3")
        edit(t3, r"(  planning:\n    status:) awaiting_approval", r"\1 in_progress")
        ps(t3, "event", "--stage", "planning", "--event", "changes_requested", "--revision", "1", "--note", "수정 요청")
        code, chk = ps(t3, "check")
        check("V18 T3 후 남은 이전 스냅샷은 경고(승인에 쓰이지 않음)", code == 0 and any("이전 제출 스냅샷(r1)" in w for w in chk["warnings"]), chk)
        tamper = root / "tamper"
        shutil.copytree(t3, tamper)
        edit(tamper, r"(  planning:\n    status:) in_progress", r"\1 awaiting_approval")
        edit(tamper, r"(  planning:\n.*?\n    revision:) 1", r"\1 2")
        for f in PLANNING:
            doc(tamper, f, 2)
        code, out, same = unchanged_after(tamper, "approve", "--stage", "planning", "--revision", "2")
        check("V19 상태를 직접 바꿔 r2 승인 대기로 만들어도 r1 스냅샷은 재사용하지 않음(submission_snapshot_stale)",
              code == 2 and out["error"] == "submission_snapshot_stale" and same, out)
        for f in PLANNING:
            doc(t3, f, 2, BODY[Path(f).name] + "\n반영\n")
        code, sub = ps(t3, "submit", "--stage", "planning", "--revision", "2", "--confirm")
        check("V20 T3 후 재제출: 이전 스냅샷 교체(replaced_snapshot r1) 후 r2 승인 가능",
              code == 0 and sub["replaced_snapshot"]["revision"] == "1" and ps(t3, "approve", "--stage", "planning", "--revision", "2")[0] == 0, sub)

        # ---- 스냅샷 없는 기존 제출 대기(하위 호환)
        lg = legacy_project(root, "legacy")
        legacy_raw = sp(lg).read_bytes()
        code, out, same = unchanged_after(lg, *APPROVE1)
        check("V21 스냅샷 없는 기존 awaiting_approval → approve 거부(submission_snapshot_missing, 선택지 안내), 무변경",
              code == 2 and out["error"] == "submission_snapshot_missing" and "migrate-snapshot" in out["message"] and same, out)
        code, chk = ps(lg, "check")
        check("V22 check: 스냅샷 없는 기존 제출은 경고만(상태 파일을 깨뜨리지 않음, 종료 0)",
              code == 0 and chk["ok"] and chk["submission"]["planning"]["result"] == "no_snapshot" and chk["warnings"], chk)
        lg0 = legacy_project(root, "legacy-null", keep_empty_block=True)
        code, out, same = unchanged_after(lg0, *APPROVE1)
        check("V23 비어 있는 스냅샷 블록(null)도 '없음'으로 취급해 거부", code == 2 and out["error"] == "submission_snapshot_missing" and same, out)
        code, out, same = unchanged_after(lg, "migrate-snapshot", "--stage", "planning", "--revision", "1")
        check("V24 migrate-snapshot은 --confirm 없이는 실행 안 함, 무변경", code == 2 and out["error"] == "confirmation_required" and same, out)
        code, out, same = unchanged_after(lg, "migrate-snapshot", "--stage", "planning", "--revision", "2", "--confirm")
        check("V25 migrate-snapshot revision 불일치 거부", code == 2 and out["error"] == "revision_mismatch" and same, out)
        before_hist = re.findall(r"^  - \{.*\}$", state(lg), re.M)
        sub_at = re.findall(r'^  - \{ at: "([^"]+)", stage: planning, event: submitted', state(lg), re.M)[-1]
        code, mg = ps(lg, *MIGRATE1)
        text = state(lg)
        snap = snapshot_text(text)
        check("V26 migrate-snapshot: history 제출 해시와 일치 → 전체 해시 스냅샷 기록(at = 원래 제출 시각, source migrated)",
              code == 0 and mg["snapshot"]["at"] == sub_at and "      source: migrated" in snap
              and all(f"        {f}: {sha(lg / f)}" in snap for f in PLANNING), (mg, snap))
        check("V27 migrate-snapshot은 상태·revision·history를 바꾸지 않음(스냅샷 블록만 추가)",
              status(text, "planning") == "awaiting_approval" and re.findall(r"^  - \{.*\}$", text, re.M) == before_hist
              and re.sub(r"^    submitted:[^\n]*\n(?:      [^\n]*\n)*", "", text, flags=re.M) == legacy_raw.decode("utf-8"), text[-600:])
        code, out, same = unchanged_after(lg, *MIGRATE1)
        check("V28 이미 스냅샷이 있으면 다시 마이그레이션 안 함", code == 2 and out["error"] == "snapshot_exists" and same, out)
        code, ap = ps(lg, *APPROVE1)
        check("V29 마이그레이션 후 승인 성공, history에 마이그레이션 스냅샷 확인 표시",
              code == 0 and ap["verified_against_submission"]["source"] == "migrated"
              and "마이그레이션" in re.findall(r"^  - \{.*\}$", state(lg), re.M)[-1], ap)

        lc = legacy_project(root, "legacy-changed")
        doc(lc, PLANNING[2], 1, BODY["04-user-flows.md"] + "\n제출 뒤 수정\n")
        code, out, same = unchanged_after(lc, *MIGRATE1)
        check("V30 기존 제출 후 문서가 바뀌었으면 마이그레이션 거부(changed_since_submission), 무변경",
              code == 2 and out["error"] == "changed_since_submission" and out["files"][0]["file"] == PLANNING[2] and same, out)
        lm = legacy_project(root, "legacy-manual")
        edit(lm, r'(event: submitted, revision: 1, note: ")[^"]*(", src: engine \})', r"\1r1 제출\2")
        code, out, same = unchanged_after(lm, *MIGRATE1)
        check("V31 제출 해시가 기록되지 않은 기존 제출(수동 등)은 확인 불가로 거부(snapshot_unverifiable), 무변경",
              code == 2 and out["error"] == "snapshot_unverifiable" and same, out)
        ln = legacy_project(root, "legacy-legacy-line")
        edit(ln, r"(event: submitted, revision: 1, note: \"[^\"]*\"), src: engine \}", r"\1 }")
        code, out, same = unchanged_after(ln, *MIGRATE1)
        check("V32 스크립트가 남기지 않은 submitted 기록(src 표지 없음)은 근거로 쓰지 않음", code == 2 and out["error"] == "snapshot_unverifiable" and same, out)

        # ---- 이상 상태
        ab = submitted_project(root, "approved-with-snapshot")
        assert ps(ab, *APPROVE1)[0] == 0
        raw = state(ab)
        h = sha(ab / PLANNING[0])
        edit(ab, r"^(    submitted:[^\n]*\n)      revision: null\n      at: null\n      hashes: \{\}",
             r'\1      revision: 1\n      at: "2026-01-01T00:00:00Z"\n      hashes:\n        ' + PLANNING[0] + ": " + h)
        code, chk = ps(ab, "check")
        check("V33 approved 상태에 스냅샷이 남아 있으면 check 문제로 보고", code == 2 and any("스냅샷이 비어 있지 않습니다" in p for p in chk["problems"]), chk)
        code, out, same = unchanged_after(ab, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("V34 그 상태에서 reopen도 거부(approval_record_invalid), 무변경", code == 2 and out["error"] == "approval_record_invalid" and same, out)
        sp(ab).write_text(raw, encoding="utf-8")

        bad = submitted_project(root, "snapshot-incomplete")
        edit(bad, r"^        docs/planning/05-acceptance-criteria\.md: [0-9a-f]{64}\n", "")
        code, out, same = unchanged_after(bad, *APPROVE1)
        check("V35 스냅샷 파일 목록이 승인 대상과 다르면 거부(submission_snapshot_invalid)", code == 2 and out["error"] == "submission_snapshot_invalid" and same, out)

        # ---- discovery: 공통 불변식(스냅샷이 있으면 비교), 스냅샷 없으면 기존 경로 유지
        dv = root / "disc"
        (dv / ".ai-workflow").mkdir(parents=True)
        shutil.copy(TEMPLATE, sp(dv))
        doc(dv, "docs/planning/01-discovery.md", 1, "디스커버리")
        edit(dv, r"(  discovery:\n    status:) in_progress", r"\1 awaiting_approval")
        edit(dv, r"(  discovery:\n.*?\n    revision:) 0", r"\1 1")
        dh = sha(dv / "docs/planning/01-discovery.md")
        edit(dv, r"(  discovery:\n(?:[^\n]*\n)*?)(    approved:)",
             r'\1    submitted:\n      revision: 1\n      at: "2026-01-01T00:00:00Z"\n      hashes:\n        docs/planning/01-discovery.md: ' + dh + r"\n\2")
        doc(dv, "docs/planning/01-discovery.md", 1, "디스커버리(제출 후 수정)")
        code, out, same = unchanged_after(dv, "approve", "--stage", "discovery", "--revision", "1")
        check("V36 discovery도 스냅샷이 있으면 같은 규칙(제출 후 변경 시 거부)", code == 2 and out["error"] == "changed_since_submission" and same, out)
        doc(dv, "docs/planning/01-discovery.md", 1, "디스커버리")
        code, out = ps(dv, "approve", "--stage", "discovery", "--revision", "1")
        check("V37 discovery 스냅샷 일치 시 승인·스냅샷 비움", code == 0 and re.search(
            r"^    submitted:\n      revision: null\n      at: null\n      hashes: \{\}$", state(dv), re.M), out)

        # ---- 원자적 쓰기 실패
        m = load_module()
        f1 = submitted_project(root, "fail")
        raw = sp(f1).read_bytes()
        orig_replace = m.os.replace

        def boom(*_a, **_k):
            raise OSError("디스크 쓰기 실패(주입)")
        outcomes = []
        for fn, args in ((m.cmd_approve, Namespace(project=str(f1), stage="planning", revision=1, note="x")),):
            m.os.replace = boom
            try:
                fn(args)
                outcomes.append(False)
            except OSError:
                outcomes.append(True)
            finally:
                m.os.replace = orig_replace
        leftovers = [p.name for p in (f1 / ".ai-workflow").iterdir() if p.name.endswith(".tmp")]
        check("V38 approve 쓰기 실패 시 state.yaml 원본 그대로(스냅샷 유지)·임시 파일 없음", all(outcomes) and sp(f1).read_bytes() == raw and not leftovers)
        f2 = legacy_project(root, "fail-migrate")
        raw2 = sp(f2).read_bytes()
        m.os.replace = boom
        try:
            m.cmd_migrate_snapshot(Namespace(project=str(f2), stage="planning", revision=1, confirm=True, note=""))
            raised = False
        except OSError:
            raised = True
        finally:
            m.os.replace = orig_replace
        check("V39 migrate-snapshot 쓰기 실패 시 원본 그대로", raised and sp(f2).read_bytes() == raw2)
        check("V40 실패 뒤 다시 승인하면 정상", ps(f1, *APPROVE1)[0] == 0)

        skill = (ENGINE / "skills/product-start/SKILL.md").read_text(encoding="utf-8")
        sm = (ENGINE / "skills/product-start/reference/state-machine.md").read_text(encoding="utf-8")
        check("V41 SKILL·state-machine이 제출 스냅샷·changed_since_submission·migrate-snapshot을 안내",
              all(k in skill for k in ("changed_since_submission", "migrate-snapshot"))
              and all(k in sm for k in ("submitted", "changed_since_submission", "migrate-snapshot")))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad_results = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad_results)}/{len(results)} passed")
    return 1 if bad_results else 0


if __name__ == "__main__":
    sys.exit(main())
