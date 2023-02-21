%include("header.tpl",title="METARMap")

<div class="py-5 text-center">
    <h2>Home</h2>
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/metars';">Metars</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/metars/raw';" role="button">Raw Metars</button>&nbsp;
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/previous';">&lt;</button>&nbsp;
    <button class="btn btn-primary" disabled>Visualizer</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="window.location='/visualizer/next';">&gt;</button>&nbsp;
    Current Visualizer: {{renderer.visualizer[1].name}}<br />
    {{renderer.visualizer[1].description}}
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/1');">Brightness 100%</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/0.75');">Brightness 75%</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/0.5');">Brightness 50%</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/0.25');">Brightness 25%</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/0.1');">Brightness 10%</button>&nbsp;
    <button type="button" class="btn btn-primary" onClick="fetch('/brightness/0.01');">Brightness 1%</button>&nbsp;
</div>
<hr />
%include("footer.tpl")
