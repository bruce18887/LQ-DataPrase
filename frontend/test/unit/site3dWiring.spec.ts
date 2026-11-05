/**
 * T2：3D 图的接线绊线（specs/2026-11-04 §2/§4 + §10 判据 ⑧ 的组件半边）。
 *
 * 静态读源文件而不是起组件：这几条判据的对象是「接线形状」，用浏览器量要付 3s 单价，
 * 而它们一旦断了就是编译期/挂载期立刻可见的错，不需要真渲染。
 * 与 test/unit/site3dOption.spec.ts 的「⑧ 常量单一来源」配对：那边量纯函数，这边量消费者。
 *
 * ⚠ 这类「读源码形状」是弱判据，本文件为此做了两件事（规格复审实测过它们的必要性）：
 * ① 先剥注释再匹配（见 codeOf）——否则 `// import 'echarts-gl'` 算命中（假绿），
 *    而注释里解释「被否证的动态写法」又算违规（假红）；
 * ② 静态导入改成**逐行全等**——否则代码里一句 `const s = "import 'echarts-gl'"` 也能过。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SRC = new URL('../../src/', import.meta.url)
const read = (rel: string) => readFileSync(new URL(rel, SRC), 'utf8')

/** 去掉行注释与块注释后的代码（按行状态机，块注释可跨行）。已知限制：不识别字符串内的注释标记。 */
function codeOf(text: string): string {
  const out: string[] = []
  let inBlock = false
  for (const line of text.split(/\r?\n/)) {
    let s = line
    if (inBlock) {
      const end = s.indexOf('*/')
      if (end < 0) { out.push(''); continue }
      s = s.slice(end + 2)
      inBlock = false
    }
    for (;;) {
      const b = s.indexOf('/*')
      if (b < 0) break
      const e = s.indexOf('*/', b + 2)
      if (e < 0) { s = s.slice(0, b); inBlock = true; break }
      s = s.slice(0, b) + s.slice(e + 2)
    }
    const d = s.indexOf('//')
    if (d >= 0) s = s.slice(0, d)
    out.push(s)
  }
  return out.join('\n')
}

const trimLines = (code: string) => code.split('\n').map((l) => l.trim())

describe('Site3DChart.vue 不自己抄机位与箱体', () => {
  const vue = read('pages/analysis/components/Site3DChart.vue')
  const code = codeOf(vue)
  const setupAt = vue.indexOf('<script setup')
  const setup = codeOf(vue.slice(setupAt))

  it('复位走 composables 的导出值', () => {
    expect(code).toContain("from '../composables/site3dOption'")
    expect(code).toMatch(/applyDefaultView\(chartInstance\.value\)/)
  })

  it('源码里不出现任何机位/箱体字面量（写了就是第二份真相，复位会漂）', () => {
    for (const literal of ['alpha:', 'beta:', 'distance:', 'boxWidth:', 'boxDepth:', 'boxHeight:']) {
      expect(code, `Site3DChart.vue 不该出现 ${literal}`).not.toContain(literal)
    }
  })

  it('渲染器恒为 canvas，且代码里不出现 svg（注释里提到不算）', () => {
    expect(code).toMatch(/\(\s*\)\s*=>\s*'canvas'/)
    expect(code).not.toMatch(/['"]svg['"]/)
  })

  it('有 echarts-gl 的静态副作用导入（逐行全等：注释与字符串都不算）', () => {
    // 缺这一行 bar3D/grid3D 从未注册，图会静默空白；换成动态形态实测撞 TS7016
    expect(trimLines(code)).toContain("import 'echarts-gl'")
    expect(code).not.toMatch(/import\(\s*['"]echarts-gl['"]\s*\)/)
  })

  it('WebGL 探测在模块级（普通 <script> 块），不在 setup——否则每挂载一次就建一张 canvas', () => {
    const probeAt = code.indexOf('function detectWebGL')
    expect(probeAt).toBeGreaterThan(-1)
    expect(setupAt).toBeGreaterThan(probeAt)
    expect(setup).not.toContain('detectWebGL(')
  })

  it('降级分支存在且不建图（WebGL 缺失与无 Site 列各一条 el-alert，且画布挂在 v-else 里）', () => {
    expect(vue).toMatch(/<el-alert\s+v-if="!webglAvailable"/)
    expect(vue).toMatch(/<el-alert\s+v-else-if="!hasSites"/)
    expect(vue).toMatch(/<template v-else>/)
    expect((vue.match(/<el-alert/g) ?? []).length).toBe(2)
  })

  it('宿主带 e2e 契约属性 data-site3d-canvas（T3 按它定位，别靠 class 猜）', () => {
    expect(vue).toContain('data-site3d-canvas')
  })

  it('useChart 是唯一建图入口（R7③：容器被 v-if 销毁重建由它兜，禁止裸调 echarts.init）', () => {
    expect(code).toMatch(/useChart\(/)
    expect(code).not.toMatch(/echarts\.init\(/)
  })
})

describe('SingleParamTab.vue 的五图接线', () => {
  const vue = read('pages/analysis/components/SingleParamTab.vue')
  const code = codeOf(vue)

  it('图体槽与控件槽都挂上（dock 已按 controls-<key> 透传，缺槽就是面板没标题栏控件）', () => {
    expect(vue).toMatch(/<template #site3d>/)
    expect(vue).toMatch(/<template #controls-site3d>/)
  })

  it('勾选文案沿用「显示」前缀（e2e 的 CHART_TOGGLE_LABELS 按文本定位）', () => {
    expect(vue).toContain('显示3D柱状图')
  })

  it('组件只经 defineAsyncComponent 进入（出现静态 import 就把 gl 分包拉进冷启动）', () => {
    expect(code).toMatch(/defineAsyncComponent\(\(\)\s*=>\s*import\('\.\/Site3DChart\.vue'\)\)/)
    expect(code).not.toMatch(/import\s+[A-Za-z_$][\w$]*\s+from\s+['"]\.\/Site3DChart\.vue['"]/)
  })

  it('勾选态不再原地持有（改由 useChartToggles 单一来源）', () => {
    expect(code).toMatch(/useChartToggles\(\)/)
    expect(code).not.toMatch(/const showHistogram = ref/)
  })

  it('面板「×」关闭接回 closeChart（T2 纯函数那半边由 chartToggles.spec.ts 钉）', () => {
    expect(code).toMatch(/@close="closeChart"/)
  })

  it('复位三环齐全：控件写 epoch → prop 传下去 → 图体 watch props.resetEpoch', () => {
    expect(code).toContain('site3dResetEpoch++')
    expect(code).toContain(':reset-epoch="site3dResetEpoch"')
    // 中间这一环单独钉：两端字符串对不代表图体在听（复审把 watch 源改成 props.param 时全绿）
    const site = codeOf(read('pages/analysis/components/Site3DChart.vue'))
    expect(site).toMatch(/watch\(\s*\(\)\s*=>\s*props\.resetEpoch\b/)
  })
})

describe('HistogramChart.vue 的 bin 显隐走共享纯函数（2D 半边不能是第二份口径）', () => {
  const code = codeOf(read('pages/analysis/components/HistogramChart.vue'))

  it('导入并调用 activeBinIndices（§8 同屏口径的结构保证）', () => {
    expect(code).toContain("from '../composables/histogramBins'")
    expect(code).toMatch(/activeBinIndices\(/)
  })

  it('没有内联裁剪变量（回退成 clipMin/clipMax 就是第二份口径）', () => {
    expect(code).not.toMatch(/clipMin|clipMax/)
  })
})

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
    // 用 currentView 判「要不要补」会被 buildOption 的实时读取误挡（首帧渲染后就恒为真）；
    // 同理 flushView 若无条件保存，切页/卸载会把默认机位写成账号视角。
    expect(code).toMatch(/let viewDecided = false/)
    expect(code).toMatch(/let userTouched = false/)
    expect(code).toMatch(/if \(hadCachedView \|\| viewDecided\) return/)
    expect(code).toMatch(/if \(!userTouched\) return/)
  })

  it('只有镜头真的动了才记用户决定（单击 tooltip 不算）', () => {
    expect(code).toMatch(/isSameSite3DView\(live, currentView\.value\)/)
    // 交互处理器里就要标记，不能拖到 400ms 静置之后（否则加载回来的旧视角会把刚拖的机位拉回去）
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
    expect(code).toContain("addEventListener('wheel'")
    expect(code).toMatch(/onDeactivated\(/)
    expect(code).toMatch(/onBeforeUnmount\(/)
    expect(code).toMatch(/saveChartState\(\s*\{\s*site3dView/)
  })

  it('复位同时落库默认视角（否则下一次重渲染被旧视角拉回去）', () => {
    expect(code).toContain('defaultSite3DView()')
    expect(code).toMatch(/applyDefaultView\(/)
  })

  it('视角只走账号记忆，不直接碰 localStorage（单一事实来源）', () => {
    expect(code).not.toContain('localStorage')
  })
})
