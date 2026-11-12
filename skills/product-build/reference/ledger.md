# 정책·편차 원장과 decide, 문서 반영 대기열 (M2.4b)

## 1. 원장

- **위치**: `.ai-workflow/build/ledger.json`
  - `state.yaml`·`build.json`과 분리돼 있고, Git 추적 대상입니다.
  - 사람용 보기는 `docs/build/10-decisions.md`(생성 문서, 직접 수정 금지)입니다.
- **항목 필드**
  - 고유 ID와 유형
  - 상태: `open` | `decided` | `closed` | `dismissed`
  - 제목·설명·차단 여부
  - 관련 배치·AC·문서, 임시값
  - 분류 근거(`rationale`)·분류자
  - 결정 이력(`decisions[]`: 결정 내용·사용자 원문·결정자·시각·영향)
  - 이력(`history[]`)
- **원문 보존**: 원래 내용(ID·유형·제목·설명·출처·생성 시각)은 digest로 고정합니다. 바뀌면 `ledger_invalid`로 멈춥니다. 결정·변경은 덧붙입니다.
- **상호 참조**: 검증 실행(run_id)·목표 변경(target_overrides)·결함 주입 인정(fi_accepted)·배치 ID를 `source`·`related`로 가리킵니다.

| 유형(ID) | 뜻 | 결정 대상 | 차단 가능 |
|---|---|---|---|
| `policy`(POL) | 명세에 없는 정책(미결정). 임시값 포함 | 예(`decide`) | 예 |
| `deviation`(DEV) | 승인 명세와 다른 구현(WF-D01 ①–⑤) | 예 | 예 |
| `evidence_gap`(EVD) | 검증 증거 부족(테스트 없음·목표 미달·실패) | 아니요(테스트·구현으로 해결) | **아니요**(검증 상태가 이미 진행을 막음) |
| `target_change`(TGT) | 사용자 승인된 목표 변경·결함 주입 인정 기록 | 이미 결정됨 | 아니요 |

## 2. 등록과 수집

- **`ledger add`**: `--type --title --desc [--blocking] [--batches] [--acs] [--docs] [--category ①–⑤] [--provisional] [--rationale]`
- **`ledger sync`**(멱등)
  - 검증 결과의 미충족 AC → `evidence_gap`. 충족되면 닫고 이력을 남깁니다.
  - 목표 변경·결함 주입 인정 → `target_change`(사용자 원문과 함께 결정됨)
  - 코드의 `TODO(POL): …` → 비차단 `policy`(소유 배치 연결)
  - `TODO(POL-001)`은 기존 항목에 위치를 기록합니다.
- **`ledger dismiss`**: `--id --reason --note`(사용자 확인)

## 3. 차단 기준

**차단**(`--blocking`)으로 둘 항목
- 보안·권한·개인정보
- 되돌리기 어려운 데이터·스키마
- 외부 계약(API·결제)
- 승인 명세와 다른 행동(① 정보·행동, ② 토큰 의미)

되돌리기 쉬운 임시값(가중치·기본값·문구·판정 기준)은 비차단입니다. 모든 항목을 일괄 차단하지 않습니다.

**영향 배치**: 지정한 배치와, 관련 AC를 가진 배치입니다.

**미결 차단 항목이 있는 영향 배치**
- `batch-start`·`resume`·`execute-gate`·`approve batch`가 막힙니다(`blocked_by_policy`).
- **실행 중** 배치는 다음 `task-done`·`checkpoint`에서 체크포인트를 남긴 뒤 `paused`가 되고 잠금을 풉니다(`paused_by_policy`).
- 정책 대기로 멈춘 배치는 활성 배치로 세지 않습니다. 그래서 관련 없는 독립 배치는 진행할 수 있습니다. 실행 잠금은 여전히 하나입니다.

## 4. decide

| 형태 | 하는 일 |
|---|---|
| `decide` | 결정 대상(정책·편차 미결) 목록과 영향 미리보기 |
| `decide --id POL-001` | 미리보기만(기록 없음): 영향 배치(현재 상태와 결정 뒤 변화)·AC·문서·이전 결정 |
| `decide --id … --decision "<요약>" --note "<사용자 원문>" --confirm [--propose "<문서>::<변경>"]` | 결정 기록 |

- 사용자 원문과 `--confirm`이 없으면 기록하지 않습니다. AI가 결정을 추측해 기록하지 않습니다.
- 결정을 바꾸면 새 결정(`supersedes`)을 덧붙입니다. 첫 결정·원문은 보존됩니다.
- **결정 효과**
  - 영향 배치 중 `verified`·`approved`는 `stale`(재검증 필요)이 되고, 승인 기록에는 무효 표시만 붙습니다.
  - 차단이 풀려도 재검증·최종 승인을 다시 거칩니다.

## 5. 문서 반영 대기열

**대상**
- 기획(`docs/planning/`)
- UX Spec(`docs/design/`, AC 화면 대응 포함)
- 구현 계획(`docs/build/`)

**단계**

| 단계 | 기록 | 내용 |
|---|---|---|
| 제안 | `proposed` | `decide --propose`. 원본 문서와 그 해시를 기준으로 기록 |
| 사용자 승인 | `approved` | `doc-proposal approve --id --note`. 원본은 아직 그대로 |
| 적용 | 소유 Skill | 기획은 `/product-start` 재검토, UX Spec은 `/product-design reopen`, 구현 계획은 `reopen plan`→수정→`submit`→승인 |
| 적용 확인 | `applied` | `doc-proposal apply-check --id`. 문서가 바뀌었고 소유 Skill의 재승인이 유효할 때만. 손으로만 고친 문서는 인정하지 않음 |

**적용 뒤**
- 기획·UX Spec이 재승인되면 `check`가 구현 계획을 outdated로 표시합니다(입력 기준선).
- 계획 재승인 때 기존 배치의 실행·검증·승인 기록은 보존됩니다.
- 영향 배치는 재검증·재승인을 거칩니다.
- 기존 승인 기록은 삭제하지 않습니다.
