# 海洋数据挖掘：AI 问答与实验材料

研究课题：浮标时序数据的 Parquet 排序与站点边界对齐。

仓库：https://github.com/wzyonepp/ocean-data-mining

本仓库保存 AI 补充问答和实验材料，最终课程报告单独提交。

## 材料入口

- [大作业ai对话记录](ai_logs/02_研究过程补充问答.md)：按已确认提纲整理的补充问答，文件开头说明其性质。
- [实验方案与过程文档](report/)：研究问题、资料、数据来源、预先方案和分阶段结果。
- [实验代码](code/)与[固定配置](config/)。
- [原始结果与图表](results/)：逐次计时、正确性检查、运行条件、行组诊断和来源清单。

`report/` 保留历史路径，因为实验脚本会读取其中的方案文件；该目录不存放最终报告。

## 已完成的实验

| 阶段 | 查询数 | 布局数 | 计时次数 |
|---|---:|---:|---:|
| 预跑 | 12 | 3 | 180 |
| 正式排序对照 | 108 | 3 | 1,620 |
| 边界对齐探索（含全表 Q0） | 109 | 3 | 1,635 |
| 两个新日期验证 | 54 | 3 | 810 |

新日期上，边界对齐相对原站点优先的 Q1、Q2 平均耗时分别下降 10.05% 和 10.12%；时间优先的两类查询平均耗时仍然更低。结论限于当前历史数据、查询范围和运行条件。

## 分析已有结果，不重新计时

在仓库根目录执行：

```bash
python -m pip install -r requirements-formal.txt
python code/analyze_alignment_fresh_dates.py
```

默认输出到 `results/alignment_fresh_v1/analysis/`，包含统计、逐查询比较、长尾样例、检查记录和 PNG/PDF 图表，不覆盖已有结果快照，不生成最终报告。只计算统计可加 `--statistics-only`；核对已恢复的本地 Parquet 字节可加 `--verify-inputs`。

## 另行复现实验

```bash
python code/restore_alignment_inputs.py
python code/run_alignment_fresh_dates.py --run-id fresh_replication
python code/analyze_alignment_fresh_dates.py --run-dir results/fresh_replication
```

运行 ID 必须此前未使用。浮标观测原始 CSV 和 Parquet 文件不纳入 Git，恢复工具按来源清单和 SHA-256 校验输入；上游无法匹配快照时明确报错。完整阶段的复现方式见 [代码说明](code/README.md)。
