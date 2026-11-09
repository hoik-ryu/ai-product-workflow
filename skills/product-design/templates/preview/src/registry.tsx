import type { ReactElement } from 'react'

export type Platform = 'mobile' | 'responsive' | '공통'

export type ScreenDef = {
  /** docs/design/02-screens.md의 화면 ID (예: "SCR-001") */
  id: string
  title: string
  platform: Platform
  /** 프리뷰에서 보여 줄 상태. id는 02-screens.md의 상태 ID(예: "SCR-001-ST1") */
  states: { id: string; label: string }[]
  render: (stateId: string) => ReactElement
}

// 화면을 추가할 때마다 여기에 등록합니다. 키 형식 "SCR-001"을 유지해야 스크립트가 등록 여부를 확인할 수 있습니다.
export const screens: Record<string, ScreenDef> = {}
