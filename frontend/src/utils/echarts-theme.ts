/**
 * ECharts 主题 & 渲染器配置
 *
 * 此文件提供了：
 * 1. 根据当前主题返回适当的ECharts颜色配置
 * 2. 统一的渲染器模式（SVG / Canvas），方便全局切换
 */

import { useThemeStore } from '../stores/theme'
import { computed } from 'vue'
import { fontFamily } from '../theme/typography'

// ============================================================
//  渲染器模式 — 全局单一切换点，改为 'canvas' 即可切回
// ============================================================
let _chartRenderer: 'svg' | 'canvas' = 'svg'

/** 获取 echarts.init 的第三个参数（渲染器配置）；单图可覆盖（如大数据量强制 canvas） */
export function getChartInitOpts(rendererOverride?: 'svg' | 'canvas'): { renderer: 'svg' | 'canvas' } {
  return { renderer: rendererOverride ?? _chartRenderer }
}

/** 运行时动态设置渲染器 */
export function setChartRenderer(renderer: 'svg' | 'canvas') {
  _chartRenderer = renderer
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

        // 文本色
        textColor: 'rgba(255, 255, 255, 0.8)',
        titleColor: '#ffffff',
        subtextColor: 'rgba(255, 255, 255, 0.6)',

        // 轴线颜色
        axisLineColor: 'rgba(255, 255, 255, 0.28)',
        axisLabelColor: 'rgba(255, 255, 255, 0.7)',
        splitLineColor: 'rgba(255, 255, 255, 0.16)',

        // 边框颜色
        borderColor: 'rgba(255, 255, 255, 0.1)',

        // 图例颜色
        legendTextColor: 'rgba(255, 255, 255, 0.8)',

        // 工具提示背景
        tooltipBg: 'rgba(22, 33, 62, 0.95)',
        tooltipBorder: 'rgba(255, 255, 255, 0.2)',
        tooltipText: '#ffffff',

        // 系列颜色（图表数据颜色；经 CVD 色盲模拟验证 protan/deutan ΔE≥15，
        // 唯 青绿/粉红 protan 12.2 为语义锚点对（success/error），使用处均有文字标签）
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
        // 浅色主题配置
        backgroundColor: 'transparent',
        textColor: '#606266',
        titleColor: '#303133',
        subtextColor: '#909399',
        axisLineColor: '#e4e7ed',
        axisLabelColor: '#606266',
        splitLineColor: '#e4e7ed',
        borderColor: '#e4e7ed',
        legendTextColor: '#606266',
        tooltipBg: 'rgba(255, 255, 255, 0.95)',
        tooltipBorder: '#e4e7ed',
        tooltipText: '#303133',
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
      // 与全局字体栈保持一致（typography.ts ↔ variables.css 单一事实来源）
      fontFamily: fontFamily.sans
    },

    title: {
      textStyle: {
        color: colors.value.titleColor,
        fontSize: 16,
        fontWeight: 600
      },
      subtextStyle: {
        color: colors.value.subtextColor,
        fontSize: 12
      }
    },

    legend: {
      textStyle: {
        color: colors.value.legendTextColor,
        fontSize: 12
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
        fontSize: 12
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
        fontSize: 11
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
        fontSize: 11
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
