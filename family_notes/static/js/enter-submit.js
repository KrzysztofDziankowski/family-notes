/*
 * Enter-to-submit for opted-in instruction boxes (S-05).
 *
 * A <textarea data-enter-submit> submits its form on a plain Enter;
 * Shift/Ctrl/Alt/Meta+Enter keep the browser default (Shift+Enter = newline).
 * A field with data-enter-submitter="<button id>" is submitted only through
 * that submit button (its formaction/name/value apply), never through the
 * form's default action. Without this script the forms work through their
 * buttons and Enter inserts a newline.
 */
(function () {
    'use strict';

    // Forms whose submission really went out during this page life.
    var submittedForms = [];

    function namedSubmitter(field) {
        var id = field.getAttribute('data-enter-submitter');
        if (id === null) {
            return undefined;
        }
        var button = document.getElementById(id);
        var isSubmit = button && (
            (button.tagName === 'BUTTON' && button.type === 'submit') ||
            (button.tagName === 'INPUT' && (button.type === 'submit' || button.type === 'image'))
        );
        if (!isSubmit || button.form !== field.form) {
            return null;
        }
        return button;
    }

    document.addEventListener('keydown', function (event) {
        var field = event.target;
        if (!field || field.tagName !== 'TEXTAREA' || !field.hasAttribute('data-enter-submit')) {
            return;
        }
        if (event.key !== 'Enter' || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) {
            return;
        }
        // An IME / predictive-text / dead-key composition is confirming a character.
        if (event.isComposing || event.keyCode === 229) {
            return;
        }
        var form = field.form;
        if (!form) {
            return;
        }
        var submitter = namedSubmitter(field);
        if (submitter === null) {
            // The named button is missing: keep the newline, never fall back
            // to the form's default action.
            return;
        }
        event.preventDefault();
        if (event.repeat || field.value.trim() === '') {
            return;
        }
        if (form.getAttribute('aria-busy') === 'true' || submittedForms.indexOf(form) !== -1) {
            return;
        }
        if (submitter) {
            form.requestSubmit(submitter);
        } else {
            form.requestSubmit();
        }
    });

    // Registered on window so it runs after submit handlers on document
    // (bubble phase), e.g. one that cancels an offline submit: only a
    // submission that was not cancelled locks Enter for this form.
    window.addEventListener('submit', function (event) {
        if (!event.defaultPrevented && submittedForms.indexOf(event.target) === -1) {
            submittedForms.push(event.target);
        }
    });

    // A page restored from the back/forward cache accepts Enter again.
    window.addEventListener('pageshow', function () {
        submittedForms = [];
    });

    function revealHints() {
        var hints = document.querySelectorAll('[data-enter-hint]');
        for (var i = 0; i < hints.length; i += 1) {
            hints[i].hidden = false;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', revealHints);
    } else {
        revealHints();
    }
}());
