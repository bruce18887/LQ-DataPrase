# 3D 视角记忆 + 网格线对齐 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 3D 站点柱阵的相机视角（旋转/缩放/平移）按账号记忆、切参数/切页/刷新都保留，并把 3D 网格线调到与 2D 直方图一致的可见度（light `#dbdee4`，night 维持淡白）。

**Architecture:** 新增纯模块 `site3dView.ts` 负责视角形状、脏数据校验与从 gl 私有 `_control` 读实时相机；`site3dOption.ts` 把视角作为 option 入参、并给出 `viewControlFromView` 映射；`useChartMemory.ts` 的 `analysis_chart_state` 增加 `site3dView` 字段并以「完整已知状态」为 PUT 基底（修掉单键上报会整份冲洗的隐患）；`Site3DChart.vue` 在每次 buildOption 前读 live 相机（重渲染天然保持机位），pointerup/wheel 静置 400ms 与 keep-alive 失活/卸载时上报；token 模块新增 `gridLineColor`。

**Tech Stack:** Vue 3.5 + echarts 6.1 + echarts-gl 2.1.0 + Pinia；vitest T2（node 环境，不挂组件）；Playwright T3（Edge 项目）。

---

## 执行约定（控制器与子代理都必须遵守）

- 分支：在 `master`（已并入上一批，含 `9f2b94e` 设计稿）上新建 `feat/site3d-view-grid-20261105`，本计划所有提交都在该分支；**不 push**。
- 子代理**不得**执行任何写操作的 git 命令（add/commit/checkout/restore/stash）；提交由控制器做。
- 变异验证一律用「脚本保存字节快照 → 改 → 跑 → 写回」，禁止 `git checkout --` / `git restore`。
- 不碰 `docs/tasks/todo.md`（另一会话的未提交改动）与 `docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`（他人草稿）。
- 每个任务收尾跑一次**该任务相关**的 vitest 文件（1s 级）；全量门禁在 Task 7。
- 600 行硬闸：`Site3DChart.vue` 现 140 行、`useChartMemory.ts` 181 行，本批增量都远小于余量。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `frontend/src/pages/analysis/composables/site3dView.ts`（新，~75 行） | `Site3DView` 类型、`sanitizeSite3DView`、`readLiveView`（gl 相机 → 视角） |
| `frontend/src/pages/analysis/composables/site3dOption.ts`（改） | `SITE3D_VIEW` 换 `orthographicSize`；`defaultSite3DView`/`viewControlFromView`/`applyView`；builder 接受 `view` |
| `frontend/src/composables/useChartMemory.ts`（改） | snapshot 加 `site3dView`；`knownState` PUT 基底；`getCachedChartState()` 同步读 |
| `frontend/src/pages/analysis/components/Site3DChart.vue`（改） | 读 live→currentView；交互后保存；keep-alive/卸载冲刷；复位写默认；迟到加载应用 |
| `frontend/src/utils/echarts-tokens.ts`（改） | 两主题加 `gridLineColor`；`GRID3D_TOKEN_KEYS` 加一项；`grid3DStyle.splitLine` 改取它 |
| `frontend/test/unit/site3dView.spec.ts`（新） | 纯函数/假 control |
| `frontend/test/unit/chartMemoryFlush.spec.ts`（新） | PUT 载荷完整性（防整份冲洗） |
| `frontend/test/unit/site3dOption.spec.ts`（改） | 默认形状、`view` 入参 |
| `frontend/test/unit/echartsTokens.spec.ts`（改） | 新 token 对称/取值、splitLine 取它 |
| `frontend/test/unit/site3dWiring.spec.ts`（改） | 组件接线形状 |
| `frontend/e2e/analysis/site3d.spec.ts`（改） | 新增视角保留用例（切参数 + 刷新） |

---

## Task 1：`site3dView.ts` 纯模块

**Files:**
- Create: `frontend/src/pages/analysis/composables/site3dView.ts`
- Test: `frontend/test/unit/site3dView.spec.ts`

- [ ] **Step 1：先写失败测试**

创建 `frontend/test/unit/site3dView.spec.ts`：

```ts
/**
 * T2：3D 视角的形状校验与实时读取（specs/2026-11-05 §4）。
 *
 * 两条承重：
 * ① `orthographicSize` 存**模型值**：gl 的 Grid3DView 用 `setFromViewControlModel(model, 0)`
 *    调用（echarts-gl.js:41467），extraOpts 为假值 ⇒ baseOrthoSize=1（:39002-39016）。
 *    所以读取 = 实时值 − 1；写回由 gl 再加 1。去掉 -1 会让「记住的视角」每次重渲染缩一档。
 * ② 毒数据整份丢弃：五个量任一非有限数就返回 null（半信一半会画出怪机位）。
 */
import { describe, expect, it } from 'vitest'

import { readLiveView, sanitizeSite3DView, type Site3DView } from '../../src/pages/analysis/composables/site3dView'

const GOOD: Site3DView = { alpha: 31.5, beta: -12, distance: 260, orthographicSize: 149, center: [1, 2, 3] }

function fakeChart(control: Record<string, unknown> | null) {
  return {
    getModel: () => ({ getComponent: (name: string) => (name === 'grid3D' ? { kind: 'grid3d' } : null) }),
    getViewOfComponentModel: () => (control ? { _control: control } : {}),
  }
}

function fakeControl(over: Record<string, unknown> = {}) {
  return {
    getAlpha: () => 40,
    getBeta: () => -7,
    getDistance: () => 300,
    getOrthographicSize: () => 151,
    getCenter: () => [0.5, 1.5, 2.5],
    ...over,
  }
}

describe('sanitizeSite3DView', () => {
  it('合法对象原样返回（center 复制成新数组，不共享入参）', () => {
    const out = sanitizeSite3DView(GOOD)!
    expect(out).toEqual(GOOD)
    expect(out.center).not.toBe(GOOD.center)
  })

  it('缺字段/NaN/字符串/center 长度不对 → null', () => {
    expect(sanitizeSite3DView(null)).toBeNull()
    expect(sanitizeSite3DView(undefined)).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, alpha: undefined })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, beta: Number.NaN })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, distance: '260' })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, orthographicSize: Number.POSITIVE_INFINITY })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, center: [1, 2] })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, center: [1, 2, Number.NaN] })).toBeNull()
  })
})

describe('readLiveView', () => {
  it('从 OrbitControl 读实时机位，orthographicSize 减掉 grid3D 的 base 1', () => {
    const v = readLiveView(fakeChart(fakeControl()))!
    expect(v).toEqual({ alpha: 40, beta: -7, distance: 300, orthographicSize: 150, center: [0.5, 1.5, 2.5] })
  })

  it('实例/视图/私有字段缺失或 getter 抛错 → null（不影响出图）', () => {
    expect(readLiveView(null)).toBeNull()
    expect(readLiveView({})).toBeNull()
    expect(readLiveView(fakeChart(null))).toBeNull()
    expect(readLiveView(fakeChart(fakeControl({ getAlpha: () => { throw new Error('disposed') } })))).toBeNull()
    expect(readLiveView(fakeChart(fakeControl({ getOrthographicSize: () => Number.NaN })))).toBeNull()
  })
})
```

- [ ] **Step 2：跑测试确认红**

```bash
cd frontend && npx vitest run test/unit/site3dView.spec.ts
```
Expected：FAIL，`Cannot find module .../site3dView`。

- [ ] **Step 3：实现模块**

创建 `frontend/src/pages/analysis/composables/site3dView.ts`：

```ts
/**
 * 3D 视角的可持久化形状 + 从 gl 相机读取（specs/2026-11-05 §4）。
 *
 * 相机实时态**不在** getOption() 里：viewControl 只代表最后一次 setOption 的初值，
 * 交互只改 OrbitControl 内部状态（2026-11-05 真机实测：拖拽后 getOption 的 alpha 不变）。
 * 所以读取统一走 Grid3D 视图上的 `_control`（gl 私有字段，锁定的 2.1.0 实测；
 * 升级 gl 要重跑 site3dView.spec 与 e2e 的视角保留用例）。
 *
 * orthographicSize 存**模型值**：gl 的 setFromViewControlModel 把生效值算成
 * `model + baseOrthoSize`，而 Grid3DView 调用时 extraOpts=0 ⇒ baseOrthoSize=1
 * （echarts-gl.js:41467 与 :39002-39016）。读取减 1，写回由 gl 加 1。
 */
export interface Site3DView {
  alpha: number
  beta: number
  distance: number
  /** 模型值（生效值 = 本值 + 1，见文件头） */
  orthographicSize: number
  /** 中键平移后的观察中心 */
  center: [number, number, number]
}

/** Grid3DView 传给 setFromViewControlModel 的 baseOrthoSize（echarts-gl.js:41467） */
const ORTHO_BASE = 1

interface OrbitControlLike {
  getAlpha(): number
  getBeta(): number
  getDistance(): number
  getOrthographicSize(): number
  getCenter(): number[]
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** 账号记忆里的视角：五个量必须都是有限数，否则整份丢弃（半信一半会画出怪机位） */
export function sanitizeSite3DView(raw: unknown): Site3DView | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const c = o.center
  if (!Array.isArray(c) || c.length !== 3 || !c.every(isFiniteNumber)) return null
  if (
    !isFiniteNumber(o.alpha) ||
    !isFiniteNumber(o.beta) ||
    !isFiniteNumber(o.distance) ||
    !isFiniteNumber(o.orthographicSize)
  ) return null
  return {
    alpha: o.alpha,
    beta: o.beta,
    distance: o.distance,
    orthographicSize: o.orthographicSize,
    center: [c[0] as number, c[1] as number, c[2] as number],
  }
}

/** 从已初始化的 echarts 实例读当前机位；实例/视图/字段缺失时返回 null */
export function readLiveView(chart: unknown): Site3DView | null {
  try {
    const inst = chart as any
    const model = inst?.getModel?.()?.getComponent?.('grid3D')
    if (!model) return null
    const view = inst?.getViewOfComponentModel?.(model)
    const control = view?._control as OrbitControlLike | undefined
    if (!control) return null
    const center = control.getCenter()
    return sanitizeSite3DView({
      alpha: control.getAlpha(),
      beta: control.getBeta(),
      distance: control.getDistance(),
      orthographicSize: control.getOrthographicSize() - ORTHO_BASE,
      center: [center?.[0] ?? 0, center?.[1] ?? 0, center?.[2] ?? 0],
    })
  } catch {
    return null
  }
}
```

- [ ] **Step 4：跑测试确认绿**

```bash
cd frontend && npx vitest run test/unit/site3dView.spec.ts
```
Expected：`Tests 4 passed`。

- [ ] **Step 5：提交**

```bash
git add frontend/src/pages/analysis/composables/site3dView.ts frontend/test/unit/site3dView.spec.ts
git commit -m "feat(analysis): 3D 视角纯模块（形状校验 + 从 gl 相机读实时机位，ortho base 1）"
```

---

## Task 2：`site3dOption` 接入视角入参、默认改 `orthographicSize`

**Files:**
- Modify: `frontend/src/pages/analysis/composables/site3dOption.ts`
- Test: `frontend/test/unit/site3dOption.spec.ts`

- [ ] **Step 1：先改测试（预期红）**

`frontend/test/unit/site3dOption.spec.ts`：

1. 顶部 import 增加：

```ts
  defaultSite3DView,
  viewControlFromView,
  applyView,
```
（加在既有 `import { ... } from '../../src/pages/analysis/composables/site3dOption'` 的括号里。）

**`Site3DView` 类型从它自己的模块取**（`site3dOption` 只 import 类型、没有 re-export，写成 `import type { Site3DView } from '.../site3dOption'` 会被 `vue-tsc -b` 判 TS2724，而 vitest 的 esbuild 会静默剥掉类型、看不出问题）：

```ts
import type { Site3DView } from '../../src/pages/analysis/composables/site3dView'
```

2. `const build = ...` 的 `over` 类型加上 `view?: Site3DView`：

```ts
const build = (r: any, over: Partial<{ mode: 'clip' | 'exclude' | 'off'; rangeType: string; param: string; view: Site3DView }> = {}, isDark = false) =>
  buildSite3DOption(r, theme(isDark), { mode: 'off', rangeType: 'RDL', param: 'Kelvin_VIN', ...over })
```

3. 把 `describe('⑧ 机位常量单一来源', ...)` 里的第一条测试整段替换为：

```ts
  it('初始 viewControl 与复位目标读同一份 SITE3D_VIEW', () => {
    expect(SITE3D_VIEW).toEqual({ alpha: 28, beta: 30, distance: 245, orthographicSize: 150 })
    const vc = build(mkResult())!.grid3D.viewControl
    expect(vc.alpha).toBe(SITE3D_VIEW.alpha)
    expect(vc.beta).toBe(SITE3D_VIEW.beta)
    expect(vc.distance).toBe(SITE3D_VIEW.distance)
    expect(vc.orthographicSize).toBe(SITE3D_VIEW.orthographicSize)
    expect(vc.center).toEqual([0, 0, 0])
    expect(vc).toEqual(defaultViewControl())
  })

  it('opts.view 生效：机位逐字段来自传入视角（记忆回放）', () => {
    const v: Site3DView = { alpha: 12, beta: -34, distance: 300, orthographicSize: 88, center: [1, 2, 3] }
    const vc = build(mkResult(), { view: v })!.grid3D.viewControl
    expect(vc).toEqual(viewControlFromView(v))
    expect(vc).toMatchObject(v)
  })

  it('applyView 写任意视角、applyDefaultView 写默认（都是 merge，不碰 series）', () => {
    const calls: any[][] = []
    const chart = { setOption: (...args: any[]) => calls.push(args) }
    const v: Site3DView = { alpha: 5, beta: 6, distance: 200, orthographicSize: 90, center: [0, 1, 0] }
    applyView(chart, v)
    applyDefaultView(chart)
    expect(calls[0][0].grid3D.viewControl).toEqual(viewControlFromView(v))
    expect(calls[1][0].grid3D.viewControl).toEqual(viewControlFromView(defaultSite3DView()))
    // 只传一个参数：setOption(opt, true) 是 notMerge，会把柱数据一起换掉
    expect(calls.map((a) => a.length)).toEqual([1, 1])
    expect(calls.every((a) => a[0].series === undefined)).toBe(true)
  })
```

4. 顶部 import 增加 `applyView`（与 `applyDefaultView` 同一 import）。

- [ ] **Step 2：跑测试确认红**

```bash
cd frontend && npx vitest run test/unit/site3dOption.spec.ts
```
Expected：FAIL（`viewControlFromView` 未导出 / `SITE3D_VIEW` 形状不符 / `vc.orthographicSize` undefined）。

- [ ] **Step 3：实现**

`frontend/src/pages/analysis/composables/site3dOption.ts`：

1. 顶部 import 区加：

```ts
import type { Site3DView } from './site3dView'
```

2. `SITE3D_VIEW` 换成（保留原有注释并补一句为什么没有 zoom）：

```ts
/**
 * 默认机位：alpha 低于 25 时后排被前排整根挡住；beta 取负会把值轴甩到左后方。
 * 初始 option 与面板头「回到默认视角」共用这一份（§10 判据 ⑧）。
 * 用 `orthographicSize` 而不是 `zoom`：gl 的 grid3D 不读 zoom（它只服务 mapbox/maptalks），
 * 正交视野的旋钮是 orthographicSize；150 与「不设置时 gl 的默认值」等价（生效 151）。
 */
export const SITE3D_VIEW = { alpha: 28, beta: 30, distance: 245, orthographicSize: 150 }
```

3. `Site3DBuildOptions` 增加字段：

```ts
  /** 当前机位（账号记忆回放）；缺省用默认机位。灵敏度/投影不在可记忆范围内 */
  view?: Site3DView
```

4. 把 `defaultViewControl` 整段替换为：

```ts
/** 默认视角（SITE3D_VIEW + 居中）：初始 option、复位、复位落库共用 */
export function defaultSite3DView(): Site3DView {
  return { ...SITE3D_VIEW, center: [0, 0, 0] as [number, number, number] }
}

/** 视角 → gl 的 viewControl；投影与灵敏度是固定项，不进可记忆视角 */
export function viewControlFromView(view: Site3DView): Record<string, unknown> {
  return {
    projection: 'orthographic',
    alpha: view.alpha,
    beta: view.beta,
    distance: view.distance,
    orthographicSize: view.orthographicSize,
    center: view.center,
    rotateSensitivity: 0.8,
    zoomSensitivity: 0.7,
  }
}

/** 正交 + 默认机位：初始 option 与复位按钮的共同来源 */
export function defaultViewControl(): Record<string, unknown> {
  return viewControlFromView(defaultSite3DView())
}

/** 应用任意视角（记忆迟到加载/复位共用）；merge 写，不碰 series */
export function applyView(
  chart: { setOption: (...args: any[]) => unknown } | null | undefined,
  view: Site3DView,
): void {
  if (!chart) return
  chart.setOption({ grid3D: { viewControl: viewControlFromView(view) } })
}

/** 复位：合并写默认 viewControl（原型 :256 的同形写法；notMerge 会把柱数据一起换掉） */
export function applyDefaultView(
  chart: { setOption: (...args: any[]) => unknown } | null | undefined,
): void {
  applyView(chart, defaultSite3DView())
}
```

5. `grid3D.viewControl` 一行改为：

```ts
      viewControl: viewControlFromView(opts.view ?? defaultSite3DView()),
```

6. 在 `rows` 生成处（`if (!(v > 0)) return`）的既有注释末尾补一句（spec §3 的动画结论）：

```
      // 副作用：柱数 = 非零 (bin, Site) 数，随参数变；gl 的顶点动画只在
      // 「前后柱数相同」时播放（echarts-gl.js 的 updateVertexAnimation），
      // 所以有时有动画有时没有。这是有意保留的行为，别为动画补 0 高柱。
```

- [ ] **Step 4：跑测试确认绿**

```bash
cd frontend && npx vitest run test/unit/site3dOption.spec.ts test/unit/site3dView.spec.ts
```
Expected：两个文件全绿（`site3dOption.spec.ts` 现 32 例 + 新增 2 例）。

- [ ] **Step 5：提交**

```bash
git add frontend/src/pages/analysis/composables/site3dOption.ts frontend/test/unit/site3dOption.spec.ts
git commit -m "feat(analysis): 3D option 接受账号视角入参，默认机位改用 orthographicSize（zoom 是死配置）"
```

---

## Task 3：记忆载荷加 `site3dView` + PUT 基底防冲洗

**Files:**
- Modify: `frontend/src/composables/useChartMemory.ts`
- Test: `frontend/test/unit/chartMemoryFlush.spec.ts`（新）、`frontend/test/unit/chartLayout.spec.ts`（增补）

- [ ] **Step 1：先写失败测试（新文件）**

创建 `frontend/test/unit/chartMemoryFlush.spec.ts`：

```ts
/**
 * T2：`analysis_chart_state` 的 PUT 载荷必须**完整**（specs/2026-11-05 §4.3）。
 *
 * 背景：后端该字段是整份 JSON 替换（apps/accounts/serializers.py，partial=True 只表示
 * 字段可选，不表示 JSON 内部合并）。旧实现`latest`只累积本次防抖窗口内的键，
 * 于是「只上报 site3dView」会把账号里的 layout/toggles 冲掉——视角是高频写入，
 * 这条窄缝会被放大成「记住视角 = 布局丢光」。
 * 判据：任何单键上报，PUT 的 analysis_chart_state 仍是**已知的 layout+toggles + 新键**；
 * 且「加载完成前就排队」与「PUT 失败」两条现实路径都不许退化成单键载荷。
 */
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const holder = vi.hoisted(() => {
  // node 环境没有 document，而 useChartMemory 只在导入时按 `typeof document` 注册
  // pagehide ⇒ 桩必须早于模块求值（vi.hoisted 先于 import 执行），否则那条通道
  // 在本文件里根本不存在，pagehide 用例会变成空跑。
  const listeners: Record<string, () => void> = {}
  ;(globalThis as any).document = {
    // Vue runtime-dom 导入时就会 doc.createElement('template')，只桩 addEventListener 会崩
    createElement: () => ({}),
    addEventListener: (type: string, fn: () => void) => {
      listeners[type] = fn
    },
  }
  return { raw: null as any, saves: [] as any[], failNext: false, listeners }
})

vi.mock('../../src/stores/userSettings', () => ({
  useUserSettingsStore: () => ({
    get raw() { return holder.raw },
    ensure: () => Promise.resolve(),
    save: (p: any) => {
      holder.saves.push(p)
      if (holder.failNext) {
        holder.failNext = false
        return Promise.reject(new Error('network down'))
      }
      return Promise.resolve()
    },
    saveKeepalive: (p: any) => { holder.saves.push(p) },
  }),
}))

// 本文件不量本机布局落盘；不 mock 会撞上真 safeStorage 的 DOMException 噪声
vi.mock('../../src/utils/safeStorage', () => ({
  safeGetItem: () => null,
  safeSetItem: () => {},
  safeRemoveItem: () => {},
}))

import {
  clearChartMemoryState,
  getCachedChartState,
  loadChartMemory,
  resetChartMemoryCache,
  saveChartState,
  setChartMemoryEnabled,
} from '../../src/composables/useChartMemory'
import type { DockLayout } from '../../src/pages/analysis/composables/useChartDock'

// 账号里存的是带 v 的存档形状（isValidLayout 要求 v===1）；DockLayout 类型本身不含 v
const LAYOUT = {
  v: 1,
  rows: [['hist'], ['box', 'site3d']],
  rowPcts: [70, 30],
  colPcts: [[100], [50, 50]],
  bodyH: 900,
} as unknown as DockLayout
const TOGGLES = { hist: true, serial: false, qq: false, box: true, site3d: true }
const VIEW = { alpha: 33, beta: -8, distance: 260, orthographicSize: 149, center: [0, 0, 0] }

beforeEach(() => {
  resetChartMemoryCache()
  holder.saves = []
  holder.failNext = false
  vi.useFakeTimers()
  holder.raw = {
    analysis_chart_memory: true,
    analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW },
  }
})

afterEach(() => {
  vi.useRealTimers()
  resetChartMemoryCache()
})

afterAll(() => {
  // 文件内隔离之外再收一次，别把只有 createElement 的假 document 留给后续用例
  delete (globalThis as any).document
})

describe('analysis_chart_state 的读取与整体性', () => {
  it('解析出 site3dView，并可从同步入口读到同一份快照', async () => {
    const r = await loadChartMemory()
    expect(r.state.site3dView).toEqual(VIEW)
    expect(getCachedChartState()).toEqual({ layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW })
  })

  it('site3dView 坏值 → null，其余字段照常', async () => {
    holder.raw.analysis_chart_state.site3dView = { alpha: Number.NaN }
    const r = await loadChartMemory()
    expect(r.state.site3dView).toBeNull()
    expect(r.state.layout).toEqual(LAYOUT)
    expect(r.state.toggles).toEqual(TOGGLES)
  })

  it('记忆开关关闭时同步快照为 null（重挂载的图回默认机位，不套旧账号态）', async () => {
    holder.raw.analysis_chart_memory = false
    const r = await loadChartMemory()
    expect(r.memoryEnabled).toBe(false)
    expect(getCachedChartState()).toBeNull()
  })

  it('视角单键上报：PUT 仍携带加载时的 layout+toggles（防整份冲洗）', async () => {
    await loadChartMemory()
    const next = { ...VIEW, alpha: 40 }
    saveChartState({ site3dView: next })
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: next },
    })
  })

  it('视角上报后同步快照立即更新（dock 勾掉再勾回不闪回旧机位）', async () => {
    await loadChartMemory()
    const next = { ...VIEW, alpha: 44 }
    saveChartState({ site3dView: next })
    expect(getCachedChartState()?.site3dView).toEqual(next)
  })

  it('布局上报同样立即反映到同步快照（快照是整份记忆，不是只有视角）', async () => {
    await loadChartMemory()
    const layout = { ...LAYOUT, bodyH: 700 }
    saveChartState({ layout })
    expect(getCachedChartState()?.layout).toEqual(layout)
  })

  it('加载完成前的上报：加载后冲刷仍带 layout+toggles', async () => {
    saveChartState({ site3dView: { ...VIEW, alpha: 45 } }) // memoryEnabled 仍为 null
    expect(holder.saves).toHaveLength(0)
    await loadChartMemory()
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, alpha: 45 } },
    })
    // 载荷合并的同时快照也要跟上：否则重挂载会短暂读回加载时的旧视角
    expect(getCachedChartState()?.site3dView).toEqual({ ...VIEW, alpha: 45 })
  })

  it('PUT 失败不丢基底：下一次冲刷仍是完整载荷', async () => {
    await loadChartMemory()
    holder.failNext = true
    saveChartState({ site3dView: { ...VIEW, alpha: 41 } })
    vi.advanceTimersByTime(800)
    saveChartState({ site3dView: { ...VIEW, alpha: 42 } })
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(2)
    expect(holder.saves[1]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, alpha: 42 } },
    })
  })

  it('pagehide 抢在防抖前冲刷：加载前排队的改动 + 基底一起发', async () => {
    // 加载前排队的 latest 只有视角；加载成功只补 knownState 并排防抖，不回填 latest。
    // 用户此刻关页 ⇒ pagehide 必须自己并基底，否则 keepalive 也是整份替换、布局/勾选被冲掉。
    saveChartState({ site3dView: { ...VIEW, beta: -12 } })
    await loadChartMemory()
    holder.listeners.pagehide?.()
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, beta: -12 } },
    })
    vi.advanceTimersByTime(800) // 处理器已清掉防抖计时器，不许再发第二次
    expect(holder.saves).toHaveLength(1)
  })

  it('会话内重新开启记忆：丢弃关闭/失败时的解析 memo，下次 load 重取', async () => {
    holder.raw.analysis_chart_memory = false
    await loadChartMemory()
    expect(getCachedChartState()).toBeNull()
    holder.raw = {
      analysis_chart_memory: true,
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW },
    }
    setChartMemoryEnabled(true)
    const r = await loadChartMemory()
    expect(r.memoryEnabled).toBe(true)
    expect(getCachedChartState()?.site3dView).toEqual(VIEW)
  })

  it('拉取失败（raw=null）：快照清空、开关记为未知，不把旧快照当当前态', async () => {
    await loadChartMemory()
    resetChartMemoryCache()
    holder.raw = null
    const r = await loadChartMemory()
    expect(r.fetchFailed).toBe(true)
    expect(r.memoryEnabled).toBeNull()
    expect(getCachedChartState()).toBeNull()
  })

  it('清空会作废解析 memo：下次 load 重新读服务端而不是回放旧结果', async () => {
    await loadChartMemory()
    await clearChartMemoryState()
    expect(getCachedChartState()).toBeNull()
    const fresh = { ...VIEW, alpha: 50 }
    holder.raw = { analysis_chart_memory: true, analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: fresh } }
    const r = await loadChartMemory()
    expect(r.state.site3dView).toEqual(fresh)
    expect(getCachedChartState()?.site3dView).toEqual(fresh)
  })
})
```

- [ ] **Step 2：跑测试确认红**

```bash
cd frontend && npx vitest run test/unit/chartMemoryFlush.spec.ts
```
Expected：FAIL（`getCachedChartState` 未导出 / `site3dView` 不在快照里 / 单键上报 PUT 缺 layout）。

- [ ] **Step 3：实现**

`frontend/src/composables/useChartMemory.ts` 按下列改动：

1. import 区加：

```ts
import { sanitizeSite3DView, type Site3DView } from '../pages/analysis/composables/site3dView'
```

2. 类型区：

```ts
export interface ChartMemorySnapshot {
  layout: DockLayout | null
  toggles: ChartToggles | null
  site3dView: Site3DView | null
}

/** 可上报/可落库的记忆键（省略 = 本次没改） */
type MemoryPatch = { layout?: DockLayout; toggles?: ChartToggles; site3dView?: Site3DView }
```

3. 模块态（替换 `latest` 那一行）：

```ts
let latest: MemoryPatch | null = null
// 服务端最近一次加载/确认的完整状态：每次 PUT 都以它为基底，避免「只带一个键」
// 把整份 JSON 覆盖掉（视角是高频写入，这条窄缝会把布局/勾选冲没）
let knownState: MemoryPatch = {}
// 已解析快照的同步读面（Site3DChart 首帧就要拿到视角，等不了 promise）
let cachedState: ChartMemorySnapshot | null = null
```

4. `parseState` 替换为：

```ts
function parseState(raw: unknown): ChartMemorySnapshot {
  if (!raw || typeof raw !== 'object') return { layout: null, toggles: null, site3dView: null }
  const o = raw as Record<string, unknown>
  return {
    layout: isValidLayout(o.layout) ? o.layout : null,
    toggles: parseToggles(o.toggles),
    site3dView: sanitizeSite3DView(o.site3dView),
  }
}

function pickKnown(state: ChartMemorySnapshot): MemoryPatch {
  return {
    ...(state.layout ? { layout: state.layout } : {}),
    ...(state.toggles ? { toggles: state.toggles } : {}),
    ...(state.site3dView ? { site3dView: state.site3dView } : {}),
  }
}

/** 同步读最近一次已解析的账号记忆；未加载/已清空时 null */
export function getCachedChartState(): ChartMemorySnapshot | null {
  return cachedState
}
```

5. `loadChartMemory` 内：

- fetchFailed 分支加两行：

```ts
        memoryEnabled = null
        latest = null
        knownState = {}
        cachedState = null
        return { memoryEnabled, fetchFailed: true, state: { layout: null, toggles: null, site3dView: null } }
```

- 成功分支在 `const state = parseState(...)` 之后（含 toggles 反推之后、`if (memoryEnabled && latest)` 之前）加：

```ts
      knownState = pickKnown(state)
      // 开关关闭时不暴露同步快照：重挂载的图应回默认机位，不能把账号里的旧视角当「当前」
      cachedState = memoryEnabled ? state : null
```

6. `flush` 替换为：

```ts
function flush() {
  timer = null
  if (memoryEnabled !== true || !latest) return
  // 发送时才合并基底：loadChartMemory 解析前就排队的上报（用户进页立刻点勾选）
  // 当时 knownState 还是空的，只靠 saveChartState 里那次合并会漏掉布局/勾选。
  const payload = { ...knownState, ...latest }
  latest = null
  // 乐观记账：请求失败只会让下次 PUT 重复携带（同一客户端不丢数据）
  knownState = { ...payload }
  if (cachedState) cachedState = { ...cachedState, ...payload }
  useUserSettingsStore().save({ analysis_chart_state: { ...payload } }).catch(() => {
    /* 后台静默同步：失败不打扰用户 */
  })
}
```

7. `saveChartState` 替换为：

```ts
/** layout / toggles / 视角变化上报（内部判开关 + 防抖合并为一次完整 PUT） */
export function saveChartState(patch: MemoryPatch) {
  if (memoryEnabled === false) return // 用户已关：不积累、不发送
  latest = { ...knownState, ...(latest ?? {}), ...patch }
  // 同步快照跟着上报一起走：dock 勾掉再勾回会重建图组件，重挂载只读得到
  // cachedState，不同步就会在防抖窗口内闪回加载时的旧视角/布局。
  if (cachedState) cachedState = { ...cachedState, ...patch }
  if (memoryEnabled === true) scheduleFlush()
}
```

8. `clearChartMemoryState` 内 `latest = null` 后加：

```ts
  knownState = {}
  cachedState = null
  // 作废解析 memo：留着会把清空前的旧结果原样喂给下一次 load（恢复默认后重进分析页
  // 仍套用旧布局/勾选）。
  loadPromise = null
```

9. `resetChartMemoryCache` 内 `latest = null` 后加：

```ts
  knownState = {}
  cachedState = null
```

10. `pagehide` 处理器内把 `const payload = latest` 替换为：

```ts
    // 与 flush() 同口径：PUT 是整份替换，未加载完就排队的改动必须带上基底
    const payload = { ...knownState, ...latest }
    knownState = { ...payload }
```

11. `setChartMemoryEnabled` 替换为：

```ts
export function setChartMemoryEnabled(enabled: boolean) {
  memoryEnabled = enabled
  // 重开必须丢弃旧解析结果：memo 里可能是「关」或拉取失败时的快照，knownState 也是空的，
  // 不重取就会让下一次单键上报退回整份冲洗。
  if (enabled) loadPromise = null
}
```

- [ ] **Step 4：跑测试确认绿**

```bash
cd frontend && npx vitest run test/unit/chartMemoryFlush.spec.ts test/unit/chartLayout.spec.ts test/unit/chartToggles.spec.ts
```
Expected：三个文件全绿（`chartLayout.spec.ts` 的既有存档/勾选用例不受影响）。

- [ ] **Step 5：补一条向后兼容断言（沿用既有文件）**

`frontend/test/unit/chartLayout.spec.ts` 的 `describe('toggles 向后兼容', ...)` 之后追加：

```ts
describe('site3dView 向后兼容', () => {
  it('旧账号 state 没有 site3dView → 快照为 null（默认机位），不报错', async () => {
    const r = await loadChartMemory()
    expect(r.state.site3dView).toBeNull()
  })
})
```

再跑一次：

```bash
cd frontend && npx vitest run test/unit/chartLayout.spec.ts
```
Expected：绿（该文件的 mock store 里没有 site3dView，parseState 返回 null）。

- [ ] **Step 6：提交**

```bash
git add frontend/src/composables/useChartMemory.ts frontend/test/unit/chartMemoryFlush.spec.ts frontend/test/unit/chartLayout.spec.ts
git commit -m "feat(analysis): 图表记忆加 site3dView，并以完整已知状态为 PUT 基底（防单键冲洗布局/勾选）"
```

---

## Task 4：`gridLineColor` token 与 3D 网格线

**Files:**
- Modify: `frontend/src/utils/echarts-tokens.ts`
- Test: `frontend/test/unit/echartsTokens.spec.ts`

- [ ] **Step 1：先改测试（预期红）**

`frontend/test/unit/echartsTokens.spec.ts` 的 `describe('grid3DStyle — 逐项取 token，不写死', ...)` 内：

1. 在「颜色确实随主题变化」那条里加两行（放在 axisLine 断言之后）：

```ts
    expect(light.splitLine.lineStyle.color).toBe(ECHARTS_COLORS_LIGHT.gridLineColor)
    expect(night.splitLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.gridLineColor)
```

2. 追加一条独立测试：

```ts
  it('网格线对齐 2D 直方图：light #dbdee4（ECharts neutral15），night 保持淡白', () => {
    // ECharts 6 默认 axisSplitLine = tokens.color.neutral15 = #dbdee4；
    // 直方图没有覆写 splitLine，所以它在两个主题下画的就是这个灰。
    expect(ECHARTS_COLORS_LIGHT.gridLineColor).toBe('#dbdee4')
    expect(ECHARTS_COLORS_NIGHT.gridLineColor).toBe('rgba(255, 255, 255, 0.04)')
  })
```

- [ ] **Step 2：跑测试确认红**

```bash
cd frontend && npx vitest run test/unit/echartsTokens.spec.ts
```
Expected：FAIL（`gridLineColor` undefined）。

- [ ] **Step 3：实现**

`frontend/src/utils/echarts-tokens.ts`：

1. `EChartsColors` 接口在 `splitLineColor: string` 之后加：

```ts
  /** 3D 网格线（对齐 2D 直方图的 ECharts 默认网格色） */
  gridLineColor: string
```

2. `ECHARTS_COLORS_NIGHT` 在 `splitLineColor: 'rgba(255, 255, 255, 0.04)',` 之后加：

```ts
  gridLineColor: 'rgba(255, 255, 255, 0.04)',
```

3. `ECHARTS_COLORS_LIGHT` 在 `splitLineColor: '#eef0f3',` 之后加：

```ts
  // ECharts 6 默认网格线（neutral15）——直方图实际画的就是它，3D 跟它对齐
  gridLineColor: '#dbdee4',
```

4. `GRID3D_TOKEN_KEYS` 改为：

```ts
export const GRID3D_TOKEN_KEYS = [
  'textColor', 'axisLabelColor', 'splitLineColor', 'gridLineColor',
  'tooltipBg', 'tooltipBorder', 'tooltipText',
] as const
```

5. `grid3DStyle` 里 splitLine 一行改为（注释同步）：

```ts
    // 网格线：2D 直方图用的是 ECharts 默认 #dbdee4（见 token 注释）；
    // 3D 之前用 splitLineColor（#eef0f3）在白底上几乎看不见（用户 2026-11-05 反馈）。
    splitLine: { show: true, lineStyle: { color: colors.gridLineColor, width: 1 } },
```

- [ ] **Step 4：跑测试确认绿**

```bash
cd frontend && npx vitest run test/unit/echartsTokens.spec.ts test/unit/site3dOption.spec.ts
```
Expected：绿（`site3dOption.spec.ts` 里 theme() 走同一份 token，不写死颜色）。

- [ ] **Step 5：提交**

```bash
git add frontend/src/utils/echarts-tokens.ts frontend/test/unit/echartsTokens.spec.ts
git commit -m "feat(theme): 3D 网格线取 gridLineColor（light 对齐直方图 #dbdee4，night 维持淡白）"
```

---

## Task 5：`Site3DChart.vue` 接线（读 live / 保存 / 复位 / 迟到加载）

**Files:**
- Modify: `frontend/src/pages/analysis/components/Site3DChart.vue`
- Test: `frontend/test/unit/site3dWiring.spec.ts`

- [ ] **Step 1：先加接线绊线（预期红）**

`frontend/test/unit/site3dWiring.spec.ts` 末尾追加：

```ts
describe('Site3DChart.vue 的视角记忆接线（specs/2026-11-05 §4.2）', () => {
  const code = codeOf(read('pages/analysis/components/Site3DChart.vue'))

  it('buildOption 先读实时相机，实时值优先于 currentView 交给 builder', () => {
    expect(code).toMatch(/readLiveView\(/)
    expect(code).toMatch(/view:\s*live \?\? currentView\.value/)
  })

  it('首帧走同步缓存，异步加载只做迟到补写', () => {
    expect(code).toContain('getCachedChartState(')
    expect(code).toMatch(/loadChartMemory\(\)/)
    expect(code).toMatch(/applyView\(/)
  })

  it('迟到加载有显式守卫：读实时机位 ≠ 用户已改；未动过的机位不落库', () => {
    expect(code).toMatch(/let viewDecided = false/)
    expect(code).toMatch(/let userTouched = false/)
    expect(code).toMatch(/if \(hadCachedView \|\| viewDecided\) return/)
    expect(code).toMatch(/if \(!userTouched\) return/)
  })

  it('只有镜头真的动了才记用户决定（单击 tooltip 不算）', () => {
    expect(code).toMatch(/isSameSite3DView\(live, currentView\.value\)/)
    // 注释已被 codeOf 剥掉，切片终点要用代码锚点（下一个 watch 调用）
    const start = code.indexOf('function onInteractionSettled')
    const handler = code.slice(start, code.indexOf('watch(', start))
    expect(handler).toMatch(/viewDecided = true/)
    expect(handler).not.toMatch(/saveChartState/)
  })

  it('buildOption 同步 currentView 回退值（实例被重建时不会拿过期机位）', () => {
    expect(code).toMatch(/if \(live\) currentView\.value = live/)
  })

  it('交互结束后保存：pointerup + wheel 静置，keep-alive 失活/卸载立即冲刷', () => {
    expect(code).toContain("addEventListener('pointerup'")
    expect(code).toContain("addEventListener('wheel', onWheel)")
    expect(code).toMatch(/onDeactivated\(/)
    expect(code).toMatch(/onBeforeUnmount\(/)
    expect(code).toMatch(/saveChartState\(\s*\{\s*site3dView/)
  })

  it('滚轮不按事件当刻的相机相等来跳过（阻尼在后续帧才落地）', () => {
    const start = code.indexOf('function onWheel')
    const wheel = code.slice(start, code.indexOf('watch(', start))
    expect(wheel).toMatch(/viewDecided = true/)
    expect(wheel).toMatch(/scheduleSettle\(\)/)
    // 事件当刻 getOrthographicSize 还没变；这里若比较相等，单次滚轮永远不落库
    expect(wheel).not.toMatch(/isSameSite3DView/)
  })

  it('复位同时落库默认视角（否则下一次重渲染被旧视角拉回去）', () => {
    expect(code).toContain('defaultSite3DView()')
    expect(code).toMatch(/applyDefaultView\(/)
  })

  it('视角只走账号记忆，不直接碰 localStorage（单一事实来源）', () => {
    expect(code).not.toContain('localStorage')
  })
})
```

- [ ] **Step 2：跑测试确认红**

```bash
cd frontend && npx vitest run test/unit/site3dWiring.spec.ts
```
Expected：FAIL（readLiveView / getCachedChartState / addEventListener 均不存在）。

- [ ] **Step 3：实现组件**

`frontend/src/pages/analysis/components/Site3DChart.vue` 的 `<script setup>` 按下面整段替换（模板与 `<style>` 不动）：

```ts
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
// 副作用式注册：echarts-gl 只有被 import 进来才会把 bar3D/grid3D 注册到同一个 echarts
// 实例上。**少了这一行，option 里写 `type: 'bar3D'` 会静默画不出任何东西**（容器在、
// canvas 在、系列不存在）。必须是**静态**副作用导入：实测 `import('echarts-gl')`/
// `await import('echarts-gl')` 这种动态形态会被 vue-tsc 判 TS7016（该包无 .d.ts，
// 动态导入要推返回值类型），而静态 `import 'x'` 不消费绑定所以干净。
// 本组件自身已经是 defineAsyncComponent 的异步块 ⇒ 这行天然落在同一异步 chunk 里，
// 冷启动入口不会加载它（spec §2「冷启动字节不变」）。
import 'echarts-gl'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import {
  applyDefaultView,
  applyView,
  buildSite3DOption,
  defaultSite3DView,
  type Site3DTheme,
} from '../composables/site3dOption'
import { isSameSite3DView, readLiveView, type Site3DView } from '../composables/site3dView'
import {
  getCachedChartState,
  isMemoryEnabled,
  loadChartMemory,
  saveChartState,
} from '../../../composables/useChartMemory'
import type { OutlierMode } from '../composables/histogramBins'

const props = defineProps<{
  /** histogram 响应的单参数结果（与 HistogramChart 同一份 histResult） */
  result: any
  param: string
  outlierHandling: OutlierMode
  rangeType: string
  /** 面板头图标每点一次 +1：复位走 props-down，不靠 defineExpose（异步组件下 ref 层数不确定） */
  resetEpoch: number
}>()

// 模块级探测结果的 setup 别名（模板只认 setup 绑定；探测本体见上方普通 <script> 块）
const webglAvailable = webglProbe

const { colors, isDark, grid3DTheme } = useEChartsTheme()

const hasSites = computed(() => Object.keys(props.result?.site_histograms ?? {}).length > 0)
const binCount = computed(() => props.result?.bin_centers?.length ?? 0)
const siteCount = computed(() => Object.keys(props.result?.site_histograms ?? {}).length)

/**
 * 当前机位（specs/2026-11-05 §4）：同步读账号记忆缓存；没有就等 loadChartMemory 迟到补。
 * 记忆关闭（用户主动关）时不读不写，等价于「始终默认机位」。
 */
const currentView = ref<Site3DView | null>(
  isMemoryEnabled() === false ? null : (getCachedChartState()?.site3dView ?? null),
)
// 首帧是否已带账号视角：有就不必再被迟到加载「补」一次
const hadCachedView = currentView.value !== null
// 用户（含复位）是否已定过视角：迟到加载不许覆盖刚调好的机位
let viewDecided = false
// 是否有尚未落库的用户改动：没动过的默认机位不许在切页/卸载时当成改动写账号
let userTouched = false

function buildOption() {
  // 重渲染（切参数/切主题/keep-alive 恢复）**之前**先把真实相机读回来，直接带进新
  // option —— 不依赖 reset 事件或任何时序。读不到（实例尚未创建）才用 currentView。
  const live = readLiveView(chartInstance.value)
  // 同步回退值：实例被重建时 buildOption 读不到 live，不能拿过期机位把用户拉回去。
  // （这不等于「用户已定过视角」——迟到加载的守卫用的是显式标记。）
  if (live) currentView.value = live
  const theme: Site3DTheme = { isDark: isDark.value, colors: colors.value, grid3D: grid3DTheme.value }
  // null（无 Site 列 / 空网格）不该走到这里：模板那两条 v-if 已经把容器挡住了
  return buildSite3DOption(props.result, theme, {
    mode: props.outlierHandling,
    rangeType: props.rangeType,
    param: props.param,
    view: live ?? currentView.value ?? undefined,
  }) ?? {}
}

// 渲染器恒为 canvas：gl 只吃 canvas（不传第 4 参时全局默认是 svg，会被 useChart
// 的 ensureRenderer 判成「渲染器不符」反复 dispose 重建）。主题切换不必自己挂——
// useChart 已 watch themeStore.currentTheme 重渲染。
const { chartRef, chartInstance } = useChart(
  buildOption,
  [() => props.result, () => props.outlierHandling, () => props.rangeType, () => props.param],
  'chartRef',
  () => 'canvas',
)
void chartRef // 绑模板 <div ref="chartRef">（noUnusedLocals 需要显式消费一次）

/** 读一次实时相机并落账号记忆（防抖在记忆模块内，这里只管 400ms 静置） */
let settleTimer: ReturnType<typeof setTimeout> | null = null
function flushView() {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  const live = readLiveView(chartInstance.value)
  if (!live) return
  const prev = currentView.value
  currentView.value = live
  if (!userTouched) return // 没动过：已加载的机位（或默认机位）不该被当成用户改动落库
  userTouched = false
  // 静置后再比一次：滚轮在事件当刻还没落到相机上，只有这里才能判出真变化
  if (prev && isSameSite3DView(prev, live)) return
  saveChartState({ site3dView: live })
}
function scheduleSettle() {
  if (settleTimer) clearTimeout(settleTimer)
  settleTimer = setTimeout(flushView, 400)
}
function onInteractionSettled() {
  const live = readLiveView(chartInstance.value)
  if (!live) return
  // 单击/tooltip 也会来 pointerup：机位没动就不算用户决定——否则会挡住迟到加载，
  // 还会把未动过的默认机位写进账号。
  if (currentView.value && isSameSite3DView(live, currentView.value)) return
  userTouched = true
  viewDecided = true
  scheduleSettle()
}
function onWheel() {
  // 滚轮只改 gl 的 `_zoomSpeed`，阻尼在后续帧才落到相机：事件当刻读不出变化，
  // 不能按「与 currentView 相等」跳过，否则单次滚轮永远不落库。
  viewDecided = true
  userTouched = true
  scheduleSettle()
}

// 容器可能被 v-if 换掉（有/无 Site、WebGL 分支），绑在 ref 上而不是 onMounted 一次
watch(
  chartRef,
  (el, old) => {
    old?.removeEventListener('pointerup', onInteractionSettled)
    old?.removeEventListener('wheel', onWheel)
    el?.addEventListener('pointerup', onInteractionSettled)
    el?.addEventListener('wheel', onWheel)
  },
  { flush: 'post' },
)

// keep-alive 切页/组件销毁：立即冲刷最后一段机位（实例此时还在，可读）
onDeactivated(flushView)
onBeforeUnmount(() => {
  chartRef.value?.removeEventListener('pointerup', onInteractionSettled)
  chartRef.value?.removeEventListener('wheel', onWheel)
  flushView()
})

// 记忆首帧没赶上（少见：进页时设置还没取到）：迟到补写一次。
// 用显式标记判「要不要补」——实时机位在重渲染时也会被读，但那不是用户的决定。
loadChartMemory().then((r) => {
  if (r.memoryEnabled === false || !r.state.site3dView) return
  if (hadCachedView || viewDecided) return
  currentView.value = r.state.site3dView
  applyView(chartInstance.value, r.state.site3dView)
}).catch(() => { /* 记忆拿不到就走默认机位 */ })

// 合并式复位：写默认机位；同时更新 currentView 与账号记忆，
// 否则下一次重渲染（切参数/切主题）会按旧视角把刚复位的图拉回去。
watch(() => props.resetEpoch, () => {
  // 防抖窗口里残留的拖拽可能落在 animateTo 中途，先取消再复位
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  userTouched = false
  viewDecided = true
  applyDefaultView(chartInstance.value)
  currentView.value = defaultSite3DView()
  saveChartState({ site3dView: defaultSite3DView() })
})
```

> `buildOption` 里引用 `chartInstance`（声明在后面的 `useChart` 返回值里）是安全的：`useChart` 只在 `onMounted`/`nextTick` 之后才调用它，不会在 setup 同步体里触发 TDZ。以后若给 `useChart` 加「同步首渲染」，这里要改成先声明实例 ref。
>
> 复审补充：本任务同时给 `site3dView.ts` 增加 `isSameSite3DView(a, b)`（五个量按 `VIEW_EPS=0.01` 判等）
> 与 `site3dView.spec.ts` 的两条 T2 用例；`pointerup` 在单击 tooltip 时也会触发，不比较机位就会
> 把「没动过」当成用户决定（挡住迟到加载 + 把默认机位写进账号）。

- [ ] **Step 4：跑接线测试与类型**

```bash
cd frontend && npx vitest run test/unit/site3dWiring.spec.ts test/unit/site3dView.spec.ts test/unit/site3dOption.spec.ts
npx vue-tsc -p tsconfig.app.json --noEmit
```
Expected：vitest 全绿；tsc 无输出。

- [ ] **Step 5：提交**

```bash
git add frontend/src/pages/analysis/components/Site3DChart.vue frontend/test/unit/site3dWiring.spec.ts
git commit -m "feat(analysis): 3D 图读实时机位并在重渲染时带回，交互静置/切页/卸载落账号记忆，复位写默认"
```

---

## Task 6：e2e 视角保留用例 + 真机视觉核对

**Files:**
- Modify: `frontend/e2e/analysis/site3d.spec.ts`

- [ ] **Step 1：写用例**

在 `frontend/e2e/analysis/site3d.spec.ts` 的 `test.describe` 内追加（import 区补 `listParams`）：

```ts
/**
 * 视角记忆（specs/2026-11-05 §4）：拖拽 → 切参数 → 刷新，机位都要保留。
 * 落库链路是 400ms 静置 + 800ms 防抖，所以等**含 site3dView 的 PUT**而不是固定 sleep。
 */
test('视角在切参数与刷新后保持', async ({ page }) => {
  await enter3D(page)
  const readView = () =>
    page.evaluate((sel) => {
      const dom = document.querySelector(sel) as any
      const inst = dom?.__echartsInstance__
      const view = inst?.getViewOfComponentModel?.(inst.getModel().getComponent('grid3D'))
      const c = view?._control
      return c
        ? { alpha: c.getAlpha(), beta: c.getBeta(), distance: c.getDistance(), ortho: c.getOrthographicSize() }
        : null
    }, HOST)

  // 先注册「带 site3dView 的 PUT」监听（切勾选也会有 PUT，不能拿第一个 PUT 当视角落库）
  const viewPut = page.waitForResponse(
    (r) =>
      r.url().includes('/auth/settings/') &&
      r.request().method() === 'PUT' &&
      (r.request().postData() || '').includes('site3dView'),
    { timeout: 20_000 },
  )

  const host = page.locator(HOST)
  await host.scrollIntoViewIfNeeded()
  const bb = (await host.boundingBox())!
  const cx = bb.x + bb.width / 2
  const cy = bb.y + bb.height / 2
  const before = (await readView())!
  await page.mouse.move(cx, cy)
  await page.mouse.down()
  await page.mouse.move(cx + 140, cy - 60, { steps: 12 })
  await page.mouse.up()
  await page.waitForTimeout(800) // damping 余量
  const rotated = (await readView())!
  expect(Math.abs(rotated.alpha - before.alpha), '拖拽应改变机位').toBeGreaterThan(1)

  await viewPut // 视角已落库

  // 切到另一个参数：重渲染必须带着同一机位
  const params = await listParams(page)
  const next = params.find((p) => p !== 'Vth' && p !== 'Vth_Post') ?? params[1]
  await selectParam(page, next)
  await waitLoadingGone(page.locator(SINGLE))
  await page.waitForTimeout(1200)
  const afterSwitch = (await readView())!
  expect(afterSwitch.alpha).toBeCloseTo(rotated.alpha, 0)
  expect(afterSwitch.beta).toBeCloseTo(rotated.beta, 0)

  // 刷新：账号记忆里应还是这个机位
  await page.reload()
  await enter3D(page)
  await page.waitForTimeout(1200)
  const afterReload = (await readView())!
  expect(afterReload.alpha).toBeCloseTo(rotated.alpha, 0)
  expect(afterReload.beta).toBeCloseTo(rotated.beta, 0)

  // 收尾：复位并等落库，别把旋转后的视角留给后续用例/手工检查
  const resetPut = page.waitForResponse(
    (r) =>
      r.url().includes('/auth/settings/') &&
      r.request().method() === 'PUT' &&
      (r.request().postData() || '').includes('site3dView'),
    { timeout: 20_000 },
  )
  await page.getByLabel('回到默认视角').click()
  await resetPut
  await ensureChartToggles(page, { site3d: false })
})
```

同时把 import 行改为：

```ts
import { selectAnalysisFile, selectParam, ensureChartToggles, listParams } from '../helpers/params'
```

- [ ] **Step 2：e2e 类型 + 单跑**

```bash
cd frontend && npm run lint:e2e
npx playwright test analysis/site3d.spec.ts --project=P1 --workers=1 > ../tasks/3d-site3d-view/e2e-site3d.log 2>&1
grep -aE "passed|failed|Error" ../tasks/3d-site3d-view/e2e-site3d.log | tail -8
```
（先 `mkdir -p ../tasks/3d-site3d-view`。）
Expected：`3 passed`（原 2 条 + 新 1 条；不含 setup 的 2 条）。若新用例红，按日志定位：常见原因是 PUT 谓词没命中（看 postData 是否含 site3dView）或 refresh 后 enter3D 过早读取（加 `waitForTimeout(1200)` 已覆盖）。

- [ ] **Step 3：真机视觉核对（网格线 + 视角）**

写一个临时 spec（跑完即删，不入库），最大化 3D 面板并截图 light/night，断言网格线颜色已落到 option：

```ts
// frontend/e2e/analysis/site3d-visual-tmp.spec.ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, ensureChartToggles } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

test('网格线视觉核对', async ({ page }) => {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await waitLoadingGone(page.locator('.single-param-tab'))
  await ensureChartToggles(page, { hist: false, site3d: true })
  const panel = page.locator('.chart-panel[data-chart-key="site3d"]')
  await expect(panel.locator('[data-site3d-canvas]')).toBeVisible({ timeout: 25_000 })
  await panel.locator('[title="最大化"]').click()
  await page.waitForTimeout(1200)
  const color = await page.evaluate(() => {
    const dom = document.querySelector('[data-site3d-canvas]') as any
    const o = dom?.__echartsInstance__?.getOption()
    return o?.grid3D?.[0]?.splitLine?.lineStyle?.color
  })
  expect(color).toBe('#dbdee4')
  await page.screenshot({ path: '../tasks/3d-site3d-view/grid-light.png' })
  await page.locator('button.theme-toggle').click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: '../tasks/3d-site3d-view/grid-night.png' })
  await page.evaluate(() => { document.documentElement.setAttribute('data-theme', 'light'); localStorage.setItem('theme', 'light') })
  await ensureChartToggles(page, { site3d: false })
})
```

跑：

```bash
cd frontend && npx playwright test analysis/site3d-visual-tmp.spec.ts --project=P1 --workers=1 > ../tasks/3d-site3d-view/e2e-visual.log 2>&1
grep -aE "passed|failed" ../tasks/3d-site3d-view/e2e-visual.log | tail -3
```
Expected：`1 passed`。看 `tasks/3d-site3d-view/grid-light.png` / `grid-night.png`：网格线应清晰可辨、与直方图观感一致；night 不刺眼。截图核对完删除临时 spec：

```bash
rm frontend/e2e/analysis/site3d-visual-tmp.spec.ts
```

- [ ] **Step 4：提交**

```bash
git add frontend/e2e/analysis/site3d.spec.ts
git commit -m "test(e2e): 3D 视角在切参数与刷新后保持（等含 site3dView 的 PUT，收尾复位落库）"
```

---

## Task 7：全量门禁收口 + 台账

**Files:**
- Modify: `docs/tasks/lessons.md`（只在有新坑时）
- Modify: `docs/superpowers/specs/2026-11-05-site3d-view-memory-and-grid-design.md`（实测偏离时）

- [ ] **Step 1：确认工作树只有本批改动**

```bash
git status --porcelain
```
Expected：只剩 `M docs/tasks/todo.md`（他人改动，不动）与 `?? docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`（他人草稿，不动）。

- [ ] **Step 2：build（含 `vue-tsc -b`，覆盖 test/）**

```bash
mkdir -p tasks/3d-site3d-view
cd frontend && npm run build > ../tasks/3d-site3d-view/build.log 2>&1
grep -aE "error TS|✓ built" ../tasks/3d-site3d-view/build.log | tail -3
```
Expected：无 `error TS`，出现 `✓ built in`。

- [ ] **Step 3：全量 vitest**

```bash
cd frontend && npx vitest run test/unit > ../tasks/3d-site3d-view/unit.log 2>&1
grep -aE "Test Files|Tests |FAIL" ../tasks/3d-site3d-view/unit.log
```
Expected：`Test Files 54 passed`（52 + 2 新文件）、`Tests ≈718 passed`（702 + 本批 16）、无 FAIL。

- [ ] **Step 4：受影响门禁（给 `--base master`，逐任务提交后自动基线只剩 HEAD~1）**

```bash
node scripts/e2e_affected.mjs --base master > tasks/3d-site3d-view/gate.log 2>&1
grep -a "changed:\|decide:\|档: \|RESULT:\|unexpected\|结论 " tasks/3d-site3d-view/gate.log | tail -10
```
Expected：末行 `RESULT: PASS · 计划 3 档全部执行`；e2e 全量池用例数 = 上一批 429 + 1（新 e2e 用例）= 430 附近（现算，不拿旧数当判据）；`unexpected 0`、结论非 `VOID`。若 `VOID (infra)`：清孤儿进程后重跑整轮，那一轮不算结论。

- [ ] **Step 5：台账（有坑才写）**

判断本轮是否踩到新坑（例如：gl 私有 `_control` 在某个操作路径下取不到、PUT 基底合并出现回归、网格线颜色与直方图实测不一致）。有就追加 `docs/tasks/lessons.md`（**CRLF**，用 Node 字节追加，禁止整文件重写）；没有就如实说明「本批无新坑」。

- [ ] **Step 6：证据落在最终字节**

```bash
git log --oneline -10
git status --porcelain
```
Expected：Task 1–6 六次提交（外加可能的台账提交）；工作树只剩他人两处未跟踪/未提交改动；Step 4/5 之后**不得**再编辑 `frontend/src/**`（否则重跑门禁）。

---

## 不做的事

- 不改 2D 直方图的任何渲染（它就是对齐目标）。
- 不为「动画一致」改数据形状或关动画。
- 不按参数/文件分别记视角（用户选全局）。
- 不把视角写 localStorage 镜像（账号是唯一事实来源）。
- 不动后端（`analysis_chart_state` 是哑 JSON 字段）。
- 不碰 `docs/tasks/todo.md` 与 `docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`。
