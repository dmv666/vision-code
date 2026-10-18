#version 330
#include "common.glsl"
#include "noise.glsl"

// Atardecer en el desierto: capas de dunas en paralaje con sombreado por
// pendiente, sol bajo, nubes finas que derivan, calima y pájaros a lo lejos.
//
// Loop: cada duna es una suma de senos de periodo 1 en su coordenada u; se
// desplaza un número entero de periodos por loop. Nubes con ruido tileable;
// pájaros cruzan la pantalla un número entero de veces.

uniform float u_horizon;
uniform float u_sun_size;
uniform float u_birds;

const float PERIOD = 4.0;

float dune(float u, float seed) {
    float h = 0.50 * sin(TAU * u + seed)
            + 0.22 * sin(TAU * 2.0 * u + seed * 1.7 + 1.3)
            + 0.10 * sin(TAU * 3.0 * u + seed * 2.3 + 0.4);
    // Crestas más afiladas que los valles.
    return h + 0.18 * (1.0 - abs(sin(TAU * u + seed + 0.6)));
}

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;

    // Calima sobre el horizonte.
    uv.x += 0.0025 * sin(uv.y * 220.0 + th * 3.0) * exp(-abs(uv.y - u_horizon) / 0.04);

    // Cielo: violeta arriba → melocotón en el horizonte.
    // Cielo: melocotón en el horizonte → rosa → violeta profundo arriba.
    float hy = uv.y - u_horizon;
    vec3 col = mix(palette(0.62), palette(0.45) * 0.8, smoothstep(0.0, 0.18, hy));
    col = mix(col, palette(0.82) * 0.35 + u_background, smoothstep(0.12, 0.5, hy));

    // Sol bajo y su halo.
    vec2 sun = vec2(-0.32, u_horizon + 0.06);
    float sd = length(uv - sun);
    col += vec3(1.0, 0.62, 0.35) * 0.30 * exp(-sd / 0.22) + vec3(1.0, 0.8, 0.55) * 0.25 * exp(-sd / 0.06);
    col = mix(col, vec3(1.0, 0.70, 0.42) * 1.05, smoothstep(u_sun_size, u_sun_size - 0.006, sd));

    // Nubes finas que derivan (ruido tileable estirado en horizontal).
    float X = uv.x * 1.6 + u_travel * PERIOD * u_phase;
    float cl = tfbm(vec2(X, uv.y * 26.0), PERIOD, 4);
    float band = smoothstep(0.05, 0.12, uv.y - u_horizon) * smoothstep(0.42, 0.15, uv.y - u_horizon);
    float cloud = smoothstep(0.55, 0.85, cl) * band;
    vec3 lit = mix(palette(0.55), vec3(1.0, 0.8, 0.6), exp(-abs(uv.x - sun.x) / 0.5) * 0.6);
    col = mix(col, lit * 0.5, cloud * 0.6);

    // Pájaros: "v" que aletean, cruzando de derecha a izquierda.
    int nb = int(u_birds);
    for (int i = 0; i < 6; ++i) {
        if (i >= nb) break;
        float fi = float(i);
        float hx = hash11(fi * 3.3 + 0.1);
        float bx = 1.1 - fract(hx + max(u_travel, 1.0) * u_phase) * 2.2;
        float by = u_horizon + 0.17 + 0.12 * hash11(fi * 5.7) + 0.01 * sin(th * 3.0 + fi);
        float s = 0.010 + 0.006 * hash11(fi * 1.9);
        float flap = 0.6 * sin(TAU * 24.0 * u_phase + fi * 2.0);
        vec2 q = (uv - vec2(bx, by)) / s;
        vec2 wl = vec2(-1.0, 0.4 + flap), wr = vec2(1.0, 0.4 + flap);
        float d = min(length(q - wl * clamp(dot(q, wl) / dot(wl, wl), 0.0, 1.0)),
                      length(q - wr * clamp(dot(q, wr) / dot(wr, wr), 0.0, 1.0)));
        col = mix(col, u_background * 1.2, smoothstep(0.22, 0.08, d) * 0.85);
    }

    // Dunas de lejos a cerca: más contraste y más rápidas cuanto más cerca.
    vec2 L = normalize(vec2(sun.x - 0.5, 0.35));      // luz rasante desde el sol
    for (int l = 0; l < 4; ++l) {
        float fl = float(l);
        float freq = 0.55 + 0.35 * fl;
        float speed = max(u_travel, 1.0) * (fl + 1.0);  // ciclos enteros por loop
        float seed = 1.7 * fl + 0.3;
        float u = uv.x * freq + speed * u_phase;
        float amp = 0.035 + 0.025 * fl;
        float base = u_horizon - 0.035 - 0.105 * fl;
        float y = base + amp * dune(u, seed);
        if (uv.y < y) {
            // La pendiente se mide un poco desplazada según la profundidad bajo la
            // cresta: los límites luz/sombra quedan inclinados, como caras de duna.
            float us = u + (y - uv.y) * freq * 1.6;
            float dy = (dune(us + 0.002, seed) - dune(us - 0.002, seed)) / 0.004 * amp * freq;
            float slope_lit = clamp(0.5 - dy * 1.2, 0.0, 1.0);
            float far = 1.0 - fl / 3.0;
            vec3 shadow = palette(0.82) * 0.10 + u_background * 0.5;
            vec3 sunny = palette(0.08) * (0.62 - 0.08 * fl);
            vec3 c = mix(shadow, sunny, smoothstep(0.25, 0.75, slope_lit));
            // Más oscuro cuanto más bajo respecto a la cresta (evita bandas verticales planas).
            c = mix(c, shadow, smoothstep(0.0, 0.10 + 0.05 * fl, y - uv.y) * 0.5);
            // Perspectiva atmosférica: las lejanas se funden con el horizonte.
            c = mix(c, palette(0.62) * 0.55, far * 0.6);
            // Borde iluminado en la cresta.
            c += vec3(1.0, 0.75, 0.5) * 0.25 * exp(-(y - uv.y) / 0.003) * slope_lit;
            // Rizos de arena en la duna más cercana.
            if (l == 3) c *= 0.96 + 0.04 * sin(uv.y * 320.0 + 6.0 * sin(uv.x * 9.0 + u * TAU));
            col = c;
        }
    }
    emit(col);
}
