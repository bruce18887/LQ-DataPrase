# 01 产品概览

它解决什么问题、由什么构成、数据放在哪里、本书怎么读。

LQ-DataPrase 面向半导体量产测试（CP / FT）场景：测试机每天产出大量 CSV datalog，工程师需要快速回答「这批良率多少、哪个 Site 拖后腿、哪个参数 CPK 不足、失效集中在晶圆哪个环带」。平台把这些问题的答案做成了开箱即用的页面，而不是让工程师自己写脚本。

| 7 | 25 | 0 |
| --- | --- | --- |
| 主功能页（仪表板 / 数据 / 分析 / SFTP / 权重 / 设置 / 管理） | 子页签与视角（数据 7 + 分析 5 + 仪表板 2 + SFTP 2 + 设置 7 + 管理 2） | 外部依赖服务（内置后端 + 本地数据库，离线可用） |

## 技术架构

<svg viewBox="0 0 860 330" role="img" aria-label="架构图：Electron 壳内含 Vue3 渲染进程与 Django 后端，本地 SQLite 存储，远端 SFTP 可选" style="width:100%;height:auto;background:var(--vp-c-bg-soft);border:1px solid var(--vp-c-border);border-radius:12px">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 10 5 0 10z" fill="var(--vp-c-text-2)"/></marker></defs>
  <rect x="10" y="10" width="560" height="310" rx="14" fill="var(--vp-c-bg)" stroke="var(--vp-c-border)" stroke-width="1.2"/>
  <text x="30" y="36" fill="var(--vp-c-brand-1)" font-size="13" font-weight="700">Electron 33 桌面壳（单实例锁 · 后端进程生命周期 · IPC 桥）</text>
  <rect x="30" y="52" width="240" height="150" rx="10" fill="var(--vp-c-brand-soft)" stroke="var(--vp-c-brand-1)" stroke-width="1.4"/>
  <text x="46" y="78" fill="var(--vp-c-brand-1)" font-size="13" font-weight="700">渲染进程 · Vue 3.5</text>
  <text x="46" y="100" fill="var(--vp-c-text-2)" font-size="11">Element Plus 2.14 · Pinia 3</text>
  <text x="46" y="120" fill="var(--vp-c-text-2)" font-size="11">ECharts 6.1（+gl 2.1 三维）</text>
  <text x="46" y="140" fill="var(--vp-c-text-2)" font-size="11">ag-Grid 35 大数据表格</text>
  <text x="46" y="160" fill="var(--vp-c-text-2)" font-size="11">Vite 8 构建 · 双主题 CSS 变量</text>
  <text x="46" y="184" fill="var(--vp-c-text-2)" font-size="11">仪表板 / 数据 / 分析 / SFTP / 权重 / 设置</text>
  <rect x="310" y="52" width="240" height="150" rx="10" fill="var(--vp-c-brand-soft)" stroke="var(--vp-c-brand-1)" stroke-width="1.4"/>
  <text x="326" y="78" fill="var(--vp-c-brand-1)" font-size="13" font-weight="700">内嵌后端 · Django 6.0.9 + DRF</text>
  <text x="326" y="100" fill="var(--vp-c-text-2)" font-size="11">/api/v1 REST · JWT 登录与限流</text>
  <text x="326" y="120" fill="var(--vp-c-text-2)" font-size="11">解析 / 统计 / 晶圆 / 相关性服务</text>
  <text x="326" y="140" fill="var(--vp-c-text-2)" font-size="11">导出作业队列（Excel / PPT）</text>
  <text x="326" y="160" fill="var(--vp-c-text-2)" font-size="11">SFTP 客户端与搜索引擎</text>
  <text x="326" y="184" fill="var(--vp-c-text-2)" font-size="11">PyInstaller 打包为单文件 exe</text>
  <path d="M270 120 H310" stroke="var(--vp-c-text-2)" stroke-width="1.4" fill="none" marker-end="url(#arr)"/>
  <text x="272" y="112" fill="var(--vp-c-text-2)" font-size="11">HTTP</text>
  <rect x="30" y="230" width="240" height="70" rx="10" fill="var(--vp-c-bg)" stroke="var(--vp-c-border)" stroke-width="1.2"/>
  <text x="46" y="258" fill="var(--vp-c-text-1)" font-size="13">SQLite 数据库</text>
  <text x="46" y="280" fill="var(--vp-c-text-2)" font-size="11">文件元数据 / 设置 / 审计</text>
  <rect x="310" y="230" width="240" height="70" rx="10" fill="var(--vp-c-bg)" stroke="var(--vp-c-border)" stroke-width="1.2"/>
  <text x="326" y="258" fill="var(--vp-c-text-1)" font-size="13">本地媒体目录</text>
  <text x="326" y="280" fill="var(--vp-c-text-2)" font-size="11">原始 CSV / 解析产物（路径可配置）</text>
  <path d="M430 202 V230" stroke="var(--vp-c-text-2)" stroke-width="1.4" fill="none" marker-end="url(#arr)"/>
  <path d="M150 202 V230" stroke="var(--vp-c-text-2)" stroke-width="1.4" fill="none" marker-end="url(#arr)"/>
  <rect x="620" y="52" width="230" height="100" rx="10" fill="var(--vp-c-bg)" stroke="var(--vp-c-border)" stroke-width="1.2"/>
  <text x="636" y="80" fill="var(--vp-c-text-1)" font-size="13">远端 SFTP 服务器（可选）</text>
  <text x="636" y="102" fill="var(--vp-c-text-2)" font-size="11">浏览 / 下载 / 解析入库</text>
  <text x="636" y="122" fill="var(--vp-c-text-2)" font-size="11">文件名 / 内容 / 列名搜索</text>
  <path d="M550 100 H620" stroke="var(--vp-c-text-2)" stroke-width="1.4" fill="none" stroke-dasharray="5 4" marker-end="url(#arr)"/>
  <rect x="620" y="180" width="230" height="70" rx="10" fill="var(--vp-c-bg)" stroke="var(--vp-c-border)" stroke-width="1.2"/>
  <text x="636" y="208" fill="var(--vp-c-text-1)" font-size="13">Excel 加载项（VBA）</text>
  <text x="636" y="230" fill="var(--vp-c-text-2)" font-size="11">把分布表送进工程师的 Excel</text>
  <path d="M550 210 H620" stroke="var(--vp-c-text-2)" stroke-width="1.4" fill="none" stroke-dasharray="5 4" marker-end="url(#arr)"/>
</svg>

## 功能地图

见封面八张功能卡，或左侧目录逐章巡礼。每章覆盖该页**全部**子功能：功能卡给口径与「怎么用」，复刻界面给上手试的机会。

<div class="intro-note">本介绍书所有截图来自演示环境（版本见顶栏徽标），数据为合成演示数据（DEMO_* 文件）；复刻界面中的账号与记录同样均为合成样例，不含任何真实量产信息。</div>