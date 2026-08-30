# VulnTell 阶段 0–1 详细实施方案

本文用于指导下游 agent 完成 VulnTell 从 `examples/vulntell` 向 `apps/vulntell` 迁移的第一轮工作。阶段 0–1 只建立基线、应用外壳和兼容入口，不接入真实网络，不重写 `magent`，不引入 Web/API 服务。

## 一、范围和最终产出

### 阶段 0：基线冻结

冻结当前可观察行为，形成迁移前的“黄金基线”：

- fixture、数据集元信息、指标版本和报告 schema；
- 默认、`--no-llm`、单源失败、`--resume`、`--trace` 场景；
- 测试、类型检查、离线 CLI 和链接检查结果；
- 新旧入口的兼容策略和已知限制清单。

### 阶段 1：应用外壳

建立 `apps/vulntell` 的可运行入口和依赖组装层，暂时复用旧实现：

- `python -m apps.vulntell` 可运行；
- 配置、应用生命周期和运行结果对象有明确位置；
- `examples.vulntell` 变为薄兼容入口；
- 新旧入口输出可自动比较，且没有第二份业务实现。

阶段 1 完成后，后续阶段才能迁移领域模块、Graph 和数据源适配器。

## 二、不可改变的边界

下游 agent 在阶段 0–1 不得：

- 修改 `src/magent` 的执行、状态合并、Checkpoint、重试或取消语义；
- 接入真实 NVD、CNVD、CISA KEV HTTP 请求；
- 增加 FastAPI、Web 前端、任务队列或 PostgreSQL 运行依赖；
- 将 VulnTell 领域模型导入 `src/magent`；
- 复制一套 `agents.py`、`graph.py` 或数据库实现到新旧两个目录；
- 以“输出看起来相同”为理由跳过结构化报告比较和恢复测试。

允许的修改范围：`apps/` 新文件、`examples/vulntell` 兼容入口、`tests/contract/vulntell`、阶段文档和必要的 README/导航链接。

## 三、阶段 0：基线冻结

### 0.1 任务拆分

#### Task 0.1：建立基线清单

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

#### Task 0.2：冻结运行场景

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

#### Task 0.3：定义结构化比较规则

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

#### Task 0.4：冻结失败和安全边界

建立清单并写入测试：

- `--faulty nvd` / `--faulty cnvd` 可生成部分报告；
- 默认运行不进行网络请求；
- raw payload 不进入 Trace、日志和 LLM prompt；
- 不执行外部命令，不抓取引用 URL；
- API key、token、cookie 等敏感字段不进入状态和报告。

#### Task 0.5：冻结质量门禁

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

### 0.2 阶段 0 验收标准

1. 默认和 `--no-llm` 报告经过两次运行后确定性字段一致；
2. 单源失败仍有结构化报告，且失败来源明确；
3. resume 结果与无中断基线一致；
4. trace summary 可生成，且不含 `raw_payload`、凭据或完整外部描述；
5. 基线文件、比较规则和已知限制已提交到文档；
6. 工作区没有数据库、缓存、trace 和临时输出；
7. 阶段 0 不产生 `src/magent` 行为变更。

### 0.3 阶段 0 建议提交

```text
test(vulntell): capture migration baseline scenarios
test(vulntell): add deterministic report comparison helpers
docs(vulntell): freeze phase-0 baseline and compatibility rules
```

## 四、阶段 1：建立 apps/vulntell 外壳

### 1.1 目标目录

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

### 1.2 Task 1.1：配置对象

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

### 1.3 Task 1.2：应用生命周期

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

### 1.4 Task 1.3：新 CLI

实现 `apps/vulntell/__main__.py`：

- 复用现有参数语义：`--db`、`--checkpoint`、`--run-id`、`--resume`、`--no-llm`、`--json`、`--faulty`、`--trace`；
- 参数解析后创建 `VulnTellConfig`；
- 调用 `VulnTellApplication.run()`；
- 保持退出码：成功为 0，运行失败为 1，KeyboardInterrupt 为 130；
- 人类可读输出和 JSON 输出继续沿用当前格式，避免在迁移阶段改变报告 schema。

### 1.5 Task 1.4：旧入口兼容层

将 `examples/vulntell` 的启动逻辑收缩为兼容转发：

```python
from apps.vulntell.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
```

注意：兼容层只负责入口，不应把旧目录中的所有业务模块立即删除。阶段 1 结束时，旧业务模块仍可作为迁移过渡依赖，但新代码只能从 `apps.vulntell` 入口进入。

### 1.6 Task 1.5：contract tests

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

### 1.7 阶段 1 验收命令

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

### 1.8 阶段 1 建议提交

```text
feat(vulntell): add apps package and application shell
feat(vulntell): add config and application lifecycle
test(vulntell): add old/new entrypoint contract tests
refactor(vulntell): route examples entrypoint through apps
docs(vulntell): document phase-1 migration boundary
```

## 五、问题处理和升级规则

### 5.1 发现输出差异时

按以下顺序排查：

1. 是否包含时间、UUID、trace id 等非确定字段；
2. 是否存在列表顺序差异；
3. 是否因工作目录导致 fixture 路径不同；
4. 是否因资源关闭顺序导致 SQLite/checkpoint 差异；
5. 是否确实改变了业务状态或报告 schema。

前四类应修复适配或比较器；第五类必须停止迁移，记录差异并获得维护者确认。

### 5.2 何时修改 magent

阶段 0–1 默认禁止修改 `magent`。只有满足以下条件才可另开框架任务：

- 问题可用与 CVE 无关的最小例子复现；
- 已证明不是入口、资源生命周期或业务适配错误；
- 有明确的通用 API 设计和回归测试；
- 变更不会破坏现有 260 个测试和 VulnTell contract tests。

### 5.3 何时暂停阶段 1

出现以下任一情况应暂停迁移并报告：

- 新旧入口业务结果无法解释地不一致；
- resume 重复执行已提交副作用；
- 默认入口发生网络访问；
- Trace/日志包含原始漏洞文本或凭据；
- 为了迁移而复制两份长期维护的业务实现。

## 六、阶段 0–1 完成定义

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
