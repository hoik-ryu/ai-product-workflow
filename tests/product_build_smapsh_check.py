#!/usr/bin/env python3
"""/product-build를 실제 프로젝트(SMAPSH) **복제본**에 적용해 범위 추출·B0–B4 비교·adopt 후보를 확인합니다.

- 원본 저장소에는 실행하지 않습니다(경로가 원본이면 거부). 복제본은 호출자가 만들고 정리합니다.
  예) rsync -a --exclude node_modules --exclude .venv --exclude .env --exclude experiments <원본>/ <임시>/smapsh/
- 복제본에서는 init(상태·프로필 생성)과 계획 파일 쓰기를 합니다. 복제본의 기획·디자인 승인 문서는 바꾸지 않고, 전후 해시로 확인합니다.
- 배치 비교 기준: tests/fixtures/smapsh-batches.json(원본을 읽기 전용으로 확인한 실제 배치).

실행: python3 tests/product_build_smapsh_check.py <복제본 경로> [--original <원본 경로>]
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

results = T.results


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    clone = Path(sys.argv[1]).resolve()
    original = Path(sys.argv[sys.argv.index("--original") + 1]).resolve() if "--original" in sys.argv else (Path.home() / "Desktop/badminton-playbook").resolve()
    if clone == original or original in clone.parents:
        print("원본 저장소에서는 실행하지 않습니다. 복제본 경로를 주세요.")
        return 2
    truth = json.loads((HERE / "fixtures/smapsh-batches.json").read_text())
    snap = T.protected_snapshot(clone)
    report: dict = {}

    code, out = T.pb(clone, "check")
    T.check("S1 check: 기획 승인·디자인 L2(UX Spec·DD 승인, 프리뷰 미승인)", code == 0 and out["design"]["level"] == "L2", out)
    report["design"] = out.get("design")
    T.pb(clone, "init")
    code, sc = T.pb(clone, "scope", "--suggest")
    c = sc["counts"]
    report["scope_counts"] = c
    report["deleted"] = sc["deleted"]
    T.check("S2 [검증 2] SCR/AC 범위 추출: SCR 29, AC 104(폐기 3개 제외), US 24, FR 24, CMP 25",
            code == 0 and c["SCR"] == 29 and c["AC"] == 104 and c["US"] == 24 and c["FR"] == 24 and c["CMP"] == 25, c)
    T.check("S3 폐기 ID(취소선) 제외: AC-048·051·052, FR/US-017·018",
            set(sc["deleted"]) == {"AC-048", "AC-051", "AC-052", "FR-017", "FR-018", "US-017", "US-018"}, sc["deleted"])
    T.check("S4 Must 범위: AC 활성 100, 필수 화면 28(SCR-005 공통 404는 범위 밖), 비UI AC 11",
            c["AC_active"] == 100 and c["SCR_required"] == 28 and sc["scope"]["SCR_outside"] == ["SCR-005"] and c["AC_non_ui"] == 11, c)

    dr = T.draft_of(clone)
    T.save_plan(clone, dr)
    code, v = T.pb(clone, "plan-validate")
    T.check("S5 [검증 6] waiver 없이 화면 배치 차단, AC·화면 배정 오류 없음", code == 2 and T.has(v, "design_not_ready")
            and not any(T.has(v, k) for k in ("ac_missing", "ac_duplicate", "scr_missing", "scr_duplicate", "dep_cycle")), T.errors_of(v))
    T.pb(clone, "waiver", "add", "--reason", "복제본 검증: 프리뷰 승인 없이 배치 구현(원본의 사용자 결정과 같은 경로)", "--all-ui",
         "--note", "복제본 검증용 승인", "--confirm")
    code, v = T.pb(clone, "plan-validate")
    T.check("S6 [검증 7] waiver 후 초안 계획 검증 통과", code == 0, T.errors_of(v))
    d = v.get("derived", {})
    report["draft"] = [{"id": b["id"], "kind": b["kind"], "screens": b["screens"], "acs": len(b["acs"]),
                        "approval": d["batches"][b["id"]]["approval"], "reasons": d["batches"][b["id"]]["approval_reasons"]} for b in dr["batches"]]
    report["warnings"] = v.get("warnings")

    # [검증 3] B0–B4 실제 배치와 비교(화면 소유 기준)
    gen = {s: b["id"] for b in dr["batches"] for s in b["screens"]}
    act = {s: k for k, ss in truth["batches"].items() for s in ss}
    common = sorted(set(gen) & set(act))
    pairs = list(itertools.combinations(common, 2))
    agree = sum(1 for x, y in pairs if (gen[x] == gen[y]) == (act[x] == act[y]))
    together_act = [(x, y) for x, y in pairs if act[x] == act[y]]
    kept = sum(1 for x, y in together_act if gen[x] == gen[y])
    per = {}
    for k, ss in truth["batches"].items():
        cand = {}
        for s in ss:
            if s in gen:
                cand.setdefault(gen[s], set()).add(s)
        if cand:
            best = max(cand, key=lambda g: len(cand[g]))
            gset = {s for s, g in gen.items() if g == best}
            per[k] = {"best_generated": best, "jaccard": round(len(set(ss) & gset) / len(set(ss) | gset), 2),
                      "split_into": sorted(cand), "actual": ss, "generated": sorted(gset)}
    report["comparison"] = {"screens_compared": len(common), "rand_index": round(agree / len(pairs), 3),
                            "pairs_together_in_actual_kept": f"{kept}/{len(together_act)}", "per_actual_batch": per}
    T.check("S7 [검증 3] 비교 계산: 공통 화면 27개 이상 비교(B0~B6 기준)", len(common) >= 27, len(common))

    # adopt 후보(읽기 전용 분석)
    stb = (clone / ".ai-workflow/build.json").read_text()
    code, ad = T.pb(clone, "adopt", "--full")
    T.check("S8 adopt: 승인·검증 이력 없이 분석만(build.json 불변), 모든 항목 verified=false", code == 0
            and (clone / ".ai-workflow/build.json").read_text() == stb
            and all(x["verified"] is False for x in ad["screens"].values()) and all(x["verified"] is False for x in ad["acs"].values()), ad.get("counts"))
    T.check("S9 adopt: AC 증거는 E0/E1만(E2 이상을 매기지 않음)", set(x["evidence_level"] for x in ad["acs"].values()) <= {"E0", "E1"})
    impl = {s for k in truth["implemented"] for s in truth["batches"][k]}
    planned = {s for k in truth.get("unimplemented", []) for s in truth["batches"][k]}  # 확실히 미구현(B6). 진행 중(B5)은 판정에서 뺌
    cand_impl = sorted(s for s in impl if ad["screens"].get(s, {}).get("candidate"))
    cand_planned = sorted(s for s in planned if ad["screens"].get(s, {}).get("candidate"))
    report["adopt"] = {"counts": ad["counts"], "implemented_screens_candidate": f"{len(cand_impl)}/{len([s for s in impl if s in ad['screens']])}",
                       "unimplemented_screens_candidate(false_positive)": cand_planned,
                       "signals_unimplemented": {s: ad["screens"][s]["signal"] for s in sorted(planned) if s in ad["screens"]},
                       "batch_candidates": ad.get("batch_candidates")}
    T.check("S10 adopt: 구현된 화면(B1–B4)의 대부분이 후보로 잡힘(≥80%)", len(cand_impl) >= 0.8 * len([s for s in impl if s in ad["screens"]]),
            report["adopt"]["implemented_screens_candidate"])
    # 자리표시자 화면은 고정 목록이 아니라 복제본 코드에서 찾습니다(원본은 다른 세션이 계속 구현 중이라 바뀜)
    import re as _re
    ph = set()
    for f in (clone / "frontend/src").rglob("*.tsx"):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if "pending(" in line:
                ph |= set(_re.findall(r"SCR-\d{3}", line))
    ph &= set(ad["screens"])
    report["adopt"]["placeholder_screens_in_code"] = sorted(ph)
    if ph:
        T.check("S10b adopt: 코드에서 pending 자리표시자로만 연결된 화면은 후보가 아님",
                all(ad["screens"][s]["signal"] == "placeholder" and not ad["screens"][s]["candidate"] for s in ph), {s: ad["screens"][s]["signal"] for s in ph})
    else:
        T.check("S10b adopt: (해당 없음) 복제본 코드에 pending 자리표시자 화면이 없음 — 판정은 단위 테스트 B10b가 담당", True)
    report["adopt"]["known_limitation"] = ("미구현으로 기록된 배치의 화면 중 후보로 잡힌 것: " + (", ".join(cand_planned) or "없음")
                                           + " — 원본이 계속 바뀌고, 실제 컴포넌트가 있는 부분 구현은 경로·ID 신호로 구분할 수 없음. 그래서 adopt 결과는 후보일 뿐임")
    T.check("S11 [검증 9] 복제본의 기획·디자인 승인 문서·상태 불변", T.protected_snapshot(clone) == snap)
    print("\n=== 보고용 요약 ===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
