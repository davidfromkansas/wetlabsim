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
  scene.background = new THREE.Color().setRGB(0.96, 0.965, 0.97, THREE.SRGBColorSpace);
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

  async function meshGeometry(id, hash) {
    const key = id + ':' + hash;
    if (!meshCache.has(key)) meshCache.set(key, (async () => {
      const buf = await (await fetch(`${base}/pg/mesh/${id}.bin?h=${hash}`)).arrayBuffer();
      const [nv, nf, hasUv] = new Uint32Array(buf, 0, 3);
      let o = 12;
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
      g.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 3), 3)); o += nv * 12;
      if (hasUv) { g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(buf, o, nv * 2), 2)); o += nv * 8; }
      g.setIndex(new THREE.BufferAttribute(new Uint32Array(buf, o, nf * 3), 1));
      return g;
    })());
    return meshCache.get(key);
  }
  // One texture per (image, repeat): a clone made before the image arrives would draw black.
  function texture(id, version, rx, ry) {
    const key = [id, version, rx, ry].join(':');
    if (!texCache.has(key)) {
      const t = new THREE.TextureLoader().load(`${base}/pg/tex/${id}.png?v=${encodeURIComponent(version)}`);
      t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
      t.anisotropy = renderer.capabilities.getMaxAnisotropy();
      t.repeat.set(rx, ry);
      texCache.set(key, t);
    }
    return texCache.get(key);
  }

  async function geomObject(g, version, meshhash) {
    let geo;
    const s = g.size;
    if (g.type === 'box') geo = new THREE.BoxGeometry(2 * s[0], 2 * s[1], 2 * s[2]);
    else if (g.type === 'sphere') geo = new THREE.SphereGeometry(s[0], 32, 16);
    else if (g.type === 'ellipsoid') { geo = new THREE.SphereGeometry(1, 32, 16); geo.scale(s[0], s[1], s[2]); }
    else if (g.type === 'capsule') { geo = new THREE.CapsuleGeometry(s[0], 2 * s[1], 8, 24); geo.rotateX(Math.PI / 2); }
    else if (g.type === 'cylinder') { geo = new THREE.CylinderGeometry(s[0], s[0], 2 * s[1], 32); geo.rotateX(Math.PI / 2); }
    else if (g.type === 'plane') geo = new THREE.PlaneGeometry(2 * (s[0] || 40), 2 * (s[1] || 40));
    else if (g.type === 'mesh') geo = await meshGeometry(g.mesh, meshhash[String(g.mesh)]);
    else return null;
    const mat = new THREE.MeshPhongMaterial({
      color: srgb(g.rgba), specular: new THREE.Color(g.specular * 0.3, g.specular * 0.3, g.specular * 0.3),
      shininess: 4 + 96 * g.shininess, transparent: g.rgba[3] < 1, opacity: g.rgba[3],
      emissive: srgb(g.rgba).multiplyScalar(g.emission)});
    if (g.tex >= 0) {
      const uni = g.type === 'plane' && g.texuniform;
      mat.map = texture(g.tex, version, uni ? 2 * (s[0] || 40) * g.texrepeat[0] : g.texrepeat[0],
                        uni ? 2 * (s[1] || 40) * g.texrepeat[1] : g.texrepeat[1]);
    }
    const obj = new THREE.Mesh(geo, mat);
    obj.position.set(...g.pos);
    obj.quaternion.set(g.quat[1], g.quat[2], g.quat[3], g.quat[0]);
    obj.castShadow = g.type !== 'plane'; obj.receiveShadow = true;
    return obj;
  }

  async function loadScene() {
    if (V.loading) return;
    V.loading = true;
    try {
      const sc = await (await fetch(`${base}/pg/scene3d`)).json();
      const next = new THREE.Group();
      const bodies = Array.from({length: sc.nbody}, () => { const b = new THREE.Group(); next.add(b); return b; });
      const objs = await Promise.all(sc.geoms.map(g => geomObject(g, sc.version, sc.meshhash).then(o => [g, o])));
      for (const [g, o] of objs) if (o) bodies[g.body].add(o);
      // Lights: MuJoCo's headlight (ambient + a light at the eye) and the scene's own lights.
      const amb = sc.headlight.ambient, dif = sc.headlight.diffuse;
      next.add(new THREE.AmbientLight(new THREE.Color(amb[0], amb[1], amb[2]), Math.PI));
      const head = new THREE.DirectionalLight(new THREE.Color(dif[0], dif[1], dif[2]), Math.PI);
      head.position.set(0, 0, 1); camera.children.forEach(c => camera.remove(c)); camera.add(head); camera.add(head.target);
      head.target.position.set(0, 0, -1);
      for (const l of sc.lights) {
        const L = new THREE.DirectionalLight(new THREE.Color(...l.diffuse), Math.PI);
        L.position.set(...l.pos); L.target.position.set(l.pos[0] + l.dir[0], l.pos[1] + l.dir[1], l.pos[2] + l.dir[2]);
        if (l.castshadow) {
          L.castShadow = true; L.shadow.mapSize.set(2048, 2048); L.shadow.bias = -0.0005;
          Object.assign(L.shadow.camera, {left: -4, right: 4, top: 4, bottom: -4, near: 0.1, far: 20});
        }
        next.add(L); next.add(L.target);
      }
      scene.remove(root); root = next; scene.add(root); V.bodies = bodies; V.version = sc.version;
      if (floorFx) { scene.remove(floorFx); floorFx = null; }
      if (sc.floorfx) floorFx = makeFloorFx();
      if (floorFx) scene.add(floorFx);
      if (!V.ready) { V.ready = true; onReady && onReady(); }
    } catch (e) { console.warn('3D view: scene failed to load', e); }
    V.loading = false;
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

  // The pose stream.
  const b64 = (s) => { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return new Float32Array(a.buffer); };
  let es = null;
  function connect() {
    es = new EventSource(`${base}/pg/poses.sse`);
    es.onmessage = (ev) => {
      const f = JSON.parse(ev.data);
      if (f.v !== V.version) { loadScene(); return; }
      const p = b64(f.p), q = b64(f.q);
      for (let i = 0; i < V.bodies.length; i++) {
        V.bodies[i].position.set(p[3 * i], p[3 * i + 1], p[3 * i + 2]);
        V.bodies[i].quaternion.set(q[4 * i + 1], q[4 * i + 2], q[4 * i + 3], q[4 * i]);
      }
      drawShapes(f.shapes);
      // Follow the server's camera (glides, presets, other tabs) unless moved here just now.
      if (V.follow && performance.now() - V.lastLocal > 800) V.cam = f.cam;
    };
    es.onerror = () => { es.close(); setTimeout(connect, 1500); };
  }

  function frame() {
    const {pos, look} = camFrame(V.cam);
    camera.position.copy(pos); camera.lookAt(look);
    if (floorFx) drawFloorFx(performance.now() / 1000);
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }

  V._scene = scene;   // for debugging from the console
  V.applyDelta = (d) => { V.cam = applyDelta(V.cam, d); V.lastLocal = performance.now(); };
  V.camForServer = () => ({...V.cam, aspect: camera.aspect});
  V.setFollow = (on) => { V.follow = on; if (on) V.lastLocal = 0; };
  loadScene().then(connect);
  requestAnimationFrame(frame);
  return V;
}
