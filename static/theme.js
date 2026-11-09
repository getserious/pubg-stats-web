(function(){
 'use strict';
 const root=document.documentElement,platforms=['steam','kakao','psn','xbox'];
 const read=(key,fallback)=>{try{return localStorage.getItem(key)||fallback}catch{return fallback}};
 const write=(key,value)=>{try{localStorage.setItem(key,value)}catch{}};
 let theme=read('gamegg-theme-v2','light'),platform=read('gamegg-platform','steam'),initialized=false;
 if(!['dark','light'].includes(theme))theme='light';if(!platforms.includes(platform))platform='steam';
 function refreshControls(){
  document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===theme)));
  document.querySelectorAll('[data-platform-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.platformChoice===platform)));
  const colors=theme==='light'?{steam:'#28638f',kakao:'#b59300',psn:'#0063b8',xbox:'#147b31'}:{steam:'#83b1db',kakao:'#e1ca60',psn:'#7fb8f2',xbox:'#88cda1'};
  for(const id of ['platform','postPlatform','leaderPlatform']){const select=document.getElementById(id);if(select)select.style.setProperty('--selection-color',colors[select.value]||colors.steam);}
 }
 function applyTheme(value,persist=true){theme=value==='light'?'light':'dark';root.dataset.theme=theme;root.style.colorScheme=theme;if(persist)write('gamegg-theme-v2',theme);refreshControls();}
 function applyPlatform(value,persist=true){platform=platforms.includes(value)?value:'steam';root.dataset.platform=platform;if(persist)write('gamegg-platform',platform);refreshControls();}
 // This script is loaded before CSS to avoid a flash of the wrong theme.
 applyTheme(theme,false);applyPlatform(platform,false);
 function init(){
  if(initialized||!document.body)return;initialized=true;
  const page=document.body.dataset.page;
  document.querySelectorAll('[data-nav]').forEach(a=>{if(a.dataset.nav===page)a.setAttribute('aria-current','page')});
  for(const id of ['platform','postPlatform','leaderPlatform']){const select=document.getElementById(id);if(select){select.value=platform;select.addEventListener('change',()=>{if(id==='platform'||(id==='postPlatform'&&page==='teams'))applyPlatform(select.value);else refreshControls();});}}
  document.querySelectorAll('[data-theme-choice]').forEach(b=>b.addEventListener('click',()=>applyTheme(b.dataset.themeChoice)));
  document.querySelectorAll('[data-platform-choice]').forEach(b=>b.addEventListener('click',()=>{const select=document.getElementById('platform');if(select){select.value=b.dataset.platformChoice;select.dispatchEvent(new Event('change',{bubbles:true}));}}));
  refreshControls();
 }
 window.GameggTheme={init,applyTheme,applyPlatform};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
 window.addEventListener('storage',e=>{if(e.key==='gamegg-theme-v2')applyTheme(e.newValue,false)});
})();
