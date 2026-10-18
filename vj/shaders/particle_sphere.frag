#version 330
#include "common.glsl"

// Esfera(s) de partículas en una espiral de Fibonacci, con deformación orgánica
// y "respiración" al ritmo del BPM. Coste por píxel ∝ count × shells.

uniform float u_count;
uniform float u_shells;
uniform float u_radius;
uniform float u_size;
uniform float u_displacement;
uniform float u_camera_distance;
uniform float u_focal;

void main() {
    vec2 uv = centered_uv();
    float th = TAU * u_phase;
    float kick = pulse(0.0);
    float golden = PI * (3.0 - sqrt(5.0));

    vec3 acc = vec3(0.0);
    int shells = int(u_shells);
    int count = int(u_count);

    for (int sh = 0; sh < shells; ++sh) {
        float fs = float(sh);
        float shell_r = u_radius * (1.0 - 0.28 * fs);
        // Capas alternas giran en sentido contrario (±u_rotation entero → periódico).
        float dir = (sh % 2 == 0) ? 1.0 : -1.0;
        mat2 ry = rot(dir * TAU * u_rotation * u_phase + fs * 1.7);
        mat2 rx = rot(0.45 + 0.25 * sin(th * u_wobble + fs));

        for (int i = 0; i < count; ++i) {
            float fi = float(i);
            float y = 1.0 - 2.0 * (fi + 0.5) / u_count;
            float rr = sqrt(max(0.0, 1.0 - y * y));
            float phi = golden * fi;
            vec3 p = vec3(cos(phi) * rr, y, sin(phi) * rr);

            // Deformación: ondas esféricas con frecuencias temporales enteras.
            float disp = sin(3.0 * phi + 4.0 * y + th * u_wobble * 2.0)
                       * cos(2.0 * y - th * u_wobble + fs);
            // Onda de pulso de polo a polo.
            float wave = pulse(0.5 * (y * 0.5 + 0.5));
            float rad = shell_r * (1.0 + u_displacement * disp + 0.18 * u_pulse_strength * wave);
            p *= rad;
            p.xz = ry * p.xz;
            p.yz = rx * p.yz;
            p.z += u_camera_distance;
            if (p.z < 0.1) continue;

            vec2 sp = p.xy * (u_focal / p.z);
            float sz = u_size * u_focal / p.z * (1.0 + 0.6 * u_pulse_strength * kick);
            vec2 dv = uv - sp;
            float d2 = dot(dv, dv);
            float core = sz * sz / (d2 + sz * sz);
            float glow = core * core * 1.5 + core * 0.02;

            float depth = smoothstep(u_camera_distance + u_radius * 1.4,
                                     u_camera_distance - u_radius, p.z);
            vec3 c = palette(fi / u_count * 0.6 + y * 0.15 + fs * 0.33 + u_hue_cycles * u_phase);
            acc += c * glow * (0.25 + 0.75 * depth) * (1.0 + 1.5 * u_pulse_strength * wave);
        }
    }

    float r = length(uv);
    acc += palette(u_hue_cycles * u_phase + 0.5) * exp(-r * 4.0) * 0.015 * (1.0 + kick * u_pulse_strength);
    emit(acc + u_background);
}
