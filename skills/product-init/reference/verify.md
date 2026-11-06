# 검증 절차

검증 명령은 보일러플레이트 manifest(`verify.stages`)가 정의합니다. 엔진은 실행, 격리, 기록, 정리만 담당합니다.

## 단계

| 단계 | 내용(fullstack-boilerplate 기준) | Docker |
|---|---|---|
| `fe` | pnpm install → lint → typecheck → test → build | 아니요 |
| `be` | uv sync → ruff check/format → mypy → pytest | 아니요 |
| `db` | db 기동 → `alembic upgrade head` → `alembic check` → `downgrade base` → `upgrade head` → `pytest -m db` | 예 |
| `smoke` | 전체 `up --build --wait` → HTTP 확인(backend `/health`의 database ok, frontend 200) | 예 |

manifest에 정의된 단계가 모두 `pass`이면 상태가 `verified`가 됩니다. 하나라도 `fail`/`error`이면 `verify_failed`입니다.

## 실행 전 확인

- 사용자에게 실행할 명령을 보여 주고 확인을 받습니다. `verify --stage <s> --dry-run`으로 확장된 명령을 확인할 수 있습니다.
- 알려야 할 영향:
  - fe/be: 의존성 다운로드(네트워크), `node_modules`, `.venv`, `dist`, 도구 캐시(예: `.pytest_cache`, `.ruff_cache`, `.mypy_cache`) 생성
  - db/smoke: Docker 이미지 빌드, 검증 전용 컨테이너, 네트워크, 볼륨 생성
- fe/be: `verify.ignored_paths`가 Git에서 무시되지 않으면 시작하지 않습니다(`gitignore_missing`). 먼저 `.gitignore` 병합을 제안합니다.

## Docker 안전 규칙

- 모든 Docker 명령은 `docker compose -p <slug>-init-verify --env-file <env_file>`로 실행합니다. 프로젝트명이 분리되므로 다른 프로젝트의 컨테이너와 볼륨에 영향을 주지 않습니다.
- `.env`를 만들지 않습니다. `--env-file .env.example`과 환경변수(`verify.ports`, `verify.env`)로 주입합니다.
- 검증 전용 포트가 이미 사용 중이면 실행하지 않습니다(`ports_in_use`).
- Docker 데몬에 연결할 수 없으면 `error: docker_unavailable`로 기록합니다.
- 단계가 끝나면(성공이든 실패든) **`down --remove-orphans`만** 실행합니다. 기본 정리에서 **`-v`를 쓰지 않습니다.**
- 볼륨 삭제는 `cleanup --remove-volumes --confirm`으로만 합니다. 다음 조건을 모두 만족해야 합니다.
  - 프로젝트명이 `-init-verify`로 끝나야 합니다.
  - 상태 파일에 이 Skill이 그 프로젝트를 만들었다는 기록(`verification.compose_project`)이 있어야 합니다.
  - 볼륨의 `com.docker.compose.project` 라벨이 그 프로젝트와 일치해야 합니다.
  - 사용자가 명시적으로 확인해야 합니다.

  삭제 전에 `cleanup --dry-run`으로 대상 목록을 보여 줍니다.

## 기록

- 단계별 결과는 `verification.<stage>`에 기록합니다: `result`, 명령별 exit 코드와 소요 시간, 실패 명령, 출력 마지막 30줄
- 전체 로그는 **프로젝트 밖** 임시 디렉터리에 저장합니다.
- 실패하면 원인 요약, 재시도 방법, 로그 경로를 보고합니다. 사용자의 요청 없이 코드를 고치지 않습니다.
