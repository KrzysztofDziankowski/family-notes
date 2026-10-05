/*
 * Registers the FamilyNotes service worker (S-06) once the page has loaded.
 * The worker URL comes from this script tag's data-sw-url. A failure is only
 * logged to the console; nothing is reported over the network or stored.
 */
(function () {
    'use strict';

    var script = document.currentScript;
    var url = script && script.dataset.swUrl;
    if (!url || !('serviceWorker' in navigator)) {
        return;
    }

    function register() {
        navigator.serviceWorker.register(url, {scope: '/'}).catch(function (error) {
            console.warn('FamilyNotes: service worker registration failed', error);
        });
    }

    if (document.readyState === 'complete') {
        register();
    } else {
        window.addEventListener('load', register);
    }
}());
