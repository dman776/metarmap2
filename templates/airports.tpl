%include("header.tpl",title="Config Airports")
<script>
function config_edit_boolean(item, airport, key) {
    fetch('/config/airports/edit/prop/' + airport + '/' + key + '/' + item.checked);
    return;
}
function config_edit(key, newkey) {
    window.location('/config/airports/edit/' + key + '/' + newkey);
    return;
}

</script>
<div class="py-5 text-center">
    <h2>Configure</h2>
</div>

<div class="row">
    <div class="col-sm">
        <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>
        &nbsp
        <button type="button" class="btn btn-secondary" onClick="window.location='/config';">Config</button>
        &nbsp
    </div>
</div>

<h4>Airports</h4>
<form class="form-inline">
    % i = 0
    %for a in airports.keys():
    <div class="form-row w-100">
        <div class="input-group col-md-1">
            <label class="sr-only">Pixel #</label>
            <div>{{i+1}}</div>
        </div>
        <div class="input-group col-md-1">
            <label class="sr-only" for="code">Airport Code</label>
            <input type="text" class="form-control mb-2 mr-sm-2" id="code" value="{{a}}"
                   onChange="config_edit('{{a}}', this.value);"/>
        </div>
        <div class=" input-group col-md-4">
            <div class="form-check mb-2 mr-sm-2">
                <input class="form-check-input" type="checkbox" id="is_oled"
                       {{"checked" if airports[a]['display'] else ""}}
                value="{{str(airports[a]['display']).lower()}}"
                onChange="config_edit_boolean(this, '{{a}}', 'display');"
                />
                <label class="form-check-label" for="is_oled">OLED Display</label>
            </div>
        </div>
    </div>
    % i+=1
    %end
</form>
%include("footer.tpl")
