'use strict';
const $=id=>document.getElementById(id), esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=v=>v==null?'—':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:1});
const maps={Baltic_Main:'에란겔',Desert_Main:'미라마',Savage_Main:'사녹',DihorOtok_Main:'비켄디',Summerland_Main:'카라킨',Chimera_Main:'파라모',Tiger_Main:'태이고',Kiki_Main:'데스턴',Neon_Main:'론도',Heaven_Main:'헤이븐',Range_Main:'훈련장'};
const tierNames={Bronze:'브론즈',Silver:'실버',Gold:'골드',Platinum:'플래티넘',Crystal:'크리스탈',Diamond:'다이아몬드',Master:'마스터',Survivor:'서바이버',Unranked:'미배치'};
let active=null,generation=0,history=[],profile=null,admin={},category='duo',styleData=null;
const mode=()=>$('rankMode').value, seconds=n=>n==null?'—':`${Math.floor(n/60)}분 ${Math.round(n%60)}초`;
async function get(path,params={}){const r=await fetch(path+'?'+new URLSearchParams(params),{cache:'no-store'}),d=await r.json();if(!d.ok)throw Error(d.error||'조회 실패');return d}
async function send(path,data,method='POST'){const r=await fetch(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':admin.csrf||''},body:JSON.stringify(data)}),d=await r.json();if(!d.ok)throw Error(d.error||'요청 실패');return d}
function table(head,rows){return `<div class="table-scroll"><table><thead><tr>${head.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
const modeNames={all:'전체 모드',solo:'솔로 3인칭','solo-fpp':'솔로 1인칭',duo:'듀오 3인칭','duo-fpp':'듀오 1인칭',squad:'스쿼드 3인칭','squad-fpp':'스쿼드 1인칭'};
function perspectiveLabel(value){return value==='fpp'?'1인칭':'3인칭';}
function modeLabel(value){const raw=String(value||'');if(modeNames[raw])return modeNames[raw];const party=raw.match(/(?:^|-)(solo|duo|squad)(?:-|$)/)?.[1];if(!party)return '기타 모드';const label=modeNames[party+(raw.endsWith('-fpp')?'-fpp':'')];const prefix=raw.split('-')[0],types={normal:'일반전',war:'워 모드',zombie:'좀비 모드',conquest:'점령전',esports:'이스포츠'};return types[prefix]?label+' · '+types[prefix]:label;}
function uniqueSeasonOptions(items,currentId=''){
 const result=new Map();for(const original of items||[]){const number=String(original.number??original.id?.split('-').at(-1)??''),key=/^\d+$/.test(number)?String(Number(number)):number,item={...original,number:key};const old=result.get(key);if(!old||(!old.current&&item.current)||(item.id===currentId&&old.id!==currentId))result.set(key,item);}
 return [...result.values()].sort((a,b)=>(Number(b.current)-Number(a.current))||(Number(b.number)-Number(a.number)));
}
const customTiers=[[9500,'HighRanker'],[6000,'챌린저'],[5500,'그랜드마스터'],[4800,'마스터'],[4000,'다이아몬드'],[3200,'플래티넘'],[2400,'골드'],[1600,'실버'],[800,'브론즈'],[0,'아이언']];
function customTier(rp){if(rp==null||!Number.isFinite(Number(rp)))return null;return customTiers.find(([minimum])=>Number(rp)>=minimum)}
function customBadge(rp){const tier=customTier(rp);return tier?`<span class="custom-badge">GAME.GG · ${esc(tier[1])}</span>`:''}
function renderTierGuide(rp){$('tierGuide').innerHTML=customTiers.map(([min,label],i)=>`<div class="tier-cell ${customTier(rp)?.[0]===min?'is-current':''}"><span class="tier-level">${String(customTiers.length-i).padStart(2,'0')}</span><strong>${esc(label)}</strong><small>${num(min)}${i===0?' RP 이상':' ~ '+num(customTiers[i-1][0]-1)+' RP'}</small></div>`).join('')}
function badge(t){if(!t)return '<span class="rank-badge unranked">미배치 / 티어 정보 없음</span>';if(typeof t==='string')t={tier:t};const key=Object.keys(tierNames).find(k=>k.toLowerCase()===String(t.tier).toLowerCase())||'Unranked';const sub=String(t.subTier||''),roman={1:'I',2:'II',3:'III',4:'IV',5:'V'}[sub]||sub;return `<span class="rank-badge"><span class="rank-art rank-${key.toLowerCase()}" aria-hidden="true"></span><span class="rank-copy"><small>PUBG 공식 티어</small><strong>${tierNames[key]} ${['Master','Survivor','Unranked'].includes(key)?'':esc(roman)}</strong></span></span>`}
function metricCard(label,value,caption=''){return `<div class="metric-card"><span>${esc(label)}</span><strong>${value}</strong>${caption?`<small>${esc(caption)}</small>`:''}</div>`}
function kdaMetric(s){
 const count=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value))&&Number(value)>=0&&Number.isInteger(Number(value))?Number(value):null;
 const kills=count(s.kills),assists=count(s.assists),deaths=count(s.deaths);
 if(kills!==null&&assists!==null&&deaths!==null){
  const caption=`${num(kills)}킬 + ${num(assists)}도움 / ${num(deaths)}사망`;
  if(deaths===0)return {text:'—',caption:caption+' · 사망 0회로 비율 계산 불가'};
  return {text:((kills+assists)/deaths).toFixed(2),caption};
 }
 const raw=s.kda!==null&&s.kda!==undefined&&s.kda!==''&&typeof s.kda!=='boolean'?Number(s.kda):NaN;
 if(Number.isFinite(raw)&&raw>0)return {text:raw.toFixed(2),caption:'API 집계값 · 처치/도움/사망 세부 집계 미제공'};
 return {text:'—',caption:'도움 또는 사망 등 계산에 필요한 집계가 없습니다.'};
}
function metrics(s,ranked=false){if(!s||!Number(s.roundsPlayed))return '<p class="empty-state">선택한 시즌과 모드의 기록이 없습니다.</p>';const n=Number(s.roundsPlayed),winRate=n?100*Number(s.wins||0)/n:0;const data=[['경기 수',num(n)+'<small> 경기</small>'],['승리',num(s.wins)+'<small> 승</small>'],['승률',num(winRate)+'<small> %</small>'],['총 처치',num(s.kills)+'<small> 킬</small>'],['평균 피해량',num(s.damageDealt==null?null:s.damageDealt/n)]];if(ranked){data.splice(0,0,['시즌 RP',num(s.currentRankPoint??s.rankPoints)]);data.push(['평균 순위',s.avgRank==null?'—':'#'+num(s.avgRank)],['KDA',kdaMetric(s).text,kdaMetric(s).caption]);}else{data.push(['TOP 10',num(s.top10s)+'<small> 회</small>'],['최장 처치',s.longestKill==null?'—':num(s.longestKill)+'<small> m</small>'],['평균 생존',seconds(s.timeSurvived==null?null:s.timeSurvived/n)]);}return `<div class="metric-grid">${data.map(([k,v,caption])=>metricCard(k,v,caption)).join('')}</div>${ranked?'<p class="metric-note">TOP 10 횟수 · 최장 처치 · 평균 생존은 아래 최근 경기 요약에서 확인하세요. 시즌 경쟁전 집계와 최근 경기 집계는 범위가 다릅니다.</p>':''}`;}
let overviewPerspective='tpp',overviewSeason='',overviewData=null,overviewLoading=false,overviewError='',overviewRequest=0;
const overviewCache=new Map();
const statNumber=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;
function statRatio(numerator,denominator,digits=1,suffix=''){const a=statNumber(numerator),b=statNumber(denominator);return a===null||b===null||b===0?'—':(a/b).toFixed(digits)+suffix;}
function modeStat(label,value,hint=''){return `<div class="mode-stat"${hint?` title="${esc(hint)}"`:''}><span>${esc(label)}</span><strong>${value}</strong></div>`;}
function modeOverviewCard(base,section,ranked){
 const key=base+(overviewPerspective==='fpp'?'-fpp':''),label={solo:'솔로',duo:'듀오',squad:'스쿼드'}[base],s=section?.data?.[key],n=statNumber(s?.roundsPlayed),unavailable=section?.available===false;
 const header=`<div class="mode-card-heading"><h4>${label}</h4><span>${perspectiveLabel(overviewPerspective)}</span></div>`;
 if(overviewLoading)return `<article class="mode-card mode-${base}" data-mode="${key}">${header}<div class="mode-empty" role="status">시즌 전적을 불러오는 중입니다…</div></article>`;
 if(overviewError||unavailable)return `<article class="mode-card mode-${base}" data-mode="${key}">${header}<div class="mode-empty"><strong>조회할 수 없습니다</strong><small>${esc(overviewError||section.reason||'잠시 후 다시 시도해 주세요.')}</small></div></article>`;
 if(!s||n===null||n===0)return `<article class="mode-card mode-${base}" data-mode="${key}">${header}<div class="mode-empty"><span class="empty-helmet" aria-hidden="true">◌</span><strong>기록 없음</strong><small>이 시즌의 ${label} ${perspectiveLabel(overviewPerspective)} ${ranked?'경쟁전':'일반전'} 기록이 없습니다.</small></div></article>`;
 const kills=statNumber(s.kills),wins=statNumber(s.wins),losses=statNumber(s.losses),deaths=statNumber(s.deaths),assists=statNumber(s.assists),damage=statNumber(s.damageDealt),headshots=statNumber(s.headshotKills),top10=statNumber(s.top10s);
 const winRate=wins===null||wins>n?'—':(wins/n*100).toFixed(1)+'%',averageDamage=damage===null?'—':num(damage/n);
 let lead,items;
 if(ranked){
  const kd=statRatio(kills,deaths,2),kda=kdaMetric(s),ratio=statNumber(s.top10Ratio);
  lead=`<div class="mode-card-profile">${badge(s.currentTier)}<div class="mode-rp"><strong>${num(s.currentRankPoint??s.rankPoints)}</strong><small>RP</small></div></div><div class="mode-card-grade">${customBadge(s.currentRankPoint??s.rankPoints)}</div>`;
  items=[['K/D',kd,'처치 수 ÷ 실제 사망 수. 사망 집계가 없거나 0이면 비율을 표시하지 않습니다.'],['KDA',kda.text,kda.caption],['승률',winRate],['TOP 10 비율',ratio===null?'—':ratio.toFixed(3),'공식 시즌 집계의 비율 원값입니다. 일반전 TOP 10 진입률(%)과 구분합니다.'],['평균 피해량',averageDamage],['경기 수',num(n)],['평균 순위',s.avgRank==null?'—':'#'+num(s.avgRank)],['총 처치',num(kills)],['도움',num(assists)]];
 }else{
  const top10Rate=top10===null||top10>n?'—':(top10/n*100).toFixed(1)+'%',hs=kills===null||headshots===null||kills===0?'—':(headshots/kills*100).toFixed(1)+'%';
  lead=`<div class="mode-normal-lead"><strong>${wins===null?'—':num(wins)}<small>승</small></strong><span>${num(n)}경기${losses===null?'':' · '+num(losses)+'패'}</span></div>`;
  const kdLabel=deaths!==null?'K/D':'킬 / 패배',kd=statRatio(kills,deaths!==null?deaths:losses,2);
  items=[[kdLabel,kd,deaths!==null?'처치 수 ÷ 실제 사망 수':'일반전 시즌의 처치 수 ÷ 패배 경기 수입니다. 실제 사망 수 기반 K/D와 구분합니다.'],['평균 킬',statRatio(kills,n,2)],['승률',winRate],['TOP 10 진입률',top10Rate],['평균 피해량',averageDamage],['경기 수',num(n)],['헤드샷 비율',hs],['최장 처치',s.longestKill==null?'—':num(s.longestKill)+'m'],['평균 생존',seconds(s.timeSurvived==null?null:Number(s.timeSurvived)/n)],['최다 처치',num(s.roundMostKills)],['TOP 10 횟수',num(top10)],['총 처치',num(kills)]];
 }
 return `<article class="mode-card mode-${base}" data-mode="${key}">${header}${lead}<div class="mode-stats-grid">${items.map(([k,v,h])=>modeStat(k,v,h)).join('')}</div></article>`;
}
function renderModeOverview(){
 const seasons=uniqueSeasonOptions(profile?.seasons?.length?profile.seasons:profile?.current_season?[profile.current_season]:[],profile?.current_season?.id);
 const activeSeason=seasons.find(s=>s.id===overviewSeason);
 $('modeOverview').innerHTML=`<div class="trend-heading"><div><span class="eyebrow">SEASON MODE STATS</span><h3>솔로 · 듀오 · 스쿼드</h3><p class="graph-note">시즌 ${esc(activeSeason?.number||'—')} · ${perspectiveLabel(overviewPerspective)} 전적</p></div><div class="mode-overview-controls"><label>시즌 <select id="modeSeason" aria-label="모드별 전적 시즌">${seasons.map(s=>`<option value="${esc(s.id)}"${s.id===overviewSeason?' selected':''}>시즌 ${esc(s.number)}${s.current?' · 현재':''}</option>`).join('')}</select></label><div class="perspective-tabs" role="group" aria-label="시점 선택"><button type="button" data-perspective="tpp" aria-pressed="${overviewPerspective==='tpp'}">3인칭</button><button type="button" data-perspective="fpp" aria-pressed="${overviewPerspective==='fpp'}">1인칭</button></div></div></div><div class="mode-section-title"><h4>경쟁전 전적</h4><span>공식 티어 · RP · 시즌 전투 통계</span></div><div id="rankedModeCards" class="mode-cards-grid">${['solo','duo','squad'].map(m=>modeOverviewCard(m,overviewData?.ranked,true)).join('')}</div><p class="mode-scope-note">시즌 36부터 경쟁전 티어와 RP는 통합되었습니다. 모드별 경기 통계는 각각 조회된 값을 표시합니다. TOP 10 비율은 시즌 집계 원값이며 최근 20경기 진입률과 구분합니다.</p><div class="mode-section-title"><h4>일반전 전적</h4><span>시즌 전체 · 일반 매치 통계</span></div><div id="normalModeCards" class="mode-cards-grid">${['solo','duo','squad'].map(m=>modeOverviewCard(m,overviewData?.normal,false)).join('')}</div>${overviewError?'<button id="retryModeOverview" class="ghost">이 시즌 다시 조회</button>':''}`;
 $('modeSeason').onchange=e=>loadModeOverview(e.target.value);
 $('modeOverview').querySelectorAll('[data-perspective]').forEach(b=>b.onclick=()=>{overviewPerspective=b.dataset.perspective;const base=mode().replace('-fpp','');$('rankMode').value=base+(overviewPerspective==='fpp'?'-fpp':'');renderModeOverview();seasons()});
 if($('retryModeOverview'))$('retryModeOverview').onclick=()=>loadModeOverview(overviewSeason);
 renderSelectedSeasonProfile();
}
function initModeOverview(){
 overviewRequest++;overviewCache.clear();overviewPerspective=mode().endsWith('-fpp')?'fpp':'tpp';overviewLoading=false;overviewError='';overviewSeason=profile?.current_season?.id||'';
 overviewData={ranked:profile.ranked,normal:profile.normal};
 if(overviewSeason)overviewCache.set(overviewSeason,overviewData);
 renderModeOverview();
}
async function loadModeOverview(season){
 if(!active||!season)return;
 const seq=generation,requestId=++overviewRequest,q={...active};overviewSeason=season;overviewError='';seasonRequest++;seasonState=null;for(const id of ['rpGraph','roundGraph','seasons'])$(id).textContent='선택한 시즌을 불러오는 중입니다…';chartHighlights([]);
 if(overviewCache.has(season)){overviewData=overviewCache.get(season);overviewLoading=false;renderModeOverview();seasons();return;}
 overviewLoading=true;overviewData=null;renderModeOverview();
 try{const d=await get('/api/season',{...q,season});if(seq!==generation||requestId!==overviewRequest)return;overviewData={ranked:d.ranked,normal:d.normal};overviewCache.set(season,overviewData);}
 catch(e){if(seq!==generation||requestId!==overviewRequest)return;overviewData=null;overviewError=e.message;}
 finally{if(seq===generation&&requestId===overviewRequest){overviewLoading=false;renderModeOverview();if(!overviewError)seasons();}}
}

let recentMode='all',chartPoints=[];
function summary(){const rows=history.filter(m=>recentMode==='all'||m.mode===recentMode),n=rows.length;const total=k=>rows.reduce((a,m)=>a+Number(m[k]||0),0),validSurvival=rows.filter(m=>m.survival!=null),longKills=rows.map(m=>m.stats?.longestKill).filter(v=>v!=null&&Number.isFinite(Number(v))).map(Number);const modes=[...new Set(history.map(m=>m.mode))];$('recentSummary').innerHTML=`<div class="trend-heading"><div><span class="eyebrow">RECENT MATCHES</span><h3>최근 경기 요약 <span class="scope-chip">${n}경기</span></h3></div><label class="filter-label">경기 모드 <select id="recentMode"><option value="all">전체 모드 (${history.length})</option>${modes.map(m=>`<option value="${esc(m)}" ${recentMode===m?'selected':''}>${esc(modeLabel(m))} (${history.filter(x=>x.mode===m).length})</option>`).join('')}</select></label></div>${n?`<div class="metric-grid recent-metrics">${metricCard('TOP 10 진입',rows.filter(m=>m.rank>0&&m.rank<=10).length+'<small> 회</small>',num(100*rows.filter(m=>m.rank>0&&m.rank<=10).length/n)+'%')}${metricCard('최장 거리 처치',longKills.length?num(Math.max(...longKills))+'<small> m</small>':'—','경기 상세 통계 기준')}${metricCard('평균 생존',seconds(validSurvival.length?validSurvival.reduce((a,m)=>a+Number(m.survival),0)/validSurvival.length:null),validSurvival.length+'경기 기준')}${metricCard('총 처치',num(total('kills'))+'<small> 킬</small>',num(total('kills')/n)+' 킬 / 경기')}</div>`:'<p class="empty-state">이 범위에 조회된 경기가 없습니다.</p>'}<p class="metric-note">최근 조회한 ${history.length}경기 중 ${esc(modeLabel(recentMode))} 기준입니다. 시즌 경쟁전 모드 선택과 별도로 필터링합니다.</p>`;$('recentMode').value=recentMode;$('recentMode').onchange=e=>{recentMode=e.target.value;summary()};}
function graph(points,key){const vals=points.filter(p=>p[key]!=null&&Number.isFinite(Number(p[key])));if(!vals.length){const pending=points.some(p=>(p.status||p.code)==='PENDING'),failed=points.some(p=>!p.available&&!['NO_RECORD','UNSUPPORTED','PENDING'].includes(p.status||p.code));return '<div class="empty-state">'+(pending?'시즌 기록을 불러오는 중입니다…':failed?'시즌 조회가 완료되지 않았습니다. 아래 상태와 재시도 버튼을 확인해 주세요.':'선택 모드의 시즌 기록이 없습니다.')+'</div>'}const w=Math.max(680,points.length*84),h=270,l=80,r=40,top=35,bottom=52,max=Math.max(1,...vals.map(p=>Number(p[key])))*1.16,pw=w-l-r,ph=h-top-bottom,xx=i=>l+24+(points.length===1?(pw-48)/2:i*(pw-48)/(points.length-1)),yy=v=>top+ph-(Number(v)/max*ph),unit=key==='rp'?'RP':'경기';let segments=[],segment=[];points.forEach((p,i)=>{if(p[key]==null){if(segment.length)segments.push(segment);segment=[]}else segment.push([xx(i),yy(p[key])])});if(segment.length)segments.push(segment);const line=segments.map(seg=>seg.map(([x,y],i)=>(i?'L':'M')+x+','+y).join(' ')).join(' ');const area=segments.map(seg=>'M'+seg[0][0]+','+(top+ph)+' '+seg.map(([x,y])=>'L'+x+','+y).join(' ')+' L'+seg.at(-1)[0]+','+(top+ph)+' Z').join(' ');return `<div class="trend-chart-scroll"><svg class="trend-chart" viewBox="0 0 ${w} ${h}" style="min-width:${w}px" role="img" aria-label="시즌별 ${unit} 추이"><defs><linearGradient id="fill-${key}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${key==='rp'?'#9a89ff':'#4ed9c4'}" stop-opacity=".35"/><stop offset="100%" stop-color="#263c56" stop-opacity="0"/></linearGradient></defs>${[0,.25,.5,.75,1].map(f=>`<line x1="${l}" x2="${w-r}" y1="${top+ph-ph*f}" y2="${top+ph-ph*f}" class="chart-grid"/><text x="${l-12}" y="${top+ph-ph*f+4}" text-anchor="end" class="chart-axis">${num(Math.round(max*f))}</text>`).join('')}<path d="${area}" fill="url(#fill-${key})"/><path d="${line}" class="chart-line ${key==='rounds'?'mint':''}"/>${points.map((p,i)=>`<text x="${xx(i)}" y="${h-20}" text-anchor="middle" class="chart-axis">S${esc(p.season.number)}</text>${p[key]==null?`<text x="${xx(i)}" y="${top+ph-10}" text-anchor="middle" class="chart-axis">${seasonPointLabel(p)}</text>`:`<circle cx="${xx(i)}" cy="${yy(p[key])}" r="5" class="chart-point ${key==='rounds'?'mint':''}"><title>시즌 ${esc(p.season.number)} · ${num(p[key])} ${unit}</title></circle><text x="${xx(i)}" y="${yy(p[key])-15}" text-anchor="middle" class="chart-value">${num(p[key])}</text>`}`).join('')}</svg></div>`}
function chartHighlights(points){const available=points.filter(p=>p.rp!=null),latest=available.at(-1),previous=available.at(-2),diff=latest&&previous?latest.rp-previous.rp:null;$('trendHighlights').innerHTML=`<div><small>최근 기록 RP</small><strong>${num(latest?.rp)} <span>RP</span></strong></div><div><small>이전 기록 대비</small><strong class="${diff>=0?'positive':''}">${diff==null?'—':(diff>0?'+':'')+num(diff)} <span>RP</span></strong></div><div><small>최고 시즌 기록</small><strong>${num(available.length?Math.max(...available.map(p=>p.rp)):null)} <span>RP</span></strong></div>`;}
function renderIdentity(stats){const t=stats?.currentTier,rp=stats?.currentRankPoint??stats?.rankPoints;const holder=$('officialRank');if(holder)holder.innerHTML=badge(t);$('profileRp').innerHTML=`<strong>${num(rp)} RP</strong>${customBadge(rp)}`;renderTierGuide(rp);}
function selectedSeasonInfo(){return (profile?.seasons||[]).find(s=>s.id===overviewSeason)||((profile?.current_season?.id===overviewSeason)?profile.current_season:null);}
function viewingPastSeason(){return !!(overviewSeason&&profile?.current_season&&overviewSeason!==profile.current_season.id);}
function renderSelectedSeasonProfile(){
 if(!profile||!$('profileRp'))return;
 const season=selectedSeasonInfo(),m=mode(),historical=viewingPastSeason(),s=!overviewLoading&&!overviewError?overviewData?.ranked?.data?.[m]:null;
 renderIdentity(s);
 const label=$('profileSeasonLabel');if(label)label.textContent=(platformLabels[active?.platform]||active?.platform||'')+' · 시즌 '+(season?.number||'—')+' · '+modeLabel(m);
 const note=$('profileScopeNote');if(note){note.hidden=!historical;note.textContent='선택한 과거 시즌의 전적입니다. 최근 경기와 전투 성향은 현재 시즌 보기에서 확인할 수 있습니다.';}
 $('currentMetrics').innerHTML=`<div class="trend-heading"><h3>시즌 ${esc(season?.number||'—')} · 경쟁전 전적</h3><span class="scope-chip">${esc(modeLabel(m))}</span></div>`+(overviewLoading?'<p class="empty-state">선택한 시즌의 전적을 불러오는 중입니다…</p>':overviewError?`<p>${esc(overviewError)}</p>`:metrics(s,true));
 for(const target of [$('recentSummary'),$('matches')?.closest('article'),$('radarGraph')?.closest('article'),$('style')?.closest('article')])if(target)target.hidden=historical;
 $('rpGraph')?.closest('.visual-grid')?.classList.toggle('historical-grid',historical);
 updateSearchStatus();
}
let seasonRequest=0,seasonState=null;
const seasonPointCache=new Map();
const platformLabels={steam:'Steam',kakao:'Kakao',psn:'PlayStation',xbox:'Xbox'};
function showSearchStatus(message,warning=false){$('status').textContent=message;$('status').className=warning?'search-warning':'loading';}
function updateSearchStatus(historyResult=null){
 if(!profile||!active)return;
 if(historyResult)profile._historyResult=historyResult;
 const h=profile._historyResult,label=platformLabels[active.platform]||active.platform;
 if(viewingPastSeason()){
  const season=selectedSeasonInfo(),m=mode(),ranked=overviewData?.ranked,normal=overviewData?.normal;
  if(overviewLoading){showSearchStatus(label+' · 시즌 '+(season?.number||'—')+' 전적 조회 중…');return;}
  const exists=[ranked?.data?.[m],normal?.data?.[m]].some(s=>Number(s?.roundsPlayed)>0);
  showSearchStatus(label+' · 시즌 '+(season?.number||'—')+' · '+modeLabel(m)+(exists?' 전적 확인':overviewError||ranked?.available===false||normal?.available===false?' 전적을 확인할 수 없습니다.':' 기록이 없습니다.'),!exists);return;
 }

 if(h?.matches?.length){showSearchStatus(`${label} · 최근 ${h.matches.length}/${h.requested}경기 조회 (실패 ${h.failed})`);return;}
 if(profile.records_available===false&&!profile._historicalRecords){showSearchStatus(profile.platform_message||`${label}에서 이 닉네임의 전적을 확인할 수 없습니다. 플랫폼과 시즌을 확인해 주세요.`,true);return;}
 if(h&&h.failed>0){showSearchStatus(`${label}에서 최근 경기 정보를 조회하지 못했습니다 (${h.failed}건 실패). 플랫폼 및 API 응답 상태를 확인해 주세요.`,true);return;}
 if(profile._historicalRecords&&profile.records_available===false){showSearchStatus(`${label} 과거 시즌 전적을 확인했습니다. 현재 시즌 기록과 최근 경기 목록은 없습니다.`);return;}
 showSearchStatus(h?`${label} 시즌 전적 확인 · 최근 경기 목록이 없습니다.`:`${label} 시즌 전적 확인 · 최근 경기 조회 중…`);
}
function seasonPointLabel(p){const code=p.status||p.code;return code==='PENDING'?'조회 대기':code==='NO_RECORD'?'기록 없음':code==='UNSUPPORTED'?'경쟁전 미지원':code==='RATE_LIMIT'?'요청 제한':p.available?'기록 확인':'조회 실패';}
function seasonTargetList(limit,anchor=overviewSeason){
 const unique=new Map();
 for(const s of profile?.seasons||[profile?.current_season].filter(Boolean))if(!unique.has(s.number)||s.current)unique.set(s.number,s);
 const ordered=[...unique.values()].sort((a,b)=>Number(b.number)-Number(a.number)),index=ordered.findIndex(s=>s.id===anchor);return ordered.slice(index>=0?index:0).slice(0,limit);
}
function selectedSeasonSeed(m){
 const season=selectedSeasonInfo(),s=!overviewLoading&&!overviewError?overviewData?.ranked?.data?.[m]:null;
 if(!season||!s||!(Number(s.roundsPlayed)>0))return;
 seasonPointCache.set(m+':'+season.id,{season,available:true,status:'AVAILABLE',rp:s.currentRankPoint??s.rankPoints,rounds:s.roundsPlayed,wins:s.wins,official_tier:s.currentTier,stats:s});
}
function drawSeasonState(state){
 if(seasonState!==state)return;
 const points=state.list.map(season=>seasonPointCache.get(state.mode+':'+season.id)||{season,available:false,status:'PENDING',code:'PENDING'}).sort((a,b)=>Number(a.season.number)-Number(b.season.number));
 chartPoints=points;$('rpGraph').innerHTML=graph(points,'rp');$('roundGraph').innerHTML=graph(points,'rounds');chartHighlights(points);
 // All-seasons charts open at the latest seasons rather than an empty oldest range.
 for(const id of ['rpGraph','roundGraph']){const scroll=$(id).querySelector('.trend-chart-scroll');if(scroll)scroll.scrollLeft=scroll.scrollWidth;}
 const completed=points.filter(p=>(p.status||p.code)!=='PENDING').length,valid=points.filter(p=>p.available).length;
 $('seasonLoadStatus').innerHTML=`<span>${state.loading?'시즌 조회 중':state.message||'시즌 조회 완료'} · ${completed}/${state.list.length}시즌 확인 · 기록 ${valid}개</span>${state.retry?'<button id="retrySeasons" class="ghost" type="button">남은 시즌 다시 조회</button>':''}`;
 if($('retrySeasons'))$('retrySeasons').onclick=()=>seasons();
 $('seasons').innerHTML=points.slice().reverse().map(p=>`<details class="season-card"><summary><span class="season-label"><small>${p.season.current?'CURRENT SEASON':'SEASON RECORD'}</small><strong>시즌 ${esc(p.season.number)}</strong></span><span class="season-rank">${p.available?badge(p.official_tier):`<span class="scope-chip">${seasonPointLabel(p)}</span>`}</span><span class="season-number"><strong>${num(p.rp)}</strong><small>RP</small></span><span class="season-number"><strong>${num(p.wins)}</strong><small>승리</small></span><span class="season-number"><strong>${num(p.rounds)}</strong><small>경기</small></span><span class="season-chevron" aria-hidden="true">⌄</span></summary><div class="season-content">${p.available?metrics(p.stats,true):`<p class="empty-state">${esc(p.error||seasonPointLabel(p))}</p>`}<button class="ghost season-load" data-season="${esc(p.season.id)}">같은 시즌 일반전 통계 보기</button><div class="normal-stats"></div></div></details>`).join('');
 const q={...active};$('seasons').querySelectorAll('.season-load').forEach(b=>b.onclick=async()=>{b.disabled=true;const target=b.nextElementSibling;try{const d=await get('/api/season',{...q,season:b.dataset.season});target.innerHTML=d.normal?.available===false?`<p>${esc(d.normal.reason||'일반전 조회 실패')}</p>`:'<h4>일반전 · '+esc(modeLabel(state.mode))+'</h4>'+metrics(d.normal?.data?.[state.mode]);}catch(e){target.textContent=e.message}finally{b.disabled=false}});
 const current=points.find(p=>p.season.current);renderSelectedSeasonProfile();
 if(valid&&profile?.records_available===false){if(current?.available)profile.records_available=true;else profile._historicalRecords=true;updateSearchStatus();}
}
async function seasons(){
 if(!active||!profile)return;
 const q={...active},seq=generation,requestId=++seasonRequest,m=mode(),limit=Number($('seasonLimit').value),anchor=overviewSeason;
 const state={mode:m,anchor,list:seasonTargetList(limit,anchor),loading:true,message:'',retry:false};seasonState=state;selectedSeasonSeed(m);
 renderSelectedSeasonProfile();drawSeasonState(state);
 let offset=0;
 try{
  while(seq===generation&&requestId===seasonRequest&&mode()===m&&overviewSeason===anchor&&Number($('seasonLimit').value)===limit){
   const d=await get('/api/season-chart',{...q,mode:m,limit,offset,batch_size:6,end_season:anchor});
   if(seq!==generation||requestId!==seasonRequest||mode()!==m||overviewSeason!==anchor||Number($('seasonLimit').value)!==limit)return;
   if(d.season_list)state.list=d.season_list;
   else{const known=new Map(state.list.map(x=>[x.id,x]));for(const p of d.points||[])known.set(p.season.id,p.season);state.list=[...known.values()];}
   for(const p of d.points||[]){const key=m+':'+p.season.id,old=seasonPointCache.get(key);if(p.available||!old?.available)seasonPointCache.set(key,p);}
   if(d.rate_limited||d.paused){state.loading=false;state.retry=true;state.message=d.rate_limited?'API 요청 제한으로 일부 시즌 조회 대기':'추가 시즌 조회 일시 중단: '+(d.pause_reason||'연결/인증 오류');drawSeasonState(state);return;}
   drawSeasonState(state);
   if(!d.has_more)break;
   const next=Number(d.next_offset);if(!Number.isFinite(next)||next<=offset)throw Error('시즌 조회 위치를 진행하지 못했습니다.');offset=next;
  }
  if(seq===generation&&requestId===seasonRequest){state.loading=false;const failed=state.list.some(s=>{const p=seasonPointCache.get(m+':'+s.id);return p&&!p.available&&!['NO_RECORD','UNSUPPORTED'].includes(p.status||p.code)});state.message=failed?'일부 시즌 조회 실패 · 확인된 기록은 유지합니다.':'시즌 조회 완료';state.retry=failed;drawSeasonState(state);}
 }catch(e){if(seq===generation&&requestId===seasonRequest){state.loading=false;state.retry=true;state.message='추가 시즌 조회 실패: '+e.message;drawSeasonState(state);}}
}

function feed(rows){return rows.length?table(['경과','처치한 사람','무기','헤드샷','처치된 사람','거리'],rows.map(x=>[seconds(x.elapsed_seconds),esc(x.killer),`<img class="weapon" loading="lazy" src="/api/weapon-icon/${encodeURIComponent(x.weapon_code||'unknown')}" alt="" onerror="this.hidden=true"> ${esc(x.weapon)}`,x.headshot?'<img class="headshot" src="/static/headshot.svg" alt="헤드샷">':'',esc(x.victim),num(x.distance)+'m'])):'기록이 없습니다.'}
let matchViewSequence=0;
function matchParty(mode){return String(mode||'').match(/(?:^|-)(solo|duo|squad)(?:-|$)/)?.[1]||'team';}
function rankText(rank){return rank!=null&&Number(rank)>0?'#'+num(rank):'순위 미제공';}
function teamTotal(team,key){return (team.members||[]).reduce((sum,p)=>sum+Number(p[key]||0),0);}
function memberTable(members,player,rank,solo=false){
 return table([solo?'개인 순위':'팀 순위','닉네임','킬','도움','피해량','기절','헤드샷','생존','최장 처치','이동 거리'],members.map(p=>[esc(rankText(p.rank??rank)),esc(p.nickname)+(String(p.nickname).toLowerCase()===String(player).toLowerCase()?' ★':''),num(p.kills),num(p.assists),num(p.damage),num(p.dbnos),num(p.headshots),seconds(p.survival),p.longest_kill==null?'—':num(p.longest_kill)+'m',p.distance==null?'—':num(p.distance)+'km']));
}
function groupedTeamResults(v,party){
 const label=party==='duo'?'듀오':party==='squad'?'스쿼드':'팀';
 return `<div class="team-results-head"><h4>${label} 팀 순위 · ${num(v.team_count)}팀</h4><p>같은 팀의 플레이어를 묶어서 표시합니다. 팀 순위는 공식 경기 결과 기준입니다.</p><div class="team-bulk-controls"><button type="button" class="ghost" data-team-expand="true">모두 펼치기</button><button type="button" class="ghost" data-team-expand="false">모두 접기</button></div></div>`+(v.teams||[]).map(team=>`<details class="team-result ${team.is_my_team?'my-team':''}" open><summary><strong class="team-place">${esc(rankText(team.rank))}${team.is_my_team?'<small>내 팀</small>':''}</strong><span class="team-player-names">${(team.members||[]).map(p=>esc(p.nickname)).join('<span class="team-name-separator"> · </span>')}</span><span class="team-total"><small>팀 처치</small><strong>${num(team.kills??teamTotal(team,'kills'))}</strong></span><span class="team-total"><small>팀 피해량</small><strong>${num(team.damage??teamTotal(team,'damage'))}</strong></span><span class="team-expand" aria-hidden="true">⌄</span></summary><div class="team-members"><div class="team-aggregate"><span>${num(team.members?.length)}명</span><span>도움 ${num(teamTotal(team,'assists'))}</span><span>기절 ${num(teamTotal(team,'dbnos'))}</span><span>헤드샷 ${num(teamTotal(team,'headshots'))}</span></div>${memberTable(team.members||[],v.player,team.rank)}</div></details>`).join('');
}
function matchStandingViews(v,queryNickname){
 const party=matchParty(v.mode),player=v.player||queryNickname,teams=v.teams||[];
 const myTeam=teams.find(t=>t.is_my_team)||teams.find(t=>(t.members||[]).some(p=>String(p.nickname).toLowerCase()===String(player).toLowerCase()));
 const me=myTeam?.members?.find(p=>String(p.nickname).toLowerCase()===String(player).toLowerCase());
 const myPlace=myTeam?.rank??me?.win_place,solo=party==='solo',id='gg-match-view-'+(++matchViewSequence),defaultView=solo?'all':'teams';
 let mine=me?`<div class="my-match-title"><div><span class="eyebrow">MY MATCH RESULT</span><h4>${esc(player)} · ${solo?'개인 순위':'팀 순위'} ${esc(rankText(myPlace))}</h4></div><span class="scope-chip">${esc(modeLabel(v.mode))}</span></div><div class="metric-grid my-match-metrics">${metricCard('처치',num(me.kills))}${metricCard('도움',num(me.assists))}${metricCard('피해량',num(me.damage))}${metricCard('기절',num(me.dbnos))}${metricCard('헤드샷',num(me.headshots))}${metricCard('생존 시간',seconds(me.survival))}${metricCard('최장 처치',me.longest_kill==null?'—':num(me.longest_kill)+'m')}${metricCard('이동 거리',me.distance==null?'—':num(me.distance)+'km')}</div>`:'<p>검색한 플레이어의 개인 전적을 이 경기에서 찾지 못했습니다.</p>';
 if(myTeam&&!solo)mine+=`<div class="my-team-highlight"><h4>내 ${party==='duo'?'듀오':party==='squad'?'스쿼드':'팀'} · ${esc(rankText(myPlace))} / ${num(v.team_count)}팀</h4><p>팀 ${num(myTeam.kills??teamTotal(myTeam,'kills'))}킬 · 피해량 ${num(myTeam.damage??teamTotal(myTeam,'damage'))} · 도움 ${num(teamTotal(myTeam,'assists'))}</p>${memberTable(myTeam.members||[],player,myPlace)}</div>`;
 const choices=solo?[['all','솔로 개인 순위'],['mine','내 개인 전적']]:[['teams',party==='duo'?'듀오 팀 순위':party==='squad'?'스쿼드 팀 순위':'팀 순위'],['mine','내 개인 / 팀 전적'],['all','전체 참가자']];
 const allRows=teams.flatMap(team=>(team.members||[]).map(p=>[''+esc(rankText(team.rank)),esc(p.nickname)+(String(p.nickname).toLowerCase()===String(player).toLowerCase()?' ★':''),num(p.kills),num(p.damage),num(p.headshots),seconds(p.survival),num(p.longest_kill)+'m']));
 return `<section class="match-standings"><div class="match-result-summary"><strong>${solo?'솔로 개인 결과':party==='duo'?'듀오 팀 결과':party==='squad'?'스쿼드 팀 결과':'경기 결과'} · ${esc(rankText(myPlace))}</strong><span>${num(v.participants)}명 / ${num(v.team_count)}팀</span></div><div class="match-view-tabs" role="tablist" aria-label="경기 전적 보기">${choices.map(([key,label])=>`<button id="${id}-tab-${key}" type="button" role="tab" data-match-view="${key}" aria-controls="${id}-panel-${key}" aria-selected="${key===defaultView}" tabindex="${key===defaultView?0:-1}">${label}</button>`).join('')}</div>${!solo?`<div id="${id}-panel-teams" class="match-view-panel" data-match-panel="teams" role="tabpanel" aria-labelledby="${id}-tab-teams">${groupedTeamResults(v,party)}</div>`:''}<div id="${id}-panel-mine" class="match-view-panel" data-match-panel="mine" role="tabpanel" aria-labelledby="${id}-tab-mine" hidden>${mine}</div><div id="${id}-panel-all" class="match-view-panel" data-match-panel="all" role="tabpanel" aria-labelledby="${id}-tab-all" ${solo?'':'hidden'}><h4>${solo?'솔로 개인 순위':'전체 참가자'} · ${num(v.participants)}명</h4>${table([solo?'개인 순위':'팀 순위','닉네임','킬','피해량','헤드샷 수','생존','최장 처치'],allRows)}</div></section>`;
}
function bindMatchViews(box){
 box.querySelectorAll('[data-team-expand]').forEach(b=>b.onclick=()=>box.querySelectorAll('.team-result').forEach(team=>team.open=b.dataset.teamExpand==='true'));
 const tabs=[...box.querySelectorAll('[data-match-view]')],panels=box.querySelectorAll('[data-match-panel]');
 const select=button=>{tabs.forEach(b=>{const active=b===button;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1});panels.forEach(p=>p.hidden=p.dataset.matchPanel!==button.dataset.matchView)};
 tabs.forEach((b,i)=>{b.onclick=()=>select(b);b.onkeydown=e=>{let target;if(e.key==='ArrowRight')target=tabs[(i+1)%tabs.length];else if(e.key==='ArrowLeft')target=tabs[(i+tabs.length-1)%tabs.length];else if(e.key==='Home')target=tabs[0];else if(e.key==='End')target=tabs.at(-1);if(target){e.preventDefault();select(target);target.focus()}}});
}
async function detail(card,q){
 if(card.dataset.loaded==='1')return;card.dataset.loaded='1';const box=card.querySelector('.detail-body');box.textContent='상세 정보 조회 중…';const params={...q,match_id:card.dataset.mid};
 const [d,t]=await Promise.allSettled([get('/api/match-detail',params),get('/api/match-telemetry',params)]);let html='';
 if(d.status==='fulfilled')html+=matchStandingViews(d.value,q.nickname);else html+=`<p>${esc(d.reason.message)}</p>`;
 if(t.status==='fulfilled'){const f=t.value.match_killfeed||[];html+=`<h4>내 처치 / 사망 로그</h4>${feed(f.filter(x=>x.my_kill||x.my_death))}<details><summary>전체 경기 킬로그</summary>${feed(f)}</details>`;}else html+=`<p>킬로그: ${esc(t.reason.message)}</p>`;
 box.innerHTML=html;bindMatchViews(box);const retry=document.createElement('button');retry.className='ghost';retry.textContent='상세 정보 다시 조회';retry.onclick=()=>{card.dataset.loaded='';detail(card,q)};box.append(retry);
}

function renderMatches(q){$('matches').innerHTML=`<p>${history.length}경기 표시 · 솔로는 개인 순위, 듀오·스쿼드는 팀 순위입니다. 실제 참가자 수에 따라 100명 미만일 수 있습니다.</p>`+history.map(m=>`<details class="match-card" data-mid="${esc(m.id)}"><summary>${esc(maps[m.map]||m.map)} · ${esc(modeLabel(m.mode))} · #${esc(m.rank)} · ${num(m.kills)}킬 · ${esc(m.createdAt?.replace('T',' ').slice(0,16))} <b>상세보기</b></summary><div class="detail-body"></div></details>`).join('');$('matches').querySelectorAll('details.match-card').forEach(c=>c.addEventListener('toggle',()=>{if(c.open)detail(c,q)}));summary()}
function radar(d,compare=null){const keys=['yeopo','jonbeo','balance'],vertices=[[180,35],[35,280],[325,280]],poly=s=>vertices.map(([x,y],i)=>`${180+(x-180)*(s[keys[i]]||0)/100},${190+(y-190)*(s[keys[i]]||0)/100}`).join(' ');$('radarGraph').innerHTML=`<svg viewBox="0 0 360 320" role="img" aria-label="전투 성향 비교"><polygon points="180,35 35,280 325,280" fill="none" stroke="#8ba3bf"/>${[.25,.5,.75].map(v=>`<polygon points="${poly({yeopo:v*100,jonbeo:v*100,balance:v*100})}" fill="none" stroke="#526984"/>`).join('')}${d.peer_average?`<polygon points="${poly(d.peer_average)}" fill="#ddd5" stroke="#ddd"/>`:''}<polygon points="${poly(d.scores)}" fill="#38bdf855" stroke="#38bdf8" stroke-width="3"/>${compare?`<polygon points="${poly(compare.scores)}" fill="#fbbf2433" stroke="#fbbf24" stroke-width="3"/>`:''}<g fill="currentColor" font-size="14"><text x="160" y="20">여포</text><text x="10" y="310">존버</text><text x="300" y="310">밸런스</text></g></svg>`;$('style').innerHTML=`<p>분석 ${d.matches_analyzed}/${d.matches_requested}경기 · 실패 ${d.matches_failed}</p><p>여포 ${d.scores.yeopo} · 존버 ${d.scores.jonbeo} · 밸런스 ${d.scores.balance}</p><p>기본점수 15점 · 5분 내 5킬 이상 / 7분 이상 생존하며 7분 내 0킬</p><p>하늘색: 검색 유저 / 회색: 같은 RP ±500 실제 표본 평균 (${d.peer_count}명, 2명 이상일 때 표시)${compare?' / 노란색: '+esc(compare.nickname):''}</p>`;}
async function search(e){e?.preventDefault();const nickname=$('nickname').value.trim();if(!nickname)return;const seq=++generation,q={nickname,platform:$('platform').value};active=q;profile=null;history=[];styleData=null;recentMode='all';overviewRequest++;seasonRequest++;seasonPointCache.clear();seasonState=null;$('search').classList.remove('hidden');$('search').scrollIntoView({behavior:'smooth'});for(const id of ['profile','matches','seasons','style','rpGraph','roundGraph','radarGraph','currentMetrics','recentSummary','modeOverview'])$(id).textContent='조회 중…';$('status').textContent='플레이어를 조회합니다.';try{const d=await get('/api/profile',q);if(seq!==generation)return;profile=d;profile.seasons=uniqueSeasonOptions(profile.seasons||[],profile.current_season?.id);$('profile').innerHTML=`<div class="player-heading"><h2>${esc(d.player.nickname)}</h2><span id="officialRank"></span></div><div class="player-meta"><span id="profileSeasonLabel">${esc(q.platform.toUpperCase())} · 시즌 ${esc(d.current_season?.number)}</span><div id="profileRp"></div></div><p id="profileScopeNote" class="profile-scope-note" hidden></p>`;initModeOverview();updateSearchStatus();await Promise.allSettled([seasons(),(async()=>{try{const h=await get('/api/history',{...q,limit:20});if(seq!==generation)return;history=h.matches;renderMatches(q);updateSearchStatus(h);}catch(e){if(seq===generation){$('matches').textContent=e.message;showSearchStatus((platformLabels[q.platform]||q.platform)+'에서 최근 경기 조회에 실패했습니다. '+e.message,true);}}})(),(async()=>{try{const s=await get('/api/playstyle',{...q,limit:20,mode:mode()});if(seq!==generation)return;styleData=s;radar(s)}catch(e){if(seq===generation){$('style').textContent=e.message;$('radarGraph').textContent='분석 데이터 없음'}}})()]);}catch(e){if(seq!==generation)return;showSearchStatus(e.message,true);for(const id of ['matches','seasons','style','rpGraph','roundGraph','radarGraph','currentMetrics','recentSummary','profile','modeOverview'])$(id).textContent='조회할 수 없습니다.';}}
async function leaders(){const p=$('leaderPlatform').value;$('leaders').textContent='실제 순위를 조회 중…';try{const d=await get('/api/leaderboard',{platform:p,mode:$('leaderMode').value,region:$('leaderRegion').value});$('leaders').innerHTML=table(['순위','닉네임','PUBG 공식 티어','RP','GAME.GG 등급'],d.leaders.map(l=>['#'+esc(l.position),`<button class="link player-link" data-name="${esc(l.nickname)}">${esc(l.nickname)}</button>`,badge(l.official_tier),`<strong>${num(l.rp)} RP</strong>`,customBadge(l.rp)]));$('leaderStatus').textContent=`${d.region} · ${d.season}`;$('leaders').querySelectorAll('.player-link').forEach(b=>b.onclick=()=>{$('platform').value=p;$('platform').dispatchEvent(new Event('change',{bubbles:true}));$('nickname').value=b.dataset.name;search()})}catch(e){$('leaders').textContent=e.message}}
function regions(){const values={steam:['pc-as','pc-krjp','pc-eu','pc-na','pc-sea','pc-jp','pc-oc','pc-ru','pc-sa'],kakao:['pc-kakao'],psn:['psn-as','psn-eu','psn-na','psn-oc'],xbox:['xbox-as','xbox-eu','xbox-na','xbox-oc','xbox-sa']};$('leaderRegion').innerHTML=values[$('leaderPlatform').value].map(v=>`<option>${v}</option>`).join('')}
const SITE_PAGE=document.body.dataset.page||'home';
let boardPosts=[],boardPage=1,boardQuery='',boardLoadRequest=0;
const boardDate=value=>new Date(Number(value)*1000).toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'});
function boardCategoryName(value){return {notice:'공지',duo:'듀오',squad:'스쿼드'}[value]||'게시글';}
function updateBoardActions(){
 const notices=SITE_PAGE==='notices';$('boardWriteButton').hidden=notices&&!admin.admin;$('adminLogout').hidden=!admin.admin;
 $('boardFormWrap').classList.toggle('hidden',notices);$('noticeFormWrap').classList.toggle('hidden',!notices||!admin.admin);
}
function previewPosts(posts,target,notice=false){
 $(target).innerHTML=posts.length?posts.slice(0,5).map(p=>`<a class="home-post-row" href="${notice?'/notices':'/teams'}?${notice?'':'category='+encodeURIComponent(p.category)+'&'}post=${encodeURIComponent(p.id)}"><span class="post-category">${boardCategoryName(p.category)}</span><strong>${esc(p.title)}</strong><time>${esc(boardDate(p.created_at))}</time></a>`).join(''):`<div class="empty">아직 등록된 ${notice?'공지사항':'모집글'}이 없습니다.</div>`;
}
async function loadHomePosts(){
 const results=await Promise.allSettled([get('/api/board',{category:'duo'}),get('/api/board',{category:'squad'}),get('/api/board',{category:'notice'})]);
 const teamPosts=results.slice(0,2).flatMap(r=>r.status==='fulfilled'?r.value.posts||[]:[]).sort((a,b)=>b.created_at-a.created_at);
 if(results[0].status==='rejected'&&results[1].status==='rejected')$('recentTeams').textContent='모집글을 불러오지 못했습니다.';else previewPosts(teamPosts,'recentTeams');
 if(results[2].status==='fulfilled')previewPosts(results[2].value.posts||[],'recentNotices',true);else $('recentNotices').textContent='공지사항을 불러오지 못했습니다.';
}
function setPostQuery(post){const url=new URL(location.href);if(post)url.searchParams.set('post',String(post));else url.searchParams.delete('post');if(SITE_PAGE==='teams')url.searchParams.set('category',category);window.history.replaceState(null,'',url.pathname+url.search);}
function showBoardList(){
 $('boardListView').hidden=false;$('boardDetail').hidden=true;$('boardCompose').hidden=true;setPostQuery(null);renderBoardList();
}
function renderBoardList(){
 const text=boardQuery.toLocaleLowerCase(),rows=boardPosts.filter(p=>!text||[p.title,p.body,p.nickname].some(v=>String(v||'').toLocaleLowerCase().includes(text))),size=10,totalPages=Math.max(1,Math.ceil(rows.length/size));boardPage=Math.min(Math.max(1,boardPage),totalPages);
 $('boardCount').textContent=`전체 ${boardPosts.length}개${boardQuery?' · 검색 결과 '+rows.length+'개':''}`;
 const subset=rows.slice((boardPage-1)*size,boardPage*size);
 $('boardRows').innerHTML=subset.length?`<div class="table-scroll community-table-scroll"><table class="community-table"><thead><tr><th>번호</th><th>제목</th><th>작성자</th><th>작성일</th></tr></thead><tbody>${subset.map((p,i)=>`<tr><td>${SITE_PAGE==='notices'?'<span class="notice-mark">공지</span>':rows.length-(boardPage-1)*size-i}</td><td><button class="board-title-link" type="button" data-open-post="${p.id}">${esc(p.title)}</button>${SITE_PAGE==='teams'?`<small class="recruit-meta">${esc(platformLabels[p.platform]||p.platform)} · ${esc(modeLabel(p.mode))} · 최소 ${num(p.min_rp)} RP</small>`:''}</td><td>${esc(p.nickname)}</td><td><time>${esc(boardDate(p.created_at))}</time></td></tr>`).join('')}</tbody></table></div>`:'<div class="board-empty"><strong>'+ (boardQuery?'검색 결과가 없습니다.':'아직 등록된 글이 없습니다.')+'</strong><p>'+(boardQuery?'다른 검색어로 다시 검색해 보세요.':SITE_PAGE==='notices'?'새로운 서비스 소식을 이곳에서 전해드립니다.':'첫 모집글을 작성하고 팀원을 찾아보세요.')+'</p></div>';
 $('boardPagination').innerHTML=rows.length?`<button type="button" data-board-page="${boardPage-1}" ${boardPage===1?'disabled':''} aria-label="이전 페이지">이전</button>${Array.from({length:totalPages},(_,i)=>`<button type="button" data-board-page="${i+1}" ${boardPage===i+1?'aria-current="page"':''}>${i+1}</button>`).join('')}<button type="button" data-board-page="${boardPage+1}" ${boardPage===totalPages?'disabled':''} aria-label="다음 페이지">다음</button>`:'';
 $('boardRows').querySelectorAll('[data-open-post]').forEach(b=>b.onclick=()=>openPost(Number(b.dataset.openPost)));
 $('boardPagination').querySelectorAll('[data-board-page]').forEach(b=>b.onclick=()=>{boardPage=Number(b.dataset.boardPage);renderBoardList();$('boardFull').scrollIntoView({behavior:'smooth',block:'start'})});
}
function openPost(id){
 const p=boardPosts.find(row=>Number(row.id)===id);if(!p){$('boardMessage').textContent='이 게시판에서 해당 글을 찾을 수 없습니다.';return;}
 $('boardListView').hidden=true;$('boardCompose').hidden=true;$('boardDetail').hidden=false;setPostQuery(id);
 const index=boardPosts.indexOf(p),previous=boardPosts[index+1],next=boardPosts[index-1];
 $('boardDetail').innerHTML=`<header class="post-detail-heading"><span class="post-category">${boardCategoryName(p.category)}</span><h2>${esc(p.title)}</h2><div class="post-detail-meta"><span>작성자 ${esc(p.nickname)}</span><time>${esc(boardDate(p.created_at))}</time>${p.category==='notice'?'':`<span>${esc(platformLabels[p.platform]||p.platform)} · ${esc(modeLabel(p.mode))} · 최소 ${num(p.min_rp)} RP</span>`}</div></header><div class="post-detail-body">${esc(p.body)}</div><div class="post-detail-actions"><button id="postBackToList" class="ghost" type="button">목록으로</button>${admin.admin?`<button class="ghost danger-button" id="deleteCurrentPost" type="button">글 삭제</button>`:''}</div><div class="post-neighbors">${previous?`<button data-neighbor="${previous.id}" type="button"><span>이전 글</span>${esc(previous.title)}</button>`:''}${next?`<button data-neighbor="${next.id}" type="button"><span>다음 글</span>${esc(next.title)}</button>`:''}</div>`;
 $('postBackToList').onclick=showBoardList;
 $('boardDetail').querySelectorAll('[data-neighbor]').forEach(b=>b.onclick=()=>openPost(Number(b.dataset.neighbor)));
 if($('deleteCurrentPost'))$('deleteCurrentPost').onclick=async()=>{try{await send('/api/admin/posts/'+id,{},'DELETE');$('boardMessage').textContent='삭제했습니다.';setPostQuery(null);refreshBoard()}catch(e){$('boardMessage').textContent=e.message}};
}
async function refreshBoard(){
 if(SITE_PAGE==='home'){loadHomePosts();return;}
 if(!['teams','notices'].includes(SITE_PAGE))return;
 const seq=++boardLoadRequest,kind=category;updateBoardActions();$('boardRows').textContent='게시글을 불러오는 중입니다.';
 try{const d=await get('/api/board',{category:kind});if(seq!==boardLoadRequest||category!==kind)return;boardPosts=d.posts||[];renderBoardList();const post=Number(new URL(location.href).searchParams.get('post'));if(post)openPost(post);else if($('boardCompose').hidden){$('boardListView').hidden=false;$('boardDetail').hidden=true;}}
 catch(e){if(seq===boardLoadRequest){$('boardRows').textContent=e.message;$('boardCount').textContent='조회 실패';}}
}
function openBoard(kind){
 if(SITE_PAGE==='home'){location.href=kind==='notice'?'/notices':'/teams?category='+encodeURIComponent(kind);return;}
 if((SITE_PAGE==='notices'&&kind!=='notice')||(SITE_PAGE==='teams'&&kind==='notice')){location.href=kind==='notice'?'/notices':'/teams?category='+encodeURIComponent(kind);return;}
 category=kind;boardPage=1;boardQuery='';$('boardQuery').value='';$('boardCompose').hidden=true;$('boardDetail').hidden=true;$('boardListView').hidden=false;$('postMode').value=kind==='squad'?'squad':'duo';if(kind!=='notice')$('postMode').querySelectorAll('option').forEach(o=>{o.hidden=!o.value.startsWith(kind);o.disabled=o.hidden;});
 $('communityTitle').textContent=kind==='notice'?'공지사항':'팀원 모집';$('boardTitle').textContent=kind==='notice'?'공지사항':'모집 게시판';$('communitySubtitle').textContent=kind==='notice'?'서비스 안내와 업데이트 소식을 확인하세요.':'함께할 듀오와 스쿼드 팀원을 찾아보세요.';
 $('boardEyebrow').textContent=kind==='notice'?'GAME.GG NEWS':'PLAY TOGETHER';$('composeTitle').textContent=kind==='notice'?'공지 작성':'모집글 작성';
 document.querySelectorAll('[data-kind]').forEach(b=>{b.hidden=SITE_PAGE==='notices'?b.dataset.kind!=='notice':b.dataset.kind==='notice';b.setAttribute('aria-pressed',String(b.dataset.kind===kind));});
 if(SITE_PAGE==='notices')$('boardTabs').hidden=true;
 refreshBoard();
}
function initPage(){
 const old={'#notices':'/notices','#teams':'/teams','#search':'/search','#boardFull':'/teams'};
 if(location.pathname==='/'&&old[location.hash]){location.replace(old[location.hash]);return;}
 if(SITE_PAGE==='search'){regions();leaders();}
 else if(SITE_PAGE==='teams'){const chosen=new URL(location.href).searchParams.get('category');openBoard(chosen==='squad'?'squad':'duo');}
 else if(SITE_PAGE==='notices')openBoard('notice');
 else if(SITE_PAGE==='home')loadHomePosts();
}

$('searchForm').onsubmit=search;$('closeResult').onclick=()=>$('search').classList.add('hidden');$('rankMode').onchange=()=>{overviewPerspective=mode().endsWith('-fpp')?'fpp':'tpp';renderModeOverview();seasons()};$('seasonLimit').onchange=seasons;$('loadLeaders').onclick=leaders;$('leaderPlatform').onchange=()=>{regions();leaders()};$('leaderMode').onchange=leaders;$('leaderRegion').onchange=leaders;
$('moreTeams').onclick=()=>location.href='/teams';$('moreNotices').onclick=()=>location.href='/notices';$('boardClose').onclick=showBoardList;document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>openBoard(b.dataset.kind));
$('boardForm').onsubmit=async e=>{e.preventDefault();try{await send('/api/board',{category,nickname:$('postNickname').value,platform:$('postPlatform').value,mode:$('postMode').value,min_rp:$('postRp').value,title:$('postTitle').value,body:$('postBody').value});$('boardMessage').textContent='등록했습니다.';$('boardCompose').hidden=true;$('boardForm').reset();setPostQuery(null);refreshBoard()}catch(e){$('boardMessage').textContent=e.message}};
$('noticeForm').onsubmit=async e=>{e.preventDefault();try{await send('/api/board',{category:'notice',title:$('noticeTitle').value,body:$('noticeBody').value});$('boardCompose').hidden=true;$('noticeForm').reset();setPostQuery(null);refreshBoard()}catch(e){$('boardMessage').textContent=e.message}};
$('compareForm').onsubmit=async e=>{e.preventDefault();if(!styleData||!active)return;const seq=generation;$('compareStatus').textContent='비교 분석 중…';try{const d=await get('/api/playstyle',{nickname:$('compareName').value,platform:active.platform,limit:20});if(seq!==generation)return;radar(styleData,d);$('compareStatus').textContent='비교 완료'}catch(e){$('compareStatus').textContent=e.message}};
get('/api/admin/status').then(d=>{admin=d;updateBoardActions();if(['teams','notices'].includes(SITE_PAGE))refreshBoard();}).catch(()=>{});initPage();

function selectChart(key){$('rpGraph').hidden=key!=='rp';$('roundGraph').hidden=key!=='rounds';$('chartRP').classList.toggle('active',key==='rp');$('chartRounds').classList.toggle('active',key==='rounds');}
$('chartRP').onclick=()=>selectChart('rp');$('chartRounds').onclick=()=>selectChart('rounds');renderTierGuide(null);

$('boardSearchForm').onsubmit=e=>{e.preventDefault();boardQuery=$('boardQuery').value.trim();boardPage=1;renderBoardList()};
$('boardClearSearch').onclick=()=>{boardQuery='';$('boardQuery').value='';boardPage=1;renderBoardList()};
$('boardWriteButton').onclick=()=>{if(SITE_PAGE==='notices'&&!admin.admin)return;$('boardCompose').hidden=false;$('boardListView').hidden=true;$('boardDetail').hidden=true;updateBoardActions();$('boardCompose').scrollIntoView({behavior:'smooth',block:'start'});};
$('adminLogout').onclick=async()=>{try{await send('/api/admin/logout',{});admin={};$('boardCompose').hidden=true;updateBoardActions();showBoardList();}catch(e){$('boardMessage').textContent=e.message}};

// Home quick search also works with templates already cached by a running server.
(function(){
 'use strict';
 const formMarkup="<form id=\"homeQuickSearch\" class=\"home-quick-search\" action=\"/search\" method=\"get\" role=\"search\" aria-label=\"홈 전적 검색\"><select id=\"homePlatform\" name=\"platform\" aria-label=\"검색 플랫폼\"><option value=\"steam\">Steam (PC)</option><option value=\"kakao\">Kakao</option><option value=\"psn\">PlayStation</option><option value=\"xbox\">Xbox</option></select><input id=\"homeNickname\" name=\"nickname\" type=\"text\" required maxlength=\"32\" placeholder=\"PUBG 닉네임을 입력하세요\" aria-label=\"PUBG 닉네임\" autocomplete=\"off\" autocapitalize=\"none\" spellcheck=\"false\"><button type=\"submit\">전적 검색</button></form>";
 const styleText=".home-quick-search{display:grid;grid-template-columns:140px minmax(0,1fr) auto;gap:8px;max-width:650px;padding:9px;margin:26px 0 15px;background:var(--surface);border:1px solid var(--border);border-radius:13px;box-shadow:0 10px 30px #00000012}.home-quick-search select,.home-quick-search input{width:100%;min-width:0;margin:0;box-sizing:border-box;padding:14px 12px;background:var(--input-bg,var(--surface-2));border:1px solid var(--border);border-radius:8px;color:var(--text);font:inherit;font-size:13px}.home-quick-search input::placeholder{color:var(--muted)}.home-quick-search button{border:0;border-radius:8px;background:var(--accent);color:var(--on-accent,#fff);font:inherit;font-size:13px;font-weight:800;padding:12px 17px;white-space:nowrap;cursor:pointer}.home-quick-search :focus-visible{outline:2px solid var(--accent);outline-offset:2px}@media(max-width:600px){.home-quick-search{grid-template-columns:minmax(0,1fr) auto;margin-top:22px}.home-quick-search select{grid-column:1/-1;padding:11px 10px}.home-quick-search input{padding:13px 10px;font-size:12px}.home-quick-search button{padding:12px;font-size:12px}.home-hero-copy .home-actions{margin-top:13px}}";
 if(!document.getElementById('homeQuickSearchStyle')){const style=document.createElement('style');style.id='homeQuickSearchStyle';style.textContent=styleText;document.head.appendChild(style);}
 const copy=document.querySelector('.home-hero-copy');
 if(copy&&!document.getElementById('homeQuickSearch')){const actions=copy.querySelector('.home-actions');if(actions){actions.insertAdjacentHTML('beforebegin',formMarkup);const old=actions.querySelector('a[href="/search"]');if(old)old.remove();}else copy.insertAdjacentHTML('beforeend',formMarkup);}
 function init(){
  const form=document.getElementById('homeQuickSearch'),select=document.getElementById('homePlatform');
  const allowed=['steam','kakao','psn','xbox'];
  if(form&&select){const current=document.documentElement.dataset.platform;if(allowed.includes(current))select.value=current;select.addEventListener('change',()=>{if(window.GameggTheme)window.GameggTheme.applyPlatform(select.value);});form.addEventListener('submit',e=>{const input=document.getElementById('homeNickname');input.value=input.value.trim();if(!input.value){e.preventDefault();input.focus();return;}if(window.GameggTheme)window.GameggTheme.applyPlatform(select.value);});if(document.body.dataset.page==='home'&&window.matchMedia('(min-width: 851px)').matches)document.getElementById('homeNickname').focus({preventScroll:true});}
  if(document.body.dataset.page!=='search')return;
  const params=new URLSearchParams(window.location.search),name=(params.get('nickname')||'').trim(),platform=params.get('platform')||'steam';
  const searchForm=document.getElementById('searchForm');
  if(!name||name.length>32||!allowed.includes(platform)||!searchForm||searchForm.dataset.quickSearchStarted)return;
  searchForm.dataset.quickSearchStarted='true';document.getElementById('platform').value=platform;document.getElementById('platform').dispatchEvent(new Event('change',{bubbles:true}));document.getElementById('nickname').value=name;searchForm.requestSubmit();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
