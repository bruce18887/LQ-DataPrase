/**
 * serial 芯片高亮的纯匹配函数（T2 承载，无 DOM 无网络）。
 * 从各 lane 的绘制点全字段数组里挑出命中 serial 的点，供 SerialChart 叠加高亮系列。
 * 与后端 isin 口径一致：**严格类型**成员判定（数值 4 不匹配字符串 '4'）。
 * 保持 lane 结构（逐 lane 返回）与点对象原样（同一引用，tooltip 需要
 * value/realY/realSerial/isFail/anchor 全字段）。
 */

/**
 * @param laneGroups 各 lane 的绘制点数组（SerialChart 的 laneGroups，非 displayLanes）
 * @param serials    命中的序列号集合（可含重复，按 Set 去重判定）
 * @returns 与 laneGroups 同形的逐 lane 命中点数组；点对象为入参同一引用
 */
export function pickHighlightPoints<T extends { realSerial: number | string }>(
  laneGroups: T[][],
  serials: (number | string)[],
): T[][] {
  // Set.has 用 SameValueZero：number 4 与 string '4' 是不同成员 ⇒ 严格不互配。
  const wanted = new Set<number | string>(serials)
  // filter 逐 lane 遍历一次：每个点最多出现一次（serials 重复不复制点），引用原样保留。
  return laneGroups.map((lane) => lane.filter((p) => wanted.has(p.realSerial)))
}
