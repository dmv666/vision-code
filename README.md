# vision-code — generador de VJ loops

Genera visuales tipo festival (túneles, esferas de partículas, caleidoscopios) en
4K/60fps como **loops perfectos**, a partir de un archivo JSON/YAML. Renderiza
con shaders GLSL en la GPU (moderngl, sin ventana) y codifica con ffmpeg
(H.264 o ProRes) mediante un pipe, sin escribir frames intermedios a disco.

```bash
pip install -r requirements.txt          # + ffmpeg en el PATH
python -m vj configs/hex_tunnel.json --plan          # ver el plan del loop (redondeos)
python -m vj configs/hex_tunnel.json --preview --stills 4   # 4 PNG rápidos a 960x540
python -m vj configs/hex_tunnel.json --check-loop    # verificación numérica del loop
python -m vj configs/hex_tunnel.json                 # render final 4K60
python -m vj configs/hex_tunnel.json --set palette.preset=acid --set output.fps=30 -o renders/acid.mp4
```

> Linux sin pantalla (servidor/contenedor): usa EGL automáticamente. Con GPU
> NVIDIA instala el driver con soporte EGL; sin GPU funciona en CPU (Mesa
> llvmpipe), útil solo para previews.

## 1. Arquitectura

```
config.json ──► config.py ──► loop.py ──────────► renderer.py ─────────► encoder.py ──► .mp4/.mov
  (usuario)     defaults +    velocidades → N      GPU (moderngl):        ffmpeg pipe
                validación    ciclos ENTEROS        patrón → acumulador    H.264 / ProRes
                --set         por loop              HDR → post → RGB8
                              palette.py ─────────►    ▲
                              patterns.py ────────►  shaders/*.frag
```

| Módulo | Responsabilidad |
|---|---|
| `vj/config.py` | Defaults, merge con el JSON/YAML, overrides `--set a.b=valor`, validación |
| `vj/loop.py` | **Matemática del loop**: frames N, fase, cuantización de velocidades a enteros |
| `vj/palette.py` | Presets y hex → RGB lineal |
| `vj/patterns.py` | Registro de patrones: shader + parámetros por defecto |
| `vj/renderer.py` | Contexto GL offscreen, supersampling, motion blur por acumulación, post |
| `vj/encoder.py` | Comandos ffmpeg por codec, PNG para stills |
| `vj/shaders/common.glsl` | Uniforms compartidos, `palette()`, `pulse()`, `line_aa()` |
| `vj/shaders/<patrón>.frag` | Un archivo por geometría |
| `vj/shaders/post.frag` | Downsample SSAA, aberración cromática, ACES, viñeta, gamma, grano |

Por frame: el patrón se dibuja `motion_blur.samples` veces (sub-frames) en un
buffer float16 a `supersample×` la resolución, sumándose; el post-proceso lo
reduce a la resolución final, aplica tonemap y lo entrega como RGB24 a ffmpeg.

**Añadir un patrón** (p. ej. ondas orgánicas): crea `vj/shaders/organic_waves.frag`
con `#include "common.glsl"`, usa `u_phase` y los contadores enteros, y regístralo
en `PATTERNS` con sus parámetros. Cada clave de `geometry.params` llega como
uniform `u_<clave>`.

## 2. Archivo de configuración

```jsonc
{
  "output": {
    "path": "renders/hex_tunnel.mp4",
    "width": 3840, "height": 2160, "fps": 60,
    "duration": 16,              // seg; se ignora si animation.bars está definido
    "codec": "h264",             // h264 | h264_nvenc | prores (→ .mov)
    "quality": "high",           // h264: draft|high|master · prores: proxy|lt|standard|hq|4444
    "supersample": 2,            // anti-aliasing SSAA 2×2 (4K → buffer de 7680×4320)
    "motion_blur": { "samples": 4, "shutter": 0.5 }   // shutter 0.5 = 180°
  },
  "geometry": {
    "pattern": "hex_tunnel",     // hex_tunnel | particle_sphere | kaleidoscope
    "params": { "sides": 6, "twist": 0.06, "grid": 3 }  // ver vj/patterns.py
  },
  "palette": {
    "preset": "cyberpunk",       // neon | cyberpunk | synthwave | acid | dark_techno | ice | sunset
    "colors": ["#ff2a6d", "#05d9e8"],  // opcional: sustituye al preset (máx. 8, gradiente cíclico)
    "background": "#01012b",
    "intensity": 1.2             // brillo HDR antes del tonemap
  },
  "animation": {
    "bpm": 128, "bars": 8, "beats_per_bar": 4,   // bars → duración exacta en compases
    "speed": 2.0,                // avance espacial (segmentos/capas por segundo)
    "rotation": 0.0625,          // vueltas por segundo
    "wobble": 0.125,             // oscilaciones secundarias por segundo
    "hue_cycles": 0.0,           // vueltas de paleta por segundo
    "pulse_strength": 0.7, "pulse_decay": 5.0
  },
  "post": { "exposure": 1.1, "vignette": 0.4, "grain": 0.015, "chromatic_aberration": 0.0015 }
}
```

Las velocidades se expresan en unidades "humanas" (por segundo / BPM) y
`loop.py` las ajusta al entero de ciclos más cercano. `--plan` muestra cada
ajuste, p. ej. `rotation: 0.938 → 1 ciclos/loop (efectivo 0.0667/s)`.

## 3. Matemática del loop perfecto

### 3.1 Frames y fase

Con duración `T` y `fps`, el loop tiene

```
N = round(T · fps)      frames, numerados 0 … N-1
p(i) = i / N            fase ∈ [0, 1)
```

El shader **nunca recibe segundos**, solo la fase `p`. Toda la animación es una
función `F(p)` y el loop es perfecto si y solo si

```
F(1) = F(0)          (periodicidad)
```

Entonces la transición del último frame al primero, `F((N-1)/N) → F(0)`, es
idéntica a `F((N-1)/N) → F(N/N)`, es decir, a un paso normal de `1/N` de fase.
No hay costura porque matemáticamente no existe un "final".

**Error clásico:** exportar también el frame `N` (o renderizar `0…T` incluido).
Como `F(1) = F(0)`, el reproductor muestra el mismo fotograma dos veces seguidas y
se nota un micro-parón en cada vuelta. Se renderizan `0…N-1`, nunca `N`.

### 3.2 Toda magnitud animada debe dar un número entero de ciclos

Cualquier término de la forma `g(K · p)` con `g` periódica de periodo 1 cumple
`g(K·1) = g(K·0)` **solo si K es entero**. Por eso:

| Elemento | Expresión en el shader | Condición |
|---|---|---|
| Rotación | `θ = 2π · R · p` | `R` = vueltas por loop, entero (`R = round(rot_hz · T)`) |
| Oscilación | `sin(2π · W · p + φ)` | `W` entero; armónicos `2W, 3W…` también valen |
| Pulso/BPM | `exp(-k · fract(B · p))` | `B` = golpes por loop, entero |
| Avance de túnel | `w = z + L · S · p`, se usa `fract(w / S)` | `L` segmentos por loop, entero (patrón con periodo espacial `S`) |
| Zoom infinito | `log(r)·z − L·p` en log-polar, `fract()` | `L` entero |
| Ciclo de color | `palette(x + H · p)` con paleta cíclica | `H` entero |

`loop.py` hace `K = round(velocidad · T)` y avisa si el redondeo deja algo en 0.
Ejemplo (`hex_tunnel.json`): 8 compases a 128 BPM → `T = 8·4·60/128 = 15 s`,
`N = 900`, `B = 32` beats exactos; `speed 2/s → L = 30` segmentos; rotación
`0.0625/s · 15 = 0.94 → R = 1` vuelta.

### 3.3 Sincronizar con la música

Para que el loop encaje en una sesión, su duración debe ser un número entero de
compases: `T = compases · beats_por_compás · 60 / BPM`. Si `T · fps` no es entero
(124 BPM, 4 compases, 60 fps → 464.5 frames ✗), se redondea `N` (465) y el tempo
efectivo queda ligeramente desviado (`--plan` lo muestra: 123.87 BPM).
El loop sigue siendo perfecto; solo cambia el BPM real. Para tempo exacto, elige
combinaciones donde `compases · 4 · 60 · fps / BPM` sea entero (128 BPM: 8 compases ✓ a 24/30/60 fps).

### 3.4 Trampas sutiles (resueltas en los shaders)

- **Valores derivados del índice de un elemento que avanza.** En el túnel, el
  anillo que ocupa la posición `z` en el frame `N` es el que estaba `L` posiciones
  detrás en el frame 0. Si su color o su parpadeo dependieran de `hash(id)`, el
  frame N mostraría colores distintos. Solución: `hash(mod(id, L))`, o hacer que
  el color dependa de la profundidad de cámara, no del mundo.
- **Efectos que acumulan con el avance.** Un twist en coordenadas de mundo gira
  `twist · L · S` radianes por loop, que no es múltiplo de `2π/lados` → salto. Se
  aplica en coordenadas de cámara.
- **Ruido.** Ruido animado como `noise(x, t)` no es periódico. Usa ruido muestreado
  sobre un círculo: `noise(x, r·cos(2πp), r·sin(2πp))` (o ruido 4D/tileable).
- **Motion blur.** Los sub-frames usan `p ± δ` envuelto con `mod 1`: el blur del
  último frame "ve" el inicio del loop, igual que cualquier otro frame.
- **Grano.** La semilla es `frame mod N`: el frame N tendría el mismo grano que el 0.
- **Simulaciones/física** (partículas con estado): no son periódicas por
  naturaleza; hay que usar crossfade entre `F(p)` y `F(p+1)` en la última parte
  o, mejor, formularlas como funciones cerradas de `p` (como aquí).

### 3.5 Verificación automática

`--check-loop` renderiza el frame 0 y el frame N con fase **sin envolver** (`p = 1.0`)
y mide la diferencia media por píxel. Un loop correcto da ~0.0007 (error de
coma flotante); si se introduce un término no periódico (p. ej. `0.37` vueltas)
da ~49 y el comando falla con código 1 — útil en CI o en un batch de renders.

## 4. Notas de producción

- **Tiempo de render 4K60** con SSAA 2× y motion blur 4: el patrón se evalúa
  4 × 33 M píxeles por frame. En una GPU moderna son milisegundos para el túnel
  y el caleidoscopio; `particle_sphere` es O(partículas) por píxel (bájalo con
  `count`/`shells` o `supersample: 1` si va lento). Usa `--preview` para iterar.
- **Codec.** H.264 `yuv420p` es universal pero en degradados oscuros puede
  haber banding: el `grain` hace de dithering. ProRes HQ (10 bits 4:2:2) es la
  opción de máster; ProRes 4444 si necesitas más calidad de color. Para Resolume
  el formato óptimo es **DXV**/HAP: renderiza ProRes y transcodifica con Alley o
  `ffmpeg -c:v hap`.
- **GOP**: un keyframe por segundo (`-g fps`) para que el seek/scratch en el
  software de VJ sea fluido.
- Para 8K o `supersample: 3` en 4K revisa la VRAM: el acumulador es RGBA16F a
  resolución supersampleada (≈265 MB para 4K × SSAA 2).

## Alternativa: Blender (bpy)

La misma matemática aplica: `frame_start = 1`, `frame_end = N` (no `N+1`),
keyframes de rotación en `2π·R` con interpolación lineal y extrapolación cíclica,
y drivers con `#frame / N` como fase. Este proyecto usa shaders porque un
fragment shader es una función pura de `p` (periodicidad garantizada, render
por frame en milisegundos), mientras que Cycles/EEVEE añaden muestreo estocástico
y tiempos de minutos por frame en 4K.
