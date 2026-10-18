// Cabecera de los fragment shaders de patrones: core.glsl + utilidades que solo
// existen en la etapa de fragment (fwidth, gl_FragCoord).
#include "core.glsl"

out vec4 fragColor;

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
