# pilot_v1 运行证据

该目录保存已完成的 12 条查询预跑，详情见 [预跑结果](../../report/05_pilot_findings.md)。

- protocol.json：实际环境、配置、源数据清单与脚本哈希。
- experiment_protocol_frozen.md：运行时方案原文，对应 protocol.json 的 experiment_protocol_sha256；历史文本不构成当前待办要求。
- documentation_revision.json：本轮取消个人预测环节、同步仓库时的说明修订；实验参数与测量未改动。
- artifact_verification_original.json：说明修订前的检查快照。
- artifact_verification.json：修订后核对冻结方案、脚本、配置与测量的检查结果。
- measurements.csv / query_summary.csv：逐次耗时和统计汇总。
- correctness.json / layout_manifest.json：答案一致性与文件内容检查。
- row_group_metadata.json / candidate_row_groups.csv：元数据与候选行组估算，不是实际磁盘 I/O。
- boundary_diagnostic.json：额外直接读取候选行组的诊断，不代表 DuckDB 实际读取路径。
- planned_formal_queries_NOT_RUN.json：预留正式查询，当前尚未运行。

表中的时间来自预热后的单线程查询，包含绑定、计划、查询和结果提取。不得将这些样例描述为冷缓存测试或已证明的通用排序优势。

