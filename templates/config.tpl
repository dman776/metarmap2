%include("header.tpl",title="METAR List")
<div class="py-5 text-center">
    <h2>CONFIG</h2>
</div>

<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<h3>Display Screen</h3>
<div class="row">
    % setdefault('key', "renderer.config.data.display_screen.enabled")
    % setdefault('val', renderer.config.data.display_screen.enabled)
    <div class="form-check">
        <input class="form-check-input" type="checkbox"
        {{"checked" if dse else ""}}
        value="{{val}}"
        id="dse"
        onChange="fetch('/config/edit/{{key}}/' + !this.value);>
        <label class="form-check-label" for="dse">Enabled</label>
    </div>
</div>
<div class="row">
    <div class="form-check">
        <input class="form-check-input" type="checkbox" {{"checked" if renderer.config.data.display_screen.locate_active else ""}} value="{{renderer.config.data.display_screen.locate_active}}" id="defaultCheck1">
        <label class="form-check-label" for="defaultCheck1">Highlight Active Airport</label>
    </div>
</div>
<hr />
<h3>LED Pixels</h3>
<div class="row">
    <div class="form-check">
        <input class="form-check-input" type="checkbox" {{"checked" if renderer.config.data.led.inittest else ""}} value="{{renderer.config.data.led.inittest}}" id="defaultCheck1">
        <label class="form-check-label" for="defaultCheck1">Show test pattern on init</label>
    </div>
</div>

%include("footer.tpl")
