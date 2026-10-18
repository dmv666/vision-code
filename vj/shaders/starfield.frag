#version 330
#include "common.glsl"

// Campo de estrellas en hiperespacio: L capas de estrellas que viajan de lejos
// a cerca. Cada capa recorre exactamente u_travel ciclos de profundidad por
// loop: depth = fract(k/L + u_travel·p) → en p = 1 cada capa vuelve a su sitio.
// Combínalo con motion_blur (shutter alto) para obtener estelas de warp.

uniform float u_layers;
uniform float u_density;     // fracción de celdas con estrella
uniform float u_size;
uniform float u_far_scale;   // densidad aparente de la capa más lejana
uniform float u_streak;      // estiramiento radial de las estrellas cercanas
uniform float u_twinkle;

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);
    uv = rot(TAU * u_rotation * u_phase) * uv;

    vec3 acc = vec3(0.0);
    int layers = int(u_layers);
    for (int k = 0; k < layers; ++k) {
        float fk = float(k);
        float depth = fract(fk / u_layers + u_travel * u_phase);   // 0 = lejos, 1 = encima
        float scale = mix(u_far_scale, 0.6, depth * depth);
        float fade = smoothstep(0.0, 0.25, depth) * smoothstep(1.0, 0.8, depth);

        // Las estrellas cercanas se alargan en dirección radial (efecto warp).
        vec2 radial = normalize(uv + 1e-5);
        float stretch = 1.0 + u_streak * depth * depth;
        float cell_fade = 1.0;

        vec2 p = rot(fk * 2.399) * uv * scale + fk * 17.3;
        vec2 id = floor(p);
        vec2 f = fract(p) - 0.5;
        float h = hash12(id + fk * 31.7);
        if (h < 1.0 - u_density) continue;

        vec2 star = (vec2(hash12(id * 1.3 + 7.1), hash12(id * 0.7 - 3.3)) - 0.5) * 0.4;
        vec2 d = f - star;
        // Distancia anisótropa: se estira a lo largo del eje radial (rotado al espacio de la capa).
        vec2 rdir = rot(fk * 2.399) * radial;
        float dl = dot(d, rdir) / stretch;
        float dp = dot(d, vec2(-rdir.y, rdir.x));
        float d2 = dl * dl + dp * dp;

        float sz = u_size * (0.6 + 0.8 * hash11(h * 91.0)) * (1.0 + 0.5 * u_pulse_strength * kick);
        float core = sz * sz / (d2 + sz * sz);
        float tw = 1.0 - u_twinkle * (0.5 + 0.5 * sin(th * u_wobble * 3.0 + h * 50.0));
        vec3 c = palette(h * 3.0 + u_hue_cycles * u_phase);
        // Recorte suave en el borde de la celda: evita estelas cortadas en cuadrado.
        cell_fade = smoothstep(0.5, 0.35, max(abs(f.x), abs(f.y)));
        acc += c * (core * core * 1.2 + core * 0.012) * fade * tw * cell_fade * (0.3 + depth);
    }

    float r = length(uv);
    acc += palette(u_hue_cycles * u_phase + 0.3) * exp(-r * 6.0) * 0.08 * (1.0 + u_pulse_strength * kick);
    emit(acc + u_background);
}
