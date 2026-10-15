// frontend/test/unit/e2ePoolCore.spec.ts
// slot 池纯逻辑的 T2 层单测：无 DOM、无子进程、无 Playwright。
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import {
  SLOT_BACKEND_BASE, SLOT_FRONTEND_BASE, DEFAULT_SLOTS, MAX_SLOTS, SLOT_TARGET_MS,
  autoSlots, allocatePortBlock, partitionFiles, assertSafeRelPath, buildSlotManifest, slotEnv, mergeRunStats, parseArgs,
  normalizeTotalMs, SERIAL_REF_PER_SPEC_MS,
} from '../../e2e/helpers/pool-core.mjs'

describe('normalizeTotalMs', () => {
  it('串行单价就是参照 ⇒ 不折算', () => {
    expect(normalizeTotalMs(1_054_000, SERIAL_REF_PER_SPEC_MS)).toBeCloseTo(1_054_000, 0)
  })
  it('并发轮单价 3.90s 折回串行等价（否则 autoSlots 会顺着重排反馈环越开越多 slot）', () => {
    // N=4 实测：原始总量 1404s、单价 3900ms ⇒ 1404000×(2890/3900) = 1040400，autoSlots 仍落在 4
    expect(normalizeTotalMs(1_404_000, 3900)).toBeCloseTo(1_040_400, 0)
    expect(autoSlots(normalizeTotalMs(1_404_000, 3900))).toBe(4)
    // 不折算时，放开上限到 6 就会多要一个 slot（默认 cap=4 时看不出来，但 auto 档上限就是 MAX_SLOTS）
    expect(autoSlots(1_404_000, 6)).toBe(6)
    expect(autoSlots(normalizeTotalMs(1_404_000, 3900), 6)).toBe(5)
  })
  it('单价缺失或为 0 时原样返回（拿不到参照不猜）', () => {
    expect(normalizeTotalMs(500_000, 0)).toBe(500_000)
    expect(normalizeTotalMs(500_000, undefined)).toBe(500_000)
    expect(normalizeTotalMs(0, 3900)).toBe(0)
  })
})

describe('parseArgs', () => {
  it('认 --k=v 与 --k v 两种写法（只认空格形式时 --slots=1 会被静默吞掉，实测踩过）', () => {
    expect(parseArgs(['--slots=1']).slots).toBe('1')
    expect(parseArgs(['--slots', '1']).slots).toBe('1')
    expect(parseArgs(['--timeout-min=30'])['timeout-min']).toBe('30')
    expect(parseArgs([]).slots).toBeUndefined()
  })
  it('布尔开关与默认值（布尔语义由 defaults 里的类型决定）', () => {
    expect(parseArgs(['--dry-run'], { 'dry-run': false }).dryRun).toBe(true)
    expect(parseArgs([], { 'dry-run': false }).dryRun).toBe(false)
    expect(parseArgs([], { slots: 'auto' }).slots).toBe('auto')
  })
  it('`--` 之后的原样进 files，且 -- 本身不算开关', () => {
    const a = parseArgs(['--slots=2', '--', 'e2e/data/data.spec.ts', 'e2e/auth/auth.spec.ts'], { slots: 'auto' })
    expect(a.slots).toBe('2')
    expect(a.files).toEqual(['e2e/data/data.spec.ts', 'e2e/auth/auth.spec.ts'])
    expect(a.unknown).toEqual([])
  })
  it('未知 --x=y 落在 unknown 里而不是被忽略（拼错参数不该静默继续）', () => {
    const a = parseArgs(['--slot=3'])
    expect(a.slots).toBeUndefined()
    expect(a.unknown).toEqual(['--slot=3'])
  })
})

describe('常量', () => {
  it('端口基址与并行度上限就是设计里那几个数', () => {
    expect(SLOT_BACKEND_BASE).toBe(8101)
    expect(SLOT_FRONTEND_BASE).toBe(3101)
    expect(DEFAULT_SLOTS).toBe(4)
    expect(MAX_SLOTS).toBe(6)
    expect(SLOT_TARGET_MS).toBe(240_000)
  })
})

describe('autoSlots', () => {
  it('按每 slot ≤SLOT_TARGET_MS 反推，不超 cap、不少于 1', () => {
    expect(autoSlots(60_000)).toBe(1)
    expect(autoSlots(1_056_000)).toBe(DEFAULT_SLOTS)   // 今天的串行总量 → 4
    expect(autoSlots(1_056_000, 6)).toBe(5)
    expect(autoSlots(0)).toBe(1)
  })
})

describe('allocatePortBlock', () => {
  it('全空闲时取基址连续块', () => {
    expect(allocatePortBlock(3, () => false)).toEqual([
      { backend: 8101, frontend: 3101 }, { backend: 8102, frontend: 3102 }, { backend: 8103, frontend: 3103 },
    ])
  })
  it('后端被占 → 整块前移', () => {
    const block = allocatePortBlock(3, (p) => p === 8102)
    expect(block.map((b) => b.backend)).toEqual([8104, 8105, 8106])
    expect(block.map((b) => b.frontend)).toEqual([3104, 3105, 3106])
  })
  it('前端被占也会整块让开', () => {
    const block = allocatePortBlock(2, (p) => p === 3102)
    expect(block.map((b) => b.backend)).toEqual([8103, 8104])
    expect(block.map((b) => b.frontend)).toEqual([3103, 3104])
  })
  it('扫不到块就抛，绝不静默复用别人在跑的服务', () => {
    expect(() => allocatePortBlock(4, () => true)).toThrow(/端口块不足/)
  })
})

describe('partitionFiles', () => {
  const d = { 'a.spec.ts': 100, 'b.spec.ts': 90, 'c.spec.ts': 10, 'd.spec.ts': 10 }
  it('LPT：重的文件不堆同一桶', () => {
    const buckets = partitionFiles(['a.spec.ts', 'b.spec.ts', 'c.spec.ts', 'd.spec.ts'], d, 2)
    expect(buckets.map((b) => b.length).sort()).toEqual([2, 2])
    expect(buckets.find((b) => b.includes('a.spec.ts'))).not.toContain('b.spec.ts')
  })
  it('缺时长按 0 算；桶多于文件时留空桶', () => {
    const buckets = partitionFiles(['a.spec.ts', 'z.spec.ts'], { 'a.spec.ts': 50 }, 4)
    expect(buckets.filter((b) => b.length === 0).length).toBe(2)
  })
  it('桶内按文件名升序 → 同分区表下组合可复现', () => {
    const [only] = partitionFiles(['b.spec.ts', 'a.spec.ts'], {}, 1)
    expect(only).toEqual(['a.spec.ts', 'b.spec.ts'])
  })
  it('n<1 直接抛', () => { expect(() => partitionFiles(['a'], {}, 0)).toThrow(/≥ 1/) })
})

describe('assertSafeRelPath', () => {
  it('放过正常相对路径', () => {
    expect(assertSafeRelPath('e2e/analysis/serial-overlap.spec.ts'))
      .toBe('e2e/analysis/serial-overlap.spec.ts')
  })
  it('拒绝 shell 元字符与空格（Windows 走 shell:true，必须自己把关）', () => {
    for (const bad of ['a b.ts', 'a&b.ts', 'a|b.ts', 'a"b.ts', "a'b.ts", 'a>b.ts', 'a<b.ts', 'a^b.ts', 'a;b.ts', 'a,b.ts']) {
      expect(() => assertSafeRelPath(bad)).toThrow(/不安全/)
    }
  })
})

describe('buildSlotManifest + slotEnv', () => {
  const m = buildSlotManifest({
    index: 2, ports: { backend: 8103, frontend: 3103 },
    slotRoot: 'C:\\lqdp-e2e\\slots\\r1\\slot2', templateRoot: 'C:\\lqdp-e2e\\template',
    redisDb: 14, secretKey: 'slot-2-secret',
  })
  it('slot 路径全部落在 slot 根下，且库名长度安全', () => {
    expect(m.dataDir).toBe('C:\\lqdp-e2e\\slots\\r1\\slot2')
    expect(m.dbPath).toContain('slot2')
    expect(m.dbPath.toLowerCase()).toMatch(/db\.sqlite3$/)
    // Django 对 sqlite 也查 63 字符库名（P0 实测）：留够余身位
    expect(m.dbPath.length).toBeLessThan(64)
    expect(m.authDir).toContain('.auth')
    expect(m.downloadsDir).toContain('.downloads')
    expect(m.tempDir).toContain('temp')
    expect(m.slotFile).toContain('slot.json')
    expect(m.systemConfigFile).toContain('system-config.json')
    expect(m.templateDbPath).toContain('template')
  })
  it('env 带齐承重变量：清单、config、slot settings 档与目录、密钥、redis db、端口、token、CI', () => {
    const env = slotEnv(m, {})
    expect(env.LQDP_E2E_SLOT_FILE).toBe(m.slotFile)
    expect(env.LQDP_SYSTEM_CONFIG_FILE).toBe(m.systemConfigFile)
    expect(env.DJANGO_SETTINGS_MODULE).toBe('config.settings.e2e_slot')
    expect(env.LQDP_E2E_SLOT_DIR).toBe(m.dataDir)
    expect(env.SECRET_KEY).toBe('slot-2-secret')
    expect(env.SFTP_SESSION_REDIS_URL).toBe('redis://localhost:6379/14')
    expect(env.E2E_PORT).toBe('8103')
    expect(env.E2E_FRONTEND_PORT).toBe('3103')
    expect(env.LQDP_ACCESS_TOKEN_MINUTES).toBe('720')
    expect(env.CI).toBe('1')
  })
  it('绝不注入存储目录重定向相关变量 —— 那是 move 语义通路', () => {
    const env = slotEnv(m, {})
    expect(env.LQDP_SKIP_STORAGE_MIGRATION).toBeUndefined()
  })
  it('给了共享 blobRoot 时所有 slot 的 blobDir 指同一目录（merge-reports 只接受一个目录）', () => {
    const shared = 'C:\\lqdp-e2e\\slots\\r1\\blob'
    const mk = (index: number) => buildSlotManifest({
      index, ports: { backend: 8101 + index, frontend: 3101 + index },
      slotRoot: `C:\\lqdp-e2e\\slots\\r1\\slot${index}`, templateRoot: 'C:\\lqdp-e2e\\template',
      redisDb: 12 + index, secretKey: 'k', blobRoot: shared,
    })
    expect(mk(0).blobDir).toBe(shared)
    expect(mk(1).blobDir).toBe(shared)
    // 不给 blobRoot 时退回各自目录
    const own = buildSlotManifest({
      index: 5, ports: { backend: 8106, frontend: 3106 }, slotRoot: 'C:\\lqdp-e2e\\slots\\r2\\slot5',
      templateRoot: 'C:\\lqdp-e2e\\template', redisDb: 17, secretKey: 'k',
    })
    expect(own.blobDir).toBe(path.join('C:\\lqdp-e2e\\slots\\r2\\slot5', 'blob'))
  })
})

describe('mergeRunStats', () => {
  it('墙钟取最长 slot（并发），效率=Σ通过时长/墙钟', () => {
    const merged = mergeRunStats([
      { specs: 100, passCount: 99, passMs: 300_000, wallMs: 320_000, stats: { expected: 99, unexpected: 1, flaky: 2, skipped: 0 } },
      { specs: 100, passCount: 100, passMs: 280_000, wallMs: 310_000, stats: { expected: 100, unexpected: 0, flaky: 1, skipped: 0 } },
    ])
    expect(merged.specs).toBe(200)
    expect(merged.wallMs).toBe(320_000)
    expect(merged.passMs).toBe(580_000)
    expect(merged.efficiency).toBeCloseTo(1.8125, 4)
    expect(merged.perSpecMs).toBeCloseTo(2914.57, 1)   // 580000 / (99+100)
    expect(merged.slots).toBe(2)
    expect(merged.stats).toEqual({ expected: 199, unexpected: 1, flaky: 3, skipped: 0 })
  })
  it('空输入不炸（全 slot 都 INFRA 时）', () => {
    expect(mergeRunStats([]).efficiency).toBe(0)
    expect(mergeRunStats([]).specs).toBe(0)
  })
})
