# 结果与证据

## 数据筛查

- [数据文件及来源校验清单](data_screening_manifest.json)
- [实际访问过程记录](data_access_notes.md)
- [数据筛选说明](../report/03_data_selection.md)

实际下载 16 个年度文件，734,800 条记录中有 713,823 条非缺测水温记录，重复的站点与时间键为 0。

## Parquet 预跑

[完整预跑说明](../report/05_pilot_findings.md)与 [pilot_v1/ 运行证据](pilot_v1/)一并保存。三种布局各有 44 个行组，36 次答案检查通过，共保存 180 次计时及 36 次额外预热。

- [运行状态](pilot_v1/run_status.json)
- [原始测量值](pilot_v1/measurements.csv)
- [查询耗时汇总](pilot_v1/query_summary.csv)
- [元数据候选行组估算](pilot_v1/candidate_row_groups.csv)
- [独立边界行组诊断](pilot_v1/boundary_diagnostic.json)
- [运行时冻结方案](pilot_v1/experiment_protocol_frozen.md)
- [后续文档说明修订](pilot_v1/documentation_revision.json)
- [当前证据检查](pilot_v1/artifact_verification.json)

文档修订只取消个人预测环节并同步文件；冻结原文按其运行时哈希保留，属于历史证据。正式实验的 108 条查询尚未运行，不能把预跑结果当作普遍性能结论。

