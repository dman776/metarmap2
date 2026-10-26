% page = get('page', '')
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="utf-8">
        <title>{{title}} · METARMap</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="theme-color" content="#0d141c">
        <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans:wght@500&display=swap">
        <link rel="stylesheet" href="/static/style.css?v={{version}}">
        % if get('leaflet', False):
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
        % end
    </head>
    <body>
        <header class="topbar">
            <div class="wrap">
                <a class="brand" href="/">
                    <svg width="28" height="28" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" fill="none" stroke="#f5b544" stroke-width="1.8" stroke-linejoin="round"/><circle cx="5" cy="4.5" r="2" fill="#3ddc84" style="filter: drop-shadow(0 0 2px #3ddc84)"/></svg>
                    METARMap
                </a>
                <nav class="nav" aria-label="Main">
                    % for href, key, label in (('/', 'home', 'Home'), ('/metars', 'metars', 'METARs'), ('/map', 'map', 'Map'), ('/config', 'config', 'Config')):
                    <a href="{{href}}"{{!' aria-current="page"' if page == key else ''}}>{{label}}</a>
                    % end
                </nav>
                % release = get('release')
                % if release and release['badge']:
                <a class="update-badge" href="/#update">{{release['badge']}}</a>
                % end
                % if defined('myIP'):
                <span class="host">{{myIP}} · v{{version}}</span>
                % else:
                <span class="host">v{{version}}</span>
                % end
            </div>
        </header>
        <main class="wrap">
