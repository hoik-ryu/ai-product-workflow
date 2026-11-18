"""테스트 임시 폴더 관리: 이번 실행이 직접 만든 폴더만 기록하고, 정상·실패 종료 모두 끝에서 지웁니다.

- `mkdtemp(prefix)`로 만든 폴더와, 이 프로세스가 실행한 명령이 출력으로 알려 준 시스템 임시 폴더 안 경로(`adopt`)만 지웁니다.
  기록되지 않은 폴더(다른 프로세스·사용자·이전 실행이 만든 폴더)는 지우지 않습니다.
- 보존: 환경 변수 `PW_KEEP_TMP=1`이면 지우지 않고 경로를 출력합니다(실패 조사·증거 보존용).
- 모듈을 import만 하는 경우(예: tests/harness의 픽스처 생성)는 지우지 않습니다. 지우는 것은 `run(main)`으로 실행할 때뿐입니다.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

KEEP_ENV = "PW_KEEP_TMP"
_OWNED: list[Path] = []


def _tmp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def mkdtemp(prefix: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    _OWNED.append(p)
    return p


def adopt(path) -> None:
    """이 프로세스가 실행한 명령이 만든 임시 폴더(출력에 경로가 나온 것)를 정리 대상에 넣습니다. 시스템 임시 폴더 안만."""
    p = Path(path).resolve()
    if _tmp_root() in p.parents and p not in _OWNED:
        _OWNED.append(p)


def adopt_from_output(text: str, name_pattern: str) -> None:
    """명령 출력에서 `.../<name_pattern>/...` 형태의 경로를 찾아 그 폴더를 정리 대상에 넣습니다."""
    for m in re.finditer(r'(/[^"\s]*?/' + name_pattern + r')(?=/|")', text or ""):
        adopt(m.group(1))


def cleanup() -> None:
    if os.environ.get(KEEP_ENV) == "1":
        if _OWNED:
            print(f"임시 폴더 보존({KEEP_ENV}=1): " + ", ".join(str(p) for p in _OWNED))
        return
    root = _tmp_root()
    for p in reversed(_OWNED):
        if root in p.parents and p.exists():  # 시스템 임시 폴더 안, 이번 실행이 기록한 폴더만
            shutil.rmtree(p, ignore_errors=True)
    _OWNED.clear()


def run(main):
    """main()을 실행하고 정상·실패(예외·sys.exit) 모두 끝에서 정리합니다."""
    try:
        return main()
    finally:
        cleanup()
