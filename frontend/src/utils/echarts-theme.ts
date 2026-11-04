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
import { useUserSettingsStore } from '../stores/userSettings'
import {
  echartsColorsFor,
  grid3DStyle,
  type EChartsColors,
} from './echarts-tokens'

export type { EChartsColors, Grid3DStyle } from './echarts-tokens'

// ============================================================
//  渲染器模式 — 全局单一切换点，改为 'canvas' 即可切回
//  值本身由 stores/userSettings.ts 唯一持有，本模块只做键位与钳位。
// ============================================================

/** 只接受 'canvas'，其余（含缺失/未知值）一律回退 'svg'，与回退默认值一致。 */
function clampChartRenderer(value: unknown): 'svg' | 'canvas' {
  return value === 'canvas' ? 'canvas' : 'svg'
}

/** 获取 echarts.init 的第三个参数（渲染器配置）；单图可覆盖（如大数据量强制 canvas） */
export function getChartInitOpts(rendererOverride?: 'svg' | 'canvas'): { renderer: 'svg' | 'canvas' } {
  return { renderer: rendererOverride ?? getChartRenderer() }
}

/** 运行时动态设置渲染器（设置页加载/保存后调用，等同于已取到账号真值） */
export function setChartRenderer(renderer: 'svg' | 'canvas') {
  useUserSettingsStore().patch({ chart_renderer: clampChartRenderer(renderer) })
}

/**
 * 预热账号级 chart_renderer。
 *
 * 图表初始化链路是同步的（echarts-init.ts 的 tryInit 里直接 getChartInitOpts），
 * 没法就地 await，所以由路由守卫在任何页面组件挂载前 await 本函数一次。
 * 请求与降级口径都在 userSettings store：**未取过时单飞发一次 GET，失败静默回退
 * 'svg' 并记为已取过**（整页生命周期内不重试，否则每次导航都重试 = 请求风暴）。
 * 签名保持 Promise<void> 不变（router/index.ts:178 在守卫里 await 它）。
 */
export function ensureChartRenderer(): Promise<void> {
  return useUserSettingsStore().ensure()
}

/** 获取当前渲染器模式（同步 getter：图表初始化链路 await 不了） */
export function getChartRenderer(): 'svg' | 'canvas' {
  return clampChartRenderer(useUserSettingsStore().raw?.chart_renderer)
}

/**
 * 获取当前主题的ECharts颜色配置
 */
export function useEChartsTheme() {
  const themeStore = useThemeStore()

  const isDark = computed(() => themeStore.currentTheme === 'night')

  // 两套值与「键集必须对称」的约束都在 utils/echarts-tokens.ts（那份是纯数据，
  // 双主题对称由 test/unit/echartsTokens.spec.ts 对真值断言）。这里只做 store 接线，
  // 选板本身也委托给 echartsColorsFor——映射写在这行就摸不进 T2，选反了没人红。
  const colors = computed<EChartsColors>(() => echartsColorsFor(isDark.value))

  /** grid3D（3D 站点柱阵）样式件：与 getBaseOption 同一个 colors 源，不散写 */
  const grid3DTheme = computed(() => grid3DStyle(colors.value))

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
        fontSize: chartFontSize.lead,
        fontWeight: 600
      },
      subtextStyle: {
        color: colors.value.subtextColor,
        fontSize: chartFontSize.dense
      }
    },

    legend: {
      textStyle: {
        color: colors.value.legendTextColor,
        fontSize: chartFontSize.dense
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
        fontSize: chartFontSize.dense
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
        fontSize: chartFontSize.micro
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
        fontSize: chartFontSize.micro
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
    getBaseOption,
    grid3DTheme
  }
}
