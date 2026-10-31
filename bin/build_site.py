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


def question_audio_path(prompt):
    fingerprint = hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:20]
    return f'media/questions/{fingerprint}.wav'


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
            items=[]
            for step in steps:
                question_audio = None
                public = question_audio_path(step['prompt'])
                wav = project / 'dist' / public
                if wav.exists():
                    try:
                        with wave.open(str(wav), 'rb') as audio:
                            duration = audio.getnframes() / audio.getframerate()
                        if duration > 0:
                            media[public] = wav
                            question_audio = {'url': public, 'duration': round(duration, 3)}
                    except (wave.Error, EOFError, OSError):
                        pass  # Optional question audio must not hide a complete answer set.
                items.append({**step, 'clips':[clips[i] for i in step['answerIndices']],
                              'questionAudio': question_audio})
            version=hashlib.sha256(json.dumps([(s['prompt'],s['answerIndices']) for s in steps]).encode()).hexdigest()[:12]
            sets.append({'id':identifier,'edition':edition,'editionLabel':label,'vignette':number,
                         'title':TITLES.get(number,f'Vignette {number}'),'source':source,'voice':voice,
                         'speed':speed,'page':f'sets/{identifier}.html','version':version,'steps':items,
                         'answerCount':len(group),'duration':round(sum(c['duration'] for c in clips.values()),1)})
    sets.sort(key=lambda s: (0 if s['edition']=='edited' else 1,s['edition'],s['vignette'],s['id']))
    return {'schema':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'sets':sets,
            'incompleteFolders':incomplete}, media


def render_template(template, values):
    """Fill values and repeat blocks while keeping all markup in HTML files."""
    def replace(match):
        if match[1]:
            return ''.join(render_template(match[2], {**values, **row})
                           for row in values[match[1]])
        return escape(str(values[match[3]]))

    return re.sub(r'{{#(\w+)}}(.*?){{/\1}}|{{(\w+)}}', replace, template, flags=re.S)


def render_library(catalog):
    sets = catalog['sets']
    editions = dict((item['edition'], item['editionLabel']) for item in sets)
    values = {
        'EDITIONS': [{'EDITION': key, 'EDITION_LABEL': label} for key, label in editions.items()],
        'CARDS': [{
            'PAGE': f"setup.html?set={quote(item['id'])}", 'SET_ID': item['id'], 'EDITION': item['edition'],
            'CHAPTER': f"{item['vignette']:02d}", 'VIGNETTE': item['vignette'],
            'TITLE': item['title'], 'QUESTION_COUNT': len(item['steps']),
            'VOICE': item['voice'].replace('af_', ''), 'EDITION_LABEL': item['editionLabel'],
            'MINUTES': max(1, int(item['duration'] / 60 + .5)),
        } for item in sets],
        'SET_COUNT': len(sets), 'EMPTY_HIDDEN': 'hidden' if sets else '',
    }
    return render_template((SITE / 'index.html').read_text(encoding='utf-8'), values)


def render_session(item):
    questions = []
    for index, step in enumerate(item['steps']):
        prompt = step['prompt']
        # Match engine.js tokenize(): Unicode letters/numbers and apostrophes.
        tokens = list(re.finditer(r"[^\W_]+(?:'[^\W\d_]+)*", prompt))
        words, cursor = [], 0
        for word_index, token in enumerate(tokens):
            words.append({'WORD_INDEX': word_index, 'WORD': token[0],
                          'BEFORE': prompt[cursor:token.start()],
                          'AFTER': prompt[token.end():] if word_index == len(tokens) - 1 else ''})
            cursor = token.end()
        questions.append({'QUESTION_ID': step['id'], 'QUESTION_HIDDEN': 'hidden' if index else '',
                          'WORDS': words, 'CONTEXT': '\n\n'.join(step['context'])})
    values = {
        'SET_ID': item['id'], 'TITLE': item['title'], 'VIGNETTE': item['vignette'],
        'QUESTION_COUNT': len(item['steps']), 'ANSWER_COUNT': item['answerCount'],
        'VOICE_LABEL': 'Heart female' if item['voice'] == 'af_heart' else item['voice'],
        'EDITION_LABEL': item['editionLabel'], 'QUESTIONS': questions,
        'CONTEXT_HIDDEN': '' if item['steps'][0]['context'] else 'hidden',
    }
    return render_template((SITE / 'session.html').read_text(encoding='utf-8-sig'), values)


def build(static_audio=False, *, project=PROJECT):
    """Build a self-contained site; recordings already live in dist/media.

    static_audio is accepted for compatibility with existing build commands.
    No audio copies are required for either local or static hosting.
    """
    project=Path(project)
    dist=project/'dist';dist.mkdir(parents=True,exist_ok=True)
    shutil.copytree(SITE/'assets',dist/'assets',dirs_exist_ok=True)
    shutil.copy2(SITE/'setup.html',dist/'setup.html')
    catalog,media=make_catalog(project)
    (dist/'index.html').write_text(render_library(catalog),encoding='utf-8')
    (dist/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    (dist/'sets').mkdir(exist_ok=True)
    for item in catalog['sets']:
        (dist/item['page']).write_text(render_session(item),encoding='utf-8')
    (dist/'.nojekyll').write_text('',encoding='utf-8')
    return catalog,media


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--static',action='store_true',help='Build for static hosting (all builds include audio in dist/media).')
    args=parser.parse_args()
    catalog,_=build(args.static)
    print(f"Built {len(catalog['sets'])} complete audio sets; {len(catalog['incompleteFolders'])} incomplete folders excluded.")
    print(DIST)
