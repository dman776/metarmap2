'use strict';
// A finished plan as the planner makes it (see RESULT in src/metarmap/web/planner_saves.py), small but whole: two
// strings, a cut, a join, a hidden pixel and a moved one, for the print table.

function pixel(over) {
    return Object.assign({ code: 'KAAA', skipped: false, x: 10, y: 10, number: 1, index: 0, string: 1, position: 1, moved_mm: 0, orig_x: 10, orig_y: 10 }, over);
}

function result(over) {
    const pixels = [
        pixel({ code: 'KAAA', number: 1, index: 0, position: 1 }),
        pixel({ code: 'KBBB', number: 2, index: 1, position: 2, x: 30, y: 10, orig_x: 30, orig_y: 10 }),
        pixel({ code: 'KCCC', number: 3, index: 2, position: 3, x: 60, y: 10, orig_x: 60, orig_y: 10 }),
        pixel({ code: null, skipped: true, number: 4, index: 3, string: 2, position: 1, x: 90, y: 10, orig_x: null, orig_y: null }),
        pixel({ code: 'KDDD', number: 5, index: 4, string: 2, position: 2, x: 100, y: 40, orig_x: 100, orig_y: 30, moved_mm: 10 }),
    ];
    const airports = ['KAAA', 'KBBB', 'KCCC', null, 'KDDD'].map((code, i) => ({ code: code, name: code ? 'Airport ' + code : '', display: !!code, skip: !code }));
    return Object.assign(
        {
            message: 'Planned 4 airports',
            chart: { name: 'Houston', kind: 'sectional', outline: [[29, -96], [30, -95]], bounds: { south: 29, west: -96, north: 30, east: -95 }, margins: { left: 0.05, top: 0.05, right: 0.05, bottom: 0.05 } },
            sheet: {
                board: { width_mm: 300, height_mm: 200, width_in: 11.8, height_in: 7.9 },
                settings: { string_len: 50, pitch_mm: 30, min_gap_mm: 20, max_move_mm: 25, tolerance: 0.1, allow_skips: true },
                pixels: pixels,
                start: { index: 0, code: 'KAAA', corner: 'tl' },
                route: [{ kind: 'wire', status: 'ok', from_index: 0, to_index: 1, length_mm: 20 }, { kind: 'join', status: 'ok', from_index: 3, to_index: 4, length_mm: 33 }],
                cuts: [{ between: [2, 3], string: 1, codes: ['KCCC', null], length_mm: 41.5, extension_mm: 12, how: 'splice' }],
                joins: [{ between: [3, 4], length_mm: 33 }],
                strings: [{ number: 1, first: 0, last: 2, pixels: 3 }, { number: 2, first: 3, last: 4, pixels: 2 }],
                shopping: { strings: 2, pixels: 5, airports: 4, skipped: 1, extensions: 1 },
                problems: { ok: false, crowded: [], drops: [], clipped: [] },
                power: { voltage: 5, reason: 'x', ma_per_pixel: 20, brightness: 0.5, margin: 1.2, estimated_amps: 1, supply_amps: 2, supply_watts: 10, feed_points: [0], notes: [] },
            },
            airports: airports,
            names: { KAAA: 'Airport KAAA' },
            left_out: [],
            notes: [],
        },
        over || {}
    );
}

module.exports = { result, pixel };
