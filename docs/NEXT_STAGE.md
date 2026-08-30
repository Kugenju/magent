# 下一阶段决策：把 VulnTell 从示例推进为可用工具

## 结论

建议继续在当前仓库开发，不建议现在另起仓库或重写框架。理由是：

- `magent` 已有稳定的 Agent/State/Graph、并发、重试、超时、取消、Checkpoint、幂等、工具、LLM 和观测协议；
- VulnTell 已经用完整的离线纵向业务流程验证了这些能力，迁移到新仓库会重复搭建测试和恢复语义；
- 当前最大缺口是产品能力（真实数据源、增量同步、查询/API、报告和部署），不是调度内核；
- 保持单仓库可以让 VulnTell 的故障和性能反馈直接形成框架回归测试。

采用“同仓库、分包、稳定核心”的边界：`src/magent` 只接受通用能力修复；VulnTell 从 `examples/vulntell` 逐步迁移到 `src/vulntell` 或 `apps/vulntell`，通过公开 API 使用框架，不把 CVE/NVD/CVSS 模型加入 `magent`。

## 什么时候才拆分仓库

只有出现以下任一条件才建议拆分：VulnTell 需要独立版本/发布节奏，生产部署权限与框架不同，团队需要独立协作，或业务依赖（Web、任务队列、数据仓库）显著增大框架仓库的安装和 CI 成本。拆分时先把 `magent` 发布为版本化依赖，并保留 contract/integration 测试。

## 产品化分层

```text
数据源适配器 → 规范化/去重 → 持久化与索引 → 评估与报告
       ↓             ↓              ↓             ↓
  限速/重试      质量告警       增量/幂等      API/CLI/UI
                         ↑
                 magent 执行与恢复内核
```

框架负责“如何可靠执行”；VulnTell 负责“采集什么、如何解释漏洞情报”。

## 建议阶段与粗略工作量

以下按一名熟悉 Python/安全数据的开发者估算，实际取决于数据源许可和上线目标。

| 阶段 | 交付物 | 估算 |
| --- | --- | ---: |
| 10. 业务包与契约冻结 | `src/vulntell`、配置、领域 schema、迁移策略、contract 测试 | 1–2 周 |
| 11. 数据源与增量管道 | NVD/CNVD/CISA KEV 适配、分页/游标、限速、缓存、失败重试、数据许可 | 3–5 周 |
| 12. 检索与存储 | SQLite→PostgreSQL 适配、全文/字段索引、去重冲突审计、增量 checkpoint | 2–4 周 |
| 13. 评估与报告 | 可配置指标、标注集、质量回归、JSON/Markdown/导出 API | 2–3 周 |
| 14. 服务化与安全 | REST API、认证、任务调度、审计、SSRF/Prompt 注入防护、部署文档 | 3–6 周 |
| 15. 可选看板 | 独立前端、查询缓存、权限和可观测面板 | 3–5 周 |

最小可用工具（阶段 10–13，离线/定时任务/CLI）约 8–14 人周；生产服务（阶段 14）通常再增加 3–6 人周。不要在阶段 11 前承诺实时性或“完整覆盖”。

## 用实际运行驱动框架迭代

每个产品阶段都先写失败场景和验收指标，再决定是否改 `magent`：

1. 记录来源延迟、分页中断、重复运行、单条脏数据、限速、进程崩溃和恢复耗时。
2. 若问题可复用于任意 Agent（例如增量 checkpoint、背压、批量提交、结构化错误），先在 `magent` 增加最小协议和回归测试。
3. 若问题只涉及 CVE 字段、供应商策略或报告展示，留在 VulnTell。
4. 每次框架语义变更都同时更新 `docs/architecture/`、API、迁移说明和 VulnTell contract 测试。

## 详细设计与路线图

- [阶段 3：Graph 与任务层迁移实施计划](vulntell/PHASE3_PLAN.md)
- [阶段 3 审查记录](vulntell/PHASE3_REVIEW.md)
- [阶段 4：数据源契约与增量模型实施计划](vulntell/PHASE4_PLAN.md)
- [阶段 4 审查记录](vulntell/PHASE4_REVIEW.md)
- [阶段 5：真实数据源接入实施计划](vulntell/PHASE5_PLAN.md)
- [最终框架实现设计](vulntell/FINAL_DESIGN.md)
- [产品化实施路线图](vulntell/ROADMAP.md)
- [MVP 范围与验收](vulntell/PRODUCT_SCOPE.md)

## 下一步（阶段 4 收尾 → 阶段 5）

阶段 4 的协议和 fixture 已提交，但同步 runner 的完成状态、重试游标和持久化 checkpoint 仍需修复并补齐专门测试。完成这些门禁后，按 [PHASE5_PLAN.md](vulntell/PHASE5_PLAN.md) 以 NVD 为首个真实数据源，保持默认离线和显式 live 开关。

## 退出/暂停条件

出现以下信号时暂停扩展功能并先修框架：恢复结果无法与基线一致、重复运行产生重复业务记录、单源失败导致整体不可用、内存随数据量线性失控，或观测数据改变执行结果。每个信号都应转化为最小可复现测试。
