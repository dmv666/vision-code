#version 330
#include "common.glsl"
#include "noise.glsl"

// Lago ártico: cortinas de aurora boreal sobre montañas, cielo estrellado y su
// reflejo ondulado en el agua.
//
// Loop: la aurora deriva u_travel·PERIOD celdas de ruido tileable por loop y
// evoluciona recorriendo un círculo (cos θ, sin θ) en la 2.ª coordenada del
// ruido, con θ = 2π·u_wobble·p. Las estrellas titilan con frecuencias enteras.

uniform float u_horizon;         // altura del agua
uniform float u_curtain_height;  // altura de las cortinas
uniform float u_intensity;
uniform float u_star_density;
uniform float u_ripple;          // ondulación del reflejo

const float PERIOD = 8.0;

float ridge(float x) {
    // Montañas estáticas: fbm con picos acentuados.
    float n = tfbm(vec2(x * 2.6 + 11.0, 1.7), 1e4, 5);
    float peaks = pow(n, 1.6);
    return u_horizon + 0.008 + 0.24 * peaks + 0.02 * sin(x * 2.3 + 1.0);
}

vec3 aurora(vec2 p) {
    float th = TAU * u_wobble * u_phase;
    vec2 cs = 0.8 * vec2(cos(th), sin(th));
    float X = p.x * 2.2 + u_travel * PERIOD * u_phase;          // en celdas de ruido

    // Línea base ondulada y pliegues de la cortina (deformación de dominio en x).
    float base = u_horizon + 0.12 + 0.12 * tfbm(vec2(X * 0.5, 3.0 + cs.x), PERIOD * 0.5, 3);
    float fold = tfbm(vec2(X, 7.0 + cs.y), PERIOD, 4);
    float xw = X + 2.0 * (fold - 0.5);
    float band = smoothstep(0.46, 0.76, tfbm(vec2(xw, 11.0 + cs.x * 0.6), PERIOD, 4));
    float streak = 0.2 + 0.8 * pow(tnoise(vec2(xw * 8.0, 2.0 + cs.y * 0.4), PERIOD * 8.0), 1.5);

    float h = p.y - base;
    float tall = u_curtain_height * (0.55 + 0.7 * band);
    float body = smoothstep(-0.015, 0.02, h) * exp(-max(h, 0.0) / tall);
    float edge = exp(-abs(h) / 0.012) * 0.9;                      // borde inferior brillante
    float I = band * streak * (body + edge) * u_intensity;

    float t = clamp(h / (u_curtain_height * 1.6), 0.0, 1.0);
    vec3 c = palette(0.02 + t * 0.6 + u_hue_cycles * u_phase);
    return c * I;
}

vec3 sky(vec2 p) {
    float hz = u_horizon;
    vec3 top = u_background;
    vec3 low = mix(u_background, palette(0.1), 0.08);
    vec3 col = mix(low, top, smoothstep(hz, hz + 0.6, p.y));

    // Estrellas: celdas fijas, titileo con 1–3 ciclos por loop.
    vec2 g = p * 140.0;
    vec2 id = floor(g);
    float hs = hash12(id + 3.7);
    if (hs > 1.0 - u_star_density) {
        vec2 sp = id + 0.5 + (vec2(hash12(id * 1.7), hash12(id * 2.3)) - 0.5) * 0.6;
        float d = length(g - sp);
        float tw = 0.55 + 0.45 * sin(TAU * (1.0 + floor(hs * 3.0)) * u_phase + hs * 40.0);
        float star = exp(-d * d * 14.0) * tw * (0.25 + 0.75 * pow(hash11(hs * 77.0), 3.0));
        col += vec3(0.85, 0.9, 1.0) * star * 0.6 * smoothstep(hz + 0.05, hz + 0.25, p.y);
    }

    vec3 au = aurora(p);
    col += au;
    // Resplandor difuso de la aurora sobre el cielo.
    col += palette(0.15) * 0.015 * smoothstep(hz + 0.4, hz, p.y);

    float m = ridge(p.x);
    if (p.y < m) {
        vec3 rock = mix(u_background * 0.6, palette(0.1) * 0.03, smoothstep(hz, m, p.y));
        // Luz de la aurora rozando las cumbres.
        rock += palette(0.05) * 0.06 * exp(-(m - p.y) / 0.01);
        col = rock;
    }
    return col;
}

void main() {
    vec2 uv = centered_uv();
    vec3 col;
    if (uv.y >= u_horizon) {
        col = sky(uv);
    } else {
        // Reflejo: espejo respecto al horizonte, ondulado con frecuencias enteras.
        float depth = u_horizon - uv.y;
        float th = TAU * u_phase;
        float wob = u_ripple * depth * (sin(uv.y * 160.0 + th * 3.0) + 0.6 * sin(uv.y * 97.0 - th * 2.0 + uv.x * 9.0));
        vec2 mp = vec2(uv.x + wob, 2.0 * u_horizon - uv.y);
        col = sky(mp) * 0.34 + u_background * 0.45;
        // Brillo horizontal del agua.
        col += palette(0.05) * 0.02 * pow(0.5 + 0.5 * sin(uv.y * 400.0 + uv.x * 3.0), 8.0) * exp(-depth * 6.0);
        col *= smoothstep(-0.55, u_horizon, uv.y) * 0.6 + 0.4;
    }
    emit(col);
}
