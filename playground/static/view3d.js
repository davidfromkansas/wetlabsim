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
  c.distance = clamp(c.distance * (d.zoom || 1), 0.4, 48.0);
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

// Particle-conserving grid automaton: persistent light packets visit local routing
// cells, which evolve when crossed. Packets usually continue straight, sometimes turn,
// and always take another cardinal edge. Nothing is born or extinguished mid-floor.
function createGridAutomaton(size = 33, seed = 0x74726f6e) {
  const step = 0.32, edges = new Float32Array(size * size * 4);
  const routing = new Uint8Array(size * size);
  const directions = [[1, 0], [0, 1], [-1, 0], [0, -1]];
  let previousTime = null;
  const random = () => {
    seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5;
    return (seed >>> 0) / 4294967296;
  };
  for (let i = 0; i < size * size; i++) {
    edges[i * 4] = edges[i * 4 + 2] = -10000;
    routing[i] = Math.floor(random() * 16);
  }
  const walkers = Array.from({length: 18}, () => ({
    x: Math.floor(random() * size), y: Math.floor(random() * size),
    dir: Math.floor(random() * 4), next: null, phase: random() * step,
  }));
  function move(w, time) {
    const cell = w.y * size + w.x, rule = routing[cell];
    // Fourteen of sixteen routing states carry on straight. The other two turn.
    const preferred = (w.dir + (rule === 0 ? 1 : rule === 1 ? 3 : 0)) % 4;
    routing[cell] = (rule + 5) % 16;
    const choices = [preferred, w.dir, (w.dir + 1) % 4, (w.dir + 3) % 4, (w.dir + 2) % 4];
    const dir = choices.find(d => {
      const [dx, dy] = directions[d];
      return w.x + dx >= 0 && w.x + dx < size && w.y + dy >= 0 && w.y + dy < size;
    });
    const [dx, dy] = directions[dir], nx = w.x + dx, ny = w.y + dy;
    const edge = (Math.min(w.y, ny) * size + Math.min(w.x, nx)) * 4 + (dy ? 2 : 0);
    edges[edge] = time; edges[edge + 1] = dx + dy;
    w.x = nx; w.y = ny; w.dir = dir;
  }
  return {edges, step, advance(time) {
    const resumed = previousTime === null || time - previousTime > step * 4;
    previousTime = time;
    let changed = false;
    for (const w of walkers) {
      if (resumed) w.next = time - w.phase;
      while (w.next <= time) {
        move(w, w.next); w.next += step; changed = true;
      }
    }
    return changed;
  }};
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
  scene.background = new THREE.Color(0x071019);
  const camera = new THREE.PerspectiveCamera(FOVY, 1, 0.03, 160);
  camera.up.set(0, 0, 1);
  scene.add(camera);

  const V = {active: true, canvas, cam: {lookat: [0, 0, 0.85], distance: 2.8, azimuth: 145, elevation: -28},
             follow: true, lastLocal: 0, version: null, loading: false, bodies: [], ready: false};
  let root = new THREE.Group(); scene.add(root);
  let shapesGroup = new THREE.Group(); scene.add(shapesGroup);
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

  async function geomObject(g, texhash, meshhash, src, themed) {
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
    if (themed && g.name === 'floor') {
      mat.color.set(0x101e29); mat.specular.set(0x587482); mat.shininess = 95;
    } else if (g.tex >= 0) {
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
    glassRoom.visible = !!sc.floorfx;
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
          ...sc.geoms.map(g => geomObject(g, texhash, sc.meshhash, src, sc.floorfx).then(o => { if (o) bodies[g.body].add(o); }, () => { failed++; })),
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
      if (o.userData.isOutline) return;   // shares its mesh's shape; its material is kept
      if (o.geometry && !o.geometry.userData.shared) o.geometry.dispose();
      if (o.material) { o.material.dispose(); }
      if (o.isLight && o.dispose) o.dispose();
    });
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

  // Audience-only animated floor. The
  // underlying MuJoCo floor, robot cameras and collision geometry are never changed.
  // Distance-field light strips provide a bright core and soft halo without a full-screen
  // bloom pass. Phong glass above the tracks adds a separate specular highlight layer.
  const roomClock = {value: 0};
  const automaton = createGridAutomaton();
  const gridFlow = new THREE.DataTexture(automaton.edges, 33, 33, THREE.RGBAFormat, THREE.FloatType);
  gridFlow.minFilter = gridFlow.magFilter = THREE.NearestFilter;
  gridFlow.needsUpdate = true;
  const roomVertex = `varying vec2 uvRoom;
    void main() { uvRoom = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
  const roomFragment = `
    uniform float time;
    uniform sampler2D gridFlow;
    uniform float gridStep;
    varying vec2 uvRoom;
    float strip(float d, float w) {
      return 1.0 - smoothstep(w, w + max(fwidth(d), 0.0015), abs(d));
    }
    // A bright moving head followed by a multi-cell tail. The same age/distance
    // relationship on successive edges keeps the ribbon continuous at intersections.
    float ribbon(float position, float age) {
      float behind = age - position;
      float glow = behind >= 0.0 ? exp(-behind / 1.1) : exp(-pow(behind / 0.12, 2.0));
      return glow * step(0.0, age) * (1.0 - smoothstep(3.5, 4.5, age));
    }
    void main() {
      vec2 metres = uvRoom * 120.0;
      vec3 cyan = vec3(0.20, 0.68, 0.86);
      vec3 white = vec3(0.68, 0.93, 1.0);
      vec3 light = vec3(0.0);
      // Independent packets follow actual horizontal or vertical edges. No diagonal
      // geometry, diagonal phase field, or animated fill inside the glass tiles.
      vec2 grid = metres / 0.625;
      vec2 joint = abs(grid - floor(grid + 0.5)) * 0.625;
      // The moving lights live on the middle 33 x 33 cells; the faint lines cover the whole floor.
      vec2 cell = grid - 80.0;   // (60 m - 10 m) / 0.625
      float inside = step(0.0, min(cell.x, cell.y)) * step(max(cell.x, cell.y), 33.0);
      vec4 horizontal = texture2D(gridFlow, (vec2(floor(cell.x), floor(cell.y + 0.5)) + 0.5) / 33.0);
      vec4 vertical = texture2D(gridFlow, (vec2(floor(cell.x + 0.5), floor(cell.y)) + 0.5) / 33.0);
      float hx = (time - horizontal.r) / gridStep;
      float vy = (time - vertical.b) / gridStep;
      float hp = horizontal.g > 0.0 ? fract(grid.x) : 1.0 - fract(grid.x);
      float vp = vertical.a > 0.0 ? fract(grid.y) : 1.0 - fract(grid.y);
      float hPulse = ribbon(hp, hx) * inside;
      float vPulse = ribbon(vp, vy) * inside;
      float hLine = strip(joint.y, 0.0018), vLine = strip(joint.x, 0.0018);
      vec2 halo = exp(-joint * 180.0) * (1.0 - smoothstep(vec2(0.018), vec2(0.035), joint));
      light = white * max(hLine, vLine) * 0.10 + cyan * max(halo.x, halo.y) * 0.025;
      light += white * (hLine * hPulse + vLine * vPulse) * 1.5;
      light += cyan * (halo.y * hPulse + halo.x * vPulse) * 0.36;
      // Additive light over the shadow-receiving floor material.
      gl_FragColor = vec4(light, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;
  const glassRoom = new THREE.Group(); glassRoom.name = 'Tron glass room';
  function lightSurface(geo) {
    return new THREE.Mesh(geo, new THREE.ShaderMaterial({
      uniforms: {time: roomClock,
        gridFlow: {value: gridFlow}, gridStep: {value: automaton.step}},
      vertexShader: roomVertex, fragmentShader: roomFragment,
      transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
  }
  const floorLight = lightSurface(new THREE.PlaneGeometry(120, 120));   // the whole floor (playground/world.py)
  floorLight.position.z = 0.002; glassRoom.add(floorLight);
  function glass(geo) {
    return new THREE.Mesh(geo, new THREE.MeshPhongMaterial({color: 0x17303d,
      specular: 0x87b5c6, shininess: 110, transparent: true, opacity: 0.10,
      depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1}));
  }
  const floorGlass = glass(floorLight.geometry);
  floorGlass.position.z = 0.006; floorGlass.receiveShadow = true; glassRoom.add(floorGlass);
  glassRoom.visible = false; scene.add(glassRoom);

  // Robots at work: a hologram shell round each working robot's own shape that moves with it.
  // Each of the robot's meshes gets a twin pushed out along smoothed normals (about 9 px at any
  // zoom). The shell is nearly clear where it faces the camera and glows only where it curves
  // away (a rim, so the robot stays visible through it), with faint scan lines drifting up. Its
  // light adds to what is behind it rather than covering it.
  // zones: [{bodies: [MuJoCo body ids of the robot], waiting}] (waiting = queued: dimmer).
  const outlineVertex = `
    attribute vec3 outlineNormal;
    uniform float widthPx;
    varying vec3 vNormal, vView, vWorld;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vec3 n = normalize(mat3(modelMatrix) * outlineNormal);
      float dist = length(cameraPosition - world.xyz);
      world.xyz += n * clamp(dist * widthPx * 0.0011, 0.006, 0.12);
      vNormal = n; vView = normalize(cameraPosition - world.xyz); vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }`;
  const outlineFragment = `
    uniform float strength, time;
    varying vec3 vNormal, vView, vWorld;
    void main() {
      float facing = abs(dot(normalize(vNormal), vView));
      float rim = pow(1.0 - facing, 3.0);
      float scan = smoothstep(0.82, 1.0, sin(vWorld.z * 140.0 - time * 3.0)) * 0.10;
      float a = (rim * 0.85 + scan * (0.4 + rim)) * strength;
      vec3 color = mix(vec3(0.10, 0.72, 0.82), vec3(0.80, 0.98, 1.0), rim);
      gl_FragColor = vec4(color * a, a);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`;
  const outlineUniforms = {strength: {value: 1.0}, widthPx: {value: 9.0}, time: {value: 0}};
  const outlineWaitUniforms = {strength: {value: 0.4}, widthPx: {value: 6.0}, time: outlineUniforms.time};
  const outlineMat = (u) => new THREE.ShaderMaterial({uniforms: u, vertexShader: outlineVertex,
    fragmentShader: outlineFragment, side: THREE.FrontSide, transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending});
  const outlineMats = {on: outlineMat(outlineUniforms), wait: outlineMat(outlineWaitUniforms)};
  // Normals averaged over vertices at the same place, so a box's or a mesh's hard edges don't
  // open cracks in the outline. Once per geometry (robots' meshes are shared between sessions).
  function outlineNormals(geo) {
    if (geo.attributes.outlineNormal) return;
    const pos = geo.attributes.position, nor = geo.attributes.normal, n = pos.count;
    const sums = new Map(), key = new Array(n), out = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const k = `${Math.round(pos.getX(i) * 1e4)},${Math.round(pos.getY(i) * 1e4)},${Math.round(pos.getZ(i) * 1e4)}`;
      key[i] = k;
      const v = sums.get(k) || [0, 0, 0];
      if (nor) { v[0] += nor.getX(i); v[1] += nor.getY(i); v[2] += nor.getZ(i); }
      sums.set(k, v);
    }
    for (let i = 0; i < n; i++) {
      const v = sums.get(key[i]), l = Math.hypot(v[0], v[1], v[2]) || 1;
      out[3 * i] = v[0] / l; out[3 * i + 1] = v[1] / l; out[3 * i + 2] = v[2] / l;
    }
    geo.setAttribute('outlineNormal', new THREE.BufferAttribute(out, 3));
  }
  let outlined = new Map();   // body id -> 'on' | 'wait'
  function setZones(zones) {
    const next = new Map();
    for (const z of zones || []) for (const b of z.bodies || []) next.set(b, z.waiting ? 'wait' : 'on');
    for (const b of outlined.keys()) if (!next.has(b)) outlineBody(b, null);
    outlined = next;
  }
  // Give a body's meshes their outline twins (or hide them: kind null). Run every frame, as a
  // world's meshes arrive a little after its bodies.
  function outlineBody(b, kind) {
    const body = V.bodies[b]; if (!body) return;
    for (const obj of body.children) {
      if (!obj.isMesh || obj.userData.isOutline) continue;
      let o = obj.userData.outline;
      if (!o) {
        if (!kind || !obj.geometry || !obj.geometry.attributes.position) continue;
        outlineNormals(obj.geometry);
        o = obj.userData.outline = new THREE.Mesh(obj.geometry, outlineMats[kind]);
        o.userData.isOutline = true; o.renderOrder = 5; o.castShadow = o.receiveShadow = false;
        obj.add(o);
      }
      o.visible = !!kind;
      if (kind) o.material = outlineMats[kind];
    }
  }
  function pulseZones(t) {
    outlineUniforms.strength.value = 0.92 + 0.08 * Math.sin(t * 2.2);
    outlineUniforms.time.value = t;
    for (const [b, kind] of outlined) outlineBody(b, kind);
  }
  V.setZones = setZones;

  // The pose stream.
  const b64 = (s) => { const bin = atob(s), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return new Float32Array(a.buffer); };
  let es = null;
  function connect() {
    if (es) es.close();          // one stream at a time: each holds one of the few connections to the lab
    es = null;
    if (document.hidden) return; // a tab in the background holds none (V.resume reconnects it)
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
      // Follow the server's own camera moves (glides, presets, framing a station) unless moved here
      // just now. Not its echo of this page's own zooms and drags: those can reach the server late
      // or not at all, and following them pulled the view back to where it was.
      const serverMove = f.camgen === undefined || f.camgen !== V.camGen || f.gliding;
      V.camGen = f.camgen;
      if (V.follow && serverMove && !V.glide && performance.now() - V.lastLocal > 800) V.cam = f.cam;
    };
    const mine = es;
    es.onerror = () => { mine.close(); if (es === mine) setTimeout(connect, 1500); };
  }

  function frame() {
    if (V.glide) glideStep();
    const {pos, look} = camFrame(V.cam);
    camera.position.copy(pos); camera.lookAt(look);
    drawPreview(); drawGizmo(); drawMarks();
    if (V.onFrame) V.onFrame();
    roomClock.value = performance.now() / 1000;
    if (glassRoom.visible && automaton.advance(roomClock.value)) gridFlow.needsUpdate = true;
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

  // Objects taken in by a box drawn over the scene: a blue outline box around each, drawn over
  // everything so it shows through what stands in front. marks: a list of body-index lists, or of
  // {bodies, corners} (corners: world points the box must take in too, e.g. a table's).
  let MK = [];
  const markBoxes = [], markColor = new THREE.Color(0x2563EB);
  V.setMarked = (marks) => { MK = marks || []; };
  function drawMarks() {
    while (markBoxes.length < MK.length) {
      const h = new THREE.Box3Helper(new THREE.Box3(), markColor);
      h.material.depthTest = false; h.material.transparent = true; h.renderOrder = 997;
      scene.add(h); markBoxes.push(h);
    }
    markBoxes.forEach((h, i) => {
      h.visible = i < MK.length;
      if (!h.visible) return;
      h.box.makeEmpty();
      const m = Array.isArray(MK[i]) ? {bodies: MK[i]} : MK[i];
      for (const b of m.bodies || []) if (V.bodies[b]) h.box.expandByObject(V.bodies[b]);
      for (const c of m.corners || []) h.box.expandByPoint(new THREE.Vector3(c[0], c[1], c[2]));
      if (h.box.isEmpty()) h.visible = false;
      else h.box.expandByScalar(0.008);
    });
  }

  V._scene = scene;   // for debugging from the console
  V.applyDelta = (d) => { V.glide = null; V.cam = applyDelta(V.cam, d); V.lastLocal = performance.now(); };
  // Glide the view to a camera (e.g. framing the robot just clicked), starting this frame: no
  // waiting on the server. A strong ease-out, so it moves at once and settles gently. While it
  // runs, and briefly after, the server's camera is not followed (it is told the end point).
  const GLIDE_MS = 600;
  V.glideTo = (to) => {
    if (!to || !to.lookat) return;
    const from = {...V.cam, lookat: [...V.cam.lookat]};
    const daz = ((to.azimuth - from.azimuth + 540) % 360) - 180;   // the short way round
    V.glide = {from, to, daz, t0: performance.now()};
    V.follow = true;
  };
  function glideStep() {
    const g = V.glide, t = Math.min(1, (performance.now() - g.t0) / GLIDE_MS);
    const k = 1 - Math.pow(1 - t, 4);                               // ease-out (quart)
    const mix = (a, b) => a + (b - a) * k;
    V.cam = {
      lookat: g.from.lookat.map((v, i) => mix(v, g.to.lookat[i])),
      distance: Math.exp(mix(Math.log(g.from.distance), Math.log(g.to.distance))),
      azimuth: (((g.from.azimuth + g.daz * k) % 360) + 360) % 360,
      elevation: mix(g.from.elevation, g.to.elevation),
    };
    if (t >= 1) { V.glide = null; V.lastLocal = performance.now(); }
  }
  V.camForServer = () => ({...V.cam, aspect: camera.aspect});
  // A point in the world on screen (CSS pixels within the stage), e.g. to hang a tag over a robot.
  V.project = (p) => {
    const v = new THREE.Vector3(p[0], p[1], p[2]).project(camera);
    const w = parseFloat(canvas.style.width) || 0, h = parseFloat(canvas.style.height) || 0;
    return {x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h, visible: v.z < 1 && Math.abs(v.x) <= 1.2 && Math.abs(v.y) <= 1.2};
  };
  // A tab in the background lets go of its pose stream, so other tabs of the same lab keep working.
  V.pause = () => { if (es) { es.close(); es = null; } };
  V.resume = () => { if (!es) connect(); };
  V.setFollow = (on) => { V.follow = on; if (on) V.lastLocal = 0; };
  // Another session: its own world (scene, meshes, textures and pose stream), drawn at once.
  V.setBase = (b) => {
    if (b === base) return;
    base = b; gen++; V.version = null; V.follow = true; V.lastLocal = 0; V.camGen = null;
    // The old session's world leaves the screen at once; the new one fills in as it loads.
    scene.remove(root); retired.push(root); root = new THREE.Group(); scene.add(root); V.bodies = []; V.skins = [];
    showNote(true);
    connect(); loadScene();
  };
  loadScene(); connect();
  requestAnimationFrame(frame);
  return V;
}
