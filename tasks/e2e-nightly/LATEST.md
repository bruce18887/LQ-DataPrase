# 夜间全量兜底轮（最近 7 轮）

阈值：墙钟 12min（目标兼挂死）· 单价 4.5s/例 · 用例 450 · flaky 5 · 效率 ≥0.7×slot
判级：负载抖动（红文件独占 slot 复跑转绿）算 flaky 不拦门禁；真红与"复跑没验成"拦。崩池轮 verdict=VOID 不计退化。
最近一轮明细：`tasks/e2e-nightly/2026-10-17-0330/`（merged.json + slot<i>.run.log + slot<i>.results.json + 合并 HTML）

| 日期 | 结果 | 墙钟 | 规模 |
|---|---|---|---|
| 2026-10-17-0330 | ⚠ DEGRADED PASSED | 8.6min · 3.13s/例 · 4slot 效率2.24 | 389 例 / flaky 6 / 抖动2 未决0 |
| 2026-10-15-0346 | SKIPPED | 工作区有 1 项未提交改动 —— 全量结果会算到本不归属它的会话头上 | — |
| 2026-10-14-1108 | FAILED | 19.7min · 2.89s/例 | 385 例 / flaky 1 |
| 2026-10-14 | ❌ VOID (infra) | 923/1099 次 attempt 连接级失败，指标不可信 | 请重跑 |
| 2026-10-13 | ⚠ DEGRADED FAILED | 21.9min · 2.78s/例 | 385 例 / flaky 6 |
| 2026-09-26 | SKIPPED | 端口被占用 3000(listening), 8000(listening) —— 另一会话在服务，跳过而不是抢它的端口 | — |
| 2026-09-26 | SKIPPED | 端口被占用 3000(listening), 8000(listening) —— 另一会话在服务，跳过而不是抢它的端口 | — |

> 出现 ⚠ DEGRADED 时：按 docs/superpowers/specs/ 的三层判据，把最慢文件的断言下沉到 T1/T2，
> 或删掉已陈旧的 T0。别靠加大超时来「消红」。
