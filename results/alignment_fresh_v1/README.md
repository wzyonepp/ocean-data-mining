# 两个新起始日上的验证

预先锁定 2024-06-15、2024-11-15，两日期未用于前述性能查询。布局、方法和写入参数没有根据本轮结果修订。

54 条查询、162 次答案检查、810 次计时、162 次额外预热均完成；3 条空 Q1 保留。类型平均耗时相对原站点优先下降约 10.05% / 10.12%，时间优先仍更低。

## 已保存的结果快照

- protocol.json / plan_frozen.md / queries.json：冻结条件。
- measurements.csv：逐次计时；correctness.json：参考与实际答案。
- joint_match_diagnostic.csv / joint_match_summary.csv：独立读取的行组诊断。
- summary.json / class_summary.csv：原有类别均值和行组统计。
- per_query_effects.csv：54 条查询的配对均值变化与中位数。
- report_revision_evidence.json：此前补充分析的改善数量、最不利均值样例、全部五次计时和哈希。该文件是实验统计证据，名称及历史哈希沿用原样。
- artifact_verification.json：原有条件检查；input_restore_verification.json：对齐文件按快照重建的字节校验。
- figures/：已保存的 PNG/PDF 图表。

这是同一历史数据上的新查询日期，不是新数据集、并发或跨硬件验证。候选行组统计不是 DuckDB 实际读取量。阶段结果见 [新日期实验说明](../../report/11_fresh_dates_results.md)。

## 重新分析，不重新测量

```bash
python code/analyze_alignment_fresh_dates.py
```

从仓库根目录执行，默认写到本目录的 `analysis/`，不覆盖上述快照。新分析输出记录当前脚本和输入哈希，提供同一主要均值指标、逐查询比较、长尾样例与图表。`--statistics-only` 跳过绘图；`--verify-inputs` 额外检查已恢复的本地 Parquet 字节。不生成最终课程报告。
