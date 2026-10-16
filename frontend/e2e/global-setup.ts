/**
 * Playwright globalSetup — 在全部测试前执行一次。
 * 1. 确保 Django 用户已创建（seed_users）
 * 2. 将 Data/SampleData 下所有 CSV 预植入 DataFile 表（seed_test_data）
 * 3. 后续业务用例可直接使用数据库中的已解析文件，无需通过 UI 上传
 */
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { E2E_SYSTEM_CONFIG_FILE, PROJECT_ROOT, DOWNLOAD_DIR } from './fixtures/test-data'
import { CURRENT_SLOT } from './helpers/slot'

const PYTHON = process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

function runDjango(cmd: string) {
  const full = `"${PYTHON}" manage.py ${cmd}`
  console.log(`[globalSetup] ${full}`)
  // 显式注入 LQDP_SYSTEM_CONFIG_FILE 与档变量（playwright.config.ts 顶层已设
  // DJANGO_SETTINGS_MODULE=config.settings.e2e_slot + LQDP_E2E_SLOT_DIR=数据根）：
  // execSync 只继承 process.env，不继承 webServer 的 env，所以这里必须把三个键都点齐，
  // 否则种子子进程会按默认档解析、落到别的库/media 上，与后端各用一套数据。
  try {
    const out = execSync(full, {
      cwd: PROJECT_ROOT, encoding: 'utf-8', timeout: 120_000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', LQDP_SYSTEM_CONFIG_FILE: E2E_SYSTEM_CONFIG_FILE },
    })
    console.log(out.trim())
  } catch (e: any) {
    // 失败必须失败：migrate/seed 任一步失败都意味着后续用例跑在
    // 未播种/半播种的库上，报错难归因（历史教训：静默继续 → 残库假绿）。
    if (e.stdout) console.log(e.stdout.toString())
    if (e.stderr) console.error(e.stderr.toString())
    throw new Error(`[globalSetup] 失败: ${full}\n${e.message}`)
  }
}

async function globalSetup() {
  if (CURRENT_SLOT) {
    // slot 模式：库与种子由 scripts/e2e_pool.mjs 预铸（模板 → 每 slot 一份 db 拷贝 + 硬链镜像 media）。
    // 这里再 migrate/seed 等于对已经就位且正被别的用例读写的 slot 库重跑一遍播种，
    // 既慢又会双重写入 SQLite，故跳过。
    console.log(`[globalSetup] slot=${CURRENT_SLOT.index} 跳过 migrate/seed（模板库已就位：${CURRENT_SLOT.dbPath}）`)
  } else {
    // 串行的库在 `<仓库根>/test/e2e-data/db.sqlite3`（DATA_DIR 由 helpers/slot 给）。
    // 该文件可能不存在（首次运行、或上一批测试残留被清）—— 先 migrate 建表，
    // 保证 e2e 后端有可用的空库，再播种。
    runDjango('migrate --noinput')
    runDjango('seed_users')
    // --refresh 增量刷新：清理 e2e_* 测试残留 + 仅重灌变化的 SampleData 文件，
    // 避免每次运行都全量复制/解析 714MB 数据（未变化时秒级完成）
    runDjango('seed_test_data --refresh')
  }
  // 清空上一轮下载产物：.downloads 不在 Playwright outputDir 内，不自动清，
  // 且文件名带时间戳 → 跨运行累积（实测 28.5MB / 59 个文件）。
  try {
    fs.rmSync(DOWNLOAD_DIR, { recursive: true, force: true })
    fs.mkdirSync(DOWNLOAD_DIR, { recursive: true })
  } catch (e: any) {
    console.warn(`[globalSetup] 清理 .downloads 失败（忽略）: ${e.message}`)
  }
}

export default globalSetup
