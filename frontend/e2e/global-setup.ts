/**
 * Playwright globalSetup — 在全部测试前执行一次。
 * 1. 确保 Django 用户已创建（seed_users）
 * 2. 将 Data/SampleData 下所有 CSV 预植入 DataFile 表（seed_test_data）
 * 3. 后续业务用例可直接使用数据库中的已解析文件，无需通过 UI 上传
 */
import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = path.resolve(__dirname, '..', '..')

const PYTHON = process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

function runDjango(cmd: string) {
  const full = `"${PYTHON}" manage.py ${cmd}`
  console.log(`[globalSetup] ${full}`)
  try {
    const out = execSync(full, { cwd: PROJECT_ROOT, encoding: 'utf-8', timeout: 120_000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    console.log(out.trim())
  } catch (e: any) {
    console.error(`[globalSetup] 失败: ${e.message}`)
    // seed 失败不阻塞（可能数据已存在），继续
    if (e.stdout) console.log(e.stdout.toString())
    if (e.stderr) console.error(e.stderr.toString())
  }
}

async function globalSetup() {
  runDjango('seed_users')
  // --refresh 增量刷新：清理 e2e_* 测试残留 + 仅重灌变化的 SampleData 文件，
  // 避免每次运行都全量复制/解析 714MB 数据（未变化时秒级完成）
  runDjango('seed_test_data --refresh')
}

export default globalSetup
