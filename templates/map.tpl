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
const map = L.map('map').setView({{config.data.geo.map.center}}, {{config.data.geo.map.zoom}});
const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
}).addTo(map);

var VFRIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

var MVFRIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

var IFRIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

var LIFRIcon = new L.Icon({
  iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-violet.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41]
});

	%for m in metars.data:
	    %if 'latitude' in metars.data[m]:
	        marker = ""
	        %if metars.data[m]['flightCategory']=='VFR':
                marker = L.marker([{{metars.data[m]['latitude']}},{{metars.data[m]['longitude']}}], {icon: VFRIcon});
            %elif metars.data[m]['flightCategory']=='MVFR':
                marker = L.marker([{{metars.data[m]['latitude']}},{{metars.data[m]['longitude']}}], {icon: MVFRIcon});
            %elif metars.data[m]['flightCategory']=='IFR':
                marker = L.marker([{{metars.data[m]['latitude']}},{{metars.data[m]['longitude']}}], {icon: IFRIcon});
            %elif metars.data[m]['flightCategory']=='LIFR':
                marker = L.marker([{{metars.data[m]['latitude']}},{{metars.data[m]['longitude']}}], {icon: LIFRIcon});
            %end
            marker.bindPopup("{{metars.data[m]['raw']}}").openPopup();
            marker.addTo(map);
	    %end
	%end

</script>
%include("footer.tpl")
