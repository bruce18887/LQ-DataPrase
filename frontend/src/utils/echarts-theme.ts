/**
 * ECharts 主题 & 渲染器配置
 *
 * 此文件提供了：
 * 1. 根据当前主题返回适当的ECharts颜色配置
 * 2. 统一的渲染器模式（SVG / Canvas），方便全局切换
 */

import { useThemeStore } from '../stores/theme'
import { computed } from 'vue'

// ============================================================
//  渲染器模式 — 全局单一切换点，改为 'canvas' 即可切回
// ============================================================
let _chartRenderer: 'svg' | 'canvas' = 'svg'

/** 获取 echarts.init 的第三个参数（渲染器配置） */
export function getChartInitOpts(): { renderer: 'svg' | 'canvas' } {
  return { renderer: _chartRenderer }
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
        axisLineColor: 'rgba(255, 255, 255, 0.2)',
        axisLabelColor: 'rgba(255, 255, 255, 0.7)',
        splitLineColor: 'rgba(255, 255, 255, 0.1)',

        // 边框颜色
        borderColor: 'rgba(255, 255, 255, 0.1)',

        // 图例颜色
        legendTextColor: 'rgba(255, 255, 255, 0.8)',

        // 工具提示背景
        tooltipBg: 'rgba(22, 33, 62, 0.95)',
        tooltipBorder: 'rgba(255, 255, 255, 0.2)',
        tooltipText: '#ffffff',

        // 系列颜色（图表数据颜色）
        seriesColors: [
          '#f9a825', // 金色
          '#11998e', // 青绿
          '#4facfe', // 蓝色
          '#f5576c', // 粉红
          '#38ef7d', // 绿色
          '#ffd54f', // 浅金
          '#00f2fe', // 浅蓝
          '#f093fb', // 浅粉
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
          '#059669', // 绿色
          '#d97706', // 橙色
          '#dc2626', // 红色
          '#0284c7', // 蓝色
          '#7c3aed', // 紫色
          '#ea580c', // 深橙
          '#047857', // 深绿
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
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
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
