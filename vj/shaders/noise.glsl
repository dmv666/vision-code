// Ruido de valor periódico en x (tileable), para escenas que se desplazan en
// horizontal sin romper el loop. Se incluye después de common.glsl.
//
// tnoise(p, P) repite cada P celdas en x (P entero). Si una escena se desplaza
// `K·P` celdas por loop con K entero, vuelve exactamente al inicio. tfbm duplica
// la frecuencia y el periodo en cada octava, así que la propiedad se conserva.

float tnoise(vec2 p, float period) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    float x0 = imod(i.x, period);
    float x1 = imod(i.x + 1.0, period);
    float a = cell_hash(vec2(x0, i.y));
    float b = cell_hash(vec2(x1, i.y));
    float c = cell_hash(vec2(x0, i.y + 1.0));
    float d = cell_hash(vec2(x1, i.y + 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float tfbm(vec2 p, float period, int octaves) {
    float s = 0.0, a = 0.5, norm = 0.0;
    for (int i = 0; i < 6; ++i) {
        if (i >= octaves) break;
        s += a * tnoise(p, period);
        norm += a;
        p = p * 2.0 + vec2(0.0, 3.17);       // solo desplazamiento en y: conserva el periodo
        period *= 2.0;
        a *= 0.5;
    }
    return s / norm;
}
