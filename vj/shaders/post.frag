#version 330
// Post-proceso: downsample SSAA (box filter), aberración cromática, tonemap
// ACES, viñeta, gamma sRGB y grano/dithering.

uniform sampler2D u_accum;
uniform vec2  u_out_res;
uniform int   u_ss;
uniform float u_exposure;
uniform float u_vignette;
uniform float u_grain;
uniform float u_ca;
uniform float u_frame;     // frame mod N → el grano también es periódico

out vec4 fragColor;

vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

vec3 box(vec2 uv) {
    vec2 texel = 1.0 / (u_out_res * float(u_ss));
    vec3 s = vec3(0.0);
    for (int j = 0; j < u_ss; ++j)
        for (int i = 0; i < u_ss; ++i)
            s += texture(u_accum, uv + (vec2(i, j) + 0.5 - 0.5 * float(u_ss)) * texel).rgb;
    return s / float(u_ss * u_ss);
}

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_out_res;
    vec2 dir = uv - 0.5;
    vec3 c;
    if (u_ca > 0.0) {
        c = vec3(box(uv + dir * u_ca).r, box(uv).g, box(uv - dir * u_ca).b);
    } else {
        c = box(uv);
    }
    c = aces(c * u_exposure);
    c *= 1.0 - u_vignette * smoothstep(0.15, 0.85, length(dir * vec2(u_out_res.x / u_out_res.y, 1.0)) * 0.9);
    c = pow(c, vec3(1.0 / 2.2));
    c += (hash12(gl_FragCoord.xy + vec2(u_frame * 17.13, u_frame * 3.71)) - 0.5) * u_grain;
    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}
