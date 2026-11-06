---
name: product-init
description: 승인된 기획 문서를 가진 제품 저장소에 공통 보일러플레이트를 태그·커밋 SHA로 고정해 추가 전용으로 적용하고, FE/BE/DB/Smoke 검증까지 수행합니다. 사용자가 /product-init을 실행하거나 진행 중인 보일러플레이트 적용을 재개할 때 사용합니다.
argument-hint: "<보일러플레이트 Git URL 또는 경로> <태그>  (생략하면 재개)"
disable-model-invocation: true
---

# /product-init — 승인된 기획 → 보일러플레이트 적용 → 검증

사용자의 **제품 저장소**(현재 작업 디렉터리)에 보일러플레이트를 안전하게 적용합니다.

보조 파일은 이 Skill의 기본 디렉터리에 있습니다. 아래에서는 그 경로를 `$SKILL`로 표기합니다.

- `reference/apply-policy.md`: 전제 조건, 파일 분류, 승인, 재개, 병합, 금지 사항
- `reference/verify.md`: 검증 단계, Docker 안전 규칙, 기록
- `reference/manifest-schema.md`: 보일러플레이트 manifest 계약
- `scripts/product_init.py`: 모든 판정과 파일 작업을 수행하는 결정적 스크립트(JSON 출력, 차단 시 종료 코드 2)

호출 형식: `python3 $SKILL/scripts/product_init.py <명령> --project "$PWD" ...`

이번 실행의 사용자 입력: `$ARGUMENTS`

## 반드시 지킬 규칙

1. **판정과 파일 작업은 스크립트로만 합니다.** 다음 일은 직접 하지 않습니다.
   - 파일 복사, 해시 계산, 승인 기록
   - `.ai-workflow/boilerplate.json` 편집
   - 스크립트의 차단(`"ok": false`)을 우회하는 일
2. **`/product-start`의 상태와 기획 문서는 읽기만 합니다.** `.ai-workflow/state.yaml`과 `docs/planning/`을 수정하지 않습니다.
3. **planning이 승인되지 않았거나 승인 해시가 일치하지 않으면 실행하지 않습니다.** 해결 방법(`/product-start` 재개)만 안내합니다.
4. **명시적 승인만 인정합니다.** "적용 승인", "승인", "approve"만 인정합니다. 애매한 응답은 다시 묻습니다. 적용, 브랜치 생성, 파일별 병합, 검증 실행, 볼륨 삭제는 **각각** 확인을 받습니다.
5. **기존 파일을 덮어쓰지 않습니다.** 충돌은 보고하고, 사용자가 파일별로 승인한 병합만 `merge`로 수행합니다.
6. **상태와 파일이 불일치하면 보고하고 멈춥니다.** 사용자가 바꾼 파일을 되돌리거나 덮어쓰지 않습니다.
7. Git 변경은 승인된 **브랜치 생성만** 합니다. commit, push, reset, checkout, clean, stash는 실행하지 않습니다.
8. Docker 정리에서 `-v`를 쓰지 않습니다. 볼륨 삭제는 `verify.md`의 조건을 모두 만족하고 사용자가 확인한 경우에만 합니다.
9. 비밀값을 요청하거나 출력하지 않습니다. `.env` 파일은 읽지도 만들지도 않습니다.
10. 사용자와의 대화는 한국어로 합니다.

## 0단계 — 사전 점검(매 실행)

1. `check`를 실행합니다.
   - 차단 사유가 `engine_repo`, `not_git_repo`, `no_commits`, `dirty_worktree`, `planning_not_approved`이면 사유와 해결 방법을 보고하고 멈춥니다.
   - `state_mismatch`도 같습니다. 이 경우 `cross_verify`의 `user_modified`, `missing`, `unexpected_changes`를 그대로 보고합니다.
2. 상태 파일(`.ai-workflow/boilerplate.json`)의 `status`에 따라 분기합니다.

| 상태 | 이동 |
|---|---|
| 없음, `$ARGUMENTS`에 소스와 태그 있음 | 1단계 |
| 없음, 인자 없음 | 보일러플레이트 Git URL(또는 경로)과 태그를 요청하고 멈춤 |
| `planned`, 승인 없음 | 3단계(계획을 다시 제시) |
| `planned`, 승인 있음 / `applying` | 5단계(재개) |
| `applied` | 6단계(충돌 처리) → 7단계 |
| `verify_failed` | 7단계(실패 단계 재시도 여부 확인) |
| `verified` | 8단계(완료 보고) |

상태 파일이 있는데 `$ARGUMENTS`로 다른 소스나 태그가 들어오면, 현재 상태를 보여 주고 멈춥니다. 상태 파일을 초기화하지 않습니다.

## 1단계 — 출처 확인

1. `resolve --source <URL> --ref <태그>`로 커밋 SHA를 확인합니다. 브랜치명은 거부됩니다.
2. 사용자에게 저장소, 태그, 커밋 SHA를 보여 줍니다.
3. 프로젝트 이름(slug: 기본은 디렉터리 이름)과 표시 제목(title)을 정합니다. 제목은 PRD의 제품명을 제안합니다.

## 2단계 — 스냅샷과 계획

1. 프로젝트 밖에 임시 디렉터리를 만듭니다. 예: `mktemp -d -t product-init`
2. `snapshot --source --ref --sha --dest <임시>/src --project "$PWD"`를 실행합니다.
3. `plan --project "$PWD" --snapshot <임시>/src --source --ref --sha --slug <slug> --title <title>`을 실행합니다.
   - manifest 오류, 버전 불일치, 기획 미승인이면 보고하고 멈춥니다.
4. PRD의 제약과 NFR(플랫폼, 기술 제약)을 읽고, 보일러플레이트 스택과 맞지 않는 점이 있으면 경고합니다.

## 3단계 — 적용 계획 제시와 승인

다음을 제시합니다.

- 출처(저장소, 태그, SHA)와 plan id
- 추가 / 동일 / 충돌 / 제외 / 보호 경로의 개수와 주요 경로
- **충돌 파일 목록.** 각 파일에 대해 다음을 함께 보여 줍니다.
  - 병합 전략이 있는지
  - `missing_required`(필수 설정 누락. 예: `.gitignore`에 `.env`, `node_modules/`가 없음)
  - "덮어쓰지 않는다"는 사실
- 치환할 값(slug, title)
- 전용 브랜치 생성 제안: `init/<source.manifest_name>-<태그>`. manifest 이름은 plan 이후 상태 파일의 `source.manifest_name`에 있으므로, 구체적인 이름으로 제안합니다. 예: `init/fullstack-boilerplate-v1.0.0`

그리고 **"적용 승인"**을 요청하고 멈춥니다. 브랜치 생성 여부도 함께 묻습니다.

- 승인 → `approve --plan-id <id>`
- 브랜치 생성도 승인 → `branch --name <브랜치>`
- 4단계로 이동합니다.
- 애매한 응답이나 수정 요청 → 아무것도 실행하지 않습니다. slug나 title을 바꾸면 2단계 3번(plan)을 다시 실행해 새 plan id로 다시 제시합니다.

## 4·5단계 — 적용과 재개

1. 스냅샷 디렉터리(`snapshot_dir`)가 없으면, 기록된 태그와 SHA로 `snapshot`을 다시 받습니다. SHA가 다르면 `sha_mismatch`를 보고하고 멈춥니다.
2. `apply --project "$PWD" --snapshot <dir>`를 실행합니다.
   - `state_mismatch`: 사용자 변경 파일 목록을 보고하고 멈춥니다. 덮어쓰거나 복구하지 않습니다.
   - `runtime_conflicts`: 계획 이후 새로 생긴 충돌 파일입니다. 보고합니다.
   - `substitution_leftovers`: 치환이 누락된 곳입니다. 보고합니다.
3. 완료되면 6단계로 이동합니다.

## 6단계 — 충돌 처리

- 계획된 충돌 파일마다 차이를 요약해 보여 줍니다. 예: `.gitignore`에 빠진 필수 줄
- 병합 전략이 있는 파일에 대해서는 "이 파일을 <전략>으로 병합할까요?"라고 **파일별로** 묻습니다.
- 승인한 파일만 `merge --path <file> --confirm-plan-id <plan id>`로 병합하고, 추가된 내용과 백업 여부를 보고합니다.
- 전략이 없거나 사용자가 거부한 파일은 그대로 두고, 직접 처리할 방법을 안내합니다.
- `.gitignore`의 필수 줄이 빠져 있으면 fe/be 검증이 차단된다는 점을 알립니다.

## 7단계 — 검증

1. 단계(fe, be, db, smoke)별로 `verify --stage <s> --dry-run`을 실행해 실행할 명령을 보여 줍니다.
   - Docker 단계는 Compose 프로젝트명(`<slug>-init-verify`), 검증 포트, 정리 방식(`down --remove-orphans`, 볼륨 유지)도 함께 보여 줍니다.
   - 실행 확인을 받습니다.
2. 확인된 단계만 `verify --stage <s>`로 실행합니다.
   - 실패하면 `verification.<s>`의 실패 명령과 출력 마지막 줄을 요약합니다.
   - Docker가 꺼져 있으면(`docker_unavailable`) 이를 보고합니다.
   - 사용자가 요청하지 않으면 코드를 고치지 않습니다.
3. 검증 볼륨을 정리하고 싶다는 요청이 있을 때만 다음 순서로 진행합니다.
   - `cleanup --dry-run`으로 삭제 대상을 보여 줍니다.
   - 확인을 받습니다.
   - `cleanup --remove-volumes --confirm`을 실행합니다.

## 8단계 — 완료 보고

다음을 보고합니다.

- 출처(태그, SHA)와 브랜치
- 추가한 파일 수
- 충돌과 병합 결과
- 단계별 검증 결과
- 남은 수동 작업(로컬 실행용 `make env` 등)

커밋은 사용자가 합니다. 예: `git add -A && git commit -m "chore: apply <name> <tag> via /product-init"`
