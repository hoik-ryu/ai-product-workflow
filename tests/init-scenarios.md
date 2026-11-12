# 테스트 시나리오 — /product-init

## 실행 방법

- **스크립트 테스트(자체 완결형)**: `python3 tests/product_init_test.py`
  - 가짜 보일러플레이트와 제품 저장소를 임시 디렉터리에 만들어 검사합니다.
  - 가짜 보일러플레이트에는 보호 경로 파일, 커밋된 비밀 파일, 실패하는 검증 명령, 위험한 manifest 태그가 일부러 들어 있습니다.
- **Skill 테스트**: 임시 제품 저장소에 `.claude/skills/product-init` 링크를 만들고, `claude -p "/product-init <소스> <태그>" --add-dir <engine>/skills`로 대화를 이어 갑니다(`--resume`).
- **실제 원격 태그 통합**: `https://github.com/hoik-ryu/fullstack-boilerplate.git`의 `v1.0.0`으로 resolve → snapshot → plan → apply → merge → verify(fe/be/db/smoke) → cleanup을 실행합니다.
- **(이전) 로컬 복사본 통합**: fullstack-boilerplate의 추적 대상 파일만 임시 저장소로 복사합니다(`.env` 제외, 원본 수정 없음). 여기에 예시 manifest와 `v1.0.0` 태그를 붙여 적용과 검증을 실행합니다.

## 스크립트 테스트(`tests/product_init_test.py`)

| ID | 영역 | 시나리오 | 기대 결과 |
|---|---|---|---|
| I01 | 차단 | `/product-start` 상태 파일 없음 | `no_workflow_state` |
| I02 | 차단 | planning `awaiting_approval` | `planning_not_approved`, 상태 파일 미생성 |
| I03 | 차단 | 승인 후 03 수정·커밋(해시 불일치) | 차단, 원인 파일 명시 |
| I04 | 차단 | 커밋되지 않은 변경 | `dirty_worktree` |
| I05 | 차단 | 엔진 저장소 안 실행 | `engine_repo` |
| I06 | 계획 | 분류 | 보호 경로 4종 `protected`, `.env.production`·manifest `excluded`, README·.gitignore `conflict`, `.gitignore` 필수 줄 누락 보고 |
| I07 | 승인 | 승인 없이 apply / 다른 plan id 승인 / 적용 전 merge | 모두 거부, 파일 미생성 |
| I08 | 적용·재개 | 승인 → 브랜치 → 1개 기록 후 중단 → 재개 | 완료, 기록 SHA = 실제, 충돌 파일·보호 경로·비밀 파일·`/product-start` 상태 불변, 치환·실행 권한 반영 |
| I09 | 재개 안전 | 적용 파일 수정 / 삭제 / 계획 밖 변경 / 계획 후 생긴 동일·다른 파일 | `state_mismatch`(user_modified / missing / unexpected) 후 사용자 내용 보존. 동일 파일은 채택, 다른 파일은 runtime 충돌로 보존 |
| I10 | 버전 고정 | 태그를 다른 커밋으로 옮김 | 스냅샷 `sha_mismatch`, `status --check-remote` → `tag_moved` |
| I11 | 병합 | 승인 증거 없는 merge / .gitignore / README / 중복 | 거부 / 누락 줄만 추가(Git clean이면 백업 없음) / 기존 내용 유지하고 섹션 추가 / 거부 |
| I12 | 검증 | fe 실패, be 통과, db dry-run, 정리, db 실행 | `verify_failed` + 실패 명령·로그 tail 기록 / `pass` / `-p <slug>-init-verify`, 정리에 `-v` 없음 / db 실행 전(기록 없음)에는 볼륨 삭제 불허 / Docker 미가동이면 `docker_unavailable`, 가동 중이면 db `fail` 기록 후에만 볼륨 삭제 허용 표시 |
| I13 | manifest | `down -v`·`volume rm` 포함 / 브랜치 ref / 태그·version 불일치 | `manifest_invalid` / `tag_not_found` / `version_mismatch` |

## Skill 테스트(`claude -p`, 대화 이어 가기)

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| K1 | 미승인 제품에서 `/product-init <src> v1.0.0` | 차단 사유와 해결 방법 안내, 상태 파일 미생성 |
| K2 | 승인 제품에서 실행 | 사전 점검·출처(SHA) 확인. 제목을 추측하지 않고 질문 |
| K3 | slug/title 제공 | 계획(추가 59 / 충돌 2 / 제외 1), 충돌별 전략·필수 줄 누락 제시, "적용 승인" 요청. 파일 미추가 |
| K4 | "좋아요" | 승인으로 보지 않음, 상태 불변 |
| K5 | "적용 승인 + 브랜치" | 브랜치 생성, 59개 추가, README 불변, 파일별 병합 질문 |
| K6 | ".gitignore만 병합 승인" | .gitignore만 병합(백업 없음), README 불변 |
| K7 | "fe, be 검증 진행" | fe·be 실제 통과, db·smoke는 "미실행(통과 아님)"으로 표시 |
| K8 | 새 세션 `/product-init` | 상태·검증 현황 보고 |
| K9 | 적용 파일 수정 후 재실행 | `state_mismatch` 보고, 사용자 수정 보존 |
| K10 | init 적용 후 `/product-start` | 교차 검증 통과(Milestone 1 완료 보고), 기획 상태·문서 불변 |

## 실행 기록

### 2026-11-06

환경은 Claude Code 2.1.312, macOS, Python 3.11.9입니다. Skill 테스트는 `--model sonnet` headless로 실행했습니다. **Docker 데몬이 꺼진 상태**에서 테스트했습니다.

| 구분 | 결과 |
|---|---|
| 스크립트 테스트 I01–I13 | **48/48 Pass** (엔진 저장소의 `tests/product_init_test.py`로 재현) |
| Skill 테스트 K1–K10 | **10/10 Pass** |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**. 새 테스트 영역에서 [scenarios.md](scenarios.md)와 같은 절차로 실행했습니다. 해시 불일치는 의도한 S09·S11·S17에서만 발생했고, 한국어 헤딩 검사도 통과했습니다. `/product-start` 파일은 변경하지 않았습니다(11-05 이후 수정 없음) |
| 실제 보일러플레이트 통합 | 계획: 추가 59 / 충돌 2(.gitignore, README.md) / 제외 1(manifest). 적용 59개, 치환 누락 0. 병합 전 fe 검증은 `gitignore_missing`으로 차단 → .gitignore 병합 후 **fe pass**(pnpm install / lint / typecheck / test / build), **be pass**(uv sync / ruff check / ruff format --check / mypy / pytest). **db·smoke는 `docker_unavailable`로 기록**(Docker 미가동, 실행 검증 안 됨) |

테스트 중 발견해 수정한 결함은 다음과 같습니다.
- `git check-ignore`는 아직 없는 디렉터리에 디렉터리 규칙(`node_modules/`)을 적용하지 않았습니다. 그래서 무시 대상인데도 "무시 안 됨"으로 오판했습니다. 경로 아래 가상 파일로 확인하도록 고쳤습니다.
- 병합 백업 파일명이 `.gitignore`가 되어 실제 ignore 규칙으로 동작할 수 있었습니다. `product-init__<path>.bak`으로 바꿨습니다.
- K3에서 브랜치명을 구체적으로 제안하지 못했습니다. SKILL.md에 `source.manifest_name`을 쓰도록 안내를 보완했습니다.

테스트 픽스처 문제로 처음에 실패한 2건(테스트 코드만 수정)도 있습니다.
- 가짜 보일러플레이트의 `.gitignore` 때문에 비밀 파일이 커밋되지 않아, 제외 로직이 검사되지 않았습니다.
- `-v` 검사가 `-init-verify` 문자열에 오탐했습니다.

### 2026-11-06 (2차: v1.0.0 릴리스 후 최종 점검)

환경은 1차와 같고, **Docker 28.0.4가 가동 중**인 상태에서 실행했습니다. 대상은 GitHub `hoik-ryu/fullstack-boilerplate`의 태그 `v1.0.0`(커밋 `43ca48c74f7fff27ca09d8737f0a2bb52567f87a`)입니다.

| 구분 | 결과 |
|---|---|
| 스크립트 테스트 | **49/49 Pass**. Docker가 켜져 있으면 I12e가 실패하던 테스트 순서 문제를 고쳤습니다(아래). Docker가 켜져 있을 때만 I12d(db 실패 기록)·I12f를 검사하고, 꺼져 있으면 I12d(`docker_unavailable`)를 검사합니다 |
| 원격 태그 조회 | HTTPS·SSH URL 모두 `v1.0.0` → `43ca48c…` 확인. 브랜치명 `main`은 `tag_not_found`로 거부 |
| 실제 원격 통합 | 계획: 추가 59 / 충돌 2(.gitignore, README.md) / 제외 1(manifest). 적용 59개, 치환 누락 0. 병합 전 `gitignore_missing` 차단 → 병합 후 **fe·be·db·smoke 모두 pass**, 상태 `verified`. smoke HTTP: `/health` 200(`database":"ok"`), frontend 200 |
| Docker 안전 | 검증 후 컨테이너가 남지 않았고, 볼륨만 유지되었습니다. `--confirm` 없는 삭제는 `confirm_required`로 거부되었습니다. `--confirm` 삭제는 라벨이 일치하는 검증 볼륨 1개만 지웠고, 다른 볼륨 44개와 기존 컨테이너는 그대로였습니다 |
| Skill 테스트 K1–K10(실제 원격 태그) | **10/10 Pass**. K7은 dry-run 제시 → 확인 → 실행 순서로 진행했고, 4단계가 모두 통과했습니다(1차에서 미실행이던 db·smoke 포함). K9는 `frontend/src/main.tsx` 수정을 감지하고 보존했습니다. K10 이후 README·`docs/`·`state.yaml`은 변경되지 않았습니다 |
| `/product-start` 회귀 S01–S19 | **19/19 Pass**. 해시 불일치는 의도한 S09·S11·S17에서만 발생했습니다 |

수정 내역:
- 테스트: I12e(기록 없는 프로젝트의 볼륨 삭제 불허)를 db 실행 **전**에 검사하도록 순서를 바꿨습니다. 1차는 Docker가 꺼져 있어 우연히 통과했습니다.
- 예시 manifest: 릴리스된 v1.0.0 manifest와 내용이 같도록 `.gitignore` 필수 줄과 `ignored_paths`에 `.pytest_cache`, `.ruff_cache`, `.mypy_cache`를 추가했습니다(주석 제외 TOML 동일성 확인).

### 3차 실행(2026-11-12, M2 최종 검증)

환경: Docker **미가동**. 격리 Compose 프로젝트(`<slug>-init-verify`)와 검증 포트 55432·58000·55173이 비어 있음을 확인한 뒤 실행했습니다. 기존 dev DB와 컨테이너는 건드리지 않았습니다. 로그: `~/Desktop/ai-product-workflow-test-logs/k1/`.

| 구분 | 결과 |
|---|---|
| Skill 테스트 K1–K10 | 최초 판정 7/10 → 판정기 수정 후 같은 로그 재판정 **9/10**. K7만 미통과(db `docker_unavailable`, Docker 필요) |
| 엔진 결함 | 모델이 fe·be 검증을 **동시에** 실행해 be 저장이 fe 기록을 덮어씀(fe 실제 로그 5단계 exit 0, 기록에는 be·db만). → 상태 변경 명령에 프로젝트 단위 잠금 추가 |
| 스크립트 테스트 | **51/51 Pass**(I12g–I12i 추가). 잠금을 뺀 변이 실행에서 I12g·I12i가 실패해 테스트가 결함을 잡는 것을 확인 |

수정 내역:
- 엔진: `product_init.py`의 상태 변경 명령(plan·approve·branch·apply·merge·verify·cleanup, dry-run 제외)이 `.ai-workflow` 디렉터리에 배타 잠금을 겁니다. 다른 명령이 실행 중이면 `state_busy`로 거부합니다. 새 파일은 만들지 않습니다.
- Skill: 7단계 검증을 한 번에 하나씩 실행하고, 결과는 `status`의 기록을 기준으로 보고하도록 명시했습니다.
- 판정기(`tests/harness/product_init/summarize.py`): 블록 경계를 `### k<번호>` 줄로 제한했습니다(모델 응답 속 `### ` 제목 때문에 K3 오판정). K8은 "k7b 직후와 상태 동일"로 판정합니다(K7 결과가 K8로 번지지 않도록).
- 테스트 픽스처: be 단계에 `sleep 1`을 넣어 동시 실행 경합을 재현 가능하게 했습니다.
- 남은 일: Docker 가동 후 K7·K8 재실행.
