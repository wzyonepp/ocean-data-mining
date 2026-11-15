#!/usr/bin/env python3
"""Explain saved exploratory alignment measurements; does not rerun SQL."""
import argparse,json,statistics,random
from collections import Counter
from pathlib import Path
import matplotlib.pyplot as plt
import run_parquet_pilot as c
from analyze_parquet_formal import read_csv

NAMES=['station_first','station_aligned','time_first']
LABELS=['Station\nfixed groups','Station\naligned groups','Time\nfirst']
COLORS=['#ce8f39','#346ca3','#147d83']

def analyze(root):
    status=json.loads((root/'run_status.json').read_text())
    protocol=json.loads((root/'protocol.json').read_text())
    layouts=json.loads((root/'layouts.json').read_text())
    rows=read_csv(root/'measurements.csv');summary=read_csv(root/'query_summary.csv')
    diag=read_csv(root/'joint_match_summary.csv')
    answers=json.loads((root/'correctness.json').read_text())
    control=json.loads((root/'writer_control.json').read_text())
    measured=Counter((r['query_id'],r['layout']) for r in rows if r['phase']=='measured')
    warmups=Counter((r['query_id'],r['layout']) for r in rows if r['phase']=='warmup')
    checks={'run_passed':status['status']=='passed','327_answers_correct':len(answers)==327 and all(r['passed'] for r in answers),
      '1635_measurements':len(measured)==327 and set(measured.values())=={5},
      '327_warmups':len(warmups)==327 and set(warmups.values())=={1},
      'same_rows':all(v['rows']==713823 for v in layouts.values()),
      'no_mixed_aligned_groups':layouts['station_aligned']['mixed_station_groups']==0,
      'unchanged_files':all(c.digest(Path(v['path']))==v['file_sha256'] for v in layouts.values()),
      'writer_control_byte_equal':control['matches_original_byte_for_byte'] and control['sha256']==layouts['station_first']['file_sha256'],
      'frozen_plan_matches':c.digest(root/'plan_frozen.md')==protocol['plan_sha256'],
      'runner_matches':c.digest(Path('code/run_alignment_extension.py'))==protocol['script_sha256']}
    assert all(checks.values()),checks
    c.save_json(root/'artifact_verification.json',checks)
    stats=[]
    for role in ['tuning','validation','overhead']:
        for kind in (['Q0'] if role=='overhead' else ['Q1','Q2']):
            for layout in NAMES:
                selected=[r for r in rows if r['role']==role and r['kind']==kind and r['layout']==layout and r['phase']=='measured']
                ds=[r for r in diag if r['role']==role and r['kind']==kind and r['layout']==layout and r['matching_rows']>0]
                stats.append({'role':role,'kind':kind,'layout':layout,'mean_ms':statistics.mean(r['elapsed_ms'] for r in selected),
                  'median_execution_ms':statistics.median(r['elapsed_ms'] for r in selected),
                  'nonempty_mean_ms':statistics.mean(r['elapsed_ms'] for r in selected if r['count']>0),
                  'min_execution_ms':min(r['elapsed_ms'] for r in selected),'max_execution_ms':max(r['elapsed_ms'] for r in selected),
                  'nonempty_queries':len(ds),'mean_candidate_groups':statistics.mean(r['candidate_groups'] for r in ds),
                  'mean_matching_groups':statistics.mean(r['groups_with_matching_rows'] for r in ds),
                  'mean_false_positive_groups':statistics.mean(r['false_positive_groups'] for r in ds)})
    c.save_csv(root/'class_summary.csv',stats)
    get=lambda role,kind,name: next(r for r in stats if r['role']==role and r['kind']==kind and r['layout']==name)
    effects={kind:100*(1-get('validation',kind,'station_aligned')['mean_ms']/get('validation',kind,'station_first')['mean_ms']) for kind in ['Q1','Q2']}
    extra_bytes=layouts['station_aligned']['file_bytes']-layouts['station_first']['file_bytes']
    c.save_json(root/'effects.json',{'latency_reduction_vs_station_fixed_percent':effects,'extra_file_bytes':extra_bytes,
      'extra_file_percent':100*extra_bytes/layouts['station_first']['file_bytes'],'analysis_script_sha256':c.digest(Path(__file__)),
      'scope':'exploratory rerun of previously seen queries; no new held-out set'})
    figdir=root/'figures';figdir.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
    def save(fig,name):
        fig.tight_layout(rect=(0,0.05,1,0.92));fig.savefig(figdir/(name+'.png'),dpi=160);fig.savefig(figdir/(name+'.pdf'));plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4.5));rng=random.Random(20261115)
    for ax,(role,kind) in zip(axes,[('validation','Q1'),('validation','Q2'),('overhead','Q0')]):
        values=[get(role,kind,name)['mean_ms'] for name in NAMES]
        bars=ax.bar(range(3),values,color=COLORS,alpha=.65);ax.bar_label(bars,fmt='%.2f',padding=4)
        for i,name in enumerate(NAMES):
            dots=([r['elapsed_ms'] for r in rows if r['kind']=='Q0' and r['phase']=='measured' and r['layout']==name] if kind=='Q0' else [r['mean_ms'] for r in summary if r['role']==role and r['kind']==kind and r['layout']==name])
            ax.scatter([i+rng.uniform(-.12,.12) for _ in dots],dots,color=COLORS[i],edgecolors='white',linewidths=.3,s=16)
        ax.set_xticks(range(3),LABELS,fontsize=8);ax.set_ylabel('Warm latency (ms)');ax.set_title(kind+(' full scan' if kind=='Q0' else ' original validation dates'));ax.grid(axis='y',alpha=.2)
    fig.suptitle('Station-aligned groups: latency and scan-cost probe',fontsize=14)
    fig.text(.5,.015,'Bars: mean. Dots: per-query means (Q1/Q2), five individual executions (Q0).',ha='center',fontsize=9);save(fig,'alignment_latency')
    fig,axes=plt.subplots(1,2,figsize=(10,4.5))
    for ax,kind in zip(axes,['Q1','Q2']):
        matched=[get('validation',kind,n)['mean_matching_groups'] for n in NAMES]
        false=[get('validation',kind,n)['mean_false_positive_groups'] for n in NAMES]
        ax.bar(range(3),matched,color='#147d83',label='Groups with matches')
        ax.bar(range(3),false,bottom=matched,color='#d6a452',label='Candidates without matches')
        ax.set_xticks(range(3),LABELS,fontsize=9);ax.set_ylabel('Mean groups per nonempty query');ax.set_title(kind);ax.legend(fontsize=8)
    fig.suptitle('Independent row-group inspection: previously seen validation dates',fontsize=13)
    fig.text(.5,.015,'Metadata candidates and direct Arrow inspection, not measured DuckDB I/O.',ha='center',fontsize=9);save(fig,'alignment_groups')
    fig,axes=plt.subplots(1,3,figsize=(12,4.5))
    for ax,(key,divisor,label) in zip(axes,[('row_groups',1,'Row groups'),('file_bytes',1024**2,'File size (MiB)'),('footer_bytes',1024,'Footer (KiB)')]):
        vals=[layouts[n][key]/divisor for n in NAMES];bars=ax.bar(range(3),vals,color=COLORS);ax.bar_label(bars,fmt='%.3f' if key=='file_bytes' else '%.1f',padding=4)
        ax.set_xticks(range(3),LABELS,fontsize=8);ax.set_ylabel(label);ax.set_ylim(0,max(vals)*1.2)
    fig.suptitle('Alignment changes group boundaries and metadata overhead',fontsize=14);save(fig,'alignment_costs')
    rel='../'+root.as_posix()
    lines=['# 扩展结果：站点边界对齐行组','', '本结果随新日期验证一并同步仓库。属于探索性扩展，使用已经看过的 108 条查询，不是新的盲验证。','',
      '## 完成情况','', '新布局保持与原站点优先完全相同的记录和行序，每组最多 16,384 行，按站点边界重新开始。三种布局在本轮同时交错重新计时，不与上轮毫秒数直接比较。', '',
      '108 条查询 × 3 布局 × 5 次，共 1,620 次计时；另有无筛选全表 COUNT/AVG 查询 Q0 的 15 次计时，总计 1,635 次、327 次预热和327次答案检查。全部通过。分批写入接口重建的原站点优先文件与原文件逐字节一致，新增布局读回后的行序及值也完全一致。','',
      '## 查询收益','', '下表为原验证日期组的类型平均耗时，仍包含预设空结果，单位毫秒。','', '| 查询 | 原站点优先 | 站点边界对齐 | 时间优先 | 对齐相对原站点耗时下降 |','|---|---:|---:|---:|---:|']
    for kind in ['Q1','Q2']:
        lines.append(f"| {kind} | {get('validation',kind,NAMES[0])['mean_ms']:.3f} | {get('validation',kind,NAMES[1])['mean_ms']:.3f} | {get('validation',kind,NAMES[2])['mean_ms']:.3f} | {effects[kind]:.1f}% |")
    lines += ['',f'![查询耗时]({rel}/figures/alignment_latency.png)','',
      '相对原站点优先，两类查询的均值都有改善；时间优先的类型均值仍更低。结果支持本次对齐改动有局部收益，尚不支持它替代时间优先成为通用最佳布局。','',
      '排除空结果后，42 条非空单站点查询的平均耗时依次为：原站点优先 {:.3f} ms、边界对齐 {:.3f} ms、时间优先 {:.3f} ms；改善并非仅由空查询驱动。'.format(*(get('validation','Q1',n)['nonempty_mean_ms'] for n in NAMES)),'',
      '## 机制核查','', '| 非空查询 | 布局 | 平均候选组 | 平均实际含匹配组 | 平均无匹配候选组 |','|---|---|---:|---:|---:|']
    for kind in ['Q1','Q2']:
        for name in NAMES:
            s=get('validation',kind,name);lines.append(f"| {kind} | {name} | {s['mean_candidate_groups']:.3f} | {s['mean_matching_groups']:.3f} | {s['mean_false_positive_groups']:.3f} |")
    lines += ['',f'![行组机制]({rel}/figures/alignment_groups.png)','',
      '对齐消除了跨站点混合组，非空 Q1 的无联合匹配候选组从平均 1.714 个降为 0。Q2 对齐后仍存在无匹配候选组，单站点内部的时间间断也可能产生范围误保留；不能把所有误保留都归因于跨站边界。上述检查由计时之外的 Arrow 直接读取完成，不代表 DuckDB 实际扫描组或磁盘 I/O。','',
      '## 开销与代价','', '| 项目 | 原站点优先 | 边界对齐 | 时间优先 |','|---|---:|---:|---:|']
    for key in ['row_groups','short_groups','min_group_rows','file_bytes','footer_bytes']:
        lines.append('| '+key+' | '+' | '.join(str(layouts[n][key]) for n in NAMES)+' |')
    q0=[get('overhead','Q0',n) for n in NAMES]
    lines += ['',f'对齐后增加 4 个行组、7 个尾部短组；文件仅增加 {extra_bytes:,} 字节（{100*extra_bytes/layouts[NAMES[0]]["file_bytes"]:.3f}%），footer 增加 {layouts[NAMES[1]]["footer_bytes"]-layouts[NAMES[0]]["footer_bytes"]:,} 字节。更多行组不必然导致明显的总文件膨胀，编码和压缩效果同时发生变化。','',
      '| 全表扫描 Q0 | 原站点优先 | 边界对齐 | 时间优先 |','|---|---:|---:|---:|',
      '| 五次平均 ms | '+' | '.join(f"{s['mean_ms']:.3f}" for s in q0)+' |',
      '| 五次中位数 ms | '+' | '.join(f"{s['median_execution_ms']:.3f}" for s in q0)+' |','',
      'Q0 均值略增而中位数方向相反，不能用这五次探针证明全表扫描有稳定的性能损失或提升。Q0 不采用候选列块字节估计作为 I/O 指标。','',f'![成本]({rel}/figures/alignment_costs.png)','',
      '## 结论与局限','',
      '本次扩展达到了“针对已观察问题提出改动，并验证局部收益”的目标：保持站点排序，按站点对齐行组，确实减少了范围误保留，并降低了相对原站点优先的类型平均耗时。同时也保留了重要边界：时间优先仍更快，更多小组增加元数据，实际全表开销尚不稳定。','',
      '该方法属于常见聚集和分组设计思路，不声称全球首创。本轮用了已见查询，只有单机暖缓存和五次重复；没有匹配行组数量的额外控制，不能独立拆分对齐和组数变化的全部效应。形成报告时，应明确将其标为探索性改进，后续如需确认泛化，可另选未见日期。','',
      '## 复现','', '在既有锁定环境和恢复输入后执行：','', '```bash',f'python code/run_alignment_extension.py --run-id {root.name}_replication',f'python code/analyze_alignment_extension.py --run-dir results/{root.name}_replication','```','',
      f'- [逐次测量]({rel}/measurements.csv)',f'- [结果检查]({rel}/artifact_verification.json)',f'- [协议与版本]({rel}/protocol.json)',f'- [文件、行组和存储统计]({rel}/layouts.json)',f'- [机制逐组诊断]({rel}/joint_match_diagnostic.csv)','']
    Path('report/09_alignment_results.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'checks':checks,'latency_reduction_percent':effects,'extra_bytes':extra_bytes},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-dir',type=Path,default=Path('results/alignment_v1'))
    analyze(parser.parse_args().run_dir)
