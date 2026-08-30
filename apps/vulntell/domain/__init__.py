"""VulnTell 领域层（阶段 2 从 examples.vulntell 迁移）。

包含领域模型、数据集/ fixture schema、纯标准化/去重/指标规则与共享策略常量。
不导入 magent 内部实现（schemas 仅使用 magent.checkpoint.models 的纯工具函数），
不依赖网络、外部命令或密钥。
"""
