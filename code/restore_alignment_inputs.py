#!/usr/bin/env python3
"""Restore original and aligned Parquet snapshots without rewriting results."""
import argparse,json
from pathlib import Path
import pyarrow.compute as pc
import pyarrow.parquet as pq
import run_parquet_pilot as c
from restore_parquet_inputs import restore

def main(verify,log):
    restore(False,Path('data/base_restore_log.json'))
    protocol=json.loads(Path('results/alignment_v1/protocol.json').read_text())
    layouts=json.loads(Path('results/alignment_v1/layouts.json').read_text())
    config=protocol['config'];manifest_path=Path(config['data_manifest'])
    assert c.digest(manifest_path)==protocol['source_manifest_sha256']
    record=layouts['station_aligned'];target=Path(record['path'])
    if target.exists() and c.digest(target)!=record['file_sha256']:raise ValueError('Existing aligned file differs; refusing overwrite')
    action='reused'
    if verify or not target.exists():
        source=json.loads(manifest_path.read_text());base=c.read_base(source).sort_by(c.CANONICAL_KEYS).combine_chunks()
        kwargs=dict(config['writer']);limit=kwargs.pop('row_group_size')
        target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_suffix('.restore-check.parquet')
        if temporary.exists():raise ValueError('Inspect existing temporary file first')
        with pq.ParquetWriter(temporary,base.schema,**kwargs) as writer:
            for station in source['requested_stations']:
                rows=base.filter(pc.equal(base['station_id'],station)).combine_chunks()
                for start in range(0,rows.num_rows,limit):writer.write_table(rows.slice(start,limit),row_group_size=limit)
        if c.digest(temporary)!=record['file_sha256']:raise ValueError('Aligned reconstruction hash differs; temporary file retained')
        if target.exists():temporary.unlink();action='rebuilt_and_verified'
        else:temporary.replace(target);action='restored'
    c.save_json(log,{'action':action,'aligned_sha256':c.digest(target),'expected_sha256':record['file_sha256'],
      'result_manifests_modified':False,'restore_script_sha256':c.digest(Path(__file__))})
    print('Aligned snapshot verified:',action,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify-rebuild',action='store_true')
    p.add_argument('--log',type=Path,default=Path('data/alignment_restore_log.json'));a=p.parse_args();main(a.verify_rebuild,a.log)
