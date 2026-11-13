#version 330
#include "common.glsl"

// Cuasicristal: suma de N ondas planas a ángulos kπ/N. Con N impar ≥ 5 el patrón
// nunca se repite en el espacio (orden sin periodicidad, como un mosaico de
// Penrose) y al desfasar las ondas “respira” en flores y estrellas.
//
// Loop: cada onda se desplaza u_travel ciclos enteros por loop.

uniform float u_waves;
uniform float u_frequency;
uniform float u_sharpness;    // 0 = suave · 1 = líneas finas tipo grabado
uniform float u_warp;
uniform float u_bands;

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);

    uv = rot(TAU * u_rotation * u_phase) * uv;
    float r = length(uv);
    // Torsión radial suave y periódica.
    uv = rot(u_warp * r * sin(th * u_wobble) ) * uv;

    int n = int(u_waves);
    float s = 0.0;
    for (int k = 0; k < 24; ++k) {
        if (k >= n) break;
        float a = PI * float(k) / float(n);
        vec2 d = vec2(cos(a), sin(a));
        float dir = (k % 2 == 0) ? 1.0 : -1.0;
        s += cos(dot(uv, d) * u_frequency * TAU + dir * th * u_travel);
    }
    s /= float(n);                                    // [-1, 1]

    float v = s * 0.5 + 0.5;
    float bands = v * u_bands;
    float fb = fwidth(bands) + 1e-5;
    float dline = abs(fract(bands) - 0.5);
    float lw = mix(0.35, 0.06, u_sharpness) * (1.0 + 0.6 * u_pulse_strength * kick);
    float line = line_aa(0.5 - dline, lw * 0.5, fb, 1.0);
    float hue = v * 0.8 + floor(bands) / u_bands * 0.3 + u_hue_cycles * u_phase;
    float wave = pulse(-r * 1.5);
    vec3 col = u_background;
    col += palette(hue) * line * (0.6 + 1.4 * u_pulse_strength * wave);
    col += palette(hue + 0.5) * pow(v, 6.0) * 0.9;     // nodos brillantes (estrellas)
    col += palette(hue + 0.25) * 0.05 * v;
    emit(col);
}
