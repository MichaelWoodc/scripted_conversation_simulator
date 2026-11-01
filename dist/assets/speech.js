export function exclusiveSpeechCapture(){
  return !!navigator.userAgentData?.mobile||/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)||(/Macintosh/i.test(navigator.userAgent)&&navigator.maxTouchPoints>1);
}

export class BrowserSpeech {
  constructor({onText,onError,onSpeech,onReady}) {
    this.onText=onText;this.onError=onError;this.onSpeech=onSpeech;this.onReady=onReady;
    this.active=false;this.epoch=0;this.prefix='';this.segment='';this.mobile=exclusiveSpeechCapture();
  }
  get supported(){return !!(globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition);}
  start(prefix='') {
    this.stop();this.active=true;this.prefix=prefix;this.segment='';
    if(!this.supported){this.onError('unsupported');return;}
    this.open(this.epoch);
  }
  open(epoch) {
    if(!this.active || epoch!==this.epoch)return;
    const Constructor=globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition;
    let recognition;
    try{recognition=new Constructor();}catch(error){this.fail(error.name||error.message);return;}
    this.recognition=recognition;
    recognition.lang='en-US';recognition.continuous=!this.mobile;recognition.interimResults=true;recognition.maxAlternatives=1;
    const current=()=>this.active&&epoch===this.epoch&&this.recognition===recognition;
    recognition.onstart=()=>{if(current()){clearTimeout(this.startTimeout);this.onReady?.();}};
    this.startTimeout=setTimeout(()=>{if(current())this.fail('start-timeout');},this.mobile?15000:5000);
    recognition.onresult=event=>{
      if(!current())return;
      clearTimeout(this.startTimeout);
      let final='',interim='';
      for(let i=0;i<event.results.length;i++) {
        const value=event.results[i][0]?.transcript||'';
        if(event.results[i].isFinal)final+=value+' ';else interim+=value+' ';
      }
      this.segment=(final+interim).trim();
      this.onText({text:[this.prefix,this.segment].filter(Boolean).join(' '),isFinal:!interim.trim(),interim:interim.trim()});
    };
    recognition.onspeechstart=()=>{if(current())this.onSpeech?.(true);};
    recognition.onspeechend=()=>{if(current())this.onSpeech?.(false);};
    recognition.onerror=event=>{
      if(!current() || ['aborted','no-speech'].includes(event.error))return;
      this.fail(event.error);
    };
    recognition.onend=()=>{
      if(!current())return;
      clearTimeout(this.startTimeout);this.onSpeech?.(false);
      this.prefix=[this.prefix,this.segment].filter(Boolean).join(' ');this.segment='';
      this.recognition=null;
      this.restart=setTimeout(()=>this.open(epoch),this.mobile?350:160);
    };
    try{recognition.start();}catch(error){this.fail(error.name||error.message);}
  }
  fail(code){this.stop();this.onError(code);}
  stop(){this.active=false;this.epoch++;clearTimeout(this.restart);clearTimeout(this.startTimeout);try{this.recognition?.abort();}catch{}this.recognition=null;}
}

export function deviceCapabilities(){
  return {
    secure:globalThis.isSecureContext===true,
    microphone:!!navigator.mediaDevices?.getUserMedia,
    volume:!!(globalThis.AudioContext||globalThis.webkitAudioContext),
    transcription:!!(globalThis.SpeechRecognition||globalThis.webkitSpeechRecognition),
    playback:!!document.getElementById('answerAudio')?.canPlayType('audio/wav')
  };
}

export function recognitionReason(code){
  return ({unsupported:'This browser does not provide speech transcription.',
    'permission-needed':'Microphone permission has not been granted. You chose manual practice.',
    'microphone-unavailable':'The microphone is unavailable or permission was denied. Manual practice is available.',
    'not-allowed':'Speech transcription permission was denied by the browser or device settings.',
    'service-not-allowed':'The browser cannot use a speech-recognition service. On GrapheneOS, verify that a compatible Android speech-recognition provider is installed and enabled; an available browser API alone does not provide the service.',
    network:'The speech transcription service could not connect to its server.',
    'audio-capture':'The transcription service could not capture microphone audio.',
    'language-not-supported':'The transcription service does not support English on this device.',
    'start-timeout':exclusiveSpeechCapture()?'The transcription service did not start within fifteen seconds. Check browser microphone permission and Android speech-recognition provider availability.':'The transcription service did not start within five seconds.',
    'no-results':'The microphone detected speech, but the transcription service returned no words.',
    NotAllowedError:'The browser blocked speech transcription.',
    SecurityError:'The browser security settings blocked speech transcription.'})[code]||`Speech transcription failed (${code}).`;
}

async function deadline(promise,ms,message){
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),ms);})]);}
  finally{clearTimeout(timer);}
}

export class MicrophoneMonitor {
  constructor(onLevel,onVoice,onInterrupted){this.onLevel=onLevel;this.onVoice=onVoice;this.onInterrupted=onInterrupted;this.available=false;this.noise=0.003;this.minimum=0.007;this.epoch=0;}
  start(){
    if(this.starting)return this.starting;
    this.starting=this.open().finally(()=>{this.starting=null;});
    return this.starting;
  }
  async open(){
    if(this.available){
      await deadline(this.context.resume(),4000,'Audio monitoring could not resume. Tap Check device again.');
      if(this.context.state&&this.context.state!=='running')throw new Error('Audio monitoring is still suspended. Check device again.');
      return;
    }
    if(!globalThis.isSecureContext)throw new Error('Microphone access requires HTTPS. Open the published HTTPS site on your phone.');
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('This browser does not provide microphone access.');
    const Context=globalThis.AudioContext||globalThis.webkitAudioContext;
    if(!Context)throw new Error('This browser cannot monitor microphone volume.');
    if(this.active){this.active=false;cancelAnimationFrame(this.frame);this.stream?.getTracks().forEach(track=>track.stop());this.context?.close().catch(()=>{});}
    const epoch=++this.epoch;
    try{
      // Create/resume synchronously from the tap, before waiting for permission.
      this.context=new Context();
      const resumed=this.context.resume();
      const capture=navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      capture.then(stream=>{if(epoch!==this.epoch)stream.getTracks().forEach(track=>track.stop());else this.stream=stream;},()=>{});
      const [stream]=await Promise.all([
        deadline(capture,15000,'Microphone permission is still pending. Allow access, then check again.'),
        deadline(resumed,4000,'Audio monitoring is suspended. Tap Check device again.')
      ]);
      if(epoch!==this.epoch)return;
      this.stream=stream;
      if(this.context.state&&this.context.state!=='running')throw new Error('Audio monitoring is suspended. Tap Check device again.');
      this.analyser=this.context.createAnalyser();this.analyser.fftSize=1024;
      this.source=this.context.createMediaStreamSource(stream);this.source.connect(this.analyser);
      this.buffer=new Float32Array(this.analyser.fftSize);this.available=true;this.active=true;this.hotSince=0;this.lastSample=performance.now();
      this.context.onstatechange=()=>{if(this.active&&epoch===this.epoch&&['suspended','interrupted','closed'].includes(this.context.state))this.onInterrupted?.('Microphone monitoring was interrupted. Tap Continue listening to resume.');};
      for(const track of stream.getTracks())track.onended=()=>{if(this.active&&epoch===this.epoch){this.available=false;this.onInterrupted?.('The microphone disconnected. Check device again.');}};
      this.loop();
    }catch(error){await this.close();throw error;}
  }
  loop(){
    if(!this.active)return;
    this.analyser.getFloatTimeDomainData(this.buffer);
    let sum=0;for(const value of this.buffer)sum+=value*value;
    const rms=Math.sqrt(sum/this.buffer.length),threshold=Math.max(this.minimum,Math.min(0.045,this.noise*2.6));
    if(rms<threshold)this.noise=this.noise*0.98+rms*0.02;
    const hot=rms>threshold,now=performance.now();
    const elapsed=Math.max(0,Math.min(100,now-this.lastSample));this.lastSample=now;
    if(hot){if(!this.hotSince)this.hotSince=now;if(now-this.hotSince>=75)this.onVoice(now,elapsed);}
    else this.hotSince=0;
    this.onLevel(Math.min(1,rms/0.075));
    this.frame=requestAnimationFrame(()=>this.loop());
  }
  async close(){this.epoch++;this.active=false;this.available=false;cancelAnimationFrame(this.frame);this.stream?.getTracks().forEach(t=>t.stop());try{await this.context?.close();}catch{}this.stream=null;}
}
