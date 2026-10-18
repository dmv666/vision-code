#version 330
#include "common.glsl"

// Estanque zen visto desde arriba: gotas de lluvia que abren ondas sobre agua
// oscura con el reflejo de la luna, hojas de loto que giran despacio y una flor.
//
// Loop: cada "ranura" de gota se repite c veces por loop (c entero) y su
// posición sale de hash(ranura, índice mod c), así que en p = 1 todo coincide.

uniform float u_drops;        // ranuras de gotas simultáneas
uniform float u_ripple_size;
uniform float u_pads;         // hojas de loto (0–5)

float ripples(vec2 p) {
    float h = 0.0;
    int n = int(u_drops);
    for (int s = 0; s < 16; ++s) {
        if (s >= n) break;
        float fs = float(s);
        float h0 = hash11(fs * 7.13 + 0.3);
        float c = max(u_travel, 1.0) * (1.0 + floor(hash11(fs * 3.31) * 2.0));
        float cyc = u_phase * c + h0;
        float age = fract(cyc);
        float idx = imod(floor(cyc), c);
        vec2 ctr = (vec2(hash12(vec2(fs, idx) + 0.5), hash12(vec2(idx, fs) + 9.1)) - 0.5) * vec2(1.7, 0.95);
        float r = length(p - ctr);
        float front = age * u_ripple_size;
        float width = 0.015 + 0.05 * age;
        float x = r - front;
        h += sin(x * 90.0) * exp(-(x * x) / (width * width)) * pow(1.0 - age, 2.0);
    }
    return h;
}

void main() {
    vec2 uv = centered_uv();
    float e = 1.5 / u_resolution.y;

    // Normal del agua por diferencias finitas de la altura de las ondas.
    float h = ripples(uv);
    float hx = ripples(uv + vec2(e, 0.0));
    float hy = ripples(uv + vec2(0.0, e));
    vec3 n = normalize(vec3(-(hx - h) / e * 0.004, -(hy - h) / e * 0.004, 1.0));

    // Agua: azul tinta, más clara hacia el reflejo de la luna.
    vec2 moon = vec2(0.32, 0.12);
    vec3 col = u_background + palette(0.55) * 0.025 * (0.5 + 0.5 * uv.y);
    vec2 md = (uv - moon) / vec2(0.05, 0.20);
    float glow = exp(-dot(md, md));
    // El reflejo tiembla con las normales de las ondas.
    float sparkle = pow(clamp(0.5 + n.x * 6.0 + n.y * 4.0, 0.0, 1.0), 3.0);
    col += palette(0.0) * (glow * 0.22 + glow * sparkle * 0.55);
    // Reflejo especular del cielo en las crestas de las ondas.
    col += mix(palette(0.0), palette(0.6), 0.3) * pow(clamp(length(n.xy) * 9.0, 0.0, 1.0), 2.0) * 0.07;

    // Hojas de loto: giran 1 vuelta por loop como máximo (u_rotation entero).
    int np = int(u_pads);
    for (int i = 0; i < 5; ++i) {
        if (i >= np) break;
        float fi = float(i);
        vec2 c = (vec2(hash11(fi * 4.1 + 0.2), hash11(fi * 6.3 + 0.8)) - 0.5) * vec2(1.4, 0.7);
        c += 0.015 * vec2(cos(TAU * u_phase + fi), sin(TAU * u_phase + fi));
        float r = 0.06 + 0.05 * hash11(fi * 2.9);
        float dir = (i % 2 == 0) ? 1.0 : -1.0;
        float ang = hash11(fi * 8.7) * TAU + dir * TAU * u_rotation * u_phase;
        vec2 q = rot(-ang) * (uv - c);
        float a = atan(q.y, q.x);
        float rr = length(q);
        float inside = smoothstep(r, r - 0.003, rr) * smoothstep(0.18, 0.24, abs(a));
        // Sombra sobre el agua.
        col *= 1.0 - 0.45 * smoothstep(r + 0.03, r - 0.01, length(uv - c - vec2(0.01, -0.012)));
        vec3 leaf = palette(0.3) * (0.18 + 0.025 * sin(a * 14.0)) * (0.7 + 0.3 * rr / r);
        leaf += palette(0.35) * 0.08 * exp(-abs(r - rr) / 0.006);        // borde iluminado (abs: sin overflow fuera de la hoja)
        col = mix(col, leaf, inside);
        // Una flor sobre la primera hoja.
        if (i == 0) {
            vec2 fq = q - vec2(-0.3 * r, 0.1 * r);
            float fa = atan(fq.y, fq.x);
            float petals = 0.5 + 0.5 * cos(fa * 8.0);
            float fr = length(fq);
            float flower = smoothstep(0.035 * (0.6 + 0.4 * petals), 0.03 * (0.6 + 0.4 * petals), fr);
            vec3 pink = palette(0.85) * (0.6 + 0.4 * petals) + vec3(1.0, 0.9, 0.6) * exp(-fr / 0.006) * 0.8;
            col = mix(col, pink, flower);
            col += palette(0.85) * 0.06 * exp(-fr / 0.05);
        }
    }
    emit(col);
}
