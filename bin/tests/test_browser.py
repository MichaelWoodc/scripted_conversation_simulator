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
window.__played=[];window.__questionPlayed=[];window.__level=0;window.__holdAudio=false;window.__blockNextAudio=false;window.__captureCount=0;window.__captureActive=false;
class TestRecognition {
  static instances=[];
  constructor(){TestRecognition.instances.push(this);}
  start(){this.running=true;setTimeout(()=>{if(!this.running)return;if(window.__rejectConcurrentCapture&&window.__captureActive)this.onerror?.({error:'audio-capture'});else if(window.__recognitionError)this.onerror?.({error:window.__recognitionError});else if(!window.__recognitionSilent){this.onstart?.();if(document.body.dataset.page==='setup'&&!window.__noTestWords)TestRecognition.emit('Testing one two three');}},0);}
  abort(){this.running=false;this.onend?.();}
  static emit(text,final=false){
    const item=Object.assign([{transcript:text,confidence:0.9}],{isFinal:final});
    TestRecognition.instances.at(-1)?.onresult?.({resultIndex:0,results:[item]});
  }
}
window.SpeechRecognition=TestRecognition;window.__recognition=TestRecognition;
Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{
  window.__captureCount++;
  if(window.__denyMicrophone)throw new DOMException('Microphone access denied','NotAllowedError');
  window.__captureActive=true;
  const track={label:'Test microphone',stop(){window.__micStopped=true;window.__captureActive=false;},getSettings:()=>({sampleRate:48000})};
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
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.assertFalse(self.page.locator('#startGate').is_visible())
        if self.page.evaluate("navigator.userAgentData?.mobile"):
            self.assertEqual(self.page.evaluate('window.__captureCount'),1)
            self.assertTrue(self.page.evaluate('window.__captureActive'))
        self.page.locator('#continueToSession').click()
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='idle'")

    def test_html_pages_are_not_cached(self):
        for path in ('index.html','setup.html','sets/'+self.fixture['page'].split('/')[-1]):
            response=self.page.request.get(self.base_url+path)
            self.assertIn('no-store',response.headers.get('cache-control',''))

    def test_clear_all_storage_resets_consent_and_local_storage(self):
        self.page.goto(self.base_url)
        self.page.wait_for_function("!document.getElementById('catalogStatus').textContent.includes('Loading')")
        self.page.locator('#consentAccept').click()
        self.page.evaluate("localStorage.setItem('test-clear-key','stored');document.cookie='test_clear_cookie=yes; Path=/'")
        self.page.on('dialog',lambda dialog:dialog.accept())
        self.page.locator('#clearAllStorage').click()
        self.page.wait_for_function("!document.getElementById('consentBanner').hidden")
        self.assertEqual(self.page.evaluate('localStorage.length'),0)
        self.assertNotIn('test_clear_cookie',self.page.evaluate('document.cookie'))

    def test_consent_precedes_dimmed_start_gate_and_start_activates_mic(self):
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id']+'&change=1')
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.assertTrue(self.page.locator('#consentBanner').is_visible())
        self.assertTrue(self.page.locator('#startGate').is_visible())
        self.assertEqual(self.page.locator('#startGate').evaluate('(element)=>getComputedStyle(element).backgroundColor'),'rgba(23, 59, 50, 0.64)')
        self.page.locator('#consentReject').click()
        self.assertTrue(self.page.locator('#startGate').is_visible())
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.assertFalse(self.page.locator('#startGate').is_visible())
        self.assertGreaterEqual(self.page.evaluate('window.__captureCount'),1)

    def start(self):
        if self.page.locator('#sessionStartGate').is_visible():self.page.locator('#beginConversationButton').click()
        else:self.page.locator('#startButton').click()
        self.page.wait_for_function("document.getElementById('statusText').textContent==='Listening'")

    def emit(self,text,final=False):
        self.page.evaluate('([text,final])=>window.__recognition.emit(text,final)',[text,final])

    def test_interim_highlights_fuzzy_match_silence_and_once_order(self):
        self.open_session();self.start();self.page.locator('#debugToggle').click()
        script_box=self.page.locator('#questionText')
        initial_size=script_box.evaluate('(element)=>({width:element.getBoundingClientRect().width,height:element.getBoundingClientRect().height})')
        initial_dimensions=self.page.evaluate("['.practice-layout','.practice-main','.question-card','#questionText'].map(selector=>{const box=document.querySelector(selector).getBoundingClientRect();return [selector,box.width,box.height]})")
        self.page.evaluate('window.__level=0.08')
        self.emit('Has the employee')
        self.assertEqual(self.page.locator('#questionText .heard').count(),3)
        self.emit('Has the worker had training for this task')
        self.assertIn('worker',self.page.locator('#transcript').inner_text())
        self.page.wait_for_timeout(1050)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'Must wait until speech stops')
        self.page.evaluate('window.__oldRecognizer=window.__recognition.instances.at(-1); window.__level=0')
        self.page.wait_for_function("document.getElementById('stepLabel').textContent==='Question 2 of 2'")
        self.assertIn('When did the employee receive the training?',self.page.locator('#questionText > :not([hidden])').inner_text())
        final_size=script_box.evaluate('(element)=>({width:element.getBoundingClientRect().width,height:element.getBoundingClientRect().height})')
        dimensions=self.page.evaluate("['.practice-layout','.practice-main','.question-card','#questionText'].map(selector=>{const box=document.querySelector(selector).getBoundingClientRect();return [selector,box.width,box.height]})")
        self.assertEqual(final_size,initial_size,(initial_dimensions,dimensions))
        self.page.wait_for_function('window.__played.length===2',timeout=4000)
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
        self.assertEqual(self.page.locator('body[data-page=session] > .site-header').count(),0)
        self.assertTrue(self.page.locator('.session-footer-links').is_visible())
        self.page.set_viewport_size({'width':1365,'height':1600})
        self.assertAlmostEqual(self.page.locator('.session-footer').evaluate('(element)=>element.getBoundingClientRect().bottom'),1600,delta=1)
        self.page.set_viewport_size({'width':390,'height':550})
        self.assertGreater(self.page.locator('.session-footer').evaluate('(element)=>element.getBoundingClientRect().bottom'),550)
        out=Path(__file__).resolve().parents[1]/'test-results';out.mkdir(exist_ok=True)
        self.page.screenshot(path=str(out/'mobile.png'),full_page=True)

    def test_settings_panel_closes_when_continuing_conversation(self):
        self.page.goto(self.url+'?mode=manual')
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='idle'")
        self.assertFalse(self.page.locator('#sessionTitle').is_visible())
        self.assertIn('session-toolbar',self.page.locator('#settingsToggle').evaluate('(element)=>element.parentElement.className'))
        self.assertTrue(self.page.locator('#sessionStartGate').is_visible())
        self.assertFalse(self.page.locator('#startButton').is_visible())
        if self.page.locator('#consentReject').is_visible():self.page.locator('#consentReject').click()
        self.start();self.page.locator('#pauseButton').click()
        self.page.locator('#settingsToggle').click()
        self.assertTrue(self.page.locator('#settingsPanel').is_visible())
        self.assertEqual(self.page.locator('#settingsPanel').evaluate('(element)=>getComputedStyle(element).position'),'fixed')
        self.assertEqual(self.page.locator('#settingsToggle').get_attribute('aria-expanded'),'true')
        self.assertEqual(self.page.locator('#startButtonLabel').inner_text(),'Continue listening')
        self.page.locator('#startButton').click()
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='listening'")
        self.assertFalse(self.page.locator('#settingsPanel').is_visible())
        self.assertEqual(self.page.locator('#settingsToggle').get_attribute('aria-expanded'),'false')

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
        self.assertEqual(page.locator('.session-card:visible').count(),sum(item['voice']=='af_heart' for item in self.catalog['sets']))
        self.assertEqual(page.locator('#edition option').count(),2)
        for item in self.catalog['sets']:
            page.goto(self.base_url+item['page'])
            self.assertEqual(page.locator('#sessionTitle').count(),0)
            self.assertEqual(page.title(),f'{item["title"]} Conversation Lab')
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
            expected=[item for item in self.catalog['sets'] if item['edition']==edition and item['voice']=='af_heart']
            cards=self.page.locator('.session-card:visible')
            self.assertEqual(cards.count(),len(expected))
            self.assertEqual(cards.evaluate_all('(cards)=>cards.map(card=>card.dataset.setId)'),[item['id'] for item in expected])
        self.assertTrue(self.page.evaluate("window.__firstCard===document.querySelector('.session-card')"))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))

    def test_catalog_failure_preserves_static_library(self):
        self.page.route('**/catalog.json',lambda route:route.fulfill(status=503,body='Unavailable'))
        self.page.goto(self.base_url)
        self.page.wait_for_function("document.getElementById('catalogStatus').textContent.includes('503')")
        self.assertEqual(self.page.locator('.session-card:visible').count(),sum(item['voice']=='af_heart' for item in self.catalog['sets']))

    def test_voice_timing_counts_only_voice_and_waits_for_adjustable_pause(self):
        self.page.add_init_script('delete window.SpeechRecognition; delete window.webkitSpeechRecognition;')
        self.open_session()
        self.assertIn('Voice timing',self.page.locator('#modeStatus').inner_text())
        self.page.locator('#debugToggle').click()
        self.assertIn('does not provide',self.page.locator('#recognitionReason').inner_text())
        self.assertEqual(self.page.locator('#fallbackSilenceSetting').input_value(),'2500')
        self.start()
        self.page.wait_for_timeout(350)
        self.assertEqual(self.page.locator('#voiceProgressBar').get_attribute('aria-valuenow'),'0')
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_timeout(650)
        self.page.evaluate('window.__level=0')
        self.page.wait_for_timeout(1800)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'A pause before 75% must not play an answer')
        self.page.evaluate("document.getElementById('fallbackSilenceSetting').value='1500';document.getElementById('fallbackSilenceSetting').dispatchEvent(new Event('input'))")
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_function("Number(document.getElementById('voiceProgressBar').getAttribute('aria-valuenow'))>=85")
        self.page.wait_for_timeout(1700)
        self.assertEqual(self.page.evaluate('window.__played.length'),0,'Continued speech must postpone the answer')
        self.assertEqual(self.page.locator('#questionText .heard').count(),0)
        self.page.evaluate('window.__level=0')
        self.page.wait_for_function('window.__played.length===2',timeout=3500)
        self.page.wait_for_function("document.getElementById('stepLabel').textContent==='Question 2 of 2'")
        self.assertEqual(self.page.locator('#voiceProgressBar').get_attribute('aria-valuenow'),'0')

    def test_recognition_network_error_keeps_transcription_until_mode_change(self):
        self.open_session();self.start()
        self.page.evaluate("window.__recognition.instances.at(-1).onerror({error:'network'})")
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.page.locator('#debugToggle').click()
        self.assertIn('could not connect',self.page.locator('#recognitionReason').inner_text())
        self.assertIn('Change mode',self.page.locator('#recognitionReason').inner_text())
        self.assertIn('Test microphone',self.page.locator('#deviceReport').inner_text())
        self.assertFalse(self.page.locator('#voiceProgress').is_visible())

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
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});window.__denyMicrophone=true;delete window.SpeechRecognition;delete window.webkitSpeechRecognition;")
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'))
        self.page.locator('#consentAccept').click()
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
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
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),0)
        self.emit('Testing one')
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),2)
        self.emit('Testing 123')
        self.assertEqual(self.page.locator('.test-phrase .heard').count(),4)
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'recommended')
        self.page.evaluate("document.getElementById('volumeSetting').value='0.015';document.getElementById('volumeSetting').dispatchEvent(new Event('input'))")
        self.assertEqual(self.page.locator('#volumeSetting').input_value(),'0.015')
        self.assertEqual(self.page.locator('#transcriptionVolume').count(),0)
        self.page.evaluate('window.__level=0.08')
        self.page.wait_for_function("document.getElementById('timingTestProgress').value===1000",timeout=4000)
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
        self.page.locator('.setup-settings').evaluate('(el)=>el.open=true')
        self.page.evaluate("const slider=document.getElementById('fallbackSilenceSetting');slider.value='3400';slider.dispatchEvent(new Event('input'))")
        self.assertEqual(self.page.locator('#setupSilenceValue').inner_text(),'3.4 seconds')
        self.page.locator('.setup-settings').evaluate('(el)=>el.open=false')
        for width,height in [(390,844),(360,740),(1365,768)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            dimensions=self.page.evaluate('({scroll:document.documentElement.scrollHeight,viewport:innerHeight})')
            self.assertTrue(dimensions['scroll']<=dimensions['viewport'],f'{width}x{height} should fit one screen: {dimensions}')
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.screenshot(path=str(Path(__file__).resolve().parents[1]/'test-results'/'compact-setup.png'),full_page=True)

    def test_answer_settings_switch_recordings_and_keep_heart_default(self):
        alternate=deepcopy(self.fixture);alternate['id']='bella-test';alternate['voice']='af_bella'
        for step in alternate['steps']:
            for clip in step['clips']:clip['url']+='&speaker=bella'
        self.page.route('**/catalog.json',lambda route:route.fulfill(content_type='application/json',body=json.dumps({'sets':[self.fixture,alternate]})))
        self.page.route('**/sets/*.html*',lambda route:route.fulfill(content_type='text/html',body=render_session(self.fixture,[self.fixture,alternate])))
        self.page.goto(self.url+'?mode=manual')
        self.page.wait_for_function("document.getElementById('statusPill').dataset.state==='idle'")
        self.assertEqual(self.page.locator('#answerVoiceSelect').input_value(),'af_heart')
        self.page.locator('#consentReject').click()
        self.page.locator('#settingsToggle').click()
        self.page.select_option('#answerVoiceSelect','af_bella')
        self.assertEqual(self.page.locator('#voiceLabel').inner_text(),'bella')
        self.start();self.page.locator('#finishButton').click()
        self.page.wait_for_function('window.__played.length===2')
        self.assertTrue(all('speaker=bella' in url for url in self.page.evaluate('window.__played')))

    def test_speaking_time_controls_are_at_question_bottom_and_live(self):
        self.page.add_init_script('delete window.SpeechRecognition;delete window.webkitSpeechRecognition;')
        self.open_session()
        self.assertTrue(self.page.locator('#speakingSettings').is_visible())
        self.assertFalse(self.page.locator('#speakingPercentSetting').is_visible())
        self.page.locator('#speakingSettings summary').click()
        self.assertTrue(self.page.locator('#speakingPercentSetting').is_visible())
        self.assertEqual(self.page.locator('#volumeSetting').input_value(),'0.007')
        self.assertEqual(self.page.locator('#fallbackSilenceSetting').get_attribute('min'),'500')
        self.assertEqual(self.page.locator('#speakingPercentSetting').input_value(),'45')
        self.assertEqual(self.page.locator('#fallbackSilenceSetting').input_value(),'2500')
        self.assertTrue(self.page.evaluate("document.querySelector('.question-card').lastElementChild.id==='speakingSettings'"))
        for control,value in [('speakingPercentSetting','65'),('fallbackSilenceSetting','500'),('volumeSetting','0.02')]:
            self.page.evaluate("([id,value])=>{const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('input'));}",[control,value])
        self.assertEqual(self.page.locator('#speakingPercentValue').inner_text(),'65%')
        self.assertEqual(self.page.locator('#silenceValue').inner_text(),'0.5 seconds')
        self.assertEqual(self.page.locator('#volumeValue').inner_text(),'0.020')

    def test_all_voice_samples_are_playable_and_filterable_on_mobile(self):
        import wave
        from project_paths import DIST
        registry=json.loads((DIST.parent/'data/kokoro_voices.json').read_text())
        for voice in registry:
            path=DIST/'media/voice-samples'/f'{voice["id"]}.wav'
            with wave.open(str(path),'rb') as audio:
                self.assertGreater(audio.getnframes()/audio.getframerate(),0)
            metadata=json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(metadata['phrase'],'The quick brown fox jumps over the lazy dog.')
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.goto(self.base_url+'voice-samples.html')
        self.assertEqual(self.page.locator('.voice-sample-card audio').count(),len(registry))
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.page.locator('#voiceSearch').fill('British English')
        self.assertEqual(self.page.locator('.voice-sample-card:visible').count(),8)
        self.page.locator('#voiceSearch').fill('af_bella')
        self.assertEqual(self.page.locator('.voice-sample-card:visible').count(),1)
        response=self.page.request.get(self.base_url+'media/voice-samples/af_bella.wav')
        self.assertEqual(response.status,200)
        self.assertTrue(response.body().startswith(b'RIFF'))

    def test_voice_sample_playback_pauses_other_samples(self):
        context=self.browser.new_context()
        self.addCleanup(context.close)
        page=context.new_page()
        page.goto(self.base_url+'voice-samples.html')
        page.locator('h1').click()
        page.locator('audio').nth(0).evaluate('(audio)=>audio.play()')
        page.wait_for_function("!document.querySelectorAll('audio')[0].paused")
        page.locator('audio').nth(1).evaluate('(audio)=>audio.play()')
        page.wait_for_function("document.querySelectorAll('audio')[0].paused&&!document.querySelectorAll('audio')[1].paused")

    def test_android_transcription_uses_one_microphone_and_restarts_short_sessions(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});")
        self.open_session()
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.start()
        self.assertEqual(self.page.evaluate('window.__captureCount'),0,'Practice transcription must not open a competing microphone stream')
        self.assertFalse(self.page.evaluate('window.__recognition.instances.at(-1).continuous'))
        self.emit('Has the employee received',True)
        self.page.evaluate('window.__oldPhoneRecognition=window.__recognition.instances.at(-1);window.__oldPhoneRecognition.onend()')
        self.page.wait_for_function('window.__recognition.instances.at(-1)!==window.__oldPhoneRecognition')
        self.emit('formal training on this task',True)
        self.assertEqual(self.page.locator('#questionText .heard').count(),9)
        self.page.evaluate("window.__oldPhoneRecognition.onresult({results:[Object.assign([{transcript:'stale result'}],{isFinal:true})]})")
        self.assertNotIn('stale',self.page.locator('#transcript').text_content())
        self.page.wait_for_function('window.__played.length===2',timeout=4000)

    def test_mobile_transcription_survives_empty_startup_sessions(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});window.__noTestWords=true;window.__testClock=0;Object.defineProperty(performance,'now',{configurable:true,value:()=>window.__testClock});")
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id'])
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        if self.page.locator('#consentAccept').is_visible():self.page.locator('#consentAccept').click()
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        for _ in range(4):
            previous=self.page.evaluate('window.__recognition.instances.length')
            self.page.evaluate('window.__recognition.instances.at(-1).onend()')
            self.page.wait_for_function('window.__recognition.instances.length>'+str(previous))
        self.emit('Testing one two three')
        self.page.wait_for_function("document.getElementById('transcriptionOption').dataset.availability==='recommended'")
        self.page.locator('#continueToSession').click()
        self.page.wait_for_function("document.getElementById('statusPill')?.dataset.state==='idle'")
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.start()
        self.assertEqual(self.page.locator('#statusPill').get_attribute('data-speech-detected'),'pending')
        self.assertEqual(self.page.locator('#statusPill').evaluate('(element)=>getComputedStyle(element).color'),'rgb(164, 59, 50)')
        self.page.evaluate('window.__testClock=21000')
        self.page.wait_for_timeout(120)
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.assertEqual(self.page.locator('#statusPill').get_attribute('data-speech-detected'),'pending')
        self.emit('Has the employee received formal training on this task?',True)
        self.assertEqual(self.page.locator('#statusPill').get_attribute('data-speech-detected'),'detected')
        self.assertNotEqual(self.page.locator('#statusPill').evaluate('(element)=>getComputedStyle(element).color'),'rgb(164, 59, 50)')
        self.page.evaluate('window.__testClock+=1000')
        self.page.wait_for_function('window.__played.length===2',timeout=4000)

    def test_mobile_session_refresh_requires_a_fresh_microphone_check(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});document.cookie='conversation_lab_device='+encodeURIComponent(JSON.stringify({mode:'transcription',pause:2500,volume:0.007,skip:true,micOK:true,speechOK:true}))+'; Path=/';")
        self.page.goto(self.url+'?mode=transcription&pause=2500&volume=0.007&reason=working')
        self.page.wait_for_function("document.body.dataset.page==='setup'&&document.getElementById('deviceSetup')?.dataset.ready==='true'")
        self.assertIn('change=1',self.page.url)
        self.assertTrue(self.page.locator('#transcriptionChoice').is_checked())
        self.assertEqual(self.page.locator('#transcriptionOption').get_attribute('data-availability'),'recommended')
        self.assertIn('Test microphone and transcription',self.page.locator('#deviceStatus').inner_text())

    def test_mobile_transcription_check_reports_when_service_is_listening(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});window.__noTestWords=true;window.__level=0.08;")
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id']+'&change=1')
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        if self.page.locator('#consentAccept').is_visible():self.page.locator('#consentAccept').click()
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.page.wait_for_function("Number(document.getElementById('transcriptionLevel').value)>0")
        self.assertTrue(self.page.locator('#retryTranscriptionButton').is_hidden())
        self.assertTrue(self.page.locator('#retryTimingButton').is_hidden())
        self.assertIn('Transcription started',self.page.locator('#transcriptionDetail').inner_text())
        self.assertIn('Transcription test: Transcription started',self.page.locator('#deviceReport').inner_text())
        self.assertNotIn('Transcription test: not checked',self.page.locator('#deviceReport').inner_text())

    def test_mobile_without_transcription_recommends_timing_and_explains_why(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});delete window.SpeechRecognition;delete window.webkitSpeechRecognition;")
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id']+'&change=1')
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        if self.page.locator('#consentAccept').is_visible():self.page.locator('#consentAccept').click()
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.assertEqual(self.page.locator('#volumeOption').get_attribute('data-availability'),'recommended')
        self.assertTrue(self.page.locator('#transcriptionChoice').is_disabled())
        self.assertTrue(self.page.locator('#retryTranscriptionButton').is_hidden())
        self.assertIn('does not provide speech transcription',self.page.locator('#transcriptionDetail').inner_text())
        self.assertTrue(self.page.evaluate('window.__captureActive'))

    def test_transcription_passes_on_any_word_and_keeps_last_twenty(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});window.__noTestWords=true;window.__level=0.08;")
        self.page.goto(self.base_url+'setup.html?set='+self.fixture['id']+'&change=1')
        self.page.wait_for_function("document.getElementById('deviceSetup').dataset.ready==='true'")
        if self.page.locator('#consentAccept').is_visible():self.page.locator('#consentAccept').click()
        self.page.locator('#beginSetupButton').click()
        self.page.wait_for_function("!document.getElementById('continueToSession').disabled")
        self.emit('mango',True)
        self.page.wait_for_function("document.getElementById('transcriptionOption').dataset.availability==='recommended'")
        self.assertTrue(self.page.locator('#transcriptionChoice').is_checked())
        self.assertEqual(self.page.locator('#transcriptionPreview').input_value(),'mango')
        self.emit('1 2 3',True)
        self.assertTrue(self.page.locator('#transcriptionChoice').is_checked())
        self.assertEqual(self.page.locator('#transcriptionPreview').input_value(),'1 2 3')
        self.emit('the quick brown fox jumps',True)
        self.assertEqual(self.page.locator('#transcriptionPreview').input_value(),'the quick brown fox jumps')
        twenty=' '.join(f'word{index}' for index in range(1,22))
        self.emit(twenty,True)
        expected=' '.join(f'word{index}' for index in range(2,22))
        self.assertEqual(self.page.locator('#transcriptionPreview').input_value(),expected)
        self.assertGreater(self.page.locator('#transcriptionPreview').evaluate('(element)=>element.scrollTop'),0)
        self.assertIn('Transcription passed',self.page.locator('#deviceStatus').inner_text())

    def test_session_keeps_transcription_after_recognition_error(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});")
        self.open_session();self.start()
        self.emit('Has the employee received',True)
        self.page.evaluate("window.__recognition.instances.at(-1).onerror({error:'network'})")
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.assertIn('Change mode',self.page.locator('#recognitionReason').inner_text())
        self.assertFalse(self.page.locator('#voiceProgress').is_visible())

    def test_android_transcription_error_keeps_mode_and_requires_explicit_change(self):
        self.page.add_init_script("Object.defineProperty(navigator,'userAgentData',{configurable:true,value:{mobile:true}});")
        self.open_session();self.start()
        self.page.evaluate("window.__recognition.instances.at(-1).onerror({error:'network'})")
        self.assertIn('Speech transcription',self.page.locator('#modeStatus').inner_text())
        self.assertIn('Change mode',self.page.locator('#recognitionReason').inner_text())
        self.assertEqual(self.page.evaluate('window.__captureCount'),0)
        self.assertFalse(self.page.evaluate('window.__recognition.instances.at(-1).running'))


if __name__=='__main__':unittest.main()
