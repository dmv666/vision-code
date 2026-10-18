#version 330
#include "common.glsl"

// Lámpara de lava: bolas de cera que suben, bajan y se fusionan (metaballs),
// con iluminación 3D falsa a partir del gradiente del campo.
//
// Loop: cada bola recorre senos con un número entero de ciclos por loop.

uniform float u_blobs;
uniform float u_size;
uniform float u_gloss;
uniform float u_glow;

void main() {
    vec2 uv = centered_uv();
    float aspect = u_resolution.x / u_resolution.y;

    float F = 0.0;
    vec2 grad = vec2(0.0);
    float heat = 0.0;
    int n = int(u_blobs);
    for (int i = 0; i < 16; ++i) {
        if (i >= n) break;
        float fi = float(i);
        float h1 = hash11(fi * 1.31 + 0.1), h2 = hash11(fi * 2.17 + 0.3);
        float h3 = hash11(fi * 3.73 + 0.7), h4 = hash11(fi * 5.11 + 0.2);
        float cy_cycles = max(u_travel, 1.0) * (1.0 + floor(h2 * 2.0));
        float cx_cycles = 1.0 + floor(h3 * 2.0);
        float ph = TAU * cy_cycles * u_phase + h4 * TAU;
        vec2 c = vec2((h1 - 0.5) * aspect * 0.8 + 0.08 * sin(TAU * cx_cycles * u_phase + h2 * TAU),
                      0.40 * sin(ph));
        // Al moverse rápido se estiran en vertical (como la cera de verdad).
        float vel = abs(cos(ph));
        vec2 d = (uv - c) * vec2(1.0 + 0.25 * vel, 1.0 - 0.2 * vel);
        float r = u_size * (0.6 + 0.8 * h3);
        float d2 = dot(d, d) + 1e-5;
        float k = r * r / d2;
        F += k;
        grad += -2.0 * r * r * d / (d2 * d2);
        heat += k * (0.5 - 0.5 * sin(ph));              // las que suben vienen calientes del fondo
    }

    float fw = fwidth(F) + 1e-5;
    float inside = smoothstep(1.0 - fw, 1.0 + fw, F);

    // Fondo: líquido oscuro con una columna de luz cálida desde abajo.
    vec3 col = u_background;
    col += palette(0.8) * 0.10 * exp(-abs(uv.x) / 0.5) * smoothstep(0.7, -0.6, uv.y);
    col += palette(0.2) * u_glow * 0.12 * smoothstep(0.25, 1.0, F) * (1.0 - inside);   // halo

    // Superficie: normal a partir del gradiente del campo.
    // ∇F/F ≈ 2/d cerca del borde: inclina la normal en los bordes y la deja plana en
    // el centro, como una esfera de cera.
    vec3 nrm = normalize(vec3(-grad / max(F, 1e-3) * 0.045, 1.0));
    vec3 L = normalize(vec3(-0.4, 0.6, 0.7));
    float diff = clamp(dot(nrm, L), 0.0, 1.0);
    float spec = pow(clamp(dot(reflect(-L, nrm), vec3(0.0, 0.0, 1.0)), 0.0, 1.0), 40.0);
    float rim = pow(1.0 - nrm.z, 2.0);
    float tcol = clamp(0.08 + 0.30 * (uv.y + 0.5) + 0.08 * heat / max(F, 1e-3), 0.0, 0.5);
    vec3 wax = palette(tcol + u_hue_cycles * u_phase);
    vec3 shade = wax * (0.35 + 0.75 * diff) + palette(tcol + 0.35) * rim * 0.6
               + vec3(1.0, 0.95, 0.9) * spec * u_gloss;
    // Translucidez: el núcleo grueso brilla un poco desde dentro.
    shade += palette(0.25) * 0.18 * smoothstep(1.2, 5.0, F);

    col = mix(col, shade, inside);
    emit(col);
}
