"""Renderizado offscreen con moderngl (GPU, sin ventana)."""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

import moderngl

from .config import layers_of
from .loop import LoopPlan
from .palette import layer_palette, resolve_color_cycle, resolve_palette
from .patterns import resolve_pattern

SHADER_DIR = Path(__file__).parent / "shaders"

VERTEX_SHADER = """
#version 330
void main() {
    // Triángulo que cubre toda la pantalla, sin buffers de vértices.
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""


INCLUDE_RE = re.compile(r'^#include "([^"]+)"\s*$', re.M)


def load_shader(name: str) -> str:
    """Lee un shader resolviendo #include "archivo" de forma recursiva."""
    src = (SHADER_DIR / name).read_text(encoding="utf-8")
    return INCLUDE_RE.sub(lambda m: load_shader(m.group(1)), src)


def create_context() -> moderngl.Context:
    try:
        return moderngl.create_standalone_context(require=330)
    except Exception:
        if sys.platform.startswith("linux"):
            # Servidores / contenedores sin X11: EGL (GPU NVIDIA/AMD/Intel o Mesa llvmpipe).
            return moderngl.create_standalone_context(require=330, backend="egl")
        raise


def set_uniforms(prog: moderngl.Program, values: dict) -> None:
    for name, value in values.items():
        if name not in prog:
            continue  # el compilador elimina uniforms no usados
        uniform = prog[name]
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
            uniform.write(b"".join(struct.pack(f"{len(v)}f", *v) for v in value))
        else:
            uniform.value = value


class Layer:
    def __init__(self, ctx: moderngl.Context, index: int, spec: dict, cfg: dict, plan: LoopPlan,
                 size: tuple[int, int], blur_samples: int):
        self.name = f"layers[{index}]:{spec['pattern']}"
        pattern, params = resolve_pattern(spec)
        self.prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=load_shader(pattern["shader"]))
        self.vao = ctx.vertex_array(self.prog, [])
        self.programs = [self.prog]

        # Geometría instanciada opcional (partículas como quads), dibujada tras la pasada completa.
        self.inst_vao = None
        inst = pattern.get("instanced")
        if inst:
            self.inst_prog = ctx.program(vertex_shader=load_shader(inst["vertex"]),
                                         fragment_shader=load_shader(inst["fragment"]))
            self.inst_vao = ctx.vertex_array(self.inst_prog, [])
            self.instances = 1
            for key in inst["instances"]:
                self.instances *= max(0, int(params[key]))
            self.programs.append(self.inst_prog)

        consumed = set(inst["instances"]) if inst else set()
        unknown = [k for k in params
                   if k not in consumed and not any(f"u_{k}" in prog for prog in self.programs)]
        if unknown:
            print(f"[vj] aviso: {self.name}: parámetros sin efecto: {unknown}", file=sys.stderr)

        anim = cfg["animation"]
        if spec.get("animation"):
            counters = plan.layer_uniforms({**anim, **spec["animation"]}, self.name, explicit=set())
        else:
            counters = {**plan.uniforms(), "u_pulse_strength": float(anim["pulse_strength"]),
                        "u_pulse_decay": float(anim["pulse_decay"])}
        pcfg = layer_palette(cfg["palette"], spec.get("palette"))
        palette = resolve_palette(pcfg)
        palette.update(u_colors_b=palette["u_colors"], u_num_colors_b=palette["u_num_colors"], u_palette_mix=0.0)
        self.cycle = resolve_color_cycle(pcfg)
        self.own_background = index == 0
        if index > 0:
            palette["u_background"] = (0.0, 0.0, 0.0)  # el fondo lo pone solo la primera capa
        values = {
            "u_resolution": (float(size[0]), float(size[1])),
            # Opacidad perceptual: la mezcla es aditiva en luz lineal y la gamma
            # haría que 0.1 se viera como ~35 %. Elevar a 2.2 la hace actuar como un fader.
            "u_weight": float(spec.get("opacity", 1.0)) ** 2.2 / blur_samples,
            **counters,
            **palette,
            **{f"u_{k}": float(v) for k, v in params.items()},
        }
        for prog in self.programs:
            set_uniforms(prog, values)

    def draw(self, phase: float) -> None:
        values = {"u_phase": phase}
        if self.cycle:
            values.update(self.cycle.uniforms(phase))
            if not self.own_background:
                values.pop("u_background")
        for prog in self.programs:
            set_uniforms(prog, values)
        self.vao.render(moderngl.TRIANGLES, vertices=3)
        if self.inst_vao is not None and self.instances:
            self.inst_vao.render(moderngl.TRIANGLES, vertices=6, instances=self.instances)


class Renderer:
    """Renderiza frames de un config. Con `ctx` reutiliza un contexto GL existente
    (la interfaz hace muchas previsualizaciones seguidas); sin él crea uno propio."""

    def __init__(self, cfg: dict, plan: LoopPlan, width: int | None = None, height: int | None = None,
                 ctx: moderngl.Context | None = None):
        out = cfg["output"]
        self.plan = plan
        self.width = width or out["width"]
        self.height = height or out["height"]
        self.ss = int(out["supersample"])
        self.blur_samples = int(out["motion_blur"]["samples"])
        self.shutter = float(out["motion_blur"]["shutter"])

        self.owns_ctx = ctx is None
        self.ctx = ctx or create_context()
        self.gpu = self.ctx.info.get("GL_RENDERER", "?")
        max_tex = self.ctx.info.get("GL_MAX_TEXTURE_SIZE", 16384)
        if max(self.width, self.height) * self.ss > max_tex:
            raise RuntimeError(f"{self.width * self.ss}px supera GL_MAX_TEXTURE_SIZE={max_tex}; "
                               f"reduce output.supersample")

        size = (self.width * self.ss, self.height * self.ss)
        self.layers = [Layer(self.ctx, i, spec, cfg, plan, size, self.blur_samples)
                       for i, spec in enumerate(layers_of(cfg))]

        post = cfg["post"]
        self.bloom = float(post["bloom"]) > 0
        self.post = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=load_shader("post.frag"))
        set_uniforms(self.post, {
            "u_out_res": (float(self.width), float(self.height)),
            "u_ss": self.ss,
            "u_exposure": float(post["exposure"]),
            "u_vignette": float(post["vignette"]),
            "u_grain": float(post["grain"]),
            "u_ca": float(post["chromatic_aberration"]),
            "u_bloom": float(post["bloom"]),
            "u_bloom_radius": float(post["bloom_radius"]),
            "u_saturation": float(post["saturation"]),
            "u_contrast": float(post["contrast"]),
            "u_accum": 0,
        })

        # Acumulador HDR (half float) a resolución supersampleada. Sus mipmaps
        # (versiones reducidas a 1/2, 1/4, 1/8...) son la base del bloom.
        self.accum = self.ctx.texture(size, 4, dtype="f2")
        self.accum.filter = ((moderngl.LINEAR_MIPMAP_LINEAR if self.bloom else moderngl.LINEAR), moderngl.LINEAR)
        self.accum.repeat_x = self.accum.repeat_y = False
        self.accum_fbo = self.ctx.framebuffer(color_attachments=[self.accum])
        self.out_fbo = self.ctx.simple_framebuffer((self.width, self.height), components=4)
        self.post_vao = self.ctx.vertex_array(self.post, [])

    def render(self, frame: int, wrap: bool = True) -> bytes:
        """Devuelve el frame como RGB24 (filas de abajo hacia arriba, convención GL)."""
        n = self.blur_samples
        self.accum_fbo.use()
        self.accum_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE   # mezcla aditiva (luz sobre luz)
        for j in range(n):
            # Sub-frames centrados en el frame. Como la fase se envuelve con %1,
            # el motion blur del último frame "ve" el inicio del loop: sin costura.
            offset = ((j + 0.5) / n - 0.5) * self.shutter if n > 1 else 0.0
            phase = self.plan.phase(frame + offset, wrap)
            for layer in self.layers:
                layer.draw(phase)
        self.ctx.disable(moderngl.BLEND)
        if self.bloom:
            self.accum.build_mipmaps()

        self.out_fbo.use()
        self.accum.use(location=0)
        if "u_frame" in self.post:
            self.post["u_frame"].value = float(frame % self.plan.frames)
        self.post_vao.render(moderngl.TRIANGLES, vertices=3)
        return self.out_fbo.read(components=3, alignment=1)

    def release(self) -> None:
        if self.owns_ctx:
            self.ctx.release()
            return
        # Contexto compartido: liberar solo los objetos de este renderer.
        objs = [self.post_vao, self.post, self.out_fbo, self.accum_fbo, self.accum]
        for layer in self.layers:
            objs += [layer.vao, *layer.programs]
            if layer.inst_vao is not None:
                objs.append(layer.inst_vao)
        for obj in objs:
            obj.release()
