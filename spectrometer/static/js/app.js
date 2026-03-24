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
  let spectrumData = { wavelengths_nm: [], intensities: [] };
  let chartDims = { left: 0, top: 0, width: 0, height: 0, pad: 50 };

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
    if (wavelengths.length === 0) return 0;
    if (wl <= wavelengths[0]) return intensities[0];
    if (wl >= wavelengths[wavelengths.length - 1]) return intensities[intensities.length - 1];
    for (let i = 0; i < wavelengths.length - 1; i++) {
      if (wl >= wavelengths[i] && wl <= wavelengths[i + 1]) {
        const t = (wl - wavelengths[i]) / (wavelengths[i + 1] - wavelengths[i]);
        return intensities[i] + t * (intensities[i + 1] - intensities[i]);
      }
    }
    return 0;
  }

  function drawSpectrum() {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    const w = rect.width;
    const h = rect.height;
    chartDims = { left: 50, top: 20, width: w - 70, height: h - 50, pad: 50 };

    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg-secondary').trim() || '#fff';
    const grid = getComputedStyle(document.documentElement).getPropertyValue('--chart-grid').trim() || '#e0e0e0';
    const line = getComputedStyle(document.documentElement).getPropertyValue('--chart-line').trim() || '#0066cc';
    const text = getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#222';

    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    const wl = spectrumData.wavelengths_nm || [];
    const ints = spectrumData.intensities || [];

    if (wl.length < 2) {
      ctx.fillStyle = text;
      ctx.font = '14px sans-serif';
      ctx.fillText('No spectrum data', chartDims.left, h / 2);
      return;
    }

    const wlMin = Math.min(...wl);
    const wlMax = Math.max(...wl);
    const intMin = Math.min(...ints);
    const intMax = Math.max(...ints) || 1;
    const intRange = intMax - intMin || 1;

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

    ctx.strokeStyle = line;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    for (let i = 0; i < wl.length; i++) {
      const x = chartDims.left + ((wl[i] - wlMin) / (wlMax - wlMin)) * chartDims.width;
      const y = chartDims.top + chartDims.height - ((ints[i] - intMin) / intRange) * chartDims.height;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    const peaks = findLocalMaxima(wl, ints, 20);
    ctx.fillStyle = text;
    ctx.font = '11px sans-serif';
    ctx.save();
    ctx.translate(0, 0);
    peaks.forEach((p) => {
      const x = chartDims.left + ((p.wl - wlMin) / (wlMax - wlMin)) * chartDims.width;
      const y = chartDims.top + chartDims.height - ((p.int - intMin) / intRange) * chartDims.height;
      ctx.save();
      ctx.translate(x, Math.max(chartDims.top, y - 12));
      ctx.rotate(-75 * Math.PI / 180);
      ctx.fillText(p.wl.toFixed(1) + ' nm', 0, 0);
      ctx.restore();
    });
    ctx.restore();

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
    const wl = spectrumData.wavelengths_nm || [];
    if (wl.length < 2) return null;
    const wlMin = Math.min(...wl);
    const wlMax = Math.max(...wl);
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
    const int = interpolateAt(wl, spectrumData.wavelengths_nm || [], spectrumData.intensities || []);
    cursorLabel.textContent = wl.toFixed(1) + ' nm, ' + int.toFixed(3);
    cursorLabel.style.left = px + 'px';
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
    cursorLabel.style.opacity = '0';
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
        spectrumData = s;
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
    const wl = spectrumData.wavelengths_nm || [];
    const ints = spectrumData.intensities || [];
    if (wl.length === 0) {
      showStatus('No spectrum data to save.', true);
      return;
    }
    const rows = ['wavelength_nm,intensity'];
    for (let i = 0; i < wl.length; i++) {
      rows.push(`${wl[i]},${ints[i] ?? ''}`);
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

      if (isRunning && st.channels && st.channels[0]) {
        const s = await api('GET', '/spectrometer/spectrum/' + st.channels[0]);
        if (s.wavelengths_nm) {
          spectrumData = s;
          lastSpectrumUpdateTime = Date.now();
          drawSpectrum();
        }
      }

      document.getElementById('intervalMs').value = st.interval_ms || 1000;
      document.getElementById('frameAverageN').value = st.processing?.frame_average_n ?? 1;
      document.getElementById('darkFlatEnabled').checked = st.processing?.dark_flat_enabled ?? false;
      document.getElementById('richardsonLucyEnabled').checked = st.processing?.richardson_lucy_enabled ?? false;
      document.getElementById('richardsonLucyPsfSigma').value = st.processing?.richardson_lucy_psf_sigma ?? 3;
      document.getElementById('richardsonLucyIterations').value = st.processing?.richardson_lucy_iterations ?? 15;
      document.getElementById('richardsonLucyPsfPath').value = st.processing?.richardson_lucy_psf_path ?? '';
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

  // --- Video ---
  const video = document.getElementById('videoStream');
  document.getElementById('btnFullscreen')?.addEventListener('click', () => {
    if (video.requestFullscreen) video.requestFullscreen();
    else if (video.webkitRequestFullscreen) video.webkitRequestFullscreen();
  });

  async function loadStream() {
    const u = await api('GET', '/stream/url');
    const cam = await api('GET', '/camera/config');
    document.getElementById('resolution').value = cam.resolution || '1080x640';
    document.getElementById('fps').value = cam.fps || 5;
    document.getElementById('shutter').value = cam.shutter || 4100;
    document.getElementById('gain').value = cam.gain ?? 1;
    document.getElementById('pixelFormat').value = cam.pixel_format || 'Y10';
    if (u.hls && video) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = u.hls + '/index.m3u8';
      } else {
        if (typeof Hls !== 'undefined' && Hls.isSupported()) {
          new Hls().loadSource(u.hls + '/index.m3u8').attachMedia(video);
        } else {
          video.src = u.hls;
        }
      }
    }
  }

  document.getElementById('btnRtspOn')?.addEventListener('click', async () => {
    await api('POST', '/camera/rtsp', { action: 'on' });
    loadStream();
  });
  document.getElementById('btnRtspOff')?.addEventListener('click', () => api('POST', '/camera/rtsp', { action: 'off' }));

  document.getElementById('resolution')?.addEventListener('change', (e) => {
    api('POST', '/camera/resolution', { value: e.target.value });
  });
  document.getElementById('fps')?.addEventListener('change', (e) => {
    api('POST', '/camera/fps', { value: e.target.value });
  });
  document.getElementById('shutter')?.addEventListener('change', (e) => {
    api('POST', '/camera/shutter', { value: e.target.value });
  });
  document.getElementById('gain')?.addEventListener('change', (e) => {
    api('POST', '/camera/gain', { value: e.target.value });
  });
  document.getElementById('pixelFormat')?.addEventListener('change', (e) => {
    api('POST', '/camera/pixel_format', { value: e.target.value });
  });

  document.querySelector('[data-tab="video"]')?.addEventListener('click', loadStream);

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
    const mqtt = await api('GET', '/config/mqtt');
    document.getElementById('mqttBroker').value = mqtt.broker || '';
    document.getElementById('mqttPort').value = mqtt.port || 1883;
    document.getElementById('mqttUser').value = mqtt.user || '';
    const wifi = await api('GET', '/config/wifi');
    if (wifi.ssid) document.getElementById('wifiSsid').value = wifi.ssid;
  })();

  // --- Init ---
  loadTheme();
  drawSpectrum();
})();
