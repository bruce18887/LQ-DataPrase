import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 版本单一事实源：根 package.json —— electron-builder 打包版本（app.getVersion()）
// 与此处注入的前端版本保持一致。
const rootPkg = JSON.parse(
  readFileSync(path.resolve(__dirname, '../package.json'), 'utf-8'),
) as { version: string }

/** git short-hash，便于排障定位用户运行的代码版本（非 git 环境回退 unknown） */
function gitShortHash(): string {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: __dirname }).toString().trim()
  } catch {
    return 'unknown'
  }
}

export default defineConfig({
  // When building for Electron the SPA is loaded via file:// protocol, so
  // asset references must be relative (./assets/...) instead of absolute
  // (/assets/...). The VITE_ELECTRON env var is set by the electron:build
  // npm script.
  base: process.env.VITE_ELECTRON === 'true' ? './' : '/',
  define: {
    __APP_VERSION__: JSON.stringify(rootPkg.version),
    __BUILD_COMMIT__: JSON.stringify(gitShortHash()),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
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
  build: {
    // Suppress "chunks larger than 500 kB" warnings — the analysis and
    // data-management views legitimately bundle echarts/ag-grid which are
    // large by nature. Code-splitting them further would hurt runtime perf.
    chunkSizeWarningLimit: 1500,
    rolldownOptions: {
      onwarn(warning, defaultHandler) {
        // @vueuse/core ships /* #__PURE__ */ annotations in positions that
        // Rolldown cannot interpret. This is a known upstream issue and
        // only affects dead-code elimination optimization, not correctness.
        if (warning.code === 'INVALID_ANNOTATION' &&
            warning.message?.includes('@vueuse/core')) {
          return
        }
        defaultHandler(warning)
      },
      output: {
        // Split vendor libs into separate chunks for better caching.
        // Rolldown's manualChunks only accepts a function form.
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts') || id.includes('vue-echarts') || id.includes('zrender')) {
              return 'echarts-vendor'
            }
            if (id.includes('ag-grid')) {
              return 'ag-grid-vendor'
            }
            if (id.includes('element-plus') || id.includes('@element-plus')) {
              return 'element-vendor'
            }
          }
        },
      },
    },
  },
})
