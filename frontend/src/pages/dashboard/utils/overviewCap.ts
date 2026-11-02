/**
 * 仪表板逐参数总览的封顶说明（B4 前端落地）。
 *
 * `/summary/` 的 `test_item_overview` 默认最多 200 行（`top_n` 回显本次生效上限），
 * `param_total` 是截断前的参数数。总览页脚原有的「共 N 项」是**卡头两个复选框
 * 过滤后**的行数，跟封顶不是一回事，所以封顶要单独说一句：1728 列那种文件若不说，
 * 用户看到的是「只有 200 个参数」。
 */

export interface OverviewCapInput {
  paramTotal?: number
  itemsCount: number
  topN?: number
}

export function overviewCapHint({ paramTotal, itemsCount, topN }: OverviewCapInput): string {
  if (typeof paramTotal !== 'number' || paramTotal <= itemsCount) return ''
  return `参数共 ${paramTotal} 项，总览最多显示 ${topN ?? itemsCount} 项`
}
