"""Detailed report sections derived from saved evidence; no SQL execution."""
import json
import statistics
from pathlib import Path
import run_parquet_pilot as c
from analyze_parquet_formal import read_csv

ROOT = Path('results/alignment_fresh_v1')

def contribution_section():
    diagnostic=json.loads(Path('results/pilot_v1/boundary_diagnostic.json').read_text())
    actual_rows=[]
    for g in diagnostic['groups']:
        if g['layout']=='station_first':
            actual_rows.append(f"| {g['row_group']} | {g['station_min']}—{g['station_max']} | {g['time_min'][:10]} 至 {g['time_max'][:10]} | {g['matching_rows_on_direct_inspection']} |")
    observed='\n'.join(actual_rows)
    return f'''## 6. 原创探索点的具体拆解

### 6.1 贡献定位：已有知识、借鉴思路与本项目新增工作

本项目的贡献是一次针对浮标时序查询的**实体边界对齐策略及其收益—成本验证**。这里的原创探索指本课程项目形成的问题诊断、方案选择、控制设计和验证链，不是声称首次发明了按实体分组。

| 层次 | 内容 | 本报告中的作用与贡献边界 |
|---|---|---|
| 课堂已有知识 | 列式布局、行组、排序和 min/max 跳过 | 实验起点，不计为新增方法 |
| 已有设计思路 | 按实体聚集、控制分组边界、工作负载驱动布局 | 可借鉴的技术基础，不声称首创 |
| 本项目的问题诊断 | 在具体浮标文件中找出站点边界混合组，核对候选组是否有联合匹配行 | 将课堂机制落到可检查的失效样例 |
| 本项目的具体改动 | 保持站点优先行序，在站点切换处重新开始行组，尾部不足上限也保留为独立组 | 与原固定切组相比改变组边界，不改变逻辑数据和查询 |
| 本项目的验证设计 | 写入接口字节控制、原查询同批复测、固定新日期、存储与全表探针 | 验证正确性、局部收益、成本与泛化边界 |

Qd-tree[5] 代表更广泛的工作负载构块研究，引用它只能说明相关研究基础，不能证明本策略在文献中未出现。当前未完成最近邻策略的穷尽检索，不提供文献层面的首创性结论。可核查的贡献以本项目实际实现、诊断和实验为准。

### 6.2 为什么普通站点排序仍会误保留：真实例子

查询条件为 `station_id = '41002'`，时间为 `[2023-03-15 00:00 UTC, 2023-03-16 00:00 UTC)`。按独立范围统计，一个行组只有在站点区间包含 41002、且时间区间与查询窗口相交时才保留为候选。写成必要条件即：

```text
station_min <= target_station <= station_max
AND time_max >= query_start
AND time_min < query_end
```

这些条件同时成立，不意味着存在**同一条记录**同时满足站点和时间条件。逐列 min/max 没有保存二者的联合对应关系。

预跑文件中实际检查到以下三个候选组，编号从 0 开始：

| 行组 | 站点范围 | 时间范围（仅展示日期） | 独立读取后的实际匹配行数 |
|---|---|---|---:|
{observed}

第 4、10 号组的独立范围都包含查询条件，但没有联合匹配记录；第 5 号组才含 144 条目标记录。这是从文件中读出的案例，不是构造的测试数据。完整时间边界及原始诊断见 [boundary_diagnostic.json](../results/pilot_v1/boundary_diagnostic.json)。它解释统计范围的局限，不代表 DuckDB 实际读取了哪几个组。

下面只示意分组规则，不对应上述真实行组编号。为便于展示，将上限简化为 8 条，每个字母代表一条示意记录；实际实验上限仍为 16,384 行：

```text
同一份站点优先行序：AAAAAA BBBBBBB CCCC

固定行数切组：     [AAAAAA BB] [BBBBB CCC] [C]
                         ↑ 混合边界组 ↑
按站点边界对齐：   [AAAAAA] [BBBBBBB] [CCCC]
```

两种方式都不改变行序。区别在于是否允许一个行组跨越站点；对齐会保留更多不足上限的尾部组。

### 6.3 精确定义改动与实现

将记录先按 `(station_id, observation_time)` 升序排列，设行组行数上限 R=16,384。每个站点的数据独立分批写入，同一文件保持打开：

```text
sorted_rows = sort(rows, station_id, observation_time)
open one ParquetWriter with the common schema and writer settings
for station in sorted(nonempty_station_ids):
    segment = filter(sorted_rows, station_id == station)
    for start in range(0, len(segment), R):
        write segment[start : start + R] as one row group
    # 尾部不足 R 行也已写出；下一站点不得拼入这个尾组
close writer
```

这与实现代码逐站 filter、切片写入一致；不是已经实现的单次流式边界扫描。每个站点少于 R 行时写一组，空站点不写组；缺测水温与重复键在生成布局前统一处理。代码入口见 [run_alignment_extension.py](../code/run_alignment_extension.py)。

若非空站点 s 有 n_s 条记录，普通固定切组数为 `ceil(N/R)`，对齐组数为 `sum_s ceil(n_s/R)`。本数据对应 44 与 48；每组仍不超过 R，但总组数与行数分布允许不同。这个公式用于说明数量变化，不证明该划分最优。

### 6.4 与相邻方法的区别及控制

| 方案 | 全局行序 | 行组边界 | 文件组织 | 本实验是否测量 |
|---|---|---|---|---|
| 普通站点优先 | 站点、时间 | 全表每 R 行切分，可能跨站点 | 单文件、不分区 | 是，直接基线 |
| 本次站点边界对齐 | 同样的站点、时间行序 | 在站点切换处重新开始 | 同一个文件、不建站点目录 | 是，扩展方案 |
| 时间优先 | 时间、站点 | 全表每 R 行切分 | 单文件、不分区 | 是，较强对照 |
| 按站点目录分区 | 不自动保证文件内行序 | 取决于各分区的写入实现 | 改变目录与文件组织 | 否，仅作概念比较 |

控制条件包括相同数据、模式、查询、压缩、编码和行组上限。原站点优先有 7 个跨站点组，新布局为 0。为排除分批写入接口本身造成文件差异，先用同一 ParquetWriter 接口按原固定边界重建基线，生成字节与原文件完全一致；新布局完整读回也与原站点优先行序、值完全一致。证据见 [writer_control.json](../results/alignment_v1/writer_control.json)。

对齐同时改变了边界、组数、行数分布及可能的压缩效果。本实验验证的是**完整策略的总体效果**；缺少相同行组数量的额外控制，不能独立宣称为“纯边界对齐效应”。

### 6.5 探索收益、取舍与可推广范围

在已见 108 条查询的同批探索复测中，原验证日期组 Q1 均值从 3.392 降为 2.827 ms（下降 16.65%），Q2 从 7.917 降为 6.049 ms（下降 23.60%）；同轮时间优先为 2.715 和 2.366 ms，仍更低。该轮只用于探索，随后锁定新日期复核，不用探索阶段较高收益替代新日期结果。

取舍是更多短组和元数据。对齐增加 4 个行组、7 个尾部短组及 1,936 字节文件体积；没有系统测量构建、重写和维护成本。当前实现逐站筛选并物化数据，在站点很多时可能增加写入工作，不能仅凭文件增长 0.072% 就宣称整体成本很低。

高站点基数、每站数据很少、长时间扫描等情况可能削弱收益；这些属于工程推断，尚未在本实验覆盖，不能当作实测结论。时间优先在本数据上仍是更强基线。贡献应落在具体问题、实现、控制、新日期结果和反例的完整验证链上。'''

def exception_section():
    summaries=read_csv(ROOT/'query_summary.csv');raw=read_csv(ROOT/'measurements.csv')
    queries={q['query_id']:q for q in json.loads((ROOT/'queries.json').read_text())}
    pairs={}
    for r in summaries:pairs.setdefault(r['query_id'],{})[r['layout']]=r
    effects=[];counts=[]
    for qid,values in sorted(pairs.items()):
        b,a=values['station_first'],values['station_aligned'];q=queries[qid]
        effects.append({'query_id':qid,'kind':q['kind'],'station_id':q['station_id'],'start_utc':q['start_utc'],
          'window_hours':q['window_hours'],'matching_rows':b['count'],'station_first_mean_ms':b['mean_ms'],
          'station_aligned_mean_ms':a['mean_ms'],'mean_reduction_percent':100*(1-a['mean_ms']/b['mean_ms']),
          'station_first_median_ms':b['median_ms'],'station_aligned_median_ms':a['median_ms'],
          'aligned_mean_lower':a['mean_ms']<b['mean_ms']})
    for kind in ['Q1','Q2']:
        selected=[r for r in effects if r['kind']==kind]
        counts.append({'kind':kind,'queries':len(selected),'mean_lower':sum(r['aligned_mean_lower'] for r in selected),
          'mean_not_lower':sum(not r['aligned_mean_lower'] for r in selected)})
    worst=min(effects,key=lambda r:r['mean_reduction_percent']);qid=worst['query_id'];q=queries[qid]
    case=[]
    for layout in ['station_first','station_aligned','time_first']:
        values=[r['elapsed_ms'] for r in raw if r['query_id']==qid and r['layout']==layout and r['phase']=='measured']
        case.append({'layout':layout,'runs_ms':values,'mean_ms':statistics.mean(values),'median_ms':statistics.median(values)})
    c.save_csv(ROOT/'per_query_effects.csv',effects)
    c.save_json(ROOT/'report_revision_evidence.json',{'counts':counts,'worst_mean_case':worst,'raw_case':case,
      'primary_mean_metric_unchanged':True,'raw_measurements_modified':False,
      'measurements_sha256':c.digest(ROOT/'measurements.csv'),'summary_sha256':c.digest(ROOT/'query_summary.csv'),
      'revision_module_sha256':c.digest(Path(__file__))})
    count_table='\n'.join(f"| {r['kind']} | {r['queries']} | {r['mean_lower']} | {r['mean_not_lower']} |" for r in counts)
    labels={'station_first':'原站点优先','station_aligned':'边界对齐','time_first':'时间优先'}
    case_table='\n'.join(f"| {labels[r['layout']]} | {', '.join(f'{v:.3f}' for v in r['runs_ms'])} | {r['mean_ms']:.3f} | {r['median_ms']:.3f} |" for r in case)
    return f'''### 7.1 逐查询变化：总体均值之外的反例

按每条查询五次计时的未舍入均值比较，结果如下。“更低”仅描述本次测量，不表示统计显著性；这些计数包含已预设的空查询。

| 类型 | 查询数 | 对齐后均值更低 | 对齐后均值未降低 |
|---|---:|---:|---:|
{count_table}

因此，类别均值约 10% 的收益不等于每条查询都改善。完整逐查询变化见 [per_query_effects.csv](../results/alignment_fresh_v1/per_query_effects.csv)。按类别先等权平均耗时再计算收益，与先计算各查询百分比再取平均不是同一指标；本文主结果沿用预先确定的前一种口径。

### 7.2 长尾样例与稳健统计

均值相对变化最不利的样例为 {q['station_id']} 站点，从 {q['start_utc'][:10]} UTC 开始查询 {q['window_hours']//24} 天，返回 {worst['matching_rows']} 条记录。全部五次计时如下，单位毫秒，按重复轮次列出：

| 布局 | 五次原始计时 | 平均值 | 中位数 |
|---|---|---:|---:|
{case_table}

对齐方案的一次约 36.719 ms 长尾值显著抬高均值，而中位数较原站点优先更低。原站点优先与时间优先在该样例中也有较长计时。现有记录不能确定长尾的具体原因，不能直接把它归因于对齐布局的持续性退化，也不能据中位数就声称这个查询稳定改善。

这些原始值保持不变，不因影响收益而删除，也不把中位数替换成新的主要指标。均值仍为预先定义的主指标，中位数与逐次计时用于补充解释；五次重复不足以作显著性或系统长尾归因。机器负载、缓存与调度因素需要另行观测才能判断原因。本节只补充已有测量分析，没有重跑或重新选择查询。'''
