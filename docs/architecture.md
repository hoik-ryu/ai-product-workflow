# 아키텍처

## 범위

아이디어 → Discovery → 승인 → Planning → 승인까지는 `/product-start`가 다룹니다.
보일러플레이트 적용은 `/product-init`, 화면 기획·설계·UI 프리뷰는 `/product-design`이 담당합니다(아래 섹션). 웹 UI, 서버, DB, 별도 Orchestrator는 포함하지 않습니다.

## 구성

```
[공통 엔진: ai-product-workflow]            [제품 프로젝트]
 skills/product-start/                       .ai-workflow/state.yaml          상태(기준)
   SKILL.md          절차·게이트·규칙  ──실행──▶ .ai-workflow/discovery-notes.md 인터뷰 원문 기록
   reference/        상태·안전·ID·인터뷰         .ai-workflow/backup/<file>       필요 시 단일 슬롯 백업
   templates/        state + 문서 01–05          docs/planning/01–05             산출물
```

- 실행 주체는 Claude Code와 Skill 하나뿐입니다. 별도 코드나 런타임은 없습니다.
- 진입점은 `/product-start` 하나입니다. 신규 시작, 재개, 승인 처리를 모두 `state.yaml`을 기준으로 분기합니다.
- 엔진에는 규칙과 템플릿만 둡니다. 산출물과 상태는 제품 프로젝트에만 기록합니다. 엔진 저장소 안에서 실행하면 Skill이 거부합니다.

## 단계와 게이트

| Stage | 상태 | 게이트 |
|---|---|---|
| discovery | in_progress → awaiting_approval → approved | 명시적 승인 필요 |
| planning | locked → not_started → in_progress → awaiting_approval → approved (+ outdated) | discovery 승인 전에는 `locked`, 명시적 승인 필요 |
| design | locked → not_started | planning 승인 시에만 unlock(Milestone 2 진입점) |

전이표, 승인 판정 기준, 재개 시 교차 검증 규칙은 [state-machine.md](../skills/product-start/reference/state-machine.md)에 정의되어 있습니다.

## 핵심 정책

- **승인**: 명시적 표현만 인정합니다. 애매한 응답은 다시 묻고, 승인과 수정이 섞인 응답은 수정 요청으로 처리합니다. 승인할 때 대상 파일의 sha256을 기록합니다.
- **재개**: 매 실행마다 state와 실제 파일(존재 여부, front matter revision, 승인 해시)을 교차 검증합니다. 불일치가 있으면 보고만 하고 멈춥니다.
- **승인 후 변경**: 해시 불일치를 감지하면 영향 범위를 설명합니다. 사용자는 재검토(Discovery는 T7, Planning은 T9)하거나 직접 복원할 수 있습니다. Discovery가 다시 열리면 Planning은 `outdated`가 되고 design은 `locked`가 됩니다.
- **사실과 추론 분리**: 문장마다 태그를 달지 않습니다. 사용자가 확인하지 않은 내용은 `ASM-`(가정)이나 `Q-`(미결) 섹션에 ID로 관리하고, 본문에서는 ID로 참조합니다.
- **추적성**: `GOAL/PRB → FR → US → FLOW → AC`. Planning 제출 전에 누락 점검 결과를 05 문서에 기록합니다. ID는 재사용하거나 재번호화하지 않습니다.
- **파일 안전**: 기존 산출물을 수정할 때는 먼저 설명하고 확인을 받은 뒤 씁니다. Git으로 추적되고 미커밋 변경이 없는 파일은 백업하지 않습니다. 그 외에는 `.ai-workflow/backup/<file>` 단일 슬롯에 백업하며, 같은 파일의 이전 백업은 덮어씁니다. Skill은 Git 이력을 바꾸는 명령을 실행하지 않습니다.
- **언어**: 문서, 템플릿, Skill 지시문은 한국어로 작성합니다. 산출물은 기본 한국어(`project.language: ko`)이며, 사용자가 다른 언어를 명시하면 그 언어로 작성합니다. 파일명, Skill 이름, YAML 키·상태값, front matter 키, 요구사항 ID, 우선순위 값(Must/Should/Could)은 영어로 유지합니다.

## `/product-init`: 보일러플레이트 적용

`/product-start`와 분리된 독립 Skill입니다. `/product-start`의 상태 머신과 승인 규칙은 바꾸지 않습니다.

```
[ai-product-workflow]                       [보일러플레이트 저장소: 별도]
 skills/product-init/                        boilerplate.manifest.toml   적용 계약(복사·치환·병합·검증)
   SKILL.md           절차·승인                   │ 태그 vX.Y.Z → 커밋 SHA
   reference/         적용 정책·검증·manifest 스키마  ▼ 프로젝트 밖 임시 디렉터리로 얕은 클론
   scripts/product_init.py  분류·복사·해시·검증 ──▶ [제품 저장소]
                                                  .ai-workflow/state.yaml        /product-start 소유 · 읽기 전용
                                                  .ai-workflow/boilerplate.json  /product-init 소유
                                                  docs/planning/                 보호 · 읽기 전용
                                                  frontend/ backend/ ...         추가 전용
```

- **역할 분리**
  - 보일러플레이트는 manifest로 자신을 기술합니다.
  - 엔진은 안전하게 적용하는 방법만 압니다. 특정 기술 스택을 모르며, 보일러플레이트 소스를 포함하지 않습니다.
- **상태 소유권**
  - 각 Skill은 자기 상태 파일만 씁니다. `/product-init`은 `state.yaml`과 `docs/planning/`을 읽기만 합니다.
  - 그래서 `/product-start`의 교차 검증은 init 적용 후에도 그대로 통과합니다.
- **게이트**
  - discovery와 planning이 `approved`이고, 01–05가 승인 해시와 일치하며, planning이 최신 discovery를 기준으로 해야 합니다. 하나라도 어긋나면 차단합니다.
  - design 승인은 요구하지 않습니다. design과 병행할 수 있습니다.
- **결정적 처리**
  - 파일 분류, 복사, SHA-256 기록, 승인 plan id 확인, Docker 명령 구성은 표준 라이브러리 스크립트가 수행합니다.
  - LLM은 설명, 승인 수집, 스크립트 호출만 맡습니다.
- **상태 흐름**: `planned → (승인) → applying → applied → verified | verify_failed`
  - 재개할 때마다 `files_done`/`merges`의 SHA-256, 파일 존재 여부, 계획 밖 변경을 교차 검증합니다.
- **Docker 격리**
  - 모든 Docker 명령은 `docker compose -p <slug>-init-verify --env-file .env.example` 형태로 실행하고, 검증 전용 포트를 씁니다.
  - 정리는 `down --remove-orphans`만 합니다.
  - 볼륨 삭제는 다음 세 조건을 모두 만족할 때만 합니다: 상태 파일에 그 프로젝트명이 기록되어 있고, 볼륨 라벨이 일치하며, 사용자가 명시적으로 확인한 경우.

## `/product-design`: 화면 기획 → UX 설계 → UI 프리뷰

`/product-start`·`/product-init`과 분리된 독립 Skill입니다. 두 Skill의 파일과 동작은 바꾸지 않습니다.

```
[ai-product-workflow]                          [제품 저장소]
 skills/product-design/                         .ai-workflow/state.yaml        읽기만(planning 승인·해시, design locked 여부)
   SKILL.md          단계·승인·피드백 규칙        docs/planning/                 읽기만
   reference/        상태·인터뷰·설계·체크리스트·프리뷰   .ai-workflow/design.json       /product-design 소유(스크립트만 씀)
   templates/        00–06 문서, preview/ 앱       .ai-workflow/design-notes.md   인터뷰 원문
   scripts/product_design.py  게이트·전이·해시·추적성·프리뷰 경계 ─▶ docs/design/00–06    UX 결정·IA·화면·흐름·UI 시스템·추적성·프리뷰 검토
                                                design-preview/                정적 프리뷰(Vite+React, mock 데이터, 제품 코드 아님)
```

| 내부 단계 | 산출물 | 승인 |
|---|---|---|
| UX Planning | 00 UX 결정(UXD/DQ/PF) + 인터뷰 원문 | UX 결정 확정 |
| UX Specification | 01 IA, 02 화면 명세(상태 6종), 03 화면 흐름, 04 컴포넌트·토큰, 05 추적성 | 구조 확인(체크포인트) → UX 설계 승인 |
| UI Preview | `design-preview/`(트리 해시) + 06 피드백 기록 | 시각 디자인 승인 |

- **게이트**: planning `approved` + 01–05 해시 일치 + `state.yaml` design이 `locked`가 아님. 시작 시 기준(`based_on`: planning revision, 해시, 커밋)을 기록합니다.
- **결정적 처리**: 상태 전이, 승인 revision·해시, 제출 후 변경 감지, ID 존재·커버리지(Must US, FLOW 단계, AC↔화면/비UI), 화면 상태 6종, 프리뷰 경계(fetch·frontend import 금지)와 빌드는 스크립트가 판정합니다. UX 적절성은 체크리스트와 사용자 승인으로 판단합니다.
- **무효화**: UX Planning 재검토 → UX 설계·프리뷰 승인 무효. UX 설계 재검토 → 프리뷰 승인 무효. planning 변경 → T9 동안 차단, 재승인 후 `outdated` → `impact`(바뀐 ID와 참조 화면) → `rebase`.
- **표시 정책**: `state.yaml`의 `design: not_started`는 "디자인 단계가 열림" 표시입니다. 디자인 진행 상태의 기준은 `design.json`이며, `/product-design`은 상태를 보고할 때 이 관계를 함께 알립니다.
- **프리뷰와 제품 코드의 경계**: 프리뷰는 `design-preview/`에만 있고 실제 API·인증·비즈니스 로직이 없습니다. `frontend/`와 서로 import하지 않습니다. 실제 구현은 `/product-build`가 담당하며, 시각 디자인 승인 전에는 UI 구현 완료로 판단하지 않습니다.
- **Figma**: 선택적 외부 참조(06 문서의 링크)만 지원합니다. 자동 생성은 하지 않습니다.

### 이후 Skill과의 연결

```
/product-start ── planning approved ──┬──▶ /product-design (design.json: approved)
                                      └──▶ /product-init   (boilerplate.json: verified)
/product-build ◀── planning approved + 해시 일치 + boilerplate.json verified
                   + design.json approved(기준 planning 해시 = 현재 승인 해시)          ※ /product-build는 아직 없음
```

## 확장 지점(Milestone 2 이후)

- 후속 Skill은 `/product-init`, `/product-design`처럼 **자기 상태 파일**을 두고, `state.yaml`과 다른 Skill의 상태 파일은 읽기만 합니다. 시작 조건은 planning 승인과 승인 해시입니다.
- 템플릿과 reference는 단계별 Skill 폴더에 같은 방식으로 둡니다.
- 배포는 `.claude-plugin/plugin.json`을 추가해 plugin 형태로 전환할 수 있습니다.
