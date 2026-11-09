# design-preview

`/product-design`이 만든 **정적 UI 프리뷰**입니다. 제품 코드가 아닙니다.

- 실제 API, DB, 인증, 비즈니스 로직이 없습니다. 모든 데이터는 `src/mock/`의 가짜 데이터입니다.
- 제품 코드(`frontend/`)는 이 폴더를 import하지 않고, 이 폴더도 제품 코드를 import하지 않습니다.
- 실제 구현은 `/product-build`가 `frontend/`에서 합니다. 이 프리뷰는 시각 기준(승인된 화면 모습)으로만 참고합니다.

실행:

```bash
pnpm --dir design-preview install
pnpm --dir design-preview dev     # http://localhost:55180/
```

화면은 `#SCR-015/SCR-015-ST2/mobile` 같은 주소로 바로 열 수 있습니다.

- `preview.manifest.json`: 화면·상태 목록과 기준 UX 설계 revision(스크립트가 문서와 대조)
- `src/registry.tsx`: 화면 ID → 화면 컴포넌트·상태 등록
- `src/tokens.css`: `docs/design/04-ui-system.md`의 토큰
