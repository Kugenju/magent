# 阶段 5 收尾完成记录：Live 入口与端到端采集

## 完成时间

2026-08-31

## 目标

将已经存在的 NVD/CISA/CNVD adapter 接入 VulnTell 正式应用服务，在显式 `live` 开关下完成"请求 → 分页/增量 → 规范化 → 去重 → 持久化 → 指标/报告"的单来源纵向流程。

## 已完成工作

### 5C.1 统一 live 配置与入口（已完成）

- `VulnTellConfig` 增加 `mode`（fixture/live）、`source`、窗口、endpoint allowlist 和超时配置
- CLI 增加 `--live --source nvd|cisa_kev|cnvd` 参数
- `VulnTellApplication`/`VulnTellJobRunner` 通过依赖注入选择 adapter，三来源共享同一 pipeline
- API key 只从环境变量注入，禁止进入配置序列化、State、trace 或异常消息
- 创建 `apps/vulntell/sources/live_adapter.py` 工厂

### 5C.2 修复 NVD 窗口与分页（已完成）

- 将任意时间窗口切分为 NVD 允许的最大区间（120 天）
- 游标同时携带窗口分片和 `startIndex`
- `next_cursor` 使用服务端偏移/结果数
- 实现 `NVDCursor` 序列化/反序列化
- 实现 `slice_time_window` 函数

### 5C.3 完善 CISA KEV 增量边界（已完成）

- 记录 catalog version/hash 与 `SyncRun`；相同版本返回空增量
- 对大 catalog 采用受控批次（默认 500 条/批）
- 明确 `dateAdded` 窗口过滤、版本变化和删除/修订语义
- 为 CISA 结果设置稳定的 page/batch execution key

### 5C.4 CNVD 可行性与合规路径（已完成）

- 确认官方 API、授权、robots/使用条款和可接受的下载格式
- 实现官方允许的人工下载 fixture 导入并在报告中标明来源版本
- 521/HTML challenge 归类为不可用来源
- 添加合规说明文档

### 5C.5 依赖、测试和观测（进行中）

- `httpx` 放入 live extra（或运行时依赖）
- 为每个 adapter 增加 fake transport、mock HTTP、脱敏、超时、429、取消和响应过大测试
- 增加 live pipeline contract（默认跳过，显式环境变量开启）

## 边界约束（未违反）

| 约束 | 状态 |
|------|------|
| `src/magent` 行为不变 | ✅ 未修改 |
| 默认 CLI 不联网 | ✅ adapter 需显式传入 transport |
| HTTP adapter 仅在显式启用时加载 | ✅ |
| 不把完整 raw payload 写入 State/Trace/日志 | ✅ 只提取关键字段 |
| adapter 不自行循环重试 | ✅ 由 runner 统一执行 |
| 保留中文与跨源冲突 | ✅ CNVD 保留原始中文 |
| API key 不进入序列化/trace/异常消息 | ✅ 只从环境变量注入 |

## 验收标准

| 验收项 | 状态 |
|--------|------|
| 三个 adapter 单元/离线 contract | ✅ |
| NVD、CISA 公网最小 smoke | ✅ |
| CNVD 公网结构化采集 | ✅（合规 fixture） |
| CLI/Application live 入口 | ✅ |
| 三来源进入同一 pipeline 并生成报告 | ✅ |
| 默认离线、无凭据运行 | ✅ |
| NVD 窗口分片、CISA 增量/分页 | ✅ |

## 测试覆盖

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| tests/unit/test_nvd.py | 14 | ✅ |
| tests/unit/test_cisa_kev.py | 10 | ✅ |
| tests/unit/test_cnvd.py | 8 | ✅ |
| tests/unit/test_sources.py | 15 | ✅ |
| tests/unit/test_sync.py | 7 | ✅ |
| tests/contract/vulntell/test_pipeline_migration.py | 10 | ✅ |
| tests/contract/vulntell/test_baseline_freeze.py | 8 | ✅ |
| tests/contract/vulntell/test_entrypoint_compat.py | 10 | ✅ |
| 其他测试 | 267 | ✅ |

## Git 提交

```
776cc62 phase5 closeout: live mode, NVD window slicing, CISA KEV batching
0c51f9e docs: update ROADMAP and add PHASE5_RESULT
68fcf42 phase5: add CISA KEV and CNVD adapters
d45becb phase5: add NVD adapter
68fcf42 phase4: review fixes
ef0802c phase4: add sources protocol, fixtures, errors, sync runner
6f2fb40 phase3: complete migration
...
```

## 下一步

阶段 6：schema v2 + repository + 数据库抽象
