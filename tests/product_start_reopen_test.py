#!/usr/bin/env python3
"""/product-start T9(승인된 planning 재개) 공식 명령 `ps_state.py reopen` 테스트.

템플릿 state.yaml로 임시 프로젝트를 만들어 discovery·planning을 스크립트로 승인한 뒤,
- 정상 재개, 승인 후 문서가 바뀐 상태에서의 재개, 승인되지 않은 상태·확인 없음·잘못된 기록의 거부
- 전이 중 오류(쓰기 실패·중간 실패) 시 state.yaml이 그대로인지
- 이전 승인 기록·이벤트 추적 가능성, design 종속 상태(read_gate·outdated 감지) 정합성
을 봅니다. 사례 프로젝트와 무관한 가상 픽스처만 씁니다.
실행: python3 tests/product_start_reopen_test.py
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
ENGINE = Path(__file__).resolve().parent.parent
PS = ENGINE / "skills/product-start/scripts/ps_state.py"
TEMPLATE = ENGINE / "skills/product-start/templates/state.yaml"
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
import pd_core  # noqa: E402  (읽기 전용 판독기)

PLANNING = ["docs/planning/02-prd.md", "docs/planning/03-user-stories.md", "docs/planning/04-user-flows.md",
            "docs/planning/05-acceptance-criteria.md"]
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail=None) -> None:
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {str(detail)[:400]}"))


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


def doc(d: Path, rel: str, rev: int, body: str = "본문") -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ndoc: x\nrevision: {rev}\n---\n# 문서\n{body}\n", encoding="utf-8")


def status(text: str, stage: str) -> str | None:
    return pd_core._field(pd_core._stage_block(text, stage), "status")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def approved_project(root: Path, name: str) -> Path:
    """discovery r1·planning r1이 스크립트로 승인된 프로젝트."""
    d = root / name
    (d / ".ai-workflow").mkdir(parents=True)
    shutil.copy(TEMPLATE, sp(d))
    ps(d, "event", "--stage", "discovery", "--event", "started", "--revision", "0")
    doc(d, "docs/planning/01-discovery.md", 1)
    edit(d, r"(  discovery:\n    status:) in_progress", r"\1 awaiting_approval")
    edit(d, r"(  discovery:\n.*?\n    revision:) 0", r"\1 1")
    assert ps(d, "approve", "--stage", "discovery", "--revision", "1")[0] == 0
    for f in PLANNING:
        doc(d, f, 1)
    edit(d, r"(  planning:\n    status:) not_started", r"\1 in_progress")
    edit(d, r"based_on_discovery_revision: null", "based_on_discovery_revision: 1")
    assert ps(d, "submit", "--stage", "planning", "--revision", "1", "--confirm")[0] == 0  # 제출 스냅샷이 있어야 approve 가능
    code, out = ps(d, "approve", "--stage", "planning", "--revision", "1", "--note", "planning 승인")
    assert code == 0, out
    return d


def load_module():
    spec = importlib.util.spec_from_file_location("ps_state_under_test", PS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def unchanged_after(d: Path, *args) -> tuple[int, dict, bool]:
    raw = sp(d).read_bytes()
    code, out = ps(d, *args)
    return code, out, sp(d).read_bytes() == raw


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-start-reopen-test-"))
    try:
        d = approved_project(root, "p")
        rec_hashes = {f: sha(d / f) for f in PLANNING}
        before_text = state(d)
        g0 = pd_core.read_gate(d)

        # ---- 거부(파일 무변경)
        code, out, same = unchanged_after(d, "reopen", "--stage", "planning", "--revision", "1")
        check("R1 --confirm 없으면 거부, state.yaml 무변경", code == 2 and out["error"] == "confirmation_required" and same, out)
        code, out, same = unchanged_after(d, "reopen", "--stage", "planning", "--revision", "2", "--confirm")
        check("R2 revision 불일치 거부, 무변경", code == 2 and out["error"] == "revision_mismatch" and same, out)
        code, out, same = unchanged_after(d, "reopen", "--stage", "discovery", "--revision", "1", "--confirm")
        check("R3 discovery(T7)는 reopen 대상 아님(다른 단계 오조작 방지), 무변경", code == 2 and out["error"] == "unsupported_stage" and same, out)
        code, out, same = unchanged_after(d, "event", "--stage", "planning", "--event", "reopened", "--revision", "1")
        check("R4 event로 planning reopened 기록 거부(우회 경로 차단), 무변경", code == 2 and out["error"] == "use_reopen" and same, out)

        # ---- 정상 재개
        code, out = ps(d, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "사용자 확인: FR 변경")
        text = state(d)
        g = pd_core.read_gate(d)
        check("R5 정상 재개: planning in_progress·revision 유지·approved 초기화",
              code == 0 and status(text, "planning") == "in_progress" and re.search(r"^  planning:\n(?:.*\n)*?    revision: 1$", text, re.M)
              and re.search(r"^    approved:\n      revision: null\n      at: null\n      hashes: \{\}$", text.split("  planning:")[1], re.M), out)
        check("R6 design locked·current_stage planning·출력에 무효화된 승인(해시 그대로) 표시",
              status(text, "design") == "locked" and re.search(r"^current_stage: planning", text, re.M)
              and out["invalidated"]["planning_approved"]["hashes"] == rec_hashes and out["preparing_revision"] == 2
              and out["changed_since_approval"] == [], out)
        check("R7 discovery 블록·project 정보는 바이트 단위로 그대로",
              text.split("  planning:")[0].replace("current_stage: planning", "current_stage: design") == before_text.split("  planning:")[0], text[:800])
        hist = re.findall(r"^  - \{.*\}$", text, re.M)
        last = hist[-1]
        check("R8 history: 기존 approved 항목 보존 + reopened 1건 추가(이전 승인 시각·해시 앞 8자, src: engine)",
              len(hist) == len(re.findall(r"^  - \{.*\}$", before_text, re.M)) + 1
              and any("stage: planning, event: approved, revision: 1" in h for h in hist[:-1])
              and "stage: planning, event: reopened, revision: 1" in last and "src: engine" in last
              and g0["planning_approved_revision"] == "1" and out["invalidated"]["planning_approved"]["at"] in last
              and all(f"={rec_hashes[f][:8]}" in last for f in PLANNING), last)
        hm = re.findall(r'(docs/planning/[\w.-]+): "?([0-9a-f]{64})"?', text)
        check("R9 승인 해시를 새로 쓰지 않음(전체 해시 줄은 discovery 1개만 남음)", len(hm) == 1 and hm[0][0].endswith("01-discovery.md"), hm)
        check("R10 /product-design·/product-build 게이트(read_gate)가 승인 무효·design locked로 판단",
              not g["ok"] and "planning 상태가 approved가 아닙니다" in g["message"] and "design 단계가 locked" in g["message"], g)
        code, chk = ps(d, "check")
        check("R11 ps_state check 통과(시각 형식·순서)", code == 0 and chk["ok"], chk)
        code, out2, same = unchanged_after(d, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R12 이미 재개된(in_progress) planning 재개 거부, 무변경", code == 2 and out2["error"] == "not_approved" and same, out2)

        # ---- 수정 → 재제출 → 재승인 → design 종속 정합성
        old_hashes = dict(g0["planning_hashes"])
        for f in PLANNING:
            doc(d, f, 2, "본문 v2" if f.endswith("03-user-stories.md") else "본문")
        # T6 제출은 공식 명령(submit)으로 합니다(event submitted 우회 경로는 planning에서 차단됨).
        assert ps(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")[0] == 0
        code, out = ps(d, "approve", "--stage", "planning", "--revision", "2", "--note", "r2 승인")
        text = state(d)
        g2 = pd_core.read_gate(d)
        events = re.findall(r"stage: planning, event: (\w+), revision: (\d+)", text)
        check("R13 재승인: design not_started·read_gate 통과·history approved r1 → reopened r1 → submitted r2 → approved r2",
              code == 0 and status(text, "design") == "not_started" and g2["ok"] and g2["planning_approved_revision"] == "2"
              and events[-4:] == [("approved", "1"), ("reopened", "1"), ("submitted", "2"), ("approved", "2")], (out, events))
        st_stub = {"based_on": {"planning_hashes": old_hashes}, "validity": {"status": "outdated"}}  # 이미 outdated 표시 → 저장 안 함
        changed = pd_core.detect_outdated(d, st_stub, g2)
        # 4개 파일은 단계 revision을 공유하므로 front matter revision(1→2)만 바뀐 파일도 해시가 달라집니다.
        check("R14 기존 디자인 기준(r1 해시)과 비교하면 /product-design이 재승인된 planning을 outdated로 감지",
              changed == PLANNING, changed)

        # ---- 승인 후 문서가 이미 수정된 상태에서 재개
        e = approved_project(root, "modified")
        rec_e = {f: sha(e / f) for f in PLANNING}
        doc(e, "docs/planning/04-user-flows.md", 1, "승인 뒤 직접 수정")
        mod_bytes = (e / "docs/planning/04-user-flows.md").read_bytes()
        code, out = ps(e, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "해시 불일치 확인 후 재검토")
        text = state(e)
        last = re.findall(r"^  - \{.*\}$", text, re.M)[-1]
        check("R15 승인 후 수정된 문서가 있어도 재개 성공, 변경 파일을 출력·history에 표시",
              code == 0 and out["changed_since_approval"] == ["docs/planning/04-user-flows.md"] and "04-user-flows.md" in last
              and status(text, "planning") == "in_progress", out)
        check("R16 기존 승인 해시를 현재 내용으로 다시 계산·기록하지 않음, 수정된 문서도 그대로",
              out["invalidated"]["planning_approved"]["hashes"] == rec_e and sha(e / "docs/planning/04-user-flows.md") not in text
              and (e / "docs/planning/04-user-flows.md").read_bytes() == mod_bytes, out)

        # ---- 전이 중 오류 시 부분 변경 방지(프로세스 안에서 실패 주입)
        m = load_module()
        f1 = approved_project(root, "fail-write")
        raw = sp(f1).read_bytes()
        orig_replace = m.os.replace

        def boom(*_a, **_k):
            raise OSError("디스크 쓰기 실패(주입)")
        m.os.replace = boom
        try:
            m.cmd_reopen(Namespace(project=str(f1), stage="planning", revision=1, confirm=True, note="x"))
            raised = False
        except OSError:
            raised = True
        finally:
            m.os.replace = orig_replace
        leftovers = [p.name for p in (f1 / ".ai-workflow").iterdir() if p.name.endswith(".tmp")]
        check("R17 쓰기(os.replace) 실패 시 state.yaml 원본 그대로·임시 파일 남지 않음",
              raised and sp(f1).read_bytes() == raw and not leftovers, leftovers)
        orig_append = m.append_history

        def boom2(*_a, **_k):
            raise RuntimeError("history 추가 중 실패(주입)")
        m.append_history = boom2
        try:
            m.cmd_reopen(Namespace(project=str(f1), stage="planning", revision=1, confirm=True, note="x"))
            raised = False
        except RuntimeError:
            raised = True
        finally:
            m.append_history = orig_append
        check("R18 전이 도중(상태·approved 변경 후 history 단계) 실패해도 state.yaml 그대로", raised and sp(f1).read_bytes() == raw)
        code, out = ps(f1, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R19 실패 뒤 다시 실행하면 정상 재개(잠금 해제·상태 일관)", code == 0 and status(state(f1), "planning") == "in_progress", out)

        # ---- 비정상 승인 기록 거부
        b = approved_project(root, "bad-hash")
        edit(b, r"(        docs/planning/03-user-stories\.md: )[0-9a-f]{64}", r"\1deadbeef")
        code, out, same = unchanged_after(b, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R20 승인 해시가 깨진 기록은 재개 거부(approval_record_invalid), 무변경",
              code == 2 and out["error"] == "approval_record_invalid" and same and any("03-user-stories" in p for p in out["problems"]), out)
        b2 = approved_project(root, "design-locked")
        edit(b2, r"(  design:\n    status:) not_started", r"\1 locked")
        code, out, same = unchanged_after(b2, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R21 planning approved인데 design locked(불일치)면 거부, 무변경", code == 2 and out["error"] == "approval_record_invalid" and same, out)
        b3 = approved_project(root, "hand-edited")
        edit(b3, r"(  planning:\n    status:) approved", r"\1 awaiting_approval")
        code, out, same = unchanged_after(b3, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R22 승인 상태가 아니면(awaiting_approval) 거부, 무변경", code == 2 and out["error"] == "not_approved" and same, out)
        b4 = approved_project(root, "other-workflow")
        edit(b4, r"^workflow: ai-product-workflow", "workflow: something-else")
        code, out, same = unchanged_after(b4, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R23 workflow 값이 다른 상태 파일(다른 프로젝트)은 거부, 무변경", code == 2 and out["error"] == "not_workflow_state" and same, out)

        # ---- 실제 적용 형식(따옴표 해시·줄 끝 주석)과 design.json 공존
        r = approved_project(root, "real-format")
        edit(r, r"(        docs/planning/02-prd\.md: )([0-9a-f]{64})", r'\1"\2"           # { 경로: sha256 }')
        (r / ".ai-workflow/design.json").write_text(json.dumps({"based_on": {"planning_revision": "1"},
                                                                 "stages": {"ux_planning": {"status": "approved"}}}), encoding="utf-8")
        dj = (r / ".ai-workflow/design.json").read_bytes()
        code, out = ps(r, "reopen", "--stage", "planning", "--revision", "1", "--confirm")
        check("R24 따옴표·주석이 붙은 해시 줄도 인식해 재개, design.json은 읽기만(무변경)·출력에 디자인 기준 표시",
              code == 0 and out["design_json"] == {"based_on_planning_revision": "1", "approved_stages": ["ux_planning"]}
              and (r / ".ai-workflow/design.json").read_bytes() == dj and "docs/planning/02-prd.md" in out["invalidated"]["planning_approved"]["hashes"], out)
        code, out = ps(r, "event", "--stage", "discovery", "--event", "reopened", "--revision", "1", "--note", "T7")
        check("R25 discovery reopened(T7) 기록은 기존대로 event로 허용", code == 0, out)

        skill = (ENGINE / "skills/product-start/SKILL.md").read_text(encoding="utf-8")
        sm = (ENGINE / "skills/product-start/reference/state-machine.md").read_text(encoding="utf-8")
        check("R26 SKILL·state-machine이 T9를 reopen --confirm으로 안내", "reopen --project . --stage planning" in skill and "reopen" in sm and "--confirm" in sm)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
