// SPDX-License-Identifier: BSD-2-Clause-Patent
// The RAM system probe: with ram-system-probe=1 it checks, in its own kernel thread, what the firmware's USB receiver
// handed over through DarwinBoot. The receiver allocates the two containers as independent EfiLoaderData allocations
// (handoff v2: no single window — the fuxi memory map cannot give one contiguous span large enough) and publishes
// their addresses, sizes and SHA-256 digests through the UniXNURamObjects protocol; DarwinBoot validates and
// re-hashes them and writes the live descriptor into the RamSystemObjects property of /chosen/memory-map. The
// objects sit outside the kernel's boot window, in RAM the kernel never owns. The probe re-validates the descriptor
// against the pinned sizes and digests of the iPadOS 17.7.11 (21H461) cryptex containers and re-hashes both objects
// in the kernel's own mapping, then reports one row (fuxi_ram_row) at the end of the touch probe's panic message:
// RAMSYS os@<base> <OK|BAD|..> sys@<base> <OK|BAD|..>, or RAMSYS none / RAMSYS invalid when there is nothing sound
// to report. It publishes nothing and mounts nothing; the publication driver is a separate step that starts from
// this proof.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <libkern/libkern.h>
#include <libkern/crypto/sha2.h>
#include <kern/thread.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <string.h>

namespace {

// The handoff layout, mirroring UniXNURamObjects.h of the firmware handoff protocol (the kernel build has no
// access to the UEFI package): version 2, each object an independent allocation described by its own address.
constexpr uint64_t kOsBytes = 6077580800ULL;               // 044-76040-038.dmg, LZFSE-decoded
constexpr uint64_t kSystemBytes = 3303014400ULL;           // 044-76034-038.dmg, raw APFS
constexpr uint8_t kOsDigest[32] = {
    0xe5, 0x63, 0x4d, 0x04, 0xa8, 0xac, 0x35, 0xf0, 0x24, 0x84, 0x5f, 0x58, 0x33, 0x94, 0xe0, 0xa3,
    0x5d, 0xeb, 0x26, 0xa0, 0x4c, 0xb0, 0xc0, 0x02, 0x86, 0xa8, 0x67, 0x4e, 0x25, 0xa9, 0xa4, 0xf2};
constexpr uint8_t kSystemDigest[32] = {
    0xb4, 0x90, 0x8c, 0xde, 0x41, 0xd2, 0x3e, 0x6b, 0xc0, 0x5e, 0x6a, 0xf5, 0x1a, 0x2c, 0x9e, 0xeb,
    0x00, 0xcf, 0x0f, 0x86, 0x3a, 0x6a, 0x18, 0xb1, 0x60, 0x0c, 0x96, 0xa3, 0xfd, 0x70, 0x41, 0x4f};

struct RamObject {
    uint64_t address;
    uint64_t bytes;
    uint8_t sha256[32];
};
struct RamHandoff {
    uint64_t version, bytes, flags, window, windowBytes;
    RamObject object[2];
};
static_assert(sizeof(RamHandoff) == 136, "the ADT placeholder and the firmware descriptor are 136 bytes");

// 0 not started, 1 hashing, 2 done. Per object: 0 pending, 1 OK, 2 BAD. state: 0 none yet, 1 no descriptor,
// 2 descriptor invalid, 3 hashes evaluated.
int gState = 0;
int gPhase = 0;
int gObject[2] = {0, 0};
uint64_t gBase[2] = {0, 0};

bool hashEquals(uint64_t physical, uint64_t bytes, const uint8_t expected[32]) {
    const uint8_t *cursor = reinterpret_cast<const uint8_t *>(ml_static_ptovirt(static_cast<vm_offset_t>(physical)));
    if (!cursor) return false;
    SHA256_CTX context;
    SHA256_Init(&context);
    while (bytes) {
        size_t chunk = bytes > 0x400000 ? 0x400000 : static_cast<size_t>(bytes);
        SHA256_Update(&context, cursor, chunk);
        cursor += chunk;
        bytes -= chunk;
    }
    uint8_t digest[32];
    SHA256_Final(digest, &context);
    return memcmp(digest, expected, 32) == 0;
}

void ramThread(void *, wait_result_t) {
    // This thread starts beside bsd_init; give the device tree plane a grace period to settle.
    OSData *data = nullptr;
    IORegistryEntry *map = nullptr;
    for (int attempt = 0; attempt < 30 && !data; ++attempt) {
        map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
        data = map ? OSDynamicCast(OSData, map->getProperty("RamSystemObjects")) : nullptr;
        if (!data) {
            if (map) map->release();
            map = nullptr;
            IOSleep(1000);
        }
    }
    if (!data || data->getLength() != sizeof(RamHandoff)) {
        gState = 1;
        gPhase = 2;
        if (map) map->release();
        return;
    }
    RamHandoff handoff;
    memcpy(&handoff, data->getBytesNoCopy(), sizeof handoff);
    map->release();
    bool zero = true;
    for (unsigned i = 0; i < sizeof handoff; ++i) zero = zero && (reinterpret_cast<const uint8_t *>(&handoff)[i] == 0);
    if (zero) {
        gState = 1;
        gPhase = 2;
        return;
    }
    // Handoff v2: no window. Each object stands on its own allocation: pinned size and digest, a nonzero
    // page-aligned base, and the two ranges must not overlap.
    const uint64_t osBase = handoff.object[0].address, sysBase = handoff.object[1].address;
    bool overlap = osBase < sysBase ? (osBase + kOsBytes > sysBase) : (sysBase + kSystemBytes > osBase);
    if (handoff.version != 2 || handoff.bytes != sizeof handoff || handoff.flags != 3 ||
        handoff.window != 0 || handoff.windowBytes != 0 ||
        handoff.object[0].bytes != kOsBytes || handoff.object[1].bytes != kSystemBytes ||
        osBase == 0 || (osBase & 0xFFF) != 0 || sysBase == 0 || (sysBase & 0xFFF) != 0 || overlap ||
        memcmp(handoff.object[0].sha256, kOsDigest, 32) != 0 ||
        memcmp(handoff.object[1].sha256, kSystemDigest, 32) != 0) {
        gState = 2;
        gPhase = 2;
        return;
    }
    gBase[0] = osBase;
    gBase[1] = sysBase;
    gPhase = 1;
    gObject[0] = hashEquals(handoff.object[0].address, handoff.object[0].bytes, kOsDigest) ? 1 : 2;
    gObject[1] = hashEquals(handoff.object[1].address, handoff.object[1].bytes, kSystemDigest) ? 1 : 2;
    gPhase = 2;
}

const char *token(int value) { return value == 1 ? "OK" : value == 2 ? "BAD" : ".."; }

}  // namespace

extern "C" void fuxi_ram_probe_start(void) {
    unsigned requested = 0;
    if (!PE_parse_boot_argn("ram-system-probe", &requested, sizeof requested) || requested != 1 || gPhase != 0) return;
    gPhase = 1;
    thread_t thread = nullptr;
    if (kernel_thread_start(ramThread, nullptr, &thread) == KERN_SUCCESS) thread_deallocate(thread);
    else gState = 2, gPhase = 2;
}

extern "C" const char *fuxi_ram_row(char *out, size_t size) {
    if (!out || size < 56 || gPhase == 0) return "";
    if (gState == 1) {
        snprintf(out, size, "\nRAMSYS none");
    } else if (gState == 2) {
        snprintf(out, size, "\nRAMSYS invalid");
    } else {
        snprintf(out, size, "\nRAMSYS os@%llx %s sys@%llx %s", gBase[0], token(gObject[0]), gBase[1], token(gObject[1]));
    }
    return out;
}
