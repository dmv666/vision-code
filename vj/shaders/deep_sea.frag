#version 330
#include "common.glsl"

// Fondo marino: rayos de luz desde la superficie, cáusticas sobre la arena,
// burbujas que suben y nieve marina que cae.
//
// Loop: la cáustica solo usa el tiempo dentro de sin/cos con multiplicadores
// enteros → periódica en 2π. Burbujas y nieve avanzan ciclos enteros con fract().

uniform float u_floor;          // altura media del lecho
uniform float u_rays;
uniform float u_bubbles;        // número de burbujas
uniform float u_caustic_scale;
uniform float u_snow;

float caustic(vec2 q, float t) {
    vec2 p = mod(q * TAU, TAU) - 250.0;
    vec2 i = p;
    float c = 1.0;
    const float inten = 0.005;
    for (int n = 0; n < 5; n++) {
        float m = (n == 0) ? 1.0 : (n == 1 ? -1.0 : (n == 2 ? 2.0 : (n == 3 ? 1.0 : -2.0)));
        float tn = t * m + float(n) * 1.3;
        i = p + vec2(cos(tn - i.x) + sin(tn + i.y), sin(tn - i.y) + cos(tn + i.x));
        c += 1.0 / length(vec2(p.x / (sin(i.x + tn) / inten), p.y / (cos(i.y + tn) / inten)));
    }
    c /= 5.0;
    c = 1.17 - pow(c, 1.4);
    return pow(abs(c), 8.0);
}

float floor_y(float x) {
    return u_floor + 0.025 * sin(x * 3.7 + 1.0) + 0.012 * sin(x * 9.3 + 2.0);
}

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;

    // Agua: más clara arriba, casi negra al fondo.
    vec3 col = mix(u_background, palette(0.55) * 0.22, smoothstep(-0.55, 0.55, uv.y));

    // Rayos de luz: abanico desde un punto sobre la superficie.
    vec2 src = vec2(0.18, 0.95);
    float a = atan(uv.x - src.x, src.y - uv.y);
    float w1 = 0.5 + 0.5 * sin(a * 19.0 + th * u_wobble + 1.0);
    float w2 = 0.5 + 0.5 * sin(a * 31.0 - th * u_wobble * 2.0 + 2.0);
    float w3 = 0.5 + 0.5 * sin(a * 11.0 + th * u_wobble + 4.0);
    float rays = pow(w1 * w2, 3.0) + 0.6 * pow(w3, 10.0);
    float dist = length(uv - src);
    rays *= smoothstep(1.5, 0.3, dist) * smoothstep(u_floor - 0.05, u_floor + 0.35, uv.y);
    col += palette(0.6) * rays * 0.28 * u_rays;

    // Superficie: banda superior que reverbera.
    float surf = smoothstep(0.36, 0.5, uv.y);
    float shimmer = 0.5 + 0.5 * sin(uv.x * 26.0 + 3.0 * sin(uv.x * 7.0 + th * u_wobble) + th * u_wobble * 2.0);
    col += palette(0.7) * surf * (0.06 + 0.12 * pow(shimmer, 4.0));

    // Lecho de arena con cáusticas en perspectiva.
    float fy = floor_y(uv.x);
    if (uv.y < fy) {
        float below = fy - uv.y;
        vec3 sand = mix(palette(0.2) * 0.10, u_background * 0.5, smoothstep(0.0, 0.25, below));
        vec2 q = vec2(uv.x, (uv.y - u_floor) * 3.2) * u_caustic_scale;
        float t = th * max(u_wobble, 1.0);
        vec3 cs = vec3(caustic(q * 0.992, t), caustic(q, t), caustic(q * 1.010, t));
        sand += cs * palette(0.6) * 0.32 * exp(-below / 0.12);
        // Ondas de arena.
        sand *= 0.85 + 0.15 * sin(uv.x * 60.0 + sin(uv.y * 40.0) * 2.0);
        col = sand + col * 0.15;
    }
    // Neblina sobre el lecho.
    col += palette(0.5) * 0.03 * exp(-abs(uv.y - fy) / 0.04);

    // Nieve marina: rejilla periódica en y (40 celdas, más que la pantalla) que
    // baja exactamente 40·K celdas por loop.
    const float SNOW_P = 40.0;
    vec2 g = uv * 34.0 + vec2(0.0, SNOW_P * max(u_travel, 1.0) * u_phase);
    vec2 cid = floor(g);
    vec2 id = vec2(cid.x, imod(cid.y, SNOW_P));
    float hs = cell_hash(id);
    if (hs > 0.9) {
        vec2 sp = cid + 0.5 + (vec2(cell_hash(id + vec2(0.0, 4096.0)), cell_hash(id + vec2(0.0, 8192.0))) - 0.5) * 0.7;
        sp.x += 0.15 * sin(TAU * u_phase + hs * 20.0);
        float d = length(g - sp);
        col += vec3(0.7, 0.85, 0.9) * exp(-d * d * 18.0) * 0.18 * u_snow;
    }

    // Burbujas: suben 1–2 ciclos completos por loop, con vaivén lateral.
    int nb = int(u_bubbles);
    for (int i = 0; i < 64; ++i) {
        if (i >= nb) break;
        float fi = float(i);
        float h1 = hash11(fi * 3.1 + 0.5), h2 = hash11(fi * 7.7 + 0.2), h3 = hash11(fi * 1.9 + 0.9);
        float speed = max(u_travel, 1.0) * (1.0 + floor(h2 * 2.0));
        float by = -0.55 + fract(h3 + speed * u_phase) * 1.1;
        float bx = (h1 - 0.5) * 1.6 + 0.012 * sin(by * 18.0 + fi);
        float r = 0.004 + 0.009 * hash11(fi * 5.3);
        float d = length(uv - vec2(bx, by));
        float ring = exp(-pow((d - r) / (r * 0.28), 2.0));
        float hi = exp(-length(uv - vec2(bx, by) - vec2(-0.35, 0.35) * r) / (r * 0.18));
        float fade = smoothstep(-0.55, -0.4, by) * smoothstep(0.55, 0.4, by);
        col += (palette(0.65) * ring * 0.35 + vec3(1.0) * hi * 0.5) * fade;
    }
    emit(col);
}
