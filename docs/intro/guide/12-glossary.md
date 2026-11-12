# 12 术语表

阅读截图与复刻界面时会遇到的半导体与统计词汇。

| 术语 | 释义 |
| --- | --- |
| CP / FT | Chip Probing（晶圆级测试）与 Final Test（封装后终测）；平台按阶段区分文件与报表口径 |
| QA1 / QA2 | 出货前质量抽检环节；Buyoff Form 按 FT / QA1 / QA2 三角色对照签核 |
| Die | 晶圆上的单个芯片粒；晶圆图一格即一 die |
| Site | 测试机并行工位；Site 间良率差异常指向硬件或接触问题 |
| Bin | 测试结果分箱：Pass bin（常为 Bin1）与各类 Fail bin；Bin 构成即良率的结构分解 |
| Wafer Map | 按 X/Y 坐标把 die 判定画回晶圆平面，用于看失效的空间图案 |
| Notch | 晶圆边缘的定位缺口；晶圆图叠加它以便与物理片对齐方位 |
| LSL / USL | 规格下限 / 上限；直方图上的红色虚线，超限即 Fail 判定依据之一 |
| RDL / DR / CL | 范围类型：文件 RowDataLimit / Data Range / CustomLimit（自定义上下限）；另有 S3/S4/S6 sigma 口径 |
| CPK | 过程能力指数：min(USL−μ, μ−LSL) / 3σ；衡量分布相对规格限的余量 |
| IQR 裁剪 | 以四分位距的 1.5×（严格）或 3.0×（宽松）为界剔除离群点后再统计 |
| KDE | 核密度估计：直方图之上的平滑分布曲线 |
| UPH | Units Per Hour，测试吞吐量指标，仪表板 KPI 之一 |
| Pareto | 按占比降序排列的构成图：先解决占比最大的失效 bin |
| Gage Summary | 量测系统分析报表：按 Site 槽位汇总重复性指标，判断量测稳定性 |
| Buyoff Form | 量产放行签核表：FT / QA1 / QA2 三方数据对照，xlsx 归档 |
| fnmatch | shell 风格通配符匹配（* / ?），SFTP 搜索的名称模式语法 |
| SFTP | SSH File Transfer Protocol；平台经它浏览与取回远端测试数据 |
| datalog | 测试机产出的逐颗记录文件（本平台以 CSV 承载） |
| trim / code | 校准权重逐点声明：每个 Code 一个权重值；权重画图页逐点画曲线并叠加同名均值 |