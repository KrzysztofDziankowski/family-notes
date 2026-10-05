/*
 * Classification progress indicator (S-06).
 *
 * A form marked data-classification-progress-form contains the server-rendered
 * progress partial. On a submit that calls the classification provider (a
 * button with data-classification-submit, or no submitter on a form marked
 * data-classification-default) this script marks the form busy and reveals
 * the matching state block: running, then slow, then stalled, from the
 * thresholds in the form's data attributes. Offline submits are blocked and
 * keep the typed text.
 *
 * Nothing posted changes: no field or submitter is disabled (that would drop
 * its value), the script never reads field values, makes no network calls and
 * uses no storage. Without this script the forms work as plain posts.
 */
(function () {
    'use strict';

    var FORM_SELECTOR = 'form[data-classification-progress-form]';

    // The in-flight submission: {form, submitter, state, readOnly, timers}.
    var active = null;
    // Forms whose state blocks this script changed during this page life.
    var touchedForms = [];

    function touch(form) {
        if (touchedForms.indexOf(form) === -1) {
            touchedForms.push(form);
        }
    }

    function isFormElement(node) {
        return Boolean(node) && node.tagName === 'FORM';
    }

    function isProgressForm(form) {
        return isFormElement(form) && form.matches(FORM_SELECTOR);
    }

    function callsProvider(form, submitter) {
        if (submitter) {
            return submitter.hasAttribute('data-classification-submit');
        }
        return form.hasAttribute('data-classification-default');
    }

    function seconds(form, name) {
        var value = parseInt(form.getAttribute(name), 10);
        return isNaN(value) || value <= 0 ? null : value;
    }

    function showState(form, name) {
        touch(form);
        var blocks = form.querySelectorAll('[data-progress-state]');
        for (var i = 0; i < blocks.length; i += 1) {
            blocks[i].hidden = blocks[i].getAttribute('data-progress-state') !== name;
        }
    }

    function elapsedNode(form) {
        return form.querySelector('[data-progress-elapsed]');
    }

    function setElapsed(form, value) {
        var node = elapsedNode(form);
        if (!node) {
            return;
        }
        if (value === null) {
            node.hidden = true;
            return;
        }
        node.textContent = value + ' s';
        node.hidden = false;
    }

    function stopTimers() {
        if (!active) {
            return;
        }
        for (var i = 0; i < active.timers.length; i += 1) {
            clearTimeout(active.timers[i]);
            clearInterval(active.timers[i]);
        }
        active.timers = [];
    }

    function setState(name) {
        active.state = name;
        showState(active.form, name);
    }

    function enterBusy(form, submitter) {
        var textareas = form.querySelectorAll('textarea');
        var madeReadOnly = [];
        for (var i = 0; i < textareas.length; i += 1) {
            if (!textareas[i].readOnly) {
                textareas[i].readOnly = true;
                madeReadOnly.push(textareas[i]);
            }
        }
        form.setAttribute('aria-busy', 'true');
        if (submitter) {
            submitter.setAttribute('aria-busy', 'true');
            submitter.setAttribute('aria-disabled', 'true');
        }
        active = {form: form, submitter: submitter, state: null, readOnly: madeReadOnly, timers: []};
        setState('running');

        var started = Date.now();
        setElapsed(form, 0);
        active.timers.push(setInterval(function () {
            setElapsed(form, Math.floor((Date.now() - started) / 1000));
        }, 1000));

        var slowAfter = seconds(form, 'data-progress-slow-after');
        if (slowAfter !== null) {
            active.timers.push(setTimeout(function () {
                if (active && active.state === 'running') {
                    setState('slow');
                }
            }, slowAfter * 1000));
        }
        var stalledAfter = seconds(form, 'data-progress-stalled-after');
        if (stalledAfter !== null) {
            active.timers.push(setTimeout(function () {
                if (active && (active.state === 'running' || active.state === 'slow')) {
                    setState('stalled');
                }
            }, stalledAfter * 1000));
        }
    }

    // Leaves the visible state block alone; callers decide what to show.
    function clearBusy() {
        if (!active) {
            return;
        }
        stopTimers();
        active.form.removeAttribute('aria-busy');
        if (active.submitter) {
            active.submitter.removeAttribute('aria-busy');
            active.submitter.removeAttribute('aria-disabled');
        }
        for (var i = 0; i < active.readOnly.length; i += 1) {
            active.readOnly[i].readOnly = false;
        }
        setElapsed(active.form, null);
        active = null;
    }

    document.addEventListener('submit', function (event) {
        var form = event.target;
        if (!isProgressForm(form)) {
            return;
        }
        if (active) {
            // One classification at a time, whatever button was used.
            event.preventDefault();
            return;
        }
        var submitter = event.submitter || null;
        if (!callsProvider(form, submitter)) {
            return;
        }
        if (navigator.onLine === false) {
            event.preventDefault();
            setElapsed(form, null);
            showState(form, 'offline');
            return;
        }
        enterBusy(form, submitter);
    });

    window.addEventListener('offline', function () {
        if (active) {
            setState('connection_lost');
        }
    });

    document.addEventListener('click', function (event) {
        var button = event.target && event.target.closest
            ? event.target.closest('[data-progress-retry]')
            : null;
        if (!button || !active || button.form !== active.form) {
            return;
        }
        var form = active.form;
        var submitter = active.submitter;
        if (!submitter && !form.hasAttribute('data-classification-default')) {
            // Never resubmit through the form's default action (e.g. a save).
            return;
        }
        clearBusy();
        // The original submitter keeps its formaction, name and value.
        if (submitter) {
            form.requestSubmit(submitter);
        } else {
            form.requestSubmit();
        }
    });

    // Leaving the page: a restored copy must not show stale timer states.
    window.addEventListener('pagehide', function () {
        stopTimers();
    });

    // Restored from the back/forward cache: not busy and no stale panel.
    // Only forms this script changed are reset, so server-rendered states
    // (the DEBUG gallery) stay as rendered.
    window.addEventListener('pageshow', function () {
        clearBusy();
        var forms = touchedForms;
        touchedForms = [];
        for (var i = 0; i < forms.length; i += 1) {
            forms[i].removeAttribute('aria-busy');
            showState(forms[i], null);
            setElapsed(forms[i], null);
        }
        touchedForms = [];
    });
}());
