/**
 * Spectrum Chart Card for Home Assistant
 * Displays wavelength vs intensity from sensor.spectrometer_spectrum_ch0 attributes.
 * Download CSV: saves [wavelength,intensity] pairs per line.
 * Requires: Copy to HA www/ folder, add as Lovelace resource.
 */
class SpectrumCard extends HTMLElement {
  setConfig(config) {
    this.config = config;
    this.entity = config.entity || "sensor.spectrometer_spectrum_ch0";
    this.title = config.title || "Spectrum";
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this.entity];
    const w = state?.attributes?.wavelengths_nm;
    const i = state?.attributes?.intensities;
    const hasData = Array.isArray(w) && Array.isArray(i) && w.length > 0;
    if (hasData && (JSON.stringify(w) !== this._lastW || JSON.stringify(i) !== this._lastI)) {
      this._lastW = JSON.stringify(w);
      this._lastI = JSON.stringify(i);
      this._renderChart(w, i);
    } else if (!hasData && this._chart) {
      this._chart.destroy();
      this._chart = null;
    }
  }

  _crosshairPlugin(wavelengths, intensities) {
    return {
      id: "spectrumCrosshair",
      afterInit(chart) {
        chart.crosshair = { x: null };
        const onMove = (e) => {
          const rect = chart.canvas.getBoundingClientRect();
          const x = e.clientX - rect.left;
          chart.crosshair.x = x >= 0 && x <= rect.width ? x : null;
          chart.update("none");
        };
        chart.canvas.addEventListener("mousemove", onMove);
        chart.canvas.addEventListener("mouseleave", () => { chart.crosshair.x = null; chart.update("none"); });
      },
      afterDraw(chart) {
        if (chart.crosshair.x == null) return;
        const ctx = chart.ctx;
        const xScale = chart.scales.x;
        const yScale = chart.scales.y;
        const idx = Math.round((chart.crosshair.x - xScale.left) / (xScale.right - xScale.left) * (wavelengths.length - 1));
        const i = Math.max(0, Math.min(idx, wavelengths.length - 1));
        const wl = wavelengths[i];
        const val = intensities[i];
        const py = yScale.getPixelForValue(val);
        ctx.save();
        ctx.strokeStyle = "rgba(255,255,255,0.6)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(chart.crosshair.x, yScale.top);
        ctx.lineTo(chart.crosshair.x, yScale.bottom);
        ctx.moveTo(xScale.left, py);
        ctx.lineTo(xScale.right, py);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = "12px sans-serif";
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        const txt = wl.toFixed(1) + " nm, " + val.toFixed(1);
        const tx = chart.crosshair.x > (xScale.left + xScale.right) / 2 ? chart.crosshair.x - ctx.measureText(txt).width - 8 : chart.crosshair.x + 8;
        ctx.fillText(txt, tx, py - 8);
        ctx.restore();
      },
    };
  }

  _downloadCSV() {
    if (!this._lastW || !this._lastI) return;
    const w = JSON.parse(this._lastW);
    const i = JSON.parse(this._lastI);
    if (!Array.isArray(w) || !Array.isArray(i) || w.length === 0 || w.length !== i.length) return;
    const lines = ["wavelength,intensity"];
    for (let idx = 0; idx < w.length; idx++) {
      lines.push(`${w[idx]},${i[idx]}`);
    }
    const csv = lines.join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `spectrum_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  _renderChart(wavelengths, intensities) {
    if (!window.Chart) {
      this._loadChartJs().then(() => this._renderChart(wavelengths, intensities));
      return;
    }
    const canvas = this.querySelector("canvas");
    if (!canvas) return;
    if (this._chart) this._chart.destroy();
    this._chart = new window.Chart(canvas.getContext("2d"), {
      type: "line",
      plugins: [this._crosshairPlugin(wavelengths, intensities)],
      data: {
        labels: wavelengths.map((v) => v.toFixed(1)),
        datasets: [{
          label: "Intensity",
          data: intensities,
          borderColor: "rgb(3, 169, 244)",
          backgroundColor: "rgba(3, 169, 244, 0.2)",
          borderWidth: 1,
          fill: true,
          tension: 0,
          pointRadius: 0,
          pointHoverRadius: 0,
          pointBackgroundColor: "transparent",
          pointBorderColor: "transparent",
          pointBorderWidth: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: { padding: { left: 4, right: 4 } },
        plugins: { legend: { display: false } },
        elements: { point: { radius: 0, hoverRadius: 0, borderWidth: 0 } },
        scales: {
          x: {
            title: { display: true, text: "Wavelength (nm)" },
            ticks: { maxTicksLimit: 12 },
          },
          y: {
            title: { display: true, text: "Intensity" },
            beginAtZero: true,
          },
        },
      },
    });
  }

  _loadChartJs() {
    return new Promise((resolve) => {
      if (window.Chart) { resolve(); return; }
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js";
      s.onload = resolve;
      document.head.appendChild(s);
    });
  }

  connectedCallback() {
    const title = (this.config && this.config.title) || "Spectrum";
    this.innerHTML = `
      <ha-card header="${title}" style="width:100%;">
        <div style="padding:8px;height:400px;position:relative;width:100%;cursor:crosshair;">
          <canvas id="spectrum-canvas" style="width:100%;height:100%;cursor:crosshair;"></canvas>
        </div>
        <div style="padding:8px 16px 16px;display:flex;justify-content:flex-end;">
          <ha-icon-button
            id="spectrum-download-btn"
            title="Download CSV"
            style="--mdc-icon-button-size:40px;"
          >
            <ha-icon icon="mdi:download"></ha-icon>
          </ha-icon-button>
        </div>
      </ha-card>
    `;
    this.querySelector("#spectrum-download-btn").addEventListener("click", () => this._downloadCSV());
  }
}

customElements.define("spectrum-card", SpectrumCard);

// HA card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "custom:spectrum-card",
  name: "Spectrum Chart",
  description: "Wavelength vs intensity from spectrometer sensor attributes. Download CSV.",
});
