// Describe a scene: a bar at the top middle of the view. The person types the scene they want;
// a model on their own key (Settings > General) picks robots and objects from our catalog;
// they check that list (robots with a count, objects they can remove or add); then Create
// scene closes the card and the model's layout is built on a free spot of the floor, robots
// first, then furniture, then objects, each with the drag-and-drop drop check
// (playground/scenegen.py). Stop halts it; Undo takes all of it away again.
(() => {
const css = `
body:not(.freeplay) #sgBar, body.watch #sgBar, body.sgHide #sgBar{display:none}
#sgBar{position:absolute;left:50%;top:12px;transform:translateX(-50%);z-index:7;display:flex;align-items:center;gap:8px;height:38px;padding:0 8px 0 12px;border-radius:12px;border:0;background:rgba(255,255,255,.95);box-shadow:0 4px 14px rgba(17,24,39,.14),0 0 0 1px rgba(17,24,39,.08);font:500 13px Inter,sans-serif;color:#4B5563;cursor:text;white-space:nowrap;transition:transform 160ms ease-out}
#sgBar:active{transform:translateX(-50%) scale(.98)}
#sgBar .k{font:600 11px Inter,sans-serif;color:#4B5563;border:1px solid #E5E7EB;border-radius:5px;padding:1px 6px;margin-left:10px}
#sgBar.busy{cursor:default;color:#111827;font-weight:600}
#sgBar.busy{padding:0 6px 0 12px;gap:10px}
#sgBar .ct{font-weight:500;color:#6B7280;font-variant-numeric:tabular-nums}
#sgBar .sep{width:1px;height:18px;background:#E5E7EB}
#sgBar .stop{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:8px;background:#F3F4F6;font:600 12.5px/1 Inter,sans-serif;color:#111827;cursor:pointer}
#sgBar .stop:hover{background:#E5E7EB}
#sgBar .spin{width:14px;height:14px;border-radius:50%;border:2px solid #DBE5FF;border-top-color:#2563EB;animation:sgSpin .8s linear infinite;flex:none}
@keyframes sgSpin{to{transform:rotate(360deg)}}
@container (max-width:780px){#sgBar{left:14px;top:58px;transform:none}#sgBar:active{transform:scale(.98)}#sgProg,#sgProg.open{left:14px;top:104px;transform:none;animation:none}}
#sgScrim{position:absolute;inset:0;z-index:20;background:rgba(17,24,39,.18);display:none}
#sgScrim.open{display:block}
#sgCard{position:absolute;left:50%;top:60px;transform:translateX(-50%);z-index:21;width:min(640px,calc(100% - 32px));max-height:calc(100% - 80px);display:none;flex-direction:column;background:#fff;border-radius:16px;box-shadow:0 24px 48px -16px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.08);font:14px Inter,sans-serif;color:#111827;overflow:hidden}
#sgCard.open{display:flex;animation:sgIn 200ms cubic-bezier(.23,1,.32,1)}
@keyframes sgIn{from{opacity:0;transform:translateX(-50%) translateY(-6px) scale(.98)}}
#sgCard .h{display:flex;align-items:center;gap:8px;padding:14px 14px 0 16px}
#sgCard .h h3{margin:0;font:650 15px Inter,sans-serif;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sgCard .x{width:30px;height:30px;border:0;background:none;border-radius:8px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:#6B7280}
#sgCard .x:hover{background:#F3F4F6}
#sgCard .body{padding:10px 16px 0;overflow:auto;min-height:0}
#sgCard textarea{width:100%;box-sizing:border-box;min-height:84px;resize:none;border:0;outline:0;font:15px/1.5 Inter,sans-serif;color:#111827;padding:2px 0}
#sgCard textarea::placeholder{color:#9CA3AF}
#sgCard .f{display:flex;align-items:center;gap:8px;padding:12px 16px 14px;position:relative}
#sgCard .f .sp{flex:1}
#sgCard .btn{height:34px;padding:0 14px;border-radius:9px;border:0;font:600 13px Inter,sans-serif;cursor:pointer;display:flex;align-items:center;gap:8px;transition:transform 120ms ease-out}
#sgCard .btn:active{transform:scale(.97)}
#sgCard .btn.blue{background:#2563EB;color:#fff}
#sgCard .btn.blue:disabled{background:#93B4F5;cursor:default}
#sgCard .btn.g{background:#fff;color:#111827;box-shadow:inset 0 0 0 1px #E5E7EB}
#sgCard .kb{font:600 11px Inter,sans-serif;opacity:.8}
#sgCard .mp{height:34px;display:flex;align-items:center;gap:7px;padding:0 10px;border-radius:9px;border:1px solid #E5E7EB;background:#fff;font:600 13px Inter,sans-serif;color:#111827;cursor:pointer}
#sgCard .mp.flat{border-color:transparent;padding-left:0;cursor:default}
#sgCard .mp img{width:16px;height:16px}
#sgCard .dd{position:absolute;left:16px;bottom:52px;width:280px;background:#fff;border-radius:12px;box-shadow:0 16px 32px -12px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.08);padding:6px;z-index:3;display:none;max-height:320px;overflow:auto}
#sgCard .dd.open{display:block}
#sgCard .dd .gh{font-size:12px;font-weight:600;color:#4B5563;padding:8px 10px 4px}
#sgCard .dd button{width:100%;height:34px;display:flex;align-items:center;gap:8px;padding:0 10px;border-radius:8px;border:0;background:none;font:14px Inter,sans-serif;color:#111827;cursor:pointer;text-align:left}
#sgCard .dd button:hover,#sgCard .dd button.on{background:#F3F4F6}
#sgCard .dd button.on{font-weight:600}
#sgCard .dd button .ck{margin-left:auto;color:#2563EB}
#sgCard .empty{display:flex;align-items:center;gap:12px;padding:14px;border-radius:12px;background:#F7F8FA;margin-top:4px}
#sgCard .empty span{flex:1;font-size:13.5px}
#sgCard .empty b{display:block}
#sgCard .err{margin:8px 0 0;font-size:13px;color:#B91C1C}
#sgCard .quote{font-size:13px;color:#4B5563;margin:0 0 10px;display:flex;gap:8px}
#sgCard .quote span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sgCard .quote a{color:#2563EB;font-weight:600;cursor:pointer;text-decoration:none}
#sgCard .sec{display:flex;align-items:baseline;gap:8px;font:650 13px Inter,sans-serif;margin:6px 0 8px}
#sgCard .sec small{font-weight:500;color:#6B7280;font-size:12px}
#sgCard .car{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px;scroll-snap-type:x mandatory}
#sgCard .rc{flex:none;width:168px;scroll-snap-align:start;position:relative}
#sgCard .rc .art{height:150px;border-radius:12px;background:#F7F8FA;display:flex;align-items:center;justify-content:center;overflow:hidden}
#sgCard .rc .art img{max-width:92%;max-height:92%;object-fit:contain}
#sgCard .rc .nm{display:flex;align-items:center;gap:6px;margin-top:8px}
#sgCard .rc .nm b{flex:1;min-width:0;font:600 13px Inter,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgCard .stp{display:flex;align-items:center;border:1px solid #E5E7EB;border-radius:8px;height:28px}
#sgCard .stp button{width:26px;height:26px;border:0;background:none;font:600 14px Inter,sans-serif;color:#111827;cursor:pointer}
#sgCard .stp button:disabled{color:#D1D5DB;cursor:default}
#sgCard .stp span{min-width:18px;text-align:center;font:600 13px Inter,sans-serif;font-variant-numeric:tabular-nums}
#sgCard .addr{flex:none;width:120px;height:150px;border-radius:12px;border:1px dashed #D1D5DB;background:#fff;font:600 13px Inter,sans-serif;color:#374151;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px}
#sgCard .addr:disabled{opacity:.5;cursor:default}
#sgCard .grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
#sgCard .oc{position:relative;border:1px solid #E5E7EB;border-radius:10px;padding:6px 6px 8px;display:flex;flex-direction:column;align-items:center;gap:4px;min-width:0}
#sgCard .oc img{width:100%;aspect-ratio:1;object-fit:contain}
#sgCard .oc b{font:500 11.5px Inter,sans-serif;width:100%;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgCard .oc .n{position:absolute;left:6px;top:5px;font:600 11px Inter,sans-serif;color:#4B5563}
#sgCard .oc .rm{position:absolute;right:2px;top:2px;width:22px;height:22px;border:0;background:none;border-radius:6px;color:#9CA3AF;cursor:pointer;display:flex;align-items:center;justify-content:center}
#sgCard .oc .rm:hover{background:#F3F4F6;color:#111827}
#sgCard .oc.add{border-style:dashed;justify-content:center;font:600 12px Inter,sans-serif;color:#374151;cursor:pointer;background:#fff;min-height:84px}
#sgCard .note{font-size:12.5px;color:#4B5563;margin:12px 0 2px;line-height:1.45}
#sgCard .srch{width:100%;box-sizing:border-box;height:34px;border:1px solid #E5E7EB;border-radius:9px;padding:0 10px;font:14px Inter,sans-serif;margin-bottom:8px}
#sgCard .sk{border-radius:12px;background:linear-gradient(90deg,#F3F4F6 0%,#E9EBEF 50%,#F3F4F6 100%);background-size:200% 100%;animation:sgSk 1.2s ease-in-out infinite}
@keyframes sgSk{from{background-position:200% 0}to{background-position:-200% 0}}
#sgCard .wait{display:flex;align-items:center;gap:8px;font-size:13px;color:#4B5563;margin:2px 0 12px}
#sgProg{position:absolute;left:50%;top:58px;transform:translateX(-50%);z-index:7;width:min(368px,calc(100% - 32px));background:#fff;border-radius:14px;box-shadow:0 12px 28px -12px rgba(17,24,39,.28),0 0 0 1px rgba(17,24,39,.06);overflow:hidden;font:13px/1.45 Inter,sans-serif;color:#111827;display:none}
#sgProg.open{display:block;animation:sgIn2 200ms cubic-bezier(.23,1,.32,1)}
@keyframes sgIn2{from{opacity:0;transform:translateX(-50%) translateY(-4px)}}
#sgProg .bar{height:3px;background:#EEF0F3}
#sgProg .bar i{display:block;height:100%;background:#2563EB;border-radius:0 2px 2px 0;transition:width 400ms cubic-bezier(.23,1,.32,1)}
#sgProg .plan{display:flex;gap:10px;padding:14px 16px 12px;border-bottom:1px solid #F1F2F4}
#sgProg .plan .pi{width:28px;height:28px;border-radius:8px;background:#EFF4FF;color:#2563EB;display:flex;align-items:center;justify-content:center;flex:none}
#sgProg .plan b{display:block;font:600 12px Inter,sans-serif;margin-bottom:2px}
#sgProg .plan p{margin:0;color:#4B5563;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
#sgProg .plan .skl{height:9px;border-radius:5px;margin-top:7px;background:linear-gradient(90deg,#EEF0F3 0%,#E3E6EB 50%,#EEF0F3 100%);background-size:200% 100%;animation:sgSk 1.2s ease-in-out infinite}
#sgProg ul{list-style:none;margin:0;padding:8px 8px 10px}
#sgProg li{display:flex;align-items:center;gap:10px;height:40px;padding:0 8px;border-radius:9px}
#sgProg li.now{background:#F7F8FA}
#sgProg .ti{width:28px;height:28px;border-radius:8px;background:#F3F4F6;color:#374151;display:flex;align-items:center;justify-content:center;position:relative;flex:none}
#sgProg li.todo .ti{color:#9CA3AF;background:#F7F8FA}
#sgProg li.todo .nm{color:#9CA3AF}
#sgProg .bd{position:absolute;right:-4px;bottom:-4px;width:15px;height:15px;border-radius:50%;background:#16A34A;display:flex;align-items:center;justify-content:center;box-shadow:0 0 0 2px #fff}
#sgProg li.now .bd{background:#fff}
#sgProg .nm{flex:1;min-width:0;font-weight:500}
#sgProg .nm small{display:block;font-weight:400;font-size:11.5px;color:#6B7280;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgProg .n{font-variant-numeric:tabular-nums;color:#6B7280;font-size:12.5px;white-space:nowrap}
#sgProg li.now .n{color:#111827;font-weight:600}
#sgProg .mini{width:56px;height:4px;border-radius:2px;background:#E5E7EB;overflow:hidden;flex:none}
#sgProg .mini i{display:block;height:100%;background:#2563EB}
#sgProg .res{display:flex;gap:12px;padding:16px 16px 4px}
#sgProg .res .ri{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:none}
#sgProg .res b{display:block;font:650 14px Inter,sans-serif;margin-bottom:2px}
#sgProg .res p{margin:0;color:#4B5563}
#sgProg .chips{display:flex;gap:6px;flex-wrap:wrap;padding:10px 16px 0 60px}
#sgProg .chip{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 8px;border-radius:7px;background:#F3F4F6;font:500 12px Inter,sans-serif;color:#374151}
#sgProg .skip{display:flex;gap:8px;align-items:flex-start;margin:10px 16px 0 60px;color:#6B7280;font-size:12.5px}
#sgProg .skip svg{flex:none;margin-top:2px}
#sgProg .acts{display:flex;justify-content:flex-end;gap:8px;padding:14px 16px 16px}
#sgProg .gb{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border-radius:9px;border:0;font:600 13px Inter,sans-serif;cursor:pointer;transition:transform 120ms ease-out}
#sgProg .gb:active{transform:scale(.97)}
#sgProg .gb.g{background:#fff;color:#111827;box-shadow:inset 0 0 0 1px #E5E7EB}
#sgProg .gb.g:hover{background:#F9FAFB}
#sgProg .gb.p{background:#111827;color:#fff}
.sgRing{width:16px;height:16px;flex:none;display:block;animation:sgSpin .8s linear infinite}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const stage = document.getElementById('stage');
const e = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const SPARK = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563EB" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>';
const XI = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const XS = '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const PLUS = '<svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M6 1 V11 M1 6 H11"/></svg>';
const CHEV = '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#4B5563" stroke-width="1.6" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>';
const OK = '<svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#16A34A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 6.2l2.4 2.3 4.6-5"/></svg>';
const PIC = {franka: '/pg/static/robot_franka.png', ur5e: '/pg/static/robot_ur5e.png', aloha: '/pg/static/robot_aloha.png', fr3_duo: '/pg/static/robot_fr3_duo.png', g1: '/pg/static/robot_g1.png'};
const LOGO = {anthropic: '/static/anthropic.svg', openai: '/static/openai.svg'};

stage.insertAdjacentHTML('beforeend', `<button id="sgBar" aria-haspopup="dialog" aria-expanded="false">${SPARK}<span id="sgBarT">Describe a scene…</span><span class="k" aria-hidden="true">/</span></button>
<div id="sgScrim"></div><div id="sgCard" role="dialog" aria-label="Describe a scene"></div><div id="sgProg" role="status" aria-live="polite"></div>`);
const bar = document.getElementById('sgBar'), card = document.getElementById('sgCard'), scrim = document.getElementById('sgScrim'), prog = document.getElementById('sgProg');
const G = {open: false, step: 'describe', prompt: '', model: '', models: [], maxRobots: 4, fromRun: {}, pick: null, err: '', build: null, poll: 0, adding: '', q: ''};

const robotsCat = () => (S.cat && S.cat.robots) || [];
const itemsCat = () => (S.cat && S.cat.items) || [];
const robotLabel = (id) => { const r = robotsCat().find(x => x.id === id); return r ? r.label.replace(/ \(two arms\)/, '') : id; };
const item = (id) => itemsCat().find(x => x.id === id) || {id, label: id, thumb: `/pg/thumb/${id}.png`};
const nRobots = () => (G.pick ? G.pick.robots.reduce((a, r) => a + r.count, 0) : 0);
const nItems = () => (G.pick ? G.pick.items.reduce((a, r) => a + r.count, 0) : 0);
const modelInfo = (id) => G.models.find(m => m.id === id) || null;

function defaultModel() {
  // one company: its most capable model; both: the model of your last task run, if it can build
  let last = '';
  try { last = localStorage.getItem('pgLastModel') || ''; } catch (err) {}
  last = G.fromRun[last] || last;
  if (G.models.length && new Set(G.models.map(m => m.provider)).size > 1 && modelInfo(last)) return last;
  if (modelInfo(G.model)) return G.model;
  return (G.models.find(m => m.default) || G.models[0] || {}).id || '';
}

async function loadInfo() {
  const r = await api('/pg/scenegen/info', {});
  if (!r || !r.ok) return;
  G.models = r.models || []; G.maxRobots = r.max_robots || 4; G.fromRun = r.from_run || {};
  G.model = defaultModel();
  if (r.build && r.build.active) follow(r.build);
}

async function openCard() {
  if (G.build && G.build.active) return;
  if (S.scene && S.scene.mode === 'free' && document.body.classList.contains('watch')) return;
  G.open = true; bar.setAttribute('aria-expanded', 'true');
  card.classList.add('open'); scrim.classList.add('open');
  if (!G.pick) G.step = 'describe';
  draw();
  await loadInfo();
  draw();
}
function closeCard() {
  G.open = false; bar.setAttribute('aria-expanded', 'false');
  card.classList.remove('open'); scrim.classList.remove('open');
}

function modelBtn() {
  const m = modelInfo(G.model);
  if (!m) return '';
  const many = G.models.length > 1 && new Set(G.models.map(x => x.provider)).size > 1;
  return `<button class="mp${many ? '' : ' flat'}" id="sgMp" ${many ? 'aria-haspopup="listbox" aria-expanded="false"' : 'tabindex="-1"'}><img src="${LOGO[m.provider]}" alt="">${e(m.label)}${many ? CHEV : ''}</button>`;
}
function modelMenu() {
  const by = {};
  for (const m of G.models) (by[m.provider] = by[m.provider] || []).push(m);
  return `<div class="dd" id="sgDd" role="listbox">` + Object.entries(by).map(([p, ms]) =>
    `<div class="gh">${p === 'anthropic' ? 'Anthropic' : 'OpenAI'}</div>` + ms.map(m =>
      `<button role="option" data-m="${m.id}" class="${m.id === G.model ? 'on' : ''}" aria-selected="${m.id === G.model}"><img src="${LOGO[m.provider]}" alt="" width="16" height="16">${e(m.label)}${m.id === G.model ? '<span class="ck">✓</span>' : ''}</button>`).join('')).join('') + '</div>';
}

function draw() {
  if (!G.open) return;
  const head = (t) => `<div class="h">${SPARK}<h3>${e(t)}</h3><button class="x" id="sgX" aria-label="Close">${XI}</button></div>`;
  if (!G.models.length) {
    card.innerHTML = head('Describe a scene') + `<div class="body"><div class="empty"><span><b>Connect an AI model first</b>Scenes are built by your own Anthropic or OpenAI model. Add a key in Settings.</span><button class="btn g" id="sgSet">Open Settings</button></div></div><div class="f"></div>`;
  } else if (G.step === 'describe') {
    card.innerHTML = head('Describe a scene') + `<div class="body"><textarea id="sgTa" placeholder="A robot making breakfast in a kitchen: cereal, milk, a mug and a kettle…" aria-label="Describe the scene">${e(G.prompt)}</textarea>${G.err ? `<p class="err">${e(G.err)}</p>` : ''}</div>
<div class="f">${modelBtn()}<span class="sp"></span><button class="btn blue" id="sgGo" ${G.prompt.trim() ? '' : 'disabled'}>Find robots and objects<span class="kb">↵</span></button>${modelMenu()}</div>`;
    const ta = document.getElementById('sgTa');
    ta.oninput = () => { G.prompt = ta.value; document.getElementById('sgGo').disabled = !ta.value.trim(); };
    ta.onkeydown = (ev) => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); find(); } };
    setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
  } else if (G.step === 'finding') {
    const sk = (w, h) => `<div class="sk" style="width:${w};height:${h}px"></div>`;
    card.innerHTML = head('Describe a scene') + `<div class="body"><div class="quote"><span>“${e(G.prompt)}”</span></div>
<div class="wait"><span class="spin" style="width:14px;height:14px;border-radius:50%;border:2px solid #DBE5FF;border-top-color:#2563EB;animation:sgSpin .8s linear infinite"></span>${e((modelInfo(G.model) || {}).label || 'The model')} is finding robots and objects…</div>
<div class="sec">Robots</div><div class="car">${sk('168px', 150)}${sk('168px', 150)}</div>
<div class="sec" style="margin-top:12px">Objects</div><div class="grid">${Array.from({length: 12}, () => sk('100%', 84)).join('')}</div></div>
<div class="f"><span class="sp"></span><button class="btn g" id="sgBack">Cancel</button></div>`;
  } else if (G.step === 'check') {
    const p = G.pick, full = nRobots() >= G.maxRobots;
    const robots = p.robots.map((r, i) => `<div class="rc"><div class="art"><img src="${PIC[r.robot] || ''}" alt="${e(robotLabel(r.robot))}"></div>
<div class="nm"><b>${e(robotLabel(r.robot))}</b><div class="stp"><button data-r="${i}" data-d="-1" aria-label="One fewer ${e(robotLabel(r.robot))}">−</button><span>${r.count}</span><button data-r="${i}" data-d="1" aria-label="One more ${e(robotLabel(r.robot))}" ${full ? 'disabled' : ''}>+</button></div></div></div>`).join('');
    const addR = G.adding === 'robot'
      ? `<div class="rc" style="width:200px"><div class="dd open" style="position:static;width:auto;box-shadow:0 0 0 1px #E5E7EB">${robotsCat().map(r => `<button data-addr="${r.id}"><img src="${PIC[r.id] || ''}" alt="" width="22" height="22" style="object-fit:contain">${e(robotLabel(r.id))}</button>`).join('')}</div></div>`
      : `<button class="addr" id="sgAddR" ${full ? 'disabled' : ''}>${PLUS}Add a robot</button>`;
    const objs = p.items.map((it, i) => { const c = item(it.id); return `<div class="oc">${it.count > 1 ? `<span class="n">×${it.count}</span>` : ''}<img src="${c.thumb}" alt=""><b title="${e(c.label)}">${e(c.label)}</b><button class="rm" data-o="${i}" aria-label="Remove ${e(c.label)}">${XS}</button></div>`; }).join('');
    let addO = `<button class="oc add" id="sgAddO">${PLUS} Add</button>`;
    let search = '';
    if (G.adding === 'object') {
      const q = G.q.toLowerCase(), have = new Set(p.items.map(x => x.id));
      const hits = itemsCat().filter(c => c.id !== 'table_packing' && !have.has(c.id) && (!q || c.label.toLowerCase().includes(q))).slice(0, 12);
      search = `<input class="srch" id="sgQ" placeholder="Search our objects" value="${e(G.q)}" aria-label="Search objects"><div class="grid" style="margin-bottom:10px">${hits.map(c => `<button class="oc add" data-addo="${c.id}" style="border-style:solid;min-height:0"><img src="${c.thumb}" alt=""><b>${e(c.label)}</b></button>`).join('') || '<span class="note">Nothing matches.</span>'}</div>`;
      addO = '';
    }
    const miss = p.missing.filter(m => m.name);
    const note = miss.length ? `<p class="note">Not in our objects yet: ${miss.map(m => `<b>${e(m.name)}</b>${m.instead ? ` (using ${e(item(m.instead).label.toLowerCase())})` : ''}`).join(', ')}. ${miss.some(m => !m.instead) ? 'They’re left out.' : ''}</p>` : '';
    card.innerHTML = head(p.title || 'New scene') + `<div class="body"><div class="quote"><span>“${e(G.prompt)}”</span><a id="sgEdit">Edit</a></div>
<div class="sec">Robots <small>${nRobots()} of up to ${G.maxRobots}</small></div><div class="car">${robots}${addR}</div>
<div class="sec" style="margin-top:12px">Objects <small>${nItems()}</small></div>${search}<div class="grid">${objs}${addO}</div>${note}
${G.err ? `<p class="err">${e(G.err)}</p>` : ''}</div>
<div class="f"><span class="sp"></span><button class="btn blue" id="sgCreate" ${nRobots() ? '' : 'disabled'}>Create scene<span class="kb">↵</span></button></div>`;
    const qi = document.getElementById('sgQ');
    if (qi) { qi.oninput = () => { G.q = qi.value; const pos = qi.selectionStart; draw(); const n = document.getElementById('sgQ'); n.focus(); n.setSelectionRange(pos, pos); }; if (!G.q) setTimeout(() => qi.focus(), 0); }
  }
  wire();
}

function wire() {
  const on = (id, f) => { const n = document.getElementById(id); if (n) n.onclick = f; };
  on('sgX', closeCard);
  on('sgSet', () => { closeCard(); window.openSettings && window.openSettings('general'); });
  on('sgGo', find);
  on('sgBack', () => { G.step = 'describe'; G.findId = 0; draw(); });
  on('sgEdit', () => { G.step = 'describe'; G.pick = null; G.adding = ''; draw(); });
  on('sgAddR', () => { G.adding = 'robot'; draw(); });
  on('sgAddO', () => { G.adding = 'object'; G.q = ''; draw(); });
  on('sgCreate', create);
  const mp = document.getElementById('sgMp'), dd = document.getElementById('sgDd');
  if (mp && dd && !mp.classList.contains('flat')) mp.onclick = (ev) => { ev.stopPropagation(); const o = !dd.classList.contains('open'); dd.classList.toggle('open', o); mp.setAttribute('aria-expanded', o); };
  card.querySelectorAll('[data-m]').forEach(b => b.onclick = () => { G.model = b.dataset.m; draw(); });
  card.querySelectorAll('[data-r]').forEach(b => b.onclick = () => {
    const r = G.pick.robots[+b.dataset.r], d = +b.dataset.d;
    if (d > 0 && nRobots() >= G.maxRobots) return;
    r.count += d;
    if (r.count <= 0) G.pick.robots.splice(+b.dataset.r, 1);
    draw();
  });
  card.querySelectorAll('[data-addr]').forEach(b => b.onclick = () => {
    const id = b.dataset.addr, have = G.pick.robots.find(r => r.robot === id);
    if (nRobots() < G.maxRobots) { if (have) have.count++; else G.pick.robots.push({robot: id, count: 1}); }
    G.adding = ''; draw();
  });
  card.querySelectorAll('[data-o]').forEach(b => b.onclick = () => { G.pick.items.splice(+b.dataset.o, 1); draw(); });
  card.querySelectorAll('[data-addo]').forEach(b => b.onclick = () => { G.pick.items.push({id: b.dataset.addo, count: 1}); G.adding = ''; G.q = ''; draw(); });
}

async function find() {
  if (!G.prompt.trim() || !G.model) return;
  G.err = ''; G.step = 'finding'; draw();
  const my = G.findId = (G.findId || 0) + 1;
  const r = await api('/pg/scenegen/pick', {prompt: G.prompt, model: G.model});
  if (my !== G.findId || G.step !== 'finding') return;     // cancelled meanwhile
  if (!r || !r.ok) { G.err = (r && r.error) || 'Something went wrong.'; G.step = 'describe'; draw(); return; }
  G.pick = r.pick; G.step = 'check'; G.adding = ''; draw();
}

async function create() {
  if (!G.pick || !nRobots()) return;
  G.err = '';
  G.last = {prompt: G.prompt, model: G.model, pick: JSON.parse(JSON.stringify(G.pick))};
  const r = await api('/pg/scenegen/build', G.last);
  if (!r || !r.ok) { G.err = (r && r.error) || 'Something went wrong.'; draw(); return; }
  closeCard();
  follow(r.build);
}

// ------------------------------------------------ the build, as it goes
function follow(b) {
  G.build = b; drawProg(); clearInterval(G.poll);
  G.poll = setInterval(async () => {
    const r = await api('/pg/scenegen/status', {});
    if (!r || !r.ok || !r.build) return;
    const was = G.build && G.build.active;
    G.build = r.build; drawProg();
    if (typeof refresh === 'function' && r.build.objects !== (G.seen || 0)) { G.seen = r.build.objects; refresh(); }
    if (was && !r.build.active) {
      clearInterval(G.poll);
      if (r.build.phase === 'done' && r.build.task) {
        for (const u of r.build.stations) S.drafts[u] = r.build.task;
        S.taskFor = null;
        if (typeof saveDrafts === 'function') saveDrafts();
      }
      G.pick = null; G.prompt = ''; G.step = 'describe';
      if (typeof refresh === 'function') refresh();
    }
  }, 700);
}

const IC = {
  plan: '<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/>',
  robots: '<path d="M5 21h8"/><path d="M9 21v-4"/><circle cx="9" cy="14" r="3"/><path d="M11 12l5-6"/><circle cx="17" cy="5" r="2"/><path d="M18.5 6.5L21 9"/>',
  furniture: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 12h18M12 4v16"/><path d="M8 8h1M15 8h1M8 16h1M15 16h1"/>',
  objects: '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 010 10h-3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  alert: '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17h.01"/>',
  pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  retry: '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
};
const ic = (k, s = 16, c = 'currentColor', w = 1.75) => `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">${IC[k]}</svg>`;
const ring = (s = 16) => { const r = s / 2 - 1.5; return `<svg class="sgRing" style="width:${s}px;height:${s}px" viewBox="0 0 ${s} ${s}" aria-hidden="true"><circle cx="${s / 2}" cy="${s / 2}" r="${r}" fill="none" stroke="#DBE5FF" stroke-width="2"/><path d="M${s / 2} ${s / 2 - r}a${r} ${r} 0 0 1 ${r} ${r}" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round"/></svg>`; };
const cap = (s) => String(s || '').replace(/^./, c => c.toUpperCase());
const list = (a, n = 3) => (a || []).length <= n ? (a || []).join(', ') : a.slice(0, n).join(', ') + '…';
const REST = () => `${SPARK}<span id="sgBarT">Describe a scene…</span><span class="k" aria-hidden="true">/</span>`;

function drawProg() {
  const b = G.build;
  const key = JSON.stringify(b);
  if (key === G.progKey) return;          // redraw only on a change (keeps the spinners smooth)
  G.progKey = key;
  if (!b || b.undone) { prog.classList.remove('open'); bar.classList.remove('busy'); bar.innerHTML = REST(); return; }
  const c = b.counts, done = c.robots[0] + c.furniture[0] + c.objects[0], all = c.robots[1] + c.furniture[1] + c.objects[1];
  if (b.active) {
    bar.classList.add('busy');
    bar.innerHTML = `${ring()}<span>${b.phase === 'plan' ? 'Planning' : 'Creating'} ${e(b.title)}</span>${b.phase !== 'plan' ? `<span class="ct">${done} of ${all}</span>` : ''}<span class="sep"></span><span class="stop" id="sgStop" role="button" tabindex="0">${ic('stop', 10)}Stop</span>`;
    const st = document.getElementById('sgStop');
    st.onclick = async (ev) => { ev.stopPropagation(); await api('/pg/scenegen/stop', {}); };
    st.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); st.click(); } };
  } else {
    bar.classList.remove('busy');
    bar.innerHTML = REST();
  }
  let html;
  if (b.active) {
    const order = ['plan', 'robots', 'furniture', 'objects'], at = order.indexOf(b.phase);
    const pct = b.phase === 'plan' ? 6 : 10 + 90 * done / Math.max(1, all);
    const plan = b.plan
      ? `<div class="plan"><span class="pi">${ic('plan')}</span><div><b>Layout plan</b><p>${e(b.plan)}</p></div></div>`
      : `<div class="plan"><span class="pi">${ic('plan')}</span><div style="flex:1"><b>${e(b.model || 'The model')} is writing the layout plan…</b><div class="skl" style="width:92%"></div><div class="skl" style="width:70%"></div></div></div>`;
    const row = (k, label, sub) => {
      const i = order.indexOf(k), st = at > i ? 'ok' : at === i ? 'now' : 'todo', [d, n] = c[k];
      const badge = st === 'ok' ? `<span class="bd">${ic('check', 9, '#fff', 3)}</span>` : st === 'now' ? `<span class="bd">${ring(13)}</span>` : '';
      const mini = st === 'now' ? `<span class="mini"><i style="width:${Math.round(100 * d / Math.max(1, n))}%"></i></span>` : '';
      return `<li class="${st}"><span class="ti">${ic(k)}${badge}</span><span class="nm">${label}${sub ? `<small>${e(sub)}</small>` : ''}</span>${mini}<span class="n">${d} of ${n}</span></li>`;
    };
    const nm = b.names || {};
    const objSub = b.phase === 'objects' && b.now ? `Placing the ${b.now.toLowerCase()}` : list(nm.objects);
    const furSub = b.phase === 'furniture' && b.now ? `Placing the ${b.now.toLowerCase()}` : list(nm.furniture);
    html = `<div class="bar"><i style="width:${pct}%"></i></div>${plan}<ul>${row('robots', c.robots[1] === 1 ? 'Robot' : 'Robots', list(nm.robots))}${c.furniture[1] ? row('furniture', 'Furniture', furSub) : ''}${row('objects', 'Objects', objSub)}</ul>`;
  } else {
    const undo = b.stations.length || b.objects ? `<button class="gb g" id="sgUndo">${ic('undo', 14)}Undo</button>` : '';
    if (b.phase === 'done') {
      const chips = [['robots', c.robots[0], 'robot'], ['furniture', c.furniture[0], 'furniture'], ['objects', c.objects[0], 'object']]
        .filter(x => x[1]).map(([k, n, w]) => `<span class="chip">${ic(k, 13)}${n} ${w}${n !== 1 && w !== 'furniture' ? 's' : ''}</span>`).join('');
      html = `<div class="res"><span class="ri" style="background:#ECFDF3">${ic('check', 16, '#16A34A', 2.4)}</span><div><b>${e(b.title)} is ready</b><p>Move anything you like.${b.task ? ' The task is filled in for the robot.' : ''}</p></div></div>
<div class="chips">${chips}</div>${b.skipped && b.skipped.length ? `<div class="skip">${ic('info', 14, '#9CA3AF')}<span>Didn't fit: ${e(b.skipped.join(', '))}</span></div>` : ''}
<div class="acts">${undo}<button class="gb p" id="sgOk">Done</button></div>`;
    } else if (b.phase === 'stopped') {
      html = `<div class="res"><span class="ri" style="background:#F3F4F6;color:#374151">${ic('pause', 15)}</span><div><b>Stopped</b><p>${done ? `${done} of ${all} placed. What's placed stays, or undo all of it.` : 'Nothing was placed.'}</p></div></div>
<div class="acts">${undo}<button class="gb p" id="sgOk">Done</button></div>`;
    } else {
      html = `<div class="res"><span class="ri" style="background:#FEF2F2">${ic('alert', 16, '#DC2626')}</span><div><b>Couldn't build the scene</b><p>${e(cap(b.error || 'something went wrong'))}.</p></div></div>
<div class="acts">${undo}<button class="gb g" id="sgOk">Close</button>${G.last ? `<button class="gb p" id="sgRetry">${ic('retry', 14)}Try again</button>` : ''}</div>`;
    }
  }
  prog.innerHTML = html;
  prog.classList.add('open');
  const ok = document.getElementById('sgOk'), un = document.getElementById('sgUndo'), re = document.getElementById('sgRetry');
  if (ok) ok.onclick = () => { G.build = null; drawProg(); };
  if (re) re.onclick = async () => {
    const r = await api('/pg/scenegen/build', G.last);
    if (!r || !r.ok) { toast((r && r.error) || 'Something went wrong.'); return; }
    follow(r.build);
  };
  if (un) un.onclick = async () => {
    const r = await api('/pg/scenegen/undo', {id: b.id});
    if (!r.ok) { toast(r.error); return; }
    for (const u of b.stations) delete S.drafts[u];
    G.build = null; drawProg(); toast('Scene removed'); if (typeof refresh === 'function') refresh();
  };
}

bar.onclick = () => { if (!(G.build && G.build.active)) openCard(); };
scrim.onclick = closeCard;
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && G.open) { closeCard(); return; }
  if (ev.key === '/' && !G.open && !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '') && !document.activeElement.isContentEditable
      && document.body.classList.contains('freeplay') && !document.body.classList.contains('watch')) { ev.preventDefault(); openCard(); }
});
document.addEventListener('click', (ev) => { const dd = document.getElementById('sgDd'); if (dd && dd.classList.contains('open') && !ev.target.closest('#sgDd')) dd.classList.remove('open'); });
// The play pill (a lock message) takes the top middle while it shows: the bar steps aside.
const pill = document.getElementById('playpill');
const sync = () => document.body.classList.toggle('sgHide', !!pill && !pill.classList.contains('none') && pill.innerHTML.trim() !== '' && !(G.build && G.build.active));
if (pill) new MutationObserver(sync).observe(pill, {attributes: true, childList: true, subtree: true});
window.sceneGen = {open: openCard};
setTimeout(loadInfo, 1500);
})();
