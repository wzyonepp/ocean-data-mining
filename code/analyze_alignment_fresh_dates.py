#!/usr/bin/env python3
"""Analyze saved fresh-date results; write derived artifacts without SQL or reports.

Run from the repository root. By default, new files go in RUN_DIR/analysis,
leaving the published measurements, checks, summaries and figures untouched.
"""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import random
import statistics

os.environ.setdefault('MPLCONFIGDIR', '/tmp/marine-course-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from analyze_parquet_formal import read_csv
from analyze_query_effects import compute_query_effects, LAYOUTS
from run_parquet_formal import summarize
import run_parquet_pilot as common

LABELS = ['Station fixed', 'Station aligned', 'Time first']
COLORS = ['#ce8f39', '#346ca3', '#147d83']


def validate_run(run_dir, rows, queries, answers, protocol, status):
    config = protocol['config']
    expected = {(q['query_id'], layout) for q in queries for layout in config['layouts']}
    measured = Counter((r['query_id'], r['layout']) for r in rows if r['phase'] == 'measured')
    warm = Counter((r['query_id'], r['layout']) for r in rows if r['phase'] == 'warmup')
    answer_map = {(r['query_id'], r['layout']): r for r in answers}
    query_map = {q['query_id']: q for q in queries}
    prior = []
    for name in ['pilot_v1/pilot_queries.json', 'formal_v1/queries.json', 'alignment_v1/queries.json']:
        prior.extend(json.loads((Path('results') / name).read_text()))
    layouts_path = Path(config['layout_manifest'])
    checks = {
        'run_passed': status['status'] == 'passed',
        '54_unique_queries': len(queries) == len(query_map) == 54,
        'expected_query_classes': Counter(q['kind'] for q in queries) == {'Q1': 48, 'Q2': 6},
        'three_layouts': tuple(config['layouts']) == LAYOUTS,
        '162_correct_answers': len(answers) == len(answer_map) == 162
            and set(answer_map) == expected and all(r['passed'] for r in answers),
        '810_timings': set(measured) == expected
            and set(measured.values()) == {5} and sum(measured.values()) == 810,
        '162_warmups': set(warm) == expected
            and set(warm.values()) == {1} and sum(warm.values()) == 162,
        'only_expected_phases': all(r['phase'] in ('measured', 'warmup') for r in rows),
        'query_dates_unused_before': not ({q['start_utc'] for q in queries}
                                         & {q['start_utc'] for q in prior}),
        'query_dates_match_protocol': {common.timestamp(q['start_utc']) for q in queries}
            == {common.timestamp(d) for d in config['start_dates_utc']},
        'frozen_plan_matches': common.digest(run_dir / 'plan_frozen.md') == protocol['plan_sha256'],
        'frozen_config_matches': common.digest(Path('config/alignment_fresh_dates.json'))
            == protocol['config_sha256'],
        'runner_matches': common.digest(Path('code/run_alignment_fresh_dates.py'))
            == protocol['script_sha256'],
        'source_manifest_matches': common.digest(Path('results/data_screening_manifest.json'))
            == protocol['source_manifest_sha256'],
        'layout_manifest_matches': common.digest(layouts_path) == protocol['layouts_manifest_sha256'],
    }
    valid_measurements = True
    unique_repeats = set()
    for row in rows:
        key = (row['query_id'], row['layout'])
        if key not in answer_map or row['query_id'] not in query_map:
            valid_measurements = False
            continue
        query = query_map[row['query_id']]
        reference = answer_map[key]['expected']
        mean_matches = (row['mean_sst'] is None and reference[1] is None) or (
            row['mean_sst'] is not None and reference[1] is not None
            and math.isclose(row['mean_sst'], reference[1], rel_tol=1e-12, abs_tol=1e-9))
        repeat = (row['phase'], row['query_id'], row['layout'], row['repetition'])
        valid_measurements &= (
            row['count'] == reference[0] and mean_matches
            and math.isfinite(row['elapsed_ms']) and row['elapsed_ms'] > 0
            and row['kind'] == query['kind']
            and row['window_hours'] == query['window_hours']
            and repeat not in unique_repeats
            and 1 <= row['repetition'] <= (5 if row['phase'] == 'measured' else 1))
        unique_repeats.add(repeat)
    checks['every_timed_answer_and_repeat_valid'] = bool(valid_measurements)
    if not all(checks.values()):
        raise ValueError('Saved run validation failed: ' + ', '.join(k for k, ok in checks.items() if not ok))
    return checks, json.loads(layouts_path.read_text())


def class_statistics(rows, diagnosis):
    stats = []
    for kind in ('Q1', 'Q2'):
        for layout in LAYOUTS:
            selected = [r for r in rows if r['kind'] == kind and r['layout'] == layout and r['phase'] == 'measured']
            nonempty = [r for r in selected if r['count'] > 0]
            groups = [r for r in diagnosis if r['kind'] == kind and r['layout'] == layout and r['matching_rows'] > 0]
            stats.append({
                'kind': kind, 'layout': layout,
                'mean_ms': statistics.mean(r['elapsed_ms'] for r in selected),
                'nonempty_mean_ms': statistics.mean(r['elapsed_ms'] for r in nonempty),
                'candidate_groups': statistics.mean(r['candidate_groups'] for r in groups),
                'matching_groups': statistics.mean(r['groups_with_matching_rows'] for r in groups),
                'false_positive_groups': statistics.mean(r['false_positive_groups'] for r in groups),
            })
    get = lambda kind, layout: next(r for r in stats if r['kind'] == kind and r['layout'] == layout)
    reductions = {kind: 100 * (1 - get(kind, 'station_aligned')['mean_ms'] / get(kind, 'station_first')['mean_ms'])
                  for kind in ('Q1', 'Q2')}
    return stats, reductions


def plot_figures(stats, effects, directory, dates):
    directory.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'pdf.fonttype': 42,
                         'axes.spines.top': False, 'axes.spines.right': False})
    rng = random.Random(20261115)
    get = lambda kind, layout: next(r for r in stats if r['kind'] == kind and r['layout'] == layout)
    for mode in ('latency', 'groups'):
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
        for ax, kind in zip(axes, ('Q1', 'Q2')):
            if mode == 'latency':
                vals = [get(kind, layout)['mean_ms'] for layout in LAYOUTS]
                bars = ax.bar(range(3), vals, color=COLORS, alpha=.7)
                ax.bar_label(bars, fmt='%.3f', padding=3)
                for i, layout in enumerate(LAYOUTS):
                    dots = [r['mean_ms'] for r in effects if r['kind'] == kind and r['layout'] == layout]
                    ax.scatter([i + rng.uniform(-.1, .1) for _ in dots], dots, s=16,
                               color=COLORS[i], edgecolors='white', linewidths=.25)
                ax.set_ylabel('Mean warm latency (ms)')
            else:
                match = [get(kind, layout)['matching_groups'] for layout in LAYOUTS]
                false = [get(kind, layout)['false_positive_groups'] for layout in LAYOUTS]
                ax.bar(range(3), match, color='#147d83', label='Groups with matching rows')
                ax.bar(range(3), false, bottom=match, color='#d6a452', label='Candidates without matches')
                ax.legend(fontsize=8)
                ax.set_ylabel('Mean groups per nonempty query')
            ax.set_xticks(range(3), LABELS, fontsize=8)
            ax.set_title(kind)
            ax.grid(axis='y', alpha=.15)
        fig.suptitle('Unchanged layouts, previously unused starts: ' + ' and '.join(d[:10] for d in dates), fontsize=13)
        note = ('Bars: class mean; dots: per-query means over five warm executions.' if mode == 'latency'
                else 'Metadata candidates and independent Arrow inspection; not DuckDB disk I/O.')
        fig.text(.5, .015, note, ha='center', fontsize=9)
        fig.tight_layout(rect=(0, .05, 1, .93))
        for ext in ('png', 'pdf'):
            fig.savefig(directory / f'fresh_{mode}.{ext}', dpi=160)
        plt.close(fig)


def analyze(run_dir, output_dir=None, statistics_only=False, verify_inputs=False):
    run_dir = Path(run_dir)
    output_dir = Path(output_dir) if output_dir else run_dir / 'analysis'
    source_path, output_path = run_dir.resolve(), output_dir.resolve()
    if output_path == source_path or output_path in source_path.parents:
        raise ValueError('Analysis output must be a separate directory, not the source run or its parent')
    protocol = json.loads((run_dir / 'protocol.json').read_text())
    status = json.loads((run_dir / 'run_status.json').read_text())
    queries = json.loads((run_dir / 'queries.json').read_text())
    answers = json.loads((run_dir / 'correctness.json').read_text())
    rows = read_csv(run_dir / 'measurements.csv')
    diagnosis = read_csv(run_dir / 'joint_match_summary.csv')
    checks, layouts = validate_run(run_dir, rows, queries, answers, protocol, status)
    expected = {(q['query_id'], layout) for q in queries for layout in LAYOUTS}
    diagnosis_keys = {(r['query_id'], r['layout']) for r in diagnosis}
    counts = {(r['query_id'], r['layout']): r['expected'][0] for r in answers}
    checks['162_joint_match_diagnostics'] = (len(diagnosis) == 162 and diagnosis_keys == expected
        and all(r['matching_rows'] == counts[(r['query_id'], r['layout'])] for r in diagnosis))
    if not checks['162_joint_match_diagnostics']:
        raise ValueError('Joint-match diagnosis does not match the saved answers')
    if verify_inputs:
        checks['current_parquet_bytes_match'] = all(
            common.digest(Path(v['path'])) == v['file_sha256'] for v in layouts.values())
        if not checks['current_parquet_bytes_match']:
            raise ValueError('Current Parquet bytes differ from the saved layout snapshot')
    stats, reductions = class_statistics(rows, diagnosis)
    pairs, evidence = compute_query_effects(rows, queries)
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes = {name: common.digest(run_dir / name) for name in
              ('measurements.csv', 'queries.json', 'correctness.json', 'joint_match_summary.csv')}
    common.save_json(output_dir / 'analysis_checks.json', {
        'checks': checks, 'parquet_bytes_verification': 'passed' if verify_inputs else 'not_requested',
        'scope': 'Saved result validation; no queries or new timings', 'source_sha256': hashes})
    common.save_json(output_dir / 'summary.json', {
        'stats': stats, 'latency_reduction_percent': reductions,
        'dates': protocol['config']['start_dates_utc'],
        'analysis_script_sha256': common.digest(Path(__file__)),
        'scope': 'new query dates; same historical dataset and machine'})
    common.save_csv(output_dir / 'class_summary.csv', stats)
    common.save_csv(output_dir / 'per_query_effects.csv', pairs)
    evidence.update({'source_sha256': hashes,
                     'analysis_module_sha256': common.digest(Path(__file__).with_name('analyze_query_effects.py'))})
    common.save_json(output_dir / 'query_effect_evidence.json', evidence)
    if not statistics_only:
        plot_figures(stats, summarize(rows), output_dir / 'figures', protocol['config']['start_dates_utc'])
    print(json.dumps({'output_dir': str(output_dir), 'checks_passed': len(checks),
                      'effects_percent': reductions, 'no_sql_executed': True}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, default=Path('results/alignment_fresh_v1'))
    parser.add_argument('--output-dir', type=Path, help='Default: RUN_DIR/analysis')
    parser.add_argument('--statistics-only', action='store_true', help='Skip figure generation')
    parser.add_argument('--verify-inputs', action='store_true', help='Also hash restored local Parquet files')
    args = parser.parse_args()
    analyze(args.run_dir, args.output_dir, args.statistics_only, args.verify_inputs)
