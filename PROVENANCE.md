# Provenance of this fork (wxrrr123/vulkan-sim, branch `divergence-study`)

This branch is **not** upstream Vulkan-Sim plus our changes. It is the
**AQB8** research tree plus our changes.

## Base

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

## Commits on this branch

| Commit | Content | Author of the changes |
|---|---|---|
| `34474d31` | "Baseline": everything uncommitted at the time | AQB8 **and** us (see below) |
| `a6af1968` | Texture sampling: decode `*_SRGB` formats to linear | us |
| `0fa5569d` | Reorder unit step 1: `reorder_thread_nv` pseudo-instruction | us |
| `d5a7b38f` | Reorder unit step 2: SM-level collect/release, full sort | us |

## File attribution of `34474d31` (53 files changed relative to `dc742faa`)

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

## What the two layers do

- **AQB8** replaced upstream's ray traversal (walking the Intel GEN_RT_BVH that
  Mesa packs into the acceleration-structure buffer) with a flat BVH
  (`node_t`/`trig_t`) that the application uploads through descriptor
  bindings 12/13/14 (AQB8's modified RayTracingInVulkan does this). Their other
  changes in the 13 + 9 files were not analysed individually.
- **Us** (Lumen / ReSTIR PT port): a fallback that builds the same flat BVH from
  triangles and instances captured at acceleration-structure build time, for
  applications that do not use bindings 12/13/14 (Lumen); functional and timing
  fixes needed by Lumen's shaders; sRGB texture decode; the thread reorder unit.

## BVH memory traffic is disabled

`transaction_record` in `VulkanRayTracing::traceRay` (the code that turns each
BVH node/triangle access into a memory transaction for the RT unit) is active
in AQB8 but **was disabled (body commented out) by us in early July 2026**
during the Lumen port; it is already disabled in our 2026-07-08 backup. No
reason was recorded; the likely one is that the fallback BVH lives in host
memory without simulated addresses (`bvh_*_addr` are NULL). Consequence: in
this tree, ray traversal generates **no BVH memory traffic** for any
application, fallback or bindings path. Upstream (`main` and the newer
`generalized-tta` branch) does generate it.

## Correction

The message of `34474d31` says it is a "snapshot of the simulator
modifications made across earlier research sessions" and "none of this is new
work". That is inaccurate: 13 of its files are AQB8's modifications verbatim
and 9 more contain AQB8's modifications. The attribution above is the correct
one. History is not rewritten; this file is the correction.
