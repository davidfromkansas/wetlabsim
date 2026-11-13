// Settings, two tabs. General (the owner's own, for every session): the time limit of each AI run
// and their own API keys (Connections), each change saved at once (GET/POST /pg/account).
// Scene: every MuJoCo setting of this session's lab (MuJoCo's own <option>, its 28
// on/off flags, contact override and motor groups, the same groups as MuJoCo's own viewer) plus
// the lab's material groups. Edits wait until Save, which asks first and restarts the scene.
// Each setting has an (i) note: what it does (from MuJoCo's XML reference), MuJoCo's default,
// the Playground's value and a link to MuJoCo's docs.
// Data: GET /pg/settings, POST /pg/settings {settings}. Loaded after the page's own script
// (uses S, SID, U, BID, api, esc, toast, $).
(() => {
// Plain-words summaries of MuJoCo's XML reference (doc/XMLreference.rst: option, option/flag, geom).
const DOCS = {
  timestep: 'Length of one simulation step, in seconds. MuJoCo calls it the most important setting for speed vs. accuracy: smaller is more accurate and stable, but slower.',
  impratio: 'How hard friction forces are compared with pushing (normal) forces, for elliptic cones. Above 1 reduces slow slipping without raising the friction itself. Not advised with pyramidal cones.',
  gravity: 'Gravity as an x, y, z vector, in m/s². Z points up.',
  wind: 'Speed of the air or water around objects, as x, y, z. Used for drag and lift, so it only matters when density or viscosity is above 0.',
  magnetic: 'The magnetic field, as x, y, z. Only magnetometer sensors use it.',
  density: 'Density of the air or water around objects, used for lift and drag. Air is about 1.2, water about 1000. 0 turns lift and drag off.',
  viscosity: 'How sticky the air or water is, for drag that grows with speed. Air is about 0.00002, water about 0.0009. 0 turns it off.',
  o_margin: 'Replaces every contact\'s margin while the Override switch is on.',
  o_solref: 'Replaces every contact\'s softness (solref: time constant and damping ratio) while the Override switch is on.',
  o_solimp: 'Replaces every contact\'s give (solimp) while the Override switch is on.',
  o_friction: 'Replaces every contact\'s friction (sliding, sliding, twisting, rolling, rolling) while the Override switch is on.',
  integrator: 'The math used to step forward in time: Euler, RK4, implicit, implicitfast (implicit without some slow terms) or discrete.',
  cone: 'Shape of the friction limit. Elliptic is closer to real life; pyramidal can make the solver faster and steadier.',
  jacobian: 'Dense or sparse math for constraints. Auto picks dense up to 60 degrees of freedom, sparse above.',
  solver: 'Which constraint solver to use: PGS, CG or Newton.',
  iterations: 'Most tries the constraint solver makes each step. Bigger, busier scenes need more.',
  tolerance: 'The solver stops early once its error is below this. 0 means it never stops early.',
  ls_iterations: 'Most line-search tries per solver try, for the CG and Newton solvers.',
  ls_tolerance: 'The line search stops early once its error is below this.',
  noslip_iterations: 'Extra passes after the main solver that stop slow sliding and drift. 0 turns them off.',
  noslip_tolerance: 'No-slip passes stop early once the error is below this.',
  ccd_iterations: 'Most tries for collision checks between convex shapes. Rarely needs changing, except for very long, thin shapes.',
  ccd_tolerance: 'Convex collision checks stop early once the error is below this.',
  sleep_tolerance: 'Objects slower than this may go to sleep (when the Sleep switch is on).',
  sdf_iterations: 'Tries per start point for collisions with SDF shapes.',
  sdf_initpoints: 'Start points used to find contacts with SDF shapes.',
  actuatorgroupdisable: 'Motors in a turned-off group produce no force. MuJoCo\'s viewer shows groups 0 to 5.',
  'flag-constraint': 'Off: no constraint forces at all (contacts, limits, joint links).',
  'flag-equality': 'Off: no equality constraints (welds, joint links).',
  'flag-frictionloss': 'Off: no joint and tendon friction loss.',
  'flag-limit': 'Off: joint and tendon limits stop working.',
  'flag-contact': 'Off: no collision detection and no contact forces.',
  'flag-spring': 'Off: no joint, tendon and flex springs.',
  'flag-damper': 'Off: no joint, tendon and flex dampers.',
  'flag-gravity': 'Off: gravity is treated as 0 0 0, without changing the Gravity setting.',
  'flag-clampctrl': 'Off: motor commands are no longer kept inside their allowed range.',
  'flag-warmstart': 'Off: the solver no longer starts from the last step\'s answer.',
  'flag-filterparent': 'Off: parts connected parent-to-child can collide with each other.',
  'flag-actuation': 'Off: no motor forces at all.',
  'flag-refsafe': 'Keeps contact softness from being too stiff for the time step, which prevents blow-ups.',
  'flag-sensor': 'Off: sensors stop updating.',
  'flag-midphase': 'Off: no fast pre-check, so every allowed pair of shapes is tested for collision.',
  'flag-eulerdamp': 'Off: the Euler integrator stops handling joint damping implicitly.',
  'flag-autoreset': 'Off: the sim no longer resets itself when numbers blow up.',
  'flag-nativeccd': 'Uses MuJoCo\'s own convex collision code instead of the libccd library.',
  'flag-island': 'Splits the scene into groups that don\'t touch and solves each one on its own.',
  'flag-multiccd': 'Finds several contact points between flat convex shapes (like mesh on mesh), so they rest steadily instead of wobbling.',
  'flag-override': 'On: uses the Contact override values for every contact.',
  'flag-energy': 'On: computes potential and kinetic energy. Good for checking accuracy.',
  'flag-fwdinv': 'On: compares forward and inverse dynamics each step.',
  'flag-invdiscrete': 'On: inverse dynamics works in discrete time.',
  'flag-sleep': 'On: still objects can go to sleep to save time.',
  'flag-diagexact': 'On: uses an exact solver diagonal instead of an estimate. Can help when a model misbehaves.',
  'flag-ipc': 'On: experimental IPC contact for soft (flex) objects. Discrete integrator only.',
  'flag-speculative': 'On: adds contacts just before fast objects hit, so they can\'t pass through thin things.',
  condim: 'How many directions a contact pushes back in: 1 no friction, 3 sliding friction, 4 adds twisting friction, 6 adds rolling friction.',
  friction: 'Sliding, twisting and rolling friction. When two shapes touch, MuJoCo uses the larger of their values.',
  solref: 'Contact softness: a time constant (seconds) and a damping ratio. Smaller time is harder.',
};
const FLAG_LABEL = {constraint: 'All constraints', equality: 'Welds and joint links', frictionloss: 'Joint friction', limit: 'Joint limits',
  contact: 'Collisions', spring: 'Springs', damper: 'Dampers', gravity: 'Gravity', clampctrl: 'Keep motor commands in range',
  warmstart: 'Start from last step\'s answer', filterparent: 'Skip parent-child collisions', actuation: 'Motors', refsafe: 'Safe softness limits',
  sensor: 'Sensors', midphase: 'Fast collision pre-check', eulerdamp: 'Smooth joint damping', autoreset: 'Reset if the sim blows up',
  nativeccd: 'MuJoCo\'s own collision code', island: 'Solve separate groups apart', multiccd: 'Several contact points per pair',
  override: 'Use Contact override values', energy: 'Track energy', fwdinv: 'Compare forward and inverse', invdiscrete: 'Discrete inverse',
  sleep: 'Let still objects sleep', diagexact: 'Exact solver diagonal', ipc: 'IPC contact model', speculative: 'Look-ahead contacts'};
const UNITS = {timestep: 's', gravity: 'm/s²', wind: 'm/s', density: 'kg/m³', viscosity: 'Pa·s', magnetic: 'T', o_margin: 'm'};
const VEC_AXES = {gravity: ['x', 'y', 'z'], wind: ['x', 'y', 'z'], magnetic: ['x', 'y', 'z'], o_solref: ['time', 'damping'],
  o_solimp: ['d0', 'dwidth', 'width', 'mid', 'power'], o_friction: ['slide', 'slide', 'twist', 'roll', 'roll'],
  friction: ['slide', 'twist', 'roll'], solref: ['time', 'damping']};
const GROUPS = [
  ['solver', 'Solver and integrator', 'The math MuJoCo uses each step. The same four choices as MuJoCo\'s own viewer.', '<path d="M4 17l5-5 4 4 7-8"/>'],
  ['accuracy', 'Accuracy and steps', 'How finely time is sliced, and how hard MuJoCo works to get each step right. More tries and smaller tolerances are more exact but slower.', '<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8"/>'],
  ['world', 'World and grip', 'Forces from the world around the objects, and how firmly friction holds.', '<path d="M12 4v13M7 12l5 5 5-5"/>'],
  ['flags', 'On / off switches', 'All 28 of MuJoCo\'s switches, in the same order as MuJoCo\'s own viewer.', '<rect x="3" y="8" width="18" height="9" rx="4.5"/><circle cx="16.5" cy="12.5" r="2.5"/>'],
  ['override', 'Contact override', 'One set of contact values for every touch in the scene, replacing each material\'s own. Only used while the Override switch is on.', '<path d="M7 11V6a2 2 0 0 1 4 0v5M11 10V5a2 2 0 0 1 4 0v6M15 10a2 2 0 0 1 4 0v3a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-3l-2-4a2 2 0 0 1 3-2l2 2"/>'],
  ['act', 'Motor groups', 'Turn whole groups of motors on or off.', '<path d="M13 3L5 13h6l-1 8 8-10h-6z"/>'],
  ['materials', 'Materials', 'The Playground\'s own material groups: every shape touches with its group\'s settings. Change a group and all its shapes change together.', '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>'],
];
const ic = (p) => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const INFO = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.2v4" stroke-linecap="round"/><circle cx="8" cy="4.9" r=".9" fill="currentColor" stroke="none"/></svg>';
const XI = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#374151" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
const css = `
#ssWrap{position:fixed;inset:0;z-index:80;background:rgba(17,24,39,.38);display:none;align-items:center;justify-content:center;padding:20px}
#ssWrap.open{display:flex}
#ss{width:min(1080px,100%);height:min(780px,100%);background:#fff;border-radius:16px;box-shadow:0 24px 60px -12px rgba(17,24,39,.45),0 0 0 1px rgba(17,24,39,.08);display:flex;flex-direction:column;overflow:hidden;position:relative;font:14px/1.5 Inter,system-ui,sans-serif;color:#111827}
#ss .mh{display:flex;align-items:center;gap:14px;padding:16px 20px;border-bottom:1px solid #E5E7EB}
#ss .mh h2{margin:0;font-size:20px}
#ss .mh .sub{font-size:13px;color:#4B5563}
#ss .mh.tabbed{padding:0 16px 0 28px;height:60px;flex:none}
#ss .tabs{display:flex;gap:28px;align-self:stretch}
#ss .tabs .tb{height:auto;border-radius:0;border:0;background:none;padding:0;font:500 15px Inter,sans-serif;color:#4B5563;border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer}
#ss .tabs .tb:hover{color:#111827}
#ss .tabs .tb.on{color:#111827;font-weight:600;border-bottom-color:#111827}
#ss .mh.tabbed .x{margin-left:auto}
#ss .mh.tabbed .srch+.x{margin-left:0}
#ss .gs{flex:1;overflow:auto;padding:22px 28px 28px;display:flex;flex-direction:column;gap:22px}
#ss .gs h3{margin:0 0 10px;font-size:17px}
#ss .gs .note{margin:0 0 10px;color:#4B5563}
#ss .tlr{display:flex;align-items:center;gap:16px;padding:12px 16px;border:1px solid #E5E7EB;border-radius:12px}
#ss .tlr span{flex:1;color:#374151}
#ss .stp{display:flex;align-items:center;height:40px;border:1px solid #D1D5DB;border-radius:9px;background:#fff;overflow:hidden}
#ss .stp button{width:40px;height:40px;border:0;background:transparent;font:500 20px Inter,sans-serif;color:#111827;cursor:pointer}
#ss .stp button:disabled{color:#C3C8D0;cursor:default}
#ss .stp output{min-width:86px;height:40px;border-left:1px solid #E5E7EB;border-right:1px solid #E5E7EB;display:flex;align-items:center;justify-content:center;font:600 15px 'JetBrains Mono',ui-monospace,monospace}
#ss .cons{border:1px solid #E5E7EB;border-radius:12px;overflow:hidden}
#ss .con{display:flex;align-items:center;gap:14px;padding:14px 16px;border-bottom:1px solid #F0F1F3;flex-wrap:wrap}
#ss .cons>:last-child{border-bottom:0}
#ss .con .lg{width:40px;height:40px;border-radius:10px;background:#F7F8FA;box-shadow:0 0 0 1px #E5E7EB;display:flex;align-items:center;justify-content:center;flex:none}
#ss .con .lg img{width:22px;height:22px}
#ss .con .t{flex:1;min-width:200px}
#ss .con .t b{font-size:15px;display:flex;align-items:center;gap:8px}
#ss .con .d{font-size:13px;color:#4B5563;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
#ss .con .d i{width:3px;height:3px;border-radius:50%;background:#9CA3AF;display:block}
#ss .con .acts{display:flex;gap:8px}
#ss .stt{display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 9px;border-radius:999px;font-size:12px;font-weight:600;background:#F3F4F6;color:#374151}
#ss .stt:before{content:"";width:7px;height:7px;border-radius:50%;background:#9CA3AF}
#ss .stt.ok{background:#DCFCE7;color:#166534}
#ss .stt.ok:before{background:#16A34A}
#ss .mkey{font:500 12.5px 'JetBrains Mono',ui-monospace,monospace;color:#374151;background:#F3F4F6;border-radius:6px;padding:1px 7px}
#ss .bt{height:38px;padding:0 14px;border-radius:9px;border:1px solid #D1D5DB;background:#fff;color:#111827;font:600 14px Inter,sans-serif;cursor:pointer;white-space:nowrap}
#ss .bt.pri{background:#2563EB;border-color:#2563EB;color:#fff}
#ss .bt.red{background:#DC2626;border-color:#DC2626;color:#fff}
#ss .bt:disabled{opacity:.6;cursor:default}
#ss .gexp{background:#FAFAFB;border-bottom:1px solid #F0F1F3;padding:4px 16px 16px 70px}
#ss .way{background:#fff;border:1px solid #E5E7EB;border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px}
#ss .way h4{margin:0;font-size:14.5px}
#ss .way p{margin:0;font-size:13px;color:#4B5563}
#ss .way a{color:#1D4ED8;font-weight:600}
#ss .kin{height:40px;border:1px solid #D1D5DB;border-radius:9px;padding:0 10px;font:500 14px 'JetBrains Mono',ui-monospace,monospace;color:#111827;width:100%;outline:none}
#ss .kin:focus{border-color:#2563EB;box-shadow:0 0 0 3px #DBEAFE}
#ss .kin.bad{border-color:#DC2626;box-shadow:0 0 0 3px #FEE2E2}
#ss .emsg{font-size:13px;color:#B91C1C;font-weight:500}
#ss .gexp .way+.way{margin-top:10px}
#ss .way ol{margin:0;padding-left:20px;font-size:13px;color:#374151;display:flex;flex-direction:column;gap:8px}
#ss .cgcode{font:600 18px 'JetBrains Mono',ui-monospace,monospace;letter-spacing:.06em;color:#111827;background:#F3F4F6;border-radius:8px;padding:4px 10px;display:inline-block;margin:6px 6px 0 0}
#ss .way .note{font-size:12.5px;color:#6B7280}
#ss .cgwait{font-size:13px;color:#4B5563;flex:1;align-self:center}
#ss .way .row2{display:flex;gap:8px}
#ss .gerr{padding:10px 14px;border-radius:10px;background:#FEF2F2;color:#991B1B;font-weight:600}
#ss .srch{margin-left:auto;width:300px;max-width:40%;height:40px;border:1px solid #D1D5DB;border-radius:9px;display:flex;align-items:center;gap:8px;padding:0 10px;color:#6B7280}
#ss .srch input{border:0;outline:none;flex:1;min-width:0;font:15px Inter,sans-serif;color:#111827;background:transparent}
#ss .x{width:40px;height:40px;border-radius:9px;border:1px solid #D1D5DB;background:#fff;display:flex;align-items:center;justify-content:center;cursor:pointer;flex:none}
#ss .lock{display:flex;align-items:center;gap:10px;margin:12px 20px 0;padding:10px 14px;border-radius:10px;background:#FEF3C7;color:#92400E;font-weight:600}
#ss .mb{flex:1;display:flex;min-height:0}
#ss .snav{width:272px;flex:none;border-right:1px solid #E5E7EB;padding:12px 10px;display:flex;flex-direction:column;gap:2px;background:#FAFAFB;overflow:auto}
#ss .snav button{height:42px;border-radius:8px;padding:0 10px;display:flex;align-items:center;gap:10px;color:#374151;font:15px Inter,sans-serif;border:0;background:transparent;cursor:pointer;text-align:left}
#ss .snav button:hover{background:#F3F4F6}
#ss .snav button.on{background:#fff;color:#111827;font-weight:600;box-shadow:0 0 0 1px #E5E7EB}
#ss .snav .n{margin-left:auto;flex:none;font-size:12.5px;color:#4B5563}
#ss .snav .chg{margin-left:auto;white-space:nowrap;flex:none;font-size:12px;font-weight:700;color:#1D4ED8;background:#DBEAFE;border-radius:999px;padding:0 8px}
#ss .snav .sep{height:1px;background:#E5E7EB;margin:8px 6px}
#ss .sc{flex:1;overflow:auto;padding:18px 24px 24px}
#ss .sc h3{margin:0;font-size:18px}
#ss .sc h4{margin:18px 0 2px;font-size:16px}
#ss .lead{margin:2px 0 10px;color:#4B5563;max-width:660px}
#ss .row{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,320px);gap:20px;align-items:center;padding:12px;border-radius:10px;border-bottom:1px solid #F0F1F3}
#ss .row.ch{background:#EFF4FF;border-bottom-color:transparent}
#ss .nm{display:flex;align-items:center;gap:8px;font-weight:600;font-size:15px;flex-wrap:wrap}
#ss .key{font:500 12.5px 'JetBrains Mono',ui-monospace,monospace;color:#4B5563;background:#F3F4F6;border-radius:5px;padding:1px 6px}
#ss .df{font-size:13px;color:#4B5563;margin-top:2px;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
#ss .lk{color:#1D4ED8;font-weight:600;font-size:13px;border:0;background:none;padding:0;cursor:pointer;font-family:Inter,sans-serif}
#ss .lk:hover{text-decoration:underline}
#ss .ctl{display:flex;gap:6px;width:100%}
#ss input.v,#ss select.v{height:40px;border:1px solid #D1D5DB;border-radius:8px;padding:0 10px;font:500 14.5px 'JetBrains Mono',ui-monospace,monospace;color:#111827;background:#fff;width:100%;min-width:0}
#ss .vec{display:grid;gap:6px;width:100%}
#ss .vec label{display:flex;flex-direction:column;font-size:11.5px;color:#4B5563;gap:2px;min-width:0}
#ss .row.ch input.v,#ss .row.ch select.v,#ss td.ch input.v,#ss td.ch select.v{border-color:#2563EB;box-shadow:0 0 0 1px #2563EB}
#ss input.v.bad{border-color:#DC2626;box-shadow:0 0 0 3px #FEE2E2}
#ss .err{color:#B91C1C;font-size:13px;font-weight:600}
#ss .u{font-size:13px;color:#4B5563;align-self:center;white-space:nowrap}
#ss .fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:4px 20px}
#ss .fl{display:flex;align-items:center;gap:10px;min-height:46px;border-bottom:1px solid #F0F1F3;padding:0 8px;border-radius:8px}
#ss .fl.ch{background:#EFF4FF;border-bottom-color:transparent}
#ss .fl .t{display:flex;flex-direction:column;line-height:1.25;min-width:0;flex:1}
#ss .fl .t b{font-size:14.5px}
#ss .fl .t span{font-size:12.5px;color:#4B5563}
#ss .sw{width:46px;height:28px;border-radius:999px;background:#D1D5DB;position:relative;flex:none;border:0;cursor:pointer;padding:0}
#ss .sw:after{content:"";position:absolute;left:3px;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.2);transition:left 120ms ease-out}
#ss .sw[aria-checked=true]{background:#2563EB}
#ss .sw[aria-checked=true]:after{left:21px}
#ss .sw:disabled{opacity:.55;cursor:default}
#ss .ib{width:28px;height:28px;border-radius:999px;border:0;background:transparent;color:#6B7280;display:inline-flex;align-items:center;justify-content:center;padding:0;flex:none;cursor:pointer}
#ss .ib:hover,#ss .ib.on{background:#2563EB;color:#fff}
#ss table.mt{width:100%;border-collapse:separate;border-spacing:0}
#ss .mt th{font-size:12.5px;font-weight:600;color:#4B5563;text-align:left;padding:8px;border-bottom:1px solid #E5E7EB;white-space:nowrap}
#ss .mt td{padding:8px;border-bottom:1px solid #F0F1F3;vertical-align:middle}
#ss .mt td.ch{background:#EFF4FF}
#ss .mt .cls{font-weight:600;white-space:nowrap}
#ss .mt .cls span{display:block;font:500 12px 'JetBrains Mono',monospace;color:#4B5563}
#ss .mt .tri{display:flex;gap:4px}
#ss .mt .tri input.v{width:76px;padding:0 6px}
#ss .mf{display:flex;align-items:center;gap:12px;padding:14px 20px;border-top:1px solid #E5E7EB;background:#fff;flex-wrap:wrap}
#ss .mf .info{flex:1;font-size:14px;color:#4B5563;display:flex;align-items:center;gap:12px;flex-wrap:wrap;min-width:200px}
#ss .mf .cnt{font-weight:700;color:#111827}
#ss .btn{height:44px;padding:0 18px;border-radius:9px;border:1px solid #D1D5DB;background:#fff;color:#111827;font:600 15px Inter,sans-serif;cursor:pointer}
#ss .save{height:44px;padding:0 24px;border-radius:9px;border:0;background:#2563EB;color:#fff;font:600 15px Inter,sans-serif;cursor:pointer}
#ss .save:disabled,#ss .btn:disabled{background:#E5E7EB;color:#6B7280;border-color:#E5E7EB;cursor:default}
#ss .empty{color:#4B5563;padding:30px 0}
#ssTip{position:fixed;z-index:95;width:340px;background:#fff;border-radius:12px;box-shadow:0 12px 32px -8px rgba(17,24,39,.35),0 0 0 1px rgba(17,24,39,.1);padding:12px 14px;display:none;flex-direction:column;gap:8px;font:14px/1.5 Inter,sans-serif;color:#111827}
#ssTip.open{display:flex}
#ssTip .th{display:flex;align-items:center;gap:8px}
#ssTip .th b{font-size:15px}
#ssTip .tx{margin-left:auto;width:30px;height:30px;border-radius:7px;border:0;background:#F3F4F6;display:none;align-items:center;justify-content:center;cursor:pointer}
#ssTip.pinned .tx{display:flex}
#ssTip p{margin:0;color:#374151}
#ssTip .tf{display:flex;flex-direction:column;gap:2px;font-size:13px;color:#4B5563;border-top:1px solid #F0F1F3;padding-top:8px}
#ssTip .tf a{font-weight:600;color:#1D4ED8;text-decoration:none;margin-top:4px}
#ssTip .tf a:hover{text-decoration:underline}
#ssDlg{position:absolute;inset:0;background:rgba(17,24,39,.3);display:none;align-items:center;justify-content:center;z-index:5;padding:20px}
#ssDlg.open{display:flex}
#ssDlg .bx{width:min(540px,100%);max-height:100%;overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 60px -12px rgba(17,24,39,.5),0 0 0 1px rgba(17,24,39,.08);padding:22px;display:flex;flex-direction:column;gap:14px}
#ssDlg h3{margin:0;font-size:19px}
#ssDlg p{margin:0;color:#374151}
#ssDlg .chl{border:1px solid #E5E7EB;border-radius:10px;overflow:hidden}
#ssDlg .chl div{display:grid;grid-template-columns:1fr auto;gap:12px;padding:9px 12px;border-bottom:1px solid #F0F1F3;align-items:center}
#ssDlg .chl div:last-child{border-bottom:0}
#ssDlg .chl code{font:500 13px 'JetBrains Mono',monospace;color:#111827;white-space:nowrap}
#ssDlg .act{display:flex;justify-content:flex-end;gap:10px}
@media (max-width:760px){#ss .gexp{padding-left:16px}#ss .gs{padding:16px}#ss .mh.tabbed{padding-left:16px}#ss .snav{width:64px}#ss .snav .lb,#ss .snav .n,#ss .snav .chg{display:none}#ss .row{grid-template-columns:1fr}#ss .srch{display:none}}
`;
document.head.insertAdjacentHTML('beforeend', `<style>${css}</style>`);
document.body.insertAdjacentHTML('beforeend', `<div id="ssWrap"><div id="ss" role="dialog" aria-modal="true" aria-label="Settings"></div></div><div id="ssTip" role="tooltip"></div>`);
const wrap = document.getElementById('ssWrap'), box = document.getElementById('ss'), tip = document.getElementById('ssTip');

const M = {data: null, draft: null, group: 'solver', q: '', only: false, busy: false, err: '', opener: null, tab: 'scene'};
const clone = (x) => JSON.parse(JSON.stringify(x));
const num = (x) => typeof x === 'number' ? (Number.isInteger(x) ? String(x) : String(+x.toPrecision(10))) : String(x);
const same = (a, b) => {
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => same(x, b[i]));
  if (typeof a === 'number' && typeof b === 'number') return a === b || Math.abs(a - b) <= 1e-12 * Math.max(Math.abs(a), Math.abs(b));
  return a === b;
};
const show = (v) => typeof v === 'boolean' ? (v ? 'on' : 'off') : Array.isArray(v) ? v.map(num).join(' ') : num(v);
const opt = (n) => M.data.schema.options.find(o => o.name === n);

// Every setting as a flat list of {id, group, label, key, get(src), doc, ...}, for search,
// counting changes and the Save summary.
function items() {
  const d = M.data, out = [];
  for (const o of d.schema.options) out.push({id: 'o:' + o.name, group: o.group, label: o.label, key: 'option/' + o.name,
    get: (src) => src.option[o.name], doc: o.name, anchor: 'option-' + o.name.replace(/_/g, '-'), o});
  for (const f of [...d.schema.disable, ...d.schema.enable]) out.push({id: 'f:' + f, group: 'flags', label: f[0].toUpperCase() + f.slice(1),
    sub: FLAG_LABEL[f] || '', key: 'option/flag/' + f, get: (src) => src.flag[f], doc: 'flag-' + f, anchor: 'option-flag-' + f, flag: f});
  for (let g = 0; g < d.schema.act_groups; g++) out.push({id: 'a:' + g, group: 'act', label: `Group ${g}`, key: 'actuatorgroupdisable',
    get: (src) => !(src.actuatorgroupdisable || []).includes(g), doc: 'actuatorgroupdisable', anchor: 'option-actuatorgroupdisable', act: g});
  for (const [c, lab] of Object.entries(d.schema.materials)) for (const k of ['condim', 'friction', 'solref'])
    out.push({id: `m:${c}:${k}`, group: 'materials', label: `${lab} ${k}`, key: `class "${c}" · geom/${k}`,
      get: (src) => (src.materials[c] || {})[k], doc: k, anchor: 'body-geom-' + k, mat: [c, k]});
  return out;
}
function setVal(it, v) {
  const s = M.draft;
  if (it.o) s.option[it.o.name] = v;
  else if (it.flag) s.flag[it.flag] = v;
  else if (it.act != null) {
    const off = new Set(s.actuatorgroupdisable || []);
    if (v) off.delete(it.act); else off.add(it.act);
    s.actuatorgroupdisable = [...off].sort((a, b) => a - b);
  } else if (it.mat) { s.materials[it.mat[0]] = {...s.materials[it.mat[0]], [it.mat[1]]: v}; }
}
const changed = (it) => !same(it.get(M.draft), it.get(M.data.current));
const fromPlayground = (it) => !same(it.get(M.draft), it.get(M.data.playground));
const pgVal = (it) => it.get(M.data.playground), mjVal = (it) => it.mat ? null : it.get(M.data.mujoco);
const bad = () => box.querySelectorAll('input.v.bad').length;

// What the session keeps: only what differs from the Playground's own values.
function sessionSettings() {
  const d = M.draft, p = M.data.playground, out = {};
  const o = {}; for (const x of M.data.schema.options) if (!same(d.option[x.name], p.option[x.name])) o[x.name] = d.option[x.name];
  if (Object.keys(o).length) out.option = o;
  const f = {}; for (const k of Object.keys(d.flag)) if (d.flag[k] !== p.flag[k]) f[k] = d.flag[k];
  if (Object.keys(f).length) out.flag = f;
  if ((d.actuatorgroupdisable || []).length) out.actuatorgroupdisable = d.actuatorgroupdisable;
  const m = {};
  for (const c of Object.keys(M.data.schema.materials)) {
    const mv = {}; for (const k of ['condim', 'friction', 'solref']) if (!same(d.materials[c][k], p.materials[c][k])) mv[k] = d.materials[c][k];
    if (Object.keys(mv).length) m[c] = mv;
  }
  if (Object.keys(m).length) out.materials = m;
  return out;
}

function locked() {
  if (S.watch) return 'You\'re watching someone else\'s lab. Only its owner can change these settings.';
  const runs = (S.scene && S.scene.runs) || {};
  if (Object.values(runs).some(r => r.active || r.queued)) return 'A robot is working on a task. Stop it to change settings (you can still read them).';
  return '';
}

// General is the owner's (not for someone watching another person's lab).
const hasGeneral = () => !S.watch;
function tabsHtml() {
  const t = (id, lab) => `<button class="tb${M.tab === id ? ' on' : ''}" role="tab" aria-selected="${M.tab === id}" data-tab="${id}">${lab}</button>`;
  return `<nav class="tabs" role="tablist" aria-label="Settings">${hasGeneral() ? t('general', 'General') : ''}${t('scene', 'Scene')}</nav>`;
}
function wireTabs() {
  box.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { if (b.dataset.tab !== M.tab) showTab(b.dataset.tab); });
}
async function open(tab) {
  M.opener = document.activeElement;
  M.data = null; M.draft = null;
  wrap.classList.add('open');
  await showTab(typeof tab === 'string' && (tab !== 'general' || hasGeneral()) ? tab : hasGeneral() ? 'general' : 'scene');
}
async function showTab(tab) {
  M.tab = tab; hideTip(true);
  if (tab === 'general') return G.load();
  if (M.data) return draw(true);       // back to Scene: the edits made so far are kept
  box.innerHTML = `<div class="mh tabbed">${tabsHtml()}<span class="sub">Loading…</span><button class="x" id="ssX" aria-label="Close settings">${XI}</button></div>`;
  wireTabs(); box.querySelector('#ssX').onclick = () => close();
  const r = await fetch(U('/pg/settings'), {headers: {'X-Browser-Id': BID}}).then(x => x.json()).catch(() => null);
  if (M.tab !== 'scene') return;
  if (!r || !r.ok) { box.querySelector('.sub').textContent = 'Could not load the settings. Try again.'; return; }
  M.data = r; M.draft = clone(r.current); M.err = ''; M.q = ''; M.only = false;
  draw(true);
}
async function close(force) {
  const n = M.data ? items().filter(changed).length : 0;
  if (!force && n && !(await askConfirm('Discard your changes?', `You have ${n} unsaved change${n > 1 ? 's' : ''}. Closing throws ${n > 1 ? 'them' : 'it'} away.`, 'Discard'))) return;
  wrap.classList.remove('open'); hideTip(true);
  if (M.opener && M.opener.focus) M.opener.focus();
}

function infoBtn(it) { return `<button class="ib" data-tip="${it.id}" aria-label="About ${esc(it.label)}">${INFO}</button>`; }
function defLine(it) {
  const pv = pgVal(it), parts = [`Playground: <b>${esc(show(pv))}</b>`];
  const bits = [];
  if (changed(it)) bits.push(`<button class="lk" data-undo="${it.id}">Undo</button>`);
  else if (fromPlayground(it) && !locked()) bits.push(`<button class="lk" data-pg="${it.id}">Use Playground's</button>`);
  return `<div class="df">${parts.join('')}${bits.join('')}</div>`;
}
function numInput(it, v, i, rng, kind) {
  return `<input class="v" inputmode="decimal" data-id="${it.id}"${i != null ? ` data-i="${i}"` : ''} data-kind="${kind}"${rng ? ` data-lo="${rng[0]}" data-hi="${rng[1]}"` : ''} value="${esc(num(v))}" aria-label="${esc(it.label)}${i != null ? ' ' + (VEC_AXES[(it.o && it.o.name) || (it.mat && it.mat[1])] || [])[i] : ''}">`;
}
function control(it) {
  const v = it.get(M.draft), o = it.o;
  if (o.kind === 'enum') return `<select class="v" data-id="${it.id}" aria-label="${esc(it.label)}">${M.data.schema.enums[o.name].map(e => `<option${e === v ? ' selected' : ''}>${e}</option>`).join('')}</select>`;
  if (o.kind === 'vec') {
    const ax = VEC_AXES[o.name] || [];
    return `<div class="vec" style="grid-template-columns:repeat(${o.extra},1fr)">${v.map((x, i) => `<label>${ax[i] || ''}${numInput(it, x, i, null, 'real')}</label>`).join('')}</div>${UNITS[o.name] ? `<span class="u">${UNITS[o.name]}</span>` : ''}`;
  }
  return `${numInput(it, v, null, o.extra, o.kind)}${UNITS[o.name] ? `<span class="u">${UNITS[o.name]}</span>` : ''}`;
}
function rowHtml(it) {
  if (it.flag || it.act != null) {
    const v = it.get(M.draft);
    return `<div class="fl${changed(it) ? ' ch' : ''}" data-row="${it.id}"><button class="sw" role="switch" aria-checked="${v}" data-id="${it.id}" aria-label="${esc(it.label)}"${locked() ? ' disabled' : ''}></button><span class="t"><b>${esc(it.label)}</b><span>${esc(it.sub || (v ? 'On' : 'Off'))} · Playground: ${show(pgVal(it))}</span></span>${changed(it) ? `<button class="lk" data-undo="${it.id}">Undo</button>` : ''}${infoBtn(it)}</div>`;
  }
  return `<div class="row${changed(it) ? ' ch' : ''}" data-row="${it.id}"><div><div class="nm">${esc(it.label)}<span class="key">${esc(it.key)}</span>${infoBtn(it)}</div>${defLine(it)}</div><div><div class="ctl">${control(it)}</div><div class="err" data-err="${it.id}"></div></div></div>`;
}
function matTable(list) {
  const d = M.data, rows = Object.entries(d.schema.materials).map(([c, lab]) => {
    const cell = (k) => {
      const it = list.find(x => x.mat && x.mat[0] === c && x.mat[1] === k);
      if (!it) return '<td></td>';
      const v = it.get(M.draft);
      const ctl = k === 'condim' ? `<select class="v" data-id="${it.id}" aria-label="${esc(lab)} condim" style="width:76px">${d.schema.condims.map(x => `<option${x === v ? ' selected' : ''}>${x}</option>`).join('')}</select>`
        : `<div class="tri">${v.map((x, i) => numInput(it, x, i, null, 'real')).join('')}</div>`;
      return `<td class="${changed(it) ? 'ch' : ''}" data-row="${it.id}">${ctl}<div class="df">Playground: ${esc(show(pgVal(it)))}${changed(it) ? ` <button class="lk" data-undo="${it.id}">Undo</button>` : ''}</div></td>`;
    };
    if (!list.some(x => x.mat && x.mat[0] === c)) return '';
    return `<tr><td class="cls">${esc(lab)}<span>class "${c}"</span></td>${cell('condim')}${cell('friction')}${cell('solref')}</tr>`;
  }).join('');
  const it0 = (k) => list.find(x => x.mat && x.mat[1] === k) || items().find(x => x.mat && x.mat[1] === k);
  return `<table class="mt"><thead><tr><th>Group</th><th>Condim ${infoBtn(it0('condim'))}</th><th>Friction (slide, twist, roll) ${infoBtn(it0('friction'))}</th><th>Softness, solref (time, damping) ${infoBtn(it0('solref'))}</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function groupHtml(g, list) {
  const sub = list.filter(it => it.group === g[0]);
  if (!sub.length) return '';
  let body;
  if (g[0] === 'flags' || g[0] === 'act') body = `<div class="fg">${sub.map(rowHtml).join('')}</div>`;
  else if (g[0] === 'materials') body = matTable(sub);
  else body = sub.map(rowHtml).join('');
  return `<h3${M.q || M.only ? ' style="margin-top:14px"' : ''}>${g[1]}</h3><p class="lead">${g[2]}</p>${body}`;
}

function draw(first) {
  const d = M.data, all = items(), lock = locked();
  const nChanged = all.filter(changed).length;
  const q = M.q.trim().toLowerCase();
  let list = all;
  if (q) list = all.filter(it => (it.label + ' ' + it.key + ' ' + (it.sub || '') + ' ' + (DOCS[it.doc] || '')).toLowerCase().includes(q));
  else if (M.only) list = all.filter(it => changed(it) || fromPlayground(it));
  const groups = q || M.only ? GROUPS : GROUPS.filter(g => g[0] === M.group);
  const content = groups.map(g => groupHtml(g, list)).join('') || `<p class="empty">${q ? 'No setting matches that.' : 'Nothing here differs from the Playground\'s own settings.'}</p>`;
  const sc = box.querySelector('.sc'), scroll = sc && !first ? sc.scrollTop : 0;
  const nav = GROUPS.map(g => {
    const ch = all.filter(it => it.group === g[0] && changed(it)).length, n = all.filter(it => it.group === g[0]).length;
    const cnt = g[0] === 'materials' ? Object.keys(d.schema.materials).length : n;
    return `<button class="${!q && !M.only && M.group === g[0] ? 'on' : ''}" data-g="${g[0]}">${ic(g[3])}<span class="lb">${g[1]}</span>${ch ? `<span class="chg">${ch} changed</span>` : `<span class="n">${cnt}</span>`}</button>`;
  }).join('');
  const differ = all.filter(fromPlayground).length;
  box.innerHTML = `<div class="mh tabbed">${tabsHtml()}
    <label class="srch"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#6B7280" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg><input id="ssQ" type="search" placeholder="Search settings" aria-label="Search settings" value="${esc(M.q)}"></label>
    <button class="x" id="ssX" aria-label="Close settings">${XI}</button></div>
    ${lock ? `<div class="lock"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>${esc(lock)}</div>` : ''}
    <div class="mb"><nav class="snav" aria-label="Setting groups">${nav}<div class="sep"></div><button class="${M.only && !q ? 'on' : ''}" data-only="1">${ic('<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/>')}<span class="lb">Changed for this lab</span><span class="${differ ? 'chg' : 'n'}">${differ}</span></button></nav>
    <div class="sc">${content}</div></div>
    <div class="mf"><div class="info">${nChanged ? `<span><span class="cnt">${nChanged} unsaved change${nChanged > 1 ? 's' : ''}</span>. Saving restarts the scene.</span>` : '<span>No unsaved changes.</span>'}${M.err ? `<span class="err">${esc(M.err)}</span>` : ''}${!lock && differ ? '<button class="lk" id="ssReset">Reset all to the Playground\'s settings</button>' : ''}</div>
    <button class="btn" id="ssDiscard"${nChanged ? '' : ' disabled'}>Discard</button><button class="save" id="ssSave"${nChanged && !lock && !M.busy ? '' : ' disabled'}>${M.busy ? 'Saving…' : 'Save'}</button></div>
    <div id="ssDlg"></div>`;
  box.querySelectorAll('.sc input, .sc select').forEach(el => { if (lock) el.disabled = true; });
  const nsc = box.querySelector('.sc'); nsc.scrollTop = scroll;
  wire();
  if (first) box.querySelector('#ssQ').focus({preventScroll: true});
}

function check(el) {
  const raw = el.value.trim(), x = Number(raw);
  let msg = '';
  if (raw === '' || !isFinite(x)) msg = 'Type a number';
  else if (el.dataset.kind === 'int' && !Number.isInteger(x)) msg = 'Type a whole number';
  else if (el.dataset.lo != null && (x < +el.dataset.lo || x > +el.dataset.hi)) msg = `Between ${num(+el.dataset.lo)} and ${num(+el.dataset.hi)}`;
  el.classList.toggle('bad', !!msg);
  const er = box.querySelector(`[data-err="${el.dataset.id}"]`); if (er) er.textContent = msg;
  return msg ? null : x;
}
function wire() {
  const all = items(), byId = Object.fromEntries(all.map(it => [it.id, it]));
  box.querySelector('#ssX').onclick = () => close();
  wireTabs();
  const qi = box.querySelector('#ssQ');
  qi.oninput = () => { M.q = qi.value; draw(); const n = box.querySelector('#ssQ'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); };
  box.querySelectorAll('.snav [data-g]').forEach(b => b.onclick = () => { M.group = b.dataset.g; M.q = ''; M.only = false; draw(); });
  box.querySelector('.snav [data-only]').onclick = () => { M.only = true; M.q = ''; draw(); };
  box.querySelectorAll('select.v').forEach(el => el.onchange = () => {
    const it = byId[el.dataset.id]; setVal(it, it.mat ? +el.value : el.value); draw();
  });
  box.querySelectorAll('input.v').forEach(el => {
    el.onchange = () => {
      const x = check(el); if (x == null) { updateFooter(); return; }
      const it = byId[el.dataset.id], cur = it.get(M.draft);
      setVal(it, el.dataset.i != null ? cur.map((v, i) => i === +el.dataset.i ? x : v) : x);
      draw();
    };
    el.oninput = () => { check(el); updateFooter(); };
    el.onkeydown = (e) => { if (e.key === 'Enter') el.blur(); };
  });
  box.querySelectorAll('.sw').forEach(b => b.onclick = () => { const it = byId[b.dataset.id]; setVal(it, !it.get(M.draft)); draw(); });
  box.querySelectorAll('[data-undo]').forEach(b => b.onclick = () => { const it = byId[b.dataset.undo]; setVal(it, clone(it.get(M.data.current))); draw(); });
  box.querySelectorAll('[data-pg]').forEach(b => b.onclick = () => { const it = byId[b.dataset.pg]; setVal(it, clone(pgVal(it))); draw(); });
  const rs = box.querySelector('#ssReset'); if (rs) rs.onclick = () => { for (const it of all) if (fromPlayground(it)) setVal(it, clone(pgVal(it))); draw(); };
  box.querySelector('#ssDiscard').onclick = () => { M.draft = clone(M.data.current); M.err = ''; draw(); };
  box.querySelector('#ssSave').onclick = confirmSave;
  box.querySelectorAll('[data-tip]').forEach(b => {
    b.onmouseenter = () => { if (!tip.classList.contains('pinned')) showTip(byId[b.dataset.tip], b, false); };
    b.onmouseleave = () => { if (!tip.classList.contains('pinned')) setTimeout(() => { if (!tip.matches(':hover') && !tip.classList.contains('pinned')) hideTip(); }, 120); };
    b.onfocus = () => { if (!tip.classList.contains('pinned')) showTip(byId[b.dataset.tip], b, false); };
    b.onblur = () => { if (!tip.classList.contains('pinned')) hideTip(); };
    b.onclick = (e) => { e.stopPropagation(); showTip(byId[b.dataset.tip], b, true); };
  });
}
function updateFooter() {
  const s = box.querySelector('#ssSave'), n = items().filter(changed).length;
  if (s) s.disabled = !n || !!bad() || !!locked() || M.busy;
}

// The (i) note: hover shows it, a click pins it open (with a close button).
let tipFor = null;
function showTip(it, anchor, pin) {
  if (!it) return;
  tipFor = anchor;
  box.querySelectorAll('.ib.on').forEach(x => x.classList.remove('on'));
  if (pin) anchor.classList.add('on');
  const mj = mjVal(it);
  tip.innerHTML = `<div class="th"><b>${esc(it.mat ? it.mat[1][0].toUpperCase() + it.mat[1].slice(1) : it.label)}</b><span class="key" style="font:500 12px 'JetBrains Mono',monospace;color:#4B5563;background:#F3F4F6;border-radius:5px;padding:1px 6px">${esc(it.mat ? 'geom/' + it.mat[1] : it.key)}</span><button class="tx" aria-label="Close">${XI}</button></div>
    <p>${esc(DOCS[it.doc] || '')}</p>
    <div class="tf">${mj != null ? `<span>MuJoCo's default: <b>${esc(show(mj))}</b></span>` : ''}${!it.mat ? `<span>Playground's value: <b>${esc(show(pgVal(it)))}</b></span>` : ''}<a href="${M.data.doc}${it.anchor}" target="_blank" rel="noopener">Read MuJoCo's docs ↗</a></div>`;
  tip.classList.add('open'); tip.classList.toggle('pinned', !!pin);
  tip.querySelector('.tx').onclick = () => hideTip(true);
  const r = anchor.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
  let x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8), y = r.bottom + 8;
  if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 8);
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
function hideTip(force) {
  if (tip.classList.contains('pinned') && !force) return;
  tip.classList.remove('open', 'pinned'); tipFor = null;
  box.querySelectorAll('.ib.on').forEach(x => x.classList.remove('on'));
}
tip.addEventListener('mouseleave', () => { if (!tip.classList.contains('pinned')) hideTip(); });
document.addEventListener('click', (e) => { if (tip.classList.contains('pinned') && !e.target.closest('#ssTip') && !e.target.closest('[data-tip]')) hideTip(true); });

function confirmSave() {
  if (bad()) return;
  const ch = items().filter(changed), dlg = box.querySelector('#ssDlg');
  dlg.innerHTML = `<div class="bx" role="alertdialog" aria-labelledby="ssDlgT"><h3 id="ssDlgT">Save ${ch.length} change${ch.length > 1 ? 's' : ''} and restart the scene?</h3>
    <p>The lab is rebuilt with the new settings. Every robot and object goes back to where it started.</p>
    <div class="chl">${ch.map(it => `<div><span>${esc(it.label)}</span><code>${esc(show(it.get(M.data.current)))} → ${esc(show(it.get(M.draft)))}</code></div>`).join('')}</div>
    <div class="act"><button class="btn" id="ssNo">Keep editing</button><button class="save" id="ssYes">Save and restart</button></div></div>`;
  dlg.classList.add('open');
  dlg.querySelector('#ssNo').onclick = () => dlg.classList.remove('open');
  dlg.querySelector('#ssYes').onclick = save;
  dlg.querySelector('#ssYes').focus();
}
async function save() {
  M.busy = true; M.err = '';
  const dlg = box.querySelector('#ssDlg'); dlg.querySelector('#ssYes').disabled = true; dlg.querySelector('#ssYes').textContent = 'Saving…';
  const r = await api('/pg/settings', {settings: sessionSettings()});
  M.busy = false;
  if (!r || !r.ok) { M.err = (r && r.error) || 'Could not save the settings'; draw(); return; }
  M.data = r; M.draft = clone(r.current);
  wrap.classList.remove('open'); hideTip(true);
  toast('Scene settings saved. The scene restarted.');
  if (M.opener && M.opener.focus) M.opener.focus();
}

// ---------------------------------------------------------------- General tab
const G = {data: null, open_: '', err: {}, busy: '', gerr: '', saveT: null, cg: null, cgT: null};
const PROV_INFO = {
  openai: {what: 'GPT models, run through Codex', where: '<a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">platform.openai.com</a>. Paid per use from your OpenAI account.'},
  anthropic: {what: 'Claude models, run through Claude Code', where: '<a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>. Paid per use from your Anthropic account.'},
  cognition: {what: 'SWE models, run through Devin', where: 'Devin\'s settings, under Service users (the key starts with cog_).'},
  typesafe: {what: 'Jev, TypeSafe\'s decision model', where: 'your TypeSafe account.'},
};
const fmtDate = (s) => { try { return new Date(s).toLocaleDateString(undefined, {month: 'short', day: 'numeric', year: 'numeric'}); } catch (e) { return ''; } };
G.load = async () => {
  G.open_ = ''; G.err = {}; G.gerr = '';
  if (!G.data) {
    box.innerHTML = `<div class="mh tabbed">${tabsHtml()}<span class="sub">Loading…</span><button class="x" id="ssX" aria-label="Close settings">${XI}</button></div>`;
    wireTabs(); box.querySelector('#ssX').onclick = () => close();
  }
  const r = await api('/pg/account').catch(() => null);
  if (M.tab !== 'general') return;
  if (!r || !r.ok) { G.data = null; G.gerr = (r && r.error) || 'Could not load your settings. Try again.'; }
  else { G.data = r; if (window.onAccount) window.onAccount(r); }
  G.draw();
};
G.draw = () => {
  const d = G.data;
  let body;
  if (!d) body = `<div class="gerr">${esc(G.gerr)}</div>`;
  else {
    const n = d.run_minutes;
    const rows = d.providers.map(p => {
      const inf = PROV_INFO[p.id] || {what: '', where: ''}, open = G.open_ === p.id, busy = G.busy === p.id;
      const chatgpt = p.connected && p.kind === 'chatgpt';
      const facts = !p.connected ? esc(inf.what) : (chatgpt
        ? ['ChatGPT plan', p.email ? esc(p.email) : '', p.connected_at ? `Connected ${esc(fmtDate(p.connected_at))}` : '']
        : [`API key <span class="mkey">••••${esc(p.last4 || '')}</span>`, p.spent_usd != null ? `Spent here: $${(+p.spent_usd).toFixed(2)}` : '', p.connected_at ? `Connected ${esc(fmtDate(p.connected_at))}` : '']
      ).filter(Boolean).join('<i></i>');
      const acts = open ? '' : p.connected
        ? `<button class="bt" data-edit="${p.id}"${busy ? ' disabled' : ''}>Edit</button><button class="bt red" data-off="${p.id}"${busy ? ' disabled' : ''}>Disconnect</button>`
        : `<button class="bt pri" data-edit="${p.id}">Connect</button>`;
      const form = open ? `<div class="gexp">${p.id === 'openai' ? G.cgHtml(p) : ''}<div class="way"><h4>${p.id === 'openai' ? (p.connected && !chatgpt ? 'Or replace your API key' : 'Or add an API key') : p.connected ? 'Replace your API key' : 'Add an API key'}</h4><p>Get one from ${inf.where}</p>
        <input class="kin${G.err[p.id] ? ' bad' : ''}" id="gsKey" type="password" autocomplete="off" spellcheck="false" placeholder="Paste API key" aria-label="${esc(p.label)} API key"${G.err[p.id] ? ' aria-describedby="gsErr" aria-invalid="true"' : ''}>
        ${G.err[p.id] ? `<span class="emsg" id="gsErr" role="alert">${esc(G.err[p.id])}</span>` : ''}
        <div class="row2"><button class="bt pri" id="gsSave"${busy ? ' disabled' : ''}>${busy ? 'Checking…' : 'Save'}</button><button class="bt" id="gsCancel"${busy ? ' disabled' : ''}>Cancel</button></div></div></div>` : '';
      return `<div class="con"><span class="lg"><img src="${LOGOS[p.id] || ''}" alt=""></span><div class="t"><b>${esc(p.label)} <span class="stt${p.connected ? ' ok' : ''}">${p.connected ? 'Connected' : 'Not connected'}</span></b><span class="d">${facts}</span></div><div class="acts">${acts}</div></div>${form}`;
    }).join('');
    body = `<section><h3>Time limit</h3><div class="tlr"><span id="gsTlLab">Max minutes per AI run (${d.min_minutes} to ${d.max_minutes}).</span>
      <div class="stp" role="group" aria-labelledby="gsTlLab"><button id="gsMinus" aria-label="One minute less"${n <= d.min_minutes ? ' disabled' : ''}>&#8722;</button><output id="gsMin" aria-live="polite">${n} min</output><button id="gsPlus" aria-label="One minute more"${n >= d.max_minutes ? ' disabled' : ''}>+</button></div></div></section>
      <section><h3>Connections</h3><div class="cons">${rows}</div></section>`;
  }
  const focusId = document.activeElement && box.contains(document.activeElement) ? document.activeElement.id : '';
  box.innerHTML = `<div class="mh tabbed">${tabsHtml()}<button class="x" id="ssX" aria-label="Close settings">${XI}</button></div><div class="gs">${body}</div><div id="ssDlg"></div>`;
  wireTabs(); box.querySelector('#ssX').onclick = () => close();
  if (focusId && box.querySelector('#' + focusId) && !box.querySelector('#' + focusId).disabled) box.querySelector('#' + focusId).focus();
  if (!d) return;
  const step = (dx) => {
    d.run_minutes = Math.max(d.min_minutes, Math.min(d.max_minutes, d.run_minutes + dx));
    G.draw();
    clearTimeout(G.saveT);      // saved once the clicking stops
    G.saveT = setTimeout(async () => {
      const r = await api('/pg/account', {action: 'minutes', minutes: d.run_minutes}).catch(() => null);
      if (!r || !r.ok) toast((r && r.error) || 'Could not save the time limit');
      else if (window.onAccount) window.onAccount(r);
    }, 450);
  };
  box.querySelector('#gsMinus').onclick = () => step(-1);
  box.querySelector('#gsPlus').onclick = () => step(1);
  box.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => {
    G.open_ = b.dataset.edit; G.err = {}; G.draw();
    const k = box.querySelector('#gsKey'); if (k) k.focus();
  });
  box.querySelectorAll('[data-off]').forEach(b => b.onclick = async () => {
    const p = d.providers.find(x => x.id === b.dataset.off);
    const what = p.kind === 'chatgpt' ? 'ChatGPT sign-in' : `${p.label} key`;
    if (!(await askConfirm(`Disconnect ${p.label}?`, `Your ${what} is deleted here. ${p.label} models can't run until you connect again.`, 'Disconnect'))) return;
    G.busy = p.id; G.draw();
    const r = await api('/pg/account', {action: 'disconnect', provider: p.id}).catch(() => null);
    G.busy = '';
    if (r && r.ok) { G.data = r; if (window.onAccount) window.onAccount(r); toast(`${p.label} disconnected`); }
    else toast((r && r.error) || 'Could not disconnect');
    G.draw();
  });
  const save = async () => {
    const pid = G.open_, key = box.querySelector('#gsKey').value.trim();
    if (!key) { G.err = {[pid]: 'Paste your API key first.'}; G.draw(); box.querySelector('#gsKey').focus(); return; }
    G.busy = pid; G.err = {}; G.draw(); box.querySelector('#gsKey').value = key;
    const r = await api('/pg/account', {action: 'connect', provider: pid, key}).catch(() => null);
    G.busy = '';
    if (r && r.ok) {
      G.data = r; G.open_ = ''; if (window.onAccount) window.onAccount(r); G.draw();
      toast(`${(r.providers.find(x => x.id === pid) || {}).label || 'Account'} connected`);
      return;
    }
    G.err = {[pid]: (r && r.error) || 'Couldn\'t connect. Try again.'};
    G.draw();
    const k2 = box.querySelector('#gsKey'); if (k2) { k2.value = key; k2.focus(); }
  };
  const sv = box.querySelector('#gsSave');
  if (sv) {
    sv.onclick = save;
    box.querySelector('#gsKey').addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    box.querySelector('#gsCancel').onclick = () => { G.cgStop(true); G.open_ = ''; G.err = {}; G.draw(); };
  }
  const cgb = box.querySelector('#gsCg');
  if (cgb) cgb.onclick = G.cgStart;
  const cgc = box.querySelector('#gsCgCancel');
  if (cgc) cgc.onclick = () => { G.cgStop(true); G.draw(); };
  const cgy = box.querySelector('#gsCgCopy');
  if (cgy) cgy.onclick = () => { try { navigator.clipboard.writeText(G.cg.code); toast('Code copied'); } catch (e) {} };
};

// Sign in with ChatGPT (OpenAI only): Codex's own device code sign-in, run on the server. The
// page shows Codex's link and one-time code, then asks the server every few seconds whether the
// person has approved it on OpenAI's page.
G.cgHtml = (p) => {
  const cg = G.cg || {};
  let inner;
  if (cg.state === 'starting') inner = `<div class="row2"><span class="cgwait">Getting a sign-in code from Codex…</span><button class="bt" id="gsCgCancel">Cancel</button></div>`;
  else if (cg.state === 'waiting') inner = `<ol>
      <li>In ChatGPT, open Settings, then Security, and turn on <b>Enable device code sign-in for Codex</b>.</li>
      <li>Open <a href="${esc(cg.url)}" target="_blank" rel="noopener">${esc(cg.url.replace(/^https:[/][/]/, ''))}</a>, sign in, and enter this code:<br><span class="cgcode">${esc(cg.code)}</span><button class="bt" id="gsCgCopy">Copy</button></li>
    </ol>
    <p class="note">OpenAI's page warns about codes that come from a website. This code was made just now by Codex on your Playground server, because you clicked Sign in with ChatGPT. Only continue if you did. The code expires in 15 minutes.</p>
    <div class="row2"><span class="cgwait">Waiting for you to approve it…</span><button class="bt" id="gsCgCancel">Cancel</button></div>`;
  else inner = `<div class="row2"><button class="bt pri" id="gsCg">Sign in with ChatGPT</button></div>`;
  return `<div class="way"><h4>${p.connected && p.kind === 'chatgpt' ? 'Sign in with ChatGPT again' : 'Use your ChatGPT plan'}</h4>
    <p>Codex runs count toward your ChatGPT plan instead of being paid per use. Only Codex models can use it.</p>
    ${inner}${cg.err ? `<span class="emsg" role="alert">${esc(cg.err)}</span>` : ''}</div>`;
};
G.cgStop = (cancel) => {
  clearTimeout(G.cgT); G.cgT = null;
  const going = G.cg && (G.cg.state === 'starting' || G.cg.state === 'waiting');
  G.cg = null;
  if (cancel && going) api('/pg/account', {action: 'chatgpt_cancel'}).catch(() => null);
};
G.cgStart = async () => {
  G.cgStop(false);
  const mine = G.cg = {state: 'starting'}; G.draw();
  const r = await api('/pg/account', {action: 'chatgpt_start'}).catch(() => null);
  if (G.cg === mine) G.cgPoll(r);
};
G.cgPoll = (r) => {
  if (!G.cg) return;      // cancelled meanwhile
  if (!r || !r.ok) { G.cg = {err: (r && r.error) || "Couldn't sign in to ChatGPT. Try again."}; G.draw(); return; }
  const st = r.chatgpt || {};
  if (st.state === 'done') {
    G.cg = null; G.data = r; G.open_ = ''; if (window.onAccount) window.onAccount(r); G.draw();
    toast('OpenAI connected with your ChatGPT plan');
    return;
  }
  const changed = st.state !== G.cg.state;
  const mine = G.cg = {...G.cg, ...st};
  if (changed && wrap.classList.contains('open') && M.tab === 'general') G.draw();
  G.cgT = setTimeout(async () => {
    if (G.cg !== mine) return;
    if (!wrap.classList.contains('open')) return G.cgStop(true);
    const r2 = await api('/pg/account', {action: 'chatgpt_status'}).catch(() => null);
    if (G.cg === mine) G.cgPoll(r2);
  }, 3000);
};

window.openSettings = open;
wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });
document.addEventListener('keydown', (e) => {
  if (!wrap.classList.contains('open') || e.key !== 'Escape') return;
  const dlg = box.querySelector('#ssDlg');
  if (document.getElementById('cdlg') && !document.getElementById('cdlg').hidden) return;
  e.preventDefault();
  if (tip.classList.contains('pinned')) hideTip(true);
  else if (dlg && dlg.classList.contains('open')) dlg.classList.remove('open');
  else close();
});
// Free play only: the Settings button (in the robot rail) shows when the page is in free play.
setInterval(() => document.body.classList.toggle('freeplay', !!(S.scene && S.scene.mode === 'free')), 500);
})();
