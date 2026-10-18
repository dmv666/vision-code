#version 330
#include "common.glsl"

// Ondas orgánicas: campo de ruido fBm con distorsión de dominio, dibujado como
// curvas de nivel de neón (estilo mapa topográfico líquido).
//
// Ruido en loop: noise(x, t) NO es periódico. Aquí el tiempo recorre un CÍRCULO
// en el espacio 3D del ruido: (R·cos θ, R·sin θ) con θ = 2π·W·p. En p = 1 el
// punto vuelve exactamente al inicio, y el campo evoluciona (no solo se desplaza).

uniform float u_scale;        // tamaño de las formas
uniform float u_bands;        // número de curvas de nivel
uniform float u_warp;         // distorsión de dominio
uniform float u_line_width;
uniform float u_flow_radius;  // cuánto "viaja" el ruido por loop (mayor = más cambio)
uniform float u_horizon;      // 0 = plano frontal; >0 = suelo en perspectiva con horizonte

float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}

// Ojo: no llamarla noise3 — es una función interna de GLSL y macOS rechaza redefinirla.
float value_noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    return mix(mix(mix(hash13(i), hash13(i + vec3(1, 0, 0)), f.x),
                   mix(hash13(i + vec3(0, 1, 0)), hash13(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash13(i + vec3(0, 0, 1)), hash13(i + vec3(1, 0, 1)), f.x),
                   mix(hash13(i + vec3(0, 1, 1)), hash13(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

float fbm(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; ++i) {
        s += a * value_noise(p);
        p = p * 2.03 + vec3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

void main() {
    vec2 uv = centered_uv();
    float kick = pulse(0.0);
    float th = TAU * u_wobble * u_phase;            // u_wobble = vueltas del círculo por loop
    vec2 loop_c = u_flow_radius * vec2(cos(th), sin(th));

    vec2 p = uv;
    float fade = 1.0;
    if (u_horizon > 0.0) {
        // Suelo en perspectiva: la mitad inferior se proyecta sobre un plano.
        float y = u_horizon - uv.y;
        fade = smoothstep(0.0, 0.25, y);
        y = max(y, 1e-3);
        p = vec2(uv.x / y, 1.0 / y) * 0.6;
        // Ojo: trasladar el ruido hacia la cámara NO sería periódico (el ruido
        // no se repite). El movimiento sale del círculo temporal y de las bandas.
    }
    p = rot(TAU * u_rotation * u_phase) * p * u_scale;

    // Distorsión de dominio (Inigo Quilez): fbm(p + fbm(p + ...)).
    vec3 P = vec3(p, 0.0) + vec3(loop_c.x, 0.0, loop_c.y);
    vec2 w1 = vec2(fbm(P), fbm(P + vec3(5.2, 1.3, 2.8)));
    vec3 P2 = vec3(p + u_warp * w1, 0.0) + vec3(0.0, loop_c.x, loop_c.y);
    float f = fbm(P2 + vec3(1.7, 9.2, 0.0));

    // Curvas de nivel que fluyen: avanzan u_travel bandas enteras por loop.
    float v = f * u_bands - u_travel * u_phase;
    float d = abs(fract(v + 0.5) - 0.5);            // distancia (en bandas) a la curva
    float fw = fwidth(v);
    float lw = u_line_width * (1.0 + 0.8 * u_pulse_strength * kick);
    float lines = line_aa(d, lw, fw, 1.0);
    float glow = exp(-d / (lw * 1.5)) * 0.18 * (1.0 - smoothstep(0.1, 0.5, fw));

    // Pulso que recorre el campo según la altura del ruido. No usar floor(v):
    // el índice de banda avanza u_travel por loop y rompería la periodicidad.
    float hot = pulse(f * 2.0);
    float hue = f * 1.4 + length(w1) * 0.6 + u_hue_cycles * u_phase;
    vec3 col = palette(hue) * (lines * (1.0 + 2.5 * u_pulse_strength * hot) + glow);
    col += palette(hue + 0.5) * pow(f, 4.0) * 0.05;   // relleno tenue en las crestas

    emit(col * fade + u_background);
}
