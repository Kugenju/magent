# VulnTell 阶段 5：真实数据源接入实施计划

## 前置条件

只有 [PHASE4_REVIEW.md](PHASE4_REVIEW.md) 中的收尾门禁全部通过，才可开始本阶段。阶段 4 的协议版本、游标语义、`SyncRun` checkpoint 格式和错误分类必须冻结；否则 live adapter 产生的 checkpoint 不承诺兼容。

## 目标与非目标

在保持 fixture/live 双轨和默认离线的前提下，依次接入 NVD、CISA KEV、CNVD。每个来源都通过统一 `SourceRequest → SourcePage/SourceError` 协议、现有同步 runner 和存储接口运行。本阶段不做查询 API、Web 看板、全文检索、分布式队列或抓取引用网页。

## 实施顺序

### 5.1 NVD adapter（首个纵向切片）

- 明确 NVD API 许可、endpoint、认证（如需）、限速和响应大小上限；
- 将 NVD 响应映射为 `SourceRecord`，保留 source record id、published/modified 时间、CVSS 和 CPE 所需字段；
- 实现分页参数与协议游标的双向转换，处理窗口半开边界和修改时间排序；
- 接入连接/读取超时、429 `Retry-After`、5xx、非法 JSON、401/403/404 分类；
- fixture 与录制响应仅保存最小脱敏样本，禁止把完整 raw payload 写入 State/Trace/日志；
- 提供离线 contract、mock HTTP 测试和显式 live smoke（默认不运行）。

验收：固定窗口重复同步结果一致；中断后从最后成功游标恢复；429/超时按 retry hint 交给执行器；单页坏记录隔离；默认 CLI 无网络且无 key 也能运行。

### 5.2 CISA KEV adapter

- 固定 KEV 字段映射、catalog version 和新增/修改时间语义；
- 处理无分页或文件版本变化时的合成游标；
- 将 known-exploited 状态映射为来源元数据，不修改通用领域指标规则；
- 使用同一错误、脱敏、大小限制和审计策略。

验收：fixture/live 字段逐项对照，重复 catalog 不重复写入，版本变化可审计，失败可恢复。

### 5.3 CNVD adapter

- 固定中文标题/描述、CVE 关联、发布日期和来源优先级映射；
- 保留中文与跨源冲突，不在 adapter 内做领域去重或指标计算；
- 处理接口限流、权限和不稳定响应，必要时提供人工下载 fixture 导入路径。

验收：中文字段编码稳定，跨源冲突进入质量问题，单条非法记录不丢弃整批，许可和来源版本记录完整。

## 共通工程任务

1. 为 live adapter 定义依赖注入的 HTTP transport（测试使用 fake transport），禁止模块级 client；
2. 设置连接/读取/总响应大小/单页记录数上限，拒绝重定向到非 allowlist 主机；
3. 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试；
4. 对请求 URL、header、异常和响应摘要做集中脱敏；
5. 增加来源许可、数据保留、版本和变更日志文档；
6. 为每个来源提供独立 feature flag，live 未显式开启时构造 fixture adapter。

## 阶段验收门禁

```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json       # 默认离线
git diff --check
```

另须满足：三来源均有 fixture、mock HTTP、离线 contract 和显式 live smoke；429/超时/取消/进程重启恢复通过；连续相同窗口同步幂等；trace、日志、checkpoint、错误和 prompt 不含凭据或 raw payload；未修改 magent 通用语义。

## 交付与回滚

每个 adapter 单独提交，包含字段映射、许可、配置示例、测试结果和结构化 diff。live adapter 出现回归时，通过 feature flag 回退到 fixture/旧 legacy adapter；不得删除旧 fixture 或破坏阶段 3 baseline。三来源全部通过后，才进入阶段 6 存储与查询产品化。

