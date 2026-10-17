/**
 * useCoalescedCall — 「连点只算首尾」的调用合并器（leading + trailing）。
 *
 * 为什么需要它（实测）：ETS88 大文件上一次 histogram 重算 ~57ms、且切换测试项会同时
 * 触发 4 条重计算 lane（直方图/箱线图/QQ/序列）。用户「扫一遍测试项」时是连点
 * ◀上一个/下一个▶，每下都发一轮；后端是**单进程**（standalone.py `runserver --noreload`），
 * 这些被 seq 守卫判定「过期」的请求照样把 CPU 算完，于是新那一个反而排在它们后面。
 *
 * 策略：
 * - **leading**：窗口外的第一次立即执行 ⇒ 单次切换零额外延迟（这是最常见的路径，不能为了
 *   连点场景给它加 150ms）；
 * - **trailing**：窗口内后续只记录最后一次参数，静默满 `ms` 后才执行 ⇒ 连点 2s ≈ 60 下
 *   从 60 轮请求降到 2 轮（第一下 + 最后一下）。
 *
 * 它与 `useAsyncData` 的分工见那边头部注释③：合并必须发生在**调用方的加载函数**外面，
 * 否则 `await run(...)` 之后那段「把响应摊给图表」的后续处理会被截断。
 */
export function useCoalescedCall<A extends unknown[]>(
  fn: (...args: A) => unknown,
  ms: number,
): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  /** 窗口是否已开：开着的窗口里到达的调用只记参数、不立即执行。 */
  let open = false
  let trailing: A | null = null

  function flush() {
    timer = null
    open = false
    const args = trailing
    trailing = null
    if (args) fn(...args)
  }

  function arm() {
    open = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(flush, ms)
  }

  return (...args: A) => {
    if (!open) {
      arm()
      fn(...args)
      return
    }
    trailing = args
    arm()
  }
}
