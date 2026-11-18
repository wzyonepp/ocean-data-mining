# 实验方案与过程文档

本目录保存实验依据与分阶段说明，不保存最终课程报告。沿用 `report/` 路径，避免改变实验脚本引用的方案位置；运行时的冻结快照和哈希仍保存在 `results/`。

- [研究问题与边界](01_research_scope.md)
- [资料调研](02_literature_review.md)
- [数据筛选](03_data_selection.md)
- [初始实验方案](04_experiment_protocol.md)
- [预跑与真实行组诊断](05_pilot_findings.md)
- [正式实验方案](06_formal_experiment_plan.md)
- [正式实验结果](07_formal_results.md)
- [边界对齐方案](08_alignment_protocol.md)与[探索结果](09_alignment_results.md)
- [新日期预先方案](10_fresh_dates_protocol.md)与[验证结果](11_fresh_dates_results.md)

配套入口：[AI 补充问答](../ai_logs/02_研究过程补充问答.md)、[实验代码](../code/README.md)、[原始结果与图表](../results/README.md)。

已有测量与方案快照保持不变。重新分析新日期结果可运行 `python code/analyze_alignment_fresh_dates.py`；默认将派生结果另存到原运行目录下的 `analysis/`，不重跑 SQL。
