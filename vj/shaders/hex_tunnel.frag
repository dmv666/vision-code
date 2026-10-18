#version 330
#include "common.glsl"

// Túnel poligonal analítico (sin raymarching): para cada píxel se calcula a qué
// profundidad el rayo choca con la pared del prisma de N lados.

uniform float u_sides;
uniform float u_radius;
uniform float u_segment;
uniform float u_line_width;
uniform float u_twist;
uniform float u_fov;
uniform float u_fog;
uniform float u_grid;
uniform float u_pulse_speed;
uniform float u_panel_density;
uniform float u_streams;       // intensidad de los "flujos de datos" por las aristas
uniform float u_stream_speed;  // velocidad relativa al avance (se redondea a ciclos enteros)

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);

    // Balanceo de cámara: frecuencias enteras (wobble y 2·wobble) → periódico.
    uv -= 0.035 * vec2(sin(th * u_wobble), sin(2.0 * th * u_wobble + 1.3));

    float r = max(length(uv), 1e-4);
    float sector = TAU / u_sides;

    // Profundidad aproximada (círculo) para aplicar el twist en espacio de cámara.
    // Si el twist dependiera de la profundidad de MUNDO, el giro acumulado al
    // avanzar u_travel segmentos no sería múltiplo de 2π/N y el loop saltaría.
    float z0 = u_radius / (r * u_fov);
    float ang = atan(uv.y, uv.x) + TAU * u_rotation * u_phase + u_twist * z0;

    float local = mod(ang, sector) - 0.5 * sector;   // ángulo dentro de la cara
    float z = z0 / cos(local);                        // profundidad real hasta la cara plana
    float face = imod(floor(ang / sector), u_sides);
    float half_w = u_radius * tan(0.5 * sector);
    float s = tan(local) / tan(0.5 * sector);         // -1..1 a lo ancho de la cara

    // Profundidad de mundo: avanza u_travel segmentos exactos por loop.
    float w = z + u_travel * u_segment * u_phase;
    float ring = w / u_segment;
    float ring_id = floor(ring);

    // Distancias (en unidades de mundo) a cada familia de líneas.
    float fw_ring = fwidth(ring) * u_segment;
    float fw_s = fwidth(s) * half_w;
    float d_ring = abs(fract(ring + 0.5) - 0.5) * u_segment;
    float d_sub = abs(fract(ring * 4.0 + 0.5) - 0.5) * u_segment * 0.25;
    float d_edge = (1.0 - abs(s)) * half_w;
    float g = (s * 0.5 + 0.5) * u_grid;
    float d_grid = abs(fract(g + 0.5) - 0.5) * (2.0 * half_w / u_grid);
    float cell = floor(g);

    float lw = u_line_width * (1.0 + 0.8 * u_pulse_strength * kick);
    float rings = line_aa(d_ring, lw, fw_ring, u_segment);
    float subs  = line_aa(d_sub, lw * 0.35, fw_ring, u_segment * 0.25);
    float edges = line_aa(d_edge, lw * 1.3, fw_s, 2.0 * half_w);
    float grid  = line_aa(d_grid, lw * 0.5, fw_s, 2.0 * half_w / u_grid);

    // Halo suave alrededor de anillos y aristas (se desvanece al hacerse sub-píxel).
    float far = smoothstep(0.1, 0.5, fw_ring / u_segment);
    float glow = (exp(-d_ring / (lw * 2.0)) * 0.25 + exp(-d_edge / (lw * 2.5)) * 0.2) * (1.0 - far)
               + 0.04 * far;

    // Paneles iluminados aleatorios. El índice de anillo se toma mod u_travel:
    // tras un loop cada anillo ha avanzado exactamente u_travel posiciones, así
    // que el anillo que ocupa el lugar de otro hereda también su "semilla".
    float seed = hash12(vec2(imod(ring_id, max(u_travel, 1.0)), face * 7.0 + cell));
    float lit = step(1.0 - u_panel_density, seed);
    float flicker = 0.5 + 0.5 * sin(th * u_wobble * 4.0 + seed * TAU);
    float panel = lit * (0.03 + 0.12 * flicker) * (1.0 - far);

    // Onda de pulso que viaja hacia el fondo del túnel.
    float wave = pulse(z * u_pulse_speed);

    // Flujos de datos: guiones de luz que corren por las líneas longitudinales.
    // Coordenada en profundidad de CÁMARA + m·p, con m entero → periódico para
    // cualquier tamaño de guion (en coordenadas de mundo dependería de u_travel).
    float m = floor(u_travel * u_stream_speed + 0.5);
    float lane = face * (u_grid + 1.0) + floor(g + 0.5);
    float q = z / u_segment * 0.35 - m * u_phase + hash11(lane * 3.7);
    float dash = smoothstep(0.82, 0.97, fract(q)) * step(hash11(lane * 9.1), 0.6);
    float streams = dash * max(edges, grid * 1.5) * u_streams * (1.0 - far);

    // Color: depende de profundidad de CÁMARA (z), cara y fase → periódico.
    float hue = z * 0.025 + face / u_sides * 0.35 + u_hue_cycles * u_phase;
    vec3 c_a = palette(hue);
    vec3 c_b = palette(hue + 0.5);

    vec3 col = c_a * (rings * (1.0 + 2.0 * u_pulse_strength * wave) + glow)
             + c_b * (edges * 0.9 + grid * 0.3 + subs * 0.12 + panel)
             + mix(c_a, vec3(1.0), 0.5) * streams * 4.0;

    col *= exp(-z / u_fog);
    // Resplandor del punto de fuga, latiendo con el kick.
    col += palette(u_hue_cycles * u_phase + 0.25) * exp(-r * 7.0) * (0.25 + 0.6 * u_pulse_strength * kick);
    col += u_background;

    emit(col);
}
