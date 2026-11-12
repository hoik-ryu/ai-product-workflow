---
doc: information-architecture
revision: 1
language: ko
based_on:
  planning_revision: {planning_revision}
  ux_planning_revision: {ux_planning_revision}
---

# 정보 구조 (Information Architecture): {project_name}

## 1. 역할과 레이아웃 셸

| 역할 | 셸 | 플랫폼 | 근거 |
|---|---|---|---|
| (예) PER-001 회원 | 회원 셸(하단 탭) | mobile | NFR-002, UXD-001 |

## 2. 메뉴 구조(사이트맵)

```
회원 셸
├─ 홈 (SCR-004)
└─ ...
```

## 3. 라우트 표

스크립트가 이 표의 SCR ID와 `02-screens.md`의 화면 헤딩이 일치하는지 검사합니다.

| 화면 ID | 화면 이름 | 경로 | 접근 역할 | 플랫폼 | 셸 |
|---|---|---|---|---|---|
| SCR-001 | 로그인 | /login | 비로그인 | mobile | 인증 |

플랫폼 값: `mobile` | `responsive` | `공통`

## 4. 역할별 접근 매트릭스

| 영역 | 회원 | 운영자 | 슈퍼 관리자 | 비로그인 |
|---|---|---|---|---|
| (예) 운영 메뉴 | ✕ (SCR-020) | ○ | ○ | ✕ → 로그인 |

## 5. 전역 내비게이션 규칙

- 인증·권한 리다이렉트, 뒤로 가기, 딥링크 규칙
