// builder.js - builder mode: a little level editor for Ember's rooftop.
//
// Open it with `python run_local.py --build` (or http://localhost:8000/?build while run_local.py is running).
// It only works on your own computer: run_local.py does the saving, uploading and publishing.
//
//   Click a building to select it. W = move, E = rotate, R = resize. Del = delete. Ctrl+S = save.
//   Save writes buildings.json. Publish sends it (and your models) to GitHub, so the live Ember gets them.

import { TransformControls } from 'three/addons/controls/TransformControls.js';

const API_HEADERS = { 'X-Ember-Builder': '1' };
const NEEDS = ['charge', 'curiosity', 'joy', 'calm', 'connection'];
const UNLOCKS = [['search', 'Internet access (Ember can search here)'], ['rest', 'Proper rest (sleeping here recharges faster)']];
const LOOK_NAMES = { terminal: 'Built-in: data terminal', pod: 'Built-in: charging pod', railing: 'Built-in: railing',
  shapes: 'Simple shapes', model: 'My 3D model (.glb / .obj)', placeholder: 'Placeholder box' };
const MODEL_FILE = /\.(glb|gltf|obj)$/i;
const EDGE = 11.5;

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
  #builder button.danger { border-color: rgba(255, 90, 90, .5); color: #ff8a8a; }
  #builder label { display: block; margin: 10px 0 3px; color: var(--muted); font-size: 10px; letter-spacing: .1em; text-transform: uppercase; }
  #builder label.check { display: flex; gap: 8px; align-items: center; margin: 4px 0; color: var(--ink); font-size: 12px; letter-spacing: 0; text-transform: none; }
  #builder input, #builder textarea, #builder select { box-sizing: border-box; width: 100%; padding: 6px 8px; border: 1px solid var(--line);
    border-radius: 3px; background: #070912; color: var(--ink); font: inherit; font-size: 12px; }
  #builder input[type=checkbox] { width: auto; }
  #builder input[type=color] { height: 30px; padding: 0 2px; }
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
`;

export async function startBuilder(ctx) {
  const { THREE, scene, camera, renderer, controls, buildWorld } = ctx;
  document.head.append(Object.assign(document.createElement('style'), { textContent: STYLE }));
  document.body.classList.add('building');
  const panel = Object.assign(document.createElement('aside'), { id: 'builder' });
  document.getElementById('app').append(panel);

  const file = await (await fetch('/api/buildings', { cache: 'no-store' })).json();
  const doc = { buildings: file.buildings, empty_lots: file.empty_lots ?? [] };
  let selectedId = null, dirty = false, mode = 'translate', status = '', rebuildTimer = null, lastDragEnd = 0;

  // ---- the world and the drag handles -------------------------------------------------------
  const gizmo = new TransformControls(camera, renderer.domElement);
  gizmo.setTranslationSnap(0.5);
  gizmo.setRotationSnap(THREE.MathUtils.degToRad(15));
  scene.add(gizmo);

  const selected = () => doc.buildings.find((b) => b.id === selectedId) ?? null;
  const groupOf = (id) => ctx.getPlaces()[id]?.group ?? null;
  const round = (value, step = 0.01) => Math.round(value / step) * step;
  const clampEdge = (value) => Math.max(-EDGE, Math.min(EDGE, value));

  function rebuild() {
    buildWorld(doc, true);
    const group = groupOf(selectedId);
    if (group) gizmo.attach(group); else gizmo.detach();
  }
  function rebuildSoon() { // for typing: don't rebuild the world on every key press
    clearTimeout(rebuildTimer);
    rebuildTimer = setTimeout(rebuild, 300);
  }
  function changed() {
    dirty = true;
    setStatus('Unsaved changes.');
  }

  function setMode(next) {
    mode = next;
    gizmo.setMode(next);
    gizmo.showX = next !== 'rotate';
    gizmo.showZ = next !== 'rotate';
    gizmo.showY = next !== 'translate'; // buildings slide along the roof, they don't float
    renderPanel();
  }

  let lastScale = 1;
  gizmo.addEventListener('mouseDown', () => { lastScale = gizmo.object?.scale.x ?? 1; });
  gizmo.addEventListener('objectChange', () => {
    const group = gizmo.object;
    if (!group) return;
    group.position.set(clampEdge(group.position.x), 0, clampEdge(group.position.z));
    if (mode === 'scale') { // keep it in proportion: whichever handle you pulled sets the size
      const s = [group.scale.x, group.scale.y, group.scale.z].reduce((a, v) => (Math.abs(v - lastScale) > Math.abs(a - lastScale) ? v : a), lastScale);
      group.scale.setScalar(Math.max(0.2, Math.min(6, s)));
    }
    readTransform(group);
  });
  gizmo.addEventListener('dragging-changed', (event) => {
    controls.enabled = !event.value;
    if (!event.value) lastDragEnd = performance.now();
  });

  function readTransform(group) { // copy the dragged position/rotation/size into the building
    const building = selected();
    if (!building) return;
    building.pos = [round(group.position.x), round(group.position.z)];
    building.rotation = round(THREE.MathUtils.radToDeg(group.rotation.y), 1);
    building.scale = round(group.scale.x);
    for (const [key, value] of [['x', building.pos[0]], ['z', building.pos[1]], ['rotation', building.rotation], ['scale', building.scale]]) {
      const input = panel.querySelector(`[data-transform="${key}"]`);
      if (input && document.activeElement !== input) input.value = value;
    }
    changed();
  }

  // Click a building to select it
  const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
  let downAt = null;
  renderer.domElement.addEventListener('pointerdown', (event) => { downAt = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (!downAt || gizmo.dragging || performance.now() - lastDragEnd < 150) return;
    if (Math.hypot(event.clientX - downAt[0], event.clientY - downAt[1]) > 5) return; // that was a camera drag
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    for (const hit of raycaster.intersectObjects(ctx.getWorldGroup().children, true)) {
      let object = hit.object;
      while (object && object.userData.buildingId === undefined) object = object.parent;
      if (object) return select(object.userData.buildingId);
    }
    select(null);
  });

  function select(id) {
    selectedId = id;
    const group = groupOf(id);
    if (group) gizmo.attach(group); else gizmo.detach();
    renderPanel();
  }

  // ---- making and removing buildings ---------------------------------------------------------
  function freshId(base) {
    const stem = base.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_|_$/g, '').slice(0, 20) || 'building';
    let id = stem;
    for (let n = 2; doc.buildings.some((b) => b.id === id); n++) id = `${stem}_${n}`;
    return id;
  }
  function addBuilding(pos, template = null) {
    const building = template ? structuredClone(template) : {
      name: 'New building', about: '', actions: [], boosts: {},
      shapes: [{ type: 'box', size: [2, 2, 1.6], pos: [0, 1, -1.8], color: '#1b1f33' },
        { type: 'box', size: [1.6, 0.12, 0.05], pos: [0, 1.6, -0.98], color: '#3ff0ff', glow: true }],
    };
    building.id = freshId(template ? `${template.id}_copy` : 'building');
    building.pos = pos;
    if (template) building.name = `${template.name} (copy)`;
    delete building.grants_wish;
    doc.buildings.push(building);
    changed();
    rebuild();
    select(building.id);
  }
  function removeBuilding(building) {
    if (!building) return;
    if (doc.buildings.length === 1) return setStatus('Ember needs at least one building.');
    if (!confirm(`Remove "${building.name}" from the roof?`)) return;
    doc.buildings = doc.buildings.filter((b) => b !== building);
    if (building.id === selectedId) {
      selectedId = null;
      gizmo.detach();
    }
    changed();
    rebuild();
    renderPanel();
  }
  const removeSelected = () => removeBuilding(selected());

  // ---- saving, uploading, publishing ---------------------------------------------------------
  async function post(path, body, contentType = 'application/json') {
    const response = await fetch(path, { method: 'POST', headers: { ...API_HEADERS, 'Content-Type': contentType }, body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error ?? `Something went wrong (${response.status}).`);
    return data;
  }
  async function save() {
    try {
      await post('/api/buildings', JSON.stringify(doc));
      dirty = false;
      setStatus('Saved to buildings.json. Publish to send it to the live Ember.');
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
  async function uploadModel(files) {
    const building = selected();
    if (!building || !files.length) return;
    setStatus(`Uploading ${files.length} file${files.length === 1 ? '' : 's'}…`);
    try {
      const paths = [];
      for (const upload of files) paths.push((await post(`/api/upload?name=${encodeURIComponent(upload.name)}`, upload, 'application/octet-stream')).path);
      const main = paths.find((p) => MODEL_FILE.test(p));
      if (!main) return setStatus('Uploaded, but none of those was a model (.glb, .gltf or .obj).');
      building.model = main;
      const mtl = paths.find((p) => /\.mtl$/i.test(p));
      if (mtl) building.mtl = mtl; else delete building.mtl;
      delete building.shapes;
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

  // ---- the side panel -------------------------------------------------------------------------
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
  // model "" means "my own model, not uploaded yet"
  const lookOf = (b) => (ctx.builtInLooks.includes(b.model) ? b.model
    : MODEL_FILE.test(b.model ?? '') || b.model === '' ? 'model' : b.shapes?.length ? 'shapes' : 'placeholder');

  function renderPanel() {
    const building = selected();
    const toolButton = (name, label, key) => h('button', { className: mode === name ? 'on' : '', textContent: `${label} (${key})`, onclick: () => setMode(name) });
    const contents = h('div', {},
      h('h1', { textContent: 'Builder' }),
      h('p', { className: 'hint', textContent: 'Click a building to select it. Drag the arrows to move it. Nothing reaches the live Ember until you Publish.' }),
      h('div', { className: 'row' }, toolButton('translate', 'Move', 'W'), toolButton('rotate', 'Rotate', 'E'), toolButton('scale', 'Resize', 'R')),
      h('div', { className: 'row' },
        h('button', { className: 'primary', textContent: 'Save', onclick: save }),
        h('button', { className: 'primary', textContent: 'Publish to GitHub', onclick: publish }),
        h('button', { textContent: 'Back to Ember', onclick: () => { location.href = '/'; } })),
      h('div', { className: 'status', textContent: status }),

      h('h2', { textContent: 'Buildings' }),
      doc.buildings.map((b) => h('div', { className: `item${b.id === selectedId ? ' selected' : ''}`, onclick: () => select(b.id) },
        h('span', { textContent: b.name }),
        h('span', { className: 'row' },
          h('span', { className: 'hint', textContent: b.id }),
          h('button', { className: 'danger', title: `Delete ${b.name}`, textContent: '✕',
            onclick: (event) => { event.stopPropagation(); removeBuilding(b); } })))),
      h('div', { className: 'row' }, h('button', { textContent: '+ New building', onclick: () => addBuilding(doc.empty_lots.shift() ?? [0, 6]) })),

      h('h2', { textContent: 'Empty lots' }),
      h('p', { className: 'hint', textContent: 'Glowing squares where something could go. Ember knows how many there are.' }),
      doc.empty_lots.map((lot, i) => h('div', { className: 'item' },
        h('span', { textContent: `Lot at ${lot[0]}, ${lot[1]}` }),
        h('span', { className: 'row' },
          h('button', { textContent: 'Build here', onclick: () => { doc.empty_lots.splice(i, 1); addBuilding(lot); } }),
          h('button', { className: 'danger', textContent: '✕', onclick: () => { doc.empty_lots.splice(i, 1); changed(); rebuild(); renderPanel(); } })))),
      h('div', { className: 'row' }, h('button', { textContent: '+ Empty lot', onclick: () => {
        doc.empty_lots.push([round(Math.random() * 16 - 8, 0.5), round(Math.random() * 16 - 8, 0.5)]);
        changed(); rebuild(); renderPanel();
      } })),

      building ? buildingForm(building) : h('p', { className: 'hint', textContent: 'Select a building to edit it.' }),
    );
    const scroll = panel.scrollTop;
    panel.replaceChildren(contents);
    panel.scrollTop = scroll; // stay where you were in the panel
  }

  function buildingForm(building) {
    const update = (apply, { structural = false } = {}) => (event) => {
      apply(event.target);
      changed();
      if (structural) { rebuild(); renderPanel(); } else rebuildSoon();
    };
    const transformInput = (key, value, step) => h('input', {
      type: 'number', step, value, dataset: { transform: key },
      onchange: (event) => {
        const v = Number(event.target.value);
        if (key === 'x') building.pos = [clampEdge(v), building.pos[1]];
        if (key === 'z') building.pos = [building.pos[0], clampEdge(v)];
        if (key === 'rotation') building.rotation = v;
        if (key === 'scale') building.scale = Math.max(0.2, Math.min(6, v));
        changed();
        rebuild();
      },
    });
    const wishes = (ctx.getState()?.wishes ?? []).filter((w) => !w.granted);
    const look = lookOf(building);

    return h('div', {},
      h('h2', { textContent: `Editing: ${building.name}` }),
      field('Name', h('input', { value: building.name, oninput: update((t) => { building.name = t.value; }) })),
      field('Id (short, lowercase, no spaces)', h('input', { value: building.id, onchange: (event) => {
        const id = event.target.value.trim();
        if (!/^[a-z0-9_]{1,30}$/.test(id) || doc.buildings.some((b) => b !== building && b.id === id)) {
          event.target.value = building.id;
          return setStatus('Ids are lowercase letters, numbers and _, and must be unique.');
        }
        building.id = selectedId = id;
        changed(); rebuild(); renderPanel();
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
          const v = Math.max(-10, Math.min(10, Number(t.value) || 0));
          if (v) building.boosts[need] = v; else delete building.boosts[need];
        }) })))),

      h('label', { textContent: 'Grants one of its wishes?' }),
      h('select', { onchange: update((t) => { if (t.value) building.grants_wish = t.value; else delete building.grants_wish; }) },
        h('option', { value: '', textContent: 'No' }),
        wishes.map((w) => h('option', { value: w.text.slice(0, 40).toLowerCase(), textContent: w.text,
          selected: building.grants_wish === w.text.slice(0, 40).toLowerCase() })),
        building.grants_wish && !wishes.some((w) => w.text.slice(0, 40).toLowerCase() === building.grants_wish)
          ? h('option', { value: building.grants_wish, textContent: building.grants_wish, selected: true }) : null),

      h('label', { textContent: 'Position, turn and size' }),
      h('div', { className: 'grid' },
        h('div', {}, h('label', { textContent: 'x' }), transformInput('x', building.pos[0], 0.5)),
        h('div', {}, h('label', { textContent: 'z' }), transformInput('z', building.pos[1], 0.5)),
        h('div', {}, h('label', { textContent: 'turn °' }), transformInput('rotation', building.rotation ?? 0, 15)),
        h('div', {}, h('label', { textContent: 'size' }), transformInput('scale', building.scale ?? 1, 0.1))),

      field('Look', h('select', { onchange: update((t) => {
        const choice = t.value;
        if (ctx.builtInLooks.includes(choice)) { building.model = choice; delete building.shapes; delete building.mtl; }
        if (choice === 'shapes') { delete building.model; delete building.mtl; building.shapes = building.shapes?.length ? building.shapes : [{ type: 'box', size: [2, 2, 1.6], pos: [0, 1, -1.8], color: '#1b1f33' }]; }
        if (choice === 'placeholder') { delete building.model; delete building.mtl; delete building.shapes; }
        if (choice === 'model' && !MODEL_FILE.test(building.model ?? '')) { building.model = ''; delete building.shapes; }
      }, { structural: true }) }, Object.entries(LOOK_NAMES).map(([value, text]) => h('option', { value, textContent: text, selected: value === look })))),
      look === 'shapes' ? shapesEditor(building) : null,
      look === 'model' ? modelPicker(building) : null,

      h('div', { className: 'row' },
        h('button', { textContent: 'Duplicate', onclick: () => addBuilding([clampEdge(building.pos[0] + 2), building.pos[1]], building) }),
        h('button', { className: 'danger', textContent: 'Delete', onclick: removeSelected })),
    );
  }

  function modelPicker(building) {
    return h('div', {},
      h('p', { className: 'hint', textContent: MODEL_FILE.test(building.model ?? '') ? `Using ${building.model}${building.mtl ? ` + ${building.mtl}` : ''}` : 'No model yet.' }),
      h('label', { textContent: 'Upload a model' }),
      h('input', { type: 'file', multiple: true, accept: '.glb,.gltf,.bin,.obj,.mtl,.png,.jpg,.jpeg',
        onchange: (event) => uploadModel([...event.target.files]) }),
      h('p', { className: 'hint', textContent: 'From Roblox Studio: select your build, File > Export Selection, then pick the .obj AND .mtl (and any textures) here together. From Blender: export .glb.' }),
      h('label', { className: 'check' },
        h('input', { type: 'checkbox', checked: building.autofit !== false, onchange: (event) => {
          if (event.target.checked) delete building.autofit; else building.autofit = false;
          changed(); rebuild();
        } }), 'Auto-fit it to a lot (turn off to use the model\'s own size)'),
    );
  }

  function shapesEditor(building) {
    const edit = (apply) => (event) => { apply(event.target); changed(); rebuildSoon(); };
    const triple = (shape, key, labels) => h('div', { className: 'grid' }, labels.map((axis, i) => h('div', {},
      h('label', { textContent: axis }),
      h('input', { type: 'number', step: 0.1, value: shape[key]?.[i] ?? (key === 'size' ? 1 : 0), oninput: edit((t) => {
        shape[key] = [...(shape[key] ?? (key === 'size' ? [1, 1, 1] : [0, 0, 0]))];
        shape[key][i] = Number(t.value) || 0;
      }) }))));
    return h('div', {},
      h('p', { className: 'hint', textContent: 'Positions are relative to where Ember stands: negative z is behind it, y is height.' }),
      building.shapes.map((shape, index) => h('div', { className: 'shape' },
        h('div', { className: 'row' },
          h('select', { style: 'width:auto', onchange: (event) => { shape.type = event.target.value; changed(); rebuild(); renderPanel(); } },
            ['box', 'cylinder', 'sphere'].map((type) => h('option', { value: type, textContent: type, selected: (shape.type ?? 'box') === type }))),
          h('input', { type: 'color', style: 'width:60px', value: shape.color ?? '#2a2f45', oninput: edit((t) => { shape.color = t.value; }) }),
          h('label', { className: 'check' }, h('input', { type: 'checkbox', checked: Boolean(shape.glow), onchange: edit((t) => { shape.glow = t.checked; }) }), 'neon'),
          h('button', { className: 'danger', textContent: '✕', onclick: () => { building.shapes.splice(index, 1); changed(); rebuild(); renderPanel(); } })),
        h('label', { textContent: shape.type === 'cylinder' ? 'radius / height' : shape.type === 'sphere' ? 'radius' : 'width / height / depth' }),
        triple(shape, 'size', shape.type === 'sphere' ? ['r'] : shape.type === 'cylinder' ? ['r', 'h'] : ['w', 'h', 'd']),
        h('label', { textContent: 'position' }),
        triple(shape, 'pos', ['x', 'y', 'z']))),
      h('div', { className: 'row' }, h('button', { textContent: '+ Add shape', onclick: () => {
        building.shapes.push({ type: 'box', size: [1, 1, 1], pos: [0, 0.5, -1.5], color: '#3ff0ff', glow: true });
        changed(); rebuild(); renderPanel();
      } })),
    );
  }

  // ---- keyboard shortcuts --------------------------------------------------------------------
  window.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); save(); return; }
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === 'w') setMode('translate');
    if (key === 'e') setMode('rotate');
    if (key === 'r') setMode('scale');
    if (key === 'delete') removeSelected();
    if (key === 'escape') select(null);
  });
  window.addEventListener('beforeunload', (event) => { if (dirty) event.preventDefault(); });

  setMode('translate');
  rebuild();
  setStatus('Builder mode. Changes here are only saved when you press Save.');
}
