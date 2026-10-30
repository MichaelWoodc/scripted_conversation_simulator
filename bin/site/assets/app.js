import {matchQuestion,SessionProgress,tokenize} from './engine.js';
import {BrowserSpeech,MicrophoneMonitor} from './speech.js';

const ROOT=new URL('../',import.meta.url);
const $=id=>document.getElementById(id);
const hide=(id,yes)=>{$(id).hidden=yes;};
const escape=text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const minutes=seconds=>`${Math.max(1,Math.round(seconds/60))} min`;
async function boot() {try {
  const response=await fetch(new URL('catalog.json',ROOT),{cache:'no-store'});
  if(!response.ok)throw new Error(`Audio catalog returned ${response.status}`);
  const catalog=await response.json();
  if(document.body.dataset.page==='library')showLibrary(catalog);
  else new Practice(catalog.sets.find(s=>s.id===document.body.dataset.setId));
} catch(error) {
  const target=$('sessionCards')||$('questionText');
  if(target)target.textContent=`The audio sets could not be loaded. ${error.message}`;
}}

function showLibrary(data) {
  const editions=[...new Map(data.sets.map(s=>[s.edition,s.editionLabel])).entries()];
  for(const [id,label] of editions){const option=new Option(label,id);$('edition').add(option);}
  let saved='edited';try{saved=localStorage.getItem('conversation-lab:edition')||saved;}catch{}
  if(editions.some(([id])=>id===saved))$('edition').value=saved;
  function render(){
    try{localStorage.setItem('conversation-lab:edition',$('edition').value);}catch{}
    const sets=data.sets.filter(s=>s.edition===$('edition').value);
    $('sessionCards').replaceChildren();
    for(const set of sets){
      const progress=new SessionProgress(set),card=document.createElement('a');
      card.className='session-card';card.href=new URL(set.page,ROOT).href;
      const sub=progress.complete?'Completed':progress.index?`Continue ${progress.index}/${set.steps.length} done`:'Begin conversation';
      card.innerHTML=`<div class="session-card-top"><span class="chapter-number">0${set.vignette}</span><span class="card-tag">Vignette ${set.vignette}</span></div><h3>${escape(set.title)}</h3><p class="card-description">${set.steps.length} questions ${escape(set.voice.replace('af_',''))} voice<br>${minutes(set.duration)}</p><div class="card-bottom"><span>${escape(sub)}</span><span class="round-arrow">↗</span></div>`;
      $('sessionCards').append(card);
    }
    if(!sets.length)$('sessionCards').textContent='No complete audio sets are ready yet.';
  }
  $('edition').addEventListener('change',render);render();
  $('catalogStatus').textContent=`${data.sets.length} complete audio sets`;
}

class Practice {
  constructor(set) {
    if(!set)throw new Error('This audio set is unavailable. Return to the library.');
    this.set=set;this.progress=new SessionProgress(set);this.state='idle';this.audio=$('answerAudio');
    this.transcript='';this.lastLexical='';this.lastTextTime=0;this.lastVoiceTime=0;this.speechHeard=false;
    this.threshold=0.58;this.pauseMs=800;this.logs=[];this.playEpoch=0;this.closed=false;
    this.speech=new BrowserSpeech({onText:r=>this.onText(r),onError:e=>this.onRecognitionError(e),
      onSpeech:active=>{if(this.state==='listening'&&!this.monitor.available){this.nativeSpeaking=active;if(active){this.lastVoiceTime=performance.now();this.speechHeard=true;}}}});
    this.monitor=new MicrophoneMonitor(level=>this.showLevel(level),now=>{
      if(this.state==='listening'){this.lastVoiceTime=now;this.speechHeard=true;}
    });
    $('sessionTitle').textContent=set.title;$('sessionEyebrow').textContent=`VIGNETTE ${set.vignette} GUIDED CONVERSATION`;
    $('totalQuestions').textContent=set.steps.length;$('voiceLabel').textContent=set.voice==='af_heart'?'Heart female':set.voice;
    $('editionLabel').textContent=set.editionLabel;
    $('startButton').addEventListener('click',()=>this.start());
    $('pauseButton').addEventListener('click',()=>this.pause());
    $('finishButton').addEventListener('click',()=>this.finish(true));
    $('resumeAudioButton').addEventListener('click',()=>this.playAnswer());
    $('debugToggle').addEventListener('click',()=>{
      const open=$('debugPanel').hidden;hide('debugPanel',!open);$('debugToggle').setAttribute('aria-expanded',String(open));
    });
    $('silenceSetting').addEventListener('change',()=>this.pauseMs=Number($('silenceSetting').value));
    $('matchSetting').addEventListener('change',()=>{this.threshold=Number($('matchSetting').value);this.updateMatch();});
    $('restartButton').addEventListener('click',()=>{
      if(!confirm('Start a new attempt? This clears progress for this conversation on this browser.'))return;
      this.progress.reset();location.reload();
    });
    this.timer=setInterval(()=>this.tick(),80);
    window.addEventListener('pagehide',()=>this.close());
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&this.state==='listening')this.pause();});
    this.renderQuestion();this.setState(this.progress.complete?'complete':'idle');
    if(new URLSearchParams(location.search).has('debug'))$('debugToggle').click();
  }

  log(message){this.logs.unshift(`${new Date().toLocaleTimeString()}  ${message}`);this.logs=this.logs.slice(0,16);$('eventLog').textContent=this.logs.join('\n');}
  error(message){$('errorMessage').textContent=message;hide('errorMessage',!message);}

  setState(state) {
    this.state=state;$('debugPhase').textContent=state;
    const names={idle:'Ready',preparing:'Preparing',listening:'Listening',paused:'Paused',playing:'Answer playing',blocked:'Ready to play',complete:'Complete'};
    $('statusText').textContent=names[state]||state;$('statusPill').dataset.state=state;
    hide('startButton',!['idle','paused'].includes(state));$('startButton').disabled=false;
    $('startButton').innerHTML=state==='paused'?'Continue listening <span>→</span>':this.progress.index?'Continue conversation <span>→</span>':'Start conversation <span>→</span>';
    hide('pauseButton',state!=='listening');hide('finishButton',state!=='listening');hide('resumeAudioButton',state!=='blocked');
    hide('answerPlayback',!['playing','blocked'].includes(state));
    if(state==='playing'){$('hint').textContent='Listen to the answer. The next question follows automatically.';$('cardLabel').textContent='LISTEN TO THE RESPONSE';}
    else if(state==='listening'){$('hint').textContent='Speak naturally. Finish your question, then leave a short pause.';$('cardLabel').textContent='READ ALOUD';}
    else if(state==='paused')$('hint').textContent="Take your time. Continue when you're ready.";
    if(state==='complete')this.showComplete();
  }

  renderQuestion() {
    const step=this.progress.current;
    $('progressFill').style.width=`${this.progress.index/this.set.steps.length*100}%`;
    $('progressLabel').textContent=`${this.progress.index} completed`;
    if(!step)return;
    $('stepLabel').textContent=`Question ${this.progress.index+1} of ${this.set.steps.length}`;
    const target=$('questionText');target.replaceChildren();let cursor=0;
    for(const [index,token] of tokenize(step.prompt).entries()){
      target.append(document.createTextNode(step.prompt.slice(cursor,token.start)));
      const span=document.createElement('span');span.dataset.word=String(index);span.textContent=token.raw;target.append(span);cursor=token.end;
    }
    target.append(document.createTextNode(step.prompt.slice(cursor)));
    $('questionContext').textContent=step.context.join('\n\n');hide('contextDetails',!step.context.length);$('contextDetails').open=false;
    $('transcript').textContent='No speech yet.';$('matchScore').textContent='0%';$('tailScore').textContent='—';
    this.preloadNext();
  }

  preloadNext() {
    const step=this.progress.current;if(!step)return;
    this.preloaded=new Audio(new URL(step.clips[0].url,ROOT).href);this.preloaded.preload='auto';this.preloaded.load();
  }

  async primeAudio() {
    // A silent, user-initiated play unlocks subsequent answer playback where supported.
    const bytes=new Uint8Array(44+1600);const view=new DataView(bytes.buffer);
    function str(offset,text){for(let i=0;i<text.length;i++)bytes[offset+i]=text.charCodeAt(i);}
    str(0,'RIFF');view.setUint32(4,bytes.length-8,true);str(8,'WAVE');str(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,8000,true);view.setUint32(28,16000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,1600,true);
    const url=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
    this.audio.onended=null;this.audio.onplaying=null;this.audio.src=url;
    try{await this.audio.play();this.audio.pause();}catch{}
    URL.revokeObjectURL(url);
  }

  async start() {
    if(!['idle','paused'].includes(this.state))return;
    const continuing=this.state==='paused';this.setState('preparing');$('startButton').disabled=true;this.error('');
    await this.primeAudio();
    try{await this.monitor.start();}
    catch(error){this.error(`Microphone unavailable: ${error.message}. Allow microphone access, or use “I'm finished” after reading.`);}
    if(this.closed)return;
    if(this.progress.current&&this.progress.asked.has(this.progress.current.id)){this.playAnswer();return;}
    this.listen(continuing);
  }

  listen(continuing=false) {
    if(this.progress.complete){this.setState('complete');return;}
    if(!continuing){this.transcript='';this.lastLexical='';this.speechHeard=false;this.match=null;}
    this.lastVoiceTime=performance.now();this.lastTextTime=this.lastVoiceTime;this.nativeSpeaking=false;
    this.setState('listening');this.speech.start(this.transcript);this.log(`Listening: question ${this.progress.index+1}`);
  }

  onRecognitionError(code) {
    const descriptions={unsupported:'This browser does not expose speech recognition. Try Chrome or Edge.',
      'not-allowed':"Microphone permission was denied. Allow it in the browser's address bar.",
      'service-not-allowed':"The browser's speech service is unavailable. Try Chrome or Edge.",
      network:'The speech service could not connect. Check the connection or try another browser.',
      'audio-capture':'The microphone could not be opened.'};
    this.error(`${descriptions[code]||`Speech recognition stopped (${code}).`} You can use “I'm finished” to continue manually.`);
    this.log(`Recognition: ${code}`);
  }

  onText(result) {
    if(this.state!=='listening')return;
    this.transcript=result.text;this.transcriptFinal=result.isFinal;
    const lexical=tokenize(result.text).map(t=>t.word).join(' ');
    if(lexical!==this.lastLexical){this.lastLexical=lexical;this.lastTextTime=performance.now();}
    if(lexical){this.speechHeard=true;if(!this.monitor.available)this.lastVoiceTime=this.lastTextTime;}
    $('transcript').textContent=result.text||'No speech yet.';$('transcript').dataset.interim=String(!result.isFinal);
    this.updateMatch();
  }

  updateMatch() {
    if(!this.progress.current)return;
    this.match=matchQuestion(this.progress.current.prompt,this.transcript,this.threshold);
    for(const span of $('questionText').querySelectorAll('[data-word]'))span.classList.toggle('heard',this.match.matched.has(Number(span.dataset.word)));
    $('matchScore').textContent=`${Math.round(this.match.coverage*100)}%`;$('tailScore').textContent=this.match.ending?'Yes':'Not yet';
  }

  tick() {
    if(this.state!=='listening')return;
    const now=performance.now(),quiet=now-this.lastVoiceTime;
    $('quietTime').textContent=`${Math.max(0,Math.round(quiet))} ms`;
    if(this.match?.ready&&this.speechHeard&&quiet>=this.pauseMs&&
       (this.transcriptFinal||now-this.lastTextTime>=180)&&(!this.nativeSpeaking||this.monitor.available))this.finish(false);
  }

  finish(manual) {
    if(this.state!=='listening'||(!manual&&!this.match?.ready))return;
    if(!this.progress.markAsked())return;
    this.setState('preparing');this.speech.stop();this.showLevel(0);
    this.log(`Question accepted (${manual?'manual':Math.round(this.match.coverage*100)+'% match'})`);
    this.playAnswer();
  }

  async playAnswer() {
    if(!['preparing','blocked','playing'].includes(this.state))return;
    this.speech.stop();
    const clip=this.progress.remainingClips[0];
    if(!clip){this.completeQuestion();return;}
    const epoch=++this.playEpoch;let started=false;
    this.setState('playing');$('answerStatus').textContent='Playing the recorded answer';
    $('debugAudio').textContent=`Answer ${clip.index.toString().padStart(3,'0')} ${clip.url.split('?')[0]}`;
    this.audio.src=new URL(clip.url,ROOT).href;
    this.audio.onplaying=()=>{
      if(epoch!==this.playEpoch||started)return;
      started=true;
      if(!this.progress.markStarted(clip)){this.audio.pause();return;}
      this.log(`Started answer ${clip.index.toString().padStart(3,'0')} (once)`);
    };
    this.audio.ontimeupdate=()=>{
      const duration=this.audio.duration||clip.duration;
      $('audioProgress').style.width=`${Math.min(100,this.audio.currentTime/duration*100)}%`;
      $('audioTime').textContent=`${Math.ceil(Math.max(0,duration-this.audio.currentTime))}s`;
    };
    this.audio.onended=()=>{
      if(epoch!==this.playEpoch||this.state!=='playing')return;
      if(!started){this.audioFailure('Playback ended before it started.');return;}
      this.playAnswer();
    };
    this.audio.onerror=()=>{if(epoch===this.playEpoch)this.audioFailure('The answer file could not be played.');};
    try{await this.audio.play();}
    catch(error){if(epoch===this.playEpoch)this.audioFailure(error.name==='NotAllowedError'?'Your browser needs one click to play the answer.':`Playback stopped: ${error.message}`);}
  }

  audioFailure(message){this.setState('blocked');this.error(message);this.log(message);}

  completeQuestion() {
    if(!this.progress.advance())return;
    this.playEpoch++;this.audio.onended=null;this.audio.onplaying=null;
    this.setState('preparing');
    if(this.progress.complete){this.setState('complete');return;}
    // The microphone's words never include the answer; allow room echoes to decay.
    this.nextTimer=setTimeout(()=>{if(this.closed)return;this.renderQuestion();this.listen(false);},420);
  }

  pause(){if(this.state!=='listening')return;this.speech.stop();this.setState('paused');this.showLevel(0);}

  showLevel(value){const count=this.state==='listening'?Math.round(value*9):0;[...$('levelMeter').children].forEach((bar,i)=>bar.classList.toggle('active',i<count));}

  showComplete(){
    hide('completion',false);document.querySelector('.question-card').hidden=true;
    $('stepLabel').textContent='All questions complete';$('progressLabel').textContent=`${this.set.steps.length} completed`;$('progressFill').style.width='100%';
    $('completionSummary').textContent=`You completed ${this.set.steps.length} questions and ${this.set.answerCount} answer recordings, in order.`;
    this.speech.stop();this.monitor.close();this.log('Conversation complete');
  }

  close(){this.closed=true;clearInterval(this.timer);clearTimeout(this.nextTimer);this.playEpoch++;this.speech.stop();this.audio.pause();this.monitor.close();}
}

boot();
