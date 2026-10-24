%include("header.tpl", title="Debug")
% num, vis = renderer.visualizer
<section class="page-head">
    <div>
        <h1>Debug</h1>
        <p>Active visualizer: {{vis.name}} · METARs fetched {{metars.lastFetchTime or 'never'}}</p>
    </div>
    <button class="btn" type="button" data-call="/fetch">Fetch</button>
</section>

<section class="card">
    <div class="card-head"><h2>LED effects</h2><span class="mono muted">{{len(vis.get_effects())}}</span></div>
    <pre class="dump">
% for i, e in enumerate(vis.get_effects()):
{{i}}: {{e}}
% end
</pre>
</section>

%include("footer.tpl")
