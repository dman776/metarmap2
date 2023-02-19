%include("header.tpl",title="METARMap")
<div class="py-5 text-center">
    <h2>Home</h2>
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/" role="button">Home</a>&nbsp;
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/metars" role="button">Metars</a>&nbsp;
    <a class="btn btn-primary" href="/raw" role="button">Raw Metars</a>&nbsp;
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/visualizer/previous" role="button">&lt;</a>&nbsp;
    <a class="btn btn-primary" href="#" role="button">Visualizer</a>&nbsp;
    <a class="btn btn-primary" href="/visualizer/next" role="button">&gt;</a>&nbsp;
    Current Visualizer: {{renderer.visualizer[1].name}}<br />
    {{renderer.visualizer[1].description}}
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/brightness/1" role="button">Brightness 100%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.75" role="button">75%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.5" role="button">50%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.25" role="button">25%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.1" role="button">10%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.01" role="button">1%</a>&nbsp;
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/fetch" role="button">Fetch</a>&nbsp;
</div>
<hr />
%include("footer.tpl")
