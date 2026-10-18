# Prism Loops — brand assets

YouTube profile pictures and channel banners for **Prism Loops**, rendered with the
same GPU pipeline as the channel's loops (`vj/`): a ray-traced 3D glass prism
with per-channel refraction, spectral light ribbons, caustics, bloom, ACES and
film grain. The text is composited with Pillow.

```bash
python brand/make_brand.py            # all variants, final quality (~2 min on CPU, seconds on a GPU)
python brand/make_brand.py --draft    # quarter resolution, for iterating
python brand/make_brand.py --only logo_orbit banner_flow
```

## Deliverables (`brand/out/`)

| File | Spec | Concept |
|---|---|---|
| `logo_infinity.png` | 2048×2048 PNG, ~3.2 MB | Light leaves the prism and returns as a Möbius ∞ loop (brand palette) |
| `logo_orbit.png` | 2048×2048 PNG, ~3.2 MB | White beam enters; a tilted spectral ring orbits behind and in front of the prism (physical spectrum) |
| `logo_loopbeam.png` | 2048×2048 PNG, ~3.2 MB | White beam enters and exits as a fan that curls back around the prism (cool palette) |
| `banner_flow.jpg` | 2560×1440 JPG, ~0.8 MB | Prism left; the fan opens around the title and twists into loops toward the right edge |
| `banner_horizon.jpg` | 2560×1440 JPG, ~0.8 MB | Title sits on the white beam; prism right with a spectral loop; reflection ribbon to the left edge |
| `banner_strands.jpg` | 2560×1440 JPG, ~0.8 MB | Minimal: fine hairline strands flowing under a wide-geometric title |

`preview_*.png` show each logo with the 70% safe circle and YouTube's circular
crop at 176/98/48 px on dark and light themes, and each banner with the TV,
desktop (2560×423) and mobile/safe (1546×423) areas plus the real crops.

Checked when generating:

- Logos stay inside the central 70% circle and are under YouTube's 4 MB profile-picture limit.
- Banners keep the title and prism inside the 1546×423 safe band, and the right-hand corners of the desktop strip at background level.
- The background renders as exactly `#0A0A12`: the post chain (ACES, saturation, contrast) is inverted to hit it.

## Fonts

Montserrat, Outfit and Michroma (SIL Open Font License, `fonts/OFL.txt`) — free
to use in logos and banners.
