/**
 * T2：dock 布局存档与账号勾选的**向后兼容**判据（specs/2026-11-04 §4/§10）。
 *
 * 这次加的是第 5 个 key，所以真正的风险不是「新 key 读不到」，而是「旧存档被判非法」：
 * `isValidLayout` 只认 `v === VERSION` 且「key ∈ ALL_KEYS」⇒ 往 ALL_KEYS 加一项会让旧存档
 * **继续合法**（旧键集是新键集的子集），而升 `VERSION` 会让所有用户存过的布局整表丢弃。
 * 所以这条文件钉的是「不丢」，不是「迁移」：
 * ① 旧 v:1 四图存档在新代码下仍判合法，且**回读后 rows/rowPcts/colPcts/bodyH 逐字不丢**
 *    （`loadLayout` 是唯一读者，用 mock 过的 safeStorage 喂真存档做回读；只断言
 *    「isValidLayout=true」是弱判据——它答不了「读出来还是不是原来那份」）；
 * ② 含 site3d 的新存档合法；
 * ③ 未知 key（回滚场景/手改 localStorage）仍判非法，别让一处坏数据顶掉整表；
 * ④ 默认布局是 hist 独立首行 + 其余每行 2 张：**4 图就是 3 行**（末行只剩 box 一张），
 *    5 图时第 3 行放 box+site3d 各半宽；
 * ⑤ 旧账号 toggles 缺 site3d ⇒ 默认关（勾过的用户才看得到 3D，别默认挤成 5 格）。
 */
import { describe, expect, it, vi } from 'vitest'

// 「服务端有 layout、toggles 丢了」的 F5 竞态：只喂 loadChartMemory 用到的两个成员。
// 真实 store 的 ensure 单飞/失败口径由 test/unit/userSettings.spec.ts 钉住，这里不重复量。
vi.mock('../../src/stores/userSettings', () => ({
  useUserSettingsStore: () => ({
    raw: {
      analysis_chart_memory: true,
      analysis_chart_state: {
        layout: { v: 1, rows: [['hist'], ['box', 'site3d']], rowPcts: [70, 30], colPcts: [[100], [50, 50]], bodyH: null },
      },
    },
    ensure: () => Promise.resolve(),
  }),
}))

import { DOCK_LAYOUT_STORAGE_KEY, defaultLayout, isValidLayout, loadLayout, type ChartKey } from '../../src/pages/analysis/composables/useChartDock'
import { loadChartMemory, parseToggles } from '../../src/composables/useChartMemory'

// localStorage 的读出面：只服务「旧存档回读」那一条真回读，值与用例同步可变。
// `safeGetItem` 校验键名——否则读错键（比如读到 toggles 那把）也会绿，回读就白测了。
const storageState = vi.hoisted(() => ({ raw: null as string | null, key: '' }))
vi.mock('../../src/utils/safeStorage', () => ({
  safeGetItem: (k: string) => (k === storageState.key ? storageState.raw : null),
  safeSetItem: () => {},
  safeRemoveItem: () => {},
}))

const LEGACY_V1 = {
  v: 1,
  rows: [['hist'], ['serial', 'qq'], ['box']],
  rowPcts: [58.6, 20.7, 20.7],
  colPcts: [[100], [50, 50], [100]],
  // bodyH 用真数值而不是 null：null 的回读断言是空断言（null 进 null 出什么都证明不了），
  // 900 落在 [DOCK_BODY_MIN_H, MAX_BODY_H] 内，回读必须原样带回
  bodyH: 900,
}

describe('存量布局存档：加第 5 个 key 不许把旧的判成非法', () => {
  it('旧 v:1 四图存档仍判合法', () => {
    expect(isValidLayout(LEGACY_V1)).toBe(true)
  })

  it('旧 v:1 四图存档回读后字段逐字不丢（不按新键集重排、不补 site3d 行）', () => {
    storageState.key = DOCK_LAYOUT_STORAGE_KEY
    storageState.raw = JSON.stringify(LEGACY_V1)
    const loaded = loadLayout()
    expect(loaded).not.toBeNull()
    expect(loaded!.rows).toEqual(LEGACY_V1.rows)
    expect(loaded!.rowPcts).toEqual(LEGACY_V1.rowPcts)
    expect(loaded!.colPcts).toEqual(LEGACY_V1.colPcts)
    expect(loaded!.bodyH).toBe(900)
  })

  it('含 site3d 的存档判合法', () => {
    expect(isValidLayout({ ...LEGACY_V1, rows: [['hist'], ['serial', 'qq'], ['box', 'site3d']] })).toBe(true)
  })

  it('未知 key 仍判非法（旧版代码读到新存档时整表作废、回落默认，不画半张图）', () => {
    expect(isValidLayout({ ...LEGACY_V1, rows: [['hist'], ['nope']] })).toBe(false)
  })

  it('重复 key 判非法（同一张图占两格会让 findPos/moveTo 找错）', () => {
    expect(isValidLayout({ v: 1, rows: [['hist', 'hist']], rowPcts: [100], colPcts: [[50, 50]], bodyH: null })).toBe(false)
  })

  it('存档键名不变（改名等于把所有用户的本机布局清零）', () => {
    expect(DOCK_LAYOUT_STORAGE_KEY).toBe('lqdp-analysis-chart-layout')
  })
})

describe('defaultLayout — 5 图时的形状', () => {
  const all: ChartKey[] = ['hist', 'serial', 'qq', 'box', 'site3d']
  const rows = defaultLayout(all).rows
  it('hist 独立首行，其余每行 2 张 ⇒ 3 行', () => {
    expect(rows).toEqual([['hist'], ['serial', 'qq'], ['box', 'site3d']])
  })
  it('四图存档不受影响（勾集合没变就不该变形状）', () => {
    expect(defaultLayout(['hist', 'serial', 'qq', 'box']).rows).toEqual([['hist'], ['serial', 'qq'], ['box']])
  })
})

describe('toggles 向后兼容', () => {
  it('旧账号 state 缺 site3d → 默认关', () => {
    expect(parseToggles({ hist: true, serial: true, qq: false, box: false })?.site3d).toBe(false)
  })
  it('site3d: true 读得回来', () => {
    expect(parseToggles({ hist: true, serial: false, qq: false, box: false, site3d: true })?.site3d).toBe(true)
  })
  it('缺 serial 仍判整个 toggles 无效（旧口径不动：残缺对象不如按默认重来）', () => {
    expect(parseToggles({ hist: true, qq: false, box: false, site3d: true })).toBeNull()
  })
})

describe('site3dView 向后兼容', () => {
  it('旧账号 state 没有 site3dView → 快照为 null（默认机位），不报错', async () => {
    const r = await loadChartMemory()
    expect(r.state.site3dView).toBeNull()
  })
})

describe('toggles 整体丢失时由布局反推（快速 F5 的真实竞态）', () => {
  it('布局里有 site3d ⇒ 反推为 true（否则默认关会把已存的 5 格裁回 4 格）', async () => {
    const r = await loadChartMemory()
    expect(r.memoryEnabled).toBe(true)
    expect(r.state.toggles).toEqual({ hist: true, serial: false, qq: false, box: true, site3d: true })
  })
})
