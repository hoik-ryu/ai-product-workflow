"""/product-build 계획: 초안 골격 제안(결정적), 계획 검증(구조·참조·중복·누락·의존성·디자인 준비·승인 정책), 문서 렌더링.

역할 분리: Claude가 implementation-plan.json을 작성·다듬고, 이 모듈은 검증과 렌더링만 합니다.
draft()는 Claude의 출발점이 되는 골격일 뿐 정답이 아닙니다(화면 묶음은 IA 셸·경로 접두사 기준의 일반 규칙).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from pb_core import GENERATED_MARK, LAYERS, PLAN_FORMAT, RISK_TAGS
from pb_exec import pattern_problems
from pb_inputs import compute_scope, known_ids

BATCH_ID = re.compile(r"^B\d{1,3}$")
TASK_ID = re.compile(r"^(B\d{1,3})-T\d{1,3}$")
KINDS = ("ui", "non_ui", "foundation")
EV_RANK = {"E0": 0, "E1": 1, "E2": 2, "EM": 3, "E3": 3}


# ---------------------------------------------------------------- 위험 감지(일반 키워드, 프로필로 조정)
def detect_tags(text: str, keywords: dict) -> dict[str, list[str]]:
    low = text.lower()
    found = {}
    for tag, words in (keywords or {}).items():
        hits = []
        for w in words:
            wl = w.lower()
            if re.fullmatch(r"[a-z][a-z ]*", wl):
                if re.search(rf"\b{re.escape(wl)}\b", low):
                    hits.append(w)
            elif wl in low:
                hits.append(w)
        if hits:
            found[tag] = hits
    return found


def ac_text(model: dict, a: str) -> str:
    s = model["AC"].get(a, {})
    return f"{s.get('title', '')}\n{s.get('text', '')}"


def waiver_valid(w: dict, dinfo: dict) -> bool:
    b = w.get("basis", {})
    return (w.get("status") == "active" and dinfo.get("level") == "L2"
            and b.get("ux_spec_revision") == dinfo.get("basis", {}).get("ux_spec_revision")
            and b.get("design_direction_revision") == dinfo.get("basis", {}).get("design_direction_revision"))


def waiver_for(batch_id: str, waivers: list[dict], dinfo: dict) -> dict | None:
    for w in waivers:
        if w.get("kind") == "preview" and waiver_valid(w, dinfo) and (w["scope"].get("all_ui") or batch_id in w["scope"].get("batches", [])):
            return w
    return None


# ---------------------------------------------------------------- 초안 골격(결정적 제안)
def _first_route(s: dict) -> list[str]:
    r = s["routes"][0] if s.get("routes") else ""
    return [x for x in r.strip("/").split("/") if x and not x.startswith((":", "[", "{", "$"))]


def suggest_groups(model: dict, screens: list[str], max_screens: int, min_screens: int) -> list[dict]:
    """IA 셸(있으면) → 크기 초과 시 경로 접두사로 나눔 → 작은 묶음은 US가 가장 많이 겹치는 묶음에 합침."""
    scr = model["SCR"]
    by_shell: dict[str, list[str]] = defaultdict(list)
    for s in sorted(screens):
        by_shell[scr[s].get("shell") or ""].append(s)
    groups: list[dict] = []
    for shell, items in by_shell.items():
        if shell and len(items) <= max_screens:
            groups.append({"key": shell, "shell": shell, "screens": items})
            continue
        depth = 1
        while True:
            parts: dict[str, list[str]] = defaultdict(list)
            for s in items:
                segs = _first_route(scr[s])
                parts["/".join(segs[:depth]) or "(경로 없음)"].append(s)
            if len(parts) > 1 or depth >= 3:
                break
            depth += 1
        for k, v in parts.items():
            groups.append({"key": f"{shell}:{k}" if shell else k, "shell": shell, "screens": v})

    def us_of(g):
        return {u for s in g["screens"] for u in scr[s]["trace"] if u.startswith("US-")}

    changed = True
    while changed:
        changed = False
        small = [g for g in groups if len(g["screens"]) < min_screens]
        for g in small:
            others = [o for o in groups if o is not g]
            if not others:
                break
            best = max(others, key=lambda o: (len(us_of(g) & us_of(o)), o["shell"] == g["shell"] and bool(g["shell"]),
                                              -abs(int(min(o["screens"])[4:]) - int(min(g["screens"])[4:]))))
            if not (us_of(g) & us_of(best)) and best["shell"] != g["shell"]:
                continue  # 공통점이 없으면 합치지 않음
            if len(best["screens"]) + len(g["screens"]) > max_screens + 2:
                continue
            best["screens"] = sorted(best["screens"] + g["screens"])
            best["key"] = best["key"] + "+" + g["key"]
            groups.remove(g)
            changed = True
            break
    return sorted(groups, key=lambda g: min(g["screens"]))


def draft(model: dict, scope: dict, profile: dict, ui_allowed: bool = True, mapped: set[str] | frozenset = frozenset()) -> dict:
    """ui_allowed=False(UX Spec 미승인)면 화면 묶음 없이 모든 AC를 화면 없는 배치(non_ui)에 둡니다.
    mapped: UI 대응표에 이미 대응된 CMP(기존·라이브러리·만든 부품). 신규가 아니라 재사용으로 제안합니다."""
    b = profile["batching"]
    screens = sorted(set(scope["SCR_required"]) | set(scope["SCR_related_optional"])) if ui_allowed else []
    groups = suggest_groups(model, screens, int(b["max_screens"]), int(b["min_screens"])) if screens else []
    owner = {s: i for i, g in enumerate(groups) for s in g["screens"]}
    cmp_groups: dict[str, set] = defaultdict(set)
    for i, g in enumerate(groups):
        for s in g["screens"]:
            for c in model["SCR"][s]["cmp"]:
                cmp_groups[c].add(i)
    shared = sorted(c for c, gs in cmp_groups.items() if len(gs) >= 2 and c not in mapped)
    acs_of: dict[int, list[str]] = defaultdict(list)
    non_ui: list[str] = []
    for a in scope["AC_active"]:
        scrs = [s for s in model["ac_screens"].get(a, []) if s in owner]
        if not scrs:  # 비UI: 그 US의 화면이 속한 묶음(세로 슬라이스), 없으면 비UI 배치
            us = model["AC"][a]["us"]
            scrs = [s for u in us for s in (model["us_screens"].get(u) or [x for x, i in model["SCR"].items() if u in i["trace"]]) if s in owner]
        if scrs:
            cnt = Counter(owner[s] for s in scrs)
            acs_of[max(cnt, key=lambda k: (cnt[k], -k))].append(a)
        else:
            non_ui.append(a)
    batches = []
    if shared:
        batches.append({"id": "B0", "title": "공통 기반", "goal": "둘 이상의 배치가 쓰는 공통 컴포넌트와 셸",
                        "kind": "foundation", "screens": [], "acs": [], "components": {"reuse": [], "new": shared}, "paths": {"allow": [], "shared": []},
                        "depends_on": [], "tasks": [{"id": "B0-T1", "layer": "fe", "title": "공통 컴포넌트 구현", "refs": shared}],
                        "risk_tags": [], "done_criteria": ["프로필 검증 명령 통과"], "test_plan": []})
    strategy = profile["project"].get("order_strategy")
    nonui_batch = None
    if non_ui:
        nonui_batch = {"id": "", "title": "화면 없는 규칙·API", "goal": "화면에 대응하지 않는 AC(서버 규칙·계약)",
                       "kind": "non_ui", "screens": [], "acs": sorted(non_ui), "components": {"reuse": [], "new": []}, "paths": {"allow": [], "shared": []},
                       "depends_on": [], "tasks": [{"id": "", "layer": "be", "title": "비UI 규칙 구현", "refs": sorted(non_ui)}],
                       "risk_tags": [], "done_criteria": ["프로필 검증 명령 통과"], "test_plan": [{"ac": a, "kind": "unit"} for a in sorted(non_ui)]}
    if nonui_batch and strategy in ("api-first", "backend-first"):
        batches.append(nonui_batch)
    for i, g in enumerate(groups):
        cmps = sorted({c for s in g["screens"] for c in model["SCR"][s]["cmp"]})
        acs = sorted(acs_of.get(i, []))
        tasks = [{"layer": "fe", "title": "화면 구현: " + ", ".join(g["screens"]), "refs": g["screens"]}]
        nui = [a for a in acs if a in model["ac_nonui"] or a in scope["AC_unmapped"]]
        if nui:
            tasks.append({"layer": "be", "title": "화면 없는 규칙", "refs": nui})
        tasks.append({"layer": "test", "title": "AC 테스트", "refs": acs})
        batches.append({"id": "", "title": g["key"], "goal": "", "kind": "ui", "screens": g["screens"], "acs": acs,
                        "components": {"reuse": [c for c in cmps if c in shared or c in mapped], "new": [c for c in cmps if c not in shared and c not in mapped]},
                        "paths": {"allow": [], "shared": []},
                        "depends_on": ["B0"] if shared else [], "tasks": tasks, "risk_tags": [],
                        "done_criteria": ["프로필 검증 명령 통과", "배치 AC 증거 수준 충족"],
                        "test_plan": [{"ac": a, "kind": "unit" if a in nui else "integration"} for a in acs]})
    if nonui_batch and strategy not in ("api-first", "backend-first"):
        batches.append(nonui_batch)
    n = 1 if shared else 0
    for bt in batches:
        if bt["id"] == "B0":
            continue
        bt["id"] = f"B{n}"
        for k, t in enumerate(bt["tasks"], 1):
            t["id"] = f"B{n}-T{k}"
        n += 1
    return {"plan_format": PLAN_FORMAT, "scope": {"priorities": scope["priorities"], "include": []},
            "order_strategy": strategy, "batches": batches, "deferred": [],
            "draft_note": "스크립트가 만든 골격입니다. 제목·목표·작업·의존성·위험 태그와 배치별 수정 범위(paths.allow·shared)를 채운 뒤 plan-validate로 검사하세요."}


# ---------------------------------------------------------------- 검증
def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    color: dict[str, int] = {}
    path: list[str] = []

    def dfs(v):
        color[v] = 1
        path.append(v)
        for w in graph.get(v, []):
            if color.get(w) == 1:
                return path[path.index(w):] + [w]
            if color.get(w, 0) == 0 and w in graph:
                r = dfs(w)
                if r:
                    return r
        color[v] = 2
        path.pop()
        return None

    for v in graph:
        if color.get(v, 0) == 0:
            r = dfs(v)
            if r:
                return r
    return None


def _closure(deps: dict[str, list[str]], start: str) -> set[str]:
    seen, stack = set(), list(deps.get(start, []))
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack.extend(deps.get(x, []))
    return seen


def validate(plan, model: dict, profile: dict, dinfo: dict, waivers: list[dict]) -> dict:
    E: list[str] = []
    W: list[str] = []

    def err(code, msg):
        E.append(f"[{code}] {msg}")

    if not isinstance(plan, dict):
        return {"ok": False, "errors": ["[plan_format] 계획이 JSON 객체가 아닙니다"], "warnings": [], "derived": {}}
    if plan.get("plan_format") != PLAN_FORMAT:
        err("plan_format", f"plan_format은 {PLAN_FORMAT}이어야 합니다")
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        err("plan_format", "batches가 비어 있거나 목록이 아닙니다")
        return {"ok": False, "errors": E, "warnings": W, "derived": {}}
    sc = plan.get("scope") or {}
    prios = sc.get("priorities") or profile["scope"].get("priorities") or ["Must"]
    for p in prios:
        if p not in ("Must", "Should", "Could"):
            err("scope", f"알 수 없는 우선순위 {p}")
    deferred = plan.get("deferred") or []
    if not isinstance(deferred, list):
        err("plan_format", "deferred는 목록이어야 합니다")
        deferred = []
    known = known_ids(model)
    deleted = set(model["deleted"])
    for inc in sc.get("include", []) or []:
        if inc not in model["US"] and inc not in model["AC"]:
            err("unknown_ref", f"scope.include의 {inc}는 기획에 없는 US/AC입니다")
    for d in deferred:
        if not isinstance(d, dict) or not d.get("id"):
            err("deferred", "deferred 항목은 {id, reason} 형식이어야 합니다")
        elif d["id"] not in known:
            err("unknown_ref", f"deferred의 {d['id']}는 기획·디자인에 없는 ID입니다")
        elif not str(d.get("reason", "")).strip():
            err("deferred_no_reason", f"{d['id']}: 미루는 사유가 필요합니다")
    scope = compute_scope(model, prios, sc.get("include"), deferred)
    ui_allowed = dinfo.get("level") in ("L2", "L3")
    if not ui_allowed:  # 승인되지 않은 UX Spec은 범위를 정할 수 없음: 화면 요구 없이 화면 없는 배치만 계획
        scope["SCR_required"], scope["SCR_related_optional"] = [], []
        if model["has_design"]:
            W.append(f"UX Spec이 승인되지 않아({dinfo.get('reason')}) 화면 범위를 적용하지 않았습니다. 화면 없는 DB/API 배치만 계획할 수 있습니다.")
    in_scope_ac, active_ac = set(scope["AC"]), set(scope["AC_active"])
    deferred_ids = {d.get("id") for d in deferred if isinstance(d, dict)}

    ids = [b.get("id") if isinstance(b, dict) else None for b in batches]
    pos = {}
    for i, b in enumerate(batches):
        if not isinstance(b, dict) or not BATCH_ID.match(str(b.get("id", ""))):
            err("batch_id", f"batches[{i}]: id는 B0, B1… 형식이어야 합니다 (현재: {b.get('id') if isinstance(b, dict) else b!r})")
            continue
        if b["id"] in pos:
            err("duplicate_batch", f"배치 ID 중복: {b['id']}")
        pos[b["id"]] = i
    if E:
        return {"ok": False, "errors": E, "warnings": W, "derived": {}}

    deps = {b["id"]: list(b.get("depends_on") or []) for b in batches}
    ac_owner: dict[str, str] = {}
    scr_owner: dict[str, str] = {}
    cmp_new_owner: dict[str, str] = {}
    task_batch: dict[str, str] = {}
    task_deps: dict[str, list[str]] = {}
    for b in batches:
        bid = b["id"]
        if b.get("kind") not in KINDS:
            err("batch_kind", f"{bid}: kind는 {'/'.join(KINDS)} 중 하나여야 합니다")
        if not str(b.get("title", "")).strip():
            err("batch_title", f"{bid}: title이 필요합니다")
        for d in deps[bid]:
            if d == bid:
                err("dep_self", f"{bid}가 자기 자신에 의존합니다")
            elif d not in pos:
                err("dep_unknown", f"{bid}: 없는 배치 {d}에 의존합니다")
            elif pos[d] > pos[bid]:
                err("order_violation", f"{bid}가 뒤에 있는 {d}에 의존합니다(배치 목록 순서가 실행 순서입니다)")
        for field in ("screens", "touches", "acs", "stories", "depends_on", "risk_tags", "done_criteria", "test_plan", "tasks"):
            if field in b and not isinstance(b[field], list):
                err("plan_format", f"{bid}.{field}는 목록이어야 합니다")
        for t in b.get("risk_tags") or []:
            if t not in RISK_TAGS:
                err("risk_tag", f"{bid}: 알 수 없는 위험 태그 {t} (허용: {', '.join(RISK_TAGS)})")
        if b.get("approval") not in (None, "auto", "user"):
            err("approval", f"{bid}: approval은 auto 또는 user입니다")
        paths = b.get("paths")
        if paths is None or not (isinstance(paths, dict) and paths.get("allow")):
            W.append(f"{bid}: paths.allow(수정 가능 경로)가 없습니다 — 배치 실행(batch-start) 전에 필요합니다")
        if paths is not None:
            if not isinstance(paths, dict) or set(paths) - {"allow", "shared"}:
                err("paths_invalid", f"{bid}: paths는 {{allow: [...], shared: [...]}} 형식이어야 합니다")
            else:
                for k in ("allow", "shared"):
                    for prob in pattern_problems(paths.get(k, [])):
                        err("paths_invalid", f"{bid}.paths.{k}: {prob}")
        for s in b.get("screens") or []:
            if s not in model["SCR"]:
                err("unknown_ref", f"{bid}: UX Spec에 없는 화면 {s}" + (" (폐기됨)" if s in deleted else ""))
            elif s in scr_owner:
                err("scr_duplicate", f"{s}가 {scr_owner[s]}와 {bid}에 모두 배정되었습니다(소유 배치는 하나, 다른 배치는 touches로)")
            else:
                scr_owner[s] = bid
        if b.get("kind") == "non_ui" and b.get("screens"):
            err("scr_in_non_ui", f"{bid}: non_ui 배치는 화면을 소유할 수 없습니다")
        for s in b.get("touches") or []:
            if s not in model["SCR"]:
                err("unknown_ref", f"{bid}.touches: 없는 화면 {s}")
        for u in b.get("stories") or []:
            if u not in model["US"]:
                err("unknown_ref", f"{bid}: 기획에 없는 {u}" + (" (폐기됨)" if u in deleted else ""))
        for a in b.get("acs") or []:
            if a not in model["AC"]:
                err("unknown_ref", f"{bid}: 기획에 없는 {a}" + (" (폐기됨)" if a in deleted else ""))
            elif a in ac_owner:
                err("ac_duplicate", f"{a}가 {ac_owner[a]}와 {bid}에 중복 배정되었습니다")
            elif a in deferred_ids or a in scope["AC_deferred"]:
                err("ac_both", f"{a}가 {bid}에 배정되면서 deferred에도 있습니다")
            elif a not in in_scope_ac:
                err("ac_out_of_scope", f"{bid}: {a}는 범위({'/'.join(prios)}) 밖입니다. 포함하려면 scope.include에 그 US를 넣으세요")
            else:
                ac_owner[a] = bid
        comps = b.get("components") or {}
        for c in comps.get("new", []) or []:
            if re.fullmatch(r"CMP-\d{3}", c):
                if model["CMP"] and c not in model["CMP"]:
                    err("unknown_ref", f"{bid}: 04에 없는 컴포넌트 {c}")
                if c in cmp_new_owner:
                    err("cmp_new_duplicate", f"{c}를 {cmp_new_owner[c]}와 {bid}가 모두 새로 만듭니다")
                cmp_new_owner[c] = bid
        tasks = b.get("tasks") or []
        if not tasks:
            err("no_tasks", f"{bid}: tasks가 비어 있습니다")
        for t in tasks:
            if not isinstance(t, dict):
                err("task_format", f"{bid}: 작업 형식 오류")
                continue
            m = TASK_ID.match(str(t.get("id", "")))
            if not m or m.group(1) != bid:
                err("task_id", f"{bid}: 작업 id는 {bid}-T1 형식이어야 합니다 (현재: {t.get('id')!r})")
                continue
            if t["id"] in task_batch:
                err("duplicate_task", f"작업 ID 중복: {t['id']}")
            task_batch[t["id"]] = bid
            task_deps[t["id"]] = list(t.get("depends_on") or [])
            if t.get("layer") not in LAYERS:
                err("task_layer", f"{t['id']}: layer는 {'/'.join(LAYERS)} 중 하나여야 합니다")
            if not str(t.get("title", "")).strip():
                err("task_title", f"{t['id']}: title이 필요합니다")
            for r in t.get("refs") or []:
                if re.fullmatch(r"(?:FR|US|AC|SCR|CMP)-\d{3}", r) and r not in known:
                    err("unknown_ref", f"{t['id']}: 없는 ID {r}")
        if not (b.get("acs") or b.get("screens") or (comps.get("new"))):
            err("empty_batch", f"{bid}: AC·화면·새 컴포넌트가 하나도 없습니다")
        if len(b.get("screens") or []) > int(profile["batching"]["max_screens"]):
            W.append(f"{bid}: 화면 {len(b['screens'])}개 — 상한 {profile['batching']['max_screens']} 초과(나누기 권장)")
        if len(b.get("acs") or []) > int(profile["batching"]["max_acs"]):
            W.append(f"{bid}: AC {len(b['acs'])}개 — 상한 {profile['batching']['max_acs']} 초과(나누기 권장)")
    cyc = _cycle(deps)
    if cyc:
        err("dep_cycle", "배치 의존성 순환: " + " → ".join(cyc))
    for tid, tds in task_deps.items():
        for d in tds:
            if d not in task_batch:
                err("task_dep_unknown", f"{tid}: 없는 작업 {d}에 의존합니다")
            elif task_batch[d] != task_batch[tid] and task_batch[d] not in _closure(deps, task_batch[tid]):
                err("task_dep_cross", f"{tid}가 {d}({task_batch[d]})에 의존하지만 배치 {task_batch[tid]}가 {task_batch[d]}에 의존하지 않습니다")
    tcyc = _cycle(task_deps)
    if tcyc:
        err("task_dep_cycle", "작업 의존성 순환: " + " → ".join(tcyc))
    for b in batches:
        for c in (b.get("components") or {}).get("reuse", []) or []:
            o = cmp_new_owner.get(c)
            if o and o != b["id"] and o not in _closure(deps, b["id"]):
                err("cmp_dep_missing", f"{b['id']}가 {o}에서 새로 만드는 {c}를 쓰지만 {o}에 의존하지 않습니다")
    missing = sorted(active_ac - set(ac_owner))
    if missing:
        err("ac_missing", f"범위 안 AC {len(missing)}개가 어느 배치에도 없고 deferred에도 없습니다: {', '.join(missing)}")
    scr_missing = sorted(set(scope["SCR_required"]) - set(scr_owner) - deferred_ids)
    if scr_missing:
        err("scr_missing", f"범위 안 AC가 쓰는 화면이 배정되지 않았습니다: {', '.join(scr_missing)}")
    opt_missing = sorted(set(scope["SCR_related_optional"]) - set(scr_owner) - deferred_ids)
    if opt_missing:
        W.append(f"범위 US와 연결됐지만 AC가 가리키지 않는 화면이 배정되지 않았습니다(필요하면 배정하거나 deferred로): {', '.join(opt_missing)}")
    for a, bid in sorted(ac_owner.items()) if ui_allowed else []:
        scrs = model["ac_screens"].get(a, [])
        b = batches[pos[bid]]
        mine = set(b.get("screens") or []) | set(b.get("touches") or [])
        if scrs and not (set(scrs) & mine):
            W.append(f"{a}({bid}): 이 AC의 화면({', '.join(scrs)})이 {bid}에 없습니다(소유: {', '.join(sorted({scr_owner.get(s, '미배정') for s in scrs}))})")

    # 디자인 준비·승인 정책·AC 목표 증거
    ap = profile["approval"]
    req_tags = set(ap.get("user_required_tags", []))
    kw = ap.get("risk_keywords") or {}
    ev = profile["evidence"]
    derived_b = {}
    for b in batches:
        bid = b["id"]
        requires_design = bool(b.get("screens")) or b.get("kind") == "ui" or any((t or {}).get("layer") == "fe" for t in b.get("tasks") or [])
        path, waiver_id = "planning_only", None
        if requires_design:
            lvl = dinfo.get("level")
            if lvl == "L3":
                path = "preview_approved"
            elif lvl == "L2":
                w = waiver_for(bid, waivers, dinfo)
                if w:
                    path, waiver_id = "preview_waiver", w["id"]
                else:
                    err("design_not_ready", f"{bid}: 화면 구현 배치인데 프리뷰가 승인되지 않았습니다. 사용자가 명시적으로 승인한 preview waiver(waiver add)가 이 배치를 포함해야 합니다")
            else:
                err("design_not_ready", f"{bid}: 화면 구현 배치는 UX Spec 승인이 필요합니다({dinfo.get('reason')}). 지금은 화면 없는 DB/API 배치(non_ui)만 계획할 수 있습니다")
        detected: dict[str, list[str]] = {}
        ac_targets = {}
        for a in b.get("acs") or []:
            if a not in model["AC"]:
                continue
            tags = detect_tags(ac_text(model, a), kw)
            for t, words in tags.items():
                detected.setdefault(t, []).append(f"{a}({', '.join(words[:2])})")
            prio = model["AC"][a]["priority"]
            level = ev["risk"] if set(tags) & req_tags else (ev["must"] if prio == "Must" else ev["should"])
            ac_targets[a] = level
        if any((t or {}).get("layer") == "db" for t in b.get("tasks") or []):
            detected.setdefault("schema_migration", []).append("db 작업 포함")
        declared = set(b.get("risk_tags") or [])
        tags_all = declared | set(detected)
        reasons = []
        if tags_all & req_tags:
            reasons.append("risk:" + ",".join(sorted(tags_all & req_tags)))
        if path == "preview_waiver" and ap.get("waived_ui") == "user":
            reasons.append("preview_waiver(시각 확인을 배치 검토로 대신함)")
        if b.get("approval") == "user":
            reasons.append("계획에서 사용자 승인 지정")
        if ap.get("default") == "user":
            reasons.append("프로필 기본값 user")
        mode = "user" if reasons else "auto"
        if b.get("approval") == "auto" and mode == "user":
            W.append(f"{bid}: approval=auto 요청은 적용하지 않습니다({'; '.join(reasons)}) — 위험 배치는 자동 승인으로 낮출 수 없습니다")
        derived_b[bid] = {"requires_design": requires_design, "design_path": path, "waiver": waiver_id,
                          "approval": mode, "approval_reasons": reasons, "risk_tags_declared": sorted(declared),
                          "risk_tags_detected": {k: v[:5] for k, v in sorted(detected.items())}, "ac_targets": ac_targets,
                          "depends_on": deps[bid]}
    derived = {"order": ids, "batches": derived_b, "scope": {k: (len(v) if isinstance(v, list) else v) for k, v in scope.items()},
               "scope_detail": scope, "design_level": dinfo.get("level"),
               "counts": {"batches": len(batches), "auto": sum(1 for v in derived_b.values() if v["approval"] == "auto"),
                          "user": sum(1 for v in derived_b.values() if v["approval"] == "user"),
                          "ac_assigned": len(ac_owner), "ac_active": len(active_ac), "ac_deferred": len(scope["AC_deferred"]),
                          "screens_owned": len(scr_owner), "screens_required": len(scope["SCR_required"])}}
    return {"ok": not E, "errors": E, "warnings": W, "derived": derived}


# ---------------------------------------------------------------- 렌더링
def render_md(plan: dict, v: dict, model: dict, revision: int, baseline: dict, waivers: list[dict], profile: dict) -> str:
    d = v["derived"]
    c = d["counts"]
    L = [f"---\ndoc: implementation-plan\nrevision: {revision}\nlanguage: ko\nbased_on:\n"
         f"  planning_revision: {baseline['planning'].get('planning_revision')}\n"
         f"  ux_spec_revision: {baseline['design']['basis'].get('ux_spec_revision')}\n"
         f"  design_direction_revision: {baseline['design']['basis'].get('design_direction_revision')}\n"
         f"  design_level: {d['design_level']}\n---\n", GENERATED_MARK, "",
         f"# 구현 계획 (Implementation Plan) r{revision}", "",
         "## 1. 요약", "",
         f"- 범위: 우선순위 {'/'.join(d['scope_detail']['priorities'])} — US {len(d['scope_detail']['US'])}개, "
         f"AC {c['ac_active']}개 배정 대상(미룸 {c['ac_deferred']}개), 화면 {c['screens_required']}개 필수",
         f"- 배치 {c['batches']}개: 자동 진행 {c['auto']}개 · 사용자 승인 필요 {c['user']}개",
         f"- 구현 순서 전략: {plan.get('order_strategy') or profile['project'].get('order_strategy')}",
         f"- 디자인 준비 수준: {d['design_level']}", ""]
    act = [w for w in waivers if w.get("status") == "active"]
    if act:
        L += ["## 2. 프리뷰 승인 예외(preview waiver)", "", "| ID | 범위 | 사유 | 기준 | 승인 |", "|---|---|---|---|---|"]
        for w in act:
            scope = "모든 화면 배치" if w["scope"].get("all_ui") else ", ".join(w["scope"].get("batches", []))
            L.append(f"| {w['id']} | {scope} | {w['reason']} | ux_spec r{w['basis'].get('ux_spec_revision')}, DD r{w['basis'].get('design_direction_revision')} | {w['approved_at']} |")
        L += ["", "예외가 적용된 배치의 시각 확인은 배치 검증(브라우저 검사·사람 확인)에서 합니다. design.json의 프리뷰 상태는 바꾸지 않습니다.", ""]
    L += ["## 3. 배치 목록(실행 순서)", "", "| 배치 | 제목 | 종류 | 화면 | AC | 의존 | 승인 | 디자인 기준 |", "|---|---|---|---|---|---|---|---|"]
    for b in plan["batches"]:
        x = d["batches"][b["id"]]
        L.append(f"| {b['id']} | {b['title']} | {b['kind']} | {len(b.get('screens') or [])} | {len(b.get('acs') or [])} | "
                 f"{', '.join(b.get('depends_on') or []) or '-'} | {'사용자' if x['approval'] == 'user' else '자동'} | {x['design_path']} |")
    L += ["", "## 4. 배치 상세", ""]
    for b in plan["batches"]:
        x = d["batches"][b["id"]]
        L += [f"### {b['id']}: {b['title']}", "", f"- **목표**: {b.get('goal') or '-'}",
              f"- **화면**: {', '.join(b.get('screens') or []) or '없음'}" + (f" (함께 수정: {', '.join(b['touches'])})" if b.get("touches") else ""),
              f"- **스토리**: {', '.join(b.get('stories') or []) or '-'}",
              f"- **컴포넌트**: 재사용 {', '.join((b.get('components') or {}).get('reuse') or []) or '-'} / 신규 {', '.join((b.get('components') or {}).get('new') or []) or '-'}",
              f"- **의존**: {', '.join(b.get('depends_on') or []) or '없음'}",
              f"- **수정 범위**: {', '.join((b.get('paths') or {}).get('allow') or []) or '미지정'}"
              + (f" / 공유 허용: {', '.join((b.get('paths') or {}).get('shared') or [])}" if (b.get('paths') or {}).get('shared') else ""),
              f"- **승인**: {'사용자 승인 필요 — ' + '; '.join(x['approval_reasons']) if x['approval'] == 'user' else '자동 진행(검증 통과 시 다음 배치)'}"]
        if x["risk_tags_detected"]:
            L.append("- **감지된 위험**: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in x["risk_tags_detected"].items()))
        L += ["", "| 작업 | 계층 | 내용 | 참조 | 선행 |", "|---|---|---|---|---|"]
        for t in b.get("tasks") or []:
            L.append(f"| {t['id']} | {t['layer']} | {t['title']} | {', '.join(t.get('refs') or [])} | {', '.join(t.get('depends_on') or []) or '-'} |")
        if b.get("acs"):
            L += ["", "| AC | 제목 | 목표 증거 |", "|---|---|---|"]
            for a in b["acs"]:
                L.append(f"| {a} | {model['AC'].get(a, {}).get('title', '')} | {x['ac_targets'].get(a, '-')} |")
        if b.get("done_criteria"):
            L += ["", "완료 기준:"] + [f"- {dc}" for dc in b["done_criteria"]]
        L.append("")
    if plan.get("deferred"):
        L += ["## 5. 미룬 항목", "", "| ID | 사유 |", "|---|---|"] + [f"| {x['id']} | {x['reason']} |" for x in plan["deferred"]] + [""]
    L += ["## 6. 증거 수준 기준", "",
          "- E1(언급): 테스트·코드에 ID가 나옴 — 검증으로 세지 않음",
          "- E2(연결·실행): 구조화된 태그가 있는 테스트가 증거 실행 리포트에서 통과",
          "- E3(검증): E2 + Then 항목별 assertion 대응 + 구현 전 실패→구현 후 통과 기록",
          "- EM(수동): 자동화할 수 없는 이유 + 근거(스크린샷 등) + 사람 확인",
          f"- 이 계획의 기준: Must {profile['evidence']['must']}, Should {profile['evidence']['should']}, 보안·권한·데이터 손실 {profile['evidence']['risk']}", ""]
    return "\n".join(L)
