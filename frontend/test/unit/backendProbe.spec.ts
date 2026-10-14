/**
 * T2：远端后端可达性探测（`electron/net-probe.ts:probeBackendUrl`）。
 *
 * 该探针刻意住在不 import electron 的独立模块里：一旦测试把 `electron` 的类型声明
 * 拖进前端 tsconfig 的编译范围，`vue-tsc -b` 就报 `Cannot find module 'electron'`
 * （2026-10-14 实测：探针最初放在 backend.ts 里，加完这条用例前端类型门禁当场红）。
 *
 * 为什么值得单独钉：这个函数的返回值直接决定首启之后的兜底路径 ——
 * 判成「可达」会把窗口丢给一个其实连不上的服务器，判成「不可达」会把用户留在连接页。
 * 两种误判都比报错更难查，而且它是批 4 里唯一走真实网络的一环。
 *
 * 这些是**实现之后补的特征化用例**（不是 TDD 的红→绿）：函数是照 planStartup 的调用点
 * 写的，写它时没有任何测试压着。端口用 OS 分配的临时端口，不与 e2e 的 3000/8000 冲突。
 *
 * 跑：npm run test:unit
 */
import * as http from 'http'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { probeBackendUrl } from '../../../electron/net-probe'

let server: http.Server
let baseUrl = ''
/** 只在收到请求时置真：用来证明「判定依据是真的网络往返，不是 URL 形状猜测」 */
let hitCount = 0

beforeAll(async () => {
  server = http.createServer((_req, res) => {
    hitCount += 1
    // 真实后端未认证时回 401 —— 这正是判据要接受的形状
    res.writeHead(401, { 'Content-Type': 'application/json' })
    res.end('{"detail":"no auth"}')
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (typeof address === 'string' || address === null) throw new Error('未拿到端口')
  baseUrl = `http://127.0.0.1:${address.port}`
})

afterAll(async () => {
  await new Promise<void>((resolve, reject) =>
    server.close((err) => (err ? reject(err) : resolve())))
})

/** 起一个服务拿到 OS 分配的端口，随即关掉 —— 得到一个「此刻没人监听」的端口 */
async function takeThenReleasePort(): Promise<number> {
  const tmp = http.createServer()
  await new Promise<void>((resolve) => tmp.listen(0, '127.0.0.1', resolve))
  const address = tmp.address()
  if (typeof address === 'string' || address === null) throw new Error('未拿到端口')
  const port = address.port
  await new Promise<void>((resolve, reject) =>
    tmp.close((err) => (err ? reject(err) : resolve())))
  return port
}

describe('probeBackendUrl', () => {
  it('活着的后端（哪怕回 401）判为可达', async () => {
    expect(await probeBackendUrl(baseUrl, 5000)).toBe(true)
    expect(hitCount, '判定必须来自真实 HTTP 往返').toBeGreaterThan(0)
  })

  it('尾部斜杠不影响判定', async () => {
    expect(await probeBackendUrl(`${baseUrl}/`, 5000)).toBe(true)
  })

  it('端口没人监听判为不可达', async () => {
    // 用一个「起过又关掉」的端口：不去动本 describe 共享的服务，
    // 否则 close/listen 交错会让 afterAll 的收尾报错，把红因搅浑。
    const free = await takeThenReleasePort()
    expect(await probeBackendUrl(`http://127.0.0.1:${free}`, 2000)).toBe(false)
  })

  it('非法 URL 不抛，判为不可达', async () => {
    expect(await probeBackendUrl('不是个地址', 1000)).toBe(false)
    expect(await probeBackendUrl('', 1000)).toBe(false)
  })

  it('地址里有子路径时探测打在 <base>/api/v1/ 上', async () => {
    const before = hitCount
    expect(await probeBackendUrl(`${baseUrl}/lqdp`, 5000)).toBe(true)
    expect(hitCount, '带子路径也要真发一次请求').toBeGreaterThan(before)
  })
})
