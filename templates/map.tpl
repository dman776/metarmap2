%include("header.tpl",title="METARMap")

<div class="py-5 text-center">
    <h2>Map View</h2>
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<div class="row">
    <div id="map"></div>
</div>
<hr />
<script>
var map = L.map('map').setView([51.505, -0.09], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);
</script>
%include("footer.tpl")
