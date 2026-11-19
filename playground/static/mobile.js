// Phones: the same Playground, laid out for a small touch screen (design: Playground canvas,
// "Phone version" row). Only applies below 761 px wide; computers are untouched.
//  - the live 3D scene fills the screen; the robot panel (rail + Chat/Files/Data/Results) becomes a
//    bottom sheet with three heights (small, half, full); the sessions list slides in from the left
//  - fingers move the view: one finger turns it, two fingers slide and pinch (no joystick)
//  - objects: tap one, tap the scene to see where it lands, then "Place here"
//  - a full-screen button hides every control so the scene fills the whole phone
// Loaded after the page's own script (uses S, $, api, uv, camera, probe, place, renderItems, markArmed,
// hideTag, setObjects, openStMenu, openPicker, openAdd, setNav).
(() => {
const MQ = matchMedia('(max-width:760px)');
const M = () => MQ.matches;
const svg = (p, s = 20) => `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC = {
  side: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  more: '<circle cx="5" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="19" cy="12" r="1.3"/>',
  target: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  robot: '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01"/>',
  station: '<path d="M3 10h18M5 10v9M19 10v9M8 10V6h8v4"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  past: '<path d="M6.5 3h11M6.5 21h11"/><path d="M7.5 3c0 4.5 4.5 6 4.5 9s-4.5 4.5-4.5 9"/><path d="M16.5 3c0 4.5-4.5 6-4.5 9s4.5 4.5 4.5 9"/>',
  set: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
};

const css = `
.m-only{display:none!important}
@media (max-width:760px){
  html,body{height:100%;overflow:hidden;overscroll-behavior:none;-webkit-tap-highlight-color:transparent}
  .m-only{display:flex!important}
  .app{height:100dvh}
  main{display:block;position:relative;height:100dvh}
  /* the scene: the whole screen */
  #stage{position:absolute!important;inset:0;margin:0!important;border-radius:0!important;box-shadow:none!important;container-type:normal!important}
  /* over the robot sheet */
  #bigCamWrap,#gal{position:fixed!important;z-index:75!important}
  #bigCamWrap{background:#0B0D12!important}
  #addModal{z-index:78!important}
  #sgScrim{position:fixed!important;z-index:78!important}
  #sgCard{position:fixed!important;z-index:79!important;top:calc(64px + env(safe-area-inset-top))!important;width:calc(100% - 20px)!important;max-height:calc(100dvh - 84px)!important}
  #runpop{z-index:76!important;align-items:stretch!important}
  #runpop .card{width:100%!important;max-width:none!important;max-height:none!important;height:100dvh;border-radius:0!important;padding:calc(14px + env(safe-area-inset-top)) 14px calc(14px + env(safe-area-inset-bottom))!important;overflow:auto}
  #runpop .hd .nm{font-size:16px}#runpop .hd .sub{display:none}
  #runpop .g8{grid-template-columns:84px 1fr 46px!important;column-gap:8px!important}
  #runpop .lb{font-size:12px;white-space:normal;line-height:1.2}
  #runpop .tt{font-size:11px}
  #rpage{z-index:77!important}
  #ssWrap{padding:0!important}
  #ss{width:100%!important;height:100dvh!important;border-radius:0!important}
  #ss .mh{padding-top:calc(16px + env(safe-area-inset-top))!important}
  .idlecard{z-index:85!important}#toast{z-index:85}
  #view{touch-action:none}
  .campad,#vbtns,#sgBar,#openRight,.bl,#axisGuide{display:none!important}
  textarea,input,select{font-size:16px!important}
  /* top row: sessions, session name, Physics */
  #mTop{position:absolute;left:10px;right:150px;top:calc(10px + env(safe-area-inset-top));z-index:8;display:flex;gap:8px;align-items:center}
  .mbtn{width:44px;height:44px;flex:none;border-radius:14px;border:0;display:flex;align-items:center;justify-content:center;padding:0;color:#111827;background:rgba(255,255,255,.94);box-shadow:0 4px 14px rgba(17,24,39,.14),0 0 0 1px rgba(17,24,39,.08)}
  #mSess{flex:1;min-width:0;height:44px;border-radius:14px;border:0;display:flex;align-items:center;gap:4px;padding:0 12px;font:600 15px Inter,sans-serif;color:#111827;background:rgba(255,255,255,.94);box-shadow:0 4px 14px rgba(17,24,39,.14),0 0 0 1px rgba(17,24,39,.08)}
  #mSess span{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:left}
  #rcol{position:absolute!important;right:10px!important;top:calc(10px + env(safe-area-inset-top))!important;left:auto!important;z-index:8;display:flex;flex-direction:column;align-items:flex-end;gap:8px}
  #rcol .fbtn{height:44px;border-radius:14px}
  #galBtn{width:44px;padding:0;justify-content:center;font-size:0;gap:0}
  /* the cameras the AI sees: two small windows, top left */
  .pips{left:10px!important;top:calc(64px + env(safe-area-inset-top))!important;bottom:auto!important;flex-direction:column;gap:8px;z-index:4}
  .pip,.pips.four .pip{width:104px!important;border-radius:10px}
  .pip img{aspect-ratio:3/2}
  .pips .pip:nth-child(n+3){display:none}
  .pcap{padding:3px 4px 3px 7px;font-size:11px}.pcap span{font-size:9px}.pcap .exp{display:none}
  body.watch .pips{top:calc(112px + env(safe-area-inset-top))!important}
  .tl{display:none!important}
  #playpill{top:calc(62px + env(safe-area-inset-top))!important;left:124px!important;right:62px;transform:none!important;max-width:none;white-space:normal;font-size:12.5px;padding:6px 10px!important}
  #toast{top:calc(64px + env(safe-area-inset-top));max-width:calc(100% - 24px);white-space:normal;text-align:center}
  .watchbanner{top:calc(62px + env(safe-area-inset-top))!important;max-width:calc(100% - 20px);white-space:normal}
  .bigcam{width:100%!important;border-radius:0}
  .bigcam img{max-height:70dvh}
  /* the robot panel: a bottom sheet */
  html body #right,html body.rclosed #right{position:fixed!important;left:0;right:0;bottom:0;width:auto!important;display:flex!important;flex-direction:column!important;z-index:50;background:#fff!important;border-radius:22px 22px 0 0;box-shadow:0 -8px 30px -10px rgba(17,24,39,.3),0 0 0 1px rgba(17,24,39,.06)!important;padding-bottom:env(safe-area-inset-bottom);transition:height 500ms cubic-bezier(.32,.72,0,1),transform 500ms cubic-bezier(.32,.72,0,1)!important;max-height:calc(100dvh - 52px)}
  body.m-half #right{height:56dvh}
  body.m-full #right{height:calc(100dvh - 52px)}
  html body.m-drag #right{transition:none!important}
  body.m-hide #right,body.m-fs #right{transform:translateY(110%)}
  #mGrab{flex:none;height:26px;display:flex!important;align-items:center;justify-content:center;touch-action:none;cursor:grab;border:0;background:transparent;width:100%;padding:0}
  #mGrab i{width:38px;height:5px;border-radius:3px;background:#D1D5DB}
  #rrail{width:auto!important;height:auto!important;flex:none;flex-direction:row!important;justify-content:flex-start;align-items:center;gap:10px!important;padding:2px 14px 8px!important;overflow-x:auto!important;overflow-y:hidden!important;background:transparent!important;border:0!important;scrollbar-width:none}
  #rrail::-webkit-scrollbar{display:none}
  #rrail #rToggle,#rrail .sep,#rrail #rPast,#rrail #rSet{display:none!important}
  #rrail .rbot,#rrail .radd{width:48px!important;height:48px!important;flex:none;border-radius:14px;-webkit-touch-callout:none;user-select:none}
  #rtip{display:none!important}
  html body #rmain,html body.rclosed #rmain{width:auto!important;flex:1;min-height:0;display:flex;flex-direction:column;padding:0!important;margin:0!important;border-radius:0!important;box-shadow:none!important;background:transparent!important}
  html body #rinner{width:auto!important;flex:1;min-height:0;height:auto!important;border-radius:0!important;box-shadow:none!important;background:transparent!important}
  #rtitle{padding:2px 14px 8px!important;touch-action:none}
  #mTabObj[hidden]{display:none!important}
  #mRMore{width:40px;height:40px;border:0;background:transparent;border-radius:10px;align-items:center;justify-content:center;padding:0;color:#374151;flex:none}
  .sidetabs{overflow-x:auto;scrollbar-width:none;margin:0 12px 6px!important}
  .sidetabs::-webkit-scrollbar{display:none}
  .sidetabs button{height:40px!important;font-size:14px!important;flex:1 0 auto}
  #feed{padding:10px 14px!important}
  .taskcard{margin:0 10px 10px!important;border-radius:16px!important}
  .taskcard textarea{min-height:48px!important}
  .tcrow .mdl,.tcrow .primary{height:44px!important}
  .tcrow .primary{padding:0 18px!important;font-size:15px}
  /* small sheet: who it is and the task box (or Stop) only */
  body.m-peek .sidetabs,body.m-peek .chathead,body.m-peek #feed,body.m-peek #jumpBtn,body.m-peek #filespane,body.m-peek #datapane,body.m-peek #resultspane{display:none!important}
  body.m-peek #chatpane{display:flex!important;flex:none}
  html body.m-peek #rinner,html body.m-peek #rmain{flex:none}
  /* sessions: a drawer from the left */
  #sessNav,#sessNav.closed{position:fixed!important;left:0;top:0;bottom:0;width:min(320px,86vw)!important;z-index:70;transform:translateX(-105%);transition:transform 500ms cubic-bezier(.32,.72,0,1);touch-action:pan-y;box-shadow:12px 0 30px -12px rgba(17,24,39,.35);border-right:0!important}
  body.m-nav #sessNav{transform:none}
  #sessNav .in{width:100%!important;padding-top:calc(14px + env(safe-area-inset-top))!important;padding-bottom:calc(14px + env(safe-area-inset-bottom))!important}
  #navClose{width:44px;height:44px}
  .srow{min-height:48px}
  #mScrim{position:fixed;inset:0;z-index:65;background:rgba(17,24,39,.4);display:none!important}
  body.m-nav #mScrim,body.m-addopen #mScrim{display:block!important}
  .mlinks{flex-direction:column;gap:2px}
  .mlinks button,.mlinks a{display:flex;align-items:center;gap:12px;height:46px;padding:0 10px;border-radius:10px;border:0;background:transparent;font:500 15px Inter,sans-serif;color:#111827;text-decoration:none;text-align:left;width:100%}
  /* the object library: a tall sheet */
  #objDrawer{position:fixed!important;left:0!important;right:0!important;bottom:0!important;top:calc(64px + env(safe-area-inset-top))!important;width:auto!important;max-width:none!important;border-radius:22px 22px 0 0!important;z-index:72!important;transform:translateY(105%)!important;opacity:1!important;transition:transform 500ms cubic-bezier(.32,.72,0,1)!important;padding-bottom:env(safe-area-inset-bottom)}
  body.objopen #objDrawer{transform:none!important;pointer-events:auto}
  #objTab{display:none!important}
  #objDrawer .tabs{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
  #objDrawer .tabs::-webkit-scrollbar{display:none}
  #objDrawer .tabs button{flex:none;height:34px}
  #objClose{width:44px;height:44px}
  #objDrawer .card,#objDrawer .pin{cursor:pointer}
  /* the pin board on a phone: back button + category name in the header instead of breadcrumbs,
     one swipeable row of pills that fades at the edge, a big search, larger names */
  #objDrawer #crumbs,#objDrawer .tabs button.up,#objDrawer .tabs .here{display:none!important}
  #objDrawer .dh{gap:6px;min-height:52px}
  #objDrawer.deep .dh{padding-left:6px!important}
  #objDrawer.deep .dh h2{display:none}
  #objDrawer.deep .dh .mback{display:flex;flex:none;width:44px;height:44px;border:0;border-radius:999px;background:transparent;align-items:center;justify-content:center}
  #objDrawer.deep .dh .mtitle{display:flex;flex-direction:column;flex:1;min-width:0}
  #objDrawer .dh .mtrail{font-size:12.5px;color:#4B5563;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #objDrawer .dh .mname{font-size:20px;font-weight:700;line-height:1.2;color:#111827;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #objDrawer .dh h2{font-size:20px!important}
  #objDrawer #search{height:46px;font-size:16px}
  #objDrawer .tabs{-webkit-mask-image:linear-gradient(90deg,#000 calc(100% - 36px),transparent);mask-image:linear-gradient(90deg,#000 calc(100% - 36px),transparent);padding-right:30px}
  #objDrawer .tabs button{height:40px!important;padding:0 16px;font-size:14px}
  #objDrawer #items{padding:2px 12px 16px}
  #objDrawer .mcols{gap:10px}
  #objDrawer .pin .n{font-size:14px}
  #objDrawer .pin .w{font-size:12px}
  /* placing an object: a preview, then Place here */
  #mPlace{position:fixed;left:0;right:0;bottom:0;z-index:60;background:#fff;border-radius:22px 22px 0 0;box-shadow:0 -8px 30px -10px rgba(17,24,39,.3);padding:14px 16px calc(14px + env(safe-area-inset-bottom));flex-direction:column;gap:12px}
  #mPlace[hidden]{display:none!important}
  #mPlace .ph{display:flex;align-items:center;gap:12px}
  #mPlace img{width:48px;height:48px;border-radius:12px;object-fit:contain;background:#F3F4F6}
  #mPlace b{display:block;font-size:16px}#mPlace .ph span{font-size:13px;color:#4B5563}
  #mPlace .acts{display:flex;gap:10px}
  .mgo{flex:1;height:48px;border-radius:12px;border:1px solid #D1D5DB;background:#fff;font:600 15px Inter,sans-serif;color:#111827}
  .mgo.blue{background:#2563EB;border-color:#2563EB;color:#fff}
  .mgo:disabled{opacity:.45}
  /* the selected object or robot: a sheet over the robot panel */
  #objPanel{position:fixed!important;left:0!important;right:0!important;bottom:0!important;top:auto!important;width:auto!important;max-height:64dvh!important;border-radius:22px 22px 0 0!important;z-index:58!important;padding:14px 16px calc(16px + env(safe-area-inset-bottom))!important;background:#fff!important;box-shadow:0 -8px 30px -10px rgba(17,24,39,.3)!important}
  #objPanel .rrow button,#objPanel .rrow input{height:44px!important;min-width:44px}
  #objPanel .poses button{min-height:56px}
  #objPanel .ghostbtn{height:44px}
  /* menus and pickers: sheets from the bottom */
  .stmenu{left:8px!important;right:8px!important;top:auto!important;bottom:calc(8px + env(safe-area-inset-bottom))!important;min-width:0!important;border-radius:18px!important;padding:6px!important;transform-origin:bottom center!important;box-shadow:0 0 0 100vmax rgba(17,24,39,.4)!important;z-index:80!important}
  .stmenu button{height:50px!important;font-size:16px!important;padding:0 14px!important}
  #rpk{left:0!important;right:0!important;bottom:0!important;top:auto!important;width:auto!important;max-width:none!important;max-height:86dvh;overflow:auto;border-radius:22px 22px 0 0!important;padding-bottom:env(safe-area-inset-bottom);box-shadow:0 0 0 100vmax rgba(17,24,39,.4)!important}
  #rpk .caret{display:none}
  #addModal{padding:0!important;align-items:flex-end!important}
  #addModal .am{border-radius:22px 22px 0 0!important;max-height:88dvh!important;padding:18px 16px calc(18px + env(safe-area-inset-bottom))!important}
  #mAdd{position:fixed;left:8px;right:8px;bottom:calc(8px + env(safe-area-inset-bottom));z-index:80;flex-direction:column;gap:8px}
  #mAdd[hidden]{display:none!important}
  #mAdd .grp{background:#fff;border-radius:18px;overflow:hidden}
  #mAdd .grp button{display:flex;align-items:center;gap:14px;width:100%;min-height:58px;border:0;border-bottom:1px solid #F0F1F3;background:#fff;padding:8px 16px;font:500 16px Inter,sans-serif;color:#111827;text-align:left}
  #mAdd .grp button:last-child{border-bottom:0}
  #mAdd .grp small{display:block;font-size:13px;color:#4B5563;font-weight:400}
  #mAdd .cancel{height:54px;border-radius:18px;border:0;background:#fff;font:600 16px Inter,sans-serif;color:#111827}
  /* full screen: only the scene */
  #mFloat{position:absolute;right:10px;z-index:7;flex-direction:column;gap:8px;top:calc(162px + env(safe-area-inset-top))}
  body.m-fs #mTop,body.m-fs #rcol,body.m-fs .pips,body.m-fs .tl,body.m-fs #mFloat,body.m-fs #objPanel,body.m-fs .watchbanner{display:none!important}
  #mFsX{position:absolute;right:12px;top:calc(12px + env(safe-area-inset-top));z-index:9;opacity:.8;display:none!important}
  body.m-fs #mFsX{display:flex!important}
  body.m-fs.m-fsui #mTop,body.m-fs.m-fsui #rcol{display:flex!important}
  body.m-fs.m-fsui #mFsX{top:calc(64px + env(safe-area-inset-top));opacity:1}
  body.m-placing #mFloat,body.m-placing .pips{display:none!important}
  /* the sheet follows the keyboard (browsers that don't resize the page for it) */
  html body #right{bottom:var(--kb,0px)}
  /* touch basics */
  button,a,[role=button],[role=tab],.rbot,.radd,#objDrawer .card,#objDrawer .pin{touch-action:manipulation;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none}
  #feed,#items,#filespane,#datapane,#resultspane,#sessNav .in,#rpk,#addModal .am,#runpop .card,#rpage,#gal,#objPanel,#ss,#ss *,#objDrawer,#sgCard{overscroll-behavior:contain}
  #rrail{touch-action:pan-x}
  #sessNav,#sessNav *{touch-action:pan-y!important}
  /* fingers need 44 px */
  #rSwap{height:40px!important;padding:0 12px!important}
  .taskcard .step button{width:40px!important;height:40px!important}
  #objX,#rpk .x,#gal .gx{width:44px!important;height:44px!important}
  .infobtn{position:relative}.infobtn::before{content:"";position:absolute;inset:-11px}
  /* drag handles on the sheets */
  #objDrawer .dh,#objPanel .ohd,#rpk .ph,#mAdd{touch-action:none}
  #objDrawer .dh::before,#rpk .ph::before{content:"";position:absolute;left:50%;top:7px;width:38px;height:5px;margin-left:-19px;border-radius:3px;background:#D1D5DB}
  #objDrawer .dh,#rpk .ph{position:relative;padding-top:18px!important}
  /* small things come in quickly */
  #mAdd:not([hidden]){animation:mUp 220ms cubic-bezier(.23,1,.32,1)}
  body.m-nav #mScrim,body.m-addopen #mScrim{animation:mFade 220ms ease-out}
  @keyframes mUp{from{transform:translateY(24px);opacity:0}}
  @keyframes mFade{from{opacity:0}}
}
@media (max-width:760px) and (pointer:coarse){html{-webkit-text-size-adjust:100%;text-size-adjust:100%}}
@media (max-width:760px) and (prefers-reduced-motion:reduce){#right,#sessNav,#objDrawer{transition:none!important}#mAdd,#mScrim{animation:none!important}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);

const stage = $('stage'), right = $('right'), view = $('view'), body = document.body;
// ---- new pieces (hidden on computers)
stage.insertAdjacentHTML('beforeend',
  `<div id="mTop" class="m-only"><button class="mbtn" id="mNav" aria-label="Sessions" aria-controls="sessNav">${svg(IC.side)}</button>`
  + `<button id="mSess" aria-label="Sessions"><span id="mSessName">Playground</span>${svg(IC.down, 16)}</button></div>`
  + `<div id="mFloat" class="m-only"><button class="mbtn" id="mReset" aria-label="Reset the view">${svg(IC.target)}</button>`
  + `<button class="mbtn" id="mFs" aria-label="Full screen scene">${svg(IC.expand)}</button></div>`
  + `<button class="mbtn m-only" id="mFsX" aria-label="Leave full screen">${svg(IC.x)}</button>`);
document.body.insertAdjacentHTML('beforeend',
  `<div id="mScrim" class="m-only"></div>`
  + `<div id="mPlace" class="m-only" hidden role="dialog" aria-label="Place the object"><div class="ph"><img id="mPlImg" alt=""><div><b id="mPlName">Placing</b><span id="mPlHint">Tap the scene where it should go</span></div></div>`
  + `<div class="acts"><button class="mgo" id="mPlCancel">Cancel</button><button class="mgo blue" id="mPlGo" disabled>Place here</button></div></div>`
  + `<div id="mAdd" class="m-only" hidden role="dialog" aria-label="Add"><div class="grp">`
  + `<button id="mAddRobot">${svg(IC.robot, 22)}<span>Add a robot<small>Pick a robot, then tap the floor</small></span></button>`
  + `<button id="mAddStation">${svg(IC.station, 22)}<span>Add a station<small>Starter stations and benchmarks</small></span></button>`
  + `<button id="mAddScene">${svg(IC.spark, 22)}<span>Describe a scene<small>Ready-made scenes, or build one from words</small></span></button>`
  + `</div><button class="cancel" id="mAddCancel">Cancel</button></div>`);
right.insertAdjacentHTML('afterbegin', `<button id="mGrab" class="m-only" aria-label="Resize the robot panel"><i></i></button>`);
$('rtitle').insertAdjacentHTML('beforeend', `<button id="mRMore" class="m-only" aria-label="Robot actions">${svg(IC.more)}</button>`);
$('tabChat').insertAdjacentHTML('afterend', `<button role="tab" id="mTabObj" class="m-only" aria-selected="false" hidden>Objects</button>`);
$('newSession').insertAdjacentHTML('afterend', `<div class="mlinks m-only"><a id="mPast" href="/pg/runs" target="_blank" rel="noopener">${svg(IC.past)}Past runs</a>`
  + `<button id="mSet">${svg(IC.set)}Settings</button></div>`);

// ---- the bottom sheet: small, half, full
// Follows the finger 1:1, then lands on the nearest height, counting where a flick would carry it.
const project = (v) => (v / 1000) * 0.998 / (1 - 0.998);          // px a flick travels at v px/s
const rubber = (o, d) => (o * d * 0.55) / (d + 0.55 * Math.abs(o)); // resistance past the ends
let level = 'peek', peekH = 0;
function setLevel(l) {
  level = l; right.style.height = '';
  body.classList.toggle('m-peek', l === 'peek'); body.classList.toggle('m-half', l === 'half'); body.classList.toggle('m-full', l === 'full');
  if (l === 'peek') setTimeout(() => { if (level === 'peek' && !body.classList.contains('m-drag') && right.offsetHeight > 80) peekH = right.offsetHeight; }, 560);
}
setLevel('peek');
(() => {
  let d = null;
  const start = (e) => {
    if (!M() || (e.pointerType === 'mouse' && e.button)) return;
    const onGrab = !!e.target.closest('#mGrab');
    if (!onGrab && e.target.closest('button, input, textarea, select, a, [contenteditable="true"], h2, h3')) return;
    d = {y: e.clientY, h: right.offsetHeight, id: e.pointerId, moved: false, onGrab, pts: [{y: e.clientY, t: e.timeStamp}]};
  };
  const move = (e) => {
    if (!d || e.pointerId !== d.id) return;
    const dy = e.clientY - d.y;
    if (!d.moved) { if (Math.abs(dy) < 6) return; d.moved = true; try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {} body.classList.add('m-drag'); body.classList.remove('m-peek'); body.classList.add('m-half'); }
    const lo = peekH || 300, hi = innerHeight - 52;
    let h = d.h - dy;
    if (h > hi) h = hi + rubber(h - hi, innerHeight);
    if (h < lo) h = lo - rubber(lo - h, innerHeight);
    right.style.height = h + 'px';
    d.pts.push({y: e.clientY, t: e.timeStamp}); if (d.pts.length > 5) d.pts.shift();
  };
  const end = (e) => {
    if (!d || e.pointerId !== d.id) return; const was = d; d = null; body.classList.remove('m-drag');
    if (!was.moved) { if (was.onGrab && e.type === 'pointerup') setLevel(level === 'peek' ? 'half' : level === 'half' ? 'full' : 'peek'); return; }
    const a = was.pts[0], b = was.pts[was.pts.length - 1], dt = Math.max(1, b.t - a.t);
    const v = (b.y - a.y) / dt * 1000;                       // + is down
    const aim = right.offsetHeight - project(v);
    const snaps = [['peek', peekH || 300], ['half', innerHeight * 0.56], ['full', innerHeight - 52]];
    snaps.sort((x, y) => Math.abs(x[1] - aim) - Math.abs(y[1] - aim));
    setLevel(snaps[0][0]);
  };
  for (const el of [$('mGrab'), $('rtitle')]) {
    el.addEventListener('pointerdown', start); el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end);
  }
})();

// ---- swipe a drawer or sheet away (the way it came in): far enough, or a quick flick
function swipeAway(el, handle, dir, close, scrim) {
  let d = null;
  const x = dir === 'left';
  const size = () => (x ? el.offsetWidth : el.offsetHeight) || 1;
  const put = (o) => { if (o == null) el.style.removeProperty('transform'); else el.style.setProperty('transform', x ? `translateX(${-o}px)` : `translateY(${o}px)`, 'important'); };
  handle.addEventListener('pointerdown', (e) => {
    if (!M() || (e.pointerType === 'mouse' && e.button)) return;
    d = {p: x ? e.clientX : e.clientY, q: x ? e.clientY : e.clientX, id: e.pointerId, on: false, o: 0, pts: []};
  });
  handle.addEventListener('pointermove', (e) => {
    if (!d || e.pointerId !== d.id) return;
    const along = x ? d.p - e.clientX : e.clientY - d.p, across = Math.abs((x ? e.clientY : e.clientX) - d.q);
    if (!d.on) {
      if (across > 10 && across > Math.abs(along)) { d = null; return; }
      if (Math.abs(along) < 8) return;
      d.on = true; try { handle.setPointerCapture(e.pointerId); } catch (_) {}
      el.style.setProperty('transition', 'none', 'important');
    }
    d.o = along >= 0 ? along : -rubber(-along, size());
    put(d.o); if (scrim) scrim.style.opacity = String(1 - Math.max(0, d.o) / size());
    d.pts.push({o: along, t: e.timeStamp}); if (d.pts.length > 5) d.pts.shift();
  });
  const end = (e) => {
    if (!d || e.pointerId !== d.id) return; const was = d; d = null;
    if (!was.on) return;
    const a = was.pts[0], b = was.pts[was.pts.length - 1];
    const v = a && b && b.t > a.t ? (b.o - a.o) / (b.t - a.t) * 1000 : 0;
    el.style.removeProperty('transition'); if (scrim) scrim.style.opacity = '';
    if (was.o > size() * 0.4 || v > 500) close();
    put(null);
    // a drag that moved is not a tap on whatever is under the finger
    const stop = (c) => { c.stopPropagation(); c.preventDefault(); };
    handle.addEventListener('click', stop, {capture: true, once: true}); setTimeout(() => handle.removeEventListener('click', stop, true), 0);
  };
  handle.addEventListener('pointerup', end); handle.addEventListener('pointercancel', end);
}

// a tab tap on the small sheet opens it to half
right.querySelector('.sidetabs').addEventListener('click', (e) => { if (M() && e.target.closest('button') && level === 'peek') setLevel('half'); }, true);
$('mTabObj').onclick = () => { if (typeof setObjects === 'function') setObjects(true); };
$('mRMore').onclick = (e) => {
  const sc = S.scene; if (!sc || !sc.active) return;
  const r = e.currentTarget.getBoundingClientRect(); openStMenu(sc.active, r.left, r.bottom);
};

// ---- sessions drawer
const nav = (open) => { body.classList.toggle('m-nav', open); if (open) $('sessNav').classList.remove('closed'); };
$('mNav').onclick = () => nav(true); $('mSess').onclick = () => nav(true);
$('mScrim').onclick = () => { nav(false); showAdd(false); };
$('navClose').addEventListener('click', (e) => { if (M()) { e.stopImmediatePropagation(); nav(false); } }, true);
$('sessNav').addEventListener('click', (e) => { if (M() && e.target.closest('.srow, .rrow, #newSession, #mPast, #mSet') && !e.target.closest('.smore')) setTimeout(() => nav(false), 50); });
$('mSet').onclick = () => { nav(false); window.openSettings && window.openSettings(); };

// ---- the + tile: one Add menu
function showAdd(open) { $('mAdd').hidden = !open; body.classList.toggle('m-addopen', open); }
$('rrail').addEventListener('click', (e) => { if (M() && e.target.closest('#rAdd') && !S.watch) { e.stopImmediatePropagation(); e.preventDefault(); showAdd(true); } }, true);
$('mAddCancel').onclick = () => showAdd(false);
$('mAddRobot').onclick = () => { showAdd(false); openPicker('add'); };
$('mAddStation').onclick = () => { showAdd(false); openAdd(); };
$('mAddScene').onclick = () => { showAdd(false); const b = $('sgBar'); if (b) b.click(); };

// ---- press and hold a robot tile for its actions
(() => {
  let t = null;
  $('rrail').addEventListener('touchstart', (e) => {
    const b = e.target.closest('.rbot'); if (!b || !M()) return;
    const p = e.touches[0];
    t = setTimeout(() => { t = null; try { navigator.vibrate && navigator.vibrate(10); } catch (_) {} b.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: p.clientX, clientY: p.clientY})); }, 500);
  }, {passive: true});
  const stop = () => { clearTimeout(t); t = null; };
  $('rrail').addEventListener('touchend', stop); $('rrail').addEventListener('touchmove', stop, {passive: true});
  $('rrail').addEventListener('contextmenu', (e) => { if (M() && e.isTrusted) e.preventDefault(); }, true);
})();

// ---- cameras: tap a small window to open it big
$('pips').addEventListener('click', (e) => {
  if (!M()) return; const p = e.target.closest('.pip'); if (!p || e.target.closest('.exp')) return;
  const x = p.querySelector('.exp'); if (x) x.click();
});

// ---- reset view, full screen
$('mReset').onclick = () => { if (window.V3) window.V3.setFollow(true); api('/pg/camera', {preset: 'home'}); };
let fsT = null;
function setFs(on) {
  body.classList.toggle('m-fs', on); body.classList.remove('m-fsui');
  try {
    if (on && document.documentElement.requestFullscreen && !document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  } catch (e) {}
}
$('mFs').onclick = () => setFs(true);
$('mFsX').onclick = () => setFs(false);
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement && body.classList.contains('m-fs') && M()) setFs(false); });
function fsPeek() {   // full screen: a tap brings the top controls back for a few seconds
  body.classList.add('m-fsui'); clearTimeout(fsT); fsT = setTimeout(() => body.classList.remove('m-fsui'), 3000);
}

// ---- placing an object: tap shows where it lands, then Place here
let plP = null;
async function plTap(p) {
  plP = p; $('mPlGo').disabled = false;
  await probe(S.armed, p); sync();
}
$('mPlCancel').onclick = () => { S.armed = null; plP = null; probeNext = null; markArmed(); hideTag(); api('/pg/ghost/clear', {}); sync(); };
$('mPlGo').onclick = async () => {
  if (!S.armed || !plP) return;
  const id = S.armed, p = plP; S.armed = null; plP = null; probeNext = null; markArmed(); hideTag();
  sync(); await place(id, p); sync();
};

// ---- fingers in the scene
// One finger works like the mouse's left button (turn the view, pick, drag an object, tap a ring);
// two fingers slide the view and pinch to zoom.
(() => {
  let one = null, two = null;
  const fake = (t) => ({clientX: t.clientX, clientY: t.clientY});
  const send = (type, t, target) => (target || view).dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, clientX: t.clientX, clientY: t.clientY, button: 0, buttons: type === 'mouseup' ? 0 : 1}));
  const mid = (a, b) => ({x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2, d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)});
  view.addEventListener('touchstart', (e) => {
    if (!M()) return;
    e.preventDefault();
    if (e.touches.length === 1) {
      const t = e.touches[0]; one = {id: t.identifier, x: t.clientX, y: t.clientY, moved: false};
      // placing an object: no mouse, just a preview where the finger lifts
      if (!S.armed) send('mousedown', t);
    } else if (e.touches.length === 2) {
      if (one && !S.armed) send('mouseup', {clientX: one.x, clientY: one.y}, window);   // not on the scene: ends the turn without a tap   // end the one-finger turn
      one = null; two = mid(e.touches[0], e.touches[1]);
    }
  }, {passive: false});
  view.addEventListener('touchmove', (e) => {
    if (!M()) return;
    e.preventDefault();
    if (two && e.touches.length >= 2) {
      const m = mid(e.touches[0], e.touches[1]);
      const dx = m.x - two.x, dy = m.y - two.y;
      const delta = {};
      if (Math.abs(dx) + Math.abs(dy) > 0.5) delta.pan = [-dx / 600, dy / 600];
      if (two.d > 10 && m.d > 10 && Math.abs(m.d - two.d) > 0.5) delta.zoom = two.d / m.d;
      if (delta.pan || delta.zoom) camera(delta);
      two = m; return;
    }
    if (!one) return;
    const t = [...e.touches].find(x => x.identifier === one.id); if (!t) return;
    if (Math.abs(t.clientX - one.x) + Math.abs(t.clientY - one.y) > 6) one.moved = true;
    if (S.armed) { if (one.moved) { const dx = t.clientX - one.x, dy = t.clientY - one.y; one.x = t.clientX; one.y = t.clientY; camera({azimuth: -dx * 0.3, elevation: -dy * 0.3}); } return; }
    send('mousemove', t);   // on the scene (it reaches the page's window listener too): the page checks the target
  }, {passive: false});
  const end = (e) => {
    if (!M()) return;
    if (two) { if (e.touches.length < 2) two = null; return; }
    if (!one) return;
    const t = [...e.changedTouches].find(x => x.identifier === one.id) || {clientX: one.x, clientY: one.y};
    const was = one; one = null;
    if (S.armed) { if (!was.moved) plTap(uv(fake(t))); return; }
    if (body.classList.contains('m-fs') && !was.moved) fsPeek();
    send('mouseup', t);
  };
  view.addEventListener('touchend', end); view.addEventListener('touchcancel', end);
})();

// ---- swipes to close
swipeAway($('sessNav'), $('sessNav'), 'left', () => nav(false), $('mScrim'));
swipeAway($('objDrawer'), $('objDrawer').querySelector('.dh'), 'down', () => setObjects(false));
swipeAway($('objPanel'), $('objPanel').querySelector('.ohd'), 'down', () => $('objX').click());
swipeAway($('mAdd'), $('mAdd'), 'down', () => showAdd(false), $('mScrim'));
// the robot picker is rebuilt each time it opens: listen on the picker itself, start only on its header
(() => {
  const pk = $('rpk'); if (!pk) return;
  let armed = false;
  pk.addEventListener('pointerdown', (e) => { armed = !!e.target.closest('.ph') && !e.target.closest('button'); }, true);
  swipeAway(pk, pk, 'down', () => closePicker());
  pk.addEventListener('pointermove', (e) => { if (!armed) e.stopImmediatePropagation(); }, true);
})();

// ---- the keyboard: keep the sheet above it where the browser doesn't move the page
if (window.visualViewport) {
  const vv = window.visualViewport;
  const kb = () => { const k = Math.max(0, Math.round(innerHeight - vv.height - vv.offsetTop)); document.documentElement.style.setProperty('--kb', (M() && k > 60 ? k : 0) + 'px'); };
  vv.addEventListener('resize', kb); vv.addEventListener('scroll', kb);
}

// ---- touch screens: hover looks stay off (a tap would leave them stuck on)
// Wraps every :hover rule in "(hover:hover) and (pointer:fine)", only on devices with no hover.
if (matchMedia('(hover:none)').matches) {
  const gate = (list, owner) => {
    for (let i = list.length - 1; i >= 0; i--) {
      const r = list[i];
      if (r.cssRules && r.conditionText !== undefined) { if (!/hover\s*:\s*hover/.test(r.conditionText)) gate(r.cssRules, r); continue; }
      if (r.selectorText && r.selectorText.includes(':hover')) {
        const t = r.cssText; owner.deleteRule(i);
        try { owner.insertRule(`@media (hover:hover) and (pointer:fine){${t}}`, i); } catch (_) {}
      }
    }
  };
  const all = () => { for (const sh of document.styleSheets) { try { gate(sh.cssRules, sh); } catch (_) {} } };
  all(); addEventListener('load', all);
  new MutationObserver((ms) => { if (ms.some(m => [...m.addedNodes].some(n => n.tagName === 'STYLE' || n.tagName === 'LINK'))) setTimeout(all, 0); })
    .observe(document.head, {childList: true});
}

// ---- words: "tap" on phones, not "click"
const TAPWORDS = [
  [/Press “\+ Station”, then click the floor to place it\./, 'Tap + below to add a robot, then tap the floor to place it.'],
  [/Drag an object onto the scene, or click it and then click where it should go\./, 'Tap an object, then tap the scene where it should go.'],
  [/ R turns it, Esc cancels\./, ''], [/\bclick\b/g, 'tap'], [/\bClick\b/g, 'Tap'],
];
function tapWords() {
  for (const el of document.querySelectorAll('#emptyMsg, #libhint, #rpk .ph p, #hintTag, #droptag, #addModal p')) {
    if (el.children.length) continue;
    let t = el.textContent, n = t; for (const [a, b] of TAPWORDS) n = n.replace(a, b);
    if (n !== t) el.textContent = n;
  }
}

// ---- keep the phone pieces in step with the page
let lastArmed = null;
function sync() {
  if (!M()) return;
  tapWords();
  const n = ($('sessName').textContent || S.sessName || 'Playground').trim();
  if ($('mSessName').textContent !== n) $('mSessName').textContent = n;
  const free = !!(S.scene && S.scene.mode === 'free') && !S.watch;
  $('mTabObj').hidden = !free;
  $('mTabObj').setAttribute('aria-selected', String(body.classList.contains('objopen')));
  if (S.armed !== lastArmed) {
    lastArmed = S.armed;
    if (S.armed) {
      const it = (S.cat && S.cat.items || []).find(i => i.id === S.armed) || {};
      $('mPlImg').src = it.thumb || ''; $('mPlName').textContent = `Placing ${(it.label || 'an object').toLowerCase()}`;
      $('mPlHint').textContent = 'Tap the scene where it should go'; $('mPlGo').disabled = true; plP = null;
      if (body.classList.contains('objopen')) setObjects(false), S.armed = lastArmed;   // closing the library clears it: keep it
      markArmed();
    }
  }
  if (S.armed && plP) {   // where it lands, or why it can't go there
    const bad = $('droptag').classList.contains('bad');
    $('mPlHint').textContent = $('droptag').textContent || 'Tap again to move it'; $('mPlGo').disabled = bad;
  }
  $('mPlace').hidden = !S.armed;
  body.classList.toggle('m-hide', !!S.armed || !!S.placing);
  body.classList.toggle('m-placing', !!S.armed || !!S.placing);
}
setInterval(sync, 250);
// and straight after any tap, so the place bar and sheet never lag behind
document.addEventListener('click', () => { setTimeout(sync, 0); setTimeout(sync, 400); }, true);
for (const t of ['touchend', 'keyup']) document.addEventListener(t, () => setTimeout(sync, 0), true);
MQ.addEventListener('change', () => { if (!M()) { body.classList.remove('m-nav', 'm-fs', 'm-fsui', 'm-hide', 'm-placing', 'm-addopen'); showAdd(false); } });
})();
