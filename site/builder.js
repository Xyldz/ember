// builder.js - builder mode: a level editor for Ember's whole world.
//
// Open it with `python run_local.py --build` (or http://localhost:8000/?build while run_local.py is running).
// It only works on your own computer: run_local.py does the saving, uploading and publishing.
//
//   Buildings tab: the places Ember uses. World tab: the platform, sky, city, flying cars, neon signs and props.
//   Click anything to select it. W = move, E = rotate, R = resize. Del = delete. Esc = deselect. Ctrl+S = save.
//   Save writes buildings.json and site/scenery.json. Publish sends them (and your models) to GitHub.

import { TransformControls } from 'three/addons/controls/TransformControls.js';

const API_HEADERS = { 'X-Ember-Builder': '1' };
const NEEDS = ['charge', 'curiosity', 'joy', 'calm', 'connection'];
const UNLOCKS = [['search', 'Internet access (Ember can search here)'], ['rest', 'Proper rest (sleeping here recharges faster)'],
  ['radio', "A radio (Ember hears what's on the city's stations)"], ['friend', "Vega's desk (Ember's friend Vega works here)"],
  ['board', 'A bulletin board (notes you leave Ember and Vega get pinned here)'],
  ['telescope', 'A telescope (Ember sees the real sky up close here)'], ['art', "An art wall (Ember's newest art hangs here)"]];
const LOOK_NAMES = { terminal: 'Built-in: data terminal', pod: 'Built-in: charging pod', railing: 'Built-in: railing',
  radio: 'Built-in: old radio', bench: 'Built-in: bench', art_wall: 'Built-in: art wall', candle_board: 'Built-in: candlestick board', chart_shelf: 'Built-in: star chart shelf', shapes: 'Simple shapes', model: 'My 3D model (.glb / .obj)', placeholder: 'Placeholder box' };
const MODEL_FILE = /\.(glb|gltf|obj)$/i;
const EDGE_NAMES = ['front edge', 'back edge', 'right edge', 'left edge'];

const STYLE = `
  body.building #panel, body.building .needs, body.building .now-card, body.building #research, body.building #bubble { display: none !important; }
  #builder { width: 390px; flex: none; min-height: 0; overflow-y: auto; padding: 16px 18px 40px; border-left: 1px solid var(--line);
    background: var(--panel); font-size: 12px; }
  #builder h1 { font-size: 20px; }
  #builder h2 { margin: 18px 0 6px; }
  #builder .row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 6px 0; }
  #builder button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 3px; background: var(--card); color: var(--ink);
    font: inherit; font-size: 11px; font-weight: 700; cursor: pointer; }
  #builder button.on, #builder button.primary { border-color: var(--cyan); color: var(--cyan); }
  #builder .tabs2 button { flex: 1; padding: 8px; }
  #builder .tabs2 button.on { border-color: var(--magenta); color: var(--magenta); }
  #builder button.danger { border-color: rgba(255, 90, 90, .5); color: #ff8a8a; }
  #builder label { display: block; margin: 10px 0 3px; color: var(--muted); font-size: 10px; letter-spacing: .1em; text-transform: uppercase; }
  #builder label.check { display: flex; gap: 8px; align-items: center; margin: 6px 0; color: var(--ink); font-size: 12px; letter-spacing: 0; text-transform: none; }
  #builder input, #builder textarea, #builder select { box-sizing: border-box; width: 100%; padding: 6px 8px; border: 1px solid var(--line);
    border-radius: 3px; background: #070912; color: var(--ink); font: inherit; font-size: 12px; }
  #builder input[type=checkbox] { width: auto; }
  #builder input[type=color] { height: 30px; padding: 0 2px; }
  #builder input[type=range] { padding: 0; accent-color: var(--cyan); }
  #builder textarea { min-height: 64px; resize: vertical; }
  #builder .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(62px, 1fr)); gap: 6px; }
  #builder .grid label { margin-top: 0; }
  #builder .item { display: flex; justify-content: space-between; align-items: center; gap: 6px; margin: 4px 0; padding: 6px 8px;
    border: 1px solid var(--line); border-radius: 3px; cursor: pointer; }
  #builder .item.selected { border-color: var(--cyan); color: var(--cyan); }
  #builder .item .row { margin: 0; flex-wrap: nowrap; }
  #builder .item button { padding: 2px 8px; }
  #builder .hint { margin: 4px 0; color: var(--muted); font-size: 11px; font-style: italic; }
  #builder .status { min-height: 1.4em; margin: 6px 0; color: var(--amber); white-space: pre-wrap; }
  #builder .shape { margin: 8px 0; padding: 8px; border: 1px dashed var(--line); border-radius: 3px; }
  #builder details { margin: 10px 0; padding: 2px 10px 8px; border: 1px solid var(--line); border-radius: 3px; }
  #builder summary { padding: 8px 0 4px; color: var(--cyan); font-size: 11px; font-weight: 700; letter-spacing: .12em;
    text-transform: uppercase; cursor: pointer; }
  #builder .editing { margin-top: 10px; padding: 8px 10px; border-left: 2px solid var(--cyan); }
`;

export async function startBuilder(ctx) {
  const { THREE, scene, camera, renderer, controls, buildWorld, buildScenery } = ctx;
  document.head.append(Object.assign(document.createElement('style'), { textContent: STYLE }));
  document.body.classList.add('building');
  const panel = Object.assign(document.createElement('aside'), { id: 'builder' });
  document.getElementById('app').append(panel);

  const file = await (await fetch('/api/buildings', { cache: 'no-store' })).json();
  const doc = { buildings: file.buildings, empty_lots: file.empty_lots ?? [] };
  const scenery = structuredClone(await ctx.loadScenery());
  let tab = 'buildings', selection = null, dirty = false, mode = 'translate', status = '', lastDragEnd = 0;
  const openSections = new Set(['roof']);
  const timers = {};
  const soon = (name, fn) => { clearTimeout(timers[name]); timers[name] = setTimeout(fn, 250); }; // don't rebuild on every key press

  const round = (value, step = 0.01) => Math.round(value / step) * step;
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value));
  const edge = () => scenery.roof.size / 2 - 0.5; // buildings have to stay on the roof
  const lists = { building: () => doc.buildings, prop: () => scenery.props, sign: () => scenery.signs };
  const selectedThing = () => (selection ? lists[selection.kind]().find((t) => t.id === selection.id) ?? null : null);
  const groupFor = (sel) => (!sel ? null
    : sel.kind === 'building' ? ctx.getPlaces()[sel.id]?.group : ctx.getSceneryParts()[`${sel.kind}s`][sel.id]) ?? null;

  // ---- the drag handles ----------------------------------------------------------------------
  const gizmo = new TransformControls(camera, renderer.domElement);
  gizmo.setTranslationSnap(0.5);
  gizmo.setRotationSnap(THREE.MathUtils.degToRad(15));
  scene.add(gizmo);

  function applyAxes() {
    gizmo.setMode(mode);
    gizmo.showX = mode !== 'rotate';
    gizmo.showZ = mode !== 'rotate';
    // Buildings slide along the roof; signs and props can be lifted into the air
    gizmo.showY = mode !== 'translate' || selection?.kind !== 'building';
  }
  function attach() {
    const group = groupFor(selection);
    if (group) gizmo.attach(group); else gizmo.detach();
    applyAxes();
  }
  function rebuildWorld() { buildWorld(doc, true); attach(); }
  function rebuildScenery() { buildScenery(scenery); attach(); }
  const rebuildFor = (kind) => (kind === 'building' ? rebuildWorld : rebuildScenery);
  function changed() {
    dirty = true;
    setStatus('Unsaved changes.');
  }
  function setMode(next) {
    mode = next;
    applyAxes();
    renderPanel();
  }

  let lastScale = 1;
  gizmo.addEventListener('mouseDown', () => { lastScale = gizmo.object?.scale.x ?? 1; });
  gizmo.addEventListener('objectChange', () => {
    const group = gizmo.object;
    if (!group || !selection) return;
    if (selection.kind === 'building') group.position.set(clamp(group.position.x, -edge(), edge()), 0, clamp(group.position.z, -edge(), edge()));
    if (mode === 'scale') { // keep it in proportion: whichever handle you pulled sets the size
      const s = [group.scale.x, group.scale.y, group.scale.z].reduce((a, v) => (Math.abs(v - lastScale) > Math.abs(a - lastScale) ? v : a), lastScale);
      group.scale.setScalar(clamp(s, 0.1, 20));
    }
    readTransform(group);
  });
  gizmo.addEventListener('dragging-changed', (event) => {
    controls.enabled = !event.value;
    if (event.value) return;
    lastDragEnd = performance.now();
    if (selection?.kind === 'sign' && mode === 'scale') { // a sign's size is its width, so bake the stretch into it
      const sign = selectedThing();
      sign.size = round(clamp(sign.size * gizmo.object.scale.x, 1, 80), 0.1);
      rebuildScenery();
      renderPanel();
    }
  });

  function transformValue(thing, kind, key) {
    if (key === 'x') return thing.pos[0];
    if (key === 'y') return thing.pos[1];
    if (key === 'z') return kind === 'building' ? thing.pos[1] : thing.pos[2];
    if (key === 'rotation') { // signs face the roof until you turn them
      return thing.rotation ?? (kind === 'sign' ? round(THREE.MathUtils.radToDeg(Math.atan2(-thing.pos[0], -thing.pos[2])), 1) : 0);
    }
    if (key === 'scale') return thing.scale ?? 1;
    return thing.size;
  }
  function setTransform(thing, kind, key, value) {
    if (key === 'rotation') thing.rotation = value;
    else if (key === 'scale') thing.scale = clamp(value, 0.1, 20);
    else if (key === 'size') thing.size = clamp(value, 1, 80);
    else if (kind === 'building') thing.pos = key === 'x' ? [clamp(value, -edge(), edge()), thing.pos[1]] : [thing.pos[0], clamp(value, -edge(), edge())];
    else thing.pos = thing.pos.map((v, i) => (i === { x: 0, y: 1, z: 2 }[key] ? value : v));
  }
  function readTransform(group) { // copy the dragged position, turn and size into what gets saved
    const thing = selectedThing(), kind = selection.kind;
    if (!thing) return;
    const p = group.position;
    thing.pos = kind === 'building' ? [round(p.x), round(p.z)] : [round(p.x), round(p.y), round(p.z)];
    thing.rotation = round(THREE.MathUtils.radToDeg(group.rotation.y), 1);
    if (kind !== 'sign') thing.scale = round(group.scale.x);
    for (const input of panel.querySelectorAll('[data-transform]')) {
      if (document.activeElement !== input) input.value = transformValue(thing, kind, input.dataset.transform);
    }
    changed();
  }

  // Click anything to select it
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let downAt = null;
  renderer.domElement.addEventListener('pointerdown', (event) => { downAt = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (!downAt || gizmo.dragging || performance.now() - lastDragEnd < 150) return;
    if (Math.hypot(event.clientX - downAt[0], event.clientY - downAt[1]) > 5) return; // that was a camera drag
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const parts = ctx.getSceneryParts();
    const targets = [...ctx.getWorldGroup().children, ...Object.values(parts.props), ...Object.values(parts.signs)];
    for (const hit of raycaster.intersectObjects(targets, true)) {
      for (let o = hit.object; o; o = o.parent) {
        if (o.userData.buildingId !== undefined) return select({ kind: 'building', id: o.userData.buildingId });
        if (o.userData.propId !== undefined) return select({ kind: 'prop', id: o.userData.propId });
        if (o.userData.signId !== undefined) return select({ kind: 'sign', id: o.userData.signId });
      }
    }
    select(null);
  });

  function select(sel) {
    selection = sel;
    if (sel) {
      tab = sel.kind === 'building' ? 'buildings' : 'world';
      if (sel.kind !== 'building') openSections.add(`${sel.kind}s`);
    }
    attach();
    renderPanel();
  }

  // ---- adding and removing things ------------------------------------------------------------
  function freshId(base, list) {
    const stem = base.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_|_$/g, '').slice(0, 20) || 'thing';
    let id = stem;
    for (let n = 2; list.some((t) => t.id === id); n++) id = `${stem}_${n}`;
    return id;
  }
  function addBuilding(pos, template = null) {
    const building = template ? structuredClone(template) : {
      name: 'New building', about: '', actions: [], boosts: {},
      shapes: [{ type: 'box', size: [2, 2, 1.6], pos: [0, 1, -1.8], color: '#1b1f33' },
        { type: 'box', size: [1.6, 0.12, 0.05], pos: [0, 1.6, -0.98], color: '#3ff0ff', glow: true }],
    };
    building.id = freshId(template ? `${template.id}_copy` : 'building', doc.buildings);
    building.pos = [clamp(pos[0], -edge(), edge()), clamp(pos[1], -edge(), edge())];
    if (template) building.name = `${template.name} (copy)`;
    delete building.grants_wish;
    doc.buildings.push(building);
    changed();
    rebuildWorld();
    select({ kind: 'building', id: building.id });
  }
  function addProp(template = null) {
    const prop = template ? structuredClone(template) : {
      name: 'New prop', rotation: 0, scale: 1,
      shapes: [{ type: 'box', size: [1, 1, 1], pos: [0, 0.5, 0], color: '#3ff0ff', glow: true }],
    };
    prop.id = freshId(template ? `${template.id}_copy` : 'prop', scenery.props);
    prop.pos = template ? [template.pos[0] + 2, template.pos[1], template.pos[2]] : [round(controls.target.x, 0.5), 0, round(controls.target.z, 0.5)];
    if (template) prop.name = `${template.name} (copy)`;
    scenery.props.push(prop);
    changed();
    rebuildScenery();
    select({ kind: 'prop', id: prop.id });
  }
  function addSign() {
    const sign = { id: freshId('sign', scenery.signs), text: 'NEON', color: '#ff3fb4', size: 8, pos: [0, 14, -(scenery.roof.size / 2 + 22)] };
    scenery.signs.push(sign);
    changed();
    rebuildScenery();
    select({ kind: 'sign', id: sign.id });
  }
  function removeThing(kind, thing) {
    if (!thing) return;
    if (kind === 'building' && doc.buildings.length === 1) return setStatus('Ember needs at least one building.');
    if (!confirm(`Remove "${thing.name ?? thing.text ?? thing.id}"?`)) return;
    if (kind === 'building') doc.buildings = doc.buildings.filter((t) => t !== thing);
    else scenery[`${kind}s`] = scenery[`${kind}s`].filter((t) => t !== thing);
    if (selection?.kind === kind && selection.id === thing.id) selection = null;
    changed();
    rebuildFor(kind)();
    renderPanel();
  }

  // ---- saving, uploading, publishing ---------------------------------------------------------
  async function post(path, body, contentType = 'application/json') {
    const response = await fetch(path, { method: 'POST', headers: { ...API_HEADERS, 'Content-Type': contentType }, body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? `Something went wrong (${response.status}).`);
    return data;
  }
  async function save() {
    try {
      await post('/api/scenery', JSON.stringify(scenery)); // first, so the roof size is known when buildings are checked
      await post('/api/buildings', JSON.stringify(doc));
      dirty = false;
      setStatus('Saved. Publish to send it to the live Ember.');
      return true;
    } catch (error) {
      setStatus(`Couldn't save: ${error.message}`);
      return false;
    }
  }
  async function publish() {
    if (dirty && !(await save())) return;
    setStatus('Publishing to GitHub…');
    try {
      const result = await post('/api/publish', '{}');
      setStatus(result.ok ? result.log : `Publishing didn't work:\n${result.log}`);
    } catch (error) {
      setStatus(`Publishing didn't work: ${error.message}`);
    }
  }
  async function uploadModel(files, thing, rebuild) {
    if (!thing || !files.length) return;
    setStatus(`Uploading ${files.length} file${files.length === 1 ? '' : 's'}…`);
    try {
      const paths = [];
      for (const upload of files) paths.push((await post(`/api/upload?name=${encodeURIComponent(upload.name)}`, upload, 'application/octet-stream')).path);
      const main = paths.find((p) => MODEL_FILE.test(p));
      if (!main) return setStatus('Uploaded, but none of those was a model (.glb, .gltf or .obj).');
      thing.model = main;
      const mtl = paths.find((p) => /\.mtl$/i.test(p));
      if (mtl) thing.mtl = mtl; else delete thing.mtl;
      delete thing.shapes;
      changed();
      rebuild();
      renderPanel();
      setStatus(`Using ${main}. Drag to place it, and use R to resize.`);
    } catch (error) {
      setStatus(`Upload failed: ${error.message}`);
    }
  }
  function setStatus(text) {
    status = text;
    const line = panel.querySelector('.status');
    if (line) line.textContent = text;
  }

  // ---- small pieces of the panel ---------------------------------------------------------------
  function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
      if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (value !== undefined && value !== null && value !== false) node[key] = value;
    }
    node.append(...children.flat(Infinity).filter((child) => child !== null && child !== undefined && child !== false));
    return node;
  }
  const field = (labelText, input) => [h('label', { textContent: labelText }), input];
  const section = (key, title, ...children) => h('details', {
    open: openSections.has(key),
    ontoggle: (event) => (event.target.open ? openSections.add(key) : openSections.delete(key)),
  }, h('summary', { textContent: title }), ...children);

  // A control bound straight to a setting in scenery.json
  function setting(labelText, obj, key, kind, options = {}) {
    const label = h('label', { textContent: kind === 'range' ? `${labelText}: ${obj[key]}` : labelText });
    const update = (target) => {
      obj[key] = kind === 'check' ? target.checked : kind === 'color' ? target.value : Number(target.value);
      if (kind === 'range') label.textContent = `${labelText}: ${obj[key]}`;
      options.after?.();
      changed();
      soon('scenery', rebuildScenery);
    };
    if (kind === 'check') {
      return h('label', { className: 'check' }, h('input', { type: 'checkbox', checked: obj[key], onchange: (e) => update(e.target) }), labelText);
    }
    return [label, h('input', { type: kind, value: obj[key], min: options.min, max: options.max, step: options.step, oninput: (e) => update(e.target) })];
  }

  function transformInputs(thing, kind) {
    const keys = kind === 'building' ? [['x', 'x'], ['z', 'z'], ['rotation', 'turn °'], ['scale', 'size']]
      : [['x', 'x'], ['y', 'height'], ['z', 'z'], ['rotation', 'turn °'], [kind === 'sign' ? 'size' : 'scale', 'size']];
    return h('div', { className: 'grid' }, keys.map(([key, text]) => h('div', {},
      h('label', { textContent: text }),
      h('input', { type: 'number', step: key === 'rotation' ? 15 : key === 'scale' ? 0.1 : 0.5, value: transformValue(thing, kind, key),
        dataset: { transform: key },
        onchange: (event) => { setTransform(thing, kind, key, Number(event.target.value) || 0); changed(); rebuildFor(kind)(); } }))));
  }

  // model "" means "my own model, not uploaded yet"
  const lookOf = (t) => (ctx.builtInLooks.includes(t.model) ? t.model
    : MODEL_FILE.test(t.model ?? '') || t.model === '' ? 'model' : t.shapes?.length ? 'shapes' : 'placeholder');
  function applyLook(thing, choice) {
    if (ctx.builtInLooks.includes(choice)) { thing.model = choice; delete thing.shapes; delete thing.mtl; }
    if (choice === 'shapes') {
      delete thing.model; delete thing.mtl;
      thing.shapes = thing.shapes?.length ? thing.shapes : [{ type: 'box', size: [2, 2, 1.6], pos: [0, 1, -1.8], color: '#1b1f33' }];
    }
    if (choice === 'placeholder') { delete thing.model; delete thing.mtl; delete thing.shapes; }
    if (choice === 'model' && !MODEL_FILE.test(thing.model ?? '')) { thing.model = ''; delete thing.shapes; }
  }
  function lookEditor(thing, rebuild) {
    const look = lookOf(thing);
    return [
      field('Look', h('select', { onchange: (event) => { applyLook(thing, event.target.value); changed(); rebuild(); renderPanel(); } },
        Object.entries(LOOK_NAMES).map(([value, text]) => h('option', { value, textContent: text, selected: value === look })))),
      look === 'shapes' ? shapesEditor(thing, rebuild) : null,
      look === 'model' ? modelPicker(thing, rebuild) : null,
    ];
  }
  function modelPicker(thing, rebuild) {
    return h('div', {},
      h('p', { className: 'hint', textContent: MODEL_FILE.test(thing.model ?? '') ? `Using ${thing.model}${thing.mtl ? ` + ${thing.mtl}` : ''}` : 'No model yet.' }),
      h('label', { textContent: 'Upload a model' }),
      h('input', { type: 'file', multiple: true, accept: '.glb,.gltf,.bin,.obj,.mtl,.png,.jpg,.jpeg',
        onchange: (event) => uploadModel([...event.target.files], thing, rebuild) }),
      h('p', { className: 'hint', textContent: 'From Roblox Studio: select your build, File > Export Selection, then pick the .obj AND .mtl (and any textures) here together. From Blender: export .glb.' }),
      h('label', { className: 'check' },
        h('input', { type: 'checkbox', checked: thing.autofit !== false, onchange: (event) => {
          if (event.target.checked) delete thing.autofit; else thing.autofit = false;
          changed(); rebuild();
        } }), 'Auto-fit it to a lot (turn off to use the model\'s own size)'),
    );
  }
  function shapesEditor(thing, rebuild) {
    const edit = (apply) => (event) => { apply(event.target); changed(); soon('look', rebuild); };
    const triple = (shape, key, labels) => h('div', { className: 'grid' }, labels.map((axis, i) => h('div', {},
      h('label', { textContent: axis }),
      h('input', { type: 'number', step: 0.1, value: shape[key]?.[i] ?? (key === 'size' ? 1 : 0), oninput: edit((t) => {
        shape[key] = [...(shape[key] ?? (key === 'size' ? [1, 1, 1] : [0, 0, 0]))];
        shape[key][i] = Number(t.value) || 0;
      }) }))));
    return h('div', {},
      h('p', { className: 'hint', textContent: 'Positions are relative to its own centre: negative z is behind, y is height.' }),
      thing.shapes.map((shape, index) => h('div', { className: 'shape' },
        h('div', { className: 'row' },
          h('select', { style: 'width:auto', onchange: (event) => { shape.type = event.target.value; changed(); rebuild(); renderPanel(); } },
            ['box', 'cylinder', 'sphere'].map((type) => h('option', { value: type, textContent: type, selected: (shape.type ?? 'box') === type }))),
          h('input', { type: 'color', style: 'width:60px', value: shape.color ?? '#2a2f45', oninput: edit((t) => { shape.color = t.value; }) }),
          h('label', { className: 'check' }, h('input', { type: 'checkbox', checked: Boolean(shape.glow), onchange: edit((t) => { shape.glow = t.checked; }) }), 'neon'),
          h('button', { className: 'danger', textContent: '✕', onclick: () => { thing.shapes.splice(index, 1); changed(); rebuild(); renderPanel(); } })),
        h('label', { textContent: shape.type === 'cylinder' ? 'radius / height' : shape.type === 'sphere' ? 'radius' : 'width / height / depth' }),
        triple(shape, 'size', shape.type === 'sphere' ? ['r'] : shape.type === 'cylinder' ? ['r', 'h'] : ['w', 'h', 'd']),
        h('label', { textContent: 'position' }),
        triple(shape, 'pos', ['x', 'y', 'z']))),
      h('div', { className: 'row' }, h('button', { textContent: '+ Add shape', onclick: () => {
        thing.shapes.push({ type: 'box', size: [1, 1, 1], pos: [0, 0.5, 0], color: '#3ff0ff', glow: true });
        changed(); rebuild(); renderPanel();
      } })),
    );
  }
  function itemRow(kind, thing, label) {
    const isSelected = selection?.kind === kind && selection.id === thing.id;
    return h('div', { className: `item${isSelected ? ' selected' : ''}`, onclick: () => select({ kind, id: thing.id }) },
      h('span', { textContent: label }),
      h('span', { className: 'row' },
        h('span', { className: 'hint', textContent: thing.id }),
        h('button', { className: 'danger', title: `Delete ${label}`, textContent: '✕',
          onclick: (event) => { event.stopPropagation(); removeThing(kind, thing); } })));
  }

  // ---- the whole panel -----------------------------------------------------------------------
  function renderPanel() {
    const toolButton = (name, label, key) => h('button', { className: mode === name ? 'on' : '', textContent: `${label} (${key})`, onclick: () => setMode(name) });
    const tabButton = (name, label) => h('button', { className: tab === name ? 'on' : '', textContent: label, onclick: () => { tab = name; renderPanel(); } });
    const contents = h('div', {},
      h('h1', { textContent: 'Builder' }),
      h('p', { className: 'hint', textContent: 'Click anything to select it, then drag the arrows. Nothing reaches the live Ember until you Publish.' }),
      h('div', { className: 'row tabs2' }, tabButton('buildings', 'Buildings'), tabButton('world', 'World')),
      h('div', { className: 'row' }, toolButton('translate', 'Move', 'W'), toolButton('rotate', 'Rotate', 'E'), toolButton('scale', 'Resize', 'R')),
      h('div', { className: 'row' },
        h('button', { className: 'primary', textContent: 'Save', onclick: save }),
        h('button', { className: 'primary', textContent: 'Publish to GitHub', onclick: publish }),
        h('button', { textContent: 'Back to Ember', onclick: () => { location.href = '/'; } })),
      h('div', { className: 'status', textContent: status }),
      tab === 'buildings' ? buildingsTab() : worldTab(),
    );
    const scroll = panel.scrollTop;
    panel.replaceChildren(contents);
    panel.scrollTop = scroll; // stay where you were in the panel
  }

  function buildingsTab() {
    const building = selection?.kind === 'building' ? selectedThing() : null;
    return [
      h('h2', { textContent: 'Buildings' }),
      h('p', { className: 'hint', textContent: 'The places Ember can go and use.' }),
      doc.buildings.map((b) => itemRow('building', b, b.name)),
      h('div', { className: 'row' }, h('button', { textContent: '+ New building', onclick: () => addBuilding(doc.empty_lots.shift() ?? [0, 6]) })),

      h('h2', { textContent: 'Empty lots' }),
      h('p', { className: 'hint', textContent: 'Glowing squares where something could go. Ember knows how many there are.' }),
      doc.empty_lots.map((lot, i) => h('div', { className: 'item' },
        h('span', { textContent: `Lot at ${lot[0]}, ${lot[1]}` }),
        h('span', { className: 'row' },
          h('button', { textContent: 'Build here', onclick: () => { doc.empty_lots.splice(i, 1); addBuilding(lot); } }),
          h('button', { className: 'danger', textContent: '✕', onclick: () => { doc.empty_lots.splice(i, 1); changed(); rebuildWorld(); renderPanel(); } })))),
      h('div', { className: 'row' }, h('button', { textContent: '+ Empty lot', onclick: () => {
        const e = edge() - 2;
        doc.empty_lots.push([round(Math.random() * 2 * e - e, 0.5), round(Math.random() * 2 * e - e, 0.5)]);
        changed(); rebuildWorld(); renderPanel();
      } })),

      building ? buildingForm(building) : h('p', { className: 'hint', textContent: 'Select a building to edit it.' }),
    ];
  }

  function buildingForm(building) {
    const update = (apply) => (event) => { apply(event.target); changed(); soon('world', rebuildWorld); };
    const wishes = (ctx.getState()?.wishes ?? []).filter((w) => !w.granted);
    const wishKey = (w) => w.text.slice(0, 40).toLowerCase();
    return h('div', { className: 'editing' },
      h('h2', { textContent: `Editing: ${building.name}` }),
      field('Name', h('input', { value: building.name, oninput: update((t) => { building.name = t.value; }) })),
      field('Id (short, lowercase, no spaces)', h('input', { value: building.id, onchange: (event) => {
        const id = event.target.value.trim();
        if (!/^[a-z0-9_]{1,30}$/.test(id) || doc.buildings.some((b) => b !== building && b.id === id)) {
          event.target.value = building.id;
          return setStatus('Ids are lowercase letters, numbers and _, and must be unique.');
        }
        building.id = id;
        selection = { kind: 'building', id };
        changed(); rebuildWorld(); renderPanel();
      } })),
      field('What Ember reads about it', h('textarea', { value: building.about ?? '', oninput: update((t) => { building.about = t.value; }) })),
      h('p', { className: 'hint', textContent: 'Describe the place, not what Ember should do there. It decides that.' }),

      h('label', { textContent: 'What it unlocks' }),
      UNLOCKS.map(([action, text]) => h('label', { className: 'check' },
        h('input', { type: 'checkbox', checked: building.actions?.includes(action), onchange: update((t) => {
          building.actions = (building.actions ?? []).filter((a) => a !== action);
          if (t.checked) building.actions.push(action);
        }) }), text)),

      h('label', { textContent: 'Which needs it helps (Ember finds this out for itself)' }),
      h('div', { className: 'grid' }, NEEDS.map((need) => h('div', {},
        h('label', { textContent: need }),
        h('input', { type: 'number', min: -10, max: 10, value: building.boosts?.[need] ?? 0, onchange: update((t) => {
          building.boosts = { ...(building.boosts ?? {}) };
          const v = clamp(Number(t.value) || 0, -10, 10);
          if (v) building.boosts[need] = v; else delete building.boosts[need];
        }) })))),

      h('label', { textContent: 'Grants one of its wishes?' }),
      h('select', { onchange: update((t) => { if (t.value) building.grants_wish = t.value; else delete building.grants_wish; }) },
        h('option', { value: '', textContent: 'No' }),
        wishes.map((w) => h('option', { value: wishKey(w), textContent: w.text, selected: building.grants_wish === wishKey(w) })),
        building.grants_wish && !wishes.some((w) => wishKey(w) === building.grants_wish)
          ? h('option', { value: building.grants_wish, textContent: building.grants_wish, selected: true }) : null),

      h('label', { textContent: 'Position, turn and size' }),
      transformInputs(building, 'building'),
      lookEditor(building, rebuildWorld),

      h('div', { className: 'row' },
        h('button', { textContent: 'Duplicate', onclick: () => addBuilding([building.pos[0] + 2, building.pos[1]], building) }),
        h('button', { className: 'danger', textContent: 'Delete', onclick: () => removeThing('building', building) })),
    );
  }

  function worldTab() {
    const { roof, tower, city, cars, sky } = scenery;
    const keepBuildingsOnRoof = () => { // shrinking the roof pulls any buildings that would fall off back on
      for (const b of doc.buildings) b.pos = [clamp(b.pos[0], -edge(), edge()), clamp(b.pos[1], -edge(), edge())];
      soon('world', rebuildWorld);
    };
    const sign = selection?.kind === 'sign' ? selectedThing() : null;
    const prop = selection?.kind === 'prop' ? selectedThing() : null;
    return [
      section('roof', 'Platform',
        setting('Size (width of the roof)', roof, 'size', 'range', { min: 8, max: 60, step: 2, after: keepBuildingsOnRoof }),
        setting('Surface colour', roof, 'color', 'color'),
        setting('Show the grid', roof, 'grid', 'check'),
        setting('Grid colour', roof, 'grid_color', 'color'),
        h('div', { className: 'grid' }, roof.edge_colors.map((_, i) => h('div', {}, setting(EDGE_NAMES[i], roof.edge_colors, i, 'color')))),
        setting('Neon edge glow (0 = off)', roof, 'edge_glow', 'range', { min: 0, max: 3, step: 0.1 }),
        setting('Show the skyscraper underneath', tower, 'show', 'check'),
        setting('Skyscraper window colour', tower, 'window_color', 'color'),
        setting('Skyscraper depth', tower, 'depth', 'range', { min: 20, max: 300, step: 10 })),

      section('sky', 'Sky & light',
        setting('Sky colour', sky, 'color', 'color'),
        setting('Fog colour', sky, 'fog_color', 'color'),
        setting('Fog', sky, 'fog', 'range', { min: 0, max: 0.05, step: 0.001 }),
        setting('Light colour', sky, 'light_color', 'color'),
        setting('Light strength', sky, 'light', 'range', { min: 0, max: 4, step: 0.1 }),
        setting('Neon glow', sky, 'glow', 'range', { min: 0, max: 2, step: 0.05 }),
        setting('Brightness', sky, 'exposure', 'range', { min: 0.3, max: 2, step: 0.05 })),

      section('city', 'City',
        setting('Towers', city, 'towers', 'range', { min: 0, max: 400, step: 10 }),
        setting('Nearest towers (distance)', city, 'near', 'range', { min: 10, max: 150, step: 1 }),
        setting('Furthest towers (distance)', city, 'far', 'range', { min: 20, max: 300, step: 1 }),
        setting('Shortest tower', city, 'min_height', 'range', { min: 0, max: 200, step: 5 }),
        setting('Tallest tower', city, 'max_height', 'range', { min: 0, max: 400, step: 5 }),
        setting('Window glow', city, 'window_glow', 'range', { min: 0, max: 2, step: 0.05 }),
        setting('Antennas with red lights (share of towers)', city, 'antennas', 'range', { min: 0, max: 1, step: 0.05 }),
        h('label', { textContent: 'Window colours' }),
        h('div', { className: 'row' },
          city.colors.map((color, i) => h('span', { className: 'row' },
            h('input', { type: 'color', style: 'width:44px', value: color, oninput: (e) => { city.colors[i] = e.target.value; changed(); soon('scenery', rebuildScenery); } }),
            h('button', { className: 'danger', textContent: '✕', onclick: () => { city.colors.splice(i, 1); changed(); rebuildScenery(); renderPanel(); } }))),
          h('button', { textContent: '+ colour', onclick: () => { city.colors.push('#3ff0ff'); changed(); rebuildScenery(); renderPanel(); } })),
        h('div', { className: 'row' }, h('button', { textContent: 'New random city', onclick: () => {
          city.seed = Math.floor(Math.random() * 1e6);
          changed(); rebuildScenery(); renderPanel();
        } }), h('span', { className: 'hint', textContent: `city #${city.seed}` }))),

      section('cars', 'Flying cars',
        setting('How many', cars, 'count', 'range', { min: 0, max: 80, step: 1 })),

      section('signs', 'Neon signs',
        h('p', { className: 'hint', textContent: 'Signs out in the city. Click one (or pick it here) to move, turn or resize it.' }),
        scenery.signs.map((s) => itemRow('sign', s, s.text)),
        h('div', { className: 'row' }, h('button', { textContent: '+ New sign', onclick: addSign })),
        sign ? h('div', { className: 'editing' },
          field('Text', h('input', { value: sign.text, oninput: (e) => { sign.text = e.target.value; changed(); soon('scenery', rebuildScenery); } })),
          field('Colour', h('input', { type: 'color', value: sign.color, oninput: (e) => { sign.color = e.target.value; changed(); soon('scenery', rebuildScenery); } })),
          h('label', { textContent: 'Position, turn and size' }),
          transformInputs(sign, 'sign'),
          h('div', { className: 'row' }, h('button', { className: 'danger', textContent: 'Delete', onclick: () => removeThing('sign', sign) }))) : null),

      section('props', 'Props',
        h('p', { className: 'hint', textContent: 'Decorations: put them anywhere, even floating. Ember doesn\'t use them, it just sees them.' }),
        scenery.props.map((p) => itemRow('prop', p, p.name)),
        h('div', { className: 'row' }, h('button', { textContent: '+ New prop', onclick: () => addProp() })),
        prop ? h('div', { className: 'editing' },
          field('Name', h('input', { value: prop.name, oninput: (e) => { prop.name = e.target.value; changed(); } })),
          h('label', { textContent: 'Position, turn and size' }),
          transformInputs(prop, 'prop'),
          lookEditor(prop, rebuildScenery),
          h('div', { className: 'row' },
            h('button', { textContent: 'Duplicate', onclick: () => addProp(prop) }),
            h('button', { className: 'danger', textContent: 'Delete', onclick: () => removeThing('prop', prop) }))) : null),
    ];
  }

  // ---- keyboard shortcuts --------------------------------------------------------------------
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'w') setMode('translate');
    if (key === 'e') setMode('rotate');
    if (key === 'r') setMode('scale');
    if (key === 'delete' && selection) removeThing(selection.kind, selectedThing());
    if (key === 'escape') select(null);
  });
  window.addEventListener('beforeunload', (event) => { if (dirty) event.preventDefault(); });

  rebuildWorld();
  renderPanel();
  setStatus('Builder mode. Changes here are only saved when you press Save.');
}
