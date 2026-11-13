#version 330
#include "common.glsl"

// Catedral giroide: vuelo a través de una superficie mínima triplemente periódica
// (giroide) con un túnel tallado a lo largo de la cámara. Iluminación por brillo
// acumulado (neón volumétrico) + niebla.
//
// Loop: el giroide repite cada 2π/scale en z y el camino de la cámara también;
// la cámara avanza fract(u_travel·fase) periodos → vuelve exactamente al inicio.

uniform float u_scale;
uniform float u_thickness;
uniform float u_steps;
uniform float u_tunnel;       // radio del túnel libre
uniform float u_glow;
uniform float u_fog;

float g_period() { return TAU / u_scale; }

vec2 path(float z) {
    float w = z * u_scale;
    return vec2(0.55 * sin(w), 0.4 * cos(w * 2.0)) / u_scale;
}

float map(vec3 p) {
    vec3 q = p * u_scale;
    float g = abs(dot(sin(q), cos(q.yzx))) / u_scale - u_thickness;
    float tun = u_tunnel - length(p.xy - path(p.z));
    return max(g * 0.6, tun);
}

void main() {
    vec2 uv = centered_uv();
    float kick = pulse(0.0);

    float zc = fract(u_travel * u_phase) * g_period();
    vec3 ro = vec3(path(zc), zc);
    vec3 ta = vec3(path(zc + 0.4), zc + 0.4);
    vec3 fw = normalize(ta - ro);
    vec3 rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw));
    vec3 up = cross(fw, rt);
    vec2 sv = rot(cyc(u_rotation) + 0.15 * sin(cyc(u_wobble))) * uv;
    vec3 rd = normalize(fw * 1.1 + rt * sv.x + up * sv.y);

    float t = 0.0;
    vec3 acc = vec3(0.0);
    int n = int(u_steps);
    float hit = 0.0;
    for (int i = 0; i < 200; ++i) {
        if (i >= n) break;
        vec3 p = ro + rd * t;
        float d = map(p);
        float h = p.z * u_scale / TAU + length(p.xy) * 0.6;   // entero por periodo: sin salto de color
        float band = pulse(-p.z * u_scale / TAU);
        acc += palette(h - fract(u_hue_cycles * u_phase)) * (0.004 / (0.02 + abs(d) * 60.0))
             * exp(-t / u_fog) * (1.0 + 1.5 * u_pulse_strength * band);
        if (d < 0.0006) { hit = 1.0; break; }
        t += max(d * 0.8, 0.002);
        if (t > u_fog * 4.0) break;
    }
    vec3 col = u_background + acc * u_glow * 0.35;
    if (hit > 0.0) {
        vec3 p = ro + rd * t;
        vec2 e = vec2(0.0015, 0.0);
        vec3 nrm = normalize(vec3(map(p + e.xyy) - map(p - e.xyy),
                                  map(p + e.yxy) - map(p - e.yxy),
                                  map(p + e.yyx) - map(p - e.yyx)));
        float fres = pow(1.0 - abs(dot(nrm, -rd)), 3.0);
        float h = p.z * u_scale / TAU + length(p.xy) * 0.6;   // entero por periodo: sin salto de color
        float diff = clamp(dot(nrm, normalize(vec3(0.3, 0.6, -0.5))), 0.0, 1.0);
        // Venas de luz sobre la superficie: isolíneas del giroide desplazado.
        vec3 q = p * u_scale * 2.0;
        float vein = abs(dot(sin(q.zxy), cos(q.yzx)));
        float vl = exp(-vein * 14.0);
        vec3 surf = palette(h + 0.25 - fract(u_hue_cycles * u_phase)) * (0.04 + 0.18 * diff + 0.5 * fres)
                  + palette(h + 0.6 - fract(u_hue_cycles * u_phase)) * vl * 1.4;
        col += surf * exp(-t / u_fog);
    }
    col += palette(0.1 - fract(u_hue_cycles * u_phase)) * kick * u_pulse_strength * 0.05;
    emit(col);
}
