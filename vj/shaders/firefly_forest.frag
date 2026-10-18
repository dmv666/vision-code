#version 330
#include "common.glsl"
#include "noise.glsl"

// Bosque de luciérnagas: troncos en capas que se pierden en la niebla, hierba
// en primer plano y luciérnagas que vagan y parpadean.
//
// Loop: luciérnagas en trayectorias de Lissajous con frecuencias enteras y
// parpadeo entero; la niebla deriva PERIOD celdas tileables por loop.

uniform float u_fireflies;
uniform float u_fog;
uniform float u_trees;

const float PERIOD = 6.0;

// Troncos de una capa: devuelve cobertura (0–1).
float trunks(vec2 uv, float density, float scale, float seed) {
    float x = uv.x * scale;
    float cell = floor(x);
    float cover = 0.0;
    for (int k = -1; k <= 1; ++k) {
        float c = cell + float(k);
        float h = hash11(c * 1.37 + seed);
        if (h > density) continue;
        float cx = c + 0.5 + (hash11(c * 2.71 + seed) - 0.5) * 0.6;
        float w = 0.06 + 0.10 * hash11(c * 4.13 + seed);
        float lean = (hash11(c * 5.9 + seed) - 0.5) * 0.15;
        float dx = abs(x - cx - lean * uv.y * scale) - w * (1.0 + 0.4 * smoothstep(-0.2, -0.5, uv.y));
        cover = max(cover, smoothstep(0.015, -0.015, dx));
    }
    return cover;
}

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;

    // Cielo nocturno entre copas: verde azulado muy oscuro, algo más claro en el centro.
    vec3 col = u_background + palette(0.6) * 0.05 * exp(-length(uv - vec2(0.0, 0.15)) / 0.6);
    // Claro del bosque al fondo: niebla iluminada que recorta las siluetas.
    col += palette(0.5) * 0.16 * exp(-length((uv - vec2(0.12, -0.06)) * vec2(0.8, 1.7)) / 0.32);

    // Niebla tileable que deriva despacio.
    float X = uv.x * 1.8 + max(u_travel, 1.0) * PERIOD * u_phase;
    float fogn = tfbm(vec2(X, uv.y * 2.5 + 0.7 * sin(th)), PERIOD, 4);
    float fogmask = smoothstep(0.35, 0.8, fogn) * smoothstep(0.45, -0.2, uv.y);

    // Capas de troncos: lejos (claros por la niebla) → cerca (siluetas).
    vec3 layer_col[3];
    layer_col[0] = mix(u_background, palette(0.55) * 0.30, 0.8);
    layer_col[1] = mix(u_background, palette(0.6) * 0.12, 0.6);
    layer_col[2] = u_background * 0.35;
    float scales[3];
    scales[0] = 9.0; scales[1] = 5.0; scales[2] = 2.6;

    // Luciérnagas: cada una pertenece a una capa (0 lejos … 2 cerca).
    int nf = int(u_fireflies);
    for (int l = 0; l < 3; ++l) {
        float cov = trunks(uv, u_trees, scales[l], float(l) * 17.0);
        col = mix(col, layer_col[l], cov);
        // Niebla entre capas.
        col += palette(0.55) * fogmask * u_fog * 0.07 * (1.0 - float(l) * 0.35);

        for (int i = 0; i < 64; ++i) {
            if (i >= nf) break;
            float fi = float(i);
            if (int(floor(hash11(fi * 9.7) * 3.0)) != l) continue;
            float h1 = hash11(fi * 1.7), h2 = hash11(fi * 2.3), h3 = hash11(fi * 3.9);
            float a = 1.0 + floor(h1 * 2.0), b = 1.0 + floor(h2 * 2.0), c = 2.0 + floor(h3 * 3.0);
            vec2 base = (vec2(h1, h2) - 0.5) * vec2(1.6, 0.6) + vec2(0.0, -0.08);
            vec2 pos = base + vec2(0.10 * sin(TAU * a * u_phase + h3 * TAU),
                                   0.05 * sin(TAU * b * u_phase + h1 * TAU));
            float blink = pow(max(0.0, sin(TAU * c * u_phase + h2 * TAU)), 3.0);
            float size = 0.003 * (1.0 + float(l) * 0.6);
            float d = length(uv - pos);
            float glow = exp(-d / size) + 0.25 * exp(-d / (size * 8.0));
            col += palette(0.1 + 0.15 * h3) * glow * blink * (0.9 + 0.9 * float(l) / 2.0);
        }
    }

    // Copas: el bosque se cierra arriba.
    col *= 0.45 + 0.55 * smoothstep(0.62, 0.15, uv.y);

    // Hierba en primer plano.
    float gy = -0.36 + 0.02 * sin(uv.x * 5.0 + 1.0);
    float blades = 0.03 * pow(abs(sin(uv.x * 140.0 + sin(uv.x * 23.0) * 3.0)), 3.0)
                 * (0.6 + 0.4 * sin(uv.x * 37.0 + 0.4 * sin(th)));
    float grass = smoothstep(0.003, -0.003, uv.y - (gy + blades));
    col = mix(col, u_background * 0.2, grass);
    emit(col);
}
