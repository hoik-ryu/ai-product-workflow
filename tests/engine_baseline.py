"""회귀 비교용 기준 엔진 추출(테스트 도우미).

비교 기준은 '테스트 목적에 맞는 고정 커밋'입니다. HEAD를 쓰지 않습니다(커밋할 때마다 기준이 움직여 비교 의미가 사라지므로).
- V1_ENGINE: /product-design v1 엔진(WF-D01 이전, 모듈 분리 이전). v1 명령 결과가 이 엔진과 같아야 한다는 테스트에 씁니다.

추출은 그 커밋의 `skills/product-design/scripts/` 디렉터리 **전체**를 가져옵니다(모듈 분리 이후에도 실행 가능).
기준 커밋이 저장소에 없으면(얕은 클론 등) 조용히 건너뛰지 않고 실패합니다.
"""
from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
V1_ENGINE = "b83907b39b4b697c188a901da765c13b832c183e"  # feat(product-design): UX 설계 및 UI 프리뷰 승인 워크플로 추가
SCRIPTS_REL = "skills/product-design/scripts"


def resolve(commit: str) -> str:
    p = subprocess.run(["git", "-C", str(ENGINE), "rev-parse", "--verify", f"{commit}^{{commit}}"], capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"기준 커밋 {commit}을 찾을 수 없습니다(얕은 클론이면 전체 이력을 가져오세요). 회귀 비교를 건너뛰지 않고 중단합니다.")
    return p.stdout.strip()


def extract_skill(commit: str, dest: Path, templates_from_current: bool = True) -> Path:
    """기준 커밋의 scripts 디렉터리 전체를 dest/scripts에 풀고, CLI 경로를 돌려줍니다.
    templates_from_current: 템플릿은 현재 엔진 것을 링크(기존 테스트와 같은 조건: 비교 대상은 스크립트 동작)."""
    sha = resolve(commit)
    data = subprocess.run(["git", "-C", str(ENGINE), "archive", "--format=tar", sha, SCRIPTS_REL], capture_output=True, check=True).stdout
    dest.mkdir(parents=True, exist_ok=True)
    prefix = SCRIPTS_REL + "/"
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            if not m.isfile() or not m.name.startswith(prefix):
                continue
            rel = m.name[len(prefix):]
            if "/" in rel or not rel.endswith(".py"):
                continue
            out = dest / "scripts" / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tf.extractfile(m).read())
    cli = dest / "scripts/product_design.py"
    if not cli.exists():
        raise SystemExit(f"기준 커밋 {sha[:7]}에 {SCRIPTS_REL}/product_design.py가 없습니다.")
    if templates_from_current and not (dest / "templates").exists():
        (dest / "templates").symlink_to(ENGINE / "skills/product-design/templates")
    return cli
