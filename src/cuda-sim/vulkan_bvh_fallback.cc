// Builds a flat 2-wide node_t BVH over world-space triangles using the same
// bvh library RayTracingInVulkan uses to produce its bindings-12/13/14 BVH
// (bvh_fallback/ is a copy of RayTracingInVulkan/src/bvh with includes
// rewritten), so the fallback BVH is directly comparable to the RTIV baseline.
//
// Kept in its own translation unit: the builder library's bvh::Bvh is a
// different definition from the traversal-side struct in bvh/bvh.hpp included
// by vulkan_ray_tracing.cc.

#include "vulkan_bvh_fallback.h"

#include <cstring>
#include <cstdio>

#include "bvh_fallback/bvh.hpp"
#include "bvh_fallback/triangle.hpp"
#include "bvh_fallback/sweep_sah_builder.hpp"
#include "bvh_fallback/utilities.hpp"

void fallback_build_flat_bvh(const std::vector<fallback_trig> &trigs,
                             std::vector<fallback_node> &out_nodes,
                             std::vector<size_t> &out_primitive_indices)
{
    typedef bvh::Bvh<float> fb_bvh_t;
    typedef bvh::Triangle<float> fb_triangle_t;
    typedef bvh::SweepSahBuilder<fb_bvh_t> fb_builder_t;

    // Same leaf limit as RTIV's BottomLevelAccelerationStructure: primitive
    // counts must fit the 3-bit field of pack_child_info.
    const size_t max_trig_in_leaf_size = 7;

    std::vector<fb_triangle_t> prims;
    prims.reserve(trigs.size());
    for (size_t i = 0; i < trigs.size(); i++)
    {
        const float(*v)[3] = trigs[i].v;
        prims.emplace_back(bvh::Vector3<float>(v[0][0], v[0][1], v[0][2]),
                           bvh::Vector3<float>(v[1][0], v[1][1], v[1][2]),
                           bvh::Vector3<float>(v[2][0], v[2][1], v[2][2]));
    }

    auto boxes_centers = bvh::compute_bounding_boxes_and_centers(prims.data(), prims.size());
    auto global_bbox = bvh::compute_bounding_boxes_union(boxes_centers.first.get(), prims.size());

    fb_bvh_t fb;
    fb_builder_t builder(fb);
    builder.max_leaf_size = max_trig_in_leaf_size;
    builder.build(global_bbox, boxes_centers.first.get(), boxes_centers.second.get(), prims.size());

    fb.convert_nodes(fb.nodes, fb.node_count);

    static_assert(sizeof(fallback_node) == sizeof(fb_bvh_t::Node_v2),
                  "fallback_node must match the builder's Node_v2 layout");
    out_nodes.resize(fb.node_count_v2);
    std::memcpy(out_nodes.data(), fb.nodes_v2.get(), fb.node_count_v2 * sizeof(fallback_node));

    out_primitive_indices.assign(fb.primitive_indices.get(),
                                 fb.primitive_indices.get() + prims.size());

    printf("gpgpusim: fallback BVH built: %zu triangles, %zu nodes\n",
           trigs.size(), out_nodes.size());
    fflush(stdout);
}
