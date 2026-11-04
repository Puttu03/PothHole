"use strict";
(()=>{const sheet=document.getElementById('searchPanel'),toggle=document.getElementById('plannerToggle'),title=document.getElementById('plannerTitle'),arrow=document.getElementById('plannerArrow');
function expand(open){sheet.classList.toggle('expanded',open);document.body.classList.toggle('planner-open',open);toggle.setAttribute('aria-expanded',String(open));arrow.textContent=open?'⌄':'⌃';setTimeout(()=>window.potholeMap?.invalidateSize(),50)}
toggle.onclick=()=>expand(!sheet.classList.contains('expanded'));
document.getElementById('planBtn').addEventListener('click',()=>expand(true));
document.getElementById('findRoutes').addEventListener('click',()=>{title.textContent='Route planner'});
const choices=document.getElementById('routeChoices');choices.addEventListener('click',e=>{if(e.target.closest('button')){title.textContent='Route selected · Tap to change';expand(false)}});
const observer=new MutationObserver(()=>{if(choices.querySelector('button')){title.textContent='Choose a driving route';expand(true)}});observer.observe(choices,{childList:true});
document.getElementById('clearBtn').addEventListener('click',()=>title.textContent='Where do you want to go?');
const media=matchMedia('(max-width:720px)');media.addEventListener('change',()=>{if(!media.matches)expand(false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')expand(false)});
})();