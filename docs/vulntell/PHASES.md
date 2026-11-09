# VulnTell 阶段文档汇总

## 完成情况

| 阶段/工作项 | 状态 | 依据与说明 |
|---|---|---|
| 0–1 基线与应用外壳 | 已完成 | 详细计划与历史审查见下方原文 |
| 2 领域层迁移 | 已完成 | 实施记录见下方原文 |
| 3 Graph 与任务层迁移 | 已完成 | 实施与审查记录见下方原文 |
| 4 数据源契约与离线同步 | 已完成 | 离线契约和门禁已通过 |
| 5 真实数据源接入 | 部分完成，整体验收未闭环 | adapters 已实现；live CLI/Application 端到端和来源验收仍有未通过项 |
| 阶段 B 真实采集 | 未通过 | 现有报告记录 6/17 来源完成真实 COSV 批次闭环，尚未满足至少 10 个来源各 100 条及批次合并要求 |

阶段状态以复核和真实采集报告为准；历史计划或实现清单中自述完成的内容不替代验收结论。以下保留原始阶段计划、结果、复核和实施记录。


<a id="phase-doc-next-phase-completion-report"></a>

## 原文：NEXT_PHASE_COMPLETION_REPORT.md

### NEXT_PHASE_IMPLEMENTATION 实现清单（历史稿，验收未通过）
> 本文仅盘点已写入的模块和离线测试，不能作为阶段 A–E 全部完成的证明。当前状态以
> [PHASE_COMPLETION_SUMMARY.md](PHASES.md#phase-doc-phase-completion-summary)、
> [PHASE5_CLOSEOUT_REVIEW.md](PHASES.md#phase-doc-phase5-closeout-review) 和
> [PHASEB_REAL_SMOKE_REPORT.md](PHASES.md#phase-doc-phaseb-real-smoke-report) 为准；阶段 B 未通过，
> 阶段 E 尚未替换 legacy 存储链路。

#### 执行摘要
按照 `docs/vulntell/NEXT_PHASE_IMPLEMENTATION.md` 规范，已完成所有五个阶段的开发工作。

#### 阶段 A：COSV 核心落盘（P0）✅
##### 完成内容
1. **COSV 数据模型** (`apps/vulntell/cosv/models.py`)
   - `COSVDocument`: 完整 COSV 文档结构
   - `Affected`, `Package`, `VersionRange`: 受影响包信息
   - `Severity`, `Reference`: 严重性和引用信息
   - 字段验证和稳定序列化

2. **JSON Schema 校验** (`apps/vulntell/cosv/schema.py`)
   - `validate_cosv_record()`: 单条记录校验
   - `validate_cosv_file()`: JSONL 文件校验
   - 完整的字段格式验证

3. **序列化与内容哈希** (`apps/vulntell/cosv/serializer.py`)
   - `serialize_cosv()`: 稳定 JSON 序列化
   - `content_hash()`: SHA-256 内容哈希
   - `read_cosv_file()`: 读取 JSONL 文件

4. **映射器** (`apps/vulntell/cosv/mapper.py`)
   - `observation_to_cosv()`: SourceObservation → COSVDocument
   - `batch_observations_to_cosv()`: 批量映射

##### 测试覆盖
- 20 个单元测试，覆盖模型、校验、序列化、映射
- 凭据泄露测试通过

---

#### 阶段 B：真实来源逐一打通（P0/P1）✅
##### 来源可用性验证
| 来源 | 状态 | 端点 | 备注 |
|------|------|------|------|
| NVD | ✅ 可用 | services.nvd.nist.gov | 需要 API key |
| CISA KEV | ✅ 可用 | cisa.gov | 公开 |
| CNVD | ⚠️ 人工 | - | 官方 API 不可用 |
| OSV.dev | ✅ 可用 | osv.dev | 公开 |
| GitHub Advisory | ✅ 可用 | api.github.com | 可选认证 |
| EUVD | ✅ 可用 | euvd.enisa.europa.eu | 公开 |
| MSRC | ✅ 可用 | api.msrc.microsoft.com | 公开 |
| Red Hat | ✅ 可用 | access.redhat.com | 公开 |
| Ubuntu | ✅ 可用 | ubuntu.com | 公开 |
| Debian | ✅ 可用 | security-tracker.debian.org | 公开 |
| JVN | ✅ 可用 | jvndb.jvn.jp | 公开 |
| CERT/CC | ⚠️ 人工 | - | 需要 API 密钥 |
| Cisco | ⚠️ 人工 | - | 需要特殊认证 |
| Fortinet | ⚠️ 人工 | - | 需要特殊认证 |
| Palo Alto | ⚠️ 人工 | - | 需要特殊认证 |
| Exploit-DB | ⚠️ 人工 | - | 需要特殊认证 |

**可用来源**: 11 个（满足"至少10个来源"要求）

---

#### 阶段 C：分布式采集批次协议（P0）✅
##### 完成内容
1. **BatchManifest** (`apps/vulntell/batch/manifest.py`)
   - `BatchManifest` 数据模型
   - `create_batch_manifest()`: 创建清单
   - `validate_manifest()`: 校验清单
   - `save_manifest()` / `load_manifest()`: 持久化

2. **批次导入器** (`apps/vulntell/batch/importer.py`)
   - `validate_batch_directory()`: 目录校验
   - `import_batch()`: 原子导入
   - `list_batches()`: 列出批次
   - 幂等导入支持

3. **批次合并器** (`apps/vulntell/batch/merger.py`)
   - `merge_batches()`: 批次合并
   - 来源优先级
   - 去重和冲突检测
   - 合并报告生成

##### 测试覆盖
- 17 个单元测试，覆盖清单、导入、合并
- 幂等性测试通过
- 去重测试通过

---

#### 阶段 D：跨来源合并与冲突治理（P0）✅
##### 合并规则实现
1. **主键优先使用合法 CVE**
   - 有 CVE 的记录以 CVE 为主键
   - 无 CVE 的记录以规范化来源 ID 建立 pending

2. **来源优先级**
   - NVD (1) > CISA KEV (2) > GitHub Advisory (3) > ...
   - 按优先级选择标题/描述

3. **冲突处理**
   - CVSS 向量可复算，冲突不得静默覆盖
   - references、aliases、affected 去重并稳定排序

4. **幂等性**
   - 同一 `id + modified + content_hash` 幂等
   - 较新 `modified` 进入修订链

5. **审计追踪**
   - 合并事件记录
   - 撤回/状态事件保留

---

#### 阶段 E：正式存储与回归门禁（P0）✅
##### 完成内容
1. **正式存储** (`apps/vulntell/storage/storage.py`)
   - `VulnTellStorage`: SQLite 存储实现
   - COSV 记录表
   - Manifest 表
   - 观察表
   - 合并事件表

2. **存储操作**
   - `upsert_cosv()`: 插入/更新 COSV
   - `upsert_manifest()`: 插入/更新 manifest
   - `insert_observation()`: 插入观察
   - `insert_merge_event()`: 插入合并事件
   - `get_stats()`: 统计信息

##### 测试覆盖
- 15 个单元测试，覆盖所有存储操作
- 幂等性测试通过
- 上下文管理器测试通过

---

#### 最终门禁
```bash
### 测试通过python -m pytest -q
### 427 passed
### 类型检查（需配置 mypy）python -m mypy src/magent

### CLI 命令python -m apps.vulntell --no-llm --json
python -m apps.vulntell collect --source <source> ...
python -m apps.vulntell validate-batch <dir>
python -m apps.vulntell merge <batch-dir> ...
```

---

#### Git 提交记录
1. `feat(cosv): implement Phase A - COSV core persistence module`
2. `fix: update source availability and correct endpoints`
3. `feat(batch): implement Phase C - distributed collection batch protocol`
4. `test(batch): add comprehensive tests for Phase D merge rules`
5. `feat(storage): implement Phase E - formal storage with SQLite`

---

#### 统计
- **新增文件**: 12 个
- **修改文件**: 3 个
- **新增测试**: 52 个
- **总测试数**: 427 个（全部通过）


<a id="phase-doc-next-phase-implementation"></a>

## 原文：NEXT_PHASE_IMPLEMENTATION.md

### 下一阶段实施规范：真实情报采集与分布式合并
本文是下游 Agent 的开发合同。目标不是继续增加空壳 adapter，而是让每个登记的情报源都能在合规前提下采集真实数据，并支持不同人员/机器独立采集后合并为统一 COSV 数据集。

#### 当前复核结论（2026-08-31）
- 阶段 A（COSV 模型、映射、校验、稳定序列化）：代码和单元测试已具备；真实三源自动化落盘验收仍缺证据。
- 阶段 C/D（manifest、批次校验、合并）：核心模块和测试已具备；合并输出为幂等覆盖写入。
- 阶段 E（正式存储）：`apps/vulntell/storage/storage.py` 已存在，但主业务 runner 仍通过 `storage/legacy.py` 转发到 `examples.vulntell.db`，迁移尚未完成。
- 阶段 B（真实来源）：未完成。除 NVD/CISA 独立 smoke 和 CNVD 人工文件导入外，其余来源尚无真实采集证据，且统一 live CLI 尚未接通。因此当前阶段整体不得标记为完成。
- 本轮真实 smoke 记录见 [PHASEB_REAL_SMOKE_REPORT.md](PHASES.md#phase-doc-phaseb-real-smoke-report)：NVD/CISA 各有 100 条 COSV 批次证据，但双人 merge 和其余来源验收仍未完成，阶段 B 仍为未通过。

下游 Agent 必须先补齐上述缺口，再更新本节；不得仅以类定义、fake transport 或单元测试作为真实来源完成证明。

#### 完成定义
阶段只有在以下条件全部满足时才算完成：

1. 17 个已登记来源均有明确结果：真实 API/feed 已验证，或官方允许的人工下载导入已验证；暂不可用来源必须有结构化失败状态和证据，不能以“有类/有测试”算完成。
2. 每个可用来源都能从独立入口运行，产生通过 COSV schema 校验的文件和 manifest。
3. 两名采集者使用不同工作目录分别采集后，可在第三个环境执行 merge，得到确定性、幂等、可追溯的合并结果。
4. 默认离线模式、凭据脱敏、WAF 合规、原始响应隔离和现有回归测试保持通过。

#### 工作流与交付物
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

#### 阶段 A：COSV 核心落盘（P0）
##### 目标
实现独立的 `apps/vulntell/cosv` 模块：模型、JSON Schema 校验、SourceObservation→COSV 映射、稳定序列化和版本迁移入口。

##### Agent 任务
- 固定并记录支持的 `schema_version`；
- 实现必填字段 `id`、`modified`，以及 `aliases`、`summary`、`details`、`affected`、`severity`、`references`、`database_specific`；
- 版本范围使用 `introduced/fixed/last_affected/limit` events；无法解析的版本进入扩展字段并生成质量问题；
- 时间统一 RFC3339 UTC，数组去重并稳定排序；
- 提供 `validate_cosv_file()`、`serialize_cosv()`、`content_hash()` API。

##### 验收
- NVD、CISA KEV、CNVD fixture 各生成至少 3 条 COSV 并通过 schema；
- 同一输入序列化哈希一致；修改字段会更新 `modified`；非法记录进入 pending；
- 凭据/raw payload 泄露测试通过。

#### 阶段 B：真实来源逐一打通（P0/P1）
##### 目标
按清单逐源完成真实采集，不得只依赖 fake transport。每个 Agent 负责一个来源或一组同类来源，并提交真实 smoke 证据（请求时间、endpoint、状态、记录数、版本/hash；禁止提交敏感响应）。

##### 接入顺序
1. NVD、CISA KEV、CNVD 人工下载导入（修复现有 pipeline 接口和窗口元数据）；
2. OSV.dev、GitHub Advisory、EUVD；
3. Microsoft MSRC、Red Hat、Ubuntu、Debian、JVN；
4. CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB；
5. VulnDB 仅在许可证和凭据获得书面确认后实施。

##### 每个来源必须完成
- 官方 API、feed 或人工下载路径记录在 adapter 文档；
- 真实分页/游标、窗口、增量、429/5xx/超时和取消处理；
- 输出 `SourcePage` 后立即转换为 COSV，不允许来源私有落盘格式；
- 记录来源版本、更新时间、许可证和内容哈希；
- 至少一次真实公网 smoke（商业/受限源可用授权数据或官方样本）；
- 无公开接口时必须返回 `unavailable`/`manual_required`，不得伪造成功或绕过 WAF。

##### 验收
- 每个来源均有 `pytest` contract test 和真实 smoke 报告；
- 至少 10 个来源能够实际产出非空 COSV；
- 其余来源有明确的合规不可用证据和人工导入计划；
- 正式 CLI/Application 可选择单一来源运行并返回正确退出码。

#### 阶段 C：分布式采集批次协议（P0）
##### 目标
允许不同人员在不同机器、不同时间窗口独立采集，产出可交换批次，不共享运行时 SQLite。

##### Agent 任务
- 实现 `BatchManifest`：batch_id、collector_id（不可含秘密）、source、dataset_version、window、COSV schema/parser 版本、created_at、record_count、content_hash、license；
- 实现目录/对象存储导入器：先校验 manifest/hash/schema，再原子导入；
- 批次状态：received、validated、merged、rejected；失败可重试且不产生重复记录；
- 提供命令行：`vulntell collect`、`vulntell validate-batch`、`vulntell merge`；
- collector_id 不作为漏洞实体身份，不能阻止相同批次合并。

##### 验收
- 两个独立批次可在无网络环境合并；
- 重复导入同一批次结果不变；篡改文件会因 hash 不匹配拒绝；
- 合并报告列出接收、拒绝、去重、冲突和待处理数量。

#### 阶段 D：跨来源合并与冲突治理（P0）
##### 合并规则
- 主键优先使用合法 CVE；无 CVE 的记录以规范化来源 ID 建立 pending，不强行猜测相等；
- 保留每个来源的 COSV 观察和 manifest 引用；
- 标题/描述按来源优先级选择，同时保留冲突字段；
- CVSS 向量可复算，冲突不得静默覆盖；
- references、aliases、affected 去重并稳定排序；
- 同一 `id + modified + content_hash` 幂等；较新 `modified` 进入修订链；
- 删除不做物理删除，使用撤回/状态事件并保留审计。

##### 验收
- NVD+OSV+CNVD 三来源共享 CVE 能合并为一个实体并保留三方来源；
- 无 CVE 的 CNVD 记录进入 pending；
- 冲突、修订、撤回、重复批次均有可重复测试和 merge report。

#### 阶段 E：正式存储与回归门禁
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


<a id="phase-doc-phase0-1-plan"></a>

## 原文：PHASE0_1_PLAN.md

### VulnTell 阶段 0–1 详细实施方案
本文用于指导下游 agent 完成 VulnTell 从 `examples/vulntell` 向 `apps/vulntell` 迁移的第一轮工作。阶段 0–1 只建立基线、应用外壳和兼容入口，不接入真实网络，不重写 `magent`，不引入 Web/API 服务。

#### 一、范围和最终产出
##### 阶段 0：基线冻结
冻结当前可观察行为，形成迁移前的“黄金基线”：

- fixture、数据集元信息、指标版本和报告 schema；
- 默认、`--no-llm`、单源失败、`--resume`、`--trace` 场景；
- 测试、类型检查、离线 CLI 和链接检查结果；
- 新旧入口的兼容策略和已知限制清单。

##### 阶段 1：应用外壳
建立 `apps/vulntell` 的可运行入口和依赖组装层，暂时复用旧实现：

- `python -m apps.vulntell` 可运行；
- 配置、应用生命周期和运行结果对象有明确位置；
- `examples.vulntell` 变为薄兼容入口；
- 新旧入口输出可自动比较，且没有第二份业务实现。

阶段 1 完成后，后续阶段才能迁移领域模块、Graph 和数据源适配器。

#### 二、不可改变的边界
下游 agent 在阶段 0–1 不得：

- 修改 `src/magent` 的执行、状态合并、Checkpoint、重试或取消语义；
- 接入真实 NVD、CNVD、CISA KEV HTTP 请求；
- 增加 FastAPI、Web 前端、任务队列或 PostgreSQL 运行依赖；
- 将 VulnTell 领域模型导入 `src/magent`；
- 复制一套 `agents.py`、`graph.py` 或数据库实现到新旧两个目录；
- 以“输出看起来相同”为理由跳过结构化报告比较和恢复测试。

允许的修改范围：`apps/` 新文件、`examples/vulntell` 兼容入口、`tests/contract/vulntell`、阶段文档和必要的 README/导航链接。

#### 三、阶段 0：基线冻结
##### 0.1 任务拆分
###### Task 0.1：建立基线清单
记录以下事实：

| 项目 | 当前基线 |
| --- | --- |
| 入口 | `python -m examples.vulntell` |
| 数据模式 | fixture-first，默认离线 |
| fixture | `examples/vulntell/fixtures/` |
| 数据集元信息 | `dataset_meta.json` |
| 运行状态 | `VulnTellState` |
| 持久化 | `VulnTellStore` + SQLite |
| checkpoint | `SqliteCheckpointStore` |
| LLM | 默认 `FakeProvider`，可 `--no-llm` |
| 观测 | `--trace <prefix>` 输出 JSONL/summary |
| 框架版本 | 从已安装包元数据读取 |

产出：`docs/vulntell/baseline.md` 或等价测试 fixture，禁止只写在 issue 评论中。

###### Task 0.2：冻结运行场景
至少保存以下场景的机器可读结果：

```text
baseline_default.json
baseline_no_llm.json
baseline_faulty_cnvd.json
baseline_trace.summary.json
baseline_resume.json
```

结果中应保留数据集、窗口、版本、来源状态、canonical/pending 数量、质量问题数量、指标和报告 schema。`generated_at` 等非确定字段必须在比较时显式忽略或固定。

建议使用临时目录和临时 SQLite 文件，禁止把运行数据库、trace 或 benchmark 输出提交到 Git。

###### Task 0.3：定义结构化比较规则
新增测试辅助函数，例如：

```python
def normalize_report_for_compare(report: dict) -> dict:
    """删除运行时间、trace id 等非业务字段并稳定排序。"""
```

比较规则：

- 指标数值、来源状态、实体数量、质量问题和版本字段必须相等；
- 列表按稳定业务键排序后比较；
- LLM explanation 单独比较，不能影响确定性字段；
- trace id、span id、generated_at 等运行标识不参与业务等价比较；
- resume 结果必须与完整运行结果相等。

###### Task 0.4：冻结失败和安全边界
建立清单并写入测试：

- `--faulty nvd` / `--faulty cnvd` 可生成部分报告；
- 默认运行不进行网络请求；
- raw payload 不进入 Trace、日志和 LLM prompt；
- 不执行外部命令，不抓取引用 URL；
- API key、token、cookie 等敏感字段不进入状态和报告。

###### Task 0.5：冻结质量门禁
阶段 0 结束前执行：

```bash
python -m pytest -q
mypy src/magent
python -m examples.vulntell --no-llm --json
python -m examples.vulntell --faulty cnvd --no-llm --json
python -m examples.vulntell --trace <temporary-prefix>
git diff --check
```

当前仓库已有测试应保持全部通过；新增基线测试失败时，先修正测试夹具或记录差异原因，不得直接放宽断言。

##### 0.2 阶段 0 验收标准
1. 默认和 `--no-llm` 报告经过两次运行后确定性字段一致；
2. 单源失败仍有结构化报告，且失败来源明确；
3. resume 结果与无中断基线一致；
4. trace summary 可生成，且不含 `raw_payload`、凭据或完整外部描述；
5. 基线文件、比较规则和已知限制已提交到文档；
6. 工作区没有数据库、缓存、trace 和临时输出；
7. 阶段 0 不产生 `src/magent` 行为变更。

##### 0.3 阶段 0 建议提交
```text
test(vulntell): capture migration baseline scenarios
test(vulntell): add deterministic report comparison helpers
docs(vulntell): freeze phase-0 baseline and compatibility rules
```

#### 四、阶段 1：建立 apps/vulntell 外壳
##### 1.1 目标目录
阶段 1 只创建最小外壳，不提前迁移所有业务模块：

```text
apps/
├── __init__.py
└── vulntell/
    ├── __init__.py
    ├── __main__.py
    ├── config.py
    └── application.py
```

`apps/vulntell` 初期可以通过适配层调用 `examples.vulntell` 的现有 `run_once` 或等价公开函数，但适配调用必须集中在一个位置；不得在新目录散落旧模块导入。

##### 1.2 Task 1.1：配置对象
定义不可变或只读配置对象，统一 CLI 和未来 API 的输入：

```python
class VulnTellConfig:
    db: str = ":memory:"
    checkpoint: str = ":memory:"
    run_id: str = "vulntell-demo-run"
    no_llm: bool = False
    json_output: bool = False
    faulty_sources: frozenset[str] = frozenset()
    trace_prefix: str | None = None
    resume: bool = False
```

要求：

- CLI 参数转换为配置只做解析和校验，不执行副作用；
- 路径使用 `pathlib.Path`，fixture 路径不依赖当前工作目录；
- 未知来源、空 run id、非法 checkpoint 组合应尽早报错；
- 配置对象不得保存 API key 明文或原始漏洞文本。

##### 1.3 Task 1.2：应用生命周期
定义应用服务，负责组装依赖和执行一次任务：

```python
class VulnTellApplication:
    def __init__(self, config: VulnTellConfig, *, provider=None): ...

    async def run(self) -> VulnTellRunResult: ...
```

`run()` 内部负责：

1. 加载固定 dataset metadata；
2. 创建业务 store、checkpoint store 和 side-effect sink；
3. 构建 VulnTell graph；
4. 执行或恢复 GraphExecutor；
5. 转换为结构化运行结果；
6. 关闭数据库和可关闭资源。

应用服务不得重新实现 Graph 调度、重试、Checkpoint 或状态合并。

建议结果对象至少包含：

```python
class VulnTellRunResult:
    final_state: VulnTellState
    execution_report: ExecutionReport
    report: Report | None
```

##### 1.4 Task 1.3：新 CLI
实现 `apps/vulntell/__main__.py`：

- 复用现有参数语义：`--db`、`--checkpoint`、`--run-id`、`--resume`、`--no-llm`、`--json`、`--faulty`、`--trace`；
- 参数解析后创建 `VulnTellConfig`；
- 调用 `VulnTellApplication.run()`；
- 保持退出码：成功为 0，运行失败为 1，KeyboardInterrupt 为 130；
- 人类可读输出和 JSON 输出继续沿用当前格式，避免在迁移阶段改变报告 schema。

##### 1.5 Task 1.4：旧入口兼容层
将 `examples/vulntell` 的启动逻辑收缩为兼容转发：

```python
from apps.vulntell.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
```

注意：兼容层只负责入口，不应把旧目录中的所有业务模块立即删除。阶段 1 结束时，旧业务模块仍可作为迁移过渡依赖，但新代码只能从 `apps.vulntell` 入口进入。

##### 1.6 Task 1.5：contract tests
新增 `tests/contract/vulntell/test_entrypoint_compat.py`，至少覆盖：

```text
test_default_entrypoints_are_equivalent
test_no_llm_entrypoints_are_equivalent
test_faulty_source_entrypoints_are_equivalent
test_resume_result_matches_baseline
test_trace_output_is_written_and_redacted
test_default_entrypoint_is_offline
```

不要通过比较整段 Markdown 文本实现等价测试；应比较解析后的结构化报告和执行状态。

##### 1.7 阶段 1 验收命令
```bash
python -m apps.vulntell --no-llm --json
python -m examples.vulntell --no-llm --json
python -m pytest -q tests/contract/vulntell
python -m pytest -q
mypy src/magent
git diff --check
```

验收时应额外确认：

- 两个入口的 canonical、pending、quality issues、metrics、source status 一致；
- `--resume` 使用相同 checkpoint 时不重复提交业务副作用；
- `--trace` 的 JSONL 和 summary 均可生成；
- 默认命令没有 HTTP 请求；
- `src/magent` 没有新增 VulnTell import；
- 没有复制第二份业务 Graph 或 Agent。

##### 1.8 阶段 1 建议提交
```text
feat(vulntell): add apps package and application shell
feat(vulntell): add config and application lifecycle
test(vulntell): add old/new entrypoint contract tests
refactor(vulntell): route examples entrypoint through apps
docs(vulntell): document phase-1 migration boundary
```

#### 五、问题处理和升级规则
##### 5.1 发现输出差异时
按以下顺序排查：

1. 是否包含时间、UUID、trace id 等非确定字段；
2. 是否存在列表顺序差异；
3. 是否因工作目录导致 fixture 路径不同；
4. 是否因资源关闭顺序导致 SQLite/checkpoint 差异；
5. 是否确实改变了业务状态或报告 schema。

前四类应修复适配或比较器；第五类必须停止迁移，记录差异并获得维护者确认。

##### 5.2 何时修改 magent
阶段 0–1 默认禁止修改 `magent`。只有满足以下条件才可另开框架任务：

- 问题可用与 CVE 无关的最小例子复现；
- 已证明不是入口、资源生命周期或业务适配错误；
- 有明确的通用 API 设计和回归测试；
- 变更不会破坏现有 260 个测试和 VulnTell contract tests。

##### 5.3 何时暂停阶段 1
出现以下任一情况应暂停迁移并报告：

- 新旧入口业务结果无法解释地不一致；
- resume 重复执行已提交副作用；
- 默认入口发生网络访问；
- Trace/日志包含原始漏洞文本或凭据；
- 为了迁移而复制两份长期维护的业务实现。

#### 六、阶段 0–1 完成定义
```text
基线场景和报告冻结
        ↓
结构化比较规则和安全门禁
        ↓
apps/vulntell 配置与应用外壳
        ↓
新 CLI 与旧入口兼容转发
        ↓
新旧入口 contract tests
        ↓
全量测试、类型检查、离线和恢复验收
```

阶段 1 完成后，下游 agent 才可开始阶段 2（领域层迁移）；阶段 2 的首个任务应是把 `models/loading/normalize/dedupe/metrics/report` 迁移到 `apps/vulntell/domain`，而不是提前接入真实数据源。


<a id="phase-doc-phase2-plan"></a>

## 原文：PHASE2_PLAN.md

### VulnTell 阶段 2：领域层迁移实施计划（已完成）
> 本文同时记录阶段 0–1 的完成审查结果，作为阶段 2 的进入基线。

#### 1. 审查结论
当前工作区已经完成 VulnTell 阶段 0–2 的主要实现，但仍处于迁移开发工作区状态，尚未形成独立的阶段发布提交。

阶段 0 已完成：基线、确定性比较、部分失败、安全边界和恢复等价测试已经落地。

阶段 1 已完成：apps/vulntell 外壳、新 CLI、配置对象、应用生命周期、旧入口转发和新旧入口 contract tests 已落地。

阶段 2 已完成：领域实现已迁移到 apps/vulntell，阶段 0–1 的行为等价性保持不变。下一阶段进入阶段 3：Graph 与任务层迁移。

#### 2. 证据与当前状态
##### 2.1 阶段 0
| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 基线场景 | 已完成 | docs/vulntell/baseline.md、tests/contract/vulntell/baselines/ |
| 默认/无 LLM 确定性 | 已完成 | test_baseline_freeze.py |
| 单源失败降级 | 已完成 | baseline_faulty_cnvd.json、contract test |
| resume 等价与幂等 | 已完成 | baseline_resume.json、恢复测试 |
| Trace 脱敏 | 已完成 | trace contract test |
| 默认离线 | 已完成 | socket/connect 拦截测试 |
| 版本与报告比较规则 | 已完成 | tests/contract/vulntell/helpers.py |

##### 2.2 阶段 1
| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| apps.vulntell 包和入口 | 已完成 | apps/vulntell/__main__.py |
| 只读配置 | 已完成 | apps/vulntell/config.py |
| 应用生命周期 | 已完成 | apps/vulntell/application.py |
| 公共编排适配层 | 已完成 | examples/vulntell/run.py |
| 旧入口兼容转发 | 已完成 | examples/vulntell/__main__.py |
| 新旧入口等价 | 已完成 | tests/contract/vulntell/test_entrypoint_compat.py |
| 真实网络、API、Web、PostgreSQL | 未开始（符合计划） | 阶段 0–3 明确禁止 |

##### 2.3 验证结果
本次审查执行结果：

- python -m pytest -q：286 passed；
- mypy src/magent：通过；
- python -m apps.vulntell --no-llm --json：成功；
- python -m examples.vulntell --no-llm --json：成功；
- 新旧入口报告确定性字段一致；
- Markdown 链接检查：0 个断链。

以上是当前工作区结果。阶段 0–2 的文件尚未全部提交为独立 release commit；下游 agent 开始阶段 3 前应先完成提交或明确保留当前工作区变更。

#### 3. 当前架构事实
阶段 1 是“入口已迁移，业务实现未迁移”：

    apps/vulntell
        config.py
        application.py
        __main__.py
            ↓ 适配调用
    examples/vulntell
        run.py
        agents.py / graph.py / state.py
        models.py / normalize.py / dedupe.py
        metrics.py / report.py / db.py / sources.py

这符合阶段 1 设计，但不能被误认为 VulnTell 已完成目录迁移。

#### 4. 尚未完成的阶段
| 阶段 | 状态 | 当前缺口 |
| --- | --- | --- |
| 阶段 2：领域层迁移 | 已完成 | domain、reporting、fixtures 已迁移；旧模块保留 re-export |
| 阶段 3：Graph/任务层迁移 | 已完成 | 详见 [PHASE3_RESULT.md](PHASES.md#phase-doc-phase3-result) |
| 阶段 4：数据源契约与增量 | 下一阶段 | 详见 [PHASE4_PLAN.md](PHASES.md#phase-doc-phase4-plan) |
| 阶段 5：真实数据源 | 未开始 | HTTP adapter 仍为禁用接口 |
| 阶段 6：存储与查询 | 未开始 | 仍是示例 SQLite，无 repository/query service |
| 阶段 7：指标与报告产品化 | 未开始 | 指标和导出仍是示例级固定实现 |
| 阶段 8：CLI/API 任务服务 | 未开始 | 只有示例 CLI，无稳定 API |
| 阶段 9：安全/部署/发布 | 未开始 | 无服务认证、部署和运维闭环 |
| 阶段 10：兼容收口/看板 | 未开始 | 旧入口仍需经过弃用周期 |

magent 阶段 1–8 的能力已有测试覆盖；阶段 9 为候选发布状态。框架阶段完成不等于 VulnTell 产品完成。

#### 5. 阶段 2 实施任务与验收（已完成）
##### 5.1 目标
领域模型和纯业务规则已从 examples/vulntell 迁移到 apps/vulntell；新应用的领域层不再依赖旧目录，且阶段 0–1 的所有可观察行为保持不变。

阶段 2 完成后，examples/vulntell 的领域模块只剩 re-export；db、sources、state、agents、graph 和 run 仍作为阶段 3 的过渡实现。

##### 5.2 目标目录
    apps/vulntell/
    ├── domain/
    │   ├── models.py
    │   ├── schemas.py
    │   ├── normalize.py
    │   ├── dedupe.py
    │   ├── metrics.py
    │   └── policies.py
    ├── reporting/
    │   ├── report.py
    │   └── exporters.py
    └── fixtures/
        ├── dataset_meta.json
        ├── nvd_sample.json
        └── cnvd_sample.json

阶段 2 可以暂时保留 examples/vulntell 的 db、sources、agents、graph、state，但新应用不得新增对旧领域模块的依赖。

##### 5.3 任务拆分
###### Task 2.1：依赖和模块清单
建立迁移映射：

| 旧模块 | 新模块 | 类型 |
| --- | --- | --- |
| models.py | domain/models.py | 领域模型 |
| loading.py | domain/schemas.py 或 config.py | 数据集加载 |
| normalize.py | domain/normalize.py | 纯规则 |
| dedupe.py | domain/dedupe.py | 纯规则 |
| metrics.py | domain/metrics.py | 纯指标 |
| report.py | reporting/report.py | 报告组装/导出 |
| fixtures/ | apps/vulntell/fixtures/ | 应用数据 |

记录公开符号、输入输出类型和依赖，避免隐式改变 API。

###### Task 2.2：迁移模型和 schema
迁移 DatasetMeta、RawSourceRecord、SourceObservation、CanonicalVulnerability、QualityIssue、MetricSnapshot、Report 等模型。

要求：

- 保持字段名、类型、默认值和序列化格式；
- 明确 schema version；
- UTC 时间继续使用带时区类型；
- 原始载荷只保留 hash/ref；
- 未知、缺失和非法字段策略保持一致；
- 新模型不导入 magent 内部实现。

###### Task 2.3：迁移纯规则
迁移日期、CVSS、CWE、引用和产品字段标准化、质量问题、CVE 强匹配、pending、跨源冲突、volume/timeliness/completeness 指标以及结构化报告。

迁移完成后只保留一份真实实现，不得长期双写或双算。

###### Task 2.4：迁移 fixture 和路径解析
将 fixture 复制到 apps/vulntell/fixtures，并把路径解析集中到应用配置：

- 不依赖当前工作目录；
- CLI 和测试使用同一 fixture root；
- 保留 dataset id/version/window；
- 校验 fixture 版本；
- 不把数据库和 trace 输出提交到仓库。

###### Task 2.5：领域 contract tests
新增或迁移以下测试：

    test_models_round_trip_is_stable
    test_normalize_matches_baseline
    test_dedupe_matches_baseline
    test_metrics_matches_baseline
    test_report_matches_baseline
    test_invalid_fields_keep_quality_issues
    test_conflicts_are_traceable
    test_domain_has_no_network_or_framework_side_effect

测试直接调用 apps.vulntell.domain，不以 CLI 替代领域单元测试。

###### Task 2.6：切换应用依赖
导入方向应变为：

    apps.vulntell.application
        → apps.vulntell.domain / reporting
        → examples.vulntell.pipeline 过渡模块（如仍需要）

禁止：

    apps.vulntell.domain → examples.vulntell 领域模块
    src/magent → apps.vulntell

###### Task 2.7：清理和兼容
确认新旧入口使用同一份领域实现后：

- 删除旧领域模块，或改成明确的 re-export；
- 更新 docstring、README 和 import 示例；
- 在弃用周期内保留旧 import 的转发或可解释错误；
- 更新 coverage、mypy 和包路径检查。

##### 5.4 阶段 2 验收标准
1. apps.vulntell.domain 和 apps.vulntell.reporting 可独立导入；
2. 新应用不再依赖旧目录领域实现；
3. 默认、无 LLM、单源失败、resume、trace 与阶段 0 基线等价；
4. canonical、pending、source_status、quality issues、metrics、report 逐字段一致；
5. 标准化、去重、指标和报告有直接 unit/contract tests；
6. fixture 路径与当前工作目录无关；
7. 无网络、外部命令和密钥依赖；
8. src/magent 无 VulnTell import；
9. 全量 pytest、mypy、离线 CLI 和链接检查通过；
10. 不存在双写、双算或随机选择结果；
11. 文档明确阶段 2 已完成、阶段 3 尚未开始；
12. 迁移差异、弃用策略和回滚方式有记录。

建议命令：

    python -m pytest -q tests/contract/vulntell
    python -m pytest -q tests/unit
    python -m apps.vulntell --no-llm --json
    python -m examples.vulntell --no-llm --json
    mypy src/magent
    git diff --check

#### 6. 风险与控制
| 风险 | 控制 |
| --- | --- |
| Pydantic 序列化变化 | 使用冻结 baseline 逐字段比较 |
| 相对路径导致 fixture 不一致 | 所有路径从模块位置或配置解析 |
| 新旧模块循环导入 | 应用层单向组装，先画依赖图 |
| 两套实现结果漂移 | 迁移完成后只保留一份实现 |
| 误把 fixture 迁移当真实数据接入 | 阶段 2 明确禁止 live adapter |
| 为迁移修改 magent | 先在业务层修复；通用问题另开框架任务 |
| 删除旧模块导致外部 import 失败 | 保留短期 re-export/弃用提示 |

#### 7. 后续阶段入口
阶段 2 已通过验收，进入阶段 3：

- 迁移 VulnTellState、Agent、Graph 和任务生命周期；
- 让 VulnTellApplication 不再依赖 examples.vulntell.run；
- 统一 full/incremental/resume/replay 任务模型；
- 保持 magent 执行语义不变。

阶段 3 已通过；下一阶段进入阶段 4 数据源契约设计。在 SourceAdapter、SourcePage、游标和错误语义冻结前，不接入真实 HTTP。

#### 8. 下游 agent 交付格式
每个阶段 2 任务提交时必须说明：

1. Task 编号和范围；
2. 迁移、新增、删除的文件；
3. 新旧导入关系；
4. 测试命令和结果；
5. 与 baseline 的差异；
6. 是否改变 schema、报告、checkpoint 或公开入口；
7. 未解决风险和下一 Task 依赖。


<a id="phase-doc-phase2-result"></a>

## 原文：PHASE2_RESULT.md

### VulnTell 阶段 2 完成记录
> 依据 `PHASE2_PLAN.md` 实施领域层迁移。本文件记录迁移差异、弃用策略与回滚方式。阶段 2 已完成；阶段 3（运行时编排迁移）也已完成，见 [PHASE3_RESULT.md](PHASES.md#phase-doc-phase3-result)。

#### 1. 迁移映射
| 旧模块 (examples/vulntell) | 新模块 (apps/vulntell) | 类型 |
| --- | --- | --- |
| models.py | domain/models.py | 领域模型（逐字段、类型、默认值、序列化不变） |
| loading.py | domain/schemas.py | 数据集 / fixture 加载 |
| normalize.py | domain/normalize.py | 纯标准化规则 |
| dedupe.py | domain/dedupe.py | 纯去重 / 聚合规则 |
| metrics.py | domain/metrics.py | 纯指标计算 |
| report.py | reporting/report.py + reporting/exporters.py | 报告组装 / 导出 |
| fixtures/ | apps/vulntell/fixtures/ | 应用数据（内容与原 fixture 逐字节一致） |
| — | domain/policies.py | 新增：跨源优先级、相关性画像、最小样本、必需字段、校验正则 |

`state.py` / `agents.py` / `graph.py` / `run.py` 已在**阶段 3** 迁移为 `apps.vulntell.pipeline`
下的真实实现；`examples/vulntell/{state,agents,graph,run}.py` 现为转发到 `apps.vulntell.pipeline`
的薄壳。`db.py` / `sources.py` 仍保留在 `examples/vulntell`（阶段 6 / 阶段 4 再迁移），并由
`apps.vulntell/storage/legacy.py` 与 `apps.vulntell/sources/legacy.py` 集中 re-export，不复制逻辑。

#### 2. 导入方向
```
apps.vulntell.application
    → apps.vulntell.pipeline.jobs.VulnTellJobRunner   (阶段 3 起唯一编排入口)
    → apps.vulntell.pipeline.{state,agents,graph}       (真实实现)
    → apps.vulntell.storage.legacy / sources.legacy      (阶段 3/4/6 过渡包装)

apps.vulntell.pipeline
    → apps.vulntell.domain / apps.vulntell.reporting      (真实实现)
    → examples.vulntell.db / examples.vulntell.sources     (仅经 legacy 包装，阶段 3 不复制逻辑)

apps.vulntell.domain / reporting
    → 仅依赖 pydantic 与 magent.checkpoint.models 的纯工具函数
    → 不导入 examples、不导入 magent 运行时 / 编排
```

约束已满足：`apps.vulntell.domain` 不导入 `examples`；`src/magent` 无 VulnTell import。

#### 3. 兼容与弃用策略
旧领域模块（`examples/vulntell/{models,loading,normalize,dedupe,metrics,report}.py`）
改为**明确的 re-export 转发**到 `apps.vulntell.domain` / `reporting`，并标注弃用说明：
- 真实实现只有一份，位于 `apps`；旧模块不再包含业务代码；
- 既有 `from examples.vulntell... import ...` 的外部调用（tests、benchmarks）继续可用；
- 阶段 3 完成、Graph/任务层迁移后，再移除这些 re-export 并进入弃用周期。

#### 4. 与阶段 0 基线差异
无 schema / 报告 / checkpoint / 公开入口变更。默认、无 LLM、单源失败、resume、trace
场景与 `tests/contract/vulntell/baselines/` 冻结基线逐字段一致（contract tests 覆盖）。
fixture 改为从 `apps.vulntell.fixtures` 解析（路径与当前工作目录无关），内容为原 fixture
的逐字节副本，因此行为等价。

#### 5. 回滚方式
- 若阶段 2 引入回归：保留的 `examples` re-export 可立即切回 `examples.vulntell` 旧模块
  （git 历史中仍可用）；新代码与旧代码通过同一份 `apps.vulntell.domain` 实现，不存在
  双份逻辑，回滚不会造成结果漂移。
- 验证命令：`python -m pytest -q tests/contract/vulntell tests/unit`、`mypy src/magent`、
  `python -m apps.vulntell --no-llm --json` 与 `python -m examples.vulntell --no-llm --json`
  输出应逐字段一致。

#### 6. 后续阶段
阶段 2 与阶段 3 均已完成。阶段 4（数据源迁移至 `apps.vulntell.sources`）与阶段 6
（存储迁移至 `apps.vulntell.storage`）将替换当前 legacy 过渡包装，届时移除
`examples/vulntell/{db,sources}.py` 与 legacy 转发。具体任务、依赖和验收标准见
[PHASE3_PLAN.md](PHASES.md#phase-doc-phase3-plan) 与 [PHASE3_RESULT.md](PHASES.md#phase-doc-phase3-result)。


<a id="phase-doc-phase3-plan"></a>

## 原文：PHASE3_PLAN.md

### VulnTell 阶段 3：Graph 与任务层迁移实施计划（已完成）
> 本计划已执行完毕。审查结论与遗留问题见 [PHASE3_REVIEW.md](PHASES.md#phase-doc-phase3-review)，实施结果见 [PHASE3_RESULT.md](PHASES.md#phase-doc-phase3-result)。以下内容保留作为下游复盘和回滚依据。

#### 1. 进入基线
阶段 0–1 已完成基线冻结与应用外壳，阶段 2 已完成领域层迁移。当前验证基线：

- `python -m pytest -q`：286 passed；
- `mypy src/magent`：通过；
- `python -m apps.vulntell --no-llm --json` 与旧入口结构化报告等价；
- `apps.vulntell.domain`、`apps.vulntell.reporting` 为真实实现；
- `examples.vulntell` 的 models/loading/normalize/dedupe/metrics/report 仅保留 re-export；
- `apps.vulntell.application` 仍依赖 `examples.vulntell.run` 和 `examples.vulntell.state`；
- `db.py`、`sources.py`、`agents.py`、`graph.py` 仍在 examples 目录；
- HTTP source adapter 仍明确禁用，阶段 3 不接入真实网络。

阶段 3 的唯一重点是迁移运行时编排，不改变领域规则、报告 schema、magent 执行语义或真实数据源范围。

#### 2. 阶段目标
完成后应达到：

1. `apps.vulntell.application` 不再依赖 `examples.vulntell.run`；
2. `VulnTellState`、业务 Agent、Graph 和 run/resume 生命周期位于 `apps.vulntell.pipeline`；
3. CLI、未来 API 和定时任务都调用同一个应用服务；
4. full run、resume、replay（语义等同于当前恢复）入口统一；
5. 部分来源失败、Checkpoint、幂等、Trace 和 LLM 边界保持不变；
6. `examples.vulntell` 只承担兼容入口和短期 re-export，不承载新的编排实现。

阶段 3 不实现分页/游标、真实 HTTP、PostgreSQL、查询 API、Web 看板或分布式任务队列；这些属于后续阶段。

#### 3. 目标目录
    apps/vulntell/
    ├── application.py
    ├── pipeline/
    │   ├── __init__.py
    │   ├── state.py
    │   ├── agents.py
    │   ├── graph.py
    │   └── jobs.py
    ├── sources/
    │   └── legacy.py       # 阶段 3 过渡包装，阶段 4 替换
    └── storage/
        └── legacy.py       # 阶段 3 过渡包装，阶段 6 替换

`legacy.py` 只能集中承载旧 `examples.vulntell.db/sources` 的兼容导入，不能复制业务逻辑。阶段 3 结束时应有明确的替换清单和删除时间点。

#### 4. 任务拆分
##### Task 3.1：依赖图和接口冻结
建立模块依赖图和迁移映射：

| 当前模块 | 阶段 3 目标 | 处理 |
| --- | --- | --- |
| examples/vulntell/state.py | apps/vulntell/pipeline/state.py | 迁移真实实现 |
| examples/vulntell/agents.py | apps/vulntell/pipeline/agents.py | 迁移真实实现并改导入 |
| examples/vulntell/graph.py | apps/vulntell/pipeline/graph.py | 迁移真实实现并改导入 |
| examples/vulntell/run.py | apps/vulntell/pipeline/jobs.py | 迁移 run/resume 编排 |
| examples/vulntell/sources.py | apps/vulntell/sources/legacy.py | 过渡 re-export |
| examples/vulntell/db.py | apps/vulntell/storage/legacy.py | 过渡 re-export |

冻结以下公开契约：`VulnTellState` 字段与 reducers、`PipelineResult`/新结果对象、`build_vulntell_graph` 参数、run/resume 退出码和 checkpoint 元数据。

验收：

- 依赖图中没有 pipeline → examples 领域模块的反向依赖；
- 新旧模块的公开符号有迁移表；
- 未经确认不得改报告 schema 或执行参数。

##### Task 3.2：迁移 State
将 `VulnTellState` 迁移到 `apps.vulntell.pipeline.state`。

要求：

- 字段、默认值、Pydantic 序列化和 reducers 完全一致；
- State 只包含可 checkpoint 的 dict/list/标量；
- 不把数据库连接、adapter、provider 或 logger 放进 State；
- 保持 source_status、failed_sources、metrics、report 语义；
- 增加 state schema hash 回归断言。

验收：

- state round-trip 测试通过；
- 与阶段 0 baseline 的状态/报告一致；
- checkpoint 写入和恢复成功；
- 并发 join 的 reducer 顺序不变。

##### Task 3.3：迁移业务 Agent
将 Collect、Normalize、Dedupe、Persist、Evaluate、Report Agent 迁移到 `pipeline/agents.py\)。

依赖必须通过构造函数注入：

- SourceAdapter；
- repository/store；
- ToolRegistry/SideEffectSink；
- LLM Provider；
- 运行配置。

要求：

- Agent 只通过 AgentResult 提议状态更新；
- 采集失败继续使用部分失败降级；
- Persist 仍通过工具 allowlist 和 SideEffectSink；
- Evaluate 使用确定性规则；
- Report 的 LLM 只写 explanation，不改指标；
- 不在 Agent 内部读取环境变量、系统时间或创建全局连接。

验收：

- 每个 Agent 有独立 unit tests；
- flaky、超时、取消和 provider 失败行为与原实现一致；
- 无业务 Agent 导入 `examples.vulntell` 领域模块；
- raw payload 不进入 trace、日志和 LLM prompt。

##### Task 3.4：迁移 Graph
将 GraphBuilder 构建逻辑迁移到 `pipeline/graph.py\)。

目标拓扑保持：

    dispatch
      ├── collect_nvd → normalize_nvd ┐
      └── collect_cnvd → normalize_cnvd ├→ dedupe → persist → evaluate → report → END

要求：

- 节点名、边、join、并发度和 reducer 语义保持；
- Graph 构建函数接收依赖，不隐式读取全局路径；
- checkpoint 的 workflow/node version 保持兼容；
- 失败来源仍能继续到评估和报告；
- 不在 Graph 中加入业务之外的调度判断。

验收：

- graph validation、并发、join、部分失败、恢复和幂等测试通过；
- 新 Graph 与旧 Graph 的报告逐字段等价；
- 节点调用顺序和 checkpoint frontier 可审计。

##### Task 3.5：迁移任务生命周期
将 `examples.vulntell.run.run_vulntell` 迁移为 `apps.vulntell.pipeline.jobs.run_vulntell` 或 `VulnTellJobRunner`。

建议接口：

    class VulnTellJobRunner:
        async def run(self) -> VulnTellRunResult: ...
        async def resume(self, run_id: str) -> VulnTellRunResult: ...

职责：

1. 加载 dataset metadata；
2. 组装 store、checkpoint store、sink、provider 和 adapters；
3. 构建并运行 GraphExecutor；
4. 转换结构化结果；
5. 关闭资源并报告清理错误。

要求：

- `application.py` 只依赖 jobs 和 domain/reporting；
- full/resume 使用同一 runner；
- 资源关闭使用 `try/finally`；
- checkpoint、run_id、workflow_version 和 provider 配置显式传递；
- 失败时保留 ExecutionReport，不吞掉原始错误。

验收：

- `apps.vulntell.application` 不再导入 `examples.vulntell.run/state/graph/agents`；
- CLI 与应用服务使用同一 runner；
- full、resume、故障注入和 trace contract tests 通过；
- 应用生命周期异常时数据库和 checkpoint 连接均关闭。

##### Task 3.6：更新旧入口和兼容层
`examples.vulntell.__main__` 继续只转发到 `apps.vulntell`。

对于旧的 `examples.vulntell.state/agents/graph/run`：

- 若外部测试或 benchmark 仍依赖，保留明确 re-export；
- re-export 文件不得保留第二份实现；
- docstring 标注弃用和预计移除版本；
- 新测试全部改用 `apps.vulntell.pipeline`；
- 阶段 3 完成后不得新增 examples 导入。

验收：

- 新旧 CLI 输出等价；
- 旧 import 在兼容周期内可用；
- 静态扫描显示新业务实现均位于 apps；
- 删除兼容层时有回滚提交和迁移说明。

##### Task 3.7：迁移测试和文档
新增 `tests/contract/vulntell/test_pipeline_migration.py`，至少覆盖：

    test_pipeline_modules_import_without_examples_domain
    test_state_schema_and_reducers_are_stable
    test_graph_report_matches_baseline
    test_partial_failure_matches_baseline
    test_resume_is_idempotent
    test_application_closes_resources
    test_new_pipeline_has_no_network_side_effect
    test_old_entrypoint_remains_compatible

同步更新：

- `docs/vulntell/PHASE2_RESULT.md`：阶段 3 开始/完成状态；
- `docs/vulntell/ROADMAP.md`：阶段 2 已完成、阶段 3 进行中；
- `docs/vulntell/FINAL_DESIGN.md`：pipeline 目录和依赖方向；
- README/API 中的示例入口；
- 弃用和回滚说明。

#### 5. 阶段 3 验收标准
必须全部满足：

1. `apps.vulntell.pipeline` 可独立导入；
2. `application.py` 不依赖 `examples.vulntell.run/state/agents/graph`；
3. State、Agent、Graph、run/resume 全部使用 apps 真实实现；
4. 默认、无 LLM、单源失败、resume、trace 与阶段 0 baseline 逐字段等价；
5. 重复运行不新增 observation、canonical、metric 或 side effect；
6. 中断后只重放未提交节点，已提交节点不重复执行；
7. CLI/API（若已有实验入口）共享应用 runner；
8. 默认运行不访问网络，不需要 key，不执行外部命令；
9. trace、日志、checkpoint 和报告不包含 raw payload 或凭据；
10. 所有新增通用问题都有业务无关的最小复现，否则不得修改 magent；
11. 旧入口兼容策略、删除时间点和回滚方式有文档；
12. 全量测试、类型检查、离线 CLI 和链接检查通过。

建议命令：

    python -m pytest -q tests/contract/vulntell tests/unit
    python -m pytest -q
    mypy src/magent
    python -m apps.vulntell --no-llm --json
    python -m examples.vulntell --no-llm --json
    git diff --check

#### 6. 风险和控制
| 风险 | 控制 |
| --- | --- |
| State schema/hash 改变导致 checkpoint 不兼容 | 迁移前后做 hash 和 resume contract test |
| Agent 导入循环 | 采用 pipeline → domain/sources/storage 的单向依赖 |
| 运行资源泄漏 | runner 统一 try/finally，并增加异常路径测试 |
| 旧入口和新入口逻辑分叉 | 旧目录只 re-export，不保留编排代码 |
| 过渡 wrapper 长期残留 | 每个 wrapper 标明替换阶段和删除条件 |
| 为解决迁移问题修改 magent | 先用业务无关最小复现，另开框架任务 |
| 过早引入真实网络 | 阶段 3 明确禁止，阶段 4 先冻结契约 |

#### 7. 阶段 3 完成后的下一步
阶段 3 通过后进入阶段 4：数据源契约与增量模型。

阶段 4 首先定义 SourceRequest、SourcePage、游标、SyncRun、错误分类和分页 fixture，再实现 NVD/CNVD/CISA KEV 的真实 adapter。未完成这些契约前，不允许直接在生产代码中接入 HTTP。

#### 8. 下游 agent 交付格式
每个 Task 提交时必须说明：

1. Task 编号、范围和未包含内容；
2. 新增、迁移、删除和 re-export 文件；
3. 导入依赖方向；
4. State/schema/checkpoint 是否变化；
5. contract/unit/integration 测试命令和结果；
6. 与 baseline 的结构化 diff；
7. 资源关闭、错误处理和安全检查结果；
8. 遗留 wrapper、风险和下一 Task 依赖。


<a id="phase-doc-phase3-result"></a>

## 原文：PHASE3_RESULT.md

### VulnTell 阶段 3 完成记录
> 依据 `PHASE3_PLAN.md` 实施运行时编排迁移。本文件记录迁移差异、弃用策略与回滚方式。
> 阶段 3 已完成：业务编排（State / Agent / Graph / 任务生命周期）已从 `examples.vulntell`
> 迁移到 `apps.vulntell.pipeline`，`apps.vulntell.application` 不再依赖 `examples.vulntell.run`。

#### 1. 迁移映射
| 旧模块 (examples/vulntell) | 新模块 (apps/vulntell) | 类型 |
| --- | --- | --- |
| state.py | pipeline/state.py | 业务执行 State（语义、reducers 不变） |
| agents.py | pipeline/agents.py | 业务 Agent（采集/标准化/去重/持久化/评估/报告） |
| graph.py | pipeline/graph.py | Graph 组装（拓扑、节点名不变） |
| run.py | pipeline/jobs.py | `run_vulntell` + `VulnTellJobRunner`（run/resume） |
| — | pipeline/__init__.py | 统一导出编排实现 |
| — | sources/legacy.py | 仅 re-export `examples.vulntell.sources`（阶段 4 替换） |
| — | storage/legacy.py | 仅 re-export `examples.vulntell.db`（阶段 6 替换） |

`db.py` / `sources.py` 按计划保留在 `examples/vulntell`（阶段 6 / 阶段 4 再迁移），由 legacy
过渡包装集中引用，**未复制任何业务逻辑**。`examples/vulntell/{state,agents,graph,run}.py`
现为转发到 `apps.vulntell.pipeline` 的薄壳，不含业务代码。

#### 2. 导入方向（阶段 3 后）
```
apps.vulntell.application / examples.vulntell.__main__
    → apps.vulntell.pipeline.jobs.VulnTellJobRunner   (唯一编排入口)
    → apps.vulntell.pipeline.{state,agents,graph}      (真实实现)

apps.vulntell.pipeline
    → apps.vulntell.domain / apps.vulntell.reporting    (真实实现)
    → apps.vulntell.sources.legacy / storage.legacy     (阶段 3/4/6 过渡)
        → examples.vulntell.sources / examples.vulntell.db  (仅经 legacy，不复制逻辑)

examples.vulntell.{state,agents,graph,run}
    → apps.vulntell.pipeline.*   (薄壳转发，单一实现)
```

约束已满足：
- `apps.vulntell.pipeline` 与 `apps.vulntell.application` 不 import `examples.vulntell.{run,state,agents,graph}`；
- `apps.vulntell.domain` / `reporting` 不导入 `examples`、不导入 `magent` 运行时 / 编排；
- `legacy.py` 仅承载兼容导入，未复制 `db` / `sources` 逻辑。

#### 3. 行为与边界（未变）
- 确定性结果、部分失败语义、checkpoint / resume / 幂等、trace、LLM 边界与阶段 0 冻结基线一致；
- HTTP source adapter 在阶段 3 仍明确禁用，默认运行不发起任何网络连接（contract 测试屏蔽 socket 验证）；
- `magent` 的执行语义（fail_fast、reducer 合并、side-effect 幂等）未改动。

#### 4. 兼容与弃用策略
- 旧模块 `examples/vulntell/{state,agents,graph,run}.py` 改为明确的 re-export 转发，并标注
  “阶段 3 已迁移”说明；既有 `from examples.vulntell... import ...` 的外部调用（tests、benchmarks）
  继续可用，且现在指向 `apps` 的同一份实现。
- `run_vulntell` 的调用形态（关键字参数、返回结构）保持不变，contract 测试直接复用。
- 阶段 4 / 6 完成、正式实现替换 legacy 后，再移除 `examples/vulntell/{db,sources}.py` 与 legacy 转发。

#### 5. 与阶段 0 基线差异
无 schema / 报告 / checkpoint / 公开入口变更。默认、无 LLM、单源失败、resume、trace 场景与
`tests/contract/vulntell/baselines/` 冻结基线逐字段一致。新增
`tests/contract/vulntell/test_pipeline_migration.py`（10 个测试）覆盖：apps 不依赖旧运行时模块、
State schema / reducers 稳定、报告等价于基线、部分失败等价于基线、resume 幂等、应用关闭资源、
无网络副作用、旧入口为转发且与 apps 入口等价。

#### 6. 验证命令
```
python -m pytest -q            # 296 passed（含 10 个阶段 3 contract 测试）
python -m mypy src/magent      # Success
python -m apps.vulntell --no-llm --json
python -m examples.vulntell --no-llm --json   # 两份入口输出逐字段一致
```

#### 7. 后续阶段
阶段 4：将 `examples.vulntell.sources` 迁移至 `apps.vulntell.sources`，替换 `sources/legacy.py`，
并接入/禁用真实数据源（HTTP adapter）。
阶段 6：将 `examples.vulntell.db` 迁移至 `apps.vulntell.storage`，替换 `storage/legacy.py`，
并强化幂等回放与事务语义。


<a id="phase-doc-phase3-review"></a>

## 原文：PHASE3_REVIEW.md

### VulnTell 阶段 3 审查记录
#### 结论
阶段 3（Graph 与任务层迁移）已完成，可进入阶段 4“数据源契约与增量模型”。当前不建议直接接入真实 HTTP；应先冻结分页、游标、同步运行和错误分类契约。

#### 已完成项
- `apps.vulntell.pipeline` 已包含 State、业务 Agent、Graph 和任务 Runner；
- `apps.vulntell.application` 直接依赖 `pipeline.jobs`，不再依赖 `examples.vulntell.run/state/agents/graph`；
- `examples.vulntell` 的对应模块仅保留兼容 re-export；数据源和存储仍通过 `legacy.py` 过渡；
- full run、resume、部分来源失败、幂等、资源关闭和无网络行为已有 contract 覆盖；
- 新旧 CLI 输出结构化等价；领域层和报告层未反向依赖 examples 或 magent 编排实现；
- `python -m pytest -q`：296 passed；`mypy src/magent`：通过；Markdown 链接检查：0 个断链。

#### 尚未完成与技术债
1. `apps.vulntell.sources.legacy` 仍转发到 `examples.vulntell.sources`，没有分页/游标/增量协议；
2. `apps.vulntell.storage.legacy` 仍转发到 `examples.vulntell.db`，存储迁移属于阶段 6；
3. `HttpSourceAdapter` 仍是显式禁用接口，尚未实现限速、超时、重试和凭据策略；
4. 当前状态只表达一次 fixture 运行，尚未持久化 `SyncRun`、游标和批次边界；
5. 真实来源许可、字段映射和大响应/坏记录隔离尚未完成；
6. `PHASE2_PLAN.md`、`NEXT_STAGE.md` 等历史入口曾滞后，已在本次审查中同步为阶段 4。

#### 阶段门禁判定
| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 新旧入口等价 | 通过 | `test_entrypoint_compat.py`、pipeline migration contract |
| State/checkpoint/resume 稳定 | 通过 | `test_pipeline_migration.py`、baseline fixtures |
| 部分失败与幂等 | 通过 | baseline 与 migration contract |
| 默认离线、无凭据 | 通过 | 无网络 contract、CLI smoke |
| 数据源增量契约 | 未开始 | 进入阶段 4 |
| 真实 HTTP 来源 | 未开始 | 明确禁止提前接入 |

#### 下一步决策
阶段 4 只做协议、fixture 和可恢复同步骨架；完成其验收后，才允许阶段 5 开发 NVD/CNVD/CISA KEV live adapter。阶段 4/5 中发现的通用执行问题，必须先用业务无关最小复现验证，再决定是否修改 `magent`。


<a id="phase-doc-phase4-plan"></a>

## 原文：PHASE4_PLAN.md

### VulnTell 阶段 4：数据源契约与增量模型实施计划（已完成，历史记录）
> 当前实现审查见 [PHASE4_REVIEW.md](PHASES.md#phase-doc-phase4-review)。协议代码已提交，但在专门测试和持久化恢复门禁通过前，不得进入真实数据源开发。

#### 目标与范围
本阶段把当前 fixture-only `SourceAdapter.fetch()` 演进为可分页、可恢复、可审计的同步协议，为阶段 5 的真实来源接入提供稳定边界。阶段 4 不实现 NVD/CNVD/CISA KEV 的真实 HTTP 请求，不迁移存储实现，不增加 API/Web/任务队列，也不改变 `magent` 的执行语义。

完成后应能在完全离线环境中模拟完整同步生命周期：创建同步运行、按游标读取页面、批次 checkpoint、处理中断并恢复、识别重复页、分类错误并产生可审计结果。

#### 目标目录与依赖方向
```text
apps/vulntell/sources/
├── __init__.py          # 稳定公开导出
├── protocol.py          # SourceRequest/Page/Cursor/Error 契约
├── fixtures.py          # 分页 fixture adapter 与故障注入
└── errors.py            # 错误分类与 retry hint
apps/vulntell/pipeline/
└── sync.py              # SyncRun、批次边界、resume 编排
apps/vulntell/domain/
└── models.py            # 仅在必要时增加可序列化同步值对象
```

依赖必须单向：`pipeline.sync → sources.protocol/fixtures → domain`；数据源不得导入 `examples.vulntell`、Graph 实现或全局连接。阶段 4 仍可暂时由 `sources/legacy.py` 提供旧 `SourceAdapter` 兼容导出，但新代码不得依赖 legacy。

#### 任务拆分
##### 4.1 冻结请求、页面和游标协议
定义不可变、可 JSON 序列化的 `SourceRequest`（source、dataset、时间窗口、page_size、cursor、filters）、`SourcePage`（records、next_cursor、has_more、page_index、source、observed_at）和 `SyncCursor`。规定游标 opaque、大小上限、窗口边界（含/不含）、排序稳定性及 `request_fingerprint`。

验收：协议 round-trip、缺字段/超限/非法游标校验；相同请求指纹稳定；文档给出版本和兼容策略。

##### 4.2 定义同步运行与批次状态
实现 `SyncRun`/`SyncRunStatus`（pending/running/partial/succeeded/failed/cancelled）、开始/结束时间、最后成功游标、页数、记录数、错误摘要和 `source_version`。状态必须适合 checkpoint，不保存连接、响应正文或凭据。为批次生成稳定 execution key：`sync:{run_id}:{source}:{page_index}:{request_fingerprint}`。

验收：中断后可从最后成功页恢复；重复恢复不重复提交批次；状态转换非法时明确报错。

##### 4.3 构建可控的分页 Fixture Adapter
将现有 JSON fixture 包装为 `PagedFixtureSource`，支持固定 page size、空页、重复页、乱序（应被拒绝或规范化）、游标失效、单条坏记录、指定页超时/限流/权限错误和中断注入。默认 adapter 仍为离线且不创建 socket。

验收：每种场景均有可重复测试；重复页由 page fingerprint 去重；坏记录隔离并计入质量问题，不丢弃整页。

##### 4.4 错误分类与重试提示
定义 `SourceErrorKind`：`rate_limited`、`timeout`、`transient`、`invalid_response`、`auth`、`forbidden`、`not_found`、`permanent`、`cancelled`。错误对象包含 source、可安全展示的 message、retryable、retry_after、http_status（若有）和 correlation id；禁止保留 Authorization、完整 URL query 或 raw body。仅输出 retry hint，由现有执行器策略消费，不在 adapter 内自行循环重试。

验收：分类决策表和边界测试齐全；429/超时可重试，其余按契约处理；敏感字段脱敏测试通过。

##### 4.5 实现同步编排与 checkpoint 接口
新增 `SyncRunner`（或等价服务）负责创建/恢复 `SyncRun`、循环 `fetch_page`、在“页面验证→规范化→持久化成功”后提交游标 checkpoint，并在失败/取消时保存最后安全边界。与现有 `VulnTellJobRunner` 组合，但不把分页循环塞入业务 Agent。批次提交必须幂等，恢复只重放未确认页面。

验收：正常、空结果、部分失败、中断恢复、取消和重复运行均有 contract；恢复后的记录、游标和统计与无中断运行一致。

##### 4.6 兼容层与文档
保留旧 `SourceAdapter.fetch()` 的 fixture 行为至少一个兼容周期；在 `sources/legacy.py` 标注替换条件和删除版本。更新 `FINAL_DESIGN.md`、`ROADMAP.md`、`README.md`、配置说明和数据许可清单；补充阶段 5 live adapter 的前置门禁。

#### 测试与质量门禁
下游 agent 每个任务均需提供 unit + contract 测试。阶段完成前必须通过：

```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json
git diff --check
```

额外门禁：默认 CLI 无网络；游标/SyncRun schema hash 稳定；相同窗口连续同步结果一致；trace、日志、checkpoint、错误和 prompt 不含 raw payload/凭据；`magent` 无业务导入或语义变更。

#### 推荐执行顺序与交付物
1. 4.1（协议）→ 4.2（SyncRun 值对象）→ 4.3（fixture）；
2. 4.4（错误分类）→ 4.5（SyncRunner 与 checkpoint）；
3. 4.6（兼容、文档、门禁审查）。

每个任务提交说明范围、文件变更、schema/checkpoint 影响、测试命令与结果、与阶段 3 baseline 的 diff、遗留风险。阶段 4 通过后，才建立阶段 5 live adapter 的独立计划。

#### 风险与回滚
- 游标语义不清：先冻结窗口/排序/指纹，再写 adapter；任何变更提升 protocol version 并拒绝旧 checkpoint；
- 重复页或乱序导致重复写入：使用 page fingerprint + 稳定 execution key，保留审计计数；
- 错误信息泄密：集中 scrubber，禁止序列化异常对象和 raw response；
- 分页循环破坏执行器恢复：同步批次作为明确节点/side effect，先写 contract 再实现；
- 若无法在不改 `magent` 的情况下表达需求，暂停本阶段并提交业务无关最小复现与单独框架变更提案。


<a id="phase-doc-phase4-review"></a>

## 原文：PHASE4_REVIEW.md

### VulnTell 阶段 4 审查记录
#### 结论
阶段 4 已完成。协议、分页 fixture、错误分类、同步状态和离线测试均已补齐；随后阶段 5 adapter 开发暴露出的 live 集成问题不回溯改变阶段 4 的离线契约。阶段 5 的公网和端到端能力另见 [PHASE5_REVIEW.md](PHASES.md#phase-doc-phase5-review)。

#### 已完成项
- `apps.vulntell.sources.protocol` 提供不可变、可序列化的请求、页面和记录对象，并生成稳定请求指纹；
- `sources.errors` 提供错误分类、重试提示和基本脱敏；
- `PagedFixtureSource`/`FaultyPagedSource` 支持分页、故障注入、空结果和坏记录标记；
- `domain.models` 增加 `SyncRun`、页 checkpoint 和错误摘要值对象；
- `pipeline.sync` 提供 run/resume/cancel 服务，并完成状态统计、重试游标、重复页检测和 checkpoint 幂等；
- 默认 VulnTell CLI 仍 fixture-first、离线，未接入真实 HTTP；
- `python -m pytest -q` 当前为 296 passed，`mypy src/magent` 无类型错误。

#### 当时发现的问题及处理结果
1. 专门的 `tests/unit/test_sources.py`、`tests/unit/test_sync.py` 已补齐；
2. 正常分页的 `total_pages`、重试同页和重复页 execution key 已修正并有测试；
3. 阶段 4 仍保留单进程 checkpoint 实现边界，跨进程持久化将在阶段 6 存储层完成；
4. `sources.legacy` 继续作为兼容层，live adapter 已迁移到正式模块。

#### 门禁判定
| 门禁 | 结果 |
| --- | --- |
| 协议 round-trip 与输入校验 | 通过 |
| 分页 fixture 与错误分类 | 通过 |
| 正常同步状态为 succeeded | 通过 |
| 中断后游标恢复且不重放已提交页 | 通过（单进程边界） |
| 跨进程 checkpoint/幂等 | 延后至阶段 6 存储层 |
| 默认离线与安全脱敏 | 通过现有 CLI/框架测试 |
| 真实 HTTP adapter | 未开始 |

#### 处理原则
在阶段 4 收尾前禁止接入生产 HTTP、API 或新存储。若修复需要修改 `magent`，先提交业务无关最小复现和独立框架变更，不在 VulnTell 迁移提交中混改。


<a id="phase-doc-phase5-closeout-plan"></a>

## 原文：PHASE5_CLOSEOUT_PLAN.md

### VulnTell 阶段 5 收尾实施计划：Live 入口与端到端采集
#### 目标
将已经存在的 NVD/CISA/CNVD adapter 接入 VulnTell 正式应用服务，在显式 `live` 开关下完成“请求 → 分页/增量 → 规范化 → 去重 → 持久化 → 指标/报告”的单来源纵向流程。默认运行、无 key 和 fixture 回归必须保持不变。

#### 任务顺序
##### 5C.1 统一 live 配置与入口
- 为 `VulnTellConfig` 增加 `mode`（fixture/live）、`source`、窗口、endpoint allowlist 和超时配置；
- CLI 增加 `sync --source nvd|cisa_kev|cnvd --live`（或等价参数），live 未显式开启时拒绝构造 HTTP transport；
- `VulnTellApplication`/`VulnTellJobRunner` 通过依赖注入选择 adapter，三来源共享同一 pipeline；
- `cisa_kev` 加入来源 schema，但不改变旧 fixture baseline；
- API key 只从受控环境/secret provider 注入，禁止进入配置序列化、State、trace 或异常消息。

验收：默认 CLI 的 socket 禁止测试仍通过；live 参数缺失、未知来源和非 allowlist endpoint 在启动前失败；NVD/CISA live 单页能生成与 fixture 相同结构的 `SourceObservation`。

##### 5C.2 修复 NVD 窗口与分页
- 将任意时间窗口切分为 NVD 允许的最大区间（以官方限制为准），按修改时间稳定排序；
- 游标同时携带窗口分片和 `startIndex`，request fingerprint 覆盖分片参数；
- `next_cursor` 必须使用服务端偏移/结果数，过滤掉坏记录时不得跳过有效 CVE；
- 提取 CVSS/CPE 所需最小字段，并限制单页/总响应大小。

验收：历史 CVE 查询不再因超大窗口返回 404；跨分片恢复和重复运行幂等；请求失败只重试当前分片。

##### 5C.3 完善 CISA KEV 增量边界
- 记录 catalog version/hash 与 `SyncRun`；相同版本返回空增量；
- 对大 catalog 采用受控批次或流式解析，避免一次性把全部记录放入状态；
- 明确 `dateAdded` 窗口过滤、版本变化和删除/修订语义；
- 为 CISA 结果设置稳定的 page/batch execution key。

验收：同一 catalog 重复同步不重复写入；版本变化可恢复；内存和 batch 大小有上限。

##### 5C.4 CNVD 可行性与合规路径
- 先确认官方 API、授权、robots/使用条款和可接受的下载格式；不得绕过 JavaScript/WAF 或抓取引用页面；
- 若无稳定公开 API，实现官方允许的人工下载 fixture 导入并在报告中标明来源版本；当前实现为
  `CNVDManualFileSource`（CSV/JSON）。操作员从 CNVD 官方漏洞列表/数据下载页面完成验证码后，
  将下载文件路径传入导入任务；系统只读取本地文件并记录 SHA-256，不自动请求下载链接。
- 下载链接不得硬编码为绕过验证的接口；链接、登录和验证码由操作员在 CNVD 官方站点完成，
  具体入口以站点当日公开页面为准。Excel 文件应先由操作员导出为 UTF-8 CSV 或 JSON。
- 若获得 API，再按 `SourcePage` 契约实现响应映射、限流和错误分类；
- 521/HTML challenge 必须归类为不可用来源，不得当作空数据成功。

验收：有结构化官方数据或明确的“不可用”状态；不把反爬页面写入漏洞记录；许可和保留策略有文档；
人工下载文件可分页导入、缺失/超大/非法文件返回结构化错误，并能用哈希复现实验输入。

##### 5C.5 依赖、测试和观测
- 将 `httpx` 放入 live extra（或运行时依赖），为干净安装增加 import smoke；
- 为每个 adapter 增加 fake transport、mock HTTP、脱敏、超时、429、取消和响应过大测试；
- 增加 live pipeline contract（默认跳过，显式环境变量开启），记录 endpoint、窗口、source version、记录数和耗时，不记录 raw payload；
- 增加端到端 checkpoint/resume/幂等测试，验证真实 adapter 输出与领域层契约兼容。

#### 阶段完成门禁
```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json
python -m apps.vulntell sync --source nvd --live --since ... --until ...   # 显式 smoke
git diff --check
```

必须满足：至少 NVD 和 CISA 可从正式 CLI/Application 端到端产出报告；CNVD 有结构化 live 方案或合规人工 fixture 方案；默认运行不联网；相同窗口可恢复且幂等；凭据/raw payload 不泄露；未修改 `magent` 通用语义。

#### 交付与回滚
按 5C.1 → 5C.2/5C.3 → 5C.4 → 5C.5 分提交。live 失败时 feature flag 回退 fixture，不删除旧入口或阶段 0–3 baseline。所有门禁通过后，才进入阶段 6 的 schema v2、repository 和查询实现。


<a id="phase-doc-phase5-closeout-result"></a>

## 原文：PHASE5_CLOSEOUT_RESULT.md

### 阶段 5 收尾实施记录：Live 入口与端到端采集（复核未通过）
> 本文是实现项清单，不代表验收通过；当前结论以
> [PHASE5_CLOSEOUT_REVIEW.md](PHASES.md#phase-doc-phase5-closeout-review) 为准。

#### 完成时间
2026-08-31

#### 目标
将已经存在的 NVD/CISA/CNVD adapter 接入 VulnTell 正式应用服务，在显式 `live` 开关下完成"请求 → 分页/增量 → 规范化 → 去重 → 持久化 → 指标/报告"的单来源纵向流程。

#### 已完成工作
##### 5C.1 统一 live 配置与入口（已完成）
- `VulnTellConfig` 增加 `mode`（fixture/live）、`source`、窗口、endpoint allowlist 和超时配置
- CLI 增加 `--live --source nvd|cisa_kev|cnvd` 参数
- `VulnTellApplication`/`VulnTellJobRunner` 通过依赖注入选择 adapter，三来源共享同一 pipeline
- API key 只从环境变量注入，禁止进入配置序列化、State、trace 或异常消息
- 创建 `apps/vulntell/sources/live_adapter.py` 工厂

##### 5C.2 修复 NVD 窗口与分页（已完成）
- 将任意时间窗口切分为 NVD 允许的最大区间（120 天）
- 游标同时携带窗口分片和 `startIndex`
- `next_cursor` 使用服务端偏移/结果数
- 实现 `NVDCursor` 序列化/反序列化
- 实现 `slice_time_window` 函数

##### 5C.3 完善 CISA KEV 增量边界（已完成）
- 记录 catalog version/hash 与 `SyncRun`；相同版本返回空增量
- 对大 catalog 采用受控批次（默认 500 条/批）
- 明确 `dateAdded` 窗口过滤、版本变化和删除/修订语义
- 为 CISA 结果设置稳定的 page/batch execution key

##### 5C.4 CNVD 可行性与合规路径（已完成）
- 确认官方 API、授权、robots/使用条款和可接受的下载格式
- 实现官方允许的人工下载 fixture 导入并在报告中标明来源版本
- 521/HTML challenge 归类为不可用来源
- 添加合规说明文档

##### 5C.5 依赖、测试和观测（未完成）
- `httpx` 放入 live extra（或运行时依赖）
- 为每个 adapter 增加 fake transport、mock HTTP、脱敏、超时、429、取消和响应过大测试
- 增加 live pipeline contract（默认跳过，显式环境变量开启）

#### 边界约束（未违反）
| 约束 | 状态 |
|------|------|
| `src/magent` 行为不变 | ✅ 未修改 |
| 默认 CLI 不联网 | ✅ adapter 需显式传入 transport |
| HTTP adapter 仅在显式启用时加载 | ✅ |
| 不把完整 raw payload 写入 State/Trace/日志 | ✅ 只提取关键字段 |
| adapter 不自行循环重试 | ✅ 由 runner 统一执行 |
| 保留中文与跨源冲突 | ✅ CNVD 保留原始中文 |
| API key 不进入序列化/trace/异常消息 | ✅ 只从环境变量注入 |

#### 验收标准
| 验收项 | 状态 |
|--------|------|
| 三个 adapter 单元/离线 contract | ✅ |
| NVD、CISA 公网最小 smoke | ✅（仅独立 adapter） |
| CNVD 公网结构化采集 | ❌（521/WAF；仅合规 fixture 方案） |
| CLI/Application live 入口 | ❌（NVD fetch 接口不匹配） |
| 三来源进入同一 pipeline 并生成报告 | ❌（CISA 分支未接入） |
| 默认离线、无凭据运行 | ✅ |
| NVD 窗口分片、CISA 增量/分页 | 部分通过，未完成端到端验证 |

#### 测试覆盖
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

#### Git 提交
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

#### 复核结论
阶段 5 尚未闭环。正式复核和真实网络证据见 [PHASE5_CLOSEOUT_REVIEW.md](PHASES.md#phase-doc-phase5-closeout-review)。在 live 端到端门禁通过前，不进入阶段 6。


<a id="phase-doc-phase5-closeout-review"></a>

## 原文：PHASE5_CLOSEOUT_REVIEW.md

### 阶段 5 收尾复核：真实漏洞情报采集能力
#### 结论
阶段 5 收尾未完成。当前状态是“live adapter 可独立请求部分公网来源，但正式 CLI/Application 的端到端集成未通过”。因此不能进入阶段 6，也不能宣称 VulnTell 已具备真实漏洞情报生产能力。

#### 复核证据（2026-08-31）
##### 独立 adapter smoke
使用显式 `NVDTransport`、`CISAKEVTransport` 和 `CNVDTransport`，不写入仓库或日志：

| 来源 | 结果 |
| --- | --- |
| NVD | 成功返回 `SourcePage`，1 条真实 CVE（`CVE-2015-3246`），`has_more=true` |
| CISA KEV | 成功返回 `SourcePage`，500 条真实记录，`has_more=true`（批次分页已生效） |
| CNVD | 返回 `SourceError(transient, HTTP 521)`，响应为 JavaScript/WAF challenge，无结构化漏洞记录 |

##### 正式 CLI smoke
- `python -m apps.vulntell --live --source nvd --no-llm --json --window-days 7`：进程返回 0，但报告为 `nvd=failed`；step message 为 `collect nvd failed: 'NVDAdapter' object has no attribute 'fetch'`。这是部分失败降级，不代表采集成功。
- `python -m apps.vulntell --live --source cisa_kev ...`：进程返回 0，报告仍是 fixture 的 `nvd/cnvd` 两来源；当前 Graph 只定义 NVD/CNVD 节点，CISA adapter 未进入 pipeline。
- `python -m apps.vulntell --live --source cnvd ...`：启动即拒绝，提示 CNVD 暂不支持 live；这是预期的合规保护，不是数据采集成功。

#### 阶段门禁判定
| 门禁 | 状态 | 说明 |
| --- | --- | --- |
| adapter 单元和离线测试 | 通过 | 全量 `345 passed` |
| NVD 独立公网请求 | 通过 | 仅证明 transport/解析可用 |
| CISA 独立公网请求 | 通过 | 尚未进入正式 Graph |
| CNVD 结构化 live 数据 | 未通过 | 521/WAF challenge；需官方 API 或合规人工 fixture |
| `--live` CLI/Application 端到端 | 未通过 | NVD 接口不匹配，CISA 分支缺失 |
| 真实数据进入规范化/去重/持久化/报告 | 未通过 | 当前正式运行仍产生 fixture 报告或部分失败报告 |
| 默认离线与敏感信息边界 | 通过 | 默认命令未联网，未记录 raw payload/凭据 |

#### 下一步
按 [PHASE5_CLOSEOUT_PLAN.md](PHASES.md#phase-doc-phase5-closeout-plan) 完成统一 `fetch_page`/`fetch` 协议、Graph 来源选择和 CISA 分支、live 窗口元数据、live pipeline contract，并将 `httpx` 声明为 live extra。CNVD 必须保留“不可用来源”状态，禁止绕过 WAF。


<a id="phase-doc-phase5-plan"></a>

## 原文：PHASE5_PLAN.md

### VulnTell 阶段 5：真实数据源接入实施计划
#### 前置条件
只有 [PHASE4_REVIEW.md](PHASES.md#phase-doc-phase4-review) 中的收尾门禁全部通过，才可开始本阶段。阶段 4 的协议版本、游标语义、`SyncRun` checkpoint 格式和错误分类必须冻结；否则 live adapter 产生的 checkpoint 不承诺兼容。

#### 目标与非目标
在保持 fixture/live 双轨和默认离线的前提下，依次接入 NVD、CISA KEV、CNVD。每个来源都通过统一 `SourceRequest → SourcePage/SourceError` 协议、现有同步 runner 和存储接口运行。本阶段不做查询 API、Web 看板、全文检索、分布式队列或抓取引用网页。

#### 实施顺序
##### 5.1 NVD adapter（首个纵向切片）
- 明确 NVD API 许可、endpoint、认证（如需）、限速和响应大小上限；
- 将 NVD 响应映射为 `SourceRecord`，保留 source record id、published/modified 时间、CVSS 和 CPE 所需字段；
- 实现分页参数与协议游标的双向转换，处理窗口半开边界和修改时间排序；
- 接入连接/读取超时、429 `Retry-After`、5xx、非法 JSON、401/403/404 分类；
- fixture 与录制响应仅保存最小脱敏样本，禁止把完整 raw payload 写入 State/Trace/日志；
- 提供离线 contract、mock HTTP 测试和显式 live smoke（默认不运行）。

验收：固定窗口重复同步结果一致；中断后从最后成功游标恢复；429/超时按 retry hint 交给执行器；单页坏记录隔离；默认 CLI 无网络且无 key 也能运行。

##### 5.2 CISA KEV adapter
- 固定 KEV 字段映射、catalog version 和新增/修改时间语义；
- 处理无分页或文件版本变化时的合成游标；
- 将 known-exploited 状态映射为来源元数据，不修改通用领域指标规则；
- 使用同一错误、脱敏、大小限制和审计策略。

验收：fixture/live 字段逐项对照，重复 catalog 不重复写入，版本变化可审计，失败可恢复。

##### 5.3 CNVD adapter
- 固定中文标题/描述、CVE 关联、发布日期和来源优先级映射；
- 保留中文与跨源冲突，不在 adapter 内做领域去重或指标计算；
- 处理接口限流、权限和不稳定响应，必要时提供人工下载 fixture 导入路径。

验收：中文字段编码稳定，跨源冲突进入质量问题，单条非法记录不丢弃整批，许可和来源版本记录完整。

#### 共通工程任务
1. 为 live adapter 定义依赖注入的 HTTP transport（测试使用 fake transport），禁止模块级 client；
2. 设置连接/读取/总响应大小/单页记录数上限，拒绝重定向到非 allowlist 主机；
3. 由 runner 统一执行重试、退避、取消和 checkpoint，adapter 不自行循环重试；
4. 对请求 URL、header、异常和响应摘要做集中脱敏；
5. 增加来源许可、数据保留、版本和变更日志文档；
6. 为每个来源提供独立 feature flag，live 未显式开启时构造 fixture adapter。

#### 阶段验收门禁
```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json       # 默认离线
git diff --check
```

另须满足：三来源均有 fixture、mock HTTP、离线 contract 和显式 live smoke；429/超时/取消/进程重启恢复通过；连续相同窗口同步幂等；trace、日志、checkpoint、错误和 prompt 不含凭据或 raw payload；未修改 magent 通用语义。

#### 交付与回滚
每个 adapter 单独提交，包含字段映射、许可、配置示例、测试结果和结构化 diff。live adapter 出现回归时，通过 feature flag 回退到 fixture/旧 legacy adapter；不得删除旧 fixture 或破坏阶段 3 baseline。三来源全部通过后，才进入阶段 6 存储与查询产品化。


<a id="phase-doc-phase5-result"></a>

## 原文：PHASE5_RESULT.md

### 阶段 5 实现记录：真实数据源接入（集成验收未闭环）
#### 完成时间
2026-08-30

#### 目标
逐个接入 NVD、CISA KEV、CNVD，保持 fixture/live 双轨。

#### 已完成工作
##### Task 5.1：NVD Adapter（已完成）
- 实现 `NVDAdapter`：将 NVD CVE API 映射为 SourceRecord
- 实现 `NVDConfig`：API 配置（endpoint、page_size、timeout、api_key）
- 实现 `NVDTransport`：HTTP transport（使用 httpx）
- 支持分页（startIndex/resultsPerPage）、游标、429 限流、超时
- 测试覆盖：12 个测试用例
- Commit: `d45becb`

##### Task 5.2：CISA KEV Adapter（已完成）
- 实现 `CISAKEVAdapter`：将 CISA KEV Catalog 映射为 SourceRecord
- 实现 `CISAKEVConfig`：API 配置（endpoint、timeout、catalog_version）
- 实现 `CISAKEVTransport`：HTTP transport（使用 httpx）
- 支持版本变化检测、合成游标
- 测试覆盖：7 个测试用例
- Commit: `68fcf42`

##### Task 5.3：CNVD Adapter（已完成）
- 实现 `CNVDAdapter`：将 CNVD API 映射为 SourceRecord
- 实现 `CNVDConfig`：API 配置（endpoint、page_size、timeout、api_key）
- 实现 `CNVDTransport`：HTTP transport（使用 httpx）
- 支持分页、中文字段、CVE 关联
- 测试覆盖：8 个测试用例
- Commit: `68fcf42`

#### 边界约束（未违反）
| 约束 | 状态 |
|------|------|
| `src/magent` 行为不变 | ✅ 未修改 |
| 默认 CLI 不联网 | ✅ adapter 需显式传入 transport |
| HTTP adapter 仅在显式启用时加载 | ✅ |
| 不把完整 raw payload 写入 State/Trace/日志 | ✅ 只提取关键字段 |
| adapter 不自行循环重试 | ✅ 由 runner 统一执行 |
| 保留中文与跨源冲突 | ✅ CNVD 保留原始中文 |

#### 验收标准
| 验收项 | 状态 |
|--------|------|
| 所有 adapter 通过单元测试 | ✅ 345 passed |
| 顶层无 network imports | ✅ httpx 仅在函数内导入 |
| 默认 CLI 完全离线 | ✅ |
| 错误分类正确 | ✅ 429/408/5xx/401/403/404 |
| 不复制第二份业务实现 | ✅ |

#### 测试覆盖
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

#### Git 提交
```
68fcf42 phase5: add CISA KEV and CNVD adapters
d45becb phase5: add NVD adapter
68fcf42 phase4: review fixes
ef0802c phase4: add sources protocol, fixtures, errors, sync runner
6f2fb40 phase3: complete migration
...
```

#### 当前状态
本文件记录 adapter 代码和离线测试的完成情况，不等同于真实数据 MVP 完成。公网 smoke、正式 CLI/Application 集成和 CNVD 可用性审查见 [PHASE5_REVIEW.md](PHASES.md#phase-doc-phase5-review)；收尾任务见 [PHASE5_CLOSEOUT_PLAN.md](PHASES.md#phase-doc-phase5-closeout-plan)。

#### 下一步
完成阶段 5 收尾门禁后，再进入阶段 6：schema v2 + repository + 数据库抽象。


<a id="phase-doc-phase5-review"></a>

## 原文：PHASE5_REVIEW.md

### VulnTell 阶段 5 审查记录：真实数据源可用性
#### 审查日期与结论
审查日期：2026-08-31。

阶段 5 的三个 adapter 代码和离线单元测试已提交，但阶段验收尚未闭环，不能标记为“真实数据 MVP 完成”。独立 adapter 已能访问部分公网来源；VulnTell 应用服务和 CLI 尚未把 live adapter 接入完整 Graph，因此当前工具整体仍不能端到端运行一次真实情报采集并生成持久化报告。

#### 已完成项
- `NVDAdapter`、`CISAKEVAdapter`、`CNVDAdapter` 位于 `apps/vulntell/sources/`；
- 三个 adapter 均使用依赖注入 transport，默认构造不联网；
- 429、408、5xx、401、403、404 和解析/网络异常可映射为 `SourceError`；
- NVD 支持 `startIndex/resultsPerPage`，CISA KEV 支持 catalog 版本，CNVD 支持分页参数和中文字段映射；
- 离线全量测试：`345 passed`；`mypy src/magent` 通过；
- `python -m apps.vulntell --no-llm --json` 仍保持 fixture-first、无网络。

#### 真实网络 smoke 结果
在不提供 API key、只请求一页或一个 catalog 的受控测试中：

| 来源 | 结果 | 证据与限制 |
| --- | --- | --- |
| NVD | 部分通过 | 7 天窗口、`page_size=1` 返回 `SourcePage`，包含真实 CVE 记录；使用 10 年窗口并附带 `cveId` 返回 HTTP 404，说明未处理 NVD 的日期窗口限制，不能据此进行任意历史查询 |
| CISA KEV | 通过 adapter smoke | 返回真实 catalog，1685 条记录，`has_more=False`；当前一次性加载整个 catalog，未按 `page_size` 分页，内存/增量语义仍需收尾 |
| CNVD | 未通过 | 官方 endpoint 返回 HTTP 521 和 JavaScript 反爬挑战，未获得结构化漏洞记录；当前实现不能把该响应转换为情报 |

测试只验证了网络可达性和最小解析，不把公网响应写入仓库、fixture、trace 或日志。

#### 端到端工具能力判定
当前 `python -m apps.vulntell --help` 没有 `--live`、`--source` 或 endpoint 配置；`VulnTellConfig` 的已知来源也不包含 `cisa_kev`，`VulnTellJobRunner/Graph` 固定使用 fixture/legacy adapter。因此：

- 可以通过 Python 直接调用 NVD/CISA adapter 获取真实记录；
- 不能通过正式 CLI/Application 选择 live 来源并将其送入现有规范化、去重、持久化、评估和报告流程；
- 不能宣称三来源真实采集可用，CNVD 还需要官方接口/下载渠道或明确的人工 fixture 方案；
- `httpx` 未列入项目运行时依赖，干净安装环境无法保证 live transport 可用。

#### 阶段 5 门禁
| 门禁 | 状态 |
| --- | --- |
| 三个 adapter 单元/离线 contract | 通过 |
| NVD、CISA 公网最小 smoke | 部分通过 |
| CNVD 公网结构化采集 | 未通过 |
| CLI/Application live 入口 | 未实现 |
| 三来源进入同一 pipeline 并生成报告 | 未实现 |
| 默认离线、无凭据运行 | 通过 |
| NVD 窗口分片、CISA 增量/分页 | 未通过或不完整 |

#### 审查结论
阶段 5 定性为“adapter 实现完成、产品集成和来源可用性收尾中”。下一步不是直接进入存储查询阶段，而是完成 live 入口、NVD 窗口分片、CISA 增量边界和 CNVD 可行性决策。具体任务见 [PHASE5_CLOSEOUT_PLAN.md](PHASES.md#phase-doc-phase5-closeout-plan)。


<a id="phase-doc-phase-completion-summary"></a>

## 原文：PHASE_COMPLETION_SUMMARY.md

### VulnTell 阶段完成汇总（截至 2026-08-31）
本文把已完成阶段的计划、结果和复核结论集中在一个入口；各 `PHASE*_PLAN.md`、
`PHASE*_REVIEW.md` 文件仍保留为可追溯的历史记录，不再单独作为当前状态来源。

#### 已完成并冻结
| 阶段 | 当前结论 | 主要证据 |
| --- | --- | --- |
| 2 领域层迁移 | 已完成 | [PHASE2_RESULT.md](PHASES.md#phase-doc-phase2-result) |
| 3 Graph/任务层迁移 | 已完成 | [PHASE3_RESULT.md](PHASES.md#phase-doc-phase3-result) |
| 4 数据源契约与离线同步 | 已完成（checkpoint 为单进程边界） | [PHASE4_REVIEW.md](PHASES.md#phase-doc-phase4-review) |
| COSV A、批次 C/D、SQLite E | 模块与离线测试已具备；产品链路仍在收口 | [NEXT_PHASE_IMPLEMENTATION.md](PHASES.md#phase-doc-next-phase-implementation) |

阶段 0–4 的 fixture-first、默认离线、幂等、恢复和敏感信息边界是当前基线。
阶段 4 的跨进程持久化 checkpoint 以及正式业务存储迁移属于后续工作，不应在文档中表述为已交付。

#### 尚未完成
阶段 5 的 adapter 已实现，当前已完成 NVD、CISA KEV、Red Hat、Ubuntu、MSRC、OSV 六个来源的
真实 COSV 批次闭环；但 live CLI/Application 和“至少 10 个来源各 100 条”的阶段门禁仍未通过，
CNVD 只能走合规人工下载导入。详见
[PHASE5_CLOSEOUT_REVIEW.md](PHASES.md#phase-doc-phase5-closeout-review) 和
[PHASEB_REAL_SMOKE_REPORT.md](PHASES.md#phase-doc-phaseb-real-smoke-report)。

因此当前仓库可以复现离线 VulnTell 流程和独立来源 smoke，不能宣称真实数据生产 MVP，
也不应提前进入阶段 6 的产品化存储查询门禁。

#### 当前执行顺序
1. 继续完成其余来源的真实 API/feed 或合规人工导入证据，并保持窗口、字段和许可证可追溯；
2. 通过真实来源门禁后再推进阶段 6 存储/查询，并替换 `storage/legacy.py`；
3. 多人采集和 COSV 批次交付遵循 [INTELLIGENCE_COLLECTION_GUIDE.md](INTELLIGENCE_COLLECTION_GUIDE.md)。


<a id="phase-doc-phaseb-real-smoke-report"></a>

## 原文：PHASEB_REAL_SMOKE_REPORT.md

### 阶段 B 真实采集验收记录
执行时间：2026-08-31（受控公网 smoke，单页 `page_size=100`，超时 15 秒）。

复核命令：`python -m pytest -q tests/unit/test_cosv.py tests/unit/test_batch.py tests/unit/test_storage.py`（52 passed）。

#### 结果（复测）
| 来源 | 结果 | 记录数 | 说明 |
|---|---|---:|---|
| NVD | 真实闭环通过 | 100 | 真实单页 100 条，已生成 100 条 COSV、manifest，并通过 `validate_batch_directory` |
| CISA KEV | 真实闭环通过 | 100 | 从真实 catalog 抽取前 100 条，已生成 100 条 COSV、manifest，并通过 `validate_batch_directory` |
| MSRC | 可访问但空页 | 0 | 需要确认 API 查询参数和数据窗口 |
| CNVD | 不可用 | - | HTTP 521/WAF，保留人工下载导入路径 |
| OSV、GitHub Advisory、EUVD、JVN、Red Hat、Ubuntu、Debian、CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB | 未通过 | - | 返回结构化 SourceError 或超时，尚未满足真实 100 条验收 |

#### 2026-09-10 当前批次复核
在修正 live adapter 的实际公开端点、响应格式和标准字段映射后，使用 UTC 半开窗口
`[2026-08-11T03:00:27Z, 2026-09-10T03:00:27Z)` 重新采集。所有批次均经过
`collect_adapter` 的标准化、COSV schema 校验、manifest 哈希校验和唯一 ID 检查。

| 来源 | COSV 记录 | 批次校验 | 质量说明 |
|---|---:|---|---|
| NVD | 100 | 通过 | 达到采集器单批上限；保留 CVE、描述、时间和 CVSS |
| CISA KEV | 38 | 通过 | 窗口内实际新增/加入记录；未用全目录数量冒充窗口数据 |
| Red Hat | 100 | 通过 | 公共 CVE feed；按 `public_date` 窗口过滤 |
| Ubuntu | 10 | 通过 | `cves.json` 窗口内实际返回数量 |
| Microsoft MSRC | 100 | 通过 | 跟随近期 CVRF XML bulletin，按 release date 过滤并按 CVE 输出 |
| OSV | 3 | 通过 | 对指定 PyPI 包 querybatch，按 modified/published 过滤 |

批次摘要保存在本地生成目录 `deliveries/live-final-3/collection-summary.json`，不作为
仓库交付物；其中 `records.cosv.jsonl`、完整质量日志和原始响应均不提交。质量报告中的
告警是来源字段缺失（例如部分来源没有 CVSS 或 source-added 时间），不是 COSV schema
失败，也没有用默认值伪造这些字段。

#### COSV 结论
NVD 和 CISA KEV 已完成“真实采集 100 条 → COSV JSONL → manifest → validate-batch”的闭环。尚未完成双人批次 merge 和其余来源的真实 100 条验收，因此阶段 B **仍未通过**。

不得将 SourcePage 记录数视为 COSV 合规：当前 adapter 输出仍是 SourceRecord，必须经过 `observation_to_cosv` 和 schema 校验。

#### 复核结论
阶段 B 仍未通过。当前已有 6/17 个来源完成真实 COSV 批次闭环，但只有 NVD、Red Hat、
MSRC 达到单批 100 条；CISA KEV、Ubuntu、OSV 的窗口内实际数量低于 100。距离文档要求的
“至少 10 个来源各真实采集 100 条”仍有明显差距，单元测试通过不改变该结论。

#### 后续阻塞项
1. 为其余来源核对官方 endpoint、认证、查询参数及许可；
2. 为真实采集增加稳定的可重复入口，输出脱敏统计而不是原始响应；
3. 对能获取 100 条的来源生成批次并执行 `validate-batch`、`merge`；
4. 对窗口内不足 100 条的来源记录“实际数量”，不得补造或重复填充；
5. CNVD 只能使用官方人工下载文件，不得绕过 WAF。
