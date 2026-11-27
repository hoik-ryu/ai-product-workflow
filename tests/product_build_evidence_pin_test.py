#!/usr/bin/env python3
"""승인 근거 증거 고정(pin_evidence·case_records·classify_e3_record) 단위 검사.

- verified에 쓰인 실패·통과 쌍은 일반 이력(HISTORY_KEEP)에서 잘려도 판정에 남는다
- 결함 주입 근거는 앞쪽 통과 기록이 잘려도 '실패 우선(fix)'으로 바뀌지 않는다(고정 당시 판정 유지)
- 고정 기록도 무효화 규칙(테스트 변경, 같은 코드로 통과)을 그대로 거친다
- 결함 주입 근거는 사용자 인정으로 verified일 때만 고정된다
- 이미 일반 이력에서 사라진 기록은 새로 만들지 않는다
실행: python3 tests/product_build_evidence_pin_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True  # 엔진 폴더에 바이트코드를 남기지 않음(D5·C4 검사)
ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE / "skills/product-build/scripts"))
import pb_verify as V  # noqa: E402

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    results.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name)


def rec(run: str, status: str, code: str, at: str, batch: str = "B1", test_sha: str = "t1") -> dict:
    return {"run": run, "tree": "x", "code": code, "test_sha": test_sha, "test_copy": None, "status": status, "at": at, "valid": True,
            "batch": batch, "mode": "final"}


def run_obj(run_id: str, code: str, case: str = "c1", ac: str = "AC-001", status: str = "passed") -> dict:
    return {"run_id": run_id, "batch": "B1", "valid": True, "code_only_tree": code, "at": "z" + run_id,
            "steps": [{"name": "test", "status": "passed", "cases": [{"id": case, "acs": [ac], "status": status, "test_sha": "t1"}]}]}


cur = {"status": "passed", "code": "C2", "test_sha": "t1"}

# 1) 결함 주입: 통과(C1) → 실패(C1 훼손=C9) → 통과(C1). 같은 배치라 fault_injection
hist = {"c1": {"acs": ["AC-001"], "records": [rec("r1", "passed", "C1", "1"), rec("r2", "failed", "C9", "2")]}}
r3 = run_obj("r3", "C1")
V.update_history(hist, r3, "x")
ev = V.evaluate(["AC-001"], {"AC-001": "E3"}, r3, hist, set(), "x", accept_fi={"AC-001"})
check("결함 주입 근거로 verified(사용자 인정)", ev["AC-001"]["status"] == "verified" and ev["AC-001"]["evidence"][0]["type"] == "fault_injection")
pins = V.pin_evidence(hist, ev, r3, "3")
check("결함 주입 쌍 고정(kind 유지)", len(pins) == 1 and hist["c1"]["pinned"][0]["kind"] == "fault_injection" and hist["c1"]["pinned"][0]["green"]["run"] == "r3")
check("같은 쌍은 다시 고정하지 않음", V.pin_evidence(hist, ev, r3, "3") == [])

# 2) 일반 이력이 잘려 실패·이전 통과 기록이 모두 사라져도 고정 증거로 판정 유지, fix로 올라가지 않음
hist["c1"]["records"] = [rec(f"n{i}", "passed", "C1", f"9{i}") for i in range(V.HISTORY_KEEP)]
r4 = run_obj("r4", "C1")
V.update_history(hist, r4, "x")
ev4 = V.evaluate(["AC-001"], {"AC-001": "E3"}, r4, hist, set(), "x", accept_fi={"AC-001"})
e4 = ev4["AC-001"]
check("잘린 뒤에도 고정 증거로 verified", e4["status"] == "verified" and e4["evidence"][0]["pinned"] is True)
check("고정 결함 주입은 E3(fix)로 바뀌지 않음", e4["level"] == "E2" and e4["evidence"][0]["type"] == "fault_injection")
ev4b = V.evaluate(["AC-001"], {"AC-001": "E3"}, r4, hist, set(), "x", accept_fi=set())
check("사용자 인정이 없으면 고정 결함 주입도 insufficient", ev4b["AC-001"]["status"] == "insufficient")

# 3) 실제 실패 우선(fix): 처음 실패(C0) → 수정(C2) 통과. 고정 뒤 이력이 잘려도 E3 유지
h2 = {"c2": {"acs": ["AC-002"], "records": [rec("a1", "failed", "C0", "1")]}}
ra = run_obj("a2", "C2", "c2", "AC-002")
V.update_history(h2, ra, "x")
eva = V.evaluate(["AC-002"], {"AC-002": "E3"}, ra, h2, set(), "x")
check("실패 우선 → E3", eva["AC-002"]["level"] == "E3")
V.pin_evidence(h2, eva, ra, "2")
h2["c2"]["records"] = [rec(f"m{i}", "passed", "C2", f"9{i}") for i in range(V.HISTORY_KEEP)]
rb = run_obj("a3", "C2", "c2", "AC-002")
V.update_history(h2, rb, "x")
evb = V.evaluate(["AC-002"], {"AC-002": "E3"}, rb, h2, set(), "x")
check("잘린 뒤에도 고정된 실패 우선 근거로 E3", evb["AC-002"]["level"] == "E3" and evb["AC-002"]["status"] == "verified")

# 4) 무효화: 지금 코드가 실패 때와 같으면 고정 fix도 fault_injection(E3 아님)
cur_same = {"status": "passed", "code": "C0", "test_sha": "t1"}
kind, _, _ = V.classify_e3_record(V.case_records(h2["c2"]), cur_same, "B1")
check("고정 기록도 같은 코드 통과는 E3 아님", kind == "fault_injection")

# 5) 무효화: 테스트 파일이 바뀌면 고정 fix도 test_changed(테스트 원문 비교 불가 → 바뀐 것으로 봄)
cur_test = {"status": "passed", "code": "C3", "test_sha": "t2", "file": None, "func": None}
kind, _, _ = V.classify_e3_record([r for r in V.case_records(h2["c2"]) if r["status"] == "failed"], cur_test, "B1")
check("고정 기록도 테스트 변경이면 test_changed", kind == "test_changed")

# 6) 이미 일반 이력에서 사라진 근거는 고정하지 않음(만들어 내지 않음)
h3 = {"c3": {"acs": ["AC-003"], "records": [rec("x1", "failed", "C0", "1")]}}
rx = run_obj("x2", "C2", "c3", "AC-003")
V.update_history(h3, rx, "x")
evx = V.evaluate(["AC-003"], {"AC-003": "E3"}, rx, h3, set(), "x")
h3["c3"]["records"] = [r for r in h3["c3"]["records"] if r["run"] != "x1"]
check("사라진 기록은 고정하지 않음", V.pin_evidence(h3, evx, rx, "2") == [] and not h3["c3"].get("pinned"))

ok = sum(1 for _, x in results if x)
print(f"\n{ok}/{len(results)} passed")
sys.exit(0 if ok == len(results) else 1)
