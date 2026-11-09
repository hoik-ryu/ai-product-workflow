# UI 프리뷰 규칙

## 목적과 경계

| | `design-preview/` (`/product-design`) | `frontend/` (`/product-build`) |
|---|---|---|
| 목적 | 승인된 UX 설계를 눈으로 확인하고 시각 디자인을 승인 | 실제 제품 구현 |
| 데이터 | `src/mock/`의 가짜 데이터만 | 실제 API |
| 금지 | 실제 API 호출(fetch, axios, WebSocket 등), API 주소 환경변수, 인증, 비즈니스 로직, `frontend/` import | `design-preview/` import |
| 승인 | 시각 디자인 승인(트리 해시) | `/product-build`의 검증 |

- 프리뷰는 **최종 제품 코드가 아닙니다.** `/product-build`는 프리뷰를 시각 기준으로만 참고하고 코드를 복사해 쓰지 않는 것을 기본으로 합니다(재사용할 경우 `/product-build`에서 별도로 검토).
- 시각 디자인이 승인되기 전에는 UI 구현을 완료로 판단하지 않습니다(`/product-build` 게이트).
- `preview-check`가 위 경계를 검사합니다(주석은 제외하고 코드만 검사).
  - 코드: 금지 패턴, 모든 모듈 경로(정적·동적 `import`, `require`, `import.meta.glob`, `new URL`)가 `design-preview/` 안을 가리키는지, 문자열이 아닌 동적 import, `package.json`에 없는 패키지(별칭 우회 방지 — **별칭(alias) 대신 상대 경로**를 씁니다), `/@fs` 직접 참조
  - 설정: `vite.config.*`, `tsconfig*.json`, `index.html`의 경로(alias, `paths`, `baseUrl`, `extends`, `server.fs.allow`, `envDir`, `src`/`href`)가 프리뷰 폴더 밖이나 `frontend`를 가리키지 않는지
  - `package.json`: `file:`/`link:`/`workspace:` 로컬 의존성, 상위 폴더를 쓰는 scripts
  - 제품 쪽: `frontend/`의 코드·설정 문자열이 `design-preview`를 참조하지 않는지
  - `node_modules`·`dist`가 Git에서 무시되는지

## 위치·소유·정리

- 위치: 제품 저장소 루트의 `design-preview/`. 독립된 Vite + React + TypeScript 앱(자체 `package.json`과 lockfile)입니다. 기존 `frontend/`의 의존성 버전을 따르지만 설치는 따로 합니다.
- 소유: `/product-design`. 다른 Skill은 쓰지 않습니다.
- 커밋 대상: 소스와 `pnpm-lock.yaml`. `node_modules/`, `dist/`는 Git에서 무시합니다(템플릿의 `.gitignore`).
- 정리: 승인 후에도 `/product-build`가 UI 구현을 마칠 때까지 보존합니다. 삭제는 사용자가 결정합니다. 빌드 산출물(`node_modules`, `dist`)은 언제든 지워도 됩니다.

## 작성 순서

1. `begin --stage preview` → `preview-scaffold`(템플릿 복사, manifest에 승인된 UX 설계 revision과 화면 목록 기록)
2. `src/tokens.css`를 04의 토큰 값으로 채웁니다.
3. `src/mock/data.ts`에 화면 상태를 재현할 가짜 데이터를 만듭니다(실제 개인정보 금지).
4. 화면마다 `src/screens/<SCR-ID>.tsx`를 만들고 `src/registry.tsx`에 `"SCR-001": {...}` 형식으로 등록합니다. `states`의 id는 02의 상태 ID를 씁니다.
5. `preview.manifest.json`의 `screens`에 화면별 `file`과 `states`를 적습니다. 프리뷰에서 제외할 화면은 `{"skip": "사유"}`.
   - MVP 기준: **모든 화면을 등록**하고, 화면마다 최소 기본 상태 + 해당 화면에 정의된 주요 상태(빈 상태, 오류, 권한 없음, 충돌 중 해당하는 것)를 보여 줍니다.
6. `preview-verify`(검사 + `pnpm install` + `pnpm build`) 통과
7. 사용자에게 실행 방법과 주소를 안내하고 화면별 피드백을 받습니다.

## 실행

```bash
pnpm --dir design-preview install
pnpm --dir design-preview dev        # http://localhost:55180/#SCR-001/SCR-001-ST1/mobile
```

포트는 `strictPort: true`입니다. 55180이 사용 중이면 다른 포트로 바뀌지 않고 실패하므로, 사용 중인 프로세스를 확인하거나 `pnpm --dir design-preview dev --port <다른 포트>`로 실행합니다.

## 피드백과 버전 일치

- 피드백은 `06-preview-review.md`의 `FB-###` 표와 `design-notes.md`의 `## 프리뷰 피드백 N`에 기록합니다.
- 시각 표현(크기, 간격, 색, 배치)은 프리뷰에서 반영합니다. 화면의 정보·행동·상태가 바뀌는 피드백은 **UX 설계 변경**이므로 `reopen --stage ux_spec`이 필요하고, 그러면 프리뷰 승인이 무효화됩니다. 먼저 이 영향을 설명하고 확인을 받습니다.
- 토큰 값을 바꾸면 04 문서와 달라집니다. 토큰 변경은 UX 설계 변경으로 처리합니다.
- `preview-check`는 manifest의 `ux_spec_revision`이 승인된 UX 설계 revision과 같은지, manifest의 화면·상태가 02와 일치하는지 검사합니다.
- 시각 디자인 승인은 `design-preview/` 트리 해시(node_modules·dist 제외)와 06 문서 해시를 기록합니다. 승인 후 프리뷰 파일이 바뀌면 `approved_modified`로 차단합니다.

## Figma(선택)

- MVP는 Figma에 의존하지 않습니다. Figma 파일을 자동으로 만들지 않습니다.
- 디자이너가 Figma로 작업했다면 06 문서의 "외부 디자인 참조" 표에 링크를 적을 수 있습니다. 승인 대상은 저장소의 문서와 프리뷰이며, 링크된 Figma가 승인 후 바뀌어도 감지하지 않습니다.
