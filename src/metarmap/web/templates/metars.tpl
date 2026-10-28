%include("header.tpl", title="METARs", page="metars")
<section class="page-head">
    <div>
        <h1>METARs</h1>
        <p>
            % if fetched:
            Fetched <span class="mono">{{fetched.strftime("%Y-%m-%d %H:%M:%S")}}</span> from aviationweather.gov
            % else:
            Not fetched yet
            % end
        </p>
    </div>
    <button class="btn" type="button" data-call="/fetch">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
        Fetch now
    </button>
</section>

<section class="toolbar">
    <div class="seg-group" role="group" aria-label="Filter by flight category">
        <button class="seg" type="button" data-filter="all" aria-pressed="true">All <span class="mono">{{len(stations)}}</span></button>
        % for c in cats:
        <button class="seg" type="button" data-filter="{{c}}" aria-pressed="false"><span class="dot {{c.lower()}}"></span>{{c}} <span class="mono">{{counts[c]}}</span></button>
        % end
        <button class="seg" type="button" data-filter="none" aria-pressed="false"><span class="dot"></span>No data <span class="mono">{{len(no_data)}}</span></button>
    </div>
    <label class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <span class="sr-only">Search airports</span>
        <input id="station-search" type="search" placeholder="Search ICAO, e.g. KHOU" autocomplete="off">
    </label>
</section>

<section class="card" style="overflow: hidden">
    <div class="scroll-x">
        <div class="trow metar head"><span>LED</span><span>Station</span><span>Cat</span><span>Raw METAR</span><span>Obs</span><span></span></div>
        % for s in stations:
        % cat = s['cat'] if s['cat'] in cats else 'none'
        <div class="trow metar" data-station="{{s['code']}}" data-cat="{{cat}}">
            <span class="mono muted">{{s['pixel'] + 1}}</span>
            <span class="station"><b>{{s['code']}}</b>{{!'<span class="badge-mock" title="A mock METAR from the Airports page (dev_mode)">mock</span>' if s['mock'] else ''}}
                % if s['name']:
                <span>{{s['name']}}</span>
                % end
            </span>
            % if s['has_data']:
            <span class="pill {{cat.lower()}}">{{s['cat'] or '—'}}</span>
            <span class="raw" title="{{s['raw']}}">{{s['raw']}}</span>
            <span class="mono muted" style="font-size: 13px">{{s['obsTime'].strftime("%H:%MZ") if s['obsTime'] else '—'}}</span>
            % else:
            <span class="pill">—</span>
            <span class="nodata">Not reporting METAR data</span>
            <span class="mono muted">—</span>
            % end
            <button class="chip sm" type="button" data-call="/locate/{{s['pixel']}}" data-then="none" aria-label="Locate {{s['code']}} on the map">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></svg>
                Locate
            </button>
        </div>
        % end
    </div>
</section>

%include("footer.tpl")
