# 结果与证据

## 边界对齐与新日期验证

- [alignment_v1/](alignment_v1/)：同批比较原站点优先、对齐、时间优先，沿用已见 108 条查询，并增加一个全表扫描探针；1,635 次计时、327 次答案检查。
- [alignment_fresh_v1/](alignment_fresh_v1/)：预先固定 2024-06-15、2024-11-15，54 条新查询、810 次计时、162 次答案检查；方法和布局未修改。
- [完整版实验报告](../report/实验报告.md)：包含局部收益、成本及未超过时间优先的边界。

新日期上边界对齐相对原站点优先的类别均值收益约为 10%，小于探索轮；不将探索值替代确认结果。候选组诊断不是实测 I/O。

## 正式实验

[formal_v1/](formal_v1/) 保存 108 条正式查询的 324 次答案检查、1,620 次计时和 324 次额外预热。选择结果仅依据调整集，在验证计时前冻结。

- [正式结果说明](../report/07_formal_results.md)
- [四组图表 PNG / PDF](formal_v1/figures/)
- [逐次测量](formal_v1/measurements.csv)
- [调整集冻结建议](formal_v1/frozen_selection.json)
- [逐比例验证结果](formal_v1/selection_validation.csv)
- [联合匹配行组诊断](formal_v1/joint_match_diagnostic.csv)
- [输入重新生成校验](formal_v1/snapshot_rebuild_verification.json)

类型平均耗时在当前验证集上均由时间优先较低；未证明按查询比例选择能比固定时间优先额外获益。保留空结果与非空敏感性分析，且不把候选行组估算当作实际磁盘读取量。

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

预跑冻结原文按其运行时哈希保留，属于历史证据；正式实验另外保存在 formal_v1/。预跑样例不能当作普遍性能结论。

