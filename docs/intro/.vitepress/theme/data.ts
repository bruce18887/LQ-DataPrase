/* 介绍书内容数据：文案/热点/种子集中在此，markdown 只写散文，组件只写交互。
   维护时改这里 + 对应 md，不碰组件逻辑。口径事实源见 spec §5。 */
import { mulberry32, normalGen } from './useUi'

export interface Hotspot { x: number; y: number; t: string; d: string }
export interface Shot { src: string; w: number; h: number; cap: string; hs: Hotspot[] }
export const SHOTS: Record<string, Shot> = {
  dash: {
    src: '/assets/02-dashboard.png', w: 2000, h: 1127, cap: '图 3-1 · 仪表板 · 单文件分析（DEMO_FT_LOTD.csv）',
    hs: [
      { x: 28, y: 19, t: '文件选择器', d: '切换任意已上传文件，整页即时重算；右侧显示本次更新时间。' },
      { x: 50, y: 25, t: 'KPI 总览带', d: '总记录 100 / Pass 87 / Fail 13 / Yield 87.00% / UPH 2,039.8 / 测试时长 2.9min，一眼读完这批的基本面。' },
      { x: 28, y: 31.5, t: '告警带', d: '自动汇总「3 项告警 · 1 项需关注」：良率低于目标、CPK 不足、Site 间差异等；展开明细可逐条定位。' },
      { x: 37, y: 52, t: 'Bin 构成', d: 'Pareto 降序排列，色即语义：Pass bin 绿、Fail bin 红。示例中 Bin1 占 87%，其余三个失效 bin 各占 4–5%。' },
      { x: 77, y: 52, t: 'Site 良率', d: '柱状 + 折线双表达；右上角直接标出最高 Site1·96%、最低 Site3·76% 与差值 20%，不用自己比。' },
      { x: 40, y: 88, t: 'Bin × Site 交叉表', d: '表格 / 热力图两种页签：精确读数与一眼定位问题 Site 各取所需。' },
    ],
  },
  analysis: {
    src: '/assets/07-analysis.png', w: 2000, h: 1127, cap: '图 5-1 · 单文件分析 · RCONT_01（CPK 0.7945，D 级）',
    hs: [
      { x: 21, y: 10.2, t: '五个分析 tab', d: '单文件分析 / 晶圆图 / 3D Site 对比 / 多文件分析 / 相关性对比；每个 tab 独立选文件、独立筛数据。' },
      { x: 77.5, y: 16.3, t: '参数选择器', d: '搜索或 ↑↓ 切换参数；「上一个 / 下一个」按钮顺序巡检全部测试项。' },
      { x: 75, y: 20.7, t: '图表坞开关', d: '直方图 / 序列分布 / QQ 图 / 箱线图 / 3D 柱状图可同屏共存；拖 ⠿ 手柄拼格、改宽改高，双击复原。' },
      { x: 25.5, y: 26.7, t: '异常值处理', d: '裁剪范围（IQR）或不处理；敏感度严格 1.5×IQR / 宽松 3.0×IQR。右侧五个过滤：忽略无 Limit / 无测试值 / 仅 Bin1 / 仅 Fail / 仅低 CPK。' },
      { x: 60, y: 32, t: '统计带', d: 'N 100 · Mean 2.1966 · STD 0.7567 · CPK 0.7945（D 级 不足）· 3σ / 6σ 区间，随裁剪口径即时重算。' },
      { x: 28, y: 38.5, t: '范围类型', d: 'RDL（文件 RowDataLimit）/ DR / CL（自定义上下限）/ S3 / S4 / S6；叠层 Limit / 3σ / 4σ / 6σ / KDE / 正态自由组合。' },
      { x: 30, y: 63, t: '范围对比表', d: 'RowDataLimit / Data Range / CustomLimit / 3σ / 4σ / 6σ 六种范围的 Low / High / Gap 对照，判断限值宽窄一眼可见。' },
      { x: 71.5, y: 52, t: '直方图 + 框选', d: '按 Site 着色柱 + All Site 背景柱 + KDE + LSL/USL 红虚线；按住左键拖框选子集，右键「新建子集直方图 / 清除选择」。' },
    ],
  },
  wafer: {
    src: '/assets/09-wafer.png', w: 2000, h: 1127, cap: '图 5-2 · 晶圆图 · DEMO_CP_WAFER01.csv（边缘环失效集中）',
    hs: [
      { x: 23, y: 22.8, t: '着色模式', d: '判定结果 / Site / Bin / 参数值四种着色：看失效、看机台差异、看 bin 分布、看数值梯度。' },
      { x: 38.5, y: 22.8, t: '边界圆 + Notch', d: '叠加晶圆轮廓与 notch 方位，失效图案可以和物理片对上方向。' },
      { x: 47.5, y: 22.8, t: '分区模式', d: '中心 / 中间 / 边缘三环分区，配合左侧分区良率表做环带下钻。' },
      { x: 27.5, y: 35, t: '分区良率表', d: '示例：中心区 100.0%、中间区 91.1%、边缘区 72.4%——边缘环明显偏低。' },
      { x: 67, y: 55, t: 'Wafer Map', d: '一格一 die，绿 Pass 红 Fail；示例 317 die / 263 Pass / 54 Fail / 良率 83.0%。工具栏提供下载与缩放复原。' },
      { x: 60, y: 92.5, t: '径向梯度洞察', d: '自动结论：「三环带良率 72.4% ~ 100.0%，极差 27.6 个百分点 → 存在径向梯度，可按环带下钻」。' },
    ],
  },
  site3d: { src: '/assets/08-site3d.png', w: 2000, h: 1127, cap: '图 5-3 · 3D 柱状图（echarts-gl，开发中新增）', hs: [] },
  multifile: { src: '/assets/10-multifile.png', w: 2000, h: 1127, cap: '图 5-4 · 多文件分析 · 四批叠加（直方图 + 箱线图）', hs: [] },
  corr: { src: '/assets/11-correlation.png', w: 2000, h: 1127, cap: '图 5-5 · 相关性对比 · 参数矩阵', hs: [] },
  weight: {
    src: '/assets/14-weight.png', w: 2560, h: 1202, cap: '图 7-1 · 权重画图 · weight_demo.txt（6 测试项 · 24 系列 · Code 0–15）',
    hs: [
      { x: 20, y: 10.5, t: '权重文件', d: '本地 .csv / .txt / .h / .c 声明式格式，≤200 万字符；「仅本页使用，不写入数据库」——看完即走，不污染数据管理。' },
      { x: 27, y: 20, t: '测试项 chips', d: '示例 6 项全选（VREF_TRIM / IBIAS_TRIM / OSC_CAL / DAC_GAIN / ADC_OFF / PLL_LOCK），可全选 / 清空。' },
      { x: 22, y: 24, t: '组内曲线线型', d: '按系列序号指定实线 / 虚线 / 点线；均值线为灰色细虚线；同名声明自动编号。' },
      { x: 86, y: 11.3, t: '显示均值 / 图例', d: '开关只关图表显示；明细表与导出的 xlsx 仍含全部曲线，口径不丢。' },
      { x: 95.3, y: 11.3, t: '导出 Excel', d: '全部曲线 + 均值导出 xlsx，供离线归档与二次计算。' },
      { x: 19, y: 30.2, t: '图表 / 数值明细双页签', d: '逐 Code 数值表与图对照读；每测试项一张独立缩放曲线。' },
    ],
  },
  night: {
    src: '/assets/18-night.png', w: 2560, h: 1202, cap: '图 8-1 · 夜间模式 · 仪表板',
    hs: [
      { x: 84.8, y: 2.9, t: '主题切换按钮', d: '顶栏一键切换；选择跟随账号保存，下次启动仍是你的主题。' },
      { x: 50, y: 23.5, t: '夜间 KPI 带', d: '同一布局换夜间调色板：深色底 + 琥珀强调，Pass/Fail 语义色保持可辨。' },
      { x: 77, y: 48, t: '夜间图表', d: 'ECharts 主题与 CSS 变量同源同步，柱色 / 网格 / 文字对比度均按夜间重新调校。' },
    ],
  },
}

export interface Feat { t: string; d: string; how: string }
export const FEATURES: Record<string, Feat[]> = {
  dashSingle: [
    { t: 'Overview 总览带', d: '程序 / 总记录 / Pass / Fail / Yield / UPH / 测试时长 / 测试开始时间八项基本面。', how: '选文件后先读这条带，确认总量与良率是否符合预期。' },
    { t: '告警横幅 AlertBanner', d: '后端 quality_alerts 逐条给出 message：良率低于目标、CPK 不足参数数、Site 差异过大。', how: '点「展开明细」逐条读，按提示跳对应分析页下钻。' },
    { t: 'Bin 构成 Pareto', d: '失效 bin 降序排列，先解决占比最大的失效模式。', how: '看第一根 Fail 柱的占比决定排查优先级。' },
    { t: 'Site 良率分析', d: '柱 + 折线双表达，自动标注最高 / 最低 Site 与差值。', how: '差值大（示例 Δ20%）时怀疑硬件或接触问题。' },
    { t: 'Bin × Site 交叉表', d: '表格 / 热力图双页签，定位「哪个 Site 集中出哪个 bin」。', how: '热力图找深色格 → 切表格读精确数。' },
    { t: '测试项总览', d: '11 列统计 + CPK 比例条 + Top10 Fail 测试项榜。', how: '按 CPK 比例条扫一眼过程能力短板，点行跳分析页。' },
    { t: 'UPH 卡片', d: '吞吐量与测试时长换算，评估机台效率。', how: '与历史批对比判断测试程序是否变慢。' },
    { t: '保存 HTML 报表', d: '整页结论导出为单文件 HTML，离线分享。', how: '页脚「保存 HTML 报表」，收件人双击即看。' },
  ],
  dashBatch: [
    { t: '批次选择 + 加载报表', d: '下拉选「组合为批次」产物，加载整批统计。', how: '先在 §4 文件列表组合批次，这里才有得选。' },
    { t: '阶段胶囊 StageFilterBar', d: 'CP / FT / QA 阶段全局过滤，一键只看某阶段。', how: '点胶囊切换，整页口径同步收敛。' },
    { t: 'QA 校验条', d: '「QA 数量校验 x/y 通过」：应测 QA 文件数与实测对照。', how: '不满通过时先补 QA 文件再谈放行。' },
    { t: '阶段汇总树 + 良率趋势', d: 'PhaseSummaryTree 逐阶段展开，YieldTrendChart 看批内走势。', how: '展开阶段行读元数据；趋势下滑即工艺漂移信号。' },
    { t: 'Site 良率矩阵 / Bin 汇总', d: '批级 Site × 阶段矩阵与 BatchBinSection 构成。', how: '矩阵深色格 = 问题 Site × 阶段组合。' },
    { t: '导出 Excel / HTML', d: '整批结论两种格式留档。', how: '放行评审用 Excel，邮件分享用 HTML。' },
  ],
  fileList: [
    { t: '上传与拖拽', d: 'CSV 多选或 ZIP 批量包；拖拽到列表区同样触发；ZIP 自动解析为批次。', how: '点「上传文件」看接受格式与解析流程说明。' },
    { t: '搜索 / 筛选 / 排序', d: '文件名 / 程序 / 标签即时过滤；表头内嵌筛选与服务端排序分页。', how: '输入关键字列表即时收敛（复刻可试）。' },
    { t: '组合为批次', d: '新建需 ≥2 文件、追加 1 个即可；批次供仪表板批次良率使用。', how: '勾选文件后点按钮，对话框里选新建 / 追加。' },
    { t: '展开行元数据', d: '完整文件名 / 行列规模 / 测试程序 / 标签一屏读全。', how: '点行首 ▸（复刻可试）。' },
    { t: '批量删除', d: '勾选后一次移除文件及其解析结果。', how: '复刻中带确认与撤销，真实应用为不可逆操作请谨慎。' },
    { t: '数据修复中心', d: '检查孤立 DB 记录 / 孤立磁盘文件 / 产品名缺失 / 重复文件四类不一致。', how: '点「数据修复」跑检查清单（复刻可试）。' },
  ],
  batchData: [
    { t: '汇总条 + 批次搜索', d: '批次数 / 文件数 / 总行数一眼读完；按批次名即时过滤。', how: '搜索框输入 LOT 关键字（复刻可试）。' },
    { t: 'SFTP 未导入目录卡', d: '远端已下载未入库的目录单独成卡，可导入或删除。', how: '点卡上「导入」送入解析链路（复刻可试）。' },
    { t: '批次头展开 / 全部展开', d: '头行聚合指标，展开看文件明细（子批次 / 行列 / 大小）。', how: '点头行或「全部展开」（复刻可试）。' },
    { t: '删批次 / 删子批次 / 移出选中', d: '三级粒度管理批次成员；勾选明细文件可移出批次。', how: '勾选明细行后「移出选中」亮起（复刻可试）。' },
  ],
  viewData: [
    { t: '多文件页签（最多 4 个）', d: '每个文件独立保留过滤与列设置，切换不丢状态。', how: '点页签切换（复刻可试，状态各自保留）。' },
    { t: '显示测试列选择器', d: '可搜索芯片式多选，Enter 全选；元数据列与测试项同列可选。', how: '点列 chips 开关列（复刻可试）。' },
    { t: 'Pass/Fail · Site · 列宽 · 固定列', d: '四组表格控制；固定列把序列号 / Site 钉在左侧横向滚动不丢。', how: '切「仅 Fail」看红格集中项（复刻可试）。' },
    { t: '质量告警 chips + 限值表头', d: '良率 / CPK 不足参数数 / Site 差异三枚 chips；每列表头自带 [Min, Max]。', how: '读表头限值即判定依据，不用另翻限值文件。' },
    { t: '右键三菜单', d: '序列号→高亮此行；表头→复制测试项名 / 展示分布图（N/Mean/STD/CPK 弹窗）；Bin fail 格→定位 Fail 单元格。', how: '在复刻表格上右键试试前两种。' },
    { t: '导出 Excel / CSV', d: 'Excel 走后台作业、CSV 同步下载；内容与当前过滤一致。', how: '先过滤再导出，导出口径即所见口径。' },
  ],
  exportTool: [
    { t: '步骤 1 · 选择参数', d: '可搜索多选 + 全选 / 清空；实时「已选 x / 共 y 个」。', how: '搜索关键字勾选测试项（复刻可试）。' },
    { t: '步骤 2 · 图表配置', d: 'Limit / 3σ / 4σ / 6σ / 正态 / KDE 叠层、柱宽 10–100%、忽略无 Limit。', how: '开关叠层看预览实时变化（复刻可试）。' },
    { t: '步骤 3 · 导出', d: 'Sigma 范围决定同步写入 xlsx 的 Sigma Limit；Excel 内嵌直方图、PPT 汇报版式。', how: '点批量导出看后台作业进度模拟（复刻可试）。' },
    { t: '后台作业 + 进度 chip', d: '作业队列执行，不阻塞页面；完成后可下载。', how: '导出后继续别的操作，进度 chip 会自己走完。' },
  ],
  compare: [
    { t: '双文件 + 序列选择', d: '文件 1（ATE）VS 文件 2（Bench），默认对比前 10 颗序列。', how: '选两份文件、定序列数（复刻可试）。' },
    { t: '测试值判定', d: '每序列 ATE / Bench / Delta / %Diff；超差单元按误差阈值计 fail_count。', how: '调阈值看「超差单元」与通过率变化（复刻可试）。' },
    { t: 'Limit Diff 三规则', d: 'A：Diff 必须为 0；B：B 的 Limit 不更紧；C：双侧变化 ≤ 容差%（默认 30）。', how: '切规则看 Limit Diff Fail 列重判（复刻可试）。' },
    { t: '双视图 + 忽略开关', d: '测试值 / Limit 对比两视图；Ignore No Limit / No Data 排除不可比单元。', how: '切视图读 LSL/USL 双侧对照。' },
    { t: '汇总卡 + 导出', d: '测试项 / 对比单元 / 超差单元 / Limit Diff Fail / 总体通过率五卡；一键导出 Excel。', how: '评审先看通过率卡，再下钻红行。' },
  ],
  gage: [
    { t: '8 Site 槽位选文件', d: '按测试机 Site 组织量测系统分析输入，可复用文件。', how: '给至少两个槽位选文件（复刻可试）。' },
    { t: 'Bin1 / 无 Limit 过滤', d: '只统计 Pass 数据与有规格限的测试项，保证 Gage 口径干净。', how: '默认勾选，按需放开。' },
    { t: '生成 + 下载 xlsx', d: '逐 Site 给出 N / Mean / STD / 极差等量测重复性指标。', how: '生成后读 Site 间 STD 差异判断量测系统稳定性。' },
  ],
  buyoff: [
    { t: 'FT / QA1 / QA2 三角色', d: '量产签核流程的三方数据各自就位，互斥分配避免口径混用。', how: '三个下拉各选文件，选过的自动从其它下拉消失（复刻可试）。' },
    { t: '共同测试项分析', d: '共同 / 部分共有 / 独有三类标签计数，签核前先看覆盖度。', how: '点「分析共同测试项」读 chips（复刻可试）。' },
    { t: '生成 Buyoff Form', d: '三方对照表一键 xlsx，供放行签核归档。', how: '≥2 角色就位后生成。' },
  ],
  sftpBrowse: [
    { t: '连接面板与保存配置', d: '主机 / 端口 / 账号，或加载已保存配置一键连接；密码加密存储在服务端配置。', how: '勾选保存后下次一键连；可存多套服务器。' },
    { t: '面包屑目录浏览', d: '点任意一级跳回；目录树式浏览远端文件系统。', how: '点面包屑或目录行导航（复刻可试）。' },
    { t: '类型过滤 + 即时搜索', d: '「仅 CSV」等类型开关 + 文件名过滤，大目录快速定位。', how: '关掉仅 CSV 可看机台日志（复刻可试）。' },
    { t: '下载 / 解析 / 批量', d: '下载存本地；解析直接入库；勾选可批量下载。', how: '要分析的文件点「解析」省手动搬运（复刻可试）。' },
    { t: '目录统计', d: '文件夹数 / 文件数 / 总大小，当前目录规模一目了然。', how: '读统计行判断是否值得整目录拉取。' },
  ],
  weight: [
    { t: '本地载入不入库', d: '.csv / .txt / .h / .c，≤200 万字符；关掉即走。', how: '「重新选择」换文件；不影响数据管理清单。' },
    { t: '同名自动编号 + 逐点均值', d: '同名多条声明视为同组系列，均值线灰色细虚线。', how: '看均值线判断组内一致性。' },
    { t: '测试项 chips + 线型槽位', d: '全选 / 清空测试项；组内曲线按系列序号实线 / 虚线 / 点线。', how: '系列多时靠线型区分而非只靠颜色。' },
    { t: '图表 / 数值明细 + 导出', d: '双页签对照读；导出 xlsx 含全部曲线与均值（显示开关不影响导出）。', how: '归档用导出，不用截图。' },
  ],
  analysisSingle: [
    { t: '五图坞拼格', d: '直方图 / 序列分布 / QQ 图 / 箱线图 / 3D 柱状图勾选共存，拖手柄排序改宽高。', how: '看趋势加序列分布、看正态性加 QQ、看分组差异加箱线图。' },
    { t: '异常值处理 + 敏感度', d: '裁剪范围 / 不处理；严格 1.5×IQR / 宽松 3.0×IQR。', how: '开关裁剪对比 CPK 变化（下方演示可玩）。' },
    { t: '五个数据过滤', d: '忽略无 Limit / 忽略无测试值 / 仅 Bin1 / 仅 Fail 项 / 仅低 CPK。', how: '巡检短板时开「仅低 CPK」直接排队处理。' },
    { t: '范围类型与范围对比表', d: 'RDL / DR / CL / S3 / S4 / S6 六种口径 Low / High / Gap 对照。', how: '怀疑限值过紧时读 Gap 列找证据。' },
    { t: '框选子集面板', d: '直方图 / 序列图拖框 → 右键新建子集直方图；面板给 N / Mean / STD / CPK / 规格限。', how: '下方演示直接拖框试试（复刻可试）。' },
    { t: 'CPK 分级与阈值联动', d: '默认 A≥1.67 / B≥1.33 / C≥1.0 / D<1.0，跟随系统设置自定义。', how: '改阈值后全平台分级与告警同步（§8 可试）。' },
  ],
  wafer: [
    { t: '四种着色模式', d: '判定 / Site / Bin / 参数值，一张图回答四类问题。', how: '怀疑机台切 Site、怀疑工艺梯度切参数值。' },
    { t: '边界圆 + Notch', d: '物理方位对齐，失效图案可与实物片对照。', how: '默认开启，截图留档时保留。' },
    { t: '三环分区 + 分区良率表', d: '中心 / 中间 / 边缘环带下钻，极差自动算。', how: '边缘环偏低 → 查边缘接触 / 探针卡磨损。' },
    { t: '径向梯度洞察', d: '自动生成「极差 x 个百分点 → 存在径向梯度」结论句。', how: '读结论句决定是否需要环带下钻。' },
  ],
  site3d: [
    { t: '三维柱阵', d: 'Site 维度 × 数值分布同时展开，一眼看出哪个 Site 整体偏移。', how: '单文件分析图表坞勾选「显示3D柱状图」。' },
    { t: '旋转 / 缩放视角', d: '拖拽旋转、滚轮缩放，从侧面看分布厚度差异。', how: '侧视角看柱高包络的错位。' },
  ],
  multifile: [
    { t: '多文件同参数叠加', d: '直方图按文件着色叠加，批间漂移一屏可见。', how: '选多文件 + 同一参数；示例 LOTA–LOTD 均值逐批右移 = 工艺漂移典型形态。' },
    { t: '箱线图五数概括', d: '并排箱线读中位数 / 四分位 / 须 / 离群点。', how: '箱体变宽 = 分散度恶化；中位数跳变 = 校准事件。' },
    { t: '独立过滤', d: '本 tab 的文件选择与过滤不与单文件 tab 串扰。', how: '放心改过滤，不会弄乱别的视角。' },
  ],
  corr: [
    { t: '相关性矩阵', d: '勾选参数后计算 Pearson 矩阵，热力格色阶即强度。', how: '先扫深色格找强联动对。' },
    { t: '格 → 散点 + 拟合', d: '点任意格展开散点与拟合线，验证线性假设。', how: '散点弯曲 = 非线性关系，r 会低估联动。' },
    { t: '找「谁跟着谁动」', d: '温度敏感项与参考源项的联动排查利器。', how: '强相关对结合工艺知识定因果方向。' },
  ],
  admin: [
    { t: '账号 KPI 四卡', d: '总用户 / 活跃 / 锁定 / 管理员，随操作即时重算。', how: '锁定数非零时先查审计失败登录。' },
    { t: '创建 / 编辑 / 角色', d: '显示名 + 角色（user / administrator）；编辑不改用户名。', how: '「创建账号」对话框填三项（复刻可试）。' },
    { t: '禁用 / 启用 / 解锁 / 重置密码', d: '状态四操作；锁定账号解锁后限流计数清零。', how: '行内按钮直接操作，带确认与撤销（复刻可试）。' },
    { t: '删除 + 自我保护', d: '删除不可逆（真实应用）；不能操作自己。', how: '复刻中删除带撤销演示；真实应用请先交接。' },
    { t: '审计筛选三件套', d: '事件下拉（10 类）/ 账号 / 起止日期 + 查询重置。', how: '选「登录失败」+ 账号定位限流事件（复刻可试）。' },
    { t: '详情摘要展开', d: 'reason / remaining_attempts / 变更字段逐条留痕。', how: '展开行读 reason=bad_password，remaining_attempts=4 这类依据。' },
  ],
}

/* ---------- 复刻种子数据（合成，红线见 check.mjs） ---------- */
export const FILES = [
  { id: 101, name: 'DEMO_FT_LOTA.csv', prod: 'DEMO_P1', stage: 'FT', fmt: 'CTA8290D', tag: 'LOT-A', size: '286.4 KB', rows: 100, cols: 271 },
  { id: 102, name: 'DEMO_FT_LOTB.csv', prod: 'DEMO_P1', stage: 'FT', fmt: 'CTA8290D', tag: 'LOT-B', size: '286.4 KB', rows: 100, cols: 271 },
  { id: 103, name: 'DEMO_FT_LOTC.csv', prod: 'DEMO_P1', stage: 'FT', fmt: 'CTA8290D', tag: 'LOT-C', size: '286.4 KB', rows: 100, cols: 271 },
  { id: 104, name: 'DEMO_FT_LOTD.csv', prod: 'DEMO_P1', stage: 'FT', fmt: 'CTA8290D', tag: 'LOT-D', size: '286.4 KB', rows: 100, cols: 271 },
  { id: 105, name: 'DEMO_CP_WAFER01.csv', prod: 'DEMO_P1', stage: 'CP', fmt: 'CTA8290D', tag: 'W01', size: '412.7 KB', rows: 317, cols: 198 },
]
export const BT_DATA = [
  { name: 'BATCH_FT_2026Q4_A（LOTA+LOTB）', phases: { FT: { files: [['DEMO_FT_LOTA.csv', 100, 91, 'CTA8290D', '2026-10-02'], ['DEMO_FT_LOTB.csv', 100, 89, 'CTA8290D', '2026-10-03']], rows: 200, pass: 180 }, QA1: { files: [['DEMO_FT_LOTA_QA1.csv', 40, 39, 'CTA8290D', '2026-10-04']], rows: 40, pass: 39 }, QA2: { files: [], rows: 0, pass: 0 } } },
  { name: 'BATCH_FT_2026Q4_B（LOTC+LOTD）', phases: { FT: { files: [['DEMO_FT_LOTC.csv', 100, 88, 'CTA8290D', '2026-10-08'], ['DEMO_FT_LOTD.csv', 100, 87, 'CTA8290D', '2026-10-09']], rows: 200, pass: 175 }, QA1: { files: [['DEMO_FT_LOTC_QA1.csv', 40, 40, 'CTA8290D', '2026-10-10']], rows: 40, pass: 40 }, QA2: { files: [['DEMO_FT_LOTD_QA2.csv', 40, 38, 'CTA8290D', '2026-10-11']], rows: 40, pass: 38 } } },
] as { name: string; phases: Record<string, { files: (string | number)[][]; rows: number; pass: number }> }[]
export const BA_BATCHES = [
  { name: 'BATCH_FT_2026Q4_A', open: true, files: [['DEMO_FT_LOTA.csv', '—', 100, 271, '286.4 KB'], ['DEMO_FT_LOTB.csv', 'SUB1', 100, 271, '286.4 KB']] },
  { name: 'BATCH_FT_2026Q4_B', open: false, files: [['DEMO_FT_LOTC.csv', '—', 100, 271, '286.4 KB'], ['DEMO_FT_LOTD.csv', 'SUB1', 100, 271, '286.4 KB']] },
] as { name: string; open: boolean; files: (string | number)[][] }[]
export const VD_COLS = [
  { key: 'serial', label: 'Serial', sticky: true, test: false, lo: 0, hi: 0 },
  { key: 'site', label: 'Site', sticky: true, test: false, lo: 0, hi: 0 },
  { key: 'bin', label: 'SW_Bin', sticky: false, test: true, lo: 1, hi: 1 },
  { key: 'rcont', label: 'RCONT_01', sticky: false, test: true, lo: 0, hi: 4 },
  { key: 'vref', label: 'VREF_TRIM', sticky: false, test: true, lo: 1.1, hi: 1.3 },
  { key: 'ibias', label: 'IBIAS_TRIM', sticky: false, test: true, lo: 9, hi: 12 },
  { key: 'osc', label: 'OSC_CAL', sticky: false, test: true, lo: 23, hi: 26 },
]
export function vdRows(fi: number) {
  const n = normalGen(mulberry32(777 + fi * 131))
  const rows: Record<string, number | string | boolean>[] = []
  for (let i = 1; i <= 12; i++) {
    const site = 'S' + (((i - 1) % 4) + 1)
    const rcont = 2.2 + 0.72 * n() + (site === 'S3' ? 0.5 : 0)
    const vref = 1.2 + 0.06 * n()
    const ibias = 10.5 + 0.8 * n()
    const osc = 24.5 + 0.8 * n()
    const fail = rcont < 0 || rcont > 4 || vref < 1.1 || vref > 1.3 || ibias < 9 || ibias > 12 || osc < 23 || osc > 26
    rows.push({ serial: i, site, bin: fail ? 4 : 1, rcont, vref, ibias, osc, fail })
  }
  return rows
}
export const EX_PARAMS = ['RCONT_01', 'VREF_TRIM', 'IBIAS_TRIM', 'OSC_CAL', 'DAC_GAIN', 'ADC_OFF', 'PLL_LOCK', 'IDDQ', 'VDD_CORE', 'TEMP_SENS', 'SHADOW_REG2', 'FREQ_MAX']
export const FC_FILES = ['DEMO_FT_LOTD.csv', 'DEMO_FT_LOTC.csv', 'DEMO_FT_LOTB.csv', 'DEMO_BENCH_REF.csv']
export const FC_BASE = [
  ['RCONT_01', 0, 4, 0, 4, 'ohm'],
  ['VREF_TRIM', 1.1, 1.3, 1.1, 1.32, 'V'],
  ['IBIAS_TRIM', 9, 12, 9.2, 12, 'uA'],
  ['OSC_CAL', 23, 26, 23, 25.4, 'MHz'],
  ['DAC_GAIN', 0.9, 1.1, 0.9, 1.1, 'x'],
  ['ADC_OFF', -2, 2, -2, 2, 'mV'],
] as (string | number)[][]
export const GG_FILES = ['DEMO_FT_LOTA.csv', 'DEMO_FT_LOTB.csv', 'DEMO_FT_LOTC.csv', 'DEMO_FT_LOTD.csv']
export const AU_EVENTS = ['登录成功', '登录失败', '账号锁定', '账号解锁', '自助修改密码', '管理员重置密码', '创建账号', '更新账号', '删除账号', '存储路径变更']
export const AU_SEED = [
  { t: '2026-11-12 10:44:32', ev: '登录成功', op: 'admin', tg: 'admin', ip: '127.0.0.1', d: '—' },
  { t: '2026-11-12 10:43:58', ev: '登录失败', op: '—', tg: 'demo_zhang', ip: '127.0.0.1', d: 'reason=bad_password，remaining_attempts=4' },
  { t: '2026-11-12 10:43:41', ev: '登录失败', op: '—', tg: 'demo_zhang', ip: '127.0.0.1', d: 'reason=bad_password，remaining_attempts=3' },
  { t: '2026-11-12 10:40:12', ev: '账号锁定', op: 'system', tg: 'demo_li', ip: '127.0.0.1', d: '连续失败达到上限' },
  { t: '2026-11-12 10:31:07', ev: '创建账号', op: 'admin', tg: 'demo_li', ip: '127.0.0.1', d: 'role=user' },
  { t: '2026-11-12 10:30:52', ev: '创建账号', op: 'admin', tg: 'demo_zhang', ip: '127.0.0.1', d: 'role=user' },
  { t: '2026-11-12 10:29:16', ev: '更新账号', op: 'admin', tg: 'user', ip: '127.0.0.1', d: 'display_name: 普通用户' },
  { t: '2026-11-11 18:02:44', ev: '存储路径变更', op: 'admin', tg: '—', ip: '127.0.0.1', d: 'data: D:/old → ~/LQ-DataPrase/data（重启后迁移）' },
  { t: '2026-11-11 17:55:03', ev: '管理员重置密码', op: 'admin', tg: 'user', ip: '127.0.0.1', d: '—' },
  { t: '2026-11-11 09:12:40', ev: '登录成功', op: 'user', tg: 'user', ip: '127.0.0.1', d: '—' },
  { t: '2026-11-10 15:26:19', ev: '自助修改密码', op: 'demo_zhang', tg: 'demo_zhang', ip: '127.0.0.1', d: '—' },
  { t: '2026-11-10 08:00:02', ev: '登录成功', op: 'admin', tg: 'admin', ip: '127.0.0.1', d: '—' },
]
export const UM_SEED = [
  { u: 'admin', disp: '管理员', role: 'administrator', active: true, locked: false, cr: '2026-11-12 10:07', last: '2026-11-12 10:44', self: true },
  { u: 'user', disp: '普通用户', role: 'user', active: true, locked: false, cr: '2026-11-12 10:07', last: '2026-11-11 09:12', self: false },
  { u: 'demo_zhang', disp: '张三', role: 'user', active: true, locked: false, cr: '2026-11-12 10:30', last: '2026-11-10 15:26', self: false },
  { u: 'demo_li', disp: '李四', role: 'user', active: false, locked: true, cr: '2026-11-12 10:31', last: '—', self: false },
]
export const SF_NODES: Record<string, { dirs?: string[]; files?: string[][] }> = {
  home: { dirs: ['datalogs', 'logs'] },
  'home/logs': { files: [['tester_02.log', '44.1 KB', 'log']] },
  'home/datalogs': { dirs: ['2026Q4'] },
  'home/datalogs/2026Q4': { dirs: ['LOTA', 'LOTB', 'LOTC'] },
  'home/datalogs/2026Q4/LOTA': { files: [['DEMO_FT_LOTA.csv', '286.4 KB', 'csv'], ['Sum_LOTA.csv', '12.0 KB', 'csv']] },
  'home/datalogs/2026Q4/LOTB': { files: [['DEMO_FT_LOTB.csv', '286.4 KB', 'csv']] },
  'home/datalogs/2026Q4/LOTC': { files: [['DEMO_FT_LOTC.csv', '286.4 KB', 'csv'], ['Sum_LOTC.csv', '12.0 KB', 'csv'], ['tester_01.log', '44.1 KB', 'log']] },
}
export const SF_CORPUS = [
  { path: 'home/datalogs/2026Q4/LOTC/DEMO_FT_LOTC.csv', sum: false, log: false, lines: ['Part_No,Site,SW_Bin,RCONT_01,SHADOW_REG2,VREF_TRIM', '1,S1,1,2.1966,ShadowReg2=0x3F,1.204', '2,S3,4,4.1022,ShadowReg2=0x41,1.291'] },
  { path: 'home/datalogs/2026Q4/LOTC/tester_01.log', sum: false, log: true, lines: ['[12:01:22] ShadowReg2 write ok addr=0x3F', '[12:02:01] ShadowReg2 readback mismatch retry=1'] },
  { path: 'home/datalogs/2026Q4/LOTA/DEMO_FT_LOTA.csv', sum: false, log: false, lines: ['Part_No,Site,SW_Bin,RCONT_01,SHADOW_REG2', '1,S1,1,2.0114,ShadowReg2=0x3E', '2,S2,1,2.2210,ShadowReg2=0x3F'] },
  { path: 'home/datalogs/2026Q4/LOTC/Sum_LOTC.csv', sum: true, log: false, lines: ['Summary,Yield,87.00', 'ShadowReg2,mean,0x3F'] },
  { path: 'home/logs/tester_02.log', sum: false, log: true, lines: ['[09:14] ShadowReg2 calibration drift +2LSB'] },
  { path: 'home/datalogs/2026Q4/LOTB/DEMO_FT_LOTB.csv', sum: false, log: false, lines: ['Part_No,Site,SW_Bin,VREF_TRIM,IBIAS_TRIM', '1,S1,1,1.2011,10.42'] },
]
export const CORR_P = ['RCONT', 'VREF', 'IBIAS', 'OSC', 'DAC', 'ADC', 'PLL', 'IDDQ']
export const CORR_M = (() => {
  const rng = mulberry32(88)
  const m: number[][] = Array.from({ length: 8 }, (_, i) => Array.from({ length: 8 }, (_, j) => (i === j ? 1 : 0)))
  const set = (i: number, j: number, v: number) => { m[i][j] = v; m[j][i] = v }
  set(0, 7, 0.86); set(1, 2, 0.78); set(3, 4, -0.62); set(5, 6, 0.41); set(0, 1, 0.22); set(2, 7, 0.35); set(4, 5, -0.18); set(6, 7, 0.12)
  for (let a = 0; a < 8; a++) for (let b = a + 1; b < 8; b++) if (!m[a][b]) set(a, b, Math.round((rng() - 0.5) * 40) / 100)
  return m
})()
export const WF_DIES = (() => {
  const rng = mulberry32(42)
  const dies: { x: number; y: number; r: number; site: number; bin: number; val: number; fail: boolean }[] = []
  for (let y = 24; y <= 296; y += 14) for (let x = 24; x <= 296; x += 14) {
    const dx = x - 160, dy = y - 160, d = Math.sqrt(dx * dx + dy * dy)
    if (d > 138) continue
    const r = d / 138
    const fail = rng() < 0.02 + 0.38 * Math.pow(r, 3)
    dies.push({ x, y, r, site: 1 + ((dx > 0 ? 1 : 0) + (dy > 0 ? 2 : 0)), bin: fail ? 2 + ((x + y) % 3) : 1, val: 2.2 + 0.9 * r + (rng() - 0.5) * 0.5, fail })
  }
  return dies
})()
export const WT_DEFAULT = `double VREF_TRIM[16] = {1.1909,1.1925,1.1948,1.1972,1.1995,1.2018,1.2040,1.2061,1.2080,1.2097,1.2110,1.2120,1.2126,1.2128,1.2127,1.2124};
double VREF_TRIM[16] = {1.1880,1.1901,1.1926,1.1952,1.1977,1.2001,1.2024,1.2046,1.2066,1.2084,1.2099,1.2110,1.2118,1.2122,1.2123,1.2121};
double IBIAS_TRIM[16] = {10.3045,10.3320,10.3610,10.3915,10.4230,10.4555,10.4890,10.5230,10.5575,10.5920,10.6265,10.6605,10.6940,10.7260,10.7560,10.7242};
double OSC_CAL[16] = {24.02,24.05,24.09,24.14,24.20,24.27,24.35,24.44,24.54,24.65,24.77,24.90,25.04,25.19,25.35,25.52};`
export const SERVER_URL = 'https://125.69.67.169:18124'