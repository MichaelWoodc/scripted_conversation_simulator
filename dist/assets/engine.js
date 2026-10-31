// Pure matching and progress logic; no microphone or DOM dependencies.
import {preferenceStorage} from './privacy.js';
const STOP = new Set('a an the is are was were be been being do does did has have had to of for in on at and or that this it they them their you your can could would should may might with from as if so i we'.split(' '));
const ALIASES = {employees:'employee',workers:'employee',worker:'employee',staff:'employee',training:'train',trained:'train',trains:'train',received:'receive',receives:'receive',receiving:'receive',completed:'complete',completes:'complete',completing:'complete',completion:'complete',performed:'perform',performing:'perform',performs:'perform',reminded:'remind',reminders:'remind',reminder:'remind',materials:'material',tasks:'task',sessions:'session',instructions:'instruction',demonstrations:'demonstration',modeling:'model',modelling:'model',rehearsal:'practice',practiced:'practice',practising:'practice',practicing:'practice',frequency:'often',frequently:'often',daily:'day',quickly:'quick',accurately:'accurate',correctly:'correct',behaviour:'behavior',behaviors:'behavior',supervisors:'supervisor',afterwards:'after',electronic:'electronically',verbally:'vocal',verbal:'vocal',vocally:'vocal'};

export function canonical(word) {
  let text = word.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/['']/g,'');
  if (ALIASES[text]) return ALIASES[text];
  if (text.length > 5 && text.endsWith('s') && !text.endsWith('ss')) text=text.slice(0,-1);
  return ALIASES[text] || text;
}

export function tokenize(text) {
  return [...String(text).matchAll(/[\p{L}\p{N}]+(?:[''][\p{L}]+)*/gu)].map(m=>({raw:m[0],word:canonical(m[0]),start:m.index,end:m.index+m[0].length}));
}

function closeWord(a,b) {
  if (a===b) return true;
  if (Math.min(a.length,b.length)<5 || Math.abs(a.length-b.length)>1) return false;
  let i=0,j=0,edits=0;
  while(i<a.length && j<b.length) {
    if(a[i]===b[j]) {i++;j++;continue;}
    if(++edits>1) return false;
    if(a.length>=b.length)i++;
    if(b.length>=a.length)j++;
  }
  return edits+(i<a.length || j<b.length?1:0)<=1;
}

export function matchQuestion(question, transcript, threshold=0.58) {
  const expected=tokenize(question), heard=tokenize(transcript).slice(-220);
  const n=expected.length,m=heard.length;
  const weights=expected.map(t=>STOP.has(t.word)?0.22:1);
  const dp=Array.from({length:n+1},()=>new Float32Array(m+1));
  for(let i=1;i<=n;i++) for(let j=1;j<=m;j++) {
    const same=closeWord(expected[i-1].word,heard[j-1].word);
    dp[i][j]=Math.max(dp[i-1][j],dp[i][j-1],same?dp[i-1][j-1]+weights[i-1]:0);
  }
  const matched=new Set(); let i=n,j=m;
  while(i>0 && j>0) {
    // Discard a later expected occurrence when an equally good alignment ends
    // earlier. This makes repeated words fill their first unspoken slot first.
    if(Math.abs(dp[i-1][j]-dp[i][j])<0.001) {
      i--;
    } else if(closeWord(expected[i-1].word,heard[j-1].word) && Math.abs(dp[i][j]-(dp[i-1][j-1]+weights[i-1]))<0.001) {
      matched.add(i-1);i--;j--;
    } else if(dp[i-1][j]>=dp[i][j-1]) i--; else j--;
  }
  const total=weights.reduce((a,b)=>a+b,0),coverage=total?dp[n][m]/total:0;
  const content=expected.map((t,k)=>STOP.has(t.word)?-1:k).filter(k=>k>=0);
  const contentHeard=content.filter(k=>matched.has(k)).length;
  const tail=content.slice(-Math.min(4,content.length));
  const tailHeard=tail.filter(k=>matched.has(k)).length;
  const ending=n<10 || tailHeard>=Math.min(2,tail.length) || coverage>=0.86;
  const enough=contentHeard>=Math.min(2,content.length) && heard.length>=Math.min(3,n);
  return {expected,matched,coverage,contentHeard,ending,ready:coverage>=threshold && ending && enough};
}

export class SessionProgress {
  constructor(set,storage=preferenceStorage) {
    this.set=set;this.storage=storage;this.key=`conversation-lab:v1:${set.id}:${set.version}`;
    let stored={};try{stored=JSON.parse(storage.getItem(this.key)||'{}');}catch{}
    this.index=Number.isInteger(stored.index)?Math.max(0,Math.min(set.steps.length,stored.index)):0;
    const valid=new Set(set.steps.flatMap(s=>s.clips.map(c=>c.id)));
    this.played=new Set((stored.played||[]).filter(id=>valid.has(id)));
    this.asked=new Set((stored.asked||[]).filter(id=>set.steps.some(s=>s.id===id)));
    // A clip that began before a refresh is never started again in this attempt.
    while(this.current && this.asked.has(this.current.id) && this.current.clips.every(c=>this.played.has(c.id)))this.index++;
    this.persist();
  }
  get current(){return this.set.steps[this.index]||null;}
  get complete(){return !this.current;}
  get remainingClips(){return this.current?this.current.clips.filter(c=>!this.played.has(c.id)):[];}
  markAsked(){if(!this.current || this.asked.has(this.current.id))return false;this.asked.add(this.current.id);this.persist();return true;}
  markStarted(clip){if(!this.current || !this.current.clips.some(c=>c.id===clip.id) || this.played.has(clip.id))return false;this.played.add(clip.id);this.persist();return true;}
  advance(){if(!this.current || this.remainingClips.length)return false;this.index++;this.persist();return true;}
  persist(){try{this.storage.setItem(this.key,JSON.stringify({index:this.index,played:[...this.played],asked:[...this.asked]}));}catch{}}
  reset(){this.index=0;this.played.clear();this.asked.clear();this.persist();}
}
