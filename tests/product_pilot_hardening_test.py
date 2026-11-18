#!/usr/bin/env python3
"""v1.0 제한 파일럿 전 보완 회귀 테스트: 데이터 손실·경로 이탈·상태 불일치.

- H1 선택 기록 원자성: explore-choose가 이전 선택을 지운 뒤 실패하지 않음(이전 선택 폴더 안 증거 재사용, 상태 저장 실패 시 되돌림)
- H2·H3 부분 쓰기: explore-init·explore-ref add가 중간에 실패해도 폴더·manifest가 남지 않아 다시 시도할 수 있음
- H4 경로 안전성: explore-tokens --variants, explore-choose --evidence, manifest render.html·plan(.., URL 인코딩, 심볼릭 링크)
- H5 잘못된 JSON: design.json·탐색 theme.json·assets.json 최상위 형식 오류 → 구조화된 오류·차단, 상태 불변
- H6 구조 탐색 stale: planning 재승인(r2) 뒤 이전 구조 선택으로 UX Planning 제출 불가, 다시 선택하면 해소
모든 승인·선택은 임시 프로젝트 안의 시뮬레이션입니다. 실행: python3 tests/product_pilot_hardening_test.py [--keep <폴더>]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import product_stabilization_test as S  # noqa: E402  (승인·작성 중 프로젝트 픽스처)

W, T, XT = S.W, S.T, S.XT
pd, pb, ps = S.pd, S.pb, S.ps
results: list[tuple[str, bool]] = []


def check(name, cond, detail=None):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  -- {str(detail)[:700]}"))


def tree_hashes(d: Path) -> dict:
    return {str(p.relative_to(d)): T.sha(p) for p in sorted(d.rglob("*")) if p.is_file()} if d.exists() else {}


class readonly:
    """상태 폴더를 읽기 전용으로 만들어 상태 저장(save_state) 단계에서 실패를 일으킵니다."""

    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        self.mode = self.p.stat().st_mode
        os.chmod(self.p, stat.S_IRUSR | stat.S_IXUSR)

    def __exit__(self, *a):
        os.chmod(self.p, self.mode)


def errs(out) -> str:
    return json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------- H1
def h1_choose(mid: Path, root: Path) -> None:
    m = S.copy_project(mid, root / "h1")
    sel = m / "design-explore/V02/selection"
    ev = next(p for p in sorted((sel / "evidence").glob("m-A-*.png")))
    code, out = pd(m, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안으로 다시 확인했어요(시뮬레이션)",
                   "--evidence", str(ev.relative_to(m)))
    code2, st2 = pd(m, "explore-status")
    check("H1a 이전 선택 폴더 안의 증거로 다시 선택해도 성공, 선택 기록 무결(changed_since_choice·retention_missing 없음)",
          code == 0 and not (st2.get("integrity") or {}).get("visual", {}).get("changed") and not (st2.get("integrity") or {}).get("visual", {}).get("missing"),
          (out.get("error"), out.get("message"), st2.get("warnings")))
    before_sel, before_state = tree_hashes(sel), (m / ".ai-workflow/design.json").read_bytes()
    with readonly(m / ".ai-workflow"):
        code, out = pd(m, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안(시뮬레이션)")
    left = [p.name for p in (m / "design-explore/V02").iterdir() if p.name.startswith(".selection.")]
    check("H1b 상태 저장 단계에서 실패하면 이전 선택 기록·상태 파일 바이트 그대로, 임시 폴더 없음",
          code != 0 and tree_hashes(sel) == before_sel and (m / ".ai-workflow/design.json").read_bytes() == before_state and not left,
          (code, out.get("error"), left, set(before_sel) ^ set(tree_hashes(sel))))
    code, out = pd(m, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안(시뮬레이션)")
    check("H1c 실패 후 다시 시도하면 정상 선택", code == 0, out)


# ---------------------------------------------------------------- H2·H3
def h2_init_ref(mid: Path, root: Path) -> None:
    m = S.copy_project(mid, root / "h2")
    man0 = (m / "design-explore/explore.manifest.json").read_bytes()
    with readonly(m / ".ai-workflow"):
        code, out = pd(m, "explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003")
    check("H2a explore-init이 상태 저장에서 실패 → 라운드 폴더(V03)·manifest 변경 없음",
          code != 0 and not (m / "design-explore/V03").exists() and (m / "design-explore/explore.manifest.json").read_bytes() == man0, (code, out.get("error")))
    code, out = pd(m, "explore-init", "--phase", "visual", "--targets", "SCR-001,SCR-003")
    check("H2b 실패 후 다시 시도하면 같은 라운드(V03) 생성(existing_files로 막히지 않음)", code == 0 and (m / "design-explore/V03").is_dir(), out)
    img = root / "h3-ref"
    img.mkdir()
    (img / "ref2.png").write_bytes(XT.img_png((200, 30, 40), 7, 7))
    with readonly(m / ".ai-workflow"):
        code, out = pd(m, "explore-ref", "add", "--file", str(img / "ref2.png"), "--rights", "own")
    check("H3a explore-ref add가 상태 저장에서 실패 → 등록 폴더(REF-002) 남지 않음", code != 0 and not (m / "design-explore/references/REF-002").exists(), (code, out.get("error")))
    code, out = pd(m, "explore-ref", "add", "--file", str(img / "ref2.png"), "--rights", "own")
    check("H3b 다시 시도하면 REF-002 등록", code == 0 and out.get("reference") == "REF-002", out)


# ---------------------------------------------------------------- H4
def h4_paths(mid: Path, root: Path) -> None:
    m = S.copy_project(mid, root / "h4")
    out_dir = m / "outside"
    out_dir.mkdir()
    shutil.copyfile(m / "design-explore/V01/A/theme.json", out_dir / "theme.json")
    before = S.raw(m)
    code, out = pd(m, "explore-tokens", "--round", "V01", "--variants", "../../outside")
    check("H4a explore-tokens --variants로 시안 폴더 밖 쓰기 거부(invalid_arguments), 밖에 tokens.css 없음",
          code == 2 and out.get("error") == "invalid_arguments" and not (out_dir / "tokens.css").exists() and S.raw(m) == before, out)
    code, out = pd(m, "explore-tokens", "--round", "V01", "--variants", "A")
    check("H4b 정상 시안 이름은 통과", code == 0 and "A" in (out.get("generated") or {}), out)
    ext = root / "outside-project.png"
    ext.write_bytes(XT.img_png((1, 2, 3), 4, 4))
    os.symlink(ext, m / "design-explore/link-shot.png")
    (m / "fake.png").write_text("not an image")
    res = {}
    for name, path in (("밖 절대 경로", str(ext)), ("밖을 가리키는 심볼릭 링크", "design-explore/link-shot.png"), ("이미지 아닌 .png", "fake.png")):
        b = S.raw(m)
        c, o = pd(m, "explore-choose", "--round", "V02", "--variant", "A", "--note", "A안(시뮬레이션)", "--evidence", path)
        res[name] = (c, o.get("error"), S.raw(m) == b)
    check("H4c --evidence: 프로젝트 밖 경로·밖을 가리키는 링크·이미지가 아닌 파일 거부(invalid_evidence), 상태 불변",
          all(v[0] == 2 and v[1] == "invalid_evidence" and v[2] for v in res.values()), res)
    man_p = m / "design-explore/explore.manifest.json"
    man0 = man_p.read_text()
    (out_dir / "page.html").write_text("<html><body>밖</body></html>")
    os.symlink(out_dir / "page.html", m / "design-explore/V01/A/link.html")
    cases = {"..": "V01/../../outside/page.html", "URL 인코딩 ..": "V01/A/%2e%2e/%2e%2e/%2e%2e/outside/page.html",
             "다른 시안 폴더": "V01/B/index.html", "심볼릭 링크": "V01/A/link.html", "절대 경로": str(out_dir / "page.html")}
    res = {}
    for name, rel in cases.items():
        man = json.loads(man0)
        man["rounds"]["V01"]["variants"]["A"]["render"]["html"] = rel
        man_p.write_text(json.dumps(man, ensure_ascii=False))
        c, o = pd(m, "explore-check", "--round", "V01")
        res[name] = (c, "variant_path_invalid" in XT.errs_of(o))
    man = json.loads(man0)
    man["rounds"]["V01"]["variants"]["A"]["plan"] = "V01/../../outside/plan.md"
    man_p.write_text(json.dumps(man, ensure_ascii=False))
    c, o = pd(m, "explore-check", "--round", "V01")
    res["plan .."] = (c, "variant_path_invalid" in XT.errs_of(o))
    man_p.write_text(man0)
    c, o = pd(m, "explore-check", "--round", "V01")
    check("H4d manifest render.html·plan이 시안 폴더 밖(.., URL 인코딩, 다른 시안, 심볼릭 링크, 절대 경로) → variant_path_invalid",
          all(v == (2, True) for v in res.values()), res)
    check("H4e 정상 manifest 경로는 통과(오탐 없음)", "variant_path_invalid" not in XT.errs_of(o), XT.errs_of(o)[:300])


# ---------------------------------------------------------------- H5
def h5_json(approved: Path, root: Path) -> None:
    res = {}
    for name, rel, content in ((".ai-workflow/design.json", ".ai-workflow/design.json", "[]"),
                               ("탐색 theme.json", "design-explore/V01/B/theme.json", "[]"),
                               ("공식 theme.json", "design-profile/theme.json", '["x"]'),
                               ("assets.json 항목", "design-profile/assets.json", '{"format":"design-assets/v1","icon_style":null,"assets":{"AST-001":[1]}}')):
        d = S.copy_project(approved, root / f"h5-{len(res)}")
        (d / rel).write_text(content)
        before = S.raw(d)
        outs = {"preview-check": pd(d, "preview-check"), "check": pd(d, "check"),
                "ui-guard": pb(d, "ui-guard", "--path", "web/src/styles/tokens.css"), "token-check": pb(d, "token-check"),
                "explore-asset list": pd(d, "explore-asset", "list")}
        res[name] = {k: (c, o.get("error")) for k, (c, o) in outs.items()}
        res[name]["_unchanged"] = S.raw(d) == before
        res[name]["_internal"] = [k for k, (c, o) in outs.items() if o.get("error") == "internal_error" or c == 1]
    check("H5a 잘못된 JSON(최상위 형식) → internal_error·traceback 없이 구조화된 오류, 상태 파일 불변", all(not v["_internal"] and v["_unchanged"] for v in res.values()), res)
    check("H5b design.json 형식 오류 → preview-check·check·ui-guard·token-check 모두 차단(종료 2)",
          all(res[".ai-workflow/design.json"][k][0] == 2 for k in ("preview-check", "check", "ui-guard", "token-check")), res[".ai-workflow/design.json"])
    check("H5c 탐색·공식 테마 형식 오류 → preview-check·ui-guard 차단", all(res[n][k][0] == 2 for n in ("탐색 theme.json", "공식 theme.json") for k in ("preview-check", "ui-guard")),
          {n: res[n] for n in ("탐색 theme.json", "공식 theme.json")})
    check("H5d 자산 항목 형식 오류 → explore-asset invalid_assets, Build 차단", res["assets.json 항목"]["explore-asset list"] == (2, "invalid_assets")
          and res["assets.json 항목"]["ui-guard"][0] == 2, res["assets.json 항목"])


# ---------------------------------------------------------------- H6
def h6_structure_stale(root: Path) -> None:
    (root / "s").mkdir()
    d = W.stage_start(root / "s")
    W.stage_ux_planning(d, root)
    assert ps(d, "reopen", "--stage", "planning", "--revision", "1", "--confirm", "--note", "범위 재검토(시뮬레이션)")[0] == 0
    for f in W.PLANNING:
        W.planning_doc(d, Path(f).name, rev=2)
    p3 = d / W.PLANNING[1]
    p3.write_text(p3.read_text() + "\n- 추가 메모(r2)\n")
    assert ps(d, "submit", "--stage", "planning", "--revision", "2", "--confirm")[0] == 0
    assert ps(d, "approve", "--stage", "planning", "--revision", "2")[0] == 0
    T.G(d, "add", "-A")
    T.G(d, "commit", "-qm", "planning r2")
    code, out = pd(d, "rebase", "--confirm")
    assert code == 0, out
    p00 = d / T.UXP
    p00.write_text(re.sub(r"^revision: \d+", "revision: 2", p00.read_text(), count=1, flags=re.M))
    code, out = pd(d, "done", "--path", T.UXP)
    assert code == 0, out
    before = S.raw(d)
    code, out = pd(d, "submit", "--stage", "ux_planning")
    check("H6a planning 재승인(r2)·rebase 뒤 이전(r1) 구조 선택으로 UX Planning 제출 → exploration_choice_stale, 상태 불변",
          code == 2 and out.get("error") == "exploration_choice_stale" and "planning" in errs(out.get("reasons")) and S.raw(d) == before, out)
    code, out = pd(d, "explore-status")
    check("H6b explore-status가 구조 선택을 stale로 표시", "structure" in (out.get("stale") or {}), out.get("stale"))
    code, out = pd(d, "explore-choose", "--round", "S01", "--variant", "B", "--note", "r2 기준으로 다시 봐도 B안이에요(시뮬레이션)",
                   "--coverage-note", "인증 실패 안내는 오류 상태에서 다루는 것에 다시 동의(시뮬레이션)")
    code2, out2 = pd(d, "submit", "--stage", "ux_planning")
    check("H6c 현재 기준으로 다시 선택하면 stale 해소(제출이 stale로 막히지 않음)", code == 0 and out2.get("error") != "exploration_choice_stale", (out, out2))


def main() -> int:
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="product-pilot-hardening-"))
    if keep:
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
    try:
        approved, mid = S.build_projects(root)
        for name, fn, args in (("H1", h1_choose, (mid, root)), ("H2·H3", h2_init_ref, (mid, root)), ("H4", h4_paths, (mid, root)),
                               ("H5", h5_json, (approved, root)), ("H6", h6_structure_stale, (root,))):
            try:
                fn(*args)
            except Exception as e:  # noqa: BLE001
                check(f"{name} 그룹 실행 중 예외", False, f"{type(e).__name__}: {e}")
    finally:
        for p in root.rglob(".ai-workflow"):
            try:
                os.chmod(p, 0o755)
            except OSError:
                pass
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    bad = [x for x in results if not x[1]]
    print(f"\nRESULT {len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
