import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './tokens.css'
import './preview.css'
import { PreviewApp } from './PreviewApp'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PreviewApp />
  </StrictMode>,
)
