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

ROOT=Path('results/alignment_fresh_v1')
ORDER=['station_first','station_aligned','time_first']
LABELS=['Station fixed','Station aligned','Time first']
COLORS=['#ce8f39','#346ca3','#147d83']

def build():
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
    for mode in ['latency','groups']:
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
    table=['| 查询 | 原站点优先 ms | 边界对齐 ms | 时间优先 ms | 相对原站点下降 |','|---|---:|---:|---:|---:|']
    for k in ['Q1','Q2']:table.append('| '+k+' | '+' | '.join(f"{get(k,n)['mean_ms']:.3f}" for n in ORDER)+f" | {effects[k]:.2f}% |")
    table='\n'.join(table)
    detail=f'''# 新日期验证结果

在测量前锁定 2024-06-15、2024-11-15 两个新起始日，与之前全部性能查询的起始日不相交。布局和参数未修改。54 条查询、162 次答案检查、810 次计时、162 次额外预热全部完成。3 条 Q1 为空结果，保留在主要分析中。

{table}

![新日期耗时](../results/alignment_fresh_v1/figures/fresh_latency.png)

收益在新查询日期上保持同方向，但幅度小于探索轮的 16.65% 和 23.60%；时间优先的类型均值仍更低。排除空结果后，Q1 的三种布局平均耗时分别为 {get('Q1',ORDER[0])['nonempty_mean_ms']:.3f}、{get('Q1',ORDER[1])['nonempty_mean_ms']:.3f}、{get('Q1',ORDER[2])['nonempty_mean_ms']:.3f} ms，改善并非只由空查询产生。

![新日期候选组](../results/alignment_fresh_v1/figures/fresh_groups.png)

非空 Q1 的原站点优先平均无匹配候选组为 {get('Q1',ORDER[0])['false_positive_groups']:.3f}，对齐后为 {get('Q1',ORDER[1])['false_positive_groups']:.3f}。候选组是元数据估算，联合匹配由额外 Arrow 读取核对，均不是实测 DuckDB I/O。所有方法使用同一历史数据和硬件，仅查询日期是新日期；不称为跨独立数据集验证，五次重复不支撑普遍最优或统计显著性结论。

原始记录见 [measurements.csv](../results/alignment_fresh_v1/measurements.csv)，冻结条件见 [protocol.json](../results/alignment_fresh_v1/protocol.json)，检查见 [artifact_verification.json](../results/alignment_fresh_v1/artifact_verification.json)。运行命令：`python code/run_alignment_fresh_dates.py --run-id fresh_replication`。新运行 ID 不覆盖旧证据；本报告与图表可用 `python code/build_final_report.py` 从保存结果重新生成，无需重新计时。
'''
    Path('report/11_fresh_dates_results.md').write_text(detail,encoding='utf-8')
    final_report(table,get,effects)
    print(json.dumps({'checks':checks,'effects_percent':effects,'stats':stats},ensure_ascii=False))

def final_report(table,get,effects):
    text=f'''# 浮标时序 Parquet 布局中站点边界对齐的效益与代价

**海洋数据挖掘课程大作业实验报告**

**公开仓库：https://github.com/wzyonepp/ocean-data-mining**  
**AI 协作记录：[指定范围对话记录](../ai_logs/01_课程解读到实验预跑.md)**  
日期：2026 年 11 月 15 日（香港时间）。提交人姓名、学号：提交时填写。

## 摘要

本实验从第二章“Parquet 排序与行组跳过”出发，研究浮标时序数据中站点优先和时间优先的取舍。在 8 个 NOAA NDBC 站点、2023—2024 年共 713,823 条非缺测水温记录上，先完成三种排序布局的对照，发现时间优先在既定查询类型的均值上占优，按查询比例选择未比固定时间优先增加收益。随后通过独立读取行组，定位固定切组在站点边界混合记录、导致逐列范围保留无联合匹配组的问题。扩展方案保持站点优先行序，将行组在站点边界处重新开始。探索复测得到局部收益，再用预先锁定的两个新起始日期验证：相对原站点优先，单站点与跨站点查询平均耗时分别下降 {effects['Q1']:.2f}% 和 {effects['Q2']:.2f}%，时间优先仍更快。对齐增加 4 个行组与 1,936 字节文件体积。实验提供了收益、机制与成本的证据，同时保留未获益和适用边界。

## 1. 研究问题与边界

课程第三讲指出，列式格式提供读取基础，排序、分区和合并决定数据跳过是否有效。本课题仅研究文件内的排序及后续的站点边界对齐，不建设湖仓平台，不比较分区算法、空间索引或预测模型。

初始问题是：相同数据按 `(station_id, observation_time)` 或 `(observation_time, station_id)` 排列，分别适合什么查询？扩展问题是：保持第一种行序不变，重置站点之间的行组边界，能否减少无效候选组并改善耗时，增加多少开销？

本实验的贡献限定为海洋浮标场景中的问题诊断、分组改动和受控验证，不声称排序、聚集、站点分组或工作负载优化的思想首创。

## 2. 相关资料与既有方法

Parquet 将列块组织为行组，并保存末尾元数据[1]。DuckDB 可将筛选与投影下推到 Parquet 读取，利用 min/max 排除不可能匹配的组[2]；范围紧密的有序排列更有利于跳过[3]。PyArrow 的 `sorting_columns` 只描述顺序，不执行排序，因此本实验先实际重排记录再写入[4]。

工作负载驱动布局已有 Qd-tree 等研究[5]。近期对开放列式格式的研究还强调编码、解码、缓存和执行接口的共同影响[6]。因此，不能把“按查询需求选布局”直接算成新算法，也不能将耗时差异全部归因于候选行组数量。本实验采用小范围的可解释对照，而不复现完整学习布局框架。

## 3. 数据来源与处理

使用 NOAA NMFS SWFSC ERD 的 ERDDAP `cwwcNDBCMet`，是对 NDBC 数据标准化、重整和轻度编辑后的版本[7]，不是完全未经处理的原始观测。站点为 41001、41002、41004、41008、41009、41010、41013、41025，每站分别取得 2023、2024 年三个字段 `station,time,WTMP`，共 16 个 CSV。

下载共 734,800 条记录，水温非缺测 713,823 条、缺测 20,977 条；重复站点—时间键为 0。统一剔除非有限水温及提供方缺测标记，不插值、不复制扩容。`station_id` 保留字符串，观测时间为 UTC 微秒时间戳，水温为摄氏度 float64。浮标传感器水温不等同于卫星皮肤温度；实际传感器深度应参考站点说明。

各站覆盖不均，查询可能为空；预先确定的空查询保持不变并另做非空敏感性分析。`AVG(sst)` 是匹配观测记录的简单平均，不用于估计海域面积加权温度。逐文件 URL、取得时间、SHA-256 和缺测统计见 [数据清单](../results/data_screening_manifest.json)。

## 4. 实验设计与可复现性

共同条件：Python 3.12.14、PyArrow 26.0.1、DuckDB 2.0.0，单查询线程、UTC、一个不分区文件、ZSTD 级别 3、站点列字典编码、开启行组统计、关闭 page index、每组最多 16,384 行。环境是单机 Linux，容器内存上限 8 GiB，CPU 配额约 2 核。固定参数见 [配置](../config/pilot_v1.json)，依赖见 [requirements-formal.txt](../requirements-formal.txt)。

Q1 指定站点，时间窗口为 1、7、30 天；Q2 不限制站点，窗口为 1 小时、1、7 天，均为半开区间，返回 COUNT 和 AVG。每个查询—布局组合先核对基表答案，再额外预热一次、计时五次，固定种子打乱查询顺序并轮换布局顺序。计时含执行、绑定、计划和结果提取，不包含布局构建和诊断。完整读回和正确性检查已预热缓存，本研究不测冷磁盘性能。

| 阶段 | 查询 | 答案检查 | 计时 | 用途 |
|---|---:|---:|---:|---|
| 预跑 | 12 × 3 布局 | 36 | 180 | 正确性与可行性 |
| 原始正式对照 | 108 × 3 布局 | 324 | 1,620 | 排序比较、调整及验证 |
| 对齐探索复测 | 108 条 + 全表 Q0，3 布局 | 327 | 1,635 | 已见查询上的改动分析 |
| 两个新日期验证 | 54 × 3 布局 | 162 | 810 | 不修改方法的新查询复核 |

各阶段均重新同时测量其对照，不将不同运行中的毫秒数直接相减当作提速。所有答案计数一致，均值采用绝对误差 1e-9 或相对误差 1e-12 检查。读回规范排序后的逻辑校验值相同；扩展布局还要求与原站点优先的行序、值完全一致。

## 5. 原始实验与问题诊断

原始布局为随机、站点优先、时间优先，各 44 个行组。108 条正式查询分为 54 条调整查询和 54 条验证查询。调整日期为 2023-02-01、2023-08-01；验证日期为 2024-02-01、2024-08-01。验证集 Q1 均值分别为随机 27.187、站点优先 4.261、时间优先 2.986 ms；Q2 为 24.388、8.699、2.453 ms。

只根据调整集，按 Q1 比例 p 对两个类别均值分别归一、加权，在 11 个 p 值上均选择时间优先；在验证集也未出现类别均值的排序切换。选择结果在验证计时前冻结。这个候选规则没有比固定时间优先增加收益，不能包装成已经成功的动态优化。比例曲线由单查询计时加权估算，没有另行回放 11 套混合查询序列。

独立检查发现，固定行数切组会在两个站点的交界处混合记录。由于每个站点内部的时间重新从早到晚排列，边界组可能覆盖很宽的时间段。逐列统计保留了站点范围和时间范围，却没有记录两者的联合关系，因而可能无法排除零匹配的组。

例如预跑的 41002 单日查询中，原站点优先保留 3 个候选组，但实际只有 1 个组含匹配行。正式对照的非空 Q1 查询平均存在 1.714 个无联合匹配候选组。这些统计是额外 Arrow 读取核对的结果，不是 DuckDB 实际 I/O 跟踪。

## 6. 原创探索点的具体拆解

### 6.1 问题与改动

针对“固定切组跨站点，扩大独立范围统计”的具体问题，新增站点边界对齐。保持站点优先的全局行序，对每个站点独立按最多 16,384 行写入行组，最后仍写入同一个 Parquet 文件。它不增加站点目录分区，不复制数据，不改变查询 SQL，也不改变数据模式、压缩算法和行组上限。

过程可表示为：排序后取一个站点的连续记录 → 按上限切完整组 → 保留该站点尾部短组 → 下一站点从新行组开始。所有组的站点 min=max，文件整体仍按站点、时间有序。

### 6.2 与原方案的差别及代价

这一步改变了分组边界，已超出初始“只改变排序”的实验，故单独命名、保存方案并重新测量。原站点优先有 44 组、7 个跨站点组；新布局有 48 组、0 个跨站点组。更细的分组可能改善范围统计，但也带来更多尾部短组和元数据，需作为成本记录，不能强行保持行组总数相同。

新增方法采用 ParquetWriter 分批写入。为检查接口差异，先用同一接口按原固定边界重建原站点优先，要求生成文件与原文件逐字节相同；该检查通过。新文件完整读回也与原站点优先行序和值完全相同。

### 6.3 探索结果与证据边界

在已见的 108 条查询上重新交错测量，原验证日期组 Q1 均值从 3.392 降为 2.827 ms（下降 16.65%），Q2 从 7.917 降为 6.049 ms（下降 23.60%）；同轮时间优先分别为 2.715 和 2.366 ms，仍更低。该轮被明确标为探索性复测，而非新的盲验证。

本课程实验的探索贡献在于：依据具体异常提出局部改动、检查写入控制和逻辑一致性、将范围误保留减少与耗时及成本一起验证。站点聚集和边界切组本身属于已有设计思路；本报告不把它们描述为全球首创，也不捏造学生独立提出或未发生的思考过程。

## 7. 预先锁定新日期的验证

在不改变布局或参数的前提下，固定 2024-06-15、2024-11-15 两个此前没有计时过的起始日。8 站点 × 3 窗口 × 2 日期产生 48 条 Q1；3 窗口 × 2 日期产生 6 条 Q2，共 54 条、810 次计时。新日期与之前全部性能查询起始日期不相交。162 次基表答案检查全部通过，3 条空 Q1 保留。

{table}

![新日期耗时](../results/alignment_fresh_v1/figures/fresh_latency.png)

对齐相对原站点优先在新日期上继续保持改善，但幅度小于探索轮。不能用探索轮的较高收益替代新日期结果。时间优先依然有更低的类别均值。

排除空结果后，Q1 均值为原站点优先 {get('Q1',ORDER[0])['nonempty_mean_ms']:.3f}、对齐 {get('Q1',ORDER[1])['nonempty_mean_ms']:.3f}、时间优先 {get('Q1',ORDER[2])['nonempty_mean_ms']:.3f} ms，方向不由空结果单独决定。

![新日期行组核查](../results/alignment_fresh_v1/figures/fresh_groups.png)

新日期非空 Q1 中，原站点优先的平均无匹配候选组为 {get('Q1',ORDER[0])['false_positive_groups']:.3f}，对齐后为 0；本轮非空 Q2 对齐后也为 0。探索轮 Q2 对齐后曾有误保留，说明即使消除跨站边界，站点内部时间间断仍可能形成范围误保留。不得将本轮为 0 推广为任意查询均为 0。

## 8. 收益、成本与局限

| 物理指标 | 原站点优先 | 站点对齐 | 时间优先 |
|---|---:|---:|---:|
| 行组数 | 44 | 48 | 44 |
| 尾部短组 | 1 | 8 | 1 |
| 最小行组行数 | 9,311 | 1,669 | 9,311 |
| 文件字节数 | 2,679,571 | 2,681,507 | 875,334 |
| Footer 字节数 | 14,979 | 16,248 | 14,866 |

对齐相对原站点优先增加 4 组、1,936 字节（约 0.072%）文件体积和 1,269 字节 footer。探索轮无筛选全表 Q0 的五次均值为 8.362、8.500、8.444 ms；中位数为 8.850、8.363、8.289 ms，均值与中位数的变化方向不同，尚不能确认稳定全表扫描开销。

![物理成本](../results/alignment_v1/figures/alignment_costs.png)

相同设置下，时间优先压缩文件显著更小。因此排序和分组的总体影响包含压缩、解码和跳过等因素，不能将全部提速归因于候选组减少。候选组、额外读取的含匹配组与实际引擎 I/O 分开解释。跨查询累计的无匹配组数是查询—行组组合次数，不是独立物理组的数量。

局限包括：仅 8 个站点、同一历史数据、两个新起始日、固定行组上限、单机暖缓存和五次重复；新日期不是新数据集。没有匹配行组数量的额外控制，不能独立拆分对齐与组数变化的全部影响。没有冷缓存、并发或跨硬件验证，也没有证明每条查询均改善或存在统计显著性。改动在本次验证前未调整；若继续修改，需要另留验证查询。

## 9. 结论

本场景中，时间优先是更好的总体基线；按查询比例选择未超过固定时间优先。围绕固定切组的边界误保留问题，站点边界对齐在保持数据、行序和写入设置的条件下，减少了无匹配候选组，并在预先固定的新查询日期上保持了相对原站点优先约 10% 的类型均值收益。它增加了行组与元数据，但文件增长较小；没有成为普遍最佳布局，也没有证明稳定的全表扫描损失。

因此，研究结果应表述为一种场景化、可解释并有成本边界的局部改进，而非通用最优方案或方法首创。

## 10. AI 协作记录、复现与提交核查

工作按课程解读、选题、资料与数据筛查、对照、诊断、扩展、新日期验证及报告整理逐步完成。AI 协助整理资料、实现与排错、计算和作图；对话记录保留实际交互，不补造个人预测或辩论。按用户要求排除指定不记录的轮次及连续解释讨论，范围见日志说明；该记录不是无删节全文，未宣称完全满足“无删节完整记录”的要求。

锁定依赖后，先恢复输入，再运行既有实验脚本。Git 不存储原始 CSV 和 Parquet 本体，提供来源、SHA-256 和恢复工具。若上游历史数据修订而不能匹配，应报告新版本，不静默替换。

```bash
python -m pip install -r requirements-formal.txt
python code/restore_alignment_inputs.py
python code/run_alignment_fresh_dates.py --run-id fresh_replication
```

恢复脚本按已提交快照重建原始与对齐布局，并验证文件 SHA-256，不覆盖已提交结果清单。新运行 ID 保留原始证据；如需重跑探索轮，可单独运行 `python code/run_alignment_extension.py --run-id alignment_replication`。报告和图表可用 `python code/build_final_report.py` 根据保存结果重新生成，无需重跑 SQL。

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

if __name__=='__main__':build()
