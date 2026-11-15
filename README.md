# 海洋数据挖掘课程大作业

研究方向：**面向两类浮标时序查询的 Parquet 排序顺序对照实验**。

仓库：https://github.com/wzyonepp/ocean-data-mining

当前已完成研究边界、资料调研、公开数据筛查、预跑及 108 条正式查询。正式实验的 324 次答案检查全部通过，保存了 1,620 次计时、324 次额外预热和四组 PNG/PDF 图表。

当前数据与暖缓存条件下，验证集类型平均耗时均由时间优先更低。调整集在所有设定查询比例下都选择时间优先，未证明选择规则比固定时间优先有额外收益。详细边界与成本见正式结果。

## 文档入口

- [研究问题与边界](report/01_research_scope.md)
- [资料调研](report/02_literature_review.md)
- [数据筛选](report/03_data_selection.md)
- [实验方案](report/04_experiment_protocol.md)
- [预跑结果及边界行组诊断](report/05_pilot_findings.md)
- [正式实验计划与执行状态](report/06_formal_experiment_plan.md)
- [正式实验结果与排序建议](report/07_formal_results.md)
- [四组图表（PNG / PDF）](results/formal_v1/figures/)
- [按用户指定范围导出的 AI 对话](ai_logs/01_课程解读到实验预跑.md)

## 目录与复现

- [report/](report/)：研究计划和报告。
- [code/](code/)：数据筛查与预跑脚本。
- [results/](results/)：实际数据检查、原始测量、查询计划与校验文件。
- [ai_logs/](ai_logs/)：用户与助手对话记录；按用户要求排除了一轮对话及对应回复。

正式结果复现：

```bash
python -m pip install -r requirements-formal.txt
python code/restore_parquet_inputs.py
python code/run_parquet_formal.py --run-id formal_v1_replication
python code/analyze_parquet_formal.py --run-dir results/formal_v1_replication
```

原始 CSV 与 Parquet 文件在本地 data/ 保存，未纳入 Git。恢复脚本按已提交清单校验 SHA-256，不覆盖已有结果；上游数据无法匹配时明确失败。三个布局已通过重新生成后的逐字节校验。运行 ID 应唯一，后续仅生成图表可单独运行分析脚本。

