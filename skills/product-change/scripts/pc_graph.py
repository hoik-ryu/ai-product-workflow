"""/product-change P1: ID 단위 변경 영향 그래프(읽기 전용).

기획(FR·NFR·US·FLOW·AC·C) → 디자인(UXD·SCR·SCR 상태·CMP·VD·토큰·AST) → 프리뷰(화면 파일·상태·공용 파일) → 구현(배치·테스트·코드)
참조 관계로 바뀐 ID의 영향을 계산합니다.

- 직접 영향(direct): 바뀐 ID를 그 블록·행·파일이 직접 적음
- 간접 영향(indirect): 직접 영향 노드를 다시 참조함(예: AC → SCR 상태 → SCR → VD → 프리뷰 화면 파일·공용 컴포넌트 → 배치 → 테스트)
- **직접 참조가 없다고 영향이 없는 것이 아닙니다.** 간접 경로로 닿으면 영향이고, 경로(`path`)를 함께 남깁니다.
- 판정할 수 없거나(기준 내용 불명·참조 해석 불가·공용 노드) 의미 영향을 기계적으로 증명할 수 없으면 범위를 넓히고 사유(`widened`)를 남깁니다.
- 바뀐 뒤에도 남은 폐기 ID 참조는 이력 참조(취소선·폐기 표기)와 유효 참조(정리 필요)로 나눕니다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ENGINE_SKILLS = Path(__file__).resolve().parent.parent.parent
import sys  # noqa: E402
for _p in (ENGINE_SKILLS / "product-design" / "scripts",):
    if str(_p) not in sys.path:
        sys.path.insert(1, str(_p))

from pd_core import (  # noqa: E402
    DD_FILE, FLOWS_FILE, IA_FILE, PLANNING_FILES, PREVIEW_MANIFEST, REVIEW_FILE, SCREENS_FILE, TRACE_FILE, UISYS_FILE, UXP_FILE,
    blocks_by_heading, field_line, read_text, sha256_bytes, sha256_file, strip_comments, strip_fences, table_rows,
)

ID_RE = re.compile(r"\b(?:FR|NFR|US|AC|UXD|SCR|CMP|VD|AST)-\d{3}(?:-ST\d+)?\b|\bFLOW-\d{3}(?:-S\d+[a-z]?)?\b|\bC-\d{2}\b")
PLANNING_KINDS = ("FR", "NFR", "US", "AC", "FLOW", "C")
DESIGN_DOCS = (UXP_FILE, IA_FILE, SCREENS_FILE, FLOWS_FILE, UISYS_FILE, TRACE_FILE, REVIEW_FILE, DD_FILE)
PLAN_JSON = "docs/build/implementation-plan.json"
HISTORY_HINT = re.compile(r"폐기|삭제됨|제거됨|철회|removed|deprecated|retired|\(r\d+에서 폐기\)", re.I)
HISTORY_SECTION = re.compile(r"^#{1,6} .*(이력|변경 기록|변경 이력|history|changelog)", re.I | re.M)


def kind_of(i: str) -> str:
    return i.split("-")[0] if not i.startswith("FLOW") else "FLOW"


def norm(i: str) -> str:
    """SCR-001-ST3 → SCR-001(화면), FLOW-001-S1a는 그대로(단계 ID)."""
    return i.split("-ST")[0] if i.startswith("SCR-") else i


# ================================================================ 기획 ID 차이
def planning_blocks(text: str) -> dict[str, dict]:
    """{ID: {"text", "struck"}} — 헤딩 블록(US·AC·FLOW)과 표 행(FR·NFR·C·FLOW 단계)·목록 단계."""
    out: dict[str, dict] = {}
    t = strip_comments(text)
    for m in re.finditer(r"^(#{2,3}) (~~)?((?:US|AC|FLOW)-\d{3})(~~)?\b.*$", t, re.M):
        end = re.compile(rf"^#{{1,{len(m.group(1))}}} ", re.M).search(t, m.end())
        body = t[m.start(): end.start() if end else len(t)]
        out[m.group(3)] = {"text": body, "struck": bool(m.group(2)) or bool(HISTORY_HINT.search(body.splitlines()[0]))}  # 그 블록 제목 줄만 봄
    for line in t.splitlines():
        m = re.match(r"^\s*(?:\|\s*|-\s*)(~~)?((?:FR|NFR)-\d{3}|C-\d{2}|FLOW-\d{3}-S\d+[a-z]?)(~~)?\b(.*)$", line)
        if m and m.group(2) not in out:
            rest = (m.group(4) or "").lstrip(" |:")
            head = re.split(r"\s\|\s|<br>", rest, maxsplit=1)[0][:80]  # 행 전체가 아닌 첫 칸(이름·제목)만: 긴 본문 속 '폐기' 언급은 폐기 표기가 아님
            out[m.group(2)] = {"text": line, "struck": bool(m.group(1)) or bool(HISTORY_HINT.search(head))}
    return out


def planning_diff(old_texts: dict[str, str] | None, new_texts: dict[str, str]) -> dict:
    """기획 문서의 ID 단위 차이: added / modified / removed(사라짐·취소선·폐기 표기). 이전 내용을 모르면 known False."""
    if old_texts is None:
        return {"known": False, "added": [], "modified": [], "removed": [], "reason": "이전 승인 기획 내용을 확인할 수 없습니다"}
    ob: dict[str, dict] = {}
    nb: dict[str, dict] = {}
    for f in PLANNING_FILES:
        ob.update(planning_blocks(old_texts.get(f, "")))
        nb.update(planning_blocks(new_texts.get(f, "")))
    active_old = {k for k, v in ob.items() if not v["struck"]}
    active_new = {k for k, v in nb.items() if not v["struck"]}
    removed = sorted(active_old - active_new)
    added = sorted(active_new - active_old)
    tracked = set(ob) | set(nb)

    def own(text: str, key: str) -> str:
        """블록 비교용 본문: 따로 추적하는 하위 ID 행(예: FLOW-001 안의 FLOW-001-S1a 행)은 그 ID의 변경으로 셉니다."""
        keep = [ln for ln in text.splitlines()
                if not ((m := re.match(r"^\s*(?:\|\s*|-\s*)(?:~~)?((?:FR|NFR)-\d{3}|C-\d{2}|FLOW-\d{3}-S\d+[a-z]?)", ln)) and m.group(1) in tracked and m.group(1) != key)]
        return re.sub(r"\s+", " ", "\n".join(keep))
    modified = sorted(k for k in active_old & active_new if own(ob[k]["text"], k) != own(nb[k]["text"], k))
    return {"known": True, "added": added, "modified": modified, "removed": removed}


# ================================================================ 그래프
class Graph:
    def __init__(self):
        self.mentions: dict[str, set[str]] = {}   # 노드 → 그 노드가 적은 ID
        self.loc: dict[str, str] = {}             # 노드 → 위치(파일#블록)
        self.kind: dict[str, str] = {}            # 노드 → 종류(design_block·trace_row·flow_row·preview_file·batch·test·code)
        self.stage: dict[str, str | None] = {}    # 노드 → 디자인 단계

    def add(self, node: str, ids, loc: str, kind: str, stage: str | None = None):
        self.mentions.setdefault(node, set()).update(ids)
        self.loc[node], self.kind[node], self.stage[node] = loc, kind, stage


def _ids(text: str) -> set[str]:
    return set(ID_RE.findall(text or ""))


def _active_text(text: str) -> str:
    """이력 참조(취소선 구간, 폐기 표기 줄, 이력 절)를 뺀 본문."""
    t = re.sub(r"~~[^~\n]*~~", "", text)
    lines, in_hist = [], False
    for ln in t.splitlines():
        if re.match(r"^#{1,6} ", ln):
            in_hist = bool(HISTORY_SECTION.match(ln))
        if in_hist or HISTORY_HINT.search(ln):
            continue
        lines.append(ln)
    return "\n".join(lines)


def build_graph(project: Path) -> tuple[Graph, list[str]]:
    g = Graph()
    widened: list[str] = []
    stage_of_doc = {UXP_FILE: "ux_planning", IA_FILE: "ux_spec", SCREENS_FILE: "ux_spec", FLOWS_FILE: "ux_spec", UISYS_FILE: "ux_spec",
                    TRACE_FILE: "ux_spec", REVIEW_FILE: "preview", DD_FILE: "design_direction"}
    for rel in DESIGN_DOCS:
        text = strip_fences(strip_comments(read_text(project, rel)))
        if not text:
            continue
        st = stage_of_doc[rel]
        blocks = {}
        for prefix, level in (("UXD", 3), ("SCR", 2), ("CMP", 3), ("VD", 3)):
            blocks.update(blocks_by_heading(text, level, prefix))
        for bid, body in blocks.items():
            g.add(bid, _ids(_active_text(body)) - {bid}, f"{rel}#{bid}", "design_block", st)
        for line in text.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            first = (re.match(r"^\|\s*([^|]+?)\s*\|", line) or [None, ""])[1]
            ids = _ids(_active_text(line))
            if not ids:
                continue
            head = next(iter(_ids(first)), None)
            node = f"{rel}:{head or first[:30]}:{abs(hash(line)) % 10**8}"
            # 표 행은 행 첫 칸 ID의 블록에 속하지 않으면 독립 노드(추적·흐름 행)
            g.add(node, ids, f"{rel}#{head or first[:30]}", "trace_row" if rel in (TRACE_FILE, FLOWS_FILE) else "table_row", st)
        tok = re.findall(r"^\|\s*`?([a-z][A-Za-z]*(?:\.[A-Za-z0-9]+)+)`?\s*\|", text, re.M)
        for t_ in tok:
            g.add(f"TOKEN:{t_}", set(), f"{rel}#{t_}", "token", st)
    # 07 VD 관련(SCR·CMP·AST) — 블록 노드에 이미 포함. 프리뷰 manifest·파일
    try:
        man = json.loads(read_text(project, PREVIEW_MANIFEST) or "{}")
    except json.JSONDecodeError:
        man = {}
        widened.append("프리뷰 manifest를 해석할 수 없어 프리뷰 전체를 영향 범위로 봅니다")
    try:
        import pd_change as CH
        closures = CH.preview_screen_closures(project)
    except Exception:  # noqa: BLE001
        closures = {}
        widened.append("프리뷰 import 관계를 계산하지 못했습니다")
    all_pv_files = set()
    for sid, m in (man.get("screens") or {}).items():
        if not isinstance(m, dict) or m.get("skip"):
            continue
        files = closures.get(sid) or ({f"design-preview/{m['file']}"} if m.get("file") else set())
        for f in files:
            all_pv_files.add(f)
            g.add(f"preview:{f}", set(), f, "preview_file", "preview")
            g.mentions[f"preview:{f}"].add(sid)
        g.add(f"preview-manifest:{sid}", {sid} | set(m.get("states") or []) | set(m.get("vd") or []), f"{PREVIEW_MANIFEST}#{sid}", "preview_manifest", "preview")
    users: dict[str, set[str]] = {}
    for sid, files in closures.items():
        for f in files:
            users.setdefault(f, set()).add(sid)
    g.shared_preview = {f for f, u in users.items() if len(u) > 1}
    # 구현 계획·테스트·코드
    plan = {}
    try:
        plan = json.loads(read_text(project, PLAN_JSON) or "{}")
    except json.JSONDecodeError:
        widened.append("구현 계획 JSON을 해석할 수 없어 모든 배치를 영향 범위로 봅니다")
    for b in plan.get("batches") or []:
        if isinstance(b, dict) and b.get("id"):
            g.add(f"batch:{b['id']}", set(b.get("acs") or []) | set(b.get("screens") or []), f"{PLAN_JSON}#{b['id']}", "batch", None)
            g.batch_paths = getattr(g, "batch_paths", {})
            g.batch_paths[b["id"]] = list((b.get("paths") or {}).get("allow") or []) + list((b.get("paths") or {}).get("shared") or [])
    return g, widened


def tracked_mentions(project: Path, ids: set[str]) -> dict[str, list[str]]:
    """저장소 추적 파일 중 바뀐 ID를 직접 적은 파일(문서·코드·테스트) → {파일: [ID...]}. 이력 표기(취소선)는 제외하지 않고 따로 셈."""
    if not ids:
        return {}
    args = ["git", "grep", "-l", "-w", "-F"]
    for i in sorted(ids):
        args += ["-e", i]
    p = subprocess.run(args + ["--", "."], cwd=project, capture_output=True, text=True)
    out = {}
    for rel in p.stdout.splitlines():
        if rel.startswith((".ai-workflow/", "docs/planning/", "docs/changes/")):
            continue
        try:
            text = (project / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hit = sorted(i for i in ids if re.search(re.escape(i) + r"\b", text))
        if hit:
            out[rel] = hit
    # 작업 트리에만 있는(미추적) 파일도 확인
    q = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=project, capture_output=True, text=True)
    for rel in q.stdout.splitlines():
        if rel.startswith((".ai-workflow/", "docs/planning/", "docs/changes/")) or not (project / rel).is_file():
            continue
        try:
            text = (project / rel).read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        hit = sorted(i for i in ids if re.search(re.escape(i) + r"\b", text))
        if hit:
            out[rel] = hit
    return out


def impact(project: Path, changed: dict) -> dict:
    """changed = {"added": [...], "modified": [...], "removed": [...], "known": bool}. 직접·간접 영향과 승계 가능 단계."""
    g, widened = build_graph(project)
    seeds = set(changed.get("modified") or []) | set(changed.get("removed") or [])
    added = set(changed.get("added") or [])
    tokens = bool(changed.get("tokens"))
    if not changed.get("known", True):
        widened.append(changed.get("reason") or "바뀐 ID를 확정할 수 없습니다")
    if tokens:
        widened.append("디자인 토큰·테마(전역 계약) 변경: 모든 화면과 프리뷰를 영향 범위로 봅니다")
    if added:
        widened.append(f"추가 ID({', '.join(sorted(added))})는 아직 참조가 없어 영향 화면을 기계적으로 정할 수 없습니다. 계약에 화면·디자인 단위를 명시해야 합니다")
    items: dict[str, dict] = {}

    def hit(node: str, level: str, path: list[str], why: str):
        cur = items.get(node)
        if cur and (cur["level"] == "direct" or level == "indirect"):
            return False
        items[node] = {"node": node, "loc": g.loc.get(node, node), "kind": g.kind.get(node), "stage": g.stage.get(node),
                       "level": level, "path": path, "why": why}
        return True

    # 1) 직접: 바뀐 ID를 적은 노드
    for node, ids in g.mentions.items():
        s = {norm(i) for i in ids} | ids
        inter = sorted(seeds & s)
        if inter:
            hit(node, "direct", [inter[0], g.loc[node]], f"{', '.join(inter)}을(를) 직접 참조")
    # 2) 간접: 직접 영향 노드가 가리키는 화면·상태(SCR) → 그 화면을 참조하는 노드(SCR 블록·VD·프리뷰·배치), VD → 자산·화면
    frontier = list(items)
    screens: dict[str, list[str]] = {}
    for node in list(items):
        if node.startswith("SCR-") and g.kind.get(node) == "design_block":
            screens.setdefault(node, items[node]["path"] + [node])  # 화면 블록은 그 화면 자체(블록 안 다른 화면 링크는 씨앗이 아님)
            continue
        for i in g.mentions.get(node, set()):
            if i.startswith("SCR-"):  # 추적·흐름 행, UXD·VD·CMP 블록, 배치: 그 대응 화면이 영향
                screens.setdefault(norm(i), items[node]["path"] + [i])
    review_only: set[str] = set()
    # 바뀐 ID 블록이 디자인에서 화면을 직접 정하지 않으면 상위(US) 경유로 확대
    for s in sorted(seeds):
        if s.startswith("AC-") and not any(s in g.mentions.get(n, set()) for n in g.mentions):
            widened.append(f"{s}: 디자인·계획 어디에도 참조가 없습니다. 같은 US의 화면으로 영향 범위를 넓힙니다(의미 영향 미증명)")
    seen_scr = set()
    while screens:
        sid, path = screens.popitem()
        if sid in seen_scr:
            continue
        seen_scr.add(sid)
        for node, ids in g.mentions.items():
            if node in items and items[node]["level"] == "direct":
                continue
            s_ids = {norm(i) for i in ids}
            if sid in s_ids or node == sid:
                if hit(node, "indirect", path + [g.loc.get(node, node)], f"영향 화면 {sid}을(를) 참조"):
                    frontier.append(node)
                # VD가 다른 화면에도 적용되면 그 화면은 '검토' 범위(한 단계만, 연쇄 확대하지 않음)
                if g.kind.get(node) == "design_block" and node.startswith("VD-") and sid not in review_only:
                    others = sorted(o for o in s_ids if o.startswith("SCR-") and o != sid and o not in seen_scr)
                    for other in others:
                        review_only.add(other)
                        if other not in items:
                            hit(other, "indirect", path + [node, other], f"공용 시각 결정 {node}가 {other}에도 적용(검토 범위)")
                    if others:
                        widened.append(f"{node}가 {sid} 외 {', '.join(others)}에도 적용됩니다: 그 화면을 검토 범위에 넣습니다(연쇄 확대 없음)")
    # 3) 프리뷰 공용 파일: 영향 화면 파일이 공용 파일을 쓰면 그 공용 파일·다른 사용 화면도 검토
    for node in list(items):
        if g.kind.get(node) == "preview_file" and node[len("preview:"):] in getattr(g, "shared_preview", set()):
            items[node]["why"] += " · 여러 화면이 함께 쓰는 공용 파일(다른 화면 회귀 검토 필요)"
    # 4) 코드·테스트의 직접 언급
    mentions = tracked_mentions(project, seeds)
    code, notes = {}, {}
    for rel, ids in mentions.items():
        if rel in DESIGN_DOCS or rel.startswith(("design-preview/", "docs/build/")):  # 구현 계획 문서는 snapshot-plan이 다룸
            continue
        if rel.startswith("docs/") and rel.endswith(".md"):  # 메모·제안 문서: 제품 코드가 아님(참고로만 보고, 계약 공백으로 세지 않음)
            notes[rel] = ids
            continue
        code[rel] = ids
    # 5) 폐기 ID의 남은 참조(이력 vs 유효)
    dangling, historical = [], []
    removed = set(changed.get("removed") or [])
    for rel in DESIGN_DOCS:
        raw = read_text(project, rel)
        if not raw:
            continue
        for n, line in enumerate(strip_comments(raw).splitlines(), 1):
            ids = set(ID_RE.findall(line)) & removed
            if not ids:
                continue
            act = set(ID_RE.findall(_active_text(line))) & removed
            (dangling if act else historical).append({"file": rel, "line": n, "ids": sorted(ids), "text": line.strip()[:160]})
    if tokens:  # 전역 계약: 모든 화면·프리뷰 파일·배치
        for node, k in g.kind.items():
            if k in ("design_block", "preview_file", "preview_manifest", "batch", "token") and node not in items:
                hit(node, "indirect", ["tokens", g.loc.get(node, node)], "전역 디자인 토큰 변경")
        seen_scr |= {n for n in g.mentions if n.startswith("SCR-")}
    stages = {}
    for it in items.values():
        if it["stage"]:
            stages.setdefault(it["stage"], []).append(it["loc"])
    all_stages = ("ux_planning", "ux_spec", "design_direction", "preview")
    affected_screens = sorted(seen_scr)
    review_screens = sorted(review_only - seen_scr)
    batches = sorted(n[len("batch:"):] for n in items if n.startswith("batch:"))
    preview_files = sorted(n[len("preview:"):] for n in items if n.startswith("preview:"))
    design_units = sorted({it["loc"].split("#", 1)[-1] for it in items.values() if it["kind"] == "design_block"})
    if widened and not changed.get("known", True):
        stages = {s: ["(범위 확대: 기준 불명)"] for s in all_stages}
    return {"seeds": sorted(seeds), "added": sorted(added), "removed": sorted(removed),
            "items": sorted(items.values(), key=lambda x: (x["level"] != "direct", x["loc"])),
            "direct": sorted({it["loc"] for it in items.values() if it["level"] == "direct"}),
            "indirect": sorted({it["loc"] for it in items.values() if it["level"] == "indirect"}),
            "screens": affected_screens, "review_screens": review_screens, "design_units": design_units, "preview_files": preview_files,
            "stages_affected": sorted(stages), "stages_inherited": [s for s in all_stages if s not in stages],
            "batches": batches, "code_mentions": code, "doc_mentions": notes, "dangling_refs": dangling, "historical_refs": historical,
            "widened": widened, "digest": sha256_bytes(json.dumps([sorted(items), affected_screens, batches, sorted(code)], ensure_ascii=False).encode())}


def planning_bytes_at(project: Path, rev: str) -> dict[str, bytes] | None:
    out = {}
    for f in PLANNING_FILES:
        p = subprocess.run(["git", "show", f"{rev}:{f}"], cwd=project, capture_output=True)
        if p.returncode != 0:
            return None
        out[f] = p.stdout
    return out


def approved_planning_texts(project: Path, approved_hashes: dict) -> dict[str, str] | None:
    """승인 해시와 바이트가 같은 기획 문서를 작업 트리 → HEAD부터 거슬러 찾습니다(최대 200개 커밋). 없으면 None(보수적 확대)."""
    cur = {f: (project / f).read_bytes() for f in PLANNING_FILES if (project / f).is_file()}
    if len(cur) == len(PLANNING_FILES) and all(sha256_bytes(cur[f]) == approved_hashes.get(f) for f in PLANNING_FILES):
        return {f: b.decode("utf-8", "replace") for f, b in cur.items()}
    p = subprocess.run(["git", "rev-list", "--max-count=200", "HEAD"], cwd=project, capture_output=True, text=True)
    for rev in p.stdout.split():
        t = planning_bytes_at(project, rev)
        if t and all(sha256_bytes(t[f]) == approved_hashes.get(f) for f in PLANNING_FILES):
            return {f: b.decode("utf-8", "replace") for f, b in t.items()}
    return None


def current_planning_texts(project: Path) -> dict[str, str]:
    return {f: read_text(project, f) for f in PLANNING_FILES}


def frontmatter_revision(path: Path) -> str | None:
    from pd_core import front_matter_revision
    r = front_matter_revision(path.read_text(encoding="utf-8")) if path.is_file() else None
    return str(r) if r is not None else None


def file_hashes(project: Path, rels) -> dict[str, str | None]:
    return {r: (sha256_file(project / r) if (project / r).is_file() else None) for r in rels}
