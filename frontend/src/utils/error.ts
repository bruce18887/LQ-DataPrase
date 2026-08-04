/**
 * formatError — 从任意请求错误中提取可读的错误消息。
 *
 * 后端错误响应有几种并存的历史格式，这里按优先级统一提取：
 *   1. `data.message`    —— 新统一异常格式（apps/common/exceptions.py）+ SFTP 旧格式
 *   2. `data.detail`     —— DRF 默认格式（字符串时）
 *   3. `data.error`      —— 遗留机器码（含中文直接展示；机器码查 ERROR_CODE_MAP）
 *   4. `{字段: [消息]}`   —— 遗留字段校验错误，取第一条
 *   5. 无 response       —— 网络错误（后端未启动 / 超时）
 * 全部不匹配时回退 fallback。
 */

/** 遗留机器码 → 中文提示（代码见 apps/ 下各 views 的 `{'error': 'xxx'}` 字面量） */
export const ERROR_CODE_MAP: Record<string, string> = {
  not_connected: '未连接到服务器',
  parse_failed: '文件解析失败，请稍后重试',
  param_required: '缺少参数',
  param_not_found: '参数不存在',
  param_no_valid_data: '该参数无有效数据',
  no_valid_params: '没有有效参数',
  no_valid_files: '没有有效文件',
  no_serial_column: '缺少序列号列',
  file_ids_required: '缺少文件 ID',
  file_not_found: '文件不存在或已删除',
  file_not_found_or_parse_failed: '文件在磁盘上找不到，或解析失败',
  serial_distribution_failed: '序列分布分析失败',
  qqplot_failed: 'QQ 图生成失败',
  params_required: '缺少参数',
  param_x_and_param_y_required: '缺少 X/Y 参数',
  param_is_metadata: '该参数为元数据，无法分析',
  no_site_column: '缺少站点列',
  no_files: '没有文件',
  no_data: '没有数据',
  no_coord_columns: '缺少坐标列',
  no_common_items: '没有公共项目',
  need_two_files: '至少需要两个文件',
  need_at_least_2_files: '至少需要 2 个文件',
  invalid_method: '不支持的分析方法',
  correlation_failed: '相关性分析失败',
  internal_error: '服务器内部错误',
}

function hasCJK(text: string): boolean {
  return /[一-龥]/.test(text)
}

interface ErrorLike {
  response?: { data?: unknown }
  message?: string
}

export function formatError(err: unknown, fallback = '请求失败'): string {
  if (!err || typeof err !== 'object') return fallback

  const e = err as ErrorLike
  // 网络层错误：无响应（后端未启动、超时、连接被拒）。
  if (!e.response) return '无法连接服务器，请检查网络'

  const data = e.response.data
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>
    if (typeof d.message === 'string' && d.message) return d.message
    if (typeof d.detail === 'string' && d.detail) return d.detail
    if (typeof d.error === 'string' && d.error) {
      return hasCJK(d.error) ? d.error : (ERROR_CODE_MAP[d.error] ?? d.error)
    }
    for (const [field, msgs] of Object.entries(d)) {
      if (Array.isArray(msgs) && msgs.length && typeof msgs[0] === 'string') {
        return `${field}: ${msgs[0]}`
      }
    }
  }
  return e.message || fallback
}
