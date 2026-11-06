# Manifest 계약: `boilerplate.manifest.toml`

보일러플레이트 저장소 루트에 두는 파일입니다. 엔진은 특정 기술 스택을 모르고, 이 계약만 읽어 적용과 검증을 수행합니다.
형식은 TOML입니다(Python 표준 라이브러리 `tomllib`로 읽기 위해서입니다). 예시는 `templates/boilerplate.manifest.example.toml`에 있습니다.

## 스키마

| 키 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `schema_version` | 정수 | 예 | `1` |
| `name` | 문자열 | 예 | 보일러플레이트 이름 |
| `version` | 문자열(SemVer) | 예 | Git 태그와 같아야 합니다(`v1.0.0` 또는 `1.0.0`) |
| `apply.exclude` | 문자열 목록(glob) | 아니요 | 복사하지 않을 경로 |
| `substitutions[]` | 표 목록 | 아니요 | 이름 치환 규칙 |
| `substitutions[].from` | 문자열 | 예 | 바꿀 정확한 문자열 |
| `substitutions[].to` | `"{project_slug}"` \| `"{project_title}"` | 예 | 치환 값 |
| `substitutions[].files` | 상대 경로 목록 | 예 | 치환을 적용할 파일(이 파일들에서만 치환) |
| `merge[]` | 표 목록 | 아니요 | 충돌 시 사용자 승인으로 쓸 수 있는 병합 전략 |
| `merge[].path` | 상대 경로 | 예 | 대상 파일 |
| `merge[].strategy` | `"append-missing-lines"` \| `"append-section"` | 예 | 병합 방식 |
| `merge[].required` | 문자열 목록 | 아니요 | 기존 파일에 반드시 있어야 하는 줄(필수 설정 누락 점검) |
| `merge[].section_title` | 문자열 | append-section이면 예 | 추가할 섹션 제목 |
| `verify.env_file` | 문자열 | 아니요(기본 `.env.example`) | Compose `--env-file` |
| `verify.ignored_paths` | 경로 목록 | 아니요 | fe/be 검증 전에 Git에서 무시되는지 확인할 산출물 경로 |
| `verify.ports` | `{이름 = 정수}` | 아니요 | 검증 전용 포트(환경변수로 주입, 사용 중이면 검증 중단) |
| `verify.env` | `{이름 = 문자열}` | 아니요 | 검증 시 주입할 환경변수 |
| `verify.stages.{fe,be,db,smoke}` | `{run, cwd?, timeout?}` 목록 | 아니요 | 단계별 명령. 정의된 단계가 모두 통과해야 `verified` |
| `verify.http[]` | `{url, expect_status?, contains?}` | 아니요 | smoke 단계 HTTP 확인 |

자리표시자:
- `{compose}`: `docker compose -p <slug>-init-verify --env-file <env_file>`
- `{포트이름}`: `verify.ports`의 값

## 검증 규칙(스크립트가 plan 단계에서 강제)

1. `schema_version == 1`이고, `name`과 `version`이 있으며, `version`은 SemVer 형식입니다.
2. 태그(`v` 제외)와 `version`이 같아야 합니다.
3. 모든 경로는 상대 경로이며 `..`을 포함하지 않습니다.
4. `substitutions[].to`는 `{project_slug}` 또는 `{project_title}`만 허용합니다.
5. `merge[].strategy`는 두 가지 중 하나이고, `append-section`에는 `section_title`이 필요합니다.
6. `verify.ports`는 1024–65535 정수입니다.
7. Docker를 쓰는 명령은 반드시 `{compose} `로 시작합니다. 이렇게 해야 Compose 프로젝트명이 격리됩니다.
8. fe/be 단계에서는 `{compose}`를 쓸 수 없습니다(호스트 명령만).
9. 금지 패턴은 허용하지 않습니다: `down -v` / `--volumes`, `volume rm|prune`, `system prune`, `rm -r…`, `git push|commit|reset|checkout|clean`
10. `verify.http[].url`은 `http://localhost:`로 시작합니다.

## 항상 적용되는 엔진 규칙(manifest로 바꿀 수 없음)

- `.env`, `.env.*`는 복사하지 않습니다. `*.example`만 예외입니다.
- 이 manifest 파일 자체와 심볼릭 링크는 복사하지 않습니다.
- 보호 경로에는 쓰지 않습니다: `.git/`, `.ai-workflow/`, `docs/planning/`, `.claude/`, `skills/product-start/`
- 기존 파일은 덮어쓰지 않습니다(충돌로 보고합니다).
- 검증 정리는 `down --remove-orphans`만 사용합니다. 볼륨은 지우지 않습니다.
