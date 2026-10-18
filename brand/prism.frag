#version 330
// Prism Loops — arte de marca. Prisma de vidrio 3D, haz blanco entrante, cintas
// espectrales que siguen un camino (polilínea) y cáusticas con dispersión.
// Salida HDR lineal; el post-proceso de vj (bloom, ACES, grano) se aplica después.

uniform vec2  u_resolution;

// Prisma 3D trazado por rayos (cámara ortográfica): sección triangular de radio
// u_prism_r, largo u_prism_len, orientado con u_prism_m (mundo → local).
uniform vec2  u_prism_c;
uniform float u_prism_r;
uniform float u_prism_len;
uniform mat3  u_prism_m;
uniform float u_cam_dist;      // distancia de la cámara (perspectiva suave, centrada en el prisma)
uniform vec3  u_ior;           // índice de refracción por canal (dispersión)
uniform float u_edge_w;        // ancho de los biseles brillantes
uniform float u_glass;         // intensidad global del vidrio

// Haz blanco: A → E (entrada) → X (salida, dentro del vidrio).
uniform vec2  u_beam_a;
uniform vec2  u_beam_e;
uniform vec2  u_beam_x;
uniform float u_beam_w;
uniform float u_beam_i;

// Caminos de cintas: (x, y, spread, twist). spread < 0 = ese tramo pasa por detrás
// del prisma; twist = ángulo de giro de la cinta (0 = plana, de frente).
const int MAXP = 160;
uniform vec4  u_path0[MAXP];
uniform int   u_path0_n;
uniform vec4  u_path1[MAXP];
uniform int   u_path1_n;
uniform vec4  u_path2[MAXP];
uniform int   u_path2_n;
uniform vec4  u_ribbon0;       // (intensidad por hebra, ancho de hebra, halo, 1 = ancho fijo)
uniform vec4  u_ribbon1;
uniform vec4  u_ribbon2;
uniform vec2  u_fade0;         // fundido en (inicio, fin) en t ∈ [0,1]
uniform vec2  u_fade1;
uniform vec2  u_fade2;

// Espectro: K colores (ya normalizados en Python) recorridos de violeta a rojo.
const int MAXK = 32;
uniform vec3  u_spec[MAXK];
uniform int   u_spec_n;

uniform vec4  u_text_box;      // (cx, cy, hw, hh): las cintas se atenúan aquí
uniform float u_text_dim;
uniform vec4  u_caustic;       // (cx, cy, radio, intensidad)
uniform vec3  u_bg;
uniform vec3  u_haze;          // color del halo ambiental
uniform float u_haze_i;

out vec4 fragColor;

const float PI = 3.14159265359;
const float TAU = 6.28318530718;

mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

float seg_dist(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h);
}

float line(float d, float w) {
    return exp(-(d * d) / (w * w)) + 0.10 * exp(-abs(d) / (w * 5.0));
}

// Cáustica de agua (algoritmo clásico de joltz0r), estática. El desplazamiento
// −250 mantiene los términos en rango; sin él la función se satura a una constante.
float caustic(vec2 q) {
    vec2 p = mod(q * TAU, TAU) - 250.0;
    vec2 i = p;
    float c = 1.0;
    const float inten = 0.005;
    for (int n = 0; n < 5; n++) {
        float t = 4.0 * (1.0 - 3.5 / float(n + 1));
        i = p + vec2(cos(t - i.x) + sin(t + i.y), sin(t - i.y) + cos(t + i.x));
        c += 1.0 / length(vec2(p.x / (sin(i.x + t) / inten), p.y / (cos(i.y + t) / inten)));
    }
    c /= 5.0;
    c = 1.17 - pow(c, 1.4);
    return pow(abs(c), 8.0);
}

struct Hit { float d; float s; float t; float spread; float depth; float twist; float over; };

vec4 path_pt(int which, int i) { return which == 0 ? u_path0[i] : (which == 1 ? u_path1[i] : u_path2[i]); }

Hit nearest(vec2 p, int which, int n) {
    Hit h; h.d = 1e9; h.s = 0.0; h.t = 0.0; h.spread = 0.0; h.depth = 0.0; h.twist = 0.0; h.over = 0.0;
    for (int i = 0; i < MAXP - 1; ++i) {
        if (i >= n - 1) break;
        vec4 P0 = path_pt(which, i), P1 = path_pt(which, i + 1);
        vec2 a = P0.xy, b = P1.xy;
        vec2 pa = p - a, ba = b - a;
        float raw = dot(pa, ba) / dot(ba, ba);
        float k = clamp(raw, 0.0, 1.0);
        vec2 q = pa - ba * k;
        float d = length(q);
        if (d < h.d) {
            h.d = d;
            // Cuánto se pasa el píxel más allá de los extremos del camino: sin esto, las
            // hebras seguirían como rectas infinitas en la dirección del primer/último tramo.
            float len = length(ba);
            h.over = (i == 0 ? max(-raw, 0.0) : 0.0) * len + (i == n - 2 ? max(raw - 1.0, 0.0) : 0.0) * len;
            vec2 nrm = normalize(vec2(-ba.y, ba.x));
            h.s = dot(pa, nrm);                       // offset con signo respecto al eje
            h.t = (float(i) + k) / float(n - 1);
            h.spread = mix(abs(P0.z), abs(P1.z), k);
            h.depth = (P0.z < 0.0 || P1.z < 0.0) ? -1.0 : 1.0;
            h.twist = mix(P0.w, P1.w, k);
        }
    }
    return h;
}

// Haz de K hebras espectrales alrededor del eje: una cinta plana que gira en 3D
// (el giro comprime las hebras hacia el eje e invierte su orden).
vec3 ribbon(Hit h, vec4 cfg, vec2 fade) {
    if (cfg.x <= 0.0) return vec3(0.0);
    float twist = cos(h.twist);
    float edge_on = clamp(0.55 / (0.4 + abs(twist)), 1.0, 1.4);   // de canto, algo más brillante
    // Fundido en los extremos; 0 = sin fundido (caminos cerrados: anillo, ∞).
    float env = (fade.x > 0.0 ? smoothstep(0.0, fade.x, h.t) : 1.0)
              * (fade.y > 0.0 ? 1.0 - smoothstep(1.0 - fade.y, 1.0, h.t) : 1.0);
    // Ancho de hebra adaptativo: ~0.65 × la separación entre hebras, con cfg.y como
    // mínimo. Banda abierta → arcoíris continuo y saturado; banda estrecha → las
    // hebras se solapan y la luz vuelve a ser blanca (como en un prisma real).
    float n = float(u_spec_n);
    float w = cfg.w > 0.5 ? cfg.y : max(cfg.y, h.spread * abs(twist) / n * 0.65);
    float gain = cfg.y / w;                        // conserva la energía al ensancharse
    env *= exp(-(h.over * h.over) / (w * w * 6.0)) * mix(1.0, gain, 0.6);
    vec3 acc = vec3(0.0);
    for (int k = 0; k < MAXK; ++k) {
        if (k >= u_spec_n) break;
        float lam = (float(k) + 0.5) / float(u_spec_n) - 0.5;
        float d = h.s - h.spread * lam * twist;
        // Halo corto: solo se evalúa la rama más cercana del camino, así que un halo
        // largo dejaría bordes visibles donde dos ramas compiten. El bloom pone el resto.
        acc += u_spec[k] * (exp(-(d * d) / (w * w)) + cfg.z * exp(-abs(d) / (w * 3.5)));
    }
    return acc * cfg.x * env * edge_on;
}

// ---- Vidrio 3D -------------------------------------------------------------
// Poliedro convexo: 3 caras laterales + 2 tapas, como semiespacios dot(N, p) <= D.
vec3 PN[5];
float PD[5];

void build_prism() {
    for (int i = 0; i < 3; ++i) {
        float a = -PI / 2.0 + float(i) * TAU / 3.0;          // normales a -90°, 30°, 150°
        PN[i] = vec3(cos(a), sin(a), 0.0);
        PD[i] = u_prism_r * 0.5;                             // apotema
    }
    PN[3] = vec3(0.0, 0.0, 1.0);  PD[3] = u_prism_len * 0.5;
    PN[4] = vec3(0.0, 0.0, -1.0); PD[4] = u_prism_len * 0.5;
}

bool prism_hit(vec3 o, vec3 d, out float tn, out int face) {
    tn = -1e9; face = 0;
    float tf = 1e9;
    for (int i = 0; i < 5; ++i) {
        float den = dot(PN[i], d);
        float dist = PD[i] - dot(PN[i], o);
        if (abs(den) < 1e-7) { if (dist < 0.0) return false; continue; }
        float t = dist / den;
        if (den < 0.0) { if (t > tn) { tn = t; face = i; } }
        else tf = min(tf, t);
    }
    return tn < tf && tf > 0.0;
}

// Desde dentro: distancia hasta la cara de salida.
float prism_exit(vec3 p, vec3 d, out int face) {
    float t = 1e9; face = 0;
    for (int i = 0; i < 5; ++i) {
        float den = dot(PN[i], d);
        if (den > 1e-7) {
            float tt = (PD[i] - dot(PN[i], p)) / den;
            if (tt < t) { t = tt; face = i; }
        }
    }
    return max(t, 0.0);
}

// Distancia de un punto de una cara a la arista más cercana (resto de planos).
float edge_dist(vec3 p, int face) {
    float e = 1e9;
    for (int i = 0; i < 5; ++i) if (i != face) e = min(e, PD[i] - dot(PN[i], p));
    return e;
}

// Estudio oscuro con softboxes en los colores de marca (las ve el vidrio por
// reflexión y refracción → reflejos iridiscentes).
vec3 env(vec3 d) {
    vec3 c = vec3(0.002, 0.002, 0.005) + vec3(0.006, 0.005, 0.014) * max(d.y, 0.0);
    c += vec3(1.00, 0.97, 1.00) * 7.0 * smoothstep(0.935, 0.975, dot(d, normalize(vec3(-0.45, 0.75, -0.50))));
    c += vec3(0.00, 0.85, 1.00) * 2.4 * smoothstep(0.910, 0.965, dot(d, normalize(vec3(-0.90, -0.10, -0.35))));
    c += vec3(1.00, 0.15, 0.85) * 2.4 * smoothstep(0.910, 0.965, dot(d, normalize(vec3(0.90, 0.20, -0.35))));
    c += vec3(1.00, 0.62, 0.10) * 1.2 * smoothstep(0.920, 0.965, dot(d, normalize(vec3(0.20, -0.90, -0.30))));
    c += vec3(0.45, 0.20, 1.00) * 2.0 * smoothstep(0.900, 0.970, dot(d, normalize(vec3(0.30, 0.55, 0.75))));
    return c;
}

// Devuelve el color del vidrio en este píxel (alpha = cobertura del prisma).
vec4 glass(vec2 uv) {
    mat3 Mi = transpose(u_prism_m);                         // local → mundo
    // Cámara en perspectiva centrada en el prisma: los reflejos recorren las caras
    // como degradados en vez de pintarlas de un color plano (como haría una ortográfica).
    vec3 cam = vec3(0.0, 0.0, -u_cam_dist);
    vec3 o = u_prism_m * cam;
    vec3 d = u_prism_m * normalize(vec3(uv - u_prism_c, 0.0) - cam);
    float tn; int f0;
    if (!prism_hit(o, d, tn, f0)) return vec4(0.0);

    vec3 p = o + d * tn;
    vec3 n = PN[f0];
    float cosi = clamp(-dot(d, n), 0.0, 1.0);
    float F = 0.04 + 0.96 * pow(1.0 - cosi, 5.0);
    vec3 refl = env(Mi * reflect(d, n));

    // Refracción por canal (dispersión) con hasta una reflexión interna total.
    vec3 trans = vec3(0.0);
    float thick = 0.0;
    vec3 p_exit = p;
    int f_exit = 0;
    for (int ch = 0; ch < 3; ++ch) {
        float ior = u_ior[ch];
        vec3 r = refract(d, n, 1.0 / ior);
        int f1;
        float t1 = prism_exit(p + r * 1e-4, r, f1);
        vec3 p1 = p + r * t1;
        vec3 out_d = refract(r, -PN[f1], ior);
        float th = t1;
        if (dot(out_d, out_d) < 1e-6) {                     // reflexión interna total
            vec3 r2 = reflect(r, -PN[f1]);
            int f2;
            float t2 = prism_exit(p1 + r2 * 1e-4, r2, f2);
            out_d = refract(r2, -PN[f2], ior);
            if (dot(out_d, out_d) < 1e-6) out_d = reflect(r2, -PN[f2]);
            th += t2;
        }
        trans[ch] = env(Mi * out_d)[ch];
        if (ch == 1) { thick = th; p_exit = p1; f_exit = f1; }
    }
    // Absorción leve: el vidrio grueso se tiñe de violeta frío.
    vec3 absorb = exp(-thick / u_prism_r * vec3(0.55, 0.45, 0.25));
    vec3 c = refl * F + trans * (1.0 - F) * absorb;
    c += vec3(0.010, 0.011, 0.022) * (1.0 - F);             // cuerpo: nunca negro puro

    // Biseles: brillo en las aristas de las caras visibles, con franja cromática.
    float e = edge_dist(p, f0);
    float w = u_edge_w;
    vec3 bevel = vec3(exp(-e / (w * 1.35)), exp(-e / w), exp(-e / (w * 0.75)));
    c += bevel * vec3(1.0, 0.98, 1.05) * 1.3;
    // Aristas traseras vistas a través del vidrio, más tenues.
    float eb = edge_dist(p_exit, f_exit);
    c += vec3(exp(-eb / (w * 1.2)), exp(-eb / w), exp(-eb / (w * 0.8))) * 0.35 * absorb;
    return vec4(c * u_glass, 1.0);
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution) / u_resolution.y;
    vec3 col = u_bg;

    // ---- Prisma (3D) ------------------------------------------------------
    build_prism();
    vec4 gl = glass(uv);
    bool in_hull = gl.a > 0.5;

    // Halo ambiental alrededor del prisma (luz dispersa en el aire).
    col += u_haze * u_haze_i * exp(-length(uv - u_prism_c) / (u_prism_r * 2.2));

    // Cáusticas con dispersión cromática en una elipse suave.
    if (u_caustic.w > 0.0) {
        vec2 cp = (uv - u_caustic.xy) / u_caustic.z;
        float mask = exp(-dot(cp * vec2(0.8, 1.8), cp * vec2(0.8, 1.8)) * 2.0);
        // Aplastada en vertical: se lee como luz proyectada sobre un suelo.
        vec2 q = (uv - u_caustic.xy) * vec2(1.6, 4.0) + 0.37;
        // Un canal por longitud de onda, con escala ligeramente distinta → bordes irisados.
        vec3 cs = vec3(caustic(q * 0.990), caustic(q * 1.000), caustic(q * 1.012));
        col += cs * mask * u_caustic.w * vec3(1.0, 0.9, 1.15);
    }

    // ---- Cintas ------------------------------------------------------------
    vec3 rib = vec3(0.0);
    if (u_path0_n > 1) {
        Hit h = nearest(uv, 0, u_path0_n);
        vec3 r = ribbon(h, u_ribbon0, u_fade0);
        if (in_hull && h.depth < 0.0) r *= 0.35;       // detrás del vidrio: atenuada
        rib += r;
    }
    if (u_path1_n > 1) {
        Hit h = nearest(uv, 1, u_path1_n);
        vec3 r = ribbon(h, u_ribbon1, u_fade1);
        if (in_hull && h.depth < 0.0) r *= 0.35;
        rib += r;
    }
    if (u_path2_n > 1) {
        Hit h = nearest(uv, 2, u_path2_n);
        vec3 r = ribbon(h, u_ribbon2, u_fade2);
        if (in_hull && h.depth < 0.0) r *= 0.35;
        rib += r;
    }
    float text_keep = 1.0;
    if (u_text_dim > 0.0) {
        vec2 tb = abs(uv - u_text_box.xy) - u_text_box.zw;
        float inside = (1.0 - smoothstep(0.0, 0.07, tb.x)) * (1.0 - smoothstep(0.0, 0.025, tb.y));
        text_keep = 1.0 - u_text_dim * inside;
    }
    col += rib * text_keep;

    // ---- Haz blanco -------------------------------------------------------
    vec3 beam_inner = vec3(0.0);
    if (u_beam_i > 0.0 && u_beam_w > 0.0) {
        float d_in = seg_dist(uv, u_beam_a, u_beam_e);
        float d_mid = seg_dist(uv, u_beam_e, u_beam_x);
        float len_in = length(u_beam_e - u_beam_a);
        float tin = clamp(dot(uv - u_beam_a, u_beam_e - u_beam_a) / (len_in * len_in), 0.0, 1.0);
        float fade_in = smoothstep(0.0, 0.35, tin);
        col += vec3(1.0) * u_beam_i * line(d_in, u_beam_w) * fade_in * text_keep;
        col += vec3(0.010, 0.012, 0.022) * u_beam_i * exp(-d_in / 0.05) * fade_in;   // dispersión en el aire
        // Dentro del vidrio: más brillante y con un leve borde espectral.
        // Dentro del vidrio el haz empieza a abrirse: abanico espectral de E a X.
        vec2 ex = u_beam_x - u_beam_e;
        float tt = clamp(dot(uv - u_beam_e, ex) / dot(ex, ex), 0.0, 1.0);
        vec2 nn = normalize(vec2(-ex.y, ex.x));
        float so = dot(uv - u_beam_e, nn);
        vec3 inner = vec3(0.0);
        for (int k = 0; k < MAXK; ++k) {
            if (k >= u_spec_n) break;
            float lam = (float(k) + 0.5) / float(u_spec_n) - 0.5;
            float dk = so + lam * u_beam_w * 6.0 * tt;
            inner += u_spec[k] * exp(-(dk * dk) / (u_beam_w * u_beam_w * 1.4));
        }
        inner *= 3.0 / float(u_spec_n);
        inner += vec3(0.5, 0.45, 0.9) * exp(-d_mid / (u_beam_w * 6.0)) * 0.12;
        beam_inner = inner * u_beam_i;
        // Destellos en los puntos de entrada y salida.
        for (int f = 0; f < 2; ++f) {
            vec2 fp = (f == 0) ? u_beam_e : u_beam_x;
            vec2 dv = uv - fp;
            float star = exp(-abs(dv.y) / (u_beam_w * 0.5)) * exp(-abs(dv.x) / (u_prism_r * 0.35))
                       + exp(-abs(dv.x) / (u_beam_w * 0.5)) * exp(-abs(dv.y) / (u_prism_r * 0.2)) * 0.6;
            float glow = exp(-length(dv) / (u_beam_w * 2.5));
            col += vec3(1.0, 0.95, 1.0) * (star * 0.25 + glow * 0.9) * u_beam_i * (f == 0 ? 0.5 : 1.0);
        }
    }

    // ---- Vidrio -------------------------------------------------------------
    // El vidrio tapa en parte lo que hay detrás (el haz/cinta que lo atraviesa se
    // redibuja dentro como abanico) y suma sus reflejos y biseles.
    if (in_hull) col = mix(col, u_bg, 0.55) + gl.rgb + beam_inner;

    // Un solo NaN se propagaría a toda la imagen a través de los mipmaps del bloom.
    if (any(isnan(col)) || any(isinf(col))) col = u_bg;
    fragColor = vec4(clamp(col, 0.0, 64.0), 1.0);
}
