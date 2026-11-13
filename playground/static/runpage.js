// One past run's results page: click a run in the Results tab. A full page over the Playground with
// the task, how it ended, the model, time, tokens and price; the run's video (or "Make the video"
// for runs from before videos were made) next to everything the AI said, thought, ran and looked
// at; and its files: the code it ran (typed straight into the terminal or saved), what it saved,
// what its AI tool made, and what we gave it. A task run several times gets a list of its runs on
// the left (up and down keys go through them).
// Data: /pg/run_page?uid=&run= (playground/runpage.py), /pg/run_file?path=, /pg/run_image?n=,
// POST /pg/run_video/make. Loaded after the page's own script, runpanel.js and results.js
// (uses S, SID, U, BID, api, $, LOGOS, openRunTimeline).
(() => {
const css = `
#rpage{position:fixed;inset:0;z-index:55;background:var(--bg);display:none;flex-direction:column;font:15px/1.5 Inter,system-ui,sans-serif;color:#111827}
#rpage.open{display:flex}
#rpage .mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums}
#rpage button{font-family:inherit}
#rpage .top{display:flex;align-items:center;gap:10px;height:60px;padding:0 16px;flex:none}
#rpage .btn{height:40px;padding:0 14px;border-radius:10px;border:1px solid #D1D5DB;background:#fff;color:#111827;font:600 14px Inter,sans-serif;display:inline-flex;align-items:center;gap:8px;cursor:pointer;text-decoration:none;white-space:nowrap}
#rpage .btn:hover:not(:disabled){background:#F3F4F6}
#rpage .btn:disabled{color:#9CA3AF;cursor:default}
#rpage .btn.ic{width:40px;padding:0;justify-content:center}
#rpage .btn.pri{background:#2563EB;border-color:#2563EB;color:#fff}
#rpage .btn.pri:hover{background:#1D4ED8}
#rpage .crumb{font-size:14.5px;color:#4B5563;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
#rpage .crumb b{color:#111827}
#rpage .body{flex:1;min-height:0;display:flex;gap:12px;padding:0 12px 12px}
#rpage .side{width:300px;flex:none;background:#fff;border-radius:14px;box-shadow:0 0 0 1px #E5E7EB;display:flex;flex-direction:column;min-height:0}
#rpage .side .sum{padding:16px;border-bottom:1px solid #E5E7EB;display:flex;flex-direction:column;gap:4px}
#rpage .side .sum b{font-size:17px}
#rpage .side .sum span{font-size:13.5px;color:#4B5563}
#rpage .side .list{overflow:auto;padding:6px;display:flex;flex-direction:column;gap:2px}
#rpage .side .row{display:grid;grid-template-columns:24px 1fr auto;gap:4px 10px;align-items:center;padding:10px;border-radius:10px;border:0;background:none;text-align:left;cursor:pointer;color:#111827;font-size:14.5px}
#rpage .side .row:hover{background:#F3F4F6}
#rpage .side .row.on{background:#EFF4FF;box-shadow:0 0 0 1.5px #2563EB inset}
#rpage .side .row .why{grid-column:2 / -1;font-size:13px;color:#4B5563;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#rpage .side .keys{padding:10px 16px;border-top:1px solid #E5E7EB;font-size:13px;color:#4B5563}
#rpage .side kbd{font:600 12px 'JetBrains Mono',monospace;border:1px solid #D1D5DB;border-bottom-width:2px;border-radius:5px;padding:0 5px;background:#fff}
#rpage .main{flex:1;min-width:0;overflow:auto;display:flex;flex-direction:column;gap:12px}
#rpage .card{background:#fff;border-radius:14px;box-shadow:0 0 0 1px #E5E7EB}
#rpage .main>*,#rpage .vid>*{flex:none}
#rpage .hero{padding:20px 22px;display:flex;flex-direction:column;gap:14px}
#rpage .hero .task{font-size:20px;font-weight:650;line-height:1.35;white-space:pre-wrap;overflow-wrap:anywhere;max-height:8.2em;overflow:auto}
#rpage .out{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#rpage .badge{display:inline-flex;align-items:center;gap:7px;height:32px;padding:0 12px;border-radius:8px;font-weight:700;font-size:15px}
#rpage .badge.ok{background:#DCFCE7;color:#14532D}#rpage .badge.no{background:#FEE2E2;color:#7F1D1D}
#rpage .badge svg{width:16px;height:16px}
#rpage .out .why{font-size:14.5px;color:#374151}
#rpage .out .chip{font-size:13.5px;font-weight:600;padding:3px 10px;border-radius:999px;background:#FEF3C7;color:#78350F}
#rpage .out .chip.red{background:#FEE2E2;color:#7F1D1D}
#rpage .errtxt{font:12.5px/1.45 'JetBrains Mono',monospace;color:#7F1D1D;background:#FEF2F2;border-radius:8px;padding:8px 10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:7em;overflow:auto}
#rpage .tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}
#rpage .tile{border-radius:12px;background:#F9FAFB;box-shadow:0 0 0 1px #E5E7EB inset;padding:12px 14px;display:flex;flex-direction:column;gap:2px;min-width:0}
#rpage .tile .k{font-size:13px;color:#4B5563;font-weight:600}
#rpage .tile .v{font-size:20px;font-weight:700;display:flex;align-items:center;gap:8px;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#rpage .tile .v img{width:20px;height:20px;flex:none}
#rpage .tile .v.sm{font-size:16px}
#rpage .tile .s{font-size:13px;color:#4B5563;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#rpage .tile .v.none{color:#6B7280;font-size:16px}
#rpage .split{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(360px,1fr);gap:12px;min-height:560px}
#rpage .vid{padding:14px;display:flex;flex-direction:column;gap:10px;min-width:0}
#rpage .hd{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:700}
#rpage .hd .sp{flex:1}
#rpage .hd .sub{font-size:13.5px;font-weight:500;color:#4B5563}
#rpage video{width:100%;aspect-ratio:16/9;background:#111827;border-radius:10px;display:block}
#rpage .novid{aspect-ratio:16/9;border-radius:10px;background:#F3F4F6;box-shadow:0 0 0 1px #E5E7EB inset;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center;padding:20px;color:#374151}
#rpage .novid b{font-size:17px;color:#111827}
#rpage .marks{position:relative;height:30px;border-radius:7px;background:#F3F4F6;cursor:pointer}
#rpage .marks i{position:absolute;top:6px;bottom:6px;width:3px;border-radius:2px;transform:translateX(-50%)}
#rpage .marks i.d{width:12px;height:12px;top:9px;bottom:auto;border-radius:2px;transform:translateX(-50%) rotate(45deg);background:#DC2626}
#rpage .marks .ph{position:absolute;top:0;bottom:0;width:2px;background:#111827;pointer-events:none}
#rpage .legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:#374151}
#rpage .legend span{display:flex;align-items:center;gap:6px}
#rpage .legend i{width:10px;height:10px;border-radius:3px}
#rpage .legend i.d{background:#DC2626;transform:rotate(45deg);border-radius:2px;width:9px;height:9px}
#rpage .pics{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
#rpage .pics img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:8px;background:#E5E7EB;cursor:pointer}
#rpage .tr{display:flex;flex-direction:column;min-height:0;min-width:0;max-height:760px}
#rpage .tr .hd{padding:14px 14px 8px}
#rpage .filters{display:flex;flex-wrap:wrap;gap:6px;padding:0 14px 8px}
#rpage .filters button{height:32px;padding:0 11px;border-radius:999px;border:1px solid #D1D5DB;background:#fff;font:600 13.5px Inter,sans-serif;color:#374151;cursor:pointer}
#rpage .filters button.on{background:#111827;border-color:#111827;color:#fff}
#rpage .jump{display:flex;gap:8px;align-items:center;padding:0 14px 8px;font-size:13.5px;color:#4B5563;flex-wrap:wrap}
#rpage .jump .btn{height:32px;font-size:13px;padding:0 10px}
#rpage .jump label{display:flex;align-items:center;gap:6px;margin-left:auto;cursor:pointer}
#rpage .steps{overflow:auto;padding:0 8px 12px;flex:1;min-height:0}
#rpage .stp{display:grid;grid-template-columns:52px 26px minmax(0,1fr);gap:8px;padding:8px 6px;border-radius:9px;cursor:pointer}
#rpage .stp:hover{background:#F9FAFB}
#rpage .stp.now{background:#EFF4FF}
#rpage .stp.hit{box-shadow:0 0 0 2px #2563EB inset}
#rpage .stp .t{font:500 13px 'JetBrains Mono',monospace;color:#4B5563;padding-top:2px}
#rpage .stp .ic{width:26px;height:26px;border-radius:7px;display:flex;align-items:center;justify-content:center;font-size:13px;color:#fff;font-weight:700}
#rpage .stp .bd{min-width:0}
#rpage .stp .lb{font-size:13px;font-weight:700;color:#374151;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#rpage .stp .lb .bad{color:#B91C1C;background:#FEE2E2;border-radius:5px;padding:0 6px}
#rpage .stp .tx{font-size:14.5px;white-space:pre-wrap;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
#rpage .stp .tx.code{font:13px/1.45 'JetBrains Mono',monospace;color:#1F2937}
#rpage .stp.open .tx{display:block;-webkit-line-clamp:unset}
#rpage .stp .o{display:none;margin-top:6px;font:12.5px/1.45 'JetBrains Mono',monospace;background:#F3F4F6;border-radius:8px;padding:8px 10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;color:#1F2937}
#rpage .stp.open .o{display:block}
#rpage .stp .o.err{background:#FEF2F2;color:#7F1D1D}
#rpage .stp .thumb{margin-top:6px;width:200px;max-width:100%;border-radius:8px;display:block;background:#E5E7EB}
#rpage .stp .sc{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}
#rpage .stp .sc button{height:28px;padding:0 9px;border-radius:7px;border:1px solid #C7D2FE;background:#EEF2FF;color:#3730A3;font:600 12.5px Inter,sans-serif;cursor:pointer}
#rpage .stp.stop{background:#FEF2F2}
#rpage .empty{padding:16px;color:#4B5563;font-size:14.5px}
#rpage .files{display:grid;grid-template-columns:300px minmax(0,1fr);min-height:460px}
#rpage .files .tree{border-right:1px solid #E5E7EB;overflow:auto;max-height:640px;padding:8px}
#rpage .files .gh{font-size:13px;font-weight:700;color:#374151;padding:10px 8px 4px;display:flex;gap:6px;align-items:baseline}
#rpage .files .gh span{font-weight:500;color:#6B7280}
#rpage .files .note{font-size:12.5px;color:#6B7280;padding:0 8px 4px}
#rpage .files .f{display:flex;align-items:center;gap:8px;width:100%;padding:7px 8px;border:0;background:none;border-radius:8px;text-align:left;cursor:pointer;font:14px Inter,sans-serif;color:#111827}
#rpage .files .f:hover{background:#F3F4F6}
#rpage .files .f.on{background:#EFF4FF;box-shadow:0 0 0 1.5px #2563EB inset}
#rpage .files .f .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#rpage .files .f .m{font:12px 'JetBrains Mono',monospace;color:#6B7280;white-space:nowrap}
#rpage .files .f .tag{font-size:11.5px;font-weight:700;color:#92400E;background:#FEF3C7;border-radius:5px;padding:0 5px}
#rpage .viewer{display:flex;flex-direction:column;min-width:0}
#rpage .viewer .vh{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #E5E7EB;min-height:58px}
#rpage .viewer .vh .nm{font:600 14.5px 'JetBrains Mono',monospace;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#rpage .viewer .vh .sub{font-size:13px;color:#4B5563;white-space:nowrap}
#rpage .viewer .vb{flex:1;overflow:auto;max-height:582px}
#rpage .code{display:grid;grid-template-columns:auto 1fr;font:13px/1.55 'JetBrains Mono',monospace;margin:0;padding:10px 0}
#rpage .code .ln{color:#9CA3AF;text-align:right;padding:0 12px;user-select:none;white-space:pre}
#rpage .code .cd{white-space:pre;padding-right:16px;color:#111827}
#rpage .viewer img.full{max-width:100%;display:block;margin:12px auto;border-radius:8px}
#rpage .viewer iframe{width:100%;height:580px;border:0}
@media (max-width:1100px){#rpage .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}#rpage .split{grid-template-columns:1fr}#rpage .side{display:none}#rpage .files{grid-template-columns:1fr}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const e = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const clock = (x) => { x = Math.max(0, Math.round(x || 0)); return `${Math.floor(x / 60)}:${String(x % 60).padStart(2, '0')}`; };
const usd = (x) => '$' + (x < 0.1 && x > 0 ? x.toFixed(3) : x.toFixed(2));
const num = (x) => x == null ? null : Number(x).toLocaleString();
const size = (b) => b == null ? '' : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;
const CHECK = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>';
const CROSS = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/></svg>';
const SQ = (ok, title) => `<span class="sq lg ${ok ? 'ok' : 'no'}" role="img" aria-label="${e(title)}" title="${e(title)}">${(ok ? CHECK : CROSS).replace('currentColor', '#fff')}</span>`;
// Each kind of step: its label, its color, its letter, and its filter.
const KIND = {
  says: ['Said', '#2563EB', 'S', 'said'], thinks: ['Thought', '#6D28D9', 'T', 'thought'], runs: ['Ran code', '#0F766E', '>', 'code'],
  writes: ['Wrote a file', '#7C3AED', 'W', 'code'], reads: ['Read', '#A16207', 'R', 'said'], looks: ['Looked', '#4B5563', 'L', 'looked'],
  tool: ['Used a tool', '#0369A1', 'U', 'code'], decides: ['Decided', '#1D4ED8', 'D', 'said'], stop: ['Safety stop', '#DC2626', '!', 'errors'],
};
const FILTERS = [['all', 'All'], ['said', 'Said'], ['thought', 'Thought'], ['code', 'Ran code'], ['looked', 'Looked'], ['errors', 'Problems']];
const OUTCOME = {finished: 'Succeeded', time_limit: 'Hit the time limit', stopped: 'Stopped', error: 'Error', agent_error: 'Error'};
const TOOL_NAME = {devin: 'Devin', codex: 'Codex', claude: 'Claude Code'};

document.body.insertAdjacentHTML('beforeend', '<div id="rpage" role="dialog" aria-modal="true" aria-label="Run results"></div>');
const root = $('rpage');
const P = {uid: null, run: null, d: null, filter: 'all', follow: true, file: null, timer: null, cache: {}};

async function open(uid, run) {
  P.uid = uid; P.run = run; P.file = null; P.filter = 'all';
  root.classList.add('open');
  if (!P.d || P.d.run_id !== run) root.innerHTML = '<div class="top"><button class="btn" data-back>← Back to Results</button></div><div class="empty">Loading the run…</div>';
  bindBack();
  await load();
}
async function load() {
  const uid = P.uid, run = P.run;
  const d = await fetch(U('/pg/run_page') + `?uid=${encodeURIComponent(uid)}&run=${encodeURIComponent(run)}`, {headers: {'X-Browser-Id': BID}})
    .then(x => x.json()).catch(() => null);
  if (P.run !== run || !root.classList.contains('open')) return;
  if (!d || !d.ok) { root.innerHTML = `<div class="top"><button class="btn" data-back>← Back to Results</button></div><div class="empty">${e((d && d.error) || 'Could not load this run.')}</div>`; bindBack(); return; }
  P.d = d; draw();
  clearTimeout(P.timer);
  if (d.video === 'making') P.timer = setTimeout(() => { if (P.run === run) refreshVideo(); }, 5000);
}
// While its video is being made: check again, and redraw only the video when it's ready.
async function refreshVideo() {
  const run = P.run;
  const d = await fetch(U('/pg/run_page') + `?uid=${encodeURIComponent(P.uid)}&run=${encodeURIComponent(run)}`, {headers: {'X-Browser-Id': BID}}).then(x => x.json()).catch(() => null);
  if (!d || !d.ok || P.run !== run) return;
  P.d.video = d.video; P.d.video_url = d.video_url;
  if (d.video === 'making') { P.timer = setTimeout(refreshVideo, 5000); return; }
  $('rpVid').outerHTML = videoCard(P.d); bindVideo();
}
function close() {
  clearTimeout(P.timer);
  const v = root.querySelector('video'); if (v) v.pause();
  root.classList.remove('open'); root.innerHTML = ''; P.d = null;
}
function bindBack() { root.querySelectorAll('[data-back]').forEach(b => b.onclick = close); }

// ------------------------------------------------------------------ drawing
function draw() {
  const d = P.d, runs = d.runs || [];
  const i = runs.findIndex(x => x.run_id === d.run_id);
  const many = runs.length >= 2;
  const name = many ? `Run ${d.index} of ${d.of}` : 'Run';
  root.innerHTML = `
  <div class="top">
    <button class="btn" data-back>← Back to Results</button>
    <span class="crumb">${e(d.station || '')} / Results / <b>${name}</b></span>
    ${many ? `<button class="btn ic" id="rpPrev" aria-label="Previous run" ${i <= 0 ? 'disabled' : ''}>↑</button><button class="btn ic" id="rpNext" aria-label="Next run" ${i >= runs.length - 1 ? 'disabled' : ''}>↓</button>` : ''}
    <button class="btn" id="rpTimeline">Timeline</button>
  </div>
  <div class="body">${many ? side(d, runs) : ''}
    <div class="main">
      ${hero(d, many)}
      <div class="split">${videoCard(d)}${transcriptCard(d)}</div>
      ${filesCard(d)}
    </div>
  </div>`;
  bindBack();
  $('rpTimeline').onclick = () => window.openRunTimeline(P.uid, P.run);
  if (many) {
    const go = (k) => { const x = runs[i + k]; if (x) open(P.uid, x.run_id); };
    const pv = $('rpPrev'), nx = $('rpNext');
    if (pv) pv.onclick = () => go(-1);
    if (nx) nx.onclick = () => go(1);
    root.querySelectorAll('[data-runid]').forEach(b => b.onclick = () => open(P.uid, b.dataset.runid));
    const on = root.querySelector('.side .row.on'); if (on) on.scrollIntoView({block: 'nearest'});
  }
  bindVideo(); drawSteps(); bindFiles();
}

function side(d, runs) {
  const ok = runs.filter(x => x.ok).length, secs = runs.reduce((a, x) => a + (x.seconds || 0), 0);
  const costs = runs.filter(x => x.cost_usd != null), cost = costs.reduce((a, x) => a + x.cost_usd, 0);
  const of = d.batch_total || runs.length;
  return `<nav class="side" aria-label="Every run of this task">
    <div class="sum"><b>${ok} of ${runs.length} succeeded</b>
      <span>${runs.length < of ? `${of - runs.length} of ${of} not run · ` : ''}Avg time ${clock(secs / runs.length)}${costs.length ? ` · Total ${usd(cost)}` : ''}</span></div>
    <div class="list">${runs.map(x => `<button class="row${x.run_id === d.run_id ? ' on' : ''}" data-runid="${e(x.run_id)}" ${x.run_id === d.run_id ? 'aria-current="true"' : ''}>
      ${SQ(x.ok, x.reason || '')}<b>Run ${x.index}</b><span class="mono" style="font-size:13px;color:#374151">${clock(x.seconds)}${x.cost_usd != null ? ` · ${usd(x.cost_usd)}` : ''}</span>
      <span class="why">${e(x.reason || OUTCOME[x.status] || x.status || '')}</span></button>`).join('')}</div>
    <div class="keys"><kbd>↑</kbd> <kbd>↓</kbd> go through the runs</div></nav>`;
}

function hero(d, many) {
  const logo = LOGOS[d.provider_id] || LOGOS[d.provider] || '';
  const tool = TOOL_NAME[d.agent] || '';
  const lim = d.time_limit ? `of ${Math.round(d.time_limit / 60)} min limit` : '';
  const out = d.tokens.output, tot = d.tokens.total;
  const devin = d.agent === 'devin';
  const tiles = [
    ['Model', `<span class="v sm">${logo ? `<img src="${e(logo)}" alt="">` : ''}<span style="overflow:hidden;text-overflow:ellipsis">${e(d.model_label)}</span></span>`, tool ? `Using ${tool}` : ''],
    ['Attempt', `<span class="v">${d.index ? `Run ${d.index} <span style="font-weight:500;color:#4B5563">of ${d.of}</span>` : 'Run 1 <span style="font-weight:500;color:#4B5563">of 1</span>'}</span>`, ''],
    ['Total time', `<span class="v mono">${clock(d.seconds)}</span>`, lim],
    ['Output tokens', out != null ? `<span class="v mono">${num(out)}</span>` : '<span class="v none">Not reported</span>',
      devin ? 'As reported by Devin' : tot != null ? `${num(tot)} in total` : ''],
    ['Price', d.cost_usd != null ? `<span class="v mono">${usd(d.cost_usd)}</span>` : '<span class="v none">Not reported</span>',
      d.cost_usd != null ? '' : (d.cost_why || '')],
  ];
  const ok = d.ok_run;
  const chips = [d.safety_stops ? `<span class="chip red">${d.safety_stops} safety stop${d.safety_stops > 1 ? 's' : ''}</span>` : '',
    d.errors ? `<span class="chip">${d.errors} code error${d.errors > 1 ? 's' : ''}</span>` : ''].join('');
  const err = d.status === 'error' && d.error_text ? `<div class="errtxt">${e(String(d.error_text).split('\n').slice(-6).join('\n'))}</div>` : '';
  return `<section class="card hero">
    <div class="task">${e(d.task)}</div>
    <div class="out"><span class="badge ${ok ? 'ok' : 'no'}">${ok ? CHECK : CROSS}${ok ? 'Succeeded' : 'Failed'}</span>
      <span class="why">${e(d.reason || OUTCOME[d.status] || d.status || '')}</span>${chips}</div>${err}
    <div class="tiles">${tiles.filter(t => !(many && t[0] === 'Attempt' && false)).map(([k, v, s]) => `<div class="tile"><span class="k">${k}</span>${v}${s ? `<span class="s" title="${e(s)}">${e(s)}</span>` : ''}</div>`).join('')}</div>
  </section>`;
}

// ------------------------------------------------------------------ video
const MARK_COLOR = {runs: '#0F766E', looks: '#6B7280', says: '#2563EB', thinks: '#6D28D9', writes: '#7C3AED', tool: '#0369A1'};
function videoCard(d) {
  const pics = d.steps.filter(s => s.image != null);
  let body;
  if (d.video_url) {
    const src = d.video_url.startsWith('/') ? U(d.video_url) : null;
    body = src ? `<video id="rpVideo" src="${e(src)}" controls playsinline preload="metadata"></video>`
      : `<div class="novid"><b>This run's video is saved on the website</b><a class="btn" href="${e(d.video_url)}" target="_blank" rel="noopener">Watch it there ↗</a></div>`;
  } else if (d.video === 'making') {
    body = `<div class="novid"><b>The video is being made…</b><span>It shows up here when it's ready. This takes about as long as the run did.</span></div>`;
  } else if (d.can_make) {
    body = `<div class="novid"><b>No video yet</b><span>This run saved its replay, so its video can be made now.</span>${d.mine ? '<button class="btn pri" id="rpMake">Make the video</button>' : ''}</div>`;
  } else {
    body = `<div class="novid"><b>No video for this run</b><span>${d.replay ? 'Its robot is no longer on the table, so the video can’t be made here.' : 'This run didn’t save a replay.'}</span></div>`;
  }
  const dur = Math.max(1, d.seconds || 1);
  const marks = d.steps.filter(s => MARK_COLOR[s.kind] || s.kind === 'stop' || s.error).map(s => {
    const x = Math.min(100, (s.t / dur) * 100);
    return s.kind === 'stop' || s.error ? `<i class="d" style="left:${x}%" title="${clock(s.t)} ${s.kind === 'stop' ? 'Safety stop' : 'Code error'}"></i>`
      : `<i style="left:${x}%;background:${MARK_COLOR[s.kind]}" title="${clock(s.t)} ${KIND[s.kind][0]}"></i>`;
  }).join('');
  return `<section class="card vid" id="rpVid">
    <div class="hd">Recorded video<span class="sp"></span><span class="sub mono">${clock(d.seconds)}</span></div>
    ${body}
    <div class="marks" id="rpMarks" title="Click to jump there">${marks}<span class="ph" id="rpPh" style="left:0"></span></div>
    <div class="legend">${[['#2563EB', 'Said'], ['#6D28D9', 'Thought'], ['#0F766E', 'Ran code'], ['#6B7280', 'Looked']].map(([c, t]) => `<span><i style="background:${c}"></i>${t}</span>`).join('')}<span><i class="d"></i>Safety stop or code error</span></div>
    ${!d.video_url && pics.length ? `<div class="hd" style="font-size:14.5px">What the AI saw<span class="sub">${pics.length} picture${pics.length > 1 ? 's' : ''}</span></div>
      <div class="pics">${pics.map(s => `<img loading="lazy" src="${e(imgUrl(s.image))}" alt="What the AI saw at ${clock(s.t)}" title="${clock(s.t)}" data-t="${s.t}">`).join('')}</div>` : ''}
  </section>`;
}
const imgUrl = (n) => U('/pg/run_image') + `?uid=${encodeURIComponent(P.uid)}&run=${encodeURIComponent(P.run)}&n=${n}`;
function seek(t) {
  const v = $('rpVideo');
  if (v) { v.currentTime = Math.max(0, t - (P.d.video_start || 0)); v.play().catch(() => {}); }
  const ph = $('rpPh'); if (ph) ph.style.left = `${Math.min(100, t / Math.max(1, P.d.seconds) * 100)}%`;
}
function bindVideo() {
  const v = $('rpVideo'), mk = $('rpMarks');
  if (mk) mk.onclick = (ev) => { const r = mk.getBoundingClientRect(); const t = (ev.clientX - r.left) / r.width * P.d.seconds; seek(t); highlight(t, true); };
  const b = $('rpMake');
  if (b) b.onclick = async () => {
    b.disabled = true; b.textContent = 'Starting…';
    const r = await api('/pg/run_video/make', {uid: P.uid, run: P.run}).catch(() => null);
    if (!r || !r.ok) { b.disabled = false; b.textContent = 'Make the video'; b.insertAdjacentHTML('afterend', `<span style="color:#991B1B">${e((r && r.error) || 'Could not start it.')}</span>`); return; }
    P.d.video = 'making'; $('rpVid').outerHTML = videoCard(P.d); bindVideo();
    P.timer = setTimeout(refreshVideo, 5000);
  };
  root.querySelectorAll('.pics img').forEach(im => im.onclick = () => { highlight(+im.dataset.t, true); });
  if (v) v.ontimeupdate = () => {
    const t = v.currentTime + (P.d.video_start || 0);
    const ph = $('rpPh'); if (ph) ph.style.left = `${Math.min(100, t / Math.max(1, P.d.seconds) * 100)}%`;
    if (P.follow && !v.paused) highlight(t, false);
  };
}

// ------------------------------------------------------------------ transcript
function transcriptCard(d) {
  const n = d.steps.length;
  return `<section class="card tr">
    <div class="hd">Transcript<span class="sp"></span><span class="sub">${n} step${n === 1 ? '' : 's'}</span></div>
    <div class="filters" role="group" aria-label="Show">${FILTERS.map(([k, t]) => `<button data-f="${k}" class="${P.filter === k ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div class="jump">${d.errors || d.safety_stops ? `<button class="btn" id="rpNextBad">Next problem ↓</button>` : ''}
      <label><input type="checkbox" id="rpFollow" ${P.follow ? 'checked' : ''}> Follow the video</label></div>
    <div class="steps" id="rpSteps"></div>
  </section>`;
}
function drawSteps() {
  const d = P.d, box = $('rpSteps');
  const shown = d.steps.map((s, i) => [s, i]).filter(([s]) => P.filter === 'all' || (P.filter === 'errors' ? (s.kind === 'stop' || s.error) : (KIND[s.kind] || [])[3] === P.filter));
  box.innerHTML = shown.length ? shown.map(([s, i]) => step(s, i)).join('') : '<div class="empty">Nothing of this kind in this run.</div>';
  root.querySelectorAll('.filters button').forEach(b => b.onclick = () => { P.filter = b.dataset.f; root.querySelectorAll('.filters button').forEach(x => x.classList.toggle('on', x === b)); drawSteps(); });
  const f = $('rpFollow'); if (f) f.onchange = () => { P.follow = f.checked; };
  box.querySelectorAll('.stp').forEach(el => el.onclick = (ev) => {
    if (ev.target.closest('[data-script]')) return;
    const s = d.steps[+el.dataset.i];
    el.classList.toggle('open');
    seek(s.t);
  });
  box.querySelectorAll('[data-script]').forEach(b => b.onclick = () => showScript(+b.dataset.script));
  const nb = $('rpNextBad');
  if (nb) nb.onclick = () => {
    const els = [...box.querySelectorAll('.stp.bad')];
    if (!els.length) return;
    const top = box.scrollTop + 8;
    const next = els.find(x => x.offsetTop - box.offsetTop > top) || els[0];
    box.scrollTop = next.offsetTop - box.offsetTop; flash(next);
  };
}
function step(s, i) {
  const k = KIND[s.kind] || [s.kind, '#6B7280', '·', 'said'];
  const code = s.kind === 'runs' || s.kind === 'tool';
  let label = k[0];
  if (s.kind === 'looks') label = 'Looked' + (s.text ? `: ${s.text}` : '');
  const bad = s.kind === 'stop' || s.error;
  const sc = (s.scripts || []).map(id => { const x = P.d.scripts[id]; return x ? `<button data-script="${id}">See code: ${e(scriptName(x))}</button>` : ''; }).join('');
  return `<div class="stp${bad ? ' bad' : ''}${s.kind === 'stop' ? ' stop' : ''}" data-i="${i}" data-t="${s.t}">
    <span class="t">${clock(s.t)}</span><span class="ic" style="background:${k[1]}" aria-hidden="true">${k[2]}</span>
    <div class="bd"><div class="lb">${e(label)}${s.error ? '<span class="bad">Error</span>' : ''}</div>
      ${s.kind === 'looks' ? '' : `<div class="tx${code ? ' code' : ''}">${e(s.text)}</div>`}
      ${s.image != null ? `<img class="thumb" loading="lazy" src="${e(imgUrl(s.image))}" alt="What the AI saw">` : ''}
      ${s.out ? `<div class="o${s.error ? ' err' : ''}">${e(s.out)}</div>` : ''}
      ${sc ? `<div class="sc">${sc}</div>` : ''}</div></div>`;
}
let lastHi = -1;
function highlight(t, scroll) {
  const box = $('rpSteps'); if (!box) return;
  const els = [...box.querySelectorAll('.stp')];
  let best = null;
  for (const el of els) { if (+el.dataset.t <= t + 0.05) best = el; else break; }
  if (!best || +best.dataset.i === lastHi && !scroll) return;
  lastHi = +best.dataset.i;
  els.forEach(x => x.classList.toggle('now', x === best));
  const top = best.offsetTop - box.offsetTop;
  if (scroll || top < box.scrollTop || top > box.scrollTop + box.clientHeight - 60) box.scrollTop = Math.max(0, top - 40);
}
function flash(el) { el.classList.add('hit'); setTimeout(() => el.classList.remove('hit'), 1200); }

// ------------------------------------------------------------------ files
const scriptName = (x) => x.kind === 'file' ? x.name : `Typed into the terminal at ${clock(x.t)}`;
function filesCard(d) {
  const f = d.files, sc = d.scripts;
  const tool = TOOL_NAME[d.agent] || 'the AI tool';
  const grp = (title, sub, items, note) => items.length ? `<div class="gh">${title} <span>${sub}</span></div>${note ? `<div class="note">${note}</div>` : ''}${items.join('')}` : '';
  const fileBtn = (x) => `<button class="f" data-path="${e(x.path)}"><span class="n">${e(x.path)}</span>${x.changed ? '<span class="tag">Changed</span>' : ''}<span class="m">${size(x.size)}</span></button>`;
  const scriptBtn = (x) => `<button class="f" data-script="${x.id}"><span class="n">${e(scriptName(x))}</span><span class="m">${x.runs > 1 ? `ran ${x.runs}×` : x.runs ? 'ran once' : 'not run'}</span></button>`;
  const typed = sc.filter(x => x.kind === 'inline').length;
  return `<section class="card" id="rpFiles">
    <div class="hd" style="padding:14px 16px 0">Files<span class="sp"></span><span class="sub">${f.saved.length} saved by the AI · ${f.given.length} given to it</span></div>
    <div class="files">
      <div class="tree">
        ${grp('Code it ran', sc.length, sc.map(scriptBtn), typed ? `${typed} script${typed > 1 ? 's were' : ' was'} typed straight into the terminal and never saved as a file.` : '')}
        ${grp('Saved by the AI', f.saved.length, f.saved.map(fileBtn))}
        ${grp(`Made by ${tool}`, f.tool.length, f.tool.map(fileBtn), 'The AI tool’s own settings, not the AI’s work.')}
        ${grp('Given to the AI', f.given.length, f.given.map(fileBtn), f.kit_known ? '' : 'This run didn’t record its starting files, so these are the usual starter files.')}
        ${!sc.length && !f.saved.length && !f.given.length ? '<div class="empty">This run left no files.</div>' : ''}
      </div>
      <div class="viewer" id="rpViewer"><div class="empty">Pick a file to see it.</div></div>
    </div></section>`;
}
function bindFiles() {
  root.querySelectorAll('#rpFiles [data-path]').forEach(b => b.onclick = () => showFile(b.dataset.path));
  root.querySelectorAll('#rpFiles [data-script]').forEach(b => b.onclick = () => showScript(+b.dataset.script));
  const d = P.d, first = d.scripts[0] ? ['s', 0] : d.files.saved[0] ? ['f', d.files.saved[0].path] : d.files.given[0] ? ['f', d.files.given[0].path] : null;
  if (first) first[0] === 's' ? showScript(0, true) : showFile(first[1], true);
}
function mark(sel) { root.querySelectorAll('#rpFiles .f').forEach(x => x.classList.toggle('on', x.matches(sel))); }
function codeView(text) {
  const lines = text.replace(/\n$/, '').split('\n');
  return `<pre class="code"><span class="ln">${lines.map((_, i) => i + 1).join('\n')}</span><span class="cd">${e(lines.join('\n'))}</span></pre>`;
}
function showScript(id, quiet) {
  const x = P.d.scripts[id]; if (!x) return;
  mark(`[data-script="${id}"]`);
  const saved = x.kind === 'file' && P.d.files.saved.find(f => f.path === x.name || f.path.endsWith('/' + x.name));
  if (!x.code && saved) return showFile(saved.path, quiet, `[data-script="${id}"]`);
  const sub = x.kind === 'file' ? `First at ${clock(x.t)} · ${x.runs > 1 ? `ran ${x.runs} times` : x.runs ? 'ran once' : 'not run'}` : `Typed into the terminal at ${clock(x.t)}, never saved`;
  $('rpViewer').innerHTML = `<div class="vh"><span class="nm">${e(scriptName(x))}</span><span class="sub">${sub}</span><button class="btn" id="rpJump">Show in transcript</button></div>
    <div class="vb">${x.code ? codeView(x.code) : '<div class="empty">The AI ran this file, but its code wasn’t in the transcript and the file isn’t in its folder any more.</div>'}</div>`;
  $('rpJump').onclick = () => jumpTo(x.t);
  if (!quiet) $('rpFiles').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function jumpTo(t) {
  P.filter = 'all'; root.querySelectorAll('.filters button').forEach(x => x.classList.toggle('on', x.dataset.f === 'all')); drawSteps();
  highlight(t, true); seek(t);
  const el = root.querySelector('.stp.now'); if (el) flash(el);
  root.querySelector('.split').scrollIntoView({behavior: 'smooth', block: 'start'});
}
async function showFile(path, quiet, sel) {
  const all = [...P.d.files.saved, ...P.d.files.tool, ...P.d.files.given];
  const f = all.find(x => x.path === path); if (!f) return;
  mark(sel || `[data-path="${CSS.escape(path)}"]`);
  const url = U('/pg/run_file') + `?uid=${encodeURIComponent(P.uid)}&run=${encodeURIComponent(P.run)}&path=${encodeURIComponent(path)}`;
  const dl = `<a class="btn" href="${e(url)}" download="${e(path.split('/').pop())}">Download</a>`;
  const head = `<div class="vh"><span class="nm">${e(path)}</span><span class="sub">${size(f.size)}</span>${dl}</div>`;
  const v = $('rpViewer');
  if (f.type === 'image') v.innerHTML = `${head}<div class="vb"><img class="full" src="${e(url)}" alt="${e(path)}"></div>`;
  else if (f.type === 'pdf') v.innerHTML = `${head}<div class="vb"><iframe src="${e(url)}" title="${e(path)}"></iframe></div>`;
  else if (f.type === 'text' && f.size <= 400000) {
    v.innerHTML = `${head}<div class="vb"><div class="empty">Loading…</div></div>`;
    const key = P.run + '|' + path;
    const text = P.cache[key] != null ? P.cache[key] : await fetch(url, {headers: {'X-Browser-Id': BID}}).then(r => r.ok ? r.text() : null).catch(() => null);
    if (text != null) P.cache[key] = text;
    const vb = v.querySelector('.vb'); if (!vb || !v.querySelector('.nm') || v.querySelector('.nm').textContent !== path) return;
    vb.innerHTML = text == null ? '<div class="empty">Could not open this file.</div>' : codeView(text);
  } else v.innerHTML = `${head}<div class="vb"><div class="empty">This kind of file can’t be shown here${f.type === 'text' ? ' (it’s too big)' : ''}. Download it to open it.</div></div>`;
  if (!quiet) $('rpFiles').scrollIntoView({behavior: 'smooth', block: 'start'});
}

// ------------------------------------------------------------------ keys
window.addEventListener('keydown', (ev) => {
  if (!root.classList.contains('open') || document.getElementById('runpop')?.classList.contains('open')
      || document.getElementById('vidWrap')?.classList.contains('open')) return;
  if (ev.target.closest && ev.target.closest('input,textarea,video')) return;
  if (ev.key === 'Escape') { close(); return; }
  const runs = (P.d && P.d.runs) || [];
  if (runs.length < 2 || (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown')) return;
  const i = runs.findIndex(x => x.run_id === P.run), x = runs[i + (ev.key === 'ArrowUp' ? -1 : 1)];
  if (x) { ev.preventDefault(); open(P.uid, x.run_id); }
});
window.openRunPage = open;
})();
