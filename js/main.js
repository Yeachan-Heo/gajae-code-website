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

  /* ---- Latest standalone GJC binary installer ---- */
  function initGjcInstallers() {
    var installers = document.querySelectorAll('[data-gjc-installer]');
    var heroDownloads = document.querySelectorAll('[data-gjc-hero-download]');
    if (!installers.length && !heroDownloads.length) return;

    var releasesBase = 'https://github.com/Yeachan-Heo/gajae-code/releases/latest/download/';
    var platforms = {
      'gjc-darwin-arm64': {
        label: 'macOS arm64',
        command: 'sudo install -m 0755 ~/Downloads/gjc-darwin-arm64 /usr/local/bin/gjc'
      },
      'gjc-darwin-x64': {
        label: 'macOS x64',
        command: 'sudo install -m 0755 ~/Downloads/gjc-darwin-x64 /usr/local/bin/gjc'
      },
      'gjc-linux-x64': {
        label: 'Linux x64',
        command: 'sudo install -m 0755 ~/Downloads/gjc-linux-x64 /usr/local/bin/gjc'
      },
      'gjc-linux-arm64': {
        label: 'Linux arm64',
        command: 'sudo install -m 0755 ~/Downloads/gjc-linux-arm64 /usr/local/bin/gjc'
      },
      'gjc-windows-x64.exe': {
        label: 'Windows x64',
        command: '$dir = "$env:LOCALAPPDATA\\Programs\\gjc"\nNew-Item -ItemType Directory -Force $dir | Out-Null\nMove-Item "$HOME\\Downloads\\gjc-windows-x64.exe" "$dir\\gjc.exe" -Force\n$userPath = [Environment]::GetEnvironmentVariable("Path", "User")\nif (($userPath -split ";") -notcontains $dir) { [Environment]::SetEnvironmentVariable("Path", "$userPath;$dir", "User") }'
      }
    };

    function detectedAsset(platform, architecture) {
      var platformName = String(platform || '').toLowerCase();
      var architectureName = String(architecture || '').toLowerCase();
      var isArm = /arm|aarch64/.test(architectureName);

      if (/win/.test(platformName)) return 'gjc-windows-x64.exe';
      if (/mac/.test(platformName)) {
        if (isArm) return 'gjc-darwin-arm64';
        if (/x86|x64|intel/.test(architectureName)) return 'gjc-darwin-x64';
        return '';
      }
      if (/linux/.test(platformName)) return isArm ? 'gjc-linux-arm64' : 'gjc-linux-x64';
      return '';
    }

    function apply(installer, asset, detected) {
      var config = platforms[asset];
      var select = installer.querySelector('[data-gjc-platform]');
      var download = installer.querySelector('[data-gjc-download]');
      var command = installer.querySelector('[data-gjc-command]');
      var copy = installer.querySelector('[data-gjc-copy]');
      var detection = installer.querySelector('[data-gjc-detection]');
      var details = installer.querySelectorAll('[data-gjc-details]');
      if (!config || !select || !download || !command) return;

      select.value = asset;
      download.href = releasesBase + asset;
      download.textContent = 'Download latest for ' + config.label;
      download.setAttribute('aria-label', 'Download the latest GJC standalone binary for ' + config.label);
      details.forEach(function (detail) { detail.removeAttribute('hidden'); });
      command.textContent = config.command;
      if (copy) copy.setAttribute('data-copy', config.command);
      if (detection) {
        detection.textContent = detected
          ? 'Detected ' + config.label + '. Change it above when downloading for another machine.'
          : 'Platform selected manually. The link always resolves to the latest stable release.';
      }
    }

    function applyHeroDownload(download, asset) {
      var config = platforms[asset];
      if (!config) return;
      download.href = releasesBase + asset;
      download.textContent = 'Download for ' + config.label;
      download.setAttribute('aria-label', 'Download the latest GJC standalone binary for ' + config.label);
    }

    installers.forEach(function (installer) {
      var select = installer.querySelector('[data-gjc-platform]');
      if (!select) return;
      apply(installer, select.value, false);
      select.addEventListener('change', function () {
        apply(installer, select.value, false);
        heroDownloads.forEach(function (download) { applyHeroDownload(download, select.value); });
      });
    });

    var fallbackPlatform = navigator.platform || navigator.userAgent;
    var fallbackArchitecture = /linux/i.test(fallbackPlatform) ? navigator.userAgent : '';
    var fallbackAsset = detectedAsset(fallbackPlatform, fallbackArchitecture);
    if (fallbackAsset) {
      installers.forEach(function (installer) { apply(installer, fallbackAsset, true); });
      heroDownloads.forEach(function (download) { applyHeroDownload(download, fallbackAsset); });
    }

    if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
      navigator.userAgentData.getHighEntropyValues(['architecture', 'platform']).then(function (values) {
        var asset = detectedAsset(values.platform, values.architecture);
        if (!asset) return;
        installers.forEach(function (installer) { apply(installer, asset, true); });
        heroDownloads.forEach(function (download) { applyHeroDownload(download, asset); });
      }).catch(function () { /* Keep the synchronous fallback. */ });
    }
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
    initGjcInstallers();
    initCopy();
    initReveal();
    initYear();
    initDocsSidebar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
