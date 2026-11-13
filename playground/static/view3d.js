// The main 3D view, drawn in the browser with three.js (playground/scene3d.py serves the data).
// The scene's shapes, meshes and textures load once; a server-sent event stream then brings
// every body's pose ~30 times a second, the view's overlay shapes (placing ghost, selection
// ring) and the server's camera (for glides and presets). The camera itself moves here, with
// no round trip, so orbiting and panning are instant. The robot's own cameras stay rendered
// on the server. start() returns null if WebGL isn't available (the page keeps its video).
import * as THREE from '/pg/static/three.module.min.js';

const D2R = Math.PI / 180;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const FOVY = 45;

// ---------------------------------------------------------------- camera (MuJoCo's free camera)
function camFrame(c) {
  const az = c.azimuth * D2R, el = c.elevation * D2R;
  const fwd = new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el));
  const look = new THREE.Vector3(...c.lookat);
  const pos = look.clone().addScaledVector(fwd, -c.distance);
  const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 0, 1)).normalize();
  return {pos, fwd, right, look};
}
// The same moves the server makes for /pg/camera (PlaygroundSim.orbit and move_camera).
function applyDelta(c, d) {
  c = {...c, lookat: [...c.lookat]};
  c.azimuth = (((c.azimuth + (d.azimuth || 0)) % 360) + 360) % 360;
  c.elevation = clamp(c.elevation + (d.elevation || 0), -89, -3);
  c.distance = clamp(c.distance * (d.zoom || 1), 0.4, 8.0);
  const flatOf = (f) => { const v = new THREE.Vector3(f.x, f.y, 0); return v.lengthSq() > 1e-12 ? v.normalize() : v; };
  if (d.pan && (d.pan[0] || d.pan[1])) {
    const {fwd, right} = camFrame(c), flat = flatOf(fwd);
    const p = new THREE.Vector3(...c.lookat).addScaledVector(right, c.distance * d.pan[0]).addScaledVector(flat, c.distance * d.pan[1]);
    c.lookat = [p.x, p.y, p.z];
  }
  if (d.move) {
    const k = 0.05 * c.distance, {fwd, right} = camFrame(c), flat = flatOf(fwd);
    const p = new THREE.Vector3(...c.lookat).addScaledVector(right, d.move[0] * k).addScaledVector(flat, d.move[1] * k);
    p.z = clamp(p.z + d.move[2] * k, -0.5, 3.0);
    c.lookat = [p.x, p.y, p.z];
  }
  return c;
}

// ---------------------------------------------------------------- the light Tron floor (tron.py)
const TRON = {CYAN: [0.0, 0.85, 1.0], STEP: 0.5, REACH: 4.0, SEG: 0.5, Z: 0.0015, WIDTH: 0.012,
              RIPPLE_SPEED: 1.1, RIPPLE_EVERY: 4.0, STREAKS: 10, STREAK_SPEED: 1.6, TRAIL: 6, FLOOR: [0.975, 0.975, 0.965]};
const hash = (i, k) => { const x = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453; return x - Math.floor(x); };
function tronShapes(t) {
  const T = TRON, out = [], lines = [], pieces = [];
  for (let c = -T.REACH; c <= T.REACH + 1e-9; c += T.STEP) lines.push(c);
  for (let p = -T.REACH + T.SEG / 2; p < T.REACH; p += T.SEG) pieces.push(p);
  const breathe = 0.25 + 0.1 * Math.sin(t * 1.6), front = (t * T.RIPPLE_SPEED) % T.RIPPLE_EVERY;
  for (const c of lines) for (const p of pieces) {
    for (const [x, y, hx, hy] of [[c, p, T.WIDTH / 2, T.SEG / 2], [p, c, T.SEG / 2, T.WIDTH / 2]]) {
      const r = Math.hypot(x, y);
      let d = ((r - front) % T.RIPPLE_EVERY + T.RIPPLE_EVERY) % T.RIPPLE_EVERY;
      d = Math.min(d, T.RIPPLE_EVERY - d);
      const ring = Math.exp(-((d / 0.35) ** 2)), fade = Math.max(0, 1 - r / T.REACH);
      out.push([x, y, T.Z, hx, hy, (breathe + ring) * fade]);
    }
  }
  const span = 2 * T.REACH;
  for (let i = 0; i < T.STREAKS; i++) {
    const travelled = t * T.STREAK_SPEED * (0.7 + 0.6 * hash(i, 0)) + span * hash(i, 1);
    const lap = Math.floor(travelled / span), head = (travelled % span) - T.REACH;
    const line = lines[Math.floor(hash(i, lap + 7) * lines.length)];
    const alongX = hash(i, lap + 3) < 0.5, sign = hash(i, lap + 5) < 0.5 ? 1 : -1;
    for (let k = 0; k < T.TRAIL; k++) {
      const s = sign * (head - k * 0.06);
      if (Math.abs(s) > T.REACH) continue;
      const fade = (1 - k / T.TRAIL) * Math.max(0, 1 - Math.abs(s) / T.REACH * 0.6);
      out.push(alongX ? [s, line, T.Z + 0.0002, 0.035, T.WIDTH, fade] : [line, s, T.Z + 0.0002, T.WIDTH, 0.035, fade]);
    }
  }
  return out;
}

// ---------------------------------------------------------------- the view
export function start({stage, base = '', onReady}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
  } catch (e) { return null; }
  if (!renderer.getContext()) return null;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const canvas = renderer.domElement;
  canvas.className = 'view3d';
  stage.prepend(canvas);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color().setRGB(0.98, 0.984, 0.988, THREE.SRGBColorSpace);
  const camera = new THREE.PerspectiveCamera(FOVY, 1, 0.03, 160);
  camera.up.set(0, 0, 1);
  scene.add(camera);

  const V = {active: true, canvas, cam: {lookat: [0, 0, 0.85], distance: 2.8, azimuth: 145, elevation: -28},
             follow: true, lastLocal: 0, version: null, loading: false, bodies: [], ready: false};
  let root = new THREE.Group(); scene.add(root);
  let floorFx = null, shapesGroup = new THREE.Group(); scene.add(shapesGroup);
  const meshCache = new Map(), texCache = new Map();

  function resize() {
    const r = stage.getBoundingClientRect();
    if (r.width < 10 || r.height < 10) return;
    renderer.setSize(r.width, r.height, false);
    canvas.style.width = r.width + 'px'; canvas.style.height = r.height + 'px';
    camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(stage); resize();

  const srgb = (rgb) => new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);

  // Meshes and textures are kept by their contents (the server's hashes), not by session: the
  // robots, tables and objects every session shares are fetched and built once per page.
  function meshFrom(buf) {
    const [nv, nf, hasUv] = new Uint32Array(buf, 0, 3);
    let o = 12;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
    g.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
    if (hasUv) { g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 2), 2)); o += nv * 8; }
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, o, nf * 3), 1));
    g.userData.shared = true;
    return g;
  }
  // The meshes a world needs that the page doesn't have yet, in a few requests rather than one
  // each (each request waits a round trip to the lab, and only a few go at once).
  // A request to the lab that gives up after a while: a stuck one would leave the view loading
  // for good, and a fresh try usually goes through.
  function get(url, ms = 25000) {
    const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
    return fetch(url, {signal: c.signal}).then(r => r.ok ? r : Promise.reject(new Error(url + ' ' + r.status)))
      .finally(() => clearTimeout(t));
  }
  // Everything one load asks for goes to the session it is loading (src), even if the page has
  // switched to another session meanwhile: that session's world has other shapes and images.
  function fetchMeshes(hashes, src) {
    const missing = [...new Set(hashes)].filter(h => !meshCache.has(h));
    const per = Math.max(20, Math.ceil(missing.length / 3));
    for (let i = 0; i < missing.length; i += per) {
      const batch = missing.slice(i, i + per);
      const p = get(`${src}/pg/meshes?h=${batch.join(',')}`, 60000).then(r => r.arrayBuffer()).then(buf => {
        const out = new Map(), dv = new DataView(buf);
        let o = 0;
        for (const h of batch) {
          const n = dv.getUint32(o, true); o += 4;
          if (n === 0xFFFFFFFF) continue;
          out.set(h, meshFrom(buf.slice(o, o + n))); o += n;
        }
        return out;
      });
      for (const h of batch) {
        const g = p.then(m => m.get(h) || Promise.reject(new Error('no mesh ' + h)));
        g.catch(() => meshCache.delete(h));    // try again next time
        meshCache.set(h, g);
      }
    }
  }
  function meshGeometry(hash, src) {
    if (!meshCache.has(hash)) fetchMeshes([hash], src);
    return meshCache.get(hash);
  }
  // One texture per (image, repeat): a clone made before the image arrives would draw black.
  function texture(id, hash, rx, ry, src) {
    const key = [hash, rx, ry].join(':');
    if (!texCache.has(key)) {
      const t = new THREE.TextureLoader().load(`${src}/pg/tex/${id}.png?h=${hash}`, undefined, undefined,
                                               () => texCache.delete(key));   // try again next time
      t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = renderer.capabilities.getMaxAnisotropy();
      t.repeat.set(rx, ry);
      texCache.set(key, t);
    }
    return texCache.get(key);
  }

  async function geomObject(g, texhash, meshhash, src) {
    let geo;
    const s = g.size;
    if (g.type === 'box') geo = new THREE.BoxGeometry(2 * s[0], 2 * s[1], 2 * s[2]);
    else if (g.type === 'sphere') geo = new THREE.SphereGeometry(s[0], 32, 16);
    else if (g.type === 'ellipsoid') { geo = new THREE.SphereGeometry(1, 32, 16); geo.scale(s[0], s[1], s[2]); }
    else if (g.type === 'capsule') { geo = new THREE.CapsuleGeometry(s[0], 2 * s[1], 8, 24); geo.rotateX(Math.PI / 2); }
    else if (g.type === 'cylinder') { geo = new THREE.CylinderGeometry(s[0], s[0], 2 * s[1], 32); geo.rotateX(Math.PI / 2); }
    else if (g.type === 'plane') geo = new THREE.PlaneGeometry(2 * (s[0] || 40), 2 * (s[1] || 40));
    else if (g.type === 'mesh') geo = await meshGeometry(meshhash[String(g.mesh)], src);
    else return null;
    const mat = new THREE.MeshPhongMaterial({
      color: srgb(g.rgba), specular: new THREE.Color(g.specular * 0.3, g.specular * 0.3, g.specular * 0.3),
      shininess: 4 + 96 * g.shininess, transparent: g.rgba[3] < 1, opacity: g.rgba[3],
      emissive: srgb(g.rgba).multiplyScalar(g.emission)});
    if (g.tex >= 0) {
      const uni = g.type === 'plane' && g.texuniform;
      mat.map = texture(g.tex, texhash[String(g.tex)], uni ? 2 * (s[0] || 40) * g.texrepeat[0] : g.texrepeat[0],
                        uni ? 2 * (s[1] || 40) * g.texrepeat[1] : g.texrepeat[1], src);
    }
    const obj = new THREE.Mesh(geo, mat);
    obj.position.set(...g.pos);
    obj.quaternion.set(g.quat[1], g.quat[2], g.quat[3], g.quat[0]);
    obj.castShadow = g.type !== 'plane'; obj.receiveShadow = true;
    return obj;
  }

  // A soft object's mesh (a MuJoCo skin, scene3d.skin_bin): each vertex follows the bodies of
  // the simulated shape it is bound to, re-placed every pose frame (drawSkins).
  async function skinObject(sk, version, src, texhash) {
    const buf = await (await get(`${src}/pg/skin/${sk.id}.bin?v=${encodeURIComponent(version)}`)).arrayBuffer();
    const [nv, nf, hasUv, k] = new Uint32Array(buf, 0, 4);
    let o = 16;
    const rest = new Float32Array(buf, o, nv * 3); o += nv * 12;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(rest), 3));
    if (hasUv) { geo.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 2), 2)); o += nv * 8; }
    geo.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, o, nf * 3), 1)); o += nf * 12;
    const body = new Int32Array(buf, o, nv * k); o += nv * k * 4;
    const w = new Float32Array(buf, o, nv * k); o += nv * k * 4;
    const bind = new Float32Array(buf, o, nv * k * 3);
    geo.computeVertexNormals();
    const mat = new THREE.MeshPhongMaterial({
      color: srgb(sk.rgba), specular: new THREE.Color(sk.specular * 0.3, sk.specular * 0.3, sk.specular * 0.3),
      shininess: 4 + 96 * sk.shininess, side: THREE.DoubleSide});
    if (sk.tex >= 0) mat.map = texture(sk.tex, texhash[String(sk.tex)], 1, 1, src);
    const obj = new THREE.Mesh(geo, mat);
    obj.castShadow = obj.receiveShadow = true; obj.frustumCulled = false;
    return {obj, geo, rest, body, w, bind, k, nv};
  }
  function drawSkins(p) {
    for (const s of V.skins || []) {
      const out = s.geo.attributes.position.array, {rest, body, w, bind, k, nv} = s;
      for (let v = 0; v < nv; v++) {
        let x = rest[3 * v], y = rest[3 * v + 1], z = rest[3 * v + 2];
        for (let j = 0; j < k; j++) {
          const b = body[v * k + j]; if (b < 0) continue;
          const wt = w[v * k + j], bi = 3 * (v * k + j);
          x += wt * (p[3 * b] - bind[bi]); y += wt * (p[3 * b + 1] - bind[bi + 1]); z += wt * (p[3 * b + 2] - bind[bi + 2]);
        }
        out[3 * v] = x; out[3 * v + 1] = y; out[3 * v + 2] = z;
      }
      s.geo.attributes.position.needsUpdate = true;
      s.geo.computeVertexNormals();
    }
  }

  let gen = 0;     // bumped when the page switches to another session's world
  let loading = null;
  const retired = [];   // worlds taken off screen, freed once the new one has been drawn
  // A small "Loading" note over the view while a session's world fills in.
  const note = document.createElement('div');
  note.textContent = 'Loading this session…';
  note.setAttribute('role', 'status');
  Object.assign(note.style, {position: 'absolute', top: '64px', left: '50%', transform: 'translateX(-50%)', zIndex: 3,
    padding: '6px 12px', borderRadius: '999px', background: 'rgba(17,24,39,.78)', color: '#fff', font: '500 13px/1.2 system-ui, sans-serif',
    pointerEvents: 'none', opacity: '0', transition: 'opacity 150ms ease'});
  stage.appendChild(note);
  let noteT = null;
  const showNote = (on) => { clearTimeout(noteT); if (on) noteT = setTimeout(() => { note.style.opacity = '1'; }, 150); else note.style.opacity = '0'; };
  const pause = (ms) => new Promise(r => setTimeout(r, ms));

  // Load the world (one load at a time; a switch to another session meanwhile starts over).
  // A session just switched to shows at once: its lights and every shape already at hand, the
  // rest filling in as they arrive. A rebuild of the same session (an object added, say) swaps
  // in whole when ready, so nothing flickers.
  function loadScene() {
    if (!loading) loading = buildScene().finally(() => { loading = null; });
    return loading;
  }
  function install(next, sc, bodies, skins, head) {
    [...camera.children].forEach(c => { camera.remove(c); c.dispose && c.dispose(); }); camera.add(head); camera.add(head.target);
    scene.remove(root); retired.push(root); root = next; scene.add(root);
    V.bodies = bodies; V.skins = skins; V.version = sc.version;
    if (floorFx) { scene.remove(floorFx); floorFx = null; }
    if (sc.floorfx) floorFx = makeFloorFx();
    if (floorFx) scene.add(floorFx);
    if (!V.ready) { V.ready = true; onReady && onReady(); }
  }
  // Free the old worlds after the new one has been drawn: their shaders are then in use again
  // by the new world's materials, so they aren't thrown away and rebuilt.
  function freeRetired() {
    const old = retired.splice(0);
    requestAnimationFrame(() => requestAnimationFrame(() => old.forEach(dispose)));
  }
  async function buildScene() {
    for (let tries = 0; ; tries++) {
      const g0 = gen, fresh = V.version === null, src = base;
      try {
        const sc = await (await get(`${src}/pg/scene3d`)).json();
        if (g0 !== gen) continue;
        const texhash = sc.texhash || {};
        fetchMeshes(Object.values(sc.meshhash || {}), src);
        const next = new THREE.Group();
        const bodies = Array.from({length: sc.nbody}, () => { const b = new THREE.Group(); next.add(b); return b; });
        // Lights: MuJoCo's headlight (ambient + a light at the eye) and the scene's own lights.
        const amb = sc.headlight.ambient, dif = sc.headlight.diffuse;
        next.add(new THREE.AmbientLight(new THREE.Color(amb[0], amb[1], amb[2]), Math.PI));
        const head = new THREE.DirectionalLight(new THREE.Color(dif[0], dif[1], dif[2]), Math.PI);
        head.position.set(0, 0, 1); head.target.position.set(0, 0, -1);
        for (const l of sc.lights) {
          const L = new THREE.DirectionalLight(new THREE.Color(...l.diffuse), Math.PI);
          L.position.set(...l.pos); L.target.position.set(l.pos[0] + l.dir[0], l.pos[1] + l.dir[1], l.pos[2] + l.dir[2]);
          if (l.castshadow) {
            L.castShadow = true; L.shadow.mapSize.set(2048, 2048); L.shadow.bias = -0.0005;
            Object.assign(L.shadow.camera, {left: -4, right: 4, top: 4, bottom: -4, near: 0.1, far: 20});
          }
          next.add(L); next.add(L.target);
        }
        const skins = [];
        if (fresh) { install(next, sc, bodies, skins, head); showNote(true); }
        // Each shape goes in as soon as it is ready; one that fails doesn't hold up the rest.
        let failed = 0;
        await Promise.all([
          ...sc.geoms.map(g => geomObject(g, texhash, sc.meshhash, src).then(o => { if (o) bodies[g.body].add(o); }, () => { failed++; })),
          ...(sc.skins || []).map(sk => skinObject(sk, sc.version, src, texhash).then(s => { next.add(s.obj); skins.push(s); }, () => { failed++; }))]);
        if (g0 !== gen) { if (!fresh) dispose(next); continue; }
        if (!fresh) install(next, sc, bodies, skins, head);
        showNote(false); freeRetired();
        if (failed) {       // a few shapes didn't come: build the world again shortly (all at once)
          console.warn(`3D view: ${failed} shapes failed to load; trying again`);
          if (tries < 5) { await pause(1500); if (g0 === gen) continue; }
        }
      } catch (e) {
        console.warn('3D view: scene failed to load', e);
        if (tries < 20) { if (g0 === gen) await pause(Math.min(4000, 500 * (tries + 1))); continue; }
      }
      return;
    }
  }
  // A world taken off screen: free its GPU copies (not the meshes and textures kept for reuse).
  function dispose(group) {
    group.traverse(o => {
      if (o.geometry && !o.geometry.userData.shared) o.geometry.dispose();
      if (o.material) { o.material.dispose(); }
      if (o.isLight && o.dispose) o.dispose();
    });
  }

  function makeFloorFx() {
    const n = tronShapes(0).length + 50;
    const m = new THREE.InstancedMesh(new THREE.BoxGeometry(2, 2, 0.001), new THREE.MeshBasicMaterial(), n);
    m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3);
    m.frustumCulled = false;
    return m;
  }
  const _m = new THREE.Matrix4(), _c = new THREE.Color(), _q = new THREE.Quaternion(), _s = new THREE.Vector3(), _p = new THREE.Vector3();
  function drawFloorFx(t) {
    const shapes = tronShapes(t), T = TRON;
    let i = 0;
    for (const [x, y, z, hx, hy, a] of shapes) {
      if (a < 0.02 || i >= floorFx.count) continue;
      const k = Math.min(a, 1);
      _m.compose(_p.set(x, y, z), _q.identity(), _s.set(hx, hy, 1));
      floorFx.setMatrixAt(i, _m);
      // what MuJoCo's alpha blend gives over the light floor
      _c.setRGB(T.FLOOR[0] * (1 - k) + T.CYAN[0] * k, T.FLOOR[1] * (1 - k) + T.CYAN[1] * k, T.FLOOR[2] * (1 - k) + T.CYAN[2] * k, THREE.SRGBColorSpace);
      floorFx.setColorAt(i, _c); i++;
    }
    floorFx.count = i;
    floorFx.instanceMatrix.needsUpdate = true; floorFx.instanceColor.needsUpdate = true;
  }

  // Overlay shapes from the server (placing ghost, selection ring): boxes and flat cylinders.
  const pool = {box: [], cylinder: []};
  function drawShapes(shapes) {
    const used = {box: 0, cylinder: 0};
    for (const sh of shapes || []) {
      const kind = sh.type === 'cylinder' ? 'cylinder' : 'box';
      let o = pool[kind][used[kind]];
      if (!o) {
        const geo = kind === 'box' ? new THREE.BoxGeometry(2, 2, 2) : new THREE.CylinderGeometry(1, 1, 2, 48).rotateX(Math.PI / 2);
        o = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({transparent: true, depthWrite: false}));
        pool[kind].push(o); shapesGroup.add(o);
      }
      used[kind]++;
      o.visible = true;
      const s = sh.size;
      if (kind === 'box') o.scale.set(s[0], s[1], s[2] || 0.001); else o.scale.set(s[0], s[0], s[1] || 0.001);
      o.position.set(...sh.pos);
      o.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), sh.yaw || 0);
      o.material.color = srgb(sh.rgba); o.material.opacity = sh.rgba[3];
    }
    for (const k of ['box', 'cylinder']) for (let i = used[k]; i < pool[k].length; i++) pool[k][i].visible = false;
  }

  // Work boxes: around each robot at work, the space it works in. Nearly clear, with a thin
  // outline that glows in and out (the robots' own cameras see solid walls there instead).
  const zonesGroup = new THREE.Group(); scene.add(zonesGroup);
  const zonePool = [];
  const ZONE_COL = new THREE.Color(0x38BDF8);
  function setZones(zones) {
    zones = zones || [];
    for (let i = 0; i < zones.length; i++) {
      let z = zonePool[i];
      if (!z) {
        const box = new THREE.BoxGeometry(2, 2, 2);
        const fill = new THREE.Mesh(box, new THREE.MeshBasicMaterial({color: ZONE_COL, transparent: true, opacity: 0.035, depthWrite: false, side: THREE.DoubleSide}));
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({color: ZONE_COL, transparent: true, opacity: 0.6, depthWrite: false}));
        fill.renderOrder = edges.renderOrder = 5;
        const g = new THREE.Group(); g.add(fill, edges); zonesGroup.add(g);
        z = zonePool[i] = {g, fill, edges};
      }
      const d = zones[i];
      z.g.visible = true;
      z.g.scale.set(d.half[0], d.half[1], d.height / 2);
      z.g.position.set(d.pos[0], d.pos[1], d.height / 2);
      z.g.rotation.set(0, 0, d.yaw || 0);
      z.waiting = !!d.waiting;
    }
    for (let i = zones.length; i < zonePool.length; i++) zonePool[i].g.visible = false;
  }
  function pulseZones(t) {
    const k = 0.5 + 0.5 * Math.sin(t * 2.6);           // a slow breath, about 2.4 s
    for (const z of zonePool) {
      if (!z.g.visible) continue;
      const lo = z.waiting ? 0.18 : 0.35, hi = z.waiting ? 0.35 : 0.95;
      z.edges.material.opacity = lo + (hi - lo) * k;
      z.fill.material.opacity = (z.waiting ? 0.015 : 0.03) + 0.03 * k;
    }
  }
  V.setZones = setZones;

  // The pose stream.
  const b64 = (s) => { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return new Float32Array(a.buffer); };
  let es = null;
  function connect() {
    if (es) es.close();          // one stream at a time: each holds one of the few connections to the lab
    es = new EventSource(`${base}/pg/poses.sse`);
    es.onmessage = (ev) => {
      const f = JSON.parse(ev.data);
      if (f.v !== V.version) { loadScene(); return; }
      const p = b64(f.p), q = b64(f.q);
      V.rawP = p; V.rawQ = q;
      for (let i = 0; i < V.bodies.length; i++) {
        V.bodies[i].position.set(p[3 * i], p[3 * i + 1], p[3 * i + 2]);
        V.bodies[i].quaternion.set(q[4 * i + 1], q[4 * i + 2], q[4 * i + 3], q[4 * i]);
      }
      drawSkins(p);
      drawShapes(f.shapes);
      // Follow the server's camera (glides, presets, other tabs) unless moved here just now.
      if (V.follow && performance.now() - V.lastLocal > 800) V.cam = f.cam;
    };
    const mine = es;
    es.onerror = () => { mine.close(); if (es === mine) setTimeout(connect, 1500); };
  }

  function frame() {
    const {pos, look} = camFrame(V.cam);
    camera.position.copy(pos); camera.lookAt(look);
    drawPreview(); drawGizmo();
    if (V.onFrame) V.onFrame();
    if (floorFx) drawFloorFx(performance.now() / 1000);
    pulseZones(performance.now() / 1000);
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }


  // ---------------------------------------------------------------- rotate rings
  // Three rings around the selected object, one per world axis (X red, Y green, Z blue), the
  // same size on screen whatever the object's size. Dragging one turns the object about that
  // axis: the page shows it turning here (a preview over the pose stream) and tells the server
  // the angle on release.
  const AXES = {x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1]};
  const RING_COL = {x: 0xDC2626, y: 0x16A34A, z: 0x2563EB};
  const gizmo = new THREE.Group(); gizmo.visible = false; scene.add(gizmo);
  const rings = {}, hitRings = {};
  const torus = (k, tube, seg = 120) => {
    const geo = new THREE.TorusGeometry(1, tube, 12, seg);
    if (k === 'x') geo.rotateY(Math.PI / 2);
    if (k === 'y') geo.rotateX(Math.PI / 2);
    return geo;
  };
  for (const k of ['x', 'y', 'z']) {
    const mat = new THREE.MeshBasicMaterial({color: RING_COL[k], depthTest: false, transparent: true});
    const halo = new THREE.Mesh(torus(k, 0.055), new THREE.MeshBasicMaterial({color: 0xffffff, depthTest: false, transparent: true}));
    const ring = new THREE.Mesh(torus(k, 0.03), mat), fat = new THREE.Mesh(torus(k, 0.055), mat);
    halo.renderOrder = 998; ring.renderOrder = fat.renderOrder = 999;
    const hit = new THREE.Mesh(torus(k, 0.12, 60), new THREE.MeshBasicMaterial({visible: false}));
    const g = new THREE.Group(); g.add(halo, ring, fat, hit); gizmo.add(g);
    rings[k] = {g, ring, fat, halo}; hitRings[k] = hit;
  }
  // Move arrows: one per world axis, the same colours, shown instead of the rings in Move mode.
  // Dragging one slides the object along that axis only.
  const arrows = {}, hitArrows = {};
  const along = (geo, k) => { if (k === 'x') geo.rotateZ(-Math.PI / 2); if (k === 'z') geo.rotateX(Math.PI / 2); return geo; };
  const arrowGeo = (k, r, head) => {
    const shaft = new THREE.CylinderGeometry(r, r, 0.8, 16).translate(0, 0.55, 0);
    const cone = new THREE.ConeGeometry(head, 0.32, 24).translate(0, 1.1, 0);
    return [along(shaft, k), along(cone, k)];
  };
  for (const k of ['x', 'y', 'z']) {
    const mat = new THREE.MeshBasicMaterial({color: RING_COL[k], depthTest: false, transparent: true});
    const white = new THREE.MeshBasicMaterial({color: 0xffffff, depthTest: false, transparent: true, opacity: 0.9});
    const g = new THREE.Group(), thin = new THREE.Group(), fat = new THREE.Group(), halo = new THREE.Group();
    for (const geo of arrowGeo(k, 0.05, 0.13)) { const m = new THREE.Mesh(geo, white); m.renderOrder = 998; halo.add(m); }
    for (const geo of arrowGeo(k, 0.03, 0.1)) { const m = new THREE.Mesh(geo, mat); m.renderOrder = 999; thin.add(m); }
    for (const geo of arrowGeo(k, 0.05, 0.13)) { const m = new THREE.Mesh(geo, mat); m.renderOrder = 999; fat.add(m); }
    const hit = new THREE.Mesh(along(new THREE.CylinderGeometry(0.16, 0.16, 1.2, 12).translate(0, 0.65, 0), k), new THREE.MeshBasicMaterial({visible: false}));
    g.add(halo, thin, fat, hit); gizmo.add(g);
    arrows[k] = {g, thin, fat, halo, mat}; hitArrows[k] = hit;
  }
  let G = null;        // {center, mode: 'rotate' | 'move', axes: 'xyz' | 'xy' | 'z', active, hover}
  function ringScale() {
    if (!G) return 1;
    const c = new THREE.Vector3(...G.center);
    return camera.position.distanceTo(c) * Math.tan(FOVY * D2R / 2) * 0.16;
  }
  function drawGizmo() {
    gizmo.visible = !!G;
    if (!G) return;
    gizmo.position.set(...G.center);
    gizmo.scale.setScalar(ringScale());
    const mv = G.mode === 'move';
    for (const k of ['x', 'y', 'z']) {
      const a = arrows[k], dim = !!G.active && G.active !== k, big = G.active === k || (!G.active && G.hover === k);
      a.g.visible = mv && G.axes.includes(k);
      a.mat.opacity = dim ? 0.18 : 1; a.halo.visible = !dim; a.thin.visible = !big; a.fat.visible = big;
    }
    for (const k of ['x', 'y', 'z']) {
      const r = rings[k], dim = !!G.active && G.active !== k, big = G.active === k || (!G.active && G.hover === k);
      r.g.visible = !mv && G.axes.includes(k);
      r.ring.material.opacity = dim ? 0.18 : 1;
      r.halo.visible = !dim; r.halo.scale.setScalar(1); r.halo.material.opacity = 0.9;
      r.ring.visible = !big; r.fat.visible = big;
    }
  }
  const ray = new THREE.Raycaster();
  function rayAt(clientX, clientY) {
    const rc = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((clientX - rc.left) / rc.width * 2 - 1, -((clientY - rc.top) / rc.height) * 2 + 1), camera);
    return ray;
  }
  V.setGizmo = (g) => { G = g ? {...(G || {}), ...g} : null; };
  V.gizmoHit = (clientX, clientY) => {
    if (!G) return null;
    gizmo.updateMatrixWorld(true);
    const r = rayAt(clientX, clientY);
    let best = null;
    for (const k of G.axes.split('')) {
      const h = r.intersectObject((G.mode === 'move' ? hitArrows : hitRings)[k], false)[0];
      if (h && (!best || h.distance < best.d)) best = {k, d: h.distance};
    }
    return best && best.k;
  };
  // The angle (radians) of the pointer around the ring of axis k, seen from the camera.
  V.gizmoAngle = (k, clientX, clientY) => {
    const n = new THREE.Vector3(...AXES[k]), c = new THREE.Vector3(...G.center);
    const r = rayAt(clientX, clientY).ray;
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(n, c);
    const p = new THREE.Vector3();
    let v;
    if (Math.abs(r.direction.dot(n)) > 0.15 && r.intersectPlane(plane, p)) v = p.sub(c);
    else {            // the ring is seen edge-on: use where the pointer is on screen instead
      const s = c.clone().project(camera), m = new THREE.Vector3(r.origin.x, r.origin.y, r.origin.z).add(r.direction).project(camera);
      v = new THREE.Vector3(m.x - s.x, m.y - s.y, 0).applyQuaternion(camera.quaternion);
    }
    const u = new THREE.Vector3(...(k === 'z' ? [1, 0, 0] : k === 'x' ? [0, 1, 0] : [0, 0, 1]));
    const w = new THREE.Vector3().crossVectors(n, u);
    return Math.atan2(v.dot(w), v.dot(u));
  };
  // How far (m) along axis k through center (else the gizmo's centre) the pointer is: the point on that line
  // closest to the pointer's ray (null when the line points straight at the camera).
  V.arrowT = (k, clientX, clientY, center) => {
    if (!G && !center) return null;
    const a = new THREE.Vector3(...AXES[k]), c = new THREE.Vector3(...(center || G.center)), r = rayAt(clientX, clientY).ray;
    const w0 = c.clone().sub(r.origin), b = a.dot(r.direction), den = 1 - b * b;
    if (den < 1e-3) return null;
    return (b * r.direction.dot(w0) - a.dot(w0)) / den;
  };
  // Show bodies turned by angle (radians) about axis k through center, or slid by offset
  // ([dx, dy, dz] m), until cleared.
  let PV = null;
  V.setPreview = (pv) => { PV = pv; };
  function drawPreview() {
    if (!PV || !V.rawP) return;
    if (PV.offset) {
      const p = V.rawP;
      for (const i of PV.bodies) {
        const b = V.bodies[i]; if (!b) continue;
        b.position.set(p[3 * i] + PV.offset[0], p[3 * i + 1] + PV.offset[1], p[3 * i + 2] + PV.offset[2]);
      }
      return;
    }
    const qd = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...AXES[PV.axis]), PV.angle);
    const c = new THREE.Vector3(...PV.center), p = V.rawP, q = V.rawQ;
    for (const i of PV.bodies) {
      const b = V.bodies[i]; if (!b) continue;
      const v = new THREE.Vector3(p[3 * i], p[3 * i + 1], p[3 * i + 2]).sub(c).applyQuaternion(qd).add(c);
      b.position.copy(v);
      b.quaternion.copy(qd).multiply(new THREE.Quaternion(q[4 * i + 1], q[4 * i + 2], q[4 * i + 3], q[4 * i]));
    }
  }
  // Where the world's X, Y and Z point on screen (unit 2D vectors, y down), for the axis guide.
  V.axesOnScreen = () => {
    const out = {};
    for (const k of ['x', 'y', 'z']) {
      const v = new THREE.Vector3(...AXES[k]).applyQuaternion(camera.quaternion.clone().invert());
      out[k] = [v.x, -v.y];
    }
    return out;
  };

  V._scene = scene;   // for debugging from the console
  V.applyDelta = (d) => { V.cam = applyDelta(V.cam, d); V.lastLocal = performance.now(); };
  V.camForServer = () => ({...V.cam, aspect: camera.aspect});
  // A point in the world on screen (CSS pixels within the stage), e.g. to hang a tag over a robot.
  V.project = (p) => {
    const v = new THREE.Vector3(p[0], p[1], p[2]).project(camera);
    const w = parseFloat(canvas.style.width) || 0, h = parseFloat(canvas.style.height) || 0;
    return {x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h, visible: v.z < 1 && Math.abs(v.x) <= 1.2 && Math.abs(v.y) <= 1.2};
  };
  V.setFollow = (on) => { V.follow = on; if (on) V.lastLocal = 0; };
  // Another session: its own world (scene, meshes, textures and pose stream), drawn at once.
  V.setBase = (b) => {
    if (b === base) return;
    base = b; gen++; V.version = null; V.follow = true; V.lastLocal = 0;
    // The old session's world leaves the screen at once; the new one fills in as it loads.
    scene.remove(root); retired.push(root); root = new THREE.Group(); scene.add(root); V.bodies = []; V.skins = [];
    showNote(true);
    connect(); loadScene();
  };
  loadScene(); connect();
  requestAnimationFrame(frame);
  return V;
}
