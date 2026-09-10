# 阶段 9：发布、展示与工程化收口实施计划

> **交付对象：** 下游开发 Agent。本文是阶段 9 的实施基线。目标是把已经完成的框架核心、
> VulnTell 示例和阶段 8 评测整理成可安装、可验证、可理解、可展示的 GitHub 项目。
> 本阶段优先完成可复现的源码仓库发布；PyPI 发布和 Web 看板不是默认交付物，必须经过额外
> 范围确认和验收。

## 1. 当前基线

截至当前工作区：

- 阶段 1～8 已完成；
- `src/magent` 已具备 Agent/State/Result、Graph、并发、EventBus、重试/超时/取消、Checkpoint/
  恢复/幂等、Tools、LLM Provider、Middleware 和只读可观测性；
- `apps/vulntell` 已提供固定 fixture 驱动的多源漏洞情报流程，`examples/vulntell` 保留兼容入口；
- `benchmarks/` 已提供离线场景、VulnTell 质量评测和参考框架对比记录；
- 阶段 9 当前全量测试为 **427 passed**，`mypy src/magent` 已通过；阶段 9 专项发布门禁为 10 个测试；
- 默认流程不需要网络、API Key 或真实 LLM；
- 当前仓库已有 README、API、DESIGN、PHASE1～9、ROADMAP、参考项目对比、许可证、第三方归属、
  GitHub Actions 和正式发布检查清单；
- `pyproject.toml` 已完成阶段 1～8 的项目描述、MIT license 和 `mypy` 开发依赖配置；
- `benchmarks/out` 为生成目录，不应作为普通 Git 提交物。

## 2. 阶段目标

1. 让新用户能在干净环境中按 README 安装并运行核心示例；
2. 让 GitHub 仓库具备完整的项目定位、架构说明、API 入口、参考分析、限制和许可证信息；
3. 建立自动化质量门禁，确保测试、类型检查、构建和离线示例在提交时持续通过；
4. 固化阶段 8 的实验复现入口、版本信息和结果解释边界；
5. 形成适合 GitHub 展示、论文材料和简历项目描述的最小可交付版本；
6. 明确核心框架、业务示例、benchmark 和未来 Web 看板的边界，避免发布阶段范围失控。

## 3. 发布范围与非目标

### 3.1 本阶段包含

- README、API、DESIGN、路线图和阶段文档的事实一致性修订；
- `../architecture/COMPARISON.md`：LangGraph、AutoGen、CrewAI 的设计对比和本项目取舍；
- 许可证、第三方归属、数据集/fixture 来源说明和安全使用说明；
- GitHub Actions CI、干净环境安装验证和离线 smoke test；
- 打包元数据、版本策略、变更日志和发布检查清单；
- 核心示例、VulnTell 示例、benchmark CLI 的最短运行路径；
- 阶段 8 结果和限制说明的归档入口；
- 发布前的敏感信息、生成产物、依赖和文档链接检查。

### 3.2 本阶段不包含

- 分布式执行、生产级服务化、远程 tracing、消息队列和多租户；
- 默认接入真实 NVD/CNVD、真实 LLM 或任何需要密钥的服务；
- 自动漏洞扫描、PoC 执行、漏洞利用和外部命令执行；
- 不经验证的跨框架性能排名；
- 生产级 Web 看板。若确实需要看板，只做独立的范围评估，不阻塞核心发布；
- 未经许可的数据扩充、论文结论重写或面向生产的安全承诺；
- 未经单独验收的 PyPI 正式发布。

## 4. 发布物结构

```text
GitHub repository
├── README.md                 # 定位、安装、最短示例和限制
├── CHANGELOG.md              # 版本变更
├── LICENSE                   # 项目许可证
├── THIRD_PARTY_NOTICES.md    # 依赖/参考项目/fixture 归属说明
├── pyproject.toml            # 包元数据与开发工具入口
├── .github/workflows/ci.yml  # 自动质量门禁
├── docs/
│   ├── API.md
│   ├── DESIGN.md
│   ├── COMPARISON.md
│   ├── BENCHMARKS.md         # 阶段 8 结果与复现说明（可选独立文档）
│   └── PHASE1～9.md
├── src/magent/               # 可复用框架核心
├── examples/vulntell/        # 下游业务示例
├── benchmarks/               # 离线评测代码与说明
└── tests/                    # 自动化测试
```

`benchmarks/out/`、数据库、缓存、`.env`、API Key、mypy/pytest 缓存和真实运行日志不属于发布物。

## 5. 实施任务拆分

### Task 0：冻结发布范围与版本策略

- 确认本次发布是 GitHub 源码仓库 release，还是同时构建 wheel/sdist；默认选择前者并验证可编辑安装；
- 冻结当前版本号、Python 支持范围、公开 API 范围和兼容性承诺；
- 明确阶段 8 benchmark 结果是示例性本地结果，不是性能保证；
- 为所有后续改动建立变更记录，不在发布前无记录地改变执行语义。

### Task 1：文档事实统一

- 更新 README 的阶段状态、安装方式、示例命令、目录结构和当前限制；
- 更新 `../architecture/API.md` 的版本范围、稳定 API、阶段 8 实际字段和已知限制；
- 更新 `../architecture/DESIGN.md` 的架构、目录、观测与业务边界；
- 将 `docs/phases/PHASE8.md` 标为已完成，补充实际实现、测试数和结果入口；
- 将本文件和 `ROADMAP.md` 标为阶段 9 当前计划，阶段完成后再切换为已完成；
- 检查所有相对链接、绝对本地链接和命令在干净 checkout 中是否可用。

### Task 2：参考项目与许可证材料

- 创建 `../architecture/COMPARISON.md`，至少比较 Agent、State、Graph/Workflow、并发、Checkpoint、重试、
  工具/LLM 扩展、可观测性和生态定位；
- 每项参考结论记录来源 URL、项目版本或 commit、查看日期和“借鉴/未采用”的原因；
- 不复制 LangGraph、AutoGen、CrewAI 源码和实现细节；
- 选择并写入本项目许可证，补充 `THIRD_PARTY_NOTICES.md`、fixture 来源、数据许可和引用方式；
- 不把论文历史数据、第三方名称或实验数字写成未经证实的项目优势。

### Task 3：安装与构建验证

- 修正 `pyproject.toml` 的 description、版本说明和开发依赖声明；
- 决定 `examples/` 和 `benchmarks/` 是源码仓库运行资产还是需要随 wheel 发布，并在 README 中明确；
- 在干净虚拟环境执行 `pip install -e ".[dev]"`、`import magent` 和核心示例；
- 如构建发行包，分别检查 sdist/wheel 内容、安装后的 import 和版本号；
- 确认安装流程不要求 OpenAI SDK、网络或环境变量。

### Task 4：CI 质量门禁

- 建立 GitHub Actions，至少执行 Python 3.11、3.12、3.13 中项目声明支持的版本；
- CI 至少包含：安装、全量 pytest、`mypy src/magent`、`git diff --check` 等价检查和离线 CLI smoke test；
- 增加网络访问防回归检查，默认测试中禁止真实 HTTP、真实 LLM 和外部命令；
- 检查测试输出、benchmark 输出和数据库不会被意外提交；
- 参考框架依赖作为可选实验，不得成为默认 CI 必需依赖。

### Task 5：安全、依赖与数据合规

- 扫描仓库中的 API Key、token、私钥、`.env`、数据库和未经许可的原始数据；
- 固化外部漏洞文本不进入日志、Trace、Checkpoint 和报告的测试；
- 审核依赖许可证、可选 OpenAI adapter 的懒加载和供应链风险；
- 明确 fixture 是脱敏/演示数据，报告不得宣称为当前真实情报统计；
- 检查 README 和示例不会诱导用户执行漏洞利用、PoC 或不安全远程抓取。

### Task 6：示例与展示路径

- 为核心框架提供一个最短可复制示例：Agent → State → Result → 执行报告；
- 为 Graph、Checkpoint/恢复、Tools/LLM/Middleware、VulnTell 和 benchmark 提供明确命令；
- 展示成功、部分来源失败、恢复和 Trace 输出等关键能力；
- 所有默认命令使用 fixture/FakeProvider，失败时给出可定位错误；
- 准备一段项目简介、技术亮点、限制和可量化结果，供 GitHub README、简历和论文材料使用；
- 若增加 Web 看板，必须独立目录、独立依赖和独立验收，不修改核心执行协议。

### Task 7：版本、变更和发布检查

- 创建 `CHANGELOG.md`，记录阶段 1～8 的主要能力和阶段 9 发布内容；
- 明确 `0.x` 阶段的 API 兼容策略：新增字段可扩展，破坏性变更必须记录；
- 创建发布 checklist，逐项记录测试、安装、构建、文档、许可证、安全和示例结果；
- 创建 Git tag/release 草稿前，确认工作区干净、无敏感文件和无生成产物；
- 发布说明中同时列出已实现能力、未实现能力、离线限制和参考框架不可比边界。

## 6. 主要风险与控制措施

| 风险 | 影响 | 控制措施 |
|---|---|---|
| 文档与代码/API 不一致 | 用户按文档无法运行 | 以公开 API 和 CI smoke test 为准，发布前逐条验证命令 |
| `pyproject` 与实际版本/功能不一致 | 安装和对外定位错误 | 修正 description、版本和依赖，构建后检查 metadata |
| examples/benchmarks 未进入安装包 | 用户安装后找不到示例 | 明确源码仓库运行策略，必要时增加打包测试，不作隐含承诺 |
| 缺少许可证或归属说明 | 法律和 GitHub 合规风险 | 选择许可证，补充第三方/fixture/参考项目归属 |
| CI 依赖网络或真实服务 | 构建不稳定、泄露凭据 | 默认完全离线，真实 smoke test 独立且不进默认门禁 |
| benchmark 小样本被误读 | 产生不当性能结论 | 保存环境/版本/n，明确不排名和限制，不写固定性能承诺 |
| 发布前偷偷改变执行语义 | 已有用户/测试回归 | 阶段 9只收口和修复发布阻塞问题，功能变更另开阶段 |
| Web 看板范围膨胀 | 延迟核心发布 | 看板独立评审，不作为核心发布前置条件 |
| 敏感日志或生成文件入库 | 凭据/数据泄露 | secret scan、`.gitignore`、发布前文件清单和输出扫描 |
| 只验证当前机器 | 跨平台安装失败 | CI 矩阵和干净环境验证，记录未支持平台 |

## 7. 测试与验证要求

阶段 9 不以盲目增加单元测试数量为目标，而以“干净环境可安装、可运行、可维护”为目标。至少
完成以下验证：

- 当前 427 个测试全部通过；
- `mypy src/magent` 通过；
- 干净虚拟环境安装 `.[dev]` 成功，`import magent` 和版本读取成功；
- 核心 Agent 示例、Graph 示例、Checkpoint 示例、Tools/LLM/Middleware 示例、VulnTell CLI 和
  benchmark CLI 均成功运行；
- VulnTell 默认、`--no-llm`、部分来源失败、`--trace` 和恢复路径均可验证；
- benchmark 结果包含版本、数据集、窗口、样本数、环境和限制说明，且不产生需提交的临时文件；
- sdist/wheel（若本阶段选择构建）在干净环境安装后，公开核心 API 可导入；
- CI 至少覆盖项目声明支持的 Python 版本；
- 文档链接、代码块命令、许可证、第三方归属和目录说明无明显错误；
- 安全检查确认仓库不含密钥、私钥、数据库、真实漏洞原始数据和未授权版权材料；
- 默认测试不访问网络、不调用真实 LLM、不执行外部命令。

## 8. 量化验收标准

阶段 9 已满足本地收口条件；正式 GitHub Release 仍以远程 CI、维护者确认和 tag 创建为最后条件。
计划验收条件如下：

1. `README.md` 能指导新用户在干净环境完成安装、核心示例、VulnTell 和 benchmark 运行；
2. 全量测试、类型检查和 CI 在所有声明支持的 Python 版本上通过；
3. 项目元数据、版本号、README、API、DESIGN、ROADMAP 和阶段文档状态一致；
4. `../architecture/COMPARISON.md` 完成，至少覆盖 LangGraph、AutoGen、CrewAI，并记录版本/来源/取舍；
5. LICENSE、第三方归属、fixture 来源/许可和安全边界文件齐全；
6. 默认流程保持离线，不要求 API Key、真实 LLM、参考框架依赖或生产数据库；
7. VulnTell 和阶段 8 benchmark 结果可按固定入口重放，结果限制和样本规模明确；
8. 发布前扫描无密钥、敏感日志、数据库、缓存和未授权数据，Git 工作区干净；
9. 核心包可安装并导入，示例和 benchmark 的归属/安装范围在文档中明确；
10. 发布说明明确列出当前不支持的分布式执行、动态规划、生产 Web 看板和跨框架排名；
11. 若未完成 Web 看板或 PyPI 发布，不得把它们写入“已交付”清单；
12. 至少生成一次候选 release 检查记录，并由维护者确认后才创建正式 tag/release。

## 9. 完成定义

```text
冻结 GitHub 发布范围与版本策略
        ↓
统一 README/API/DESIGN/路线图事实
        ↓
完成参考项目、许可证与数据归属材料
        ↓
完成干净安装、构建和跨版本 CI
        ↓
完成离线示例、VulnTell 和 benchmark 展示路径
        ↓
完成安全、依赖、敏感信息和生成物审计
        ↓
完成 CHANGELOG、发布清单和限制说明
        ↓
候选 release 验收通过并创建 GitHub release
```

## 10. 建议提交节奏

```text
design(phase9): freeze release scope and compatibility policy
docs: align README API design and phase status
docs: add framework comparison and third-party notices
chore: finalize package metadata and license files
ci: add clean-install test type-check and offline smoke tests
docs: add examples benchmark reproduction and changelog
test: add release security packaging and documentation gates
release: prepare candidate checklist and GitHub release notes
```
