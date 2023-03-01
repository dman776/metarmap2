%include("header.tpl",title="METARMap")
<style>
    html, body {
        height: 100%;
        margin: 0;
    }
    .leaflet-container {
        height: 600px;
        width: 800px;
        max-width: 100%;
        max-height: 100%;
    }
</style>


<div class="py-5 text-center">
    <h2>Map View</h2>
</div>
<hr />
<div class="row">
    <button type="button" class="btn btn-primary" onClick="window.location='/';">Home</button>&nbsp;
</div>
<hr />
<div id="map"></div>
<hr />
<script>
const map = L.map('map').setView([30.603, -93.581], 13);

	const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
		maxZoom: 19,
		attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
	}).addTo(map);

	function onMapClick(e) {
		popup
			.setLatLng(e.latlng)
			.setContent(`You clicked the map at ${e.latlng.toString()}`)
			.openOn(map);
	}

	map.on('click', onMapClick);
</script>
%include("footer.tpl")
