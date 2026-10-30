export class BrowserSpeech {
  constructor({onText,onError,onSpeech}) {
    this.onText=onText;this.onError=onError;this.onSpeech=onSpeech;
    this.active=false;this.epoch=0;this.prefix='';this.segment='';
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
    const recognition=new Constructor();this.recognition=recognition;
    recognition.lang='en-US';recognition.continuous=true;recognition.interimResults=true;recognition.maxAlternatives=1;
    recognition.onresult=event=>{
      if(!this.active || epoch!==this.epoch)return;
      let final='',interim='';
      for(let i=0;i<event.results.length;i++) {
        const value=event.results[i][0]?.transcript||'';
        if(event.results[i].isFinal)final+=value+' ';else interim+=value+' ';
      }
      this.segment=(final+interim).trim();
      this.onText({text:[this.prefix,this.segment].filter(Boolean).join(' '),isFinal:!interim.trim(),interim:interim.trim()});
    };
    recognition.onspeechstart=()=>{if(this.active&&epoch===this.epoch)this.onSpeech?.(true);};
    recognition.onspeechend=()=>{if(this.active&&epoch===this.epoch)this.onSpeech?.(false);};
    recognition.onerror=event=>{
      if(!this.active || epoch!==this.epoch || ['aborted','no-speech'].includes(event.error))return;
      this.onError(event.error);this.stop();
    };
    recognition.onend=()=>{
      if(!this.active || epoch!==this.epoch)return;
      this.prefix=[this.prefix,this.segment].filter(Boolean).join(' ');this.segment='';
      this.restart=setTimeout(()=>this.open(epoch),160);
    };
    try{recognition.start();}catch(error){this.onError(error.message);this.stop();}
  }
  stop(){this.active=false;this.epoch++;clearTimeout(this.restart);try{this.recognition?.abort();}catch{}this.recognition=null;}
}

export class MicrophoneMonitor {
  constructor(onLevel,onVoice){this.onLevel=onLevel;this.onVoice=onVoice;this.available=false;this.noise=0.003;}
  async start(){
    if(this.available){await this.context.resume();return;}
    this.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
    const Context=globalThis.AudioContext||globalThis.webkitAudioContext;
    this.context=new Context();await this.context.resume();
    this.analyser=this.context.createAnalyser();this.analyser.fftSize=1024;
    this.source=this.context.createMediaStreamSource(this.stream);this.source.connect(this.analyser);
    this.buffer=new Float32Array(this.analyser.fftSize);this.available=true;this.active=true;this.hotSince=0;
    this.loop();
  }
  loop(){
    if(!this.active)return;
    this.analyser.getFloatTimeDomainData(this.buffer);
    let sum=0;for(const value of this.buffer)sum+=value*value;
    const rms=Math.sqrt(sum/this.buffer.length),threshold=Math.max(0.008,Math.min(0.045,this.noise*2.6));
    if(rms<threshold)this.noise=this.noise*0.98+rms*0.02;
    const hot=rms>threshold,now=performance.now();
    if(hot){if(!this.hotSince)this.hotSince=now;if(now-this.hotSince>=75)this.onVoice(now);}
    else this.hotSince=0;
    this.onLevel(Math.min(1,rms/0.075));
    this.frame=requestAnimationFrame(()=>this.loop());
  }
  async close(){this.active=false;this.available=false;cancelAnimationFrame(this.frame);this.stream?.getTracks().forEach(t=>t.stop());try{await this.context?.close();}catch{}}
}
