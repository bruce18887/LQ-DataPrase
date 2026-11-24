# 04 数据管理 · 七页签

文件列表 / 组合数据 / 查看数据 / 导出工具 / 文件对比 / Gage Summary / Buyoff Form——数据进入平台后的全部操作。七个页签全部做成可操作复刻。

## 文件列表

<FileListMock />

<FeatureCards k="fileList" accent="#0d9488" />

文件的「隐藏」是**软隐藏**：隐藏后该文件不再出现在分析、仪表板、导出等选文件的下拉里，
但仍留在本页文件列表（带「已隐藏」徽标、置灰显示），可用工具栏「隐藏状态」筛选找回并
随时取消隐藏。组合数据、修复中心与存储统计不受影响——隐藏不会删除数据，磁盘占用照算。

## 组合数据

<BatchDataMock />

<FeatureCards k="batchData" accent="#0d9488" />

组合是供实验室调试使用的数据集，可把已上传文件归入同一组合，再用可选批次号区分组合内的来源批次。
每个文件最多属于一个组合；未归组文件仍可在文件列表、查看数据及分析页面使用。点击「存量归组」可一次归入全部未分组文件，
对话框会再次显示文件数供确认；批次号留空时保留文件原值，不从文件名或目录自动猜测。

组合成员可显示手动标签与系统标签：手动标签继续由用户维护，系统标签由组合名和可选批次号生成，二者互不覆盖。
重命名组合后，其系统标签同步更新，无需逐文件修改。

页面下方的「来源批次目录」仍负责管理 ZIP、目录与 SFTP 导入形成的物理批次，包括目录查看、文件展开与删除。
组合不会改写或替代这些物理批次，只提供面向实验室调试的业务视图。

## 查看数据

<ViewDataMock />

<FeatureCards k="viewData" accent="#0d9488" />

## 导出工具

<ExportWizardMock />

<FeatureCards k="exportTool" accent="#0d9488" />

<div class="intro-note">导出图表的像素密度由「系统设置 → 显示设置 → 图表 DPI」控制（72–600，默认 100 已按 Excel 嵌入尺寸调优）。</div>

## 文件对比

<CompareMock />

<FeatureCards k="compare" accent="#0d9488" />

## Gage Summary

<GageMock />

<FeatureCards k="gage" accent="#0d9488" />

## Buyoff Form

<BuyoffMock />

<FeatureCards k="buyoff" accent="#0d9488" />