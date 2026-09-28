#ifndef VULKAN_RT_THREAD_DATA_H
#define VULKAN_RT_THREAD_DATA_H

#include "vulkan/vulkan.h"

#if defined(MESA_USE_INTEL_DRIVER)
#include "vulkan/vulkan_intel.h"
#endif

#include "vulkan_ray_tracing.h"

// #include "ptx_ir.h"
#include "ptx_ir.h"
#include "../../libcuda/gpgpu_context.h"
#include "compiler/shader_enums.h"
#include <fstream>
#include <cmath>
#include <stack>

#include "compiler/nir/nir.h"

typedef struct variable_decleration_entry
{
    nir_variable_mode type;
    std::string name;
    uint64_t address;
    uint32_t size;
} variable_decleration_entry;

typedef struct Hit_data
{
    VkGeometryTypeKHR geometryType;
    float world_min_thit;
    uint32_t geometry_index;
    uint32_t primitive_index;
    float3 intersection_point;
    float3 barycentric_coordinates;
    int32_t hitGroupIndex; // Shader ID of the closest hit for procedural geometries

    uint32_t instance_index;
    float4x4 worldToObjectMatrix;
    float4x4 objectToWorldMatrix;
} Hit_data;

typedef struct Traversal_data
{
    bool hit_geometry;
    Hit_data closest_hit;
    float3 ray_world_direction;
    float3 ray_world_origin;
    float Tmin;
    float Tmax;
    int32_t current_shader_counter; // set to shader_counter in call_intersection and -1 in call_miss and call_closest_hit
    int32_t current_shader_type;
    uint32_t n_all_hits;
    uint32_t rayFlags;
    uint32_t cullMask;
    uint32_t sbtRecordOffset;
    uint32_t sbtRecordStride;
    uint32_t missIndex;
} Traversal_data;

typedef struct Vulkan_RT_thread_data
{
    std::vector<variable_decleration_entry> variable_decleration_table;

    std::vector<Traversal_data *> traversal_data;
    std::vector<Hit_data *> all_hit_data;

    variable_decleration_entry *get_variable_decleration_entry(nir_variable_mode type, std::string name, uint32_t size)
    {
        if (type == nir_var_ray_hit_attrib)
            return get_hitAttribute();

        for (int i = 0; i < variable_decleration_table.size(); i++)
        {
            if (variable_decleration_table[i].name == name &&
                variable_decleration_table[i].size == size)
            {
                assert(variable_decleration_table[i].address != NULL);
                return &(variable_decleration_table[i]);
            }
        }

        // Payloads alias between the raygen side (function_temp, its own
        // variable name) and the callee side (shader_call_data, always named
        // after the callee's declaration), so name matching fails whenever a
        // pipeline uses more than one payload location/type. The payload
        // location is not carried through rt_alloc_mem, so alias by unique
        // size instead: correct as long as the app's concurrently-live
        // payload types have distinct sizes (holds for Lumen: 20B GrisHit vs
        // 4B AnyHit; single-payload apps like RTIV never reach this).
        if (type == nir_var_shader_call_data)
        {
            variable_decleration_entry *match = NULL;
            int nmatch = 0;
            for (int i = 0; i < variable_decleration_table.size(); i++)
            {
                if (variable_decleration_table[i].size == size &&
                    (variable_decleration_table[i].type == nir_var_function_temp ||
                     variable_decleration_table[i].type == nir_var_shader_call_data))
                {
                    match = &(variable_decleration_table[i]);
                    nmatch++;
                }
            }
            if (nmatch == 1)
            {
                assert(match->address != NULL);
                return match;
            }
        }
        return NULL;
    }

    uint64_t add_variable_decleration_entry(nir_variable_mode type, std::string name, uint32_t size)
    {
        variable_decleration_entry entry;
        entry.type = type;
        entry.name = name;
        // entry.address = (uint64_t) malloc(size);
        entry.address = (uint64_t)VulkanRayTracing::gpgpusim_alloc(size);
        entry.size = size;
        variable_decleration_table.push_back(entry);

        return entry.address;
    }

    variable_decleration_entry *get_hitAttribute()
    {
        variable_decleration_entry *hitAttribute = NULL;
        for (int i = 0; i < variable_decleration_table.size(); i++)
        {
            if (variable_decleration_table[i].type == nir_var_ray_hit_attrib)
            {
                assert(variable_decleration_table[i].address != NULL);
                assert(hitAttribute == NULL); // There should be only 1 hitAttribute
                hitAttribute = &(variable_decleration_table[i]);
            }
        }
        return hitAttribute;
    }

    void set_hitAttribute(float3 barycentric, const ptx_instruction *pI, ptx_thread_info *thread)
    {
        variable_decleration_entry *hitAttribute = get_hitAttribute();
        float *address;
        if (hitAttribute == NULL)
        {
            address = (float *)add_variable_decleration_entry(nir_var_ray_hit_attrib, "attribs", 12);
        }
        else
        {
            assert(hitAttribute->type == nir_var_ray_hit_attrib);
            assert(hitAttribute->address != NULL);
            // hitAttribute->name = name;
            address = (float *)(hitAttribute->address);
        }
        // address[0] = barycentric.x;
        // address[1] = barycentric.y;
        // address[2] = barycentric.z;

        memory_space *mem = thread->get_global_memory();
        mem->write(address, sizeof(float3), &barycentric, thread, pI);
    }
} Vulkan_RT_thread_data;

#endif /* VULKAN_RT_THREAD_DATA_H */