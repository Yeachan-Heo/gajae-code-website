/*
 * Gajae pets - verbatim data + renderer ported from gajae-code:
 *   packages/tui/src/components/gajae-pet.ts        (crab grids, RED/BLUE palettes,
 *                                                    GAJAE_IDLE_STEPS, PARA_PARA_STEPS, bursts)
 *   packages/tui/src/components/ouroboros-pet.ts    (idle, work enter/loop/exit, heart burst)
 *   packages/tui/src/components/ouroboros-pet-frames.json
 * Grids, palettes and every step duration are exact copies of the source
 * implementation, dumped straight from PET_SKINS rather than transcribed.
 */
(function () {
  'use strict';

  var CRAB_FRAMES = {
    "base": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGGVVGGK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "gazeL": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGGVGGVK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "gazeR": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KVGGVGGK.KK.","KRRKKVVVVVVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "flicker": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KVVVVVVK.KK.","KRRKKVGVVGVKKRRK","KRrRKRRRRRRKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "danceL": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.",".KK.KRRRRRRK....","KRRKKGVVVGVK.KK.","KRrRKVGVGVVKKRRK",".KRRKGVVVGVKRrRK","....KKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","...KRRRRRRK.....","..KRrK..KrRK....","..K......K......"],
    "danceR": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK.KK.",".KK.KVGVVGVKKRRK","KRRKKGVGGVGKRrRK","KRrRKVVVVVVKRRK.",".KRRKKRbbRKK....",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....",".....KRRRRRRK...","....KRrK..KrRK..","....K......K...."],
    "flex": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.",".KK.KRRRRRRK.KK.","KRRKKVGVVGVKKRRK","KRrRKGVGGVGKRrRK",".KRRKVVVVVVKRRK.","....KKRbbRKK....",".....KRbbRK.....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "cry1": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGVVVGVK.KK.","KRRKKVGVGVVKKRRK","KRrRKGVVVGVKRrRK",".KRRKKRbbRKKRRK.","....wKRbbRKw....",".....KRbbRK.....",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "cry2": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGVVVGVK.KK.","KRRKKVGVGVVKKRRK","KRrRKGVVVGVKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....","...w.KRbbRK.w...",".....KRRRRK.....","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."],
    "cry3": ["..A.........A...","...A..HHHH..A...","....AHHHHHHA....",".HHHHHHHHHHHHHH.",".hhhhhhhhhhhhhh.","....KRRRRRRK....",".KK.KGVVVGVK.KK.","KRRKKVGVGVVKKRRK","KRrRKGVVVGVKRrRK",".KRRKKRbbRKKRRK.",".....KRbbRK.....",".....KRbbRK.....","..w..KRRRRK..w..","....KRRRRRRK....","...KRrK..KrRK...","...K......K....."]
  };

  var OURO_FRAMES = {
    "idle": ["................","................",".....RRR........","....RRDRRR......","....RRRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "blink": ["................","................",".....RRR........","....RRRRRR......","....RRRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "tongue-1": ["................","................",".....RRR........","....RRDRRR......","....RRRRRRR.....","....ARRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "tongue-2": ["................","................",".....RRR........","....RRDRRR......","..A.RRRRRRR.....","...AARRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-1": ["................","................",".....RRR........","....RRwRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-2": ["................","........w.......","...w.RRR........","....RRRRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "cry-3": ["..........ww....","ww......w.......","...w.RRR........","....RRRRRR......","....RDRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "spin-1": ["................","..RR............",".RRGR......RRR..",".RRRRR....RrrR..","..RRRRR..RR..RR.",".....rRRRRr..RR.",".R....rRRr....RR","R......RR.....RR","Rr.....rR.....RR","Rr....RrRR....Rr","RRR..RRrrRR..RRr",".rR..Rr..rR..Rr.","..RRRr....rRRR..","..rrr......rrr..","................","................"],
    "spin-2": ["................","................","..RRR......RRR..","..RrrR....RrrR..",".RR..RR..RR..RR.","RRR..rRRRRr..RR.","RRR...rRRr....RR","RGR....RR.....RR","RR.....rR.....RR","......RrRR....Rr",".R...RRrrRR..RRr",".RR..Rr..rR..Rr.","..rRRr....rRRR..","...rr......rrr..","................","................"],
    "spin-3": ["................","................","..RRR......RRR..","..RrrR....RrrR..",".RR..RR..RR..RR.",".RR..rRRRRr..RR.","RR....rRRr....RR","RR.....rR.....RR","RR.....rR.....RR","RR....RrRR....Rr","rRR...r.rRR..RRr",".rRRR....rR..Rr.","..RRRRR...rRRR..","..RGRRR....rrr..","...RRR..........","................"],
    "spin-4": ["................","................","..RRR......RRR..","..RrrR....RrrR..",".RR..RR..R...RR.",".RR..rRR.....RR.","RR....rr......RR","RR.....RRR....RR","RR....RRGR....RR","rR....RRRR....Rr","rRR..RRRRrR..RRr",".rR..RrR.rr..Rr.","..RRRr....rRRR..","..rrr......rrr..","................","................"],
    "spin-5": ["...........RR...","..........RRRR..","..RRR.....RRGR..","..RrrR....RRRR..",".RR..RR..RRRR...",".RR..rRRRRr.....","RR....rRRr....R.","RR.....RR.....R.","RR.....Rr.....RR","rR....RRrR....Rr","rRR..RRrrRR..RRr",".rR..Rr..rR..Rr.","..RRRr....rRRR..","..rrr......rrr..","................","................"],
    "spin-6": ["................","................","..RRR......RRR..","..RrrR....RRRRR.",".RR..RR..RRrrRRR",".RR..rRRRRr..RRR","RR....rRRr...RRR","RR.....RR....RGR","RR.....Rr.....RR","rR....RRrR......","rRR..RRrrRR.....",".rR..Rr..rR...R.","..RRRr....rRRr..","..rrr......rr...","................","................"],
    "spin-7": ["................","................","..RRR......RRR..","..RrrR....RrrR..",".RR..RR..RR..RR.",".RR..rRRRRr..RR.","RR....rRRr....RR","RR.....Rr.....RR","RR.....Rr.....RR","rR....RRrR....RR","rRR..RRr.r...RRr",".rR..Rr....RRRr.","..RRRr...RRRRR..","..rrr....RRRGR..","..........RRR...","................"],
    "spin-8": ["................","................","..RRR......RRR..","..RrrR....RrrR..",".RR...R..RR..RR.",".RR.....RRr..RR.","RR......rr....RR","RR....RRR.....RR","RR....RGRR....RR","rR....RRRR....Rr","rRR..RrRRRR..RRr",".rR..rr.RrR..Rr.","..RRRr....rRRR..","..rrr......rrr..","................","................"],
    "enter-1": ["................","................","................",".RRRR...........",".RRGRRR.........",".rrRRRRR........","..rRRRRR........","....RRrRRR......","...R..RRRRRR....","..RR..rrRRRR....","..RRR.RRRRRR....","..rRRRRRRR......","...RRRRR........","....rr..........","................","................"],
    "enter-2": ["................","..RR............",".RRDR......RRR..",".RRRRR....RrrR..","..RRRRR..RR..RR.",".....rRRRRr..RR.",".R....rRRr....RR","R......RR.....RR","Rr.....rR.....RR","Rr....RrRR....Rr","RRR..RRrrRR..RRr",".rR..Rr..rR..Rr.","..RRRr....rRRR..","..rrr......rrr..","................","................"],
    "heart-turn-0": ["................","................",".....RRR........","....RRGRRR......","....RRRRRRR.....",".....RRRrRRR....",".........rRRR...","..........rRR...",".....R.....RRR..","....RR.....RRR..","...RR..RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "heart-turn-1": ["................","......RRR.......","....RRRRRRR.....","...RRRRrrRRR....","..RRGRr..rRRR...","..RRRR....RRRR..","...RR......RRR..","............RRR.","....R.......RRR.","...R........RRr.","..RR...RR..RRR..","..rRRRRRRRRRRr..","...rRRrRrRRRr...","....rr...rrr....","................","................"],
    "heart-turn-3": ["................",".....RRRRR......","...RRRRRRRRR....","..RRRrrrrrRRR...",".RRRr.....rRRR..","RRRR.......rRRR.","RGRR........rRR.","RRRR.........RR.",".RR..........RR.","............RRR.",".R.........RRRr.","..RR......RRRr..","...RRRRRRRRRR...","....rRRRRRRr....",".....rrrrrr.....","................"],
    "heart-turn-4": ["................","......RRRRR.....","....RRRRRRRR....","...RRrRrrRrRR...","..RRrr......RR..",".RRrr.......RRr.",".Rrr........RRr.","RRR.........RRR.","RRR.........RRR.",".RRR........RRr.",".RRRR......RRRr.","RRGR......RRRr..",".RRRR....RRRr...",".......RRRRr....",".....RRRRrr.....","................"],
    "heart-turn-5": ["................",".....RRRRRr.....","....RRRRRRRr....","...RRRr..RRRR...","..RRRr....RRRr..","..RRr......RRRr.",".RRr........RRr.",".RRr........RRr.",".RRr........RRr.",".RRr........RRr.",".RRr........RRr.","..RRr.......Rr..","..RRRRRR...RR...","...RRRRRR..R....","....RRGRR.R.....",".....RRR........"],
    "heart-turn-6": ["................",".....RRRrR......","....RRRRRRRrr...","..RRRR.RRRRRr...","..RRr....R.RRr..","..RR.......RRrr.",".RRRr.......RRr.",".RRr........RRR.",".RRr.........Rr.",".RRr.........RR.",".RRRr........R..","..RRr........R..","...RRrr.RRRR.R..","...RRRRRRRRR....",".....RRRRGRR....","........RRR....."],
    "heart-turn-10": ["................",".....rrRRrr.....","....RRRRRRRr....","...RRRRRRRRRr...","..RR......RRRr..",".RRr.......RRRr.",".RRR........RRr.",".RRr.........RR.",".RRr.........RR.",".RRR..........R.","..Rrr.........R.","..RRrr....R.R...","...RRrr..RRRR...","....RRrRRRRGR...",".....RRRRRRRR...",".......RR..R...."],
    "heart-turn-11": ["................","................","....RRR...RR....","...RRRRRRRRRR...","..RRRrrRRrrrRR..","..RRr..rr...rR..",".RRR.........R..",".RR.........A.A.",".RRR.........A..",".rRRR......RR...","..rRRR....RRRR..","...rRRR..RRGRR..","....rRRRRRRRRr..",".....rRRRRRrr...","......rrrrr.....","................"],
    "heart": ["................","................","....rrr...rr....","...rRRRrRrRRr...","..rRRRRRRRRRRr..","..RRR..RR..RR...","..RRR.....RR....","..RRR.....R.....","...RRr..........","...RRRr.........","....RRRrRRR.....",".....RRRRRRR....","......RRRGRR....","........RRR.....","................","................"],
    "heart-accent": ["................","................","....rrr...rr....","...rRRRrRrRRr...","..rRRRRRRRRRRr..","..RRR..RR..RR...","..RRR.....RR....","..RRR.....R.....","...RRr......A.A.","...RRRr......A..","....RRRrRRR.....",".....RRRRRRR....","......RRRDRR....","........RRR.....","................","................"]
  };

  var PETS = {
    red: { label: "RedGajae", description: "The Red Crab, who likes to work-out.", palette: {"K":[74,20,8],"R":[229,72,46],"r":[255,122,82],"V":[14,22,14],"G":[61,245,146],"H":[232,180,90],"h":[169,117,47],"b":[216,154,74],"A":[196,60,30],"w":[200,230,255]}, frames: CRAB_FRAMES, baseFrame: "base", idle: [["base",1100],["gazeL",350],["base",500],["gazeR",350],["base",800],["flicker",150]], work: [["danceL",300],["danceR",300],["base",260],["flex",480],["base",260]], workEnter: [], workExit: [], burst: {"intro":[["danceL",300],["danceR",300],["base",260],["flex",480],["base",260]],"tail":{"frames":["flex","base"],"stepMs":200,"ms":1000}}, poses: {"idle":"base","work":"danceL","signature":"flex"} },
    blue: { label: "BlueGajae", description: "The Blue Crab, who wants to rest.", palette: {"K":[7,38,74],"R":[47,155,255],"r":[94,200,255],"V":[14,22,14],"G":[61,245,146],"H":[232,180,90],"h":[169,117,47],"b":[125,211,252],"A":[37,120,200],"w":[230,247,255]}, frames: CRAB_FRAMES, baseFrame: "base", idle: [["base",1100],["gazeL",350],["base",500],["gazeR",350],["base",800],["flicker",150]], work: [["danceL",300],["danceR",300],["base",260],["flex",480],["base",260]], workEnter: [], workExit: [], burst: {"intro":[["danceL",300],["danceR",300],["base",260],["flex",480],["base",260]],"tail":{"frames":["cry1","cry2","cry3"],"stepMs":110,"ms":990}}, poses: {"idle":"base","work":"danceL","signature":"cry3"} },
    ouroboros: { label: "Ouroboros", description: "The little snake who keeps going.", palette: {"D":[20,100,48],"R":[174,232,14],"r":[112,146,190],"G":[255,231,134],"A":[255,137,180],"w":[190,231,255]}, frames: OURO_FRAMES, baseFrame: "idle", idle: [["idle",1400],["blink",120],["idle",500],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",1600],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",2200],["blink",120],["idle",900],["tongue-1",110],["tongue-2",150],["tongue-1",90],["idle",1800],["cry-1",180],["cry-2",180],["cry-3",320],["cry-2",180],["cry-3",320],["cry-2",180],["cry-3",420],["idle",1600]], work: [["spin-1",220],["spin-2",220],["spin-3",220],["spin-4",220],["spin-5",220],["spin-6",220],["spin-7",220],["spin-8",220]], workEnter: [["enter-1",120],["enter-2",120]], workExit: [["enter-2",110],["enter-1",120],["idle",160]], burst: {"intro":[["heart-turn-0",100],["heart-turn-1",110],["heart-turn-3",110],["heart-turn-4",110],["heart-turn-5",110],["heart-turn-6",110],["heart-turn-10",110],["heart-turn-11",110],["heart",300],["heart-accent",160],["heart",110],["heart-accent",160],["heart",350],["heart-turn-11",100],["heart-turn-10",100],["heart-turn-6",100],["heart-turn-5",100],["heart-turn-4",100],["heart-turn-3",100],["heart-turn-1",100],["heart-turn-0",100],["idle",500]]}, poses: {"idle":"idle","work":"spin-1","signature":"heart"} }
  };
  /* Each theme slot is paired with the pet skin that shares its palette. */
  var THEME_SKIN = { 'red-claw': 'red', 'blue-crab': 'blue', 'ouroboros': 'ouroboros' };
  var DEFAULT_SKIN = 'red';
  var WORK_CYCLES = 3;
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

  function pushSteps(target, steps) {
    for (var i = 0; i < steps.length; i++) target.push(steps[i]);
  }

  /* Signature burst: authored intro beats, then the looping tail cycled every
     stepMs until its total ms is spent (the shape petBurstFrame walks). */
  function burstTimeline(pet) {
    var steps = [];
    pushSteps(steps, pet.burst.intro);
    var tail = pet.burst.tail;
    if (tail) {
      var elapsed = 0;
      var index = 0;
      while (elapsed < tail.ms) {
        var step = Math.min(tail.stepMs, tail.ms - elapsed);
        steps.push([tail.frames[index % tail.frames.length], step]);
        elapsed += step;
        index++;
      }
    }
    return steps;
  }

  /* Work run: the authored enter transition, a few loop cycles, then the exit. */
  function workTimeline(pet) {
    var steps = [];
    pushSteps(steps, pet.workEnter);
    for (var c = 0; c < WORK_CYCLES; c++) pushSteps(steps, pet.work);
    pushSteps(steps, pet.workExit);
    return steps;
  }

  function timelineFor(pet, mode) {
    if (mode === 'work') return workTimeline(pet);
    if (mode === 'signature') return burstTimeline(pet);
    return [];
  }

  var players = [];

  function playerFor(canvas) {
    for (var i = 0; i < players.length; i++) {
      if (players[i].canvas === canvas) return players[i];
    }
    return null;
  }

  function resumeIdle(player) {
    player.queue = null;
    player.step = 0;
    player.remaining = player.pet.idle[0][1];
    drawFrame(player.canvas, player.pet, player.pet.idle[0][0]);
  }

  function setSkin(player, skinId) {
    var pet = PETS[skinId];
    if (!pet || player.pet === pet) return false;
    player.pet = pet;
    resumeIdle(player);
    return true;
  }

  /* Play one animation family. Under reduced motion each family still shows a
     representative authored pose instead of moving. */
  function playMode(player, mode) {
    if (!player) return;
    if (mode === 'idle') {
      resumeIdle(player);
      return;
    }
    if (REDUCED) {
      drawFrame(player.canvas, player.pet, player.pet.poses[mode] || player.pet.baseFrame);
      return;
    }
    var steps = timelineFor(player.pet, mode);
    if (!steps.length) {
      resumeIdle(player);
      return;
    }
    player.queue = steps;
    player.queueIndex = 0;
    player.remaining = steps[0][1];
    drawFrame(player.canvas, player.pet, steps[0][0]);
  }

  function initCanvas(canvas) {
    var pet = PETS[canvas.getAttribute('data-gajae-pet')];
    if (!pet) return;
    canvas.width = CELL;
    canvas.height = CELL;
    drawFrame(canvas, pet, pet.idle[0][0]);
    players.push({
      canvas: canvas,
      pet: pet,
      step: 0,
      remaining: pet.idle[0][1],
      visible: true,
      queue: null,
      queueIndex: 0,
      followTheme: canvas.hasAttribute('data-gajae-pet-follow-theme')
    });
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
      if (p.queue) {
        while (p.remaining <= 0) {
          p.queueIndex++;
          if (p.queueIndex >= p.queue.length) {
            resumeIdle(p);
            break;
          }
          drawFrame(p.canvas, p.pet, p.queue[p.queueIndex][0]);
          p.remaining += p.queue[p.queueIndex][1];
        }
        continue;
      }
      while (p.remaining <= 0) {
        p.step = (p.step + 1) % p.pet.idle.length;
        drawFrame(p.canvas, p.pet, p.pet.idle[p.step][0]);
        p.remaining += p.pet.idle[p.step][1];
      }
    }
    window.requestAnimationFrame(tick);
  }

  /* Theme-following pets (the hero companion) swap to the skin paired with the
     active slot and celebrate the change with their signature pose. */
  function syncThemedPets(withBurst) {
    var theme = document.documentElement.getAttribute('data-site-theme');
    var skin = THEME_SKIN[theme] || DEFAULT_SKIN;
    for (var i = 0; i < players.length; i++) {
      if (!players[i].followTheme) continue;
      if (setSkin(players[i], skin) && withBurst && !players[i].brand) {
        playMode(players[i], 'signature');
      }
    }
    updateFavicon(PETS[skin]);
  }

  /* The favicon is the active pet, nearest-neighbour scaled so the 16x16 art
     stays crisp. The emoji-SVG icon in the markup remains the no-JS fallback. */
  function updateFavicon(pet) {
    var link = document.querySelector('link[rel="icon"]');
    if (!link || !pet) return;
    var source = document.createElement('canvas');
    source.width = CELL;
    source.height = CELL;
    drawFrame(source, pet, pet.baseFrame);
    var out = document.createElement('canvas');
    out.width = 64;
    out.height = 64;
    var ctx = out.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;
    ctx.msImageSmoothingEnabled = false;
    ctx.drawImage(source, 0, 0, out.width, out.height);
    try {
      link.setAttribute('href', out.toDataURL('image/png'));
    } catch (e) { /* tainted canvas or data-URL policy: keep the emoji icon. */ }
  }

  /* Brand marks ship an emoji so they work without JS; upgrade them in place. */
  function upgradeBrandMarks() {
    var marks = document.querySelectorAll('[data-gajae-brand]');
    Array.prototype.forEach.call(marks, function (mark) {
      var canvas = document.createElement('canvas');
      canvas.className = 'brand-pet';
      canvas.setAttribute('data-gajae-pet', DEFAULT_SKIN);
      canvas.setAttribute('data-gajae-pet-follow-theme', '');
      mark.textContent = '';
      mark.appendChild(canvas);
      initCanvas(canvas);
      var player = playerFor(canvas);
      if (player) player.brand = true;
    });
  }

  function cardPlayer(card) {
    return playerFor(card.querySelector('canvas[data-gajae-pet]'));
  }

  function initPetInteraction() {
    document.addEventListener('click', function (event) {
      var node = event.target;
      if (!node || !node.closest) return;
      var control = node.closest('[data-pet-anim]');
      if (control) {
        var owner = control.closest('.pet-card');
        if (owner) playMode(cardPlayer(owner), control.getAttribute('data-pet-anim'));
        return;
      }
      var card = node.closest('.pet-card');
      if (card) playMode(cardPlayer(card), 'signature');
    });
    if (window.MutationObserver) {
      new window.MutationObserver(function () { syncThemedPets(true); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['data-site-theme'] });
    }
  }

  function init() {
    upgradeBrandMarks();
    var canvases = document.querySelectorAll('canvas[data-gajae-pet]');
    if (!canvases.length) return;
    Array.prototype.forEach.call(canvases, function (canvas) {
      if (!playerFor(canvas)) initCanvas(canvas);
    });
    if (!players.length) return;
    syncThemedPets(false);
    initPetInteraction();
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        for (var e = 0; e < entries.length; e++) {
          var player = playerFor(entries[e].target);
          if (player) player.visible = entries[e].isIntersecting;
        }
      }, { threshold: 0.05 });
      Array.prototype.forEach.call(canvases, function (c) { io.observe(c); });
    }
    if (!REDUCED) window.requestAnimationFrame(tick);
  }

  init();
})();
