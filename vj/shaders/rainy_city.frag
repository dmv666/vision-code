#version 330
#include "common.glsl"

// Ciudad bajo la lluvia, vista a través de un cristal: luces desenfocadas
// (bokeh) que derivan despacio y gotas que resbalan dejando estela.
//
// Loop: cada capa de bokeh se repite cada `period` celdas en x (el hash usa el
// índice de celda mod period) y se desplaza period·K celdas por loop, con K
// entero. Desplazar un número entero de celdas no basta: se verían celdas
// distintas. Las gotas caen un número entero de veces.

uniform float u_lights;      // densidad de luces
uniform float u_drops;       // densidad de gotas en el cristal
uniform float u_blur;        // suavidad del borde del bokeh

vec3 bokeh_layer(vec2 uv, float scale, float period, float loops, float bright, float seed) {
    vec2 q = uv * scale + vec2(period * loops * u_phase, 0.0);
    vec2 cell = floor(q);
    vec3 acc = vec3(0.0);
    for (int j = -1; j <= 1; ++j)
    for (int i = -1; i <= 1; ++i) {
        vec2 cid = cell + vec2(i, j);
        vec2 id = vec2(imod(cid.x, period), cid.y);       // contenido periódico en x
        float h = cell_hash(id + vec2(seed * 97.0, 0.0));
        if (h < 1.0 - u_lights) continue;
        vec2 c = cid + 0.5 + (vec2(cell_hash(id + vec2(seed * 97.0, 4096.0)), cell_hash(id + vec2(seed * 97.0, 8192.0))) - 0.5) * 0.7;
        float r = 0.28 + 0.3 * cell_hash(id + vec2(seed * 97.0, 12288.0));
        float d = length(q - c);
        float soft = r * u_blur;
        float disc = smoothstep(r, r - soft, d);
        float ring = exp(-pow((d - r * 0.9) / (r * 0.09), 2.0)) * 0.35;
        float breathe = 0.75 + 0.25 * sin(TAU * (1.0 + floor(h * 2.0)) * u_phase + h * 30.0);
        // Más luces cálidas abajo (calle), frías arriba (ventanas).
        float warm = smoothstep(0.3, -0.4, uv.y);
        vec3 tint = palette(fract(h * 7.3) * 0.5 + warm * 0.5);
        acc += tint * (disc * 0.55 + ring) * breathe * bright;
    }
    return acc;
}

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float tr = max(u_travel, 1.0);

    // Noche: un poco de resplandor urbano cerca del suelo.
    vec3 col = u_background + palette(0.8) * 0.035 * smoothstep(0.5, -0.5, uv.y);
    // Periodos mayores que el ancho de pantalla en celdas: la repetición no se ve.
    col += bokeh_layer(uv, 3.5, 8.0, tr, 0.55, 1.0);
    col += bokeh_layer(uv, 6.0, 12.0, tr, 0.45, 7.0);
    col += bokeh_layer(uv, 11.0, 20.0, -tr, 0.30, 13.0);

    // Gotas fijas en el cristal: lentes que aclaran y tienen brillo arriba.
    vec2 g = uv * 22.0;
    vec2 gid = floor(g);
    float gh = hash12(gid + 5.0);
    if (gh > 1.0 - u_drops) {
        vec2 c = gid + 0.5 + (vec2(hash12(gid * 1.7), hash12(gid * 2.9)) - 0.5) * 0.5;
        float r = 0.12 + 0.18 * hash12(gid * 4.1);
        float d = length((g - c) * vec2(1.0, 0.85));
        float lens = smoothstep(r, r * 0.8, d);
        col = mix(col, col * 1.6 + palette(0.3) * 0.02, lens * 0.7);
        col += vec3(0.9) * exp(-length(g - c - vec2(-0.3, 0.35) * r) / (r * 0.15)) * 0.25 * lens;
        col *= 1.0 - 0.35 * exp(-pow((d - r) / (r * 0.12), 2.0));    // borde oscuro
    }

    // Gotas que resbalan: carriles con 1–2 caídas completas por loop.
    vec2 lq = vec2(uv.x * 9.0, uv.y);
    float lane = floor(lq.x);
    float lh = hash11(lane * 3.7 + 1.1);
    if (lh > 0.45) {
        float cycles = tr * (1.0 + floor(hash11(lane * 9.1) * 2.0));
        float y = 0.6 - fract(hash11(lane * 5.3) + cycles * u_phase) * 1.3;
        float x = lane + 0.5 + 0.12 * sin(uv.y * 25.0 + lane);
        vec2 d = vec2((lq.x - x) * 0.11, uv.y - y);
        float drop = exp(-dot(d / vec2(0.006, 0.009), d / vec2(0.006, 0.009)));
        float trail = smoothstep(0.004, 0.0, abs(d.x)) * smoothstep(0.0, 0.01, d.y)
                    * exp(-d.y / 0.18) * 0.35;
        col += (vec3(0.85, 0.9, 1.0) * drop * 1.1 + vec3(0.7, 0.8, 0.95) * trail * 0.3);
    }
    emit(col);
}
