#ifndef VULKAN_BVH_FALLBACK_H
#define VULKAN_BVH_FALLBACK_H

#include <cstdint>
#include <cstddef>
#include <vector>

// Fallback flat-BVH builder for apps that do not provide the pre-built
// node_t/trig_t BVH at descriptor bindings 12/13/14 (RayTracingInVulkan does;
// standard Vulkan apps like Lumen don't). These are plain-layout mirrors of
// bvh_t's Trig/Node (bvh/bvh.hpp): the builder lives in its own translation
// unit (vulkan_bvh_fallback.cc) because it includes the full RTIV builder
// library, whose bvh::Bvh definition differs from the traversal-side one.

struct fallback_trig
{
    float v[3][3]; // world-space triangle vertices, same layout as trig_t
};

struct fallback_node
{
    float left_bounds[6];
    float right_bounds[6];
    uint32_t left_child_data;
    uint32_t right_child_data;
};

// What a real TLAS/BLAS traversal would have reported for each flat triangle.
struct fallback_prim_meta
{
    uint32_t instance_custom_index; // -> gl_InstanceCustomIndexEXT
    uint32_t geometry_index;        // -> gl_GeometryIndexEXT
    uint32_t primitive_index;       // -> gl_PrimitiveID (within the instance's geometry)
};

void fallback_build_flat_bvh(const std::vector<fallback_trig> &trigs,
                             std::vector<fallback_node> &out_nodes,
                             std::vector<size_t> &out_primitive_indices);

#endif // VULKAN_BVH_FALLBACK_H
