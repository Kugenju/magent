# 文档导航

本目录采用“稳定入口 + 按主题归档”的方式组织。根目录保留兼容入口，实际内容按主题归档；新文档请放入对应主题目录，不再继续向根目录添加散落文件。

## 从这里开始

1. [下一阶段决策与路线](NEXT_STAGE.md)：是否继续在本仓库开发 VulnTell，以及阶段 10+ 的交付顺序。
2. [架构设计](architecture/DESIGN.md)：框架与业务边界、执行语义和安全约束。
3. [公共 API](architecture/API.md)：可依赖的 Python 接口和当前限制。
4. [路线图](phases/ROADMAP.md)：阶段 0–9 的完成情况。

## 主题目录

| 目录 | 内容 | 入口 |
| --- | --- | --- |
| `architecture/` | 架构、API、框架取舍 | [目录说明](architecture/README.md) |
| `phases/` | 阶段实施计划与验收记录 | [目录说明](phases/README.md) |
| `vulntell/` | VulnTell 产品化设计、路线和领域边界 | [目录说明](vulntell/README.md) |
| `evaluation/` | benchmark、可观测性与复现 | [目录说明](evaluation/README.md) |
| `release/` | 发布、兼容性和工程化收口 | [目录说明](release/README.md) |

## 归档位置

旧版根目录文档已完成迁移，不再保留重复副本。正文位置固定为 `architecture/`、`phases/` 和 `evaluation/`；后续引用必须使用这些新路径，新增内容也应放入对应主题目录。

## 文档约定

- 设计/协议文档描述“当前事实”，变更后同步代码、测试和版本记录。
- 阶段文档描述“为什么做、如何验收”，完成后保留，不覆盖历史结论。
- VulnTell 业务文档不得把领域模型或依赖倒灌到 `src/magent`。
- benchmark 结果必须带数据集、版本、环境和样本量；小样本不做排名。
- 默认示例保持离线；真实网络、LLM 和生产部署另设明确开关与验收。
