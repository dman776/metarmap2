% page = get('page', '')
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <title>{{title}} · METARMap</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="theme-color" content="#0d141c">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans:wght@500&display=swap">
        <link rel="stylesheet" href="/static/style.css?v={{config.app_version}}">
        % if get('leaflet', False):
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
        % end
    </head>
    <body>
        <header class="topbar">
            <div class="wrap">
                <a class="brand" href="/">
                    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="none" stroke="#f5b544" stroke-width="2"/><circle cx="14" cy="14" r="4" fill="#3ddc84"/><circle cx="7" cy="9" r="2" fill="#4ea8ff"/><circle cx="20" cy="19" r="2" fill="#ff5a5a"/></svg>
                    METARMap
                </a>
                <nav class="nav" aria-label="Main">
                    % for href, key, label in (('/', 'home', 'Home'), ('/metars', 'metars', 'METARs'), ('/map', 'map', 'Map'), ('/config', 'config', 'Config'), ('/raw', 'raw', 'Raw')):
                    <a href="{{href}}"{{!' aria-current="page"' if page == key else ''}}>{{label}}</a>
                    % end
                </nav>
                % if defined('myIP'):
                <span class="host">{{myIP}} · v{{config.app_version}}</span>
                % else:
                <span class="host">v{{config.app_version}}</span>
                % end
            </div>
        </header>
        <main class="wrap">
