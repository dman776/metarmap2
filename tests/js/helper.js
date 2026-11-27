// Loads the real planner page (templates/planner.tpl) and the real planner.js into jsdom, with a fetch the test owns.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const WEB = path.join(__dirname, '..', '..', 'src', 'metarmap', 'web');

// The template is bottle syntax. Only its shape matters here: lines that start with % (include, for, if, end) are
// dropped, and each {{ expression }} becomes empty text, so the page has every element planner.js looks up.
function pageHtml() {
    const tpl = fs.readFileSync(path.join(WEB, 'templates', 'planner.tpl'), 'utf8');
    const body = tpl
        .split('\n')
        .filter((line) => !/^\s*%/.test(line) && !line.includes("data-code=\"{{a['code']}}\""))  // no current airports
        .join('\n')
        .replace(/\{\{!?[^}]*\}\}/g, '');
    return '<!DOCTYPE html><html><head><title>Plan a new chart</title></head><body>' + body + '</body></html>';
}

const SCRIPT = fs.readFileSync(path.join(WEB, 'static', 'planner.js'), 'utf8');

// a fake fetch: routes is a list of [method, url-regex, handler]; a handler returns {status, data} (or a promise of it)
function makeFetch(routes, calls) {
    return function (url, opts) {
        const method = (opts && opts.method) || 'GET';
        const body = opts && opts.body ? JSON.parse(opts.body) : null;
        calls.push({ method, url, body });
        for (const [m, re, handler] of routes) {
            if (m === method && re.test(url)) {
                return Promise.resolve(handler({ url, body })).then((r) => ({
                    status: r.status === undefined ? 200 : r.status,
                    json: () => (r.data === undefined ? Promise.reject(new Error('not json')) : Promise.resolve(r.data)),
                }));
            }
        }
        return Promise.resolve({ status: 404, json: () => Promise.resolve({ error: 'no route ' + method + ' ' + url }) });
    };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

// Loads the page. routes: see makeFetch (planner.js asks for the progress, the undo and the saves at start).
async function loadPlanner(routes) {
    const calls = [];
    const dom = new JSDOM(pageHtml(), { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://chart.test/config/planner' });
    const w = dom.window;
    w.fetch = makeFetch(routes || [], calls);
    w.Element.prototype.scrollIntoView = function () {};
    w.print = function () { calls.push({ method: 'PRINT' }); };
    w.eval(SCRIPT);
    await settle();
    return { window: w, document: w.document, calls, $: (id) => w.document.getElementById(id), close: () => w.close() };
}

// let every promise chain that is already runnable finish
async function settle() {
    for (let i = 0; i < 8; i++) await tick();
}

module.exports = { loadPlanner, settle, tick, pageHtml };

// the routes every page load asks for, so a test names only the ones it cares about
function baseRoutes(extra, opts) {
    const o = opts || {};
    return (extra || []).concat([
        ['GET', /\/config\/planner\/progress$/, () => ({ data: o.job || { idle: true } })],
        ['GET', /\/config\/planner\/saves$/, () => ({ data: { saves: o.saves || [], limit: 50, max_name: 60 } })],
        ['GET', /\/config\/planner\/apply\/status$/, () => ({ data: {} })],
    ]);
}

module.exports.baseRoutes = baseRoutes;
