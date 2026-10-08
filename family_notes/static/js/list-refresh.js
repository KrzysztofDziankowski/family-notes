/*
 * Refreshes an entry list when the app resumes (mobile-gui-enhancements).
 * Loaded only by the parent and child list pages, which hold no form input.
 *
 * The first load and plain focus changes never reload. A return from the
 * background (hidden -> visible) or a back/forward-cache restore reloads the
 * current URL, family context included, once; overlapping signals are
 * deduplicated. Offline, the visible list stays and one refresh waits for the
 * next "online" event. Nothing is stored in the browser.
 */
(function () {
    'use strict';

    var wasHidden = document.visibilityState === 'hidden';
    var pending = false;
    var reloading = false;

    function refresh() {
        if (reloading) {
            return;
        }
        if (!navigator.onLine) {
            pending = true;
            return;
        }
        pending = false;
        reloading = true;
        window.location.reload();
    }

    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') {
            wasHidden = true;
        } else if (wasHidden) {
            wasHidden = false;
            refresh();
        }
    });

    window.addEventListener('pageshow', function (event) {
        if (event.persisted) {
            // The restore may also fire visibilitychange; refresh() runs once.
            wasHidden = false;
            refresh();
        }
    });

    window.addEventListener('online', function () {
        if (pending && document.visibilityState === 'visible') {
            refresh();
        }
    });
}());
