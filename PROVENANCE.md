# Provenance of this fork (wxrrr123/vulkan-sim)

## Branch `upstream-port` (current, from 2026-09-30)

This branch **is** upstream Vulkan-Sim plus our changes. It contains none of
AQB8's modifications. The AQB8-based branch `divergence-study` is kept
unchanged as a historical reference; its provenance is further below.

### Base

- **ubc-aamodt-group/vulkan-sim `dc742faa`** (2023-10-10, "change interconnect
  configs"; upstream `main`).
- Paired with **ubc-aamodt-group/mesa-vulkan-sim `b8f3e3980e8`** (upstream
  `main`), with our changes on wxrrr123/mesa-vulkan-sim branch `upstream-port`.
- Ray traversal, and the BVH memory transactions it generates, are upstream's
  (Intel GEN_RT_BVH packed by Mesa, `maxLeafSize` 1).

### Commits on this branch

| Commit | Content | Author |
|---|---|---|
| `02e62a53` | Lumen-required fixes, category (b) below | us |
| `49efceba` | Closest-hit selection fix, cherry-picked from upstream (see below) | Lucy Liu (upstream) |
| `6a6dd8ee` | Commit non-opaque hits when no any-hit shader exists (see below) | us |

### Category (b) fixes carried over from `divergence-study` (`02e62a53`)

Only changes that Lumen needs on any Vulkan-Sim version. Taken from
`divergence-study` `34474d31` and `a6af1968` as the diff against AQB8
`baseline-2wide`, i.e. our changes only.

- Multiple descriptor sets: `MAX_DESCRIPTOR_SETS` 1 -> 8, descriptor lookup by setID.
- Buffer device addresses: registered from Mesa, identity-bound into the
  simulator's address map at `vkCmdTraceRaysKHR`.
- Push constants: captured from `vkCmdPushConstants`, copied into each
  thread's `push_const` variable in `rt_alloc_mem`.
- Raygen shader selected from the SBT handle instead of shader ID 0
  (multiple RT pipelines).
- `getTexture`: storage vs sampled images, format-aware reads (rgba32f,
  rgba16 unorm, rgba16f, rgba8, sRGB decoded to linear).
- Image store: pixel data written back to the image's host memory (so later
  image loads see it), per-image float dumps, more formats.
- `image_deref_load`: sets the lane's effective address for the timing model.
- Ray payloads: aliased by size when names differ (two payload types).
- L2: odd-size requests split into per-sector requests.
- `ray_coherency_engine`: counters initialized; drained pool handled.
- `scripts/generate_rt_ptxinfo.py`: register types normalized for ptxas.

Not carried over (only needed for the AQB8 tree): the fallback flat BVH
(`vulkan_bvh_fallback.*`, `bvh_fallback/`), the binding-12/13/14 guard, the
disabled `transaction_record`; debug output (ATOMRES, NULLLOAD, ICI, RAYSTAT,
MISSSTAT, PC/UBO/FLAGS/LIGHTS dumps, BVHCK).

### Closest-hit fix (`49efceba`)

Cherry-picked (`git cherry-pick -x`) from upstream commit **`17656474`**
("closest-hit bug patch", author **Lucy Liu**, **2024-09-24**), on upstream
branch **`25-incorrect-selection-of-closest-hit-primitive`**, which is not
merged into upstream `main`. On `main`, every triangle hit inside
[tmin, tmax] overwrote the recorded closest hit, so a farther triangle could be
reported instead of the nearest one.

### Any-hit fix (`6a6dd8ee`)

On upstream, a hit on a ray without the Opaque flag is only committed by the
any-hit loop that Mesa's PTX lowering emits when the pipeline contains an
any-hit shader. Lumen has no any-hit shader, so such hits were never
committed and the ray was reported as a miss; Lumen's shadow rays
(TerminateOnFirstHit | SkipClosestHitShader, no Opaque flag) then saw every
light (classroom frame-1 output 2.5x too bright, correlation 0.41).

Basis, Vulkan specification, chapter "Ray Traversal", section "Ray
Intersection Confirmation", subsection "Triangle and Generated Intersection
Candidates":

> If the any-hit shader identified is VK_SHADER_UNUSED_KHR, the candidate is
> immediately confirmed as a valid hit and passes to the next stage of
> processing.

Fix: when no any-hit shader is registered, the ray is treated as opaque, so
the hit is confirmed.

**Limitation:** the check is over **all registered shaders**, not per hit
group. If an application has an any-hit shader in some hit group, rays that
hit geometry of a hit group without one still go through the old path, and
their non-opaque hits are still not committed. Correct for Lumen (no any-hit
shader at all); a per-hit-group check would need the SBT hit group record at
traversal time.

### Validation (classroom 128x128, depth 8, N=3, MOBILE, LUMEN_FIXED_SEED=1)

Against the `divergence-study` baseline: frame-1 output correlation 0.9994,
thread instruction counts within 0.21% per kernel, ray counts within 0.3%.
Cycles +54% in total (only kernels that trace rays), from BVH memory traffic
that the `divergence-study` tree did not generate.

---

## Branch `divergence-study` (AQB8-based, historical; kept unchanged)

This branch is **not** upstream Vulkan-Sim plus our changes. It is the
**AQB8** research tree plus our changes.

### Base

- **AQB8** (nycu-caslab, "Energy-Efficient Ray Tracing Accelerator through
  Multi-Level Quantization"), configuration `baseline-2wide`: the
  uncompressed, unquantized control configuration of that study
  (github.com/nycu-caslab/AQB8, branch `baseline-2wide`, directory `vulkan-sim/`).
- AQB8 `baseline-2wide` is itself based on upstream
  **ubc-aamodt-group/vulkan-sim `dc742faa`** (2023-10-10, "change interconnect
  configs"; this is also upstream `main`).
- It reached us as the Docker image `ycpin/aqb8-vulkan-sim`: an upstream
  `dc742faa` checkout with the AQB8 modifications present as uncommitted
  working-tree changes.

### Commits on this branch

| Commit | Content | Author of the changes |
|---|---|---|
| `34474d31` | "Baseline": everything uncommitted at the time | AQB8 **and** us (see below) |
| `a6af1968` | Texture sampling: decode `*_SRGB` formats to linear | us |
| `0fa5569d` | Reorder unit step 1: `reorder_thread_nv` pseudo-instruction | us |
| `d5a7b38f` | Reorder unit step 2: SM-level collect/release, full sort | us |

### File attribution of `34474d31` (53 files changed relative to `dc742faa`)

Determined by comparing each file with AQB8 `baseline-2wide`.

**13 files identical to AQB8 (AQB8's modifications, untouched by us):**
`src/abstract_hardware_model.cc`, `src/abstract_hardware_model.h`,
`src/cuda-sim/bvh/bvh.hpp`, `src/cuda-sim/cuda-sim.cc`, `src/cuda-sim/cuda-sim.h`,
`src/cuda-sim/memory.cc`, `src/cuda-sim/ptx_sim.h`, `src/gpgpu-sim/gpu-cache.cc`,
`src/gpgpu-sim/gpu-cache.h`, `src/gpgpu-sim/gpu-sim.cc`, `src/gpgpu-sim/shader.cc`,
`src/gpgpu-sim/shader.h`, `version_detection.mk`.

**9 files = AQB8's version plus our changes** (diff lines relative to AQB8):
`src/cuda-sim/vulkan_ray_tracing.cc` (804), `scripts/generate_rt_ptxinfo.py` (57),
`src/cuda-sim/instructions.cc` (55), `src/gpgpu-sim/l2cache.cc` (43),
`src/cuda-sim/vulkan_ray_tracing.h` (37), `src/cuda-sim/vulkan_rt_thread_data.h` (32),
`src/cuda-sim/gpgpusim_calls_from_mesa.cc` (26), `src/gpgpu-sim/ray_coherency_engine.cc` (21),
`src/cuda-sim/Makefile` (8).

**31 files added by us:** `src/cuda-sim/vulkan_bvh_fallback.{cc,h}` and
`src/cuda-sim/bvh_fallback/*.hpp` (29 headers: the header-only BVH builder
library copied from AQB8's RayTracingInVulkan `src/bvh/`, includes rewritten).

Later commits (`a6af1968` onward) are entirely ours, including their edits to
files that were AQB8-identical in `34474d31` (e.g. `shader.cc`, `cuda-sim.cc`).

### What the two layers do

- **AQB8** replaced upstream's ray traversal (walking the Intel GEN_RT_BVH that
  Mesa packs into the acceleration-structure buffer) with a flat BVH
  (`node_t`/`trig_t`) that the application uploads through descriptor
  bindings 12/13/14 (AQB8's modified RayTracingInVulkan does this). Their other
  changes in the 13 + 9 files were not analysed individually.
- **Us** (Lumen / ReSTIR PT port): a fallback that builds the same flat BVH from
  triangles and instances captured at acceleration-structure build time, for
  applications that do not use bindings 12/13/14 (Lumen); functional and timing
  fixes needed by Lumen's shaders; sRGB texture decode; the thread reorder unit.

### BVH memory traffic is disabled

`transaction_record` in `VulkanRayTracing::traceRay` (the code that turns each
BVH node/triangle access into a memory transaction for the RT unit) is active
in AQB8 but **was disabled (body commented out) by us in early July 2026**
during the Lumen port; it is already disabled in our 2026-07-08 backup. No
reason was recorded; the likely one is that the fallback BVH lives in host
memory without simulated addresses (`bvh_*_addr` are NULL). Consequence: in
this tree, ray traversal generates **no BVH memory traffic** for any
application, fallback or bindings path. Upstream (`main` and the newer
`generalized-tta` branch) does generate it.

### Correction

The message of `34474d31` says it is a "snapshot of the simulator
modifications made across earlier research sessions" and "none of this is new
work". That is inaccurate: 13 of its files are AQB8's modifications verbatim
and 9 more contain AQB8's modifications. The attribution above is the correct
one. History is not rewritten; this file is the correction.
