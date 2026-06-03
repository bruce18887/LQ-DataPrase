import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** 项目根目录（frontend 的上一级） */
export const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..')

/** 样例数据根目录 */
export const SAMPLE_DATA_DIR = path.join(PROJECT_ROOT, 'Data', 'SampleData')

/** 登录态存放目录 */
export const AUTH_DIR = path.join(__dirname, '..', '.auth')
export const ADMIN_STATE = path.join(AUTH_DIR, 'admin.json')
export const USER_STATE = path.join(AUTH_DIR, 'user.json')

/** 下载文件保存目录（供后续人工比对导出内容） */
export const DOWNLOAD_DIR = path.join(__dirname, '..', '.downloads')

/** 种子账号（来自 apps/accounts/management/commands/seed_users.py） */
export const ACCOUNTS = {
  admin: { username: 'admin', password: 'admin123', role: 'administrator', displayName: '管理员' },
  user: { username: 'user', password: 'user123', role: 'user', displayName: '普通用户' },
  viewer: { username: 'viewer', password: 'viewer123', role: 'viewer', displayName: '查看者' },
} as const

export type Role = keyof typeof ACCOUNTS

/**
 * 预植入数据集的元信息（由 seed_test_data --clear 在 globalSetup 中执行）。
 * 测试用例直接用这些文件名定位列表中已存在的卡片，无需 UI 上传。
 */

/** 已预植入的文件总数 */
export const SEEDED_FILE_COUNT = 11

/** 预植入文件列表（按文件名识别） */
export const SEEDED_FILES = {
  // CTA8290D (FT)
  CTA8290D_FT: 'BPD60320_C01F40#AAA12603030006_FT1-FT1-1_R2603030042_20260305_204439.csv',
  // CTA8280F (FT) — 10000 行，适合分析抽样
  CTA8280F_FT: 'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv',
  // ETS88 (FT)
  ETS88_FT: 'BPD93204_FT1_ETS163550_12252024.csv',
  // STS8200 (CP) — 有 Wafer 坐标，唯一适合 Wafer Map 的文件
  STS8200_CP: 'BN281R3CYCAA_2604160006_TTTA803100.03_06_CP1_20260418161733.csv',
  // Buyoff — 同产品 3 个测试阶段
  BUYOFF_FT: 'BPD60320_FT.csv',
  BUYOFF_QA1: 'BPD60320_QA1.csv',
  BUYOFF_QA2: 'BPD60320_QA2.csv',
  // Gage — 4 个 Site
  GAGE_S1: 'gage_m_S1.csv',
  GAGE_S2: 'gage_m_S2.csv',
  GAGE_S3: 'gage_m_S3.csv',
  GAGE_S4: 'gage_m_S4.csv',
} as const

/** 按测试场景推荐使用的文件 */
export const RECOMMENDED = {
  /** 分析页默认选择（CTA8280F 参数最多，适合抽样 5 个参数） */
  analysis: SEEDED_FILES.CTA8280F_FT,
  /** 分析页多文件趋势用（同产品 CTF8290D） */
  analysisMulti: [SEEDED_FILES.BUYOFF_FT, SEEDED_FILES.BUYOFF_QA1],
  /** Wafer Map 必需 CP 数据 */
  waferMap: SEEDED_FILES.STS8200_CP,
  /** Buyoff 用（同产品 3 阶段） */
  buyoff: [SEEDED_FILES.BUYOFF_FT, SEEDED_FILES.BUYOFF_QA1, SEEDED_FILES.BUYOFF_QA2],
  /** Gage 用（4 Site） */
  gage: [SEEDED_FILES.GAGE_S1, SEEDED_FILES.GAGE_S2, SEEDED_FILES.GAGE_S3, SEEDED_FILES.GAGE_S4],
} as const

/**
 * 原始磁盘文件路径（仅用于唯一命名上传测试的副本来源，不再用于批量上传）。
 * seed_test_data 已预先将 SampleData 所有 CSV 复制到 media/uploads/ 并注册为 DataFile。
 */
export const PRIMARY_SAMPLE_FILE = path.join(
  SAMPLE_DATA_DIR,
  'CTA8290D',
  'BPD60320_C01F40#AAA12603030006_FT1-FT1-1_R2603030042_20260305_204439.csv',
)

/** 图表测试抽样的参数个数（可用 PARAM_SAMPLE_COUNT 覆盖，默认 5） */
export const PARAM_SAMPLE_COUNT = Number(process.env.PARAM_SAMPLE_COUNT || 5)

/** 应用全部路由（用于冒烟） */
export const ROUTES = [
  { path: '/dashboard', title: '仪表板', menu: '仪表板' },
  { path: '/data', title: '数据管理', menu: '数据管理' },
  { path: '/analysis', title: '数据分析', menu: '数据分析' },
  { path: '/batch', title: '批次报表', menu: '批次报表' },
  { path: '/sftp', title: 'SFTP 浏览器', menu: 'SFTP浏览器' },
  { path: '/settings', title: '系统设置', menu: '系统设置' },
  { path: '/roadmap', title: '功能路线图', menu: '功能路线图' },
] as const
