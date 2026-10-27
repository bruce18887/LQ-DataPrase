import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// 版本单一事实源：frontend/package.json —— electron-builder 打包版本
// （app.getVersion()，因 directories.app 指向 frontend 而读取该文件）
// 与此处注入的前端版本保持一致。
const appPkg = JSON.parse(
  readFileSync(path.resolve(__dirname, './package.json'), 'utf-8'),
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
    __APP_VERSION__: JSON.stringify(appPkg.version),
    __BUILD_COMMIT__: JSON.stringify(gitShortHash()),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    // 默认 3000（electron:dev 的 wait-on 写死它）；同机并发跑两套 e2e 时，
    // strictPort 会让第二个 preview 直接失败而不是自动错开 —— 所以跑测侧需要能显式换端口。
    // 用 E2E_FRONTEND_PORT 覆盖，与 playwright.config.ts 的 FRONTEND_URL 读同一个变量。
    port: Number(process.env.E2E_FRONTEND_PORT || 3000),
    strictPort: true,
    proxy: {
      '/api': {
        // 代理目标跟随 E2E_PORT（默认 8000）：playwright 可以把后端挪到别的端口，
        // 这里若写死 8000 就会在换端口时静默 ECONNREFUSED（2026-10-14 实测踩过）。
        // server 与 preview 两处必须同源 —— 只改一处会在 e2e 里表现为「登录全红」。
        target: `http://localhost:${process.env.E2E_PORT || '8000'}`,
        changeOrigin: true,
      },
    },
  },
  // e2e 的生产构建 webServer（playwright.config 的 PW_DEV_SERVER=1 逃生门不用它）：
  // preview 不继承 server.proxy，必须显式声明同一份 /api 代理
  preview: {
    host: '0.0.0.0',
    port: Number(process.env.E2E_FRONTEND_PORT || 3000),
    strictPort: true,
    proxy: {
      '/api': {
        // 代理目标跟随 E2E_PORT（默认 8000）：playwright 可以把后端挪到别的端口，
        // 这里若写死 8000 就会在换端口时静默 ECONNREFUSED（2026-10-14 实测踩过）。
        // server 与 preview 两处必须同源 —— 只改一处会在 e2e 里表现为「登录全红」。
        target: `http://localhost:${process.env.E2E_PORT || '8000'}`,
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
        // 分块走 codeSplitting + priority，不用函数式 manualChunks。
        // 根因（2026-10-27 用 hidden sourcemap 取证）：函数返回值在 rolldown 合并阶段只是
        // 建议，@vue/{shared,reactivity,runtime-core,runtime-dom} 被塞回 ag-grid-vendor，
        // 于是每个 chunk 都要先下载 1.19MB 才拿到 createApp —— 登录页也一样。
        // priority 大的组先认领模块，Vue 才能与网格分开。
        codeSplitting: {
          groups: [
            {
              name: 'vue-vendor',
              test: /[\\/]node_modules[\\/](vue|@vue|vue-router|pinia)[\\/]/,
              priority: 100,
            },
            {
              name: 'echarts-vendor',
              test: /[\\/]node_modules[\\/](echarts|vue-echarts|zrender)[\\/]/,
              priority: 90,
            },
            {
              name: 'ag-grid-vendor',
              test: /[\\/]node_modules[\\/]ag-grid-/,
              priority: 80,
            },
            {
              name: 'element-vendor',
              test: /[\\/]node_modules[\\/](@element-plus|element-plus)[\\/]/,
              priority: 70,
            },
          ],
        },
      },
    },
  },
})
