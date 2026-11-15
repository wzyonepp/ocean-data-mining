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

本项目围绕浮标时序查询，**实现站点边界对齐策略，并验证查询改进和额外代价**。这里的原创探索指本课程项目中完成的问题诊断、方案选择、对照实验和结果分析，不声称首次提出按站点等实体分组的思路。

| 层次 | 内容 | 本报告中的作用与贡献边界 |
|---|---|---|
| 课堂已有知识 | 列式布局、行组、排序和 min/max 跳过 | 实验起点，不计为新增方法 |
| 已有设计思路 | 将同一实体的数据放在一起、控制分组边界、根据查询需求设计布局 | 可借鉴的技术基础，不声称首创 |
| 本项目的问题诊断 | 在具体浮标文件中找出站点边界混合组，核对候选行组是否有同时满足站点和时间条件的记录 | 用实际文件说明范围统计为何未能排除无匹配行组 |
| 本项目的具体改动 | 保持站点优先行序，在站点切换处重新开始行组，尾部不足上限也保留为独立组 | 与原固定切组相比改变组边界，不改变逻辑数据和查询 |
| 本项目的验证设计 | 用相同写入接口重建原布局并逐字节核对、同轮复测原查询、另用新日期验证、检查存储与全表扫描耗时 | 验证结果正确性、局部改进、额外代价及适用范围 |

Qd-tree[5] 研究如何根据查询需求组织数据布局，可作为相关工作的参考。但引用这一研究不能证明站点边界对齐此前无人使用。当前尚未全面比较所有相近方法，因此本文不作方法首创的判断，贡献以本项目实际完成的实现、诊断和实验为准。

### 6.2 为什么按站点排序仍会保留无匹配行组：真实例子

查询条件为 `station_id = '41002'`，时间为 `[2023-03-15 00:00 UTC, 2023-03-16 00:00 UTC)`。按独立范围统计，一个行组只有在站点区间包含 41002、且时间区间与查询窗口相交时才保留为候选。写成必要条件即：

```text
station_min <= target_station <= station_max
AND time_max >= query_start
AND time_min < query_end
```

这些条件同时成立，不意味着存在**同一条记录**同时满足站点和时间条件。逐列 min/max 只记录各列的范围，没有记录某个站点具体对应哪些时间。

预跑文件中实际检查到以下三个候选组，编号从 0 开始：

| 行组 | 站点范围 | 时间范围（仅展示日期） | 独立读取后的实际匹配行数 |
|---|---|---|---:|
{observed}

第 4、10 号组的独立范围都包含查询条件，但没有同时满足站点与时间条件的记录；第 5 号组才含 144 条目标记录。这是从文件中读出的案例，不是构造的测试数据。完整时间边界及原始诊断见 [boundary_diagnostic.json](../results/pilot_v1/boundary_diagnostic.json)。它解释统计范围的局限，不代表 DuckDB 实际读取了哪几个组。

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

实际代码也是逐站筛选数据，再按行数切片写入，并未实现只遍历一次数据的流式写入。每个站点少于 R 行时写一组，没有记录的站点不写组；生成布局前已统一剔除缺测水温，并检查站点与时间的组合是否重复。代码入口见 [run_alignment_extension.py](../code/run_alignment_extension.py)。

设总记录数为 N，有记录的站点 s 包含 n_s 条记录，ceil 表示向上取整。普通固定分组的行组数为 `ceil(N/R)`，边界对齐后的行组数为 `sum_s ceil(n_s/R)`，即分别计算每个站点需要的组数，再求和。本数据对应 44 与 48；每组仍不超过 R，但总组数和各组行数会变化。这个公式只说明组数如何变化，并不证明这种分组方式最优。

### 6.4 方法比较与实验控制条件

| 方案 | 全局行序 | 行组边界 | 文件组织 | 本实验是否测量 |
|---|---|---|---|---|
| 普通站点优先 | 站点、时间 | 全表每 R 行切分，可能跨站点 | 单文件、不分区 | 是，直接对照 |
| 本次站点边界对齐 | 同样的站点、时间行序 | 在站点切换处重新开始 | 同一个文件、不建站点目录 | 是，扩展方案 |
| 时间优先 | 时间、站点 | 全表每 R 行切分 | 单文件、不分区 | 是，性能更好的对照 |
| 按站点目录分区 | 不自动保证文件内行序 | 取决于各分区的写入实现 | 改变目录与文件组织 | 否，仅作概念比较 |

各方案使用相同的数据、字段类型、查询、压缩设置、编码设置和行组行数上限。原站点优先有 7 个跨站点组，新布局为 0。为排除分批写入接口本身造成文件差异，先用同一 ParquetWriter 接口按原固定边界重建对照布局，生成文件与原文件逐字节完全一致；新布局完整读回也与原站点优先行序、值完全一致。证据见 [writer_control.json](../results/alignment_v1/writer_control.json)。

边界对齐也会改变行组数量、各组行数，并可能影响压缩效果。本实验验证的是**整套分组策略的总体效果**。由于没有增加行组数量相同的对照方案，无法将观察到的改进全部归因于边界变化本身。

### 6.5 探索阶段的改进、代价与适用范围

探索阶段使用之前测试过的 108 条查询，在同一轮中复测各布局。其中，属于原验证日期的 Q1 平均耗时从 3.392 降为 2.827 ms（下降 16.65%），Q2 平均耗时从 7.917 降为 6.049 ms（下降 23.60%）；同轮时间优先的平均耗时为 2.715 和 2.366 ms，仍然更低。该轮用于探索改动效果，随后预先确定新日期进行验证，最终结论采用新日期的结果。

相应代价是行数不足上限的行组增多，元数据也随之增加。对齐增加 4 个行组、7 个尾部短组及 1,936 字节文件体积；没有系统测量构建、重写和维护成本。当前实现需要逐站筛选，并在内存中生成各站点的数据，在站点很多时可能增加处理时间和内存占用。因此，文件仅增长 0.072% 并不说明生成和维护这种布局的总代价很小。

当站点数量很多、每站记录很少，或者查询需要扫描很长的时间范围时，这种分组方式可能不再有效；这些情况尚未测试，只是后续需要验证的推测。在本数据上，时间优先的两类查询平均耗时仍然更低。本项目的贡献是发现具体问题、实现改动，并同时检查改善、不利结果和额外代价。'''

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
    return f'''### 7.1 逐条查询检查：并非每条查询都改善

对每条查询先计算五次计时的平均值，再比较两种布局，比较时使用未经四舍五入的数值。“更低”只表示本次测量值更小，不能据此判断差异是否具有统计显著性；表中包含预先确定的空结果查询。

| 类型 | 查询数 | 对齐后平均耗时更低 | 对齐后平均耗时未降低 |
|---|---:|---:|---:|
{count_table}

因此，两类查询平均耗时下降约 10%，不等于每条查询都更快。完整逐查询变化见 [per_query_effects.csv](../results/alignment_fresh_v1/per_query_effects.csv)。本文先对每类查询的耗时取等权平均，再比较两种布局的平均耗时，计算下降百分比；没有先计算每条查询的下降百分比再取平均。这两种计算方式不同，主结果始终使用前一种方式。

### 7.2 一次较长计时如何影响平均值

按平均耗时的相对变化比较，边界对齐表现最不利的查询来自 {q['station_id']} 站点，从 {q['start_utc'][:10]} UTC 开始查询 {q['window_hours']//24} 天，返回 {worst['matching_rows']} 条记录。全部五次计时如下，单位毫秒，按重复轮次列出：

| 布局 | 五次原始计时 | 平均值 | 中位数 |
|---|---|---:|---:|
{case_table}

边界对齐有一次查询耗时约 36.719 ms，明显长于其余四次。这种少数耗时较长的情况称为“长尾”，会抬高平均值；但对齐方案的中位数仍低于原站点优先。原站点优先与时间优先在该样例中也有较长计时。现有记录不能确定长尾的具体原因，既不能据此断言边界对齐会持续变慢，也不能只凭中位数较低就断言它会稳定变快。

分析保留全部原始计时，不删除较长的数值，也不更换预先确定的主要指标。平均值仍用于主要比较，中位数和逐次计时只作补充解释。每条查询只有五次计时，尚不足以可靠判断差异是否具有统计显著性，也不足以查明长尾出现的原因。机器负载、缓存与调度因素需要另行观测才能判断原因。本节只补充已有测量分析，没有重跑或重新选择查询。'''
