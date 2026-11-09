import { useEffect, useMemo, useState } from 'react'
import manifest from '../preview.manifest.json'
import { screens } from './registry'

type Viewport = 'mobile' | 'tablet' | 'desktop'
const WIDTH: Record<Viewport, number> = { mobile: 390, tablet: 768, desktop: 1280 }

function parseHash(): { screen?: string; state?: string; vp?: Viewport } {
  const [screen, state, vp] = window.location.hash.replace(/^#/, '').split('/')
  return { screen: screen || undefined, state: state || undefined, vp: (vp as Viewport) || undefined }
}

export function PreviewApp() {
  const ids = useMemo(() => Object.keys(screens).sort(), [])
  const initial = parseHash()
  const [screenId, setScreenId] = useState(initial.screen && screens[initial.screen] ? initial.screen : ids[0])
  const screen = screenId ? screens[screenId] : undefined
  const [stateId, setStateId] = useState(initial.state ?? screen?.states[0]?.id ?? '')
  const [vp, setVp] = useState<Viewport>(initial.vp ?? (screen?.platform === 'responsive' ? 'desktop' : 'mobile'))

  useEffect(() => {
    if (screenId) window.location.hash = `${screenId}/${stateId}/${vp}`
  }, [screenId, stateId, vp])

  const select = (id: string) => {
    setScreenId(id)
    setStateId(screens[id].states[0]?.id ?? '')
    setVp(screens[id].platform === 'responsive' ? 'desktop' : 'mobile')
  }

  return (
    <div className="pv-root">
      <aside className="pv-nav" aria-label="화면 목록">
        <p className="pv-badge">정적 프리뷰 · 제품 코드 아님 · UX 설계 r{String(manifest.ux_spec_revision)}</p>
        {ids.length === 0 && <p>등록된 화면이 없습니다. src/registry.tsx에 화면을 등록하세요.</p>}
        <ul>
          {ids.map((id) => (
            <li key={id}>
              <button type="button" aria-current={id === screenId} onClick={() => select(id)}>
                <span className="pv-id">{id}</span> {screens[id].title}
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main className="pv-main">
        {screen && (
          <>
            <div className="pv-toolbar">
              <div role="tablist" aria-label="화면 상태">
                {screen.states.map((s) => (
                  <button key={s.id} type="button" role="tab" aria-selected={s.id === stateId} onClick={() => setStateId(s.id)}>
                    {s.label} <span className="pv-id">{s.id}</span>
                  </button>
                ))}
              </div>
              <div aria-label="화면 폭">
                {(Object.keys(WIDTH) as Viewport[]).map((v) => (
                  <button key={v} type="button" aria-pressed={v === vp} onClick={() => setVp(v)}>
                    {v} {WIDTH[v]}px
                  </button>
                ))}
              </div>
            </div>
            <div className="pv-stage">
              <div className="pv-frame" style={{ width: WIDTH[vp] }} data-viewport={vp}>
                {screen.render(stateId)}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  )
}
