import {BrowserSpeech,MicrophoneMonitor,deviceCapabilities,recognitionReason,exclusiveSpeechCapture} from './speech.js';
import {readDeviceSettings,saveDeviceSettings,deviceStorageAllowed} from './privacy.js';

const ROOT=new URL('../',import.meta.url);
const $=id=>document.getElementById(id);
export const MODES=['transcription','volume','manual'];

export function sessionURL(set,settings,reason='selected'){
  const url=new URL(set.page,ROOT);
  url.search=new URLSearchParams({mode:settings.mode,pause:String(settings.pause),volume:String(settings.volume),reason,deviceCheck:'1'});
  return url.href;
}

export async function savedModeCanSkip(settings){
  if(!settings||settings.skip===false)return false;
  if(settings.mode==='manual')return true;
  if(exclusiveSpeechCapture())return false;
  const caps=deviceCapabilities();
  if(!caps.secure||!caps.microphone||!caps.volume)return false;
  if(settings.mode==='transcription'&&!caps.transcription)return false;
  try{
    const permission=await navigator.permissions.query({name:'microphone'});
    if(permission.state==='denied')return false;
  }catch{} // Some browsers do not expose microphone permission queries.
  return true;
}

export class DeviceSetup {
  constructor(set){
    if(!set)throw new Error('Choose a conversation from the library first.');
    this.set=set;this.caps=deviceCapabilities();this.saved=readDeviceSettings();this.closed=false;
    const needsPhoneCheck=exclusiveSpeechCapture();
    this.speechOK=!needsPhoneCheck&&!!this.saved?.speechOK;this.speechStarted=false;this.checkedOnce=false;this.micOK=!needsPhoneCheck&&!!this.saved?.micOK;this.testWords=new Set();this.testMs=0;
    this.reasonCode=this.caps.transcription?'permission-needed':'unsupported';
    if(this.saved){this.speechReason=this.speechOK?'Previously verified. Tap Test to check again.':undefined;this.microphoneReason=this.micOK?'Previously verified microphone.':undefined;}
    $('setupSessionTitle').textContent=set.title;
    this.monitor=new MicrophoneMonitor(level=>{
      $('transcriptionLevel').value=level;$('timingLevel').value=level;
    },(now,elapsed)=>{
      this.testMs=Math.min(1000,this.testMs+elapsed);
      $('timingTestProgress').value=this.testMs;
      $('timingTestLabel').textContent=`${(this.testMs/1000).toFixed(1)} / 1 second${this.testMs>=1000?' — passed':''}`;
    },message=>{if(!this.closed)$('deviceStatus').textContent='Microphone paused. Tap Test to resume. Your previous test results are remembered.';});
    $('beginSetupButton').addEventListener('click',()=>{$('startGate').hidden=true;this.check();});
    for(const id of ['checkDeviceButton','retryTranscriptionButton','retryTimingButton'])$(id).addEventListener('click',()=>this.check(id==='retryTimingButton'));
    $('continueToSession').addEventListener('click',()=>this.continue());
    $('rememberDeviceSettings').addEventListener('change',()=>this.persist());
    $('volumeSetting').addEventListener('input',()=>{this.monitor.minimum=Number($('volumeSetting').value);this.persist();});
    $('fallbackSilenceSetting').addEventListener('input',()=>{this.showPause();this.persist();});
    for(const mode of MODES)$(mode+'Choice').addEventListener('change',()=>this.persist());
    $('setupDebugToggle').addEventListener('click',()=>{
      const open=$('setupDebug').hidden;$('setupDebug').hidden=!open;$('setupDebugToggle').setAttribute('aria-expanded',String(open));
    });
    window.addEventListener('storagechoice',()=>{
      if(deviceStorageAllowed())this.persist();
      else $('rememberDeviceSettings').checked=false;
    });
    window.addEventListener('pagehide',()=>{this.closed=true;this.probe?.stop();this.monitor.close();});
    if(this.saved){$('fallbackSilenceSetting').value=this.saved.pause;$('volumeSetting').value=this.saved.volume;$('rememberDeviceSettings').checked=this.saved.skip;}
    this.showPause();this.updateOptions();
    if(needsPhoneCheck){$('deviceStatus').textContent='Tap Test microphone and transcription. Allow microphone access if your browser prompts.';$('retryTranscriptionButton').hidden=true;$('retryTimingButton').hidden=true;}
    $('deviceSetup').dataset.ready='true';
    this.skipSaved();
  }

  showPause(){
    const seconds=Number($('fallbackSilenceSetting').value)/1000;
    $('setupSilenceValue').textContent=`${seconds.toFixed(1)} seconds`;
    $('fallbackSilenceSetting').setAttribute('aria-valuetext',`${seconds.toFixed(1)} seconds`);
  }

  async skipSaved(){
    if(new URLSearchParams(location.search).has('change'))return;
    if(await savedModeCanSkip(this.saved))location.replace(sessionURL(this.set,this.saved,'remembered'));
  }

  probeTranscription(){
    if(!this.caps.transcription)return Promise.resolve({ok:false,code:'unsupported'});
    return new Promise(resolve=>{
      const probe=new BrowserSpeech({
        onText:result=>{
          const words=(result.text.match(/[\p{L}\p{N}]+/gu)||[]).flatMap(word=>word==='123'?['1','2','3']:[word]);
          const lastWords=(result.text.match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu)||[]).slice(-20).join(' ');
          $('transcriptionPreview').value=lastWords;
          $('transcriptionPreview').scrollTop=$('transcriptionPreview').scrollHeight;
          const aliases={'1':'one','2':'two','3':'three',to:'two',too:'two'};
          for(const word of words)this.testWords.add(aliases[word.toLowerCase()]||word.toLowerCase());
          for(const span of document.querySelectorAll('[data-test-word]'))span.classList.toggle('heard',this.testWords.has(span.dataset.testWord));
          if(words.length){
            this.speechOK=true;this.speechStarted=true;this.micOK=true;this.reasonCode='working';this.speechReason=`Transcription verified. Heard: ${lastWords}`;
            $('deviceStatus').textContent=`Transcription passed. Heard: ${lastWords}`;
            this.updateOptions();this.persist();resolve({ok:true,text:lastWords});
          }
        },
        onReady:()=>{
          this.speechStarted=true;this.reasonCode='test-needed';
          this.speechReason='Transcription started. Say anything to test it.';
          this.updateOptions();resolve({ok:false,code:'test-needed'});
        },
        onError:code=>{
          if(!this.speechOK){this.speechStarted=false;this.reasonCode=code;this.speechReason=recognitionReason(code);$('deviceStatus').textContent=`Transcription unavailable: ${this.speechReason}`;this.updateOptions();this.persist();}
          resolve({ok:false,code});
        }
      });
      this.probe=probe;probe.start();
    });
  }

  async check(timingOnly=false){
    if(this.checking)return;
    this.checking=true;this.caps=deviceCapabilities();
    this.probe?.stop();this.testWords.clear();this.testMs=0;$('timingTestProgress').value=0;$('timingTestLabel').textContent='0.0 / 1 second';
    for(const span of document.querySelectorAll('[data-test-word]'))span.classList.remove('heard');
    for(const id of ['checkDeviceButton','retryTranscriptionButton','retryTimingButton','continueToSession'])$(id).disabled=true;
    $('deviceStatus').textContent='Checking your microphone and transcription. Allow access when your browser asks.';
    if(exclusiveSpeechCapture()){
      await this.checkMobile(timingOnly);
      return;
    }
    // Permission-sensitive APIs are all invoked by the visitor's tap.
    this.monitor.minimum=timingOnly||!this.caps.transcription?Number($('volumeSetting').value):0.004;
    const microphone=this.monitor.start();
    const speech=this.caps.secure?this.probeTranscription():Promise.resolve({ok:false,code:'SecurityError'});
    const [micResult,speechResult]=await Promise.allSettled([microphone,speech]);
    if(this.closed)return;
    this.checking=false;
    this.micOK=this.speechOK||(micResult.status==='fulfilled'&&this.monitor.available);
    this.speechOK=this.micOK&&this.speechOK&&speechResult.status==='fulfilled';
    this.reasonCode=this.speechOK?'working':speechResult.value?.code||'microphone-unavailable';
    this.microphoneReason=this.micOK?'Microphone connected.':micResult.reason?.message||'Microphone permission is needed.';
    this.speechReason=this.speechOK?'Transcription verified.':this.micOK&&speechResult.value?.code==='test-needed'?'Transcription started. Say anything to test it.':this.micOK?recognitionReason(this.reasonCode):'Microphone access is unavailable or needs permission.';
    this.checkedOnce=true;
    $('deviceStatus').textContent=this.micOK?'Microphone level is live. '+this.speechReason:this.microphoneReason+' Retry or continue manually.';
    this.updateOptions();
    this.persist();
    for(const id of ['checkDeviceButton','retryTranscriptionButton','retryTimingButton','continueToSession'])$(id).disabled=false;
  }

  async checkMobile(timingOnly){
    try{
      if(!this.caps.secure){this.speechOK=false;throw new Error('Microphone access requires HTTPS. Open the published HTTPS site on your phone.');}
      this.probe?.stop();this.monitor.minimum=timingOnly||!this.caps.transcription?Number($('volumeSetting').value):0.004;this.speechOK=false;
      const speech=this.caps.transcription&&!timingOnly?this.probeTranscription():Promise.resolve({ok:false,code:'unsupported'});
      const microphone=this.monitor.start();
      const [micResult,speechResult]=await Promise.allSettled([microphone,speech]);
      this.micOK=this.speechOK||(micResult.status==='fulfilled'&&this.monitor.available);
      this.microphoneReason=this.micOK?'Microphone connected.':micResult.reason?.message||'Microphone permission is needed.';
      if(!this.caps.transcription||timingOnly){this.speechOK=false;this.speechReason=recognitionReason(this.caps.transcription?'permission-needed':'unsupported');}
      else if(speechResult.status==='fulfilled'&&speechResult.value?.code&&speechResult.value.code!=='test-needed'&&!this.speechOK){
        this.reasonCode=speechResult.value.code;this.speechReason=recognitionReason(this.reasonCode);
      }
      this.checkedOnce=true;
      this.updateOptions();
      if(this.speechOK)$('deviceStatus').textContent=`Transcription passed. Heard: ${$('transcriptionPreview').value}`;
      else if(this.micOK)$('deviceStatus').textContent=this.caps.transcription&&!timingOnly
        ?`Microphone level is live. ${this.speechReason||'Waiting for speech recognition.'}`
        :'Microphone level is live. Timing mode is available.';
      else $('deviceStatus').textContent=`${this.microphoneReason} ${this.speechReason||''}`.trim();
      this.persist();
    }catch(error){
      this.microphoneReason=error.message;this.micOK=false;
      $('deviceStatus').textContent=error.message+' Retry or continue manually.';
    }finally{
      if(!this.closed){
        this.checking=false;this.updateOptions();this.persist();
        for(const id of ['checkDeviceButton','retryTranscriptionButton','retryTimingButton','continueToSession'])$(id).disabled=false;
      }
    }
  }

  updateOptions(){
    const speechAvailable=this.caps.transcription&&this.micOK&&(this.speechOK||this.speechStarted);
    const transcriptionCandidate=this.caps.transcription&&(!this.checkedOnce||speechAvailable||this.speechOK);
    const timingCandidate=this.micOK||(!this.checkedOnce&&this.caps.microphone&&this.caps.volume);
    const preferred=transcriptionCandidate?'transcription':timingCandidate?'volume':'manual';
    for(const mode of MODES){
      const available=mode==='manual'||(mode==='transcription'?transcriptionCandidate:timingCandidate);
      const row=$(mode+'Option');
      row.dataset.availability=mode===preferred?'recommended':available?'available':'unavailable';
      $(mode+'Choice').disabled=!available;
      $(mode+'Choice').checked=mode===preferred;
      $(mode+'Badge').textContent=mode===preferred?'Recommended':available?'Available':'Unavailable';
    }
    $('transcriptionDetail').textContent=this.speechReason||(this.caps.transcription?'Test the microphone and say anything to verify transcription.':recognitionReason('unsupported'));
    $('volumeDetail').textContent=this.micOK?'Microphone verified. Fill the bar by speaking.':this.microphoneReason||'Microphone permission needed.';
    $('retryTranscriptionButton').hidden=exclusiveSpeechCapture();
    $('retryTimingButton').hidden=exclusiveSpeechCapture();
    $('deviceReport').textContent=[
      `Secure connection: ${this.caps.secure?'yes':'no — open the HTTPS site on your phone'}`,
      `Microphone API: ${this.caps.microphone?'available':'unavailable'}`,
      `Volume monitoring API: ${this.caps.volume?'available':'unavailable'}`,
      `Transcription API: ${this.caps.transcription?'available':'unavailable'}`,
      `Phone capture: ${exclusiveSpeechCapture()?'exclusive microphone, short recognition sessions':'desktop capture'}`,
      `Browser: ${navigator.userAgent}`,
      `Microphone test: ${this.micOK?'passed':'permission needed or unavailable'}`,
      `Transcription test: ${this.speechOK?'passed':this.speechReason||'not checked'}`,
      `Active microphone: ${this.monitor.stream?.getAudioTracks?.()[0]?.label||'not reported'}`
    ].join('\n');
  }

  continue(){
    const mode=document.querySelector('input[name="practiceMode"]:checked')?.value||'manual';
    const settings={mode,pause:Number($('fallbackSilenceSetting').value),volume:Number($('volumeSetting').value)};
    this.persist();
    this.probe?.stop();this.monitor.close();
    location.assign(sessionURL(this.set,settings,mode==='transcription'?'working':this.reasonCode));
  }

  persist(){
    if(!deviceStorageAllowed())return;
    const mode=document.querySelector('input[name="practiceMode"]:checked')?.value||'manual';
    try{saveDeviceSettings({mode,pause:Number($('fallbackSilenceSetting').value),volume:Number($('volumeSetting').value),
      skip:$('rememberDeviceSettings').checked,micOK:this.micOK,speechOK:this.speechOK});}catch{}
  }
}
