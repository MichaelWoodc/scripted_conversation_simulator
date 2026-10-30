"""Build the student pages and map ordered DOCX questions to existing WAV files."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import re
import shutil
import sys
import wave
from urllib.parse import quote

from project_paths import BIN, ROOT, DIST, audio_root

SITE = BIN / 'site'
PROJECT = ROOT
from answer_tts import LABEL, load_answers, read_docx

PROFILES = {'edited':'Edited recordings', 'original':'Original recordings',
            'reviewed':'Earlier reviewed recordings'}
TITLES = {1:'Materials & resources', 2:'Training & support', 3:'Feedback & performance'}


def slug(text):
    return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')


def question_parts(raw):
    """Keep optional examples separate from the question the student reads."""
    main, context, depth, chunk = [], [], 0, []
    for char in raw:
        if char == '(':
            if depth: chunk.append(char)
            depth += 1
        elif char == ')' and depth:
            depth -= 1
            if not depth:
                context.append(''.join(chunk).strip()); chunk=[]; main.append(' ')
            else: chunk.append(char)
        elif depth: chunk.append(char)
        else: main.append(char)
    prompt=re.sub(r'\s+',' ',''.join(main)).strip()
    prompt=re.split(r'\bOR\b',prompt)[0].strip()
    prompt=re.sub(r'\s+([?.!,;:])',r'\1',prompt)
    return prompt, context


def ordered_steps(path, answers, overrides):
    markers=list(LABEL.finditer(read_docx(path)))
    question_id=-1; ids=[]
    for marker in markers:
        if marker[1]=='QUESTION': question_id+=1
        else: ids.append(question_id)
    if len(ids)!=len(answers): raise ValueError(f'Answer numbering mismatch: {path.name}')
    steps=[]
    for question_id, answer in zip(ids,answers):
        key=f'{path.name}::{answer.index:03d}'
        prompt,context=question_parts(answer.question)
        prompt=overrides.get(key,prompt)
        if steps and steps[-1]['questionId']==question_id:
            steps[-1]['answerIndices'].append(answer.index)
        else:
            steps.append({'id':f'q-{len(steps)+1:03d}','questionId':question_id,'prompt':prompt,
                          'sourceQuestion':answer.question,'context':context,'answerIndices':[answer.index]})
    return steps


def make_catalog(project=PROJECT):
    project=Path(project)
    scripts=project/'data'/'scripts'
    answers=load_answers(scripts)
    override_path=project/'data'/'question_overrides.json'
    overrides=json.loads(override_path.read_text(encoding='utf-8'))
    documents={}
    for source in dict.fromkeys(a.source for a in answers):
        group=[a for a in answers if a.source==source]
        documents[Path(source).stem]=(source,group,ordered_steps(scripts/source,group,overrides))
    sets=[]; media={}; incomplete=[]
    for edition,label in PROFILES.items():
        root=audio_root(edition,project)
        if not root.exists(): continue
        for folder in sorted({f.parent for f in root.rglob('answer_*.wav')}):
            if folder.name not in documents: continue
            source,group,steps=documents[folder.name]
            expected=[a.index for a in group]
            missing=[i for i in expected if not (folder/f'answer_{i:03d}.wav').exists()]
            if missing:
                incomplete.append({'folder':str(folder.relative_to(project)),'missing':missing});continue
            relative=folder.relative_to(root)
            voice=relative.parts[0] if len(relative.parts)>1 else 'reviewed'
            speed=relative.parts[-2] if len(relative.parts)>2 else 'speed_1p00'
            number=int(re.search(r'Vignette (\d+)',source)[1])
            identifier=slug(f'{edition}-{voice}-{speed}-vignette-{number}')
            clips={}; failed=False
            for index in expected:
                wav=folder/f'answer_{index:03d}.wav'
                try:
                    with wave.open(str(wav),'rb') as audio:
                        duration=audio.getnframes()/audio.getframerate()
                        if not duration: raise ValueError('Empty WAV')
                except (ValueError,wave.Error,EOFError) as exc:
                    incomplete.append({'folder':str(folder.relative_to(project)),'error':str(exc)});failed=True;break
                public=wav.relative_to(project/'dist').as_posix()
                media[public]=wav
                clips[index]={'id':f'answer-{index:03d}','index':index,'url':quote(public)+f'?v={wav.stat().st_mtime_ns}',
                              'duration':round(duration,3)}
            if failed: continue
            items=[{**s,'clips':[clips[i] for i in s['answerIndices']]} for s in steps]
            version=hashlib.sha256(json.dumps([(s['prompt'],s['answerIndices']) for s in steps]).encode()).hexdigest()[:12]
            sets.append({'id':identifier,'edition':edition,'editionLabel':label,'vignette':number,
                         'title':TITLES.get(number,f'Vignette {number}'),'source':source,'voice':voice,
                         'speed':speed,'page':f'sets/{identifier}.html','version':version,'steps':items,
                         'answerCount':len(group),'duration':round(sum(c['duration'] for c in clips.values()),1)})
    sets.sort(key=lambda s: (0 if s['edition']=='edited' else 1,s['edition'],s['vignette'],s['id']))
    return {'schema':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'sets':sets,
            'incompleteFolders':incomplete}, media


def build(static_audio=False, *, project=PROJECT):
    """Build a self-contained site; recordings already live in dist/media.

    static_audio is accepted for compatibility with existing build commands.
    No audio copies are required for either local or static hosting.
    """
    project=Path(project)
    dist=project/'dist';dist.mkdir(parents=True,exist_ok=True)
    shutil.copytree(SITE/'assets',dist/'assets',dirs_exist_ok=True)
    shutil.copy2(SITE/'index.html',dist/'index.html')
    catalog,media=make_catalog(project)
    (dist/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    template=(SITE/'session.html').read_text(encoding='utf-8')
    (dist/'sets').mkdir(exist_ok=True)
    for item in catalog['sets']:
        (dist/item['page']).write_text(template.replace('{{SET_ID}}',escape(item['id'])).replace('{{TITLE}}',escape(item['title'])),encoding='utf-8')
    (dist/'.nojekyll').write_text('',encoding='utf-8')
    return catalog,media


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static',action='store_true',help='Build for static hosting (all builds include audio in dist/media).')
    args=parser.parse_args()
    catalog,_=build(args.static)
    print(f"Built {len(catalog['sets'])} complete audio sets; {len(catalog['incompleteFolders'])} incomplete folders excluded.")
    print(DIST)
