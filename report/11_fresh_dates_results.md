# 新日期验证结果

在测量前锁定 2024-06-15、2024-11-15 两个新起始日，与之前全部性能查询的起始日不相交。布局和参数未修改。54 条查询、162 次答案检查、810 次计时、162 次额外预热全部完成。3 条 Q1 为空结果，保留在主要分析中。

| 查询 | 原站点优先 ms | 边界对齐 ms | 时间优先 ms | 相对原站点优先的耗时下降 |
|---|---:|---:|---:|---:|
| Q1 | 3.492 | 3.141 | 2.933 | 10.05% |
| Q2 | 7.717 | 6.936 | 2.580 | 10.12% |

![新日期耗时](../results/alignment_fresh_v1/figures/fresh_latency.png)

在新查询日期上，边界对齐的平均耗时仍比原站点优先更低，但下降幅度小于探索轮的 16.65% 和 23.60%；时间优先的两类查询平均耗时仍更低。排除空结果后，Q1 的三种布局平均耗时分别为 3.579、3.196、2.992 ms，改善并非只由空查询产生。

![新日期候选组](../results/alignment_fresh_v1/figures/fresh_groups.png)

在有匹配记录的 Q1 中，原站点优先布局每条查询平均有 1.467 个候选行组实际没有匹配记录，对齐后为 0.000。候选行组数由元数据推算，实际匹配情况由 Arrow 额外读取后核对；这两项均不是 DuckDB 实际读取量。所有方法使用同一份历史数据和同一硬件，只更换查询起始日，因此这不是在独立新数据集上的验证。每条查询五次计时，也不足以证明方案普遍最优或性能差异具有统计显著性。

原始记录见 [measurements.csv](../results/alignment_fresh_v1/measurements.csv)，运行前确定的实验条件见 [protocol.json](../results/alignment_fresh_v1/protocol.json)，检查见 [artifact_verification.json](../results/alignment_fresh_v1/artifact_verification.json)。运行命令：`python code/run_alignment_fresh_dates.py --run-id fresh_replication`。使用新的运行 ID 将结果另存，不覆盖旧证据。统计与图表可用 `python code/analyze_alignment_fresh_dates.py` 从保存结果重新生成，默认另存到 `results/alignment_fresh_v1/analysis/`，无需重新计时，不生成最终课程报告。只计算统计可加 `--statistics-only`。
