#!/usr/bin/env python3
"""Build evidence-backed coursework report and fresh-date figures, without SQL."""
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/marine-course-matplotlib')
import json,statistics,random
from pathlib import Path
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import run_parquet_pilot as c
from analyze_parquet_formal import read_csv
from report_revision_sections import contribution_section, exception_section

ROOT=Path('results/alignment_fresh_v1')
ORDER=['station_first','station_aligned','time_first']
LABELS=['Station fixed','Station aligned','Time first']
COLORS=['#ce8f39','#346ca3','#147d83']

def build(report_only=False):
    status=json.loads((ROOT/'run_status.json').read_text());protocol=json.loads((ROOT/'protocol.json').read_text())
    rows=read_csv(ROOT/'measurements.csv');query_summary=read_csv(ROOT/'query_summary.csv')
    diag=read_csv(ROOT/'joint_match_summary.csv');queries=json.loads((ROOT/'queries.json').read_text())
    answers=json.loads((ROOT/'correctness.json').read_text())
    layouts=json.loads(Path('results/alignment_v1/layouts.json').read_text())
    oldq=[]
    for path in ['results/pilot_v1/pilot_queries.json','results/formal_v1/queries.json','results/alignment_v1/queries.json']:oldq+=json.loads(Path(path).read_text())
    counts=Counter((r['query_id'],r['layout']) for r in rows if r['phase']=='measured')
    warm=Counter((r['query_id'],r['layout']) for r in rows if r['phase']=='warmup')
    checks={'run_passed':status['status']=='passed','54_queries':len(queries)==54,
      '162_correct_answers':len(answers)==162 and all(r['passed'] for r in answers),
      '810_timings':len(counts)==162 and set(counts.values())=={5},
      '162_warmups':len(warm)==162 and set(warm.values())=={1},
      'query_dates_unused_before':not ({q['start_utc'] for q in queries}&{q['start_utc'] for q in oldq}),
      'frozen_plan_matches':c.digest(ROOT/'plan_frozen.md')==protocol['plan_sha256'],
      'frozen_config_matches':c.digest(Path('config/alignment_fresh_dates.json'))==protocol['config_sha256'],
      'runner_matches':c.digest(Path('code/run_alignment_fresh_dates.py'))==protocol['script_sha256'],
      'layouts_unchanged':all(c.digest(Path(v['path']))==v['file_sha256'] for v in layouts.values())}
    assert all(checks.values()),checks
    c.save_json(ROOT/'artifact_verification.json',checks)
    stats=[]
    for kind in ['Q1','Q2']:
        for name in ORDER:
            selected=[r for r in rows if r['kind']==kind and r['layout']==name and r['phase']=='measured']
            nonempty=[r for r in selected if r['count']>0]
            group=[r for r in diag if r['kind']==kind and r['layout']==name and r['matching_rows']>0]
            stats.append({'kind':kind,'layout':name,'mean_ms':statistics.mean(r['elapsed_ms'] for r in selected),
              'nonempty_mean_ms':statistics.mean(r['elapsed_ms'] for r in nonempty),
              'candidate_groups':statistics.mean(r['candidate_groups'] for r in group),
              'matching_groups':statistics.mean(r['groups_with_matching_rows'] for r in group),
              'false_positive_groups':statistics.mean(r['false_positive_groups'] for r in group)})
    get=lambda k,n:next(r for r in stats if r['kind']==k and r['layout']==n)
    effects={k:100*(1-get(k,'station_aligned')['mean_ms']/get(k,'station_first')['mean_ms']) for k in ['Q1','Q2']}
    summary={'stats':stats,'latency_reduction_percent':effects,'dates':protocol['config']['start_dates_utc'],
      'build_script_sha256':c.digest(Path(__file__)),'scope':'new query dates; same historical dataset and machine'}
    c.save_json(ROOT/'summary.json',summary);c.save_csv(ROOT/'class_summary.csv',stats)
    figs=ROOT/'figures';figs.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    rng=random.Random(20261115)
    for mode in ([] if report_only else ['latency','groups']):
        fig,axes=plt.subplots(1,2,figsize=(11,4.6))
        for ax,k in zip(axes,['Q1','Q2']):
            if mode=='latency':
                vals=[get(k,n)['mean_ms'] for n in ORDER]
                bars=ax.bar(range(3),vals,color=COLORS,alpha=.7);ax.bar_label(bars,fmt='%.3f',padding=3)
                for i,n in enumerate(ORDER):
                    dots=[r['mean_ms'] for r in query_summary if r['kind']==k and r['layout']==n]
                    ax.scatter([i+rng.uniform(-.1,.1) for _ in dots],dots,s=16,color=COLORS[i],edgecolors='white',linewidths=.25)
                ax.set_ylabel('Mean warm latency (ms)')
            else:
                match=[get(k,n)['matching_groups'] for n in ORDER];false=[get(k,n)['false_positive_groups'] for n in ORDER]
                ax.bar(range(3),match,color='#147d83',label='Groups with matching rows')
                ax.bar(range(3),false,bottom=match,color='#d6a452',label='Candidates without matches');ax.legend(fontsize=8)
                ax.set_ylabel('Mean groups per nonempty query')
            ax.set_xticks(range(3),LABELS,fontsize=8);ax.set_title(k);ax.grid(axis='y',alpha=.15)
        fig.suptitle('Unchanged layouts, previously unused starts: 2024-06-15 and 2024-11-15',fontsize=13)
        note='Bars: class mean; dots: per-query means over five warm executions.' if mode=='latency' else 'Metadata candidates and independent Arrow inspection; not DuckDB disk I/O.'
        fig.text(.5,.015,note,ha='center',fontsize=9);fig.tight_layout(rect=(0,.05,1,.93))
        for ext in ['png','pdf']:fig.savefig(figs/f'fresh_{mode}.{ext}',dpi=160)
        plt.close(fig)
    table=['| 查询 | 原站点优先 ms | 边界对齐 ms | 时间优先 ms | 相对原站点优先的耗时下降 |','|---|---:|---:|---:|---:|']
    for k in ['Q1','Q2']:table.append('| '+k+' | '+' | '.join(f"{get(k,n)['mean_ms']:.3f}" for n in ORDER)+f" | {effects[k]:.2f}% |")
    table='\n'.join(table)
    detail=f'''# 新日期验证结果

在测量前锁定 2024-06-15、2024-11-15 两个新起始日，与之前全部性能查询的起始日不相交。布局和参数未修改。54 条查询、162 次答案检查、810 次计时、162 次额外预热全部完成。3 条 Q1 为空结果，保留在主要分析中。

{table}

![新日期耗时](../results/alignment_fresh_v1/figures/fresh_latency.png)

在新查询日期上，边界对齐的平均耗时仍比原站点优先更低，但下降幅度小于探索轮的 16.65% 和 23.60%；时间优先的两类查询平均耗时仍更低。排除空结果后，Q1 的三种布局平均耗时分别为 {get('Q1',ORDER[0])['nonempty_mean_ms']:.3f}、{get('Q1',ORDER[1])['nonempty_mean_ms']:.3f}、{get('Q1',ORDER[2])['nonempty_mean_ms']:.3f} ms，改善并非只由空查询产生。

![新日期候选组](../results/alignment_fresh_v1/figures/fresh_groups.png)

在有匹配记录的 Q1 中，原站点优先布局每条查询平均有 {get('Q1',ORDER[0])['false_positive_groups']:.3f} 个候选行组实际没有匹配记录，对齐后为 {get('Q1',ORDER[1])['false_positive_groups']:.3f}。候选行组数由元数据推算，实际匹配情况由 Arrow 额外读取后核对；这两项均不是 DuckDB 实际读取量。所有方法使用同一份历史数据和同一硬件，只更换查询起始日，因此这不是在独立新数据集上的验证。每条查询五次计时，也不足以证明方案普遍最优或性能差异具有统计显著性。

原始记录见 [measurements.csv](../results/alignment_fresh_v1/measurements.csv)，运行前确定的实验条件见 [protocol.json](../results/alignment_fresh_v1/protocol.json)，检查见 [artifact_verification.json](../results/alignment_fresh_v1/artifact_verification.json)。运行命令：`python code/run_alignment_fresh_dates.py --run-id fresh_replication`。使用新的运行 ID 将结果另存，不覆盖旧证据；本报告与图表可用 `python code/build_final_report.py` 从保存结果重新生成，无需重新计时。
'''
    Path('report/11_fresh_dates_results.md').write_text(detail,encoding='utf-8')
    final_report(table,get,effects)
    print(json.dumps({'checks':checks,'effects_percent':effects,'stats':stats},ensure_ascii=False))

def final_report(table,get,effects):
    text=f'''# 浮标时序 Parquet 布局中站点边界对齐的效益与代价

**海洋数据挖掘课程大作业实验报告**

**公开仓库：https://github.com/wzyonepp/ocean-data-mining**  
**AI 记录：[大作业ai对话记录（补充问答）](../ai_logs/02_研究过程补充问答.md)**  
日期：2026 年 11 月 15 日（香港时间）。提交人姓名、学号：提交时填写。

## 摘要

本实验从第二章“Parquet 排序与行组跳过”出发，研究浮标时序数据中站点优先和时间优先的取舍。在 8 个 NOAA NDBC 站点、2023—2024 年共 713,823 条非缺测水温记录上，先完成三种排序布局的对照，发现时间优先在两类查询中的平均耗时均更低；根据查询类型比例选择布局，也没有比始终使用时间优先进一步缩短耗时。随后通过独立读取行组，发现按固定行数划分行组时，部分行组跨越站点边界；各列的范围统计无法排除其中实际没有匹配记录的行组。扩展方案保持站点优先行序，将行组在站点边界处重新开始。在已测试的查询上复测后观察到部分改进，再用预先锁定的两个新起始日期验证：相对原站点优先，单站点与跨站点查询平均耗时分别下降 {effects['Q1']:.2f}% 和 {effects['Q2']:.2f}%，时间优先在这两类查询中的平均耗时仍更低。对齐增加 4 个行组与 1,936 字节文件体积。报告分析了耗时改善的可能机制和额外代价，同时列出没有改善的查询及结论的适用范围。

## 1. 研究问题与边界

课程第三讲指出，列式格式提供读取基础，排序、分区和合并决定数据跳过是否有效。本课题仅研究文件内的排序及后续的站点边界对齐，不建设湖仓平台，不比较分区算法、空间索引或预测模型。

初始问题是：相同数据按 `(station_id, observation_time)` 或 `(observation_time, station_id)` 排列，分别适合什么查询？扩展问题是：保持第一种行序不变，让新站点从新的行组开始，能否减少实际没有匹配记录的候选行组、缩短查询耗时，又会增加多少开销？

本实验的贡献是针对海洋浮标数据发现具体问题、修改分组规则，并在相同条件下进行对照验证。排序、聚集、按站点分组和根据查询需求优化布局，都是已有思路。

## 2. 相关资料与既有方法

Parquet 按行组组织数据，每个行组内部按列存储，并在文件末尾保存描述文件结构和各行组的信息（footer，文件尾部元数据）[1]。DuckDB 读取 Parquet 时，可以只读取查询需要的列，并利用各列的最小值、最大值（min/max）排除不可能包含匹配记录的行组[2]。尚不能被这些统计信息排除的行组，本文称为“候选行组”；候选行组中也可能没有实际匹配的记录。排序通常能缩小各组的数值或时间范围，使无关行组更容易被跳过[3]。PyArrow 的 `sorting_columns` 只描述顺序，不执行排序，因此本实验先实际重排记录再写入[4]。

根据查询需求设计数据布局，已有 Qd-tree 等研究[5]。近期对开放列式格式的研究还强调编码、解码、缓存和执行接口的共同影响[6]。因此，不能把“按查询需求选布局”直接算成新算法，也不能将耗时差异全部归因于候选行组数量。本实验聚焦于可以逐组检查的小范围对照，不复现完整的学习型布局优化框架。

## 3. 数据来源与处理

数据来自 NOAA NMFS SWFSC ERD 的 ERDDAP 数据集 `cwwcNDBCMet`。该数据集对 NDBC 观测进行了标准化、重整和少量编辑[7]。站点为 41001、41002、41004、41008、41009、41010、41013、41025，每站分别取得 2023、2024 年三个字段 `station,time,WTMP`，共 16 个 CSV。

共下载 734,800 条记录，其中水温有效记录为 713,823 条，缺测记录为 20,977 条；没有站点和观测时间均相同的重复记录。处理时统一剔除 NaN、无穷值及提供方标记的缺测水温，不插值补齐，也不通过复制记录扩大数据规模。`station_id` 保留字符串，观测时间为 UTC 微秒时间戳，水温为摄氏度 float64。浮标传感器水温不等同于卫星皮肤温度；实际传感器深度应参考站点说明。

各站点的观测时间覆盖不均，部分查询没有匹配记录。实验保留预先选定的这些查询，并额外检查排除空结果后结论是否一致。`AVG(sst)` 是匹配观测记录的简单平均，不用于估计海域面积加权温度。逐文件 URL、取得时间、SHA-256 和缺测统计见 [数据清单](../results/data_screening_manifest.json)。

## 4. 实验设计与可复现性

共同条件：Python 3.12.14、PyArrow 26.0.1、DuckDB 2.0.0，单查询线程、UTC、一个不分区文件、ZSTD 级别 3 压缩、站点列使用字典编码、开启行组统计、关闭页索引（page index）、每组最多 16,384 行。环境是单机 Linux，容器内存上限 8 GiB，CPU 配额约 2 核。固定参数见 [配置](../config/pilot_v1.json)，依赖见 [requirements-formal.txt](../requirements-formal.txt)。

Q1 指定站点，时间窗口为 1、7、30 天；Q2 不限制站点，窗口为 1 小时、1、7 天，时间范围均包含起点、不包含终点，返回记录数 COUNT 和平均水温 AVG。每条查询在每种布局上先与基准表的结果核对，再执行一次不计时的预热和五次计时。使用固定随机种子打乱查询顺序，并轮换三种布局的执行顺序。计时含执行、绑定、计划和结果提取，不包含布局构建和诊断。完整读取文件和正确性检查已使部分数据进入缓存，因而本研究测量的是预热后的查询表现，不代表首次从磁盘读取时的性能。

| 阶段 | 查询 | 答案检查 | 计时 | 用途 |
|---|---:|---:|---:|---|
| 预跑 | 12 × 3 布局 | 36 | 180 | 正确性与可行性 |
| 原始正式对照 | 108 × 3 布局 | 324 | 1,620 | 排序比较、调整及验证 |
| 对齐探索复测 | 108 条 + 全表 Q0，3 布局 | 327 | 1,635 | 使用已测试查询分析改动效果 |
| 两个新日期验证 | 54 × 3 布局 | 162 | 810 | 不修改方法的新查询复核 |

每个阶段都在同一轮实验中重新测量相应的对照布局，避免把不同轮次的耗时直接相减来计算改进。各布局返回的记录数均一致，平均水温按绝对误差 1e-9 或相对误差 1e-12 的容差核对。将各布局的数据读回并按相同规则排序后，数据内容的校验值一致；边界对齐布局还与原站点优先布局逐行核对，确认行序和值完全相同。

## 5. 原始实验与问题诊断

原始布局为随机、站点优先、时间优先，各 44 个行组。108 条正式查询分为 54 条调整查询和 54 条验证查询。调整日期为 2023-02-01、2023-08-01；验证日期为 2024-02-01、2024-08-01。验证集 Q1 的平均耗时分别为随机 27.187、站点优先 4.261、时间优先 2.986 ms；Q2 的平均耗时为 24.388、8.699、2.453 ms。

布局选择只使用调整集的结果：设 Q1 在全部查询中的比例为 p，先对 Q1、Q2 两类查询的平均耗时分别归一化，再按比例加权比较。测试的 11 个 p 值均选择时间优先，选择结果在验证计时前固定。在验证集中，时间优先的两类查询平均耗时也都更低，因此这条选择规则没有优于始终使用时间优先。比例曲线由已有单条查询的计时加权估算，没有实际执行 11 套混合查询序列。

独立检查发现，固定行数切组会在两个站点的交界处混合记录。由于每个站点内部的时间重新从早到晚排列，边界组可能覆盖很宽的时间段。逐列统计保留了站点范围和时间范围，却没有记录两者的联合关系，因而可能无法排除零匹配的组。

例如预跑的 41002 单日查询中，原站点优先保留 3 个候选组，但实际只有 1 个组含匹配行。正式对照的非空 Q1 查询平均存在 1.714 个实际没有匹配记录的候选行组。这些统计由 Arrow 额外读取各行组并逐条核对得到；实验没有跟踪 DuckDB 实际读取了哪些行组或多少字节。

{contribution_section()}

## 7. 使用预先确定的新日期验证

在不改变布局或参数的前提下，固定 2024-06-15、2024-11-15 两个此前没有计时过的起始日。8 站点 × 3 窗口 × 2 日期产生 48 条 Q1；3 窗口 × 2 日期产生 6 条 Q2，共 54 条、810 次计时。这两个起始日均未用于之前的性能查询。162 次结果核对全部通过，3 条没有匹配记录的 Q1 仍保留在统计中。

{table}

![新日期耗时](../results/alignment_fresh_v1/figures/fresh_latency.png)

对齐相对原站点优先在新日期上继续保持改善，但幅度小于探索轮。正式结论采用新日期验证的结果。时间优先在两类查询中的平均耗时依然更低。

排除空结果后，Q1 的平均耗时为原站点优先 {get('Q1',ORDER[0])['nonempty_mean_ms']:.3f}、对齐 {get('Q1',ORDER[1])['nonempty_mean_ms']:.3f}、时间优先 {get('Q1',ORDER[2])['nonempty_mean_ms']:.3f} ms，说明平均耗时的改善方向不变。

![新日期行组核查](../results/alignment_fresh_v1/figures/fresh_groups.png)

在新日期有匹配记录的 Q1 中，原站点优先布局每条查询平均有 {get('Q1',ORDER[0])['false_positive_groups']:.3f} 个候选行组实际没有匹配记录，对齐后为 0；本轮有匹配记录的 Q2 也未发现这种情况。不过，探索轮的 Q2 在对齐后仍出现过这种行组。这表明，即使行组不再跨越站点，站点内部观测时间的间断仍可能使范围统计保留没有匹配记录的行组，不能据本轮结果断言这种情况已彻底消除。

{exception_section()}

## 8. 改进、代价与局限

### 8.1 改进效果

边界对齐减少了实际没有匹配记录的候选行组；新日期验证中，两类查询的平均耗时均低于原站点优先布局。不过，时间优先的两类查询平均耗时仍然更低，且并非每条查询都因对齐而变快，具体结果见第 7 节。

### 8.2 额外代价

| 文件与行组指标 | 原站点优先 | 边界对齐 | 时间优先 |
|---|---:|---:|---:|
| 行组数 | 44 | 48 | 44 |
| 不足行数上限的尾部行组 | 1 | 8 | 1 |
| 最小行组行数 | 9,311 | 1,669 | 9,311 |
| 文件字节数 | 2,679,571 | 2,681,507 | 875,334 |
| 文件尾部元数据（footer）字节数 | 14,979 | 16,248 | 14,866 |

对齐相对原站点优先增加 4 组、1,936 字节（约 0.072%）文件体积，以及 1,269 字节的文件尾部元数据。探索轮还执行了不带筛选条件的全表查询 Q0。按原站点优先、边界对齐、时间优先的顺序，五次查询的平均耗时分别为 8.362、8.500、8.444 ms；中位数为 8.850、8.363、8.289 ms，均值与中位数的变化方向不同，现有测量不足以确认边界对齐是否会持续增加全表扫描耗时。

![文件与行组的额外代价](../results/alignment_v1/figures/alignment_costs.png)

本节测量了行组数量、文件大小、尾部元数据大小和一条全表扫描查询的耗时。生成新布局、重写已有文件和日常维护的额外时间与资源消耗，尚未系统测量，因此不能仅凭文件增大约 0.072% 就认为整体代价很小。

相同设置下，时间优先布局压缩后的文件明显更小。因此排序和分组的总体影响包含压缩、解码和跳过等因素，不能将全部提速归因于候选组减少。根据元数据推算的候选行组数、用 Arrow 核对的实际含匹配记录行组数，以及 DuckDB 实际读取量，是不同指标。跨查询累计没有匹配记录的行组时，同一行组可能被多条查询重复计数，累计值不代表不同的物理行组个数。

### 8.3 实验局限

实验只覆盖 8 个站点、同一份历史数据、两个新查询起始日、固定的行组行数上限，以及单机预热缓存下每条查询五次计时。新查询日期并不等于新数据集。实验也没有增加行组数量相同的对照方案，因而无法单独区分边界变化和组数变化的影响。约 10% 的改善表示整套策略在当前条件下对两类查询平均耗时的影响，不能全部归因于边界变化本身。\n\n此外，本实验没有验证未预热缓存、并发查询或不同硬件下的表现，也没有证明每条查询都更快，或性能差异具有统计显著性。新日期验证前没有修改策略；如果后续继续改动，应另外预留未测试的查询进行验证。

## 9. 结论

在本实验中，时间优先是总体表现更好的对照布局，根据查询类型比例选择布局没有带来进一步改进。针对固定行数分组可能保留无匹配行组的问题，站点边界对齐在保持数据、行序和写入设置不变的条件下，减少了实际没有匹配记录的候选行组。使用预先确定的新日期验证时，Q1、Q2 的平均耗时相对原站点优先均下降约 10%。代价是行组和元数据增多，文件大小略有增加；现有全表查询测量不足以判断是否会持续增加扫描耗时。

这一结果支持在本实验场景下采用边界对齐来改进原站点优先布局，但不说明它是通用的最佳布局，也不代表首次提出这种分组思路。

## 10. AI 协作记录、复现与提交核查

工作包括课程解读、选题、资料与数据筛查、对照实验、诊断、扩展、新日期验证和报告整理。AI 协助资料整理、实现与排错、计算和作图。仓库当前保留的《大作业ai对话记录》是在研究完成后，根据用户确认的 14 项提纲集中编写的补充问答，包含代码示例、结果分析和证据链接。旧的自动对话记录已从当前版本移除；现有补充问答不包含完整历史聊天过程，不能替代作业要求中的无删节完整对话记录。

按指定版本安装依赖后，先恢复输入数据，再运行实验脚本。仓库不保存原始 CSV 和 Parquet 文件，而是提供数据来源、SHA-256 校验值和恢复工具。如果上游历史数据发生修订、无法通过校验，应记录为新数据版本，不直接替换原实验输入。

```bash
python -m pip install -r requirements-formal.txt
python code/restore_alignment_inputs.py
python code/run_alignment_fresh_dates.py --run-id fresh_replication
```

恢复脚本按已提交快照重建原始与对齐布局，并验证文件 SHA-256，不覆盖已提交结果清单。使用新的运行 ID 将结果另存，保留原始证据；如需重跑探索轮，可单独运行 `python code/run_alignment_extension.py --run-id alignment_replication`。报告和图表可用 `python code/build_final_report.py` 根据保存结果重新生成，无需重跑 SQL。

数据与结果入口：[原始正式结果](07_formal_results.md)、[探索扩展](09_alignment_results.md)、[新日期验证](11_fresh_dates_results.md)、[新日期原始计时](../results/alignment_fresh_v1/measurements.csv)、[验证检查](../results/alignment_fresh_v1/artifact_verification.json)。姓名、学号和学校要求的版式在提交时填写与核对，技术结果保留原始证据。

## 参考资料

[1] Apache Parquet, File Format. https://parquet.apache.org/docs/file-format/  
[2] DuckDB, Reading and Writing Parquet Files. https://duckdb.org/docs/2.0/data/parquet/overview  
[3] DuckDB, Parquet Tips. https://duckdb.org/docs/2.0/data/parquet/tips  
[4] Apache Arrow, pyarrow.parquet.write_table. https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_table.html  
[5] Yang Z., et al. Qd-tree: Learning Data Layouts for Big Data Analytics. SIGMOD 2020. https://doi.org/10.1145/3318464.3389770  
[6] Liu C., Pavlenko A., Interlandi M., Haynes B. Data formats in analytical DBMSs: performance trade-offs and future directions. The VLDB Journal 34, 30 (2025). https://doi.org/10.1007/s00778-025-00911-1  
[7] NOAA ERDDAP, NDBC Standard Meteorological Buoy Data, cwwcNDBCMet. https://upwell.pfeg.noaa.gov/erddap/info/cwwcNDBCMet/index.html  
课程依据：用户提供《第二章 第3讲 列式布局与AI数据底座》，文件页序第4、6、7、9页。资料查阅过程见 [资料调研记录](02_literature_review.md)。
'''
    Path('report/实验报告.md').write_text(text,encoding='utf-8')

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-only',action='store_true',help='Update text and derived statistics without regenerating figures')
    args=parser.parse_args();build(args.report_only)
