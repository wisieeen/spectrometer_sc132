(function () {
  'use strict';

  const API = '/api';

  // --- Theme ---
  function loadTheme() {
    const t = localStorage.getItem('spectrometer-theme') || 'light';
    document.documentElement.setAttribute('data-theme', t);
    const sel = document.getElementById('themeSelect');
    if (sel) sel.value = t;
  }

  function saveTheme(theme) {
    localStorage.setItem('spectrometer-theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
  }

  document.getElementById('themeSelect')?.addEventListener('change', (e) => {
    saveTheme(e.target.value);
  });

  // --- Tabs ---
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      const panel = document.getElementById('tab-' + tab);
      if (panel) panel.classList.add('active');
      if (tab === 'spectrometer') {
        drawSpectrum();
        loadCameraConfigForSpectrometer();
      }
    });
  });

  // --- Spectrum chart ---
  const canvas = document.getElementById('spectrumCanvas');
  const cursorLabel = document.getElementById('cursorLabel');
  const realChannels = {};
  const virtualChannels = {};
  const channelControls = {};
  const channelColors = {};
  const plotColors = ['#0066cc', '#cc3300', '#228833', '#8844cc', '#cc8800', '#008899', '#bb2255', '#6666cc'];
  let lastAxis = null; // { wlMin, wlMax, intMin, intMax }
  let chartDims = { left: 0, top: 0, width: 0, height: 0, pad: 50 };

  function getSeriesMap() {
    const out = {};
    Object.keys(realChannels).forEach((id) => {
      out[id] = realChannels[id];
    });
    Object.keys(virtualChannels).forEach((id) => {
      out[id] = virtualChannels[id].series;
    });
    return out;
  }

  function getVisiblePlotSeries() {
    const all = getSeriesMap();
    return Object.keys(channelControls)
      .filter((id) => channelControls[id]?.plotEnabled)
      .map((id) => ({ id, data: all[id], isVirtual: !!channelControls[id]?.isVirtual }))
      .filter((x) => x.data && Array.isArray(x.data.wavelengths_nm) && x.data.wavelengths_nm.length > 1);
  }

  function getCsvSeries() {
    const all = getSeriesMap();
    return Object.keys(channelControls)
      .filter((id) => channelControls[id]?.csvEnabled)
      .map((id) => ({ id, data: all[id] }))
      .filter((x) => x.data && Array.isArray(x.data.wavelengths_nm) && x.data.wavelengths_nm.length > 0);
  }

  function hexToRgb(hex) {
    const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
    if (!match) return null;
    return {
      r: parseInt(match[1], 16),
      g: parseInt(match[2], 16),
      b: parseInt(match[3], 16),
    };
  }

  function colorDistance(a, b) {
    const c1 = hexToRgb(a);
    const c2 = hexToRgb(b);
    if (!c1 || !c2) return 0;
    const dr = c1.r - c2.r;
    const dg = c1.g - c2.g;
    const db = c1.b - c2.b;
    return Math.sqrt(dr * dr + dg * dg + db * db);
  }

  function hslToHex(h, s, l) {
    const hue = (((h % 360) + 360) % 360) / 360;
    const sat = Math.max(0, Math.min(1, s));
    const lig = Math.max(0, Math.min(1, l));
    const hue2rgb = (p, q, t) => {
      let tt = t;
      if (tt < 0) tt += 1;
      if (tt > 1) tt -= 1;
      if (tt < 1 / 6) return p + (q - p) * 6 * tt;
      if (tt < 1 / 2) return q;
      if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
      return p;
    };
    let r;
    let g;
    let b;
    if (sat === 0) {
      r = g = b = lig;
    } else {
      const q = lig < 0.5 ? lig * (1 + sat) : lig + sat - lig * sat;
      const p = 2 * lig - q;
      r = hue2rgb(p, q, hue + 1 / 3);
      g = hue2rgb(p, q, hue);
      b = hue2rgb(p, q, hue - 1 / 3);
    }
    const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, '0');
    return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
  }

  function pickDistinctColor() {
    const used = Object.values(channelColors);
    for (const c of plotColors) {
      if (!used.includes(c)) return c;
    }
    let best = '#ffffff';
    let bestScore = -1;
    for (let i = 0; i < 72; i++) {
      const candidate = hslToHex(i * 137.508, 0.8, 0.5);
      const minDist = used.reduce((acc, c) => Math.min(acc, colorDistance(candidate, c)), 9999);
      if (minDist > bestScore) {
        bestScore = minDist;
        best = candidate;
      }
    }
    return best;
  }

  function ensureChannelColor(id) {
    if (!channelColors[id]) {
      channelColors[id] = pickDistinctColor();
    }
    return channelColors[id];
  }

  function findLocalMaxima(wl, ints, windowNm) {
    const peaks = [];
    for (let i = 1; i < ints.length - 1; i++) {
      if (ints[i] >= ints[i - 1] && ints[i] >= ints[i + 1]) {
        const w = wl[i];
        const win = Math.floor(w / windowNm) * windowNm;
        const existing = peaks.find((p) => Math.floor(p.wl / windowNm) * windowNm === win);
        if (!existing || ints[i] > existing.int) {
          if (existing) peaks.splice(peaks.indexOf(existing), 1);
          peaks.push({ wl: w, int: ints[i], idx: i });
        }
      }
    }
    return peaks.sort((a, b) => a.wl - b.wl);
  }

  function interpolateAt(wl, wavelengths, intensities) {
    const n = Math.min(wavelengths.length, intensities.length);
    if (n === 0) return 0;
    if (n === 1) return intensities[0];

    const first = wavelengths[0];
    const last = wavelengths[n - 1];
    const ascending = first <= last;

    if (ascending) {
      if (wl <= first) return intensities[0];
      if (wl >= last) return intensities[n - 1];
    } else {
      if (wl >= first) return intensities[0];
      if (wl <= last) return intensities[n - 1];
    }

    for (let i = 0; i < n - 1; i++) {
      const x0 = wavelengths[i];
      const x1 = wavelengths[i + 1];
      const left = Math.min(x0, x1);
      const right = Math.max(x0, x1);
      if (wl >= left && wl <= right) {
        const denom = (x1 - x0) || 1;
        const t = (wl - x0) / denom;
        return intensities[i] + t * (intensities[i + 1] - intensities[i]);
      }
    }
    return intensities[n - 1];
  }

  function drawSpectrum() {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    // Reset transform each draw to avoid cumulative scaling.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = rect.width;
    const h = rect.height;
    chartDims = { left: 50, top: 20, width: w - 70, height: h - 50, pad: 50 };

    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg-secondary').trim() || '#fff';
    const grid = getComputedStyle(document.documentElement).getPropertyValue('--chart-grid').trim() || '#e0e0e0';
    const text = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#222';

    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    const visible = getVisiblePlotSeries();
    if (visible.length === 0) {
      ctx.fillStyle = text;
      ctx.font = '14px sans-serif';
      ctx.fillText('No visible spectrum channels', chartDims.left, h / 2);
      return;
    }
    const allWl = [];
    const allInts = [];
    visible.forEach((s) => {
      allWl.push(...(s.data.wavelengths_nm || []));
      allInts.push(...(s.data.intensities || []));
    });
    const wlMin = Math.min(...allWl);
    const wlMax = Math.max(...allWl);
    const intMin = Math.min(...allInts);
    const intMax = Math.max(...allInts) || 1;
    const intRange = intMax - intMin || 1;
    lastAxis = { wlMin, wlMax, intMin, intMax };

    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
      const x = chartDims.left + (i / 5) * chartDims.width;
      ctx.beginPath();
      ctx.moveTo(x, chartDims.top);
      ctx.lineTo(x, chartDims.top + chartDims.height);
      ctx.stroke();
    }
    for (let i = 0; i <= 5; i++) {
      const y = chartDims.top + (i / 5) * chartDims.height;
      ctx.beginPath();
      ctx.moveTo(chartDims.left, y);
      ctx.lineTo(chartDims.left + chartDims.width, y);
      ctx.stroke();
    }

    visible.forEach((series) => {
      const wl = series.data.wavelengths_nm || [];
      const ints = series.data.intensities || [];
      const color = ensureChannelColor(series.id);
      ctx.strokeStyle = color;
      ctx.lineWidth = series.isVirtual ? 1.3 : 0.7;
      ctx.beginPath();
      for (let i = 0; i < wl.length; i++) {
        const x = chartDims.left + ((wl[i] - wlMin) / (wlMax - wlMin || 1)) * chartDims.width;
        const y = chartDims.top + chartDims.height - ((ints[i] - intMin) / intRange) * chartDims.height;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });

    // Keep peak labels on the first visible channel only to limit clutter.
    const peakBase = visible[0];
    const peaks = findLocalMaxima(peakBase.data.wavelengths_nm || [], peakBase.data.intensities || [], 20);
    ctx.fillStyle = text;
    ctx.font = '11px sans-serif';
    peaks.forEach((p) => {
      const x = chartDims.left + ((p.wl - wlMin) / (wlMax - wlMin || 1)) * chartDims.width;
      const y = chartDims.top + chartDims.height - ((p.int - intMin) / intRange) * chartDims.height;
      ctx.save();
      ctx.translate(x, Math.max(chartDims.top, y - 12));
      ctx.rotate(-75 * Math.PI / 180);
      ctx.fillText(p.wl.toFixed(1) + ' nm', 0, 0);
      ctx.restore();
    });

    ctx.fillStyle = text;
    ctx.font = '12px sans-serif';
    ctx.fillText('Wavelength (nm)', chartDims.left + chartDims.width / 2 - 50, h - 5);
    ctx.save();
    ctx.translate(15, chartDims.top + chartDims.height / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('Intensity', 0, 0);
    ctx.restore();
  }

  function pixelToWavelength(px) {
    if (!lastAxis || !Number.isFinite(lastAxis.wlMin) || !Number.isFinite(lastAxis.wlMax)) return null;
    const wlMin = lastAxis.wlMin;
    const wlMax = lastAxis.wlMax;
    const x = (px - chartDims.left) / chartDims.width;
    return wlMin + x * (wlMax - wlMin);
  }

  function updateCursorLabel(clientX) {
    if (!cursorLabel) return;
    const rect = canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    if (px < chartDims.left || px > chartDims.left + chartDims.width) {
      cursorLabel.style.opacity = '0';
      return;
    }
    const wl = pixelToWavelength(px);
    if (wl == null) return;
    const all = getSeriesMap();
    const cursorSeries = Object.keys(channelControls)
      .filter((id) => channelControls[id]?.cursorEnabled && channelControls[id]?.plotEnabled)
      .map((id) => ({ id, data: all[id] }))
      .filter((x) => x.data && Array.isArray(x.data.wavelengths_nm) && x.data.wavelengths_nm.length > 1);
    if (cursorSeries.length === 0) {
      cursorLabel.style.opacity = '0';
      return;
    }
    const parts = cursorSeries.map((s) => {
      const int = interpolateAt(wl, s.data.wavelengths_nm || [], s.data.intensities || []);
      return `${s.id}: ${int.toFixed(3)}`;
    });
    cursorLabel.textContent = `${wl.toFixed(1)} nm | ${parts.join(' | ')}`;
    const labelWidth = cursorLabel.offsetWidth || 0;
    const minX = labelWidth / 2 + 4;
    const maxX = rect.width - labelWidth / 2 - 4;
    const clampedX = Math.max(minX, Math.min(maxX, px));
    cursorLabel.style.left = clampedX + 'px';
    cursorLabel.style.top = '10px';
    cursorLabel.style.opacity = '1';
  }

  function drawCursorLine(clientX) {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    const ctx = canvas.getContext('2d');
    drawSpectrum();
    if (px >= chartDims.left && px <= chartDims.left + chartDims.width) {
      ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0066cc';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(px, chartDims.top);
      ctx.lineTo(px, chartDims.top + chartDims.height);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    updateCursorLabel(clientX);
  }

  canvas?.addEventListener('mousemove', (e) => drawCursorLine(e.clientX));
  canvas?.addEventListener('mouseleave', () => {
    if (cursorLabel) cursorLabel.style.opacity = '0';
    drawSpectrum();
  });
  canvas?.addEventListener('touchmove', (e) => {
    if (e.touches.length) drawCursorLine(e.touches[0].clientX);
  });
  canvas?.addEventListener('touchstart', (e) => {
    if (e.touches.length) drawCursorLine(e.touches[0].clientX);
  });

  window.addEventListener('resize', () => drawSpectrum());

  // --- API helpers ---
  function showStatus(msg, isError = false) {
    const el = document.getElementById('apiStatus');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('error', isError);
    if (!isError && msg) {
      setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 3000);
    }
  }

  async function api(method, path, body) {
    const opts = { method };
    if (body) {
      opts.headers = { 'Content-Type': 'application/json' };
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(API + path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = data.error || data.message || `HTTP ${r.status}`;
      throw new Error(err);
    }
    return data;
  }

  // --- Spectrometer state ---
  let lastSpectrumUpdateTime = 0;
  let isRunning = false;

  function updateButtonStates() {
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    const wrap = document.querySelector('.btn-start-wrap');
    if (btnStart) btnStart.disabled = isRunning;
    if (btnStop) btnStop.disabled = !isRunning;
    wrap?.classList.toggle('running', isRunning);
  }

  function updateSpectrumTimer() {
    const el = document.getElementById('spectrumTimer');
    if (!el) return;
    if (!isRunning || lastSpectrumUpdateTime === 0) {
      el.textContent = '--';
      return;
    }
    const sec = Math.floor((Date.now() - lastSpectrumUpdateTime) / 1000);
    el.textContent = String(sec).padStart(2, '0');
  }

  function ensureChannelControl(id, isVirtual = false) {
    if (!channelControls[id]) {
      channelControls[id] = {
        activeEnabled: true,
        plotEnabled: true,
        csvEnabled: true,
        cursorEnabled: true,
        description: '',
        isVirtual,
      };
    } else if (isVirtual) {
      channelControls[id].isVirtual = true;
    }
    if (typeof channelControls[id].activeEnabled !== 'boolean') {
      channelControls[id].activeEnabled = true;
    }
    if (typeof channelControls[id].cursorEnabled !== 'boolean') {
      channelControls[id].cursorEnabled = true;
    }
    if (typeof channelControls[id].description !== 'string') {
      channelControls[id].description = '';
    }
    ensureChannelColor(id);
  }

  function renderChannelList() {
    const list = document.getElementById('channelList');
    if (!list) return;
    list.innerHTML = '';
    const ids = Object.keys(channelControls).sort();
    if (ids.length === 0) {
      list.textContent = 'No channels available.';
      return;
    }
    ids.forEach((id) => {
      const row = document.createElement('div');
      row.className = 'control-row';
      const label = document.createElement('span');
      label.className = 'channel-label';
      const swatch = document.createElement('span');
      swatch.className = 'channel-color-box';
      swatch.style.backgroundColor = ensureChannelColor(id);
      const txt = document.createElement('span');
      txt.textContent = channelControls[id].isVirtual ? `${id} (virtual)` : id;
      label.appendChild(swatch);
      label.appendChild(txt);
      if (channelControls[id].isVirtual) {
        label.style.cursor = 'pointer';
        label.title = 'Click to load virtual expression';
        label.addEventListener('click', () => {
          const nameEl = document.getElementById('virtualChannelName');
          const exprEl = document.getElementById('virtualChannelExpr');
          if (nameEl) nameEl.value = id;
          if (exprEl) exprEl.value = virtualChannels[id]?.expr || '';
        });
      }
      const plotLabel = document.createElement('label');
      const plot = document.createElement('input');
      plot.type = 'checkbox';
      plot.checked = !!channelControls[id].plotEnabled;
      plot.addEventListener('change', () => {
        channelControls[id].plotEnabled = plot.checked;
        drawSpectrum();
      });
      plotLabel.appendChild(plot);
      plotLabel.append(' Plot');
      const activeLabel = document.createElement('label');
      const active = document.createElement('input');
      active.type = 'checkbox';
      active.checked = !!channelControls[id].activeEnabled;
      active.disabled = !!channelControls[id].isVirtual;
      active.addEventListener('change', async () => {
        channelControls[id].activeEnabled = active.checked;
        if (channelControls[id].isVirtual) return;
        try {
          await api('POST', '/spectrometer/channel_active', { channel_id: id, active: active.checked });
          showStatus(`Channel ${id} ${active.checked ? 'activated' : 'deactivated'}.`);
          schedulePoll();
        } catch (e) {
          channelControls[id].activeEnabled = !active.checked;
          active.checked = channelControls[id].activeEnabled;
          showStatus('Channel active update failed: ' + (e.message || 'Unknown error'), true);
        }
      });
      activeLabel.appendChild(active);
      activeLabel.append(' Active');
      const csvLabel = document.createElement('label');
      const csv = document.createElement('input');
      csv.type = 'checkbox';
      csv.checked = !!channelControls[id].csvEnabled;
      csv.addEventListener('change', () => {
        channelControls[id].csvEnabled = csv.checked;
      });
      csvLabel.appendChild(csv);
      csvLabel.append(' CSV');
      const cursorLabelToggle = document.createElement('label');
      const cursorToggle = document.createElement('input');
      cursorToggle.type = 'checkbox';
      cursorToggle.checked = !!channelControls[id].cursorEnabled;
      cursorToggle.addEventListener('change', () => {
        channelControls[id].cursorEnabled = cursorToggle.checked;
      });
      cursorLabelToggle.appendChild(cursorToggle);
      cursorLabelToggle.append(' Cursor');
      row.appendChild(label);
      const descInput = document.createElement('input');
      descInput.type = 'text';
      descInput.placeholder = 'description';
      descInput.value = channelControls[id].description || '';
      descInput.className = 'channel-desc-input';
      descInput.title = 'Description will appear in CSV under channel name';
      descInput.addEventListener('change', () => {
        channelControls[id].description = descInput.value || '';
      });
      row.appendChild(descInput);
      row.appendChild(activeLabel);
      row.appendChild(plotLabel);
      row.appendChild(csvLabel);
      row.appendChild(cursorLabelToggle);
      list.appendChild(row);
    });
  }

  function tokenizeExpr(expr) {
    const tokens = [];
    const re = /\s*([A-Za-z_]\w*|\d+(?:\.\d+)?|[()+\-*])\s*/g;
    let m;
    let consumed = 0;
    while ((m = re.exec(expr)) !== null) {
      tokens.push(m[1]);
      consumed = re.lastIndex;
    }
    if (consumed !== expr.length) throw new Error('Invalid token in expression');
    return tokens;
  }

  function toRpn(tokens) {
    const prec = { '+': 1, '-': 1, '*': 2 };
    const out = [];
    const ops = [];
    tokens.forEach((t) => {
      if (/^[A-Za-z_]\w*$/.test(t) || /^\d+(\.\d+)?$/.test(t)) {
        out.push(t);
      } else if (t in prec) {
        while (ops.length && (ops[ops.length - 1] in prec) && prec[ops[ops.length - 1]] >= prec[t]) {
          out.push(ops.pop());
        }
        ops.push(t);
      } else if (t === '(') {
        ops.push(t);
      } else if (t === ')') {
        while (ops.length && ops[ops.length - 1] !== '(') out.push(ops.pop());
        if (ops.pop() !== '(') throw new Error('Mismatched parentheses');
      } else {
        throw new Error('Unsupported token');
      }
    });
    while (ops.length) {
      const op = ops.pop();
      if (op === '(') throw new Error('Mismatched parentheses');
      out.push(op);
    }
    return out;
  }

  function evaluateVirtualExpression(expr) {
    const tokens = tokenizeExpr(expr);
    const rpn = toRpn(tokens);
    const stack = [];
    const seriesMap = getSeriesMap();
    rpn.forEach((token) => {
      if (/^\d+(\.\d+)?$/.test(token)) {
        stack.push({ type: 'const', value: Number(token) });
        return;
      }
      if (/^[A-Za-z_]\w*$/.test(token)) {
        const s = seriesMap[token];
        if (!s) throw new Error(`Unknown channel: ${token}`);
        stack.push({ type: 'series', value: s });
        return;
      }
      if (!['+', '-', '*'].includes(token)) throw new Error('Unsupported operator');
      const b = stack.pop();
      const a = stack.pop();
      if (!a || !b) throw new Error('Malformed expression');
      stack.push(applyBinaryOp(a, b, token));
    });
    if (stack.length !== 1 || stack[0].type !== 'series') {
      throw new Error('Expression must produce a channel series');
    }
    return stack[0].value;
  }

  function applyBinaryOp(a, b, op) {
    if (a.type === 'const' && b.type === 'const') {
      const n = op === '+' ? a.value + b.value : op === '-' ? a.value - b.value : a.value * b.value;
      return { type: 'const', value: n };
    }
    if (a.type === 'series' && b.type === 'const') {
      return { type: 'series', value: mapSeriesConst(a.value, b.value, op) };
    }
    if (a.type === 'const' && b.type === 'series') {
      if (op !== '*') throw new Error('Only multiplication supports constant on left side');
      return { type: 'series', value: mapSeriesConst(b.value, a.value, op) };
    }
    return { type: 'series', value: mapSeriesSeries(a.value, b.value, op) };
  }

  function mapSeriesConst(series, c, op) {
    const wl = series.wavelengths_nm || [];
    const ints = (series.intensities || []).map((v) => {
      if (op === '+') return v + c;
      if (op === '-') return v - c;
      return v * c;
    });
    return { wavelengths_nm: wl.slice(), intensities: ints };
  }

  function mapSeriesSeries(a, b, op) {
    const wlA = a.wavelengths_nm || [];
    const wlB = b.wavelengths_nm || [];
    const ia = a.intensities || [];
    const ib = b.intensities || [];
    const baseN = Math.min(wlA.length, ia.length);
    if (baseN < 2) return { wavelengths_nm: [], intensities: [] };
    const baseWl = wlA.slice(0, baseN);
    const resampledB = resampleSeriesToWavelengths({ wavelengths_nm: wlB, intensities: ib }, baseWl);
    const bInts = resampledB.intensities || [];
    const n = Math.min(baseWl.length, bInts.length);
    const wl = baseWl.slice(0, n);
    const ints = new Array(n);
    for (let i = 0; i < n; i++) {
      const av = ia[i];
      const bv = bInts[i];
      if (op === '+') ints[i] = av + bv;
      else if (op === '-') ints[i] = av - bv;
      else ints[i] = av * bv;
    }
    return { wavelengths_nm: wl, intensities: ints };
  }

  function resampleSeriesToWavelengths(series, targetWavelengths) {
    const wl = series.wavelengths_nm || [];
    const ints = series.intensities || [];
    const n = Math.min(wl.length, ints.length);
    if (n < 2 || !Array.isArray(targetWavelengths) || targetWavelengths.length === 0) {
      return { wavelengths_nm: targetWavelengths ? targetWavelengths.slice() : [], intensities: [] };
    }
    const out = new Array(targetWavelengths.length);
    let j = 0;
    for (let i = 0; i < targetWavelengths.length; i++) {
      const t = targetWavelengths[i];
      while (j < n - 2 && t > wl[j + 1]) j++;
      if (t <= wl[0]) {
        out[i] = ints[0];
        continue;
      }
      if (t >= wl[n - 1]) {
        out[i] = ints[n - 1];
        continue;
      }
      const x0 = wl[j];
      const x1 = wl[j + 1];
      const y0 = ints[j];
      const y1 = ints[j + 1];
      const denom = (x1 - x0) || 1;
      const tt = (t - x0) / denom;
      out[i] = y0 + tt * (y1 - y0);
    }
    return { wavelengths_nm: targetWavelengths.slice(), intensities: out };
  }

  function recomputeVirtualChannels() {
    Object.keys(virtualChannels).forEach((id) => {
      try {
        virtualChannels[id].series = evaluateVirtualExpression(virtualChannels[id].expr);
      } catch (e) {
        virtualChannels[id].series = { wavelengths_nm: [], intensities: [] };
      }
    });
  }

  // --- Spectrometer controls ---
  document.getElementById('btnStart')?.addEventListener('click', async () => {
    try {
      await api('POST', '/spectrometer/start');
      isRunning = true;
      updateButtonStates();
      schedulePoll();
      showStatus('Continuous acquisition started.');
    } catch (e) {
      showStatus('Start failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  document.getElementById('btnStop')?.addEventListener('click', async () => {
    try {
      await api('POST', '/spectrometer/stop');
      isRunning = false;
      updateButtonStates();
      schedulePoll();
      showStatus('Continuous acquisition stopped.');
    } catch (e) {
      showStatus('Stop failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  document.getElementById('btnSingle')?.addEventListener('click', async () => {
    try {
      const s = await api('POST', '/spectrometer/single');
      if (s.wavelengths_nm) {
        if (s.channel_id) {
          realChannels[s.channel_id] = s;
          ensureChannelControl(s.channel_id, false);
        }
        recomputeVirtualChannels();
        renderChannelList();
        lastSpectrumUpdateTime = Date.now();
        drawSpectrum();
        const over = s.meta && s.meta.overexposure;
        if (over && over.checked && over.overexposed) {
          showStatus('Single spectrum acquired. Warning: overexposure detected on line of interest.', true);
        } else {
          showStatus('Single spectrum acquired.');
        }
      } else {
        showStatus('No spectrum data returned.', true);
      }
    } catch (e) {
      showStatus('Single failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  document.getElementById('btnPreview')?.addEventListener('click', async () => {
    try {
      await api('POST', '/spectrometer/preview');
      showStatus('Preview started.');
    } catch (e) {
      showStatus('Preview failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  document.getElementById('btnSaveCsv')?.addEventListener('click', () => {
    const selected = getCsvSeries();
    if (selected.length === 0) {
      showStatus('No spectrum data to save.', true);
      return;
    }
    const base = selected[0].data;
    const wl = base.wavelengths_nm || [];
    const minLen = selected.reduce((m, s) => Math.min(m, (s.data.intensities || []).length, (s.data.wavelengths_nm || []).length), wl.length);
    const header = ['wavelength_nm', ...selected.map((s) => s.id)];
    const rows = [header.join(',')];
    const descriptionRow = [''];
    selected.forEach((s) => {
      const d = channelControls[s.id]?.description || '';
      descriptionRow.push(String(d).replace(/[\r\n]+/g, ' ').trim());
    });
    rows.push(descriptionRow.join(','));
    for (let i = 0; i < minLen; i++) {
      const vals = [wl[i]];
      selected.forEach((s) => vals.push((s.data.intensities || [])[i] ?? ''));
      rows.push(vals.join(','));
    }
    const csv = rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `spectrum_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showStatus('Spectrum saved as CSV.');
  });

  document.getElementById('btnAddVirtualChannel')?.addEventListener('click', () => {
    const name = (document.getElementById('virtualChannelName')?.value || '').trim();
    const expr = (document.getElementById('virtualChannelExpr')?.value || '').trim();
    if (!name || !/^[A-Za-z_]\w*$/.test(name)) {
      showStatus('Virtual channel name must be identifier-like (e.g. v0).', true);
      return;
    }
    if (!expr) {
      showStatus('Virtual channel expression is required.', true);
      return;
    }
    try {
      const series = evaluateVirtualExpression(expr);
      virtualChannels[name] = { expr, series };
      ensureChannelControl(name, true);
      renderChannelList();
      drawSpectrum();
      showStatus(`Virtual channel ${name} added.`);
    } catch (e) {
      showStatus('Virtual channel error: ' + (e.message || 'Invalid expression'), true);
    }
  });

  async function apiSilent(method, path, body) {
    try {
      await api(method, path, body);
    } catch (e) {
      showStatus(e.message || 'Request failed', true);
    }
  }

  document.getElementById('intervalMs')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/interval_ms', { value: e.target.value });
  });

  document.getElementById('frameAverageN')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_frame_average_n', { value: e.target.value });
  });
  document.getElementById('darkFlatEnabled')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_dark_flat_enabled', { value: e.target.checked });
  });
  document.getElementById('richardsonLucyEnabled')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_richardson_lucy_enabled', { value: e.target.checked });
  });
  document.getElementById('richardsonLucyPsfSigma')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_richardson_lucy_psf_sigma', { value: e.target.value });
  });
  document.getElementById('richardsonLucyIterations')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_richardson_lucy_iterations', { value: e.target.value });
  });
  document.getElementById('richardsonLucyPsfPath')?.addEventListener('change', (e) => {
    apiSilent('POST', '/spectrometer/processing_richardson_lucy_psf_path', { value: e.target.value });
  });

  document.getElementById('spectrometerShutter')?.addEventListener('change', (e) => {
    apiSilent('POST', '/camera/shutter', { value: e.target.value });
  });
  document.getElementById('spectrometerGain')?.addEventListener('change', (e) => {
    apiSilent('POST', '/camera/gain', { value: e.target.value });
  });

  async function loadCameraConfigForSpectrometer() {
    try {
      const cam = await api('GET', '/camera/config');
      const shutterEl = document.getElementById('spectrometerShutter');
      const gainEl = document.getElementById('spectrometerGain');
      if (shutterEl) shutterEl.value = cam.shutter || 4100;
      if (gainEl) gainEl.value = cam.gain ?? 1;
    } catch (e) {
      /* ignore */
    }
  }

  // --- Poll spectrum ---
  const POLL_INTERVAL_RUNNING = 250;
  const POLL_INTERVAL_IDLE = 10000;
  let pollTimeoutId = null;

  function schedulePoll() {
    if (pollTimeoutId) clearTimeout(pollTimeoutId);
    const interval = isRunning ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE;
    pollTimeoutId = setTimeout(() => {
      pollSpectrum();
    }, interval);
  }

  async function pollSpectrum() {
    try {
      const st = await api('GET', '/spectrometer/status');
      isRunning = st.status === 'running';
      updateButtonStates();
      const channelIds = Array.isArray(st.channels) ? st.channels : [];
      const activityMap = st.channel_activity || {};
      Object.keys(activityMap).forEach((channelId) => {
        ensureChannelControl(channelId, false);
        channelControls[channelId].activeEnabled = !!activityMap[channelId];
      });
      for (const channelId of channelIds) {
        ensureChannelControl(channelId, false);
      }
      if (channelIds.length > 0) {
        const fetched = await Promise.all(channelIds.map(async (id) => {
          try {
            return await api('GET', '/spectrometer/spectrum/' + id);
          } catch (e) {
            return null;
          }
        }));
        Object.keys(realChannels).forEach((id) => {
          if (!channelIds.includes(id)) {
            delete realChannels[id];
          }
        });
        fetched.forEach((s) => {
          if (s && s.channel_id && s.wavelengths_nm) {
            realChannels[s.channel_id] = s;
          }
        });
        recomputeVirtualChannels();
        renderChannelList();
        lastSpectrumUpdateTime = Date.now();
        drawSpectrum();
      } else {
        Object.keys(realChannels).forEach((id) => delete realChannels[id]);
        recomputeVirtualChannels();
        renderChannelList();
        drawSpectrum();
      }

      const setInputValue = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
      };
      const setInputChecked = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.checked = value;
      };
      setInputValue('intervalMs', st.interval_ms || 1000);
      setInputValue('frameAverageN', st.processing?.frame_average_n ?? 1);
      setInputChecked('darkFlatEnabled', st.processing?.dark_flat_enabled ?? false);
      setInputChecked('richardsonLucyEnabled', st.processing?.richardson_lucy_enabled ?? false);
      const psfSigmaEl = document.getElementById('richardsonLucyPsfSigma');
      const rlIterationsEl = document.getElementById('richardsonLucyIterations');
      const rlPathEl = document.getElementById('richardsonLucyPsfPath');
      if (psfSigmaEl) psfSigmaEl.value = st.processing?.richardson_lucy_psf_sigma ?? 3;
      if (rlIterationsEl) rlIterationsEl.value = st.processing?.richardson_lucy_iterations ?? 15;
      if (rlPathEl) rlPathEl.value = st.processing?.richardson_lucy_psf_path ?? '';
    } catch (e) {
      showStatus('Status fetch failed: ' + (e.message || 'Unknown error'), true);
    }
    schedulePoll();
  }

  pollSpectrum();
  loadCameraConfigForSpectrometer();

  // Timer tick: update seconds-since-last-spectrum every second when running
  setInterval(() => {
    updateSpectrumTimer();
  }, 1000);

  // --- Config ---
  document.getElementById('btnWifiSave')?.addEventListener('click', async () => {
    const ssid = document.getElementById('wifiSsid').value;
    const password = document.getElementById('wifiPassword').value;
    await api('POST', '/config/wifi', { ssid, password });
    alert('WiFi credentials saved.');
  });

  document.getElementById('btnMqttSave')?.addEventListener('click', async () => {
    const broker = document.getElementById('mqttBroker').value;
    const port = document.getElementById('mqttPort').value;
    const user = document.getElementById('mqttUser').value;
    const pass = document.getElementById('mqttPass').value;
    await api('POST', '/config/mqtt', { broker, port, user, pass });
    alert('MQTT config saved.');
  });

  document.getElementById('btnCaptureDarkFrame')?.addEventListener('click', async () => {
    if (!confirm('Capture dark frame now? Ensure light path is blocked.')) return;
    try {
      const r = await api('POST', '/spectrometer/capture_dark_frame');
      showStatus('Dark frame saved: ' + (r.path || 'ok'));
      alert('Dark frame saved: ' + (r.path || 'ok'));
    } catch (e) {
      showStatus('Dark frame capture failed: ' + (e.message || 'Unknown error'), true);
      alert('Dark frame capture failed: ' + (e.message || 'Unknown error'));
    }
  });

  document.getElementById('btnCaptureFlatFrame')?.addEventListener('click', async () => {
    if (!confirm('Capture flat frame now? Ensure uniform illumination with no saturation.')) return;
    try {
      const r = await api('POST', '/spectrometer/capture_flat_frame');
      showStatus('Flat frame saved: ' + (r.path || 'ok'));
      alert('Flat frame saved: ' + (r.path || 'ok'));
    } catch (e) {
      showStatus('Flat frame capture failed: ' + (e.message || 'Unknown error'), true);
      alert('Flat frame capture failed: ' + (e.message || 'Unknown error'));
    }
  });

  document.getElementById('btnReboot')?.addEventListener('click', async () => {
    if (!confirm('Reboot the device now?')) return;
    try {
      await api('POST', '/system/reboot');
      showStatus('Rebooting...');
    } catch (e) {
      showStatus('Reboot failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  document.getElementById('btnShutdown')?.addEventListener('click', async () => {
    if (!confirm('Shutdown the device now?')) return;
    try {
      await api('POST', '/system/shutdown');
      showStatus('Shutting down...');
    } catch (e) {
      showStatus('Shutdown failed: ' + (e.message || 'Unknown error'), true);
    }
  });

  (async () => {
    try {
      const [mqtt, wifi] = await Promise.all([
        api('GET', '/config/mqtt'),
        api('GET', '/config/wifi'),
      ]);
      const brokerEl = document.getElementById('mqttBroker');
      const portEl = document.getElementById('mqttPort');
      const userEl = document.getElementById('mqttUser');
      const ssidEl = document.getElementById('wifiSsid');
      if (brokerEl) brokerEl.value = mqtt.broker || '';
      if (portEl) portEl.value = mqtt.port || 1883;
      if (userEl) userEl.value = mqtt.user || '';
      if (ssidEl && wifi.ssid) ssidEl.value = wifi.ssid;
    } catch (e) {
      showStatus('Initial config load failed: ' + (e.message || 'Unknown error'), true);
    }
  })();

  // --- Init ---
  loadTheme();
  renderChannelList();
  drawSpectrum();
})();
