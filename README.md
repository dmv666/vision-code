# vision-code — generador de VJ loops

Genera visuales tipo festival (túneles, esferas de partículas, caleidoscopios,
hiperespacio, ondas líquidas) en 4K/60fps como **loops perfectos**, a partir de
un archivo JSON/YAML. Renderiza con shaders GLSL en la GPU (moderngl, sin
ventana), mezcla varios patrones por capas, y codifica con ffmpeg (H.264, HEVC
o ProRes, por hardware cuando está disponible) mediante un pipe, sin escribir
frames intermedios a disco.

```bash
python -m vj configs/showcase/cyber_hyperdrive.json --plan          # plan del loop (redondeos)
python -m vj configs/showcase/cyber_hyperdrive.json --preview --stills 4   # 4 PNG rápidos a 960x540
python -m vj configs/showcase/cyber_hyperdrive.json --check-loop    # verificación numérica del loop
python -m vj configs/showcase/cyber_hyperdrive.json                 # render final 4K60
python -m vj configs/hex_tunnel.json --set palette.preset=acid --set output.fps=30 -o renders/acid.mp4
```

`--set` cambia cualquier valor sin editar el archivo. En las capas se entra por
índice o por nombre de patrón:

```bash
python -m vj configs/showcase/liquid_temple.json \
  --set layers.particle_sphere.params.count=1200 \
  --set layers.kaleidoscope.palette.preset=acid \
  --set layers.-1.opacity=0.8 \
  --set animation.bpm=128 --set animation.bars=16 -o renders/liquid_variante.mov
```

Si un patrón aparece dos veces (p. ej. dos `hex_tunnel` en `techno_prism`), usa
el índice (`layers.0`, `layers.1`); el error te indica cuáles hay.

## Interfaz (sin comandos)

```bash
python -m vj.gui          # abre http://127.0.0.1:8765 en el navegador
```

En macOS basta con **doble clic en `Prism Loops Studio.command`** (activa el
`.venv` si existe). La primera vez, si macOS pide confirmación: clic derecho →
Abrir. Para apagarla, cierra la ventana de Terminal que se abre.

- **Izquierda:** todas las configuraciones de `configs/` (buscador incluido).
- **Centro:** vista previa en vivo: se actualiza al mover cualquier control.
  El deslizador recorre el loop; **▶ Animar** lo reproduce en vista rápida;
  **Calidad final** activa supersampling y motion blur; **Comprobar loop** hace
  la verificación numérica. Debajo, el plan del loop y sus redondeos.
- **Derecha:** pestañas Escena (patrón o capas, con sus parámetros), Paleta
  (presets o colores propios), Animación, Salida (resolución, fps, duración,
  codec), Post y JSON.
- **Renderizar:** cola de renders con progreso, fps, tiempo restante, cancelar y
  «Mostrar en Finder». Cada render corre en su propio proceso.
- **Guardar / Guardar como… (⌘S):** escribe en `configs/` (p. ej. `configs/mine/`).

La interfaz solo escucha en `127.0.0.1` (no es accesible desde la red) y no
necesita dependencias extra.

## Instalación en macOS (Apple Silicon o Intel)

```bash
brew install python ffmpeg git              # Homebrew: https://brew.sh
git clone https://github.com/dmv666/vision-code.git && cd vision-code
python3 -m venv .venv && source .venv/bin/activate   # repetir "source" en cada Terminal nueva
pip install -r requirements.txt
python -m vj configs/showcase/neon_core.json --preview --stills 2 && open renders/
```

En Mac el export usa **VideoToolbox** (el codificador por hardware del chip)
automáticamente (`"hardware": "auto"`):

| `codec` | Encoder en Mac | Notas |
|---|---|---|
| `h264` | `h264_videotoolbox` | Universal. Bitrate según `quality` (4K60 high ≈ 60 Mbps) |
| `hevc` | `hevc_videotoolbox` 10 bits | Menos banding y archivos más pequeños; etiqueta `hvc1` (QuickTime) |
| `prores` | `prores_videotoolbox` | Motor ProRes en M1 Pro/Max/Ultra, M2 y posteriores |

Antes de renderizar se prueba cada encoder con 2 frames reales; si el Mac no
tiene ese motor (p. ej. ProRes en un M1 base o un Intel antiguo) se usa el
encoder por software y se avisa en la terminal. `--no-hw` fuerza software
(libx264/libx265 dan algo más de calidad por bit); `--hw` lo fuerza en Linux/Windows (NVENC).
Además, la GPU renderiza el frame siguiente mientras ffmpeg codifica el actual.

Ver en bucle: abre el archivo en QuickTime → *Visualización → Repetir* (⌥⌘L).

> Linux sin pantalla (servidor/contenedor): usa EGL automáticamente. Sin GPU
> funciona en CPU (Mesa llvmpipe), útil solo para previews.

## 1. Arquitectura

```
config.json ──► config.py ──► loop.py ──────────► renderer.py ──────────────► encoder.py ──► .mp4/.mov
  (usuario)     defaults +    velocidades → N      GPU (moderngl):             prueba encoders
                validación    ciclos ENTEROS        capa 1 ┐                    (HW → SW), hilo
                --set         por loop y capa       capa 2 ├► acumulador HDR    + pipe a ffmpeg
                              palette.py ────────►  capa n ┘   → bloom → post → RGB8
                              patterns.py ───────►  shaders/*.frag
```

| Módulo | Responsabilidad |
|---|---|
| `vj/config.py` | Defaults, merge con el JSON/YAML, overrides `--set a.b=valor`, validación, capas |
| `vj/loop.py` | **Matemática del loop**: frames N, fase, cuantización de velocidades a enteros (global y por capa) |
| `vj/palette.py` | Presets y hex → RGB lineal |
| `vj/patterns.py` | Registro de patrones: shader + parámetros por defecto |
| `vj/renderer.py` | Contexto GL offscreen, capas aditivas, supersampling, motion blur, mipmaps para bloom |
| `vj/encoder.py` | Candidatos por codec, prueba de hardware, escritor en hilo, PNG para stills |
| `vj/check.py` | Verificación numérica del loop (CLI e interfaz) |
| `vj/gui/` | Interfaz web local: servidor (`server.py`), GPU y cola de renders (`worker.py`), rangos de controles (`schema.py`), frontend (`static/`) |
| `vj/shaders/core.glsl` | Uniforms y utilidades válidas en vertex y fragment: `palette()`, `pulse()`, `rot()` |
| `vj/shaders/common.glsl` | `core.glsl` + utilidades solo de fragment: `line_aa()`, `centered_uv()`, `emit()` |
| `vj/shaders/<patrón>.frag` | Un archivo por geometría |
| `vj/shaders/post.frag` | Downsample SSAA, bloom, aberración cromática, ACES, saturación/contraste, viñeta, gamma, grano |

Por frame: cada capa se dibuja `motion_blur.samples` veces (sub-frames) en un
buffer float16 a `supersample×` la resolución, sumándose (mezcla aditiva, como
luz). Sus mipmaps alimentan el bloom; el post-proceso reduce a la resolución
final, aplica tonemap y entrega RGB24 a ffmpeg.

### Patrones

| Patrón | Qué es | Parámetros clave |
|---|---|---|
| `hex_tunnel` | Túnel poligonal analítico con anillos, rejilla, paneles y flujos de datos | `sides`, `twist`, `grid`, `streams`, `stream_speed`, `panel_density` |
| `particle_sphere` | Esferas de partículas (Fibonacci) que respiran con el BPM; dibujadas como quads instanciados | `count`, `shells`, `size`, `displacement` |
| `kaleidoscope` | Espejos + pliegues KIFS con zoom infinito log-polar | `segments`, `zoom`, `complexity`, `line_width` (0.002–0.01) |
| `starfield` | Hiperespacio: capas de estrellas con estelas warp | `layers`, `density`, `streak`, `twinkle` |
| `organic_waves` | Curvas de nivel de neón sobre ruido con distorsión de dominio | `bands`, `warp`, `scale`, `horizon` (>0 = suelo synthwave) |
| `aurora_lake` · `deep_sea` · `lava_lounge` · `rainy_city` · `zen_pond` · `desert_dusk` · `firefly_forest` | Escenas chill (ver tabla de configs) | ver `vj/patterns.py` |

**Añadir un patrón**: crea `vj/shaders/<nombre>.frag` con `#include "common.glsl"`,
usa `u_phase` y los contadores enteros, y regístralo en `PATTERNS` con sus
parámetros. Cada clave de `params` llega como uniform `u_<clave>`. Para
elementos discretos (partículas, sprites) usa `"instanced"` como
`particle_sphere`: un vertex shader que posiciona cada instancia es mucho más
rápido que recorrer todos los elementos en cada píxel. No nombres funciones
como las internas de GLSL (`noise1`–`noise4`...): el compilador de macOS lo
rechaza; `glslangValidator` detecta estos casos.

### Configs incluidas

- `configs/*.json`: un patrón cada una (punto de partida).
- `configs/chill/*.json`: escenas tranquilas (sin golpe, movimiento lento, loops de 30–40 s).
  Cada una tiene su propio shader y elementos que no aparecen en ninguna otra:

| Config | Escena | Elementos |
|---|---|---|
| `aurora_lake` | Lago ártico | Cortinas de aurora boreal, montañas, estrellas, reflejo ondulado en el agua |
| `deep_sea` | Fondo marino | Rayos de luz desde la superficie, cáusticas en la arena, burbujas, nieve marina |
| `lava_lounge` | Lámpara de lava | Bolas de cera que se fusionan (metaballs) con brillo e iluminación 3D |
| `rainy_city` | Ciudad bajo la lluvia | Luces desenfocadas (bokeh) a la deriva, gotas que resbalan por el cristal |
| `zen_pond` | Estanque zen | Ondas de gotas sombreadas con normales, hojas de loto, una flor, reflejo de luna |
| `desert_dusk` | Atardecer en el desierto | Dunas en paralaje con sombreado por pendiente, sol, nubes finas, pájaros |
| `firefly_forest` | Bosque de luciérnagas | Troncos en capas, niebla a la deriva, luciérnagas que vagan y parpadean, hierba |

- `configs/showcase/*.json`: composiciones de 3 capas listas para festival:

| Config | Capas | Estilo |
|---|---|---|
| `cyber_hyperdrive` | túnel octogonal con flujos + hiperespacio a corcheas + caleidoscopio | cyberpunk, HEVC |
| `techno_prism` | túnel triangular + túnel interior a contra-giro + estrellas a semicorcheas | rojo/blanco, golpe seco |
| `liquid_temple` | ondas líquidas + caleidoscopio helado + esfera de partículas | synthwave, ProRes HQ |
| `synthwave_horizon` | suelo de neón en perspectiva + cielo estrellado + mandala | sunset |
| `neon_core` | esfera de 3 capas + mandala de 16 espejos + estrellas | neon |

## 2. Archivo de configuración

```jsonc
{
  "output": {
    "path": "renders/cyber_hyperdrive.mp4",
    "width": 3840, "height": 2160, "fps": 60,
    "duration": 16,              // seg; se ignora si animation.bars está definido
    "codec": "hevc",             // h264 | hevc | prores (→ .mov)
    "quality": "high",           // draft|high|master · prores: proxy|lt|standard|hq|4444|xq
    "hardware": "auto",          // auto (sí en macOS) | true | false
    "supersample": 2,            // anti-aliasing SSAA 2×2 (4K → buffer de 7680×4320)
    "motion_blur": { "samples": 4, "shutter": 0.6 }   // shutter 0.5 = 180°
  },
  "palette": {                   // paleta global (cada capa puede tener la suya)
    "preset": "cyberpunk",       // neon | cyberpunk | synthwave | acid | dark_techno | ice | sunset
    "colors": ["#ff2a6d", "#05d9e8"],  // opcional: sustituye al preset (máx. 8, gradiente cíclico)
    "background": "#01012b",
    "intensity": 1.25            // brillo HDR antes del tonemap
  },
  "animation": {                 // animación global (cada capa puede sobrescribir campos)
    "bpm": 128, "bars": 8, "beats_per_bar": 4,   // bars → duración exacta en compases
    "speed": 2.0,                // avance espacial (segmentos/capas por segundo)
    "rotation": 0.0667,          // vueltas por segundo
    "wobble": 0.133,             // oscilaciones secundarias por segundo
    "hue_cycles": 0.0,           // vueltas de paleta por segundo
    "pulse_strength": 0.75, "pulse_decay": 5.5
  },
  "layers": [                    // o un solo patrón con "geometry": {"pattern", "params"}
    { "pattern": "hex_tunnel", "params": { "sides": 8, "streams": 0.9 } },
    {
      "pattern": "starfield",
      "opacity": 0.9,            // perceptual (como un fader de mesa de VJ)
      "params": { "streak": 4.0 },
      "palette": { "colors": ["#ffffff", "#05d9e8"] },
      "animation": { "speed": 0.8, "rotation": -0.0667, "beat_multiplier": 2 }  // 2 = corcheas
    }
  ],
  "post": {
    "exposure": 1.0, "bloom": 0.6, "bloom_radius": 1.1,
    "vignette": 0.45, "grain": 0.015, "chromatic_aberration": 0.002,
    "saturation": 1.1, "contrast": 1.05
  }
}
```

Las velocidades se expresan en unidades "humanas" (por segundo / BPM) y
`loop.py` las ajusta al entero de ciclos más cercano, también por capa.
`--plan` muestra cada ajuste, p. ej. `rotation: 0.938 → 1 ciclos/loop (efectivo 0.0667/s)`.
Todas las capas comparten duración y tempo, así que la composición entera
sigue siendo un loop perfecto.

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
- **Velocidades derivadas dentro del shader.** Los flujos de datos del túnel
  corren a `stream_speed × travel`; el shader usa `floor(travel·stream_speed + 0.5)`
  para que siga siendo un entero. En las ondas orgánicas el pulso usa la altura
  del ruido, no `floor(banda)`, porque el índice de banda avanza `travel` por loop.
- **Efectos que acumulan con el avance.** Un twist en coordenadas de mundo gira
  `twist · L · S` radianes por loop, que no es múltiplo de `2π/lados` → salto. Se
  aplica en coordenadas de cámara.
- **Ruido.** Ruido animado como `noise(x, t)` no es periódico. Usa ruido muestreado
  sobre un círculo: `noise(x, r·cos(2πp), r·sin(2πp))` (o ruido 4D/tileable).
- **Motion blur.** Los sub-frames usan `p ± δ` envuelto con `mod 1`: el blur del
  último frame "ve" el inicio del loop, igual que cualquier otro frame.
- **Grano.** La semilla es `frame mod N`: el frame N tendría el mismo grano que el 0.
- **Rejillas que se desplazan.** Mover una rejilla de celdas aleatorias un número
  entero de celdas *no* basta: se verían celdas distintas (su contenido sale del
  índice). La rejilla debe repetirse (`hash(índice mod P)`) y avanzar `K·P` celdas
  por loop. `vj/shaders/noise.glsl` da ruido así (`tnoise`, `tfbm`).
- **Hash entero.** Para esas celdas se usa `cell_hash` (aritmética `uint`), no
  `hash12`: el hash en float encadena `fract` de productos y, cerca de 0/1, el
  compilador puede redondear distinto en cada llamada (0.001 frente a 0.998). Con
  `hash12` la aurora no cerraba el loop en ~12 000 valores de píxel.
- **`mod` de enteros.** Usa `imod(x, P)` en vez de `mod`: en múltiplos exactos de
  P, el recíproco aproximado de la GPU puede dar `128 mod 64 = 64`.
- **Simulaciones/física** (partículas con estado): no son periódicas por
  naturaleza; hay que usar crossfade entre `F(p)` y `F(p+1)` en la última parte
  o, mejor, formularlas como funciones cerradas de `p` (como aquí).

### 3.5 Verificación automática

`--check-loop` renderiza el frame 0 y el frame N con fase **sin envolver** (`p = 1.0`)
y los compara valor a valor. Falla (código 1) si cualquier valor difiere en más
de 2/255: el criterio es por píxel, no por media, porque un salto local (una
costura en el ruido) puede tener una media casi nula y verse claramente. Un loop
correcto da máx 1 (redondeo); un término no periódico (p. ej. `0.37` vueltas)
da miles de valores fuera — útil en CI o en un batch de renders.

## 4. Notas de producción

- **Tiempo de render 4K60** con SSAA 2× y motion blur 4: cada capa se evalúa
  4 × 33 M píxeles por frame. Túnel, caleidoscopio y ondas son baratos;
  `starfield` cuesta ∝ `layers`. `particle_sphere` dibuja cada partícula como
  un quad instanciado (solo se sombrean los píxeles de su halo), así que miles
  de partículas son baratas. Lo que más pesa es `supersample` (2 = 4× píxeles)
  y `motion_blur.samples` (× pasadas): para un render rápido usa
  `--set output.supersample=1`. La terminal muestra fps y ETA (sin contar el
  primer frame, que incluye compilar shaders); usa `--preview` para iterar.
- **Codec.** H.264 `yuv420p` es universal pero en degradados oscuros puede
  haber banding: el `grain` hace de dithering. HEVC 10 bits lo reduce mucho. ProRes HQ (10 bits 4:2:2) es la
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
