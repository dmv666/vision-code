#version 330
#include "core.glsl"

// Esfera(s) de partículas dibujadas como QUADS INSTANCIADOS: una instancia por
// partícula, 6 vértices por quad. La GPU solo sombrea los píxeles que cubre el
// halo de cada partícula, en vez de recorrer todas las partículas en cada píxel
// de la pantalla (de O(píxeles × partículas) a O(área de los halos)).
//
// La matemática de posición es una función cerrada de u_phase con frecuencias
// enteras, igual que en los patrones de pantalla completa → loop perfecto.

uniform float u_count;
uniform float u_radius;
uniform float u_size;
uniform float u_displacement;
uniform float u_camera_distance;
uniform float u_focal;

const float HALO = 12.0;   // radio del quad en tamaños de partícula (el brillo cae a ~1e-4)

out vec2  v_local;         // posición dentro del quad, en tamaños de partícula
out vec3  v_color;

const vec2 CORNERS[6] = vec2[6](vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
                                vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0));

void main() {
    int count = int(u_count);
    int sh = gl_InstanceID / count;
    int i = gl_InstanceID - sh * count;
    float fs = float(sh);
    float fi = float(i);
    float th = TAU * u_phase;
    float kick = pulse(0.0);
    float golden = PI * (3.0 - sqrt(5.0));

    float shell_r = u_radius * (1.0 - 0.28 * fs);
    // Capas alternas giran en sentido contrario (±u_rotation entero → periódico).
    float dir = (sh % 2 == 0) ? 1.0 : -1.0;
    mat2 ry = rot(dir * TAU * u_rotation * u_phase + fs * 1.7);
    mat2 rx = rot(0.45 + 0.25 * sin(th * u_wobble + fs));

    float y = 1.0 - 2.0 * (fi + 0.5) / u_count;
    float rr = sqrt(max(0.0, 1.0 - y * y));
    float phi = golden * fi;
    vec3 p = vec3(cos(phi) * rr, y, sin(phi) * rr);

    // Deformación: ondas esféricas con frecuencias temporales enteras.
    float disp = sin(3.0 * phi + 4.0 * y + th * u_wobble * 2.0)
               * cos(2.0 * y - th * u_wobble + fs);
    // Onda de pulso de polo a polo.
    float wave = pulse(0.5 * (y * 0.5 + 0.5));
    p *= shell_r * (1.0 + u_displacement * disp + 0.18 * u_pulse_strength * wave);
    p.xz = ry * p.xz;
    p.yz = rx * p.yz;
    p.z += u_camera_distance;

    if (p.z < 0.1) {                     // detrás de la cámara: quad fuera de pantalla
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_local = vec2(0.0);
        v_color = vec3(0.0);
        return;
    }

    vec2 sp = p.xy * (u_focal / p.z);    // centro en coordenadas centered_uv
    float sz = u_size * u_focal / p.z * (1.0 + 0.6 * u_pulse_strength * kick);
    float depth = smoothstep(u_camera_distance + u_radius * 1.4, u_camera_distance - u_radius, p.z);

    vec2 corner = CORNERS[gl_VertexID];
    v_local = corner * HALO;
    v_color = palette(fi / u_count * 0.6 + y * 0.15 + fs * 0.33 + u_hue_cycles * u_phase)
            * (0.25 + 0.75 * depth) * (1.0 + 1.5 * u_pulse_strength * wave);

    // centered_uv → NDC: uv = (frag − res/2) / res.y  ⇒  ndc = uv · 2·res.y / res
    vec2 uv = sp + corner * (HALO * sz);
    gl_Position = vec4(uv * (2.0 * u_resolution.y / u_resolution), 0.0, 1.0);
}
