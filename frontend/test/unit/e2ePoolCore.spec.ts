// frontend/test/unit/e2ePoolCore.spec.ts
// slot 池纯逻辑的 T2 层单测：无 DOM、无子进程、无 Playwright。
import { describe, expect, it } from 'vitest'
import path from 'node:path'
import {
  SLOT_BACKEND_BASE, SLOT_FRONTEND_BASE, DEFAULT_SLOTS, MAX_SLOTS, SLOT_TARGET_MS,
  autoSlots, allocatePortBlock, partitionFiles, assertSafeRelPath, buildSlotManifest, slotEnv, mergeRunStats, parseArgs,
  normalizeTotalMs, SERIAL_REF_PER_SPEC_MS, classifySlotHealth, roundVerdict,
  nextLivenessState, LIVENESS_MISSES, LIVENESS_TIMEOUT_MS, classifyReds, parsePassthrough,
} from '../../e2e/helpers/pool-core.mjs'

describe('classifyReds（红文件自动复跑判级）', () => {
  it('复跑绿 ⇒ 记负载抖动，不算真红；复跑仍红 ⇒ 真红', () => {
    const r = classifyReds(['a.spec.ts', 'b.spec.ts'], [
      { file: 'a.spec.ts', red: false, infra: false },
      { file: 'b.spec.ts', red: true, infra: false },
    ])
    expect(r.loadFlakes).toEqual(['a.spec.ts'])
    expect(r.confirmed).toEqual(['b.spec.ts'])
    expect(r.unresolved).toEqual([])
  })
  it('复跑那一轮本身崩池（服务失联）⇒ 悬而未决，保守算红，不许当成抖动放过', () => {
    const r = classifyReds(['a.spec.ts'], [{ file: 'a.spec.ts', red: true, infra: true }])
    expect(r.unresolved).toEqual(['a.spec.ts'])
    expect(r.confirmed).toEqual([])
    expect(r.countsBlock).toBe(true)          // 门禁仍然拦
  })
  it('复跑时用例整条没跑上（specs=0）也算没验成，不放行', () => {
    const r = classifyReds(['a.spec.ts'], [{ file: 'a.spec.ts', red: false, infra: false, specs: 0 }])
    expect(r.unresolved).toEqual(['a.spec.ts'])
  })
  it('漏掉某个文件的复跑结果 ⇒ 该文件进 unresolved', () => {
    const r = classifyReds(['a.spec.ts', 'b.spec.ts'], [{ file: 'a.spec.ts', red: false, infra: false, specs: 5 }])
    expect(r.loadFlakes).toEqual(['a.spec.ts'])
    expect(r.unresolved).toEqual(['b.spec.ts'])
  })
  it('没有红就不该调用复跑，但被调用时结论是干净放行', () => {
    const r = classifyReds([], [])
    expect(r.confirmed).toEqual([])
    expect(r.countsBlock).toBe(false)
  })
})

describe('nextLivenessState（看门狗防谎报）', () => {
  it('单次探测失败不算掉线 —— 满载时 150ms 超时就曾把活着的 4 个 slot 全报死', () => {
    expect(nextLivenessState({ misses: 0, dead: false }, false, true)).toEqual({ misses: 1, dead: false })
    expect(nextLivenessState({ misses: 1, dead: false }, false, true).dead).toBe(true)
  })
  it('一次成功就把计数清零（间歇性超时不误判）', () => {
    expect(nextLivenessState({ misses: 99, dead: false }, true, true)).toEqual({ misses: 0, dead: false })
  })
  it('子进程已退出或已判死就不再改状态：收尾关端口不是事故', () => {
    expect(nextLivenessState({ misses: 1, dead: false }, false, false)).toEqual({ misses: 1, dead: false, done: true })
    expect(nextLivenessState({ misses: 2, dead: true }, true, true)).toEqual({ misses: 2, dead: true, done: true })
  })
  it('常量与实测教训一致', () => {
    expect(LIVENESS_MISSES).toBe(2)
    expect(LIVENESS_TIMEOUT_MS).toBe(1_500)
  })
})

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

describe('classifySlotHealth / roundVerdict', () => {
  it('服务半路死掉那种成片红判 INFRA（实测：某轮 2 个 slot 掉线，refused 473 次、155 红）', () => {
    expect(classifySlotHealth({ specs: 96, unexpected: 77, refusedCount: 240 })).toBe('INFRA')
    expect(classifySlotHealth({ specs: 96, unexpected: 30, refusedCount: 6 })).toBe('INFRA')
    expect(roundVerdict([
      { slot: 0, specs: 96, unexpected: 0, refusedCount: 0 },
      { slot: 1, specs: 96, unexpected: 77, refusedCount: 240 },
    ])).toEqual({ verdict: 'VOID (infra)', infraSlots: [1] })
  })
  it('真回归不能被误判成 INFRA：40 条红但没有连接级错误 ⇒ 照实报成一轮有红的测量', () => {
    expect(classifySlotHealth({ specs: 96, unexpected: 40, refusedCount: 0 })).toBe('OK')
    expect(roundVerdict([{ slot: 0, specs: 96, unexpected: 40, refusedCount: 0 }]))
      .toEqual({ verdict: 'MEASURED', infraSlots: [] })
  })
  it('少量偶发红与个别 strict mode 红都算正常轮', () => {
    expect(classifySlotHealth({ specs: 96, unexpected: 2, refusedCount: 0 })).toBe('OK')
    expect(roundVerdict([
      { slot: 0, specs: 96, unexpected: 2, refusedCount: 0 },
      { slot: 1, specs: 96, unexpected: 0, refusedCount: 0 },
    ]).verdict).toBe('MEASURED')
  })
  it('连 JSON 都没有的 slot 直接算 INFRA（不能因为"没数据"而放行）', () => {
    expect(roundVerdict([{ slot: 2, specs: 0, unexpected: 0, refusedCount: 5 }]).infraSlots).toEqual([2])
  })
})

describe('常量', () => {
  it('并行度上限与单 slot 墙钟目标就是设计里那几个数', () => {
    expect(DEFAULT_SLOTS).toBe(4)
    expect(MAX_SLOTS).toBe(6)
    expect(SLOT_TARGET_MS).toBe(240_000)
  })
  it('端口基址在动态端口区间之外 —— 监听口不该落在临时端口池里（这是卫生，不是掉线的修法）', () => {
    // 本机实测 netsh 动态区间 = 1024..15000，旧基址 8101/3101 就在里面。
    // 上界取 49152：万一哪天把动态区间改回 Windows 默认值，这两个基址仍然在区间外。
    // 注意：preview 掉线与此无关 —— 换到区间外的第三轮照样掉两个（spec §6 的否证记录）。
    for (const base of [SLOT_BACKEND_BASE, SLOT_FRONTEND_BASE]) {
      expect(base).toBeGreaterThanOrEqual(15_001)
      expect(base + MAX_SLOTS).toBeLessThan(49_152)
    }
  })
})

describe('parsePassthrough（透传给 playwright 的开关，走 env 不混进文件表）', () => {
  it('认常见开关，多个空格也归一', () => {
    expect(parsePassthrough('--project=P0  --grep=@p0')).toEqual(['--project=P0', '--grep=@p0'])
    expect(parsePassthrough(undefined)).toEqual([])
  })
  it('带 shell 元字符就抛 —— 编排器用 shell 起 npx，这里必须把关', () => {
    for (const bad of ['--grep=a;b', '--grep=$(x)', '--grep=`id`', '--project="P0"', '--grep=(a)']) {
      expect(() => parsePassthrough(bad)).toThrow(/不安全/)
    }
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
  const B = SLOT_BACKEND_BASE
  const F = SLOT_FRONTEND_BASE
  it('全空闲时取基址连续块', () => {
    expect(allocatePortBlock(3, () => false)).toEqual([
      { backend: B, frontend: F }, { backend: B + 1, frontend: F + 1 }, { backend: B + 2, frontend: F + 2 },
    ])
  })
  it('后端被占 → 整块前移', () => {
    const block = allocatePortBlock(3, (p) => p === B + 1)
    expect(block.map((b) => b.backend)).toEqual([B + 3, B + 4, B + 5])
    expect(block.map((b) => b.frontend)).toEqual([F + 3, F + 4, F + 5])
  })
  it('前端被占也会整块让开', () => {
    const block = allocatePortBlock(2, (p) => p === F + 1)
    expect(block.map((b) => b.backend)).toEqual([B + 2, B + 3])
    expect(block.map((b) => b.frontend)).toEqual([F + 2, F + 3])
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
