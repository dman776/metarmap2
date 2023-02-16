%include("header.tpl",title="METARMap")
<div class="py-5 text-center">
    <h2>Home</h2>
</div>
<hr />
<div class="row">
    <a class="btn btn-primary" href="/" role="button">Control</a>&nbsp;
</div>
<div class="row">
    <a class="btn btn-primary" href="/metars" role="button">Metars</a>&nbsp;
    <a class="btn btn-primary" href="/raw" role="button">Raw Metars</a>&nbsp;
</div>
<div class="row">
    <a class="btn btn-primary" href="/visualizer/previous" role="button">Prev</a>
    &nbsp;Visualizer&nbsp;
    <a class="btn btn-primary" href="/visualizer/next" role="button">Next</a>&nbsp;
</div>
<div class="row">
    <a class="btn btn-primary" href="/brightness/1" role="button">Brightness 100%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.75" role="button">Brightness 75%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.5" role="button">Brightness 50%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.25" role="button">Brightness 25%</a>&nbsp;
    <a class="btn btn-primary" href="/brightness/0.1" role="button">Brightness 10%</a>&nbsp;
</div>
<div class="row">
    <a class="btn btn-primary" href="/fetch" role="button">Fetch</a>&nbsp;
</div>
<div class="row">
    Current Visualizer: {{renderer.visualizer[1]}}
</div>
%include("footer.tpl")
