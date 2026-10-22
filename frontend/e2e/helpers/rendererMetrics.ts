import type { Page } from '@playwright/test'

export interface MetricRequest {
  url: string
  responseEndMs: number
  durationMs: number
  transferMiB: number
}
export interface MetricRow {
  label: string
  jsHeapUsedMiB: number
  longTasksMsTotal: number
  longestTaskMs: number
  requests: MetricRequest[]
}
export interface RendererMetrics {
  snapshot(label: string): Promise<MetricRow>
  stop(): Promise<void>
}

const HEAVY = /\/(browse|summary)\//

/**
 * 渲染进程取样：堆走 CDP、long task 走页面里的 PerformanceObserver、请求走 Resource Timing，
 * 三条通路都不依赖产品代码里的任何埋点。
 *
 * ⚠ 两个口径必须知道再读数：
 * - `longTasksMsTotal` / `longestTaskMs` 与 `requests` 都是**自上次整页导航起的累计量**
 *   （`addInitScript` 每次导航重装 → 累计归零；同页内开标签不导航 → 一路累加）。
 *   要的是「某个形状贡献了多少」，取相邻两次 snapshot 的差。
 * - 堆是 `Runtime.getHeapUsage` 的 usedSize，**不是** RSS，也不等于 Chromium 的提交内存；
 *   每次取样前先 `HeapProfiler.collectGarbage`，所以读到的 = 「GC 之后仍驻留」的那部分。
 *
 * ⚠ `startRendererMetrics` 必须在任何导航前调用：longtask 观察器要注入到文档创建前。
 */
export async function startRendererMetrics(page: Page): Promise<RendererMetrics> {
  await page.addInitScript(() => {
    const w = window as unknown as { __lt?: Array<{ start: number; dur: number }> }
    w.__lt = []
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) w.__lt!.push({ start: e.startTime, dur: e.duration })
      }).observe({ entryTypes: ['longtask'] })
    } catch {
      /* 通道不支持 longtask 时探针仍要能跑，不能把自己测死 */
    }
  })

  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Performance.enable')
  await cdp.send('Runtime.enable')

  const heapMiB = async (): Promise<number> => {
    /*
     * 先强制一次 GC 再读堆。不 GC 时 `usedSize` 里混着「还没来得及回收的垃圾」，
     * 同一个形状两轮实测差 53%（ETS88 19 块增量：87.2 MiB vs 133.1 MiB，
     * 2026-10-22 16:37 与 16:42 两轮），而 spec §5 Q1 要求两轮差 <20%。
     * 这个探针量的是 IRM 缓存**驻留**多少，驻留 = GC 之后还活着的那部分，所以 GC 才是对的口径。
     * 代价：GC 自身可能是一条 long task，会被记进**下一次** snapshot 的窗口 —— 读
     * `longTasksMsTotal` 的差值时按「含若干次 GC 暂停」理解。
     */
    await cdp.send('HeapProfiler.collectGarbage')
    const { usedSize } = await cdp.send('Runtime.getHeapUsage')
    return usedSize / 1048576
  }

  return {
    async snapshot(label: string): Promise<MetricRow> {
      // 先读 long task 再 GC：本次 snapshot 触发的那次 GC 就不算进它自己的窗口
      const lt = await page.evaluate(() => (window as any).__lt ?? [])
      const heap = await heapMiB()
      const reqs = await page.evaluate(
        (re: string) =>
          (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
            .filter((e) => new RegExp(re).test(e.name))
            .map((e) => ({
              url: e.name.replace(/^.*\/api\/v1/, ''),
              responseEndMs: Math.round(e.responseEnd),
              durationMs: Math.round(e.duration),
              transferMiB: +(e.transferSize / 1048576).toFixed(2),
            })),
        HEAVY.source,
      )
      return {
        label,
        jsHeapUsedMiB: +heap.toFixed(1),
        longTasksMsTotal: Math.round(lt.reduce((a: number, x: any) => a + x.dur, 0)),
        longestTaskMs: Math.round(lt.reduce((a: number, x: any) => Math.max(a, x.dur), 0)),
        requests: reqs,
      }
    },
    async stop() {
      await cdp.detach().catch(() => undefined)
    },
  }
}
