/*
 * Instant child filter of the parent calendar (child-calendar-view).
 * Loaded only by the parent calendar page.
 *
 * The page always holds every row of the 14-day window, and the server marks
 * the initial state; the filter links ([data-member-filter] a) are real
 * links carrying ?member=<pk>, so filtering works without JavaScript. A
 * plain click switches without a request, by the server's rule: with
 * "Wszyscy" every assignee group shows, with a child only that child's
 * group (data-assignee-group="member-<pk>") and "Ogólne" ("family"). A day
 * without a visible group shows its "Brak wpisów" ([data-day-empty]) and
 * gets fn-calendar-day--empty. The script then moves aria-current, reveals
 * the matching state block of the data-live-region status region (so the
 * change is announced), rewrites the member parameter of every
 * [data-member-link] href and replaces the address bar URL, so a reload,
 * list-refresh.js and the entry pages keep the filter. Ctrl/Cmd/Shift/Alt
 * and middle clicks are left to the browser. Nothing is stored in the
 * browser.
 *
 * The privacy filter ([data-privacy-filter], _privacy_filter.html) is
 * server-side only: its links reload the page. They are data-member-link,
 * so a child switch keeps them in step, and only the member parameter is
 * ever rewritten, so a selected privacy filter survives every switch.
 */
(function () {
    'use strict';

    var ALL = 'all';
    var FAMILY = 'family';
    var MEMBER_PREFIX = 'member-';
    var nav = document.querySelector('[data-member-filter]');

    if (!nav) {
        return;
    }

    function groupVisible(groupKey, memberKey) {
        return memberKey === ALL || groupKey === memberKey || groupKey === FAMILY;
    }

    function applyVisibility(memberKey) {
        var days = document.querySelectorAll('[data-day-group]');
        for (var i = 0; i < days.length; i++) {
            var groups = days[i].querySelectorAll('[data-assignee-group]');
            var visible = 0;
            for (var j = 0; j < groups.length; j++) {
                var show = groupVisible(groups[j].getAttribute('data-assignee-group'), memberKey);
                groups[j].hidden = !show;
                if (show) {
                    visible++;
                }
            }
            var empty = days[i].querySelector('[data-day-empty]');
            if (empty) {
                empty.hidden = visible > 0;
            }
            days[i].classList.toggle('fn-calendar-day--empty', visible === 0);
        }
    }

    function markCurrent(link) {
        var links = nav.querySelectorAll('a[data-member-key]');
        for (var i = 0; i < links.length; i++) {
            if (links[i] === link) {
                links[i].setAttribute('aria-current', 'page');
            } else {
                links[i].removeAttribute('aria-current');
            }
        }
    }

    function announce(memberKey) {
        var blocks = document.querySelectorAll('[data-member-status] [data-member-state]');
        for (var i = 0; i < blocks.length; i++) {
            blocks[i].hidden = blocks[i].getAttribute('data-member-state') !== memberKey;
        }
    }

    function withMember(href, memberKey) {
        var url = new URL(href, window.location.href);
        if (memberKey === ALL) {
            url.searchParams.delete('member');
        } else {
            url.searchParams.set('member', memberKey.slice(MEMBER_PREFIX.length));
        }
        return url.pathname + url.search + url.hash;
    }

    function rewriteLinks(memberKey) {
        var links = document.querySelectorAll('a[data-member-link]');
        for (var i = 0; i < links.length; i++) {
            links[i].setAttribute('href', withMember(links[i].getAttribute('href'), memberKey));
        }
        if (window.history && window.history.replaceState) {
            window.history.replaceState(window.history.state, '', withMember(window.location.href, memberKey));
        }
    }

    nav.addEventListener('click', function (event) {
        var link = event.target.closest('a[data-member-key]');
        if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
            return;
        }
        event.preventDefault();
        var memberKey = link.getAttribute('data-member-key');
        applyVisibility(memberKey);
        markCurrent(link);
        announce(memberKey);
        rewriteLinks(memberKey);
    });
}());
