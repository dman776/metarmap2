// B128: the printed plan (Download PDF): the table of pixels in wired order, and the tab put back afterwards.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { loadPlanner, baseRoutes } = require('./helper');
const { result } = require('./fixtures');

// the page with this plan already on it (a reloaded page shows the last finished plan), then Download PDF is pressed
async function printed(plan) {
    const job = { id: 7, done: true, ok: true, params: { chart: 'Houston' }, result: plan };
    const p = await loadPlanner(baseRoutes([], { job }));
    p.$('pl-print-btn').click();
    const rows = Array.from(p.document.querySelectorAll('#pl-print table.pr-table tbody tr')).map((tr) =>
        Array.from(tr.children).map((td) => td.textContent)
    );
    return { p, rows, trs: p.document.querySelectorAll('#pl-print table.pr-table tbody tr') };
}

// column numbers of the table: Done, Pixel, Airport, Name, String, Pixel in string, Status, Wire, X, Y
const [PIXEL, AIRPORT, NAME, STRING, POS, STATUS, WIRE, X, Y] = [1, 2, 3, 4, 5, 6, 7, 8, 9];

test('the table lists the pixels in wired order with their airport, string and place', async () => {
    const { p, rows } = await printed(result());
    assert.deepStrictEqual(rows.map((r) => r[PIXEL]), ['1', '2', '3', '4', '5']);
    assert.deepStrictEqual(rows.map((r) => r[AIRPORT]), ['KAAA', 'KBBB', 'KCCC', 'skipped', 'KDDD']);
    assert.strictEqual(rows[0][NAME], 'Airport KAAA');
    assert.strictEqual(rows[1][STRING], '1');
    assert.strictEqual(rows[1][POS], '2 of 50');
    assert.strictEqual(rows[0][X], '10 mm / 0.4 in');
    assert.strictEqual(rows[4][Y], '40 mm / 1.6 in');
    p.close();
});

test('the table has one header row of ten columns and a tick box in every row', async () => {
    const { p, trs } = await printed(result());
    const heads = Array.from(p.document.querySelectorAll('#pl-print thead th')).map((th) => th.textContent);
    assert.deepStrictEqual(heads, ['Done', 'Pixel', 'Airport', 'Name', 'String', 'Pixel in string', 'Status', 'Wire', 'X from left', 'Y from top']);
    assert.strictEqual(trs.length, 5);
    for (const tr of trs) assert.ok(tr.querySelector('td.pr-box'));
    p.close();
});

test('the wire column says where each string starts, and where a cut or a join falls, with lengths', async () => {
    const { p, rows } = await printed(result());
    assert.strictEqual(rows[0][WIRE], 'String 1 starts here');
    assert.strictEqual(rows[1][WIRE], '');
    // cut after pixel 3 (index 2): splice 12 mm in before pixel 4, over a gap of 41.5 mm
    assert.strictEqual(rows[2][WIRE], 'CUT after this pixel: splice in 12 mm / 0.5 in before pixel 4 (gap 42 mm / 1.6 in)');
    // pixel 4 starts string 2 and a join runs from it to pixel 5
    assert.strictEqual(rows[3][WIRE], 'String 2 starts here; JOIN after this pixel: cable 33 mm / 1.3 in to pixel 5');
    p.close();
});

test('status is On target, Moved by how much and which way, or Skipped', async () => {
    const { p, rows, trs } = await printed(result());
    assert.strictEqual(rows[0][STATUS], 'On target');
    assert.strictEqual(rows[3][STATUS], 'Skipped: hidden pixel');
    assert.strictEqual(rows[4][STATUS], 'Moved 10 mm / 0.4 in S');
    assert.ok(trs[3].classList.contains('pr-skip'));
    assert.ok(trs[4].classList.contains('pr-moved'));
    assert.ok(!trs[0].classList.contains('pr-moved'));
    p.close();
});

test('the compass says the way the pixel sits from its true place', async () => {
    const at = (dx, dy) => ({ x: 100 + dx, y: 100 + dy, orig_x: 100, orig_y: 100, moved_mm: 10 });
    const cases = [[0, -10, 'N'], [8, -8, 'NE'], [10, 0, 'E'], [8, 8, 'SE'], [0, 10, 'S'], [-8, 8, 'SW'], [-10, 0, 'W'], [-8, -8, 'NW']];
    for (const [dx, dy, want] of cases) {
        const plan = result();
        plan.sheet.pixels[1] = Object.assign({}, plan.sheet.pixels[1], at(dx, dy));
        const { p, rows } = await printed(plan);
        assert.strictEqual(rows[1][STATUS], 'Moved 10 mm / 0.4 in ' + want, 'dx ' + dx + ' dy ' + dy);
        p.close();
    }
});

test('a pixel moved no more than 1 mm is On target', async () => {
    const plan = result();
    plan.sheet.pixels[1].moved_mm = 1;
    plan.sheet.pixels[1].orig_x = 29;
    const { p, rows } = await printed(plan);
    assert.strictEqual(rows[1][STATUS], 'On target');
    p.close();
});

test('a saved plan that lacks fields prints dashes, not NaN or a crash', async () => {
    const plan = result();
    plan.sheet.pixels = plan.sheet.pixels.map((px) => {
        const old = Object.assign({}, px);
        for (const k of ['position', 'string', 'x', 'y', 'moved_mm', 'orig_x', 'orig_y']) delete old[k];
        return old;
    });
    plan.sheet.cuts = [{ between: [2, 3], string: 1, codes: [], how: 'splice' }];
    plan.sheet.joins = [{ between: [3, 4] }];
    const { p, rows } = await printed(plan);
    assert.strictEqual(rows.length, 5);
    for (const r of rows) {
        assert.strictEqual(r[STRING], '-');
        assert.strictEqual(r[POS], '-');
        assert.strictEqual(r[X], '-');
        assert.strictEqual(r[Y], '-');
        assert.strictEqual(r[STATUS] === 'On target' || r[STATUS] === 'Skipped: hidden pixel', true);
        assert.ok(!/NaN|undefined/.test(r.join('|')));
    }
    assert.strictEqual(rows[0][WIRE], '', 'no String N starts here without a position');
    assert.strictEqual(rows[2][WIRE], 'CUT after this pixel: splice in - before pixel 4 (gap -)');
    assert.strictEqual(rows[3][WIRE], 'JOIN after this pixel: cable - to pixel 5');
    p.close();
});

test('an airport with no name falls back to the name the plan lists for its code, or nothing', async () => {
    const plan = result();
    plan.airports.forEach((a) => { a.name = ''; });
    const { p, rows } = await printed(plan);
    assert.strictEqual(rows[0][NAME], 'Airport KAAA'); // from the result's names
    assert.strictEqual(rows[1][NAME], '');
    assert.strictEqual(rows[3][NAME], 'Wired, shows nothing: bridges a gap');
    p.close();
});

test('the print copy is named for the chart and the date, and the page enters print mode', async () => {
    const { p } = await printed(result());
    const doc = p.document;
    assert.match(doc.title, /^MetarMap plan - Houston - \d{4}-\d{2}-\d{2}$/);
    assert.strictEqual(doc.querySelector('#pl-print h1').textContent, 'MetarMap plan - Houston');
    assert.ok(doc.body.classList.contains('pl-printing'));
    assert.ok(doc.documentElement.classList.contains('pl-printing'));
    assert.match(doc.getElementById('pl-print-page').textContent, /@page \{ size: landscape; margin: 12mm; \}/);
    assert.ok(p.calls.some((c) => c.method === 'PRINT'));
    p.close();
});

test('a tall board prints portrait', async () => {
    const plan = result();
    plan.sheet.board = { width_mm: 200, height_mm: 300, width_in: 7.9, height_in: 11.8 };
    const { p } = await printed(plan);
    assert.match(p.document.getElementById('pl-print-page').textContent, /size: portrait/);
    p.close();
});

test('afterprint puts the title and the classes back', async () => {
    const { p } = await printed(result());
    const doc = p.document;
    assert.notStrictEqual(doc.title, 'Plan a new chart');
    p.window.dispatchEvent(new p.window.Event('afterprint'));
    assert.strictEqual(doc.title, 'Plan a new chart');
    assert.ok(!doc.body.classList.contains('pl-printing'));
    assert.ok(!doc.documentElement.classList.contains('pl-printing'));
    assert.strictEqual(doc.getElementById('pl-print-page').textContent, '');
    assert.ok(doc.getElementById('pl-print'), 'the print copy stays, hidden by the stylesheet');
    p.close();
});

test('printing twice keeps the first title and leaves one print copy', async () => {
    const { p } = await printed(result());
    p.$('pl-print-btn').click();
    assert.strictEqual(p.document.querySelectorAll('#pl-print').length, 1);
    p.window.dispatchEvent(new p.window.Event('afterprint'));
    assert.strictEqual(p.document.title, 'Plan a new chart');
    p.close();
});

test('the Download PDF button is off until a plan is on the page', async () => {
    const p = await loadPlanner(baseRoutes());
    assert.strictEqual(p.$('pl-print-btn').disabled, true);
    p.$('pl-print-btn').click();
    assert.strictEqual(p.document.getElementById('pl-print'), null);
    assert.ok(!p.calls.some((c) => c.method === 'PRINT'));
    p.close();
});

// the printed plan's second map is the back view: the same pixels with x flipped across the board's width
test('the printed plan has a Back view page that mirrors every pixel left to right', async () => {
    const plan = result();
    const { p } = await printed(plan);
    const W = plan.sheet.board.width_mm;
    const maps = p.document.querySelectorAll('#pl-print svg.pr-map');
    assert.strictEqual(maps.length, 2);
    assert.ok(p.document.querySelector('#pl-print .pr-back'));
    const xs = (svgEl) => Array.from(svgEl.querySelectorAll('circle.pm-dot')).map((c) => parseFloat(c.getAttribute('cx')));
    const front = xs(maps[0]), back = xs(maps[1]);
    assert.strictEqual(back.length, front.length);
    front.forEach((x, i) => assert.ok(Math.abs(back[i] - (W - x)) < 1e-6));
    assert.ok(/Back view/.test(maps[1].getAttribute('aria-label')));
    p.close();
});

test('the Back button redraws the board mirrored and shows its note', async () => {
    const plan = result();
    const job = { id: 7, done: true, ok: true, params: { chart: 'Houston' }, result: plan };
    const p = await loadPlanner(baseRoutes([], { job }));
    const W = plan.sheet.board.width_mm;
    p.document.querySelector('#pl-view button[data-view="board"]').click();
    const front = Array.from(p.document.querySelectorAll('#pl-board-svg circle.pm-dot')).map((c) => parseFloat(c.getAttribute('cx')));
    assert.ok(p.$('pl-back-note').hidden);
    p.document.querySelector('#pl-view button[data-view="back"]').click();
    const back = Array.from(p.document.querySelectorAll('#pl-board-svg circle.pm-dot')).map((c) => parseFloat(c.getAttribute('cx')));
    assert.ok(!p.$('pl-back-note').hidden);
    assert.ok(!p.$('pl-board').hidden);
    front.forEach((x, i) => assert.ok(Math.abs(back[i] - (W - x)) < 1e-6));
    p.close();
});
