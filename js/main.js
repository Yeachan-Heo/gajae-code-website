/*
 * Gajae Code — Website interactions
 * Plain JS, no dependencies. Used by the homepage and docs pages.
 */
(function () {
  'use strict';

  /* ---- Mobile nav toggle ---- */
  function initNav() {
    var hamburger = document.querySelector('.nav__hamburger');
    var links = document.querySelector('.nav__links');
    var overlay = document.querySelector('.nav__overlay');
    if (!hamburger || !links) return;

    function close() {
      hamburger.classList.remove('active');
      links.classList.remove('active');
      if (overlay) overlay.classList.remove('active');
      hamburger.setAttribute('aria-expanded', 'false');
    }

    function toggle() {
      var open = links.classList.toggle('active');
      hamburger.classList.toggle('active', open);
      if (overlay) overlay.classList.toggle('active', open);
      hamburger.setAttribute('aria-expanded', String(open));
    }

    hamburger.addEventListener('click', toggle);
    if (overlay) overlay.addEventListener('click', close);
    links.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', close);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  /* ---- Nav shadow on scroll ---- */
  function initNavScroll() {
    var nav = document.querySelector('.nav');
    if (!nav) return;
    function onScroll() {
      nav.classList.toggle('scrolled', window.scrollY > 24);
    }
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  /* ---- Copy-to-clipboard for code blocks ---- */
  function initCopy() {
    document.querySelectorAll('.code-block__copy').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var text = btn.getAttribute('data-copy');
        if (!text) {
          var body = btn.closest('.code-block');
          var code = body && body.querySelector('.code-block__body');
          text = code ? code.innerText.trim() : '';
        }
        if (!text) return;

        var done = function () {
          var original = btn.textContent;
          btn.textContent = 'Copied';
          btn.classList.add('copied');
          setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove('copied');
          }, 1600);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(done).catch(function () {
            fallbackCopy(text);
            done();
          });
        } else {
          fallbackCopy(text);
          done();
        }
      });
    });
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* noop */ }
    document.body.removeChild(ta);
  }

  /* ---- Reveal on scroll ---- */
  function initReveal() {
    var els = document.querySelectorAll('.reveal');
    if (!els.length) return;

    if (!('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

    els.forEach(function (el) { io.observe(el); });
  }


  /* ---- Live package/repo metadata ---- */
  var LIVE_META = {
    npmLatest: 'https://registry.npmjs.org/gajae-code/latest',
    npmDownloads: 'https://api.npmjs.org/downloads/point/last-week/gajae-code',
    githubRepo: 'https://api.github.com/repos/Yeachan-Heo/gajae-code'
  };

  function formatCompactNumber(value) {
    var number = Number(value);
    if (!Number.isFinite(number) || number < 0) return null;
    if (typeof Intl !== 'undefined' && Intl.NumberFormat) {
      return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(number);
    }
    return String(Math.round(number));
  }

  function setText(selector, value) {
    if (value == null || value === '') return;
    document.querySelectorAll(selector).forEach(function (el) {
      el.textContent = value;
      el.classList.add('is-live');
    });
  }

  function fetchJson(url) {
    return fetch(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    }).then(function (res) {
      if (!res.ok) throw new Error('metadata request failed: ' + res.status);
      return res.json();
    });
  }

  function initLiveStats() {
    if (!('fetch' in window)) return;

    fetchJson(LIVE_META.npmLatest).then(function (data) {
      if (data && typeof data.version === 'string') {
        setText('[data-live-version]', 'v' + data.version);
      }
    }).catch(function () { /* keep static fallback */ });

    fetchJson(LIVE_META.npmDownloads).then(function (data) {
      var formatted = data && formatCompactNumber(data.downloads);
      setText('[data-live-downloads]', formatted);
    }).catch(function () { /* keep static fallback */ });

    fetchJson(LIVE_META.githubRepo).then(function (data) {
      var formatted = data && formatCompactNumber(data.stargazers_count);
      setText('[data-live-stars]', formatted);
    }).catch(function () { /* keep static fallback */ });
  }

  /* ---- Current year ---- */
  function initYear() {
    document.querySelectorAll('[data-year]').forEach(function (el) {
      el.textContent = String(new Date().getFullYear());
    });
  }

  /* ---- Docs sidebar toggle ---- */
  function initDocsSidebar() {
    var burger = document.getElementById('docsBurger');
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');

    // Backward-compatible: older docs pages use .docs-menu and #docs-sidebar
    if (!burger) {
      burger = document.querySelector('.docs-menu');
    }
    if (!sidebar) {
      sidebar = document.getElementById('docs-sidebar');
    }

    if (!burger || !sidebar) return;

    function close() {
      sidebar.classList.remove('active');
      if (overlay) overlay.classList.remove('active');
      burger.setAttribute('aria-expanded', 'false');
    }
    burger.addEventListener('click', function () {
      var open = sidebar.classList.toggle('active');
      if (overlay) overlay.classList.toggle('active', open);
      burger.setAttribute('aria-expanded', String(open));
    });
    if (overlay) overlay.addEventListener('click', close);
    sidebar.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', close);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  function init() {
    initNav();
    initNavScroll();
    initCopy();
    initReveal();
    initLiveStats();
    initYear();
    initDocsSidebar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
