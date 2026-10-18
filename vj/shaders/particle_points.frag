#version 330
#include "common.glsl"

// Fragment de cada partícula instanciada (ver particle_sphere.vert).

in vec2 v_local;
in vec3 v_color;

const float HALO = 12.0;

void main() {
    float d2 = dot(v_local, v_local);              // distancia² en tamaños de partícula
    float core = 1.0 / (d2 + 1.0);
    float glow = core * core * 1.5 + core * 0.02;
    // Ventana suave hasta el borde del quad: sin cortes cuadrados.
    float w = 1.0 - smoothstep(0.5 * HALO, HALO, sqrt(d2));
    fragColor = vec4(v_color * glow * w * u_weight, 0.0);
}
