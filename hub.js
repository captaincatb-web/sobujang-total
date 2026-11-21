'use strict';
const el=id=>document.getElementById(id),escapeHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let data=null,offset=0,tasks=[];const groups={core:'핵심',managed:'별도 관리',new:'신규 조사'};
try{const v=JSON.parse(localStorage.getItem('supply-research-tasks-v1')||'[]');if(Array.isArray(v))tasks=v.filter(x=>typeof x.id==='string'&&typeof x.title==='string'&&typeof x.done==='boolean').slice(0,500);}catch{}
function save(){try{localStorage.setItem('supply-research-tasks-v1',JSON.stringify(tasks));}catch{el('hub-status').textContent='브라우저 저장에 실패했습니다. 현재 화면에서만 작업이 유지됩니다.';}renderTasks();}
function renderTasks(){el('hub-tasks').innerHTML=tasks.map(t=>`<p><label><input type="checkbox" data-task="${escapeHtml(t.id)}" ${t.done?'checked':''}> ${escapeHtml(t.title)}</label> <small>${t.done?'내 작업 완료':'진행 필요'}</small></p>`).join('')||'<p class="empty">기업의 조사 추가 버튼을 누르거나 직접 작업을 입력하세요.</p>';}
function addTask(title){if(tasks.length>=500){el('hub-status').textContent='작업은 최대 500개까지 보관합니다.';return;}tasks.unshift({id:crypto.randomUUID(),title,done:false});save();}
function hasSite(id){return data.sites.some(s=>s.entity_id===id&&s.status==='approved');}
function gaps(c){return [c.verified_facts===0?'승인 재무 없음':'',c.meta.classification_status!=='verified'?'분류 원문 확인 전':'',!hasSite(c.id)?'승인 사업장 없음':''].filter(Boolean);}
function list(){return data.companies.filter(c=>c.legal_name.toLowerCase().includes(el('hub-query').value.trim().toLowerCase())&&(!el('hub-market').value||(c.meta.market||'미확인')===el('hub-market').value)&&(!el('hub-process').value||(c.meta.process||'미확인')===el('hub-process').value)&&(!el('hub-business').value||(c.meta.business_type||'미확인')===el('hub-business').value)&&(!el('hub-gap').value||({finance:c.verified_facts===0,classification:c.meta.classification_status!=='verified',site:!hasSite(c.id)})[el('hub-gap').value]));}
function evidence(company) {
  const periods = new Map();
  const metrics = { revenue: '매출액', operating_income: '영업이익' };
  const scopes = { consolidated: '연결', separate: '별도', standalone: '개별' };
  for (const fact of data.facts) {
    if (fact.entity_id !== company.id || fact.status !== 'approved' || fact.verified !== true) continue;
    const p = fact.payload;
    let url;
    try { url = new URL(p.source_url); } catch { continue; }
    if (url.protocol !== 'https:') continue;
    const loc = p.source_locator || {};
    if (loc.type === 'pdf' && Number.isSafeInteger(Number(loc.page)) && Number(loc.page) > 0 && !url.hash) url.hash = 'page=' + Number(loc.page);
    const period = [p.period_start, p.period_end].filter(Boolean).join(' ~ ') || p.fiscal_year_label || '기간 미확인';
    const scope = scopes[p.scope] || p.scope || '범위 미확인';
    const title = period + ' · ' + scope;
    if (!periods.has(title)) periods.set(title, []);
    const reference = [loc.page && loc.page+'쪽', loc.table, loc.row, loc.column].filter(Boolean).join(' · ');
    const amount = [p.raw_value ?? '값 미확인', p.raw_unit, p.currency && !String(p.raw_unit || '').includes(p.currency) && p.currency].filter(v => v !== false && v != null && v !== '').join(' ');
    periods.get(title).push('<li><strong>'+escapeHtml(metrics[p.metric] || p.metric)+'</strong> '+escapeHtml(amount)+'<br><a target="_blank" rel="noopener noreferrer" href="'+escapeHtml(url.href)+'">'+escapeHtml(reference || '공시 원문')+'</a></li>');
  }
  const sections = [...periods.keys()].sort().reverse().map(title => '<section><b>'+escapeHtml(title)+'</b><ul>'+periods.get(title).join('')+'</ul></section>');
  return sections.length ? '<details><summary>검증 재무·공시 근거 보기</summary>'+sections.join('')+'</details>' : '';
}
function render(){const rows=list();offset=Math.min(offset,Math.max(0,Math.ceil(rows.length/15)-1));el('hub-count').textContent=`${rows.length}개 기업 · 누락은 사업 부재가 아니라 이 스냅샷의 근거 미확보를 뜻합니다.`;el('hub-page').textContent=`${offset+1} / ${Math.max(1,Math.ceil(rows.length/15))}`;el('hub-prev').disabled=offset===0;el('hub-next').disabled=(offset+1)*15>=rows.length;el('hub-rows').innerHTML=rows.slice(offset*15,(offset+1)*15).map(c=>`<tr><td><b>${escapeHtml(c.legal_name)}</b><small>${escapeHtml(c.country+' · '+(c.meta.business_type||'사업 유형 미확인'))}</small></td><td>${escapeHtml(c.meta.market||'미확인')}<small>${escapeHtml(c.meta.process||'공정 미확인')}</small></td><td>${escapeHtml(groups[c.meta.population]||'미분류')}</td><td>${escapeHtml(gaps(c).join(' · ')||'등록 항목 확인됨')}${evidence(c)}</td><td><button data-add="${escapeHtml(c.id)}">조사 추가</button></td></tr>`).join('')||'<tr><td colspan="5">선택 조건에 해당하는 기업이 없습니다.</td></tr>';}
for(const id of ['hub-query','hub-market','hub-process','hub-business','hub-gap'])el(id).addEventListener('input',()=>{offset=0;if(data)render();});
el('hub-reset').onclick=()=>{for(const id of ['hub-query','hub-market','hub-process','hub-business','hub-gap'])el(id).value='';offset=0;render();};el('hub-prev').onclick=()=>{offset--;render();};el('hub-next').onclick=()=>{offset++;render();};
el('task-form').onsubmit=e=>{e.preventDefault();const t=el('task-title').value.trim();if(t){addTask(t);el('task-title').value='';}};
el('hub-rows').onclick=e=>{const b=e.target.closest('[data-add]');if(b){const c=data.companies.find(c=>c.id===b.dataset.add);addTask(c.legal_name+' · '+(gaps(c).join(' / ')||'추가 근거 검토'));el('hub-status').textContent=c.legal_name+' 조사 작업을 추가했습니다.';}};
el('hub-tasks').onchange=e=>{const t=tasks.find(t=>t.id===e.target.dataset.task);if(t){t.done=e.target.checked;save();}};renderTasks();
fetch('./snapshot.json').then(r=>{if(!r.ok)throw Error('load');return r.json();}).then(d=>{data=d;for(const [id,key] of [['hub-market','market'],['hub-process','process'],['hub-business','business_type']])el(id).innerHTML='<option value="">전체</option>'+[...new Set(data.companies.map(c=>c.meta[key]||'미확인'))].sort().map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');el('hub-metrics').innerHTML=[['기업 마스터',data.companies.length],['재무 확인 기업',data.companies.filter(c=>c.verified_facts>0).length],['승인 재무 사실',data.facts.length],['승인 사업장',data.sites.filter(s=>s.status==='approved').length]].map(([k,v])=>`<div class="metric"><small>${k}</small><strong>${v}</strong></div>`).join('');el('population-summary').innerHTML=Object.entries(groups).map(([key,label])=>{const cs=data.companies.filter(c=>c.meta.population===key);return `<div><b>${label}</b><h2>${cs.length}개</h2><p>재무 확인 ${cs.filter(c=>c.verified_facts>0).length}개 기업</p></div>`;}).join('');el('hub-status').textContent='자료 묶음 생성 '+new Date(data.generated_at).toLocaleString('ko-KR')+' · 가상 기업·예시 재무 미반입';render();}).catch(()=>el('hub-status').textContent='자료를 불러오지 못했습니다. 잠시 후 새로고침하세요.');
