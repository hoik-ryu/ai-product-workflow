# 요구사항 ID 규칙

ID는 산출물 언어와 관계없이 항상 영어 접두사 + 세 자리 숫자입니다.

| 접두사 | 의미 | 정의 위치 |
|---|---|---|
| `PRB-` | 문제(Problem) | 01-discovery |
| `PER-` | 페르소나 / 대상 사용자 | 01-discovery |
| `GOAL-` | 목표 / 성공 지표 | 01-discovery |
| `ASM-` | 가정(Assumption, 사용자가 확인하지 않음) | 01-discovery, 02-prd |
| `Q-` | 미결 질문(Open Question, 미정) | 01-discovery, 02-prd |
| `FR-` | 기능 요구사항(Functional Requirement) | 02-prd |
| `NFR-` | 비기능 요구사항(Non-Functional Requirement) | 02-prd |
| `US-` | 사용자 스토리(User Story) | 03-user-stories |
| `FLOW-` | 사용자 플로우(User Flow, 단계는 `FLOW-001-S1`) | 04-user-flows |
| `AC-` | 인수 조건(Acceptance Criterion) | 05-acceptance-criteria |

## 규칙

- 번호는 접두사별로 프로젝트 전체에서 `001`부터 매깁니다. `ASM-`과 `Q-`는 문서를 넘어 이어집니다(PRD는 discovery의 마지막 번호 다음부터).
- ID를 재사용하거나 번호를 다시 매기지 않습니다. 삭제한 항목은 `~~FR-004~~ (r3에서 폐기: 사유)` 형태로 남깁니다.
- 모든 항목은 상위 ID를 참조합니다.
  - `FR` → `GOAL` / `PRB` (관련 있으면 `PER`도)
  - `US` → `FR` + `PER`
  - `FLOW` → `US`
  - `AC` → `US` + `FR`
- 사용자의 진술이 아니라 AI의 추론인 내용은 `가정(Assumptions)` 섹션에 두거나 본문에서 `(ASM-002)`처럼 `ASM-` ID를 인용합니다. 모든 문장에 태그를 달지 않습니다.
- 미결 질문에 따라 달라지는 항목은 `(Q-003)`처럼 인용합니다.
- 표의 ID 열과 항목 헤딩(`### US-001: ...`, `### AC-001: ...`, `## FLOW-001: ...`)은 ID로 시작하게 유지합니다.

## 추적성 점검(planning `awaiting_approval` 전)

다음을 확인하고 결과를 사용자에게 보고합니다.

1. 모든 `FR`이 1개 이상의 `US`로 커버되는가
2. 모든 `US`(Must/Should)에 1개 이상의 `AC`가 있는가
3. 모든 `US`가 1개 이상의 `FLOW`에 나타나는가(또는 "UI 플로우 없음"으로 명시됐는가)
4. 참조한 ID가 모두 존재하고 폐기되지 않았는가
5. 05 문서의 `추적 매트릭스(Traceability Matrix)`가 위 결과와 일치하는가

누락이 있으면 제출 전에 고치거나, 승인 요청 시 미해결 항목으로 명시합니다.
