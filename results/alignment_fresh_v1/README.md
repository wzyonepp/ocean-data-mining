# 两个新起始日上的验证

报告审查补充：per_query_effects.csv 给出全部 54 条查询的配对均值变化与中位数；report_revision_evidence.json 保存改善/未改善数量、最不利均值样例的全部五次计时和源文件哈希。这些仅为原测量的补充分析，主要均值指标未更换，也没有删除长尾值或重跑查询。

预先锁定 2024-06-15、2024-11-15，两日期未用于前述性能查询。布局、代码方法和写入参数没有根据本轮结果修订。

54 条查询、162 次答案检查、810 次计时、162 次额外预热均完成；3 条空 Q1 保留。类型平均耗时相对原站点优先下降约 10.05% / 10.12%，时间优先仍更低。非空敏感性与独立行组诊断见 summary.json 和原始 CSV。

protocol.json / plan_frozen.md / queries.json 为冻结条件；measurements.csv 是逐次记录，correctness.json 为参考与实际答案，joint_match_diagnostic.csv 为独立读取诊断。artifact_verification.json 检查日期不相交、布局不变、测量数量和代码哈希。input_restore_verification.json 证明对齐文件按快照重建后字节一致。

figures/ 提供 PNG/PDF；这是同一历史数据上新的查询日期，不是新数据集、并发或跨硬件泛化验证。报告见 ../../report/实验报告.md。
