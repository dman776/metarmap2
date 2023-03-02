%include("header.tpl",title="METAR List")
<script>
function config_edit_boolean(item, key) {
    fetch('/config/edit/' + key + '/' + item.checked);
    return;
}
function config_edit(key, value) {
    fetch('/config/edit/' + key + '/' + value);
    return;
}
</script>
<div class="py-5 text-center">
    <h2>CONFIG</h2>
</div>

<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<h3>Visualizer Settings</h3>
<div class="row">
    % key = "visualizer.active"
    % val = renderer.config.data.visualizer.active
    <div class="dropdown show">
      <button class="btn btn-secondary dropdown-toggle" type="button" id="defaultVisualizer" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
        Default Visualizer
      </button>
      <div class="dropdown-menu" aria-labelledby="defaultVisualizer">
        %for i in range(0, len(renderer.visualizers)):
            <a class="dropdown-item" onClick="config_edit('{{key}}', '{{i}}');">{{renderer.visualizers[i].name}}</a>
        %end
      </div>
    </div>&nbsp;
</div>
<div class="row">
    % key = "lightning.animation"
    % val = renderer.config.data.lightning.animation
    <div class="form-check">
        <input class="form-check-input" type="checkbox"
        {{"checked" if val else ""}}
        value="{{str(val).lower()}}"
        id="la"
        onChange="config_edit_boolean(this, '{{key}}');">
        <label class="form-check-label" for="la">Lightning animation enabled</label>
    </div>
</div>
<hr />
<h3>Display Screen</h3>
<div class="row">
    % key = "display_screen.enabled"
    % val = renderer.config.data.display_screen.enabled
    <div class="form-check">
        <input class="form-check-input" type="checkbox"
        {{"checked" if val else ""}}
        value="{{str(val).lower()}}"
        id="dse"
        onChange="config_edit_boolean(this, '{{key}}');">
        <label class="form-check-label" for="dse">Enabled</label>
    </div>
</div>
<div class="row">
    % key = "display_screen.locate_active"
    % val = renderer.config.data.display_screen.locate_active
    <div class="form-check">
        <input class="form-check-input" type="checkbox"
        {{"checked" if val else ""}}
        value="{{str(val).lower()}}"
        id="dsla"
        onChange="config_edit_boolean(this, '{{key}}');">
        <label class="form-check-label" for="dsla">Highlight Active Airport</label>
    </div>
</div>
<hr />
<h3>LED Pixels</h3>
<div class="row">
    % key = "led.inittest"
    % val = renderer.config.data.led.inittest
    <div class="form-check">
        <input class="form-check-input" type="checkbox"
        {{"checked" if renderer.config.data.led.inittest else ""}}
        value="{{str(val).lower()}}"
        id="li"
        onChange="config_edit_boolean(this, '{{key}}');">
        <label class="form-check-label" for="li">Show test pattern on init</label>
    </div>
</div>

%include("footer.tpl")
