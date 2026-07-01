(() => {
  'use strict';

  const canvas = document.getElementById('game');
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;

  const TILE = 16;
  const GRAVITY = 0.42;
  const MAX_FALL = 7.5;
  const JUMP_VEL = -7.2;
  const RUN_SPEED = 2.1;
  const WORLD_W = 100;
  const WORLD_H = 12;

  function row(chars) {
    if (chars.length > WORLD_W) return chars.slice(0, WORLD_W);
    return chars.padEnd(WORLD_W, '.');
  }

  const LEVEL = [
    row(''),
    row(''),
    row(''),
    row(''),
    row(''),
    row(''),
    row('....................???.................????.................???..............'),
    row('...................B?B.................B??B.................B?B.............'),
    row('...........???....................PPPP....................???...............'),
    row('..........B???....................pppp...................B???..............'),
    row('..........................PPpp...............................F.hHH.........'),
    row('SSSSSSSSSSS....SSSSSSSSSSSSS...SSSSSSSSSSSSSSS...SSSSSSSSSSSSSSSSSSSSSSSSSSS'),
  ];

  const ENEMY_SPOTS = [
    [14, 10], [24, 10], [38, 10], [48, 10], [58, 10], [68, 10], [78, 10], [86, 10],
  ];

  const BONE_SPOTS = [
    [6, 9], [18, 7], [30, 6], [42, 5], [55, 7], [63, 5], [72, 6], [81, 4], [90, 7],
  ];

  const BLOCK_MARKS = {
    '?': 'question',
    'B': 'brick',
    'P': 'pipeTop',
    'p': 'pipeBody',
    'f': 'flagCloth',
    'F': 'flagPole',
    'h': 'doghouseRoof',
    'H': 'doghouseWall',
  };

  const STATE = { TITLE: 0, PLAY: 1, DEAD: 2, WIN: 3, GAMEOVER: 4 };

  let gameState = STATE.TITLE;
  let cameraX = 0;
  let score = 0;
  let lives = 3;
  let timeLeft = 300;
  let frame = 0;
  let levelEndX = 0;
  let particles = [];
  let floatTexts = [];
  let blocks = [];
  let enemies = [];
  let bones = [];
  let powerups = [];
  let flag = null;
  let doghouse = null;

  const keys = {};
  let jumpHeld = false;
  let jumpQueued = false;

  const player = {
    x: 2 * TILE,
    y: 8 * TILE,
    w: 14,
    h: 14,
    vx: 0,
    vy: 0,
    onGround: false,
    facing: 1,
    anim: 0,
    big: false,
    invuln: 0,
    dead: false,
    deadTimer: 0,
    winAnim: false,
  };

  const audioCtx = typeof AudioContext !== 'undefined' ? new AudioContext() : null;

  function beep(freq, dur, type = 'square', vol = 0.08) {
    if (!audioCtx) return;
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.value = vol;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + dur);
    osc.stop(audioCtx.currentTime + dur);
  }

  function sfxJump() { beep(280, 0.12, 'square', 0.06); }
  function sfxCoin() { beep(880, 0.08); setTimeout(() => beep(1100, 0.1), 60); }
  function sfxStomp() { beep(180, 0.1, 'triangle', 0.1); }
  function sfxBreak() { beep(120, 0.08, 'sawtooth', 0.07); }
  function sfxPower() { [440, 554, 659, 880].forEach((f, i) => setTimeout(() => beep(f, 0.1), i * 80)); }
  function sfxDie() { beep(300, 0.2); setTimeout(() => beep(200, 0.3), 150); setTimeout(() => beep(120, 0.4), 350); }
  function sfxWin() { [523, 659, 784, 1047].forEach((f, i) => setTimeout(() => beep(f, 0.15), i * 120)); }

  function tileAt(tx, ty) {
    if (tx < 0 || ty < 0 || tx >= WORLD_W || ty >= WORLD_H) return ty >= WORLD_H ? 'S' : '.';
    return LEVEL[ty][tx] || '.';
  }

  function isSolid(ch) {
    return ch === 'S' || ch === 's' || ch === '?' || ch === 'B' || ch === 'P' || ch === 'p' ||
           ch === 'f' || ch === 'F' || ch === 'h' || ch === 'H';
  }

  function resetLevel() {
    blocks = [];
    enemies = [];
    bones = [];
    powerups = [];
    particles = [];
    floatTexts = [];
    flag = null;
    doghouse = null;

    for (let y = 0; y < WORLD_H; y++) {
      for (let x = 0; x < WORLD_W; x++) {
        const ch = LEVEL[y][x];
        if (BLOCK_MARKS[ch]) {
          blocks.push({
            x: x * TILE,
            y: y * TILE,
            type: BLOCK_MARKS[ch],
            hit: false,
            bounce: 0,
            contents: ch === '?' ? (x === 22 || x === 66 ? 'steak' : 'bone') : null,
          });
        }
        if (ch === 'F') flag = { x: x * TILE, y: y * TILE, slide: 0 };
        if (ch === 'H') doghouse = { x: x * TILE - TILE * 2, y: y * TILE - TILE };
      }
    }

    ENEMY_SPOTS.forEach(([x, y]) => {
      enemies.push({
        x: x * TILE,
        y: y * TILE - 12,
        w: 14,
        h: 12,
        vx: -0.7,
        alive: true,
        squished: false,
        squishTimer: 0,
        anim: 0,
      });
    });

    BONE_SPOTS.forEach(([x, y]) => {
      bones.push({ x: x * TILE + 4, y: y * TILE + 2, w: 8, h: 8, collected: false, bob: Math.random() * Math.PI * 2 });
    });

    levelEndX = (WORLD_W - 4) * TILE;
    player.x = 2 * TILE;
    player.y = 8 * TILE;
    player.vx = 0;
    player.vy = 0;
    player.onGround = false;
    player.facing = 1;
    player.big = false;
    player.invuln = 0;
    player.dead = false;
    player.deadTimer = 0;
    player.winAnim = false;
    player.h = 14;
    player.w = 14;
    cameraX = 0;
    timeLeft = 300;
    jumpHeld = false;
    jumpQueued = false;
  }

  function startGame() {
    score = 0;
    lives = 3;
    resetLevel();
    gameState = STATE.PLAY;
  }

  function spawnParticle(x, y, color, count = 4) {
    for (let i = 0; i < count; i++) {
      particles.push({
        x, y,
        vx: (Math.random() - 0.5) * 3,
        vy: (Math.random() - 0.5) * 3 - 1,
        life: 30 + Math.random() * 20,
        color,
        size: 2 + Math.random() * 2,
      });
    }
  }

  function floatText(x, y, text, color = '#fff') {
    floatTexts.push({ x, y, text, color, life: 45 });
  }

  function rectsOverlap(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
  }

  function getCollidables() {
    const list = [];
    blocks.forEach((b) => {
      if (!b.hit || b.type === 'pipeTop' || b.type === 'pipeBody' || b.type === 'flagPole' || b.type === 'doghouseWall' || b.type === 'doghouseRoof') {
        list.push({ x: b.x, y: b.y, w: TILE, h: TILE, block: b });
      }
    });
    for (let y = 0; y < WORLD_H; y++) {
      for (let x = 0; x < WORLD_W; x++) {
        const ch = LEVEL[y][x];
        if ((ch === 'S' || ch === 's') && !BLOCK_MARKS[ch]) {
          list.push({ x: x * TILE, y: y * TILE, w: TILE, h: TILE });
        }
      }
    }
    return list;
  }

  function moveEntity(ent, dx, dy) {
    ent.x += dx;
    let collidables = getCollidables();
    for (const c of collidables) {
      if (rectsOverlap(ent, c)) {
        if (dx > 0) ent.x = c.x - ent.w;
        else if (dx < 0) ent.x = c.x + c.w;
      }
    }
    ent.y += dy;
    ent.onGround = false;
    collidables = getCollidables();
    for (const c of collidables) {
      if (rectsOverlap(ent, c)) {
        if (dy > 0) {
          ent.y = c.y - ent.h;
          ent.onGround = true;
          ent.vy = 0;
        } else if (dy < 0) {
          ent.y = c.y + c.h;
          ent.vy = 0;
          if (c.block && (c.block.type === 'question' || c.block.type === 'brick')) {
            hitBlock(c.block, ent);
          }
        }
      }
    }
  }

  function hitBlock(block, ent) {
    if (block.bounce > 0) return;
    if (block.type === 'brick') {
      if (player.big) {
        block.hit = true;
        spawnParticle(block.x + 8, block.y + 8, '#c84c0c', 6);
        sfxBreak();
        score += 50;
        floatText(block.x, block.y - 8, '+50');
      }
      block.bounce = 8;
    } else if (block.type === 'question' && !block.used) {
      block.used = true;
      block.bounce = 8;
      if (block.contents === 'steak') {
        const emergeY = block.y - TILE;
        powerups.push({
          x: block.x + 2,
          y: block.y + 2,
          emergeY,
          w: 12,
          h: 10,
          vy: -1.4,
          vx: 1.2,
          emerged: false,
          type: 'steak',
        });
      } else {
        score += 100;
        sfxCoin();
        floatText(block.x, block.y - 8, '+100', '#ffe066');
        spawnParticle(block.x + 8, block.y, '#f8d878', 5);
      }
      setTimeout(() => { block.type = 'used'; }, 200);
    }
  }

  function updatePlayer() {
    if (player.dead) {
      player.deadTimer++;
      player.vy += GRAVITY;
      player.y += player.vy;
      if (player.deadTimer > 90) {
        lives--;
        if (lives <= 0) {
          gameState = STATE.GAMEOVER;
        } else {
          resetLevel();
          gameState = STATE.PLAY;
        }
      }
      return;
    }

    if (player.winAnim) {
      player.x += 1.2;
      if (frame % 8 === 0) sfxCoin();
      if (player.x > levelEndX) gameState = STATE.WIN;
      return;
    }

    let move = 0;
    if (keys.ArrowLeft || keys.KeyA) move -= 1;
    if (keys.ArrowRight || keys.KeyD) move += 1;

    if (move !== 0) {
      player.facing = move;
      player.vx = move * RUN_SPEED;
      player.anim += 0.25;
    } else {
      player.vx *= 0.72;
      if (Math.abs(player.vx) < 0.05) player.vx = 0;
      player.anim = 0;
    }

    if ((keys.Space || keys.KeyZ) && !jumpHeld) jumpQueued = true;
    jumpHeld = keys.Space || keys.KeyZ;

    if (jumpQueued && player.onGround) {
      player.vy = JUMP_VEL;
      player.onGround = false;
      jumpQueued = false;
      sfxJump();
    }

    if (!keys.Space && !keys.KeyZ && player.vy < -2) {
      player.vy *= 0.65;
    }

    player.vy += GRAVITY;
    if (player.vy > MAX_FALL) player.vy = MAX_FALL;

    moveEntity(player, player.vx, player.vy);

    if (player.y > WORLD_H * TILE + 32) {
      killPlayer();
    }

    if (player.invuln > 0) player.invuln--;

    if (flag && player.x + player.w > flag.x + 4 && !player.winAnim) {
      player.winAnim = true;
      player.vx = 0;
      sfxWin();
    }

    cameraX = Math.max(0, Math.min(player.x - 80, levelEndX - 160));
  }

  function killPlayer() {
    if (player.invuln > 0 || player.dead) return;
    if (player.big) {
      player.big = false;
      player.h = 14;
      player.invuln = 90;
      sfxDie();
      return;
    }
    player.dead = true;
    player.vy = -5;
    sfxDie();
  }

  function updateEnemies() {
    enemies.forEach((e) => {
      if (!e.alive) return;
      if (e.squished) {
        e.squishTimer++;
        if (e.squishTimer > 30) e.alive = false;
        return;
      }
      e.anim += 0.15;
      e.x += e.vx;
      const ent = { x: e.x, y: e.y, w: e.w, h: e.h };
      let hitWall = false;
      for (const c of getCollidables()) {
        if (rectsOverlap(ent, c)) {
          e.vx *= -1;
          hitWall = true;
          if (e.vx > 0) e.x = c.x - e.w;
          else e.x = c.x + c.w;
        }
      }
      if (!hitWall && Math.random() < 0.005) e.vx *= -1;

      if (rectsOverlap(player, e)) {
        if (player.vy > 0 && player.y + player.h - 6 < e.y + 4) {
          e.squished = true;
          e.h = 4;
          player.vy = -4.5;
          score += 200;
          sfxStomp();
          floatText(e.x, e.y - 10, '+200', '#7fff7f');
          spawnParticle(e.x + 7, e.y, '#ff9966', 4);
        } else if (player.invuln <= 0 && !player.dead) {
          killPlayer();
        }
      }
    });
  }

  function updateBones() {
    bones.forEach((b) => {
      if (b.collected) return;
      b.bob += 0.08;
      const box = { x: b.x, y: b.y + Math.sin(b.bob) * 2, w: b.w, h: b.h };
      if (rectsOverlap(player, box)) {
        b.collected = true;
        score += 100;
        sfxCoin();
        floatText(b.x, b.y - 8, '+100', '#ffe066');
      }
    });
  }

  function updatePowerups() {
    powerups.forEach((p, i) => {
      if (!p.emerged) {
        p.y += p.vy;
        if (p.y <= p.emergeY) {
          p.y = p.emergeY;
          p.emerged = true;
          p.vx = 1.2;
        }
      } else {
        p.x += p.vx;
        p.vy += GRAVITY;
        p.y += p.vy;
        const ent = { x: p.x, y: p.y, w: p.w, h: p.h };
        for (const c of getCollidables()) {
          if (rectsOverlap(ent, c)) {
            if (p.vy > 0) { p.y = c.y - p.h; p.vy = 0; }
            else p.vy = 0;
          }
        }
        if (rectsOverlap(player, p)) {
          player.big = true;
          player.h = 22;
          score += 500;
          sfxPower();
          floatText(p.x, p.y - 10, 'STEAK!', '#ff9966');
          powerups.splice(i, 1);
        }
      }
    });
  }

  function updateBlocks() {
    blocks.forEach((b) => {
      if (b.bounce > 0) b.bounce--;
    });
    if (flag) flag.slide = Math.min(flag.slide + 0.4, TILE * 3);
  }

  function updateParticles() {
    particles = particles.filter((p) => {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.15;
      p.life--;
      return p.life > 0;
    });
    floatTexts = floatTexts.filter((t) => {
      t.y -= 0.6;
      t.life--;
      return t.life > 0;
    });
  }

  function update() {
    frame++;
    if (gameState === STATE.PLAY) {
      if (frame % 60 === 0) {
        timeLeft--;
        if (timeLeft <= 0) killPlayer();
      }
      updatePlayer();
      updateEnemies();
      updateBones();
      updatePowerups();
      updateBlocks();
      updateParticles();
    }
  }

  function drawPixel(x, y, color) {
    if (!color) return;
    ctx.fillStyle = color;
    ctx.fillRect(Math.floor(x - cameraX), Math.floor(y), 1, 1);
  }

  function drawRect(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.floor(x - cameraX), Math.floor(y), w, h);
  }

  function drawSky() {
    const grad = ctx.createLinearGradient(0, 0, 0, 180);
    grad.addColorStop(0, '#5c94fc');
    grad.addColorStop(0.55, '#7eb8ff');
    grad.addColorStop(1, '#b8e0ff');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 320, 180);

  }

  function drawCloud(cx, cy, scale) {
    const x = cx - cameraX * 0.3;
    drawRect(x, cy, 16 * scale, 6 * scale, '#fff');
    drawRect(x + 4 * scale, cy - 4 * scale, 12 * scale, 6 * scale, '#fff');
    drawRect(x + 10 * scale, cy - 2 * scale, 10 * scale, 5 * scale, '#f8f8ff');
  }

  function drawBackground() {
    drawSky();
    drawCloud(40, 28, 1);
    drawCloud(120, 40, 0.8);
    drawCloud(200, 22, 1.1);
    drawCloud(280, 36, 0.7);

    for (let x = 0; x < WORLD_W; x++) {
      const tx = x * TILE - (cameraX * 0.2) % (TILE * 2);
      drawRect(tx, 148, TILE, 32, '#5cad3a');
      drawRect(tx, 156, TILE, 4, '#4a9a2e');
    }
  }

  function drawTiles() {
    const startX = Math.floor(cameraX / TILE);
    const endX = startX + 22;
    for (let y = 0; y < WORLD_H; y++) {
      for (let x = startX; x <= endX; x++) {
        const ch = tileAt(x, y);
        const px = x * TILE;
        const py = y * TILE;
        if (ch === 'S' || ch === 's') {
          drawRect(px, py, TILE, TILE, ch === 'S' ? '#c84c0c' : '#5cad3a');
          if (ch === 'S') {
            drawRect(px, py, TILE, 3, '#e86830');
            drawRect(px, py + 3, TILE, 2, '#a33a08');
            drawRect(px + 2, py + 7, 4, 2, '#7a2a06');
            drawRect(px + 10, py + 10, 3, 2, '#7a2a06');
          } else {
            drawRect(px, py + 12, TILE, 4, '#4a9a2e');
          }
        }
      }
    }
  }

  function drawBlock(b) {
    const by = b.y + (b.bounce > 4 ? -2 : b.bounce > 0 ? -1 : 0);
    const x = b.x;
    const y = by;
    switch (b.type) {
      case 'question':
        drawRect(x, y, TILE, TILE, '#f0b030');
        drawRect(x + 1, y + 1, TILE - 2, TILE - 2, '#ffc848');
        ctx.fillStyle = '#8b5a14';
        ctx.font = '8px monospace';
        ctx.fillText('?', x + 5 - cameraX, y + 12);
        break;
      case 'used':
        drawRect(x, y, TILE, TILE, '#8b6914');
        drawRect(x + 1, y + 1, TILE - 2, TILE - 2, '#6b5010');
        break;
      case 'brick':
        if (!b.hit) {
          drawRect(x, y, TILE, TILE, '#c84c0c');
          drawRect(x, y, TILE, 2, '#e86830');
          drawRect(x, y + 7, TILE, 2, '#7a2a06');
          drawRect(x + 7, y, 2, TILE, '#7a2a06');
        }
        break;
      case 'pipeTop':
        drawRect(x, y, TILE, TILE, '#2d8a38');
        drawRect(x - 2, y, TILE + 4, 4, '#3cb04a');
        drawRect(x + 2, y + 4, TILE - 4, TILE - 4, '#1f6b28');
        break;
      case 'pipeBody':
        drawRect(x, y, TILE, TILE, '#1f6b28');
        drawRect(x + 2, y, 2, TILE, '#2d8a38');
        drawRect(x + 12, y, 2, TILE, '#174f20');
        break;
      case 'flagPole':
        drawRect(x + 7, y, 2, TILE, '#f0f0f0');
        if (flag) {
          const fh = flag.slide;
          drawRect(x + 9, y + TILE - fh, 14, fh, '#e85d75');
          drawRect(x + 9, y + TILE - fh, 14, 3, '#ff8fa8');
        }
        break;
      case 'doghouseRoof':
        drawRect(x, y, TILE * 3, TILE, '#c43d58');
        drawRect(x + 4, y - 4, TILE * 3 - 8, 6, '#e85d75');
        ctx.fillStyle = '#fff';
        ctx.font = '6px monospace';
        ctx.fillText('HOME', x + 10 - cameraX, y + 10);
        break;
      case 'doghouseWall':
        drawRect(x, y, TILE, TILE, '#f5e6c8');
        drawRect(x + 2, y + 4, 8, 10, '#3d2914');
        break;
      default:
        break;
    }
  }

  function drawBone(b) {
    if (b.collected) return;
    const bob = Math.sin(b.bob) * 2;
    const x = b.x;
    const y = b.y + bob;
    drawRect(x + 2, y + 3, 4, 2, '#fff8e8');
    drawRect(x, y + 2, 3, 4, '#fff8e8');
    drawRect(x + 5, y + 2, 3, 4, '#fff8e8');
    drawRect(x + 1, y + 1, 2, 2, '#f0e0c8');
    drawRect(x + 5, y + 1, 2, 2, '#f0e0c8');
  }

  function drawSteak(p) {
    drawRect(p.x, p.y, p.w, p.h, '#c43d58');
    drawRect(p.x + 2, p.y + 2, p.w - 4, p.h - 5, '#ff9966');
    drawRect(p.x + 4, p.y + 4, 3, 2, '#ffe0cc');
  }

  function drawCat(e) {
    if (!e.alive) return;
    const x = e.x;
    const y = e.y;
    const wiggle = e.squished ? 0 : Math.sin(e.anim) * 1;
    if (e.squished) {
      drawRect(x, y + 8, e.w, 4, '#ff7744');
      return;
    }
    drawRect(x + 2, y + 4 + wiggle, 10, 7, '#ff9966');
    drawRect(x + 1, y + 1 + wiggle, 4, 4, '#ff9966');
    drawRect(x + 9, y + 1 + wiggle, 4, 4, '#ff9966');
    drawRect(x + 2, y + 2 + wiggle, 2, 2, '#ffb088');
    drawRect(x + 10, y + 2 + wiggle, 2, 2, '#ffb088');
    drawRect(x + 4, y + 6 + wiggle, 6, 4, '#ffe0cc');
    drawRect(x + 5, y + 7 + wiggle, 1, 1, '#1a1a1a');
    drawRect(x + 8, y + 7 + wiggle, 1, 1, '#1a1a1a');
    drawRect(x + 6, y + 9 + wiggle, 2, 1, '#e85d75');
    drawRect(x + 1, y + 10 + wiggle, 3, 2, '#ff9966');
    drawRect(x + 10, y + 10 + wiggle, 3, 2, '#ff9966');
    const eyeX = e.vx < 0 ? 5 : 8;
    drawRect(x + eyeX, y + 5 + wiggle, 1, 2, '#1a1a1a');
  }

  function drawFrenchie() {
    const x = player.x;
    const y = player.y;
    const h = player.h;
    const big = player.big;
    const blink = player.invuln > 0 && Math.floor(frame / 4) % 2 === 0;
    if (blink) return;

    const bodyColor = '#d4a574';
    const maskColor = '#3d2914';
    const chestColor = '#f5e6d3';
    const wiggle = player.onGround && Math.abs(player.vx) > 0.3 ? Math.sin(player.anim) * 1.5 : 0;

    if (big) {
      drawRect(x, y + 8, 14, 14, bodyColor);
      drawRect(x + 1, y + 14, 4, 4, maskColor);
      drawRect(x + 9, y + 14, 4, 4, maskColor);
      drawRect(x + 3, y + 10, 8, 6, chestColor);
    }

    const headY = big ? y + 2 : y;
    const earOffset = player.facing;

    drawRect(x + 1, headY + 1 + wiggle, 4, 5, bodyColor);
    drawRect(x + 9, headY + 1 + wiggle, 4, 5, bodyColor);
    drawRect(x + 2, headY + 2 + wiggle, 2, 2, '#ffb6c1');
    drawRect(x + 10, headY + 2 + wiggle, 2, 2, '#ffb6c1');

    drawRect(x + 2, headY + 4 + wiggle, 10, 8, bodyColor);
    drawRect(x + 3, headY + 5 + wiggle, 8, 6, maskColor);
    drawRect(x + 4, headY + 8 + wiggle, 6, 4, chestColor);

    drawRect(x + 5, headY + 6 + wiggle, 2, 2, '#fff');
    drawRect(x + 9, headY + 6 + wiggle, 2, 2, '#fff');
    drawRect(x + 6, headY + 7 + wiggle, 1, 1, '#1a1a1a');
    drawRect(x + 10, headY + 7 + wiggle, 1, 1, '#1a1a1a');

    drawRect(x + 6, headY + 10 + wiggle, 3, 2, '#1a1a1a');
    drawRect(x + 7, headY + 11 + wiggle, 1, 1, '#e85d75');

    if (!big) {
      drawRect(x + 2, y + 10 + wiggle, 10, 4, bodyColor);
      drawRect(x + 3, y + 11 + wiggle, 8, 3, chestColor);
      const legAnim = Math.sin(player.anim) * 2;
      drawRect(x + 2, y + 13 + wiggle + (legAnim > 0 ? 0 : 1), 3, 3, maskColor);
      drawRect(x + 9, y + 13 + wiggle + (legAnim > 0 ? 1 : 0), 3, 3, maskColor);
    }

    if (player.facing > 0) {
      drawRect(x + 11, y + 9 + wiggle, 3, 2, bodyColor);
    } else {
      drawRect(x + 1, y + 9 + wiggle, 3, 2, bodyColor);
    }
  }

  function drawHUD() {
    ctx.fillStyle = '#fff';
    ctx.font = '6px "Press Start 2P", monospace';
    ctx.fillText('FRENCHIE', 8, 10);
    ctx.fillStyle = '#ffe066';
    ctx.fillText(String(score).padStart(6, '0'), 8, 20);

    ctx.fillStyle = '#fff';
    ctx.fillText('LIVES', 100, 10);
    for (let i = 0; i < lives; i++) {
      drawMiniFrenchie(148 + i * 14, 6);
    }

    ctx.fillStyle = '#fff';
    ctx.fillText('TIME', 240, 10);
    ctx.fillStyle = timeLeft < 60 ? '#ff6b6b' : '#ffe066';
    ctx.fillText(String(Math.max(0, timeLeft)), 240, 20);
  }

  function drawMiniFrenchie(x, y) {
    drawRect(x, y, 10, 8, '#d4a574');
    drawRect(x + 1, y + 2, 8, 5, '#3d2914');
    drawRect(x + 2, y + 3, 2, 2, '#fff');
    drawRect(x + 6, y + 3, 2, 2, '#fff');
    drawRect(x + 1, y, 2, 3, '#d4a574');
    drawRect(x + 7, y, 2, 3, '#d4a574');
  }

  function drawParticles() {
    particles.forEach((p) => {
      ctx.globalAlpha = p.life / 50;
      drawRect(p.x, p.y, p.size, p.size, p.color);
      ctx.globalAlpha = 1;
    });
    floatTexts.forEach((t) => {
      ctx.globalAlpha = t.life / 45;
      ctx.fillStyle = t.color;
      ctx.font = '6px "Press Start 2P", monospace';
      ctx.fillText(t.text, t.x - cameraX, t.y);
      ctx.globalAlpha = 1;
    });
  }

  function drawTitle() {
    drawSky();
    drawCloud(60, 30, 1);
    drawCloud(180, 50, 0.9);
    drawCloud(260, 25, 1);

    drawRect(0, 130, 320, 50, '#5cad3a');
    drawRect(0, 138, 320, 8, '#4a9a2e');

    ctx.fillStyle = '#3d2914';
    ctx.font = '14px "Press Start 2P", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('FRENCHIE', 160, 52);
    ctx.fillStyle = '#e85d75';
    ctx.fillText('QUEST', 160, 72);

    drawFrenchieAt(145, 88, 2);
    drawCatAt(200, 92, 1);

    ctx.fillStyle = '#fff';
    ctx.font = '7px "Press Start 2P", monospace';
    if (Math.floor(frame / 30) % 2 === 0) {
      ctx.fillText('PRESS ENTER TO START', 160, 112);
    }

    ctx.fillStyle = '#ffe8c8';
    ctx.font = '5px "Press Start 2P", monospace';
    ctx.fillText('STOMP CATS  ·  GRAB BONES  ·  FIND STEAKS', 160, 126);

    ctx.textAlign = 'left';
  }

  function drawFrenchieAt(x, y, scale) {
    const s = scale;
    drawRect(x, y, 14 * s, 14 * s, '#d4a574');
    drawRect(x + 2 * s, y + 2 * s, 10 * s, 8 * s, '#3d2914');
    drawRect(x + 4 * s, y + 4 * s, 6 * s, 5 * s, '#f5e6d3');
    drawRect(x + 1 * s, y, 3 * s, 4 * s, '#d4a574');
    drawRect(x + 10 * s, y, 3 * s, 4 * s, '#d4a574');
    drawRect(x + 5 * s, y + 4 * s, 2 * s, 2 * s, '#fff');
    drawRect(x + 9 * s, y + 4 * s, 2 * s, 2 * s, '#fff');
  }

  function drawCatAt(x, y, scale) {
    const s = scale;
    drawRect(x, y + 4 * s, 12 * s, 8 * s, '#ff9966');
    drawRect(x + 1 * s, y, 4 * s, 5 * s, '#ff9966');
    drawRect(x + 8 * s, y, 4 * s, 5 * s, '#ff9966');
  }

  function drawCenteredText(lines, color = '#fff') {
    ctx.textAlign = 'center';
    ctx.fillStyle = color;
    lines.forEach((line, i) => {
      ctx.font = `${line.size || 8}px "Press Start 2P", monospace`;
      ctx.fillText(line.text, 160, line.y || (70 + i * 18));
    });
    ctx.textAlign = 'left';
  }

  function drawGameOver() {
    drawBackground();
    drawTiles();
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.fillRect(0, 0, 320, 180);
    drawCenteredText([
      { text: 'GAME OVER', size: 12, y: 70 },
      { text: `SCORE ${score}`, size: 7, y: 95 },
      { text: 'ENTER TO RETRY', size: 6, y: 120 },
    ], '#ff8fa8');
  }

  function drawWin() {
    drawBackground();
    drawTiles();
    ctx.fillStyle = 'rgba(0,0,0,0.45)';
    ctx.fillRect(0, 0, 320, 180);
    drawCenteredText([
      { text: 'GOOD BOY!', size: 12, y: 65 },
      { text: 'YOU MADE IT HOME!', size: 7, y: 88 },
      { text: `FINAL SCORE ${score}`, size: 7, y: 108 },
      { text: 'ENTER TO PLAY AGAIN', size: 6, y: 130 },
    ], '#ffe066');
  }

  function drawDead() {
  }

  function render() {
    ctx.clearRect(0, 0, 320, 180);

    if (gameState === STATE.TITLE) {
      drawTitle();
      return;
    }

    drawBackground();
    drawTiles();
    blocks.forEach(drawBlock);
    bones.forEach(drawBone);
    powerups.forEach(drawSteak);
    enemies.forEach(drawCat);
    drawFrenchie();
    drawParticles();
    drawHUD();

    if (gameState === STATE.GAMEOVER) drawGameOver();
    if (gameState === STATE.WIN) drawWin();
  }

  function loop() {
    update();
    render();
    requestAnimationFrame(loop);
  }

  window.addEventListener('keydown', (e) => {
    keys[e.code] = true;
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) {
      e.preventDefault();
    }
    if (e.code === 'Enter') {
      if (gameState === STATE.TITLE) startGame();
      else if (gameState === STATE.GAMEOVER || gameState === STATE.WIN) {
        gameState = STATE.TITLE;
        frame = 0;
      }
    }
  });

  window.addEventListener('keyup', (e) => {
    keys[e.code] = false;
  });

  canvas.addEventListener('click', () => {
    if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    if (gameState === STATE.TITLE) startGame();
  });

  resetLevel();
  loop();
})();
