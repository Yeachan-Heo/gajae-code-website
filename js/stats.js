/**
 * Live project metadata for the Gajae Code website.
 *
 * Release/version claims are deliberately NOT touched here: they are owned by
 * the reviewed release-sync regions in index.html and docs/*.html. This script
 * only fills community metadata that has no generated source of truth, so it
 * stays current between deployments:
 *
 *   [data-gjc-stat="stars"]     GitHub stargazers
 *   [data-gjc-stat="forks"]     GitHub forks
 *   [data-gjc-stat="downloads"] npm downloads, last 30 days
 */
(function () {
  'use strict';

  var REPO = 'https://api.github.com/repos/Yeachan-Heo/gajae-code';
  var DOWNLOADS = 'https://api.npmjs.org/downloads/point/last-month/gajae-code';
  var CACHE_KEY = 'gjc-live-stats';
  var CACHE_TTL = 5 * 60 * 1000;

  function format(value) {
    if (typeof value !== 'number' || !isFinite(value)) return null;
    if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
    if (value >= 1000) return (value / 1000).toFixed(1) + 'k';
    return String(value);
  }

  function fill(stats) {
    var values = {
      stars: format(stats.stars),
      forks: format(stats.forks),
      downloads: format(stats.downloads)
    };
    var nodes = document.querySelectorAll('[data-gjc-stat]');
    Array.prototype.forEach.call(nodes, function (node) {
      var value = values[node.getAttribute('data-gjc-stat')];
      if (value) {
        node.textContent = value;
        node.removeAttribute('data-gjc-stat-pending');
      }
    });
  }

  function readCache() {
    try {
      var raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      var entry = JSON.parse(raw);
      if (!entry || Date.now() - entry.timestamp > CACHE_TTL) return null;
      return entry.data;
    } catch (error) {
      return null;
    }
  }

  function writeCache(data) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: data, timestamp: Date.now() }));
    } catch (error) {
      /* storage disabled; live fetching still works */
    }
  }

  function json(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (response) {
      if (!response.ok) throw new Error(url + ' -> HTTP ' + response.status);
      return response.json();
    });
  }

  function load() {
    if (!document.querySelector('[data-gjc-stat]')) return;

    var cached = readCache();
    if (cached) {
      fill(cached);
      return;
    }

    var quiet = function () {
      return null;
    };

    Promise.all([json(REPO).catch(quiet), json(DOWNLOADS).catch(quiet)]).then(function (results) {
      var repo = results[0];
      var downloads = results[1];
      if (!repo && !downloads) return;

      var stats = {};
      if (repo) {
        stats.stars = repo.stargazers_count;
        stats.forks = repo.forks_count;
      }
      if (downloads) {
        stats.downloads = downloads.downloads;
      }

      writeCache(stats);
      fill(stats);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
