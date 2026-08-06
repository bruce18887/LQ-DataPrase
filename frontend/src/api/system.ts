import api from './index'

/**
 * 系统级存储路径（/api/v1/system/paths/）。
 *
 * 与用户设置（/auth/settings/）不同，路径配置是全局的：GET 任何登录用户
 * 可见，PUT 仅管理员。路径修改需重启后端生效（DB 连接在启动时固定），
 * 响应以 `restart_required` 标识。
 */
export interface SystemPaths {
  /** 有效数据目录（数据库 + 上传数据所在） */
  data_dir: string
  /** 数据库文件路径 */
  db_path: string
  /** 上传数据目录 */
  media_path: string
  /** 有效临时文件目录 */
  temp_dir: string
  /** 配置文件路径（system_config.json，固定锚点目录） */
  config_file: string
  /** 配置文件中待生效的值（null = 使用默认） */
  configured: { data_dir: string | null; temp_dir: string | null }
  /** 当前用户是否可修改 */
  editable: boolean
  /** 是否需重启后端生效 */
  restart_required: boolean
}

export const systemApi = {
  getPaths() {
    return api.get<SystemPaths>('/system/paths/')
  },
  updatePaths(data: { data_dir?: string | null; temp_dir?: string | null }) {
    return api.put<SystemPaths>('/system/paths/', data)
  },
}
