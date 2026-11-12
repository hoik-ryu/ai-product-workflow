"""/product-build 정책·편차 원장(M2.4b): 정책 미결정·구현 편차·검증 증거 부족·목표 변경을 구분해 기록하고, 사용자 결정과 문서 반영 제안을 관리합니다.

- 원장은 `.ai-workflow/build/ledger.json`(state.yaml·build.json과 분리, Git 추적 대상)입니다. 사람용 보기는 `docs/build/10-decisions.md`(생성 문서).
- 항목 원문과 결정은 덮어쓰지 않습니다. 결정·변경은 decisions[]·history[]에 덧붙입니다.
- 차단(blocking) 정책은 policy·deviation만 가질 수 있습니다. evidence_gap은 검증 상태가 이미 진행을 막으므로 차단 정책으로 만들지 않습니다.
- 문서 반영: 승인된 원본 문서를 고치지 않고 변경 제안(proposed) → 사용자 승인(approved) → 소유 Skill이 개정·재승인한 것을 확인(applied)합니다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pb_core import BUILD_DIR_REL, block, digest, now, sha_file, write_owned

LEDGER_REL = f"{BUILD_DIR_REL}/ledger.json"
VIEW_REL = "docs/build/10-decisions.md"
TYPES = {"policy": "POL", "deviation": "DEV", "evidence_gap": "EVD", "target_change": "TGT"}
STATUSES = ("open", "decided", "closed", "dismissed")
DEV_CATEGORIES = ("①", "②", "③", "④", "⑤")
DOC_KINDS = {"docs/planning/": "planning", "docs/design/": "ux_spec", "docs/build/": "build_plan"}
TODO_POL = re.compile(r"TODO\(POL(?:-(\d{3}))?\)\s*:?\s*(.*)")


def empty() -> dict:
    return {"schema": "pb-ledger/v1", "items": [], "proposals": [], "history": []}


def load(project: Path) -> dict:
    p = project / LEDGER_REL
    if not p.exists():
        return empty()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        block("ledger_invalid", f"{LEDGER_REL}을 읽을 수 없습니다({e}). 자동으로 고치지 않습니다.")
    probs = problems(d)
    if probs:
        block("ledger_invalid", "원장 구조가 올바르지 않습니다(수동 편집 의심). 자동으로 고치지 않습니다.", problems=probs)
    return d


def problems(d) -> list[str]:
    out = []
    if not isinstance(d, dict) or d.get("schema") != "pb-ledger/v1":
        return ["schema가 pb-ledger/v1이 아닙니다"]
    ids = set()
    for it in d.get("items", []):
        if it.get("id") in ids:
            out.append(f"항목 ID 중복: {it.get('id')}")
        ids.add(it.get("id"))
        if it.get("type") not in TYPES or it.get("status") not in STATUSES:
            out.append(f"{it.get('id')}: 유형·상태가 올바르지 않습니다")
        if it.get("type") == "evidence_gap" and it.get("blocking"):
            out.append(f"{it.get('id')}: 검증 증거 부족(evidence_gap)은 차단 정책이 될 수 없습니다")
        if it.get("status") == "decided" and not any(x.get("statement") for x in it.get("decisions", [])):
            out.append(f"{it.get('id')}: decided인데 사용자 결정 문장이 있는 결정 기록이 없습니다")
        if it.get("digest") != digest(original(it)):
            out.append(f"{it.get('id')}: 원래 내용이 바뀌었습니다(원문은 수정하지 않고 이력으로 남겨야 함)")
    for pr in d.get("proposals", []):
        if pr.get("status") in ("approved", "applied") and not any(a.get("statement") for a in pr.get("approvals", [])):
            out.append(f"{pr.get('id')}: 승인 문장 없는 문서 변경 승인")
    return out


def original(it: dict) -> dict:
    return {k: it.get(k) for k in ("id", "type", "title", "description", "created_at", "source")}


def save(project: Path, d: dict) -> None:
    write_owned(project, LEDGER_REL, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    write_owned(project, VIEW_REL, render(d))


def next_id(d: dict, typ: str) -> str:
    pre = TYPES[typ]
    n = max([int(i["id"].split("-")[1]) for i in d["items"] if i["id"].startswith(pre + "-")] + [0]) + 1
    return f"{pre}-{n:03d}"


def add_item(d: dict, typ: str, title: str, desc: str, *, blocking: bool = False, batches=None, acs=None, docs=None, category=None,
             provisional=None, source=None, rationale="", classified_by="", status="open", decided=None) -> dict:
    if typ not in TYPES:
        block("invalid_type", f"유형은 {', '.join(TYPES)} 중 하나입니다.")
    if typ == "evidence_gap" and blocking:
        block("evidence_gap_not_policy", "검증 증거 부족(evidence_gap)은 정책 미결정이 아니므로 차단 정책으로 만들 수 없습니다(검증 상태가 이미 진행을 막음).")
    if typ == "deviation" and category not in (None, *DEV_CATEGORIES):
        block("invalid_category", "편차 분류는 ①–⑤ 중 하나입니다(WF-D01).")
    it = {"id": next_id(d, typ), "type": typ, "title": title.strip(), "description": desc.strip(), "created_at": now(), "source": source or {},
          "status": status, "blocking": bool(blocking), "category": category, "provisional": provisional,
          "related": {"batches": sorted(set(batches or [])), "acs": sorted(set(acs or [])), "docs": sorted(set(docs or []))},
          "rationale": rationale, "classified_by": classified_by, "decisions": [decided] if decided else [], "history": []}
    it["digest"] = digest(original(it))
    d["items"].append(it)
    d["history"].append({"at": now(), "event": "added", "id": it["id"], "note": title[:120]})
    return it


def find(d: dict, iid: str) -> dict:
    it = next((x for x in d["items"] if x["id"] == iid), None)
    if not it:
        block("unknown_item", f"원장에 {iid}가 없습니다.")
    return it


def affected_batches(it: dict, plan_batches: dict) -> list[str]:
    """항목이 영향을 주는 배치: 지정 배치 + 관련 AC를 가진 배치 + 관련 문서가 계획 문서면 전체."""
    out = set(it["related"]["batches"])
    acs = set(it["related"]["acs"])
    for bid, pb in plan_batches.items():
        if acs & set(pb.get("acs") or []):
            out.add(bid)
    return sorted(out)


def blocking_for(d: dict, bid: str, plan_batches: dict) -> list[dict]:
    return [it for it in d["items"] if it["blocking"] and it["status"] == "open" and bid in affected_batches(it, plan_batches)]


def doc_kind(path: str) -> str | None:
    return next((k for p, k in DOC_KINDS.items() if path.startswith(p)), None)


def add_proposal(d: dict, project: Path, item_id: str, doc: str, change: str, base: dict) -> dict:
    kind = doc_kind(doc)
    if kind is None:
        block("invalid_doc", f"문서 반영 대상은 기획(docs/planning/)·UX Spec(docs/design/)·구현 계획(docs/build/)입니다: {doc}")
    if not (project / doc).is_file():
        block("invalid_doc", f"{doc} 파일이 없습니다.")
    n = len(d["proposals"]) + 1
    pr = {"id": f"DOC-{n:03d}", "item": item_id, "doc": doc, "kind": kind, "change": change.strip(), "status": "proposed", "created_at": now(),
          "base": {"sha256": sha_file(project / doc), **base}, "approvals": [], "history": []}
    d["proposals"].append(pr)
    d["history"].append({"at": now(), "event": "proposal_added", "id": pr["id"], "note": f"{item_id} → {doc}"})
    return pr


def scan_todo_pol(project: Path, files: list[str]) -> list[dict]:
    out = []
    for f in files:
        try:
            lines = (project / f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            m = TODO_POL.search(line)
            if m:
                out.append({"file": f, "line": n, "ref": f"POL-{m.group(1)}" if m.group(1) else None, "text": m.group(2).strip()[:200]})
    return out


def render(d: dict) -> str:
    L = ["<!-- generated by /product-build: 직접 수정하지 마세요. 원장(.ai-workflow/build/ledger.json)의 보기입니다. -->", "",
         "# 정책·편차 원장", ""]
    label = {"policy": "정책 미결정", "deviation": "구현 편차", "evidence_gap": "검증 증거 부족", "target_change": "목표 변경·증거 기준 승인"}
    for typ, name in label.items():
        items = [i for i in d["items"] if i["type"] == typ]
        if not items:
            continue
        L += [f"## {name}", "", "| ID | 상태 | 차단 | 제목 | 관련 | 최근 결정 |", "|---|---|---|---|---|---|"]
        for i in items:
            last = i["decisions"][-1] if i["decisions"] else None
            rel = ", ".join(i["related"]["batches"] + i["related"]["acs"]) or "-"
            L.append(f"| {i['id']} | {i['status']} | {'예' if i['blocking'] else '-'} | {i['title']} | {rel} | "
                     f"{(last['decision'][:60] + ' (' + last['at'] + ')') if last else '-'} |")
        L.append("")
    if d["proposals"]:
        L += ["## 문서 반영 대기열", "", "| ID | 근거 | 문서 | 상태 | 변경 제안 |", "|---|---|---|---|---|"]
        for p in d["proposals"]:
            L.append(f"| {p['id']} | {p['item']} | {p['doc']} | {p['status']} | {p['change'][:80]} |")
        L.append("")
    return "\n".join(L)
