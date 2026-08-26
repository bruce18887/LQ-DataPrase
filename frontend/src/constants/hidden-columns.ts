/**
 * 默认隐藏列（记录级/系统列）：导出 Excel（列保留但设隐藏属性）与
 * 查看数据 ag-grid（隐藏但可从列菜单重新显示）共用。
 *
 * 候选清单 = 四种格式（CTA8290D/CTA8280F/ETS88/STS8200）解析器 SYSTEM_COLUMNS
 * （apps/datafiles/parsers/base.py），按列名精确匹配（仅对文件中存在的列生效）。
 * 设置页按「ATE 平台 → 属性」分组展示（免逐个勾选）。
 */

/** 默认隐藏的列（用户默认：Part_No/Dut_Pass/X_COORD/Y_COORD/QR_Code/Start_T/Alarm/Data_Cnt） */
export const DEFAULT_HIDDEN_COLUMNS: string[] = [
  'Part_No', 'Dut_Pass', 'X_COORD', 'Y_COORD', 'QR_Code',
  'Start_T', 'Alarm', 'Data_Cnt',
]

/** 属性分组：同一语义（料号/槽位/坐标…）下的各平台列名 */
export interface HiddenColumnGroup {
  /** 属性名（如 料号 / 槽位 / 坐标） */
  property: string
  /** 该属性在该平台下的列名（可多列，如 X_COORD + Y_COORD） */
  cols: string[]
}

export interface HiddenColumnPlatform {
  /** ATE 平台（解析器格式名） */
  name: string
  groups: HiddenColumnGroup[]
}

/** 系统设置页候选列：按 ATE 平台 → 属性归类 */
export const HIDDEN_COLUMNS_BY_PLATFORM: HiddenColumnPlatform[] = [
  {
    name: 'CTA8290D',
    groups: [
      { property: '序列号', cols: ['Serial_No'] },
      { property: '料号', cols: ['Part_No'] },
      { property: '槽位', cols: ['Dut_No', 'Site_No'] },
      { property: '过点', cols: ['Dut_Pass'] },
      { property: 'Bin', cols: ['SW_Bin'] },
      { property: '坐标', cols: ['X_COORD', 'Y_COORD'] },
      { property: 'QR 码', cols: ['QR_Code'] },
      { property: '开始时间', cols: ['Start_T'] },
      { property: '测试时间', cols: ['Test_Time'] },
      { property: '告警', cols: ['Alarm'] },
      { property: '数据计数', cols: ['Data_Cnt'] },
    ],
  },
  {
    name: 'CTA8280F',
    groups: [
      { property: '编号', cols: ['Index_No'] },
      { property: '序列号', cols: ['Serial_No'] },
      { property: '槽位', cols: ['Dut_No', 'Site_No'] },
      { property: '过点', cols: ['Dut_Pass'] },
      { property: 'Bin', cols: ['SW_Bin'] },
      { property: '坐标', cols: ['X_COORD', 'Y_COORD'] },
      { property: 'QR 码', cols: ['QR_Code'] },
      { property: '开始时间', cols: ['Start_Time'] },
      { property: '测试时间', cols: ['Test_Time'] },
      { property: 'Handler 时间', cols: ['Handler_Time'] },
      { property: '告警', cols: ['Alarm'] },
      { property: '数据计数', cols: ['Data_Num'] },
    ],
  },
  {
    name: 'ETS88',
    groups: [
      { property: '槽位', cols: ['Site #'] },
      { property: '序列号', cols: ['Serial #'] },
      { property: 'Bin', cols: ['Bin'] },
      { property: '坐标', cols: ['XCoord', 'YCoord'] },
    ],
  },
  {
    name: 'STS8200',
    groups: [
      { property: '槽位', cols: ['SITE_NUM'] },
      { property: '料号', cols: ['PART_ID'] },
      { property: '过点', cols: ['PASSFG'] },
      { property: 'Bin', cols: ['SOFT_BIN'] },
      { property: '测试时间', cols: ['T_TIME'] },
      { property: '坐标', cols: ['X_COORD', 'Y_COORD'] },
      { property: '数据计数', cols: ['TEST_NUM'] },
    ],
  },
]

/** 扁平候选清单（各平台并集，按出现顺序去重）——供测试/其它消费方使用 */
export const HIDDEN_COLUMN_CANDIDATES: string[] = Array.from(new Set(
  HIDDEN_COLUMNS_BY_PLATFORM.flatMap((p) => p.groups.flatMap((g) => g.cols)),
))
