/**
 * ECharts 颜色 token（纯数据）与 grid3D 样式件（纯函数）
 * ────────────────────────────────────────────────
 * 为什么从 echarts-theme.ts 拆出来：那份是 `useEChartsTheme()` 里的 computed，取一次
 * 就要过 pinia，而 stores/theme 的 watch 一初始化就摸 `document` ⇒ node 环境的 T2 量不到。
 * 双主题对称（lessons R7①）与「3D 样式件逐项归 token」（specs/2026-11-04 §5）都需要
 * 对**真值**下断言，所以把数据放这儿。echarts-theme.ts 只保留 store 接线。
 *
 * ⚠ 这里只放颜色/字号/字族。业务色（站点色板）在 utils/chart-bar.ts，字号在
 * theme/typography.ts——两处都不要在这里再抄一份。
 */
import { chartFontSize, fontFamily } from '../theme/typography'

/** 两套主题必须提供**同一组键**：不对称会让 colors 退化成联合类型、消费点报 TS2339 */
export interface EChartsColors {
  backgroundColor: string
  textColor: string
  titleColor: string
  subtextColor: string
  axisLineColor: string
  axisLabelColor: string
  splitLineColor: string
  /** 3D 网格线（对齐 2D 直方图的 ECharts 默认网格色） */
  gridLineColor: string
  borderColor: string
  legendTextColor: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  successColor: string
  warnColor: string
  errorColor: string
  infoColor: string
  brandColor: string
  brandColorSoft: string
  seriesColors: string[]
}

/** night 分支（原 `useEChartsTheme()` 的 `isDark` 分支，值与注释逐字迁来） */
export const ECHARTS_COLORS_NIGHT: EChartsColors = {
  // 背景色
  backgroundColor: 'transparent',

  // 文本色（对齐指南 §6.2：--text / --text-2 / --text-3）
  textColor: 'rgba(255, 255, 255, 0.76)',
  titleColor: '#ffffff',
  subtextColor: 'rgba(255, 255, 255, 0.55)',

  // 轴线颜色（--border / --bar-grid）
  axisLineColor: 'rgba(255, 255, 255, 0.10)',
  axisLabelColor: 'rgba(255, 255, 255, 0.76)',
  splitLineColor: 'rgba(255, 255, 255, 0.04)',
  gridLineColor: 'rgba(255, 255, 255, 0.04)',

  // 边框颜色
  borderColor: 'rgba(255, 255, 255, 0.10)',

  // 图例颜色
  legendTextColor: 'rgba(255, 255, 255, 0.76)',

  // 工具提示（--card-glass / --border-2 / --text）
  tooltipBg: 'rgba(19, 19, 39, 0.88)',
  tooltipBorder: 'rgba(255, 255, 255, 0.18)',
  tooltipText: '#ffffff',

  // 语义状态色：与 design-tokens.css 的 --success/--warn/--error/--info/--brand
  // 同源（night 分支取 --p-teal-600 / --p-amber-500 / --p-red-500 /
  // --p-sky-600 / --p-amber-500）。ECharts 走 canvas/svg 渲染，**不解析**
  // CSS 变量也不解析 color-mix()，所以 setOption 里的颜色必须取这里的
  // JS 常量；DOM 模板里才用 var(--token)。两个主题分支的键集必须对称，
  // 否则 TS 会把返回值推成联合类型、访问时报错。
  successColor: '#11998e',
  warnColor: '#f9a825',
  errorColor: '#f5576c',
  infoColor: '#4facfe',
  brandColor: '#f9a825',
  /** 品牌色 45% 透明——替代 CSS color-mix(in srgb, var(--brand) 45%, transparent) */
  brandColorSoft: 'rgba(249, 168, 37, 0.45)',

  // 系列颜色：2026-08-29 拿 --chart-1..8 做过一次 CVD 复验，未通过（protan/deutan ΔE 达不到
  // 指南要求的 ≥15），故按 docs/reference/ui-design-guide.md:193-196 维持现状；复验脚本在本机
  // tasks/cvd_verify.mjs（`/tasks/*` 已 gitignore，不入库），判据是 protan/deutan ΔE ≥15；
  // 别人 clone 到的新机器既没脚本也没判据，要换色板就得重做一遍复验。
  // 轴系/文本/tooltip 已对齐。
  seriesColors: [
    '#fdd835', // 金色
    '#14b8a6', // 青绿
    '#4facfe', // 蓝色
    '#fb7185', // 粉红
    '#38ef7d', // 绿色
    '#b45309', // 棕色（替代原浅金：与金色在色盲视角下不可分）
    '#00f2fe', // 浅蓝
    '#ff9f43', // 橙色（替代原浅粉：与青绿在 protan 视角下不可分）
  ],
}

/** light 分支（原 `useEChartsTheme()` 的 else 分支，值与注释逐字迁来） */
export const ECHARTS_COLORS_LIGHT: EChartsColors = {
  // 浅色主题配置（对齐指南 §6.2）
  backgroundColor: 'transparent',
  textColor: '#6b7280',
  titleColor: '#1f2937',
  subtextColor: '#9ca3af',
  axisLineColor: '#e5e7eb',
  axisLabelColor: '#6b7280',
  splitLineColor: '#eef0f3',
  // ECharts 6 默认网格线（neutral15）——直方图实际画的就是它，3D 跟它对齐
  gridLineColor: '#dbdee4',
  borderColor: '#e5e7eb',
  legendTextColor: '#6b7280',
  tooltipBg: 'rgba(255, 255, 255, 0.92)',
  tooltipBorder: '#e5e7eb',
  tooltipText: '#1f2937',
  // 语义状态色：与 night 分支同一组键，取 light 语义层
  // （--p-teal-700 / --p-amber-800 / --p-red-700 / --p-sky-700 / --p-blue-600）
  successColor: '#047857',
  warnColor: '#92400e',
  errorColor: '#b91c1c',
  infoColor: '#0369a1',
  brandColor: '#2563eb',
  brandColorSoft: 'rgba(37, 99, 235, 0.45)',
  // 系列颜色：同 night 分支说明，CVD 复验未过维持现状
  seriesColors: [
    '#2563eb', // 专业蓝
    '#047857', // 绿色
    '#d97706', // 琥珀（替代橙：橙与红在 deutan 下不可分）
    '#b91c1c', // 红色
    '#0284c7', // 蓝色
    '#86198f', // 李子（替代紫：紫与蓝在 deutan 下不可分）
    '#475569', // 深灰（替代深橙）
    '#0d9488', // 青色
  ],
}

/**
 * ECharts 通用色板（本文件那两套）的主题映射——返回**同一份对象**，不复制：复制出来的
 * 同值对象就是两份事实来源。放这儿而不是留在 `useEChartsTheme()` 里，是因为那行 ternary
 * 摸得到 pinia 就摸不进 T2——「把 night 和 light 选反」这类变异在 node 层原本无人红
 * （2026-11-04 实测 SURVIVED），只有把它变成纯函数的入参才能按值断言。
 *
 * 边界：它只管**通用色板**，不是全仓唯一一处主题映射。站点 8 色在
 * `utils/chart-bar.ts` 的 `getSiteColors8(isDark)`（另一套值、另一条 CVD 约束），
 * 语义色在别处——都别往这儿合。
 */
export function echartsColorsFor(isDark: boolean): EChartsColors {
  return isDark ? ECHARTS_COLORS_NIGHT : ECHARTS_COLORS_LIGHT
}

/** 3D 图消费的 token（T2 逐个断言两分支都有，缺一个就是运行时 undefined） */
export const GRID3D_TOKEN_KEYS = [
  'textColor', 'axisLabelColor', 'splitLineColor', 'gridLineColor',
  'tooltipBg', 'tooltipBorder', 'tooltipText',
] as const

/** grid3D（echarts-gl）的样式件形状 */
export interface Grid3DStyle {
  axisLine: { show: true; lineStyle: { color: string; width: number } }
  splitLine: { show: true; lineStyle: { color: string; width: number } }
  axisTick: { show: false }
  axisLabel: {
    show: true
    margin: number
    color: string
    fontSize: number
    fontFamily: string
  }
  nameTextStyle: { color: string; fontSize: number }
  light: { main: { intensity: number }; ambient: { intensity: number } }
}

/**
 * grid3D 的样式件：gl 的默认长相（#333 宽 2 硬轴线、12px 无字色标签、黑胶囊 axisPointer、
 * lambert 打光）逐项改回项目 token。只含样式——箱体几何与数据在
 * pages/analysis/composables/site3dOption.ts。
 *
 * 不写 `axisPointer`：bar3D 的 tooltip 走默认 `item` 触发（没有 trigger:'axis'），gl 不画
 * 那个黑胶囊，写了就是无人消费的死配置（spec §5 末条）。
 */
export function grid3DStyle(colors: EChartsColors): Grid3DStyle {
  return {
    // show 必须为 true：echarts-gl 的 Grid3DAxis 只在 `if (axisLineModel.get('show'))`
    // 里写 axisLineCoords（构造里先置 null），而 _updateAxisLabelAlign() 经 _onCameraChange
    // → _updateAxisLinePosition 无条件读它 ⇒ show:false 时每次相机更新抛一次 TypeError。
    // 复核：`cd frontend && grep -n axisLineCoords node_modules/echarts-gl/dist/echarts-gl.js`
    // 恰好三处命中（node_modules 在 frontend 下，从仓库根跑这条会报 No such file）。
    // 这条读的是装在 node_modules 的 2.1.0；清单里是 `^2.1.0` 区间（package.json:40 与
    // package-lock.json 都是），脱离 lockfile 重装可能拿到别的 2.x，届时先重跑上面那条 grep。
    // 想彻底抹掉轴线的正确写法是保持 show:true + 全透明色，不是关 show（spec §6.6）。
    axisLine: { show: true, lineStyle: { color: colors.splitLineColor, width: 1 } },
    // 网格线：2D 直方图用的是 ECharts 默认 #dbdee4（见 token 注释）；
    // 3D 之前用 splitLineColor（#eef0f3）在白底上几乎看不见（用户 2026-11-05 反馈）。
    splitLine: { show: true, lineStyle: { color: colors.gridLineColor, width: 1 } },
    axisTick: { show: false },
    axisLabel: {
      show: true,
      margin: 6,
      // 字号/字族/字色三件都归 token（§5），gl 默认只有 12px 且没有字色。
      // 必须是**平铺**属性：ECharts 6 对旧的 `axisLabel.textStyle` 只做兼容拆平
      // （setOption 后 getOption 里 `textStyle:null`、三件被提到 axisLabel 本级），
      // 而 gl 的 Grid3DAxis 直接读 `axisLabelModel.get('color'|'fontSize'|'fontFamily')`。
      color: colors.axisLabelColor,
      fontSize: chartFontSize.micro,
      fontFamily: fontFamily.sans,
    },
    nameTextStyle: { color: colors.textColor, fontSize: chartFontSize.micro },
    // 平涂不吃光，也不写 shadow：阴影是「demo 感」的主要来源。前提是 series 侧
    // `shading:'color'`——那行不在本函数返回值里，由 pages/analysis/composables/site3dOption.ts
    // 写（Task 5）。那边改成 lambert/normal 就会打光，这两条强度立刻失效，两处要一起改。
    light: { main: { intensity: 0 }, ambient: { intensity: 1 } },
  }
}
