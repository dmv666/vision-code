#version 330
#include "common.glsl"

// Mosaico hiperbólico {p,q} en el disco de Poincaré (como los “Circle Limit” de
// Escher). Cada píxel se pliega al triángulo fundamental con reflexiones en dos
// rectas y una inversión en el círculo ortogonal; el número de inversiones da la
// “profundidad” (anillos de teselas hacia el borde).
//
// Loop: el disco gira u_rotation vueltas enteras y se traslada con una isometría
// de Möbius cuyo desplazamiento recorre un círculo (u_wobble vueltas); el color
// fluye hacia el borde con fract(·, u_travel) entero.

uniform float u_p;            // lados de cada polígono
uniform float u_q;            // polígonos por vértice   (1/p + 1/q < 1/2)
uniform float u_scale;        // radio del disco en alturas de pantalla
uniform float u_drift;        // amplitud del paseo de Möbius (0–0.6)
uniform float u_line_width;
uniform float u_fill;         // intensidad del relleno de las teselas

vec2 cmul(vec2 a, vec2 b) { return vec2(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x); }
vec2 cdiv(vec2 a, vec2 b) { return cmul(a, vec2(b.x, -b.y)) / dot(b, b); }

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);

    vec2 z = uv / u_scale;
    float rr = length(z);

    float p = max(u_p, 3.0), q = max(u_q, 3.0);
    if (1.0 / p + 1.0 / q >= 0.5) q = floor(2.0 * p / (p - 2.0)) + 1.0;   // fuerza hiperbólico
    float A = PI / p, B = PI / q;
    float cb = cos(B), sa = sin(A);
    float cx = cb / sqrt(cb * cb - sa * sa);          // centro del círculo espejo (eje x)
    float r2 = cx * cx - 1.0;                          // radio² (ortogonal al disco)

    vec3 col = u_background;
    if (rr < 1.0) {
        // Isometría: rotación + traslación de Möbius z → (z + t)/(1 + t̄ z).
        z = rot(TAU * u_rotation * u_phase) * z;
        vec2 t = u_drift * vec2(cos(th * max(u_wobble, 1.0)), sin(th * max(u_wobble, 1.0)));
        z = cdiv(z + t, vec2(1.0, 0.0) + cmul(vec2(t.x, -t.y), z));

        float depth = 0.0, parity = 0.0;
        for (int i = 0; i < 48; ++i) {
            float a = atan(z.y, z.x);
            float k = floor(a / (2.0 * A));
            a -= k * 2.0 * A;
            if (a > A) { a = 2.0 * A - a; parity += 1.0; }
            z = length(z) * vec2(cos(a), sin(a));
            vec2 d = z - vec2(cx, 0.0);
            float d2 = dot(d, d);
            if (d2 >= r2) break;
            z = vec2(cx, 0.0) + d * (r2 / d2);
            depth += 1.0;
            parity += 1.0;
        }
        // Distancias en el triángulo fundamental.
        float e_poly = abs(length(z - vec2(cx, 0.0)) - sqrt(r2));       // arista del polígono
        float e_spoke = min(abs(z.y), abs(dot(z, vec2(sin(A), -cos(A))))); // radios internos
        float e_center = length(z);

        // Factor conforme: las teselas encogen hacia el borde → escala de línea.
        float conf = (1.0 - rr * rr);
        float lw = u_line_width * conf * (1.0 + 0.8 * u_pulse_strength * kick);
        float fw1 = fwidth(e_poly) + 1e-6;
        float sp = 0.25 * conf + 1e-4;
        float l1 = line_aa(e_poly * conf, lw, fw1 * conf, sp);
        float l2 = line_aa(e_spoke * conf, lw * 0.35, (fwidth(e_spoke) + 1e-6) * conf, sp);

        float flow = fract(u_travel * u_phase);
        float hue = depth * 0.11 - flow + mod(parity, 2.0) * 0.08 + u_hue_cycles * u_phase;
        float wave = pulse(-depth * 0.12);
        vec3 tile = palette(hue) * (0.06 + 0.22 * mod(parity, 2.0)) * u_fill
                  * (1.0 + 1.5 * u_pulse_strength * wave);
        tile += palette(hue + 0.5) * exp(-e_center * 6.0) * 0.25 * u_fill;   // núcleo de cada tesela
        col += tile * smoothstep(1.0, 0.9, rr);
        col += palette(hue + 0.2) * (l1 * 1.3 + l2 * 0.6) * (1.0 + 1.2 * u_pulse_strength * wave);
        col *= smoothstep(1.0, 0.985, rr) * 0.85 + 0.15 * smoothstep(1.0, 0.0, rr);
    }
    // Halo del borde del infinito.
    float ring = exp(-abs(rr - 1.0) * 40.0) + 0.25 * exp(-abs(rr - 1.0) * 6.0);
    col += palette(u_hue_cycles * u_phase + th / TAU * 0.0 + atan(uv.y, uv.x) / TAU) * ring * 0.5
         * (1.0 + kick * u_pulse_strength);
    emit(col);
}
