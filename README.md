# 海洋数据挖掘课程大作业

研究方向：**面向两类浮标时序查询的 Parquet 排序顺序对照实验**。

仓库：https://github.com/wzyonepp/ocean-data-mining

当前已完成研究边界、资料调研、公开数据筛查、实验方案及 12 条查询的预跑。三个布局的 36 次答案检查通过，保存了 180 次计时；正式实验尚未运行。

## 文档入口

- [研究问题与边界](report/01_research_scope.md)
- [资料调研](report/02_literature_review.md)
- [数据筛选](report/03_data_selection.md)
- [实验方案](report/04_experiment_protocol.md)
- [预跑结果及边界行组诊断](report/05_pilot_findings.md)
- [下一步：正式实验计划](report/06_formal_experiment_plan.md)
- [按用户指定范围导出的 AI 对话](ai_logs/01_课程解读到实验预跑.md)

## 目录与复现

- [report/](report/)：研究计划和报告。
- [code/](code/)：数据筛查与预跑脚本。
- [results/](results/)：实际数据检查、原始测量、查询计划与校验文件。
- [ai_logs/](ai_logs/)：用户与助手对话记录；按用户要求排除了一轮对话及对应回复。

数据筛查：`python code/screen_ndbc_data.py`。

预跑：安装 [requirements-pilot.txt](requirements-pilot.txt) 后，执行 `python code/run_parquet_pilot.py --run-id pilot_v1_replication`。运行 ID 应保持唯一，保留既有证据。

原始 CSV 与 Parquet 文件在本地 data/ 保存，未纳入 Git；来源与 SHA-256 见结果清单。方案修订仅取消个人预测环节，研究假设与实验参数继续保留。下一步运行预留的 108 条正式查询，检验排序适用边界及选择建议。

