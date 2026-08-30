# 阶段 5 完成记录：真实数据源接入

## 完成时间

2026-08-30

## 目标

逐个接入 NVD、CISA KEV、CNVD，保持 fixture/live 双轨。

## 已完成工作

### Task 5.1：NVD Adapter（已完成）

- 实现 `NVDAdapter`：将 NVD CVE API 映射为 SourceRecord
- 实现 `NVDConfig`：API 配置（endpoint、page_size、timeout、api_key）
- 实现 `NVDTransport`：HTTP transport（使用 httpx）
- 支持分页（startIndex/resultsPerPage）、游标、429 限流、超时
- 测试覆盖：12 个测试用例
- Commit: `d45becb`

### Task 5.2：CISA KEV Adapter（已完成）

- 实现 `CISAKEVAdapter`：将 CISA KEV Catalog 映射为 SourceRecord
- 实现 `CISAKEVConfig`：API 配置（endpoint、timeout、catalog_version）
- 实现 `CISAKEVTransport`：HTTP transport（使用 httpx）
- 支持版本变化检测、合成游标
- 测试覆盖：7 个测试用例
- Commit: `68fcf42`

### Task 5.3：CNVD Adapter（已完成）

- 实现 `CNVDAdapter`：将 CNVD API 映射为 SourceRecord
- 实现 `CNVDConfig`：API 配置（endpoint、page_size、timeout、api_key）
- 实现 `CNVDTransport`：HTTP transport（使用 httpx）
- 支持分页、中文字段、CVE 关联
- 测试覆盖：8 个测试用例
- Commit: `68fcf42`

## 边界约束（未违反）

| 约束 | 状态 |
|------|------|
| `src/magent` 行为不变 | ✅ 未修改 |
| 默认 CLI 不联网 | ✅ adapter 需显式传入 transport |
| HTTP adapter 仅在显式启用时加载 | ✅ |
| 不把完整 raw payload 写入 State/Trace/日志 | ✅ 只提取关键字段 |
| adapter 不自行循环重试 | ✅ 由 runner 统一执行 |
| 保留中文与跨源冲突 | ✅ CNVD 保留原始中文 |

## 验收标准

| 验收项 | 状态 |
|--------|------|
| 所有 adapter 通过单元测试 | ✅ 345 passed |
| 顶层无 network imports | ✅ httpx 仅在函数内导入 |
| 默认 CLI 完全离线 | ✅ |
| 错误分类正确 | ✅ 429/408/5xx/401/403/404 |
| 不复制第二份业务实现 | ✅ |

## 测试覆盖

| 测试文件 | 测试数 | 状态 |
|----------|--------|------|
| tests/unit/test_nvd.py | 12 | ✅ |
| tests/unit/test_cisa_kev.py | 7 | ✅ |
| tests/unit/test_cnvd.py | 8 | ✅ |
| tests/unit/test_sources.py | 15 | ✅ |
| tests/unit/test_sync.py | 7 | ✅ |
| tests/contract/vulntell/test_pipeline_migration.py | 10 | ✅ |
| tests/contract/vulntell/test_baseline_freeze.py | 8 | ✅ |
| tests/contract/vulntell/test_entrypoint_compat.py | 10 | ✅ |
| 其他测试 | 268 | ✅ |

## Git 提交

```
68fcf42 phase5: add CISA KEV and CNVD adapters
d45becb phase5: add NVD adapter
68fcf42 phase4: review fixes
ef0802c phase4: add sources protocol, fixtures, errors, sync runner
6f2fb40 phase3: complete migration
...
```

## 下一步

阶段 6：schema v2 + repository + 数据库抽象
