#version 330
#include "common.glsl"

// Caleidoscopio con zoom infinito en coordenadas log-polares.
// En log-polar, escalar la imagen = desplazar log(r). Desplazar u_travel celdas
// enteras por loop produce un zoom infinito que cierra perfectamente.

uniform float u_segments;
uniform float u_zoom;
uniform float u_complexity;
uniform float u_line_width;

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);

    float r = max(length(uv), 1e-5);
    float seg = TAU / u_segments;
    float a = atan(uv.y, uv.x) + TAU * u_rotation * u_phase;
    a = abs(mod(a, seg) - 0.5 * seg);               // pliegue espejo (continuo)

    float lr = log(r);
    vec2 q = vec2(lr * u_zoom * 2.0 - u_travel * u_phase, a * u_zoom * 2.0);
    vec2 f = fract(q) - 0.5;

    // Pliegues iterativos (KIFS) con rotación periódica.
    int iters = int(u_complexity);
    for (int i = 0; i < iters; ++i) {
        f = abs(f) - 0.22;
        f = rot(0.6 + 0.35 * sin(th * u_wobble + float(i) * 1.9)) * f;
        f *= 1.25;
    }

    // Hexágono + círculo en el espacio plegado.
    vec2 h = abs(f);
    float hex = max(dot(h, normalize(vec2(1.0, 1.7320508))), h.x) - 0.28;
    float circ = length(f) - 0.12 - 0.05 * u_pulse_strength * kick;
    float fw_h = fwidth(hex);
    float fw_c = fwidth(circ);

    float lw = u_line_width * (1.0 + 0.6 * u_pulse_strength * kick);
    float l1 = line_aa(abs(hex), lw, fw_h, 0.5);
    float l2 = line_aa(abs(circ), lw * 0.6, fw_c, 0.5);
    float glow = exp(-abs(hex) / (lw * 1.5)) * 0.2 * (1.0 - smoothstep(0.1, 0.5, fw_h / 0.5));

    float wave = pulse(-lr * 0.35);                 // anillos de pulso hacia afuera
    float hue = lr * 0.3 + a * 0.4 + u_hue_cycles * u_phase;
    vec3 col = palette(hue) * (l1 * (1.0 + 2.0 * u_pulse_strength * wave) + glow)
             + palette(hue + 0.5) * l2 * 0.8;

    col *= smoothstep(0.0, 0.12, r);                // el centro converge a negro (sin aliasing)
    col += palette(u_hue_cycles * u_phase) * exp(-r * 10.0) * 0.4 * (0.4 + kick * u_pulse_strength);
    emit(col + u_background);
}
