---
doc: design-traceability
revision: 1
language: ko
based_on:
  planning_revision: {planning_revision}
  ux_planning_revision: {ux_planning_revision}
---

# 디자인 추적성 (Design Traceability): {project_name}

스크립트(`trace --stage ux_spec`)가 이 표를 검사합니다. FLOW 단계 → 화면 대응은 `03-screen-flows.md`에 있습니다.

## 1. User Story → 화면

Must·Should US는 모두 행이 있어야 합니다. Should를 이번에 설계하지 않으면 `후속: 사유`를 적습니다.

| US | 우선순위 | 화면 | UX 결정 |
|---|---|---|---|
| US-001 | Must | SCR-002 | UXD-001 |

## 2. Acceptance Criteria → 화면·상태

모든 AC가 행을 가져야 합니다. 화면에서 확인할 수 없는 AC는 `비UI: 사유`를 적습니다.

| AC | 화면·상태 | 확인 방법 |
|---|---|---|
| AC-001 | SCR-002-ST1 | 제출 후 승인 대기 안내 |
| AC-028 | 비UI: 서버 알고리즘의 결정성 | 백엔드 테스트 |

## 3. 커버리지 점검 결과

`trace` 결과(화면 수, Must US 커버, AC 매핑, 비UI 수, 경고)를 적습니다.

## 4. 검토 체크리스트 결과

`reference/review-checklist.md` 항목별 결과와 남은 이슈를 적습니다.

## 5. 기획 피드백

디자인 중 발견한 기획 공백이나 모순입니다(00 문서의 PF와 연결). 기획 문서는 수정하지 않았습니다.
