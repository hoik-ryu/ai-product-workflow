"""/product-build adopt(M2.1: 읽기 전용 분석): 이미 있는 코드·테스트·라우트를 계획의 화면·AC·배치와 연결할 '후보'를 만듭니다.

원칙
- ID가 코드에 언급됐다는 이유로 구현 완료나 검증 통과로 판정하지 않습니다. 모든 결과는 후보(candidate)이고 verified=false입니다.
- AC 증거 수준은 E0(언급 없음)·E1(테스트에 언급)까지만 매깁니다. E2 이상은 실제 테스트 실행 리포트(M2.3)로만 판정합니다.
- 상태 파일(build.json)과 승인 기록을 만들거나 바꾸지 않습니다.
"""
from __future__ import annotations

import re
from pathlib import Path

from pb_scan import component_inventory, id_mentions, iter_source, route_hits, route_regex

SIGNAL_NOTE = "후보일 뿐입니다. 구현 여부는 코드 검토와 M2.3 검증(테스트 리포트·브라우저 검사)으로 확인합니다."
# 자리표시자(아직 구현 안 됨) 표시: 라우트·ID가 이런 줄에만 있으면 후보에서 뺍니다(일반 관례 단어, 프로필 adopt.placeholder_words로 추가)
PLACEHOLDER_WORDS = ("pending", "placeholder", "todo", "stub", "not implemented", "notimplemented", "coming soon", "wip",
                     "준비 중", "준비중", "미구현", "구현 예정", "자리표시자")


def _placeholder_re(extra: list[str] | None) -> re.Pattern:
    words = list(PLACEHOLDER_WORDS) + list(extra or [])
    return re.compile("|".join(rf"\b{re.escape(w)}\b" if re.fullmatch(r"[a-z ]+", w) else re.escape(w) for w in words), re.I)


def _lines(project: Path, rel: str) -> list[str]:
    try:
        return (project / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def placeholder_only(project: Path, screen: dict, route: dict, mention: dict | None, rx_ph: re.Pattern) -> bool:
    """코드에서 이 화면의 경로·ID가 나오는 줄이 모두 자리표시자 줄이면 True."""
    lines = []
    for rel in route.get("code", []):
        src = _lines(project, rel)
        for r in screen.get("routes", []):
            rx = route_regex(r)
            if rx:
                lines += [ln for ln in src if rx.search(ln)]
    for loc in (mention or {}).get("code", []):
        rel, _, n = loc.split(" ")[0].rpartition(":")
        src = _lines(project, rel)
        if n.isdigit() and 0 < int(n) <= len(src):
            lines.append(src[int(n) - 1])
    return bool(lines) and all(rx_ph.search(ln) for ln in lines)


def screen_signal(route: dict, mention: dict | None) -> str:
    code_route = bool(route.get("code"))
    code_id = bool(mention and mention["code"])
    test_id = bool(mention and mention["test"])
    if code_route and not route.get("overlay") and (code_id or test_id):
        return "route_and_id"
    if code_route and not route.get("overlay"):
        return "route_only"
    if code_route:  # 시트·패널: 부모 경로만 확인됨
        return "parent_route" + ("_and_id" if code_id or test_id else "")
    if code_id or test_id:
        return "id_only"
    return "none"


def analyze(project: Path, model: dict, scope: dict, profile: dict, plan: dict | None) -> dict:
    paths = profile["paths"]
    roots = sorted(set((paths.get("source") or []) + (paths.get("tests") or []))) or None
    files = iter_source(project, roots, paths.get("exclude"))
    mentions = id_mentions(project, files)
    screens = {s: model["SCR"][s] for s in sorted(set(scope["SCR_required"]) | set(scope["SCR_related_optional"])) if s in model["SCR"]}
    routes = route_hits(project, files, screens)
    comps = component_inventory(project, paths.get("components") or [], files, model["CMP"]) if paths.get("components") else None

    rx_ph = _placeholder_re((profile.get("adopt") or {}).get("placeholder_words"))
    scr_out = {}
    for s in screens:
        m = mentions.get(s)
        sig = screen_signal(routes[s], m)
        if sig != "none" and placeholder_only(project, screens[s], routes[s], m, rx_ph):
            sig = "placeholder"
        scr_out[s] = {"signal": sig, "candidate": sig in ("route_and_id", "route_only", "parent_route_and_id"),
                      "routes": routes[s]["routes"], "route_files": routes[s]["code"][:5],
                      "id_in_code": (m or {}).get("code", [])[:5], "id_in_tests": (m or {}).get("test", [])[:5],
                      "verified": False}
    ac_out = {}
    for a in scope["AC_active"]:
        m = mentions.get(a) or {"code": [], "test": []}
        ac_out[a] = {"evidence_level": "E1" if m["test"] else "E0", "test_mentions": m["test"][:5],
                     "code_mentions": len(m["code"]), "verified": False}
    counts = {
        "source_files": len(files), "test_files": sum(1 for f in files if _is_test(f)),
        "screens": len(scr_out), "screen_candidates": sum(1 for v in scr_out.values() if v["candidate"]),
        "screen_signals": _count(v["signal"] for v in scr_out.values()),
        "ac_active": len(ac_out), "ac_E1_mentioned": sum(1 for v in ac_out.values() if v["evidence_level"] == "E1"),
        "ac_E0": sum(1 for v in ac_out.values() if v["evidence_level"] == "E0"),
    }
    out = {"ok": True, "mode": "analysis_only", "note": SIGNAL_NOTE, "counts": counts, "screens": scr_out, "acs": ac_out,
           "components": comps, "writes": "없음(분석 전용: 상태·승인·검증 이력을 만들지 않음)"}
    if plan and isinstance(plan.get("batches"), list):
        cand = []
        for b in plan["batches"]:
            scrs = [s for s in b.get("screens") or [] if s in scr_out]
            acs = [a for a in b.get("acs") or [] if a in ac_out]
            sc = sum(1 for s in scrs if scr_out[s]["candidate"])
            ae = sum(1 for a in acs if ac_out[a]["evidence_level"] == "E1")
            ratio = (sc / len(scrs)) if scrs else None
            if scrs:
                status = "existing_candidate" if ratio >= 0.5 else ("partial_candidate" if sc else "no_signal")
            else:
                status = "partial_candidate" if ae else "no_signal"
            cand.append({"batch": b["id"], "title": b.get("title"), "status": status,
                         "screens_with_signal": f"{sc}/{len(scrs)}", "acs_mentioned_in_tests": f"{ae}/{len(acs)}",
                         "next": ("M2.2·M2.3에서 imported로 등록 후 검증(테스트 리포트·브라우저)으로 확인" if status != "no_signal" else "신규 구현 대상")})
        out["batch_candidates"] = cand
    return out


def _is_test(f: str) -> bool:
    from pb_scan import is_test_path
    return is_test_path(f)


def _count(it) -> dict:
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out
