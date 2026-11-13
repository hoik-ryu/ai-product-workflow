#!/usr/bin/env python3
"""/product-start T6(planning 제출) 공식 명령 `ps_state.py submit` 테스트.

템플릿 state.yaml로 임시 프로젝트를 만들어 discovery를 스크립트로 승인하고 planning 문서 4개를 쓴 뒤,
- 정상 제출, 승인 후 reopen → 수정 → 재제출, 기존 approve와의 연결
- revision 불일치·건너뛰기, front matter 불일치, discovery 미승인·변경, 문서 누락, 중복 제출, 상태 불일치 거부(파일 무변경)
- 추적성 미해결 항목은 보고만 하고 제출을 막지 않음(id-conventions.md 규칙)
- 쓰기 실패·전이 도중 실패 시 state.yaml이 그대로인지
를 봅니다. 사례 프로젝트와 무관한 가상 픽스처만 씁니다.
실행: python3 tests/product_start_submit_test.py
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
BODY = {
    "02-prd.md": "## 기능 요구사항\n\n| ID | 내용 | 우선순위 | 추적 |\n|---|---|---|---|\n| FR-001 | 기능 A | Must | GOAL-001 |\n"
                 "| FR-002 | 기능 B | Should | PRB-001 |\n| ~~FR-003~~ | (r1에서 폐기: 범위 제외) | - | - |\n\n| NFR-001 | 응답 시간 | Must | GOAL-001 |\n",
    "03-user-stories.md": "### US-001: 스토리 A\n\n- **우선순위**: Must\n- **추적 대상**: FR-001, PER-001\n\n"
                          "### US-002: 스토리 B\n\n- **우선순위**: Could\n- **추적 대상**: FR-002, PER-001\n",
    "04-user-flows.md": "## FLOW-001: 흐름 A\n\n| 단계 | 내용 |\n|---|---|\n| FLOW-001-S1 | US-001, US-002 |\n",
    "05-acceptance-criteria.md": "## US-001: 스토리 A\n\n### AC-001: 조건 A\n\n- 추적: US-001, FR-001\n",
}
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


def doc(d: Path, rel: str, rev: int, body: str | None = None, based: int = 1) -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = BODY.get(p.name, "본문") if body is None else body
    p.write_text(f"---\ndoc: x\nrevision: {rev}\nlanguage: ko\nbased_on:\n  discovery_revision: {based}\n---\n# 문서\n\n{body}", encoding="utf-8")


def status(text: str, stage: str) -> str | None:
    return pd_core._field(pd_core._stage_block(text, stage), "status")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def generating_project(root: Path, name: str, rev: int = 1) -> Path:
    """discovery r1 승인, planning T5(in_progress, 기준 discovery r1)에서 문서 4개를 rev로 다 쓴 상태."""
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
    ps(d, "event", "--stage", "planning", "--event", "generated", "--revision", "0")
    for f in PLANNING:
        doc(d, f, rev)
    edit(d, r"^    artifacts_done: \[\][^\n]*$", "    artifacts_done:   # 현재 revision 사이클에서 작성을 마친 파일\n"
         + "\n".join(f"      - {f}" for f in PLANNING))
    return d


def unchanged_after(d: Path, *args) -> tuple[int, dict, bool]:
    raw = sp(d).read_bytes()
    code, out = ps(d, *args)
    return code, out, sp(d).read_bytes() == raw


def load_module():
    spec = importlib.util.spec_from_file_location("ps_state_under_test", PS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SUBMIT1 = ("submit", "--stage", "planning", "--revision", "1", "--confirm")


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-start-submit-test-"))
    try:
        d = generating_project(root, "p")
        before = state(d)

        # ---- 거부(파일 무변경)
        code, out, same = unchanged_after(d, "submit", "--stage", "planning", "--revision", "1")
        check("U1 --confirm 없으면 거부, 무변경", code == 2 and out["error"] == "confirmation_required" and same, out)
        code, out, same = unchanged_after(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")
        check("U2 revision 건너뛰기(0 → 2) 거부, 무변경", code == 2 and out["error"] == "revision_mismatch" and same, out)
        code, out, same = unchanged_after(d, "submit", "--stage", "planning", "--revision", "0", "--confirm")
        check("U3 현재 revision 그대로(0) 제출 거부, 무변경", code == 2 and out["error"] == "revision_mismatch" and same, out)
        code, out, same = unchanged_after(d, "submit", "--stage", "discovery", "--revision", "2", "--confirm")
        check("U4 discovery 제출(T2)은 submit 대상 아님, 무변경", code == 2 and out["error"] == "unsupported_stage" and same, out)
        code, out, same = unchanged_after(d, "event", "--stage", "planning", "--event", "submitted", "--revision", "1")
        check("U5 event로 planning submitted 기록 거부(우회 경로 차단), 무변경", code == 2 and out["error"] == "use_submit" and same, out)
        doc(d, "docs/planning/04-user-flows.md", 2)
        code, out, same = unchanged_after(d, *SUBMIT1)
        check("U6 문서 front matter revision 불일치 거부(파일·값 표시), 무변경",
              code == 2 and out["error"] == "frontmatter_mismatch" and out["files"] == {"docs/planning/04-user-flows.md": "2"} and same, out)
        doc(d, "docs/planning/04-user-flows.md", 1)
        hidden = d / "docs/planning/05-acceptance-criteria.md"
        hidden.rename(hidden.with_suffix(".bak"))
        code, out, same = unchanged_after(d, *SUBMIT1)
        check("U7 필수 문서 누락 거부, 무변경", code == 2 and out["error"] == "artifact_missing"
              and out["files"] == ["docs/planning/05-acceptance-criteria.md"] and same, out)
        hidden.with_suffix(".bak").rename(hidden)
        check("U8 거부 호출들 뒤에도 state.yaml은 처음 그대로", state(d) == before)

        # ---- 정상 제출
        hashes = {f: sha(d / f) for f in PLANNING}
        code, out = ps(d, *SUBMIT1, "--note", "Planning r1 제출")
        text = state(d)
        pl = text.split("  planning:")[1].split("  design:")[0]
        check("U9 정상 제출: awaiting_approval·revision 1·artifacts_done 비움(주석 유지)·design locked 유지",
              code == 0 and status(text, "planning") == "awaiting_approval" and re.search(r"^    revision: 1$", pl, re.M)
              and re.search(r"^    artifacts_done: \[\]     # 현재 revision[^\n]*\n    submitted:", pl, re.M)
              and status(text, "design") == "locked", out)
        snap = pl.split("    submitted:")[1].split("    approved:")[0]
        check("U10 승인 해시를 만들지 않음(planning approved는 비어 있고, 제출 해시 전체는 submitted 스냅샷과 출력에만)",
              re.search(r"^    approved:\n      revision: null\n      at: null\n      hashes: \{\}$", pl, re.M)
              and not re.search(r"[0-9a-f]{64}", pl.split("    approved:")[1]) and out["submitted_hashes"] == hashes
              and all(f"        {f}: {h}" in snap for f, h in hashes.items()) and f'at: "{out["submitted_at"]}"' in snap, pl)
        hist = re.findall(r"^  - \{.*\}$", text, re.M)
        check("U11 history에 submitted 정확히 1건(revision 1, src: engine, 개수·추적성·제출 해시 앞 8자)",
              len(hist) == len(re.findall(r"^  - \{.*\}$", before, re.M)) + 1 and "stage: planning, event: submitted, revision: 1" in hist[-1]
              and "src: engine" in hist[-1] and "FR 2·US 2·FLOW 1·AC 1" in hist[-1] and "누락 없음" in hist[-1]
              and all(f"={hashes[f][:8]}" in hist[-1] for f in PLANNING), hist[-1])
        check("U12 추적성: Could 스토리(US-002)는 AC 없어도 누락 아님, 취소선 폐기 ID·FLOW 단계 ID는 미정의로 보지 않음",
              out["traceability"]["clean"] and out["traceability"]["counts"] == {"FR": 2, "US": 2, "FLOW": 1, "AC": 1}, out["traceability"])
        check("U13 discovery 블록·project 정보는 바이트 단위로 그대로", text.split("  planning:")[0] == before.split("  planning:")[0])
        code, chk = ps(d, "check")
        check("U14 ps_state check 통과", code == 0 and chk["ok"], chk)
        code, out2, same = unchanged_after(d, *SUBMIT1)
        check("U15 중복 제출 거부(이미 awaiting_approval), 무변경", code == 2 and out2["error"] == "not_in_progress" and "중복" in out2["message"] and same, out2)
        code, out2, same = unchanged_after(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")
        check("U16 승인 대기 중 다음 revision으로도 재제출 거부(수정 요청 T3 절차 먼저), 무변경", code == 2 and out2["error"] == "not_in_progress" and same, out2)

        # ---- 기존 approve와 연결
        code, ap = ps(d, "approve", "--stage", "planning", "--revision", "1", "--note", "승인")
        g = pd_core.read_gate(d)
        check("U17 제출 → approve: 승인 해시 = 제출 해시, design 잠금 해제, read_gate 통과",
              code == 0 and ap["approved"]["hashes"] == hashes and g["ok"] and status(state(d), "design") == "not_started", (ap, g))

        # ---- reopen → 수정 → 재제출 → 재승인
        assert ps(d, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "FR-002 변경")[0] == 0
        code, out, same = unchanged_after(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")
        check("U18 reopen 직후 문서를 올리지 않고 제출하면 front matter 불일치로 거부", code == 2 and out["error"] == "frontmatter_mismatch" and same, out)
        for f in PLANNING:
            doc(d, f, 2, BODY[Path(f).name].replace("기능 B", "기능 B(수정)"))
        code, out = ps(d, "submit", "--stage", "planning", "--revision", "2", "--confirm", "--note", "Planning r2 제출")
        code2, ap2 = ps(d, "approve", "--stage", "planning", "--revision", "2", "--note", "r2 승인")
        text = state(d)
        events = re.findall(r"stage: planning, event: (\w+), revision: (\d+)", text)
        check("U19 reopen → 수정 → submit r2 → approve r2, 이력 generated·submitted r1·approved r1·reopened r1·submitted r2·approved r2 보존",
              code == 0 and code2 == 0 and events == [("generated", "0"), ("submitted", "1"), ("approved", "1"), ("reopened", "1"),
                                                      ("submitted", "2"), ("approved", "2")]
              and ap2["approved"]["hashes"] == out["submitted_hashes"], events)

        # ---- discovery 기준 문제
        e = generating_project(root, "disc-open")
        edit(e, r"(  discovery:\n    status:) approved", r"\1 in_progress")
        code, out, same = unchanged_after(e, *SUBMIT1)
        check("U20 discovery 미승인(재검토 중)이면 거부, 무변경", code == 2 and out["error"] == "discovery_not_basis" and same, out)
        e2 = generating_project(root, "disc-modified")
        doc(e2, "docs/planning/01-discovery.md", 1, "승인 뒤 직접 수정")
        code, out, same = unchanged_after(e2, *SUBMIT1)
        check("U21 승인된 discovery 문서가 바뀌었으면 거부(4단계 전제 조건), 무변경", code == 2 and out["error"] == "discovery_modified" and same, out)
        e3 = generating_project(root, "disc-other-basis")
        edit(e3, r"based_on_discovery_revision: 1", "based_on_discovery_revision: 0")
        code, out, same = unchanged_after(e3, *SUBMIT1)
        check("U22 planning 기준이 승인된 discovery revision과 다르면 거부, 무변경", code == 2 and out["error"] == "discovery_not_basis" and same, out)

        # ---- 상태 불일치
        x = generating_project(root, "design-open")
        edit(x, r"(  design:\n    status:) locked", r"\1 not_started")
        code, out, same = unchanged_after(x, *SUBMIT1)
        check("U23 planning 작성 중인데 design 잠금 해제 상태면 거부, 무변경", code == 2 and out["error"] == "state_inconsistent" and same, out)
        x2 = generating_project(root, "approved-left")
        edit(x2, r"(  planning:\n(?:.*\n)*?    approved:\n      revision:) null", r"\1 1")
        code, out, same = unchanged_after(x2, *SUBMIT1)
        check("U24 작성 중인데 승인 기록이 남아 있으면(reopen 없이 상태 변경) 거부, 무변경", code == 2 and out["error"] == "state_inconsistent" and same, out)
        x3 = generating_project(root, "other-workflow")
        edit(x3, r"^workflow: ai-product-workflow", "workflow: something-else")
        code, out, same = unchanged_after(x3, *SUBMIT1)
        check("U25 workflow 값이 다른 상태 파일은 거부, 무변경", code == 2 and out["error"] == "not_workflow_state" and same, out)

        # ---- 추적성 미해결: 보고만, 제출은 허용
        t = generating_project(root, "trace-gaps")
        for f in PLANNING:
            doc(t, f, 1, BODY[Path(f).name] + ("\n| FR-004 | 새 기능 | Must | GOAL-001 |\n" if f.endswith("02-prd.md") else "")
                + ("\n- 참조: AC-009\n" if f.endswith("05-acceptance-criteria.md") else ""))
        doc(t, "docs/planning/03-user-stories.md", 1, BODY["03-user-stories.md"], based=9)
        code, out = ps(t, *SUBMIT1)
        last = re.findall(r"^  - \{.*\}$", state(t), re.M)[-1]
        check("U26 추적성 미해결(FR 미커버·미정의 참조)은 출력·history에 표시하되 제출은 허용(id-conventions 규칙)",
              code == 0 and out["traceability"]["issues"]["fr_without_us"] == ["FR-004"]
              and out["traceability"]["issues"]["undefined_refs"] == ["AC-009"] and "미해결 2건" in last, out.get("traceability"))
        check("U27 front matter based_on.discovery_revision 불일치는 경고(기존 정책에 차단 규칙 없음)",
              any("03-user-stories.md" in w for w in out["warnings"]), out.get("warnings"))

        # ---- 원자적 쓰기 실패 복구
        m = load_module()
        f1 = generating_project(root, "fail")
        raw = sp(f1).read_bytes()
        args = Namespace(project=str(f1), stage="planning", revision=1, confirm=True, note="x")
        orig_replace = m.os.replace

        def boom(*_a, **_k):
            raise OSError("디스크 쓰기 실패(주입)")
        m.os.replace = boom
        try:
            m.cmd_submit(args)
            raised = False
        except OSError:
            raised = True
        finally:
            m.os.replace = orig_replace
        leftovers = [p.name for p in (f1 / ".ai-workflow").iterdir() if p.name.endswith(".tmp")]
        check("U28 쓰기(os.replace) 실패 시 state.yaml 원본 그대로·임시 파일 없음", raised and sp(f1).read_bytes() == raw and not leftovers, leftovers)
        orig_append = m.append_history

        def boom2(*_a, **_k):
            raise RuntimeError("history 추가 중 실패(주입)")
        m.append_history = boom2
        try:
            m.cmd_submit(args)
            raised = False
        except RuntimeError:
            raised = True
        finally:
            m.append_history = orig_append
        check("U29 전이 도중(상태·revision 변경 후 history 단계) 실패해도 state.yaml 그대로", raised and sp(f1).read_bytes() == raw)
        code, out = ps(f1, *SUBMIT1)
        check("U30 실패 뒤 다시 실행하면 정상 제출", code == 0 and status(state(f1), "planning") == "awaiting_approval", out)

        skill = (ENGINE / "skills/product-start/SKILL.md").read_text(encoding="utf-8")
        sm = (ENGINE / "skills/product-start/reference/state-machine.md").read_text(encoding="utf-8")
        check("U31 SKILL·state-machine이 T6를 submit --confirm으로 안내", "submit --project . --stage planning" in skill and "submit --stage planning" in sm)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
