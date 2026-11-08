// SPDX-License-Identifier: BSD-2-Clause-Patent
// Fuxi minimal glue for the GopFramebuffer Legacy display provider
// (CPU-first route, round 1: provider registration and main CADisplay
// enumeration only; no CPU presentation is enabled by the first-round
// boot arguments).
//
// This file provides exactly the two initialisation entry points the
// framework patch series calls (native_legacy_display_probe /
// native_legacy_display_late_probe) and the 18 board callbacks the
// fixed GopFramebuffer component (19ef3a75) declares. The callbacks
// are observation-only counters plus the component contract points:
// backend_guard is noreturn by contract, prepare_scanout permits
// scanout (the fuxi boot-progress layer exports no scanout
// prepare/cancel pair, so the kernel console and any presented frame
// share the GOP framebuffer; that is an evidence-quality caveat for
// presentation judging, not a registration blocker), and gpu_offer
// returns false so no GPU presenter is ever engaged on this route.
//
// Only phase 4 (park at the early probe, start at the late probe,
// DT-plane display-subsystem attach) is implemented; any other phase
// value fails closed. The late probe starts the display and nothing
// else: no other subsystem probes are aggregated here.
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOUserClient.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSerialize.h>
#include <libkern/c++/OSData.h>
#include <libkern/libkern.h>
#include <kern/task.h>
#include <pexpert/pexpert.h>
#include <mach/kmod.h>
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void native_legacy_display_static_init(void) __asm__("__GLOBAL__sub_I_NativeLegacyDisplay.cpp");
extern "C" IOService *native_legacy_display_allocate(void);
extern "C" kern_return_t OSKextLoadKextWithIdentifier(const char *);

static IOService *pendingLegacyDisplay;
static IOService *activeLegacyDisplay;
static IOService *activeGOPNub;

extern "C" {
// Stage of the two-probe lifecycle: 0 idle, 1 early probe entered,
// 2 PE console validated, 3 object allocated, 4 late probe building
// the nub, 5 display attached, 6 late probe failed (rolled back),
// 7 object released unstarted, 8 terminal, 10 started (phase 4).
volatile uint32_t fuxi_legacy_stage;
volatile int fuxi_legacy_meta_status = -1;
volatile uint32_t fuxi_legacy_init_result, fuxi_legacy_start_result, fuxi_legacy_probe_match;
volatile uint32_t fuxi_legacy_object_size, fuxi_legacy_released;
volatile uint64_t fuxi_legacy_object, fuxi_legacy_nub;
volatile uint32_t fuxi_legacy_guard_slot;
volatile uint64_t fuxi_legacy_guard_object, fuxi_legacy_guard_caller;
volatile int fuxi_legacy_surface_status = -1;
volatile uint32_t fuxi_legacy_surface_found;
volatile uint64_t fuxi_legacy_video_base, fuxi_legacy_video_bytes;
volatile uint64_t fuxi_legacy_gop_map, fuxi_legacy_gop_virtual, fuxi_legacy_gop_physical, fuxi_legacy_gop_bytes;
volatile uint32_t fuxi_legacy_gop_width, fuxi_legacy_gop_height;
volatile uint32_t fuxi_legacy_registration_calls, fuxi_legacy_properties_length;
volatile uint32_t fuxi_legacy_dt_attached;
volatile uint32_t fuxi_legacy_pm_stage, fuxi_legacy_pm_calls;
volatile int fuxi_legacy_pm_status = -1;
volatile uint32_t fuxi_legacy_pm_ordinal;
volatile uint32_t fuxi_legacy_swap_validation_calls, fuxi_legacy_swap_accepted, fuxi_legacy_swap_rejected_count;
volatile uint32_t fuxi_legacy_swap_validation_reason;
volatile uint64_t fuxi_legacy_rej_surface[7];
volatile uint32_t fuxi_legacy_transfer_calls;
volatile int fuxi_legacy_transfer_status = -1;
volatile uint64_t fuxi_legacy_transfer_bytes;
volatile uint32_t fuxi_legacy_retirement_calls;
volatile uint32_t fuxi_legacy_frame_calls, fuxi_legacy_frame_colors_calls;
volatile uint32_t fuxi_legacy_copy_calls;
volatile uint64_t fuxi_legacy_copy_bytes;
volatile uint32_t fuxi_legacy_prepare_calls;
volatile uint32_t fuxi_legacy_gpu_offer_calls, fuxi_legacy_gpu_fallbacks;
volatile int fuxi_legacy_gpu_last_status = -1;
volatile uint32_t fuxi_legacy_vsync_events[6];
volatile uint32_t fuxi_legacy_vsync_hz;
volatile uint32_t fuxi_legacy_client_calls, fuxi_legacy_client_type;
volatile int fuxi_legacy_client_status = -1;
volatile uint32_t fuxi_legacy_swap_stage_calls[4];
char fuxi_legacy_properties[4096];
}

// ---------------------------------------------------------------------------
// The 18 component callbacks (observation-only; see the file header).
// The component declares every one of them extern "C"
// (NativeLegacyDisplay.cpp), so the definitions must carry C linkage:
// as plain C++ definitions their symbols are mangled and the kernel
// link fails on the component's _native_legacy_* imports (Build #95).

extern "C" {

__attribute__((noreturn)) void native_legacy_backend_guard(unsigned slot, void *object, void *caller) {
    fuxi_legacy_guard_slot = slot;
    fuxi_legacy_guard_object = (uintptr_t)object;
    fuxi_legacy_guard_caller = (uintptr_t)caller;
    panic("FuxiLegacyDisplay: leaf=%u caller=%llx stage=%u pm=%u swap=%u/%u copy=%08x retire=%u",
          slot, (uint64_t)(uintptr_t)caller, fuxi_legacy_stage, fuxi_legacy_pm_stage,
          fuxi_legacy_swap_accepted, fuxi_legacy_swap_rejected_count,
          (unsigned)fuxi_legacy_transfer_status, fuxi_legacy_retirement_calls);
}

bool native_legacy_gop_mapping_observed(IOService *object, IOMemoryMap *mapping, uint32_t width, uint32_t height) {
    fuxi_legacy_gop_map = (uintptr_t)mapping;
    if (mapping) {
        fuxi_legacy_gop_virtual = mapping->getVirtualAddress();
        fuxi_legacy_gop_physical = mapping->getPhysicalAddress();
        fuxi_legacy_gop_bytes = mapping->getLength();
    }
    fuxi_legacy_gop_width = width;
    fuxi_legacy_gop_height = height;
    (void)object;
    return true;
}

void native_legacy_registration_observed(IOService *display) {
    fuxi_legacy_registration_calls = fuxi_legacy_registration_calls + 1;
    OSSerialize *xml = OSSerialize::withCapacity(2048);
    if (xml && display && display->serializeProperties(xml)) {
        unsigned size = xml->getLength();
        if (size >= sizeof(fuxi_legacy_properties)) size = sizeof(fuxi_legacy_properties) - 1;
        memcpy(fuxi_legacy_properties, xml->text(), size);
        fuxi_legacy_properties[size] = 0;
        fuxi_legacy_properties_length = size;
    }
    OSSafeReleaseNULL(xml);
    printf("fuxi-legacy: registration observed calls=%u stage=%u\n",
           fuxi_legacy_registration_calls, fuxi_legacy_stage);
}

void native_legacy_swap_stage(unsigned stage) {
    if (stage < 4) fuxi_legacy_swap_stage_calls[stage] = fuxi_legacy_swap_stage_calls[stage] + 1;
}

void native_legacy_client_enter(task_t task, uint32_t type) {
    fuxi_legacy_client_calls = fuxi_legacy_client_calls + 1;
    fuxi_legacy_client_type = type;
    (void)task;
}

void native_legacy_client_observed(IOReturn status, IOUserClient *client) {
    fuxi_legacy_client_status = status;
    (void)client;
}

void native_legacy_pm_observed(unsigned stage, IOReturn status, unsigned long ordinal) {
    fuxi_legacy_pm_stage = stage;
    fuxi_legacy_pm_status = status;
    fuxi_legacy_pm_ordinal = (uint32_t)ordinal;
    fuxi_legacy_pm_calls = fuxi_legacy_pm_calls + 1;
}

void native_legacy_frame_observed(unsigned kind, uint64_t count, uint64_t minx, uint64_t miny, uint64_t maxx, uint64_t maxy) {
    fuxi_legacy_frame_calls = fuxi_legacy_frame_calls + 1;
    (void)kind; (void)count; (void)minx; (void)miny; (void)maxx; (void)maxy;
}

void native_legacy_frame_colors_observed(const uint32_t *colors, const uint64_t *counts, uint64_t other) {
    fuxi_legacy_frame_colors_calls = fuxi_legacy_frame_colors_calls + 1;
    (void)colors; (void)counts; (void)other;
}

void native_legacy_swap_validation_observed(bool accepted, unsigned reason, const void *request, const void *surface) {
    fuxi_legacy_swap_validation_calls = fuxi_legacy_swap_validation_calls + 1;
    if (accepted) fuxi_legacy_swap_accepted = fuxi_legacy_swap_accepted + 1;
    else fuxi_legacy_swap_rejected_count = fuxi_legacy_swap_rejected_count + 1;
    fuxi_legacy_swap_validation_reason = reason;
    (void)request; (void)surface;
}

void native_legacy_surface_rejected(uint64_t width, uint64_t height, uint32_t format, uint32_t planes,
                                    uint64_t stride, uint64_t allocation, uint64_t bytes) {
    fuxi_legacy_rej_surface[0] = width;
    fuxi_legacy_rej_surface[1] = height;
    fuxi_legacy_rej_surface[2] = format;
    fuxi_legacy_rej_surface[3] = planes;
    fuxi_legacy_rej_surface[4] = stride;
    fuxi_legacy_rej_surface[5] = allocation;
    fuxi_legacy_rej_surface[6] = bytes;
}

bool native_legacy_prepare_scanout(void) {
    fuxi_legacy_prepare_calls = fuxi_legacy_prepare_calls + 1;
    return true;
}

void native_legacy_transfer_observed(IOReturn status, const void *request, uint64_t bytes) {
    fuxi_legacy_transfer_calls = fuxi_legacy_transfer_calls + 1;
    fuxi_legacy_transfer_status = status;
    fuxi_legacy_transfer_bytes = bytes;
    (void)request;
}

void native_legacy_copy_timing_observed(uint64_t ticks, uint64_t bytes) {
    fuxi_legacy_copy_calls = fuxi_legacy_copy_calls + 1;
    fuxi_legacy_copy_bytes = fuxi_legacy_copy_bytes + bytes;
    (void)ticks;
}

void native_legacy_retirement_observed(IOService *display) {
    fuxi_legacy_retirement_calls = fuxi_legacy_retirement_calls + 1;
    (void)display;
}

bool native_legacy_gpu_offer(void *display, IOMemoryDescriptor *memory, uint64_t stride,
                             uint32_t width, uint32_t height, uint32_t format) {
    fuxi_legacy_gpu_offer_calls = fuxi_legacy_gpu_offer_calls + 1;
    (void)display; (void)memory; (void)stride; (void)width; (void)height; (void)format;
    return false;
}

void native_legacy_gpu_fallback_observed(int status) {
    fuxi_legacy_gpu_last_status = status;
    fuxi_legacy_gpu_fallbacks = fuxi_legacy_gpu_fallbacks + 1;
}

void native_legacy_vsync_observed(unsigned event, unsigned hz) {
    if (event < 6) fuxi_legacy_vsync_events[event] = fuxi_legacy_vsync_events[event] + 1;
    fuxi_legacy_vsync_hz = hz;
}

}  // extern "C" (the 18 component callbacks above)

// ---------------------------------------------------------------------------
// Early probe: register the component metaclasses once, allocate and
// initialise the display object, and park it for the late probe. The
// patch series reaches this entry from two call sites, so the stage
// guard makes it idempotent.

extern "C" {
// The framework patch series declares both probe entry points as
// plain C: patches/xnu/offline-component-load-probes.patch and
// patches/xnu/offline-legacy-start.patch patch bsd/kern/bsd_init.c
// with `extern void native_legacy_display_probe(void);` and
// `extern void native_legacy_display_late_probe(void);`. The
// definitions therefore carry C linkage; as plain C++ definitions
// they exported only the mangled names, and Build #96's final kernel
// link failed on _native_legacy_display_probe and
// _native_legacy_display_late_probe.

void native_legacy_display_probe(void);
void native_legacy_display_probe(void) {
    if (fuxi_legacy_stage) return;
    fuxi_legacy_stage = 1;
    void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (!handle) {
        printf("fuxi-legacy: early probe: preModLoad failed\n");
        return;
    }
    native_legacy_display_static_init();
    fuxi_legacy_meta_status = OSMetaClass::postModLoad(handle);
    if (fuxi_legacy_meta_status) {
        printf("fuxi-legacy: early probe: postModLoad status=%d\n", fuxi_legacy_meta_status);
        return;
    }
    PE_Video video = {};
    fuxi_legacy_stage = 2;
    if (PE_current_console(&video) || !video.v_baseAddr || !video.v_width || !video.v_height ||
        video.v_depth != 32 || video.v_rotate || video.v_width > 16384 || video.v_height > 16384 ||
        video.v_rowBytes < video.v_width * 4 || video.v_rowBytes > UINT64_MAX / video.v_height) {
        printf("fuxi-legacy: early probe: PE console video rejected\n");
        return;
    }
    IOService *display = native_legacy_display_allocate();
    fuxi_legacy_object = (uintptr_t)display;
    if (!display) {
        printf("fuxi-legacy: early probe: allocate failed\n");
        return;
    }
    fuxi_legacy_object_size = display->getMetaClass()->getClassSize();
    fuxi_legacy_stage = 3;
    fuxi_legacy_init_result = display->init();
    unsigned phase = 1;
    PE_parse_boot_argn("offline-legacy-phase", &phase, sizeof(phase));
    if (fuxi_legacy_init_result && (phase == 2 || phase == 3 || phase == 4)) {
        // IOSurface matches the genuine IOBSD resource, published by
        // bsd_autoconf; retain the object until that boundary.
        pendingLegacyDisplay = display;
        printf("fuxi-legacy: early probe: parked phase=%u size=%u\n", phase, fuxi_legacy_object_size);
        return;
    }
    fuxi_legacy_stage = 7;
    display->release();
    fuxi_legacy_released = 1;
    fuxi_legacy_stage = 8;
    printf("fuxi-legacy: early probe: released unstarted init=%u phase=%u\n",
           fuxi_legacy_init_result, phase);
}

// ---------------------------------------------------------------------------
// Late probe (after IOKitBSDInit): wait for the genuine IOSurface
// root, build the GOP provider nub over the exact PE framebuffer
// range, and probe/attach/start the parked display. Phase 4 also
// publishes the nub in the device-tree plane as the display
// subsystem. Any failure rolls back in exact reverse order and
// releases the display unstarted.

void native_legacy_display_late_probe(void);
void native_legacy_display_late_probe(void) {
    IOService *display = pendingLegacyDisplay;
    if (!display) return;
    pendingLegacyDisplay = nullptr;
    fuxi_legacy_surface_status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOSurface");
    OSDictionary *matching = IOService::nameMatching("IOCoreSurfaceRoot");
    IOService *surface = matching ? IOService::waitForMatchingService(matching, 5000000000ULL) : nullptr;
    fuxi_legacy_surface_found = surface != nullptr;
    OSSafeReleaseNULL(surface);
    OSSafeReleaseNULL(matching);
    PE_Video video = {};
    if (!fuxi_legacy_surface_status && fuxi_legacy_surface_found && !PE_current_console(&video) &&
        video.v_baseAddr && video.v_width && video.v_height && video.v_depth == 32 &&
        !video.v_rotate && video.v_width <= 16384 && video.v_height <= 16384 &&
        video.v_rowBytes >= video.v_width * 4 && video.v_rowBytes <= UINT64_MAX / video.v_height) {
        fuxi_legacy_video_base = video.v_baseAddr;
        fuxi_legacy_video_bytes = video.v_rowBytes * video.v_height;
        // A plain service over the real firmware framebuffer range
        // from the GOP handoff; no invented compatible, display
        // list, panel timing or vendor registers.
        fuxi_legacy_stage = 4;
        IOService *nub = new IOService;
        fuxi_legacy_nub = (uintptr_t)nub;
        bool nubAttached = false, nubStarted = false, attached = false, started = false;
        IORegistryEntry *displayTreeParent = nullptr;
        bool dtAttached = false;
        IOService *parent = IOService::getResourceService();
        IODeviceMemory *memory = IODeviceMemory::withRange(video.v_baseAddr, video.v_rowBytes * video.v_height);
        OSArray *ranges = OSArray::withCapacity(1);
        if (nub && memory && ranges && parent && nub->init()) {
            ranges->setObject(memory);
            nub->setDeviceMemory(ranges);
            nub->setName("NativeGOPFramebuffer");
            nubAttached = nub->attach(parent);
            if (nubAttached) nubStarted = nub->start(parent);
            if (nubStarted) {
                unsigned phase = 0;
                PE_parse_boot_argn("offline-legacy-phase", &phase, sizeof(phase));
                if (phase == 4) {
                    displayTreeParent = IORegistryEntry::fromPath("/arm-io", gIODTPlane);
                    const char type[] = "display-subsystem";
                    OSData *data = OSData::withBytes(type, sizeof(type));
                    if (displayTreeParent && data && nub->setProperty("device_type", data)) {
                        nub->setName("gop-display", gIODTPlane);
                        dtAttached = nub->attachToParent(displayTreeParent, gIODTPlane);
                    }
                    OSSafeReleaseNULL(data);
                    fuxi_legacy_dt_attached = dtAttached;
                }
                SInt32 score = 0;
                fuxi_legacy_probe_match = (phase != 4 || dtAttached) && display->probe(nub, &score) == display;
                if (fuxi_legacy_probe_match) attached = display->attach(nub);
                if (attached) {
                    fuxi_legacy_stage = 5;
                    started = display->start(nub);
                    fuxi_legacy_start_result = started;
                }
                if (started && phase == 4) {
                    activeLegacyDisplay = display;
                    activeGOPNub = nub;
                    fuxi_legacy_stage = 10;
                    OSSafeReleaseNULL(displayTreeParent);
                    printf("fuxi-legacy: late probe: started base=%llx bytes=%llx dt=%u\n",
                           fuxi_legacy_video_base, fuxi_legacy_video_bytes, fuxi_legacy_dt_attached);
                    return;
                }
            }
        }
        fuxi_legacy_stage = 6;
        if (started) display->stop(nub);
        if (attached) display->detach(nub);
        if (dtAttached) nub->detachFromParent(displayTreeParent, gIODTPlane);
        if (nubStarted) nub->stop(parent);
        if (nubAttached) nub->detach(parent);
        OSSafeReleaseNULL(ranges);
        OSSafeReleaseNULL(memory);
        OSSafeReleaseNULL(nub);
        OSSafeReleaseNULL(displayTreeParent);
    }
    fuxi_legacy_stage = 7;
    display->release();
    fuxi_legacy_released = 1;
    fuxi_legacy_stage = 8;
    printf("fuxi-legacy: late probe: released unstarted surface_status=%d found=%u\n",
           fuxi_legacy_surface_status, fuxi_legacy_surface_found);
}

}  // extern "C" (the two probe entry points above)
