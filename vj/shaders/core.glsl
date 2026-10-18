// Uniforms y utilidades válidas en cualquier etapa (vertex y fragment).
// La inserta renderer.load_shader; common.glsl la incluye.
//
// REGLA DE ORO DEL LOOP: el tiempo solo existe como u_phase ∈ [0,1).
// Cualquier término animado debe ser periódico en u_phase con periodo 1:
//   sin(TAU * K * u_phase)   con K entero         ✓
//   fract(K * u_phase + x)   con K entero         ✓
//   x + K * u_phase  usado vía fract()/mod(·,1)   ✓
//   sin(TAU * 0.37 * u_phase)                     ✗  (salta al cerrar el loop)
// Todos los u_<contador> de abajo ya llegan como enteros desde loop.py.

uniform vec2  u_resolution;   // tamaño del framebuffer (incluye supersampling)
uniform float u_phase;        // fase del loop [0,1)

uniform float u_travel;       // ciclos espaciales por loop       (entero)
uniform float u_rotation;     // vueltas por loop                 (entero)
uniform float u_wobble;       // oscilaciones secundarias por loop (entero)
uniform float u_hue_cycles;   // vueltas de paleta por loop       (entero)
uniform float u_beats;        // golpes por loop                  (entero, 0 = off)
uniform float u_pulse_strength;
uniform float u_pulse_decay;

uniform vec3  u_colors[8];
uniform int   u_num_colors;
uniform vec3  u_background;
// Cambio de colores (palette.cycle): paleta siguiente y cuánto se ha fundido ya.
uniform vec3  u_colors_b[8];
uniform int   u_num_colors_b;
uniform float u_palette_mix;  // 0 = solo u_colors, 1 = solo u_colors_b
uniform float u_weight;       // opacidad^2.2 / muestras de motion blur

const float PI  = 3.14159265358979;
const float TAU = 6.28318530717959;

// Gradiente cíclico entre los colores de la paleta: palette(x) == palette(x+1).
// Con palette.cycle se mezcla con la paleta siguiente (u_palette_mix lo calcula la CPU por frame).
vec3 palette(float x) {
    float f = fract(x) * float(u_num_colors);
    int i = int(floor(f));
    vec3 a = mix(u_colors[i % u_num_colors], u_colors[(i + 1) % u_num_colors], smoothstep(0.0, 1.0, fract(f)));
    if (u_palette_mix <= 0.0)
        return a;
    f = fract(x) * float(u_num_colors_b);
    i = int(floor(f));
    vec3 b = mix(u_colors_b[i % u_num_colors_b], u_colors_b[(i + 1) % u_num_colors_b], smoothstep(0.0, 1.0, fract(f)));
    return mix(a, b, u_palette_mix);
}

float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

mat2 rot(float a) {
    float c = cos(a), s = sin(a);
    return mat2(c, -s, s, c);
}

// Envolvente de pulso: 1 en cada beat, cae exponencialmente. `offset` desfasa
// la onda en el espacio (ondas que viajan) sin romper la periodicidad.
float pulse(float offset) {
    if (u_beats < 0.5) return 0.0;
    return exp(-u_pulse_decay * fract(u_phase * u_beats - offset));
}

// mod() exacto para enteros: los compiladores de GPU calculan mod(x, P) como
// x − P·floor(x·(1/P)) con un recíproco aproximado, y en múltiplos exactos de P
// el floor puede caer una unidad por debajo (128 mod 64 → 64 en vez de 0). Eso
// abría una costura en el ruido cada `period` celdas y rompía el loop.
float imod(float x, float period) {
    return x - period * floor((x + 0.5) / period);
}

// Hash entero de una celda: aritmética uint, idéntica bit a bit para la misma
// celda. hash12 (encadena fract de productos en float) es mal condicionado: cerca
// de 0/1 un redondeo distinto —el compilador puede reordenar operaciones en cada
// llamada— lo hace saltar de 0.001 a 0.998, y el ruido dejaba de ser periódico.
float cell_hash(vec2 c) {
    uvec2 q = uvec2(ivec2(c) + ivec2(65536));
    uint h = (q.x * 1597334673u) ^ (q.y * 3812015801u);
    h = (h ^ (h >> 16u)) * 2246822519u;
    h ^= h >> 13u;
    return float(h >> 8u) * (1.0 / 16777216.0);
}
