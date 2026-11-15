import { execSync } from 'node:child_process'
import path from 'node:path'
import { PROJECT_ROOT } from '../fixtures/test-data'

const PYTHON = process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')

/**
 * 执行 Django shell 代码（代码内只用单引号，外层双引号包裹兼容 cmd）。
 *
 * 与 `e2e/global-setup.ts:15-35` 的 `runDjango` **刻意不合并**：后者跑的是子命令
 * （migrate / seed_users / seed_test_data）、显式注入 `LQDP_SYSTEM_CONFIG_FILE`、
 * 且失败必须抛（静默继续 = 残库假绿）；本函数跑 `shell -c`，且**由调用方决定要不要吞错**
 * （`repair-center.spec.ts` 的 afterEach 刻意 `try/catch` 不阻塞用例，`cleanupDup` 则
 * `console.error` 出声）。把两种失败策略并成一个函数，等于替调用方改了它的判据。
 */
export function shellDjango(code: string) {
  execSync(`"${PYTHON}" manage.py shell -c "${code}"`, {
    cwd: PROJECT_ROOT,
    encoding: 'utf-8',
    timeout: 60_000,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  })
}
