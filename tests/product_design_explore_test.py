#!/usr/bin/env python3
"""/product-design 디자인 탐색 회귀 테스트(EX1 상태·활성화·경로 안전, EX2 1차 구조 탐색, EX3 레퍼런스 기반 탐색, EX4 측정·선택 게이트).

설계: docs/roadmap/design-exploration-design.md. 임시 디렉터리의 독립 픽스처만 씁니다(실제 프로젝트·브라우저 없이).
실행: python3 tests/product_design_explore_test.py
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_design_test as T  # noqa: E402

ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE / "skills/product-design/scripts"))
sys.path.insert(1, str(ENGINE / "skills/product-build/scripts"))
import pd_explore as EX  # noqa: E402

results: list[tuple[str, bool]] = []


def check(name: str, cond, detail=None) -> None:
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


pi, state, G = T.pi, T.state, T.G
UXP = T.UXP


def P(d: Path) -> tuple[str, str]:
    return ("--project", str(d))


def raw(d: Path) -> bytes:
    return (d / ".ai-workflow/design.json").read_bytes()


def approvals(st: dict) -> dict:
    """승인·제출 기록, revision, 해시, history 앞부분 — 탐색 기능이 바꾸면 안 되는 것."""
    return {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted", "artifacts_done")} for k, v in st["stages"].items()} | {
        "based_on": st.get("based_on"), "theme": st.get("theme"), "gates": (st.get("config") or {}).get("gates"),
        "theme_file": (st.get("config") or {}).get("theme_file")}


NOTES_DONE = T.ROUND1_PENDING.replace("- **상태**: 답변 대기", "- **상태**: 답변 완료").replace("(대기 중)", "R01-Q1: a, R01-Q2: b")


def approve_ux_planning(d: Path) -> None:
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    for args in (("done", "--path", UXP), ("submit", "--stage", "ux_planning"), ("approve", "--stage", "ux_planning", "--revision", "1")):
        code, out = pi(*args, *P(d))
        assert code == 0, (args, out)


# ---------------------------------------------------------------- EX1
def ex1(root: Path) -> None:
    # 기본 start는 이전과 같음(v1, 탐색 없음)
    d1 = T.make_product(root, "v1")
    code, out = pi("start", *P(d1))
    st = state(d1)
    check("E1 기본 start는 이전과 같은 v1(config·exploration 없음)", code == 0 and "config" not in st and "exploration" not in st
          and list(st["stages"]) == ["ux_planning", "ux_spec", "preview"], st.get("config"))

    # 신규 v2: 게이트·탐색 기본 활성
    d2 = T.make_product(root, "v2new")
    code, out = pi("start", "--workflow", "v2", *P(d2))
    st = state(d2)
    cfg = st.get("config") or {}
    check("E2 start --workflow v2: 게이트 켜짐·1차·2차 탐색 기본 활성·design_direction locked·테마 기준 필드",
          code == 0 and cfg.get("workflow") == "v2" and cfg.get("gates") == {"design_direction": True}
          and cfg["exploration"]["structure"]["enabled"] and cfg["exploration"]["visual"]["enabled"] and cfg["exploration"]["source"] == "start_v2"
          and st["stages"]["design_direction"]["status"] == "locked" and "theme" in st and st["exploration"]["structure"]["status"] == "not_started"
          and out["exploration"]["structure"]["enabled"], (out, cfg))
    code, out = pi("check", *P(d2))
    check("E3 신규 v2 check 정상·탐색 요약 표시(상태 형태 문제 없음)", code == 0 and out["exploration"]["visual"]["enabled"]
          and out["workflow"]["gates"]["design_direction"], out)
    code, out = pi("start", "--theme-file", "x.json", *P(T.make_product(root, "badopt")))
    check("E4 --theme-file은 --workflow v2와 함께만", code == 2 and out["error"] == "invalid_arguments", out)

    # 기존 v1 프로젝트(승인 기록 있음): 탐색 명령 거부, 파일 불변
    approve_ux_planning(d1)
    before = raw(d1)
    code, out = pi("explore-config", "--enable", "structure", "--note", "켭니다", "--confirm", *P(d1))
    check("E5 v1 프로젝트는 탐색을 켤 수 없음(exploration_unavailable), 상태 파일 불변", code == 2 and out["error"] == "exploration_unavailable"
          and raw(d1) == before, out)

    # 기존 v1 → v2 전환: 탐색 자동 활성 없음
    code, out = pi("migrate", "--to", "v2", "--confirm", *P(d1))
    st = state(d1)
    check("E6 기존 프로젝트의 v2 전환은 탐색을 자동으로 켜지 않음(config.exploration 없음, 게이트도 기존대로 꺼짐)",
          code == 0 and "exploration" not in (st.get("config") or {}) and "exploration" not in st and not (st["config"].get("gates") or {}).get("design_direction"), st.get("config"))
    before = raw(d1)
    for args in (("check",), ("status",)):
        code, out = pi(*args, *P(d1))
        check(f"E7 기존 v2의 {args[0]}: 탐색 요약 없음·상태 파일 불변", code == 0 and "exploration" not in out and raw(d1) == before, out.get("exploration"))
    code, out = pi("explore-config", "--enable", "visual", "--note", "켭니다", "--confirm", *P(d1))
    check("E8 게이트가 꺼진 기존 v2에서 2차 탐색 켜기 거부(design_direction_gate_required, D7), 불변",
          code == 2 and out["error"] == "design_direction_gate_required" and raw(d1) == before, out)
    code, out = pi("explore-config", "--enable", "all", "--note", "켭니다", "--confirm", *P(d1))
    check("E9 all도 게이트 없이는 거부(한 명령에서 함께 켜지 않음)", code == 2 and out["error"] == "design_direction_gate_required" and raw(d1) == before, out)

    # 1차 켜기: 계획 → 문장 없으면 거부 → 기록. 승인 기록 불변
    appr0 = approvals(state(d1))
    hist0 = state(d1)["history"]
    code, out = pi("explore-config", "--enable", "structure", *P(d1))
    check("E10 explore-config 기본은 계획만(dry_run), 쓰지 않음, 승인된 단계는 다음 reopen부터 적용",
          code == 0 and out["dry_run"] and out["plan"]["effects"]["structure"]["applies_from"] == "next_reopen" and raw(d1) == before, out)
    code, out = pi("explore-config", "--enable", "structure", "--confirm", *P(d1))
    check("E11 사용자 문장(--note) 없으면 거부, 불변", code == 2 and out["error"] == "statement_required" and raw(d1) == before, out)
    code, out = pi("explore-config", "--enable", "structure", "--confirm", "--note", "구조 탐색을 켭니다", *P(d1))
    st = state(d1)
    check("E12 1차 탐색 켜기: 설정·활성화 기록(문장·적용 시점) 추가", code == 0 and st["config"]["exploration"]["structure"]["enabled"]
          and not st["config"]["exploration"]["visual"]["enabled"] and st["exploration"]["activations"][-1]["statement"] == "구조 탐색을 켭니다"
          and st["exploration"]["activations"][-1]["applies_from"] == "next_reopen", st.get("exploration"))
    check("E13 활성화 전후 승인·제출 기록·revision·해시·테마·게이트·history 앞부분 불변", approvals(st) == appr0 and st["history"][:len(hist0)] == hist0,
          (approvals(st), appr0))
    code, out = pi("explore-config", "--disable", "structure", "--confirm", "--note", "이 프로젝트는 탐색 없이 진행", *P(d1))
    st = state(d1)
    check("E14 끄기(프로젝트 정책): 기록 보존, enabled false, 승인 불변", code == 0 and not st["config"]["exploration"]["structure"]["enabled"]
          and len(st["exploration"]["activations"]) == 2 and approvals(st) == appr0, st.get("exploration"))
    code, out = pi("migrate", "--to", "v2", "--enable-gate", "design_direction", "--confirm", *P(d1))
    assert code == 0, out
    code, out = pi("explore-config", "--enable", "visual", "--confirm", "--note", "게이트를 켰으니 시각 탐색을 켭니다", *P(d1))
    check("E15 게이트를 먼저 켠 뒤에는 2차 탐색 켜기 가능", code == 0 and state(d1)["config"]["exploration"]["visual"]["enabled"], out)
    code, out = pi("migrate", "--to", "v2", "--confirm", *P(d1))
    check("E16 탐색 설정이 있어도 migrate 멱등(already_v2, 탐색 필드를 보존 검사에서 문제 삼지 않음)", code == 0 and out.get("status") == "already_v2", out)

    # 시작 전 경로 검사
    d3 = T.make_product(root, "has-explore")
    (d3 / "design-explore").mkdir()
    (d3 / "design-explore/x.html").write_text("<p>old</p>")
    code, out = pi("start", "--workflow", "v2", *P(d3))
    check("E17 design-explore/가 이미 있으면 start 거부(덮어쓰지 않음)", code == 2 and out["error"] == "existing_files" and "design-explore" in out["paths"], out)

    # 섞임 판정(D4): 동일 파일·명시 참조 차단, 비슷한 파일·주석 언급은 통과
    w = root / "contam"
    (w / "design-explore/S01/A").mkdir(parents=True)
    (w / "design-explore/S01/A/styles.css").write_text(".card { padding: 12px; }\n.row { gap: 8px; }\n")
    (w / "src").mkdir()
    (w / "src/copy.css").write_text(".card { padding: 12px; }   \r\n.row { gap: 8px; }\n")
    (w / "src/import.ts").write_text("import x from '../design-explore/S01/A/index.html'\n")
    (w / "src/similar.css").write_text(".card { padding: 12px; }\n.row { gap: 10px; }\n")
    (w / "src/comment.ts").write_text("// 시안은 design-explore/S01 을 시각 참고만 했습니다\nexport const a = 1\n")
    found = {x["file"]: x["kind"] for x in EX.explore_contamination(w, ["src/copy.css", "src/import.ts", "src/similar.css", "src/comment.ts"])}
    check("E18 product-design 판정: 동일 파일(줄 끝·공백만 다름)=explore_copy, import=explore_reuse, 비슷한 파일·주석 언급=통과",
          found == {"src/copy.css": "explore_copy", "src/import.ts": "explore_reuse"}, found)
    import pb_core
    import pb_ui
    found_b = {x["file"]: x["kind"] for x in pb_ui.explore_findings(w, ["src/copy.css", "src/import.ts", "src/similar.css", "src/comment.ts"])}
    check("E19 product-build 판정이 같은 규칙(두 Skill 독립 구현 일치)", found_b == found, found_b)
    check("E20 product-build 보호 경로에 design-explore/ 포함(배치 쓰기·계획 경로·가드 차단)", pb_core.is_protected("design-explore/S01/A/index.html")
          and not pb_core.is_protected("src/design-explorer.ts"))
    import product_build as PBM
    (w / "src/own.ts").write_text("export const own = 1\n")
    files = PBM._batch_text_files(w, {"paths": {"allow": ["src/"], "shared": []}})
    xf = {x["file"]: x["kind"] for x in pb_ui.explore_findings(w, files)}
    check("E22 verify 경로: 배치 범위 파일(.css 포함) 수집 → 동일 복사·참조만 차단 대상, 시안 폴더 자체는 검사 대상 아님",
          set(files) >= {"src/copy.css", "src/import.ts", "src/own.ts"} and not any(f.startswith("design-explore/") for f in files)
          and xf == {"src/copy.css": "explore_copy", "src/import.ts": "explore_reuse"}, (files, xf))
    errs, warns = pb_ui.preview_findings({"screens": {"SCR-001": {"tree": [{"part": "P", "file": "design-explore/S01/A/index.html"}]}},
                                          "notes": ["design-explore/S01의 B안 배치를 참고했습니다", "design-explore/S01/B/index.html을 복사해 구현"]})
    check("E21 UI Plan: 경로 필드의 design-explore/ 오류, 설명은 경고, 복사 지시는 오류", "screens.SCR-001.tree[0].file" in errs
          and "notes[0]" in warns and "notes[1]" in errs, (errs, warns))


# ---------------------------------------------------------------- EX2 픽스처(Claude 대신 시안 작성)
def png_bytes() -> bytes:
    import struct
    import zlib

    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xffffffff)
    raw_ = b"\x00\xff\xff\xff"
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw_)) + chunk(b"IEND", b"")


# 시안별 요소 순서·영역이 다르게(구조가 다른 시안). (id, target, kind, refs, region, sample, html)
LAYOUTS = {
    "A": [("e1", "T1", "info", ["FR-001"], "header", False, '<h1 data-el="e1">배드민턴 모임</h1>'),
          ("e2", "T1", "action", ["US-001", "AC-001"], "main", False, '<button data-el="e2">로그인</button>'),
          ("e3", "T2", "info", ["AC-003"], "main", True, '<ol data-el="e3" data-sample><li>코트 1 · 예시 A·B</li></ol>'),
          ("e4", "T2", "action", ["AC-003"], "footer", False, '<button data-el="e4">대진 만들기</button>')],
    "B": [("e2", "T1", "action", ["US-001", "AC-001"], "main", False, '<button data-el="e2">로그인</button>'),
          ("e1", "T1", "info", ["FR-001"], "footer", False, '<p data-el="e1">배드민턴 모임</p>'),
          ("e4", "T2", "action", ["AC-003"], "header", False, '<button data-el="e4">대진 만들기</button>'),
          ("e3", "T2", "info", ["AC-003"], "main", True, '<ol data-el="e3" data-sample><li>코트 1 · 예시 A·B</li></ol>')],
    "C": [("e1", "T1", "info", ["FR-001"], "main", False, '<h1 data-el="e1">배드민턴 모임</h1>'),
          ("e2", "T1", "action", ["US-001"], "footer", False, '<button data-el="e2">로그인</button>'),
          ("e3", "T2", "info", ["AC-003"], "aside", True, '<table data-el="e3" data-sample><tr><td>코트 1</td></tr></table>'),
          ("e4", "T2", "action", ["AC-003"], "main", False, '<a href="#T2" data-el="e4">대진 만들기</a>')],
}
PLAN_BODY = "## 구조 개념\n- {c}\n\n## 정보 우선순위\n- 소개 → 행동\n\n## 주 행동 위치\n- {p}\n\n## 진부한 기본값 대조\n- 카드 나열을 피함\n\n## 다른 시안과의 차이\n- 행동 위치\n"


def write_variant(d: Path, rid: str, lb: str, layout, css: str = "", title=None, axes=("layout",)) -> None:
    base = d / "design-explore" / rid / lb
    secs = {}
    for _id, tgt, _k, _r, _reg, _s, html in layout:
        secs.setdefault(tgt, []).append(html)
    body = "\n".join(f'<section data-target="{t}" id="{t}">{"".join(h)}</section>' for t, h in secs.items())
    (base / "index.html").write_text(f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"></head><body>{body}</body></html>')
    (base / "styles.css").write_text(css or f"body{{font-family:system-ui;padding:16px}} section{{border:1px solid #999;margin:8px 0;padding:8px}} /* {lb} */\n")
    (base / "plan.md").write_text(PLAN_BODY.format(c=f"{lb}안 구조", p="하단" if lb == "A" else "상단"))
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    v = man["rounds"][rid]["variants"][lb]
    v.update(title=title or f"{lb}안", concept=f"{lb}안 개념", distinct_axes=list(axes),
             elements=[{"id": i, "target": t, "kind": k, "refs": r, "region": reg, **({"sample": True} if s else {})} for i, t, k, r, reg, s, _ in layout])
    man["guidance"] = [{"name": "frontend-design", "version": "1.1.1", "used_for": ["plan", "contrast", "critique"]}]
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def write_critique(d: Path, rid: str, labels, kind: str = "explore") -> None:
    fields = EX.CRITIQUE_FIELDS[kind]
    body = "".join(f"\n## {rid}-{lb}\n" + "".join(f"- **{f}**: {lb}안 {f} 평가\n" for f in fields) for lb in labels)
    (d / f"design-explore/{rid}/critique.md").write_text(f"# {rid} 시각 평가\n{body}")


def ex2(root: Path) -> None:
    d = T.make_product(root, "explore-flow")
    assert pi("start", "--workflow", "v2", *P(d))[0] == 0
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    assert pi("done", "--path", UXP, *P(d))[0] == 0
    code, out = pi("submit", "--stage", "ux_planning", *P(d))
    check("X1 탐색이 켜진 신규 v2: 탐색 없이 UX Planning 제출 거부(exploration_required), 상태 불변",
          code == 2 and out["error"] == "exploration_required" and state(d)["stages"]["ux_planning"]["status"] == "in_progress", out)

    for args, err in ((("--phase", "visual"), "upstream_not_approved"), (("--phase", "structure", "--mode", "reference"), "intent_required"),
                      (("--phase", "structure", "--variants", "1"), "variant_count"), (("--phase", "structure", "--variants", "4"), "variant_count")):
        code, out = pi("explore-init", *args, *P(d))
        check(f"X2 explore-init {' '.join(args)} → {err}", code == 2 and out["error"] == err, out)
    check("X3 거부된 init은 파일·라운드를 만들지 않음", not (d / "design-explore").exists() and not state(d)["exploration"]["structure"]["rounds"])

    code, out = pi("explore-init", "--phase", "structure", *P(d))
    st = state(d)
    r = st["exploration"]["structure"]["rounds"][0] if st["exploration"]["structure"]["rounds"] else {}
    check("X4 explore-init: 라운드 S01, AI 기본 시안 3개(A·B·C), 기획 ID 앵커 대상 2개(허브 단계 우선·선정 근거 출력), brief·plan·HTML 골격·critique·manifest·.gitignore",
          code == 0 and out["round"] == "S01" and out["variants"] == ["A", "B", "C"] and [t["anchor"][0] for t in out["targets"]] == ["FLOW-001-S2", "FLOW-002-S1"]
          and any("허브" in b for b in out["targets"][0]["basis"]) and all(t["basis"] for t in out["targets"])
          and all((d / f"design-explore/S01/{x}").is_file() for x in ("brief.md", "critique.md", "A/plan.md", "B/index.html", "C/styles.css"))
          and (d / "design-explore/.gitignore").is_file() and r.get("kind") == "explore" and st["exploration"]["structure"]["status"] == "in_progress", out)
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    check("X5 manifest 공통 계약(design-explore/v1, experimental, html 렌더러, 시안별 render·plan·elements 자리)",
          man["format"] == "design-explore/v1" and man["experimental"] is True and man["renderer"]["kind"] == "html"
          and set(man["rounds"]["S01"]["variants"]) == {"A", "B", "C"}, man)
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("X6 작성 전 골격은 검사 실패(제목·개념·계획·요소 없음)", code == 2 and any("manifest_incomplete" in e for e in out["errors"])
          and any("plan_incomplete" in e for e in out["errors"]), out.get("errors"))

    for lb in "ABC":
        write_variant(d, "S01", lb, LAYOUTS[lb])
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("X7 구조가 서로 다른 시안 3개: 검사 통과(critique는 선택 전 경고)", code == 0 and out["ok"] and out["critique_missing"], out.get("errors"))

    # 계약 위반 재현(B를 잠시 망가뜨림)
    good_b = (d / "design-explore/S01/B/index.html").read_text()
    bad_html = good_b.replace('<button data-el="e2">로그인</button>', '<button data-el="e2">로그인</button><button>공유하기</button>')
    bad_html = bad_html.replace("</head>", '<link rel="stylesheet" href="https://fonts.example.com/a.css"><script>1</script></head>')
    bad_html = bad_html.replace('<ol data-el="e3" data-sample>', '<ol data-el="e3"><li data-el="e9">x</li>')
    (d / "design-explore/S01/B/index.html").write_text(bad_html)
    (d / "design-explore/S01/B/styles.css").write_text("body{background:url(../../../frontend/x.png)}\n")
    code, out = pi("explore-check", "--round", "S01", *P(d))
    e = " | ".join(out.get("errors", []))
    check("X8 근거 없는 버튼(요구사항 밖 기능)·외부 리소스·스크립트·예시 데이터 미표시·선언 없는 요소·라운드 밖 경로 → 오류",
          code == 2 and all(k in e for k in ("unbacked_element", "external_resource", "script_not_allowed", "sample_unmarked", "undeclared_element", "path_escape")), e)
    (d / "design-explore/S01/B/index.html").write_text(good_b)
    write_variant(d, "S01", "B", LAYOUTS["B"])
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    man["rounds"]["S01"]["variants"]["C"]["elements"][0]["refs"] = ["FR-099"]
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False))
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("X9 기획에 없는 근거 ID → 오류", code == 2 and any("FR-099" in x for x in out["errors"]), out.get("errors"))
    write_variant(d, "S01", "C", LAYOUTS["C"])
    # 색만 다른 시안(D2)
    write_variant(d, "S01", "C", LAYOUTS["A"], css="body{background:#123456;color:#fff}\n")
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("X10 A와 구조가 같고 색만 다른 C → variants_not_distinct(D2, 오류)", code == 2 and any("variants_not_distinct" in x and "A와 C" in x for x in out["errors"]), out.get("errors"))
    write_variant(d, "S01", "C", LAYOUTS["C"])

    code, out = pi("explore-compare", "--round", "S01", *P(d))
    cmp_html = (d / "design-explore/S01/compare.html").read_text() if code == 0 else ""
    view = (d / "design-explore/S01/compare/B-T2.html").read_text() if code == 0 else ""
    check("X11 비교 페이지: 대상 × 뷰포트 × 시안 iframe(대상별 파생 보기, #앵커 미사용), 외부 리소스 없음", code == 0 and cmp_html.count("<iframe") == 2 * 2 * 3
          and 'src="compare/B-T2.html"' in cmp_html and "#T" not in re.sub(r'href="#cmp-T\d"', "", cmp_html) and "http" not in cmp_html.replace("http-equiv", ""), out)
    check("X11b 대상별 보기: 원본 시안을 바꾸지 않고 다른 대상 영역만 숨김(<base>로 원본 CSS 사용)",
          '<base href="../B/">' in view and '[data-target]:not([data-target="T2"])' in view and "대진 만들기" in view
          and "compare" not in (d / "design-explore/S01/B/index.html").read_text(), view[:300])

    shot = d / "captures" / "capture.png"  # 증거는 프로젝트 안 파일만(파일럿 보완: 경로 범위)
    shot.parent.mkdir(exist_ok=True)
    shot.write_bytes(png_bytes())
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", *P(d))
    check("X12 선택 문장 없으면 거부", code == 2 and out["error"] == "choice_statement_required", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "좋네요", *P(d))
    check("X13 '좋네요'는 선택이 아님(choice_statement_unclear)", code == 2 and out["error"] == "choice_statement_unclear", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로 갑니다", "--evidence", str(shot), *P(d))
    check("X14 시각 평가(critique) 미완성이면 선택 거부(critique_incomplete)", code == 2 and out["error"] == "critique_incomplete", out)
    write_critique(d, "S01", "ABC")
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로 갑니다", *P(d))
    check("X15 핵심 시각 증거 없이 선택 거부(retention_incomplete, D6)", code == 2 and out["error"] == "retention_incomplete", out)
    before = raw(d)
    appr0 = approvals(state(d))
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로 갑니다. 행동이 위에 있어 좋습니다", "--evidence", str(shot),
                   "--feedback", "A는 행동이 너무 아래", *P(d))
    st = state(d)
    ch = st["exploration"]["structure"]["choice"] or {}
    gi = (d / "design-explore/.gitignore").read_text()
    check("X16 선택 기록: EXP-S01-B, 사용자 문장·피드백, 측정 미실행 경고, 모든 시안 파일 해시, 증거 사본",
          code == 0 and ch.get("id") == "EXP-S01-B" and ch["statement"].startswith("B안") and ch["feedback"] == ["A는 행동이 너무 아래"]
          and ch["measurement"] == "not_run" and any("measurement_not_run" in w for w in out["warnings"])
          and any(k.startswith("design-explore/S01/A/") for k in ch["files"]) and (d / "design-explore/S01/selection/selection.json").is_file()
          and ch["evidence"] and (d / ch["evidence"][0]["path"]).is_file(), out)
    check("X17 Git 보존(D6): 미선택 A·C와 compare(파생 보기 포함)·shots는 제외, 선택 B·manifest·brief·critique·선택 기록은 보존", "S01/A/" in gi and "S01/C/" in gi
          and "S01/B/" not in gi and "*/compare.html" in gi and "*/compare/" in gi and "*/shots/" in gi
          and not any("/compare/" in k for k in ch["files"])
          and {"design-explore/S01/B/index.html", "design-explore/S01/critique.md", "design-explore/S01/brief.md", "design-explore/explore.manifest.json"} <= set(ch["retention"]), gi)
    check("X18 선택은 승인이 아님: 승인·제출 기록·revision·해시 불변", approvals(st) == appr0 and st["stages"]["ux_planning"]["status"] == "in_progress")

    code, out = pi("submit", "--stage", "ux_planning", *P(d))
    check("X19 선택을 반영한 UXD가 없으면 제출 거부(exploration_not_reflected)", code == 2 and out["error"] == "exploration_not_reflected", out)
    txt = (d / UXP).read_text()
    (d / UXP).write_text(txt.replace("- **근거**: 사용자 답변(라운드 1)", "- **근거**: 사용자 선택 EXP-S01-A(라운드 1)"))
    pi("done", "--path", UXP, *P(d))
    code, out = pi("trace", "--stage", "ux_planning", *P(d))
    check("X20 선택하지 않은 시안을 근거로 쓰면 trace 오류(exploration_ref_not_chosen)", code == 2 and any("exploration_ref_not_chosen" in x for x in out["errors"]), out)
    (d / UXP).write_text(txt.replace("- **근거**: 사용자 답변(라운드 1)", "- **근거**: 사용자 선택 EXP-S07-B(라운드 1)"))
    pi("done", "--path", UXP, *P(d))
    code, out = pi("trace", "--stage", "ux_planning", *P(d))
    check("X21 기록에 없는 선택 ID → exploration_ref_unknown", code == 2 and any("exploration_ref_unknown" in x for x in out["errors"]), out)
    (d / UXP).write_text(txt.replace("- **근거**: 사용자 답변(라운드 1)", "- **근거**: 사용자 선택 EXP-S01-B(라운드 1)"))
    pi("done", "--path", UXP, *P(d))

    # 선택 후 보존 파일 변경 → 상태 경고·제출 거부
    bfile = d / "design-explore/S01/B/index.html"
    orig = bfile.read_text()
    bfile.write_text(orig.replace("로그인", "로그인하기"))
    code, st_out = pi("explore-status", *P(d))
    code2, out = pi("submit", "--stage", "ux_planning", *P(d))
    check("X22 선택 후 선택 시안이 바뀌면 explore-status 경고·제출 거부(changed_since_choice)",
          any("changed_since_choice" in w for w in st_out["warnings"]) and code2 == 2 and out["error"] == "changed_since_choice", (st_out.get("warnings"), out))
    bfile.write_text(orig)
    before = raw(d)
    pi("explore-status", *P(d))
    check("X23 explore-status는 읽기 전용(상태 파일 불변)", raw(d) == before)

    code, out = pi("submit", "--stage", "ux_planning", *P(d))
    code2, ap = pi("approve", "--stage", "ux_planning", "--revision", "1", *P(d))
    st = state(d)
    check("X24 선택이 UXD 근거로 이어지면 제출·승인 통과, 승인 단계에 탐색 근거(추적용 exploration_basis) 기록",
          code == 0 and code2 == 0 and st["stages"]["ux_planning"]["status"] == "approved"
          and st["stages"]["ux_planning"]["exploration_basis"]["choice"] == "EXP-S01-B" and "exploration_basis" not in st["stages"]["ux_planning"]["approved"], (out, ap))
    check("X25 승인 해시에 design-explore/ 없음(시안은 승인 대상 아님)", all("design-explore" not in k for k in st["stages"]["ux_planning"]["approved"]["hashes"]))
    code, out = pi("check", *P(d))
    check("X26 check 일치(탐색 산출물이 교차 검증을 흔들지 않음)", code == 0 and out["cross_verify"]["consistent"], out.get("cross_verify"))
    code, out = pi("explore-init", "--phase", "structure", *P(d))
    check("X27 승인 후에는 새 라운드 불가(reopen 필요, invalid_transition)", code == 2 and out["error"] == "invalid_transition", out)

    # 후속 수정 라운드(단일 시안 허용) — reopen 후
    assert pi("reopen", "--stage", "ux_planning", "--reason", "B안을 조금 고쳐 보기로 함", *P(d))[0] == 0
    code, out = pi("explore-init", "--phase", "structure", "--parent", "S01", "--variants", "1", *P(d))
    check("X28 단일 시안은 기준 시안(--base) 없이는 불가", code == 2 and out["error"] == "invalid_arguments" or out.get("error") == "variant_count", out)
    code, out = pi("explore-init", "--phase", "structure", "--parent", "S01", "--base", "S01-B", "--variants", "1", *P(d))
    check("X29 후속 수정 라운드 S02: 기준 S01-B, 단일 시안 A, 대상 상속", code == 0 and out["round"] == "S02" and out["kind"] == "revision"
          and out["variants"] == ["A"] and [t["id"] for t in out["targets"]] == ["T1", "T2"], out)
    for f in ("index.html", "styles.css"):
        shutil.copyfile(d / f"design-explore/S01/B/{f}", d / f"design-explore/S02/A/{f}")
    write_variant(d, "S02", "A", LAYOUTS["B"], css=(d / "design-explore/S01/B/styles.css").read_text(), axes=())
    (d / "design-explore/S02/A/plan.md").write_text(EX.PLAN_HEADINGS["revision"] and "\n".join(f"## {h}\n- 내용\n" for h in EX.PLAN_HEADINGS["revision"]))
    code, out = pi("explore-check", "--round", "S02", *P(d))
    check("X30 기준과 같은 산출물인 수정 시안 → revision_identical_to_base", code == 2 and any("revision_identical_to_base" in x for x in out["errors"]), out.get("errors"))
    write_variant(d, "S02", "A", LAYOUTS["B"], css="body{padding:24px} button{min-height:48px}\n", axes=())
    (d / "design-explore/S02/A/plan.md").write_text("\n".join(f"## {h}\n- 내용\n" for h in EX.PLAN_HEADINGS["revision"]))
    code, out = pi("explore-check", "--round", "S02", *P(d))
    check("X31 단일 수정 시안: D2 구분 검사 대신 기준 대비 변경 검사로 통과", code == 0, out.get("errors"))
    code, out = pi("explore-choose", "--round", "S02", "--variant", "A", "--note", "A로 확정", "--evidence", str(shot), *P(d))
    check("X32 단일 시안도 시각 평가 없으면 선택 불가", code == 2 and out["error"] == "critique_incomplete", out)
    write_critique(d, "S02", "A", "revision")
    code, out = pi("explore-choose", "--round", "S02", "--variant", "A", "--note", "수정한 A로 확정합니다", "--evidence", str(shot), *P(d))
    st = state(d)
    check("X33 단일 시안 선택 기록 EXP-S02-A, 이전 라운드 선택은 superseded_by로 보존", code == 0 and st["exploration"]["structure"]["choice"]["id"] == "EXP-S02-A"
          and st["exploration"]["structure"]["rounds"][0]["superseded_by"] == "S02" and len(st["exploration"]["structure"]["choices"]) == 2, out)

    # 대상별 조합 선택
    code, out = pi("explore-choose", "--round", "S01", "--per-target", "T1=A,T2=C", "--note", "T1은 A", "--evidence", str(shot), *P(d))
    check("X34 조합 선택은 고른 시안이 모두 문장에 드러나야 함", code == 2 and out["error"] == "choice_statement_unclear", out)
    code, out = pi("explore-choose", "--round", "S01", "--per-target", "T1=A,T2=C", "--note", "로그인은 A, 대진은 C로 합니다", "--evidence", str(shot), *P(d))
    gi = (d / "design-explore/.gitignore").read_text()
    check("X35 대상별 조합 EXP-S01-MIX, 보존 대상이 A·C로 바뀜(B 제외)", code == 0 and out["choice"] == "EXP-S01-MIX" and "S01/B/" in gi and "S01/A/" not in gi, (out, gi))

    # 정식 프리뷰에 시안이 섞이면 preview-check 오류(D4)
    (d / "design-preview/src").mkdir(parents=True)
    shutil.copyfile(d / "design-explore/S01/C/styles.css", d / "design-preview/src/copied.css")
    (d / "design-preview/src/use.ts").write_text("import page from '../../design-explore/S01/C/index.html'\nexport default page\n")
    (d / "design-preview/src/own.css").write_text("body{padding:16px}\n")
    (d / "design-preview/preview.manifest.json").write_text('{"screens": {}}')
    code, out = pi("preview-check", *P(d))
    e = " | ".join(out.get("errors", []))
    check("X39 preview-check: 시안 동일 파일 복사(explore_copy)·design-explore 참조(explore_reuse) 오류, 자체 작성 파일은 해당 없음",
          code == 2 and "copied.css" in e and "explore_copy" in e and "use.ts" in e and "explore_reuse" in e and "own.css" not in e, e[:600])
    shutil.rmtree(d / "design-preview")

    # 건너뛰기
    d2 = T.make_product(root, "explore-skip")
    assert pi("start", "--workflow", "v2", *P(d2))[0] == 0
    T.write_00(d2, 1)
    T.write_notes(d2, NOTES_DONE)
    pi("done", "--path", UXP, *P(d2))
    code, out = pi("explore-skip", "--phase", "structure", *P(d2))
    check("X36 건너뛰기는 사용자 문장 필요", code == 2 and out["error"] == "statement_required", out)
    code, out = pi("explore-skip", "--phase", "structure", "--note", "이미 화면 구성을 정해 두어 탐색 없이 진행합니다", *P(d2))
    code2, out2 = pi("submit", "--stage", "ux_planning", *P(d2))
    code3, out3 = pi("approve", "--stage", "ux_planning", "--revision", "1", *P(d2))
    check("X37 사용자 skip 후 제출·승인 정상, 근거에 skip 기록", code == 0 and code2 == 0 and code3 == 0
          and state(d2)["stages"]["ux_planning"]["exploration_basis"]["skipped"], (out2, out3))

    # 탐색이 꺼진 신규 v2(정책): 기존과 같은 제출
    d3 = T.make_product(root, "explore-off")
    assert pi("start", "--workflow", "v2", *P(d3))[0] == 0
    assert pi("explore-config", "--disable", "all", "--confirm", "--note", "이 프로젝트는 탐색을 쓰지 않습니다", *P(d3))[0] == 0
    T.write_00(d3, 1)
    T.write_notes(d3, NOTES_DONE)
    pi("done", "--path", UXP, *P(d3))
    code, out = pi("submit", "--stage", "ux_planning", *P(d3))
    code2, out2 = pi("explore-init", "--phase", "structure", *P(d3))
    check("X38 정책으로 끈 신규 v2: 탐색 없이 제출 가능, explore-init 거부", code == 0 and code2 == 2 and out2["error"] == "exploration_disabled", (out, out2))


# ---------------------------------------------------------------- EX2.1(P0-1 critique·P0-2 커버리지·P1 대상 선정·P2 라벨)
COV = {
    "T1": {"acs": {"AC-001": {"status": "required", "note": ""}, "AC-002": {"status": "delegated", "note": "인증 실패 안내는 오류 상태에서 다룸"}},
           "items": [{"id": "R1", "what": "로그인 행동", "kind": "action", "refs": ["US-001", "AC-001"]},
                     {"id": "R2", "what": "서비스 이름·소개", "kind": "info", "refs": ["FR-001", "AC-001"]}]},
    "T2": {"acs": {"AC-003": {"status": "required", "note": ""}, "AC-004": {"status": "not_ui", "note": "같은 입력 같은 결과는 서버 결정성"}},
           "items": [{"id": "R1", "what": "대진 생성 행동", "kind": "action", "refs": ["AC-003"]},
                     {"id": "R2", "what": "생성된 대진 결과", "kind": "info", "refs": ["AC-003"]}]},
}
# (id, target, kind, refs, region, covers, html)
COV_LAYOUT = {
    "A": [("e1", "T1", "info", ["FR-001", "AC-001"], "header", ["R2"], '<h1 data-el="e1">모임 앱</h1>'),
          ("e2", "T1", "action", ["US-001", "AC-001"], "footer", ["R1"], '<button data-el="e2">로그인</button>'),
          ("e3", "T2", "info", ["AC-003"], "main", ["R2"], '<ol data-el="e3" data-sample><li>예시 결과</li></ol>'),
          ("e4", "T2", "action", ["AC-003"], "footer", ["R1"], '<button data-el="e4">만들기</button>')],
    "B": [("e2", "T1", "action", ["US-001", "AC-001"], "main", ["R1"], '<button data-el="e2">로그인</button>'),
          ("e1", "T1", "info", ["FR-001", "AC-001"], "footer", ["R2"], '<p data-el="e1">모임 앱</p>'),
          ("e4", "T2", "action", ["AC-003"], "header", ["R1"], '<button data-el="e4">만들기</button>'),
          ("e3", "T2", "info", ["AC-003"], "main", ["R2"], '<ol data-el="e3" data-sample><li>예시 결과</li></ol>')],
    # C: T2의 결과(R2)를 빠뜨린 시안(실사용 검증에서 본 '필수 정보 누락' 유형)
    "C": [("e1", "T1", "info", ["FR-001", "AC-001"], "main", ["R2"], '<h1 data-el="e1">모임 앱</h1>'),
          ("e2", "T1", "action", ["US-001", "AC-001"], "aside", ["R1"], '<a href="#" data-el="e2">로그인</a>'),
          ("e4", "T2", "action", ["AC-003"], "main", ["R1"], '<a href="#" data-el="e4">만들기</a>')],
}


def write_cov_variant(d: Path, rid: str, lb: str, layout, extra_decl=None) -> None:
    base = d / "design-explore" / rid / lb
    secs = {}
    for _i, tgt, _k, _r, _reg, _c, html in layout:
        secs.setdefault(tgt, []).append(html)
    body = "".join(f'<section data-target="{t}" id="{t}">{"".join(h)}</section>' for t, h in secs.items())
    (base / "index.html").write_text(f'<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"></head><body>{body}</body></html>')
    (base / "styles.css").write_text(f"body{{margin:0}} /* {lb} */\n")
    (base / "plan.md").write_text(PLAN_BODY.format(c=f"{lb}안", p="아래"))
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    v = man["rounds"][rid]["variants"][lb]
    v.update(title=f"{lb}안", concept=f"{lb}안 개념", distinct_axes=["layout"],
             elements=[{"id": i, "target": t, "kind": k, "refs": r, "region": reg, "covers": c, **({"sample": True} if "data-sample" in html else {})}
                       for i, t, k, r, reg, c, html in layout] + (extra_decl or []))
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def set_cov(d: Path, rid: str, cov: dict) -> None:
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    man["rounds"][rid]["coverage"] = cov
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def errs_of(out) -> str:
    return " | ".join(out.get("errors") or [])


def ex21(root: Path) -> None:
    # P0-1: critique 빈 항목 우회
    F = EX.CRITIQUE_FIELDS["explore"]
    cp = root / "crit.md"

    def gaps(body):
        cp.write_text("# x\n## S01-A\n" + body)
        return EX.critique_gaps(cp, "S01", ["A"], "explore")
    g_all = gaps("".join(f"- **{f}**: \n" for f in F))
    g_part = gaps("".join(f"- **{f}**: 값\n" if i % 2 else f"- **{f}**:\n" for i, f in enumerate(F)))
    g_last = gaps("".join(f"- **{f}**:\n" for f in F[:-1]) + f"- **{F[-1]}**: 마지막만 채움\n")
    g_multi = gaps("".join(f"- **{f}**:\n  첫 줄 평가\n  둘째 줄 평가\n" for f in F))
    g_ph = gaps("".join(f"- **{f}**: TODO\n" for f in F))
    check("K1 critique: 모두 빈 항목·일부 빈 항목·마지막만 채운 경우 모두 누락으로 잡음(다음 항목 텍스트를 값으로 읽지 않음)",
          len(g_all) == len(F) and len(g_part) == (len(F) + 1) // 2 and len(g_last) == len(F) - 1, (len(g_all), len(g_part), len(g_last)))
    check("K2 critique: 여러 줄 평가는 통과, 자리표시(TODO)만 있으면 누락", g_multi == [] and len(g_ph) == len(F), (g_multi, g_ph[:2]))

    # 라벨·대상 지정(P2)
    d = T.make_product(root, "ex21")
    assert pi("start", "--workflow", "v2", *P(d))[0] == 0
    code, out = pi("explore-init", "--phase", "structure", "--targets", "US-001=로그인 AC-001 화면", *P(d))
    check("K3 라벨에 요구사항 ID를 넣으면 거부(라벨은 표시용)", code == 2 and out["error"] == "invalid_target_label", out)
    code, out = pi("explore-init", "--phase", "structure", "--targets", "=로그인 화면", *P(d))
    check("K4 ID 없이 라벨만으로 대상 지정 불가", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = pi("explore-init", "--phase", "structure", "--targets", "US-001+FLOW-001-S1=로그인 화면,US-002=대진 화면", *P(d))
    tg = out.get("targets") or []
    brief = (d / "design-explore/S01/brief.md").read_text() if code == 0 else ""
    man = json.loads((d / "design-explore/explore.manifest.json").read_text()) if code == 0 else {}
    check("K5 대상 라벨은 표시 이름, 근거는 앵커 ID 그대로(source_label 별도)", code == 0 and tg[0]["label"] == "로그인 화면" and tg[0]["anchor"] == ["US-001", "FLOW-001-S1"]
          and tg[0]["source_label"] != "로그인 화면" and "사용자 지정" in tg[0]["basis"][0], tg)
    check("K6 AC 후보 계산(앵커 US → US·FR을 추적하는 AC): T1=AC-001·AC-002, T2=AC-003·AC-004, manifest 분류 자리와 brief 목록",
          sorted(man["rounds"]["S01"]["coverage"]["T1"]["acs"]) == ["AC-001", "AC-002"] and sorted(man["rounds"]["S01"]["coverage"]["T2"]["acs"]) == ["AC-003", "AC-004"]
          and "T1 요구사항 후보(AC)" in brief and "모두 필수가 아닙니다" in brief, man.get("rounds", {}).get("S01", {}).get("coverage"))
    for lb in "ABC":
        write_cov_variant(d, "S01", lb, COV_LAYOUT[lb])
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("K7 후보를 분류하지 않으면 오류(coverage_unclassified) — 모든 AC를 필수로 간주하지 않고 분류를 요구", code == 2 and errs_of(out).count("coverage_unclassified") == 4, errs_of(out)[:400])
    bad = copy.deepcopy(COV)
    bad["T1"]["acs"]["AC-002"]["note"] = ""
    bad["T2"]["items"] = []
    set_cov(d, "S01", bad)
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("K8 위임·비UI는 사유 필요(coverage_note_missing), required인데 항목 없음(coverage_item_missing)",
          code == 2 and "coverage_note_missing" in errs_of(out) and "coverage_item_missing" in errs_of(out), errs_of(out)[:500])
    set_cov(d, "S01", COV)
    code, out = pi("explore-check", "--round", "S01", *P(d))
    e = errs_of(out)
    check("K9 필수 항목(T2 R2 생성된 대진 결과)이 HTML에 없는 시안 C만 required_missing, A·B는 통과",
          code == 2 and out["variants"]["A"]["ok"] and out["variants"]["B"]["ok"] and not out["variants"]["C"]["ok"]
          and "S01-C: T2 필수 항목 R2" in e and "required_missing" in e and out["variants"]["C"]["coverage"]["T2"]["missing"] == ["R2"], e[:500])
    c2 = copy.deepcopy(COV)
    c2["T2"]["acs"]["AC-004"] = {"status": "other_target", "note": "다른 화면의 결정성 요구"}
    set_cov(d, "S01", c2)
    code2, out2 = pi("explore-check", "--round", "S01", *P(d))
    set_cov(d, "S01", COV)
    check("K10b other_target(이 장면과 무관)은 사유와 함께 공개 목록(not_ui)으로, 사용자 확인 대상은 아님",
          any("AC-004" in x and "무관" in x for x in out2["coverage"]["not_ui"]) and not any("AC-004" in x for x in out2["coverage"]["confirmations"]), out2.get("coverage"))
    check("K10 위임(delegated) 항목은 사용자 확인 대상, 비UI는 정보로 분리", any("AC-002" in c and "위임" in c for c in out["coverage"]["confirmations"])
          and any("AC-004" in x for x in out["coverage"]["not_ui"]), out.get("coverage"))
    # manifest에만 있는 선언은 덮은 것으로 보지 않음
    write_cov_variant(d, "S01", "C", COV_LAYOUT["C"], extra_decl=[{"id": "e3", "target": "T2", "kind": "info", "refs": ["AC-003"], "covers": ["R2"], "sample": True}])
    code, out = pi("explore-check", "--round", "S01", *P(d))
    e = errs_of(out)
    check("K11 manifest에만 선언하고 HTML에 없는 요소: element_missing + 여전히 required_missing(선언만으로 통과 안 함)",
          code == 2 and "S01-C: 선언한 요소 e3가 HTML에 없습니다(element_missing)" in e and "S01-C: T2 필수 항목 R2" in e, e[:500])
    # covers 불일치
    lay = copy.deepcopy(COV_LAYOUT["C"]) + [("e3", "T2", "info", ["FR-001"], "main", ["R2"], '<ol data-el="e3" data-sample><li>x</li></ol>'),
                                           ("e5", "T2", "info", ["AC-003"], "main", ["R1"], '<p data-el="e5">설명</p>')]
    write_cov_variant(d, "S01", "C", lay)
    code, out = pi("explore-check", "--round", "S01", *P(d))
    e = errs_of(out)
    check("K12 근거가 겹치지 않는 covers(cover_ref_mismatch)·정보 요소로 행동 항목 덮기(cover_kind_mismatch)는 덮은 것으로 보지 않음",
          "cover_ref_mismatch" in e and "cover_kind_mismatch" in e and "required_missing" in e, e[:500])
    lay2 = copy.deepcopy(COV_LAYOUT["C"]) + [("e3", "T2", "info", ["AC-003"], "main", ["R2"], '<table data-el="e3" data-sample><tr><td>x</td></tr></table>'),
                                            ("e9", "T2", "action", ["AC-003"], "main", None, '<button>공유</button>')]
    write_cov_variant(d, "S01", "C", lay2[:-1])
    (d / "design-explore/S01/C/index.html").write_text((d / "design-explore/S01/C/index.html").read_text().replace("</section></body>", "<button>공유</button></section></body>"))
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("K13 HTML에 있지만 근거 없는 요소는 기존대로 차단(unbacked_element)", code == 2 and "unbacked_element" in errs_of(out), errs_of(out)[:300])
    write_cov_variant(d, "S01", "C", COV_LAYOUT["C"])

    # 선택: 누락 시안 차단, 위임 확인 문장 필요, 정상 시안 선택
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    write_critique(d, "S01", "ABC")
    shot = d / "captures" / "cap21.png"  # 증거는 프로젝트 안 파일만(파일럿 보완: 경로 범위)
    shot.parent.mkdir(exist_ok=True)
    shot.write_bytes(png_bytes())
    code, out = pi("explore-choose", "--round", "S01", "--variant", "C", "--note", "C안", "--evidence", str(shot), "--coverage-note", "확인", *P(d))
    check("K14 필수 정보가 빠진 시안(C)은 선택 불가(exploration_check_failed: required_missing)", code == 2 and out["error"] == "exploration_check_failed"
          and any("required_missing" in x for x in out["errors"]), out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로", "--evidence", str(shot), *P(d))
    check("K15 위임·불확실 해석이 있으면 사용자 확인 문장 없이 선택 불가(coverage_confirmation_required)", code == 2 and out["error"] == "coverage_confirmation_required"
          and out["confirmations"], out)
    appr0 = approvals(state(d))
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로", "--evidence", str(shot),
                   "--coverage-note", "인증 실패 안내는 오류 상태에서 다루는 것에 동의합니다", *P(d))
    ch = state(d)["exploration"]["structure"]["choice"] or {}
    check("K16 정상 시안은 기존처럼 선택 가능, 커버리지 결과·확인 문장 기록, 승인 불변", code == 0 and ch.get("id") == "EXP-S01-A"
          and ch["coverage"]["variants"]["A"]["T2"]["missing"] == [] and ch["coverage"]["confirmation_statement"].startswith("인증 실패")
          and approvals(state(d)) == appr0 and state(d)["stages"]["ux_planning"]["status"] == "in_progress", out)
    code, out = pi("explore-compare", "--round", "S01", *P(d))
    cmp_html = (d / "design-explore/S01/compare.html").read_text()
    check("K17 비교 페이지: 대상 라벨·근거 ID·기획 문장, 시안별 필수 충족(누락 표시), 사용자 확인 목록",
          "T1 · 로그인 화면" in cmp_html and "근거 US-001, FLOW-001-S1" in cmp_html and "필수 2/2" in cmp_html and "누락 R2" in cmp_html
          and "사용자 확인이 필요한 요구사항 해석" in cmp_html, out)

    # P1: 한국어 유형·프로젝트 설정 우선
    sty = EX.screen_types(d)
    check("K18 한국어 유형 판별 보강: '명단 화면을 엽니다' browse, '마이페이지' hub, '청백 기록을 저장' input",
          EX.classify("운영진이 명단 화면을 엽니다", sty["types"]) == "browse" and EX.classify("회원이 마이페이지를 엽니다", sty["types"]) == "hub"
          and EX.classify("결과를 저장합니다", sty["types"]) == "input")
    (d / "design-profile").mkdir(exist_ok=True)
    (d / "design-profile/screen-types.json").write_text(json.dumps({"format": "design-screen-types/v1", "extends": "default",
                                                                     "types": {"start": {"label": "시작", "keywords": ["홈"]}}, "assign": {"FLOW-002-S1": "start"}}))
    sty = EX.screen_types(d)
    tg = EX.structure_targets(d, 2, None, sty)
    check("K19 프로젝트 screen-types 우선: 동점이면 프로젝트 유형, assign 지정이 판별보다 우선, 자동 선정 근거 출력",
          EX.classify("홈 진입 홈 표시", sty["types"]) == "start" and any(t["anchor"][0] == "FLOW-002-S1" and t["type"] == "start" for t in tg)
          and all(t["basis"] for t in tg), tg)


# ---------------------------------------------------------------- EX3 레퍼런스 기반 탐색
def img_png(rgb=(255, 255, 255), w=1, h=1, pad=0) -> bytes:
    import struct
    import zlib

    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xffffffff)
    rows = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b"") + b"\x00" * pad)


JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x11\x08\x00\x10\x00\x20\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xd9")
WEBP = b"RIFF" + (22).to_bytes(4, "little") + b"WEBPVP8X" + (10).to_bytes(4, "little") + b"\x00" * 4 + (39).to_bytes(3, "little") + (19).to_bytes(3, "little")


def it(i, axis, basis, conf, stt):
    return {"id": i, "axis": axis, "basis": basis, "confidence": conf, "statement": stt, "evidence": "화면 상단·목록 영역"}


def extraction(rid: str, sha: str, items, excluded=None, cand=None) -> dict:
    return {"format": "design-reference-extract/v1", "ref": rid, "sha256": sha, "extracted_by": {"model": "test-model"},
            "items": items, "excluded": excluded or [], "system_candidates": cand or {}}


def ref_variant(d: Path, rid: str, lb: str, **kw) -> None:
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    man["rounds"][rid]["variants"][lb].update(kw)
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def ex3(root: Path) -> None:
    import pd_reference as RF
    # 형식 판정(매직 바이트)
    check("R1 형식 판정은 파일 앞부분으로(PNG·JPEG·WebP 크기 읽기, 확장자 무관)",
          RF.sniff(img_png(w=3, h=2)) == ("png", 3, 2) and RF.sniff(JPEG) == ("jpeg", 32, 16) and RF.sniff(WEBP) == ("webp", 40, 20)
          and RF.sniff(b"GIF89a....")[0] is None)

    dv1 = T.make_product(root, "ref-v1")
    assert pi("start", *P(dv1))[0] == 0
    before = raw(dv1)
    code, out = pi("explore-ref", "list", *P(dv1))
    check("R2 v1 프로젝트는 레퍼런스 명령 거부(exploration_disabled), 상태 불변", code == 2 and out["error"] == "exploration_disabled" and raw(dv1) == before, out)

    d = T.make_product(root, "ref-flow")
    assert pi("start", "--workflow", "v2", *P(d))[0] == 0
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    assert pi("done", "--path", UXP, *P(d))[0] == 0
    appr0 = approvals(state(d))
    up = root / "uploads"
    up.mkdir()
    (up / "fake.png").write_bytes(b"not an image at all")
    (up / "big.png").write_bytes(img_png(pad=600))
    (up / "secret-name-REF.png").write_bytes(img_png((20, 160, 140), 4, 4))
    (up / "second.webp").write_bytes(WEBP)
    (up / "third.jpg").write_bytes(JPEG)
    code, out = pi("explore-ref", "add", "--file", str(up / "fake.png"), *P(d))
    check("R3 이미지가 아닌 파일(.png 확장자) → unsupported_format, 아무것도 만들지 않음", code == 2 and out["error"] == "unsupported_format"
          and not (d / "design-explore/references").exists(), out)
    code, out = pi("explore-ref", "policy", "--limit", "reference_max_bytes=300", *P(d))
    check("R4 상한 변경은 사용자 문장 필요", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = pi("explore-ref", "policy", "--limit", "reference_max_bytes=300", "--note", "작은 이미지만 받습니다", *P(d))
    code2, out2 = pi("explore-ref", "add", "--file", str(up / "big.png"), *P(d))
    check("R5 프로젝트별 크기 상한(policy) → 초과 이미지 reference_too_large", code == 0 and code2 == 2 and out2["error"] == "reference_too_large", (out, out2))
    pi("explore-ref", "policy", "--limit", "reference_max_bytes=10485760", "--limit", "reference_formats=png,webp", "--note", "기본값으로 되돌림, jpeg 제외", *P(d))
    code, out = pi("explore-ref", "add", "--file", str(up / "third.jpg"), *P(d))
    check("R6 프로젝트 허용 형식 밖(jpeg 제외 정책) → unsupported_format", code == 2 and out["error"] == "unsupported_format", out)
    code, out = pi("explore-ref", "add", "--file", str(up / "secret-name-REF.png"), "--rights", "maybe", *P(d))
    check("R7 권리 상태는 own·licensed·reference_only·unknown 중 하나", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = pi("explore-ref", "add", "--file", str(up / "secret-name-REF.png"), *P(d))
    st = state(d)
    ref = (st["exploration"].get("references") or {}).get("REF-001") or {}
    rj = (d / "design-explore/references/REF-001/reference.json").read_text() if code == 0 else ""
    gi = (d / "design-explore/.gitignore").read_text() if code == 0 else ""
    import hashlib
    check("R8 등록: REF-001, 격리 경로 original.png, SHA-256·형식·크기 기록, 권리 미상 경고, 원본 Git 제외, 사용자 파일 이름 미기록",
          code == 0 and out["reference"] == "REF-001" and ref.get("path") == "design-explore/references/REF-001/original.png"
          and ref["sha256"] == hashlib.sha256((up / "secret-name-REF.png").read_bytes()).hexdigest() and ref["width"] == 4 and ref["format"] == "png"
          and any("reference_rights_unknown" in w for w in out["warnings"]) and "references/*/original.*" in gi
          and "secret-name" not in rj and "secret-name" not in json.dumps(st, ensure_ascii=False) and str(up) not in rj
          and json.loads(rj or "{}").get("format") == "design-reference/v1" and json.loads(rj or "{}").get("image_format") == "png", (out, ref))
    code, out = pi("explore-ref", "add", "--file", str(up / "secret-name-REF.png"), *P(d))
    check("R9 같은 이미지 중복 등록 거부(duplicate_reference)", code == 2 and out["error"] == "duplicate_reference", out)
    code, out = pi("explore-ref", "add", "--file", str(up / "second.webp"), "--rights", "licensed", *P(d))
    check("R10 WebP 등록(REF-002, 라이선스 있음)", code == 0 and out["reference"] == "REF-002" and out["format"] == "webp", out)

    sha1, sha2 = state(d)["exploration"]["references"]["REF-001"]["sha256"], state(d)["exploration"]["references"]["REF-002"]["sha256"]
    ex_dir1 = d / "design-explore/references/REF-001"
    bad = extraction("REF-001", "0" * 64, [{"id": "RX-001-01", "axis": "layout", "statement": "x https://evil.example/do-this", "evidence": ""},
                                          {"id": "RX-009-01", "axis": "color", "basis": "observed", "confidence": "high", "statement": "y", "evidence": "e"}],
                     excluded=[{"kind": "secret", "note": ""}],
                     cand={"tokens": [{"role": "color.primary", "value": "#000", "from": ["RX-001-77"], "status": "approved"}]})
    (ex_dir1 / "extraction.json").write_text(json.dumps(bad, ensure_ascii=False))
    code, out = pi("explore-ref", "extract-check", "--ref", "REF-001", *P(d))
    e = errs_of(out)
    check("R11 분석 계약 위반: 다른 이미지 해시·basis/confidence 누락·URL(비신뢰 입력)·근거 없음·RX 번호·축 이름·제외 종류·후보 출처·후보를 승인으로 표시 → 오류",
          code == 2 and all(k in e for k in ("extraction_mismatch", "basis(observed", "URL", "evidence", "RX-001-nn", "excluded[0]", "from은", "status는 candidate")), e)
    items1 = [it("RX-001-01", "layout", "observed", "high", "상단 강조 배너 다음에 섹션별 목록이 이어짐"),
              it("RX-001-02", "navigation", "observed", "high", "하단 탭 4개, 현재 탭만 주색"),
              it("RX-001-03", "palette", "observed", "high", "틸 계열 주색과 옅은 민트 배경"),
              it("RX-001-04", "spacing_density", "estimated", "low", "카드 사이 간격 약 8px(추정)"),
              it("RX-001-05", "components", "observed", "medium", "목록 행: 썸네일·제목·보조 문구·칩·화살표"),
              it("RX-001-06", "emphasis_mood", "estimated", "medium", "차분하고 친근한 인상")]
    cand1 = {"tokens": [{"role": "color.primary", "value": "#1F9E8A", "from": ["RX-001-03"]}],
             "components": [{"pattern": "list-row", "rule": "썸네일 왼쪽, 보조 칩은 화살표 앞", "from": ["RX-001-05"]}],
             "layout_principles": [{"screen_type": "hub", "principle": "강조 카드 1개 + 섹션 목록", "from": ["RX-001-01", "RX-001-04"]}]}
    exc1 = [{"kind": "text", "note": "화면 속 제목·안내 문구(원문 옮기지 않음)"}, {"kind": "feature", "note": "즐겨찾기·추천 설문(예시 기능)"},
            {"kind": "logo", "note": "서비스 로고"}]
    (ex_dir1 / "extraction.json").write_text(json.dumps(extraction("REF-001", sha1, items1, exc1, cand1), ensure_ascii=False))
    code, out = pi("explore-ref", "extract-check", "--ref", "REF-001", *P(d))
    check("R12 올바른 분석 통과: 7개 축 분류, 저신뢰·추정 항목은 확인 필요(RX-001-04, RX-001-06), 제외 3건",
          code == 0 and out["needs_confirm"] == ["RX-001-04", "RX-001-06"] and out["axes"]["navigation"] == ["RX-001-02"] and out["excluded"] == 3, out)
    items2 = [it("RX-002-01", "emphasis_mood", "observed", "high", "숫자 하나를 크게 강조"), it("RX-002-02", "layout", "observed", "high", "2열 격자")]
    (d / "design-explore/references/REF-002/extraction.json").write_text(json.dumps(extraction("REF-002", sha2, items2), ensure_ascii=False))
    assert pi("explore-ref", "extract-check", "--ref", "REF-002", *P(d))[0] == 0

    # 원본 해시 재검증
    orig = (ex_dir1 / "original.png").read_bytes()
    (ex_dir1 / "original.png").write_bytes(orig + b"x")
    code, out = pi("explore-ref", "extract-check", "--ref", "REF-001", *P(d))
    check("R13 격리 경로 원본이 바뀌면 재검증 실패(original_modified)", code == 2 and out["error"] == "reference_original_invalid" and "original_modified" in out["message"], out)
    (ex_dir1 / "original.png").write_bytes(orig)

    # 참고 의도
    code, out = pi("explore-ref", "intent", "--use", "REF-001=layout", *P(d))
    check("R14 참고 의도는 사용자 문장 필요(엔진·Claude가 추정 기록하지 않음)", code == 2 and out["error"] == "statement_required", out)
    code, out = pi("explore-ref", "intent", "--use", "REF-001=layout,navigation", "--use", "REF-002=layout,emphasis_mood", "--note", "둘 다 참고", *P(d))
    check("R15 같은 축(layout)을 두 레퍼런스에서 가져오면 거부(axis_conflict), 의도 미기록", code == 2 and out["error"] == "axis_conflict"
          and not state(d)["exploration"]["intents"], out)
    code, out = pi("explore-ref", "intent", "--use", "REF-001=layout,colour", "--note", "x", *P(d))
    check("R16 알 수 없는 축 거부", code == 2 and out["error"] == "invalid_arguments", out)
    pi("explore-ref", "policy", "--limit", "references_per_round=1", "--note", "한 장만", *P(d))
    code, out = pi("explore-ref", "intent", "--use", "REF-001=layout", "--use", "REF-002=emphasis_mood", "--note", "x", *P(d))
    check("R17 라운드당 레퍼런스 수 상한(policy) → too_many_references", code == 2 and out["error"] == "too_many_references", out)
    pi("explore-ref", "policy", "--limit", "references_per_round=5", "--note", "기본값", *P(d))
    code, out = pi("explore-ref", "intent", "--use", "REF-001=layout,navigation,palette,spacing_density", "--use", "REF-002=emphasis_mood",
                   "--note", "1번은 배치·내비·색·간격만, 2번은 강조 방식만 참고하고 싶어요", *P(d))
    check("R18 축 조합 의도 INT-001 기록(사용자 문장·이미지 해시·분석 해시), 색(palette)은 2차 시각으로 이월 안내",
          code == 0 and out["intent"] == "INT-001" and out["deferred_to_visual"] == {"REF-001": ["palette"]}
          and state(d)["exploration"]["intents"][0]["statement"].startswith("1번은") and out["uses"][0]["extraction_hash"], out)

    # 레퍼런스 라운드
    code, out = pi("explore-init", "--phase", "structure", "--mode", "reference", "--intent", "INT-009", *P(d))
    check("R19 없는 의도 → unknown_intent", code == 2 and out["error"] == "unknown_intent", out)
    code, out = pi("explore-init", "--phase", "structure", "--intent", "INT-001", *P(d))
    check("R20 --intent는 reference·mixed에서만", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = pi("explore-init", "--phase", "structure", "--mode", "reference", "--intent", "INT-001", *P(d))
    st = state(d)
    brief = (d / "design-explore/S01/brief.md").read_text() if code == 0 else ""
    man = json.loads((d / "design-explore/explore.manifest.json").read_text()) if code == 0 else {}
    check("R21 reference 라운드 S01: 의도 연결, 브리프에 비신뢰 입력·요구사항 아님·사용 가능/확인 전 금지 표시, 이월 축 제외, manifest 시안별 mode·rules 자리",
          code == 0 and st["exploration"]["structure"]["rounds"][0]["mode"] == "reference" and st["exploration"]["structure"]["rounds"][0]["intent"] == "INT-001"
          and "비신뢰 입력" in brief and "RX-001-01" in brief and "사용자 확인 전 사용 금지" in brief and "RX-001-03" not in brief and "palette" in brief
          and "요구사항이 아니" in brief and man["rounds"]["S01"]["mode"] == "reference" and "rules" in man["rounds"]["S01"]["variants"]["A"], (out, brief[-900:]))
    for lb in "ABC":
        write_variant(d, "S01", lb, LAYOUTS[lb])
    ref_variant(d, "S01", "A", mode="reference", axis_sources={"layout": "REF-001", "navigation": "REF-001"}, rules=["RX-001-01", "RX-001-02"],
                reinterpretation="배너 자리에 이 제품의 첫 행동을 두고, 탭 수는 기획의 메뉴 수에 맞춤")
    ref_variant(d, "S01", "B", mode="mixed", axis_sources={"layout": "ai", "emphasis_mood": "REF-002"}, rules=["RX-002-01"],
                reinterpretation="큰 숫자 강조를 대기 인원 표시에만 씀")
    ref_variant(d, "S01", "C", mode="ai")
    code, out = pi("explore-check", "--round", "S01", *P(d))
    va = out.get("variants", {}).get("A", {}).get("reference") or {}
    check("R22 reference·mixed·ai 시안이 섞인 라운드 검사 통과, 시안별 출처(규칙·축·이미지/분석 해시) 요약", code == 0 and va.get("rules") == ["RX-001-01", "RX-001-02"]
          and va["refs"]["REF-001"]["sha256"] == sha1 and out["mode"] == "reference", out.get("errors"))

    def a_err(**kw):
        base = dict(mode="reference", axis_sources={"layout": "REF-001", "navigation": "REF-001"}, rules=["RX-001-01", "RX-001-02"], reinterpretation="재해석")
        base.update(kw)
        ref_variant(d, "S01", "A", **base)
        c, o = pi("explore-check", "--round", "S01", *P(d))
        return c, errs_of(o)
    c, e = a_err(rules=["RX-001-01", "RX-001-04"])
    check("R23 저신뢰 추정 항목을 사용자 확인 없이 쓰면 오류(reference_unconfirmed)", c == 2 and "reference_unconfirmed" in e and "RX-001-04" in e, e)
    c, e = a_err(rules=["RX-001-01", "RX-001-03"])
    check("R24 색(palette) 규칙을 1차 구조 시안에 쓰면 오류(scope_deferred_to_visual)", c == 2 and "scope_deferred_to_visual" in e, e)
    c, e = a_err(rules=["RX-001-01", "RX-002-02"], axis_sources={"layout": "REF-001", "components": "REF-002"})
    check("R25 의도 범위 밖 규칙(REF-002의 layout)·축 출처 → reference_scope_violation", c == 2 and e.count("reference_scope_violation") >= 2, e)
    c, e = a_err(reinterpretation="")
    check("R26 재해석 기록 없으면 오류(reinterpretation_missing)", c == 2 and "reinterpretation_missing" in e, e)
    c, e = a_err(rules=[])
    check("R27 reference 시안인데 규칙이 없으면 오류", c == 2 and "rules" in e, e)
    ref_variant(d, "S01", "B", mode="mixed", axis_sources={"emphasis_mood": "REF-002"}, rules=["RX-002-01"], reinterpretation="x")
    c, e = a_err()
    check("R28 mixed 시안은 AI 축과 레퍼런스 축이 모두 필요", c == 2 and "mixed 시안" in e, e)
    ref_variant(d, "S01", "B", mode="mixed", axis_sources={"layout": "ai", "emphasis_mood": "REF-002"}, rules=["RX-002-01"], reinterpretation="큰 숫자 강조를 대기 인원 표시에만 씀")
    shutil.copyfile(ex_dir1 / "original.png", d / "design-explore/S01/A/hero.png")
    c, e = a_err()
    check("R29 시안 폴더에 원본 사본 → reference_asset_embedded", c == 2 and "reference_asset_embedded" in e and "hero.png" in e, e)
    (d / "design-explore/S01/A/hero.png").unlink()
    import base64
    css0 = (d / "design-explore/S01/A/styles.css").read_text()
    (d / "design-explore/S01/A/styles.css").write_text(css0 + ".h{background:url(data:image/png;base64," + base64.b64encode(orig).decode() + ")}\n")
    c, e = a_err()
    check("R30 data: URI로 원본을 넣어도 reference_asset_embedded", c == 2 and "data URI" in e, e)
    (d / "design-explore/S01/A/styles.css").write_text(css0)
    r_ai = {"id": "S09", "mode": "ai"}
    E_, _, _ = RF.reference_variant_errors(d, state(d), r_ai, "A", {"rules": ["RX-001-01"], "mode": "reference"}, "structure")
    check("R31 AI 라운드 시안은 레퍼런스 규칙을 쓸 수 없음", E_ and "AI 라운드" in E_[0], E_)

    # 디자인 시스템 후보(EX5용, 승인 아님)
    code, out = pi("explore-ref", "candidates", *P(d))
    cf = json.loads((d / "design-explore/references/system-candidates.json").read_text()) if code == 0 else {}
    check("R32 디자인 시스템 후보 파일: 토큰·컴포넌트 규칙·화면 유형별 레이아웃 원칙 분리, approved false·status candidate, 확인 전 출처 표시",
          code == 0 and cf["approved"] is False and cf["status"] == "candidate" and len(cf["tokens"]) == 1 and len(cf["components"]) == 1
          and cf["layout_principles"][0]["pending_confirm"] == ["RX-001-04"] and cf["layout_principles"][0]["usable"] is False
          and cf["tokens"][0]["usable"] is True and "Design Direction" in cf["note"], cf)
    check("R33 후보 생성은 Design Direction·승인 기록을 바꾸지 않음", approvals(state(d)) == appr0 and state(d)["stages"]["design_direction"]["status"] == "locked")

    # 사용자 확인·거부
    code, out = pi("explore-ref", "confirm", "--ref", "REF-001", "--items", "RX-001-04", "--decision", "confirmed", *P(d))
    check("R34 확인은 사용자 문장 필요", code == 2 and out["error"] == "invalid_arguments", out)
    code, out = pi("explore-ref", "confirm", "--ref", "REF-001", "--items", "RX-001-99", "--decision", "confirmed", "--note", "네", *P(d))
    check("R35 분석에 없는 항목 확인 거부", code == 2 and out["error"] == "unknown_rule", out)
    assert pi("explore-ref", "confirm", "--ref", "REF-001", "--items", "RX-001-04", "--decision", "confirmed", "--note", "간격은 그 정도로 보는 게 맞아요", *P(d))[0] == 0
    c, e = a_err(rules=["RX-001-01", "RX-001-02", "RX-001-04"], axis_sources={"layout": "REF-001", "navigation": "REF-001", "spacing_density": "REF-001"})
    check("R36 사용자 확인 뒤에는 추정 항목 사용 가능", c == 0, e)
    assert pi("explore-ref", "confirm", "--ref", "REF-001", "--items", "RX-001-02", "--decision", "rejected", "--note", "탭 구성은 참고하지 않을래요", *P(d))[0] == 0
    c, e = a_err(rules=["RX-001-01", "RX-001-02", "RX-001-04"], axis_sources={"layout": "REF-001", "navigation": "REF-001", "spacing_density": "REF-001"})
    check("R37 사용자가 거부한 규칙 사용 → reference_rule_rejected", c == 2 and "reference_rule_rejected" in e, e)
    a_err(rules=["RX-001-01", "RX-001-04"], axis_sources={"layout": "REF-001", "spacing_density": "REF-001", "navigation": "ai"})
    # 분석이 의도 이후 바뀜
    ej = (ex_dir1 / "extraction.json").read_text()
    (ex_dir1 / "extraction.json").write_text(ej.replace("약 8px", "약 12px"))
    c, o = pi("explore-check", "--round", "S01", *P(d))
    check("R38 의도 기록 뒤 분석 파일이 바뀌면 오류(reference_extraction_changed)", c == 2 and "reference_extraction_changed" in errs_of(o), errs_of(o))
    (ex_dir1 / "extraction.json").write_text(ej)
    c, o = pi("explore-check", "--round", "S01", *P(d))
    assert c == 0, errs_of(o)

    # 선택: 개인정보 점검(모델·사용자) 필요
    write_critique(d, "S01", "ABC")
    shot = d / "captures" / "ref-capture.png"  # 증거는 프로젝트 안 파일만(파일럿 보완: 경로 범위)
    shot.parent.mkdir(exist_ok=True)
    shot.write_bytes(img_png((1, 2, 3)))
    choose = ("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로 하겠습니다", "--evidence", str(shot))
    code, out = pi(*choose, *P(d))
    check("R39 개인정보 점검 기록 없이 레퍼런스 시안 선택 거부(reference_privacy_unconfirmed)", code == 2 and out["error"] == "reference_privacy_unconfirmed", out)
    pi("explore-ref", "privacy", "--ref", "REF-001", "--by", "model", "--result", "none", "--note", "얼굴·실명·연락처 없음, 예시 이름만", *P(d))
    code, out = pi(*choose, *P(d))
    check("R40 모델 점검만으로는 선택 불가(사용자 확인 필요, U4)", code == 2 and out["error"] == "reference_privacy_unconfirmed", out)
    pi("explore-ref", "privacy", "--ref", "REF-002", "--by", "model", "--result", "suspected", "--note", "사람 얼굴로 보이는 영역", *P(d))
    pi("explore-ref", "privacy", "--ref", "REF-002", "--by", "user", "--result", "confirmed", "--note", "실제 회원 사진 맞아요", *P(d))
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로", "--evidence", str(shot), *P(d))
    check("R41 사용자가 개인정보가 있다고 확인한 레퍼런스를 쓴 시안은 선택 거부(reference_privacy_flagged)", code == 2 and out["error"] == "reference_privacy_flagged", out)
    pi("explore-ref", "privacy", "--ref", "REF-001", "--by", "user", "--result", "none", "--note", "개인정보 없습니다", *P(d))
    code, out = pi(*choose, *P(d))
    st = state(d)
    ch = st["exploration"]["structure"]["choice"] or {}
    prov = ch.get("reference") or {}
    sel = json.loads((d / "design-explore/S01/selection/selection.json").read_text()) if code == 0 else {}
    check("R42 선택 기록에 출처 연결: REF-001(이미지·분석 해시·권리·개인정보) → RX 규칙 → INT-001(사용자 문장) → 시안 A(재해석) → EXP-S01-A",
          code == 0 and ch["id"] == "EXP-S01-A" and ch["mode"] == "reference" and prov["intent"] == "INT-001" and prov["statement"].startswith("1번은")
          and prov["refs"]["REF-001"]["sha256"] == sha1 and prov["refs"]["REF-001"]["confirmations"] == {"RX-001-04": "confirmed", "RX-001-02": "rejected"}
          and prov["variants"]["A"]["rules"] == ["RX-001-01", "RX-001-04"] and prov["variants"]["A"]["reinterpretation"]
          and "design-explore/references/REF-001/extraction.json" in ch["retention"] and sel.get("reference", {}).get("intent") == "INT-001", (out, prov))
    check("R43 선택은 승인이 아님(승인·제출·revision·해시 불변, Design Direction locked)", approvals(st) == appr0)
    check("R44 원본은 보존 집합·선택 기록 해시 대상 아님(Git 제외 유지)", not any("original." in k for k in ch["retention"]) and "references/*/original.*" in (d / "design-explore/.gitignore").read_text())

    # 추적(원본 Git 포함) 조건
    code, out = pi("explore-ref", "track", "--ref", "REF-001", "--note", "넣어 주세요", *P(d))
    check("R45 권리 미상 원본은 Git 추적 불가(track_not_allowed)", code == 2 and out["error"] == "track_not_allowed", out)
    code, out = pi("explore-ref", "track", "--ref", "REF-002", "--note", "넣어 주세요", *P(d))
    check("R46 라이선스가 있어도 개인정보가 확인된 원본은 추적 불가", code == 2 and out["error"] == "track_not_allowed", out)
    pi("explore-ref", "privacy", "--ref", "REF-002", "--by", "model", "--result", "none", "--note", "다시 보니 일러스트", *P(d))
    pi("explore-ref", "privacy", "--ref", "REF-002", "--by", "user", "--result", "none", "--note", "일러스트예요, 사진 아님", *P(d))
    code, out = pi("explore-ref", "track", "--ref", "REF-002", "--note", "직접 만든 이미지라 저장소에 넣습니다", *P(d))
    check("R47 권리 licensed + 개인정보 모델·사용자 모두 없음 + 사용자 문장 → 추적 예외(.gitignore 부정 규칙)",
          code == 0 and "!references/REF-002/original.webp" in (d / "design-explore/.gitignore").read_text(), out)

    # 제품 코드로 원본 복사 → 오염 판정(D4)
    (d / "frontend/src").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ex_dir1 / "original.png", d / "frontend/src/hero.png")
    cont = EX.explore_contamination(d, ["frontend/src/hero.png"])
    check("R48 레퍼런스 원본을 제품 코드에 복사하면 reference_asset_embedded(EX6: preview-check·product-build 공통 판정, 이전 explore_copy보다 구체적)", cont and cont[0]["kind"] == "reference_asset_embedded"
          and "REF-001" in cont[0]["detail"], cont)
    (d / "frontend/src/hero.png").unlink()

    # 추적: UXD 근거 → 철회 시 trace 오류
    txt = (d / UXP).read_text()
    (d / UXP).write_text(txt.replace("- **근거**: 사용자 답변(라운드 1)", "- **근거**: 사용자 선택 EXP-S01-A(라운드 1)"))
    pi("done", "--path", UXP, *P(d))
    appr1 = approvals(state(d))  # 사용자가 UXD 문서를 고친 done 이후 기준(산출물 해시 갱신은 레퍼런스 기능과 무관)
    check("R48b done 전후에도 승인·제출 기록·revision 불변", {k: {x: v[x] for x in ("status", "revision", "approved", "submitted")} for k, v in appr1.items() if isinstance(v, dict) and "status" in v}
          == {k: {x: v[x] for x in ("status", "revision", "approved", "submitted")} for k, v in appr0.items() if isinstance(v, dict) and "status" in v})
    code, out = pi("trace", "--stage", "ux_planning", *P(d))
    check("R49 출처가 온전하면 trace 통과", code == 0, out)
    code, out = pi("explore-ref", "withdraw", "--ref", "REF-001", *P(d))
    check("R50 철회는 사유 필요", code == 2 and out["error"] == "statement_required", out)
    assert pi("explore-ref", "withdraw", "--ref", "REF-001", "--note", "이 이미지는 더 이상 쓰지 않기로 함", *P(d))[0] == 0
    code, out = pi("trace", "--stage", "ux_planning", *P(d))
    check("R51 근거 레퍼런스 철회 → trace 오류(reference_withdrawn), 선택·UXD 자동 변경 없음",
          code == 2 and any("reference_withdrawn" in x for x in out["errors"]) and state(d)["exploration"]["structure"]["choice"]["id"] == "EXP-S01-A", out)
    code, out = pi("explore-init", "--phase", "structure", "--mode", "reference", "--intent", "INT-001", *P(d))
    check("R52 철회된 레퍼런스를 쓰는 의도로 새 라운드 불가", code == 2 and out["error"] == "reference_withdrawn", out)
    code, out = pi("explore-ref", "list", *P(d))
    check("R53 list: 원본 재검증·개인정보 상태 요약(읽기 전용)", code == 0 and out["references"]["REF-002"]["original"] == "ok"
          and out["references"]["REF-002"]["privacy"]["safe_confirmed"], out)
    check("R54 철회·추적·후보 이후에도 승인·제출 기록·revision·해시 불변", approvals(state(d)) == appr1)
    code, out = pi("impact", "--design", "--choice", "EXP-S01-A", *P(d))
    it0 = (out.get("items") or [{}])[0]
    check("R57 impact --design --choice(1차): ① 정보·행동, UX Planning부터 재검토, 선택을 근거로 한 UXD·화면 식별",
          code == 0 and [c["key"] for c in it0.get("categories", [])] == ["info_behavior"] and any(i["effective_stage"] == "ux_planning" for i in it0["impact"])
          and out["exploration"]["uxd"], out)
    # EX4 호환: 레퍼런스 라운드도 같은 측정 계약으로 측정, 측정 명세에 레퍼런스 원본을 넣지 않음
    (d / "tools").mkdir(exist_ok=True)
    (d / "tools/fake_measure.py").write_text(FAKE_ADAPTER)
    fake(d)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    rid = [r for r in state(d)["exploration"]["structure"]["rounds"] if r.get("mode") in ("reference", "mixed")][-1]["id"]
    code, out = pi("explore-verify", "--round", rid, *P(d))
    spec_text = (d / f"design-explore/{rid}/shots/{out.get('run_id')}/measure-spec.json").read_text() if code == 0 else ""
    code2, out2 = pi("explore-check", "--round", rid, *P(d))
    check("R55 EX4 호환: reference 라운드 측정 완료, 측정 명세에 레퍼런스 경로 없음, 레퍼런스 출처 검사는 그대로",
          code == 0 and out["status"] == "completed" and "references/" not in spec_text and '"mode": "reference"' in spec_text
          and any((v.get("reference") or {}).get("rules") for v in out2["variants"].values()), (out, out2.get("errors")))
    check("R56 측정 후에도 승인 기록 불변", approvals(state(d)) == appr1)


# ---------------------------------------------------------------- EX4 브라우저 측정·선택 게이트(가짜 어댑터: 명세를 읽어 시나리오대로 사실만 씀)
FAKE_ADAPTER = r"""
import json, os, struct, sys, time, zlib
from pathlib import Path
rd = Path(os.environ["PD_REPORT_DIR"]); spec = json.loads(Path(os.environ["PD_MEASURE_SPEC"]).read_text())
sc = json.loads(Path("fake.json").read_text()) if Path("fake.json").is_file() else {}
time.sleep(sc.get("sleep", 0))
if sc.get("no_report"):
    sys.exit(sc.get("exit", 0))
def png(w, h):
    def ch(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b"")
(rd / "shots").mkdir(exist_ok=True)
res = []
for p in spec["pages"]:
    for vp in spec["viewports"]:
        o = {**sc.get("all", {}), **sc.get("per", {}).get(p["variant"], {})}
        W, H, dpr = vp["width"], vp["height"], vp["dpr"]
        sw, sh = o.get("shot_size", [round(W * dpr), round(H * dpr)])
        shot = f"shots/{p['variant']}-{p['target']}-{vp['name']}.png"
        (rd / shot).write_bytes(png(sw, sh))
        lay_ids = {i for L in p["layouts"] for i in L["elements"]}
        els, y, y_prev, x_next = [], 0, 0, 0
        for e in p["elements"]:
            if e["id"] in o.get("hidden", []):
                els.append({"id": e["id"], "box": [0, 0, 0, 0], "visible": False})
                continue
            if e["id"] in lay_ids and x_next and not o.get("stack_layouts"):
                box, x_next = [x_next, y_prev, 10, 10], 0
            else:
                y += 20
                box, y_prev, x_next = [0, y, 10, 10], y, (12 if e["id"] in lay_ids else 0)
            els.append({"id": e["id"], "box": box, "visible": True, "reachable": e["id"] not in o.get("unreachable", []), "in_fixed": False,
                        "contains_fixed": False, "within": None, "contrast": o.get("contrast", 7.0), "font_size": 16, "font_weight": 400})
        if spec.get("asset_fallback") and sc.get("fallback_fail"):
            o = dict(o, render_failed=True)
        res.append({"variant": p["variant"], "target": p["target"], "viewport": vp["name"], "viewport_requested": {"width": W, "height": H, "dpr": dpr},
                    "viewport_actual": {"width": o.get("actual_width", W), "height": H, "dpr": dpr}, "method": spec["method"],
                    "rendered": not o.get("render_failed"), "console_errors": o.get("console", []), "a11y": o.get("a11y", {"critical": 0, "serious": 0}),
                    "a11y_tool": "fake", "overflow": False, "clipped": False, "touch_target_violations": 0,
                    "interactions": [{"name": "tap:" + e["id"], "element": e["id"], "passed": e["id"] not in o.get("tap_fail", []),
                                      "core": e["core"] and not o.get("downgrade_core")} for e in p["elements"] if e["kind"] in ("action", "navigation", "input")],
                    "screenshot": o.get("shot_path", shot),
                    "layout": {"scroll_width": W + o.get("overflow_px", 0), "client_width": W, "scroll_height": 200, "viewport_height": H, "elements": els,
                               "fixed": [{"label": "tabbar", "position": "fixed", "box": [0, 0, W, H]}] if o.get("fixed_cover") else [],
                               "touch": [{"el": "e2", "w": o.get("touch", 48), "h": 48}],
                               "components": o.get("components", {}).get(p["target"], [])},
                    "extensions": o.get("extensions", {})})
if sc.get("drop_last"):
    res = res[:-1]
rep = {"format": sc.get("format", "design-explore-report/v1"), "run_id": sc.get("run_id", os.environ["PD_RUN_ID"]), "tool": "fake",
       "status": sc.get("status", "completed"), "reason": "측정 도구 없음(가짜)", "results": res}
(rd / "report.json").write_text(json.dumps(rep, ensure_ascii=False))
"""
EX4_C = COV_LAYOUT["C"] + [("e3", "T2", "info", ["AC-003"], "main", ["R2"], '<table data-el="e3" data-sample><tr><td>x</td></tr></table>')]


def fake(d: Path, **sc) -> None:
    (d / "fake.json").write_text(json.dumps(sc, ensure_ascii=False))


def setup_measure(d: Path, cmd: str) -> None:
    code, out = pi("explore-config", "--measure-cmd", cmd, "--measure-viewports", "mobile=40x80@2,desktop=120x80@1", "--confirm", "--note", "가짜 측정 어댑터 사용", *P(d))
    assert code == 0, out


def cite_shots(d: Path, rid: str, run: str, labels) -> None:
    cp = d / f"design-explore/{rid}/critique.md"
    text = cp.read_text()
    for lb in labels:
        text = text.replace(f"## {rid}-{lb}\n", f"## {rid}-{lb}\n- **근거 스크린샷**: shots/{run}/shots/{lb}-T1-mobile.png\n", 1)
    cp.write_text(text)


def ex4(root: Path) -> None:
    import pd_measure as MS
    import pb_uiev
    # pb-ui-report/v1과 같은 필드·같은 분류(두 Skill이 같은 예시로 같은 결론)
    common = {"viewport": "mobile", "rendered": True, "console_errors": ["boom"], "a11y": {"critical": 1, "serious": 2}, "overflow": True, "clipped": True,
              "touch_target_violations": 3, "interactions": [{"name": "save", "passed": False, "core": True}, {"name": "hint", "passed": False, "core": False}]}
    rp = root / "pbui"
    rp.mkdir()
    (rp / "ui.json").write_text(json.dumps({"format": "pb-ui-report/v1", "run_id": "R1", "results": [common | {"screen": "SCR-001"}]}))
    pb = pb_uiev.parse_ui_report(rp / "ui.json", "R1", rp)["results"][0]
    B, W, _ = MS.common_findings(common, "x")
    check("M1 pb-ui-report/v1 공통 필드를 같은 분류로 판정(차단: 렌더·콘솔·critical·핵심 상호작용, 보고: serious·넘침·잘림·터치·비핵심)",
          sorted(B) == sorted(pb["blocking"]) and sorted(W) == sorted(pb["warnings"]) and "console_errors:1" in B and "interaction_failed:hint" in W, (B, W, pb))
    check("M2 열 수 계산: 같은 줄의 나란한 상자는 2열, 세로로 쌓이면 1열", MS.columns_of([[0, 0, 10, 10], [12, 1, 10, 10]]) == 2
          and MS.columns_of([[0, 0, 10, 10], [0, 20, 10, 10]]) == 1)

    d = T.make_product(root, "ex4")
    assert pi("start", "--workflow", "v2", *P(d))[0] == 0
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    code, out = pi("explore-init", "--phase", "structure", "--targets", "US-001+FLOW-001-S1=로그인 화면,US-002=대진 화면", *P(d))
    assert code == 0, out
    set_cov(d, "S01", COV)
    for lb, lay in (("A", COV_LAYOUT["A"]), ("B", COV_LAYOUT["B"]), ("C", EX4_C)):
        write_cov_variant(d, "S01", lb, lay)
    write_critique(d, "S01", "ABC")
    (d / "tools").mkdir()
    (d / "tools/fake_measure.py").write_text(FAKE_ADAPTER)
    shot = d / "captures" / "cap4.png"  # 증거는 프로젝트 안 파일만(파일럿 보완: 경로 범위)
    shot.parent.mkdir(exist_ok=True)
    shot.write_bytes(png_bytes())
    appr0 = approvals(state(d))
    hist0 = len(state(d)["history"])
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("M3 측정 명령이 없으면 시안 측정 상태 not_run(정적 검사는 그대로)", code == 0 and all(v["status"] == "not_run" for v in out["measurement"].values()), out.get("errors"))
    code, out = pi("explore-verify", "--round", "S01", *P(d))
    check("M4 측정 명령 없음 → not_run 기록(실패 아님, 종료 0)", code == 0 and out["status"] == "not_run"
          and state(d)["exploration"]["structure"]["rounds"][0]["measurements"][-1]["status"] == "not_run", out)

    # 측정 설정: 계획 → 문장 필요 → 기록, 승인 불변
    code, out = pi("explore-config", "--measure-cmd", "python3 tools/fake_measure.py", *P(d))
    check("M5 측정 명령 설정은 기본 계획만(dry_run)", code == 0 and out.get("dry_run") and not (state(d)["config"]["exploration"].get("measure_cmd")), out)
    code, out = pi("explore-config", "--measure-cmd", "python3 tools/fake_measure.py", "--confirm", *P(d))
    check("M6 측정 명령 설정은 사용자 문장 필요", code == 2 and out["error"] == "statement_required", out)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    check("M7 측정 설정 기록(명령·뷰포트), 승인·제출 기록·revision·해시 불변", state(d)["config"]["exploration"]["measure_cmd"].endswith("fake_measure.py")
          and state(d)["config"]["exploration"]["measure"]["viewports"][0] == {"name": "mobile", "width": 40, "height": 80, "dpr": 2.0, "mobile": True}
          and approvals(state(d)) == appr0)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로", "--evidence", str(shot), "--coverage-note", "확인", *P(d))
    check("M8 측정 명령이 있는데 아직 측정 안 함 → measurement_pending(측정 또는 사용자 문장)", code == 2 and out["error"] == "measurement_pending", out)

    # 정상 측정
    fake(d)
    code, out = pi("explore-verify", "--round", "S01", *P(d))
    run = out.get("run_id")
    rec = state(d)["exploration"]["structure"]["rounds"][0]["measurements"][-1]
    sdir = d / f"design-explore/S01/shots/{run}"
    spec = json.loads((sdir / "measure-spec.json").read_text()) if run else {}
    r0 = (rec.get("variants") or {}).get("A", {}).get("results", [{}])[0]
    check("M9 측정 완료: 명세(시안×대상 파생 페이지·뷰포트·EX5 확장 예약)·리포트 판정, 실제 뷰포트·DPR·스크린샷 해시·시안 해시 기록",
          code == 0 and out["status"] == "completed" and len(spec.get("pages", [])) == 6 and spec["extensions"] == {"reference_compare": None}
          and (sdir / "pages/A-T1.html").is_file() and '<base href="../../../A/">' in (sdir / "pages/A-T1.html").read_text()
          and r0.get("actual") == {"width": 40, "height": 80, "dpr": 2} and r0["screenshot"]["width"] == 80 and len(r0["screenshot"]["sha256"]) == 64
          and len(rec["variants"]["A"]["basis"]) == 64 and (sdir / "summary.md").is_file() and "모델 평가 아님" in (sdir / "summary.md").read_text()
          and out["level"] == "measured", out)
    check("M10 측정 산출물(shots/)은 Git 제외, 시안 파일 해시(보존 집합)에도 섞이지 않음", "*/shots/" in (d / "design-explore/.gitignore").read_text()
          and not any("/shots/" in k for k in EX._round_files(d, "S01")))

    # 차단 결과: 선언 2열인데 세로 배치(B), 콘솔 오류(C)
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    man["rounds"]["S01"]["variants"]["B"]["layouts"] = [{"id": "L1", "target": "T2", "columns": 2, "elements": ["e4", "e3"]}]
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("M11 레이아웃 선언 뒤 기존 측정은 B만 무효(stale), A·C는 그대로 통과", code == 0 and out["measurement"]["B"]["status"] == "stale"
          and out["measurement"]["A"]["status"] == "passed", out.get("measurement"))
    fake(d, per={"B": {"stack_layouts": True}, "C": {"console": ["Failed to load resource: x.css"]}})
    code, out = pi("explore-verify", "--round", "S01", *P(d))
    run = out.get("run_id")
    check("M12 선언 2열·실제 1열 → layout_mismatch 차단(B), 콘솔 오류 → 차단(C), 정상 A는 차단 없음",
          code == 0 and any("layout_mismatch:L1" in x for x in out["variants"]["B"]["blocking"]) and any("console_errors:1" in x for x in out["variants"]["C"]["blocking"])
          and out["variants"]["A"]["blocking"] == [] and out["variants"]["B"]["measurement_blocks_choice"] is True, out.get("variants"))
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로", "--evidence", str(shot), "--coverage-note", "확인", *P(d))
    check("M13 차단 결과가 있는 시안 선택 거부(variant_has_blocking_findings), 사용자 문장·증거로도 우회 불가, 다른 시안 상태 안내",
          code == 2 and out["error"] == "variant_has_blocking_findings" and out["other_variants"]["A"] == "passed", out)
    code, out = pi("explore-choose", "--round", "S01", "--per-target", "T1=A,T2=C", "--note", "T1은 A, T2는 C로", "--coverage-note", "확인",
                   "--measurement-waiver", "측정 없이 진행", *P(d))
    check("M14 대상별 조합에서도 차단 시안(C)이 있으면 거부, 측정 무효용 문장(waiver)으로 차단을 넘을 수 없음", code == 2 and out["error"] == "variant_has_blocking_findings", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로", "--coverage-note", "확인", *P(d))
    check("M15 측정한 시안의 모델 평가에 측정 스크린샷 근거가 없으면 거부(critique_unsupported)", code == 2 and out["error"] == "critique_unsupported", out)
    cite_shots(d, "S01", "M00000000-000000-zzzzzz", "A")
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로", "--coverage-note", "확인", *P(d))
    check("M16 측정 기록에 없는 스크린샷 인용은 근거가 아님", code == 2 and out["error"] == "critique_unsupported", out)
    write_critique(d, "S01", "ABC")
    cite_shots(d, "S01", run, "ABC")
    before = raw(d)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안으로 갑니다", "--coverage-note", "인증 실패 안내 위임에 동의", *P(d))
    st = state(d)
    ch = st["exploration"]["structure"]["choice"] or {}
    ev = [e for e in ch.get("evidence", []) if e["source"] == "measurement"]
    check("M17 정상 시안 선택: 측정 통과 기록(measured)·모델 평가 구분(visually_reviewed: model)·측정 스크린샷(대상×뷰포트 4장)이 핵심 증거(사람 캡처 없이), 해시 연결",
          code == 0 and ch.get("measurement") == "passed" and ch["measurement_detail"]["variants"]["A"]["run_id"] == run
          and ch["visually_reviewed"] == "model" and len(ev) == 4 and {(e["target"], e["viewport"]) for e in ev} == {(t, v) for t in ("T1", "T2") for v in ("mobile", "desktop")}
          and all((d / e["path"]).is_file() and e["sha256"] == e["measured_sha256"] for e in ev)
          and ch["measurement_detail"]["variants"]["A"]["report_sha256"], out)
    check("M18 선택 후에도 승인·제출 기록·revision·해시 불변, history는 추가만", approvals(state(d)) == appr0 and state(d)["history"][:hist0] == st["history"][:hist0])
    code, out = pi("explore-status", *P(d))
    check("M19 측정 증거도 보존 무결성 대상(바뀌지 않음)", code == 0 and out["integrity"]["structure"]["changed"] == [] and out["integrity"]["structure"]["missing"] == [], out)

    # 측정 이후 시안 변경 → 무효(stale), 재측정 후 선택
    (d / "design-explore/S01/B/styles.css").write_text("body{margin:0} .x{display:grid}\n")
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안", "--coverage-note", "확인", *P(d))
    check("M20 측정 이후 시안이 바뀌면 결과 무효(measurement_stale) — 이전 차단 결과도 그대로 쓰지 않음", code == 2 and out["error"] == "measurement_stale", out)
    fake(d)
    code, out = pi("explore-verify", "--round", "S01", "--variants", "B", *P(d))
    run_b = out.get("run_id")
    write_critique(d, "S01", "ABC")
    cite_shots(d, "S01", run, "AC")
    cite_shots(d, "S01", run_b, "B")
    code, out = pi("explore-choose", "--round", "S01", "--variant", "B", "--note", "B안으로 바꿉니다", "--coverage-note", "확인", *P(d))
    check("M21 고친 시안만 다시 측정해 통과하면 선택 가능(재선택은 같은 라운드 기록 갱신)", code == 0 and state(d)["exploration"]["structure"]["choice"]["id"] == "EXP-S01-B"
          and state(d)["exploration"]["structure"]["choice"]["measurement_detail"]["variants"]["B"]["run_id"] == run_b, out)

    # 측정 실패 유형(무효) — 미실행과 구분
    cases = [("viewport_mismatch", {"all": {"actual_width": 50}}, "viewport_mismatch"),
             ("screenshot_mismatch", {"all": {"shot_size": [40, 80]}}, "screenshot_mismatch"),
             ("run_id", {"run_id": "M-old"}, "run_id"),
             ("format", {"format": "pb-ui-report/v1"}, "형식"),
             ("shot_path", {"all": {"shot_path": "../../x.png"}}, "screenshot"),
             ("missing", {"drop_last": True}, "빠졌습니다"),
             ("no_report", {"no_report": True}, "report.json"),
             ("exit", {"no_report": True, "exit": 3}, "종료 코드 3")]
    for name, sc, frag in cases:
        fake(d, **sc)
        code, out = pi("explore-verify", "--round", "S01", "--variants", "A", *P(d))
        check(f"M22 {name} → 측정 무효(invalid, 종료 2), 사유 기록", code == 2 and out["status"] == "invalid" and frag in (out.get("reason") or ""), out)
    fake(d, sleep=3)
    code, out = pi("explore-verify", "--round", "S01", "--variants", "A", "--timeout", "1", *P(d))
    check("M23 시간 초과 → invalid", code == 2 and out["status"] == "invalid" and "초" in out["reason"], out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안", "--coverage-note", "확인", *P(d))
    check("M24 최근 측정이 무효면 선택 거부(measurement_invalid) — 무효를 숨기지 않음", code == 2 and out["error"] == "measurement_invalid", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안", "--coverage-note", "확인",
                   "--measurement-waiver", "측정 환경이 고장 나서 측정 없이 진행합니다", *P(d))
    check("M25 사용자 문장(waiver)으로 측정 없이 진행: 사람 캡처 증거 필요(retention_incomplete)", code == 2 and out["error"] == "retention_incomplete", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안", "--coverage-note", "확인", "--evidence", str(shot),
                   "--measurement-waiver", "측정 환경이 고장 나서 측정 없이 진행합니다", *P(d))
    ch = state(d)["exploration"]["structure"]["choice"]
    check("M26 waiver 선택 기록: measurement=waived, 사용자 문장, 경고(measurement_waived)", code == 0 and ch["measurement"] == "waived"
          and ch["measurement_detail"]["waiver"].startswith("측정 환경") and any("measurement_waived" in w for w in out["warnings"]), out)

    # 미실행(도구 없음) → 경고 후 선택 허용
    fake(d, status="not_run")
    code, out = pi("explore-verify", "--round", "S01", "--variants", "A", *P(d))
    check("M27 어댑터가 도구 없음(not_run) 보고 → not_run(무효 아님, 종료 0)", code == 0 and out["status"] == "not_run", out)
    code, out = pi("explore-choose", "--round", "S01", "--variant", "A", "--note", "A안", "--coverage-note", "확인", "--evidence", str(shot), *P(d))
    check("M28 측정 not_run이면 기존 정책대로 경고 후 선택(measurement_not_run)", code == 0 and state(d)["exploration"]["structure"]["choice"]["measurement"] == "not_run"
          and any("measurement_not_run" in w for w in out["warnings"]), out)
    setup_measure(d, "no-such-measure-tool --x")
    code, out = pi("explore-verify", "--round", "S01", "--variants", "A", *P(d))
    check("M29 측정 명령 자체가 없음 → not_run(환경 없음)", code == 0 and out["status"] == "not_run" and "찾지 못했습니다" in out["reason"], out)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")

    # 레이아웃 사실 판정(차단·경고 분류)
    def verify_with(**per):
        fake(d, per={"A": per})
        return pi("explore-verify", "--round", "S01", "--variants", "A", *P(d))[1]
    out = verify_with(hidden=["e3"])
    check("M30 필수 항목 요소가 렌더되지 않음 → required_not_rendered 차단", any("required_not_rendered:e3" in x for x in out["variants"]["A"]["blocking"]), out)
    out = verify_with(unreachable=["e4"])
    check("M31 필수 요소가 어떤 스크롤 위치에서도 가려짐 → required_unreachable 차단", any("required_unreachable:e4" in x for x in out["variants"]["A"]["blocking"]), out)
    out = verify_with(tap_fail=["e2"], downgrade_core=True)
    check("M32 핵심 상호작용 실패는 어댑터가 core=false로 낮춰도 차단", any("interaction_failed:tap:e2" in x for x in out["variants"]["A"]["blocking"]), out)
    out = verify_with(a11y={"critical": 1, "serious": 1})
    check("M33 접근성 critical 차단·serious 보고", any("a11y_critical:1" in x for x in out["variants"]["A"]["blocking"])
          and any("a11y_serious:1" in x for x in out["variants"]["A"]["warnings"]), out)
    out = verify_with(render_failed=True)
    check("M34 렌더 실패 차단", any("render_failed" in x for x in out["variants"]["A"]["blocking"]), out)
    out = verify_with(fixed_cover=True, overflow_px=30, touch=20, contrast=2.0, extensions={"reference_compare": {"score": 1}})
    w = " | ".join(out["variants"]["A"]["warnings"])
    rec = state(d)["exploration"]["structure"]["rounds"][0]["measurements"][-1]
    check("M35 고정 하단 요소의 첫 화면 가림·수평 스크롤·작은 터치 영역·낮은 대비는 보고(경고, 선택 허용), EX5 확장은 판정 없이 기록",
          out["variants"]["A"]["blocking"] == [] and all(k in w for k in ("fixed_overlap:", "horizontal_scroll:30px", "touch_target_small:", "contrast_low:"))
          and rec["variants"]["A"]["results"][0]["extensions"] == {"reference_compare": "recorded_not_judged"}, w)

    # 정적 검사: 레이아웃 선언 형식
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    man["rounds"]["S01"]["variants"]["C"]["layouts"] = [{"id": "L9", "target": "T2", "columns": 0, "elements": ["e1"]}]
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    code, out = pi("explore-check", "--round", "S01", *P(d))
    check("M36 레이아웃 선언 형식 오류(layout_invalid: 열 수·요소 수)", code == 2 and errs_of(out).count("layout_invalid") >= 2, errs_of(out)[:300])
    code, out = pi("explore-verify", "--round", "S01", "--viewports", "mobile=390", *P(d))
    check("M37 뷰포트 인자 형식 오류", code == 2 and out["error"] == "invalid_arguments", out)
    check("M38 측정·선택 전 과정 후에도 승인·제출 기록·revision·해시 불변", approvals(state(d)) == appr0)


# ---------------------------------------------------------------- EX5 2차 시각 탐색
TOKENS04 = """
## 토큰
| 토큰 | 값 | 용도 |
|---|---|---|
| color.action.primary | #1D5BD0 | 주 버튼 |
| color.action.onPrimary | #FFFFFF | 버튼 글자 |
| color.text.primary | #1A1D23 | 본문 |
| color.bg.page | #FFFFFF | 배경 |
| color.bg.surface | #F4F5F7 | 카드 |
| font.size.body / title | 16 / 22px | 글자 |
| font.weight.regular / bold | 400 / 700 | |
| space.2 / 4 | 8 / 16px | 간격 |
| radius.md | 10px | 모서리 |
"""
SCR_TABLES = {
    "SCR-001": "### 정보와 우선순위\n| 순서 | 정보 | 출처(데이터) | 권한별 노출 |\n|---|---|---|---|\n| 1 | 서비스 소개 | 고정 | 모두 |\n\n"
               "### 행동\n| 행동 | 결과 | 관련 |\n|---|---|---|\n| 로그인 | SCR-003 | AC-001 |\n\n",
    "SCR-003": "### 정보와 우선순위\n| 순서 | 정보 | 출처(데이터) | 권한별 노출 |\n|---|---|---|---|\n| 1 | 랭크 | 계산 | 본인 |\n| 2 | 전적 | 집계 | 본인 |\n\n"
               "### 행동\n| 행동 | 결과 | 관련 |\n|---|---|---|\n| 프로필 수정 | SCR-001 | AC-001 |\n\n",
}
OFFICIAL = {"color.action.primary": "#1D5BD0", "color.action.onPrimary": "#FFFFFF", "color.text.primary": "#1A1D23", "color.bg.page": "#FFFFFF",
            "color.bg.surface": "#F4F5F7", "font.size.body": "16px", "font.size.title": "22px", "font.weight.regular": "400", "font.weight.bold": "700",
            "space.2": "8px", "space.4": "16px", "radius.md": "10px"}
# (id, target, kind, refs, html)
VIS_ELEMENTS = [("v1", "SCR-001", "info", ["SCR-001:info-1"], '<h1 data-el="v1">모임 앱</h1>'),
                ("v2", "SCR-001", "action", ["SCR-001:action-1", "CMP-001"], '<button data-el="v2" data-cmp="CMP-001">로그인</button>'),
                ("v3", "SCR-003", "info", ["SCR-003:info-1"], '<p data-el="v3" data-sample class="rank">A 등급</p>'),
                ("v4", "SCR-003", "info", ["SCR-003:info-2"], '<p data-el="v4" data-sample class="rec">24경기 14승</p>'),
                ("v5", "SCR-003", "action", ["SCR-003:action-1", "CMP-001"], '<button data-el="v5" data-cmp="CMP-001">프로필 수정</button>')]
VCSS = {
    "A": "body{margin:0;font-family:system-ui;font-size:var(--font-size-body);background:var(--color-bg-page);color:var(--color-text-primary)}\n"
         "h1{font-size:var(--font-size-title);font-weight:var(--font-weight-bold)}\n"
         "button{border:0;border-radius:var(--radius-md);padding:var(--space-2) var(--space-4);background:var(--color-action-primary);color:var(--color-action-onPrimary)}\n",
    "B": "body{margin:0;font-family:Georgia,serif;font-size:17px;background:var(--color-bg-page);color:var(--color-text-primary)}\n"
         "h1{font-size:30px;font-weight:800;letter-spacing:-0.02em}\n.rank{font-size:40px}\n"
         "button{border:0;border-radius:999px;padding:14px 24px;background:var(--color-action-primary);color:var(--color-action-onPrimary)}\n",
    "C": "body{margin:0;font-family:system-ui;font-size:var(--font-size-body);background:var(--color-bg-surface);color:var(--color-text-primary)}\n"
         "section{display:grid;gap:4px;padding:8px}\nh1{font-size:var(--font-size-title);font-weight:var(--font-weight-bold)}\n"
         "button{border:2px solid var(--color-action-primary);border-radius:4px;padding:6px 10px;background:var(--color-bg-page);color:var(--color-action-primary)}\n",
}


def patch_spec_for_visual(d: Path) -> None:
    p02 = d / "docs/design/02-screens.md"
    t = p02.read_text()
    for sid, tables in SCR_TABLES.items():
        i = t.index(f"## {sid}:")
        j = t.index("### 상태", i)
        t = t[:j] + tables + t[j:]
    p02.write_text(t)
    p04 = d / "docs/design/04-ui-system.md"
    p04.write_text(p04.read_text() + TOKENS04)


def write_vvariant(d: Path, rid: str, lb: str, css: str | None = None, tokens: dict | None = None, elements=None, extra_html: str = "",
                   axes=("typography", "component"), prov=None, **man_kw) -> None:
    base = d / "design-explore" / rid / lb
    els = elements if elements is not None else VIS_ELEMENTS
    secs = {}
    for _i, tgt, _k, _r, html in els:
        secs.setdefault(tgt, []).append(html)
    body = "".join(f'<section data-target="{t}" id="{t}">{"".join(h)}</section>' for t, h in secs.items()) + extra_html
    (base / "index.html").write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8"><link rel="stylesheet" href="tokens.css">'
                                     f'<link rel="stylesheet" href="styles.css"></head><body>{body}</body></html>')
    (base / "styles.css").write_text(css if css is not None else VCSS[lb])
    th = {"schema": "design-theme/v1", "name": f"cand-{lb}", "tokens": dict(OFFICIAL, **(tokens or {})), "provenance": prov or {}}
    (base / "theme.json").write_text(json.dumps(th, ensure_ascii=False))
    (base / "plan.md").write_text("".join(f"## {h}\n- {lb}안 {h}\n\n" for h in EX.PLAN_HEADINGS["visual"]))
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    v = man["rounds"][rid]["variants"][lb]
    v.update(title=f"{lb}안", concept=f"{lb}안 시각 개념", distinct_axes=list(axes),
             elements=[{"id": i, "target": t, "kind": k, "refs": r, **({"sample": True} if "data-sample" in h else {})} for i, t, k, r, h in els], **man_kw)
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    assert pi("explore-tokens", "--round", rid, "--variants", lb, *P(d))[0] == 0


def write_vcritique(d: Path, rid: str, labels, run: str | None = None, reference: bool = False) -> None:
    fields = EX.CRITIQUE_FIELDS["visual_reference" if reference else "visual"]
    body = ""
    for lb in labels:
        body += f"\n## {rid}-{lb}\n" + "".join(f"- **{f}**: {lb}안 {f}\n" for f in fields)
        if run:
            body += f"- **근거 스크린샷**: shots/{run}/shots/{lb}-SCR-001-mobile.png\n"
    (d / f"design-explore/{rid}/critique.md").write_text(f"# {rid} 시각 평가\n{body}")


def visual_project(root: Path, name: str) -> Path:
    d = T.make_product(root, name)
    (d / "design-profile").mkdir(exist_ok=True)
    (d / "design-profile/theme.json").write_text(json.dumps({"schema": "design-theme/v1", "name": "official", "tokens": OFFICIAL}))
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "theme (user commit)")
    code, out = pi("start", "--workflow", "v2", "--theme-file", "design-profile/theme.json", *P(d))
    assert code == 0, out
    T.write_00(d, 1)
    T.write_notes(d, NOTES_DONE)
    assert pi("explore-skip", "--phase", "structure", "--note", "구조는 기획 그대로 두고 건너뜁니다", *P(d))[0] == 0
    for args in (("done", "--path", UXP), ("submit", "--stage", "ux_planning"), ("approve", "--stage", "ux_planning", "--revision", "1"),
                 ("begin", "--stage", "ux_spec")):
        code, out = pi(*args, *P(d))
        assert code == 0, (args, out)
    T.write_spec(d, 1)
    patch_spec_for_visual(d)
    T.done_all(d, T.SPEC)
    for args in (("checkpoint",), ("submit", "--stage", "ux_spec"), ("approve", "--stage", "ux_spec", "--revision", "1"),
                 ("begin", "--stage", "design_direction")):
        code, out = pi(*args, *P(d))
        assert code == 0, (args, out)
    return d


def ex5(root: Path) -> None:
    import pd_visual as VS
    import product_design_dd_test as DDT
    d = visual_project(root, "ex5")
    appr0 = approvals(state(d))
    fp = VS.fingerprint(d, "SCR-003")
    check("V1 구조 지문: 승인된 02의 정보(순서)·행동·컴포넌트·상태", fp["info"] == ["랭크", "전적"] and fp["actions"] == ["프로필 수정"]
          and fp["cmps"] == ["CMP-001"] and "SCR-003-ST1" in fp["states"], fp)
    # 게이트 꺼짐 상태 복원 → 2차 명령 거부
    sp = d / ".ai-workflow/design.json"
    good_state = sp.read_text()
    st = json.loads(good_state)
    st["config"]["gates"]["design_direction"] = False
    sp.write_text(json.dumps(st, ensure_ascii=False))
    code, out = pi("explore-init", "--phase", "visual", *P(d))
    sp.write_text(good_state)
    check("V2 게이트가 꺼진 상태로 복원되면 2차 탐색 거부(exploration_gate_mismatch, D7)", code == 2 and out["error"] == "exploration_gate_mismatch", out)
    code, out = pi("explore-init", "--phase", "visual", *P(d))
    tg = out.get("targets") or []
    check("V3 기본 대표 화면: Must 화면 중 구성 서명이 다른 2개(선정 근거), 라운드 V01·시안 A·B·C·후보 테마·토큰 CSS 골격",
          code == 0 and out["round"] == "V01" and [t["id"] for t in tg] == ["SCR-001", "SCR-002"] and all(t["basis"] for t in tg)
          and (d / "design-explore/V01/A/theme.json").is_file() and (d / "design-explore/V01/A/tokens.css").is_file()
          and "--color-action-primary: #1D5BD0" in (d / "design-explore/V01/A/tokens.css").read_text(), out)
    shutil.rmtree(d / "design-explore/V01")
    sp.write_text(good_state)
    code, out = pi("explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003", *P(d))
    brief = (d / "design-explore/V01/brief.md").read_text() if code == 0 else ""
    st = state(d)
    check("V4 대상 지정(SCR-001·SCR-003): 브리프에 구조 지문(SCR-003:info-1 랭크…), 라운드 기준에 UX Spec revision·지문 해시, 승인 불변",
          code == 0 and "`SCR-003:info-2` 전적" in brief and "`SCR-001:action-1` 로그인" in brief
          and st["exploration"]["visual"]["rounds"][0]["basis"]["ux_spec_revision"] == 1 and approvals(st) == appr0, out)
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("V5 골격은 검사 실패(제목·요소·구조 지문 누락)", code == 2 and "structure_drift" in errs_of(out), errs_of(out)[:300])
    for lb in "ABC":
        write_vvariant(d, "V01", lb, axes=("typography", "component") if lb != "C" else ("density", "component"),
                       tokens={"radius.md": "14px", "color.action.primary": "#0E7C6B"} if lb == "A" else None)
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("V6 구조 고정·토큰만 쓰는 시안 3개(타이포·밀도·컴포넌트 표현이 다름) 통과", code == 0 and out["ok"] and out["phase"] == "visual", errs_of(out)[:600])

    def bad(lb="B", **kw):
        write_vvariant(d, "V01", lb, **kw)
        c, o = pi("explore-check", "--round", "V01", *P(d))
        write_vvariant(d, "V01", lb)
        return c, errs_of(o), o
    extra = VIS_ELEMENTS + [("v9", "SCR-003", "action", ["SCR-003:action-2"], '<button data-el="v9">알림</button>')]
    c, e, _ = bad(elements=extra)
    check("V7 이미지에만 있는 기능(승인 02에 없는 행동) → structure_drift", c == 2 and "v9의 근거 SCR-003:action-2가 승인된 02" in e, e[:300])
    c, e, _ = bad(elements=[x for x in VIS_ELEMENTS if x[0] != "v4"])
    check("V8 승인된 정보 누락 → structure_drift", c == 2 and "info-2(전적)이 시안에 없습니다(structure_drift)" in e, e[:300])
    swapped = [VIS_ELEMENTS[0], VIS_ELEMENTS[1], VIS_ELEMENTS[3], VIS_ELEMENTS[2], VIS_ELEMENTS[4]]
    c, e, _ = bad(elements=swapped)
    check("V9 승인된 정보 순서 변경 → structure_drift", c == 2 and "정보 순서 [2, 1]" in e, e[:300])
    c, e, _ = bad(extra_html='<section data-target="SCR-003"><button>공유</button></section>')
    check("V10 근거 없는 버튼(요구사항 밖 기능) → unbacked_element", c == 2 and "unbacked_element" in e, e[:300])
    mixed = [x if x[0] != "v5" else ("v5", "SCR-003", "action", ["SCR-003:action-1", "CMP-002"], '<button data-el="v5" data-cmp="CMP-002">프로필 수정</button>') for x in VIS_ELEMENTS]
    c, e, _ = bad(elements=mixed)
    check("V11 화면의 승인 컴포넌트가 아닌 CMP → structure_drift", c == 2 and "CMP-002" in e and "structure_drift" in e, e[:300])
    c, e, _ = bad(css=VCSS["B"].replace("color:var(--color-action-onPrimary)", "color:#fff"))
    check("V12 날 색 값 → raw_color_literal(토큰 우회 금지)", c == 2 and "raw_color_literal" in e, e[:300])
    c, e, _ = bad(css=VCSS["B"] + ".x{color:var(--color-brand-mint)}\n")
    check("V13 테마에 없는 토큰 변수 → token_var_unknown", c == 2 and "token_var_unknown" in e, e[:300])
    write_vvariant(d, "V01", "B")
    th = json.loads((d / "design-explore/V01/B/theme.json").read_text())
    th["tokens"]["radius.md"] = "4px"
    (d / "design-explore/V01/B/theme.json").write_text(json.dumps(th))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("V14 theme.json을 고치고 토큰 CSS를 다시 만들지 않으면 tokens_css_stale", code == 2 and "tokens_css_stale" in errs_of(out), errs_of(out)[:300])
    write_vvariant(d, "V01", "B")
    c, e, o = bad(lb="C", css=VCSS["A"], tokens={"color.action.primary": "#058176", "radius.md": "14px"}, axes=("typography",))
    check("V15 A와 CSS 구조·값이 같고 색 토큰만 다른 시안 → variants_color_only", c == 2 and "A와 C" in e and "variants_color_only" in e, e[:300])
    write_vvariant(d, "V01", "C", tokens={"color.brand.mint": "#058176"}, css=VCSS["C"] + ".rank{color:var(--color-brand-mint)}\n", axes=("density", "component"))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("V16 04에 없는 토큰은 오류가 아니라 ② 변경 요청 후보로 표시(token_needs_cr)", code == 0 and any("token_needs_cr" in w for w in out["warnings"])
          and out["visual"]["C"]["tokens_needing_cr"] == ["color.brand.mint"], out.get("errors"))

    # 측정(EX4) 연결: 화면 간 컴포넌트 일관성
    (d / "tools").mkdir()
    (d / "tools/fake_measure.py").write_text(FAKE_ADAPTER)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    btn = {"background-color": "rgb(29, 91, 208)", "border-radius": "10px", "font-size": "16px"}
    fake(d, per={"B": {"components": {"SCR-001": [{"cmp": "CMP-001", "el": "v2", "style": btn}],
                                      "SCR-003": [{"cmp": "CMP-001", "el": "v5", "style": dict(btn, **{"border-radius": "999px"})}]}},
                 "A": {"components": {"SCR-001": [{"cmp": "CMP-001", "el": "v2", "style": btn}], "SCR-003": [{"cmp": "CMP-001", "el": "v5", "style": btn}]}}})
    code, out = pi("explore-verify", "--round", "V01", *P(d))
    run = out.get("run_id")
    check("V17 측정: 같은 시안에서 같은 컴포넌트(CMP-001)가 화면마다 다른 스타일 → component_inconsistent 차단(B), A는 통과",
          code == 0 and any("component_inconsistent:CMP-001" in x and "border-radius" in x for x in out["variants"]["B"]["blocking"])
          and out["variants"]["A"]["blocking"] == [], out.get("variants"))
    sel = dict(btn, **{"background-color": "rgb(255, 255, 255)"})
    fake(d, per={"B": {"components": {"SCR-001": [{"cmp": "CMP-001", "el": "v2", "style": btn}, {"cmp": "CMP-001", "el": "v2", "state": "disabled", "style": sel}],
                                      "SCR-003": [{"cmp": "CMP-001", "el": "v5", "style": btn}, {"cmp": "CMP-001", "el": "v5", "state": "selected", "style": sel},
                                                  {"cmp": "CMP-001", "el": "v5", "variant": "ghost", "style": sel}]}}})
    code, outs = pi("explore-verify", "--round", "V01", "--variants", "B", *P(d))
    check("V17b 선언된 상태(disabled·selected)·명시적 변형(ghost)은 스타일이 달라도 허용(같은 조건끼리만 비교)",
          code == 0 and outs["variants"]["B"]["blocking"] == [], outs.get("variants"))
    fake(d, per={"B": {"components": {"SCR-001": [{"cmp": "CMP-001", "el": "v2", "state": "selected", "style": btn}],
                                      "SCR-003": [{"cmp": "CMP-001", "el": "v5", "state": "selected", "style": sel}]}}})
    code, outs = pi("explore-verify", "--round", "V01", "--variants", "B", *P(d))
    check("V17c 같은 상태(selected)끼리 선언 없이 다르면 여전히 차단", code == 0 and any("component_inconsistent:CMP-001/[selected]" in x for x in outs["variants"]["B"]["blocking"]), outs.get("variants"))
    fake(d, per={"B": {"components": {"SCR-001": [{"cmp": "CMP-001", "el": "v2", "style": btn}],
                                      "SCR-003": [{"cmp": "CMP-001", "el": "v5", "style": dict(btn, **{"border-radius": "999px"})}]}}})
    pi("explore-verify", "--round", "V01", "--variants", "B", *P(d))  # B를 다시 차단 상태로(이후 V19·V20 기대)
    rr = [{"viewport": vp, "target": "SCR-001", "layout": {"components": [{"cmp": "CMP-001", "el": "v2", "style": {"font-size": fs}}]}} for vp, fs in (("mobile", "16px"), ("desktop", "18px"))]
    check("V17d 뷰포트별 반응형 표현(모바일 16px·데스크톱 18px)은 차단하지 않음", VS.component_findings(rr)[0] == [])
    spec = json.loads((d / f"design-explore/V01/shots/{run}/measure-spec.json").read_text())
    check("V18 2차 측정 명세: 승인 구조의 모든 정보·행동 요소가 필수(장식 제외), 행동은 핵심 상호작용",
          all(e["required"] for p_ in spec["pages"] for e in p_["elements"]) and any(e["core"] for p_ in spec["pages"] for e in p_["elements"] if e["kind"] == "action"))
    write_vcritique(d, "V01", "ABC", run)
    code, out = pi("explore-choose", "--round", "V01", "--variant", "B", "--note", "B안으로", *P(d))
    check("V19 컴포넌트 불일치 시안은 선택 불가(variant_has_blocking_findings)", code == 2 and out["error"] == "variant_has_blocking_findings", out)
    code, out = pi("explore-choose", "--round", "V01", "--variant", "A", "--axes", "typography=B", "--note", "A안 기준, 글자는 B안으로", *P(d))
    check("V20 축별 조합에 차단 시안(B)이 들어가도 거부", code == 2 and out["error"] == "variant_has_blocking_findings", out)
    code, out = pi("explore-choose", "--round", "V01", "--variant", "A", "--axes", "typography=C", "--note", "A안 기준으로", *P(d))
    check("V21 조합 선택 문장에 쓰인 시안(C)이 드러나야 함", code == 2 and out["error"] == "choice_statement_unclear", out)
    before07 = (d / DDT.DD).read_bytes() if (d / DDT.DD).is_file() else b""
    theme_before = (d / "design-profile/theme.json").read_bytes()
    code, out = pi("explore-choose", "--round", "V01", "--variant", "A", "--axes", "typography=C", "--note", "A안 기준에 글자 축만 C안으로 합니다", *P(d))
    st = state(d)
    ch = st["exploration"]["visual"]["choice"] or {}
    check("V22 2차 조합 선택 기록(EXP-V01-MIX, 축별 시안, 측정 통과, visually_reviewed: model), 승인 불변",
          code == 0 and ch.get("id") == "EXP-V01-MIX" and ch["axes"]["typography"] == "C" and ch["axes"]["component"] == "A"
          and ch["measurement"] == "passed" and ch["visually_reviewed"] == "model" and approvals(st) == appr0, out)

    # 채택: 후보 VD·후보 테마(공식 아님)
    DDT.write_07(d, 1)
    pre07 = (d / DDT.DD).read_bytes()
    code, out = pi("explore-adopt", "--round", "V01", *P(d))
    adir = d / "design-explore/V01/selection/adoption"
    vdc = (adir / "vd-candidates.md").read_text() if code == 0 else ""
    cand = json.loads((adir / "theme.candidate.json").read_text()) if code == 0 else {}
    check("V23 채택: 후보 VD(상태 후보, 근거 EXP-V01-MIX, 관련 SCR·토큰), 후보 테마(approved false, 04 토큰만), 테마 diff·UI Brief 근거 후보, 07·공식 테마 불변",
          code == 0 and "- **상태**: 후보" in vdc and "사용자 선택 EXP-V01-MIX" in vdc and "SCR-001, SCR-003" in vdc and "### VD-003" in vdc
          and cand["approved"] is False and "color.brand.mint" not in cand["tokens"] and cand["source_variants"]["font.size.body"] == "C"
          and (adir / "theme.diff.json").is_file() and json.loads((adir / "ui-brief-hints.json").read_text())["screens"]["SCR-003"]["vds"]
          and (d / DDT.DD).read_bytes() == pre07 and (d / "design-profile/theme.json").read_bytes() == theme_before, out)
    ad = state(d)["exploration"]["visual"]["adoption"]
    # 제출 조건·추적
    pi("done", "--path", DDT.DD, *P(d))
    code, out = pi("submit", "--stage", "design_direction", *P(d))
    check("V24 선택을 근거로 하는 VD가 07에 없으면 Design Direction 제출 거부(exploration_not_reflected)", code == 2 and out["error"] == "exploration_not_reflected", out)
    cands = re.sub(r"<!--.*?-->", "", vdc, flags=re.S)
    DDT.write_07(d, 1, extra_vd=cands)
    pi("done", "--path", DDT.DD, *P(d))
    code, out = pi("submit", "--stage", "design_direction", *P(d))
    check("V25 후보 VD가 남아 있으면 기존 규칙대로 제출 거부(승인 또는 제외 결정 필요)", code == 2 and "승인되지 않은 VD(후보)" in errs_of(out), out)
    DDT.write_07(d, 1, extra_vd=cands.replace("- **상태**: 후보", "- **상태**: 제외(사용자가 기존 값 유지)").replace("사용자 선택 EXP-V01-MIX", "사용자 선택 EXP-V01-B", 1))
    code, out = pi("trace", "--stage", "design_direction", *P(d))
    check("V26 선택되지 않은 시안 ID를 VD 근거로 쓰면 trace 오류(exploration_ref_not_chosen)", code == 2 and "exploration_ref_not_chosen" in errs_of(out), errs_of(out)[:300])
    DDT.write_07(d, 1, extra_vd=cands.replace("- **상태**: 후보", "- **상태**: 제외(사용자가 기존 값 유지)"))
    tok, val = next(iter(ad["candidate_tokens"].items())) if not any(t for t in ad["token_vd"]) else next((t, ad["candidate_tokens"][t]) for t in ad["token_vd"])
    off = json.loads(theme_before)
    off["tokens"][tok] = val
    (d / "design-profile/theme.json").write_text(json.dumps(off))
    code, out = pi("trace", "--stage", "design_direction", *P(d))
    check("V27 승인되지 않은(제외) VD의 후보 값을 공식 테마에 넣으면 trace 오류(adopted_theme_unapproved)", code == 2 and "adopted_theme_unapproved" in errs_of(out), errs_of(out)[:300])
    (d / "design-profile/theme.json").write_bytes(theme_before)
    DDT.write_07(d, 1, extra_vd=cands.replace("- **상태**: 후보", "- **상태**: 승인"))
    pi("done", "--path", DDT.DD, *P(d))
    code, out = pi("trace", "--stage", "design_direction", *P(d))
    check("V28 사용자가 후보 VD를 승인으로 결정하면 trace 통과(선택 ID·관련 SCR·04 토큰 대조)", code == 0, errs_of(out)[:400])
    core = lambda a_: {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted")} for k, v in a_.items() if isinstance(v, dict) and "status" in v}
    check("V29 탐색·측정·선택·채택 전 과정에서 승인·제출 기록·revision·해시 불변(07 done 기록만 추가)", core(approvals(state(d))) == core(appr0))

    # 레퍼런스 기반 2차(reference·mixed)
    up = root / "up5"
    up.mkdir()
    (up / "ref.png").write_bytes(img_png((5, 129, 118), 4, 4))
    assert pi("explore-ref", "add", "--file", str(up / "ref.png"), "--rights", "own", *P(d))[0] == 0
    sha = state(d)["exploration"]["references"]["REF-001"]["sha256"]
    items = [it("RX-001-01", "palette", "observed", "high", "주색 짙은 틸") | {"value": {"primary": "#058176"}},
             it("RX-001-02", "typography", "observed", "high", "굵은 제목, 숫자 크게"),
             it("RX-001-03", "components", "observed", "high", "둥근 카드·옅은 그림자"),
             it("RX-001-04", "spacing_density", "estimated", "medium", "카드 사이 약 12px") | {"value": {"gap": "12px"}}]
    (d / "design-explore/references/REF-001/extraction.json").write_text(json.dumps(extraction("REF-001", sha, items, [{"kind": "feature", "note": "알림·즐겨찾기(예시 기능)"}]), ensure_ascii=False))
    assert pi("explore-ref", "extract-check", "--ref", "REF-001", *P(d))[0] == 0
    code, out = pi("explore-ref", "intent", "--use", "REF-001=palette,typography,components,spacing_density", "--note", "민트·틸 색과 글자, 카드 표현을 참고", *P(d))
    check("V30 참고 의도에 시각 축 기록(1차에는 이월 안내, 2차 라운드에서는 그대로 사용)", code == 0 and out["deferred_to_visual"] == {"REF-001": ["palette", "typography", "components"]}, out)
    code, out = pi("explore-init", "--phase", "visual", "--mode", "reference", "--intent", "INT-001", "--targets", "SCR-001,SCR-003", *P(d))
    assert code == 0, out
    rv = dict(mode="reference", rules=["RX-001-01", "RX-001-02"], axis_sources={"palette": "REF-001", "typography": "REF-001"},
              reinterpretation="틸 주색만 버튼에, 이미지 속 알림·즐겨찾기 기능과 문구는 쓰지 않음")
    write_vvariant(d, "V02", "A", tokens={"color.action.primary": "#058176"}, prov={"color.action.primary": ["RX-001-01"]}, **rv)
    write_vvariant(d, "V02", "B", tokens={"color.action.primary": "#0B9280"}, prov={"color.action.primary": ["RX-001-01"]},
                   mode="mixed", rules=["RX-001-01"], axis_sources={"palette": "REF-001", "typography": "ai"}, reinterpretation="색만 참고, 글자는 AI")
    write_vvariant(d, "V02", "C", tokens={"color.action.primary": "#058176", "space.4": "12px"},
                   prov={"color.action.primary": ["RX-001-01"], "space.4": ["RX-001-04"]}, axes=("density", "component"),
                   mode="reference", rules=["RX-001-01", "RX-001-04"], axis_sources={"palette": "REF-001", "spacing_density": "REF-001"}, reinterpretation="간격 참고")
    write_vcritique(d, "V02", "ABC", reference=False)
    code, out = pi("explore-check", "--round", "V02", *P(d))
    e = errs_of(out)
    al = {x["rule"]: x["result"] for x in (out.get("visual") or {}).get("A", {}).get("alignment", [])}
    alb = {x["rule"]: x["result"] for x in (out.get("visual") or {}).get("B", {}).get("alignment", [])}
    check("V31 reference·mixed 2차: 확인 전 추정 간격(RX-001-04)을 쓴 C만 오류(reference_unconfirmed), 토큰↔규칙 대조 사실(A 같음·B 가까움)",
          code == 2 and "V02-C: 규칙 RX-001-04" in e and "reference_unconfirmed" in e and "V02-A" not in e.replace("V02-A와", "")
          and al.get("RX-001-01") == "same" and alb.get("RX-001-01") == "near", (e[:400], al, alb))
    check("V32 레퍼런스 라운드 critique는 레퍼런스 대비·다른 점·자산 미사용 항목 필수", any("레퍼런스 대비" in x for x in out["critique_missing"]), out.get("critique_missing"))
    write_vvariant(d, "V02", "C", tokens={"color.action.primary": "#058176"}, prov={"color.action.primary": ["RX-001-01", "RX-001-03"]}, axes=("density", "component"),
                   mode="reference", rules=["RX-001-01"], axis_sources={"palette": "REF-001"}, reinterpretation="색만")
    code, out = pi("explore-check", "--round", "V02", *P(d))
    check("V33 테마 출처(provenance)는 시안 rules에 있는 규칙만(provenance_rule_missing)", code == 2 and "provenance_rule_missing" in errs_of(out), errs_of(out)[:300])
    write_vvariant(d, "V02", "C", tokens={"color.action.primary": "#058176"}, prov={"color.action.primary": ["RX-001-01"]}, axes=("density", "component"),
                   mode="reference", rules=["RX-001-01"], axis_sources={"palette": "REF-001"}, reinterpretation="색만")
    code, out = pi("explore-compare", "--round", "V02", *P(d))
    cmp_html = (d / "design-explore/V02/compare.html").read_text() if code == 0 else ""
    check("V34 2차 비교 페이지: 레퍼런스 원본(로컬 경로)과 시안을 나란히, 토큰↔규칙 대조 표(엔진 사실), 외부 리소스 없음",
          code == 0 and '../references/REF-001/original.png' in cmp_html and "후보 테마 ↔ 레퍼런스 규칙 대조" in cmp_html and "2차 시각 탐색" in cmp_html
          and "http" not in cmp_html.replace("http-equiv", ""), out)
    code, out = pi("explore-impact", "--items", "RX-001-01", *P(d))
    hit = [h for h in out.get("variants", []) if h["round"] == "V02"]
    check("V35 후보 변경 영향: 규칙 RX-001-01을 쓴 2차 시안·토큰·화면 식별(읽기 전용)", code == 0 and {h["variant"] for h in hit} == {"A", "B", "C"}
          and all("color.action.primary" in h["tokens"] for h in hit) and set(out["screens"]) >= {"SCR-001", "SCR-003"} and out["read_only"], out)
    check("V36 레퍼런스 2차 이후에도 승인 기록 불변", core(approvals(state(d))) == core(appr0))
    code, out = pi("explore-init", "--phase", "visual", "--mode", "reference", "--intent", "INT-001", "--parent", "V02", "--base", "V02-A", "--variants", "1",
                   "--goal", "강조 보강", "--feedback", "A안을 조금 더 다듬어 주세요", *P(d))
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    nv = (man["rounds"].get(out.get("round") or "-") or {}).get("variants", {}).get("A", {})
    check("V37 레퍼런스 라운드의 수정 라운드도 기준 시안의 rules·axis_sources·provenance 선언을 그대로 이어받음",
          code == 0 and nv.get("rules") == man["rounds"]["V02"]["variants"]["A"]["rules"] and nv.get("axis_sources") == man["rounds"]["V02"]["variants"]["A"]["axis_sources"]
          and nv.get("revised_from") == "V02-A", out)
    code, out = pi("impact", "--design", "--choice", "EXP-V01-MIX", *P(d))
    ex_ = out.get("exploration") or {}
    cats = {i["id"].split(":")[1]: [c["key"] for c in i["categories"]] for i in out.get("items", [])}
    check("V38 impact --design --choice(2차): 구도 ④·테마 값 ③, 영향 화면·컴포넌트·VD(승인 기록 아님)·후보와 공식 테마 차이",
          code == 0 and cats.get("composition") == ["visual"] and cats.get("theme") == ["theme_value"]
          and set(ex_["screens"]) >= {"SCR-001", "SCR-003"} and "CMP-001" in ex_["components"]
          and ex_["approved_vs_candidate"]["vds_not_approved"] and "radius.md" in ex_["theme"]["changed_vs_official"] and out["read_only"], out)
    req = root / "req6.json"
    req.write_text(json.dumps({"schema": "design-change-request/v1", "items": [
        {"id": "C1", "summary": "선택 변경", "facts": [{"kind": "exploration_choice", "choice": "EXP-V01-MIX", "aspect": "theme_value", "tokens": ["color.brand.mint"]}]},
        {"id": "C2", "summary": "없는 선택", "facts": [{"kind": "exploration_choice", "choice": "EXP-V09-A", "aspect": "composition"}]}]}))
    code, out = pi("impact", "--design", "--request", str(req), *P(d))
    it_ = {i["id"]: i for i in out.get("items", [])}
    check("V39 요청 파일의 exploration_choice: 04 밖 후보 토큰은 ②, 기록에 없는 선택은 needs_review",
          code == 0 and [c["key"] for c in it_["C1"]["categories"]] == ["token_semantics"] and it_["C2"]["status"] == "needs_review", out)


# ---------------------------------------------------------------- EX5.1 시각 자산·품질 평가·수정 라운드
ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            'stroke-linecap="round"><path d="M4 12h16"/></svg>')
ILLU_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80"><rect x="4" y="4" width="112" height="72" rx="8" fill="#E7F7EE"/></svg>'
ASSET_ELEMENTS = [("v1", "SCR-001", "info", ["SCR-001:info-1"], '<h1 data-el="v1"><img src="../_assets/AST-002.svg" alt="" aria-hidden="true" data-asset="AST-002">모임 앱</h1>'),
                  ("v2", "SCR-001", "action", ["SCR-001:action-1", "CMP-001"], '<button data-el="v2" data-cmp="CMP-001"><span class="ico" data-asset="AST-001" aria-hidden="true"></span>로그인</button>'),
                  VIS_ELEMENTS[2], VIS_ELEMENTS[3],
                  ("v5", "SCR-003", "action", ["SCR-003:action-1", "CMP-001"], '<button data-el="v5" data-cmp="CMP-001"><img src="../_assets/AST-003.svg" alt="프로필 수정" data-asset="AST-003">프로필 수정</button>')]
ICO_CSS = ".ico{display:inline-block;width:20px;height:20px;mask:url(../_assets/AST-001.svg) center/contain no-repeat;background:currentColor}\n"


def write_quality(d: Path, rid: str, labels, run: str, override=None, goals=None, before_run=None, base_lb="A") -> None:
    crit = {}
    for i, k in enumerate(EX.__dict__.get("QL_CRITERIA") or __import__("pd_quality").CRITERIA):
        crit[k] = {"rating": "adequate", "observations": f"{k}: 스크린샷에서 확인한 구체적 관찰 {i}번 — 위치와 크기를 적음",
                   "evidence": [f"shots/{run}/shots/{{lb}}-SCR-001-mobile.png"],
                   "issues": [{"id": f"Q{i}", "severity": "minor", "what": f"{k} 개선이 필요한 부분", "where": "SCR-001", "fix": "간격을 8px 늘려 묶음을 분리"}]}
    vs = {}
    for lb in labels:
        c = json.loads(json.dumps(crit).replace("{lb}", lb))
        c["reference_alignment"] = {"rating": "not_applicable"}  # AI 라운드
        if override:
            override(lb, c)
        vs[lb] = {"criteria": c}
    data = {"format": "design-quality-review/v1", "round": rid, "reviewer": "model", "variants": vs}
    if goals:
        data["goals"] = {f"G{i}": {"status": "addressed", "before": [f"shots/{before_run}/shots/{base_lb}-SCR-001-mobile.png"],
                                   "after": [f"shots/{run}/shots/{lb}-SCR-001-mobile.png" for lb in labels], "note": "히어로 여백과 강조를 조정함"}
                         for i in range(1, goals + 1)}
    (d / f"design-explore/{rid}/quality.json").write_text(json.dumps(data, ensure_ascii=False))


def ex51(root: Path) -> None:
    d = visual_project(root, "ex51")
    appr0 = approvals(state(d))
    core = lambda a_: {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted")} for k, v in a_.items() if isinstance(v, dict) and "status" in v}
    up = root / "assets51"
    up.mkdir()
    (up / "ico.svg").write_text(ICON_SVG)
    (up / "illu.svg").write_text(ILLU_SVG)
    (up / "fn.svg").write_text(ICON_SVG.replace("M4 12h16", "M12 4v16"))
    (up / "bad-script.svg").write_text(ICON_SVG.replace("<path", "<script>x</script><path"))
    (up / "bad-ext.svg").write_text(ICON_SVG.replace("<path", '<use href="https://cdn.example.com/i.svg#a"/><path'))
    (up / "bad-color.svg").write_text(ICON_SVG.replace('stroke="currentColor"', 'stroke="#058176"'))
    (up / "bad-stroke.svg").write_text(ICON_SVG.replace('stroke-width="1.8"', 'stroke-width="2.5"'))
    code, out = pi("explore-asset", "style", "--set", "style=outline", "--set", "stroke_width=1.8", "--set", "grid=24", "--set", "linecap=round", *P(d))
    check("A1 아이콘 스타일 가이드는 사용자 문장 필요", code == 2 and out["error"] == "statement_required", out)
    code, out = pi("explore-asset", "style", "--set", "style=outline", "--set", "stroke_width=1.8", "--set", "grid=24", "--set", "linecap=round",
                   "--note", "선형 아이콘, 1.8 선, 24 격자로 통일", *P(d))
    check("A2 프로젝트 아이콘 스타일 기록(윤곽선·1.8·24·round·currentColor)", code == 0 and out["icon_style"]["stroke_width"] == 1.8 and out["icon_style"]["color"] == "currentColor", out)
    code, out = pi("explore-asset", "add", "--file", str(up / "ico.svg"), "--kind", "icon", "--role", "decorative", "--source", "model_drawn", *P(d))
    reg = json.loads((d / "design-profile/assets.json").read_text()) if code == 0 else {}
    check("A3 아이콘 등록: AST-001, 프로젝트 자산 폴더 사본·SHA-256·출처·라이선스 미확인(공식 채택 불가 경고)",
          code == 0 and out["asset"] == "AST-001" and (d / "design-profile/assets/AST-001.svg").is_file() and len(reg["assets"]["AST-001"]["sha256"]) == 64
          and out["official_ok"] is False and any("asset_rights_unconfirmed" in w for w in out["warnings"]), out)
    for f, frag in (("bad-script.svg", "svg_unsafe"), ("bad-ext.svg", "svg_external"), ("bad-color.svg", "icon_style_mismatch"), ("bad-stroke.svg", "icon_style_mismatch")):
        code, out = pi("explore-asset", "add", "--file", str(up / f), "--kind", "icon", "--role", "decorative", "--source", "model_drawn", *P(d))
        check(f"A4 {f} → 등록 거부({frag})", code == 2 and out["error"] == "asset_invalid" and frag in " ".join(out.get("errors", [])), out)
    code, out = pi("explore-asset", "add", "--file", str(up / "fn.svg"), "--kind", "icon", "--role", "functional", "--source", "model_drawn", *P(d))
    check("A5 기능 자산은 무엇을 나타내는지 승인된 ID 필요(asset_refs_required)", code == 2 and out["error"] == "asset_refs_required", out)
    assert pi("explore-asset", "add", "--file", str(up / "illu.svg"), "--kind", "illustration", "--role", "decorative", "--source", "self_made", "--license", "own", *P(d))[0] == 0
    assert pi("explore-asset", "add", "--file", str(up / "fn.svg"), "--kind", "icon", "--role", "functional", "--source", "model_drawn",
              "--refs", "SCR-003:action-1", "--depicts", "프로필 수정", *P(d))[0] == 0
    (up / "ref.png").write_bytes(img_png((5, 129, 118), 3, 3))
    assert pi("explore-ref", "add", "--file", str(up / "ref.png"), *P(d))[0] == 0
    code, out = pi("explore-asset", "add", "--file", str(up / "ref.png"), "--kind", "image", "--role", "decorative", "--source", "reference_derived", *P(d))
    check("A6 레퍼런스 원본을 자산으로 등록 거부(reference_copy)", code == 2 and out["error"] == "reference_copy", out)

    # 시안에서 자산 사용
    assert pi("explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003", *P(d))[0] == 0
    assert pi("explore-asset", "sync", "--round", "V01", *P(d))[0] == 0
    write_vvariant(d, "V01", "A", elements=ASSET_ELEMENTS, css=VCSS["A"] + ICO_CSS)
    write_vvariant(d, "V01", "B")
    write_vvariant(d, "V01", "C", axes=("density", "component"))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("A7 등록 자산(장식 일러스트·아이콘 마스크·기능 아이콘)을 역할대로 쓰면 통과, 자산·아이콘 사용 기록",
          code == 0 and out["visual"]["A"]["assets_used"] == ["AST-001", "AST-002", "AST-003"] and out["visual"]["A"]["icons"] == ["AST-001", "AST-003"]
          and "AST-001" in out["visual"]["A"]["rights_unconfirmed"] and "AST-002" in out["visual"]["A"]["rights_unconfirmed"], errs_of(out)[:500])

    def bad_el(els, css=None, extra=""):
        write_vvariant(d, "V01", "A", elements=els, css=(css or VCSS["A"] + ICO_CSS), extra_html=extra)
        c, o = pi("explore-check", "--round", "V01", *P(d))
        write_vvariant(d, "V01", "A", elements=ASSET_ELEMENTS, css=VCSS["A"] + ICO_CSS)
        return c, errs_of(o)
    rep_ = lambda i, html: [x if x[0] != i else (x[0], x[1], x[2], x[3], html) for x in ASSET_ELEMENTS]
    c, e = bad_el(rep_("v1", '<h1 data-el="v1"><svg viewBox="0 0 24 24"><path d="M1 1"/></svg>모임 앱</h1>'))
    check("A8 인라인 SVG(등록 우회) → asset_inline_svg", c == 2 and "asset_inline_svg" in e, e[:300])
    (d / "design-explore/V01/A/x.png").write_bytes(img_png())
    c, e = bad_el(rep_("v1", '<h1 data-el="v1"><img src="x.png" alt="">모임 앱</h1>'))
    (d / "design-explore/V01/A/x.png").unlink()
    check("A9 등록되지 않은 이미지 → asset_unregistered", c == 2 and "asset_unregistered" in e, e[:300])
    c, e = bad_el(rep_("v1", '<h1 data-el="v1"><img src="../_assets/AST-002.svg" alt="배드민턴 코트" data-asset="AST-002">모임 앱</h1>'))
    check("A10 장식 자산에 대체 텍스트(정보처럼 보임) → decorative_alt", c == 2 and "decorative_alt" in e, e[:300])
    c, e = bad_el(ASSET_ELEMENTS, extra='<section data-target="SCR-003"><a href="#" data-el="v5x"><img src="../_assets/AST-002.svg" alt="" data-asset="AST-002"></a></section>')
    check("A11 장식 자산만 든 링크(장식을 기능처럼) → decorative_as_control", c == 2 and "decorative_as_control" in e, e[:400])
    c, e = bad_el(rep_("v2", '<button data-el="v2" data-cmp="CMP-001"><img src="../_assets/AST-003.svg" alt="프로필 수정" data-asset="AST-003">로그인</button>'))
    check("A12 기능 아이콘(프로필 수정)을 다른 근거의 요소(로그인)에 씀 → asset_implies_unapproved", c == 2 and "asset_implies_unapproved" in e, e[:300])
    c, e = bad_el(rep_("v2", '<button data-el="v2" data-cmp="CMP-001"><span class="ico"></span>로그인</button>'))
    check("A13 CSS로만 쓰고 HTML 표지가 없는 자산 → asset_unmarked", c == 2 and "asset_unmarked" in e, e[:300])
    c, e = bad_el(ASSET_ELEMENTS, css=VCSS["A"] + ICO_CSS.replace("mask:url(../_assets/AST-001.svg) center/contain no-repeat;", ""))
    check("A13b 표지(data-asset)는 있지만 CSS가 그 자산을 불러오지 않음(빈 자리) → asset_marked_unused", c == 2 and "asset_marked_unused" in e, e[:300])
    regf = d / "design-profile/assets/AST-002.svg"
    orig = regf.read_text()
    regf.write_text(orig.replace("#E7F7EE", "#FFFFFF"))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("A14 등록 이후 자산 파일 변경 → asset_modified·라운드 사본 불일치", code == 2 and "asset_modified" in errs_of(out), errs_of(out)[:300])
    regf.write_text(orig)
    code, out = pi("explore-asset", "check", *P(d))
    check("A15 자산 점검(읽기 전용): 권리 상태·공식 채택 가능 여부", code == 0 and out["assets"]["AST-002"]["official_ok"] is False and out["assets"]["AST-002"]["license"] == "own", out)

    # 측정·품질 평가
    (d / "tools").mkdir()
    (d / "tools/fake_measure.py").write_text(FAKE_ADAPTER)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    fake(d)
    code, out = pi("explore-verify", "--round", "V01", *P(d))
    run = out["run_id"]
    code, out = pi("explore-quality", "--round", "V01", *P(d))
    check("A16 품질 평가 파일이 없으면 기준·자동 사실을 안내하고 실패(quality_review_missing)", code == 2 and out["error"] == "quality_review_missing"
          and "iconography" in out["criteria"] and out["facts"]["A"]["assets_used"] == 3 and out["facts"]["B"]["assets_used"] == 0, out)

    def q(override=None, **kw):
        write_quality(d, "V01", "ABC", run, override=override, **kw)
        return pi("explore-quality", "--round", "V01", *P(d))
    code, out = q(lambda lb, c: c["hierarchy"].update(rating=9))
    check("A17 숫자 점수는 받지 않음", code == 2 and "숫자 점수는 받지 않음" in errs_of(out), errs_of(out)[:300])

    def all_strong(lb, c):
        for k in c:
            c[k].update(rating="strong", issues=[])
    code, out = q(all_strong)
    check("A18 모두 strong·개선 항목 0 → review_without_improvements, 자산 없는 시안의 아이콘 strong은 사실과 모순",
          code == 2 and "review_without_improvements" in errs_of(out) and "V01-B.iconography: strong은 자동 사실과 모순" in errs_of(out), errs_of(out)[:600])
    code, out = q(lambda lb, c: c["typography"].update(evidence=["shots/M00000000-000000-zzzzzz/shots/A-SCR-001-mobile.png"]))
    check("A19 측정 기록에 없는 스크린샷 근거 → quality_evidence_invalid", code == 2 and "quality_evidence_invalid" in errs_of(out), errs_of(out)[:300])
    code, out = q(lambda lb, c: c["typography"].update(observations=c["hierarchy"]["observations"]))
    check("A20 기준 간 같은 문장 반복 → review_boilerplate", code == 2 and "review_boilerplate" in errs_of(out), errs_of(out)[:300])
    code, out = q(lambda lb, c: c["density_balance"].update(rating="weak", issues=[]))
    check("A21 weak·adequate에는 개선 항목 필수", code == 2 and "개선 항목(issues)이 필요" in errs_of(out), errs_of(out)[:300])
    fake(d, all={"contrast": 2.0})
    code, out = pi("explore-verify", "--round", "V01", *P(d))
    run2 = out["run_id"]
    write_quality(d, "V01", "ABC", run2, override=lambda lb, c: c["typography"].update(rating="strong"))
    code, out = pi("explore-quality", "--round", "V01", *P(d))
    check("A22 낮은 대비(측정 사실)인데 타이포 strong → rating_contradicts_facts", code == 2 and "rating_contradicts_facts" in errs_of(out), errs_of(out)[:300])
    fake(d)
    code, out = pi("explore-verify", "--round", "V01", *P(d))
    run = out["run_id"]
    code, out = q()
    st = state(d)
    check("A23 계약을 지킨 평가는 통과: 자동 사실(measured·checked)과 평가(visually_reviewed: model)를 구분해 기록, 디자인 품질 판정 아님",
          code == 0 and st["exploration"]["visual"]["rounds"][0]["quality"]["valid"] and "visually_reviewed" in out["levels"]["ratings"]
          and out["facts"]["A"]["first_screen_fill"] and "디자인 품질이 좋다는 엔진 판정이 아니며" in out["note"], errs_of(out)[:400])

    # 수정 라운드
    v01_files = {k: v for k, v in EX._round_files(d, "V01").items() if "/shots/" not in k}
    code, out = pi("explore-init", "--phase", "visual", "--parent", "V01", "--base", "V01-A", "--variants", "1", *P(d))
    check("A24 2차 수정 라운드는 수정 목표·사용자 피드백 필요(revision_goals_required)", code == 2 and out["error"] == "revision_goals_required", out)
    code, out = pi("explore-init", "--phase", "visual", "--parent", "V01", "--base", "V01-A", "--variants", "1",
                   "--goal", "히어로 강조 보강", "--goal", "아이콘 일관성", "--feedback", "A안이 좋은데 첫 화면이 밋밋해요", *P(d))
    st = state(d)
    r2 = next(r for r in st["exploration"]["visual"]["rounds"] if r["id"] == "V02") if code == 0 else {}
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    check("A25 수정 라운드 V02: 기준 V01-A 산출물·선언 복사, 목표·피드백·회차 기록, 원본 라운드 보존",
          code == 0 and r2["kind"] == "revision" and r2["revision"]["goals"] == ["히어로 강조 보강", "아이콘 일관성"] and r2["revision"]["depth"] == 1
          and (d / "design-explore/V02/A/theme.json").read_text() == (d / "design-explore/V01/A/theme.json").read_text()
          and man["rounds"]["V02"]["variants"]["A"]["revised_from"] == "V01-A" and len(man["rounds"]["V02"]["variants"]["A"]["elements"]) == 5
          and "G1: 히어로 강조 보강" in (d / "design-explore/V02/brief.md").read_text(), out)
    assert pi("explore-asset", "sync", "--round", "V02", *P(d))[0] == 0
    code, out = pi("explore-check", "--round", "V02", *P(d))
    check("A26 고치지 않은 수정 시안 → revision_identical_to_base", code == 2 and "revision_identical_to_base" in errs_of(out), errs_of(out)[:300])
    (d / "design-explore/V02/A/styles.css").write_text((d / "design-explore/V02/A/styles.css").read_text() + "h1{letter-spacing:-0.01em;font-size:26px}\n")
    write_vcritique(d, "V02", "A")
    h2 = d / "design-explore/V02/A/index.html"
    good_h2 = h2.read_text()
    h2.write_text(good_h2.replace('<p data-el="v4" data-sample class="rec">24경기 14승</p>', ""))
    code, out = pi("explore-check", "--round", "V02", *P(d))
    check("A27 수정 중 승인된 정보 누락 → structure_drift(요구사항 검사 재실행)", code == 2 and "structure_drift" in errs_of(out) and "element_missing" in errs_of(out), errs_of(out)[:300])
    h2.write_text(good_h2)
    code, out = pi("explore-check", "--round", "V02", *P(d))
    check("A28 수정 시안 정적 검사 통과(구조·토큰·자산)", code == 0, errs_of(out)[:400])
    code, out = pi("explore-verify", "--round", "V02", *P(d))
    run_v2 = out["run_id"]
    write_vcritique(d, "V02", "A", run_v2)
    code, out = pi("explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본으로", *P(d))
    check("A29 수정 라운드는 품질 평가(목표별 수정 전후) 없이 선택 불가(quality_review_required)", code == 2 and out["error"] == "quality_review_required", out)
    write_quality(d, "V02", "A", run_v2, goals=1, before_run=run)
    code, out = pi("explore-quality", "--round", "V02", *P(d))
    check("A30 기록된 수정 목표마다 수정 전·후 근거 필요(G2 누락)", code == 2 and "수정 목표 G2" in errs_of(out), errs_of(out)[:300])
    write_quality(d, "V02", "A", run_v2, goals=2, before_run=run)
    code, out = pi("explore-quality", "--round", "V02", *P(d))
    check("A31 목표별 수정 전(V01-A 측정)·후(V02-A 측정) 근거를 갖춘 평가 통과", code == 0, errs_of(out)[:400])
    code, out = pi("explore-compare", "--round", "V02", *P(d))
    cmp_html = (d / "design-explore/V02/compare.html").read_text() if code == 0 else ""
    check("A32 비교 페이지에 수정 전후(측정 스크린샷)와 목표·피드백", code == 0 and "수정 전후" in cmp_html and f"../V01/shots/{run}/shots/A-SCR-001-mobile.png" in cmp_html
          and "G2: 아이콘 일관성" in cmp_html, out)
    # 자산 없이 렌더(fallback)
    fake(d, fallback_fail=True)
    code, out = pi("explore-verify", "--round", "V02", "--asset-fallback", *P(d))
    code2, out2 = pi("explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본으로", *P(d))
    check("A33 자산 없이 렌더 측정이 실패하면 선택 거부(asset_fallback_failed), 일반 측정 결과(게이트)는 그대로",
          out["asset_fallback"] is True and code2 == 2 and out2["error"] == "asset_fallback_failed", (out, out2))
    fake(d)
    pi("explore-verify", "--round", "V02", "--asset-fallback", *P(d))
    before = (d / "design-explore/V01/A/index.html").read_text()
    code, out = pi("explore-choose", "--round", "V02", "--variant", "A", "--note", "A안 수정본으로 갑니다", *P(d))
    check("A34 대체 표시 측정 통과 후 수정 시안 선택 가능(사용자 문장), 원본 라운드 V01 파일 불변",
          code == 0 and state(d)["exploration"]["visual"]["choice"]["id"] == "EXP-V02-A"
          and {k: v for k, v in EX._round_files(d, "V01").items() if "/shots/" not in k and "quality.json" not in k}
          == {k: v for k, v in v01_files.items() if "quality.json" not in k}, out)
    # 반복 상한(기본 2회)
    code, out = pi("explore-init", "--phase", "visual", "--parent", "V02", "--base", "V02-A", "--variants", "1", "--goal", "여백", "--feedback", "조금 더", *P(d))
    code2, out2 = pi("explore-init", "--phase", "visual", "--parent", "V03", "--base", "V03-A", "--variants", "1", "--goal", "여백", "--feedback", "한 번 더", *P(d))
    check("A35 수정 회차 상한(기본 2): V03(2회째) 허용, V04(3회째) revision_limit", code == 0 and code2 == 2 and out2["error"] == "revision_limit", (out, out2))
    # 채택·추적: 권리 미확인 자산
    code, out = pi("explore-adopt", "--round", "V02", *P(d))
    vdc = (d / "design-explore/V02/selection/adoption/vd-candidates.md").read_text() if code == 0 else ""
    hints = json.loads((d / "design-explore/V02/selection/adoption/ui-brief-hints.json").read_text()) if code == 0 else {}
    check("A36 채택 후보: 아이콘·일러스트 VD는 권리 미확인 자산을 채택 불가로 분리(공식 후보 0), 07·자산 레지스트리 불변",
          code == 0 and "아이콘·일러스트" in vdc and "채택 불가" in vdc and hints["assets"]["adoptable"] == []
          and set(hints["assets"]["blocked"]) == {"AST-001", "AST-002", "AST-003"}, out)
    import product_design_dd_test as DDT
    DDT.write_07(d, 1, extra_vd="### VD-009: 아이콘\\n- **결정**: 선형 아이콘\\n- **상태**: 승인\\n- **근거**: 사용자 선택 EXP-V02-A\\n- **관련**: SCR-001, AST-001\\n- **토큰 밖 값**: 없음\\n".replace("\\n", "\n"))
    code, out = pi("trace", "--stage", "design_direction", *P(d))
    check("A37 권리 미확인 자산을 승인 VD에 넣으면 trace 오류(asset_rights_unconfirmed)", code == 2 and "AST-001의 출처·권리가 확인되지 않았습니다" in errs_of(out), errs_of(out)[:300])
    code, out = pi("explore-asset", "confirm", "--id", "AST-001", "--license", "own", *P(d))
    check("A38 권리 확인은 사용자 문장 필요", code == 2 and out["error"] == "statement_required", out)
    assert pi("explore-asset", "confirm", "--id", "AST-001", "--license", "own", "--note", "직접 만든 아이콘이라 우리 소유입니다", *P(d))[0] == 0
    code, out = pi("trace", "--stage", "design_direction", *P(d))
    check("A39 사용자가 권리를 확인한 자산은 VD 관련으로 통과", "AST-001" not in errs_of(out), errs_of(out)[:300])
    check("A40 자산·품질·수정 라운드 전 과정에서 승인·제출 기록·revision 불변", core(approvals(state(d))) == core(appr0))


# ---------------------------------------------------------------- EX6 탐색 산출물 격리·공식 디자인 근거·영향
def ex6(root: Path) -> None:
    import pd_guard as GD
    d = visual_project(root, "ex6")
    appr0 = approvals(state(d))
    core = lambda a_: {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted")} for k, v in a_.items() if isinstance(v, dict) and "status" in v}
    up = root / "assets6"
    up.mkdir()
    (up / "ico.svg").write_text(ICON_SVG)
    (up / "illu.svg").write_text(ILLU_SVG)
    assert pi("explore-asset", "style", "--set", "style=outline", "--set", "stroke_width=1.8", "--set", "grid=24", "--set", "linecap=round", "--note", "선형 아이콘", *P(d))[0] == 0
    assert pi("explore-asset", "add", "--file", str(up / "ico.svg"), "--kind", "icon", "--role", "decorative", "--source", "self_made", "--license", "own", *P(d))[0] == 0
    assert pi("explore-asset", "add", "--file", str(up / "illu.svg"), "--kind", "illustration", "--role", "decorative", "--source", "model_drawn", *P(d))[0] == 0
    assert pi("explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003", *P(d))[0] == 0
    assert pi("explore-asset", "sync", "--round", "V01", *P(d))[0] == 0  # 라운드 사본(_assets)이 있어도 자산 기준으로 판정되는지
    for lb in "ABC":
        write_vvariant(d, "V01", lb, axes=("typography", "component") if lb != "C" else ("density", "component"),
                       tokens={"color.brand.mint": "#058176"} if lb == "C" else None, css=VCSS[lb] + (".rank{color:var(--color-brand-mint)}\n" if lb == "C" else ""))
    fe = d / "frontend/src"
    fe.mkdir(parents=True, exist_ok=True)
    pv = d / "design-preview/src"
    pv.mkdir(parents=True, exist_ok=True)

    def F(rel, body, binary=False):
        q = d / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(body) if binary else q.write_text(body)
        return rel
    kinds = lambda files: {(x["file"], x["kind"]) for x in GD.findings(d, files)}
    f1 = F("frontend/src/Login.html", (d / "design-explore/V01/B/index.html").read_text())
    x = GD.findings(d, [f1])
    check("P1 미선택 시안 HTML을 이름을 바꿔 복사 → explore_copy(선택되지 않은 시안 표시)", x and x[0]["kind"] == "explore_copy" and x[0]["status"] == "unselected_variant", x)
    css = (d / "design-explore/V01/A/styles.css").read_text()
    f2 = F("frontend/src/theme.css", "/* 우리 스타일 */\n" + css.replace(";", " ;\n  ").replace("{", " {\n").upper())
    check("P2 주석 추가·다시 들여 쓰기·대소문자 변경으로 우회한 복사도 explore_copy", (f2, "explore_copy") in kinds([f2]), GD.findings(d, [f2]))
    f3 = F("frontend/src/app.css", ".mine{display:flex;gap:8px}\n" + (d / "design-explore/V01/C/styles.css").read_text().replace(".rank{color:var(--color-brand-mint)}\n", "") + ".foot{margin:0;padding:4px}\n")
    check("P3 시안 CSS 규칙 블록 여러 개를 다른 파일에 섞어 넣으면 explore_copy_partial", (f3, "explore_copy_partial") in kinds([f3]), GD.findings(d, [f3]))
    f4 = F("frontend/src/a.ts", 'import x from "../../DESIGN-EXPLORE/V01/A/index.html"\n')
    f5 = F("frontend/src/b.ts", 'const p = "..\\\\design-explore\\\\V01\\\\A\\\\styles.css"\n')
    f6 = F("frontend/src/c.ts", 'fetch("/static/design%2Dexplore/x")\nconst q = "design-explore%2FV01"\n')
    check("P4 대소문자·역슬래시·URL 인코딩 경로 참조 → explore_reuse", {(f4, "explore_reuse"), (f5, "explore_reuse"), (f6, "explore_reuse")} <= kinds([f4, f5, f6]), GD.findings(d, [f4, f5, f6]))
    (pv / "linked").symlink_to(d / "design-explore/V01/A", target_is_directory=True)
    check("P5 design-explore를 가리키는 폴더 심볼릭 링크 → explore_reuse(파일 목록 우회 방지)",
          any(x["kind"] == "explore_reuse" for x in GD.symlink_findings(d, ["design-preview"])))
    (pv / "linked").unlink()
    f7 = F("frontend/src/tokens.css", ":root{--color-action-primary:#1D5BD0;--color-brand-mint:#058176}\n")
    check("P6 탐색 후보에만 있는 토큰(04·공식 테마에 없음)을 정의 → explore_token", (f7, "explore_token") in kinds([f7]), GD.findings(d, [f7]))
    f8 = F("frontend/public/hero.svg", (d / "design-profile/assets/AST-002.svg").read_bytes(), binary=True)
    f9 = F("frontend/src/icon.ts", 'export const icon = "/design-profile/assets/AST-001.svg"\n')
    x8 = GD.findings(d, [f8, f9])
    check("P7 등록 자산 사본(권리 미확인)·자산 경로 참조(승인 VD 밖) → asset_unapproved", {(f8, "asset_unapproved"), (f9, "asset_unapproved")} <= {(y["file"], y["kind"]) for y in x8}
          and "권리 미확인" in next(y["detail"] for y in x8 if y["file"] == f8), x8)
    f10 = F("frontend/src/own.css", ".card{border-radius:12px;padding:16px;color:var(--color-text-primary)}\n.btn{border:0;background:var(--color-action-primary)}\n")
    check("P8 시각적으로 비슷한 자체 작성 CSS는 통과(유사도는 판정하지 않음)", GD.findings(d, [f10]) == [], GD.findings(d, [f10]))
    check("P9 product-build도 같은 규칙(pb_ui.explore_findings = pd_guard)", __import__("pb_ui").explore_findings(d, [f1, f8]) == GD.findings(d, [f1, f8]))
    src = (ENGINE / "skills/product-design/scripts/pd_guard.py").read_text()
    check("P10 pd_guard는 읽기 전용(파일·상태를 쓰지 않음, product-build가 가져옴)", not re.search(r"write_text|write_bytes|save_state|open\([^)]*['\"]w|unlink|rmtree|mkdir", src))
    # preview-check 통합
    (d / "design-preview/preview.manifest.json").write_text(json.dumps({"ux_spec_revision": 1, "screens": {}}))
    shutil.copyfile(d / "design-explore/V01/A/styles.css", pv / "explore.css")
    shutil.copyfile(d / "design-profile/assets/AST-002.svg", pv / "hero.svg")
    code, out = pi("preview-check", *P(d))
    e = errs_of(out)
    check("P11 preview-check: 시안 CSS 복사(explore_copy)·미승인 자산(asset_unapproved) 차단", code == 2 and "explore_copy" in e and "asset_unapproved" in e, e[:500])
    (pv / "explore.css").unlink()
    (pv / "hero.svg").unlink()

    # 공식 경로: 권리 확인 자산 + 승인 VD 관련 → 사용 가능
    import product_design_dd_test as DDT
    assert pi("explore-skip", "--phase", "visual", "--note", "이번에는 시각 탐색 없이 기존 방향으로 승인합니다", *P(d))[0] == 0
    assert pi("explore-asset", "confirm", "--id", "AST-001", "--license", "own", "--note", "직접 만든 아이콘이라 우리 소유입니다", *P(d))[0] == 0
    DDT.write_07(d, 1, extra_vd="### VD-009: 아이콘\n- **결정**: 선형 아이콘 세트\n- **상태**: 승인\n- **근거**: 사용자 결정\n- **관련**: SCR-001, AST-001\n- **토큰 밖 값**: 없음\n")
    for args in (("done", "--path", DDT.DD), ("submit", "--stage", "design_direction"), ("approve", "--stage", "design_direction", "--revision", "1")):
        code, out = pi(*args, *P(d))
        assert code == 0, (args, out)
    od = GD.official_design(d)
    f11 = F("frontend/public/icon.svg", (d / "design-profile/assets/AST-001.svg").read_bytes(), binary=True)
    check("P12 승인된 VD 관련에 있고 권리가 확인된 자산(AST-001)은 제품 코드에서 정상 사용, 아닌 자산(AST-002)은 차단",
          od["assets"]["AST-001"]["official"] and GD.findings(d, [f11]) == [] and (f8, "asset_unapproved") in kinds([f8]), od["assets"])
    bs = GD.brief_sources(d, ["SCR-001", "SCR-003"])
    check("P13 UI Brief 근거: 승인 기록의 VD·승인 VD에 묶인 권리 확인 자산만, 탐색 선택(건너뜀)은 출처(source_only)",
          bs["design_direction"]["approved"] and "VD-009" in bs["design_direction"]["approved_vds"] and [a["id"] for a in bs["screens"]["SCR-001"]["assets"]] == ["AST-001"]
          and bs["screens"]["SCR-003"]["assets"] == [] and bs["exploration_provenance"]["use"] == "source_only"
          and bs["exploration_provenance"]["records"]["design_direction"]["skipped"], bs)
    t07 = (d / DDT.DD).read_text()
    (d / DDT.DD).write_text(t07.replace("### VD-002: 둥근 버튼\n- **결정**: 반경 24\n- **상태**: 제외(시안 비교 후 제외)", "### VD-002: 둥근 버튼\n- **결정**: 반경 24\n- **상태**: 승인"))
    od2 = GD.official_design(d)
    check("P14 승인 이후 07에서 후보를 '승인'으로 바꾸면 공식 근거가 아님(승인 기록 해시 불일치 → VD·자산 공식 근거 없음)",
          not od2["design_direction_intact"] and od2["approved_vds"] == {} and not od2["assets"]["AST-001"]["official"]
          and (f11, "asset_unapproved") in kinds([f11]), od2["approved_vds"])
    (d / DDT.DD).write_text(t07)
    reg_p = d / "design-profile/assets/AST-001.svg"
    reg_o = reg_p.read_text()
    reg_p.write_text(reg_o.replace("M4 12h16", "M4 12h12"))
    check("P15 자산 파일이 등록 해시와 달라지면 공식 자산이 아님", not GD.official_design(d)["assets"]["AST-001"]["official"])
    reg_p.write_text(reg_o)
    check("P16 v1 프로젝트·탐색 없는 프로젝트는 판정 없음(기존 동작)", GD.findings(T.make_product(root, "v1-guard"), ["README.md"]) == [])
    check("P17 격리 검사 전 과정에서 승인 기록(디자인 방향 승인 제외) 불변", core(approvals(state(d)))["ux_spec"] == core(appr0)["ux_spec"]
          and core(approvals(state(d)))["ux_planning"] == core(appr0)["ux_planning"])


# ---------------------------------------------------------------- EX7 렌더러 공통 계약·Figma 선택 연동(모의 Figma 산출물)
FIGMA_KEY = "AbCdEfGhIjKlMnOpQrStUv12"


def figma_variant(d: Path, rid: str, lb: str, frames=None, nodes=True, **render_kw) -> None:
    write_vvariant(d, rid, lb, axes=("density", "component"))
    vdir = d / "design-explore" / rid / lb / "figma"
    vdir.mkdir(exist_ok=True)
    shots = {}
    for t in ("SCR-001", "SCR-003"):
        f = vdir / f"{t}-mobile.png"
        f.write_bytes(img_png((240, 248, 250), 39, 84))
        shots[t] = [{"path": f"figma/{t}-mobile.png", "viewport": "mobile", "sha256": __import__("hashlib").sha256(f.read_bytes()).hexdigest()}]
    fr = frames if frames is not None else {
        t: {"node_id": f"1:{10 + i}", "screenshots": shots[t], "tokens": ["color.action.primary", "radius.md"], "components": ["CMP-001"], "assets": []}
        for i, t in enumerate(("SCR-001", "SCR-003"))}
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    v = man["rounds"][rid]["variants"][lb]
    v["render"] = {"figma": {"file_key": FIGMA_KEY, "page_id": "0:1", "url": f"https://www.figma.com/design/{FIGMA_KEY}/explore", "tool": "figma-mcp",
                             "tool_version": "test", "frames": fr, "transfer": {"layout": True, "sample_text": True, "tokens": True}} | render_kw}
    for i, e in enumerate(v["elements"]):
        if nodes:
            e["node"] = f"2:{i + 1}"
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def set_render(d: Path, rid: str, lb: str, fn) -> None:
    man = json.loads((d / "design-explore/explore.manifest.json").read_text())
    fn(man["rounds"][rid]["variants"][lb])
    (d / "design-explore/explore.manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))


def ex7(root: Path) -> None:
    import pd_guard as GD
    d = visual_project(root, "ex7")
    appr0 = approvals(state(d))
    core = lambda a_: {k: {x: v.get(x) for x in ("status", "revision", "approved", "submitted")} for k, v in a_.items() if isinstance(v, dict) and "status" in v}
    code, out = pi("explore-renderer", "status", *P(d))
    check("N1 렌더러 기본값 html(checked·측정 가능), Figma는 꺼짐(declared·측정 불가)", code == 0 and out["default"] == "html"
          and out["renderers"]["figma"]["enabled"] is False and out["renderers"]["figma"]["level"] == "declared", out)
    assert pi("explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003", *P(d))[0] == 0
    write_vvariant(d, "V01", "A")
    write_vvariant(d, "V01", "B")
    figma_variant(d, "V01", "C")
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N2 사용자가 Figma를 선택하지 않았는데 figma 시안 → renderer_not_enabled", code == 2 and "renderer_not_enabled" in errs_of(out), errs_of(out)[:300])
    before = raw(d)
    code, out = pi("explore-renderer", "enable", "figma", "--data-scope", "sample_data_and_tokens", *P(d))
    code2, out2 = pi("explore-renderer", "enable", "figma", "--data-scope", "everything", "--note", "피그마 씁니다", *P(d))
    check("N3 Figma 사용은 사용자 문장 필요, 전송 범위는 정해진 값만, 거부 시 상태 불변", code == 2 and out["error"] == "statement_required"
          and code2 == 2 and out2["error"] == "invalid_arguments" and raw(d) == before, (out, out2))
    assert pi("explore-renderer", "enable", "figma", "--data-scope", "sample_data_and_tokens", "--note", "이번 시안 하나는 Figma로 그려 비교하고 싶어요(예시 데이터·토큰만)", *P(d))[0] == 0
    code, out = pi("explore-check", "--round", "V01", *P(d))
    rc = (out.get("renderers") or {}).get("C") or {}
    check("N4 html 2개 + figma 1개 혼합 라운드 통과: figma는 declared·스크린샷 증거·렌더러 출처 기록, 색만 다른 시안 판정 불가 경고",
          code == 0 and rc.get("level") == "declared" and rc.get("renderer") == "figma@figma-mcp" and len(rc.get("evidence") or []) == 2
          and out["renderers"]["A"]["level"] == "checked" and any("distinctness_declared_only" in w for w in out["warnings"]), errs_of(out)[:400])

    def bad(fn, frag, lb="C"):
        man0 = (d / "design-explore/explore.manifest.json").read_text()
        set_render(d, "V01", lb, fn)
        c, o = pi("explore-check", "--round", "V01", *P(d))
        (d / "design-explore/explore.manifest.json").write_text(man0)
        return c == 2 and frag in errs_of(o), errs_of(o)[:300]
    fr = lambda v: v["render"]["figma"]["frames"]
    for name, fn, frag in (
            ("대상 프레임 누락", lambda v: fr(v).pop("SCR-003"), "render_incomplete"),
            ("스크린샷 없음", lambda v: fr(v)["SCR-001"].update(screenshots=[]), "render_incomplete"),
            ("렌더링 실패", lambda v: v["render"]["figma"].update(status="failed", reason="rate limited"), "render_failed"),
            ("MCP 사용 불가", lambda v: v["render"]["figma"].update(status="unavailable", reason="MCP 연결 없음"), "render_unavailable"),
            ("파일 키 형식", lambda v: v["render"]["figma"].update(file_key="../../x"), "renderer_contract"),
            ("figma.com 밖 URL(비신뢰 출력)", lambda v: v["render"]["figma"].update(url="https://evil.example/x"), "figma.com"),
            ("요소 노드 누락", lambda v: v["elements"][0].pop("node"), "element_missing"),
            ("승인 화면 밖 컴포넌트", lambda v: fr(v)["SCR-003"].update(components=["CMP-002"]), "structure_drift"),
            ("후보 테마에 없는 토큰", lambda v: fr(v)["SCR-001"].update(tokens=["color.brand.unknown"]), "token_var_unknown"),
            ("시안 폴더 밖 스크린샷", lambda v: fr(v)["SCR-001"]["screenshots"][0].update(path="../../A/styles.css"), "render_evidence_invalid"),
            ("스크린샷 해시 불일치", lambda v: fr(v)["SCR-001"]["screenshots"][0].update(sha256="0" * 64), "render_evidence_modified"),
            ("전송 범위 기록 없음", lambda v: v["render"]["figma"].pop("transfer"), "external_transfer_unrecorded"),
            ("레퍼런스 원본 전송", lambda v: v["render"]["figma"]["transfer"].update(reference_images=True), "external_transfer_unconfirmed"),
            ("개인정보 전송", lambda v: v["render"]["figma"]["transfer"].update(personal_data=True), "external_transfer_unconfirmed")):
        ok, e = bad(fn, frag)
        check(f"N5 figma 계약 위반: {name} → {frag}", ok, e)
    els = [x for x in VIS_ELEMENTS if x[0] != "v4"]
    man0 = (d / "design-explore/explore.manifest.json").read_text()
    figma_variant(d, "V01", "C")
    set_render(d, "V01", "C", lambda v: v.update(elements=[e for e in v["elements"] if e["id"] != "v4"]))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N6 렌더러를 바꿔도 승인 구조는 그대로 검사: figma 시안에서 승인된 정보 누락 → structure_drift", code == 2 and "info-2(전적)이 시안에 없습니다(structure_drift)" in errs_of(out), errs_of(out)[:300])
    figma_variant(d, "V01", "C")
    (d / "design-explore/V01/C/figma/SCR-001-mobile.png").write_bytes(b"not a png at all, just text")
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N7 렌더러 스크린샷은 비신뢰 산출물: PNG가 아니면 render_evidence_invalid", code == 2 and "render_evidence_invalid" in errs_of(out), errs_of(out)[:300])
    figma_variant(d, "V01", "C")
    # 측정(EX4): figma는 측정하지 않음
    (d / "tools").mkdir()
    (d / "tools/fake_measure.py").write_text(FAKE_ADAPTER)
    setup_measure(d, f"{sys.executable} tools/fake_measure.py")
    fake(d)
    code, out = pi("explore-verify", "--round", "V01", *P(d))
    run = out.get("run_id")
    spec = json.loads((d / f"design-explore/V01/shots/{run}/measure-spec.json").read_text()) if run else {}
    code2, out2 = pi("explore-check", "--round", "V01", *P(d))
    check("N8 explore-verify: html 시안만 측정, figma 시안은 측정 불가로 건너뜀(not_run, 사유 기록)",
          code == 0 and out["skipped_renderer"] == {"C": "figma(측정 불가, declared)"} and {p_["variant"] for p_ in spec.get("pages", [])} == {"A", "B"}
          and out2["measurement"]["C"]["status"] == "not_run" and out2["measurement"]["A"]["status"] == "passed", (out, out2.get("measurement")))
    # 품질 평가(EX5.1): figma 시안 근거는 렌더러 스크린샷
    def ov(lb, c):
        if lb == "C":
            for k in c:
                if "evidence" in c[k]:
                    c[k]["evidence"] = ["C/figma/SCR-001-mobile.png"]
    write_quality(d, "V01", "AB", run)
    q = json.loads((d / "design-explore/V01/quality.json").read_text())
    write_quality(d, "V01", "ABC", run, override=ov)
    code, out = pi("explore-quality", "--round", "V01", *P(d))
    check("N9 품질 평가: figma 시안은 렌더러 스크린샷을 근거로 받음(측정 사실 아님), html 시안은 측정 스크린샷", code == 0, errs_of(out)[:400])
    code, out = pi("explore-compare", "--round", "V01", *P(d))
    cmp_html = (d / "design-explore/V01/compare.html").read_text() if code == 0 else ""
    check("N10 비교 페이지: 렌더러 출처 표시, figma 시안은 스크린샷", code == 0 and "렌더러 figma@figma-mcp(declared)" in cmp_html and "렌더러 html(checked)" in cmp_html
          and 'src="C/figma/SCR-001-mobile.png"' in cmp_html, out)
    write_vcritique(d, "V01", "ABC", run)
    code, out = pi("explore-choose", "--round", "V01", "--variant", "C", "--note", "C안(피그마)으로 갑니다", *P(d))
    ch = state(d)["exploration"]["visual"]["choice"] or {}
    check("N11 figma 시안 선택: 측정 미실행 경고·렌더러 스크린샷이 핵심 증거(사람 캡처 없이)·렌더러 기록, 승인 아님",
          code == 0 and ch.get("measurement") == "not_run" and ch["renderers"] == {"C": "figma@figma-mcp"}
          and [e["source"] for e in ch["evidence"]] == ["renderer_screenshot", "renderer_screenshot"]
          and core(approvals(state(d))) == core(appr0), out)
    # EX6: 렌더러 산출물도 탐색 산출물 — 제품 코드 복사 차단
    (d / "frontend/public").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(d / "design-explore/V01/C/figma/SCR-001-mobile.png", d / "frontend/public/tutorial.png")
    x = GD.findings(d, ["frontend/public/tutorial.png"])
    check("N12 Figma 렌더러 스크린샷을 제품 코드로 복사 → explore_copy(EX6 격리 유지)", x and x[0]["kind"] == "explore_copy", x)
    # 코드 어댑터(정적 HTML 산출)
    set_render(d, "V01", "B", lambda v: v["render"].update(adapter={"name": "react-static", "version": "1.0.0", "source": "V01/B/src"}))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N13 코드 어댑터는 프로젝트가 켠 것만(renderer_not_enabled)", code == 2 and "어댑터 react-static" in errs_of(out), errs_of(out)[:300])
    assert pi("explore-renderer", "enable", "adapter", "--name", "react-static", "--note", "React 정적 출력으로도 시안을 만들 수 있게", *P(d))[0] == 0
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N14 어댑터 산출 HTML은 html과 같은 대조(checked)·렌더러 버전 기록", out["renderers"]["B"]["renderer"] == "adapter:react-static@1.0.0"
          and out["renderers"]["B"]["level"] == "checked" and "react-static" not in errs_of(out), errs_of(out)[:300])
    set_render(d, "V01", "B", lambda v: v["render"]["adapter"].update(source="../../../frontend/src"))
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N15 어댑터 소스가 시안 폴더 밖(제품 코드)이면 거부", code == 2 and "시안 폴더 안" in errs_of(out), errs_of(out)[:300])
    set_render(d, "V01", "B", lambda v: v["render"].pop("adapter"))
    before = core(approvals(state(d)))
    assert pi("explore-renderer", "disable", "figma", "--note", "Figma 연결이 끊겨 html로만 진행", *P(d))[0] == 0
    code, out = pi("explore-check", "--round", "V01", *P(d))
    check("N16 Figma를 끄거나 연결이 실패해도 승인·해시·revision 불변, 해당 시안만 오류(html 시안은 그대로)",
          core(approvals(state(d))) == before and "renderer_not_enabled" in errs_of(out) and out["variants"]["A"]["ok"], errs_of(out)[:300])


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="product-design-explore-"))
    try:
        ex1(root)
        if "--ex1-only" not in sys.argv:
            globals().get("ex2", lambda r: None)(root)
            ex21(root)
            ex3(root)
            ex4(root)
            ex5(root)
            ex51(root)
            ex6(root)
            ex7(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
