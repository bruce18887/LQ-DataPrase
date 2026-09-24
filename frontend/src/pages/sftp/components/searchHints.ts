/**
 * 「命中」区的两段说明文案（唯一出处）。
 *
 * 放模块里而不是模板里，是因为 `SearchCriteria.vue` 已贴近单文件 600 行硬上限
 * （`.claude/CLAUDE.md`），而这两段都是长句中文 prose。
 */

export const CONTENT_ENGINE_NOTE =
  '模糊匹配、以及含中文等非 ASCII 字符的关键词必然走客户端引擎：服务端 grep 给不出同一个'
  + '结果集（会静默漏 GBK 文件）。整词不在其列 —— 关键词是纯 ASCII 时它照样能走服务端加速。'

/**
 * 列名档的三条口径都与 `scanners.match_headers` / `scanners.read_column` 一对一，
 * 改语义时两头都要动（`*` `?` `[` 那个元字符集在 `scanners._GLOB_META`）。
 */
export const COLUMN_MATCH_NOTE =
  '列名含 * ? [ 时按通配匹配整个列名（大小写敏感；*BV*2 读作「以 2 结尾」，'
  + '要任意位置含 2 得写 *BV*2*）；不含这三个字符时仍是精确相等，所以带 ? 的列名会被放宽。'
  + '匹配到的列会全部列出，每列各取前 N 个非空读数；表头里有这一列却一个读数都没有 → 标 no data。'
