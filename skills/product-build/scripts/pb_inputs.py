"""/product-build 입력 모델: 승인된 기획(FR·US·AC)과 UX Spec(SCR·CMP·AC→화면)을 읽어 구현 범위를 계산합니다.

도메인 지식은 없습니다. ID 형식과 엔진 템플릿의 표·헤딩 규칙만 씁니다.
"""
from __future__ import annotations

import re
from pathlib import Path

from pb_core import (
    IA_FILE, PLANNING_FILES, SCREENS_FILE, TRACE_FILE, UISYS_FILE,
    blocks_by_heading, field_line, planning_ids, read_text, screen_info, strip_comments, strip_fences, table_rows,
)

PRIORITIES = ("Must", "Should", "Could")
RANK = {"Must": 0, "Should": 1, "Could": 2, None: 3}


def _header_index(text: str, first_col_re: str, names: tuple[str, ...]) -> int | None:
    """첫 열이 ID인 표의 머리 행에서 원하는 열(이름 일부 일치)의 위치(ID 열 다음부터 0)를 찾습니다."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not re.match(rf"^\|\s*{first_col_re}\s*\|", line):
            continue
        for j in range(i - 1, -1, -1):  # 위로 올라가 구분선 위의 머리 행
            if re.match(r"^\|\s*:?-{2,}", lines[j]):
                continue
            if lines[j].startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                for k, c in enumerate(cells[1:]):
                    if any(n in c for n in names):
                        return k
            break
        break
    return None


def deleted_ids(texts: list[str]) -> set[str]:
    """취소선 헤딩·행(~~US-017~~ 등)으로 폐기 표시된 ID."""
    out = set()
    for t in texts:
        for m in re.finditer(r"^#{2,3} ~~((?:US|AC|FR|SCR|CMP)-\d{3})~~", t, re.M):
            out.add(m.group(1))
        for m in re.finditer(r"^\|\s*~~((?:FR|US|AC)-\d{3})~~", t, re.M):
            out.add(m.group(1))
    return out


def load_model(project: Path) -> dict:
    prd = strip_comments(read_text(project, PLANNING_FILES[0]))
    us_doc = strip_comments(read_text(project, PLANNING_FILES[1]))
    ac_doc = strip_comments(read_text(project, PLANNING_FILES[3]))
    pid = planning_ids(project)
    deleted = deleted_ids([prd, us_doc, ac_doc])

    fr_rows = table_rows(prd, r"FR-\d{3}")
    pi_ = _header_index(prd, r"FR-\d{3}", ("우선순위", "Priority", "priority"))
    frs = {}
    for k, cells in fr_rows.items():
        prio = None
        if pi_ is not None and pi_ < len(cells):
            m = re.search(r"\b(Must|Should|Could)\b", cells[pi_])
            prio = m.group(1) if m else None
        if prio is None:
            m = re.search(r"\b(Must|Should|Could)\b", " ".join(cells))
            prio = m.group(1) if m else None
        frs[k] = {"priority": prio, "text": cells[0] if cells else ""}

    us_blocks = blocks_by_heading(us_doc, 3, "US")
    stories = {}
    for k, b in us_blocks.items():
        title = re.sub(r"^###\s+US-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip()
        stories[k] = {"priority": pid["US_priority"].get(k), "title": title,
                      "frs": sorted(set(re.findall(r"FR-\d{3}", field_line(b, "추적 대상")))), "text": b}

    ac_blocks = blocks_by_heading(ac_doc, 3, "AC")
    # AC가 속한 '## US-xxx' 섹션(추적 대상 줄이 없을 때의 대체)
    section_of = {}
    cur = None
    for line in ac_doc.splitlines():
        m = re.match(r"^## (US-\d{3})\b", line)
        if m:
            cur = m.group(1)
        elif re.match(r"^## ", line):
            cur = None
        m2 = re.match(r"^### (AC-\d{3})\b", line)
        if m2:
            section_of[m2.group(1)] = cur
    acs = {}
    for k, b in ac_blocks.items():
        title = re.sub(r"^###\s+AC-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip()
        trace = field_line(b, "추적 대상")
        us = [u for u in re.findall(r"US-\d{3}", trace) if u in stories]
        if not us and section_of.get(k) in stories:
            us = [section_of[k]]
        prio = min((stories[u]["priority"] for u in us), key=lambda p: RANK[p], default=None)
        acs[k] = {"title": title, "us": us, "frs": sorted(set(re.findall(r"FR-\d{3}", trace))), "priority": prio, "text": b}

    # ---- 디자인(있을 때만)
    screens, cmps, ac_screens, ac_nonui, us_screens = {}, {}, {}, {}, {}
    if (project / SCREENS_FILE).exists():
        ia = strip_fences(read_text(project, IA_FILE))
        ia_rows = table_rows(ia, r"SCR-\d{3}")
        path_i = _header_index(ia, r"SCR-\d{3}", ("경로", "Path", "path", "Route", "route"))
        shell_i = _header_index(ia, r"SCR-\d{3}", ("셸", "Shell", "shell", "영역", "Area", "area"))
        name_i = _header_index(ia, r"SCR-\d{3}", ("이름", "Name", "name"))
        for k, i in screen_info(project).items():
            row = ia_rows.get(k, [])
            route_text = field_line(i["block"], "경로") or (row[path_i] if path_i is not None and path_i < len(row) else "")
            title = re.sub(r"^##\s+SCR-\d{3}\s*:?\s*", "", i["block"].splitlines()[0]).strip()
            screens[k] = {"name": title or (row[name_i] if name_i is not None and name_i < len(row) else ""),
                          "route_text": route_text, "routes": parse_routes(route_text),
                          "overlay": bool(re.search(r"\((?:[^)]*시트|[^)]*패널|[^)]*sheet|[^)]*modal|[^)]*dialog)", route_text, re.I)),
                          "shell": row[shell_i] if shell_i is not None and shell_i < len(row) else "",
                          "platform": i["platform"], "role": field_line(i["block"], "역할"),
                          "trace": sorted(i["trace"]), "cmp": sorted(i["cmp"]), "states": sorted(i["states"])}
        uisys = strip_fences(read_text(project, UISYS_FILE))
        for k, b in blocks_by_heading(uisys, 3, "CMP").items():
            cmps[k] = re.sub(r"^###\s+CMP-\d{3}\s*:?\s*", "", b.splitlines()[0]).strip()
        trace_doc = strip_fences(read_text(project, TRACE_FILE))
        for a, cells in table_rows(trace_doc, r"AC-\d{3}").items():
            cell = " | ".join(cells)
            refs = {r.split("-ST")[0] for r in re.findall(r"SCR-\d{3}(?:-ST\d+)?", cells[0] if cells else "")}
            if refs:
                ac_screens[a] = sorted(refs)
            elif "비UI" in cell:
                m = re.search(r"비UI\s*:\s*([^|]+)", cell)
                ac_nonui[a] = (m.group(1).strip() if m else "")
        for u, cells in table_rows(trace_doc, r"US-\d{3}").items():
            refs = sorted({r.split("-ST")[0] for r in re.findall(r"SCR-\d{3}(?:-ST\d+)?", " ".join(cells))})
            us_screens[u] = refs
    return {"FR": frs, "US": stories, "AC": acs, "SCR": screens, "CMP": cmps, "deleted": sorted(deleted),
            "ac_screens": ac_screens, "ac_nonui": ac_nonui, "us_screens": us_screens, "has_design": bool(screens)}


def parse_routes(text: str) -> list[str]:
    """'/admin/users, /admin/orders (시트)' → ['/admin/users', '/admin/orders']. 와일드카드·설명은 버립니다."""
    out = []
    for part in re.split(r"[,、]", re.sub(r"\([^)]*\)", "", text or "")):
        p = part.strip().strip("`").split()[0] if part.strip() else ""
        if p.startswith("/") and p not in ("/*", "*") and "*" not in p:
            out.append(p)
    return out


def known_ids(model: dict) -> set[str]:
    return set(model["FR"]) | set(model["US"]) | set(model["AC"]) | set(model["SCR"]) | set(model["CMP"])


def compute_scope(model: dict, priorities: list[str], include: list[str] | None = None, deferred: list[dict] | None = None) -> dict:
    """구현 범위. 기본은 Must US의 AC. include로 Should/Could US(또는 AC)를 더하고, deferred(사유 포함)는 범위 안에서 미룹니다."""
    include = set(include or [])
    deferred_ids = {d.get("id") for d in (deferred or []) if isinstance(d, dict)}
    us_in = {u for u, s in model["US"].items() if s["priority"] in priorities or u in include}
    ac_in = {a for a, s in model["AC"].items() if any(u in us_in for u in s["us"]) or a in include}
    deferred_us = {d for d in deferred_ids if d in model["US"]}
    for a, s in model["AC"].items():  # 미룬 US에만 속한 AC는 함께 미룸
        if s["us"] and all(u in deferred_us for u in s["us"]):
            deferred_ids.add(a)
    ac_active = ac_in - deferred_ids
    scr_required = set()
    for a in ac_active:
        scr_required |= set(model["ac_screens"].get(a, []))
    scr_required -= deferred_ids
    scr_related = set()
    for s, i in model["SCR"].items():
        if any(u in us_in for u in i["trace"]):
            scr_related.add(s)
    return {"priorities": list(priorities), "US": sorted(us_in), "AC": sorted(ac_in), "AC_active": sorted(ac_active),
            "AC_deferred": sorted(ac_in & deferred_ids), "SCR_required": sorted(scr_required),
            "SCR_related_optional": sorted(scr_related - scr_required - deferred_ids),
            "SCR_outside": sorted(set(model["SCR"]) - scr_required - scr_related),  # 범위 AC·US와 연결되지 않은 화면(예: 공통 오류 화면)
            "AC_non_ui": sorted(a for a in ac_active if a in model["ac_nonui"]),
            "AC_unmapped": sorted(a for a in ac_active if a not in model["ac_screens"] and a not in model["ac_nonui"]),
            "out_of_scope_US": sorted(set(model["US"]) - us_in)}
