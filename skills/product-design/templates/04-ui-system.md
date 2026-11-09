---
doc: ui-system
revision: 1
language: ko
based_on:
  planning_revision: {planning_revision}
  ux_planning_revision: {ux_planning_revision}
---

# UI 컴포넌트와 디자인 토큰 (UI System): {project_name}

화면 명세에서 **실제로 반복해 쓰인 것만** 컴포넌트로 정의합니다. 토큰은 최소한으로 둡니다. 특정 디자인 도구 형식에 묶이지 않습니다.

## 1. 디자인 토큰

| 토큰 | 값 | 용도 |
|---|---|---|
| color.bg | #FFFFFF | 페이지 배경 |
| color.text | #1A1A1A | 본문 |
| color.primary | ... | 주요 행동 |
| color.danger | ... | 오류·삭제 |
| space.unit | 4px | 간격 기본 단위 |
| radius.md | 8px | 카드·버튼 |
| font.size.body | 16px | 본문(모바일 최소 16px) |
| breakpoint.mobile-max | 480px | 회원 화면 최대 폭 |

색 대비: 본문 텍스트 4.5:1 이상, 큰 텍스트·아이콘 3:1 이상.

## 2. 컴포넌트

<!-- 형식(스크립트가 검사함):
### CMP-001: 이름
- **용도**: ...
- **변형**: primary / secondary
- **상태**: 기본, 비활성, 로딩, 오류
- **사용 화면**: SCR-001, SCR-004
- **접근성**: 레이블, 포커스, 터치 영역 44px -->

## 3. 공통 패턴

- 확인 창, 토스트, 빈 상태, 오류 표시, 충돌 안내의 공통 규칙
