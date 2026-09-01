# VulnTell 阶段 5 收尾实施计划：Live 入口与端到端采集

## 目标

将已经存在的 NVD/CISA/CNVD adapter 接入 VulnTell 正式应用服务，在显式 `live` 开关下完成“请求 → 分页/增量 → 规范化 → 去重 → 持久化 → 指标/报告”的单来源纵向流程。默认运行、无 key 和 fixture 回归必须保持不变。

## 任务顺序

### 5C.1 统一 live 配置与入口

- 为 `VulnTellConfig` 增加 `mode`（fixture/live）、`source`、窗口、endpoint allowlist 和超时配置；
- CLI 增加 `sync --source nvd|cisa_kev|cnvd --live`（或等价参数），live 未显式开启时拒绝构造 HTTP transport；
- `VulnTellApplication`/`VulnTellJobRunner` 通过依赖注入选择 adapter，三来源共享同一 pipeline；
- `cisa_kev` 加入来源 schema，但不改变旧 fixture baseline；
- API key 只从受控环境/secret provider 注入，禁止进入配置序列化、State、trace 或异常消息。

验收：默认 CLI 的 socket 禁止测试仍通过；live 参数缺失、未知来源和非 allowlist endpoint 在启动前失败；NVD/CISA live 单页能生成与 fixture 相同结构的 `SourceObservation`。

### 5C.2 修复 NVD 窗口与分页

- 将任意时间窗口切分为 NVD 允许的最大区间（以官方限制为准），按修改时间稳定排序；
- 游标同时携带窗口分片和 `startIndex`，request fingerprint 覆盖分片参数；
- `next_cursor` 必须使用服务端偏移/结果数，过滤掉坏记录时不得跳过有效 CVE；
- 提取 CVSS/CPE 所需最小字段，并限制单页/总响应大小。

验收：历史 CVE 查询不再因超大窗口返回 404；跨分片恢复和重复运行幂等；请求失败只重试当前分片。

### 5C.3 完善 CISA KEV 增量边界

- 记录 catalog version/hash 与 `SyncRun`；相同版本返回空增量；
- 对大 catalog 采用受控批次或流式解析，避免一次性把全部记录放入状态；
- 明确 `dateAdded` 窗口过滤、版本变化和删除/修订语义；
- 为 CISA 结果设置稳定的 page/batch execution key。

验收：同一 catalog 重复同步不重复写入；版本变化可恢复；内存和 batch 大小有上限。

### 5C.4 CNVD 可行性与合规路径

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

### 5C.5 依赖、测试和观测

- 将 `httpx` 放入 live extra（或运行时依赖），为干净安装增加 import smoke；
- 为每个 adapter 增加 fake transport、mock HTTP、脱敏、超时、429、取消和响应过大测试；
- 增加 live pipeline contract（默认跳过，显式环境变量开启），记录 endpoint、窗口、source version、记录数和耗时，不记录 raw payload；
- 增加端到端 checkpoint/resume/幂等测试，验证真实 adapter 输出与领域层契约兼容。

## 阶段完成门禁

```text
python -m pytest -q tests/contract/vulntell tests/unit
python -m pytest -q
mypy src/magent
python -m apps.vulntell --no-llm --json
python -m apps.vulntell sync --source nvd --live --since ... --until ...   # 显式 smoke
git diff --check
```

必须满足：至少 NVD 和 CISA 可从正式 CLI/Application 端到端产出报告；CNVD 有结构化 live 方案或合规人工 fixture 方案；默认运行不联网；相同窗口可恢复且幂等；凭据/raw payload 不泄露；未修改 `magent` 通用语义。

## 交付与回滚

按 5C.1 → 5C.2/5C.3 → 5C.4 → 5C.5 分提交。live 失败时 feature flag 回退 fixture，不删除旧入口或阶段 0–3 baseline。所有门禁通过后，才进入阶段 6 的 schema v2、repository 和查询实现。
