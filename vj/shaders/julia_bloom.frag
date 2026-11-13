#version 330
#include "common.glsl"

// Flor de Julia: conjunto de Julia z → z² + c con c recorriendo un círculo en el
// plano complejo (u_wobble vueltas enteras por loop) → la forma muta sin parar y
// vuelve exactamente a la inicial. Simetría radial opcional por pliegue espejo,
// coloreado suave (escape continuo) + trampa orbital para filamentos brillantes.

uniform float u_iterations;
uniform float u_radius;       // |c|: 0.7885 = la clásica “galaxia”
uniform float u_zoom;
uniform float u_symmetry;     // 0/1 = sin pliegue; 2..12 = espejos
uniform float u_glow;
uniform float u_flow;         // velocidad del color hacia dentro (× u_travel)

void main() {
    vec2 uv = centered_uv();
        float kick = pulse(0.0);

    uv = rot(cyc(u_rotation)) * uv;
    if (u_symmetry >= 2.0) {
        float seg = TAU / u_symmetry;
        float a = atan(uv.y, uv.x);
        a = abs(mod(a, seg) - 0.5 * seg);
        uv = length(uv) * vec2(cos(a), sin(a));
    }
    float breathe = 1.0 + 0.06 * sin(cyc(max(u_wobble, 1.0) * 2.0));
    vec2 z = uv * (2.6 / u_zoom) * breathe;

    float ang = 2.0 + cyc(max(u_wobble, 1.0));
    vec2 c = u_radius * vec2(cos(ang), sin(ang));

    int n = int(u_iterations);
    float i_esc = float(n);
    float trap = 1e9;
    float m2 = 0.0;
    for (int i = 0; i < 400; ++i) {
        if (i >= n) break;
        z = vec2(z.x * z.x - z.y * z.y, 2.0 * z.x * z.y) + c;
        m2 = dot(z, z);
        trap = min(trap, abs(z.x * z.y));            // cruz: filamentos finos
        if (m2 > 256.0) { i_esc = float(i); break; }
    }

    vec3 col = u_background;
    float flow = fract(u_travel * u_flow * u_phase);
    if (i_esc < float(n)) {
        float sn = i_esc - log2(log2(m2)) + 4.0;     // iteración continua
        float t = sn / 48.0;
        float near = clamp(t * 1.4, 0.0, 1.0);       // lejos del conjunto: oscuro
        float hue = t * 1.6 - flow + fract(u_hue_cycles * u_phase);
        col += palette(hue) * near * near * 0.8;
        col += palette(hue + 0.33) * pow(near, 7.0) * 0.9 * u_glow
             * (1.0 + u_pulse_strength * pulse(-t * 2.0));
    } else {
        // Interior: brillo tenue según la trampa orbital.
        col += palette(0.5 + log(trap + 1e-4) * 0.05 - flow) * 0.05;
    }
    float f = exp(-trap * 18.0);
    col += palette(log(trap + 1e-3) * 0.08 - flow + 0.6) * f * 0.35 * u_glow * (1.0 + kick * u_pulse_strength);
    emit(col);
}
