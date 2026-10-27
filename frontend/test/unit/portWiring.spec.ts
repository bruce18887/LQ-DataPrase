/**
 * T2：端口接线契约（四家读者必须用同一对变量名）。
 *
 * 端口在本仓有四个读者：`manage.py runserver` / `standalone.py` 的 argv、
 * `frontend/vite.config.ts` 的监听口与 `/api` 代理目标（读 `E2E_FRONTEND_PORT` / `E2E_PORT`）、
 * `electron/backend.ts` 里找后端的那条路、`electron/main.ts` 里加载 Vite 的那条路。
 * 名字写错、或有人把 Electron 那两处退回写死常量，表现是「登录全红」或「Electron 白屏」
 * 这类查起来很远的错——因为它们都不报错，只是安静地连了另一个地址。
 *
 * 2026-10-27 定案：原先想做的那个开发启动器（`scripts/dev.mjs`，唯一写入方）已删 —— 打包态与
 * `standalone.py` 覆盖了真实需求（后端单独起 + 浏览器访问网页）。这里留的是它唯一不可替代的部分。
 *
 * ⚠ 本文件只读被点名的那几个文件做源码扫描，不做全仓 grep —— 它自己就含有将被命中的字面量。
 *
 * 跑：`cd frontend && npm run test:unit`（CI 已含这一步）。不需要浏览器。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const REPO_ROOT = new URL('../../../', import.meta.url)
const read = (rel: string) => readFileSync(new URL(rel, REPO_ROOT), 'utf8')

const vite = read('frontend/vite.config.ts')
const backendTs = read('electron/backend.ts')
const mainTs = read('electron/main.ts')
const standalonePy = read('standalone.py')

describe('Vite 与 Electron 读同一对变量名', () => {
  it('前端口：两处都读 E2E_FRONTEND_PORT', () => {
    expect(vite).toMatch(/process\.env\.E2E_FRONTEND_PORT/)
    expect(mainTs).toMatch(/process\.env\.E2E_FRONTEND_PORT/)
  })

  it('后端口：代理目标与 Electron 复用检测都读 E2E_PORT', () => {
    expect(vite).toMatch(/process\.env\.E2E_PORT/)
    expect(backendTs).toMatch(/process\.env\.E2E_PORT/)
  })
})

describe('Electron 的两处端口不许退回写死', () => {
  it('后端端口从 env 来，兜底 8000', () => {
    expect(backendTs).toMatch(/const DEV_BACKEND_PORT = Number\(process\.env\.E2E_PORT \|\| 8000\)/)
    expect(backendTs).not.toMatch(/const DEV_BACKEND_PORT = 8000\n/)
  })

  it('dev 渲染进程 URL 的端口从 env 来，兜底 3000', () => {
    expect(mainTs).toMatch(/Number\(process\.env\.E2E_FRONTEND_PORT \|\| 3000\)/)
    expect(mainTs).not.toMatch(/'http:\/\/localhost:3000'/)
  })
})

describe('兜底值与另外两家读者的默认值一致（不同源就是暗雷）', () => {
  it('Electron 兜的后端口 == standalone.py 的 --port 默认值', () => {
    // 改了 CLI 默认而没改 Electron 的兜底，dev 模式下 Electron 会去敲一个没人听的口。
    expect(standalonePy).toMatch(/--port', type=int, default=8000/)
    expect(backendTs).toMatch(/process\.env\.E2E_PORT \|\| 8000/)
  })

  it('Electron 兜的前端口 == vite.config 自己的默认监听口', () => {
    expect(vite).toMatch(/E2E_FRONTEND_PORT \|\| 3000/)
    expect(mainTs).toMatch(/E2E_FRONTEND_PORT \|\| 3000/)
  })

  it('Vite 是 strictPort：端口被占会硬失败而不是静默错口', () => {
    // 这条是整个契约的前提——若哪天改成自动错开，"四个读者同源"就不够，还得回读实际口。
    expect(vite).toMatch(/strictPort: true/)
  })
})
