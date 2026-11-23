"""TEMP 산출물(일회성 탐색·검증·디버깅 결과) 작업 폴더 경로(docs/policies/artifact-retention.md).

원칙
- 엔진 명령이 아닌 작업(검토용 캡처·임시 측정 JSON·테스트 로그·중간 렌더)은 제품 저장소 **밖**의 실행 폴더에 씁니다.
  기본 경로: `$AI_WORKFLOW_TEMP_ROOT` → `$XDG_CACHE_HOME/ai-product-workflow/temp` → `~/.cache/ai-product-workflow/temp`
  그 아래 `<프로젝트 키>/runs/<용도>/<실행 ID>/`(프로젝트 키 = 폴더 이름 + 절대 경로 해시).
- 저장소 밖에 쓸 수 없으면(샌드박스 등) 저장소 안 `.ai-workflow/tmp/`로 대체합니다. 이 폴더는 스스로를 무시하는
  `.gitignore`(`*`)를 가지므로 프로젝트 `.gitignore`를 고치지 않아도 Git 변경 파일이 늘지 않습니다.
- 오류 재현 자료는 `--keep`(새 폴더) 또는 `--mark-keep <폴더>`(기존 폴더)로 보관 표시(KEEP.json)를 남깁니다. 옮기지 않습니다.
- 이 모듈은 폴더를 만들고 메타(RUN.json·KEEP.json)만 씁니다. 상태 파일(state.yaml·design.json·build.json)·승인 해시·
  기존 산출물 경로(design-explore·design-preview·.ai-workflow/build/evidence)는 건드리지 않고, 아무것도 지우지 않습니다.
- product-build의 pb_temp.py와 같은 규칙입니다(Skill 간 import 없음). 한쪽을 바꾸면 다른 쪽도 같이 바꿉니다(테스트가 일치를 확인).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

TEMP_FORMAT = "ai-workflow-temp-run/v1"
ENV_ROOT = "AI_WORKFLOW_TEMP_ROOT"
REPO_FALLBACK_REL = ".ai-workflow/tmp"
PURPOSE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RUN_META = "RUN.json"
KEEP_META = "KEEP.json"


class TempPathError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_root() -> tuple[Path, str]:
    env = os.environ.get(ENV_ROOT, "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.is_absolute():
            raise TempPathError("temp_root_not_absolute", f"{ENV_ROOT}는 절대 경로여야 합니다: {env}")
        return p, "env"
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg and Path(xdg).expanduser().is_absolute() else Path.home() / ".cache"
    return base / "ai-product-workflow" / "temp", "default"


def project_key(project: Path) -> str:
    rp = project.resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", rp.name).strip("-.") or "project"
    return f"{name[:40]}-{hashlib.sha256(str(rp).encode('utf-8')).hexdigest()[:10]}"


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _ensure_repo_fallback(project: Path) -> Path:
    base = project / REPO_FALLBACK_REL
    base.mkdir(parents=True, exist_ok=True)
    gi = base / ".gitignore"
    if not gi.exists():
        gi.write_text("# ai-product-workflow TEMP 폴백 경로(저장소 밖에 쓸 수 없을 때). 이 폴더 전체를 Git에서 제외합니다.\n*\n", encoding="utf-8")
    return base


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def create_run(project: Path, purpose: str, keep: bool = False, note: str = "", location: str = "auto") -> dict:
    """실행 단위 TEMP 폴더를 만들고 경로를 돌려줍니다. location: auto(밖 → 실패 시 저장소 안 폴백) | outside | repo."""
    project = project.resolve()
    if not project.is_dir():
        raise TempPathError("project_not_found", f"프로젝트 폴더가 없습니다: {project}")
    if not PURPOSE_RE.match(purpose or ""):
        raise TempPathError("invalid_purpose", "--purpose는 영문 소문자·숫자·하이픈 1–40자입니다(예: preview-review, explore-review, e2e, visual, measure, debug).")
    if keep and not note.strip():
        raise TempPathError("keep_note_required", "--keep에는 보관 이유(--note)가 필요합니다.")
    rid, kind = _run_id(), ("kept" if keep else "runs")
    fallback_reason = None
    base = None
    if location in ("auto", "outside"):
        root, source = default_root()
        if _inside(root, project):
            raise TempPathError("temp_root_inside_project", f"TEMP 루트({root})가 제품 저장소 안입니다. 저장소 밖 경로를 쓰거나 --location repo를 쓰세요.")
        try:
            base = root / project_key(project)
            (base / kind / purpose / rid).mkdir(parents=True)
            pj = base / "PROJECT.json"
            if not pj.exists():
                pj.write_text(json.dumps({"format": TEMP_FORMAT, "project": str(project), "created_at": _now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as e:
            if location == "outside":
                raise TempPathError("temp_root_unwritable", f"TEMP 루트에 쓸 수 없습니다({root}): {e}")
            fallback_reason, base = f"저장소 밖 TEMP 루트에 쓸 수 없음({type(e).__name__}): {root}", None
    if base is None:
        root, source = _ensure_repo_fallback(project), "repo_fallback"
        base = root
        (base / kind / purpose / rid).mkdir(parents=True)
    d = base / kind / purpose / rid
    meta = {"format": TEMP_FORMAT, "class": "TEMP", "project": str(project), "purpose": purpose, "run_id": rid, "created_at": _now(),
            "location": source, "keep": keep, "retention_days": None}
    (d / RUN_META).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if keep:
        _write_keep(d, note)
    return {"ok": True, "temp_dir": str(d), "run_id": rid, "purpose": purpose, "kept": keep, "location": source,
            "inside_repo": _inside(d, project), "root": str(root), "project_key": project_key(project), "fallback_reason": fallback_reason,
            "env": {"AI_WORKFLOW_TEMP_DIR": str(d)},
            "note": "일회성 캡처·측정·로그는 이 폴더에 씁니다. 승인 근거로 남길 파일만 엔진 명령(explore-choose --evidence 등)으로 등록하세요. "
                    "엔진은 이 폴더를 자동으로 지우지 않습니다."}


def _write_keep(d: Path, note: str) -> None:
    (d / KEEP_META).write_text(json.dumps({"format": TEMP_FORMAT, "keep": True, "note": note.strip(), "marked_at": _now()},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_keep(project: Path, run_dir: str, note: str) -> dict:
    """기존 실행 폴더에 보관 표시만 남깁니다(이동·복사 없음). 이 프로젝트의 TEMP 실행 폴더만 허용합니다."""
    project = project.resolve()
    if not note.strip():
        raise TempPathError("keep_note_required", "--mark-keep에는 보관 이유(--note)가 필요합니다.")
    d = Path(run_dir).expanduser().resolve()
    meta_p = d / RUN_META
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise TempPathError("not_temp_run", f"TEMP 실행 폴더가 아닙니다({RUN_META} 없음): {d}")
    if meta.get("format") != TEMP_FORMAT or Path(meta.get("project") or "").resolve() != project:
        raise TempPathError("not_temp_run", f"이 프로젝트의 TEMP 실행 폴더가 아닙니다: {d}")
    _write_keep(d, note)
    return {"ok": True, "temp_dir": str(d), "kept": True, "note": "보관 표시(KEEP.json)를 남겼습니다. 향후 정리 대상에서 제외됩니다."}


def cli(project: Path, purpose: str | None, keep: bool, note: str, location: str, mark: str | None) -> dict:
    if mark:
        return mark_keep(project, mark, note)
    if not purpose:
        raise TempPathError("invalid_arguments", "--purpose 또는 --mark-keep 중 하나가 필요합니다.")
    return create_run(project, purpose, keep=keep, note=note, location=location)
