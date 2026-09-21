/**
 * 本地 paramiko SFTP 服务器（e2e 用）。
 *
 * 启动 sftp_server.py（监听 127.0.0.1 随机端口，接受任意账号密码，root 指向
 * 临时目录），从 stdout 首行 JSON 解析端口。返回 { host, port, root, stop() }。
 */
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export interface SftpTestServer {
  host: string
  port: number
  /** 服务器 root 目录（已建好 sub1/sample.csv + root.csv + notes.txt + big.csv；
   *  `options.fixture` 为真时再叠一层 `sftp_server.py:write_fixture_tree` 的搜索树） */
  root: string
  stop: () => void
}

const PYTHON_BIN = process.env.PYTHON_BIN || path.resolve(__dirname, '..', '..', '..', '.venv', 'Scripts', 'python.exe')

export interface StartSftpServerOptions {
  /**
   * 让服务器在 `--root` 下多造一棵**搜索用**的文件树（`sftp_server.py:write_fixture_tree`，
   * 由 Task 11B 的 Python 集成测试引入）。计划 Task 18 Step 1 点名的那五样
   * （`batch1/Deep/RT_3.csv` 深度档、GBK 中文 CSV、`Sum_total.csv` 汇总、`backup/RT_9.csv`
   * 剪枝、20 万行 `BIG.csv`）全在那棵树里，且每一项都为一条断言而存在。
   *
   * **为什么是开关而不是把树并进默认**：`sftp.spec.ts` / `reconnect.spec.ts` 的行内
   * `.first()` 断言靠的是「根目录只有 4 个条目」这个隐含前提，树一并进默认就等于把两条
   * 既有用例的选中文件换成 `batch1/*`（含 20 万行那份，下载用例会慢一个量级）。
   * 也不需要另写一份树：树只有一份事实来源（Python 侧），两条链路（集成测试 / e2e）
   * 断言的是同一批字节，改树时不会出现「e2e 绿了集成测试红了」。
   */
  fixture?: boolean
}

/** 启动 SFTP 服务器；fixture 模式下造树要时间，超时相应放宽。 */
export async function startSftpServer(
  options: StartSftpServerOptions = {},
): Promise<SftpTestServer> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'e2e-sftp-'))
  fs.mkdirSync(path.join(root, 'sub1'))
  fs.writeFileSync(path.join(root, 'sub1', 'sample.csv'), 'a,b\n1,2\n')
  fs.writeFileSync(path.join(root, 'root.csv'), 'x,y\n1,2\n')
  // 非 CSV 文件：验证「仅 CSV」过滤默认隐藏、切换「全部文件」后可见
  fs.writeFileSync(path.join(root, 'notes.txt'), 'not a csv\n')
  // 大文件：验证单文件下载 SSE 进度（百分比/速率）
  const bigRows = Array.from({ length: 200_000 }, (_, i) => `${i},${i * 2}\n`).join('')
  fs.writeFileSync(path.join(root, 'big.csv'), 'n,double\n' + bigRows)

  const script = path.resolve(__dirname, 'sftp_server.py')
  const argv = [script, '--root', root]
  if (options.fixture) argv.push('--fixture')
  const proc = spawn(PYTHON_BIN, argv, { stdio: ['ignore', 'pipe', 'pipe'] })
  // 端口 JSON 之前服务器要先把 fixture 树写完（含 20 万行那份），故按模式给超时
  const startupTimeoutMs = options.fixture ? 30_000 : 10_000

  // 启动失败/超时路径同样需要回收临时目录（stop() 只覆盖成功路径）
  function cleanupRoot(): void {
    try { fs.rmSync(root, { recursive: true, force: true }) } catch { /* 已删除或占锁 */ }
  }

  const port = await new Promise<number>((resolve, reject) => {
    let buf = ''
    const timer = setTimeout(() => {
      proc.kill()
      cleanupRoot()
      reject(new Error(`SFTP 服务器启动超时：${buf || '无输出'}`))
    }, startupTimeoutMs)
    proc.stdout.on('data', (chunk: Buffer) => {
      buf += chunk.toString()
      const line = buf.split('\n').find((l) => l.trim().startsWith('{'))
      if (!line) return
      try {
        const info = JSON.parse(line)
        clearTimeout(timer)
        resolve(info.port as number)
      } catch {
        /* 继续等下一行 */
      }
    })
    proc.on('error', (err) => {
      clearTimeout(timer)
      cleanupRoot()
      reject(err)
    })
  })

  return {
    host: '127.0.0.1',
    port,
    root,
    stop: () => {
      // Windows 下直接 spawn 的 python.exe 可用 kill() 终止
      try { proc.kill() } catch { /* 已退出 */ }
      // mkdtempSync 创建的 root 必须成对清理，否则每次运行都在 %TEMP% 泄漏目录
      try { fs.rmSync(root, { recursive: true, force: true }) } catch { /* 已删除或占锁 */ }
    },
  }
}
