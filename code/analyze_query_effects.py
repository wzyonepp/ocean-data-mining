"""Compute per-query alignment effects from saved timings, without SQL or prose."""
from collections import defaultdict
import statistics

LAYOUTS = ('station_first', 'station_aligned', 'time_first')


def compute_query_effects(rows, queries):
    """Return paired means/medians and the worst observed relative mean change.

    Empty-result queries and every measured repeat are retained.  Negative
    reduction percentages mean that the aligned mean was higher in this run;
    neither the counts nor the worst case establish statistical significance.
    """
    grouped = defaultdict(list)
    for row in rows:
        if row['phase'] == 'measured':
            grouped[(row['query_id'], row['layout'])].append(row)
    effects = []
    for query in sorted(queries, key=lambda q: q['query_id']):
        values = {}
        for layout in LAYOUTS:
            selected = grouped[(query['query_id'], layout)]
            if not selected:
                raise ValueError(f"Missing measurements: {query['query_id']} / {layout}")
            elapsed = [r['elapsed_ms'] for r in selected]
            values[layout] = {
                'mean': statistics.mean(elapsed),
                'median': statistics.median(elapsed),
                'count': selected[0]['count'],
            }
        baseline, aligned = values['station_first'], values['station_aligned']
        effects.append({
            'query_id': query['query_id'], 'kind': query['kind'],
            'station_id': query['station_id'], 'start_utc': query['start_utc'],
            'window_hours': query['window_hours'], 'matching_rows': baseline['count'],
            'station_first_mean_ms': baseline['mean'],
            'station_aligned_mean_ms': aligned['mean'],
            'mean_reduction_percent': 100 * (1 - aligned['mean'] / baseline['mean']),
            'station_first_median_ms': baseline['median'],
            'station_aligned_median_ms': aligned['median'],
            'aligned_mean_lower': aligned['mean'] < baseline['mean'],
        })
    counts = []
    for kind in ('Q1', 'Q2'):
        selected = [r for r in effects if r['kind'] == kind]
        lower = sum(r['aligned_mean_lower'] for r in selected)
        counts.append({'kind': kind, 'queries': len(selected),
                       'mean_lower': lower, 'mean_not_lower': len(selected) - lower})
    worst = min(effects, key=lambda r: r['mean_reduction_percent'])
    raw_case = []
    for layout in LAYOUTS:
        selected = sorted(grouped[(worst['query_id'], layout)],
                          key=lambda r: r['repetition'])
        elapsed = [r['elapsed_ms'] for r in selected]
        raw_case.append({'layout': layout, 'runs_ms': elapsed,
                         'mean_ms': statistics.mean(elapsed),
                         'median_ms': statistics.median(elapsed)})
    return effects, {'counts': counts, 'worst_mean_case': worst, 'raw_case': raw_case,
                     'primary_mean_metric_unchanged': True,
                     'raw_measurements_modified': False}
