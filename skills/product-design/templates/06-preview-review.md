---
doc: preview-review
revision: 1
language: ko
based_on:
  ux_spec_revision: {ux_spec_revision}
---

# UI 프리뷰 검토 (Preview Review): {project_name}

- 프리뷰 위치: `design-preview/` (정적 프리뷰, 제품 코드 아님)
- 실행: `pnpm --dir design-preview install && pnpm --dir design-preview dev` → http://localhost:55180/
- 기준: UX 설계 r{ux_spec_revision}(승인됨)

## 화면별 피드백

| ID | 화면·상태 | 피드백(사용자 원문 요약) | 조치 | 상태 |
|---|---|---|---|---|
| FB-001 | SCR-015-ST2 | ... | 코트 카드 글자 크기 18px로 | 반영 / 보류 / UX 설계 변경 필요 |

`UX 설계 변경 필요`인 피드백은 프리뷰에서 임의로 반영하지 않습니다. UX 설계를 다시 열어(reopen) 승인받은 뒤 반영합니다.

## 외부 디자인 참조(선택)

| 화면 | 도구 | 링크 | 비고 |
|---|---|---|---|
| SCR-015 | Figma | (선택) | 승인 대상은 이 저장소의 문서와 프리뷰입니다 |
