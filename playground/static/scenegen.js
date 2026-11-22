// Describe a scene: a bar at the top middle of the view. Clicking it (or "/", or opening a new,
// empty session) grows it into a box floating over the live 3D view: type the scene you want, or
// add a photo, and press Enter. Recent prompts and ready-made scenes sit under the box; Tab puts
// the closest ready scene down as it is. Enter goes straight to building (no check-list step): the
// box slides into a panel on the left, the model on your own key (Settings > General) picks robots
// and objects from our catalog (each streams into a strip), then plans the layout, which shows as
// outlines on the floor, one line per thing in the panel; each thing drops into its outline and
// flashes green when it lands (the drag-and-drop drop check) or red when it doesn't fit
// (playground/scenegen.py). Things the library lacks are made by the AI and physics-tested first.
// The camera flies to the build and stops following the moment you move the view yourself.
// At the end the panel shrinks to a "ready" pill above the menu bar, with Undo.
(() => {
const css = `
body:not(.freeplay) #sgBar, body.watch #sgBar, body.freeplay.robotsel #sgBar, body.sgHide #sgBar, body.sgOpen #sgBar{display:none}
body.sgOpen .emptyfloor,body.sgPanel .emptyfloor{display:none!important}
#sgBar{position:absolute;left:50%;top:12px;transform:translateX(-50%);z-index:7;display:flex;align-items:center;gap:6px;height:44px;padding:0 5px;border-radius:22px;border:0;background:rgba(255,255,255,.95);box-shadow:0 10px 28px -10px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.08);font:400 14px Inter,sans-serif;color:#6B7280;cursor:text;white-space:nowrap;transition:transform 160ms ease-out}
#sgBar:not(.busy){width:270px}
#sgBar:hover:not(.busy){box-shadow:0 0 0 2px #93C5FD,0 10px 28px -10px rgba(17,24,39,.35)}
#sgBar #sgBarT{flex:1;text-align:left}
#sgBar .ph,#sgCard .phb{width:34px;height:34px;flex:none;border-radius:50%;border:0;padding:0;background:#F3F4F6;box-shadow:inset 0 0 0 1px #E5E7EB;color:#111827;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:background 120ms ease-out,transform 120ms ease-out}
#sgBar .ph:hover,#sgCard .phb:hover{background:#E5E7EB}
#sgCard .phb:active{transform:scale(.94)}
#sgBar .snd{width:34px;height:34px;flex:none;border-radius:50%;background:#E5E7EB;color:#fff;display:flex;align-items:center;justify-content:center}
#sgBar:active{transform:translateX(-50%) scale(.98)}
#sgBar .k{font:600 11px Inter,sans-serif;color:#4B5563;border:1px solid #E5E7EB;border-radius:5px;padding:1px 6px;margin-left:10px}
#sgBar.busy{cursor:default;color:#111827;font-weight:600;padding:0 6px 0 14px;gap:10px}
#sgBar .ct{font-weight:500;color:#6B7280;font-variant-numeric:tabular-nums}
#sgBar .sep{width:1px;height:18px;background:#E5E7EB}
#sgBar .stop{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:8px;background:#F3F4F6;font:600 12.5px/1 Inter,sans-serif;color:#111827;cursor:pointer}
#sgBar .stop:hover{background:#E5E7EB}
@keyframes sgSpin{to{transform:rotate(360deg)}}
@keyframes sgSk{from{background-position:200% 0}to{background-position:-200% 0}}
@keyframes sgFade{from{opacity:0;transform:translateY(4px)}}
@keyframes sgPop{0%{opacity:0;transform:scale(.6)}60%{opacity:1;transform:scale(1.06)}100%{transform:none}}
.sgRing{width:16px;height:16px;flex:none;display:block;animation:sgSpin .8s linear infinite}

/* the box */
#sgCard{position:absolute;left:50%;top:8px;transform:translateX(-50%);z-index:21;width:min(660px,calc(100% - 32px));max-height:calc(100% - 100px);display:none;flex-direction:column;background:rgba(255,255,255,.94);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-radius:18px;box-shadow:0 24px 56px -18px rgba(17,24,39,.45),0 0 0 1px rgba(17,24,39,.08);font:14px Inter,sans-serif;color:#111827;overflow:hidden;transform-origin:50% 0}
#sgCard.open{display:flex;animation:sgGrow 240ms cubic-bezier(.23,1,.32,1)}
#sgCard.center{top:min(14%,120px)}
@keyframes sgGrow{from{opacity:0;transform:translateX(-50%) scaleX(.55) scaleY(.2)}}
#sgCard .in{display:flex;align-items:flex-start;gap:10px;padding:16px 16px 4px}
#sgCard .in>.phb{margin:-5px 0 0 -4px;width:36px;height:36px}
#sgCard textarea{flex:1;box-sizing:border-box;min-height:26px;max-height:180px;resize:none;border:0;outline:0;background:none;font:16px/1.55 Inter,sans-serif;color:#111827;padding:0}
#sgCard textarea::placeholder{color:#6B7280}
#sgCard .pc{display:flex;align-items:center;gap:10px;margin:6px 16px 2px 42px;padding:6px;border-radius:12px;background:#F3F4F6;width:max-content;max-width:calc(100% - 58px)}
#sgCard .pc img{width:64px;height:48px;object-fit:cover;border-radius:8px;display:block}
#sgCard .pc span{font:600 12.5px Inter,sans-serif;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sgCard .pc small{display:block;font-weight:500;color:#6B7280}
#sgCard .pc button{width:26px;height:26px;border:0;border-radius:7px;background:none;color:#6B7280;cursor:pointer;display:flex;align-items:center;justify-content:center}
#sgCard .pc button:hover{background:#E5E7EB;color:#111827}
#sgCard .sgTl{display:flex;align-items:center;gap:6px;padding:6px 12px 12px 12px;position:relative}
#sgCard .sgTl .sp{flex:1}
#sgCard .ib{width:34px;height:34px;border-radius:9px;border:0;background:none;color:#4B5563;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform 120ms ease-out}
#sgCard .ib:hover{background:rgba(17,24,39,.06);color:#111827}
#sgCard .ib:active{transform:scale(.94)}
#sgCard .go{width:34px;height:34px;border-radius:50%;border:0;background:#2563EB;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:transform 120ms ease-out,opacity 120ms}
#sgCard .go:disabled{opacity:.35;cursor:default}
#sgCard .go:not(:disabled):active{transform:scale(.94)}
#sgCard .mp{height:32px;display:flex;align-items:center;gap:7px;padding:0 9px;border-radius:9px;border:0;background:none;font:600 13px Inter,sans-serif;color:#374151;cursor:pointer}
#sgCard .mp:hover{background:rgba(17,24,39,.06)}
#sgCard .mp.flat{cursor:default}
#sgCard .mp.flat:hover{background:none}
#sgCard .mp img{width:16px;height:16px}
#sgCard .dd{position:absolute;left:52px;top:44px;width:280px;background:#fff;border-radius:12px;box-shadow:0 16px 32px -12px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.08);padding:6px;z-index:3;display:none;max-height:320px;overflow:auto}
#sgCard .dd.open{display:block}
#sgCard .dd .gh{font-size:12px;font-weight:600;color:#4B5563;padding:8px 10px 4px}
#sgCard .dd button{width:100%;height:34px;display:flex;align-items:center;gap:8px;padding:0 10px;border-radius:8px;border:0;background:none;font:14px Inter,sans-serif;color:#111827;cursor:pointer;text-align:left}
#sgCard .dd button:hover,#sgCard .dd button.on{background:#F3F4F6}
#sgCard .dd button.on{font-weight:600}
#sgCard .dd button .ck{margin-left:auto;color:#2563EB}
#sgCard .sec{border-top:1px solid rgba(17,24,39,.07);padding:4px 6px 6px;overflow:auto;min-height:0}
#sgCard .gh2{font:600 11.5px Inter,sans-serif;color:#6B7280;padding:8px 10px 4px;text-transform:uppercase;letter-spacing:.06em}
#sgCard .it{display:flex;align-items:center;gap:10px;width:100%;height:36px;padding:0 10px;border-radius:9px;border:0;background:none;font:14px Inter,sans-serif;color:#111827;cursor:pointer;text-align:left}
#sgCard .it span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sgCard .it svg{flex:none;color:#9CA3AF}
#sgCard .it:hover,#sgCard .it.on{background:rgba(17,24,39,.06)}
#sgCard .it mark{background:#DBEAFE;color:inherit;border-radius:3px;font-weight:600}
#sgCard .st4{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:2px 10px 8px}
#sgCard .s4{border-radius:10px;border:0;padding:0;background:#fff;box-shadow:0 0 0 1px #E5E7EB;overflow:hidden;font:600 12.5px Inter,sans-serif;color:#111827;cursor:pointer;text-align:left;transition:box-shadow 140ms,opacity 140ms,transform 120ms ease-out}
#sgCard .s4:hover{box-shadow:0 0 0 1px #9CA3AF}
#sgCard .s4:active{transform:scale(.98)}
#sgCard .s4 img{width:100%;height:64px;object-fit:cover;display:block;background:#F3F4F6}
#sgCard .s4 span{display:block;padding:5px 8px 6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgCard .s4 small{display:block;font-weight:500;color:#6B7280;font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgCard .s4.on{box-shadow:0 0 0 2px #2563EB}
#sgCard .s4.dim{opacity:.45}
#sgCard .cft{display:flex;align-items:center;gap:14px;padding:8px 16px 10px;border-top:1px solid rgba(17,24,39,.07);font-size:12px;color:#4B5563;flex-wrap:wrap}
#sgCard .cft .k{font:600 11px Inter,sans-serif;border:1px solid #E5E7EB;border-radius:5px;padding:0 5px;color:#374151;background:#fff;margin-right:4px}
#sgCard .err{margin:0 16px 8px 42px;font-size:13px;color:#B91C1C}
#sgCard .empty{display:flex;align-items:center;gap:12px;margin:0 12px 10px;padding:12px 14px;border-radius:12px;background:#F3F4F6}
#sgCard .empty span{flex:1;font-size:13px;color:#374151}
#sgCard .empty b{display:block;color:#111827}
#sgCard .btn{height:32px;padding:0 12px;border-radius:9px;border:0;font:600 13px Inter,sans-serif;cursor:pointer;background:#fff;color:#111827;box-shadow:inset 0 0 0 1px #E5E7EB}
#sgCard.over{box-shadow:0 0 0 2px #2563EB,0 24px 56px -18px rgba(17,24,39,.45)}

/* the panel on the left while it builds */
body.sgPanel .pips{left:372px!important}
#sgProg{position:absolute;left:14px;top:12px;z-index:9;width:min(344px,calc(100% - 28px));max-height:calc(100% - 136px);display:none;flex-direction:column;background:rgba(255,255,255,.96);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border-radius:16px;box-shadow:0 18px 40px -16px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.07);overflow:hidden;font:13px/1.45 Inter,sans-serif;color:#111827}
#sgProg.open{display:flex}
#sgProg .hd{display:flex;align-items:center;gap:10px;padding:12px 10px 10px 14px}
#sgProg .hd .tt{flex:1;min-width:0}
#sgProg .hd b{display:block;font:650 14px Inter,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgProg .hd small{display:block;color:#6B7280;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#sgProg .gb{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:9px;border:0;font:600 12.5px Inter,sans-serif;cursor:pointer;transition:transform 120ms ease-out;background:#fff;color:#111827;box-shadow:inset 0 0 0 1px #E5E7EB;flex:none}
#sgProg .gb:hover{background:#F9FAFB}
#sgProg .gb:active{transform:scale(.97)}
#sgProg .gb.p{background:#111827;color:#fff;box-shadow:none}
#sgProg .q{margin:0 14px 10px;padding:8px 10px;border-radius:10px;background:#F3F4F6;color:#374151;font-size:12.5px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
#sgProg .photo{margin:0 14px 10px;border-radius:12px;overflow:hidden;background:#111827}
#sgProg .photo img{display:block;width:100%;max-height:200px;object-fit:cover}
#sgProg .pbar{height:3px;background:#EEF0F3;flex:none}
#sgProg .pbar i{display:block;height:100%;background:#2563EB;border-radius:0 2px 2px 0;transition:width 500ms cubic-bezier(.23,1,.32,1)}
#sgProg .body{overflow:auto;min-height:0;overscroll-behavior:contain;padding-bottom:6px}
#sgProg .step{display:flex;align-items:center;gap:8px;padding:10px 14px 6px;font:600 12.5px Inter,sans-serif;color:#111827}
#sgProg .step small{font-weight:500;color:#6B7280;margin-left:auto;font-variant-numeric:tabular-nums}
#sgProg .hint{margin:0 14px 8px;font-size:12px;color:#6B7280}
#sgProg .strip{display:flex;gap:6px;padding:4px 14px 8px;overflow:hidden;mask-image:linear-gradient(90deg,#000 85%,transparent);-webkit-mask-image:linear-gradient(90deg,#000 85%,transparent)}
#sgProg .tile{flex:none;width:52px;height:52px;border-radius:10px;background:#F3F4F6;display:flex;align-items:center;justify-content:center;overflow:hidden;animation:sgPop 380ms cubic-bezier(.23,1,.32,1) backwards}
#sgProg .tile img{max-width:88%;max-height:88%;object-fit:contain}
#sgProg .tile.sk{animation:none;background:linear-gradient(90deg,#F3F4F6 0%,#E5E7EB 50%,#F3F4F6 100%);background-size:200% 100%;animation:sgSk 1.2s ease-in-out infinite}
#sgProg .tile.mk{background:#EFF4FF}
#sgProg p.plan{margin:2px 14px 8px;color:#4B5563;font-size:12.5px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;animation:sgFade 300ms ease-out}
#sgProg ul{list-style:none;margin:0;padding:0 8px}
#sgProg li{display:flex;align-items:center;gap:9px;min-height:30px;padding:3px 8px;border-radius:8px;font-size:12.5px;color:#374151}
#sgProg li.nw{animation:sgFade 260ms ease-out backwards}
#sgProg li.at{cursor:default}
#sgProg li.at:hover{background:#EFF4FF}
#sgProg li .ki{width:22px;height:22px;border-radius:6px;background:#F3F4F6;display:flex;align-items:center;justify-content:center;flex:none;color:#4B5563}
#sgProg li .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sgProg li em{font-style:normal;font-size:11.5px;color:#6B7280;display:flex;align-items:center;gap:4px;flex:none}
#sgProg li .dot{width:12px;height:12px;border-radius:50%;border:1.5px dashed #93B4F5;box-sizing:border-box;flex:none}
#sgProg li.now{background:#F7F8FA;color:#111827;font-weight:600}
#sgProg li.now em{color:#2563EB}
#sgProg li.ok em,#sgProg li.ready em{color:#16A34A}
#sgProg li.bad em,#sgProg li.failed em{color:#B91C1C}
#sgProg li.making em,#sgProg li.testing em,#sgProg li.fixing em{color:#2563EB}
#sgProg li.waiting{color:#9CA3AF}
#sgProg li .ok{animation:sgPop 320ms cubic-bezier(.23,1,.32,1)}
#sgProg .think{margin:4px 14px 8px;font-size:12px;color:#6B7280;display:flex;gap:6px;align-items:flex-start}
#sgProg .think svg{flex:none;margin-top:2px}
#sgProg .cam{display:flex;align-items:center;gap:8px;margin:2px 14px 10px;padding:6px 8px 6px 10px;border-radius:9px;background:#FFFBEB;font-size:12px;color:#92400E}
#sgProg .cam span{flex:1}
#sgProg .cam button{border:0;background:none;font:600 12px Inter,sans-serif;color:#1D4ED8;cursor:pointer;padding:2px 4px}
#sgProg .res{display:flex;gap:12px;padding:14px 14px 4px}
#sgProg .res .ri{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:none}
#sgProg .res b{display:block;font:650 14px Inter,sans-serif;margin-bottom:2px}
#sgProg .res p{margin:0;color:#4B5563}
#sgProg .skip{display:flex;gap:8px;align-items:flex-start;margin:8px 14px 0 58px;color:#6B7280;font-size:12.5px}
#sgProg .acts{display:flex;justify-content:flex-end;gap:8px;padding:12px 14px 14px}

/* the "ready" pill above the menu bar, and the nudge to add a robot */
#sgDone{position:absolute;left:50%;bottom:84px;transform:translateX(-50%);z-index:9;display:none;align-items:center;gap:10px;height:42px;padding:0 6px 0 12px;border-radius:14px;background:#111827;color:#fff;font:600 13px Inter,sans-serif;box-shadow:0 12px 28px -10px rgba(17,24,39,.5);white-space:nowrap;max-width:calc(100% - 32px)}
#sgDone.open{display:flex;animation:sgFade 280ms cubic-bezier(.23,1,.32,1)}
#sgDone.up{bottom:132px}
#sgDone .t{overflow:hidden;text-overflow:ellipsis}
#sgDone small{font-weight:500;color:#9CA3AF;margin-left:2px}
#sgDone button{height:30px;padding:0 10px;border-radius:9px;border:0;background:rgba(255,255,255,.12);color:#fff;font:600 12.5px Inter,sans-serif;cursor:pointer;display:inline-flex;align-items:center;gap:6px;flex:none}
#sgDone button:hover{background:rgba(255,255,255,.2)}
#sgDone .x{width:30px;padding:0;justify-content:center;background:none}
#sgNudge{position:fixed;z-index:30;display:none;transform:translate(-50%,-100%);padding:8px 12px;border-radius:10px;background:#2563EB;color:#fff;font:600 12.5px Inter,sans-serif;box-shadow:0 10px 24px -8px rgba(37,99,235,.6);white-space:nowrap;pointer-events:none}
#sgNudge.open{display:block;animation:sgFade 280ms ease-out}
#sgNudge:after{content:"";position:absolute;left:50%;bottom:-5px;width:10px;height:10px;background:#2563EB;transform:translateX(-50%) rotate(45deg)}
#addRobot.sgPulse{box-shadow:0 0 0 2px #2563EB;border-radius:11px}
#sgFly{position:absolute;inset:0;z-index:25;background:rgba(17,24,39,.82);display:flex;align-items:center;justify-content:center;pointer-events:none}
#sgFly img{max-width:86%;max-height:80%;border-radius:14px;box-shadow:0 30px 60px -20px rgba(0,0,0,.6)}
@container (max-width:780px){#sgCard{top:8px}#sgCard .st4{grid-template-columns:repeat(2,minmax(0,1fr))}body.sgPanel .pips,body.sgPanel #sgBar{display:none}}
@media (prefers-reduced-motion:reduce){#sgCard.open,#sgProg li.nw,#sgProg .tile,#sgDone.open,#sgProg p.plan{animation:none}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
const stage = document.getElementById('stage');
const e = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
// A picture with a small + : add a photo (the scene bar and the box both lead with it).
const IMGPLUS = (s = 18) => `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 4.5H5.5A2.5 2.5 0 0 0 3 7v11a2.5 2.5 0 0 0 2.5 2.5h12A2.5 2.5 0 0 0 20 18v-6"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M20 16l-4.5-4.5L6 20.5"/><path d="M19 2.5v6M16 5.5h6"/></svg>`;
const BAR_REST = () => `<span class="ph" title="Add a photo">${IMGPLUS(17)}</span><span id="sgBarT">Describe a scene…</span><span class="snd" aria-hidden="true"><svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg></span>`;
const SPARK = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#2563EB" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg>';
const XS = '<svg aria-hidden="true" width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const CHEV = '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="#4B5563" stroke-width="1.6" stroke-linecap="round"><path d="M3 4.5l3 3 3-3"/></svg>';
const SEND = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
const CLOCK = '<svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>';
const PIC = {franka: '/pg/static/robot_franka.png', ur5e: '/pg/static/robot_ur5e.png', aloha: '/pg/static/robot_aloha.png', fr3_duo: '/pg/static/robot_fr3_duo.png', g1: '/pg/static/robot_g1.png', piper: '/pg/static/robot_piper.png', n220: '/pg/static/robot_n220.png', crx30ia: '/pg/static/robot_crx30ia.png', rby1: '/pg/static/robot_rby1.png'};
const LOGO = {anthropic: '/static/anthropic.svg', openai: '/static/openai.svg'};

stage.insertAdjacentHTML('beforeend', `<button id="sgBar" aria-haspopup="dialog" aria-expanded="false" aria-keyshortcuts="/" title="Describe a scene (/)">${BAR_REST()}</button>
<div id="sgCard" role="dialog" aria-label="Describe a scene"></div><div id="sgProg" role="status" aria-live="polite"></div><div id="sgDone" role="status"></div>`);
document.body.insertAdjacentHTML('beforeend', '<div id="sgNudge">Now add a robot</div>');
const bar = document.getElementById('sgBar'), card = document.getElementById('sgCard'), prog = document.getElementById('sgProg');
const done = document.getElementById('sgDone'), nudge = document.getElementById('sgNudge');
const G = {open: false, photo: null, prompt: '', model: '', models: [], fromRun: {}, recent: [], sel: -1, err: '', build: null, poll: 0, grabbed: false, autoFor: null};

const itemsCat = () => (S.cat && S.cat.items) || [];
const item = (id) => itemsCat().find(x => x.id === id) || {id, label: id, thumb: `/pg/thumb/${id}.png`};
const modelInfo = (id) => G.models.find(m => m.id === id) || null;

// ------------------------------------------------ ready-made scenes the box offers
// The four one-click scenes (scenegen.PRESETS), and while you type also the free starter rooms
// (WetRobo's two labs, LIBERO's 12 rooms) that match your words. Tab or a click puts one down as it is.
const PRESETS = [
  {k: 'kitchen', name: 'Kitchen', sub: 'Make breakfast', img: '/pg/static/scene_kitchen.jpg', words: 'kitchen breakfast cook cooking coffee espresso toast microwave fridge fruit home food meal'},
  {k: 'wetlab', name: 'Wet lab', sub: 'Load a centrifuge', img: '/pg/static/scene_wetlab.jpg', words: 'wet lab laboratory bench centrifuge pipette tube tubes biology bio sample plate reader fume hood incubator'},
  {k: 'factory', name: 'Factory', sub: 'Sort parts', img: '/pg/static/scene_factory.jpg', words: 'factory assembly line conveyor parts sort sorting warehouse boxes totes pallet forklift gearbox'},
  {k: 'car', name: 'Car assembly', sub: 'Fit a wheel', img: '/pg/static/scene_car.jpg', words: 'car assembly automotive wheel hood vehicle auto engine brake garage'},
];
const LABS = [
  {k: 'wetrobo_x', name: 'Incubator lab X', sub: 'WetRobo', img: '/pg/static/wetrobo/lab_x.jpg', words: 'lab laboratory incubator petri dish bottle biology wetrobo cell culture'},
  {k: 'wetrobo_y', name: 'Incubator lab Y', sub: 'WetRobo', img: '/pg/static/wetrobo/lab_y.jpg', words: 'lab laboratory incubator petri dish bottle biology wetrobo cell culture'},
];
let ROOMS = null;          // LIBERO's rooms, loaded the first time you type
async function loadRooms() {
  if (ROOMS) return;
  ROOMS = [];
  try {
    const L = (typeof S !== 'undefined' && S.LB) || await api('/pg/libero');
    if (typeof S !== 'undefined') S.LB = L;
    ROOMS = ((L && L.rooms) || []).map(r => ({k: 'libero:' + r.id, room: r.id, name: r.name, sub: 'LIBERO room', img: `/pg/static/libero/${r.id}.jpg`, words: `${r.name} libero home house room`}));
  } catch (err) { ROOMS = []; }
}
const words = (q) => String(q || '').toLowerCase().split(/[^a-z0-9]+/).filter(w => w.length >= 3);
function score(r, q) {
  const have = (r.name + ' ' + r.words).toLowerCase().split(/[^a-z0-9]+/);
  return words(q).reduce((a, w) => a + (have.some(h => h.startsWith(w) || (w.length > 4 && w.startsWith(h) && h.length > 3)) ? 1 : 0), 0);
}
// The four cards and the one Tab would put down (the closest match), for what's typed so far.
function readyFor(q) {
  if (!words(q).length) return {cards: PRESETS, lit: null};
  const all = PRESETS.concat(LABS, ROOMS || []).map((r, i) => ({r, s: score(r, q), i})).sort((a, b) => b.s - a.s || a.i - b.i);
  if (!all[0].s) return {cards: PRESETS, lit: null};
  return {cards: all.slice(0, 4).map(x => x.r), lit: all[0].r, scores: new Map(all.map(x => [x.r.k, x.s]))};
}
async function placeReady(r) {
  closeCard();
  if (r.k.startsWith('libero:')) { await holdPhysics(); startPlacing('franka', 'libero', r.room, true); return; }
  if (r.k.startsWith('wetrobo_')) { await holdPhysics(); startPlacing('franka', r.k, '', true); return; }
  preset(r.k);
}

// ------------------------------------------------ the box
function defaultModel() {
  // Scenes are built by the strongest model you have: one company, its strongest model; both,
  // the strongest model of the company your last task run used (Anthropic if none yet).
  if (modelInfo(G.model)) return G.model;
  let last = '';
  try { last = localStorage.getItem('pgLastModel') || ''; } catch (err) {}
  last = G.fromRun[last] || last;
  const lastCo = (modelInfo(last) || {}).provider || (/^(gpt|codex)/.test(last) ? 'openai' : /^claude/.test(last) ? 'anthropic' : '');
  const tops = G.models.filter(m => m.default);
  return ((lastCo && tops.find(m => m.provider === lastCo)) || tops[0] || G.models[0] || {}).id || '';
}

async function loadInfo() {
  const r = await api('/pg/scenegen/info', {});
  if (!r || !r.ok) return;
  G.models = r.models || []; G.fromRun = r.from_run || {}; G.recent = r.recent || [];
  G.model = defaultModel();
  G.loaded = true;
  if (r.build && r.build.active && !(G.build && G.build.active)) follow(r.build);
}

async function openCard(center = false) {
  if (G.build && G.build.active) return;
  if (document.body.classList.contains('watch') || !document.body.classList.contains('freeplay')) return;
  hideDone();
  G.open = true; G.sel = -1; G.err = '';
  bar.setAttribute('aria-expanded', 'true');
  document.body.classList.add('sgOpen');
  card.classList.toggle('center', !!center);
  card.classList.add('open');
  draw(true);
  await loadInfo();
  if (G.open) draw();
}
function closeCard() {
  if (!G.open) return;
  G.open = false; bar.setAttribute('aria-expanded', 'false');
  card.classList.remove('open', 'center', 'over');
  document.body.classList.remove('sgOpen');
}

function modelBtn() {
  const m = modelInfo(G.model);
  if (!m) return '';
  const many = G.models.length > 1;
  return `<button class="mp${many ? '' : ' flat'}" id="sgMp" ${many ? 'aria-haspopup="listbox" aria-expanded="false"' : 'tabindex="-1"'}><img src="${LOGO[m.provider]}" alt="">${e(m.label)}${many ? CHEV : ''}</button>`;
}
function modelMenu() {
  const by = {};
  for (const m of G.models) (by[m.provider] = by[m.provider] || []).push(m);
  return `<div class="dd" id="sgDd" role="listbox">` + Object.entries(by).map(([p, ms]) =>
    `<div class="gh">${p === 'anthropic' ? 'Anthropic' : 'OpenAI'}</div>` + ms.map(m =>
      `<button role="option" data-m="${m.id}" class="${m.id === G.model ? 'on' : ''}" aria-selected="${m.id === G.model}"><img src="${LOGO[m.provider]}" alt="" width="16" height="16">${e(m.label)}${m.id === G.model ? '<span class="ck">✓</span>' : ''}</button>`).join('')).join('') + '</div>';
}
function marked(text, q) {
  const ws = words(q);
  if (!ws.length) return e(text);
  return e(text).replace(new RegExp(`\\b(${ws.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'gi'), '<mark>$1</mark>');
}
const recentsFor = (q) => {
  const ws = words(q);
  if (!ws.length) return G.recent.slice(0, 3);
  return G.recent.filter(p => { const l = p.toLowerCase(); return ws.some(w => l.includes(w)); }).slice(0, 4);
};

// The whole box, drawn again only for what changes (typing redraws the lists, not the text).
function draw(first = false) {
  if (!G.open) return;
  const can = !!G.models.length;
  card.innerHTML = `<div class="in"><button class="phb" id="sgPh" aria-label="Add a photo" title="Add a photo: the AI rebuilds what it sees">${IMGPLUS()}</button><textarea id="sgTa" rows="1" placeholder="${G.photo ? 'Add a note for the AI (optional): what to leave out, which way doors open…' : 'Describe a scene: the place, the robot, what it should do…'}" aria-label="Describe the scene">${e(G.prompt)}</textarea></div>
<div id="sgPc"></div>
${G.err ? `<p class="err">${e(G.err)}</p>` : ''}
<div class="sgTl">${modelBtn()}<span class="sp"></span><button class="go" id="sgGo" aria-label="Build the scene">${SEND}</button>${modelMenu()}</div>
${can || !G.loaded ? '' : `<div class="empty"><span><b>Connect an AI model to build from your words</b>Scenes are built by your own Anthropic or OpenAI account. The ready scenes below work without one.</span><button class="btn" id="sgSet">Open Settings</button></div>`}
<div class="sec" id="sgLists"></div><div class="cft" id="sgFoot"></div><input type="file" id="sgFile" accept="image/*" hidden>`;
  const ta = document.getElementById('sgTa');
  const grow = () => { ta.style.height = 'auto'; ta.style.height = Math.min(180, ta.scrollHeight) + 'px'; };
  ta.oninput = () => { G.prompt = ta.value; G.sel = -1; G.err = ''; grow(); lists(); if (words(G.prompt).length) loadRooms().then(() => G.open && lists()); };
  ta.onkeydown = keys;
  grow();
  photoChip(); lists(); wire();
  setTimeout(() => { if (G.open && document.activeElement !== ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }, first ? 30 : 0);
}
function photoChip() {
  const pc = document.getElementById('sgPc');
  if (!pc) return;
  pc.innerHTML = G.photo ? `<div class="pc"><img src="${G.photo.url}" alt="Your photo"><span>${e(G.photo.name)}<small>The AI rebuilds everything it sees. You add robots after.</small></span><button id="sgPhX" aria-label="Remove the photo">${XS}</button></div>` : '';
  const x = document.getElementById('sgPhX');
  if (x) x.onclick = () => { G.photo = null; draw(); };
}
function lists() {
  const box = document.getElementById('sgLists'), foot = document.getElementById('sgFoot'), go = document.getElementById('sgGo');
  if (!box) return;
  const q = G.prompt, rec = G.photo ? [] : recentsFor(q), rd = G.photo ? {cards: [], lit: null} : readyFor(q);
  G.shown = {rec, rd};
  if (G.sel >= rec.length) G.sel = rec.length - 1;
  const typed = !!words(q).length;
  box.innerHTML = (rec.length ? `<div class="gh2">Recent</div>` + rec.map((p, i) => `<button class="it${i === G.sel ? ' on' : ''}" data-rec="${i}">${CLOCK}<span>${marked(p, q)}</span></button>`).join('') : '')
    + (rd.cards.length ? `<div class="gh2">${typed && rd.lit ? 'Closest ready scene' : 'Or start from a ready scene'}</div><div class="st4">${rd.cards.map(r =>
      `<button class="s4${rd.lit && r.k === rd.lit.k ? ' on' : ''}${rd.lit && r.k !== rd.lit.k ? ' dim' : ''}" data-ready="${e(r.k)}" title="Put ${e(r.name)} down as it is"><img src="${r.img}" alt="" onerror="this.style.visibility='hidden'"><span>${e(r.name)}<small>${e(r.sub)}</small></span></button>`).join('')}</div>` : '');
  box.style.display = box.innerHTML ? '' : 'none';
  const can = !!G.models.length;
  if (go) go.disabled = !can || !(G.photo || q.trim() || G.sel >= 0);
  foot.innerHTML = G.photo
    ? `<span><span class="k">↵</span>build from the photo</span><span><span class="k">esc</span>hide</span>`
    : typed
    ? `<span><span class="k">↵</span>build from your words</span>${rd.lit ? `<span><span class="k">⇥</span>put down ${e(rd.lit.name)} as it is</span>` : ''}<span><span class="k">esc</span>hide</span>`
    : `<span><span class="k">↑↓</span>pick</span><span><span class="k">↵</span>build</span><span><span class="k">esc</span>hide, the box goes back to the top bar</span>`;
  box.querySelectorAll('[data-rec]').forEach(b => b.onclick = () => { G.prompt = rec[+b.dataset.rec]; G.sel = -1; draw(); });
  box.querySelectorAll('[data-ready]').forEach(b => b.onclick = () => { const r = rd.cards.find(x => x.k === b.dataset.ready); if (r) placeReady(r); });
}
function keys(ev) {
  const rec = (G.shown && G.shown.rec) || [], lit = G.shown && G.shown.rd && G.shown.rd.lit;
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); go(); return; }
  if (ev.key === 'Tab' && !ev.shiftKey && lit) { ev.preventDefault(); placeReady(lit); return; }
  if ((ev.key === 'ArrowDown' || ev.key === 'ArrowUp') && rec.length && (!G.prompt.includes('\n'))) {
    ev.preventDefault();
    G.sel = ev.key === 'ArrowDown' ? Math.min(rec.length - 1, G.sel + 1) : Math.max(-1, G.sel - 1);
    lists();
  }
}
function wire() {
  const on = (id, f) => { const n = document.getElementById(id); if (n) n.onclick = f; };
  on('sgGo', go);
  on('sgSet', () => { closeCard(); window.openSettings && window.openSettings('general'); });
  on('sgPh', () => document.getElementById('sgFile').click());
  const file = document.getElementById('sgFile');
  file.onchange = () => { if (file.files[0]) readPhoto(file.files[0]); };
  const mp = document.getElementById('sgMp'), dd = document.getElementById('sgDd');
  if (mp && dd && !mp.classList.contains('flat')) mp.onclick = (ev) => { ev.stopPropagation(); const o = !dd.classList.contains('open'); dd.classList.toggle('open', o); mp.setAttribute('aria-expanded', o); };
  card.querySelectorAll('[data-m]').forEach(b => b.onclick = () => { G.model = b.dataset.m; draw(); });
}
// A photo dropped on the box, pasted, or chosen: made small enough to send (longest side 1600 px, JPEG).
card.addEventListener('dragover', (ev) => { if (ev.dataTransfer && [...ev.dataTransfer.types].includes('Files')) { ev.preventDefault(); card.classList.add('over'); } });
card.addEventListener('dragleave', () => card.classList.remove('over'));
card.addEventListener('drop', (ev) => { ev.preventDefault(); card.classList.remove('over'); const f = ev.dataTransfer.files && ev.dataTransfer.files[0]; if (f) readPhoto(f); });
function readPhoto(f) {
  G.err = '';
  if (!/^image\//.test(f.type || '') && !/\.(jpe?g|png|webp|heic|heif)$/i.test(f.name || '')) { G.err = 'That file isn\'t a photo.'; draw(); return; }
  const url = URL.createObjectURL(f), im = new Image();
  im.onload = () => {
    const k = Math.min(1, 1600 / Math.max(im.naturalWidth, im.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(im.naturalWidth * k); c.height = Math.round(im.naturalHeight * k);
    c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
    URL.revokeObjectURL(url);
    const data = c.toDataURL('image/jpeg', 0.88);
    G.photo = {url: data, data, name: f.name || 'photo.jpg'};
    draw();
  };
  im.onerror = () => { URL.revokeObjectURL(url); G.err = 'This photo can\'t be read in this browser. Save it as JPG or PNG and try again.'; draw(); };
  im.src = url;
}
document.addEventListener('paste', (ev) => {
  if (!G.open) return;
  const f = [...((ev.clipboardData || {}).files || [])].find(x => /^image\//.test(x.type));
  if (f) { ev.preventDefault(); readPhoto(f); }
});

// Enter: straight to building, from the photo, a recent prompt you picked, or your words.
async function go() {
  if (!G.models.length || !G.model) return;
  const rec = (G.shown && G.shown.rec) || [];
  if (!G.photo && G.sel >= 0 && rec[G.sel]) G.prompt = rec[G.sel];
  const from = card.getBoundingClientRect();
  if (G.photo) {
    G.last = {kind: 'photo', body: {photo: G.photo.data, note: G.prompt.trim(), model: G.model}};
    G.photoUrl = G.photo.url;
  } else {
    if (!G.prompt.trim()) return;
    G.last = {kind: 'go', body: {prompt: G.prompt.trim(), model: G.model}};
  }
  const btn = document.getElementById('sgGo'); if (btn) btn.disabled = true;
  const r = await start(G.last);
  if (!r) { if (btn) btn.disabled = false; return; }
  const p = G.prompt.trim();
  if (p && !G.photo) G.recent = [p].concat(G.recent.filter(x => x !== p)).slice(0, 10);
  const photo = G.photo;
  G.prompt = ''; G.photo = null;
  closeCard();
  follow(r.build, photo ? null : from);
  if (photo) flyPhoto(photo.url);
}
async function start(last) {
  G.err = '';
  const r = await api(last.kind === 'photo' ? '/pg/scenegen/photo' : '/pg/scenegen/go', last.body);
  if (!r || !r.ok) {
    const msg = (r && r.error) || 'Something went wrong.';
    if (G.open) { G.err = msg; draw(); } else toast(msg);
    return null;
  }
  return r;
}
// The photo fills the view for a moment, then shrinks into the panel's photo.
function flyPhoto(url) {
  stage.insertAdjacentHTML('beforeend', `<div id="sgFly"><img src="${url}" alt=""></div>`);
  const fly = document.getElementById('sgFly'), im = fly.querySelector('img');
  setTimeout(() => {
    const to = prog.querySelector('.photo img'), a = im.getBoundingClientRect();
    if (!to || !im.animate) { fly.remove(); return; }
    const b = to.getBoundingClientRect();
    fly.animate([{background: 'rgba(17,24,39,.82)'}, {background: 'rgba(17,24,39,0)'}], {duration: 520, fill: 'forwards'});
    im.animate([{transform: 'none'}, {transform: `translate(${b.left + b.width / 2 - (a.left + a.width / 2)}px,${b.top + b.height / 2 - (a.top + a.height / 2)}px) scale(${b.width / a.width})`}],
      {duration: 520, easing: 'cubic-bezier(.23,1,.32,1)', fill: 'forwards'}).onfinish = () => fly.remove();
  }, 750);
}

// ------------------------------------------------ the build, as it goes
function follow(b, from = null) {
  G.build = b; G.grabbed = false; G.rows = []; G.tiles = 0; G.panelKey = {};
  hideDone();
  if (window.V3) window.V3.setFollow(true);
  prog.innerHTML = '';
  drawProg();
  if (from && prog.animate) {        // the box slides into the panel
    const to = prog.getBoundingClientRect();
    prog.animate([{transform: `translate(${from.left - to.left}px,${from.top - to.top}px) scale(${from.width / to.width},${Math.min(1.4, from.height / Math.max(1, to.height))})`, opacity: 0.4, transformOrigin: '0 0'},
      {transform: 'none', opacity: 1, transformOrigin: '0 0'}], {duration: 380, easing: 'cubic-bezier(.23,1,.32,1)'});
  }
  clearInterval(G.poll);
  if (typeof render === 'function' && S.scene) render();      // Add robot steps aside while it builds
  G.poll = setInterval(async () => {
    const id = G.poll;
    const r = await api('/pg/scenegen/status', {});
    // a slow answer from a poll this one has replaced or ended (a scene build keeps the server busy)
    if (!r || !r.ok || !r.build || id !== G.poll) return;
    const was = G.build && G.build.active;
    G.build = r.build; drawProg();
    if (typeof refresh === 'function' && r.build.objects !== (G.seen || 0)) { G.seen = r.build.objects; refresh(); }
    if (was && !r.build.active) {
      clearInterval(G.poll); G.poll = 0;
      if (r.build.phase === 'done' && r.build.task) {
        for (const u of r.build.stations) S.drafts[u] = r.build.task;
        S.taskFor = null;
        if (typeof saveDrafts === 'function') saveDrafts();
      }
      if (r.build.phase === 'done') ready(r.build);
      setTimeout(() => { if (window.V3 && !(G.build && G.build.active)) window.V3.setFollow(true); }, 2500);
      if (typeof refresh === 'function') refresh();
    }
  }, 600);
}
// You move the view while it builds: the camera stops following the build (until it ends).
const grab = (ev) => {
  if (!(G.build && G.build.active) || G.grabbed) return;
  if (ev.target.closest && ev.target.closest('#sgProg,#sgCard,#sgDone,#sbar,#pips,.pips,#right,#sessNav,.tl,.bl')) return;
  if (!stage.contains(ev.target)) return;
  G.grabbed = true;
  if (window.V3) window.V3.setFollow(false);
  G.panelKey.cam = null; drawProg(true);
};
stage.addEventListener('pointerdown', grab, true);
stage.addEventListener('wheel', grab, {capture: true, passive: true});

const IC = {
  robot: '<path d="M5 21h8"/><path d="M9 21v-4"/><circle cx="9" cy="14" r="3"/><path d="M11 12l5-6"/><circle cx="17" cy="5" r="2"/><path d="M18.5 6.5L21 9"/>',
  furniture: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 12h18M12 4v16"/>',
  object: '<path d="M21 8l-9-5-9 5 9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 010 10h-3"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  alert: '<path d="M12 3l9.5 17h-19z"/><path d="M12 10v4M12 17h.01"/>',
  pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  retry: '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
  cam: '<path d="M3 8a2 2 0 012-2h2l2-2h6l2 2h2a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><circle cx="12" cy="13" r="3.5"/>',
};
function PHOTO(s = 16) { return `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="2.5"/><circle cx="9" cy="11" r="2"/><path d="M21 16l-5-5-8 9"/></svg>`; }
const ic = (k, s = 16, c = 'currentColor', w = 1.75) => `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">${IC[k]}</svg>`;
const ring = (s = 16) => { const r = s / 2 - 1.5; return `<svg class="sgRing" style="width:${s}px;height:${s}px" viewBox="0 0 ${s} ${s}" aria-hidden="true"><circle cx="${s / 2}" cy="${s / 2}" r="${r}" fill="none" stroke="#DBE5FF" stroke-width="2"/><path d="M${s / 2} ${s / 2 - r}a${r} ${r} 0 0 1 ${r} ${r}" fill="none" stroke="#2563EB" stroke-width="2" stroke-linecap="round"/></svg>`; };
const cap = (s) => String(s || '').replace(/^./, c => c.toUpperCase());
const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const REST = BAR_REST;

// The panel is a few parts, each written again only when it changes, so the list keeps its
// place, hover and animations while the build moves on.
function part(name, html, where) {
  let n = prog.querySelector(`[data-part="${name}"]`);
  if (html == null) { if (n) n.remove(); delete G.panelKey[name]; return null; }
  if (!n) { n = document.createElement('div'); n.dataset.part = name; (where || prog).appendChild(n); }
  if (G.panelKey[name] !== html) { n.innerHTML = html; G.panelKey[name] = html; }
  return n;
}
function barBusy(b, text, ct) {
  bar.classList.add('busy');
  bar.innerHTML = `${ring()}<span>${e(text)}</span>${ct ? `<span class="ct">${ct}</span>` : ''}<span class="sep"></span><span class="stop" id="sgStop" role="button" tabindex="0">${ic('stop', 10)}Stop</span>`;
  const st = document.getElementById('sgStop');
  st.onclick = async (ev) => { ev.stopPropagation(); await api('/pg/scenegen/stop', {}); };
  st.onkeydown = (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); st.click(); } };
}
function barRest() { bar.classList.remove('busy'); bar.innerHTML = REST(); }

const STATE = {plan: 'Planned', now: 'Putting down…', ok: 'Landed', bad: 'Didn’t fit', waiting: 'Waiting', making: 'Making…', testing: 'Physics test…', fixing: 'Fixing…', ready: 'Passed', failed: 'Didn’t pass', done: 'Passed'};
const badge = (st) => st === 'now' || st === 'making' || st === 'testing' || st === 'fixing' ? ring(12)
  : st === 'ok' || st === 'ready' || st === 'done' ? `<span class="ok">${ic('check', 12, '#16A34A', 3)}</span>`
  : st === 'bad' || st === 'failed' ? ic('x', 12, '#DC2626', 2.6) : st === 'plan' ? '<span class="dot"></span>' : '';

// One row per thing: its kind, name and where it is. A thing with a spot on the floor lights its
// outline in 3D while you point at it.
function rows(list, ul) {
  const have = ul.children.length;
  list.forEach((r, i) => {
    let li = ul.children[i];
    const cls = `${r.state}${r.at ? ' at' : ''}`;
    const html = `<span class="ki">${ic(r.kind || 'object', 13)}</span><span class="nm">${e(r.name)}</span><em>${badge(r.state)}${STATE[r.state] || ''}</em>`;
    if (!li) {
      li = document.createElement('li'); li.className = cls + (i >= have && G.animRows ? ' nw' : ''); li.style.animationDelay = `${Math.min(8, i - have) * 40}ms`;
      li.innerHTML = html; li.dataset.k = html;
      if (r.at) { li.onmouseenter = () => hl(r.ix); li.onmouseleave = () => hl(-1); }
      ul.appendChild(li);
    } else if (li.dataset.k !== html || !li.className.startsWith(r.state)) {
      li.className = cls; li.innerHTML = html; li.dataset.k = html;
      if (r.state === 'now' && li.scrollIntoView) li.scrollIntoView({block: 'nearest'});
    }
  });
  while (ul.children.length > list.length) ul.lastChild.remove();
  G.animRows = true;
}
let hlT = 0;
function hl(i) { clearTimeout(hlT); hlT = setTimeout(() => api('/pg/scenegen/hl', {i}), i < 0 ? 120 : 40); }

function drawProg(force = false) {
  const b = G.build;
  const key = JSON.stringify(b) + (G.grabbed ? 'g' : '');
  if (key === G.progKey && !force) return;          // redraw only on a change (keeps the spinners smooth)
  G.progKey = key;
  document.body.classList.toggle('sgPanel', !!(b && b.active));
  if (!b || b.undone || (b.phase === 'done')) {
    prog.classList.remove('open'); prog.innerHTML = ''; G.panelKey = {}; barRest();
    if (!b || b.undone) { if (typeof render === 'function' && S.scene) render(); }
    return;
  }
  prog.classList.add('open');
  if (!b.active) return drawEnd(b);
  if (b.photo) return drawPhoto(b);
  const c = b.counts, placed = c.robots[0] + c.furniture[0] + c.objects[0], all = c.robots[1] + c.furniture[1] + c.objects[1];
  const mk = c.make || [0, 0];
  const title = b.title || (b.preset ? 'Ready scene' : 'Your scene');
  barBusy(b, b.phase === 'pick' ? 'Choosing robots and objects' : b.phase === 'make' ? `Making objects for ${title}` : b.phase === 'plan' ? `Planning ${title}` : `Building ${title}`,
    ['robots', 'furniture', 'objects'].includes(b.phase) ? `${placed} of ${all}` : '');
  part('hd', `<div class="hd">${SPARK}<div class="tt"><b>${e(title)}</b><small>${e(b.model || (b.preset ? 'Ready-made scene' : 'The model'))} · ${mmss(b.elapsed || 0)}</small></div><button class="gb" data-stop="1">${ic('stop', 10)}Stop</button></div>`);
  part('q', b.prompt ? `<div class="q">“${e(b.prompt)}”</div>` : null);
  const ended = (b.making || []).filter(m => m.state === 'done' || m.state === 'failed').length;
  const pct = b.phase === 'pick' ? 4 + Math.min(10, (b.elapsed || 0) / 3) : b.phase === 'make' ? 15 + 25 * Math.max(Math.min(1, (b.elapsed || 0) / 300) * 0.5, ended / Math.max(1, mk[1]))
    : b.phase === 'plan' ? (mk[1] ? 42 : 22) + Math.min(10, (b.quiet || 0) / 6) : 50 + 50 * placed / Math.max(1, all);
  part('bar', `<div class="pbar"><i style="width:${Math.min(100, pct).toFixed(1)}%"></i></div>`);
  const body = part('body', '') || prog;
  body.className = 'body';
  // the step it's on
  const step = b.phase === 'pick' ? ['Choosing robots and objects', '']
    : b.phase === 'make' ? [`Making ${mk[1] === 1 ? 'an object' : `${mk[1]} objects`} our library doesn’t have`, `${ended} of ${mk[1]}`]
    : b.phase === 'plan' ? ['Planning where everything goes', '']
    : ['Putting it all in place', `${placed} of ${all}`];
  part('step', `<div class="step">${ring(14)}${e(step[0])}<small>${step[1]}</small></div>`, body);
  // the strip of what it picked (skeletons while it picks)
  const pk = b.picked || {robots: [], items: []};
  const tiles = pk.robots.map(r => `<span class="tile"><img src="${PIC[r] || `/pg/static/robot_${r}.png`}" alt=""></span>`)
    .concat(pk.items.map(id => `<span class="tile" title="${e(item(id).label)}"><img src="${item(id).thumb}" alt="" loading="lazy"></span>`))
    .concat((b.names && b.names.make || []).map(n => `<span class="tile mk" title="${e(n)}: made by AI">${SPARK}</span>`));
  part('strip', b.phase === 'pick' ? `<div class="strip">${'<span class="tile sk"></span>'.repeat(6)}</div>`
    : tiles.length ? `<div class="strip">${tiles.map((t, i) => t.replace('class="tile', `style="animation-delay:${Math.min(i, 14) * 45}ms" class="tile`)).join('')}</div>` : null, body);
  const slow = (b.phase === 'pick' || b.phase === 'plan') && (b.quiet || 0) > 25;
  part('hint', slow ? `<p class="hint">Still working. Some models (like ChatGPT sign-ins) send their whole answer at the end, then it all appears at once.</p>` : null, body);
  part('think', b.phase === 'make' && b.thought ? `<div class="think">${SPARK.replace('width="16" height="16"', 'width="12" height="12"')}<span>${e(b.thought)}…</span></div>` : null, body);
  part('plan', b.plan ? `<p class="plan">${e(b.plan)}</p>` : null, body);
  part('cam', G.grabbed ? `<div class="cam">${ic('cam', 14, '#B45309')}<span>You moved the view, so the camera stopped following.</span><button data-follow="1">Follow</button></div>` : null, body);
  // the AI-made objects while they're made and tested, then every planned thing
  let list;
  if (b.phase === 'make' || (b.phase === 'pick')) list = (b.making || []).map(m => ({name: m.name, kind: 'object', state: m.state, at: false}));
  else list = (b.items || []).map((it, ix) => ({...it, ix}));
  let ul = body.querySelector('ul');
  if (G.listFor !== (b.phase === 'make' ? 'make' : 'items')) { if (ul) ul.remove(); ul = null; G.listFor = b.phase === 'make' ? 'make' : 'items'; G.animRows = true; }
  if (!ul) { ul = document.createElement('ul'); body.appendChild(ul); }
  rows(list, ul);
  wireProg(b);
}

function drawPhoto(b) {
  const c = b.counts, total = c.total || b.expected || 0;
  const name = b.title || 'Your photo';
  const rowsL = b.rows || [];
  const at = ['look', 'measure', 'build', 'test', 'place'].indexOf(b.phase);
  const writing = b.phase === 'look' && b.steps > 0 && b.quiet > 40;   // Codex on a ChatGPT sign-in sends nothing while it writes
  const step = b.phase === 'look' ? [writing ? 'Writing the scene' : 'Looking at the photo', b.elapsed > 20 ? mmss(b.elapsed) : '']
    : b.phase === 'measure' ? ['Measuring sizes', ''] : b.phase === 'build' ? ['Building each object', `${c.built} of ${b.expected || '?'}`]
    : b.phase === 'test' ? ['Testing each object in physics', `${c.tested} of ${total}`] : ['Putting it in your session', `${c.placed} of ${total - (b.skipped || []).length}`];
  barBusy(b, `Building ${name.replace(/^./, x => x.toLowerCase())}`, step[1]);
  part('hd', `<div class="hd">${PHOTO(16).replace('currentColor', '#2563EB')}<div class="tt"><b>${e(name)}</b><small>${e(b.model || 'The model')} · ${mmss(b.elapsed || 0)}</small></div><button class="gb" data-stop="1">${ic('stop', 10)}Stop</button></div>`);
  part('photo', G.photoUrl ? `<div class="photo"><img src="${G.photoUrl}" alt="Your photo"></div>` : null);
  const pct = [4 + Math.min(9, (b.elapsed || 0) / 60), 14, 20 + 40 * c.built / Math.max(1, b.expected || 1), 60 + 25 * c.tested / Math.max(1, total), 85 + 15 * c.placed / Math.max(1, total)][Math.max(0, at)];
  part('bar', `<div class="pbar"><i style="width:${Math.min(100, pct).toFixed(1)}%"></i></div>`);
  const body = part('body', '');
  body.className = 'body';
  part('step', `<div class="step">${ring(14)}${e(step[0])}<small>${step[1]}</small></div>`, body);
  part('q', b.note ? `<div class="q">“${e(b.note)}”</div>` : null, body);
  const heads = String(b.thinking || '').match(/\*\*([^*]+)\*\*/g);
  part('think', b.phase === 'look' || b.phase === 'measure' ? `<div class="think">${SPARK.replace('width="16" height="16"', 'width="12" height="12"')}<span>${e(heads ? heads[heads.length - 1].replace(/\*/g, '') + '…' : writing ? 'Writing its answer. Some models send it all at the end.' : 'Thinking…')}</span></div>` : null, body);
  part('cam', G.grabbed ? `<div class="cam">${ic('cam', 14, '#B45309')}<span>You moved the view, so the camera stopped following.</span><button data-follow="1">Follow</button></div>` : null, body);
  const ix = new Map((b.items || []).map((it, i) => [it.name, i]));
  const list = rowsL.map(r => ({name: r.name, kind: 'object', state: r.state, at: ix.has(r.name) && (b.items[ix.get(r.name)] || {}).at, ix: ix.get(r.name)}));
  let ul = body.querySelector('ul');
  if (!ul) { ul = document.createElement('ul'); body.appendChild(ul); }
  rows(list, ul);
  wireProg(b);
}

function drawEnd(b) {
  barRest();
  document.body.classList.remove('sgPanel');
  G.panelKey = {}; prog.innerHTML = '';
  const c = b.counts || {}, placed = b.photo ? b.objects : (c.robots[0] + c.furniture[0] + c.objects[0]);
  const undo = (b.stations || []).length || b.objects ? `<button class="gb" id="sgUndo">${ic('undo', 14)}Undo</button>` : '';
  let html;
  if (b.phase === 'stopped') {
    html = `<div class="res"><span class="ri" style="background:#F3F4F6;color:#374151">${ic('pause', 15)}</span><div><b>Stopped</b><p>${placed ? `${placed} placed. What's placed stays, or undo all of it.` : 'Nothing was placed.'}</p></div></div>
<div class="acts">${undo}<button class="gb p" id="sgOk">Done</button></div>`;
  } else {
    html = `<div class="res"><span class="ri" style="background:#FEF2F2">${ic('alert', 16, '#DC2626')}</span><div><b>Couldn't build the scene</b><p>${e(cap(b.error || 'something went wrong'))}.</p></div></div>
${(b.skipped || []).length ? `<div class="skip">${ic('info', 14, '#9CA3AF')}<span>${b.photo ? 'Failed the physics test' : 'Left out'}: ${e(b.skipped.join(', '))}</span></div>` : ''}
<div class="acts">${undo}<button class="gb" id="sgOk">Close</button>${G.last ? `<button class="gb p" id="sgRetry">${ic('retry', 14)}Try again</button>` : ''}</div>`;
  }
  prog.innerHTML = html;
  const ok = document.getElementById('sgOk'), un = document.getElementById('sgUndo'), re = document.getElementById('sgRetry');
  if (ok) ok.onclick = () => { G.build = null; drawProg(); };
  if (re) re.onclick = async () => { const r = await start(G.last); if (r) follow(r.build); };
  if (un) un.onclick = () => undoBuild(b);
}
function wireProg() {
  prog.querySelectorAll('[data-stop]').forEach(x => x.onclick = async () => { await api('/pg/scenegen/stop', {}); });
  prog.querySelectorAll('[data-follow]').forEach(x => x.onclick = () => { G.grabbed = false; if (window.V3) window.V3.setFollow(true); drawProg(true); });
}
async function undoBuild(b) {
  const r = await api('/pg/scenegen/undo', {id: b.id});
  if (!r.ok) { toast(r.error); return; }
  for (const u of b.stations || []) delete S.drafts[u];
  G.build = null; drawProg(); hideDone(); toast('Scene removed'); if (typeof refresh === 'function') refresh();
}

// ------------------------------------------------ done: a pill above the menu bar
function ready(b) {
  const sk = b.skipped || [];
  const what = b.photo ? `${b.objects} object${b.objects === 1 ? '' : 's'}` : b.task ? 'Task filled in' : '';
  done.innerHTML = `${ic('check', 16, '#4ADE80', 2.6)}<span class="t">${e(b.title || 'Your scene')} is ready${what ? ` <small>· ${e(what)}</small>` : ''}${sk.length ? ` <small>· left out ${e(sk.slice(0, 2).join(', '))}${sk.length > 2 ? '…' : ''}</small>` : ''}</span><button id="sgDUndo">${ic('undo', 13)}Undo</button><button class="x" id="sgDX" aria-label="Close">${XS}</button>`;
  done.classList.add('open');
  document.getElementById('sgDUndo').onclick = () => undoBuild(b);
  document.getElementById('sgDX').onclick = hideDone;
  clearTimeout(G.doneT); G.doneT = setTimeout(hideDone, 14000);
  if (b.photo) {                  // a photo's scene has no robot yet: point at Add robot
    const ar = document.getElementById('addRobot');
    if (ar && ar.offsetParent) {
      const r = ar.getBoundingClientRect();
      nudge.style.left = `${r.left + r.width / 2}px`; nudge.style.top = `${r.top - 10}px`;
      nudge.classList.add('open'); ar.classList.add('sgPulse'); done.classList.add('up');
      const off = () => { nudge.classList.remove('open'); ar.classList.remove('sgPulse'); done.classList.remove('up'); };
      ar.addEventListener('click', off, {once: true});
      setTimeout(off, 12000);
    }
  }
  G.build = null; drawProg();
}
function hideDone() { done.classList.remove('open', 'up'); nudge.classList.remove('open'); const ar = document.getElementById('addRobot'); if (ar) ar.classList.remove('sgPulse'); }

// ------------------------------------------------ opening and closing
bar.onclick = async (ev) => {
  if (G.build && G.build.active) return;
  const photo = ev.target.closest && ev.target.closest('.ph');
  await openCard();
  if (photo) { const f = document.getElementById('sgFile'); if (f) f.click(); }   // the picture button: straight to choosing a photo
};
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && G.open) { const dd = document.getElementById('sgDd'); if (dd && dd.classList.contains('open')) { dd.classList.remove('open'); return; } closeCard(); return; }
  if (ev.key === '/' && !G.open && !/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '') && !document.activeElement.isContentEditable
      && document.body.classList.contains('freeplay') && !document.body.classList.contains('watch')) { ev.preventDefault(); openCard(); }
});
document.addEventListener('click', (ev) => { const dd = document.getElementById('sgDd'); if (dd && dd.classList.contains('open') && !ev.target.closest('#sgDd')) dd.classList.remove('open'); });
// A click on the 3D view (or anywhere outside the box) hides it again.
document.addEventListener('pointerdown', (ev) => { if (G.open && !ev.target.closest('#sgCard,#sgBar')) closeCard(); }, true);
// The play pill (a lock message) takes the top middle while it shows: the bar steps aside.
const pill = document.getElementById('playpill');
const sync = () => document.body.classList.toggle('sgHide', !!pill && !pill.classList.contains('none') && pill.innerHTML.trim() !== '' && !(G.build && G.build.active));
if (pill) new MutationObserver(sync).observe(pill, {attributes: true, childList: true, subtree: true});
// A new, empty session: the box is already open, centred over the live 3D view (once per session).
setInterval(() => {
  if (typeof S === 'undefined' || !S.scene || typeof SID === 'undefined' || !SID || G.autoFor === SID) return;
  const sc = S.scene, b = document.body.classList;
  if (sc.mode !== 'free' || b.contains('watch') || !b.contains('freeplay')) return;
  G.autoFor = SID;
  const empty = !(sc.robots || []).length && !(sc.objects || []).length;
  if (empty && !G.open && !(G.build && G.build.active) && !document.querySelector('.modal[style*="flex"]')) openCard(true);
}, 500);
// A ready-made scene (Add station or the box): built the same way, from its own layout, no model.
async function preset(name) {
  if (G.build && G.build.active) { toast('A scene is already being built'); return; }
  const r = await api('/pg/scenegen/preset', {name});
  if (!r || !r.ok) { toast((r && r.error) || 'Something went wrong.'); return; }
  G.last = null;
  follow(r.build);
}
window.sceneGen = {open: openCard, preset, busy: () => !!(G.build && G.build.active)};
setTimeout(loadInfo, 1500);
})();
