// Repeat runs and results: the Runs stepper on the task card (1 to 30 runs, each starting from
// the robot's table as it was when you pressed Run), a square per run in the chat (not started,
// running, succeeded, failed) while a batch goes, and the Results tab: every finished run of the
// selected robot, newest first; a click opens that run's timeline.
// A run "succeeded" when the AI finished on its own (no error, not stopped, not out of time).
// Data: /pg/scene (runs[uid].batch), /pg/results?uid=. Loaded after the page's own script and
// runpanel.js (uses S, SID, U, BID, api, esc, $, LOGOS, openRunTimeline).
(() => {
const MAX = 30;
const css = `
.taskcard .runs{display:flex;align-items:center;gap:8px;padding:0 10px 2px}
.taskcard .runs .lb{font:500 13px Inter,sans-serif;flex:1;color:#4B5563}
.taskcard .step{display:flex;align-items:center;height:28px;border:1px solid #E5E7EB;border-radius:8px;background:#fff;overflow:hidden;flex:none}
.taskcard .step button{width:26px;height:26px;border:0;background:transparent;font:500 15px Inter,sans-serif;color:#111827;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0}
.taskcard .step button:hover:not(:disabled){background:#F3F4F6}
.taskcard .step button:disabled{color:#C3C8D0;cursor:default}
.taskcard .step output{min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;font:600 13px 'JetBrains Mono',ui-monospace,monospace;color:#111827}
.sqs{display:flex;gap:4px;flex-wrap:wrap}
.sq{width:16px;height:16px;border-radius:4px;display:inline-flex;align-items:center;justify-content:center;flex:none;box-sizing:border-box}
.sq.lg{width:24px;height:24px;border-radius:6px}
.sq.ok{background:#16A34A}.sq.no{background:#DC2626}.sq.run{background:#2563EB;box-shadow:0 0 0 3px #BFDBFE}
.sq.todo{background:#fff;border:1.5px dashed #9CA3AF}
.sq svg{width:10px;height:10px}.sq.lg svg{width:14px;height:14px}
.sq .pulse{width:6px;height:6px;border-radius:50%;background:#fff;display:block;animation:sqp 1.2s ease-in-out infinite}
.sq.lg .pulse{width:8px;height:8px}
@keyframes sqp{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.sq .pulse{animation:none}}
.sqkey{display:flex;gap:12px;flex-wrap:wrap;font-size:12.5px;color:#374151}
.sqkey>span{display:flex;align-items:center;gap:6px}
#batchBox{display:none;flex-direction:column;gap:10px;margin:0 12px 10px;padding:12px;border-radius:12px;background:#fff;border:1px solid #E5E7EB}
#batchBox .bh{display:flex;align-items:baseline;gap:8px}
#batchBox .bh b{font-size:15px;color:var(--ink);flex:1}
#batchBox .bh span{font-size:13px;color:#4B5563;white-space:nowrap}
#batchBox .note{font-size:13px;color:#92400E;background:#FEF3C7;border-radius:8px;padding:6px 10px}
#batchBox .acts{display:flex;gap:8px}
#batchBox .acts button{height:38px;padding:0 14px;border-radius:8px;border:1px solid #D1D5DB;background:#fff;color:#111827;font:600 13.5px Inter,sans-serif;cursor:pointer}
#batchBox .acts button.lnk{border:0;background:none;color:#1D4ED8;padding:0 4px}
#results{display:flex;flex-direction:column;gap:14px;padding:14px 16px 20px}
#results .rempty{color:#4B5563;font-size:14px;padding:20px 0;line-height:1.5}
#results .grp{display:flex;flex-direction:column;gap:2px}
#results .gh{display:flex;flex-direction:column;gap:6px;padding:2px 2px 8px;border-bottom:1px solid #E5E7EB}
#results .gh .t{font-size:14px;font-weight:600;color:var(--ink);overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
#results .gh .m{font-size:12.5px;color:#4B5563;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
#results .gh .m img{width:14px;height:14px}
#results .gh .m b{color:var(--ink)}
#results .rrow{display:grid;grid-template-columns:16px minmax(0,1fr) auto auto 12px;gap:10px;align-items:center;padding:9px 6px;border-radius:8px;font:13.5px Inter,sans-serif;color:#111827;border:0;background:transparent;text-align:left;width:100%;cursor:pointer}
#results .rrow:hover{background:#F3F4F6}
#results .rrow .acts{grid-column:2 / -1;display:flex;gap:8px;align-items:center;margin-top:2px}
#results .vbtn{height:34px;padding:0 12px;border-radius:8px;border:1px solid #D1D5DB;background:#fff;color:#111827;font:600 13px Inter,sans-serif;display:inline-flex;align-items:center;gap:6px;cursor:pointer;text-decoration:none}
#results .vbtn:hover{background:#F3F4F6}
#results .vnote{font-size:12.5px;color:#4B5563}
#vidWrap{position:fixed;inset:0;z-index:90;background:rgba(17,24,39,.6);display:none;align-items:center;justify-content:center;padding:20px}
#vidWrap.open{display:flex}
#vidWrap .bx{width:min(1180px,100%);background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 24px 60px -12px rgba(17,24,39,.5)}
#vidWrap .hd{display:flex;align-items:center;gap:10px;padding:12px 14px;font:600 15px Inter,sans-serif;color:#111827}
#vidWrap .hd span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#vidWrap .hd button{width:38px;height:38px;border-radius:9px;border:1px solid #D1D5DB;background:#fff;cursor:pointer;font-size:18px}
#vidWrap video{display:block;width:100%;aspect-ratio:16/9;background:#111827}
#results .rrow:focus-visible{outline:2px solid #2563EB;outline-offset:1px}
#results .rrow .st{color:#4B5563;font-size:12.5px;white-space:nowrap}
#results .rrow .n{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#results .rrow .why{grid-column:2 / -1;font-size:12.5px;color:#4B5563;line-height:1.4;margin-top:-4px}
#results .rrow .why.bad{color:#991B1B}
#results .rrow .why .err{display:block;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;color:#991B1B;background:#FEF2F2;border-radius:6px;padding:4px 6px;margin-top:4px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:4.4em;overflow:hidden}
#results .rrow .mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12.5px;color:#374151;white-space:nowrap}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const CHECK = '<svg viewBox="0 0 16 16" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const CROSS = '<svg viewBox="0 0 16 16" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>';
const PLAY = '<svg width="11" height="11" viewBox="0 0 14 14" fill="#111827" aria-hidden="true"><path d="M3 1.5 L12.5 7 L3 12.5 Z"/></svg>';
// A run's video, in a player over the page.
document.body.insertAdjacentHTML('beforeend', '<div id="vidWrap" role="dialog" aria-modal="true" aria-label="Run video"><div class="bx"><div class="hd"><span id="vidTitle"></span><button id="vidX" aria-label="Close video">×</button></div><video id="vid" controls playsinline></video></div></div>');
function openVideo(src, title) {
  const w = document.getElementById('vidWrap'), v = document.getElementById('vid');
  document.getElementById('vidTitle').textContent = title || 'Run video';
  v.src = src; w.classList.add('open'); v.play().catch(() => {});
  document.getElementById('vidX').focus();
}
function closeVideo() { const v = document.getElementById('vid'); v.pause(); v.removeAttribute('src'); v.load(); document.getElementById('vidWrap').classList.remove('open'); }
document.getElementById('vidX').onclick = closeVideo;
document.getElementById('vidWrap').addEventListener('click', (e) => { if (e.target.id === 'vidWrap') closeVideo(); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.getElementById('vidWrap').classList.contains('open')) closeVideo(); });
const CHEV = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#6B7280" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M4.5 2.5L8 6l-3.5 3.5"/></svg>';
const LABEL = {finished: 'Succeeded', error: 'Error', stopped: 'Stopped', time_limit: 'Time limit', agent_error: 'Error'};
const fmt = (x) => { x = Math.max(0, x || 0); return `${Math.floor(x / 60)}:${String(Math.floor(x % 60)).padStart(2, '0')}`; };
const usd = (x) => x == null ? '' : '$' + (x < 0.1 && x > 0 ? x.toFixed(3) : x.toFixed(2));

// One square: kind is ok, no, run or todo.
function sq(kind, big, title) {
  const inner = kind === 'ok' ? CHECK : kind === 'no' ? CROSS : kind === 'run' ? '<i class="pulse"></i>' : '';
  return `<span class="sq ${kind}${big ? ' lg' : ''}" role="img" aria-label="${title}" title="${title}">${inner}</span>`;
}
// A batch's squares: finished runs, the one going now, the rest not started.
function squares(b, running, big) {
  const out = [];
  b.results.forEach((r, i) => out.push(sq(r === 'succeeded' ? 'ok' : 'no', big, `Run ${i + 1}: ${r}`)));
  if (!b.finished) {
    const now = b.results.length;
    if (now < b.total) out.push(sq(running ? 'run' : 'todo', big, `Run ${now + 1}: ${running ? 'running' : 'waiting'}`));
    for (let i = now + 1; i < b.total; i++) out.push(sq('todo', big, `Run ${i + 1}: not started`));
  }
  return `<div class="sqs">${out.join('')}</div>`;
}
window.runSquares = squares;
const KEY = `<div class="sqkey">${[['todo', 'Not started'], ['run', 'Running'], ['ok', 'Succeeded'], ['no', 'Failed']].map(([k, t]) => `<span>${sq(k, false, t)}${t}</span>`).join('')}</div>`;

// ------------------------------------------------------------- the Runs stepper
S.runsBy = S.runsBy || {};
window.runsFor = (uid) => Math.max(1, Math.min(MAX, S.runsBy[uid] || 1));
function drawStepper() {
  const uid = S.scene && S.scene.active, n = window.runsFor(uid);
  $('runsN').textContent = n;
  $('runsMinus').disabled = n <= 1;
  $('runsPlus').disabled = n >= MAX;
  $('runsPlus').title = n >= MAX ? `${MAX} runs at most` : '';
  const btn = $('startBtn'), label = n > 1 ? `Run ${n} times` : 'Run task';
  const tn = [...btn.childNodes].find(x => x.nodeType === 3);
  if (tn && tn.textContent !== label) tn.textContent = label;
}
const step = (d) => { const uid = S.scene && S.scene.active; if (!uid) return; S.runsBy[uid] = Math.max(1, Math.min(MAX, window.runsFor(uid) + d)); drawStepper(); };
$('runsMinus').onclick = () => step(-1);
$('runsPlus').onclick = () => step(1);

// ------------------------------------------------------- the batch, in the chat
$('runbar').insertAdjacentHTML('beforebegin', '<div id="batchBox" aria-live="polite"></div>');
const box = $('batchBox');
function drawBatch() {
  const sc = S.scene, uid = sc && sc.active, run = (sc && sc.mode === 'free' && (sc.runs || {})[uid]) || {}, b = run.batch;
  if (!b || b.total <= 1 || S.sideTab !== 'chat') {
    box.style.display = 'none'; box.dataset.key = '';
    if ($('stopBtn').textContent !== 'Stop') $('stopBtn').textContent = 'Stop';
    return;
  }
  const running = !!run.active, ok = b.results.filter(r => r === 'succeeded').length, bad = b.results.length - ok;
  const key = JSON.stringify([uid, b, running]);
  box.style.display = 'flex';
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  const k = Math.min(b.total, b.results.length + (b.finished ? 0 : 1));
  const head = b.finished ? `Done: ${ok} of ${b.results.length} succeeded` : `Run ${k} of ${b.total}`;
  const tail = b.finished ? (b.results.length < b.total ? `${b.total - b.results.length} not run` : '') : `${ok} succeeded · ${bad} failed`;
  box.innerHTML = `<div class="bh"><b>${head}</b><span>${tail}</span></div>${squares(b, running, true)}${b.finished ? '' : KEY}
    ${b.note ? `<div class="note">${esc(b.note)}</div>` : ''}
    <div class="acts">${b.finished ? '<button class="lnk" id="bResults">See every run in Results</button>'
      : b.stop_after ? '<span class="small" style="align-self:center">Stopping after this run</span>' : '<button id="bAfter">Stop after this run</button>'}</div>`;
  const a = $('bAfter'); if (a) a.onclick = async () => { await api('/pg/stop', {station: uid, after_this: true}); };
  const rr = $('bResults'); if (rr) rr.onclick = () => $('tabResults').click();
  $('stopBtn').textContent = b.finished ? 'Stop' : 'Stop all';
}

// ------------------------------------------------------------- the Results tab
const R = {uid: null, data: null, at: 0, key: ''};
async function pollResults(force) {
  const uid = S.scene && S.scene.active;
  if (!uid || S.sideTab !== 'results') return;
  if (!force && R.uid === uid && Date.now() - R.at < 3000) return;
  R.uid = uid; R.at = Date.now();
  const sid = SID;
  const r = await fetch(U('/pg/results') + '?uid=' + encodeURIComponent(uid), {headers: {'X-Browser-Id': BID}}).then(x => x.json()).catch(() => null);
  if (sid !== SID || !r || !r.ok || R.uid !== uid) return;
  R.data = r; drawResults();
}
window.pollResults = pollResults;
function drawResults() {
  const r = R.data, el = $('results');
  const key = JSON.stringify([R.uid, r]);
  if (key === R.key) return;
  R.key = key;
  if (!r.runs.length) { el.innerHTML = '<div class="rempty">No finished runs yet. Give this robot a task, and every run it finishes shows up here.</div>'; return; }
  // Runs of one batch together, newest batch first.
  const groups = [];
  for (const x of r.runs) {
    const g = groups[groups.length - 1];
    if (g && x.batch && g.batch === x.batch) g.runs.push(x); else groups.push({batch: x.batch, runs: [x]});
  }
  const live = r.batch && !r.batch.finished ? r.batch : null;
  el.innerHTML = groups.map(g => {
    const x0 = g.runs[0], of = x0.of || 1, ok = g.runs.filter(x => x.ok).length;
    const logo = LOGOS[x0.provider] || LOGOS.anthropic;
    const cost = g.runs.reduce((a, x) => a + (x.cost_usd || 0), 0), anyCost = g.runs.some(x => x.cost_usd != null);
    const when = x0.started ? new Date(x0.started * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}) : '';
    const going = live && live.id === g.batch;
    const sqs = of > 1 ? (going ? squares(live, ((S.scene.runs || {})[R.uid] || {}).active, false)
      : `<div class="sqs">${[...g.runs].reverse().map(x => sq(x.ok ? 'ok' : 'no', false, `Run ${x.index}: ${LABEL[x.status] || x.status}`)).join('')}</div>`) : '';
    const head = `<div class="gh"><span class="t">${esc(x0.task || '')}</span><span class="m"><img src="${logo}" alt="">${esc(x0.model_label || '')}${when ? ` · ${when}` : ''}${of > 1 ? ` · <b>${ok} of ${g.runs.length} succeeded</b>${going ? ' so far' : ''}` : ''}${anyCost ? ` · ${usd(cost)}` : ''}</span>${sqs}</div>`;
    const rows = g.runs.map(x => {
      const lab = LABEL[x.status] || x.status, why = x.reason || lab;
      const err = x.status === 'error' && x.error_text ? `<span class="err">${esc(String(x.error_text).split('\n').slice(-2).join('\n').slice(0, 240))}</span>` : '';
      const said = x.status !== 'finished' && x.ai_done != null ? (x.ai_done ? ' · The AI had said DONE' : '') : '';
      const vid = x.video_url ? (x.video_url.startsWith('/') ? `<button class="vbtn" data-video="${esc(x.video_url)}" data-title="${esc((of > 1 ? `Run ${x.index} of ${of}` : 'Run') + ' · ' + (x.task || ''))}">${PLAY}Watch video</button>`
          : `<a class="vbtn" href="${esc(x.video_url)}" target="_blank" rel="noopener">${PLAY}Watch video ↗</a>`)
        : x.video === 'making' ? '<span class="vnote">Video is being made…</span>' : x.video === 'failed' ? '<span class="vnote">No video for this run</span>' : '';
      return `<div class="rrow" role="button" tabindex="0" data-run="${esc(x.run_id)}" aria-label="Open run ${of > 1 ? `${x.index} of ${of}` : ''}: ${esc(why)}">${sq(x.ok ? 'ok' : 'no', false, why)}<span class="n">${of > 1 ? `Run ${x.index} of ${of}` : 'Run'} <span class="st">· ${esc(lab)}</span></span><span class="mono">${fmt(x.seconds)}</span><span class="mono">${x.cost_usd != null ? usd(x.cost_usd) : ''}</span>${CHEV}<span class="why${x.ok ? '' : ' bad'}">${esc(why)}${said}${err}</span>${vid ? `<span class="acts">${vid}</span>` : ''}</div>`;
    }).join('');
    return `<div class="grp">${head}${rows}</div>`;
  }).join('');
  el.querySelectorAll('[data-run]').forEach(b => {
    b.onclick = (e) => { if (!e.target.closest('.vbtn')) window.openRunTimeline(R.uid, b.dataset.run); };
    b.onkeydown = (e) => { if ((e.key === 'Enter' || e.key === ' ') && e.target === b) { e.preventDefault(); window.openRunTimeline(R.uid, b.dataset.run); } };
  });
  el.querySelectorAll('button[data-video]').forEach(b => b.onclick = (e) => { e.stopPropagation(); openVideo(U(b.dataset.video), b.dataset.title); });
}

setInterval(() => {
  if (!S.scene) return;
  drawStepper(); drawBatch();
  if (S.sideTab === 'results') pollResults(false);
}, 300);
})();
