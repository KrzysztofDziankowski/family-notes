/*
 * Refreshes an entry list when the app resumes (mobile-gui-enhancements).
 * Loaded only by the parent and child list pages, which hold no form input.
 *
 * The first load and plain focus changes never reload. Returning after at
 * least MIN_HIDDEN_MS in the background (hidden -> visible, or a back/forward
 * cache restore) reloads the current URL, family context included, once;
 * overlapping signals are deduplicated and brief app switches keep the page,
 * its focus and its messages. Before reloading, a HEAD request to the health
 * URL (this script tag's data-health-url) confirms the server answers, so an
 * unreachable server never swaps the list for the offline page. Offline or
 * unreachable, the visible list stays and one refresh waits for the next
 * "online" event or resume. Nothing is stored in the browser.
 */
(function () {
    'use strict';

    var MIN_HIDDEN_MS = 30000;
    var script = document.currentScript;
    var healthUrl = script && script.dataset.healthUrl;
    var hiddenAt = document.visibilityState === 'hidden' ? Date.now() : null;
    var pending = false;
    var reloading = false;

    function stale() {
        return hiddenAt !== null && Date.now() - hiddenAt >= MIN_HIDDEN_MS;
    }

    function markPending() {
        reloading = false;
        pending = true;
    }

    function refresh() {
        if (reloading) {
            return;
        }
        if (!navigator.onLine || !healthUrl) {
            pending = true;
            return;
        }
        reloading = true;
        fetch(healthUrl, {method: 'HEAD', cache: 'no-store', credentials: 'same-origin'})
            .then(function (response) {
                if (!response.ok) {
                    markPending();
                    return;
                }
                pending = false;
                window.location.reload();
            }, markPending);
    }

    function resumed() {
        var due = pending || stale();
        hiddenAt = null;
        if (due) {
            refresh();
        }
    }

    function hidden() {
        if (hiddenAt === null) {
            hiddenAt = Date.now();
        }
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') {
            hidden();
        } else {
            resumed();
        }
    });

    window.addEventListener('pagehide', hidden);

    window.addEventListener('pageshow', function (event) {
        // The restore may also fire visibilitychange; refresh() runs once.
        if (event.persisted) {
            resumed();
        }
    });

    window.addEventListener('online', function () {
        if (pending && document.visibilityState === 'visible') {
            refresh();
        }
    });
}());
