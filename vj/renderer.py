"""Renderizado offscreen con moderngl (GPU, sin ventana)."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import moderngl

from .loop import LoopPlan
from .palette import resolve_palette
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


def load_shader(name: str) -> str:
    src = (SHADER_DIR / name).read_text(encoding="utf-8")
    common = (SHADER_DIR / "common.glsl").read_text(encoding="utf-8")
    return src.replace('#include "common.glsl"', common)


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


class Renderer:
    def __init__(self, cfg: dict, plan: LoopPlan, width: int | None = None, height: int | None = None):
        out = cfg["output"]
        self.plan = plan
        self.width = width or out["width"]
        self.height = height or out["height"]
        self.ss = int(out["supersample"])
        self.blur_samples = int(out["motion_blur"]["samples"])
        self.shutter = float(out["motion_blur"]["shutter"])

        self.ctx = create_context()
        self.gpu = self.ctx.info.get("GL_RENDERER", "?")
        max_tex = self.ctx.info.get("GL_MAX_TEXTURE_SIZE", 16384)
        if max(self.width, self.height) * self.ss > max_tex:
            raise RuntimeError(f"{self.width * self.ss}px supera GL_MAX_TEXTURE_SIZE={max_tex}; "
                               f"reduce output.supersample")

        shader_file, params = resolve_pattern(cfg["geometry"])
        self.pattern = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=load_shader(shader_file))
        self.post = self.ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=load_shader("post.frag"))

        unknown = [k for k in params if f"u_{k}" not in self.pattern]
        if unknown:
            print(f"[vj] aviso: parámetros sin efecto en este shader: {unknown}", file=sys.stderr)

        anim, post = cfg["animation"], cfg["post"]
        set_uniforms(self.pattern, {
            "u_resolution": (float(self.width * self.ss), float(self.height * self.ss)),
            "u_pulse_strength": float(anim["pulse_strength"]),
            "u_pulse_decay": float(anim["pulse_decay"]),
            "u_weight": 1.0 / self.blur_samples,
            **plan.uniforms(),
            **resolve_palette(cfg["palette"]),
            **{f"u_{k}": float(v) for k, v in params.items()},
        })
        set_uniforms(self.post, {
            "u_out_res": (float(self.width), float(self.height)),
            "u_ss": self.ss,
            "u_exposure": float(post["exposure"]),
            "u_vignette": float(post["vignette"]),
            "u_grain": float(post["grain"]),
            "u_ca": float(post["chromatic_aberration"]),
            "u_accum": 0,
        })

        # Acumulador HDR (half float) a resolución supersampleada.
        self.accum = self.ctx.texture((self.width * self.ss, self.height * self.ss), 4, dtype="f2")
        self.accum.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.accum.repeat_x = self.accum.repeat_y = False
        self.accum_fbo = self.ctx.framebuffer(color_attachments=[self.accum])
        self.out_fbo = self.ctx.simple_framebuffer((self.width, self.height), components=4)

        self.pattern_vao = self.ctx.vertex_array(self.pattern, [])
        self.post_vao = self.ctx.vertex_array(self.post, [])

    def render(self, frame: int, wrap: bool = True) -> bytes:
        """Devuelve el frame como RGB24 (filas de abajo hacia arriba, convención GL)."""
        n = self.blur_samples
        self.accum_fbo.use()
        self.accum_fbo.clear(0.0, 0.0, 0.0, 0.0)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.ONE, moderngl.ONE
        for j in range(n):
            # Sub-frames centrados en el frame. Como la fase se envuelve con %1,
            # el motion blur del último frame "ve" el inicio del loop: sin costura.
            offset = ((j + 0.5) / n - 0.5) * self.shutter if n > 1 else 0.0
            self.pattern["u_phase"].value = self.plan.phase(frame + offset, wrap)
            self.pattern_vao.render(moderngl.TRIANGLES, vertices=3)
        self.ctx.disable(moderngl.BLEND)

        self.out_fbo.use()
        self.accum.use(location=0)
        if "u_frame" in self.post:
            self.post["u_frame"].value = float(frame % self.plan.frames)
        self.post_vao.render(moderngl.TRIANGLES, vertices=3)
        return self.out_fbo.read(components=3, alignment=1)

    def release(self) -> None:
        self.ctx.release()
