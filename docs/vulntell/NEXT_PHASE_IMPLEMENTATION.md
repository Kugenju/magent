# 下一阶段实施规范：真实情报采集与分布式合并

本文是下游 Agent 的开发合同。目标不是继续增加空壳 adapter，而是让每个登记的情报源都能在合规前提下采集真实数据，并支持不同人员/机器独立采集后合并为统一 COSV 数据集。

## 当前复核结论（2026-08-31）

- 阶段 A（COSV 模型、映射、校验、稳定序列化）：代码和单元测试已具备；真实三源自动化落盘验收仍缺证据。
- 阶段 C/D（manifest、批次校验、合并）：核心模块和测试已具备；合并输出为幂等覆盖写入。
- 阶段 E（正式存储）：`apps/vulntell/storage/storage.py` 已存在，但主业务 runner 仍通过 `storage/legacy.py` 转发到 `examples.vulntell.db`，迁移尚未完成。
- 阶段 B（真实来源）：未完成。除 NVD/CISA 独立 smoke 和 CNVD 人工文件导入外，其余来源尚无真实采集证据，且统一 live CLI 尚未接通。因此当前阶段整体不得标记为完成。
- 本轮真实 smoke 记录见 [PHASEB_REAL_SMOKE_REPORT.md](PHASEB_REAL_SMOKE_REPORT.md)：NVD/CISA 各有 100 条 COSV 批次证据，但双人 merge 和其余来源验收仍未完成，阶段 B 仍为未通过。

下游 Agent 必须先补齐上述缺口，再更新本节；不得仅以类定义、fake transport 或单元测试作为真实来源完成证明。

## 完成定义

阶段只有在以下条件全部满足时才算完成：

1. 17 个已登记来源均有明确结果：真实 API/feed 已验证，或官方允许的人工下载导入已验证；暂不可用来源必须有结构化失败状态和证据，不能以“有类/有测试”算完成。
2. 每个可用来源都能从独立入口运行，产生通过 COSV schema 校验的文件和 manifest。
3. 两名采集者使用不同工作目录分别采集后，可在第三个环境执行 merge，得到确定性、幂等、可追溯的合并结果。
4. 默认离线模式、凭据脱敏、WAF 合规、原始响应隔离和现有回归测试保持通过。

## 工作流与交付物

```text
Source adapter → SourceObservation → COSV serializer/validator
       → batch/*.cosv.json + manifest.json + quality.json
       → merge/import → canonical COSV dataset + merge report
```

每个采集批次至少交付：

- `records.cosv.jsonl`：一行一个 COSV 对象，UTF-8、稳定字段顺序；
- `manifest.json`：source、dataset/version、窗口、采集时间、schema/parser 版本、记录数、文件 SHA-256、许可证；
- `quality.json`：丢弃/待处理记录、字段质量问题和结构化错误；
- 不得把 API key、Cookie、Authorization、HTML challenge 或完整 raw payload 写入上述文件。

## 阶段 A：COSV 核心落盘（P0）

### 目标

实现独立的 `apps/vulntell/cosv` 模块：模型、JSON Schema 校验、SourceObservation→COSV 映射、稳定序列化和版本迁移入口。

### Agent 任务

- 固定并记录支持的 `schema_version`；
- 实现必填字段 `id`、`modified`，以及 `aliases`、`summary`、`details`、`affected`、`severity`、`references`、`database_specific`；
- 版本范围使用 `introduced/fixed/last_affected/limit` events；无法解析的版本进入扩展字段并生成质量问题；
- 时间统一 RFC3339 UTC，数组去重并稳定排序；
- 提供 `validate_cosv_file()`、`serialize_cosv()`、`content_hash()` API。

### 验收

- NVD、CISA KEV、CNVD fixture 各生成至少 3 条 COSV 并通过 schema；
- 同一输入序列化哈希一致；修改字段会更新 `modified`；非法记录进入 pending；
- 凭据/raw payload 泄露测试通过。

## 阶段 B：真实来源逐一打通（P0/P1）

### 目标

按清单逐源完成真实采集，不得只依赖 fake transport。每个 Agent 负责一个来源或一组同类来源，并提交真实 smoke 证据（请求时间、endpoint、状态、记录数、版本/hash；禁止提交敏感响应）。

### 接入顺序

1. NVD、CISA KEV、CNVD 人工下载导入（修复现有 pipeline 接口和窗口元数据）；
2. OSV.dev、GitHub Advisory、EUVD；
3. Microsoft MSRC、Red Hat、Ubuntu、Debian、JVN；
4. CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB；
5. VulnDB 仅在许可证和凭据获得书面确认后实施。

### 每个来源必须完成

- 官方 API、feed 或人工下载路径记录在 adapter 文档；
- 真实分页/游标、窗口、增量、429/5xx/超时和取消处理；
- 输出 `SourcePage` 后立即转换为 COSV，不允许来源私有落盘格式；
- 记录来源版本、更新时间、许可证和内容哈希；
- 至少一次真实公网 smoke（商业/受限源可用授权数据或官方样本）；
- 无公开接口时必须返回 `unavailable`/`manual_required`，不得伪造成功或绕过 WAF。

### 验收

- 每个来源均有 `pytest` contract test 和真实 smoke 报告；
- 至少 10 个来源能够实际产出非空 COSV；
- 其余来源有明确的合规不可用证据和人工导入计划；
- 正式 CLI/Application 可选择单一来源运行并返回正确退出码。

## 阶段 C：分布式采集批次协议（P0）

### 目标

允许不同人员在不同机器、不同时间窗口独立采集，产出可交换批次，不共享运行时 SQLite。

### Agent 任务

- 实现 `BatchManifest`：batch_id、collector_id（不可含秘密）、source、dataset_version、window、COSV schema/parser 版本、created_at、record_count、content_hash、license；
- 实现目录/对象存储导入器：先校验 manifest/hash/schema，再原子导入；
- 批次状态：received、validated、merged、rejected；失败可重试且不产生重复记录；
- 提供命令行：`vulntell collect`、`vulntell validate-batch`、`vulntell merge`；
- collector_id 不作为漏洞实体身份，不能阻止相同批次合并。

### 验收

- 两个独立批次可在无网络环境合并；
- 重复导入同一批次结果不变；篡改文件会因 hash 不匹配拒绝；
- 合并报告列出接收、拒绝、去重、冲突和待处理数量。

## 阶段 D：跨来源合并与冲突治理（P0）

### 合并规则

- 主键优先使用合法 CVE；无 CVE 的记录以规范化来源 ID 建立 pending，不强行猜测相等；
- 保留每个来源的 COSV 观察和 manifest 引用；
- 标题/描述按来源优先级选择，同时保留冲突字段；
- CVSS 向量可复算，冲突不得静默覆盖；
- references、aliases、affected 去重并稳定排序；
- 同一 `id + modified + content_hash` 幂等；较新 `modified` 进入修订链；
- 删除不做物理删除，使用撤回/状态事件并保留审计。

### 验收

- NVD+OSV+CNVD 三来源共享 CVE 能合并为一个实体并保留三方来源；
- 无 CVE 的 CNVD 记录进入 pending；
- 冲突、修订、撤回、重复批次均有可重复测试和 merge report。

## 阶段 E：正式存储与回归门禁

将当前 `examples.vulntell.db` 过渡层替换为 `apps/vulntell/storage`：COSV 原文、manifest、观察、规范化实体和合并事件分表保存，SQLite 用于本地部署，后续可替换 PostgreSQL/对象存储。

最终门禁：

```text
python -m pytest -q
python -m mypy src/magent
python -m apps.vulntell --no-llm --json
python -m apps.vulntell collect --source <source> ...
python -m apps.vulntell validate-batch <dir>
python -m apps.vulntell merge <batch-dir> ...
```

任何来源仅通过单元测试、未提供真实采集或合规人工导入证据，均不得标记为“完成”。
