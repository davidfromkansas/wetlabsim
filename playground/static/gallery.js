// Gallery: a live view of every robot in the session, in a grid over the scene, whether it is
// working on a task or not. Each tile is the robot's "side" camera (its station's audience
// camera, the one made for people watching: the robot and its table from the front), with the
// robot's name and type, Running or Idle, and its current task's short name when it has one
// (after a run: its last task, dimmed).
(() => {
const css = `
#galBtn{position:absolute;right:14px;top:12px;z-index:6}
@container (max-width:1060px){#galBtn{top:66px}}
body:not(.freeplay) #galBtn{display:none}
#gal{position:absolute;inset:0;z-index:30;background:#0B0D12;display:none;flex-direction:column;border-radius:inherit;overflow:hidden}
#gal.open{display:flex;animation:galIn 180ms cubic-bezier(.23,1,.32,1)}
@keyframes galIn{from{opacity:0;transform:scale(.985)}}
#gal .gh{display:flex;align-items:center;gap:10px;padding:14px 16px 10px;color:#F9FAFB;flex:none}
#gal .gh b{font:650 15px Inter,sans-serif}
#gal .gh .n{font:500 12.5px Inter,sans-serif;color:#9CA3AF}
#gal .gx{margin-left:auto;width:34px;height:34px;border-radius:9px;border:0;background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;cursor:pointer}
#gal .gx:hover{background:rgba(255,255,255,.16)}
#gal .gg{flex:1;min-height:0;overflow:auto;padding:4px 16px 16px;display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));align-content:start}
#gal .gt{position:relative;aspect-ratio:16/10;border-radius:12px;overflow:hidden;background:#1F2937;box-shadow:0 0 0 1px rgba(255,255,255,.06)}
#gal .gt img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
#gal .gt .ld{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:500 12px Inter,sans-serif;color:#6B7280}
#gal .gt .st{position:absolute;left:10px;top:10px;display:flex;align-items:center;gap:6px;padding:4px 9px;border-radius:999px;background:rgba(17,24,39,.72);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);font:600 11.5px Inter,sans-serif;color:#E5E7EB}
#gal .gt .st i{width:7px;height:7px;border-radius:50%;background:#9CA3AF}
#gal .gt .st.run{color:#fff}#gal .gt .st.run i{background:#22C55E;box-shadow:0 0 0 3px rgba(34,197,94,.25)}
#gal .gt .st .t{font-weight:500;color:#9CA3AF;font-variant-numeric:tabular-nums}
#gal .gt .info{position:absolute;left:0;right:0;bottom:0;padding:26px 12px 10px;background:linear-gradient(transparent,rgba(0,0,0,.78));color:#fff}
#gal .gt .info b{display:block;font:650 13.5px Inter,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#gal .gt .info .ty{font:500 11.5px Inter,sans-serif;color:#D1D5DB}
#gal .gt .info .tk{margin-top:4px;font:12px/1.4 Inter,sans-serif;color:#F3F4F6;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
#gal .gt .info .tk.none{color:#9CA3AF}
#gal .gempty{grid-column:1/-1;padding:60px 0;text-align:center;font:14px Inter,sans-serif;color:#9CA3AF}
@media (max-width:700px){#gal .gg{grid-template-columns:1fr}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const stage = document.getElementById('stage');
const TV = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="7" width="19" height="13" rx="2.5"/><path d="M8 3l4 4 4-4"/></svg>';
const XI = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#E5E7EB" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
stage.insertAdjacentHTML('beforeend', `<button class="fbtn" id="galBtn" aria-haspopup="dialog" aria-expanded="false">${TV}Gallery</button>`
  + `<div id="gal" role="dialog" aria-label="Gallery: every robot, live"><div class="gh"><b>Gallery</b><span class="n" id="galN"></span><button class="gx" id="galX" aria-label="Close gallery">${XI}</button></div><div class="gg" id="galG"></div></div>`);
const btn = document.getElementById('galBtn'), gal = document.getElementById('gal'), grid = document.getElementById('galG');
const G = {open: false, key: '', seen: {}, busy: 0};
const e = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const robots = () => (S.scene && S.scene.mode === 'free' ? S.scene.robots || [] : []);
const mmss = (s) => { s = Math.max(0, Math.floor(+s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };

function status(r) {
  const run = ((S.scene && S.scene.runs) || {})[r.id] || {};
  // The task's short name (made when it starts) where there is one, else the task itself.
  const name = run.title || run.task || '';
  if (run.active) return {cls: 'run', label: 'Running', time: mmss(run.elapsed), task: name, full: run.task};
  if (run.queued) return {cls: '', label: 'Idle', task: run.task ? 'Waiting to start: ' + run.task : '', full: run.task};
  if (run.started && name) return {cls: '', label: 'Idle', task: 'Last task: ' + name, full: run.task, past: true};
  return {cls: '', label: 'Idle', task: ''};
}

// The tiles are built once per set of robots; their words are refreshed in place, so the live
// pictures never flicker.
function draw() {
  const list = robots();
  document.getElementById('galN').textContent = list.length ? `${list.length} robot${list.length === 1 ? '' : 's'} · live` : '';
  const key = SID + '|' + list.map(r => r.id).join();
  if (key !== G.key) {
    G.key = key; G.seen = {};
    grid.innerHTML = list.length ? list.map(r => `<div class="gt" data-st="${e(r.id)}"><div class="ld">Connecting…</div><img alt="${e(r.name)}, live side camera" hidden>`
      + `<div class="st"><i></i><span class="l"></span><span class="t"></span></div><div class="info"><b></b><span class="ty"></span><div class="tk"></div></div></div>`).join('')
      : '<div class="gempty">No robots in this session yet.</div>';
  }
  for (const r of list) {
    const t = grid.querySelector(`.gt[data-st="${CSS.escape(r.id)}"]`); if (!t) continue;
    const s = status(r);
    t.querySelector('.st').className = 'st ' + s.cls;
    t.querySelector('.st .l').textContent = s.label;
    t.querySelector('.st .t').textContent = s.time || '';
    t.querySelector('.info b').textContent = r.name || 'Robot';
    t.querySelector('.info .ty').textContent = r.label || r.robot || '';
    const tk = t.querySelector('.info .tk');
    tk.textContent = s.task || 'No task'; tk.classList.toggle('none', !s.task || !!s.past); tk.title = s.full || '';
  }
}

// Live pictures: still frames, one robot after another, the one shown longest ago first. Each
// video stream would hold one of the browser's six connections to the lab, so a grid of them
// would starve the page; two frames in flight at a time keeps every tile moving.
function pump() {
  if (!G.open || document.hidden) return;
  while (G.busy < 2) {
    const tiles = [...grid.querySelectorAll('.gt[data-st]')].filter(t => !t.dataset.loading);
    if (!tiles.length) return;
    tiles.sort((a, b) => (G.seen[a.dataset.st] || 0) - (G.seen[b.dataset.st] || 0));
    const t = tiles[0], uid = t.dataset.st, key = G.key;
    t.dataset.loading = '1'; G.busy++; G.seen[uid] = Date.now();
    const pre = new Image(), done = (ok) => {
      G.busy--; delete t.dataset.loading;
      if (ok && key === G.key && t.isConnected) {
        const im = t.querySelector('img'); im.src = pre.src; im.hidden = false; t.querySelector('.ld').hidden = true;
      }
      setTimeout(pump, ok ? 60 : 1000);
    };
    pre.onload = () => done(true); pre.onerror = () => done(false);
    pre.src = `/s/${SID}/st/${encodeURIComponent(uid)}/camera/side.jpg?viewer=1&r=${Date.now()}`;
  }
}

function setOpen(open) {
  G.open = open; gal.classList.toggle('open', open);
  btn.classList.toggle('on', open); btn.setAttribute('aria-expanded', String(open));
  if (open) { draw(); pump(); document.getElementById('galX').focus(); } else btn.focus();
}
btn.onclick = () => setOpen(!G.open);
document.getElementById('galX').onclick = () => setOpen(false);
document.addEventListener('keydown', (ev) => { if (G.open && ev.key === 'Escape') { ev.preventDefault(); setOpen(false); } });
document.addEventListener('visibilitychange', pump);
setInterval(() => { if (G.open) { if (!(S.scene && S.scene.mode === 'free')) return setOpen(false); draw(); pump(); } }, 500);
})();
