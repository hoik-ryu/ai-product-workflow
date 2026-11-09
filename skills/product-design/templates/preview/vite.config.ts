import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 정적 프리뷰 전용 설정입니다. API 프록시를 두지 않습니다.
export default defineConfig({
  plugins: [react()],
  server: { port: 55180, strictPort: true }, // 포트가 사용 중이면 다른 포트로 바꾸지 않고 실패합니다(안내한 주소와 일치)
})
