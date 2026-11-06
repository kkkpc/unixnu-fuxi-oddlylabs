// SPDX-License-Identifier: MIT
// Fuxi boot-progress observer: weak no-op definitions of the thirteen
// boot_progress_* entry points that patches/xnu/zzz-boot-progress.patch
// declares in osfmk/kern/boot_progress.h when CONFIG_XNU_BOOT_PROGRESS=y.
// The baseline (UniXNU scripts/build-xnu-4k-baseline.sh) builds this file
// into build/boot-progress/libBootProgress.a and force-loads the archive;
// the verified UFS driver polls boot_progress_poll() while reading, and the
// patch's call sites in arm_init, startup, the consoles, bsd_init,
// kern_exec, sleh and kern_exit call the rest.
//
// This is deliberately a no-op observer, not the full monitor that
// UniXNU-sheng ships as package/BootProgress.c: that monitor renders
// stages to the raw framebuffer, keeps a process census and enforces a
// watchdog launch policy, and this kernel has no working display path yet.
// The observer's only load-bearing job here is satisfying the link, and
// boot_progress_active() returning 0 keeps console output on the real
// console. The definitions are weak, as the verified UFS driver expects
// ("the source runtime archive carries a weak no-op definition").
//
// One exception since the persistent Data stage (2026-11-06):
// boot_progress_exit prints the NativeRamBlock persist counters on every
// process exit. No renderer on this board reads those counters and the
// attach's IOLog lines scroll off long before the exit report, so
// without this the persist stage's result is invisible on the only
// evidence source the board has, the photographed console. The first
// version printed once, at the first exit; chain52's photograph
// (2026-11-06) showed the photographed screen is the console tail - the
// LAST exit-reason report - so the once-only rows scrolled off. The
// rows now repeat, and the copy at the final report carries the final
// counter values.
#include <stdint.h>
#include <stddef.h>
#include <kern/misc_protos.h>

// Data persistence counters (NativeRamBlock.cpp, an unchanged copy of
// UniXNU RamBlock 4be2d7e): weak imports, exactly as UniXNU-sheng's
// BootProgress.c declares them, so this observer still links if the RAM
// block archive ever drops them. State: 0 off, 1 blank (read-only
// probe), 2 resumed, 3 fresh, 4 refused/failed, 5 degraded after an I/O
// error, 6 resumed read-only (probe), 7 kept (the store holds no Data of
// this seed; this boot's Data runs from the seed alone).
extern volatile uint32_t native_data_persist_state __attribute__((weak_import));
extern volatile uint32_t native_data_persist_header __attribute__((weak_import));
extern volatile uint32_t native_data_persist_gpt __attribute__((weak_import));
extern volatile uint32_t native_data_persist_gpt_after __attribute__((weak_import));
extern volatile uint64_t native_data_persist_pages __attribute__((weak_import));
extern volatile uint64_t native_data_persist_loaded __attribute__((weak_import));
extern volatile uint64_t native_data_persist_writes __attribute__((weak_import));
extern volatile uint64_t native_data_persist_syncs __attribute__((weak_import));
extern volatile uint64_t native_data_persist_errors __attribute__((weak_import));
extern volatile uint64_t native_data_persist_first_lba __attribute__((weak_import));
extern volatile uint64_t native_data_persist_present __attribute__((weak_import));

__attribute__((weak)) void
boot_progress_init(void)
{
}

__attribute__((weak)) void
boot_progress_start(void)
{
}

__attribute__((weak)) int
boot_progress_active(void)
{
	return 0;
}

__attribute__((weak)) void
boot_progress_bind(uintptr_t base, unsigned width, unsigned height,
    unsigned rowbytes, unsigned depth)
{
	(void)base;
	(void)width;
	(void)height;
	(void)rowbytes;
	(void)depth;
}

__attribute__((weak)) void
boot_progress_putc(char c)
{
	(void)c;
}

__attribute__((weak)) void
boot_progress_stage(const char *stage)
{
	(void)stage;
}

__attribute__((weak)) void
boot_progress_irq(uint64_t pc, uint64_t cpsr, uint64_t sp)
{
	(void)pc;
	(void)cpsr;
	(void)sp;
}

__attribute__((weak)) void
boot_progress_poll(void)
{
}

__attribute__((weak)) void
boot_progress_user_breakpoint(void *state, unsigned esr)
{
	(void)state;
	(void)esr;
}

__attribute__((weak)) void
boot_progress_user_abort(void *state, unsigned esr, uint64_t fault_addr)
{
	(void)state;
	(void)esr;
	(void)fault_addr;
}

__attribute__((weak)) void
boot_progress_critical_exit(int pid, char *message, unsigned long size)
{
	(void)pid;
	(void)message;
	(void)size;
}

__attribute__((weak)) void
boot_progress_process_stage(int pid, const char *name, const char *stage)
{
	(void)pid;
	(void)name;
	(void)stage;
}

__attribute__((weak)) void
boot_progress_exit(int pid, const char *name, int status, unsigned ns,
    uint64_t code)
{
	(void)pid;
	(void)name;
	(void)status;
	(void)ns;
	(void)code;
	// The persist counters are final before the first process exit
	// (the attach ran before launchd). Printing on every exit leaves
	// a copy directly above the final exit-reason report - the
	// photographed console tail - with the final values. The formats
	// are UniXNU-sheng's BootProgress.c rows: the GPT check
	// before/after the attach, and the write/sync counters a
	// read-only proof (sheng-data-persist=1) must leave at zero.
	if (&native_data_persist_state) {
		printf("fuxi persist st=%u hdr=%u gpt=%x/%x lba=%llx\n",
		    native_data_persist_state, native_data_persist_header,
		    native_data_persist_gpt, native_data_persist_gpt_after,
		    (unsigned long long)native_data_persist_first_lba);
		printf("fuxi persist pres=%llu ld=%llu wr=%llu sy=%llu er=%llu\n",
		    (unsigned long long)native_data_persist_present,
		    (unsigned long long)native_data_persist_loaded,
		    (unsigned long long)native_data_persist_writes,
		    (unsigned long long)native_data_persist_syncs,
		    (unsigned long long)native_data_persist_errors);
	} else {
		printf("fuxi persist counters unavailable\n");
	}
}
