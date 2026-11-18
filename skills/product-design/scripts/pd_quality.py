"""/product-design EX5.1: 시각 품질 평가 계약(design-quality-review/v1). EX4 기술 측정과 별도입니다.

원칙
- 평가는 모델(또는 사람)이 실제 스크린샷을 보고 씁니다(`visually_reviewed`). 엔진은 평가 내용의 옳고 그름을 판정하지 않고,
  형식·근거·자동 사실과의 모순만 검사합니다. 엔진이 계산한 사실(`facts`)은 측정·정적 검사 결과이며 평가와 섞지 않습니다.
- 점수(숫자)는 받지 않습니다. 등급(strong·adequate·weak)과 관찰·근거 스크린샷·개선 항목을 받습니다.
  높게만 써서 통과하는 구조를 막기 위해: 기준마다 근거 스크린샷(현재 측정의 실제 파일), 시안마다 개선 항목 1개 이상,
  strong이 아니면 개선 항목 필수, 자동 사실과 모순되는 strong 금지, 기준 간 같은 문장 반복 금지.
- 수정 라운드는 기록된 수정 목표마다 수정 전(기준 시안 측정)·수정 후 스크린샷과 상태를 요구합니다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pd_core import block, emit, now, require_state, save_state, sha256_file

QUALITY_FORMAT = "design-quality-review/v1"
QUALITY_FILE = "quality.json"
CRITERIA = {"hierarchy": "시각적 계층", "density_balance": "정보 밀도와 균형", "typography": "타이포그래피 완성도",
            "component_consistency": "컴포넌트 표현 일관성", "iconography": "아이콘·일러스트 품질",
            "reference_alignment": "레퍼런스 디자인 언어와의 일치", "mobile_balance": "모바일 화면의 시각적 균형"}
RATINGS = ("strong", "adequate", "weak")
SEVERITIES = ("major", "minor")
GOAL_STATUS = ("addressed", "partial", "not_addressed")
SHOT_RE = re.compile(r"^shots/(M[0-9A-Za-z-]+)/shots/([^/]+\.png)$")
FILL_MIN = 0.6  # 모바일 첫 화면에서 콘텐츠가 차지하는 높이 비율 — 이보다 낮으면 '균형 strong'과 모순(사실 기반 하한, 미감 판정 아님)


def _ex():
    import pd_explore as EX
    return EX


def _shots_of(r: dict, lb: str, current_run: str | None = None) -> dict[str, dict]:
    """시안의 완료된 측정 스크린샷: 'shots/<run>/shots/<file>' → 결과."""
    out = {}
    for run in r.get("measurements") or []:
        if run.get("status") != "completed" or run.get("asset_fallback"):
            continue
        if current_run and run["run_id"] != current_run:
            continue
        for x in ((run.get("variants") or {}).get(lb) or {}).get("results") or []:
            if x.get("screenshot"):
                out[f"shots/{run['run_id']}/{x['screenshot']['path']}"] = x | {"run_id": run["run_id"]}
    return out


def facts(project: Path, st: dict, r: dict, lb: str, check_info: dict | None) -> dict:
    """자동으로 확인할 수 있는 사실(엔진 계산). 평가 등급이 아닙니다."""
    import pd_measure as MS
    ms = MS.variant_measurement(project, st, r, lb)
    f = {"measurement": ms.get("status"), "run_id": ms.get("run_id"), "contrast_low": 0, "fixed_overlap_mobile": 0, "overlap": 0,
         "component_inconsistent": 0, "first_screen_fill": {}, "touch_small": 0}
    run = next((x for x in reversed(r.get("measurements") or []) if x.get("run_id") == ms.get("run_id")), None)
    v = ((run or {}).get("variants") or {}).get(lb) or {}
    f["component_inconsistent"] = sum(1 for b in v.get("blocking") or [] if "component_inconsistent" in b)
    for x in v.get("results") or []:
        ws = x.get("warnings") or []
        f["contrast_low"] += sum(1 for w in ws if w.startswith("contrast_low"))
        f["overlap"] += sum(1 for w in ws if w.startswith("overlap:"))
        if x["viewport"].startswith("mobile"):
            f["fixed_overlap_mobile"] += sum(1 for w in ws if w.startswith("fixed_overlap"))
            f["touch_small"] += sum(1 for w in ws if w.startswith("touch_target_small"))
    for x in ((run or {}).get("variants") or {}).get(lb, {}).get("results") or []:
        if x["viewport"].startswith("mobile") and x.get("fill") is not None:
            f["first_screen_fill"][x["target"]] = x["fill"]
    ci = check_info or {}
    f["assets_used"] = len(ci.get("assets_used") or [])
    f["icons"] = len(ci.get("icons") or [])
    f["asset_rights_unconfirmed"] = ci.get("rights_unconfirmed") or []
    al = ci.get("alignment") or []
    f["reference_alignment"] = {k: sum(1 for x in al if x["result"] == k) for k in ("same", "near", "different", "unknown")} if al else None
    fb = [x for x in r.get("measurements") or [] if x.get("asset_fallback") and lb in (x.get("variants") or {})]
    f["asset_fallback"] = (None if not fb else ("passed" if fb[-1]["status"] == "completed" and not fb[-1]["variants"][lb]["blocking"] else "failed"))
    return f


CONTRADICTIONS = {
    "component_consistency": lambda f: f["component_inconsistent"] > 0 and "측정에서 컴포넌트 불일치(component_inconsistent)",
    "typography": lambda f: f["contrast_low"] > 0 and f"낮은 글자 대비 {f['contrast_low']}건(contrast_low)",
    "mobile_balance": lambda f: ((f["fixed_overlap_mobile"] > 0 and f"모바일 첫 화면 고정 요소 가림 {f['fixed_overlap_mobile']}건")
                                 or (any(v < FILL_MIN for v in f["first_screen_fill"].values())
                                     and f"모바일 첫 화면 채움 비율 {min(f['first_screen_fill'].values()):.2f} < {FILL_MIN}")),
    "iconography": lambda f: ((f["assets_used"] == 0 and "등록 자산(아이콘·일러스트)을 쓰지 않음")
                              or (f["asset_fallback"] == "failed" and "자산 없이 렌더(fallback) 측정 실패")),
    "density_balance": lambda f: f["overlap"] > 0 and f"요소 겹침 {f['overlap']}건",
}


def validate(project: Path, st: dict, r: dict, data: dict, check: dict | None) -> tuple[list[str], list[str], dict]:
    EX = _ex()
    E, W = [], []
    rid = r["id"]
    if data.get("format") != QUALITY_FORMAT or data.get("round") != rid:
        return [f"{QUALITY_FILE}: format은 {QUALITY_FORMAT}, round는 {rid}여야 합니다"], W, {}
    if data.get("reviewer") not in ("model", "human"):
        E.append("reviewer는 model 또는 human입니다(누가 본 평가인지)")
    vs = data.get("variants") or {}
    allf = {}
    for lb in r["variants"]:
        tag = f"{rid}-{lb}"
        v = vs.get(lb)
        if not isinstance(v, dict):
            E.append(f"{tag}: 평가가 없습니다")
            continue
        ci = dict(((check or {}).get("visual") or {}).get(lb) or {})
        f = facts(project, st, r, lb, ci)
        allf[lb] = f
        shots = _shots_of(r, lb)
        import pd_render as RD  # EX7: figma 시안은 렌더러 스크린샷이 근거(측정 사실 아님)
        shots.update({x["path"]: x for x in RD.renderer_evidence(r, (EX.load_manifest(project).get("rounds") or {}).get(rid) or {}, lb)})
        if not shots:
            E.append(f"{tag}: 완료된 측정 스크린샷이 없습니다 — 평가는 실제 렌더 스크린샷을 근거로 씁니다(quality_no_evidence)")
        crit = v.get("criteria") or {}
        texts, issues_total = [], 0
        for key, label in CRITERIA.items():
            c = crit.get(key)
            if not isinstance(c, dict):
                E.append(f"{tag}: '{label}'({key}) 평가가 없습니다")
                continue
            rating = c.get("rating")
            if key == "reference_alignment" and r.get("mode", "ai") == "ai":
                if rating != "not_applicable":
                    E.append(f"{tag}: AI 라운드의 reference_alignment는 not_applicable입니다")
                continue
            if isinstance(rating, (int, float)) or rating not in RATINGS:
                E.append(f"{tag}.{key}: 등급은 {'/'.join(RATINGS)} 중 하나(숫자 점수는 받지 않음)")
            obs = str(c.get("observations") or "").strip()
            if len(obs) < 20:
                E.append(f"{tag}.{key}: 관찰(observations)이 비었거나 너무 짧습니다(구체적으로 무엇을 봤는지)")
            if obs and obs in texts:
                E.append(f"{tag}.{key}: 다른 기준과 같은 문장입니다(review_boilerplate)")
            texts.append(obs)
            ev = c.get("evidence") or []
            if not ev:
                E.append(f"{tag}.{key}: 근거 스크린샷(evidence)이 없습니다")
            for p in ev:
                if p not in shots:
                    E.append(f"{tag}.{key}: 근거 {p}는 이 시안의 완료된 측정 스크린샷이 아닙니다(quality_evidence_invalid)")
                elif not (project / EX.round_rel(rid) / p).is_file():
                    E.append(f"{tag}.{key}: 근거 파일 {p}가 없습니다")
            iss = c.get("issues") or []
            issues_total += len(iss)
            for j, x in enumerate(iss):
                if not isinstance(x, dict) or x.get("severity") not in SEVERITIES or len(str(x.get("what") or "")) < 8 \
                        or len(str(x.get("fix") or "")) < 8 or x.get("where") not in [t["id"] for t in r["targets"]]:
                    E.append(f"{tag}.{key}.issues[{j}]: severity(major/minor)·what·where(대상 화면)·fix(구체적 수정)가 필요합니다")
            if rating in ("adequate", "weak") and not iss:
                E.append(f"{tag}.{key}: {rating} 평가에는 개선 항목(issues)이 필요합니다")
            why = CONTRADICTIONS.get(key, lambda f: None)(f)
            if rating == "strong" and why:
                E.append(f"{tag}.{key}: strong은 자동 사실과 모순입니다 — {why}(rating_contradicts_facts)")
        if issues_total == 0:
            E.append(f"{tag}: 개선 항목이 하나도 없습니다 — 평가는 구체적인 개선 사항을 함께 씁니다(review_without_improvements)")
        if f["measurement"] not in ("passed", "blocked"):
            W.append(f"{tag}: 측정 상태 {f['measurement']} — 평가 근거가 현재 시안과 다를 수 있습니다")
    # 수정 라운드: 목표별 수정 전·후
    goals = (r.get("revision") or {}).get("goals") or []
    if goals:
        gv = data.get("goals") or {}
        base_round, base_lb = r["base"].rsplit("-", 1)
        _, br = EX._round(st, base_round)
        before_shots = _shots_of(br, base_lb)
        for i, g in enumerate(goals, 1):
            gid = f"G{i}"
            x = gv.get(gid)
            if not isinstance(x, dict) or x.get("status") not in GOAL_STATUS:
                E.append(f"수정 목표 {gid}({g[:30]}): status({'/'.join(GOAL_STATUS)})가 필요합니다")
                continue
            bf = [p for p in x.get("before") or [] if p in before_shots]  # 기준 라운드 기준 경로(shots/<run>/shots/…)
            if not bf:
                E.append(f"수정 목표 {gid}: 수정 전 근거(before)는 기준 시안 {r['base']}의 측정 스크린샷이어야 합니다")
            for lb in r["variants"]:
                if not [p for p in x.get("after") or [] if p in _shots_of(r, lb)]:
                    E.append(f"수정 목표 {gid}: 수정 후 근거(after)는 {rid}-{lb}의 측정 스크린샷이어야 합니다")
            if len(str(x.get("note") or "")) < 10:
                E.append(f"수정 목표 {gid}: 무엇을 어떻게 바꿨는지(note)가 필요합니다")
    return E, W, allf


def load(project: Path, r: dict) -> dict | None:
    p = project / _ex().round_rel(r["id"]) / QUALITY_FILE
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"_error": str(e)}


def review_state(project: Path, st: dict, r: dict, check: dict | None) -> dict:
    data = load(project, r)
    if data is None:
        return {"present": False, "valid": False, "errors": []}
    if "_error" in data:
        return {"present": True, "valid": False, "errors": [f"{QUALITY_FILE} JSON 오류: {data['_error']}"]}
    e, w, f = validate(project, st, r, data, check)
    return {"present": True, "valid": not e, "errors": e, "warnings": w, "facts": f}


def cmd_explore_quality(a) -> None:
    EX = _ex()
    project = Path(a.project).resolve()
    st = require_state(project)
    phase, r = EX._round(st, a.round)
    if phase != "visual":
        block("invalid_arguments", "시각 품질 평가는 2차(시각) 라운드에서 씁니다(1차는 critique.md).")
    check = EX.check_round(project, st, r["id"])
    rs = review_state(project, st, r, check)
    if not rs["present"]:
        emit({"ok": False, "round": r["id"], "error": "quality_review_missing",
              "message": f"{EX.round_rel(r['id'])}/{QUALITY_FILE}(design-quality-review/v1)를 실제 측정 스크린샷을 보고 작성합니다.",
              "criteria": CRITERIA, "facts": {lb: facts(project, st, r, lb, ((check.get('visual') or {}).get(lb) or {})) for lb in r["variants"]}}, 2)
    p = project / EX.round_rel(r["id"]) / QUALITY_FILE
    r["quality"] = {"at": now(), "valid": rs["valid"], "sha256": sha256_file(p), "errors": len(rs["errors"])}
    save_state(project, st)
    emit({"ok": rs["valid"], "round": r["id"], "errors": rs["errors"], "warnings": rs.get("warnings", []), "facts": rs.get("facts"),
          "levels": {"facts": "measured·checked(엔진)", "ratings": f"visually_reviewed: {(load(project, r) or {}).get('reviewer')}(평가자 판단, 엔진 판정 아님)"},
          "note": "평가 통과는 형식·근거·사실 모순 검사를 통과했다는 뜻입니다. 디자인 품질이 좋다는 엔진 판정이 아니며 선택·승인도 아닙니다."},
         0 if rs["valid"] else 2)
