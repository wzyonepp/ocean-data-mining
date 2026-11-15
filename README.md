# 海洋数据挖掘课程大作业

研究课题：浮标时序 Parquet 布局中站点边界对齐的效益与代价。

仓库：https://github.com/wzyonepp/ocean-data-mining

## 提交材料

- [最终实验报告](report/实验报告.md)
- [大作业ai对话记录](ai_logs/02_研究过程补充问答.md)：按已确认提纲整理的补充问答，文件开头说明其性质。

新日期验证中，边界对齐相对原站点优先布局的 Q1、Q2 平均耗时分别下降 10.05% 和 10.12%；时间优先的两类查询平均耗时仍然更低。结论限于当前数据和实验条件。

## 报告依据与复现

- [研究文档](report/)：资料、实验方案与分阶段结果。
- [实验代码](code/)及[依赖版本](requirements-formal.txt)。
- [原始结果与图表](results/)：计时、正确性检查、运行条件、行组诊断和数据来源清单。
- [实验配置](config/)：固定参数和查询范围。

在仓库根目录执行以下命令可另行复现新日期验证，运行 ID 必须此前未使用：

```bash
python -m pip install -r requirements-formal.txt
python code/restore_alignment_inputs.py
python code/run_alignment_fresh_dates.py --run-id fresh_replication
```

原始 CSV 与 Parquet 文件不纳入 Git，恢复工具按已保存的来源和 SHA-256 校验输入。只更新报告文字及派生统计可运行 `python code/build_final_report.py --report-only`，不重新执行 SQL 或生成图表。
