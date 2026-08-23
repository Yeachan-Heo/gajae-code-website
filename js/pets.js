/*
 * Gajae pets - verbatim data + renderer ported from gajae-code:
 *   packages/tui/src/components/gajae-pet.ts        (crab frames, RED/BLUE palettes, GAJAE_IDLE_STEPS)
 *   packages/tui/src/components/ouroboros-pet-frames.json + ouroboros-pet.ts (OUROBOROS_*)
 * Grids, palettes and idle step durations are exact copies of the source implementation.
 */
(function () {
  'use strict';

var CRAB_FRAMES = {
    "base": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGGVVGGK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "gazeL": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGGVGGVK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "gazeR": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KVGGVGGK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "flicker": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KVVVVVVK.KK.","KRRKKVGVVGVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."]
  };

  var OURO_FRAMES = {
    "idle": ["................","................",".....RRR........","....RRDRRR......","....RRRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "blink": ["................","................",".....RRR........","....RRRRRR......","....RRRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "tongue-1": ["................","................",".....RRR........","....RRDRRR......","....RRRRRRR.....","....ARRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "tongue-2": ["................","................",".....RRR........","....RRDRRR......","..A.RRRRRRR.....","...AARRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-1": ["................","................",".....RRR........","....RRwRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-2": ["................","........w.......","...w.RRR........","....RRRRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-3": ["..........ww....","ww......w.......","...w.RRR........","....RRRRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"]
  };

  var PETS = {
    red: { label: "RedGajae", description: "The Red Crab, who likes to work-out.", palette: {"K":[74,20,8],"R":[229,72,46],"r":[255,122,82],"V":[14,22,14],"G":[61,245,146],"H":[232,180,90],"h":[169,117,47],"b":[216,154,74],"A":[196,60,30],"w":[200,230,255]}, frames: CRAB_FRAMES, idle: [["base",1100],["gazeL",350],["base",500],["gazeR",350],["base",800],["flicker",150]] },
    blue: { label: "BlueGajae", description: "The Blue Crab, who wants to rest.", palette: {"K":[7,38,74],"R":[47,155,255],"r":[94,200,255],"V":[14,22,14],"G":[61,245,146],"H":[232,180,90],"h":[169,117,47],"b":[125,211,252],"A":[37,120,200],"w":[230,247,255]}, frames: CRAB_FRAMES, idle: [["base",1100],["gazeL",350],["base",500],["gazeR",350],["base",800],["flicker",150]] },
    ouroboros: { label: "Ouroboros", description: "The little snake who keeps going.", palette: {"D":[20,100,48],"R":[174,232,14],"r":[112,146,190],"G":[255,231,134],"A":[255,137,180],"w":[190,231,255]}, frames: OURO_FRAMES, idle: [["idle",1400],["blink",120],["idle",500],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",1600],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",2200],["blink",120],["idle",900],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",1800],["cry-1",180],["cry-2",180],["cry-3",320],["cry-2",180],["cry-3",320],["cry-2",180],["cry-3",420],["idle",1600]] }
  };
  var CELL = 16;
  var REDUCED = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function drawFrame(canvas, pet, frameName) {
    var grid = pet.frames[frameName];
    if (!grid || !canvas.getContext) return;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (var y = 0; y < grid.length; y++) {
      var row = grid[y];
      for (var x = 0; x < row.length; x++) {
        var rgb = pet.palette[row.charAt(x)];
        if (!rgb) continue;
        ctx.fillStyle = 'rgb(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ')';
        ctx.fillRect(x, y, 1, 1);
      }
    }
  }

  var players = [];

  function initCanvas(canvas) {
    var pet = PETS[canvas.getAttribute('data-gajae-pet')];
    if (!pet) return;
    canvas.width = CELL;
    canvas.height = CELL;
    drawFrame(canvas, pet, pet.idle[0][0]);
    if (REDUCED) return; // static first frame only
    players.push({ canvas: canvas, pet: pet, step: 0, remaining: pet.idle[0][1], visible: true });
  }

  var last = null;
  function tick(now) {
    if (last === null) last = now;
    var dt = Math.min(now - last, 250);
    last = now;
    for (var i = 0; i < players.length; i++) {
      var p = players[i];
      if (!p.visible || document.hidden) continue;
      p.remaining -= dt;
      while (p.remaining <= 0) {
        p.step = (p.step + 1) % p.pet.idle.length;
        drawFrame(p.canvas, p.pet, p.pet.idle[p.step][0]);
        p.remaining += p.pet.idle[p.step][1];
      }
    }
    window.requestAnimationFrame(tick);
  }

  function init() {
    var canvases = document.querySelectorAll('canvas[data-gajae-pet]');
    if (!canvases.length) return;
    Array.prototype.forEach.call(canvases, initCanvas);
    if (!players.length) return;
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        for (var e = 0; e < entries.length; e++) {
          for (var i = 0; i < players.length; i++) {
            if (players[i].canvas === entries[e].target) {
              players[i].visible = entries[e].isIntersecting;
            }
          }
        }
      }, { threshold: 0.05 });
      Array.prototype.forEach.call(canvases, function (c) { io.observe(c); });
    }
    window.requestAnimationFrame(tick);
  }

  init();
})();
