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
from build_site import build, make_catalog, render_session
from server import Handler


class TestHandler(Handler):
    def log_message(self, *args):
        pass

MOCKS=r'''
window.__played=[];window.__questionPlayed=[];window.__level=0;window.__holdAudio=false;window.__blockNextAudio=false;
class TestRecognition {
  static instances=[];
  constructor(){TestRecognition.instances.push(this);}
  start(){this.running=true;setTimeout(()=>{if(!this.running)return;if(window.__recognitionError)this.onerror?.({error:window.__recognitionError});else if(!window.__recognitionSilent){this.onstart?.();if(document.body.dataset.page==='setup'&&!window.__noTestWords)TestRecognition.emit('Testing one two three');}},0);}
  abort(){this.running=false;this.onend?.();}
  static emit(text,final=false){
    const item=Object.assign([{transcript:text,confidence:0.9}],{isFinal:final});
    TestRecognition.instances.at(-1)?.onresult?.({resultIndex:0,results:[item]});
  }
}
window.SpeechRecognition=TestRecognition;window.__recognition=TestRecognition;
Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{
  if(window.__denyMicrophone)throw new DOMException('Microphone access denied','NotAllowedError');
  const track={label:'Test microphone',stop(){window.__micStopped=true;},getSettings:()=>({sampleRate:48000})};
  return {getTracks:()=>[track],getAudioTracks:()=>[track]};
}}});
window.AudioContext=class{
  constructor(){window.__audioContext=this;}
  state='running';
  async resume(){} async close(){}
  createMediaStreamSource(){return{connect(){}};}
  createAnalyser(){return{fftSize:1024,getFloatTimeDomainData(buffer){buffer.fill(window.__level);}};}
};
HTMLMediaElement.prototype.play=function(){
  if(this.id==='questionAudio'){
    window.__questionPlayed.push(this.src);setTimeout(()=>this.dispatchEvent(new Event('ended')),140);return Promise.resolve();
  }
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
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
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
        for step in item['steps']:
            source=next(s for s in cls.catalog['sets'][0]['steps'] if s['prompt']==step['prompt'])
            step['questionAudio']={**source['questionAudio'],'duration':2.0}
        cls.fixture=item

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1365,'height':1000})
        self.page=self.context.new_page();self.errors=[]
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.add_init_script(MOCKS)
        self.page.route('**/catalog.json',lambda route:route.fulfill(content_type='application/json',body=json.dumps({'sets':[self.fixture]})))
        self.page.route('**/sets/*.html*',lambda route:route.fulfill(content_type='text/html',body=render_session(self.fixture)))
        self.url=self.base_url+self.fixture['page']

    def tearDown(self):
        self.assertEqual(self.errors,[])
        self.context.close()

    def open_session(self):
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        if self.page.locator('#consentAccept').is_visible():self.page.locator('#consentAccept').click()
        self.page.locator('#checkDeviceButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.page.locator('#continueToSession').click()
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='idle'")

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
        self.assertNotIn('heard',self.page.locator('#questionText [data-question-id]:not([hidden]) [data-word="7"]').get_attribute('class') or '')

    def test_all_pages_contain_their_content_without_javascript(self):
        context=self.browser.new_context(java_script_enabled=False)
        self.addCleanup(context.close)
        page=context.new_page()
        page.goto(self.base_url)
        self.assertEqual(page.locator('.session-card:visible').count(),len(self.catalog['sets']))
        self.assertEqual(page.locator('#edition option').count(),2)
        for item in self.catalog['sets']:
            page.goto(self.base_url+item['page'])
            self.assertEqual(page.locator('#sessionTitle').inner_text(),item['title'])
            self.assertEqual(page.locator('#questionText > [data-question-id]').count(),len(item['steps']))
            self.assertEqual(page.locator('#questionText > :visible').count(),1)
            for step in item['steps']:
                question=page.locator(f'#questionText > [data-question-id="{step["id"]}"]')
                self.assertEqual(question.text_content(),step['prompt'])
                context_text=page.locator(f'#questionContext > [data-question-id="{step["id"]}"]')
                self.assertEqual(context_text.text_content(),'\n\n'.join(step['context']))

    def test_library_edition_filter_and_progress_use_existing_cards(self):
        self.page.unroute('**/catalog.json')
        self.page.goto(self.base_url)
        self.page.wait_for_function("!document.getElementById('edition').disabled")
        self.page.evaluate("window.__firstCard=document.querySelector('.session-card')")
        for edition in ('edited','original'):
            self.page.select_option('#edition',edition)
            expected=[item for item in self.catalog['sets'] if item['edition']==edition]
            cards=self.page.locator('.session-card:visible')
            self.assertEqual(cards.count(),len(expected))
            self.assertEqual(cards.evaluate_all('(cards)=>cards.map(card=>card.dataset.setId)'),[item['id'] for item in expected])
        self.assertTrue(self.page.evaluate("window.__firstCard===document.querySelector('.session-card')"))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))

    def test_catalog_failure_preserves_static_library(self):
        self.page.route('**/catalog.json',lambda route:route.fulfill(status=503,body='Unavailable'))
        self.page.goto(self.base_url)
        self.page.wait_for_function("document.getElementById('catalogStatus').textContent.includes('503')")
        self.assertEqual(self.page.locator('.session-card:visible').count(),len(self.catalog['sets']))

    def test_voice_timing_counts_only_voice_and_waits_for_adjustable_pause(self):
        self.page.add_init_script('delete window.SpeechRecognition; delete window.webkitSpeechRecognition;')
        self.open_session()
        self.assertIn('Voice timing',self.page.locator('#modeStatus').inner_text())
        self.page.locator('#debugToggle').click()
        self.assertIn('does not provide',self.page.locator('#recognitionReason').inner_text())
        self.assertEqual(self.page.locator('#fallbackSilenceSetting').input_value(),'3000')
        self.start()
        self.page.wait_for_timeout(350)
        self.assertEqual(self.page.locator('#voiceProgressBar').get_attribute('aria-valuenow'),'0')
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_timeout(650)
        self.page.evaluate('window.__level=0')
        self.page.wait_for_timeout(1800)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'A pause before 75% must not play an answer')
        self.page.select_option('#fallbackSilenceSetting','1500')
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_function("Number(document.getElementById('voiceProgressBar').getAttribute('aria-valuenow'))>=85")
        self.page.wait_for_timeout(1700)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'Continued speech must postpone the answer')
        self.assertEqual(self.page.locator('#questionText .heard').count(),0)
        self.page.evaluate('window.__level=0')
        self.page.wait_for_function('window.__played.length===2',timeout=3500)
        self.page.wait_for_function("document.getElementById('stepLabel').textContent==='Question 2 of 2'")
        self.assertEqual(self.page.locator('#voiceProgressBar').get_attribute('aria-valuenow'),'0')

    def test_recognition_network_error_switches_to_volume_and_explains_why(self):
        self.open_session();self.start()
        self.page.evaluate("window.__recognition.instances.at(-1).onerror({error:'network'})")
        self.assertIn('Voice timing',self.page.locator('#modeStatus').inner_text())
        self.page.locator('#debugToggle').click()
        self.assertIn('could not connect',self.page.locator('#recognitionReason').inner_text())
        self.assertIn('Test microphone',self.page.locator('#deviceReport').inner_text())
        self.assertTrue(self.page.locator('#voiceProgress').is_visible())

    def test_transcription_start_failure_uses_voice_timing_before_session(self):
        self.page.add_init_script("window.__recognitionError='service-not-allowed'")
        self.open_session()
        self.assertIn('Voice timing',self.page.locator('#modeStatus').inner_text())
        self.assertIn('disabled',self.page.locator('#recognitionReason').text_content())

    def test_silent_transcription_start_times_out_to_voice_timing(self):
        self.page.add_init_script('window.__recognitionSilent=true')
        self.open_session()
        self.assertIn('Voice timing',self.page.locator('#modeStatus').inner_text())
        self.assertIn('five seconds',self.page.locator('#recognitionReason').text_content())

    def test_mobile_manual_mode_and_consent_fit_the_viewport(self):
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))
        self.page.locator('#consentReject').click()
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'unavailable')
        self.assertEqual(self.page.locator('#volumeOption').get_attribute('data-availability'),'unavailable')
        self.assertEqual(self.page.locator('#manualOption').get_attribute('data-availability'),'recommended')
        self.page.locator('#rememberDeviceSettings').check()
        self.page.locator('#continueToSession').click()
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='idle'")
        self.assertIn('Manual',self.page.locator('#modeStatus').inner_text())
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_url('**/sets/*.html?mode=manual*')
        self.page.locator('#changeDeviceLink').click()
        self.page.wait_for_function("document.getElementById('deviceSetup')?.dataset.ready==='true'")
        self.assertTrue(self.page.locator('#rememberDeviceSettings').is_checked())

    def test_microphone_denied_keeps_manual_practice_available(self):
        self.page.add_init_script('window.__denyMicrophone=true; delete window.SpeechRecognition; delete window.webkitSpeechRecognition;')
        self.open_session()
        self.assertIn('Manual',self.page.locator('#modeStatus').inner_text())
        self.start();self.page.locator('#finishButton').click()
        self.page.wait_for_function('window.__played.length===2')

    def test_question_preview_never_counts_as_speech_or_plays_an_answer(self):
        self.open_session()
        self.page.locator('#hearQuestionButton').click()
        self.page.wait_for_function('window.__questionPlayed.length===1')
        self.page.wait_for_function("document.getElementById('statusPill').dataset.state==='idle'")
        self.assertEqual(self.page.evaluate('window.__played.length'),0)
        self.assertEqual(self.page.locator('#voiceProgressBar').get_attribute('aria-valuenow'),'0')

    def test_storage_requires_consent_and_revocation_clears_saved_progress(self):
        self.page.add_init_script('''
          window.__storageReads=0;window.__storageWrites=0;
          const read=Storage.prototype.getItem,write=Storage.prototype.setItem;
          Storage.prototype.getItem=function(...args){window.__storageReads++;return read.apply(this,args);};
          Storage.prototype.setItem=function(...args){window.__storageWrites++;return write.apply(this,args);};
        ''')
        self.page.goto(self.url+'?mode=manual')
        self.page.wait_for_function("document.getElementById('statusPill').dataset.state==='idle'")
        self.assertEqual(self.page.evaluate('[window.__storageReads,window.__storageWrites]'),[0,0])
        self.page.locator('#consentAccept').click()
        self.assertGreater(self.page.evaluate('window.__storageWrites'),0)
        self.assertTrue(self.page.evaluate("Object.keys(localStorage).some(k=>k.startsWith('conversation-lab:'))"))
        self.page.locator('#storageSettings').click();self.page.locator('#consentReject').click()
        self.assertEqual(self.page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('conversation-lab:')).length"),0)
        self.page.reload()
        self.page.wait_for_function("document.getElementById('statusPill').dataset.state==='idle'")
        self.assertEqual(self.page.evaluate('[window.__storageReads,window.__storageWrites]'),[0,0])
        self.assertFalse(self.page.locator('#consentBanner').is_visible())

    def test_question_recordings_have_measured_duration_and_playable_urls(self):
        from urllib.parse import unquote
        import wave
        from project_paths import DIST
        for item in self.catalog['sets']:
            for step in item['steps']:
                clip=step['questionAudio'];self.assertIsNotNone(clip)
                with wave.open(str(DIST/unquote(clip['url'])), 'rb') as audio:
                    self.assertAlmostEqual(clip['duration'],audio.getnframes()/audio.getframerate(),places=3)
        response=self.page.request.get(self.base_url+self.catalog['sets'][0]['steps'][0]['questionAudio']['url'])
        self.assertEqual(response.status,200)
        self.assertTrue(response.body().startswith(b'RIFF'))

    def test_setup_live_phrase_two_second_test_and_remembered_results(self):
        self.page.add_init_script('window.__noTestWords=true')
        setup=self.base_url+'setup.html?set='+self.fixture['id']+'&change=1'
        self.page.goto(setup)
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.page.locator('#consentAccept').click()
        self.page.locator('#checkDeviceButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),0)
        self.emit('Testing one')
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),2)
        self.emit('Testing 1 2 3')
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),4)
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'recommended')
        self.page.evaluate("document.getElementById('volumeSetting').value='0.015';document.getElementById('volumeSetting').dispatchEvent(new Event('input'))")
        self.assertEqual(self.page.locator('#transcriptionVolume').input_value(),'0.015')
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_function("document.getElementById('timingTestProgress').value===2000",timeout=4000)
        self.assertIn('passed',self.page.locator('#timingTestLabel').inner_text())
        self.page.evaluate("window.__audioContext.state='suspended';window.__audioContext.onstatechange()")
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'recommended')
        self.page.reload()
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'recommended')
        self.assertEqual(self.page.locator('#volumeOption').get_attribute('data-availability'),'available')
        self.assertEqual(self.page.locator('#volumeSetting').input_value(),'0.015')

    def test_compact_setup_fits_phone_screen(self):
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.page.locator('#consentReject').click()
        for width,height in [(390,844),(360,740),(1365,768)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            self.assertTrue(self.page.evaluate('document.documentElement.scrollHeight<=innerHeight'),f'{width}x{height} should fit one screen')
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.screenshot(path=str(Path(__file__).resolve().parents[1]/'test-results'/'compact-setup.png'),full_page=True)


if __name__=='__main__':unittest.main()
