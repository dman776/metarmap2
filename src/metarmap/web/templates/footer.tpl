% import datetime
        </main>
        <footer class="foot">
            &copy; {{datetime.date.today().year}} Darryl Quinn · <a href="http://metarmap.local">metarmap.local</a> · Version {{version}}{{' (' + release['build']['describe'] + ', commit ' + release['build']['commit'] + (', modified' if release['build']['modified'] else '') + ')' if get('release') and release['build'] and not release['build']['release'] else ''}}
        </footer>
        <dialog id="output" aria-labelledby="output-title">
            <div class="card-head"><h2 id="output-title">Output</h2></div>
            <div class="body"></div>
            <form method="dialog" class="foot-actions">
                <button class="btn" type="submit">Close</button>
                <button class="btn primary" type="button" data-call="/restart" data-then="restart" data-confirm="Restart the map now?">Restart</button>
            </form>
        </dialog>
        <dialog id="update-dialog" aria-labelledby="update-title">
            <div class="card-head"><h2 id="update-title">Update</h2></div>
            <div class="update-body">
                <p class="update-label" role="status">Starting</p>
                <progress class="update-bar" max="1" value="0" aria-labelledby="update-title"></progress>
                <pre class="update-errors" hidden></pre>
            </div>
            <form method="dialog" class="foot-actions">
                <button class="btn" type="submit">Close</button>
                <button class="btn primary update-restart" type="button" data-call="/restart" data-then="restart" hidden>Restart now</button>
            </form>
        </dialog>
        <script src="/static/app.js?v={{assets}}"></script>
    </body>
</html>
