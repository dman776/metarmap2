// B122: the Saved plans card and the Save this plan card, against a fake Chart (a stubbed fetch).
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { loadPlanner, baseRoutes, settle } = require('./helper');
const { result } = require('./fixtures');

const SAVED_AT = '2026-11-25T10:00:00+00:00';
const item = (id, name) => ({ id, name, saved_at: SAVED_AT, summary: { chart: 'Houston', airports: 4, strings: 2 } });

// a Chart that keeps saved plans in memory; `gate` makes a route wait until the test lets it go
function chart(initial, opts) {
    const o = opts || {};
    const state = { saves: initial.slice(), job: o.job || null, gates: {} };
    const wait = (key) => (state.gates[key] ? state.gates[key].promise : Promise.resolve());
    state.hold = (key) => {
        let release;
        const promise = new Promise((r) => { release = r; });
        state.gates[key] = { promise, release: () => { delete state.gates[key]; release(); } };
        return state.gates[key];
    };
    const find = (url) => state.saves.find((s) => url.includes('/' + s.id + '/'));
    state.routes = [
        ['GET', /\/config\/planner\/saves$/, async () => { await wait('list'); return { data: { saves: state.saves.slice(), limit: 50, max_name: 60 } }; }],
        ['POST', /\/config\/planner\/saves$/, ({ body }) => {
            if (o.saveError) return o.saveError;
            const saved = item('new' + (state.saves.length + 1), body.name);
            state.saves.unshift(saved);
            return { status: 201, data: { ok: true, save: saved } };
        }],
        ['POST', /\/load$/, async ({ url }) => {
            await wait('load');
            const s = find(url);
            if (!s) return { status: 404, data: { error: 'That saved plan is gone', reason: 'missing' } };
            const loaded = { id: s.id, name: s.name, saved_at: s.saved_at };
            return { data: { ok: true, job: { id: 20 + state.saves.indexOf(s), done: true, ok: true, params: { chart: 'Houston' }, result: result(), loaded } } };
        }],
        ['POST', /\/rename$/, async ({ url, body }) => {
            await wait('rename');
            const s = find(url);
            if (!s) return { status: 404, data: { error: 'That saved plan is gone', reason: 'missing' } };
            if (state.saves.some((x) => x !== s && x.name.toLowerCase() === body.name.toLowerCase())) {
                return { status: 409, data: { error: 'A saved plan called ' + body.name + ' exists already', reason: 'exists' } };
            }
            s.name = body.name;
            return { data: { ok: true, save: s } };
        }],
        ['POST', /\/delete$/, async ({ url }) => {
            const s = find(url);
            if (!s) return { status: 404, data: { error: 'That saved plan is gone', reason: 'missing' } };
            state.saves.splice(state.saves.indexOf(s), 1);
            return { data: { ok: true } };
        }],
    ];
    return state;
}

async function open(initial, opts) {
    const c = chart(initial, opts);
    const job = (opts && opts.job) || null;
    const p = await loadPlanner(baseRoutes(c.routes, { job: job }));
    return { c, p };
}

const planJob = () => ({ id: 7, done: true, ok: true, params: { chart: 'Houston' }, result: result() });
const names = (p) => Array.from(p.document.querySelectorAll('#pl-saves-list .pl-save-name')).map((n) => n.textContent);
const button = (p, what, name) => p.document.querySelector('#pl-saves-list button[aria-label="' + what + ' ' + name + '"]');
const text = (p, id) => p.$(id).textContent;

test('the list shows each saved plan, newest first as the Chart sent them, and hides the empty note', async () => {
    const { p } = await open([item('a', 'Houston 2026-11-25'), item('b', 'Dallas')]);
    assert.deepStrictEqual(names(p), ['Houston 2026-11-25', 'Dallas']);
    assert.strictEqual(p.$('pl-saves-empty').hidden, true);
    assert.match(p.document.querySelector('#pl-saves-list .pl-save-meta').textContent, /Houston, 4 airports, 2 strings, saved /);
    p.close();
});

test('no saved plans shows the empty note', async () => {
    const { p } = await open([]);
    assert.strictEqual(p.$('pl-saves-empty').hidden, false);
    assert.deepStrictEqual(names(p), []);
    p.close();
});

test('Save sends the name and the id of the plan on the page, says so, and lists the new plan', async () => {
    const { c, p } = await open([], { job: planJob() });
    assert.match(p.$('pl-save-name').value, /^Houston \d{4}-\d{2}-\d{2}$/);
    p.$('pl-save-name').value = '  Trip plan ';
    p.$('pl-save-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
    await settle();
    const post = p.calls.find((x) => x.method === 'POST');
    assert.deepStrictEqual(post.body, { name: 'Trip plan', job: 7 });
    assert.strictEqual(text(p, 'pl-save-status'), 'Saved as Trip plan.');
    assert.deepStrictEqual(names(p), ['Trip plan']);
    assert.strictEqual(c.saves.length, 1);
    p.close();
});

test('Save with no name, a name already in the list (any case) or no plan on the page asks nothing of the Chart', async () => {
    const { p } = await open([item('a', 'Dallas')], { job: planJob() });
    const submit = async (name) => {
        p.$('pl-save-name').value = name;
        p.$('pl-save-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
        await settle();
    };
    await submit('   ');
    assert.strictEqual(text(p, 'pl-save-status'), 'Type a name for the plan.');
    await submit('DALLAS');
    assert.match(text(p, 'pl-save-status'), /already exists: pick another name/);
    assert.ok(p.$('pl-save-status').className.includes('bad'));
    assert.ok(!p.calls.some((x) => x.method === 'POST'));
    p.close();

    const empty = await open([]);
    empty.p.$('pl-save-name').value = 'Anything';
    empty.p.$('pl-save-form').dispatchEvent(new empty.p.window.Event('submit', { cancelable: true }));
    await settle();
    assert.match(text(empty.p, 'pl-save-status'), /no finished plan on the page/);
    assert.ok(!empty.p.calls.some((x) => x.method === 'POST'));
    empty.p.close();
});

test('a Save the Chart refuses says why and saves nothing', async () => {
    const { p } = await open([], { job: planJob(), saveError: { status: 409, data: { error: 'A plan is still running', reason: 'running' } } });
    p.$('pl-save-name').value = 'Trip';
    p.$('pl-save-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
    await settle();
    assert.strictEqual(text(p, 'pl-save-status'), 'A plan is still running');
    assert.ok(p.$('pl-save-status').className.includes('bad'));
    assert.deepStrictEqual(names(p), []);
    p.close();
});

test('Load shows the plan, fills the form, says where it came from and what happened', async () => {
    const { p } = await open([item('a', 'Houston 2026-11-25')]);
    assert.strictEqual(p.$('pl-result').hidden, true);
    button(p, 'Load', 'Houston 2026-11-25').click();
    await settle();
    const post = p.calls.find((x) => x.url.endsWith('/a/load'));
    assert.deepStrictEqual(post.body, {});
    assert.strictEqual(p.$('pl-result').hidden, false);
    assert.strictEqual(p.$('pl-loaded').hidden, false);
    assert.match(text(p, 'pl-loaded'), /^Loaded from saved plan Houston 2026-11-25, saved .+\.$/);
    assert.strictEqual(text(p, 'pl-saves-status'), 'Loaded Houston 2026-11-25.');
    assert.strictEqual(p.$('pl-print-btn').disabled, false, 'a loaded plan can be printed');
    p.close();
});

test('a Load the Chart refuses leaves the page as it was and says why', async () => {
    const { c, p } = await open([item('a', 'Gone soon')]);
    c.saves.length = 0; // deleted from another tab
    button(p, 'Load', 'Gone soon').click();
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'That saved plan is gone');
    assert.strictEqual(p.$('pl-result').hidden, true);
    assert.strictEqual(p.$('pl-loaded').hidden, true);
    p.close();
});

test('the buttons are off while a request is on its way', async () => {
    const { c, p } = await open([item('a', 'One')]);
    const gate = c.hold('load');
    button(p, 'Load', 'One').click();
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Loading One...');
    assert.strictEqual(button(p, 'Rename', 'One').disabled, true);
    assert.strictEqual(p.$('pl-save-btn').disabled, true);
    gate.release();
    await settle();
    assert.strictEqual(button(p, 'Rename', 'One').disabled, false);
    p.close();
});

test('Rename opens a field with the name, sends the new one, lists it and moves focus to the row', async () => {
    const { p } = await open([item('a', 'Old'), item('b', 'Other')]);
    button(p, 'Rename', 'Old').click();
    const input = p.document.querySelector('.pl-save-edit input');
    assert.strictEqual(input.value, 'Old');
    input.value = 'New name';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    const post = p.calls.find((x) => x.url.endsWith('/a/rename'));
    assert.deepStrictEqual(post.body, { name: 'New name' });
    assert.deepStrictEqual(names(p), ['New name', 'Other']);
    assert.strictEqual(text(p, 'pl-saves-status'), 'Renamed to New name.');
    assert.strictEqual(p.document.querySelector('.pl-save-edit'), null);
    assert.strictEqual(p.document.activeElement, button(p, 'Rename', 'New name'));
    p.close();
});

test('Rename by Enter in the field, and Escape closes it without a request', async () => {
    const { p } = await open([item('a', 'Old')]);
    button(p, 'Rename', 'Old').click();
    let input = p.document.querySelector('.pl-save-edit input');
    input.dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.strictEqual(p.document.querySelector('.pl-save-edit'), null);
    assert.ok(!p.calls.some((x) => x.url.endsWith('/rename')));
    button(p, 'Rename', 'Old').click();
    input = p.document.querySelector('.pl-save-edit input');
    input.value = 'Via Enter';
    input.dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await settle();
    assert.deepStrictEqual(names(p), ['Via Enter']);
    p.close();
});

test('a Rename the Chart refuses keeps the field open and says why', async () => {
    const { p } = await open([item('a', 'One'), item('b', 'Two')]);
    button(p, 'Rename', 'One').click();
    p.document.querySelector('.pl-save-edit input').value = 'two';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    assert.match(text(p, 'pl-saves-status'), /exists already/);
    assert.deepStrictEqual(names(p), ['One', 'Two']);
    p.close();
});

test('renaming the plan that is loaded renames the banner too; renaming another leaves it', async () => {
    const { p } = await open([item('a', 'First'), item('b', 'Second')]);
    button(p, 'Load', 'First').click();
    await settle();
    button(p, 'Rename', 'Second').click();
    p.document.querySelector('.pl-save-edit input').value = 'Second 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    assert.match(text(p, 'pl-loaded'), /^Loaded from saved plan First, /);
    button(p, 'Rename', 'First').click();
    p.document.querySelector('.pl-save-edit input').value = 'First 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    assert.match(text(p, 'pl-loaded'), /^Loaded from saved plan First 2, saved /);
    p.close();
});

test('Delete asks first; Keep it closes the question without a request', async () => {
    const { p } = await open([item('a', 'Doomed')]);
    button(p, 'Delete', 'Doomed').click();
    assert.match(p.document.querySelector('.pl-save-edit').textContent, /Delete Doomed\? The saved plan is removed from this Chart\. This cannot be undone\./);
    assert.ok(!p.calls.some((x) => x.url.endsWith('/delete')));
    Array.from(p.document.querySelectorAll('.pl-save-edit button')).find((b) => b.textContent === 'Keep it').click();
    assert.strictEqual(p.document.querySelector('.pl-save-edit'), null);
    assert.ok(!p.calls.some((x) => x.url.endsWith('/delete')));
    assert.deepStrictEqual(names(p), ['Doomed']);
    p.close();
});

test('Delete removes the plan, says so and moves focus to the next row', async () => {
    const { c, p } = await open([item('a', 'One'), item('b', 'Two')]);
    button(p, 'Delete', 'One').click();
    p.document.querySelector('.pl-save-edit button.danger').click();
    await settle();
    assert.deepStrictEqual(names(p), ['Two']);
    assert.strictEqual(c.saves.length, 1);
    assert.strictEqual(text(p, 'pl-saves-status'), 'Deleted One.');
    assert.strictEqual(p.document.activeElement, button(p, 'Load', 'Two'));
    p.close();
});

test('deleting the last plan shows the empty note and focuses the card title', async () => {
    const { p } = await open([item('a', 'Only')]);
    button(p, 'Delete', 'Only').click();
    p.document.querySelector('.pl-save-edit button.danger').click();
    await settle();
    assert.strictEqual(p.$('pl-saves-empty').hidden, false);
    assert.strictEqual(p.document.activeElement, p.$('pl-saves-title'));
    p.close();
});

test('a Delete of a plan that is already gone (404) just refreshes the list', async () => {
    const { c, p } = await open([item('a', 'Ghost')]);
    c.saves.length = 0;
    button(p, 'Delete', 'Ghost').click();
    p.document.querySelector('.pl-save-edit button.danger').click();
    await settle();
    assert.deepStrictEqual(names(p), []);
    assert.strictEqual(text(p, 'pl-saves-status'), 'Deleted Ghost.');
    p.close();
});

// B122b: a Rename or a Delete re-reads the list after it answers, and the buttons are on again while it does. A Load
// begun in that gap must keep the status line and the banner it wrote: the late "Renamed to" or "Deleted" is stale.
test('a rename that finishes after a load that began meanwhile does not write over the load\'s status or banner', async () => {
    const { c, p } = await open([item('a', 'Alpha'), item('b', 'Beta')]);
    button(p, 'Load', 'Alpha').click();
    await settle();
    assert.match(text(p, 'pl-loaded'), /Alpha/);

    const refresh = c.hold('list');
    button(p, 'Rename', 'Alpha').click();
    p.document.querySelector('.pl-save-edit input').value = 'Alpha 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();  // the rename was answered; the list is being read again (held)
    assert.match(text(p, 'pl-loaded'), /Alpha 2/);
    button(p, 'Load', 'Beta').click();  // the buttons are on again: the user loads the other plan
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Loaded Beta.');
    assert.match(text(p, 'pl-loaded'), /Loaded from saved plan Beta, /);

    refresh.release();  // the list comes back
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Loaded Beta.', 'the late "Renamed to" must not replace it');
    assert.match(text(p, 'pl-loaded'), /Loaded from saved plan Beta, /);
    assert.deepStrictEqual(names(p), ['Alpha 2', 'Beta'], 'the list itself is still brought up to date');
    p.close();
});

test('a delete that finishes after a load that began meanwhile does not write over the load\'s status', async () => {
    const { c, p } = await open([item('a', 'Alpha'), item('b', 'Beta'), item('c', 'Gamma')]);
    const refresh = c.hold('list');
    button(p, 'Delete', 'Alpha').click();
    p.document.querySelector('.pl-save-edit button.danger').click();
    await settle();
    button(p, 'Load', 'Gamma').click();
    await settle();
    refresh.release();
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Loaded Gamma.');
    assert.deepStrictEqual(names(p), ['Beta', 'Gamma']);
    p.close();
});

test('a Save during a rename\'s re-read does not leave the rename stuck on "Renaming..."', async () => {
    const { c, p } = await open([item('a', 'Alpha')], { job: planJob() });
    const refresh = c.hold('list');
    button(p, 'Rename', 'Alpha').click();
    p.document.querySelector('.pl-save-edit input').value = 'Alpha 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    p.$('pl-save-name').value = 'Fresh';
    p.$('pl-save-form').dispatchEvent(new p.window.Event('submit', { cancelable: true }));
    await settle();
    assert.strictEqual(text(p, 'pl-save-status'), 'Saved as Fresh.');
    refresh.release();
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Renamed to Alpha 2.');
    p.close();
});

test('focus is not lost when a late refresh rebuilds the list under a Load', async () => {
    const { c, p } = await open([item('a', 'Alpha'), item('b', 'Beta')]);
    const refresh = c.hold('list');
    button(p, 'Rename', 'Alpha').click();
    p.document.querySelector('.pl-save-edit input').value = 'Alpha 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    button(p, 'Load', 'Beta').click();
    await settle();
    refresh.release();
    await settle();
    assert.strictEqual(p.document.activeElement, button(p, 'Load', 'Beta'));
    p.close();
});

test('a rename left alone still says Renamed (the guard only stops a stale one)', async () => {
    const { p } = await open([item('a', 'Alpha')]);
    button(p, 'Rename', 'Alpha').click();
    p.document.querySelector('.pl-save-edit input').value = 'Alpha 2';
    p.document.querySelector('.pl-save-edit button.primary').click();
    await settle();
    assert.strictEqual(text(p, 'pl-saves-status'), 'Renamed to Alpha 2.');
    p.close();
});
