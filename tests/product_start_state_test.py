#!/usr/bin/env python3
"""/product-start 상태 도우미(ps_state.py) 회귀 테스트 — D-001(이력 시각을 LLM이 임의 생성) 수정 확인.

템플릿 state.yaml로 임시 프로젝트를 만들고 Discovery·Planning 승인 전이를 스크립트로 기록한 뒤,
- 시각이 실제 시스템 UTC 시각(실행 전후 사이)인지
- 기존 판독기(/product-design read_gate, /product-start 하네스 check.py의 정규식)와 호환되는지
- 미래·역순·형식 오류 시각을 check가 찾는지, 기존(legacy) 항목은 고치지 않는지
- 조건이 맞지 않는 승인(상태·revision·front matter·discovery 기준)을 거부하는지
를 봅니다. 사례 프로젝트와 무관한 가상 픽스처만 씁니다.
실행: python3 tests/product_start_state_test.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent.parent
PS = ENGINE / "skills/product-start/scripts/ps_state.py"
TEMPLATE = ENGINE / "skills/product-start/templates/state.yaml"
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
import pd_core  # noqa: E402  (읽기 전용 판독기 호환 확인)

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail=None) -> None:
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {str(detail)[:300]}"))


def ps(d: Path, *args) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, "-I", str(PS), *args, *(["--project", str(d)] if args[0] != "now" else [])],
                       capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except json.JSONDecodeError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def state(d: Path) -> str:
    return (d / ".ai-workflow/state.yaml").read_text(encoding="utf-8")


def edit(d: Path, pattern: str, repl: str, count: int = 1) -> None:
    """LLM이 하는 상태 편집(상태·revision 등 시각 없는 값)을 흉내 냅니다."""
    p = d / ".ai-workflow/state.yaml"
    t, n = re.subn(pattern, repl, p.read_text(encoding="utf-8"), count=count, flags=re.M | re.S)
    assert n, pattern
    p.write_text(t, encoding="utf-8")


def doc(d: Path, rel: str, rev: int, body: str = "본문") -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ndoc: x\nrevision: {rev}\n---\n# 문서\n{body}\n", encoding="utf-8")


def stage_status(text: str, stage: str) -> str | None:
    return pd_core._field(pd_core._stage_block(text, stage), "status")


def utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-start-state-test-"))
    try:
        d = root / "p"
        (d / ".ai-workflow").mkdir(parents=True)
        shutil.copy(TEMPLATE, d / ".ai-workflow/state.yaml")
        t0 = datetime.now(timezone.utc).replace(microsecond=0)

        code, out = ps(d, "now")
        check("S1 now: 시스템 UTC 시각(형식·실행 시점)", code == 0 and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", out["now"])
              and abs((utc(out["now"]) - t0).total_seconds()) < 60, out)
        code, out = ps(d, "event", "--stage", "discovery", "--event", "started", "--revision", "0", "--note", "idea \"received\"")
        text = state(d)
        check("S2 event: history: [] → 항목 추가, 시각은 스크립트가 기록, src: engine 표지·따옴표 이스케이프",
              code == 0 and "history: []" not in text and re.search(r'^  - \{ at: "' + re.escape(out["recorded"]["at"]) +
                                                                    r'", stage: discovery, event: started, revision: 0, note: "idea \\"received\\"", src: engine \}$', text, re.M), text[-400:])
        code, out = ps(d, "event", "--stage", "discovery", "--event", "approved", "--revision", "1")
        check("S3 event로 approved 기록 거부(승인은 approve로만)", code == 2 and out["error"] == "use_approve", out)
        code, out = ps(d, "approve", "--stage", "discovery", "--revision", "1")
        check("S4 제출 전(in_progress) 승인 거부", code == 2 and out["error"] == "not_awaiting_approval", out)

        # LLM이 초안을 쓰고 제출 상태로 바꾼 상황
        doc(d, "docs/planning/01-discovery.md", 1)
        edit(d, r"(  discovery:\n    status:) in_progress", r"\1 awaiting_approval")
        edit(d, r"(  discovery:\n.*?\n    revision:) 0", r"\1 1")
        ps(d, "event", "--stage", "discovery", "--event", "submitted", "--revision", "1", "--note", "r1 제출")
        code, out = ps(d, "approve", "--stage", "discovery", "--revision", "2")
        check("S5 제시한 revision과 다르면 승인 거부", code == 2 and out["error"] == "revision_mismatch", out)
        doc(d, "docs/planning/01-discovery.md", 2)
        code, out = ps(d, "approve", "--stage", "discovery", "--revision", "1")
        check("S6 front matter revision이 다르면 승인 거부(수동 편집 의심)", code == 2 and out["error"] == "frontmatter_mismatch", out)
        doc(d, "docs/planning/01-discovery.md", 1)
        before = datetime.now(timezone.utc).replace(microsecond=0)
        code, out = ps(d, "approve", "--stage", "discovery", "--revision", "1", "--note", "사용자 명시적 승인")
        after = datetime.now(timezone.utc)
        text = state(d)
        h01 = hashlib.sha256((d / "docs/planning/01-discovery.md").read_bytes()).hexdigest()
        check("S7 discovery 승인: approved.{revision,at,hashes}·상태·planning 잠금 해제·history approved",
              code == 0 and stage_status(text, "discovery") == "approved" and stage_status(text, "planning") == "not_started"
              and out["approved"]["hashes"]["docs/planning/01-discovery.md"] == h01
              and re.search(r'event: approved, revision: 1, note: "사용자 명시적 승인", src: engine', text), out)
        check("S8 승인 시각은 실제 시스템 시각(실행 전후 사이)", before <= utc(out["approved"]["at"]) <= after, (before, out["approved"]["at"], after))
        check("S9 주석이 붙은 status 줄도 값만 바꾸고 주석 유지",
              re.search(r"^    status: approved   # in_progress \| awaiting_approval \| approved$", text, re.M), text[:900])

        # Planning
        for f, _ in zip(["02-prd", "03-user-stories", "04-user-flows", "05-acceptance-criteria"], range(4)):
            doc(d, f"docs/planning/{f}.md", 1)
        edit(d, r"(  planning:\n    status:) not_started", r"\1 awaiting_approval")
        edit(d, r"(  planning:\n.*?\n    revision:) 0", r"\1 1")
        edit(d, r"based_on_discovery_revision: null", "based_on_discovery_revision: 9")
        code, out = ps(d, "approve", "--stage", "planning", "--revision", "1")
        check("S10 승인된 discovery revision을 기준으로 하지 않은 planning 승인 거부", code == 2 and out["error"] == "discovery_not_basis", out)
        edit(d, r"based_on_discovery_revision: 9", "based_on_discovery_revision: 1")
        code, out = ps(d, "approve", "--stage", "planning", "--revision", "1", "--note", "planning 승인")
        text = state(d)
        g = pd_core.read_gate(d)
        check("S11 planning 승인: design 잠금 해제·current_stage design·해시 4개", code == 0 and stage_status(text, "design") == "not_started"
              and re.search(r"^current_stage: design", text, re.M) and len(out["approved"]["hashes"]) == 4, out)
        check("S12 /product-design read_gate(기존 정규식 판독기)가 승인·해시를 그대로 인식", g["ok"] and g["discovery_approved_revision"] == "1"
              and g["planning_approved_revision"] == "1", g)
        hm = re.findall(r'(docs/planning/[\w.-]+): "?([0-9a-f]{64})"?', text)
        check("S13 /product-start 하네스 check.py 형식의 해시 줄 5개 일치", len(hm) == 5 and all(
            hashlib.sha256((d / p).read_bytes()).hexdigest() == h for p, h in hm), hm)
        code, out = ps(d, "check")
        check("S14 check: 스크립트가 쓴 기록은 모두 문제 없음", code == 0 and out["ok"] and out["legacy"] == 0 and out["engine_recorded"] == 4, out)  # started·submitted·approved×2(거부된 호출은 기록 없음)

        # 기존(legacy) 기록과 잘못된 시각
        e = root / "legacy"
        (e / ".ai-workflow").mkdir(parents=True)
        legacy = TEMPLATE.read_text(encoding="utf-8").replace(
            "history: []", 'history:\n  - { at: "2026-01-01T00:00:00Z", stage: discovery, event: started, revision: 0, note: "old" }')
        (e / ".ai-workflow/state.yaml").write_text(legacy, encoding="utf-8")
        raw = (e / ".ai-workflow/state.yaml").read_bytes()
        code, out = ps(e, "check")
        check("S15 기존 항목(src 없음)은 legacy로 세고 문제 아님, 파일은 바뀌지 않음", code == 0 and out["legacy"] == 1
              and (e / ".ai-workflow/state.yaml").read_bytes() == raw, out)
        ps(e, "event", "--stage", "discovery", "--event", "submitted", "--revision", "1")
        t = (e / ".ai-workflow/state.yaml").read_text(encoding="utf-8")
        check("S16 기존 항목 뒤에 새 항목 추가(기존 줄 보존)", 'note: "old" }' in t and t.index('note: "old"') < t.index("event: submitted"), t[-300:])
        bad = t.replace('  - { at: "2026-01-01T00:00:00Z"', '  - { at: "2099-01-01T00:00:00Z"')
        (e / ".ai-workflow/state.yaml").write_text(bad, encoding="utf-8")
        code, out = ps(e, "check")
        check("S17 미래 시각을 찾음(D-001 재현: LLM이 쓴 시각)", code == 2 and any("미래" in x for x in out["problems"]), out)
        bad2 = t.replace('event: submitted, revision: 1', 'event: submitted, revision: 1').replace(
            '  - { at: "2026-01-01T00:00:00Z"', '  - { at: "2026-13-01 25:00"')
        (e / ".ai-workflow/state.yaml").write_text(bad2, encoding="utf-8")
        code, out = ps(e, "check")
        check("S18 형식 오류 시각을 찾음", code == 2 and any("형식" in x for x in out["problems"]), out)
        rev = 'history:\n  - { at: "2026-05-02T00:00:00Z", stage: discovery, event: started, revision: 0, note: "a" }\n' \
              '  - { at: "2026-05-01T00:00:00Z", stage: discovery, event: submitted, revision: 1, note: "b" }'
        (e / ".ai-workflow/state.yaml").write_text(TEMPLATE.read_text(encoding="utf-8").replace("history: []", rev), encoding="utf-8")
        code, out = ps(e, "check")
        check("S19 앞 항목보다 이른 시각(역순)을 찾음", code == 2 and any("이른" in x for x in out["problems"]), out)
        skill = (ENGINE / "skills/product-start/SKILL.md").read_text(encoding="utf-8")
        check("S20 SKILL이 history·승인 기록을 스크립트로만 쓰도록 지시", "ps_state.py" in skill and "직접 쓰지 않습니다" in skill)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
