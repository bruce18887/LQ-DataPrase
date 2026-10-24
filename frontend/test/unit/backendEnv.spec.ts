/**
 * T2：后端子进程的 env 构造（`electron/backend-env.ts`）。
 *
 * 为什么要单独测这个：打包版的中文乱码与「日志级别失真」都不是产品代码的错，而是
 * spawn 时少给了 stdio 编码口径 —— 这类「少一行 env」的回归在类型检查里抓不到，
 * 跑界面也看不出来（日志文件人眼读），只能由判据钉住。
 *
 * 跑法：cd frontend && npx vitest run test/unit/backendEnv.spec.ts
 */
import { describe, expect, it } from 'vitest'

import { buildBackendEnv } from '../../../electron/backend-env'

const BASE = { PATH: '/usr/bin', SYSTEMROOT: 'C:\\Windows', HOME: '/home/u' }
const INPUT = { userDataPath: 'C:\\Users\\u\\LQ-DataPrase', shutdownToken: 'tok-abc' }

describe('buildBackendEnv', () => {
  it('继承父进程 env（漏了这条等于把 PATH 抹掉，dev 档找不到 python.exe）', () => {
    const env = buildBackendEnv(BASE, INPUT)
    expect(env.PATH).toBe('/usr/bin')
    expect(env.SYSTEMROOT).toBe('C:\\Windows')
  })

  it('父进程的同名值被覆盖而不是反向覆盖', () => {
    const env = buildBackendEnv({ ...BASE, LQDP_BASE_DIR: 'C:\\\\wrong' }, INPUT)
    expect(env.LQDP_BASE_DIR).toBe(INPUT.userDataPath)
  })

  it('钉住 stdio 编码与逐行 flush', () => {
    const env = buildBackendEnv(BASE, INPUT)
    // Electron 侧 `data.toString()` 按 UTF-8 解；不给这条，Windows 上 Python 用 cp936 写
    expect(env.PYTHONIOENCODING).toBe('utf-8')
    expect(env.PYTHONUNBUFFERED).toBe('1')
  })

  it('带本次启动的 shutdown token 与数据目录锚点', () => {
    const env = buildBackendEnv(BASE, INPUT)
    expect(env.LQDP_SHUTDOWN_TOKEN).toBe('tok-abc')
    expect(env.LQDP_BASE_DIR).toBe(INPUT.userDataPath)
  })

  it('刻意不设 PYTHONUTF8（它会把 open() 的默认文本编码一起改掉）', () => {
    const env = buildBackendEnv(BASE, INPUT)
    expect(env.PYTHONUTF8).toBeUndefined()
    expect(env.PYTHONCOERCECLOCALE).toBeUndefined()
  })
})
