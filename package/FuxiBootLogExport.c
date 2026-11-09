// SPDX-License-Identifier: MIT
// The bounded pipeline-cache export half of V2's BootLog.c, isolated from the
// background log writer.  In particular this file contains no reset,
// autoreset, panic-reboot or fastboot path.
//
// NativeAdrenoPublish accepts ordered pieces from user space through
// boot_log_export_put().  Two halves of NativeUfs's export window alternate,
// so the last completed generation remains intact while the next one is being
// written.  The final 16 MiB stays reserved for the V2 crash-export layout.
#include <stdint.h>
#include <string.h>
#include <IOKit/IOLib.h>

extern uint64_t native_ufs_export_blocks(void);
extern int native_ufs_export_write(uint64_t, uint32_t, const void *);

enum {
    FuxiExportBlock = 4096,
    FuxiExportStageBlocks = 64,
    FuxiExportCrashBlocks = 4096,
};

static IOLock *fuxi_export_lock;
static uint8_t *fuxi_export_stage;
static uint32_t fuxi_export_total;
static uint32_t fuxi_export_filled;
static uint32_t fuxi_export_generation;
static uint32_t fuxi_export_target;

volatile uint32_t fuxi_boot_export_ready;
volatile uint32_t fuxi_boot_export_ready_bytes;
volatile uint32_t fuxi_boot_export_ready_first;
volatile int32_t fuxi_boot_export_last_status;

static IOLock *
fuxi_export_get_lock(void)
{
    IOLock *lock = __atomic_load_n(&fuxi_export_lock, __ATOMIC_ACQUIRE);
    if (lock != NULL) {
        return lock;
    }
    IOLock *candidate = IOLockAlloc();
    if (candidate == NULL) {
        return NULL;
    }
    IOLock *expected = NULL;
    if (!__atomic_compare_exchange_n(&fuxi_export_lock, &expected, candidate,
        false, __ATOMIC_RELEASE, __ATOMIC_ACQUIRE)) {
        IOLockFree(candidate);
    }
    return __atomic_load_n(&fuxi_export_lock, __ATOMIC_ACQUIRE);
}

int
boot_log_export_put(uint32_t generation, uint32_t total, uint32_t offset,
    const void *data, uint32_t size)
{
    if (generation == 0 || total == 0 || data == NULL || size == 0 ||
        offset > total || size > total - offset) {
        fuxi_boot_export_last_status = -1;
        return -1;
    }
    IOLock *lock = fuxi_export_get_lock();
    if (lock == NULL) {
        fuxi_boot_export_last_status = -2;
        return -2;
    }

    IOLockLock(lock);
    int status = 0;
    const uint64_t region64 = native_ufs_export_blocks();
    if (region64 > UINT32_MAX) {
        status = -4;
    }
    const uint32_t region = status ? 0 : (uint32_t)region64;
    const uint32_t half = region / 2;
    const uint32_t usable = half > FuxiExportCrashBlocks ?
        half - FuxiExportCrashBlocks : 0;
    const uint32_t stage_bytes = FuxiExportStageBlocks * FuxiExportBlock;
    if (usable == 0) {
        status = -4;
    } else if ((uint64_t)total > (uint64_t)usable * FuxiExportBlock) {
        status = -5;
    }
    if (status == 0 && fuxi_export_stage == NULL) {
        fuxi_export_stage = (uint8_t *)IOMallocAligned(stage_bytes,
            FuxiExportBlock);
        if (fuxi_export_stage == NULL) {
            status = -2;
        }
    }
    if (status == 0 && offset == 0) {
        fuxi_export_generation = generation;
        fuxi_export_total = total;
        fuxi_export_filled = 0;
        fuxi_export_target = fuxi_boot_export_ready != 0 &&
            fuxi_boot_export_ready_first == 0 ? half : 0;
    }
    if (status == 0 && (generation != fuxi_export_generation ||
        total != fuxi_export_total || offset != fuxi_export_filled)) {
        status = -3;
    }

    const uint8_t *from = (const uint8_t *)data;
    while (status == 0 && size != 0) {
        const uint32_t at = fuxi_export_filled % stage_bytes;
        const uint32_t room = stage_bytes - at;
        const uint32_t count = size < room ? size : room;
        memcpy(fuxi_export_stage + at, from, count);
        fuxi_export_filled += count;
        from += count;
        size -= count;
        const int full = at + count == stage_bytes;
        const int done = fuxi_export_filled == fuxi_export_total;
        if (full || done) {
            const uint32_t used = at + count;
            const uint32_t blocks =
                (used + FuxiExportBlock - 1) / FuxiExportBlock;
            if (used % FuxiExportBlock != 0) {
                memset(fuxi_export_stage + used, 0,
                    blocks * FuxiExportBlock - used);
            }
            const uint64_t first = fuxi_export_target +
                (fuxi_export_filled - used) / FuxiExportBlock;
            if (!native_ufs_export_write(first, blocks,
                fuxi_export_stage)) {
                status = -6;
                fuxi_export_generation = 0;
            }
        }
        if (status == 0 && done) {
            fuxi_boot_export_ready = fuxi_export_generation;
            fuxi_boot_export_ready_bytes = fuxi_export_total;
            fuxi_boot_export_ready_first = fuxi_export_target;
        }
    }
    fuxi_boot_export_last_status = status;
    IOLockUnlock(lock);
    return status;
}
