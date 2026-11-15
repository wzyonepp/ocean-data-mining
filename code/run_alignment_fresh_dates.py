#!/usr/bin/env python3
"""Freeze two unused query dates and test unchanged alignment layouts."""
import argparse,json,random,time
from pathlib import Path
from collections import Counter
import duckdb
import pyarrow.parquet as pq
import run_parquet_pilot as c
import run_parquet_formal as f

def run(run_id):
    path=Path('config/alignment_fresh_dates.json');config=json.loads(path.read_text())
    out=Path('results')/run_id
    if out.exists():raise ValueError('Choose a fresh run ID')
    out.mkdir(parents=True);status=out/'run_status.json'
    c.save_json(status,{'status':'running'})
    try:
        pilot=json.loads(Path('config/pilot_v1.json').read_text())
        source=json.loads(Path(pilot['data_manifest']).read_text())
        layouts=json.loads(Path(config['layout_manifest']).read_text())
        queries=[]
        for i,start in enumerate(config['start_dates_utc']):
            for sid in source['requested_stations']:
                for h in config['q1_hours']:queries.append(c.make_query(f'fresh_Q1_{i}_{sid}_{h}','fresh_dates','Q1',sid,start,h))
            for h in config['q2_hours']:queries.append(c.make_query(f'fresh_Q2_{i}_{h}','fresh_dates','Q2',None,start,h))
        prior=[]
        for oldpath in ['results/pilot_v1/pilot_queries.json','results/formal_v1/queries.json','results/alignment_v1/queries.json']:
            prior+=json.loads(Path(oldpath).read_text())
        assert not ({q['start_utc'] for q in queries}&{q['start_utc'] for q in prior})
        assert len(queries)==54
        con=duckdb.connect();con.execute('SET threads=1');con.execute("SET TimeZone='UTC'")
        protocol={'created_at_utc':f.timestamp_now(),'config':config,'environment':c.environment(con),
          'script_sha256':c.digest(Path(__file__)),'config_sha256':c.digest(path),
          'source_manifest_sha256':c.digest(Path(pilot['data_manifest'])),
          'layouts_manifest_sha256':c.digest(Path(config['layout_manifest'])),
          'plan_sha256':c.digest(Path('report/10_fresh_dates_protocol.md')),
          'queries_frozen_before_measurement':True,'query_dates_disjoint_from_all_previous':True}
        c.save_json(out/'protocol.json',protocol);c.save_json(out/'queries.json',queries)
        (out/'plan_frozen.md').write_bytes(Path('report/10_fresh_dates_protocol.md').read_bytes())
        base=c.read_base(source);canonical=c.logical_digest(base);con.register('reference_data',base)
        groups={}
        for name in config['layouts']:
            p=Path(layouts[name]['path'])
            assert c.digest(p)==layouts[name]['file_sha256']
            assert c.logical_digest(pq.ParquetFile(p).read())==canonical
            groups[name]=c.extract_groups(p)
        refs={};checks=[];candidates=[]
        for q in queries:
            sql,args=c.query_sql(q);ref=con.execute(sql,args).fetchone();refs[q['query_id']]=ref
            for name in config['layouts']:
                sql,args=c.query_sql(q,layouts[name]['path']);actual=con.execute(sql,args).fetchone();c.check_answer(actual,ref,pilot)
                checks.append({'query_id':q['query_id'],'layout':name,'expected':ref,'actual':actual,'passed':True})
                candidates.append({'query_id':q['query_id'],'kind':q['kind'],'layout':name,**c.candidate_stats(q,groups[name])})
        c.save_json(out/'correctness.json',checks);c.save_csv(out/'candidate_groups.csv',candidates)
        print('54 new queries frozen; 162 answers verified',flush=True)
        rows=[];rng=random.Random(config['seed']);order=config['layouts']
        for phase,rounds in [('warmup',1),('measured',5)]:
            for rep in range(rounds):
                shuffled=list(queries);rng.shuffle(shuffled)
                for pos,q in enumerate(shuffled):
                    offset=(rep+pos)%3
                    for lp,name in enumerate(order[offset:]+order[:offset]):
                        sql,args=c.query_sql(q,layouts[name]['path']);start=time.perf_counter_ns()
                        actual=con.execute(sql,args).fetchone();elapsed=(time.perf_counter_ns()-start)/1e6
                        c.check_answer(actual,refs[q['query_id']],pilot)
                        rows.append({'role':'fresh_dates','kind':q['kind'],'query_id':q['query_id'],'station_id':q['station_id'],
                          'start_utc':q['start_utc'],'window_hours':q['window_hours'],'layout':name,'phase':phase,'repetition':rep+1,
                          'query_position':pos,'layout_position':lp,'elapsed_ms':elapsed,'count':actual[0],'mean_sst':actual[1]})
        c.save_csv(out/'measurements.csv',rows);c.save_csv(out/'query_summary.csv',f.summarize(rows))
        details,diag=f.diagnose_groups(queries,layouts,groups,refs,{'diagnostic_layouts':order})
        c.save_csv(out/'joint_match_diagnostic.csv',details);c.save_csv(out/'joint_match_summary.csv',diag)
        counts=Counter(r['phase'] for r in rows);assert counts=={'measured':810,'warmup':162}
        c.save_json(status,{'status':'passed','completed_at_utc':f.timestamp_now(),'queries':54,'answer_checks':162,
          'measured_executions':810,'extra_warmups':162,'empty_queries':sum(refs[q['query_id']][0]==0 for q in queries),
          'no_method_or_query_revision':True})
        print(status.read_text(),flush=True)
    except Exception as err:c.save_json(status,{'status':'failed','error':str(err)});raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',default='alignment_fresh_v1');a=p.parse_args()
    if not a.run_id or not all(x.isalnum() or x in '_-' for x in a.run_id):p.error('Invalid run ID')
    run(a.run_id)
