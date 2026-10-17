import { computed, type Ref } from 'vue'

/**
 * Site 统计表：数据直接来自直方图响应里的 `site_stats`。
 *
 * 之前它自己打 `POST /statistics/site_stats/`：每切一次测试项就发两个请求，后端
 * 把同一列扫两遍，CL 口径还各自解释过一次（2026-09-05 审查 契约#4：Site 表 Fail
 * 恒 0、Yield 恒 100%，与同屏直方图矛盾）。现在两端共用
 * `apps/analysis/services/range_limits.site_table_limits`，由
 * `apps/analysis/tests_param_switch_load.py` 钉住「并入直方图的站点表与独立端点
 * 逐字段相等」——所以下面不再有任何请求/竞态守卫，纯派生。
 *
 * 无 Site 列：直方图响应里 `site_stats` 为 null（后端仅在检测不到 Site 列时留空），
 * 提示语与原端点的 400 `no_site_column` 同文案，卡片内联显示。
 */
export function useSiteStats(histResult: Ref<any>) {
  const siteStats = computed<any[]>(() => histResult.value?.site_stats ?? [])

  const siteStatsError = computed(() => (
    histResult.value && histResult.value.site_stats == null
      ? '该文件没有 Site 列，无法进行站点统计'
      : ''
  ))

  return { siteStats, siteStatsError }
}
