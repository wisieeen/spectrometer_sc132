import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider

# ======= FUNKCJE =======
def diffraction_angle(lam, d, theta_i, m):
    sin_theta = (m * lam / d) - np.sin(theta_i)
    if abs(sin_theta) > 1:
        return None
    return np.arcsin(sin_theta)

def ray(ax, theta, color, lw=2, label=None, alpha=1.0):
    x = np.sin(theta)
    y = np.cos(theta)
    ax.plot([0, x], [0, y], color=color, lw=lw, alpha=alpha, label=label)

# ======= FIGURA =======
fig, ax = plt.subplots(figsize=(6, 6))
plt.subplots_adjust(bottom=0.35)

# Podłoże (siatka)
ax.plot([-1, 1], [0, 0], lw=6, color='gray')

# Normalna
normal_line, = ax.plot([0, 0], [0, 1], color='black', lw=2)

# ======= PARAMETRY POCZĄTKOWE =======
lines_mm_0 = 1200
lambda1_0 = 700
lambda2_0 = 400
theta_i_0 = 30

# ======= SUWAKI =======
ax_lpm = plt.axes([0.15, 0.25, 0.7, 0.03])
ax_l1  = plt.axes([0.15, 0.20, 0.7, 0.03])
ax_l2  = plt.axes([0.15, 0.15, 0.7, 0.03])
ax_th  = plt.axes([0.15, 0.10, 0.7, 0.03])

s_lpm = Slider(ax_lpm, 'linie / mm', 300, 3000, valinit=lines_mm_0, valstep=10)
s_l1  = Slider(ax_l1, 'λ₁ [nm]', 200, 900, valinit=lambda1_0)
s_l2  = Slider(ax_l2, 'λ₂ [nm]', 200, 900, valinit=lambda2_0)
s_th  = Slider(ax_th, 'θ₀ [°]', 0, 80, valinit=theta_i_0)

# ======= RYSOWANIE =======
def update(val):
    ax.cla()

    # Podłoże
    ax.plot([-1, 1], [0, 0], lw=6, color='gray')
    ax.plot([0, 0], [0, 1], color='black', lw=2)

    # Dane
    lines_mm = s_lpm.val
    lam1 = s_l1.val * 1e-9
    lam2 = s_l2.val * 1e-9
    theta_i = np.deg2rad(s_th.val)

    d = 1e-3 / lines_mm

    # Promień padający
    ray(ax, -theta_i, color='lightgray', lw=2, label='padanie')

    # Dyfrakcja: m = 1, 2
    for m, alpha in zip([1, 2], [1.0, 0.5]):
        t1 = diffraction_angle(lam1, d, theta_i, m)
        t2 = diffraction_angle(lam2, d, theta_i, m)

        if t1 is not None:
            ray(ax, t1, color='red', lw=2,
                label=f'λ₁={s_l1.val:.0f} nm, m={m}', alpha=alpha)

        if t2 is not None:
            ray(ax, t2, color='blue', lw=2,
                label=f'λ₂={s_l2.val:.0f} nm, m={m}', alpha=alpha)

    ax.set_aspect('equal')
    ax.set_xlim(-1, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.legend(loc='upper right', fontsize=8)

    fig.canvas.draw_idle()

# ======= PODPIĘCIE =======
s_lpm.on_changed(update)
s_l1.on_changed(update)
s_l2.on_changed(update)
s_th.on_changed(update)

update(None)
plt.show()
