import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import os from 'node:os'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, '..')

// venv Python（Windows 路径；其它平台用 PYTHON_BIN 覆盖）
const PYTHON_BIN =
  process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

const FRONTEND_URL = 'http://localhost:3000'
const BACKEND_PORT = '8000'
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`

// 默认由 Playwright 自动拉起前后端；设 PW_NO_WEBSERVER=1 改为手动起服务
const NO_WEBSERVER = process.env.PW_NO_WEBSERVER === '1'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // 本地也保留 1 次重试：dev 环境 Vite/Django 长时间运行后可能劣化（Vite 进程偶发退出）
  retries: process.env.CI ? 2 : 1,
  // workers 上限 6：webServer 只起一个单进程 Django dev server，默认（核数/2=14）
  // 个并行浏览器打同一后端会触发崩溃/锁库/flaky（见 lessons R1/R6），反而更慢
  workers: process.env.CI ? 1 : Math.min(6, Math.floor(os.cpus().length / 2)),
  timeout: 60_000,
  expect: { timeout: 10_000 },

  // 全局前置：seed 用户 + 预植入 SampleData 到 DB（在所有项目之前）
  globalSetup: path.join(__dirname, 'e2e', 'global-setup.ts'),

  reporter: [['html', { open: 'never' }], ['list']],

  // 测试产物（含失败截图/视频/trace）与下载文件目录
  outputDir: './test-results',

  // 📊 Playwright UI 模式下显示的元数据
  metadata: {
    title: 'LQ-DataPrase E2E',
    description: 'ATE 量产数据分析平台 — 端到端测试套件',
    modules: 'smoke | auth | global | dashboard | data | analysis | batch | sftp | settings | roadmap | admin | exports',
    priorities: '@p0 冒烟 | @p1 核心 | @p2 增强',
  },

  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    channel: 'msedge',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    // 1) 登录态准备：登录 admin / user 并导出 storageState
    {
      name: 'setup',
      testMatch: /fixtures[\\/]auth\.setup\.ts/,
    },
    // 2) 业务用例：默认使用 admin 登录态（仅含 localStorage token）
    //    带 @pN 标签的用例由 P0/P1/P2 项目承接——若不排除，全量运行时
    //    每个带标签用例会在 Edge + 优先级项目里各跑一遍（实测多跑 357 次）
    {
      name: 'Edge',
      use: {
        ...devices['Desktop Edge'],
        channel: 'msedge',
        storageState: path.join(__dirname, 'e2e', '.auth', 'admin.json'),
      },
      dependencies: ['setup'],
      grepInvert: /@p[012]/,
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    // 3) 按优先级选择性运行（在 UI 中用 filter 切，或 CLI: --grep @p0）
    {
      name: 'P0',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: path.join(__dirname, 'e2e', '.auth', 'admin.json') },
      grep: /@p0/,
      dependencies: ['setup'],
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    {
      name: 'P1',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: path.join(__dirname, 'e2e', '.auth', 'admin.json') },
      grep: /@p1/,
      dependencies: ['setup'],
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    {
      name: 'P2',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: path.join(__dirname, 'e2e', '.auth', 'admin.json') },
      grep: /@p2/,
      dependencies: ['setup'],
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
  ],

  webServer: NO_WEBSERVER
    ? undefined
    : [
        {
          // Django 后端（development 配置 + sqlite）
          command: `"${PYTHON_BIN}" manage.py runserver ${BACKEND_PORT} --noreload`,
          cwd: PROJECT_ROOT,
          url: `${BACKEND_URL}/api/schema/`,
          reuseExistingServer: true,
          timeout: 120_000,
          stdout: 'pipe',
          stderr: 'pipe',
          // 系统存储路径配置（system_config.json）隔离到临时文件，
          // 避免 e2e 修改路径时污染项目根目录
          env: {
            ...process.env,
            LQDP_SYSTEM_CONFIG_FILE: path.join(os.tmpdir(), 'lqdp-e2e-system-config.json'),
          },
        },
        {
          // Vite 前端（/api 代理到 8000）
          command: 'npm run dev',
          cwd: __dirname,
          url: FRONTEND_URL,
          reuseExistingServer: true,
          timeout: 120_000,
          stdout: 'pipe',
          stderr: 'pipe',
        },
      ],
})
