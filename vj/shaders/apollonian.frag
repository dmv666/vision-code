#version 330
#include "common.glsl"

// Encaje apoloniano: fractal de inversiones circulares (círculos dentro de
// círculos hasta el infinito) con trampas orbitales para el color.
//
// Loop: el fractal repite cada 2 unidades → se desplaza 2·fract(u_travel·fase)
// en diagonal; el factor de inversión “respira” con u_wobble ciclos enteros.

uniform float u_zoom;
uniform float u_iterations;
uniform float u_morph;        // amplitud de la respiración del fractal
uniform float u_line_width;
uniform float u_glow;

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);

    vec2 p = rot(TAU * u_rotation * u_phase + 0.3) * uv * (2.0 / u_zoom);
    p += vec2(2.0, 2.0) * fract(u_travel * u_phase) + vec2(0.35, 0.1);

    float k0 = 1.15 + u_morph * sin(th * max(u_wobble, 1.0));
    float sc = 1.0;
    vec3 trap = vec3(1e9);
    int n = int(u_iterations);
    for (int i = 0; i < 16; ++i) {
        if (i >= n) break;
        p = -1.0 + 2.0 * fract(0.5 * p + 0.5);
        float r2 = dot(p, p);
        trap = min(trap, vec3(abs(p.x), abs(p.y), r2));
        float k = k0 / r2;
        p *= k;
        sc *= k;
    }
    float d = 0.25 * abs(p.y) / sc;                    // distancia al encaje
    float fw = fwidth(d) + 1e-6;
    float lw = u_line_width * (1.0 + 0.8 * u_pulse_strength * kick);
    float line = line_aa(d, lw, fw, 0.08);
    float hue = log(trap.z + 1e-3) * 0.12 + trap.x * 0.4 + u_hue_cycles * u_phase;
    float wave = pulse(-log(trap.z + 1e-3) * 0.15);
    vec3 col = u_background;
    col += palette(hue) * line * 0.8 * (1.0 + 1.5 * u_pulse_strength * wave);
    col += palette(hue + 0.4) * exp(-d / (lw * 4.0)) * 0.12 * u_glow;
    col += palette(hue + 0.7) * exp(-trap.y * 30.0) * 0.12 * u_glow;
    emit(col);
}
