// TDD da lógica pura do radar (radar_logic.js). Rodar: node --test tests/test_radar_logic.js
const test = require('node:test');
const assert = require('node:assert');
const RL = require('../radar_logic.js');

test('resolvePeek: nao esta espiando -> false', () => {
  assert.strictEqual(RL.resolvePeek(false, {x:0,z:0}, {x:0,z:0}, 5, 5), false);
});

test('resolvePeek: parado perto da base -> continua espiando', () => {
  assert.strictEqual(RL.resolvePeek(true, {x:10,z:10}, {x:10,z:10}, 10.5, 10.2), true);
});

test('resolvePeek: andou >1.2 -> volta a seguir (false)', () => {
  assert.strictEqual(RL.resolvePeek(true, {x:10,z:10}, {x:10,z:10}, 12, 10), false);
});

// bug relatado pelo user: follow travava num ponto vazio apos TP
test('REGRESSAO TP: salto grande volta a seguir mesmo com peek travado', () => {
  assert.strictEqual(RL.resolvePeek(true, {x:490,z:490}, {x:10,z:10}, 500, 500), false);
});

// bug latente: peek setado com base nula (drag antes da 1a posicao) travava pra sempre
test('REGRESSAO base nula: peek sem base se recupera (false)', () => {
  assert.strictEqual(RL.resolvePeek(true, null, {x:10,z:10}, 10.1, 10.1), false);
});

test('xform: SWAP X<->Z com offsets identidade', () => {
  const adj={ox:0,oy:0,oz:0,fx:1,fz:1,swap:true};
  assert.deepStrictEqual(RL.xform(adj, 3, 7, 9), {x:9, y:7, z:3});  // mesh.x=game.z, mesh.z=game.x
});

test('xform/unxform: round-trip com offset/flip/swap', () => {
  const adj={ox:5,oy:-2,oz:8,fx:1,fz:-1,swap:true};
  const g={x:12.5, y:3.5, z:-4.5};
  const m=RL.xform(adj, g.x, g.y, g.z);
  const back=RL.unxform(adj, m.x, m.y, m.z);
  assert.ok(Math.abs(back.x-g.x)<1e-6 && Math.abs(back.y-g.y)<1e-6 && Math.abs(back.z-g.z)<1e-6);
});

test('poiRows: 1 item com descricao', () => {
  const r=RL.poiRows({label:'Chloranthy Ring', items:['Chloranthy Ring'], descs:['Raises stamina recovery speed']});
  assert.deepStrictEqual(r.rows, [{name:'Chloranthy Ring', desc:'Raises stamina recovery speed'}]);
  assert.strictEqual(r.hasDesc, true);
});

test('poiRows: multi-item pareia nome<->desc por indice', () => {
  const r=RL.poiRows({label:'Life Ring +N', items:['Life Ring','Large Titanite Shard'],
                      descs:['Raises maximum HP','Reinforces equipment']});
  assert.strictEqual(r.rows.length, 2);
  assert.strictEqual(r.rows[1].name, 'Large Titanite Shard');
  assert.strictEqual(r.rows[1].desc, 'Reinforces equipment');
});

test('poiRows: item sem descricao -> desc vazia, hasDesc so se algum tiver', () => {
  const r=RL.poiRows({label:'Halberd +N', items:['Halberd','Soul of a Nameless Soldier'],
                      descs:['','Use to acquire souls']});
  assert.strictEqual(r.rows[0].desc, '');
  assert.strictEqual(r.hasDesc, true);
});

test('poiRows: sem items (boss/bonfire) -> fallback no label, sem +', () => {
  const r=RL.poiRows({label:'The Pursuer', cat:'boss'});
  assert.deepStrictEqual(r.rows, [{name:'The Pursuer', desc:''}]);
  assert.strictEqual(r.hasDesc, false);
});
