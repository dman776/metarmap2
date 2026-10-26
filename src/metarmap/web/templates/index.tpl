%include("header.tpl", title="Home", page="home")
<section class="page-head">
    <div>
        <h1>Map status</h1>
        <p>{{len(stations)}} airports · METARs update every 10 minutes</p>
        <p class="fetched" data-fetched="{{int(fetched.timestamp()) if fetched else ''}}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
            % if fetched:
            Last METAR fetch <span class="mono">{{fetched.strftime("%Y-%m-%d %H:%M:%S")}}</span>
            <span class="ago"></span>
            % else:
            METARs not fetched yet
            % end
        </p>
    </div>
    <div class="actions">
        <button class="btn primary" type="button" data-call="/fetch">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
            Fetch METARs
        </button>
        % release = get('release')
        % newer = release and release['available'] and not release['installed']
        <button class="btn{{' primary' if newer else ''}}" id="update" type="button" data-update>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>
            % if newer and release['channel'] == 'releases':
            Update to {{release['available']}}
            % else:
            Update
            % end
        </button>
        <button class="btn danger" type="button" data-call="/restart" data-then="restart" data-confirm="Restart the map now?">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 3v9"/><path d="M6.3 6.3a8 8 0 1 0 11.4 0"/></svg>
            Restart
        </button>
    </div>
</section>

<section class="cat-tiles" aria-label="Flight categories">
    % for c in cats:
    <div class="card tile {{c.lower()}}">
        <div class="lbl">{{c}}</div>
        <div class="row"><span class="n">{{counts[c]}}</span><span class="muted">{{'airport' if counts[c] == 1 else 'airports'}}</span></div>
    </div>
    % end
    <div class="card tile">
        <div class="lbl">No data</div>
        <div class="row"><span class="n">{{len(no_data)}}</span><span class="mono muted" style="font-size: 12px">{{' · '.join(no_data[:3])}}{{' …' if len(no_data) > 3 else ''}}</span></div>
    </div>
</section>

<section class="split">
    <div class="main">
        <div class="card pad">
            <div class="card-row" style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
                <div class="lbl">Visualizer</div>
                % if active['exclusive']:
                <span class="badge warn">Exclusive · Locate is paused</span>
                % else:
                <span class="badge ok">Allows interrupts</span>
                % end
            </div>
            <div class="vis-head">
                <button class="btn icon" type="button" aria-label="Previous visualizer" data-call="/visualizer/previous" data-then="home">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg>
                </button>
                <div style="flex: 1; min-width: 0">
                    <div class="name">{{active['name']}}</div>
                    <div class="desc">{{active['description']}}</div>
                </div>
                <button class="btn icon" type="button" aria-label="Next visualizer" data-call="/visualizer/next" data-then="home">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
            </div>
            %include("legend.tpl", legend=active['legend'])
            <div class="chip-row" role="group" aria-label="Choose a visualizer">
                % for i, name in enumerate(visualizers):
                <button class="chip" type="button" aria-pressed="{{'true' if i == active['index'] else 'false'}}" data-call="/visualizer/{{i}}" data-then="home">{{name}}</button>
                % end
            </div>
        </div>
    </div>

    <div class="side">
        <div class="card pad">
            <label class="lbl" for="brightness">LED brightness</label>
            <div class="big" id="brt_label">{{int(round(brightness * 100))}}%</div>
            <input id="brightness" type="range" min="0" max="1" step="0.01" value="{{brightness}}" data-label="brt_label" data-format="pct">
            <p class="muted" style="margin: 0; font-size: 13px">Temporary. The schedule below sets it again at the next sun event.</p>
            % if schedule:
            <dl class="sched">
                % for s in schedule:
                <div{{!' class="next"' if s['next'] else ''}}>
                    <dt>{{s['name']}}{{' · next' if s['next'] else ''}}</dt>
                    <dd>{{s['time'].strftime("%H:%M")}} <span>→ {{int(round(s['level'] * 100))}}%</span></dd>
                </div>
                % end
            </dl>
            % end
        </div>
        % if oled_on is not None:
        <div class="card pad">
            <div class="set-inline">
                <label class="lbl" for="oled-on">OLED display</label>
                <input id="oled-on" class="switch" type="checkbox"{{!' checked' if oled_on else ''}}>
            </div>
            <p class="muted" style="margin: 0; font-size: 13px">Turns the screen, and its copy on the Map page, on or off. Temporary: it's back on when the map restarts.</p>
        </div>
        % end
    </div>
</section>

% if below_vfr:
<section class="card">
    <div class="card-head">
        <h2>Below VFR</h2>
        <a href="/metars" style="font-size: 14px; font-weight: 500">All METARs →</a>
    </div>
    <div class="scroll-x">
        % for s in below_vfr:
        <div class="trow brief">
            <span class="station"><b>{{s['code']}}</b>
                % if s['name']:
                <span>{{s['name']}}</span>
                % end
            </span>
            <span class="pill {{s['cat'].lower()}}">{{s['cat']}}</span>
            <span class="raw" title="{{s['raw']}}">{{s['raw']}}</span>
            <span class="mono muted" style="font-size: 13px; text-align: right">{{s['obsTime'].strftime("%H:%MZ") if s['obsTime'] else '—'}}</span>
        </div>
        % end
    </div>
</section>
% end

%include("footer.tpl")
