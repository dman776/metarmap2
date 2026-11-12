% import datetime
        </main>
        % if not get('kiosk', False):
        <footer class="foot">
            &copy; {{datetime.date.today().year}} Darryl Quinn · <a href="http://metarmap.local">metarmap.local</a> · Version {{version}}{{' (' + release['build']['describe'] + ', commit ' + release['build']['commit'] + (', modified' if release['build']['modified'] else '') + ')' if get('release') and release['build'] and not release['build']['release'] else ''}}
        </footer>
        <dialog id="output" aria-labelledby="output-title">
            <div class="card-head"><h2 id="output-title">Output</h2></div>
            <div class="body"></div>
            <form method="dialog" class="foot-actions">
                <button class="btn" type="submit">Close</button>
                <button class="btn primary" type="button" data-call="/restart" data-then="restart" data-confirm="Restart the Chart now?">Restart</button>
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
            </form>
        </dialog>
        <dialog id="install-dialog" aria-labelledby="install-title">
            <div class="card-head"><h2 id="install-title">Network discovery</h2></div>
            <div class="update-body">
                <p class="update-note">This one-time install can take 5 minutes or more on a Pi Zero. You can close this window: the install goes on, and the button on Home shows how long it has run.</p>
                <p class="update-label" role="status">Starting</p>
                <progress class="update-bar" max="1" value="0" aria-labelledby="install-title"></progress>
                <pre class="update-errors" hidden></pre>
            </div>
            <form method="dialog" class="foot-actions">
                <button class="btn" type="submit">Close</button>
            </form>
        </dialog>
        % end
        <script src="/static/app.js?v={{assets}}"></script>
    </body>
</html>
