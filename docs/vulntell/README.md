# VulnTell 产品文档

- [下一阶段决策与路线](../NEXT_STAGE.md)
- [MVP 范围与验收](PRODUCT_SCOPE.md)
- [最终框架实现设计](FINAL_DESIGN.md)
- [产品化实施路线图](ROADMAP.md)
- [阶段 0–1 详细实施方案](PHASE0_1_PLAN.md)
- [阶段 2：领域层迁移实施计划](PHASE2_PLAN.md)
- [阶段 3：Graph 与任务层迁移实施计划](PHASE3_PLAN.md)
- [阶段 3 审查记录](PHASE3_REVIEW.md)
- [阶段 4：数据源契约与增量模型实施计划](PHASE4_PLAN.md)
- [阶段 7 纵向示例](../phases/PHASE7.md)
- [评测与复现](../evaluation/BENCHMARKS.md)

`apps/vulntell` 是当前产品化应用入口，默认仍为离线、fixture-first；`examples/vulntell` 仅保留迁移兼容入口和过渡模块。VulnTell 继续通过 `magent` 的公开 API 集成，避免修改框架核心语义。
