/**
 * Playwright globalSetup — 在全部测试前执行一次。
 * 1. 确保 Django 用户已创建（seed_users）
 * 2. 将 Data/SampleData 下所有 CSV 预植入 DataFile 表（seed_test_data）
 * 3. 后续业务用例可直接使用数据库中的已解析文件，无需通过 UI 上传
 */
import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { E2E_SYSTEM_CONFIG_FILE, PROJECT_ROOT } from './fixtures/test-data'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const PYTHON = process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

function runDjango(cmd: string) {
  const full = `"${PYTHON}" manage.py ${cmd}`
  console.log(`[globalSetup] ${full}`)
  try {
    // 显式注入 LQDP_SYSTEM_CONFIG_FILE（playwright.config.ts 顶层已写入
    // data_dir=PROJECT_ROOT）：execSync 只继承 process.env，不继承 webServer
    // 的 env；不加则种子进程读项目根锚点配置，触发默认 data_dir 迁移并操作
    // 用户主目录 DB，与后端各用一套数据库。
    const out = execSync(full, {
      cwd: PROJECT_ROOT, encoding: 'utf-8', timeout: 120_000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', LQDP_SYSTEM_CONFIG_FILE: E2E_SYSTEM_CONFIG_FILE },
    })
    console.log(out.trim())
  } catch (e: any) {
    console.error(`[globalSetup] 失败: ${e.message}`)
    // seed 失败不阻塞（可能数据已存在），继续
    if (e.stdout) console.log(e.stdout.toString())
    if (e.stderr) console.error(e.stderr.toString())
  }
}

async function globalSetup() {
  // e2e 把 data_dir 钉死在项目根（playwright.config.ts），而项目根 db.sqlite3
  // 可能不存在（Storage Layout v2 默认迁移把开发数据放到了用户主目录）——
  // 先 migrate 建表，保证 e2e 后端有可用的空库，再播种。
  runDjango('migrate --noinput')
  runDjango('seed_users')
  // --refresh 增量刷新：清理 e2e_* 测试残留 + 仅重灌变化的 SampleData 文件，
  // 避免每次运行都全量复制/解析 714MB 数据（未变化时秒级完成）
  runDjango('seed_test_data --refresh')
}

export default globalSetup
