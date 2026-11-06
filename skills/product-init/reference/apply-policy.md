# 적용 정책

`/product-init`은 보일러플레이트를 **추가 전용**으로 적용합니다. 모든 파일 작업은 `scripts/product_init.py`가 수행합니다. Skill은 `.ai-workflow/boilerplate.json`을 직접 편집하지 않습니다.

## 실행 전제 조건(`check`, `plan`이 강제)

- 엔진 저장소가 아니어야 합니다(`skills/product-start/SKILL.md`가 없어야 함).
- Git 저장소 루트이고 커밋이 1개 이상 있어야 합니다.
- **커밋되지 않은 변경이 없어야 합니다.** `.claude/` 아래의 도구 설정은 예외입니다.
- `/product-start` 상태(읽기 전용 확인):
  - discovery와 planning이 모두 `approved`
  - 01–05의 현재 SHA-256이 승인 해시와 일치
  - planning이 최신 승인 discovery revision을 기준으로 함

  하나라도 어긋나면 **차단**합니다. design 승인은 요구하지 않습니다.

## 출처와 버전 고정

- 태그만 허용합니다. 브랜치명은 거부합니다.
- `resolve`로 커밋 SHA를 확인합니다(annotated 태그는 peeled 커밋 기준).
- 스냅샷은 **프로젝트 밖** 임시 디렉터리에 얕은 클론으로 받고, SHA를 대조합니다.
- 다시 받을 때 태그가 다른 SHA를 가리키면 `sha_mismatch`로 중단합니다(태그가 옮겨졌거나 공급망 변경 가능성).
- 인증은 사용자의 기존 Git 인증(SSH 등)만 사용합니다. 토큰을 요청하거나 저장하지 않습니다.

## 파일 분류(plan)

| 분류 | 조건 | 처리 |
|---|---|---|
| `add` | 제품 저장소에 없음 | 승인 후 복사 |
| `identical` | 치환 후 내용이 같음 | 건너뜀 |
| `conflict` | 내용이 다르거나 종류가 다름(파일↔디렉터리) | **덮어쓰지 않음.** 보고하고, manifest 병합 전략이 있으면 `missing_required`(필수 설정 누락)를 함께 보고 |
| `excluded` | manifest 자체, 심볼릭 링크, `.env`/`.env.*`(example 제외), `apply.exclude` | 복사하지 않음 |
| `protected` | `.git/`, `.ai-workflow/`, `docs/planning/`, `.claude/`, `skills/product-start/` | 절대 쓰지 않음 |

`plan`은 이 결과로 plan id를 만듭니다. 커밋, slug, title, add 목록, 충돌 목록이 바뀌면 plan id도 바뀝니다.

## 승인

- 계획을 제시한 뒤 **명시적 승인**("적용 승인", "승인", "approve")만 인정합니다. 기준은 `/product-start`와 같습니다.
- 승인을 받으면 `approve --plan-id <id>`로 기록합니다. `apply`는 승인된 plan id가 현재 plan id와 같을 때만 실행됩니다.
- 전용 브랜치(`init/<name>-v<version>`)는 사용자가 승인한 경우에만 `branch`로 만듭니다. 이 Skill이 하는 Git 변경은 브랜치 생성뿐입니다.

## 적용과 재개(apply)

- add 파일을 하나씩 원자적으로 씁니다(임시 파일 → rename). 쓰자마자 `files_done`에 SHA-256을 기록합니다.
- 실행할 때마다(재개 포함) 먼저 교차 검증합니다:
  - `files_done`과 `merges`의 기록 해시 = 실제 파일 해시인가
  - 기록된 파일이 모두 존재하는가
  - Git의 미커밋 변경이 계획된 경로와 상태 파일 안에만 있는가
- **불일치가 있으면 `state_mismatch`로 중단합니다.** 사용자가 바꾼 파일을 덮어쓰거나 복구하지 않습니다.
- 계획 이후 생긴 파일을 만나면:
  - 내용이 같으면 `adopted_identical`로 기록합니다(중단 직후 재개하는 경우).
  - 내용이 다르면 `runtime_conflicts`로 보고하고 건너뜁니다.
- 끝나면 치환 대상 파일에 원래 문자열이 남아 있는지 확인합니다.

## 충돌 병합(merge)

- manifest에 전략이 있는 충돌 파일만, **파일별로 사용자의 명시적 승인**을 받은 뒤 실행합니다.
- 승인 증거로 `--confirm-plan-id`를 함께 넘깁니다.
- `append-missing-lines`: 보일러플레이트의 줄 중 기존 파일에 없는 줄만, 출처 주석과 함께 끝에 추가합니다.
- `append-section`: 출처 주석과 `## <section_title>` 아래에 보일러플레이트 내용을 끝에 추가합니다.
- 계획 이후 파일이 바뀌었으면 거부합니다.
- 백업 판단은 `/product-start`와 같은 규칙을 따릅니다. Git이 추적하고 변경이 없는 파일이면 백업하지 않습니다. 그 외에는 `.ai-workflow/backup/product-init__<path>.bak`을 만듭니다.

## 금지

- 기존 파일 덮어쓰기와 삭제
- `git commit`, `push`, `reset`, `checkout`, `clean`, `stash`. 커밋은 사용자가 합니다.
- 보일러플레이트 소스를 엔진 저장소로 복사하기
- `/product-start`의 `state.yaml`과 `docs/planning/` 수정
