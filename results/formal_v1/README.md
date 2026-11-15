# formal_v1 正式实验结果

按预留的 54 条调整查询与 54 条验证查询执行。三种布局逻辑内容相同，每种 44 个行组；324 次基表答案检查通过，完成 1,620 次计时及 324 次额外预热。

- [结果解释](../../report/07_formal_results.md)
- [图表 PNG / PDF](figures/)
- protocol.json / formal_plan_frozen.md：实际配置、环境、执行前计划与哈希。
- queries.json / reference_answers.json / correctness.json：查询、基表参考答案与实际答案。
- measurements_tuning.csv / measurements_validation.csv / measurements.csv：两阶段及合并后的逐次测量，phase 区分预热与计时。
- frozen_selection.json：仅用调整集形成并在验证计时前保存的选择建议。
- query_summary.csv / class_costs.csv / selection_validation.csv：逐查询、逐类别、逐混合比例的统计。
- candidate_row_groups.csv：按元数据估算的候选行组，不是实际读取量。
- joint_match_diagnostic.csv / joint_match_summary.csv / boundary_summary.csv：全部计时完成后，额外用 PyArrow 读取两个有序布局的候选组，核查实际联合匹配。
- snapshot_rebuild_verification.json：16 个 CSV 哈希与三个 Parquet 文件重新生成后的哈希检查。
- artifact_verification.json：计时数量、选择冻结顺序、配置和文件校验结果。
- analysis_summary.json：供图表与报告使用的指标及分析脚本版本。

9 条预设查询为空结果（调整集 3 条、验证集 6 条），全部保留；非空敏感性分析单列。当前样本全部混合比例选择时间优先，未证明选择规则比固定时间优先有额外收益。

计时采用单线程、暖引擎与系统缓存。原始数据和 Parquet 本体留在 data/，按冻结清单恢复，不纳入 Git。本目录不包含用户指定排除的对话内容。
