import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,   // 같은 wifi 의 폰에서 접속하려면 필요하다
    port: 5173,
  },
  build: {
    outDir: 'dist',
  },
})
