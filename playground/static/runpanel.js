// The run's cost and timeline: a tag over each working robot (model, time, money, a thick bar of
// what it has been doing) and, on click, the run popup (result, spend, rows of what the AI and the
// robot did over time, snapshots, and a playhead that shows all three cameras at any moment).
// Data: /pg/run_timeline?uid=<robot> (wetlabsim/timeline.py); pictures: the robot's
// camera/<name>.jpg?t=<robot clock>. Loaded after the page's own script (uses S, SID, U, LOGOS, esc).
(() => {
const COLORS = {thinking: '#1D4ED8', reading: '#A16207', looking: '#6B7280', writing: '#7C3AED', running: '#0F766E',
                moving: '#F59E0B', gripper: '#DB2777', errors: '#DC2626'};
const DOING = {thinking: 'Thinking', reading: 'Reading docs', looking: 'Looking', writing: 'Writing code',
               running: 'Running code', moving: 'Moving', gripper: 'Gripper'};
const PRIORITY = ['moving', 'gripper', 'running', 'writing', 'looking', 'reading', 'thinking'];
const STATUS = {running: 'Live', finished: 'Done', time_limit: 'Time limit', error: 'Error', stopped: 'Stopped', agent_error: 'Error'};
const css = `
#rtags{position:absolute;inset:0;pointer-events:none;z-index:5}
.rtg{position:absolute;display:flex;flex-direction:column;align-items:flex-start;pointer-events:auto;cursor:pointer;border:0;padding:0;background:none;text-align:left;
  transform:translate(-50%,-100%) scale(var(--s,1));transform-origin:50% 100%;filter:drop-shadow(0 0 .6px rgba(17,24,39,.45)) drop-shadow(0 4px 10px rgba(17,24,39,.14))}
.rtg:active{transform:translate(-50%,-100%) scale(calc(var(--s,1) * .97))}
.rtg .ftab{display:flex;align-items:center;gap:6px;height:30px;padding:2px 10px 4px 8px;margin-bottom:-4px;background:#fff;border-radius:8px 8px 0 0;font:600 12.5px Inter,sans-serif;color:#111827;white-space:nowrap;position:relative;z-index:1}
.rtg .ftab:after{content:"";position:absolute;right:-10px;bottom:0;width:10px;height:14px;background:radial-gradient(circle at 100% 0,transparent 9.5px,#fff 10px) 0 0/10px 10px no-repeat,linear-gradient(#fff,#fff) 0 10px/10px 4px no-repeat}
.rtg .ftab img{width:14px;height:14px}
.rtg .tbody{background:#fff;border-radius:0 10px 10px 10px;padding:8px 12px 10px;display:flex;flex-direction:column;gap:7px;min-width:220px}
.rtg .r{display:flex;align-items:center;gap:8px;font:14px Inter,sans-serif;color:#111827}
.rtg .r b{font:600 15px 'JetBrains Mono',monospace}
.rtg .mut{color:#4B5563;font:500 13px 'JetBrains Mono',monospace}
.rtg .now{font:600 12.5px Inter,sans-serif;color:#374151}
.rtg .dot{width:9px;height:9px;border-radius:50%;flex:none}
.rtg .thick{height:10px;border-radius:5px;background:#E5E7EB;display:flex;overflow:hidden}
.rtg .thick i{height:100%}
.rtg .pointer{width:0;height:0;border:7px solid transparent;border-bottom:0;border-top-color:#fff;align-self:center;margin-top:-1px}
.rtg .ttl{font:650 14px Inter,sans-serif;color:#111827;max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rtg .badge{font:600 12px Inter,sans-serif;padding:1px 7px;border-radius:6px;background:#DCFCE7;color:#166534}
.rtg .badge.bad{background:#FEE2E2;color:#991B1B}.rtg .badge.mid{background:#FEF3C7;color:#92400E}
.rtg:focus-visible{outline:2px solid #2563EB;outline-offset:3px;border-radius:10px}
#runpop{position:fixed;inset:0;z-index:60;display:none;align-items:center;justify-content:center;background:rgba(17,24,39,.28)}
#runpop.open{display:flex}
#runpop .card{width:min(1440px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 64px rgba(17,24,39,.28);padding:18px 22px 20px;
  font:14px/1.5 Inter,system-ui,sans-serif;color:#111827;opacity:0;transform:scale(.97);transition:opacity 160ms ease-out,transform 160ms ease-out}
#runpop.open .card{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){#runpop .card{transform:none}}
#runpop .mono{font-family:'JetBrains Mono',monospace;font-variant-numeric:tabular-nums}
#runpop .hd{display:flex;align-items:center;gap:10px}
#runpop .hd img{width:20px;height:20px}
#runpop .hd .nm{font-size:18px;font-weight:700}
#runpop .st{font-size:12px;font-weight:600;padding:2px 8px;border-radius:6px;background:#DCFCE7;color:#166534}
#runpop .st.live{background:#DBEAFE;color:#1E40AF}#runpop .st.bad{background:#FEE2E2;color:#991B1B}#runpop .st.mid{background:#FEF3C7;color:#92400E}
#runpop .sub{color:#374151;font-size:13.5px;margin-left:6px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#runpop .x{margin-left:auto;width:40px;height:40px;border-radius:10px;border:1px solid #D1D5DB;background:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none;transition:transform 120ms ease-out}
#runpop .x:active{transform:scale(.95)}
#runpop .ban{margin-top:14px;display:flex;flex-wrap:wrap;gap:6px 0;align-items:center;padding:10px 14px;border-radius:12px;background:#F0FDF4;box-shadow:0 0 0 1px #BBF7D0 inset;color:#14532D;font-weight:500}
#runpop .ban.mid{background:#FFFBEB;box-shadow:0 0 0 1px #FDE68A inset;color:#78350F}
#runpop .ban.bad{background:#FEF2F2;box-shadow:0 0 0 1px #FECACA inset;color:#7F1D1D}
#runpop .ban.live{background:#EFF6FF;box-shadow:0 0 0 1px #BFDBFE inset;color:#1E3A8A}
#runpop .ban span{display:flex;align-items:center;gap:7px;padding:0 14px;border-left:1px solid rgba(17,24,39,.12)}
#runpop .ban span:first-child{padding-left:2px;border-left:0;font-weight:700;font-size:15.5px}
#runpop .g8{display:grid;grid-template-columns:132px 1fr 104px;column-gap:12px;row-gap:5px;align-items:center;position:relative;margin-top:14px}
#runpop .lb{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600;white-space:nowrap}
#runpop .lb i{width:12px;height:12px;border-radius:3px;flex:none}
#runpop .tt{font:500 12.5px 'JetBrains Mono',monospace;text-align:right;white-space:nowrap}
#runpop .r8{position:relative;height:28px;background:#F4F5F7;border-radius:7px}
#runpop .e8{position:absolute;top:3px;bottom:3px;border-radius:5px;color:#fff;font:600 12px Inter,sans-serif;display:flex;align-items:center;padding:0 6px;overflow:hidden;white-space:nowrap;min-width:3px}
#runpop .e8.dark{color:#111827}
#runpop .wait{position:absolute;top:3px;bottom:3px;border-radius:5px;background:repeating-linear-gradient(135deg,#E5E7EB 0 6px,#F9FAFB 6px 12px);box-shadow:0 0 0 1px #9CA3AF inset;color:#374151;font:600 12px Inter,sans-serif;display:flex;align-items:center;padding:0 6px;overflow:hidden;white-space:nowrap}
#runpop .err{position:absolute;top:50%;transform:translate(-50%,-50%);display:flex;align-items:center;gap:8px}
#runpop .err b{width:14px;height:14px;background:#DC2626;transform:rotate(45deg);border-radius:2px;flex:none}
#runpop .err span{font:600 12.5px Inter,sans-serif;color:#991B1B;background:#FEE2E2;padding:1px 6px;border-radius:5px;white-space:nowrap}
#runpop .flags{position:relative;height:28px}
#runpop .fl{position:absolute;bottom:0;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center}
#runpop .fl span{font:600 12.5px Inter,sans-serif;background:#fff;border:1px solid #D1D5DB;border-radius:999px;padding:0 9px;white-space:nowrap}
#runpop .fl.error span{color:#B91C1C;border-color:#FCA5A5;background:#FEF2F2}
#runpop .fl i{width:1px;height:6px;background:#9CA3AF}
#runpop .strip{position:relative;height:84px;border-radius:7px;overflow:hidden;background:#E5E7EB;display:flex;gap:2px}
#runpop .strip img{height:100%;flex:1;min-width:0;object-fit:cover;background:#E5E7EB;cursor:pointer}
#runpop .ruler{position:relative;height:18px;font:500 12px 'JetBrains Mono',monospace;color:#4B5563}
#runpop .ruler span{position:absolute;transform:translateX(-50%)}
#runpop .ruler span:first-child{transform:none}#runpop .ruler span:last-child{transform:translateX(-100%)}
#runpop .ph{position:absolute;top:0;bottom:22px;width:2px;background:#111827;pointer-events:none;z-index:3}
#runpop .ph:before{content:"";position:absolute;left:-7px;top:-8px;width:16px;height:16px;border-radius:50%;background:#111827}
#runpop .ph.live{background:#2563EB}#runpop .ph.live:before{background:#2563EB}
#runpop .track{position:absolute;top:0;bottom:22px;cursor:ew-resize;z-index:2}
#runpop .sphead{display:flex;flex-direction:column;line-height:1.15}
#runpop .sphead .cap{font:700 11px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#6B7280}
#runpop .sphead b{font:700 26px 'JetBrains Mono',monospace;margin-top:2px}
#runpop .sphead .tok{font:500 12.5px Inter,sans-serif;color:#6B7280;margin-top:2px}
#runpop .chips{display:flex;flex-wrap:wrap;gap:4px 18px;font:600 13px Inter,sans-serif;color:#374151;margin-bottom:6px}
#runpop .chips span{display:inline-flex;align-items:center;gap:6px}
#runpop .chips i{width:10px;height:10px;border-radius:3px}
#runpop .chips b{font-family:'JetBrains Mono',monospace;color:#111827}
#runpop .spark{position:relative;background:#fff;border-radius:7px;box-shadow:0 0 0 1px #E5E7EB inset;height:48px;overflow:hidden}
#runpop .spark svg{display:block;width:100%;height:100%}
#runpop .spark .tag{position:absolute;top:4px;font:700 12px 'JetBrains Mono',monospace;background:#fff;padding:0 4px;border-radius:4px;box-shadow:0 0 0 1px #E5E7EB;white-space:nowrap}
#runpop .note{font-size:12.5px;color:#4B5563;margin-top:4px}
#runpop .hr{grid-column:1/-1;height:1px;background:#E5E7EB;margin:6px 0 2px}
#runpop .pv{margin-top:14px;display:grid;grid-template-columns:repeat(var(--pics,3),minmax(0,1fr)) minmax(220px,.9fr);gap:12px;background:#F4F5F7;border-radius:12px;padding:12px}
#runpop .pv figure{margin:0}
#runpop .pv img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:8px;background:#E5E7EB;display:block}
#runpop .pv figcaption{font-size:13px;font-weight:600;margin-top:6px}
#runpop .pv .what{display:flex;flex-direction:column;justify-content:center;gap:8px;padding:0 6px;font-size:14px;color:#374151}
#runpop .pv .what b{font:700 24px 'JetBrains Mono',monospace;color:#111827}
@media (max-width:820px){#runpop .pv{grid-template-columns:1fr 1fr}#runpop .g8{grid-template-columns:96px 1fr 64px}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const stage = document.getElementById('stage');
stage.insertAdjacentHTML('beforeend', '<div id="rtags" aria-label="Robots at work"></div>');
document.body.insertAdjacentHTML('beforeend', '<div id="runpop" role="dialog" aria-modal="true" aria-label="Run timeline"><div class="card" id="rpCard"></div></div>');
const tagsEl = document.getElementById('rtags'), pop = document.getElementById('runpop'), card = document.getElementById('rpCard');
const fmt = (x) => { x = Math.max(0, x || 0); return `${Math.floor(x / 60)}:${String(Math.floor(x % 60)).padStart(2, '0')}`; };
const usd = (x) => x == null ? '' : '$' + (x < 0.1 && x > 0 ? x.toFixed(3) : x.toFixed(2));
const ktok = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1000 ? Math.round(n / 1000) + 'k' : String(n || 0);
const robotBase = (uid) => `/s/${SID}/st/${uid}`;
// The popup's pictures: the scene, the overhead camera and the wrist camera, or both wrists
// on a two-arm robot (ALOHA). [img id, camera, caption]
const popCams = (uid) => {
  const two = ((S.scene && S.scene.robots || []).find(r => r.id === uid) || {}).robot === 'aloha';
  return [['rpSide', 'side', 'Scene'], ['rpOver', 'overhead', 'Overhead camera'],
          ...(two ? [['rpWristL', 'left_wrist', 'Left wrist camera'], ['rpWristR', 'right_wrist', 'Right wrist camera']]
                  : [['rpWrist', 'wrist', 'Wrist camera']])];
};
const TL = {};                 // the latest timeline per robot
const fetching = {};

// key: the robot (its latest run), or "<robot>#<run id>" for one of its past runs.
async function loadTimeline(key) {
  if (fetching[key]) return TL[key];
  fetching[key] = true;
  const [uid, run] = key.split('#');
  try {
    const r = await fetch(U('/pg/run_timeline') + '?uid=' + encodeURIComponent(uid) + (run ? '&run=' + encodeURIComponent(run) : ''), {headers: {'X-Browser-Id': BID}});
    const j = await r.json();
    if (j.ok) TL[key] = j;
  } catch (e) { /* the next poll tries again */ } finally { fetching[key] = false; }
  return TL[key];
}

// Where the time went, as one bar: time slices coloured by the busiest thing in each.
function stripSegments(tl, span) {
  const n = 80, out = [];
  const lanes = Object.fromEntries((tl.lanes || []).map(l => [l.id, l.blocks || []]));
  for (let i = 0; i < n; i++) {
    const a = span * i / n, b = span * (i + 1) / n;
    if (a >= tl.duration) break;
    let c = null;
    for (const k of PRIORITY) if ((lanes[k] || []).some(x => x.start < b && x.end > a)) { c = k; break; }
    c = c || 'thinking';
    if (out.length && out[out.length - 1].c === c) out[out.length - 1].w += 1; else out.push({c, w: 1});
  }
  return out.map(s => `<i style="width:${(s.w / n * 100).toFixed(2)}%;background:${COLORS[s.c]}"></i>`).join('');
}

function tagHtml(uid, run, tl) {
  const m = run.model || {}, live = !!run.active;
  const limit = (tl && tl.time_limit) || run.time_limit || 300;
  const secs = live ? (run.elapsed || 0) : (tl ? tl.duration : run.elapsed || 0);
  const cost = run.cost_usd != null ? usd(run.cost_usd) : (tl && tl.cost && tl.cost.known ? usd(tl.cost.usd) : '');
  const money = cost || `${ktok(run.tokens || (tl && tl.cost && tl.cost.tokens) || 0)} tok`;
  const doing = run.doing || ((tl && tl.now || [])[0]);
  const st = run.status, bad = st === 'error', mid = st === 'stopped' || st === 'time_limit';
  const first = live ? `<span class="dot" style="background:${COLORS[doing] || '#9CA3AF'}"></span><span class="now">${DOING[doing] || 'Starting'}</span>`
    : `<span class="badge${bad ? ' bad' : mid ? ' mid' : ''}">${STATUS[st] || 'Done'}</span>`;
  const bar = tl ? stripSegments(tl, live ? Math.max(limit, secs) : Math.max(secs, 1)) : '';
  // Repeat runs (more than one): which run this is, and a square per run.
  const b = run.batch, many = b && b.total > 1 && window.runSquares;
  const k = many ? Math.min(b.total, b.results.length + (b.finished ? 0 : 1)) : 0;
  const batch = many ? `<div class="r" style="font-size:12.5px"><b>${b.finished ? `${b.results.filter(x => x === 'succeeded').length} of ${b.results.length} succeeded` : `Run ${k} of ${b.total}`}</b></div>${window.runSquares(b, live, false)}` : '';
  return `<div class="ftab"><img src="${LOGOS[m.provider] || LOGOS.anthropic}" alt="">${esc(m.label || '')}</div>
    <div class="tbody">${run.title ? `<div class="ttl" title="${esc(run.task || '')}">${esc(run.title)}</div>` : ''}${batch}<div class="r">${first}<span><b>${fmt(secs)}</b>${live && limit ? ` <span class="mut">/ ${fmt(limit)}</span>` : ''}</span><span style="margin-left:auto"><b>${money}</b></span></div>
    <div class="thick" role="img" aria-label="What the robot has been doing over time">${bar}</div></div><div class="pointer"></div>`;
}

let lastPoll = 0;
const TAG_PPM = 240;    // at this zoom (screen pixels per metre) or closer, a tag is full size
function drawTags() {
  const sc = S.scene, V = window.V3;
  const runs = (sc && sc.mode === 'free' && sc.runs) || {};
  const keep = new Set();
  if (V && V.project) {
    for (const rb of sc && sc.robots || []) {
      const run = runs[rb.id];
      if (!run || !run.started || run.queued || !rb.base) continue;
      // Pinned in the world above the robot's middle: it stays with the robot as the camera
      // moves (it never slides to the screen's edge), and shrinks with distance like the robot.
      const p = V.project([rb.base[0], rb.base[1], rb.base[2] + 1.05]);
      if (!p.visible) continue;
      const q = V.project([rb.base[0], rb.base[1], rb.base[2] + 1.55]);
      const ppm = Math.hypot(p.x - q.x, p.y - q.y) / 0.5;      // screen pixels per metre there
      keep.add(rb.id);
      let el = tagsEl.querySelector(`[data-uid="${rb.id}"]`);
      if (!el) {
        el = document.createElement('button'); el.className = 'rtg'; el.dataset.uid = rb.id;
        el.setAttribute('aria-label', `Open ${rb.name}'s run: time, cost and timeline`);
        el.onclick = () => openRun(rb.id);
        tagsEl.appendChild(el);
      }
      const key = JSON.stringify([run.title, run.active, run.status, Math.floor(run.elapsed || 0), run.cost_usd, run.tokens, run.doing, TL[rb.id] && TL[rb.id].duration, run.batch]);
      if (el.dataset.key !== key) { el.dataset.key = key; el.innerHTML = tagHtml(rb.id, run, TL[rb.id]); }
      el.style.left = p.x + 'px'; el.style.top = p.y + 'px';
      el.style.setProperty('--s', Math.min(1, Math.max(0.8, ppm / TAG_PPM)).toFixed(3));
      el.style.zIndex = Math.round(ppm);      // nearer robots' tags on top
    }
  }
  tagsEl.querySelectorAll('.rtg').forEach(el => { if (!keep.has(el.dataset.uid)) el.remove(); });
  // The bars need each working robot's timeline: every 3 s while it runs, once when it ends.
  if (Date.now() - lastPoll > 3000) {
    lastPoll = Date.now();
    for (const uid of keep) {
      const run = runs[uid], tl = TL[uid];
      if (run.active || !tl || tl.live || tl.run_id !== run.run_id) loadTimeline(uid);
    }
  }
  requestAnimationFrame(drawTags);
}
requestAnimationFrame(drawTags);

// ------------------------------------------------------------------ the popup
const P = {uid: null, key: null, t: null, follow: true, timer: null, pics: null};
function openRun(uid, runId) {
  P.uid = uid; P.key = runId ? `${uid}#${runId}` : uid; P.t = null; P.follow = true;
  pop.classList.add('open'); P.opener = document.activeElement;
  card.innerHTML = `<div class="hd"><span class="nm">Loading the run…</span><button class="x" id="rpX" aria-label="Close"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="#111827" stroke-width="2" stroke-linecap="round"><path d="M2 2l10 10M12 2L2 12"/></svg></button></div>`;
  document.getElementById('rpX').onclick = closeRun;
  refreshRun(true);
  clearInterval(P.timer);
  P.timer = setInterval(() => { if (TL[P.key] && TL[P.key].live) refreshRun(); }, 2000);
}
function closeRun() {
  pop.classList.remove('open'); clearInterval(P.timer); P.uid = null; P.key = null;
  if (P.opener && P.opener.focus) P.opener.focus();
}
pop.addEventListener('click', (e) => { if (e.target === pop) closeRun(); });
window.addEventListener('keydown', (e) => {
  if (!P.uid) return;
  if (e.key === 'Escape') closeRun();
  const tl = TL[P.key];
  if (tl && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
    P.follow = false; setPlayhead(Math.min(tl.duration, Math.max(0, (P.t || 0) + (e.key === 'ArrowLeft' ? -1 : 1))));
  }
});
window.openRunTimeline = openRun;

async function refreshRun(first) {
  const tl = await loadTimeline(P.key);
  if (!P.uid) return;
  if (!tl) { if (first) card.querySelector('.nm').textContent = 'This robot has no run yet'; return; }
  const sc = card.scrollTop;
  render(tl);
  card.scrollTop = sc;
}

function lineChart(tl) {
  const s = tl.cost.series || [], known = tl.cost.known, D = Math.max(tl.duration, 0.001);
  const vals = s.map(p => known ? (p[1] || 0) : (p[2] || 0)), top = Math.max(...vals, 1e-9);
  const pts = s.map((p, i) => `${(p[0] / D * 1000).toFixed(1)},${(44 - vals[i] / top * 36).toFixed(1)}`);
  // a step line: the total holds until the next call adds to it
  const step = [];
  pts.forEach((p, i) => { if (i) step.push(`${p.split(',')[0]},${pts[i - 1].split(',')[1]}`); step.push(p); });
  return `<svg viewBox="0 0 1000 48" preserveAspectRatio="none" aria-hidden="true"><polyline points="${step.join(' ')}" fill="none" stroke="#111827" stroke-width="3" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}
function spendAt(tl, t) {
  let u = 0, k = 0;
  for (const p of tl.cost.series || []) { if (p[0] <= t + 1e-6) { u = p[1]; k = p[2]; } }
  return {usd: u, tokens: k};
}

function render(tl) {
  const D = Math.max(tl.duration, 0.001), pct = (x) => (Math.min(Math.max(x / D, 0), 1) * 100).toFixed(3) + '%';
  const st = tl.result.status, live = tl.live;
  const cls = live ? 'live' : st === 'error' || st === 'agent_error' ? 'bad' : (st === 'stopped' || st === 'time_limit' || tl.result.safety_stops) ? 'mid' : '';
  const prov = tl.provider_id || ({Anthropic: 'anthropic', OpenAI: 'openai', Cognition: 'cognition', TypeSafe: 'typesafe'})[tl.provider];
  if (P.t == null || P.follow) P.t = live ? D : Math.min(D, Math.max(0, (tl.flags.find(f => f.kind === 'grip') || {t: D / 2}).t));
  // Result banner: how it ended, whether the AI said it was done, and safety.
  const outcome = live ? 'Running' : ({finished: 'Finished', time_limit: 'Hit the time limit', error: 'Stopped with an error', agent_error: 'Stopped with an error', stopped: 'Stopped by you'})[st] || st;
  const ok = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M3 8.5l3 3 7-7"/></svg>';
  const ban = [`<span>${tl.result.passed === true ? ok + 'Passed' : tl.result.passed === false ? 'Failed' : (!live && st === 'finished' ? ok : '') + outcome}</span>`];
  if (tl.result.passed != null) ban.push(`<span>${outcome}</span>`);
  ban.push(`<span>${tl.result.ai_done_at != null ? ok + `AI said “done” at ${fmt(tl.result.ai_done_at)}` : live ? 'AI hasn’t said it’s done yet' : 'AI never said it was done'}</span>`);
  ban.push(`<span>${tl.result.safety_stops ? `${tl.result.safety_stops} safety stop${tl.result.safety_stops > 1 ? 's' : ''}` : ok + 'No safety stops'}</span>`);
  if (!live && tl.error_text && cls === 'bad') ban.push(`<span>${esc(tl.error_text.split('\n')[0].slice(0, 120))}</span>`);
  // Spend header.
  const ai = tl.lanes.filter(l => 'usd' in l && (l.tokens || l.usd)).sort((a, b) => (b.usd || 0) - (a.usd || 0) || b.tokens - a.tokens);
  const chips = ai.map(l => `<span><i style="background:${COLORS[l.id]}"></i>${l.label} <b>${tl.cost.known ? usd(l.usd) : ktok(l.tokens) + ' tok'}</b></span>`).join('');
  const big = tl.cost.known ? usd(tl.cost.usd || 0) : ktok(tl.cost.tokens) ;
  const sp = spendAt(tl, P.t);
  // Rows.
  const rows = tl.lanes.filter(l => l.id !== 'errors' && l.id !== 'waiting').map(l => {
    const blocks = l.blocks.map(b => {
      const w = (b.end - b.start) / D, show = b.label && w * 1100 > b.label.length * 7.2 + 14;
      return `<div class="e8${l.id === 'moving' ? ' dark' : ''}" style="left:${pct(b.start)};width:calc(${(w * 100).toFixed(3)}% - 2px);background:${COLORS[l.id]}" title="${esc(b.detail || b.label || l.label)}">${show ? esc(b.label) : ''}</div>`;
    }).join('');
    const right = l.seconds ? fmt(l.seconds) : '';
    return `<span class="lb"><i style="background:${COLORS[l.id]}"></i>${l.label}</span><div class="r8">${blocks}</div><span class="tt">${right}</span>`;
  }).join('');
  const wl = tl.lanes.find(l => l.id === 'waiting'), el = tl.lanes.find(l => l.id === 'errors');
  const waitRow = `<span class="lb"><i style="background:repeating-linear-gradient(135deg,#6B7280 0 3px,#F3F4F6 3px 6px)"></i>Waiting on AI</span><div class="r8">${wl.blocks.map(b => {
      const w = (b.end - b.start) / D;
      return `<div class="wait" style="left:${pct(b.start)};width:calc(${(w * 100).toFixed(3)}% - 2px)">${w * 1100 > 170 ? 'Robot still, AI working' : ''}</div>`; }).join('')}</div><span class="tt">${fmt(wl.seconds)} · ${Math.round(wl.share * 100)}%</span>`;
  const errRow = `<span class="lb"><i style="background:#DC2626;transform:rotate(45deg);width:10px;height:10px;margin:0 1px"></i>Errors</span><div class="r8" style="${el.count ? 'background:#FEF2F2' : ''}">${el.points.map(p => `<div class="err" style="left:${pct(p.t)}"><b></b>${el.count <= 3 ? `<span>${esc(p.label)}</span>` : ''}</div>`).join('')}</div><span class="tt" style="color:${el.count ? '#991B1B' : '#111827'}">${el.count}</span>`;
  const flags = tl.flags.map(f => `<div class="fl ${f.kind}" style="left:${pct(f.t)}"><span>${esc(f.label)}</span><i></i></div>`).join('');
  const nSnap = 7, snaps = Array.from({length: nSnap}, (_, i) => (i + 0.5) * D / nSnap);
  const base = robotBase(tl.uid), t0 = tl.sim_start;
  const snapImgs = snaps.map(t => `<img src="${base}/camera/side.jpg?t=${(t0 + t).toFixed(2)}" alt="The scene at ${fmt(t)}" data-t="${t}" loading="lazy">`).join('');
  const ticks = [0, .2, .4, .6, .8, 1].filter((f, i, a) => i === 0 || fmt(f * D) !== fmt(a[i - 1] * D)).map(f => `<span style="left:${f * 100}%">${fmt(f * D)}</span>`).join('');   // a short run: no repeated labels
  card.innerHTML = `
    <div class="hd"><img src="${LOGOS[prov] || LOGOS.anthropic}" alt=""><span class="nm">${esc(tl.model_label || tl.model)}</span>
      <span class="st ${cls}">${live ? 'Live' : STATUS[st] || 'Done'}</span>
      <span class="sub">${esc((S.scene.robots.find(r => r.id === tl.uid) || {}).name || '')} · ${esc(tl.task)} · <b class="mono">${fmt(D)}</b></span>
      <button class="x" id="rpX" aria-label="Close"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="#111827" stroke-width="2" stroke-linecap="round"><path d="M2 2l10 10M12 2L2 12"/></svg></button></div>
    <div class="ban ${cls}">${ban.join('')}</div>
    <div class="g8" id="rpGrid">
      <div class="sphead"><span class="cap">Spend</span><b>${big}</b><span class="tok">${tl.cost.known ? ktok(tl.cost.tokens) + ' tokens' : 'tokens'}</span></div>
      <div><div class="chips">${chips || '<span>No AI calls yet</span>'}</div>
        <div class="spark">${lineChart(tl)}<span class="tag" id="rpSpTag"></span></div>
        ${tl.cost.known ? '' : `<div class="note">${esc(tl.cost.why_unknown || 'Cost not reported')}, so this shows tokens.</div>`}</div><span></span>
      <div class="hr"></div>
      <span></span><div class="flags">${flags}</div><span></span>
      <span class="lb"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#374151" stroke-width="1.6" aria-hidden="true"><rect x="1.5" y="3" width="13" height="10" rx="2"/><circle cx="8" cy="8" r="2.5"/></svg>Snapshots</span><div class="strip">${snapImgs}</div><span></span>
      ${rows}${waitRow}${errRow}
      <span></span><div class="ruler">${ticks}</div><span></span>
      <div class="track" id="rpTrack"></div><div class="ph${live && P.follow ? ' live' : ''}" id="rpPh"></div>
    </div>
    <div class="pv" style="--pics:${popCams(tl.uid).length}"><figure><img id="rpSide" alt="The scene at the playhead"><figcaption>Scene</figcaption></figure>
      <figure><img id="rpOver" alt="The overhead camera at the playhead"><figcaption>Overhead camera (AI sees)</figcaption></figure>
      ${popCams(tl.uid).slice(2).map(([id, , cap]) => `<figure><img id="${id}" alt="The ${cap.toLowerCase()} at the playhead"><figcaption>${cap} (AI sees)</figcaption></figure>`).join('')}
      <div class="what"><b id="rpT"></b><span id="rpWhat"></span><span id="rpSpent" class="mono"></span></div></div>`;
  document.getElementById('rpX').onclick = closeRun;
  card.querySelectorAll('.strip img').forEach(im => im.onclick = () => { P.follow = false; setPlayhead(+im.dataset.t); });
  // The track over the rows: where the playhead can be dragged.
  const grid = document.getElementById('rpGrid'), track = document.getElementById('rpTrack');
  const rowEl = grid.querySelector('.r8');
  const place = () => {
    const g = grid.getBoundingClientRect(), r = rowEl.getBoundingClientRect();
    const top = grid.querySelector('.flags').getBoundingClientRect().top - g.top;
    track.style.left = (r.left - g.left) + 'px'; track.style.width = r.width + 'px'; track.style.top = top + 'px';
    document.getElementById('rpPh').style.top = top + 'px';
    P.geo = {x: r.left - g.left, w: r.width};
  };
  place();
  const drag = (e) => { const r = track.getBoundingClientRect(); P.follow = false; setPlayhead((e.clientX - r.left) / r.width * D); };
  track.onpointerdown = (e) => { track.setPointerCapture(e.pointerId); drag(e); track.onpointermove = drag; };
  track.onpointerup = () => { track.onpointermove = null; };
  setPlayhead(P.t, true);
}

function setPlayhead(t, quick) {
  const tl = TL[P.key]; if (!tl || !P.geo) return;
  const D = Math.max(tl.duration, 0.001);
  P.t = Math.min(Math.max(t, 0), D);
  const ph = document.getElementById('rpPh');
  ph.style.left = (P.geo.x + P.t / D * P.geo.w - 1) + 'px';
  ph.classList.toggle('live', tl.live && P.follow);
  const sp = spendAt(tl, P.t), tag = document.getElementById('rpSpTag');
  tag.textContent = `${tl.cost.known ? usd(sp.usd || 0) : ktok(sp.tokens) + ' tok'} at ${fmt(P.t)}`;
  tag.style.left = `min(calc(${(P.t / D * 100).toFixed(2)}% + 8px), calc(100% - 130px))`;
  document.getElementById('rpT').textContent = fmt(P.t);
  // What was going on: the rows busy at t, and what the AI last said or thought.
  const busy = tl.lanes.filter(l => (l.blocks || []).some(b => b.start <= P.t && b.end >= P.t) && DOING[l.id]).map(l => DOING[l.id]);
  const note = [...tl.notes].reverse().find(n => n.t <= P.t + 0.01);
  document.getElementById('rpWhat').textContent = (busy.length ? busy.join(' + ') + '. ' : 'Waiting. ') + (note ? `Last from the AI: “${note.text}”` : '');
  document.getElementById('rpSpent').textContent = tl.cost.known ? `Spent so far ${usd(sp.usd || 0)}` : `${ktok(sp.tokens)} tokens so far`;
  // The three pictures at t (after a short pause while dragging).
  clearTimeout(P.pics);
  P.pics = setTimeout(() => {
    const base = robotBase(tl.uid), at = (tl.sim_start + P.t).toFixed(2);
    for (const [id, cam] of popCams(tl.uid)) {
      const im = document.getElementById(id); if (im) im.src = `${base}/camera/${cam}.jpg?t=${at}`;
    }
  }, quick ? 0 : 120);
}
window.addEventListener('resize', () => { if (P.key && TL[P.key]) render(TL[P.key]); });
})();
