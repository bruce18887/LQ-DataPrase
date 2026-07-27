import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  // When building for Electron the SPA is loaded via file:// protocol, so
  // asset references must be relative (./assets/...) instead of absolute
  // (/assets/...). The VITE_ELECTRON env var is set by the electron:build
  // npm script.
  base: process.env.VITE_ELECTRON === 'true' ? './' : '/',
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    // Fail fast if port 3000 is taken — the electron:dev script's wait-on
    // is hardcoded to :3000, so a silent port shift would hang Electron.
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
