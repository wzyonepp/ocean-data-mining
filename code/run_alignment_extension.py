#!/usr/bin/env python3
"""Exploratory station-boundary alignment experiment; local files only."""
import argparse
import json
import math
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path
import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import run_parquet_pilot as c
import run_parquet_formal as f

ORDER = ['station_first', 'station_aligned', 'time_first']

def sql_for(q, path=None):
    if q['kind'] != 'Q0': return c.query_sql(q, path)
    return ('SELECT count(*), avg(sst) FROM '+('read_parquet(?)' if path else 'reference_data'), [str(path)] if path else [])

def run(run_id):
    out=Path('results')/run_id
    data=Path('data/parquet')/run_id
    if out.exists() or data.exists(): raise ValueError('Choose a fresh run ID')
    out.mkdir(parents=True); data.mkdir(parents=True)
    status=out/'run_status.json'
    c.save_json(status, {'status':'running'})
    try:
        config=json.loads(Path('config/pilot_v1.json').read_text())
        old=json.loads(Path('results/pilot_v1/layout_manifest.json').read_text())
        source=json.loads(Path(config['data_manifest']).read_text())
        queries=json.loads(Path('results/formal_v1/queries.json').read_text())
        queries.append(c.make_query('overhead_Q0_full_scan','overhead','Q0',None,'2023-01-01T00:00:00Z',17544))
        protocol={'run_id':run_id,'purpose':'exploratory extension; previously seen queries',
          'config':config,'layouts':ORDER,'queries':queries,'created_at_utc':f.timestamp_now(),
          'script_sha256':c.digest(Path(__file__)), 'plan_sha256':c.digest(Path('report/08_alignment_protocol.md')),
          'source_manifest_sha256':c.digest(Path(config['data_manifest'])),
          'original_layout_manifest_sha256':c.digest(Path('results/pilot_v1/layout_manifest.json'))}
        (out/'plan_frozen.md').write_bytes(Path('report/08_alignment_protocol.md').read_bytes())
        con=duckdb.connect();con.execute('SET threads=1');con.execute("SET TimeZone='UTC'")
        protocol['environment']=c.environment(con)
        c.save_json(out/'protocol.json',protocol)
        base=c.read_base(source)
        station=base.sort_by(c.CANONICAL_KEYS).combine_chunks()
        canonical=c.logical_digest(base)
        for name in ['station_first','time_first']:
            if c.digest(Path(old[name]['path']))!=old[name]['file_sha256']:raise AssertionError('Original file changed')
            if c.logical_digest(pq.ParquetFile(old[name]['path']).read())!=canonical:raise AssertionError('Logical input mismatch')
        kwargs=dict(config['writer']);limit=kwargs.pop('row_group_size')
        control=data/'writer_control.parquet'
        with pq.ParquetWriter(control,station.schema,**kwargs) as writer:
            for start in range(0,station.num_rows,limit):writer.write_table(station.slice(start,limit),row_group_size=limit)
        if c.digest(control)!=old['station_first']['file_sha256']:raise AssertionError('Writer-interface control differs from original bytes')
        aligned=data/'station_aligned.parquet'
        with pq.ParquetWriter(aligned,station.schema,**kwargs) as writer:
            for sid in source['requested_stations']:
                subset=station.filter(pc.equal(station['station_id'],sid)).combine_chunks()
                for start in range(0,subset.num_rows,limit):writer.write_table(subset.slice(start,limit),row_group_size=limit)
        restored=pq.ParquetFile(aligned).read().combine_chunks()
        if not restored.equals(station):raise AssertionError('Alignment changed row order/content')
        layouts={name:old[name] for name in ['station_first','time_first']}
        layouts['station_aligned']={'path':str(aligned),'file_sha256':c.digest(aligned),'logical_sha256':canonical}
        groups={name:c.extract_groups(Path(layouts[name]['path'])) for name in ORDER}
        if any(g['columns']['station_id']['min']!=g['columns']['station_id']['max'] for g in groups['station_aligned']):raise AssertionError('Mixed-station aligned group')
        for name in ORDER:
            path=Path(layouts[name]['path']);meta=pq.ParquetFile(path).metadata
            layouts[name]={**layouts[name],'rows':meta.num_rows,'row_groups':meta.num_row_groups,
              'file_bytes':path.stat().st_size,'footer_bytes':meta.serialized_size,
              'short_groups':sum(g['rows']<limit for g in groups[name]),
              'min_group_rows':min(g['rows'] for g in groups[name]),
              'mixed_station_groups':sum(g['columns']['station_id']['min']!=g['columns']['station_id']['max'] for g in groups[name])}
            if meta.num_rows!=base.num_rows or any(g['rows']>limit for g in groups[name]):raise AssertionError('Group size/content invariant failed')
        c.save_json(out/'layouts.json',layouts)
        c.save_json(out/'writer_control.json',{'matches_original_byte_for_byte':True,'sha256':c.digest(control)})
        c.save_json(out/'row_groups.json',groups)
        con.register('reference_data',base)
        answers={}; checks=[]; candidates=[]
        for q in queries:
            sql,args=sql_for(q);ref=con.execute(sql,args).fetchone();answers[q['query_id']]=ref
            for name in ORDER:
                sql,args=sql_for(q,layouts[name]['path']);actual=con.execute(sql,args).fetchone();c.check_answer(actual,ref,config)
                checks.append({'query_id':q['query_id'],'layout':name,'expected':ref,'actual':actual,'passed':True})
                candidates.append({'query_id':q['query_id'],'role':q['role'],'kind':q['kind'],'window_hours':q['window_hours'],'layout':name,**c.candidate_stats(q,groups[name])})
        c.save_json(out/'correctness.json',checks);c.save_json(out/'queries.json',queries)
        c.save_csv(out/'candidate_groups.csv',candidates)
        print('Aligned groups:',layouts['station_aligned']['row_groups'],'; all 327 answers verified',flush=True)
        rows=[];rng=random.Random(config['random_seed'])
        for phase,rounds in [('warmup',1),('measured',5)]:
            for rep in range(rounds):
                shuffled=list(queries);rng.shuffle(shuffled)
                for pos,q in enumerate(shuffled):
                    offset=(rep+pos)%3
                    for layout_pos,name in enumerate(ORDER[offset:]+ORDER[:offset]):
                        sql,args=sql_for(q,layouts[name]['path']);start=time.perf_counter_ns()
                        actual=con.execute(sql,args).fetchone();ms=(time.perf_counter_ns()-start)/1e6
                        c.check_answer(actual,answers[q['query_id']],config)
                        rows.append({'role':q['role'],'kind':q['kind'],'query_id':q['query_id'],'station_id':q['station_id'],
                          'start_utc':q['start_utc'],'window_hours':q['window_hours'],'layout':name,'phase':phase,
                          'repetition':rep+1,'query_position':pos,'layout_position':layout_pos,'elapsed_ms':ms,
                          'count':actual[0],'mean_sst':actual[1]})
        c.save_csv(out/'measurements.csv',rows);c.save_csv(out/'query_summary.csv',f.summarize(rows))
        print('All timings saved; inspecting candidate groups outside timers',flush=True)
        details,diag=f.diagnose_groups(queries,layouts,groups,answers,{'diagnostic_layouts':ORDER})
        c.save_csv(out/'joint_match_diagnostic.csv',details);c.save_csv(out/'joint_match_summary.csv',diag)
        assert sum(r['phase']=='measured' for r in rows)==1635
        assert sum(r['phase']=='warmup' for r in rows)==327
        c.save_json(status,{'status':'passed','completed_at_utc':f.timestamp_now(),'queries':109,'main_queries':108,
          'overhead_queries':1,'correctness_checks':len(checks),'measured_executions':1635,'warmups':327,
          'main_measured_executions':1620,'overhead_measured_executions':15,'logical_rows':base.num_rows,
          'exploratory':True,'writer_control_passed':True})
        print(json.dumps(json.loads(status.read_text())),flush=True)
    except Exception as error:
        c.save_json(status,{'status':'failed','error':str(error)});raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',default='alignment_v1')
    args=parser.parse_args()
    if not args.run_id or not all(ch.isalnum() or ch in '_-' for ch in args.run_id):parser.error('Invalid run ID')
    run(args.run_id)
