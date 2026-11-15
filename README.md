# 海洋数据挖掘课程大作业

研究方向：**面向两类浮标时序查询的 Parquet 排序顺序对照实验**。

仓库：https://github.com/wzyonepp/ocean-data-mining

当前已完成研究问题与边界、资料调研，以及公开数据的实际下载和筛查。尚未运行 Parquet 性能实验，未形成排序优劣结论。

## 文档入口

- [研究问题与研究边界](report/01_research_scope.md)
- [资料调研与研究定位](report/02_literature_review.md)
- [公开数据筛选与实测检查](report/03_data_selection.md)
- [数据筛查结果与校验清单](results/data_screening_manifest.json)
- [数据访问过程记录](results/data_access_notes.md)

## 目录

- [report/](report/)：研究计划与报告。
- [code/](code/)：数据筛查及后续实验代码。
- [results/](results/)：真实运行结果与证据。
- [ai_logs/](ai_logs/)：完整 AI 对话 Markdown 的存放位置，目前尚待导出上传。

数据筛查脚本仅依赖 Python 标准库。在仓库根目录运行 `python code/screen_ndbc_data.py`；详细说明见 [代码目录](code/README.md)。

下一步：锁定实验参数、查询集合、软件版本和测量规则，再进行小规模试跑。
