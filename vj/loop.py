"""Matemática del loop perfecto.

Idea central: el tiempo nunca entra a los shaders como segundos, sino como una
FASE normalizada p = frame / N en [0, 1). Todo lo que cambia con el tiempo debe
ser una función periódica de p con periodo 1, es decir, contener solo números
ENTEROS de ciclos por loop. Este módulo convierte las velocidades "humanas"
del config (Hz, BPM, vueltas/seg) en esos enteros y reporta el redondeo.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoopPlan:
    fps: int
    frames: int              # N: se renderizan los frames 0..N-1 (el frame N == frame 0)
    duration: float          # N / fps, duración real del archivo
    travel: int              # ciclos espaciales por loop (segmentos de túnel, capas de zoom)
    rotation: int            # vueltas completas por loop (puede ser negativo)
    wobble: int              # oscilaciones secundarias por loop
    hue_cycles: int          # vueltas de paleta por loop
    beats: int               # golpes de pulso por loop (0 = sin pulso)
    notes: list[str] = field(default_factory=list)

    def phase(self, frame: float, wrap: bool = True) -> float:
        """Fase en [0,1). Acepta frames fraccionarios (sub-frames de motion blur).

        wrap=False deja la fase sin envolver (frame N → 1.0): lo usa --check-loop
        para evaluar de verdad el shader en fase 1 y compararlo con fase 0.
        """
        p = frame / self.frames
        return p % 1.0 if wrap else p

    def uniforms(self) -> dict[str, float]:
        return {
            "u_travel": float(self.travel),
            "u_rotation": float(self.rotation),
            "u_wobble": float(self.wobble),
            "u_hue_cycles": float(self.hue_cycles),
            "u_beats": float(self.beats),
        }


def quantize(rate_per_sec: float, duration: float, name: str, notes: list[str],
             min_abs: int = 0) -> int:
    """Redondea `rate * duration` al entero de ciclos más cercano.

    min_abs=1 evita que algo que pediste en movimiento quede congelado.
    """
    exact = rate_per_sec * duration
    cycles = round(exact)
    if rate_per_sec != 0 and abs(cycles) < min_abs:
        cycles = min_abs if exact > 0 else -min_abs
    if rate_per_sec != 0 and cycles == 0:
        notes.append(f"{name}: {rate_per_sec}/s × {duration:.3f}s = {exact:.3f} ciclos → 0 "
                     f"(queda estático; súbelo o alarga la duración)")
    elif abs(exact - cycles) > 1e-6:
        notes.append(f"{name}: {exact:.3f} → {cycles} ciclos/loop "
                     f"(efectivo {cycles / duration:.4f}/s)")
    return int(cycles)


def plan_loop(cfg: dict) -> LoopPlan:
    out, anim = cfg["output"], cfg["animation"]
    fps = int(out["fps"])
    notes: list[str] = []
    bpm = float(anim.get("bpm") or 0)

    if anim.get("bars"):
        beats = int(anim["bars"]) * int(anim["beats_per_bar"])
        target = beats * 60.0 / bpm
        notes.append(f"duración sincronizada a {anim['bars']} compases @ {bpm:g} BPM = {target:.4f}s")
    else:
        target = float(out["duration"])
        beats = None

    frames = max(1, round(target * fps))
    duration = frames / fps
    if abs(duration - target) > 1e-9:
        notes.append(f"duración {target:.4f}s no es múltiplo de 1/{fps}s → {frames} frames "
                     f"= {duration:.4f}s")

    if beats is None:
        beats = quantize(bpm / 60.0, duration, "pulso (beats)", notes, min_abs=1) if bpm > 0 else 0
    elif bpm > 0:
        real_bpm = beats * 60.0 / duration
        if abs(real_bpm - bpm) > 1e-6:
            notes.append(f"tempo efectivo {real_bpm:.4f} BPM (por redondeo a frames enteros)")

    return LoopPlan(
        fps=fps,
        frames=frames,
        duration=duration,
        travel=quantize(float(anim["speed"]), duration, "speed (travel)", notes, min_abs=1)
        if anim["speed"] else 0,
        rotation=quantize(float(anim["rotation"]), duration, "rotation", notes),
        wobble=quantize(float(anim["wobble"]), duration, "wobble", notes),
        hue_cycles=quantize(float(anim["hue_cycles"]), duration, "hue_cycles", notes),
        beats=beats,
        notes=notes,
    )
