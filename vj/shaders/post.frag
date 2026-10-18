#version 330
// Post-proceso: downsample SSAA (box filter), bloom por mipmaps, aberración
// cromática, tonemap ACES, saturación/contraste, viñeta, gamma sRGB y grano.

uniform sampler2D u_accum;
uniform vec2  u_out_res;
uniform int   u_ss;
uniform float u_exposure;
uniform float u_vignette;
uniform float u_grain;
uniform float u_ca;
uniform float u_bloom;
uniform float u_bloom_radius;
uniform float u_saturation;
uniform float u_contrast;
uniform float u_frame;     // frame mod N → el grano también es periódico

out vec4 fragColor;

vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

// Nivel 0 explícito: con mipmaps activos, texture() elegiría un nivel borroso.
vec3 box(vec2 uv) {
    vec2 texel = 1.0 / (u_out_res * float(u_ss));
    vec3 s = vec3(0.0);
    for (int j = 0; j < u_ss; ++j)
        for (int i = 0; i < u_ss; ++i)
            s += textureLod(u_accum, uv + (vec2(i, j) + 0.5 - 0.5 * float(u_ss)) * texel, 0.0).rgb;
    return s / float(u_ss * u_ss);
}

// Filtro tienda 3x3 sobre un mip: suaviza el aspecto "pixelado" de los mips bajos.
vec3 tent(vec2 uv, float lod) {
    vec2 t = exp2(lod) / (u_out_res * float(u_ss));
    vec3 s = textureLod(u_accum, uv, lod).rgb * 4.0;
    s += (textureLod(u_accum, uv + vec2(t.x, 0.0), lod).rgb + textureLod(u_accum, uv - vec2(t.x, 0.0), lod).rgb
        + textureLod(u_accum, uv + vec2(0.0, t.y), lod).rgb + textureLod(u_accum, uv - vec2(0.0, t.y), lod).rgb) * 2.0;
    s += textureLod(u_accum, uv + t, lod).rgb + textureLod(u_accum, uv - t, lod).rgb
       + textureLod(u_accum, uv + vec2(t.x, -t.y), lod).rgb + textureLod(u_accum, uv + vec2(-t.x, t.y), lod).rgb;
    return s / 16.0;
}

vec3 bloom(vec2 uv) {
    // Suma de mips desde 1/4 hasta 1/256 de resolución: halo amplio y suave.
    float base = log2(float(u_ss)) + 2.0;
    vec3 b = vec3(0.0);
    float wsum = 0.0;
    for (int i = 0; i < 6; ++i) {
        float w = pow(0.85 * u_bloom_radius, float(i));
        b += tent(uv, base + float(i)) * w;
        wsum += w;
    }
    // Solo lo brillante florece: umbral suave sobre la luminancia.
    vec3 bb = b / wsum;
    float l = dot(bb, vec3(0.2126, 0.7152, 0.0722));
    return bb * smoothstep(0.05, 0.6, l);
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
    if (u_bloom > 0.0) c += bloom(uv) * u_bloom;

    c = aces(c * u_exposure);
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    c = max(mix(vec3(l), c, u_saturation), 0.0);
    c *= 1.0 - u_vignette * smoothstep(0.15, 0.85, length(dir * vec2(u_out_res.x / u_out_res.y, 1.0)) * 0.9);
    c = pow(c, vec3(1.0 / 2.2));
    c = clamp((c - 0.5) * u_contrast + 0.5, 0.0, 1.0);   // contraste en espacio perceptual
    c += (hash12(gl_FragCoord.xy + vec2(u_frame * 17.13, u_frame * 3.71)) - 0.5) * u_grain;
    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}
