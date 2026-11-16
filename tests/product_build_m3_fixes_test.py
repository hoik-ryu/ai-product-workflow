#!/usr/bin/env python3
"""/product-build M3 실전 검증 결함 수정 회귀 테스트(P0-1 부품 표지, P0-2 프리뷰 언급, P2-1 init .gitignore).

검증 프로젝트와 무관한 독립 픽스처만 씁니다(임시 디렉터리). 실행: python3 tests/product_build_m3_fixes_test.py
CLI 수준 검사(ui-map check·ui-plan-validate·ui-guard·batch-start)는 product_build_ui_test.py B2b·B10b–c·B13b–e,
product_build_uiguard_test.py G16b에 있습니다.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_build_test as T  # noqa: E402

sys.path.insert(0, str(HERE.parent / "skills/product-build/scripts"))
import pb_exec  # noqa: E402
import pb_scan  # noqa: E402
import pb_ui  # noqa: E402

results = T.results
check, pb, G = T.check, T.pb, T.G

COMPS = {"CMP-021": {"source": "existing", "path": "src/components/Sheet.tsx", "export": "Sheet"},
         "CMP-045": {"source": "existing", "path": "src/components/RecordSummary.tsx", "export": "RecordSummary"}}
FILES = {
    "src/components/Sheet.tsx": "import { Dialog } from 'ui-lib'\n\n// CMP-021 Sheet — 04: 하단 시트\nexport function Sheet(p) { return '<div data-cmp=\"CMP-021\">' }\n",
    "src/components/RecordSummary.tsx": "// CMP-045 RecordSummary\nexport const RecordSummary = (p) => p\n",
    # 참조만: 보조 훅의 머리 주석, 본문 주석, 대응 부품을 import해 감싸는 사용처
    "src/components/sheetHooks.ts": "// CMP-021 Sheet 보조 훅. 열림 상태를 history state에 둡니다.\nexport function useSheetHistory() { return 1 }\n"
                                    "export const SHEET_KEY = 'sheet'\n",
    "src/features/EditPerson.tsx": "import { Sheet } from '../components/Sheet'\n\n// 사람 편집\n// - 회원 현황(CMP-045 ops): 지인·랭크\n"
                                   "export function EditPerson() {\n  return '<Sheet data-cmp=\"CMP-021\">'  // CMP-021 안에 둡니다\n}\n",
    # 구현 표지(중복)
    "src/features/MySheet.tsx": "'use client'\nimport { x } from 'y'\n// CMP-021 Sheet 복사본(화면 전용)\nexport function MySheet() { return x }\n",
    "src/features/InlineSummary.tsx": "export function InlineSummary() {\n  return '<section data-cmp=\"CMP-045\" class=\"sum\"></section>'\n}\n",
}


def marker_cases() -> None:
    cm = getattr(pb_scan, "cmp_markers", None)
    if cm is None:
        check("M0 공통 표지 판정 함수 pb_scan.cmp_markers 존재", False, "없음(수정 전)")
        return
    cases = [
        ("머리 선언(부품 파일)", "// CMP-001 Button\nexport function Button() {}\n", {"CMP-001"}, set()),
        ("import·지시문 뒤 머리 선언", "'use client'\nimport a from 'a'\nimport {\n  b,\n} from 'b'\n\n// CMP-001 Button — 설명\nexport const Button = (p) => p\n",
         {"CMP-001"}, set()),
        ("한 파일 여러 CMP 선언(다중 export)", "/* CMP-001 Button\n * CMP-002 IconButton\n */\nexport function Button() {}\nexport function IconButton() {}\n",
         {"CMP-001", "CMP-002"}, set()),
        ("export 없는 단일 파일 부품(.vue·.svelte 등)", "<!-- CMP-003 DataTable -->\n<template><table/></template>\n", {"CMP-003"}, set()),
        ("보조 훅 파일의 머리 주석은 참조", "// CMP-021 Sheet 보조 훅\nexport function useSheet() {}\nexport const SHEET_KEY = 1\n", set(), {"CMP-021"}),
        ("보조 파일이 문맥(Context)·상수를 함께 내보내도 머리 주석은 참조",
         "// CMP-021 Sheet 보조 훅\nexport function useSheet() {}\nexport const WideLayoutContext = createContext(true)\n", set(), {"CMP-021"}),
        ("화면 파일(Page)의 머리 선언은 종전대로 표지", "// CMP-010 Wizard\nexport function SetupPage() {}\n", {"CMP-010"}, set()),
        ("본문 주석·문장 속 언급은 참조", "export function Page() {\n  // 버튼(CMP-001) 사용\n  return 1\n}\n", set(), {"CMP-001"}),
        ("머리 주석이라도 CMP로 시작하지 않으면 참조", "// 시트(CMP-021)와 함께 쓰는 패널\nexport function Panel() {}\n", set(), {"CMP-021"}),
        ("data-cmp 렌더 표지", "export function X() { return '<i data-cmp=\"CMP-005\" />' }\n", {"CMP-005"}, set()),
        ("data-cmp 따옴표·중괄호 변형", "const a = <b data-cmp='CMP-006'/>; const c = <d data-cmp={\"CMP-007\"}/>\n", {"CMP-006", "CMP-007"}, set()),
    ]
    for name, text, impl, refs in cases:
        m = cm(text)
        got_impl = set(m["declared"]) | set(m["rendered"])
        check(f"M1 표지 판정: {name}", got_impl == impl and set(m["referenced"]) == refs, m)


def duplicate_cases(root: Path) -> None:
    d = root / "dup"
    for rel, text in FILES.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    files = sorted(FILES)
    dup, E, W = pb_ui.duplicate_findings(d, files, COMPS)
    found = sorted((x["file"], x["cmp"]) for x in dup)
    check("M2 주석 참조·보조 훅·감싸는 사용처는 중복 아님, 머리 선언·직접 data-cmp 렌더만 duplicate_component",
          found == [("src/features/InlineSummary.tsx", "CMP-045"), ("src/features/MySheet.tsx", "CMP-021")]
          and all(e.startswith("[duplicate_component]") for e in E) and len(E) == 2, (found, E))
    texts = {r: FILES[r] for r in files}
    dup2, _, _ = pb_ui.duplicate_findings(d, files, COMPS, texts)
    check("M3 ui-guard 경로(스냅샷 텍스트)와 파일 경로의 판정이 같음", sorted((x["file"], x["cmp"]) for x in dup2) == found)
    inv = pb_scan.component_inventory(d, ["src/components"], files, {"CMP-021": "Sheet", "CMP-045": "RecordSummary"})
    by = {x["file"]: x["cmp_markers"] for x in inv["files"]}
    cm = getattr(pb_scan, "cmp_markers", None)
    same = cm is not None and all(by[f] == sorted(set(cm(FILES[f])["declared"]) | set(cm(FILES[f])["rendered"])) for f in by)
    check("M4 scan 후보(component_inventory)와 ui-map check가 같은 표지 판정을 씀(보조 훅은 CMP-021 후보 아님)",
          same and by["src/components/sheetHooks.ts"] == [] and inv["cmp_candidates"]["CMP-021"] == ["src/components/Sheet.tsx"], by)
    big = "// CMP-021 Sheet 사본\nexport function BigSheet() {}\n" + "x\n" * 3000
    (d / "src/features/BigSheet.tsx").write_text(big, encoding="utf-8")
    dup3, _, _ = pb_ui.duplicate_findings(d, ["src/features/BigSheet.tsx"], COMPS)
    check("M5 큰 파일도 머리 선언은 탐지(앞부분 범위 유지)", [x["cmp"] for x in dup3] == ["CMP-021"], dup3)


def preview_cases() -> None:
    pf = getattr(pb_ui, "preview_findings", None)
    if pf is None:
        check("P0 프리뷰 언급 분류 함수 pb_ui.preview_findings 존재", False, "없음(수정 전)")
        return
    plan = {"screens": {"SCR-001": {
        "tree": [{"part": "P", "file": "web/a.tsx", "children": [{"part": "Q", "file": "design-preview/src/Q.tsx"}]}],
        "states": {"SCR-001-ST1": {"how": "story", "ref": "design-preview/stories/x"}},
        "data": [{"name": "s", "source": "mock", "mock_file": "design-preview/mocks/s.json"}],
        "visual_ref": "design-preview/src/screens/SCR-001.tsx",
        "notes": "design-preview/의 간격은 참고만"}},
        "components": {"CMP-001": {"action": "reuse", "part": "Button", "source": "design-preview/src/Button.tsx"}},
        "notes": ["프리뷰(design-preview/)는 시각 참고만 합니다. 코드는 재사용하지 않습니다",
                  "design-preview/screens/SCR-001.html 결과물을 참고 대상으로 봅니다",
                  "Do not copy design-preview/ code; visual reference only",
                  "design-preview/src/Q.tsx를 복사해 구현",
                  "cp design-preview/src/Q.tsx web/src/Q.tsx",
                  "const Q = require('../design-preview/src/Q')",
                  "Port design-preview/src/Q.tsx into the product as-is"]}
    errs, warns = pf(plan)
    check("P1 경로 필드(tree file·state ref·mock_file)와 알 수 없는 필드(source)는 계속 오류",
          {"screens.SCR-001.tree[0].children[0].file", "screens.SCR-001.states.SCR-001-ST1.ref", "screens.SCR-001.data[0].mock_file",
           "components.CMP-001.source"} <= set(errs), errs)
    check("P2 visual_ref는 오류도 경고도 아님", not any("visual_ref" in x for x in errs + warns))
    check("P3 자유 서술의 설명·참고 언급·부정문(재사용하지 않음, do not copy)은 경고만",
          {"notes[0]", "notes[1]", "notes[2]", "screens.SCR-001.notes"} <= set(warns) and not {"notes[0]", "notes[1]", "notes[2]"} & set(errs), (errs, warns))
    check("P4 자유 서술의 실제 재사용 지시(복사·cp·require/import·port)는 오류",
          {"notes[3]", "notes[4]", "notes[5]", "notes[6]"} <= set(errs), (errs, warns))


def gitignore_cases(root: Path) -> None:
    want = list(pb_exec.GITIGNORE_LINES)
    a = T.make_product(root, "gi-new", T.LIBRARY, with_design=False)
    code, out = pb(a, "init")
    gi = a / ".ai-workflow/build/.gitignore"
    lines = gi.read_text().split()
    check("I1 신규 init 직후 .gitignore가 실행 시 규칙(GITIGNORE_LINES) 전체를 포함", code == 0 and all(x in lines for x in want), gi.read_text())
    raw = gi.read_bytes()
    pb_exec.ensure_gitignore(a)
    check("I2 init 결과에 실행 경로(ensure_gitignore)가 더할 것이 없음(첫 batch-start에서 변경 없음)", gi.read_bytes() == raw)
    code, out = pb(a, "init")
    check("I3 반복 init(이미 초기화)은 결과 동일", code == 0 and out.get("status") == "already_initialized" and gi.read_bytes() == raw, out)

    b = T.make_product(root, "gi-custom", T.LIBRARY, with_design=False)
    custom = "# 팀 규칙\n*.tmp\ncache/\nevidence/\n"
    (b / ".ai-workflow/build").mkdir(parents=True, exist_ok=True)
    (b / ".ai-workflow/build/.gitignore").write_text(custom)
    code, out = pb(b, "init")
    text = (b / ".ai-workflow/build/.gitignore").read_text()
    check("I4 기존 .gitignore가 있으면 사용자 규칙·주석·순서를 보존하고 빠진 규칙만 덧붙임",
          code == 0 and text.startswith(custom) and all(x in text.split() for x in want) and text.split().count("evidence/") == 1, text)
    check("I5 init 출력이 .gitignore 갱신을 알림(created가 아니라 updated)", ".ai-workflow/build/.gitignore" in (out.get("updated") or [])
          and ".ai-workflow/build/.gitignore" not in out.get("created", []), out)
    raw_b = (b / ".ai-workflow/build/.gitignore").read_bytes()
    (b / ".ai-workflow/build.json").unlink()
    code, out = pb(b, "init")
    check("I6 상태 없이 다시 init해도 .gitignore는 그대로(중복 추가 없음, 멱등)", code == 0
          and (b / ".ai-workflow/build/.gitignore").read_bytes() == raw_b and ".ai-workflow/build/.gitignore" not in (out.get("updated") or []), out)
    prof = (b / "docs/build/build-profile.toml").read_bytes()
    check("I7 재 init은 기존 프로필을 덮어쓰지 않음", (b / "docs/build/build-profile.toml").read_bytes() == prof)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-build-m3-fixes-"))
    try:
        marker_cases()
        duplicate_cases(root)
        preview_cases()
        gitignore_cases(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
