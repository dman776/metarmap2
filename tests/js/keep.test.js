// The Must keep ticks and the box for extra airport codes.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { loadPlanner, baseRoutes } = require('./helper');
const { result } = require('./fixtures');

const ticks = (p) => Array.from(p.document.querySelectorAll('#pl-keep input')).map((i) => i.value);

// the page has no current airports in this harness (the template loop is dropped), so use a pasted list
async function pasted(codes) {
    const p = await loadPlanner(baseRoutes([['POST', /\/config\/planner\/plan$/, () => ({ status: 202, data: { id: 1 } })]]));
    p.$('pl-source').value = 'paste';
    p.$('pl-source').dispatchEvent(new p.window.Event('change'));
    p.$('pl-codes').value = codes;
    p.$('pl-codes').dispatchEvent(new p.window.Event('input'));
    return p;
}

async function planBody(p) {
    p.$('planner-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
    await new Promise((r) => setImmediate(r));
    const post = p.calls.find((c) => c.method === 'POST' && /planner\/plan$/.test(c.url));
    return post && post.body;
}

test('the tick boxes are in alphabetical order', async () => {
    const p = await pasted('KSAT KAUS KDFW KBOS');
    assert.deepStrictEqual(ticks(p), ['KAUS', 'KBOS', 'KDFW', 'KSAT']);
    p.close();
});

test('typed codes are uppercased, deduped and merged with the ticked ones into must_keep', async () => {
    const p = await pasted('KSAT KAUS');
    p.document.querySelector('#pl-keep input[value=KSAT]').checked = true;
    p.$('pl-keep-extra').value = 'kbos, kjfk KBOS ksat';
    p.$('pl-keep-extra').dispatchEvent(new p.window.Event('input'));
    const body = await planBody(p);
    assert.deepStrictEqual(body.must_keep, ['KSAT', 'KBOS', 'KJFK']);
    p.close();
});

test('restoring params puts kept codes without a tick box back into the box', async () => {
    const params = {
        chart: 'Houston', source: 'paste', codes: ['KSAT', 'KAUS'], must_keep: ['KAUS', 'KBOS', 'KJFK'], start_fresh: false,
        target: 'max', coverage: 0.5, width_in: 32, pitch: 80, min_gap: 18, max_move: 18, string_len: 50, tolerance: 0.1,
        brightness: 0.5, ma_white_5v: 20, ma_white_12v: 20,
    };
    const job = { id: 3, done: true, ok: true, params, result: result() };
    const p = await loadPlanner(baseRoutes([], { job }));
    assert.strictEqual(p.$('pl-keep-extra').value, 'KBOS KJFK');
    assert.deepStrictEqual(ticks(p), ['KAUS', 'KSAT']);
    assert.strictEqual(p.document.querySelector('#pl-keep input[value=KAUS]').checked, true);
    assert.strictEqual(p.document.querySelector('#pl-keep input[value=KSAT]').checked, false);
    p.close();
});
