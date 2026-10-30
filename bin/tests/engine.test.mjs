import test from 'node:test';
import assert from 'node:assert/strict';
import {matchQuestion,SessionProgress} from '../site/assets/engine.js';

const question='Has the employee received formal training on this task?';
test('interim words align and an incomplete question does not trigger',()=>{
  const partial=matchQuestion(question,'Has the employee');
  assert.equal(partial.ready,false);assert.equal(partial.matched.size,3);
  assert.equal(matchQuestion(question,question).ready,true);
});
test('close wording is accepted; unrelated speech is rejected',()=>{
  assert.equal(matchQuestion(question,'Has the worker had training for this task').ready,true);
  assert.equal(matchQuestion(question,'The weather outside is sunny today').ready,false);
  assert.equal(matchQuestion('How often?','How frequently').ready,true);
});
test('a pause halfway through a long question does not complete it',()=>{
  const q='Is a job aid for completing the task visibly located or easily accessible in the task area?';
  assert.equal(matchQuestion(q,'Is a job aid for completing the task').ready,false);
});
const feedbackQuestion='For vocal feedback, was that feedback positive feedback for steps performed correctly or corrective feedback for steps performed incorrectly?';
test('the first feedback highlights before later occurrences',()=>{
  const result=matchQuestion(feedbackQuestion,'For vocal feedback');
  assert.deepEqual([...result.matched].sort((a,b)=>a-b),[0,1,2]);
  assert.equal(result.ending,false);
});
test('every spoken prefix fills expected words from left to right',()=>{
  const words=feedbackQuestion.match(/[A-Za-z]+/g);
  for(let length=1;length<=words.length;length++) {
    const result=matchQuestion(feedbackQuestion,words.slice(0,length).join(' '));
    assert.deepEqual([...result.matched].sort((a,b)=>a-b),Array.from({length},(_,i)=>i));
  }
});
test('repeated words consume successive occurrences, one per heard word',()=>{
  for(let count=1;count<=4;count++) {
    const result=matchQuestion(feedbackQuestion,Array(count).fill('feedback').join(' '));
    assert.deepEqual([...result.matched].sort((a,b)=>a-b),[2,5,7,14].slice(0,count));
  }
});
const fixture=()=>({id:'set',version:'1',steps:[{id:'q1',clips:[{id:'a1'},{id:'a2'}]},{id:'q2',clips:[{id:'a3'}]}]});
const storage=()=>{const map=new Map();return{getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v)};};
test('answers are reserved once and cannot advance out of sequence',()=>{
  const p=new SessionProgress(fixture(),storage());
  assert.equal(p.markAsked(),true);assert.equal(p.markAsked(),false);
  assert.equal(p.advance(),false);assert.equal(p.markStarted({id:'a3'}),false);
  assert.equal(p.markStarted({id:'a1'}),true);assert.equal(p.markStarted({id:'a1'}),false);
  assert.equal(p.advance(),false);assert.equal(p.markStarted({id:'a2'}),true);
  assert.equal(p.advance(),true);assert.equal(p.index,1);
});
test('refresh never replays a clip that already started',()=>{
  const memory=storage(),set=fixture();let p=new SessionProgress(set,memory);
  p.markAsked();p.markStarted({id:'a1'});
  p=new SessionProgress(set,memory);assert.deepEqual(p.remainingClips.map(c=>c.id),['a2']);
  p.markStarted({id:'a2'});p=new SessionProgress(set,memory);assert.equal(p.index,1);
  p.markAsked();p.markStarted({id:'a3'});p.advance();assert.equal(p.complete,true);
  p.reset();assert.equal(p.index,0);assert.equal(p.played.size,0);
});
