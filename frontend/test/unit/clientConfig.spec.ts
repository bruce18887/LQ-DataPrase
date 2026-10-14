/**
 * T2：客户端「连哪个后端」的配置解析与校验（`electron/client-config.ts`）。
 *
 * 这块逻辑必须**纯**（不碰 electron/fs），理由有三：
 * 1. 它是唯一一处「用户输入 → 后端地址」的判据，坏了会让 Electron 去连一个非法地址；
 * 2. 它跑在主进程，崩了就是白屏，没有任何界面能显示错误；
 * 3. 纯函数才能进 T2（毫秒级），不必为它起浏览器（T3 一条 ≈5.4s）。
 *
 * 关键契约：**任何输入都不得抛异常**，一律回落到 `{mode:'local', serverUrl:''}`。
 * 配置在 userData 里，坏 JSON 多半来自半截写入或手工编辑 —— 那种情况下把用户
 * 留在本机模式启动，比让他对着一个崩溃的启动画面有用。
 *
 * 跑：npm run test:unit
 */
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'
import { describe, expect, it } from 'vitest'

import {
  configFilePath,
  DEFAULT_CLIENT_CONFIG,
  hasClientConfig,
  normalizeServerUrl,
  parseClientConfig,
  planStartup,
  readClientConfig,
  serializeClientConfig,
  writeClientConfig,
} from '../../../electron/client-config'
import type { ClientConfig } from '../../../electron/client-config'

describe('parseClientConfig：坏输入一律回落本机，绝不抛', () => {
  it('空文本回落默认（首次运行就是这条路）', () => {
    expect(parseClientConfig('')).toEqual(DEFAULT_CLIENT_CONFIG)
    expect(parseClientConfig('   ')).toEqual(DEFAULT_CLIENT_CONFIG)
  })

  it('半截 JSON 不抛，回落本机', () => {
    expect(parseClientConfig('{"mode":"remote","serverUrl":"http://10.0')).toEqual(
      DEFAULT_CLIENT_CONFIG,
    )
  })

  it('顶层不是对象也不抛', () => {
    for (const bad of ['[]', '"str"', '42', 'null', 'true']) {
      expect(parseClientConfig(bad), bad).toEqual(DEFAULT_CLIENT_CONFIG)
    }
  })

  it('mode 不认识就当本机', () => {
    expect(parseClientConfig('{"mode":"server","serverUrl":"http://h:1"}').mode).toBe('local')
  })

  it('remote 但没给可用地址 → 本机（不能让主进程去连空 URL）', () => {
    for (const raw of ['{"mode":"remote"}', '{"mode":"remote","serverUrl":""}',
                       '{"mode":"remote","serverUrl":"ftp://h:1"}']) {
      expect(parseClientConfig(raw), raw).toEqual(DEFAULT_CLIENT_CONFIG)
    }
  })

  it('合法远端配置被完整保留', () => {
    const cfg = parseClientConfig('{"mode":"remote","serverUrl":"http://10.0.0.9:8000"}')
    expect(cfg).toEqual({ mode: 'remote', serverUrl: 'http://10.0.0.9:8000' })
  })
})

describe('normalizeServerUrl：只接受 http/https + 有主机名，返回可判别联合', () => {
  it('接受 IPv4 / 主机名 / 端口 / 子路径', () => {
    expect(normalizeServerUrl('http://10.0.0.9:8000')).toEqual({ ok: true, url: 'http://10.0.0.9:8000' })
    expect(normalizeServerUrl('https://server01')).toEqual({ ok: true, url: 'https://server01' })
    expect(normalizeServerUrl('http://h/app')).toEqual({ ok: true, url: 'http://h/app' })
  })

  it('去掉首尾空白与结尾斜杠（否则 /api/v1 会拼成 //api/v1）', () => {
    expect(normalizeServerUrl('  http://h:8000/  ')).toEqual({ ok: true, url: 'http://h:8000' })
    expect(normalizeServerUrl('http://h:8000///')).toEqual({ ok: true, url: 'http://h:8000' })
  })

  it('拒绝非 http(s) 协议，并给出可显示的中文原因', () => {
    const bad = normalizeServerUrl('ftp://10.0.0.9')
    expect(bad.ok).toBe(false)
    expect(bad.ok ? '' : bad.error).toContain('http')
  })

  it('拒绝没有主机名的地址', () => {
    expect(normalizeServerUrl('http://').ok).toBe(false)
    expect(normalizeServerUrl('').ok).toBe(false)
    expect(normalizeServerUrl('localhost:8000').ok).toBe(false)  // 缺协议，别偷偷补
  })

  it('拒绝带凭证的 URL（user:pass@host 不是这里的用法，且会把口令写进配置文件）', () => {
    expect(normalizeServerUrl('http://admin:pw@10.0.0.9:8000').ok).toBe(false)
  })
})

describe('planStartup：四条启动分支（主进程只消费结果，判据在这里）', () => {
  const LOCAL: ClientConfig = { mode: 'local', serverUrl: '' }
  const REMOTE: ClientConfig = { mode: 'remote', serverUrl: 'http://10.0.0.9:8000' }

  it('首启：不 spawn 本机后端，也不加载远端，先进连接页', () => {
    // 这条是整套设计的根：先 spawn 就等于替用户做了「连哪个后端」的决定，
    // 而且本机那份库会被建出来。
    expect(planStartup(LOCAL, { firstRun: true, remoteReachable: false })).toEqual({
      spawnLocalBackend: false, loadUrl: null, route: '#/connect',
    })
  })

  it('本机模式：spawn 本机，不改路由', () => {
    expect(planStartup(LOCAL, { firstRun: false, remoteReachable: true })).toEqual({
      spawnLocalBackend: true, loadUrl: null, route: null,
    })
  })

  it('远端可达：加载服务器地址，不 spawn', () => {
    expect(planStartup(REMOTE, { firstRun: false, remoteReachable: true })).toEqual({
      spawnLocalBackend: false, loadUrl: 'http://10.0.0.9:8000', route: null,
    })
  })

  it('远端不可达：留在连接页，且**不许**偷偷 spawn 本机兜底', () => {
    // 静默退回本机 = 用户的分析结果写进另一个库，比报错危险得多。
    expect(planStartup(REMOTE, { firstRun: false, remoteReachable: false })).toEqual({
      spawnLocalBackend: false, loadUrl: null, route: '#/connect',
    })
  })
})

describe('serializeClientConfig：写出去读得回来', () => {
  it('round-trip 稳定', () => {
    const cfg = { mode: 'remote' as const, serverUrl: 'http://10.0.0.9:8000' }
    expect(parseClientConfig(serializeClientConfig(cfg))).toEqual(cfg)
  })

  it('序列化结果里的键是 mode/serverUrl（文件是给人排查的，别改字段名）', () => {
    const text = serializeClientConfig({ mode: 'remote', serverUrl: 'http://h:1' })
    expect(Object.keys(JSON.parse(text)).sort()).toEqual(['mode', 'serverUrl'])
  })
})

describe('配置文件读写（目录由调用方给定，模块本身不依赖 electron）', () => {
  const makeDir = (): string => fs.mkdtempSync(path.join(os.tmpdir(), 'lqdp-client-config-'))

  it('目录不存在 / 文件不存在 → 默认本机，且 hasClientConfig 为假（这就是首启判据）', () => {
    const dir = path.join(makeDir(), 'not-created-yet')
    expect(hasClientConfig(dir)).toBe(false)
    expect(readClientConfig(dir)).toEqual(DEFAULT_CLIENT_CONFIG)
  })

  it('写入后可读回，且不留 .tmp（原子写的证据）', () => {
    const dir = makeDir()
    writeClientConfig(dir, { mode: 'remote', serverUrl: 'http://10.0.0.9:8000' })
    expect(hasClientConfig(dir)).toBe(true)
    expect(readClientConfig(dir)).toEqual({ mode: 'remote', serverUrl: 'http://10.0.0.9:8000' })
    expect(fs.existsSync(configFilePath(dir) + '.tmp')).toBe(false)
  })

  it('半截 JSON 的配置文件不抛，回落本机', () => {
    const dir = makeDir()
    fs.writeFileSync(configFilePath(dir), '{"mode":"rem', 'utf-8')
    expect(readClientConfig(dir)).toEqual(DEFAULT_CLIENT_CONFIG)
  })

  it('重复写入是覆盖而不是追加', () => {
    const dir = makeDir()
    writeClientConfig(dir, { mode: 'remote', serverUrl: 'http://a:1' })
    writeClientConfig(dir, { mode: 'local', serverUrl: '' })
    expect(readClientConfig(dir)).toEqual(DEFAULT_CLIENT_CONFIG)
  })
})
