%include("header.tpl", title="Airports", page="config")
<section class="page-head">
    <div>
        <h1>Configuration</h1>
        <p>Changes save as you make them.</p>
    </div>
</section>

<section class="banner" id="restart-banner" role="status"{{!'' if count != strip_leds else ' hidden'}}>
    <span>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f5b544" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
        The strip is running {{strip_leds}} LEDs; the new number takes effect after the map restarts.
    </span>
    <button class="btn primary" type="button" data-call="/restart" data-then="restart">Restart now</button>
</section>

%include("config_tabs.tpl", active="airports")

<p class="tab-intro">{{count}} {{'LED' if count == 1 else 'LEDs'}} in the order they're wired{{!' and %d virtual %s' % (virtual, 'airport' if virtual == 1 else 'airports') if virtual else ''}}: {{with_airport}} with an airport{{', %d without' % without_airport if without_airport else ''}}. Changes save right away.</p>

<section class="card settings">
    <div class="set" style="border-top: 0">
        <div>
            <label class="t" for="led-count">Number of LEDs</label>
            <div class="d">New LEDs are added at the end with no airport. Lowering it removes the airports on the last LEDs.</div>
        </div>
        <input id="led-count" class="led-count" type="number" inputmode="numeric" min="1" max="{{max_leds - virtual}}" value="{{count}}" data-led-count="{{count}}" data-first="0" data-count-key="led.count">
    </div>
    <div class="set">
        <div>
            <label class="t" for="virtual-count">Virtual airports</label>
            <div class="d">Airports after the LEDs, with no LED of their own: shown on the Map page (in a dashed circle), in Home Assistant, and on the OLED if switched on (the code in a dashed box). Lowering it removes the last ones. {{max_leds}} airports at most, LEDs and virtual together.</div>
        </div>
        <input id="virtual-count" class="led-count" type="number" inputmode="numeric" min="0" max="{{max_leds - count}}" value="{{virtual}}" data-led-count="{{virtual}}" data-first="{{count}}" data-count-key="led.virtual_count">
    </div>
</section>

<section class="card">
    <div class="ap-row trow head" style="border-top: 0"><span>LED</span><span>ICAO</span><span class="ap-name">Name</span><span>OLED</span><span class="ap-move">Move</span></div>
    % for led in leds:
    % n = led['pixel'] + 1
    % if led['virtual'] and led['pixel'] == count:
    <div class="ap-divider">Virtual airports · web map and Home Assistant only</div>
    % end
    <div class="ap-row{{' virtual' if led['virtual'] else ''}}" data-row="{{led['pixel']}}" data-code="{{led['code']}}">
        <span class="mono muted">{{n}}{{!'<span class="tag">virtual</span>' if led['virtual'] else ''}}{{!'<span class="tag mock-tag">mock</span>' if dev_mode and led['mock'] else ''}}</span>
        <input class="code" type="text" value="{{led['code']}}" maxlength="4" spellcheck="false" placeholder="—" aria-label="Airport for LED {{n}}" data-led="{{led['pixel']}}" data-field="code">
        <input class="ap-name" type="text" value="{{led['name']}}" maxlength="40" placeholder="Name" aria-label="Name for LED {{n}}" data-led="{{led['pixel']}}" data-field="name">
        <input class="switch" type="checkbox" aria-label="Show LED {{n}} on the OLED display" data-led="{{led['pixel']}}" data-field="display"{{!' checked' if led['display'] else ''}}{{!'' if led['code'] else ' disabled'}}>
        <span class="ap-move">
            <button class="btn icon sm" type="button" aria-label="Move LED {{n}} up" data-call="/config/airports/move/{{led['pixel']}}/{{led['pixel'] - 1}}"{{!' disabled' if led['pixel'] == 0 else ''}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m6 15 6-6 6 6"/></svg>
            </button>
            <button class="btn icon sm" type="button" aria-label="Move LED {{n}} down" data-call="/config/airports/move/{{led['pixel']}}/{{led['pixel'] + 1}}"{{!' disabled' if led['pixel'] == len(leds) - 1 else ''}}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
            </button>
        </span>
        % if dev_mode:
        <input class="ap-mock mono" type="text" value="{{led['mock']}}" spellcheck="false" autocapitalize="characters" placeholder="Mock METAR (dev_mode): replaces the real report, e.g. METAR {{led['code'] or 'KDWH'}} 272353Z 08003KT 9SM CLR 21/18 A3014" aria-label="Mock METAR for LED {{n}}" data-mock="{{led['pixel']}}"{{!'' if led['code'] else ' disabled'}}>
        % end
    </div>
    % end
</section>

%include("footer.tpl")
