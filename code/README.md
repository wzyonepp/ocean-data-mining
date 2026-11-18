# 实验代码与复现

从仓库根目录运行命令，先安装固定依赖：

```bash
python -m pip install -r requirements-formal.txt
```

Python 与包版本须与运行协议一致；原实验使用 Python 3.12.14、PyArrow 26.0.1、DuckDB 2.0.0。

## 只分析已有新日期结果

```bash
python code/analyze_alignment_fresh_dates.py
```

入口读取 `results/alignment_fresh_v1/`，默认写入其 `analysis/` 子目录。它不执行 SQL、不构建布局、不生成最终报告，也不覆盖已发表的原始结果或派生统计。输出包括：

- `analysis_checks.json`：查询集合、计时数量、正确性、冻结条件及源文件哈希检查。
- `summary.json`、`class_summary.csv`：两类查询的平均耗时和行组统计。
- `per_query_effects.csv`、`query_effect_evidence.json`：逐查询比较、未改善数量和长尾样例的全部重复计时。
- `figures/`：耗时与候选行组的 PNG/PDF 图表。

```bash
python code/analyze_alignment_fresh_dates.py --statistics-only
python code/analyze_alignment_fresh_dates.py --run-dir results/fresh_replication
```

可用 `--output-dir` 指定独立分析目录，但不能写回源运行目录或其父目录。默认校验已保存结果与元数据；加 `--verify-inputs` 才会额外读取本地 Parquet 文件计算 SHA-256，需要先恢复输入。元数据候选行组统计不是实际引擎读取量。

新入口由原来的报告工具拆出，保留实验分析和作图，移除了最终报告撰写功能。历史结果中的旧分析代码哈希保持原样，新分析输出记录当前脚本及输入哈希。

## 恢复输入

```bash
python code/restore_parquet_inputs.py
python code/restore_alignment_inputs.py
```

恢复工具只在 `data/` 保存 CSV、Parquet 与恢复日志，按已提交来源和 SHA-256 校验，不改写原数据清单。上游变化或本地字节不匹配时明确失败。不要用重新筛查覆盖清单来复现旧结果。

## 另行运行各阶段

每次选用未使用过的运行 ID，以下命令供需要重新测量时执行：

```bash
python code/run_parquet_pilot.py --run-id pilot_replication
python code/run_parquet_formal.py --run-id formal_replication
python code/analyze_parquet_formal.py --run-dir results/formal_replication
python code/run_alignment_extension.py --run-id alignment_replication
python code/analyze_alignment_extension.py --run-dir results/alignment_replication
python code/run_alignment_fresh_dates.py --run-id fresh_replication
python code/analyze_alignment_fresh_dates.py --run-dir results/fresh_replication
```

各运行脚本使用原有的固定输入和方案，不会因为运行了另一个新 ID 而自动替换后续阶段的输入。新日期验证仍按配置读取原扩展布局清单。若更改数据、布局或查询，应另定方案，不沿用旧验证结论。

正式与探索分析脚本可生成实验阶段结果说明；它们不生成最终课程报告。新日期统计和图表只写到独立分析目录。

## 文件用途

| 文件 | 用途 |
|---|---|
| screen_ndbc_data.py | 下载和筛查浮标数据 |
| restore_parquet_inputs.py / restore_alignment_inputs.py | 按快照恢复输入 |
| run_parquet_pilot.py | 预跑、原始布局生成与基础查询 |
| run_parquet_formal.py | 调整集、验证集与行组诊断 |
| run_alignment_extension.py | 边界对齐与全表扫描探索 |
| run_alignment_fresh_dates.py | 固定新日期验证 |
| analyze_parquet_formal.py | 正式结果分析和作图 |
| analyze_alignment_extension.py | 探索结果分析和作图 |
| analyze_alignment_fresh_dates.py | 新日期检查、统计和作图 |
| analyze_query_effects.py | 逐查询变化与长尾样例计算 |

## 另取数据时的独立筛查

```bash
python code/screen_ndbc_data.py --output-dir data/new_screening --manifest results/new_screening_manifest.json
```

该命令用于新的数据筛查，不是恢复原实验。原始数据提供方、取得时间、缺测和重复键等信息见 `results/data_screening_manifest.json`。
