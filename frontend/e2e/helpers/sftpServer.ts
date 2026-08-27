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
  /** 服务器 root 目录（已建好 sub1/sample.csv + root.csv） */
  root: string
  stop: () => void
}

const PYTHON_BIN = process.env.PYTHON_BIN || path.resolve(__dirname, '..', '..', '..', '.venv', 'Scripts', 'python.exe')

/** 启动 SFTP 服务器；10s 内未输出端口 JSON 视为失败。 */
export async function startSftpServer(): Promise<SftpTestServer> {
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
  const proc = spawn(PYTHON_BIN, [script, '--root', root], { stdio: ['ignore', 'pipe', 'pipe'] })

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
    }, 10_000)
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
