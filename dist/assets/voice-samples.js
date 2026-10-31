const cards=[...document.querySelectorAll('.voice-sample-card')];
document.getElementById('voiceSearch').addEventListener('input',event=>{
  const query=event.target.value.trim().toLowerCase();
  let visible=0;
  for(const card of cards){card.hidden=!card.dataset.search.includes(query);if(!card.hidden)visible++;else card.querySelector('audio').pause();}
  document.getElementById('sampleCount').textContent=`${visible} of ${cards.length} voices`;
  document.getElementById('noVoices').hidden=visible>0;
});
document.addEventListener('play',event=>{
  if(!(event.target instanceof HTMLAudioElement))return;
  for(const audio of document.querySelectorAll('audio'))if(audio!==event.target)audio.pause();
},true);
