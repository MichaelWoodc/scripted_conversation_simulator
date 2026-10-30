"""Browser state tests with simulated interim speech and real catalog/audio URLs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from http.server import ThreadingHTTPServer
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build_site import build, make_catalog
from server import Handler

MOCKS=r'''
window.__played=[];window.__level=0;window.__holdAudio=false;window.__blockNextAudio=false;
class TestRecognition {
  static instances=[];
  constructor(){TestRecognition.instances.push(this);}
  start(){this.running=true;}
  abort(){this.running=false;this.onend?.();}
  static emit(text,final=false){
    const item=Object.assign([{transcript:text,confidence:0.9}],{isFinal:final});
    TestRecognition.instances.at(-1)?.onresult?.({resultIndex:0,results:[item]});
  }
}
window.SpeechRecognition=TestRecognition;window.__recognition=TestRecognition;
Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}});
window.AudioContext=class{
  async resume(){} async close(){}
  createMediaStreamSource(){return{connect(){}};}
  createAnalyser(){return{fftSize:1024,getFloatTimeDomainData(buffer){buffer.fill(window.__level);}};}
};
HTMLMediaElement.prototype.play=function(){
  if(this.id!=='answerAudio'||!this.src.includes('/media/'))return Promise.resolve();
  if(window.__blockNextAudio){window.__blockNextAudio=false;return Promise.reject(new DOMException('Click required','NotAllowedError'));}
  const url=this.src;
  setTimeout(()=>{window.__played.push(url);this.dispatchEvent(new Event('playing'));
    if(!window.__holdAudio)setTimeout(()=>this.dispatchEvent(new Event('ended')),140);
  },5);
  return Promise.resolve();
};
HTMLMediaElement.prototype.pause=function(){};
'''


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,media=build()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.media=media
        cls.server_thread=Thread(target=cls.server.serve_forever,daemon=True)
        cls.server_thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        cls.base_url=f'http://127.0.0.1:{cls.server.server_port}/'
        cls.driver=sync_playwright().start()
        cls.addClassCleanup(cls.driver.stop)
        cls.browser=cls.driver.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        cls.addClassCleanup(cls.browser.close)
        catalog,_=make_catalog();cls.catalog=catalog
        item=deepcopy(next(s for s in catalog['sets'] if s['edition']=='edited' and s['vignette']==1))
        clips=[c for s in item['steps'] for c in s['clips']]
        item['steps']=[{'id':'test-q1','prompt':'Has the employee received formal training on this task?',
                        'context':[],'answerIndices':[1,2],'clips':clips[:2]},
                       {'id':'test-q2','prompt':'When did the employee receive the training?',
                        'context':[],'answerIndices':[3],'clips':[clips[2]]}]
        item['answerCount']=3;item['version']='browser-test-1'
        cls.fixture=item

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1365,'height':1000})
        self.page=self.context.new_page();self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.add_init_script(MOCKS)
        self.page.route('**/catalog.json',lambda route:route.fulfill(content_type='application/json',body=json.dumps({'sets':[self.fixture]})))
        self.url=self.base_url+self.fixture['page']

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.context.close()

    def open_session(self):
        self.page.goto(self.url)
        self.page.wait_for_function("document.getElementById('sessionTitle').textContent==='Materials & resources'")

    def start(self):
        self.page.locator('#startButton').click()
        self.page.wait_for_function("document.getElementById('statusText').textContent==='Listening'")

    def emit(self,text,final=False):
        self.page.evaluate('([text,final])=>window.__recognition.emit(text,final)',[text,final])

    def test_interim_highlights_fuzzy_match_silence_and_once_order(self):
        self.open_session();self.start();self.page.locator('#debugToggle').click()
        self.page.evaluate('window.__level=0.08')
        self.emit('Has the employee')
        self.assertEqual(self.page.locator('#questionText .heard').count(),3)
        self.emit('Has the worker had training for this task')
        self.assertIn('worker',self.page.locator('#transcript').inner_text())
        self.page.wait_for_timeout(1050)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'Must wait until speech stops')
        self.page.evaluate('window.__oldRecognizer=window.__recognition.instances.at(-1); window.__level=0')
        self.page.wait_for_function('window.__played.length===2',timeout=4000)
        self.page.wait_for_function("document.getElementById('stepLabel').textContent==='Question 2 of 2'")
        self.page.evaluate("window.__oldRecognizer.onresult({results:[Object.assign([{transcript:'When did the employee receive the training?'}],{isFinal:true})]})")
        self.page.wait_for_timeout(1000)
        self.assertEqual(self.page.evaluate('window.__played.length'),2,'Late result must not repeat/advance')
        self.page.evaluate('window.__level=0.08')
        self.emit('When did the employee receive training',True)
        self.page.wait_for_timeout(120)
        self.page.evaluate('window.__level=0')
        self.page.wait_for_function("!document.getElementById('completion').hidden",timeout=4000)
        urls=self.page.evaluate('window.__played')
        self.assertEqual([u.split('/')[-1].split('?')[0] for u in urls],['answer_001.wav','answer_002.wav','answer_003.wav'])
        self.page.reload();self.page.wait_for_function("!document.getElementById('completion').hidden")
        self.assertEqual(self.page.evaluate('window.__played.length'),0)

    def test_autoplay_block_can_resume_without_replaying_a_started_answer(self):
        self.open_session();self.start();self.page.evaluate('window.__blockNextAudio=true')
        self.page.locator('#finishButton').click()
        self.page.locator('#resumeAudioButton').wait_for(state='visible')
        self.assertEqual(self.page.evaluate('window.__played.length'),0)
        self.page.locator('#resumeAudioButton').click()
        self.page.wait_for_function('window.__played.length===2')
        self.assertEqual(len(set(self.page.evaluate('window.__played'))),2)

    def test_mobile_layout_has_no_horizontal_overflow(self):
        self.page.set_viewport_size({'width':390,'height':844})
        self.open_session()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))
        out=Path(__file__).resolve().parents[1]/'test-results';out.mkdir(exist_ok=True)
        self.page.screenshot(path=str(out/'mobile.png'),full_page=True)

    def test_repeated_feedback_highlights_the_first_occurrence_first(self):
        self.fixture=deepcopy(self.fixture)
        self.fixture['steps'][0]['prompt']='For vocal feedback, was that feedback positive feedback for steps performed correctly or corrective feedback for steps performed incorrectly?'
        self.open_session();self.start()
        self.page.evaluate('window.__level=0.08')
        self.emit('For vocal feedback')
        heard=self.page.locator('#questionText .heard').evaluate_all('(elements)=>elements.map(e=>Number(e.dataset.word)).sort((a,b)=>a-b)')
        self.assertEqual(heard,[0,1,2])
        self.emit('For vocal feedback was that feedback')
        heard=self.page.locator('#questionText .heard').evaluate_all('(elements)=>elements.map(e=>Number(e.dataset.word)).sort((a,b)=>a-b)')
        self.assertEqual(heard,[0,1,2,3,4,5])
        self.assertNotIn('heard',self.page.locator('[data-word="7"]').get_attribute('class') or '')


if __name__=='__main__':unittest.main()
