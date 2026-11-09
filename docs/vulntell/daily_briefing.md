# VulnTell 每日简报工作流（daily briefing）

一条命令完成 **多源并行采集 → 确定性评估 → 双路径一致性对照 → 静态前端展示**
的完整多 agent 协作链。生产调度只包这一条命令；全部评估沿用既有的确定性
指标方法（样本不足记 `insufficient_data`，不做无依据排名）。

```
python -m apps.vulntell.daily
```

## 一次运行包含什么

| 阶段 | 机制 | 文件 |
|------|------|------|
| 1. 并行采集 | `build_daily_vulntell_graph` N 源扇出（默认 `cisa_kev` 直连 REST + `osv_mcp` MCP 协议）；失败来源降级为 `source_status=failed`，不阻塞其他分支 | `apps/vulntell/pipeline/graph.py` |
| 2. 归一化/去重/持久化 | 与常规 VulnTell 同一套 Agent 与 `ToolRegistry` + `SideEffectSink` 幂等管线 | `apps/vulntell/pipeline/agents.py` |
| 3. 确定性评估 | `compute_metrics` 全套 + `compute_source_metrics` 每来源快照（置信/分母/证据可审计） | `apps/vulntell/domain/metrics.py` |
| 4. 双路径对照（live） | 同一 OSV.dev 端点：HTTP 直连 GET vs MCP `osv_get_payload` 工具调用，比较 canonical hash 与归一化字段 | `apps/vulntell/sources/mcp_bridge.py` |
| 5. 展示 | `dashboard.html`（单文件、零依赖、无外部 URL）+ `report.md` / `report.json`（+ `dual_path.json`） | `apps/vulntell/reporting/dashboard.py` |

dashboard 页面内容（服务端全量渲染）：

1. **多智能体执行时间线**——GraphExecutor 每个 agent 的顺序/状态/耗时/消息；
2. **数据源状态表**——采集状态、记录数、失败样本数；
3. **每来源指标卡**——时效（avg/p50/p90 延迟）、字段在位率、URL 覆盖、
   已验证引用率、traceable、完整度，以及置信徽标；
4. **质量告警聚合**——missing/invalid/ambiguous 按来源与严重度分组；
5. **OSV 双路径一致性对照**——同端点两条采集路径的 hash/字段一致性
   与同形失败统计；
6. **Canonical 预览**——按 modified 倒序展示近期活动（不是严重性排名）。

页面同时内嵌完整数据帧（`<script type="application/json" id="vulntell-data">`，
`<` 已转义加固），供未来的前端增强使用，不依赖任何运行时框架。

## 数据源与默认参数

- 默认源集合：`cisa_kev`（CISA KEV 目录，免 key）+ `osv_mcp`（本仓库
  FastMCP 服务器 `tools/mcp_example_server.py` 的 `osv_get_payload` 工具）。
  MCP 路径按样本 ID 检索 OSV（OSV 无全局"最近发布"feed API，per-ID 查询
  是该源的真实形态；样本默认 2 条高关注 CVE，可以 `--osv-ids` 替换）。
- 窗口：`--window-days`（默认 7 天半开 UTC 窗口）。
- `--max-kev-records`：KEV 受控批次上限（调度演示/烟测用；全量目录≈1400 条）。
- `--date YYYY-MM-DD`：日期锚定（影响 run_id 与窗口末端，重放用）。
- run_id 与归档：`daily-YYYYMMDD`，输出在 `runs/<run_id>/`（`--out` 覆盖）。
  SQLite 库落在产物目录；同日重跑幂等（upsert + 幂等副作用管线）。

## 每日自动调度（Windows 任务计划程序）

```
schtasks /create /tn "VulnTell Daily" /sc daily /st 08:00 /tr ^
  "powershell -ExecutionPolicy Bypass -File <repo>\scripts\daily_briefing.ps1"
```

脚本内部即调用 `python -m apps.vulntell.daily`；`-WindowDays / -OutDir /
-SkipDualPath` 透传。cron 机器上直接包同一条命令即可。

## 网络边界

默认测试/CI 基线保持离线确定性：live 行为全部在
`tests/live/test_daily_live_smoke.py`（`MAGENT_RUN_LIVE=1` 门控）。日报命令
本身是**显式 live 采集入口**（免 key 源）：CISA KEV 直连 + 本地 MCP 服务器
进程（OSV.dev 只读查询）+ REST 直连对照，遵循
`docs/architecture/NETWORK_POLICY.md` 的三层划分：magent 提供 transport/
policy 基础设施，领域适配全部在 VulnTell（L3）。API key 类源（NVD 等）
不在默认集合——需要时在环境变量注入 key 后按 VulnTell 既有 live 模式接入。

## 与 Phase 10 MCP 客户端的关系

每日工作流是 phase 10 MCP 通道的第一个真实下游用例：`McpSourceAdapter`
直接使用 `magent.mcp.transport` 接缝（数据面），与 P10.2 已验证的
`StdioMcpTransport` / 官方 SDK 组合；双路径对照是"MCP 采集路径 vs 直连
路径"一致性的持续审计（真实运行 2026-11-07：2/2 hash 一致，MCP 路径
延迟低于直连）。策略面（loader/allowlist）留给未来把 MCP 工具注册进
ToolRegistry 的 LLM 调用链。
