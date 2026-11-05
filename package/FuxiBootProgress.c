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
#include <stdint.h>

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
}
