import {matchQuestion,SessionProgress,tokenize} from './engine.js';
import {BrowserSpeech,MicrophoneMonitor,deviceCapabilities,recognitionReason,exclusiveSpeechCapture} from './speech.js';
import {initPrivacy,preferenceStorage,readDeviceSettings} from './privacy.js';
import {DeviceSetup,MODES,savedModeCanSkip} from './devices.js';

const ROOT=new URL('../',import.meta.url);
const $=id=>document.getElementById(id);
const hide=(id,yes)=>{$(id).hidden=yes;};
async function boot() {initPrivacy();try {
  const response=await fetch(new URL('catalog.json',ROOT),{cache:'no-store'});
  if(!response.ok)throw new Error(`Audio catalog returned ${response.status}`);
  const catalog=await response.json();
  const params=new URLSearchParams(location.search);
  if(document.body.dataset.page==='library')showLibrary(catalog);
  else if(document.body.dataset.page==='setup')new DeviceSetup(catalog.sets.find(s=>s.id===params.get('set')));
  else{
    const set=catalog.sets.find(s=>s.id===document.body.dataset.setId);
    const saved=readDeviceSettings();
    let settings=null;
    if(MODES.includes(params.get('mode'))){
      settings={mode:params.get('mode'),pause:(Number(params.get('pause'))>=500&&Number(params.get('pause'))<=5000)?Number(params.get('pause')):2500,
        volume:(Number(params.get('volume'))>=0.004&&Number(params.get('volume'))<=0.04)?Number(params.get('volume')):0.007,reason:params.get('reason')||'selected'};
    }else if(await savedModeCanSkip(saved))settings={...saved,reason:'remembered'};
    if(!settings){location.replace(new URL(`setup.html?set=${encodeURIComponent(document.body.dataset.setId)}`,ROOT).href);return;}
    new Practice(set,settings,catalog);
  }
} catch(error) {
  const target=$('catalogStatus')||$('errorMessage');
  if(target){target.textContent=`The audio sets could not be loaded. ${error.message}`;target.hidden=false;}
}}

function showLibrary(data) {
  const cards=[...$('sessionCards').querySelectorAll('[data-set-id]')];
  const editions=[...$('edition').options].map(option=>option.value);
  let saved=preferenceStorage.getItem('conversation-lab:edition')||'edited';
  if(editions.includes(saved))$('edition').value=saved;
  function render(){
    preferenceStorage.setItem('conversation-lab:edition',$('edition').value);
    let visible=0;
    for(const card of cards){
      card.hidden=card.dataset.edition!==$('edition').value;
      if(!card.hidden)visible++;
      const set=data.sets.find(set=>set.id===card.dataset.setId);
      if(!set)continue;
      const progress=new SessionProgress(set);
      const sub=progress.complete?'Completed':progress.index?`Continue ${progress.index}/${set.steps.length} done`:'Begin conversation';
      card.querySelector('[data-progress]').textContent=sub;
    }
    hide('emptyLibrary',visible>0);
  }
  $('edition').addEventListener('change',render);render();
  window.addEventListener('storagechoice',render);
  $('edition').disabled=false;
  $('catalogStatus').textContent=`${data.sets.length} complete audio sets`;
}

class Practice {
  constructor(set,settings,catalog) {
    if(!set)throw new Error('This audio set is unavailable. Return to the library.');
    this.set=set;this.progress=new SessionProgress(set);this.state='idle';this.audio=$('answerAudio');
    this.transcript='';this.lastLexical='';this.lastTextTime=0;this.lastVoiceTime=0;this.speechHeard=false;
    this.threshold=0.58;this.pauseMs=800;this.fallbackPauseMs=2500;this.requiredPercent=45;this.logs=[];this.playEpoch=0;this.closed=false;
    this.checked=true;this.mode=settings.mode;this.voicedMs=0;this.capabilities=deviceCapabilities();
    this.reason=settings.reason==='working'?'Speech transcription passed the device check.':settings.reason==='remembered'?'Using the mode saved in your settings cookie. Microphone access is checked when you start.':settings.reason==='selected'?'You chose this mode on the setup screen.':recognitionReason(settings.reason);
    this.fallbackPauseMs=settings.pause;
    this.deviceNotes=[];this.questionAudio=$('questionAudio');
    this.speech=new BrowserSpeech({onText:r=>this.onText(r),onError:e=>this.onRecognitionError(e),
      onReady:()=>{this.log('Speech transcription started');},
      onSpeech:active=>{if(this.state==='listening'&&!this.monitor.available){this.nativeSpeaking=active;if(active){this.lastVoiceTime=performance.now();this.speechHeard=true;this.updateSpeechIndicator();}}}});
    this.monitor=new MicrophoneMonitor(level=>this.showLevel(level),(now,elapsed)=>{
      if(this.state==='listening'){this.lastVoiceTime=now;this.speechHeard=true;this.voicedMs+=elapsed;}
    },message=>{if(this.state==='listening'){this.pause();this.error(message);}});
    this.monitor.minimum=settings.volume;
    $('fallbackSilenceSetting').value=settings.pause;$('volumeSetting').value=settings.volume;
    $('sessionTitle').textContent=set.title;$('sessionEyebrow').textContent=`VIGNETTE ${set.vignette} GUIDED CONVERSATION`;
    $('totalQuestions').textContent=set.steps.length;$('voiceLabel').textContent=set.voice==='af_heart'?'Heart female':set.voice;
    $('editionLabel').textContent=set.editionLabel;
    $('startButton').addEventListener('click',()=>this.start());
    $('hearQuestionButton').addEventListener('click',()=>this.previewQuestion());
    $('pauseButton').addEventListener('click',()=>this.pause());
    $('finishButton').addEventListener('click',()=>this.finish(true));
    $('resumeAudioButton').addEventListener('click',()=>this.playAnswer());
    $('debugToggle').addEventListener('click',()=>{
      const open=$('debugPanel').hidden;hide('debugPanel',!open);$('debugToggle').setAttribute('aria-expanded',String(open));
    });
    $('speakingPercentSetting').addEventListener('input',()=>{this.requiredPercent=Number($('speakingPercentSetting').value);this.updateVoiceProgress();});
    $('silenceSetting').addEventListener('change',()=>this.pauseMs=Number($('silenceSetting').value));
    $('fallbackSilenceSetting').addEventListener('input',()=>{this.fallbackPauseMs=Number($('fallbackSilenceSetting').value);this.updateVoiceProgress();});
    $('volumeSetting').addEventListener('input',()=>{this.monitor.minimum=Number($('volumeSetting').value);this.updateVoiceProgress();});
    $('matchSetting').addEventListener('change',()=>{this.threshold=Number($('matchSetting').value);this.updateMatch();});
    $('restartButton').addEventListener('click',()=>{
      if(!confirm('Start a new attempt? This clears progress for this conversation on this browser.'))return;
      this.progress.reset();location.reload();
    });
    this.timer=setInterval(()=>this.tick(),80);
    window.addEventListener('pagehide',()=>this.close());
    document.addEventListener('visibilitychange',()=>{if(document.hidden){if(this.state==='listening')this.pause();if(this.state==='previewing')this.stopPreview();}});
    this.answerVariants=catalog.sets.filter(item=>item.edition===set.edition&&item.source===set.source&&item.version===set.version);
    $('settingsToggle').addEventListener('click',()=>{const open=$('settingsPanel').hidden;hide('settingsPanel',!open);$('settingsToggle').setAttribute('aria-expanded',String(open));});
    $('answerVoiceSelect').addEventListener('change',()=>this.chooseAnswerVoice($('answerVoiceSelect').value));
    this.chooseAnswerVoice(preferenceStorage.getItem('conversation-lab:answerVoice')||'af_heart');
    this.renderQuestion();this.setState(this.progress.complete?'complete':'idle');
    this.selectMode(this.mode,this.reason);
    if(new URLSearchParams(location.search).has('debug'))$('debugToggle').click();
  }

  chooseAnswerVoice(voice){
    const variant=this.answerVariants.find(item=>item.voice===voice)||this.set;
    this.set=variant;this.progress.set=variant;
    $('answerVoiceSelect').value=variant.voice;
    preferenceStorage.setItem('conversation-lab:answerVoice',variant.voice);
    $('voiceLabel').textContent=variant.voice.replace(/^[a-z]{2}_/,'');
    $('answerVoiceStatus').textContent=`Answer voice: ${variant.voice.replace(/^[a-z]{2}_/,'')}. Pending voices appear after generation and a page refresh.`;
    this.preloadNext();
  }

  log(message){this.logs.unshift(`${new Date().toLocaleTimeString()}  ${message}`);this.logs=this.logs.slice(0,16);$('eventLog').textContent=this.logs.join('\n');}
  error(message){$('errorMessage').textContent=message;hide('errorMessage',!message);}

  selectMode(mode,reason){
    this.mode=mode;this.reason=reason;
    const names={transcription:'Speech transcription · word highlighting',volume:'Voice timing · speaking progress bar',manual:'Manual · tap when finished'};
    $('modeStatus').textContent=names[mode];
    hide('voiceProgress',mode!=='volume');hide('speakingSettings',mode!=='volume');
    if(mode!=='transcription')for(const word of $('questionText').querySelectorAll('.heard'))word.classList.remove('heard');
    this.showDiagnostics();this.updateVoiceProgress();
  }

  updateSpeechIndicator(){
    const waiting=this.state==='listening'&&this.mode==='transcription'&&!this.speechHeard;
    $('statusPill').dataset.speechDetected=waiting?'pending':this.state==='listening'&&this.mode==='transcription'?'detected':'idle';
  }

  showDiagnostics(){
    $('recognitionReason').textContent=this.reason;
    $('deviceReport').textContent=[
      `Connection: ${this.capabilities.secure?'secure (HTTPS or localhost)':'insecure: microphone access needs HTTPS'}`,
      `Microphone API: ${this.capabilities.microphone?'available':'unavailable'}`,
      `Volume monitoring API: ${this.capabilities.volume?'available':'unavailable'}`,
      `Transcription API: ${this.capabilities.transcription?'available (service also needs to work)':'unavailable'}`,
      `WAV playback: ${this.capabilities.playback?'supported':'not reported'}`,
      `Selected mode: ${this.mode}`,...this.deviceNotes
    ].join('\n');
  }

  updateVoiceProgress(){
    $('volumeValue').textContent=this.monitor.minimum.toFixed(3);$('silenceValue').textContent=`${this.fallbackPauseMs/1000} seconds`;$('speakingPercentValue').textContent=`${this.requiredPercent}%`;
    document.querySelector('.voice-target').style.left=`${this.requiredPercent}%`;
    const seconds=this.progress.current?.questionAudio?.duration;
    if(seconds)$('questionTiming').textContent=`TTS: ${seconds.toFixed(1)}s | ${this.requiredPercent}% target: ${(seconds*this.requiredPercent/100).toFixed(1)}s`;
    $('fallbackSilenceSetting').setAttribute('aria-valuetext',`${this.fallbackPauseMs/1000} seconds`);
    $('speakingPercentSetting').setAttribute('aria-valuetext',`${this.requiredPercent}%`);
    if(this.mode==='volume'&&this.state==='listening')$('hint').textContent=`Reach ${this.requiredPercent}% speaking time, then pause for ${this.fallbackPauseMs/1000} seconds.`;
    const percent=seconds?Math.min(100,this.voicedMs/(seconds*1000)*100):0;
    $('voiceProgressFill').style.width=`${percent}%`;
    $('voiceProgressBar').setAttribute('aria-valuenow',String(Math.round(percent)));
    $('voiceProgressLabel').textContent=`${Math.round(percent)}%`;
    $('voiceProgressHint').textContent=seconds?`Speak above the volume threshold to fill the bar. Reach ${this.requiredPercent}%, then pause for ${this.fallbackPauseMs/1000} seconds. ${ (this.voicedMs/1000).toFixed(1)} / ${seconds.toFixed(1)} seconds spoken.`:'Question TTS timing is unavailable. Use “I’m finished” after reading.';
  }

  previewQuestion(){
    if(this.state==='previewing'){this.stopPreview();return;}
    if(!['idle','paused','listening'].includes(this.state))return;
    const clip=this.progress.current?.questionAudio;
    if(!clip){this.error('Question audio is unavailable. Rebuild the question recordings.');return;}
    if(this.state==='listening')this.pause();
    this.previewPrevious=this.state;this.speech.stop();this.setState('previewing');
    this.questionAudio.src=new URL(clip.url,ROOT).href;
    this.questionAudio.onended=()=>this.stopPreview();
    this.questionAudio.onerror=()=>{this.stopPreview();this.error('The question recording could not be played.');};
    const playing=this.questionAudio.play();
    playing?.catch(error=>{this.stopPreview();this.error(`Question playback needs another tap: ${error.message}`);});
  }

  stopPreview(){this.questionAudio.pause();this.questionAudio.onended=null;this.questionAudio.onerror=null;if(this.state==='previewing')this.setState(this.previewPrevious||'idle');}

  setState(state) {
    $('answerVoiceSelect').disabled=['playing','preparing','blocked'].includes(state);
    this.state=state;$('debugPhase').textContent=state;
    const names={idle:'Ready',checking:'Checking device',previewing:'Question preview',preparing:'Preparing',listening:'Listening',paused:'Paused',playing:'Answer playing',blocked:'Ready to play',complete:'Complete'};
    $('statusText').textContent=names[state]||state;$('statusPill').dataset.state=state;this.updateSpeechIndicator();
    hide('startButton',!['idle','paused'].includes(state));$('startButton').disabled=!this.checked;
    $('hearQuestionButton').disabled=!['idle','paused','listening','previewing'].includes(state);
    $('hearQuestionButton').textContent=state==='previewing'?'Stop question preview':'Hear this question';
    $('startButtonLabel').textContent=state==='paused'?'Continue listening':this.progress.index?'Continue conversation':'Start conversation';
    hide('pauseButton',state!=='listening');hide('finishButton',state!=='listening');hide('resumeAudioButton',state!=='blocked');
    hide('answerPlayback',!['playing','blocked'].includes(state));
    if(state==='playing'){$('hint').textContent='Listen to the answer. The next question follows automatically.';$('cardLabel').textContent='LISTEN TO THE RESPONSE';}
    else if(state==='listening'){$('hint').textContent=this.mode==='volume'?`Read aloud until the bar reaches ${this.requiredPercent}%, then pause for ${this.fallbackPauseMs/1000} seconds.`:this.mode==='manual'?'Read the question, then tap “I’m finished”.':'Finish your question, then leave a short pause.';$('cardLabel').textContent='READ ALOUD';}
    else if(state==='paused')$('hint').textContent="Take your time. Continue when you're ready.";
    if(state==='complete')this.showComplete();
  }

  renderQuestion() {
    this.voicedMs=0;
    const step=this.progress.current;
    $('progressFill').style.width=`${this.progress.index/this.set.steps.length*100}%`;
    $('progressLabel').textContent=`${this.progress.index} completed`;
    if(!step)return;
    $('stepLabel').textContent=`Question ${this.progress.index+1} of ${this.set.steps.length}`;
    for(const question of $('questionText').children){
      question.hidden=question.dataset.questionId!==step.id;
      for(const word of question.querySelectorAll('[data-word]'))word.classList.remove('heard');
    }
    for(const context of $('questionContext').children)context.hidden=context.dataset.questionId!==step.id;
    hide('contextDetails',!step.context.length);$('contextDetails').open=false;
    $('transcript').textContent='No speech yet.';$('matchScore').textContent='0%';$('tailScore').textContent=':';
    const timing=step.questionAudio?.duration;
    $('questionTiming').textContent=timing?`TTS: ${timing.toFixed(1)}s · ${this.requiredPercent}% target: ${(timing*this.requiredPercent/100).toFixed(1)}s`:'TTS timing unavailable';
    $('hearQuestionButton').hidden=!step.questionAudio;
    this.updateVoiceProgress();
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
    this.audio.onended=null;this.audio.onplaying=null;this.audio.onerror=null;this.audio.ontimeupdate=null;this.audio.src=url;
    let timeout;
    try{
      await Promise.race([this.audio.play(),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new Error('Audio playback timed out')),4000);})]);
      this.audio.pause();return true;
    }catch{return false;}
    finally{clearTimeout(timeout);URL.revokeObjectURL(url);}
  }

  async start() {
    if(!['idle','paused'].includes(this.state)||!this.checked)return;
    const continuing=this.state==='paused';this.setState('preparing');$('startButton').disabled=true;this.error('');
    // Keep audio, microphone resume, and recognition within the user's tap.
    const nativePhone=this.mode==='transcription'&&exclusiveSpeechCapture();
    // Native phone recognition owns the microphone. Do not open getUserMedia or
    // play/pause a silent media element while that recognition session starts.
    const audioReady=nativePhone?Promise.resolve(true):this.primeAudio();
    const microphoneReady=this.mode==='manual'||nativePhone?Promise.resolve():this.monitor.start();
    if(this.mode==='transcription')this.speech.start(this.transcript);
    const [,microphone]=await Promise.allSettled([audioReady,microphoneReady]);
    if(microphone.status==='rejected'){
      this.error(`Microphone unavailable: ${microphone.reason.message}`);
      if(this.mode==='volume')this.selectMode('manual','The microphone could not resume. Tap “I’m finished” after reading.');
    }
    const track=this.monitor.stream?.getAudioTracks?.()[0];
    if(track){this.deviceNotes=[`Active microphone: ${track.label||'not reported'}`,`Input sample rate: ${track.getSettings?.().sampleRate||'not reported'} Hz`];this.showDiagnostics();}
    if(this.closed)return;
    if(this.progress.current&&this.progress.asked.has(this.progress.current.id)){this.playAnswer();return;}
    this.listen(continuing,true);
  }

  listen(continuing=false,recognitionStarted=false) {
    if(this.progress.complete){this.setState('complete');return;}
    if(!continuing){this.transcript='';this.lastLexical='';this.speechHeard=false;this.match=null;this.voicedMs=0;}
    this.lastVoiceTime=performance.now();this.lastTextTime=this.lastVoiceTime;this.nativeSpeaking=false;
    this.listeningSince=performance.now();
    this.setState('listening');
    if(this.mode==='transcription'&&!recognitionStarted)this.speech.start(this.transcript);
    this.log(`Listening: question ${this.progress.index+1} (${this.mode})`);
  }

  onRecognitionError(code) {
    this.speech.stop();
    if(exclusiveSpeechCapture()&&!this.monitor.available&&!this.closed){
      const reason=recognitionReason(code);
      this.selectMode('manual',reason+' Starting microphone timing fallback.');
      this.monitor.start().then(()=>{
        if(this.closed)return;
        this.selectMode('volume',reason);
        if(this.state==='listening')this.setState('listening');
      }).catch(error=>{if(!this.closed){this.selectMode('manual',reason+' '+error.message);this.error(error.message);}});
      this.log(`Recognition: ${code}`);return;
    }
    this.selectMode(this.monitor.available?'volume':'manual',recognitionReason(code));
    if(this.state==='listening')this.setState('listening');
    this.log(`Recognition: ${code}`);
  }

  onText(result) {
    if(this.state!=='listening'||this.mode!=='transcription')return;
    this.transcript=result.text;this.transcriptFinal=result.isFinal;
    const lexical=tokenize(result.text).map(t=>t.word).join(' ');
    if(lexical!==this.lastLexical){this.lastLexical=lexical;this.lastTextTime=performance.now();}
    if(lexical){this.speechHeard=true;if(!this.monitor.available)this.lastVoiceTime=this.lastTextTime;this.updateSpeechIndicator();}
    $('transcript').textContent=result.text||'No speech yet.';$('transcript').dataset.interim=String(!result.isFinal);
    this.updateMatch();
  }

  updateMatch() {
    if(!this.progress.current||this.mode!=='transcription')return;
    this.match=matchQuestion(this.progress.current.prompt,this.transcript,this.threshold);
    for(const span of $('questionText').querySelectorAll('[data-question-id]:not([hidden]) [data-word]'))span.classList.toggle('heard',this.match.matched.has(Number(span.dataset.word)));
    $('matchScore').textContent=`${Math.round(this.match.coverage*100)}%`;$('tailScore').textContent=this.match.ending?'Yes':'Not yet';
  }

  tick() {
    if(this.state!=='listening')return;
    const now=performance.now(),quiet=now-this.lastVoiceTime;
    $('quietTime').textContent=`${Math.max(0,Math.round(quiet))} ms`;
    if(this.mode==='volume'){
      this.updateVoiceProgress();
      const duration=this.progress.current?.questionAudio?.duration;
      if(duration&&this.monitor.available&&this.speechHeard&&this.voicedMs>=duration*1000*this.requiredPercent/100&&quiet>=this.fallbackPauseMs)this.finish(false);
    }else if(this.mode==='transcription'&&this.match?.ready&&this.speechHeard&&quiet>=this.pauseMs&&
       (this.transcriptFinal||now-this.lastTextTime>=180)&&(!this.nativeSpeaking||this.monitor.available))this.finish(false);
  }

  finish(manual) {
    const timedReady=this.mode==='volume'&&this.progress.current?.questionAudio?.duration&&this.voicedMs>=this.progress.current.questionAudio.duration*1000*this.requiredPercent/100;
    if(this.state!=='listening'||(!manual&&!(this.mode==='transcription'?this.match?.ready:timedReady)))return;
    if(!this.progress.markAsked())return;
    this.setState('preparing');this.speech.stop();this.showLevel(0);
    this.log(`Question accepted (${manual?'manual':this.mode==='volume'?'voice timing':Math.round(this.match.coverage*100)+'% match'})`);
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
    this.nextTimer=setTimeout(async()=>{
      if(this.closed)return;
      this.renderQuestion();
      if(this.mode!=='manual'&&this.monitor.available){
        try{await this.monitor.start();}
        catch(error){this.setState('paused');this.error(error.message);return;}
      }
      if(!this.closed){
        if(document.hidden){this.setState('paused');return;}
        this.listen(false);
      }
    },420);
  }

  pause(){if(this.state!=='listening')return;this.speech.stop();this.setState('paused');this.showLevel(0);}

  showLevel(value){const count=['checking','idle','paused','listening'].includes(this.state)?Math.round(value*9):0;[...$('levelMeter').children].forEach((bar,i)=>bar.classList.toggle('active',i<count));}

  showComplete(){
    hide('completion',false);document.querySelector('.question-card').hidden=true;
    $('stepLabel').textContent='All questions complete';$('progressLabel').textContent=`${this.set.steps.length} completed`;$('progressFill').style.width='100%';
    $('completionSummary').textContent=`You completed ${this.set.steps.length} questions and ${this.set.answerCount} answer recordings, in order.`;
    this.speech.stop();this.monitor.close();this.log('Conversation complete');
  }

  close(){this.closed=true;clearInterval(this.timer);clearTimeout(this.nextTimer);this.playEpoch++;this.probe?.stop();this.speech.stop();this.audio.pause();this.questionAudio.pause();this.monitor.close();}
}

boot();
