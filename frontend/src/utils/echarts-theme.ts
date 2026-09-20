/**
 * ECharts 主题 & 渲染器配置
 *
 * 此文件提供了：
 * 1. 根据当前主题返回适当的ECharts颜色配置
 * 2. 统一的渲染器模式（SVG / Canvas），方便全局切换
 */

import { useThemeStore } from '../stores/theme'
import { computed } from 'vue'
import { chartFontSize, fontFamily } from '../theme/typography'
import { authApi } from '../api/auth'

// ============================================================
//  渲染器模式 — 全局单一切换点，改为 'canvas' 即可切回
// ============================================================
let _chartRenderer: 'svg' | 'canvas' = 'svg'
let _rendererFetched = false
let _rendererPromise: Promise<void> | null = null

/** 只接受 'canvas'，其余（含缺失/未知值）一律回退 'svg'，与模块初值一致。 */
function clampChartRenderer(value: unknown): 'svg' | 'canvas' {
  return value === 'canvas' ? 'canvas' : 'svg'
}

/** 获取 echarts.init 的第三个参数（渲染器配置）；单图可覆盖（如大数据量强制 canvas） */
export function getChartInitOpts(rendererOverride?: 'svg' | 'canvas'): { renderer: 'svg' | 'canvas' } {
  return { renderer: rendererOverride ?? _chartRenderer }
}

/** 运行时动态设置渲染器（设置页加载/保存后调用，等同于已取到账号真值） */
export function setChartRenderer(renderer: 'svg' | 'canvas') {
  _chartRenderer = clampChartRenderer(renderer)
  _rendererFetched = true
}

/** 清空缓存并退回默认值（auth store 登录/登出时调用，防跨账号串值）。 */
export function resetChartRendererCache(): void {
  _chartRenderer = 'svg'
  _rendererFetched = false
  _rendererPromise = null
}

/**
 * 把账号级 chart_renderer 取进上面的模块缓存。
 *
 * 图表初始化链路是同步的（echarts-init.ts 的 tryInit 里直接 getChartInitOpts），
 * 没法就地 await，所以由路由守卫在任何页面组件挂载前 await 本函数一次：
 * 未取过时单飞发一次 /auth/settings/ 请求，整页生命周期内只发一次。
 * 请求失败静默回退 'svg' 并记为已取过 —— 与 utils/exportTimeout.ts 的降级口径
 * 一致，避免每次导航都重试。
 */
export function ensureChartRenderer(): Promise<void> {
  if (_rendererFetched) return Promise.resolve()
  if (!_rendererPromise) {
    _rendererPromise = (async () => {
      try {
        const { data } = await authApi.getSettings()
        _chartRenderer = clampChartRenderer(data?.chart_renderer)
      } catch {
        _chartRenderer = 'svg'
      }
      _rendererFetched = true
    })()
  }
  return _rendererPromise
}

/** 获取当前渲染器模式 */
export function getChartRenderer(): 'svg' | 'canvas' {
  return _chartRenderer
}

/**
 * 获取当前主题的ECharts颜色配置
 */
export function useEChartsTheme() {
  const themeStore = useThemeStore()

  const isDark = computed(() => themeStore.currentTheme === 'night')

  // 基础颜色配置
  const colors = computed(() => {
    if (isDark.value) {
      return {
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

        // 系列颜色：2026-08-29 新色板（--chart-1..8）CVD 复验未通过
        // （tasks/cvd_verify.mjs：light 灰/青绿 deutan ΔE=7.6、night 浅蓝/粉红 deutan ΔE=13.6），
        // 按指南 §6.2 维持现状；轴系/文本/tooltip 已对齐。
        seriesColors: [
          '#fdd835', // 金色
          '#14b8a6', // 青绿
          '#4facfe', // 蓝色
          '#fb7185', // 粉红
          '#38ef7d', // 绿色
          '#b45309', // 棕色（替代原浅金：与金色在色盲视角下不可分）
          '#00f2fe', // 浅蓝
          '#ff9f43', // 橙色（替代原浅粉：与青绿在 protan 视角下不可分）
        ]
      }
    } else {
      return {
        // 浅色主题配置（对齐指南 §6.2）
        backgroundColor: 'transparent',
        textColor: '#6b7280',
        titleColor: '#1f2937',
        subtextColor: '#9ca3af',
        axisLineColor: '#e5e7eb',
        axisLabelColor: '#6b7280',
        splitLineColor: '#eef0f3',
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
        ]
      }
    }
  })

  /**
   * 获取ECharts通用配置
   */
  const getBaseOption = computed(() => ({
    backgroundColor: colors.value.backgroundColor,
    color: colors.value.seriesColors,

    textStyle: {
      color: colors.value.textColor,
      // 与全局字体栈保持一致（typography.ts ↔ design-tokens.css 单一事实来源）
      fontFamily: fontFamily.sans
    },

    title: {
      textStyle: {
        color: colors.value.titleColor,
        fontSize: chartFontSize.title,
        fontWeight: 600
      },
      subtextStyle: {
        color: colors.value.subtextColor,
        fontSize: chartFontSize.body
      }
    },

    legend: {
      textStyle: {
        color: colors.value.legendTextColor,
        fontSize: chartFontSize.body
      },
      pageTextStyle: {
        color: colors.value.legendTextColor
      }
    },

    tooltip: {
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      borderWidth: 1,
      textStyle: {
        color: colors.value.tooltipText,
        fontSize: chartFontSize.body
      },
      axisPointer: {
        lineStyle: {
          color: colors.value.axisLineColor
        },
        crossStyle: {
          color: colors.value.axisLineColor
        }
      }
    },

    grid: {
      borderColor: colors.value.borderColor
    },

    xAxis: {
      axisLine: {
        lineStyle: {
          color: colors.value.axisLineColor
        }
      },
      axisLabel: {
        color: colors.value.axisLabelColor,
        fontSize: chartFontSize.axis
      },
      splitLine: {
        lineStyle: {
          color: colors.value.splitLineColor
        }
      },
      nameTextStyle: {
        color: colors.value.textColor
      }
    },

    yAxis: {
      axisLine: {
        lineStyle: {
          color: colors.value.axisLineColor
        }
      },
      axisLabel: {
        color: colors.value.axisLabelColor,
        fontSize: chartFontSize.axis
      },
      splitLine: {
        lineStyle: {
          color: colors.value.splitLineColor
        }
      },
      nameTextStyle: {
        color: colors.value.textColor
      }
    }
  }))

  return {
    isDark,
    colors,
    getBaseOption
  }
}
