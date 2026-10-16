import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { E2E_SYSTEM_CONFIG_FILE } from './e2e/fixtures/test-data'
import { ADMIN_STATE, CURRENT_SLOT, SLOTS } from './e2e/helpers/slot'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, '..')

// e2e 两种模式统一跑 config.settings.e2e_slot：库 / MEDIA_ROOT / 临时区全由
// LQDP_E2E_SLOT_DIR 这一个变量直接指认（串行 = test/e2e-data，slot = 该 slot 自己的目录）。
// 刻意**不**走 data_dir 那条导入期重定向 —— 它是 move 语义（copy → verify → 删源），
// 2026-10-14 就是这样把仓库根 media/ 与 db.sqlite3 搬走并删掉的
// （docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md §4.1、lessons 同日）。
// 写在 webServer spawn 之前；同时写入 process.env 让 globalSetup 的 execSync 子进程
// （migrate / seed_users / seed_test_data）与 repair-center 用例的 `manage.py shell` 读同一套配置。
process.env.DJANGO_SETTINGS_MODULE = 'config.settings.e2e_slot'
process.env.LQDP_E2E_SLOT_DIR = SLOTS.dataDir
if (CURRENT_SLOT) {
  // slot 模式：编排器已写好 slot.json 与 system-config.json，这里只认不重写。
  process.env.LQDP_SYSTEM_CONFIG_FILE = CURRENT_SLOT.systemConfigFile
} else {
  // 这份配置在 e2e_slot 档下完全惰性（该档不调 apply_system_config），留着是因为
  // /api/v1/system/paths/ 的 `configured` 字段读的就是它（settings.system-paths 用例据此断言），
  // 同时万一某个进程仍按 development 档解析，data_dir=项目根 → target==anchor → 空操作，搬不走东西。
  fs.writeFileSync(
    E2E_SYSTEM_CONFIG_FILE,
    JSON.stringify({ data_dir: PROJECT_ROOT }),
    'utf-8',
  )
  process.env.LQDP_SYSTEM_CONFIG_FILE = E2E_SYSTEM_CONFIG_FILE
}

// venv Python（Windows 路径；其它平台用 PYTHON_BIN 覆盖）
const PYTHON_BIN =
  process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

// 前端端口也可换（默认 3000）：vite 的 server/preview 都读 E2E_FRONTEND_PORT。
// 只换后端端口是半个修复 —— strictPort 下第二个 preview 会失败，而并发跑测会互相
// 把对方的前端服务打穿，表现为成片 net::ERR_CONNECTION_REFUSED（lessons 2026-10-14）。
const FRONTEND_PORT = process.env.E2E_FRONTEND_PORT || '3000'
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`
// 默认仍是 8000（夜间轮与其它会话的既有约定）。留一个覆盖口：本机常挂着别人起的
// `manage.py runserver 8000`，那个进程读的是仓库根 system_config.json
// （data_dir = 用户真实数据目录），用例的 PUT /auth/settings/ 就会写进真实账号
// （lessons 2026-09-19 / 2026-10-14 两条同一险情）。这条险情现由后端
// `reuseExistingServer: false` 关闭 —— 不再静默复用，代价是 8000 被占时自起会失败，
// 所以换端口（E2E_PORT 指空闲口）比停掉别人的进程安全。
const BACKEND_PORT = process.env.E2E_PORT || '8000'
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`

// 默认由 Playwright 自动拉起前后端；设 PW_NO_WEBSERVER=1 改为手动起服务，
// 设 PW_DEV_SERVER=1 前端改用 vite dev（单 spec 快速迭代用；全量默认走
// vite build + preview：dev 模式每次导航要拉取数百个模块，~350 次 goto 的
// 累计开销显著，且 6 workers 曾压垮 dev server，见 lessons）
const NO_WEBSERVER = process.env.PW_NO_WEBSERVER === '1'
const USE_DEV_SERVER = process.env.PW_DEV_SERVER === '1'

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

  // 非 slot：沿用 html + list。slot：blob（供编排器 merge-reports 出统一 HTML）+ json
  // （供编排器自算合并）。blob 的输出目录只能经 reporter 选项给，`--blob-report` 在 1.60 不是 CLI 选项。
  reporter: CURRENT_SLOT
    ? [
        ['blob', { outputDir: CURRENT_SLOT.blobDir }],
        ['json', { outputFile: CURRENT_SLOT.jsonOut }],
        ['list'],
      ]
    : [['html', { open: 'never' }], ['list']],

  // 测试产物（含失败截图/视频/trace）与下载文件目录
  outputDir: './test-results',

  // 📊 Playwright UI 模式下显示的元数据
  metadata: {
    title: 'LQ-DataPrase E2E',
    description: 'ATE 量产数据分析平台 — 端到端测试套件',
    modules: 'smoke | auth | global | dashboard | data | analysis | batch | sftp | settings | admin | exports',
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
        storageState: ADMIN_STATE,
      },
      dependencies: ['setup'],
      grepInvert: /@p[012]/,
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    // 3) 按优先级选择性运行（在 UI 中用 filter 切，或 CLI: --grep @p0）
    {
      name: 'P0',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: ADMIN_STATE },
      grep: /@p0/,
      dependencies: ['setup'],
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    {
      name: 'P1',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: ADMIN_STATE },
      grep: /@p1/,
      dependencies: ['setup'],
      testIgnore: /fixtures[\\/]auth\.setup\.ts/,
    },
    {
      name: 'P2',
      use: { ...devices['Desktop Edge'], channel: 'msedge', storageState: ADMIN_STATE },
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
          // 专用探针，不再借 /api/schema/：那条路由由 API_DOCS_ENABLED 控制，
          // 而它存在与否是「要不要暴露 API 文档」的决定，跟「后端起没起来」无关
          // （standalone/server 档都关掉了它）。/api/v1/health/ 恒 200、无鉴权、
          // 不限流，见 apps/common/health.py。
          url: `${BACKEND_URL}/api/v1/health/`,
          // 一律自起自收，**包括本地**：后端现在跑 config.settings.e2e_slot，数据面由
          // LQDP_E2E_SLOT_DIR 指认；而本机常挂着一个 development 档的 `manage.py runserver 8000`
          // （读的是用户主目录那份库与 media）。复用它 = 种子写 test/e2e-data、服务读 home 的
          // 分裂态，比 lessons R3 的「复用旧代码进程」更难归因。端口被占就该炸出来，
          // 要留服务自己起：E2E_PORT 换空闲口（先 `netsh int ipv4 show dynamicport tcp` 问区间）。
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: 'pipe',
          stderr: 'pipe',
          // 系统存储路径配置（system_config.json）隔离到临时文件：
          // 内容在模块顶层写入（data_dir=PROJECT_ROOT），避免 e2e 修改路径
          // 时污染项目根目录、也防止默认 data_dir 迁移触发
          env: {
            ...process.env,
            LQDP_SYSTEM_CONFIG_FILE: E2E_SYSTEM_CONFIG_FILE,
            // 全量轮 CI=1 下 workers=1 要跑 40+ min，而 storageState 里的 access token
            // 只有 30 min（config/settings/base.py）；这里放宽只对本机 e2e 的 webServer
            // 生效，生产与默认开发配置不变。
            LQDP_ACCESS_TOKEN_MINUTES: '720',
          },
        },
        {
          // Vite 前端：默认生产构建 + preview（加载快、负载稳）；
          // PW_DEV_SERVER=1 时退回 dev server（改测试时快速迭代用；全量默认走
          // build + preview：dev 每次导航要拉数百模块，~350 次 goto 的累计开销显著，
          // 且 6 workers 曾压垮 dev server，见 lessons）。
          // E2E_SKIP_BUILD=1 由 slot 编排器注入：包已经 build 过一次，N 个进程各 build 一遍是纯浪费。
          // slot 模式再套一层监督器（`scripts/e2e_preview_supervised.mjs`）：preview 会无声消失，
          // Playwright 直接起 npm 时**没人记退出码**，而重生一次就能省下整轮（6 轮里 4 轮作废的账）。
          command: USE_DEV_SERVER
            ? 'npm run dev'
            : CURRENT_SLOT
              ? `${process.env.E2E_SKIP_BUILD === '1' ? '' : 'npm run build && '}node ../scripts/e2e_preview_supervised.mjs`
              : process.env.E2E_SKIP_BUILD === '1'
                ? 'npm run preview'
                : 'npm run build && npm run preview',
          cwd: __dirname,
          url: FRONTEND_URL,
          reuseExistingServer: !process.env.CI && !CURRENT_SLOT,
          timeout: USE_DEV_SERVER || process.env.E2E_SKIP_BUILD === '1' ? 120_000 : 300_000,
          // 显式把后端端口传给 vite：proxy 目标读的就是它（写死 8000 会在换端口时
          // 让 /api 直接 ECONNREFUSED，登录 setup 全红、383 例不跑 —— 2026-10-14 实测）
          env: { ...process.env, E2E_PORT: BACKEND_PORT, E2E_FRONTEND_PORT: FRONTEND_PORT },
          stdout: 'pipe',
          stderr: 'pipe',
        },
      ],
})
