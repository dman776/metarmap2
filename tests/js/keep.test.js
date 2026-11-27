// The Must keep ticks and the box for extra airport codes.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { loadPlanner, baseRoutes } = require('./helper');
const { result } = require('./fixtures');

const ticks = (p) => Array.from(p.document.querySelectorAll('#pl-keep input')).map((i) => i.value);

// the page has no current airports in this harness (the template loop is dropped); a pasted list gives tick boxes
async function pasted(codes, source) {
    const p = await loadPlanner(baseRoutes([['POST', /\/config\/planner\/plan$/, () => ({ status: 202, data: { id: 1 } })]]));
    p.$('pl-source').value = source || 'paste';
    p.$('pl-source').dispatchEvent(new p.window.Event('change'));
    p.$('pl-codes').value = codes;
    p.$('pl-codes').dispatchEvent(new p.window.Event('input'));
    return p;
}

async function planBody(p) {
    p.$('planner-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
    await new Promise((r) => setImmediate(r));
    const post = p.calls.slice().reverse().find((c) => c.method === 'POST' && /planner\/plan$/.test(c.url));
    return post && post.body;
}

test('the tick boxes are in alphabetical order', async () => {
    const p = await pasted('KSAT KAUS KDFW KBOS');
    assert.deepStrictEqual(ticks(p), ['KAUS', 'KBOS', 'KDFW', 'KSAT']);
    p.close();
});

test('with Recommended, typed codes are uppercased, deduped and sent as must_keep; the box is the only Must keep control here', async () => {
    const p = await pasted('', 'recommended');
    assert.strictEqual(p.$('pl-keep-extra-wrap').hidden, false);
    assert.strictEqual(p.$('pl-keep-set').hidden, false);
    assert.strictEqual(p.$('pl-keep').hidden, true);  // no current airports: no tick group
    assert.doesNotMatch(p.$('pl-keep-note').textContent, /ticked here/);
    p.$('pl-keep-extra').value = 'kbos, kjfk KBOS';
    p.$('pl-keep-extra').dispatchEvent(new p.window.Event('input'));
    assert.match(p.$('pl-strings-help').textContent, /The 2 airports you keep/);
    const body = await planBody(p);
    assert.deepStrictEqual(body.must_keep, ['KBOS', 'KJFK']);
    p.close();
});

test('with Paste, the box is hidden and typed codes are not sent; the pasted order is kept while the ticks are sorted', async () => {
    const p = await pasted('KSAT KAUS', 'recommended');
    p.$('pl-keep-extra').value = 'KBOS KJFK';
    p.$('pl-keep-extra').dispatchEvent(new p.window.Event('input'));
    p.$('pl-source').value = 'paste';
    p.$('pl-source').dispatchEvent(new p.window.Event('change'));
    p.$('pl-codes').value = 'KSAT KAUS';
    p.$('pl-codes').dispatchEvent(new p.window.Event('input'));
    assert.strictEqual(p.$('pl-keep-extra-wrap').hidden, true);
    assert.deepStrictEqual(ticks(p), ['KAUS', 'KSAT']);
    p.document.querySelector('#pl-keep input[value=KSAT]').checked = true;
    p.$('pl-keep').dispatchEvent(new p.window.Event('change'));
    assert.match(p.$('pl-strings-help').textContent, /The 1 airport you keep/);  // KBOS and KJFK are not counted
    const body = await planBody(p);
    assert.deepStrictEqual(body.must_keep, ['KSAT']);
    assert.deepStrictEqual(body.codes, ['KSAT', 'KAUS']);
    p.close();
});

test('switching to Current drops the typed codes too, and back to Recommended brings them back', async () => {
    const p = await pasted('', 'recommended');
    p.$('pl-keep-extra').value = 'KBOS';
    p.$('pl-keep-extra').dispatchEvent(new p.window.Event('input'));
    p.$('pl-source').value = 'current';
    p.$('pl-source').dispatchEvent(new p.window.Event('change'));
    assert.strictEqual(p.$('pl-keep-extra-wrap').hidden, true);
    assert.deepStrictEqual((await planBody(p)).must_keep, []);
    p.$('pl-source').value = 'recommended';
    p.$('pl-source').dispatchEvent(new p.window.Event('change'));
    assert.strictEqual(p.$('pl-keep-extra-wrap').hidden, false);
    assert.deepStrictEqual((await planBody(p)).must_keep, ['KBOS']);
    p.close();
});

const params = (over) => Object.assign({
    chart: 'Houston', source: 'recommended', codes: [], must_keep: ['KAUS', 'KBOS', 'KJFK'], start_fresh: false,
    target: 'max', coverage: 0.5, width_in: 32, pitch: 80, min_gap: 18, max_move: 18, string_len: 50, tolerance: 0.1,
    brightness: 0.5, ma_white_5v: 20, ma_white_12v: 20,
}, over);

test('restoring a Recommended plan puts the kept codes without a tick box back into the box', async () => {
    const job = { id: 3, done: true, ok: true, params: params(), result: result() };
    const p = await loadPlanner(baseRoutes([], { job }));
    assert.strictEqual(p.$('pl-keep-extra').value, 'KAUS KBOS KJFK');
    p.close();
});

test('restoring a Paste plan ticks the pasted ones and leaves the hidden box empty', async () => {
    const job = { id: 3, done: true, ok: true, params: params({ source: 'paste', codes: ['KSAT', 'KAUS'] }), result: result() };
    const p = await loadPlanner(baseRoutes([], { job }));
    assert.strictEqual(p.$('pl-keep-extra').value, '');
    assert.strictEqual(p.$('pl-keep-extra-wrap').hidden, true);
    assert.deepStrictEqual(ticks(p), ['KAUS', 'KSAT']);
    assert.strictEqual(p.document.querySelector('#pl-keep input[value=KAUS]').checked, true);
    assert.strictEqual(p.document.querySelector('#pl-keep input[value=KSAT]').checked, false);
    p.close();
});
