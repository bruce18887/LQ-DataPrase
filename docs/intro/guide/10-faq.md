# 10 常见问题

<details class="faq"><summary>支持哪些上传格式？上传后发生了什么？</summary><div class="faq-a">CSV 单文件 / 多选，以及 ZIP 批量包（自动解析为批次）。上传后后端自动解析：识别 CP/FT 阶段、测试程序、限值与测试列，写入本地数据库；文件列表可见解析状态与行列规模，失败会给出原因。</div></details>

<details class="faq"><summary>数据存在哪里？会出本机吗？</summary><div class="faq-a">SQLite 数据库 + 本地媒体目录，落盘位置可在「系统设置 → 存储路径」迁移（需重启并迁移存量）。桌面形态完全离线运行；只有主动使用 SFTP 功能时才连接你指定的服务器。</div></details>

<details class="faq"><summary>CPK 的 A/B/C/D 级怎么划？能改吗？</summary><div class="faq-a">默认 A≥1.67、B≥1.33、C≥1.0、D&lt;1.0。「系统设置 → CPK 阈值」可自定义，改完全平台分级、告警与导出同步生效（§8 复刻可试）。示例 RCONT_01 的 CPK 0.7945 落在 D 级（不足）。</div></details>

<details class="faq"><summary>有「导出中心」或任务列表页吗？</summary><div class="faq-a">没有独立页面。批量导出 Excel / PPT 走后台作业队列，进度以按钮旁的进度 chip 显示，完成后可下载；页面可继续操作。单文件导出 Excel 同样走作业、CSV 为同步下载。</div></details>

<details class="faq"><summary>文件对比的规则 C 到底怎么判？</summary><div class="faq-a">规则 C 是双侧容差：LSL 与 USL 各自相对文件 1 的变化百分比都必须 ≤ 变化容差（默认 30%）。规则 A 要求 Limit Diff 为 0；规则 B 要求文件 2 的 Limit 不更紧。测试值判定另按误差阈值（默认 3%）计超差单元。</div></details>

<details class="faq"><summary>Gage Summary / Buyoff Form 最少要几个文件？</summary><div class="faq-a">Gage：8 个 Site 槽位中至少 2 个槽位选了文件（同一文件可复用）。Buyoff：FT / QA1 / QA2 三角色中至少 2 个角色分配了文件，且分配互斥。两者都默认只选 Bin1，产物为 xlsx。</div></details>

<details class="faq"><summary>框选子集怎么用？会影响原图统计吗？</summary><div class="faq-a">在直方图 / 序列分布图上按住左键拖框，右键菜单「新建子集直方图」生成子集面板（N / Mean / STD / CPK / 规格限），「清除选择」复原。子集是独立视图，不改原图过滤口径。</div></details>

<details class="faq"><summary>SFTP 搜索为什么有时显示「引擎 client」？</summary><div class="faq-a">平台优先探测服务器端 grep 加速；服务器不支持 exec、或关键词含非 ASCII 字符等情况下自动回落客户端扫描。状态条会写明回落原因（如「Channel closed.」），结果口径一致，只是速度换兼容。</div></details>

<details class="faq"><summary>晶圆图的 Fail 判定和直方图过滤是一回事吗？</summary><div class="faq-a">不是。晶圆图始终画全部 die，数据筛选不影响它；未选参数时按全部测试项的限值判 Fail，选参数后按该参数判定。直方图 / 统计带则跟随当前过滤与裁剪口径。</div></details>

<details class="faq"><summary>哪些设置改完要重启？</summary><div class="faq-a">连接形态（本机内嵌 / 远端）与存储路径需重启（路径还会触发存量迁移）。渲染器、DPI、表格行为、CPK 阈值、导出模板、SFTP 超时均为保存即生效。</div></details>

<details class="faq"><summary>密码输错被限流怎么办？</summary><div class="faq-a">连续失败会触发登录限流并可能锁定账号，审计中记录原因与剩余尝试次数。联系管理员在「用户管理」解锁；限流与审计正是为了防止暴力尝试。</div></details>

<details class="faq"><summary>权重文件会进数据库吗？</summary><div class="faq-a">不会。权重画图页明确标注「仅本页使用，不写入数据库」：本地载入（.csv / .txt / .h / .c，≤200 万字符）、本页出图与导出，关掉即走，不影响数据管理中的文件清单。</div></details>

<style>
details.faq { border: 1px solid var(--vp-c-border); border-radius: 11px; background: var(--vp-c-bg); margin: 10px 0; overflow: hidden; }
details.faq summary { cursor: pointer; padding: 14px 18px; font-weight: 600; font-size: 14.5px; list-style: none; display: flex; align-items: center; gap: 12px; }
details.faq summary:hover { background: var(--vp-c-bg-soft); }
details.faq summary::before { content: ""; flex: none; width: 8px; height: 8px; border-right: 2px solid var(--vp-c-brand-1); border-bottom: 2px solid var(--vp-c-brand-1); transform: rotate(-45deg); transition: transform .25s; }
details.faq[open] summary::before { transform: rotate(45deg); }
details.faq .faq-a { padding: 0 18px 16px 38px; font-size: 14px; color: var(--vp-c-text-2); }
</style>