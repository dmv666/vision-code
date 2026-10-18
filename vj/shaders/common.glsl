// Cabecera compartida por todos los patrones (la inserta renderer.load_shader).
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
uniform float u_weight;       // 1 / muestras de motion blur

out vec4 fragColor;

const float PI  = 3.14159265358979;
const float TAU = 6.28318530717959;

// Gradiente cíclico entre los colores de la paleta: palette(x) == palette(x+1).
vec3 palette(float x) {
    float n = float(u_num_colors);
    float f = fract(x) * n;
    int i = int(floor(f));
    float t = smoothstep(0.0, 1.0, fract(f));
    return mix(u_colors[i % u_num_colors], u_colors[(i + 1) % u_num_colors], t);
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

// Línea con anti-aliasing analítico y filtrado por distancia: cuando las líneas
// se vuelven más finas que un píxel (fondo del túnel) converge a su cobertura
// media en lugar de producir moiré/parpadeo.
float line_aa(float d, float width, float fw, float spacing) {
    fw = max(fw, 1e-6);
    float cov = clamp((width - d) / fw + 0.5, 0.0, 1.0);
    float avg = clamp(2.0 * width / spacing, 0.0, 1.0);
    return mix(cov, avg, smoothstep(0.15, 0.6, fw / spacing));
}

vec2 centered_uv() {
    return (gl_FragCoord.xy - 0.5 * u_resolution) / u_resolution.y;
}

void emit(vec3 c) {
    fragColor = vec4(max(c, 0.0) * u_weight, u_weight);
}
