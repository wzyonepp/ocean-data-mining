# 数据筛查与实验代码

当前提供 [screen_ndbc_data.py](screen_ndbc_data.py)，用于从 NOAA ERDDAP 下载固定浮标子集并检查数据规模、缺测、重复键和时间覆盖；它尚不执行 Parquet 性能实验。

## 运行

本脚本只依赖 Python 标准库，已在 Python 3.12.14 实际运行。在仓库根目录执行：

```bash
python code/screen_ndbc_data.py
```

默认筛查 8 个站点的 2023、2024 年，共 16 个 CSV。最多同时发送两个子集请求，主站失败时尝试 NOAA 备用站；清单始终记录实际来源，不假定镜像相同。

输出：

- `data/raw/`：输入 CSV、提供方元数据及下载侧写文件，仅保留在本地。
- `results/data_screening_manifest.json`：来源、取得时间、SHA-256、行数、缺测、时间覆盖及完整性状态。

重复运行会校验并复用已有缓存；缺失的文件重新尝试下载。缓存来源或哈希不匹配时会报错，不会静默覆盖。

小范围检查可使用独立输出路径，避免覆盖正式清单：

```bash
python code/screen_ndbc_data.py --stations 41001 --years 2024 --output-dir data/smoke --manifest results/smoke_manifest.json
```

发生下载或解析错误时，清单标记 `complete: false`，脚本返回非零退出码；检查并解决错误后重新运行。重新取得的上游数据应与原清单比对，变化需作为新版本记录。

PyArrow、DuckDB 的依赖版本将在后续实验设计和试跑阶段锁定。
