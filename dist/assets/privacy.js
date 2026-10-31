const KEY='conversation_lab_consent';
const PREFIX='conversation-lab:';
const DEVICE_KEY='conversation_lab_device';
const memory=new Map();
let choice=typeof document==='undefined'?null:document.cookie.split('; ').find(row=>row.startsWith(KEY+'='))?.split('=')[1];

export function readDeviceSettings(){
  try{
    const raw=document.cookie.split('; ').find(row=>row.startsWith(DEVICE_KEY+'='))?.split('=')[1];
    const settings=JSON.parse(decodeURIComponent(raw));
    if(!['transcription','volume','manual'].includes(settings.mode))return null;
    return {mode:settings.mode,pause:settings.pause>=500&&settings.pause<=5000?settings.pause:2500,
      volume:settings.volume>=0.004&&settings.volume<=0.04?settings.volume:0.007,
      skip:settings.skip!==false,
      micOK:settings.micOK??settings.mode!=='manual',speechOK:settings.speechOK??settings.mode==='transcription'};
  }catch{return null;}
}

export function saveDeviceSettings(settings){
  const value=settings?encodeURIComponent(JSON.stringify(settings)):'';
  document.cookie=`${DEVICE_KEY}=${value}; Path=/; Max-Age=${settings?31536000:0}; SameSite=Lax${location.protocol==='https:'?'; Secure':''}`;
}

export function deviceStorageAllowed(){return choice==='remember'||!!readDeviceSettings();}

// Optional storage is never touched until the visitor explicitly accepts it.
export const preferenceStorage={
  getItem(key){
    if(choice==='remember'){try{return globalThis.localStorage.getItem(key)??memory.get(key)??null;}catch{}}
    return memory.get(key)??null;
  },
  setItem(key,value){
    memory.set(key,String(value));
    if(choice==='remember'){try{globalThis.localStorage.setItem(key,String(value));}catch{}}
  }
};

export function initPrivacy(){
  const banner=document.getElementById('consentBanner');
  if(!banner)return;
  const status=document.getElementById('consentStatus');
  function show(){
    banner.hidden=choice==='remember'||choice==='session';
    status.textContent=choice==='remember'?'Progress is saved on this device.':'Progress lasts for this page visit only.';
  }
  function choose(value){
    choice=value;
    try{document.cookie=`${KEY}=${value}; Path=/; Max-Age=31536000; SameSite=Lax${location.protocol==='https:'?'; Secure':''}`;}catch{}
    try{
      if(value==='session'){
        saveDeviceSettings(null);
        const storage=globalThis.localStorage;
        for(const key of Object.keys(storage))if(key.startsWith(PREFIX))storage.removeItem(key);
      }else for(const [key,value] of memory)globalThis.localStorage.setItem(key,value);
    }catch{}
    show();window.dispatchEvent(new Event('storagechoice'));
  }
  document.getElementById('consentAccept').addEventListener('click',()=>choose('remember'));
  document.getElementById('consentReject').addEventListener('click',()=>choose('session'));
  document.getElementById('storageSettings').addEventListener('click',()=>{banner.hidden=false;banner.scrollIntoView({block:'nearest'});document.getElementById('consentReject').focus();});
  show();
}
