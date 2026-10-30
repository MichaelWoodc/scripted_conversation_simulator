"""Replace legacy processed answer files with direct model audio, preserving text."""
from __future__ import annotations

import ast
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import soundfile as sf

from answer_tts import MODEL_ID, RENDER_VERSION, ROOT, SAMPLE_RATE, TTSEngine, load_answers
from project_paths import DATA
from urllib.parse import unquote


def notebook_settings(root=ROOT):
    """Read literal cell settings without executing user notebook code."""
    records={}
    notebooks=Path(root)/'notebooks'
    paths=[notebooks/'answer_review.ipynb',notebooks/'answers_tts.ipynb',*sorted((notebooks/'answers').glob('*.ipynb'))]
    for path in sorted((p for p in paths if p.exists()),key=lambda p:p.stat().st_mtime_ns):
        notebook=json.loads(path.read_text(encoding='utf-8'))
        for cell in notebook['cells']:
            meta=cell.get('metadata',{})
            if cell['cell_type']!='code' or 'answer_source' not in meta or 'answer_index' not in meta:continue
            values={}
            for node in ast.parse(''.join(cell['source'])).body:
                if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('text','voice','speed'):
                    try:values[node.targets[0].id]=ast.literal_eval(node.value)
                    except (ValueError,TypeError):pass
            if isinstance(values.get('text'),str):
                records[(meta['answer_source'],meta['answer_index'])]={**values,'notebook':str(path.relative_to(root))}
    return records


def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def atomic_replace(temp,path):
    for attempt in range(30):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==29:raise
            time.sleep(0.1)


def refresh():
    from build_site import make_catalog
    catalog,media=make_catalog()
    source={(a.source,a.index):a for a in load_answers()}
    edited=notebook_settings()
    drafts=json.loads((DATA/'answer_edits.json').read_text(encoding='utf-8'))
    jobs=[];kept=[]
    for item in catalog['sets']:
        speed=float(item['speed'].removeprefix('speed_').replace('p','.'))
        for step in item['steps']:
            for clip in step['clips']:
                path=media[unquote(clip['url'].split('?')[0])]
                old=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                if old.get('audio_processing')=='none' and not old.get('stretch_method'):
                    kept.append(str(path.relative_to(ROOT)));continue
                key=(item['source'],clip['index'])
                text=path.with_suffix('.txt').read_text(encoding='utf-8')
                origin='existing transcript'
                if item['edition']=='edited':
                    settings=edited.get(key) or drafts.get(f'{key[0]}::{key[1]:03d}',{})
                    text=settings.get('text',text)
                    origin=settings.get('notebook','saved text edits')
                jobs.append({'path':path,'answer':replace(source[key],spoken_text=text),'voice':item['voice'],
                             'speed':speed,'origin':origin,'old':old})
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/'.cache'/'audio_refresh_backups'/stamp
    report_path=DATA/'reports'/'audio_refresh_report.json'
    report={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),
            'planned':len(jobs),'kept_clean':kept,'replaced':[],'backup_folder':str(backup.relative_to(ROOT))}
    write_json(report_path,report)
    print(f'Regenerating {len(jobs)} legacy clips; preserving {len(kept)} clean saved clips.',flush=True)
    engine=TTSEngine()
    for done,job in enumerate(jobs,1):
        path=job['path'];answer=job['answer']
        audio=engine.synthesize(answer.spoken_text,job['voice'],job['speed'])
        if not audio.size or not np.isfinite(audio).all() or float(np.abs(audio).max())>=1:
            raise RuntimeError(f'Invalid model audio: {path}')
        for old_file in [path,path.with_suffix('.txt'),path.with_suffix('.json')]:
            copy=backup/old_file.relative_to(ROOT);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(old_file,copy)
        temp=path.with_name('.'+path.name+'.refresh.wav')
        sf.write(str(temp),audio,SAMPLE_RATE,subtype='PCM_24');atomic_replace(temp,path)
        settings={'model':MODEL_ID,'voice':job['voice'],'speed':job['speed'],'render_version':RENDER_VERSION,
                  'answer':asdict(answer),'audio_processing':'none'}
        record={**settings,'fingerprint':hashlib.sha256(json.dumps(settings,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                'sample_rate':SAMPLE_RATE,'subtype':'PCM_24','duration_seconds':round(len(audio)/SAMPLE_RATE,3),
                'audio_file':str(path.relative_to(ROOT/'dist')),
                'created_utc':datetime.now(timezone.utc).isoformat(),'text_source':job['origin']}
        path.with_suffix('.txt').write_text(answer.spoken_text,encoding='utf-8')
        write_json(path.with_suffix('.json'),record)
        report['replaced'].append({'path':str(path.relative_to(ROOT)),'text_source':job['origin']})
        write_json(report_path,report)
        print(f'[{done}/{len(jobs)}] Replaced {path.relative_to(ROOT)}',flush=True)
    manifests={}
    for item in catalog['sets']:
        files=[media[unquote(c['url'].split('?')[0])] for step in item['steps'] for c in step['clips']]
        folder=files[0].parent;variant=folder.parent
        combined=folder/'all_answers.wav';sidecar=combined.with_suffix('.json')
        prior=json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.exists() else {}
        gap=prior.get('gap_seconds',0.65);frames=0;timeline=[]
        temp=folder/'.all_answers.refresh.wav'
        with sf.SoundFile(str(temp),mode='w',samplerate=SAMPLE_RATE,channels=1,subtype='PCM_24') as sink:
            for i,path in enumerate(files):
                if i:sink.write(np.zeros(round(gap*SAMPLE_RATE),np.float32));frames+=round(gap*SAMPLE_RATE)
                start=frames/SAMPLE_RATE;audio,rate=sf.read(str(path),dtype='float32')
                if rate!=SAMPLE_RATE:raise RuntimeError('Unexpected sample rate')
                sink.write(audio);frames+=len(audio)
                index=int(path.stem.split('_')[-1]);text=path.with_suffix('.txt').read_text(encoding='utf-8')
                timeline.append({'answer_index':index,'start_seconds':round(start,3),'end_seconds':round(frames/SAMPLE_RATE,3),'text':text})
                record=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                if 'answer' not in record:record['answer']=asdict(replace(source[(item['source'],index)],spoken_text=text))
                manifests.setdefault(variant,[]).append(record)
        atomic_replace(temp,combined)
        write_json(sidecar,{'source':item['source'],'voice':item['voice'],'gap_seconds':gap,'answers':timeline,'audio_processing':'none'})
    for folder,records in manifests.items():write_json(folder/'manifest.json',records)
    report['status']='complete';report['finished_utc']=datetime.now(timezone.utc).isoformat()
    write_json(report_path,report)
    print(f"Finished: {len(jobs)} replaced, {len(kept)} clean clips preserved; combined tracks rebuilt.",flush=True)


if __name__=='__main__':
    try:refresh()
    except BaseException as error:
        path=DATA/'reports'/'audio_refresh_report.json'
        if path.exists():
            report=json.loads(path.read_text(encoding='utf-8'));report.update(status='failed',error=str(error));write_json(path,report)
        raise
