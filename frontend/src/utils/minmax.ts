/**
 * 单趟迭代求 [min, max]。
 *
 * 替代 Math.min(...arr) / Math.max(...arr)：大数据数组（如 6 万行文件的
 * 分位数数组）展开为函数参数会超出 JS 引擎调用栈上限，抛出
 * RangeError: Maximum call stack size exceeded。实测约 11 万+ 元素即崩溃。
 *
 * 空数组返回 [Infinity, -Infinity]（与 Math.min(...[]) 语义一致），
 * 调用处自行保证非空。
 */
export function minMax(values: number[]): [number, number] {
  let min = Infinity
  let max = -Infinity
  for (const v of values) {
    if (v < min) min = v
    if (v > max) max = v
  }
  return [min, max]
}
