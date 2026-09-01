# VulnTell 漏洞情报源扩展候选（调研清单）

本文用于下一阶段选型，不表示已完成接入。所有自动采集都必须遵守来源的使用条款、robots、速率限制和许可证；无法确认授权时采用人工下载后本地导入。

## 候选来源

| 来源 | 主要内容 | 推荐获取方式 | 稳定性/限制 | 优先级 |
|---|---|---|---|---|
| NVD | CVE、CVSS、CPE、CWE、引用 | 官方 REST 2.0 API | API 限流；需窗口分片 | 已有 |
| CISA KEV | 已被实际利用漏洞目录 | 官方 JSON feed | 字段较少；catalog 版本需记录 | 已有 |
| CNVD | 中国漏洞编号、中文描述和危害等级 | 官方页面人工下载 CSV/JSON 后导入 | 自动请求可能触发 WAF；下载许可需确认 | P0 |
| OSV.dev | 开源包漏洞、受影响版本范围 | OSV API / bulk JSON | 生态以开源包为主；需统一 ecosystem | P0 |
| GitHub Advisory Database | 开源依赖安全公告、GHSA/CVE | GitHub GraphQL/REST（需 token）或官方仓库导出 | token、速率限制；许可证和再分发需审查 | P0 |
| EUVD | 欧盟漏洞数据库、风险和协调信息 | 欧盟官方 API/导出（以当前公开接口为准） | 接口与字段可能演进；需记录版本 | P1 |
| JVN | 日本漏洞公告、JVN iPedia | JVN RSS/CSV/XML | 日文字段、更新频率不一 | P1 |
| CERT/CC Vulnerability Notes | 协调披露、厂商与影响说明 | 官方 RSS/网页人工导入 | 不保证覆盖全部 CVE；网页字段需解析 | P1 |
| Microsoft MSRC | Microsoft 产品安全更新、CVE、KB | MSRC API/安全更新目录 | 微软产品范围；需处理 KB 与 CVE 关联 | P1 |
| Red Hat Security Data | RHSA、CVE、受影响 RPM、CVSS | 官方 JSON/API | Red Hat 生态；版本映射复杂 | P1 |
| Ubuntu CVE Tracker | Ubuntu 状态、修复版本、优先级 | 官方 Git 仓库/数据文件 | Git 同步；需保留 Ubuntu release 维度 | P1 |
| Debian Security Tracker | Debian CVE 状态和修复版本 | 官方 JSON/仓库数据 | Debian release 维度；字段规范独特 | P1 |
| Cisco PSIRT | Cisco 产品公告、修复和 CVSS | 官方 API/公告 RSS（若需授权则人工导入） | 厂商专属；自动化入口需核验 | P2 |
| Fortinet PSIRT | FortiOS 等产品漏洞公告 | 官方 PSIRT RSS/网页 | 厂商专属；产品版本解析成本高 | P2 |
| Palo Alto Networks PSIRT | PAN-OS 等产品公告 | 官方 RSS/公告导出 | 厂商专属；可能有访问频率限制 | P2 |
| Exploit-DB | 公开 PoC/利用条目索引 | 官方 Git 仓库/CSV | 不是完整漏洞库；不得下载或执行 PoC | P2 |
| VulnDB（VulDB） | 商业漏洞情报、别名和利用信息 | 官方 API（商业许可） | 需购买许可；禁止未经授权再分发 | P2 |

## 推荐拓展顺序

第一批（阶段 6）：OSV、GitHub Advisory、EUVD。它们能补齐开源依赖、GHSA 和欧洲协调披露，且结构化程度较高。

第二批（阶段 7）：Microsoft、Red Hat、Ubuntu、Debian、JVN。重点验证产品/发行版版本映射和修复状态。

第三批（阶段 8）：CERT/CC、Cisco、Fortinet、Palo Alto、Exploit-DB；商业 VulnDB 仅在获得许可后评估。

CNVD 作为 P0 维护人工下载导入，不以绕过 WAF 为目标。CNNVD 等无稳定公开结构化接口的来源暂列为人工导入候选，待确认授权和下载格式后再排期。

## 统一接入验收标准

每个来源必须提供：稳定的 `SourceRequest/SourcePage` 映射、来源版本或 feed hash、分页/增量边界、错误分类、字段质量报告、幂等与 checkpoint/resume 测试，以及明确的许可和数据保留说明。API token、Cookie、原始响应和受限数据不得写入 State、Trace、日志或默认报告。

## 统一落盘标准：COSV

所有来源进入 VulnTell 的最终漏洞记录必须转换为 COSV（Chinese Open Source Vulnerability
format）文档；来源原始字段只允许保存在受控的原始归档区，不得直接作为业务查询格式。实现时固定一个受支持的
COSV `schema_version`（当前实现应在配置和报告元数据中显式记录，例如 `1.0`），升级必须通过版本化迁移，不能静默改变含义。

### COSV 文档结构（规范要求）

每条记录是一个 JSON 对象，至少遵循以下字段和约束：

| 字段 | 要求 |
|---|---|
| `schema_version` | 必填，非空字符串；表示 COSV schema 版本 |
| `id` | 必填、全局唯一、稳定；优先使用 `CVE-...`，无 CVE 时使用来源稳定 ID（如 `CNVD-...`），不得因标题变化而改变 |
| `modified` | 必填，RFC 3339/ISO-8601 UTC 时间（带 `Z`）；每次语义变化必须更新 |
| `published` | 有则为 RFC 3339 UTC 时间；未知时省略，不得伪造 |
| `aliases` | 可选字符串数组；放置 CVE、GHSA、CNVD 等跨库别名，不重复，不能把别名误当主 ID |
| `summary` | 可选短标题，字符串；保留来源语言，不把 HTML 当纯文本混入 |
| `details` | 可选详细描述，字符串；不得拼接未授权的引用网页内容 |
| `affected` | 可选数组；每项必须有 `package`（`name`、`ecosystem`），版本范围用 `ranges` 的事件表达 |
| `severity` | 可选数组；保存 CVSS 向量和评分类型，评分应可由向量复算；未知值省略 |
| `references` | 有则为数组；每项包含 `type`（如 `ADVISORY`、`WEB`、`FIX`、`REPORT`）和绝对 `url`，去重且保留来源 |
| `credits` | 可选字符串数组；仅记录来源明确公开的致谢信息 |
| `database_specific` | 可选对象；仅放来源专属、非标准字段（如 `cnvd_level`、`kev_date_added`），键名使用稳定的小写命名空间 |

版本范围必须使用 COSV/OSV 兼容的 `events` 语义：`introduced`、`fixed`、`last_affected`、`limit`。
不得把 `"1.2-1.4"` 之类无法比较的自由文本直接写入标准字段；无法可靠解析时保留在
`database_specific.source_version_text` 并标记质量问题。时间统一 UTC，数组和对象输出顺序必须稳定，
以保证相同输入产生相同内容哈希。

### 来源映射规则

- NVD：`id`=CVE；CVSS/CPE 映射到 `severity`/`affected`；NVD URL 进入 `references`。
- CISA KEV：CVE 作为 `id`；`dateAdded`、`dueDate`、`knownRansomwareCampaignUse` 放入 `database_specific`，不得臆造版本范围。
- OSV/GitHub Advisory：保留原 `aliases` 和 ecosystem；包版本范围原样转换为 `events`。
- CNVD：CNVD 编号作为主 ID（若有 CVE 则 CVE 为 alias 或按产品策略设主 ID）；中文等级放入 `database_specific.cnvd_level`，人工下载文件哈希放入 `database_specific.import_sha256`。
- 厂商/发行版公告：公告编号放入 `aliases` 或 `database_specific.advisory_id`，修复版本必须能定位到具体 package/release。

### COSV 验收门禁

1. JSON schema 校验通过，必填字段、类型、时间格式和 URL 格式无错误。
2. `id`、`aliases`、`references` 去重且跨来源合并后保持可追溯；原始来源和导入批次写入 `database_specific`。
3. 同一来源版本重复同步产生相同规范化内容哈希（幂等）；字段修订会更新 `modified`。
4. 无法标准化的记录进入 `pending`/质量问题队列，不得生成看似完整的 COSV 数据。
5. 报告、查询和后续存储只依赖 COSV 规范化对象；原始 payload 与凭据不得进入默认状态、Trace 或 LLM prompt。
