"""/product-build AC 기반 자동 검증(M2.3): 테스트 실행·리포트 출처 검증·AC 매핑·증거 수준(E0–E3) 판정·무효화.

원칙
- 증거로 인정하는 리포트는 `verify`가 직접 실행한 프로필 검증 단계가 **그 실행 중에** 만든 파일뿐입니다(임의 파일 가져오기 없음).
- 실행 전후 코드 트리 해시가 같아야 유효한 실행입니다. 리포트 해시·실행 기록 digest를 남깁니다.
- AC 매핑은 구조화된 태그만 인정합니다(이름 속 `[AC-001]`, 리포트의 acs 필드, 또는 프로필 tag_style=prefix의 `AC-001 / AC-002:` 머리).
  그 밖의 언급은 E1(언급)일 뿐 검증이 아닙니다.
- E2: 태그된 테스트가 유효한 실행에서 통과. E3: 같은 테스트가 이전 실행(다른 코드 버전)에서 실패한 기록이 있고 현재 코드에서 통과.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from pb_core import BUILD_DIR_REL, digest, is_protected, now, sha_file, write_owned
from pb_exec import WEAKEN_RE, _ignored, in_patterns
from pb_scan import is_test_path
import pb_uiev as UV

EVIDENCE_REL = f"{BUILD_DIR_REL}/evidence"
REPORT_FORMATS = ("pb-json", "junit-xml", "pb-ui")  # pb-ui: 브라우저 검증 리포트 pb-ui-report/v1(M3.4)
CASE_STATUSES = ("passed", "failed", "error", "skipped")
MAX_REPORT_BYTES = 20_000_000
HISTORY_KEEP = 12
TAG_BRACKET = re.compile(r"\[\s*(AC-\d{3}(?:\s*[,/]\s*AC-\d{3})*)\s*\]")
# prefix: 테스트 이름(마지막 '>' 구간)의 콜론 앞 머리가 ID 목록으로만 이루어질 때. 예) "SCR-001-ST2 / AC-001:", "AC-001·002·003:"
PREFIX_HEAD = re.compile(r"[A-Z]{2,4}-\d{3}(?:[A-Z0-9\-·→/,\s])*")
AC_ANY = re.compile(r"\bAC-\d{3}\b")
AC_SNAKE = re.compile(r"\bac_(\d{3})\b", re.I)
LEVEL_RANK = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "EM": 3}


# ---------------------------------------------------------------- 코드 버전(트리 해시)
def tracked_files(project: Path, exclude: list[str]) -> list[str]:
    out = subprocess.run(["git", "-C", str(project), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True).stdout
    return sorted(p for p in set(out.splitlines()) if p and not _ignored(p, exclude) and not is_protected(p) and (project / p).is_file())


def tree_hash(project: Path, files: list[str]) -> str:
    h = hashlib.sha256()
    for p in sorted(set(files)):
        h.update(p.encode() + b"\0" + (sha_file(project / p) or "deleted").encode() + b"\n")
    return h.hexdigest()


def code_files(project: Path, prof: dict) -> list[str]:
    """실행 유효성 판정에 쓰는 코드 범위: 프로필 source·tests 경로(없으면 저장소 전체에서 상태·문서 제외)."""
    roots = sorted(set((prof["paths"].get("source") or []) + (prof["paths"].get("tests") or [])))
    files = tracked_files(project, list(prof["paths"].get("exclude") or []))
    if roots:
        files = [f for f in files if any(f == r or f.startswith(r.rstrip("/") + "/") for r in roots)]
    else:
        files = [f for f in files if not f.startswith(("docs/", ".ai-workflow/", "design-preview/"))]
    return files


def batch_scope_files(project: Path, prof: dict, plan_batch: dict, batch: dict, case_files: list[str]) -> list[str]:
    """배치 검증의 무효화 범위: 배치 수정 범위(allow·shared) + 배치가 바꾼 파일 + 그 AC 테스트 파일."""
    paths = plan_batch.get("paths") or {}
    pats = list(paths.get("allow") or []) + list(paths.get("shared") or [])
    files = set(f for f in tracked_files(project, list(prof["paths"].get("exclude") or [])) if in_patterns(f, pats))
    files |= set(((batch.get("run") or {}).get("submitted") or {}).get("files", {}).keys())
    files |= set(f for f in case_files if f)
    return sorted(f for f in files if not is_protected(f))


DEP_FILES = ("package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "pyproject.toml", "uv.lock", "poetry.lock",
             "requirements.txt", "requirements-dev.txt", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Gemfile.lock", "composer.lock")


def dependency_files(project: Path, prof: dict) -> list[str]:
    """의존성 선언·잠금 파일(프로필 verify.dependency_files로 덮어쓸 수 있음)."""
    declared = prof["verify"].get("dependency_files")
    files = tracked_files(project, list(prof["paths"].get("exclude") or []) + ["node_modules"])
    if declared is not None:
        return sorted(f for f in files if in_patterns(f, declared))
    return sorted(f for f in files if f.rsplit("/", 1)[-1] in DEP_FILES)


def deps_tree(project: Path, prof: dict) -> dict:
    return {f: sha_file(project / f) for f in dependency_files(project, prof)}


def deps_affecting(deps: dict, scope_files: list[str]) -> dict:
    """배치에 영향을 주는 의존성 파일: 그 파일이 있는 디렉터리 아래에 배치 파일이 있거나 저장소 루트의 파일."""
    out = {}
    for f, h in deps.items():
        d = f.rsplit("/", 1)[0] + "/" if "/" in f else ""
        if not d or any(s.startswith(d) for s in scope_files):
            out[f] = h
    return out


# ---------------------------------------------------------------- 리포트 파서
class ReportError(Exception):
    pass


PYTEST_NAME = re.compile(r"^test_ac_(\d{3}(?:_\d{3})*)(?:_|\[|$)")
TAG_STYLES = ("bracket", "prefix", "pytest_name")


def _styles(style) -> list[str]:
    return list(style) if isinstance(style, (list, tuple)) else [style or "bracket"]


def _tags(name: str, explicit: list[str] | None, style) -> list[str]:
    acs = set(a for a in (explicit or []) if re.fullmatch(r"AC-\d{3}", str(a)))
    styles = _styles(style)
    for m in TAG_BRACKET.finditer(name or ""):
        acs |= set(AC_ANY.findall(m.group(1)))
    if "pytest_name" in styles:  # 함수 이름 규칙: test_ac_010_…, test_ac_012_013_… (매개변수 [..]는 무시)
        m = PYTEST_NAME.match((name or "").split("::")[-1].split(".")[-1])
        if m:
            acs |= {f"AC-{n}" for n in m.group(1).split("_")}
    if "prefix" in styles:
        last = (name or "").split(" > ")[-1]
        head, sep, _ = last.partition(":")
        if sep and PREFIX_HEAD.fullmatch(head.strip()):
            for m in re.finditer(r"AC-(\d{3})((?:·\d{3})*)", head):
                acs.add(f"AC-{m.group(1)}")
                acs |= {f"AC-{n}" for n in m.group(2).split("·")[1:]}
    return sorted(acs)


def parse_report(path: Path, fmt: str, style: str) -> list[dict]:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ReportError("리포트가 너무 큽니다")
    cases = []
    if fmt == "pb-json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ReportError(f"JSON 해석 실패: {e}")
        if not isinstance(data, dict) or data.get("format") != "pb-test-report/v1" or not isinstance(data.get("cases"), list):
            raise ReportError("pb-test-report/v1 형식이 아닙니다(format·cases 필요)")
        for c in data["cases"]:
            if not isinstance(c, dict) or not c.get("name") or c.get("status") not in CASE_STATUSES:
                raise ReportError(f"케이스 형식 오류: {str(c)[:120]}")
            cases.append({"id": str(c.get("id") or c["name"]), "name": str(c["name"]), "file": c.get("file"), "status": c["status"],
                          "acs": _tags(c["name"], c.get("acs"), style), "mentions": sorted(set(AC_ANY.findall(c["name"]))),
                          "states": UV.state_tags(c["name"], c.get("states"), style)})
    elif fmt == "junit-xml":
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as e:
            raise ReportError(f"XML 해석 실패: {e}")
        for tc in root.iter("testcase"):
            name = tc.get("name") or ""
            cls = tc.get("classname") or ""
            if tc.find("failure") is not None:
                status = "failed"
            elif tc.find("error") is not None:
                status = "error"
            elif tc.find("skipped") is not None:
                status = "skipped"
            else:
                status = "passed"
            props = [p.get("value") for p in tc.iter("property") if (p.get("name") or "").lower() in ("ac", "acs", "acceptance_criteria")]
            explicit = [a for v in props for a in AC_ANY.findall(v or "")]
            sprops = [p.get("value") for p in tc.iter("property") if (p.get("name") or "").lower() in ("state", "states")]
            full = f"{cls} {name}".strip()
            cases.append({"id": f"{cls}::{name}", "name": name, "classname": cls, "file": tc.get("file"), "status": status,
                          "acs": _tags(name, explicit, style), "mentions": sorted(set(AC_ANY.findall(full))),
                          "states": UV.state_tags(name, [s for v in sprops for s in UV.STATE_ID.findall(v or "")], style)})
    else:
        raise ReportError(f"지원하지 않는 형식: {fmt}")
    # 같은 케이스가 여러 번 나오면 가장 나쁜 결과로(오염·중복 리포트 대비)
    worst = {"error": 3, "failed": 2, "skipped": 1, "passed": 0}
    merged: dict[str, dict] = {}
    for c in cases:
        k = c["id"]
        if k not in merged or worst[c["status"]] > worst[merged[k]["status"]]:
            merged[k] = c
    return list(merged.values())


# ---------------------------------------------------------------- 실행
def run_steps(project: Path, prof: dict, batch: str, steps: list[dict], available: set[str], timeout_default: int) -> dict:
    """검증 단계들을 실행하고 리포트를 수집합니다. 코드 트리가 실행 중 바뀌면 그 실행은 무효."""
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir_rel = f"{EVIDENCE_REL}/{batch}/runs/{run_id}"
    run_dir = project / run_dir_rel
    (run_dir / "reports").mkdir(parents=True, exist_ok=True)
    files = code_files(project, prof)
    before = tree_hash(project, files)
    code_only = tree_hash(project, [f for f in files if not is_test_path(f)])
    style = (prof["verify"].get("tag_style") or "bracket")
    results = []
    for s in steps:
        rec = {"name": s["name"], "stage": s.get("stage", "other"), "optional": bool(s.get("optional")), "report": None}
        missing = [r for r in s.get("requires", []) if r not in available]
        if missing:
            rec.update(status="not_run", reason=f"필요한 환경 없음: {', '.join(missing)}")
            results.append(rec)
            continue
        rep = s.get("report") or {}
        fixed = rep.get("path")
        pre = sha_file(project / fixed) if fixed else None
        env = dict(os.environ, PB_REPORT_DIR=str(run_dir / "reports"), PB_RUN_ID=run_id, PB_BATCH=batch)
        t0 = time.time()
        try:
            p = subprocess.run(s["run"], shell=True, cwd=project / s.get("cwd", "."), capture_output=True, text=True,
                               timeout=int(s.get("timeout") or timeout_default), env=env)
            code, out = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            code, out = 124, f"timeout\n{e.stdout or ''}{e.stderr or ''}"
        log_rel = f"{run_dir_rel}/{s['name']}.log"
        write_owned(project, log_rel, out if isinstance(out, str) else str(out))
        rec.update(exit=code, seconds=round(time.time() - t0, 1), log=log_rel, tail="\n".join(str(out).splitlines()[-30:]))
        if code == 124:
            rec.update(status="timeout")
            results.append(rec)
            continue
        if rep:
            fmt = rep.get("format")
            src = (run_dir / "reports" / rep["file"]) if rep.get("file") else (project / fixed if fixed else None)
            problem = None
            if src is None or fmt not in REPORT_FORMATS:
                problem = "프로필 report 설정 오류(format·file 또는 path 필요)"
            elif not src.is_file():
                problem = "리포트 파일이 만들어지지 않음"
            elif src.stat().st_mtime < t0 - 1:
                problem = "리포트가 이번 실행 전에 만들어진 파일임(오래된 리포트)"
            elif fixed and pre is not None and sha_file(src) == pre:
                problem = "고정 경로 리포트가 이번 실행에서 바뀌지 않음(이전 결과 재사용 의심)"
            cases, ui_rep = [], None
            if not problem and fmt == "pb-ui":
                if fixed:
                    problem = "브라우저 리포트는 실행별 폴더(file)에만 씁니다(고정 경로는 오래된 결과 위험)"
                else:
                    try:
                        ui_rep = UV.parse_ui_report(src, run_id, run_dir / "reports")
                        cases = ui_rep["cases"]
                    except UV.UIReportError as e:
                        problem = f"리포트 해석 실패: {e}"
            elif not problem:
                try:
                    cases = parse_report(src, fmt, style)
                except ReportError as e:
                    problem = f"리포트 해석 실패: {e}"
            if ui_rep is not None and ui_rep["status"] == "not_run":
                rec.update(status="not_run", reason=f"브라우저 검증 미실행: {ui_rep['reason']}", ui_report={"tool": ui_rep["tool"], "results": []})
                results.append(rec)
                continue
            if problem:
                rec.update(status="report_invalid", reason=problem)
                results.append(rec)
                continue
            dest_rel = f"{run_dir_rel}/reports/{s['name']}.{ 'xml' if fmt == 'junit-xml' else 'json'}"
            if src.resolve() != (project / dest_rel).resolve():
                write_owned(project, dest_rel, src.read_text(encoding="utf-8", errors="replace"))
            for c in cases:  # 케이스 파일(저장소 기준) 추정과 그 내용 해시(테스트가 바뀌었는지 판정용)
                base_dir = Path(s.get("cwd", "."))
                cands = [c.get("file")] if c.get("file") else []
                if c.get("classname"):
                    cl = c["classname"]
                    cands += [cl, cl.replace(".", "/") + ".py"]
                for f in cands:
                    rel = str((base_dir / f)).lstrip("./") if f else None
                    if rel and (project / rel).is_file():
                        c["file"] = rel
                        break
                else:
                    c["file"] = c.get("file") if c.get("file") and (project / c["file"]).is_file() else None
                c["test_sha"] = sha_file(project / c["file"]) if c.get("file") else None
                if c.get("file") and c["acs"]:  # 태그 테스트 파일 사본(실패→통과 사이 테스트가 바뀌었는지 판정)
                    cp_rel = f"{run_dir_rel}/testfiles/{c['file']}"
                    if not (project / cp_rel).exists():
                        write_owned(project, cp_rel, (project / c["file"]).read_text(encoding="utf-8", errors="replace"))
                    c["test_copy"] = cp_rel
            bad = [c for c in cases if c["status"] in ("failed", "error")]
            rec["report"] = {"format": fmt, "sha256": sha_file(project / dest_rel), "path": dest_rel, "cases": len(cases),
                             "failed": len(bad), "passed": sum(1 for c in cases if c["status"] == "passed")}
            rec["cases"] = cases
            if ui_rep is not None:
                rec["ui_report"] = {k: ui_rep[k] for k in ("tool", "base_url", "results")}
            if not cases:
                rec.update(status="report_empty", reason="리포트에 테스트 케이스가 없음")
            elif code != 0 and not bad:
                rec.update(status="inconsistent", reason="종료 코드는 실패인데 리포트에는 실패가 없음(리포트 신뢰 불가)")
            elif code == 0 and bad:
                rec.update(status="failed", reason="종료 코드는 성공인데 리포트에 실패가 있음")
            else:
                rec["status"] = "passed" if code == 0 else "failed"
        else:
            rec["status"] = "passed" if code == 0 else "failed"
        results.append(rec)
    after = tree_hash(project, code_files(project, prof))
    run = {"run_id": run_id, "batch": batch, "at": now(), "tree_before": before, "tree_after": after, "code_only_tree": code_only,
           "deps_tree": deps_tree(project, prof),
           "valid": before == after, "steps": results, "dir": run_dir_rel}
    if before != after:
        run["invalid_reason"] = "실행 중 코드가 바뀌었습니다(결과를 증거로 쓰지 않음)"
    body = {k: v for k, v in run.items()}
    body["digest"] = digest({k: v for k, v in body.items() if k != "digest"})
    write_owned(project, f"{run_dir_rel}/run.json", json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    run["digest"] = body["digest"]
    return run


def load_run(project: Path, rec: dict) -> dict | None:
    """기록된 실행의 원본(run.json)이 있고 digest가 맞으면 반환."""
    if not rec or not rec.get("dir"):
        return None
    p = project / rec["dir"] / "run.json"
    if not p.exists():
        return None
    try:
        body = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if body.get("digest") != rec.get("digest") or body.get("digest") != digest({k: v for k, v in body.items() if k != "digest"}):
        return None
    return body


# ---------------------------------------------------------------- AC 판정
def mentions_in_tests(project: Path, prof: dict) -> set[str]:
    out = set()
    for f in code_files(project, prof):
        if is_test_path(f):
            try:
                txt = (project / f).read_text(encoding="utf-8", errors="replace")
                out |= set(AC_ANY.findall(txt)) | {f"AC-{n}" for n in AC_SNAKE.findall(txt)}
            except OSError:
                pass
    return out


def update_history(hist: dict, run: dict, tree: str, mode: str = "final") -> None:
    for s in run["steps"]:
        for c in s.get("cases", []):
            if not c["acs"]:
                continue
            h = hist.setdefault(c["id"], {"acs": c["acs"], "file": c.get("file"), "records": []})
            h["acs"] = c["acs"]
            h["records"].append({"run": run["run_id"], "tree": tree, "code": run.get("code_only_tree"), "test_sha": c.get("test_sha"),
                                 "test_copy": c.get("test_copy"),
                                 "status": c["status"], "at": run["at"], "valid": run["valid"], "batch": run["batch"], "mode": mode})
            h["records"] = h["records"][-HISTORY_KEEP:]


def test_weakened_or_changed(project: Path | None, red: dict, current: dict) -> bool:
    """실패 시점과 지금 사이에 테스트 파일의 기존 줄이 지워지거나 바뀌었거나, 약화 표기가 추가됐으면 True(추가만은 허용)."""
    if red.get("test_sha") == current.get("test_sha"):
        return False
    if project is None or not red.get("test_copy") or not current.get("file"):
        return True
    try:
        old = (project / red["test_copy"]).read_text(encoding="utf-8", errors="replace").splitlines()
        new = (project / current["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return True
    fn = current.get("func")
    if fn:  # 그 테스트 함수 블록만 비교(Python def). 찾지 못하면 파일 전체 비교(보수적)
        ob, nb = _py_block(old, fn), _py_block(new, fn)
        if ob is not None and nb is not None:
            old, new = ob, nb
    for line in difflib.unified_diff(old, new, lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-") and line[1:].strip():
            return True
        if line.startswith("+") and WEAKEN_RE.search(line):
            return True
    return False


def _py_block(lines: list[str], fn: str) -> list[str] | None:
    for i, ln in enumerate(lines):
        m = re.match(rf"^(\s*)(?:async\s+)?def\s+{re.escape(fn)}\s*\(", ln)
        if m:
            ind = len(m.group(1))
            out = [ln]
            for nx in lines[i + 1:]:
                if nx.strip() and len(nx) - len(nx.lstrip()) <= ind and not nx.lstrip().startswith((")", "]", "}")):
                    break
                out.append(nx)
            j = i - 1
            while j >= 0 and lines[j].strip().startswith("@"):  # 데코레이터(skip 등)도 포함
                out.insert(0, lines[j])
                j -= 1
            return out
    return None


def case_func(case_id: str) -> str | None:
    last = re.split(r"::|\.", case_id or "")[-1]
    last = last.split("[")[0]
    return last if re.fullmatch(r"[A-Za-z_]\w*", last or "") else None


def classify_e3(records: list[dict], current: dict | None, batch: str, project: Path | None = None) -> tuple[str | None, str]:
    """통과한 현재 기록에 대한 실패→통과 이력의 유형.
    fix: 테스트의 첫 결과가 실패이고, 테스트 파일은 그대로인 채 코드가 바뀌어 통과(테스트 먼저·실제 결함 수정)
    regression_fix: 통과하던 테스트가 '다른 배치'의 실행에서 실패(회귀 감지)한 뒤, 이전과 다른 코드로 고쳐 통과
    fault_injection: 통과하던 테스트를 같은 배치에서 실패시켰다가 다시 통과(정상 코드 훼손·복구) — E3 아님
    test_changed: 실패와 통과 사이에 테스트 파일이 바뀜 — E3 아님"""
    if not current or current["status"] != "passed":
        return None, ""
    valid = [r for r in records if r.get("valid")]
    kinds = []
    for i, r in enumerate(valid):
        if r["status"] not in ("failed", "error") or r.get("code") is None:
            continue
        if test_weakened_or_changed(project, r, current):
            kinds.append(("test_changed", "실패와 통과 사이에 테스트의 기존 줄이 바뀌거나 약화 표기가 추가됨"))
            continue
        if r.get("code") == current.get("code"):
            kinds.append(("fault_injection", "실패 때와 같은 코드로 통과(코드 수정 없음)"))
            continue
        before = [x for x in valid[:i] if x["status"] == "passed"]
        if not before:
            kinds.append(("fix", "테스트가 처음 실패 → 코드 수정 → 통과"))
        elif r.get("batch") != batch:
            if current.get("code") in {x.get("code") for x in before}:
                kinds.append(("fault_injection", "회귀 후 이전과 같은 코드로 되돌려 통과(수정이 아니라 복구)"))
            else:
                kinds.append(("regression_fix", f"다른 배치({r.get('batch')}) 실행에서 회귀 감지 → 수정 → 통과"))
        else:
            kinds.append(("fault_injection", "통과하던 테스트를 같은 배치에서 실패시켰다가 다시 통과(결함 주입·복구)"))
    for want in ("fix", "regression_fix", "fault_injection", "test_changed"):
        for k, why in kinds:
            if k == want:
                return k, why
    return None, ""


def evaluate(acs: list[str], targets: dict, run: dict, hist: dict, mentioned: set[str], tree: str,
             accept_fi: set[str] | None = None, legacy: bool = False, project: Path | None = None) -> dict:
    """AC별 판정: verified / insufficient / failing / not_run / untested / invalid_run."""
    steps = run["steps"]
    # 필수 단계가 실행되지 않았거나 결과를 믿을 수 없을 때만 '미실행' 사유로 씀(선택 단계 미실행은 태그 테스트 없음과 구분)
    not_run = [s["name"] for s in steps if s["status"] == "not_run" and not s.get("optional")]
    broken = [s["name"] for s in steps if s["status"] in ("report_invalid", "report_empty", "inconsistent", "timeout") and not s.get("optional")]
    cases = [c for s in steps for c in s.get("cases", [])]
    out = {}
    for a in acs:
        target = targets.get(a, "E2")
        mine = [c for c in cases if a in c["acs"]]
        rec = {"target": target, "cases": [{"id": c["id"], "status": c["status"]} for c in mine][:10]}
        if not run["valid"]:
            rec.update(status="invalid_run", level="E1" if a in mentioned else "E0", reason=run.get("invalid_reason"))
        elif any(c["status"] in ("failed", "error") for c in mine):
            rec.update(status="failing", level="E1", reason="태그된 테스트 실패: " + ", ".join(c["id"] for c in mine if c["status"] in ("failed", "error"))[:300])
        elif mine and all(c["status"] == "skipped" for c in mine):
            rec.update(status="not_run", level="E1", reason="태그된 테스트가 모두 건너뛰어짐(skipped)")
        elif mine:
            level, types = "E2", []
            cur_code = run.get("code_only_tree")
            for c in mine:
                recs = hist.get(c["id"], {}).get("records", [])
                kind, why = classify_e3(recs[:-1] if recs and recs[-1].get("run") == run["run_id"] else recs,
                                        {"status": c["status"], "code": cur_code, "test_sha": c.get("test_sha"), "file": c.get("file"),
                                         "func": case_func(c["id"])},
                                        run["batch"], project)
                if kind:
                    types.append({"case": c["id"], "type": kind, "why": why})
                if kind in ("fix", "regression_fix"):
                    level = "E3"
            rec.update(level=level, evidence=types)
            fi_ok = a in (accept_fi or set()) and any(x["type"] == "fault_injection" for x in types)
            if LEVEL_RANK[level] >= LEVEL_RANK.get(target, 2):
                rec.update(status="verified", reason=f"태그된 테스트 통과({level}" + (", 실패→수정→통과" if level == "E3" else "") + ")")
            elif target == "E3" and fi_ok:
                rec.update(status="verified", reason="E2 + 결함 주입 증거(사용자 승인으로 이 AC에 인정됨) — 실제 결함 수정 이력은 아님")
            elif target == "E3":
                hint = [x["why"] for x in types if x["type"] in ("fault_injection", "test_changed")]
                rec.update(status="insufficient", reason="E2 증거 — 목표 E3(실제 실패→수정→통과 기록 필요)"
                           + (f"; 인정되지 않은 이력: {hint[0]}" if hint else "")
                           + ("; 기존 구현: 실패 우선 기록 불가 → 결함 주입 증거 인정 또는 목표 변경은 사용자 승인 필요" if legacy else ""))
            else:
                rec.update(status="insufficient", reason=f"{level} < 목표 {target}")
        else:
            level = "E1" if a in mentioned else "E0"
            rec["level"] = level
            if LEVEL_RANK[level] >= LEVEL_RANK.get(target, 2):
                rec.update(status="verified", reason=f"목표 {target} 충족(언급)")
            elif not_run or broken:
                rec.update(status="not_run", reason="태그된 테스트 결과 없음 — 실행되지 않은 단계: " + ", ".join(not_run + broken))
            else:
                rec.update(status="untested", reason="태그된 테스트 없음" + (" (테스트에 언급만 있음: E1)" if level == "E1" else ""))
        out[a] = rec
    return out


def step_summary(run: dict) -> dict:
    return {s["name"]: {k: s.get(k) for k in ("status", "exit", "reason", "log") if s.get(k) is not None}
            | ({"report": {k: s["report"][k] for k in ("format", "cases", "passed", "failed", "sha256")}} if s.get("report") else {})
            for s in run["steps"]}


def batch_verdict(run: dict, evaluation: dict) -> tuple[bool, list[str]]:
    reasons = []
    if not run["valid"]:
        reasons.append(run.get("invalid_reason", "무효 실행"))
    for s in run["steps"]:
        if s["status"] != "passed" and not s.get("optional"):
            reasons.append(f"검증 단계 {s['name']}: {s['status']}" + (f" ({s.get('reason')})" if s.get("reason") else ""))
    req = {a: e for a, e in evaluation.items() if LEVEL_RANK.get(e["target"], 2) >= 2}
    for a, e in sorted(req.items()):
        if e["status"] != "verified":
            reasons.append(f"{a}: {e['status']} — {e.get('reason')}")
    return not reasons, reasons
