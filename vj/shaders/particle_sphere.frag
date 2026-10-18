#version 330
#include "common.glsl"

// Pasada de pantalla completa de particle_sphere: solo fondo y resplandor central.
// Las partículas se dibujan aparte como quads instanciados (particle_sphere.vert),
// que es lo que hace viable este patrón a 4K.

void main() {
    vec2 uv = centered_uv();
    float kick = pulse(0.0);
    float r = length(uv);
    vec3 acc = palette(u_hue_cycles * u_phase + 0.5) * exp(-r * 4.0) * 0.015 * (1.0 + kick * u_pulse_strength);
    emit(acc + u_background);
}
