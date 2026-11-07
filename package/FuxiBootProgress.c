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
// boot_progress_exit prints the NativeRamBlock persist counters on
// every process exit, and boot_progress_critical_exit appends the same
// counters to the exit prefix string itself. No renderer on this board
// reads those counters and the attach's IOLog lines scroll off long
// before the exit report, so without this the persist stage's result
// is invisible on the only evidence source the board has, the
// A second exception since the UI stage (2026-11-07): the same append
// now also carries the skip-setup writer's outcome (weak imports from
// BootWatchdogPolicy.c) and a two-process UI census (SpringBoard and
// backboardd exec/exit counts, taken in the process-stage and exit
// hooks below). chain58's boots proved the pattern's limit — its
// photograph could neither confirm the writer ran nor say whether
// the UI processes ever started — so both answers now ride the panic
// string too. The history matters: the first version printed
// once, at the first exit, and chain52's photograph showed the rows
// had scrolled off; printing on every exit (chain53) still showed
// none, because the photographed page is the panic page that
// panic_with_options renders for a critical exit - it carries only
// the panic record, and console output printed before the panic never
// lands on it. The counters therefore ride inside the panic string:
// proc_handle_critical_exit hands boot_progress_critical_exit the
// prefix buffer ("watchdogd[151] exited", 1024 bytes under
// XNU_BOOT_PROGRESS) before panicking with it, so the append makes
// the counters part of that record. The per-exit printf rows stay as
// the console-stream copy.
//
// A third exception (chain60): the lifecycle probe further below
// keeps one fixed-size record per SpringBoard / backboardd lifecycle
// event, so the next boot can answer when each SpringBoard launch
// happened and what the kernel actually saw at its exit, instead of
// only how many launches the census counted. It is observe-only and
// records raw hook arguments verbatim; see its own comment.
//
// A fourth exception (chain61, Phase 1 of the fault/KCDATA design):
// the two user-fault hooks stop discarding the EL0 fault state the
// trap path hands them and keep it in the fault records further
// below, so a SpringBoard exit can be printed beside the machine
// state of its own faults. See the fault section's own comment for
// the capture and publication discipline.
#include <stdint.h>
#include <stddef.h>
#include <kern/misc_protos.h>
#include <arm/thread.h>
#include <kern/task.h>

// The fault capture runs in the trapping process's own context, so
// these BSD helpers identify it without any process-list walk.
extern int proc_selfpid(void);
extern void proc_selfname(char *, int);

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

// Skip-setup writer outcome (BootWatchdogPolicy.c): weak imports, the
// same pattern as the persist counters above, so this observer still
// links if the policy archive ever drops them. result: -1 = the
// writer never ran (argument off or not reached), otherwise the first
// error it collected (0 = the profile is in place). probe: -2 =
// never ran, -1 = the existing purplebuddy plist could not be read,
// 0 = Setup was not done and the writer wrote, 1 = Setup already
// done, nothing written.
extern volatile int sheng_skip_setup_result __attribute__((weak_import));
extern volatile int sheng_skip_setup_probe __attribute__((weak_import));

// Stage-2 UI census: exec and exit counts for the two processes that
// would have to run before anything graphical can appear, SpringBoard
// and backboardd. The patch hands every exec stage and every exit to
// this observer with the process name (p_name), so the census needs
// no process-list walk and no locking: the stage hook counts an exec
// when it reaches the signature stage (the note point UniXNU-sheng's
// census uses), the exit hook counts the exit. The name and stage
// compares are hand-rolled: this file deliberately uses nothing
// beyond the printf/snprintf its header already declares.
static volatile unsigned int bp_sb_stage;
static volatile unsigned int bp_sb_exit;
static volatile unsigned int bp_bb_stage;
static volatile unsigned int bp_bb_exit;

static int
bp_text_is(const char *text, const char *want)
{
	if (text == NULL) {
		return 0;
	}
	while (*want != '\0') {
		if (*text != *want) {
			return 0;
		}
		text++;
		want++;
	}
	return *text == '\0';
}

static void
bp_census_exec(const char *name)
{
	if (bp_text_is(name, "SpringBoard")) {
		bp_sb_stage++;
	} else if (bp_text_is(name, "backboardd")) {
		bp_bb_stage++;
	}
}

static void
bp_census_exit(const char *name)
{
	if (bp_text_is(name, "SpringBoard")) {
		bp_sb_exit++;
	} else if (bp_text_is(name, "backboardd")) {
		bp_bb_exit++;
	}
}

// Stage-2 lifecycle probe (chain60): per-event records for the same
// two processes, taken in the same two hooks the census uses, so the
// probe's coverage is exactly the coverage chain59's counts already
// proved on device (sb 3/3 on chain59, sb 4/4 on the usb1 boot —
// signature-entry counts both times, see the semantics note below).
// Each record carries a global sequence number, the process, the
// event kind, the pid, a mach_absolute_time stamp, and — for exits —
// the exit hook's raw arguments (status, reason namespace, reason
// code) exactly as the boot-progress patch's call site in
// bsd/kern/kern_exit.c hands them over: rv, and p->p_exit_reason's
// osr_namespace / osr_code. The call site passes 0 for both when
// p_exit_reason is NULL, but a reason object carrying namespace 0
// and code 0 would arrive identically, so the hook cannot observe
// reason presence: the printed exit lines carry
// reason_presence=unavailable, and the values are recorded raw,
// never classified — a plain exit status stays a plain exit
// status, and no jetsam, watchdog or crash label is ever derived
// from it. The sig field in the printed exit line is the
// wait-status ABI field (status & 0x7f) carried losslessly inside
// the raw status, not a cause. The parent pid is likewise not
// observable at either hook (the patch passes pid, name and stage,
// and pid, name, status, ns, code), and walking the process list
// for it would break this observer's no-locking design, so every
// printed line carries ppid=unavailable: an explicit hole in the
// data, not a format omission.
//
// Stage semantics, from the patch's call sites in
// bsd/kern/kern_exec.c: "exec load_machfile returned" fires before
// the caller checks lret against LOAD_SUCCESS, so lm-returned
// means only that load_machfile returned — its return value is not
// carried. "exec process signature accepted" means
// proc_process_signature returned 0, i.e. the signature check
// passed; it does NOT mean the exec as a whole committed, and this
// revision deliberately has no exec-success event, because no call
// site observes the final exec commit. The census above counts at
// signature entry, so its exec counts are signature-entry counts.
//
// Ordering: an event's sequence number is its buffer-claim order,
// taken after the timestamp; under multi-CPU concurrency the two
// orders can differ, so the raw mach_absolute_time ticks are the
// time basis for any timeline. The ticks are raw counter units,
// not milliseconds and not wall time.
//
// Storage and publication: a fixed 64-entry array, first-come
// kept, later events only bump the dropped counter — the first
// SpringBoard failure is the evidence that matters, and a bounded
// buffer can never turn the probe into memory pressure. The claim
// counter alone does not make a record readable: a writer fills
// every field first and publishes the slot's ready flag last with
// release semantics, and every reader takes the counters with
// atomic loads and a slot with acquire semantics, skipping slots
// whose ready flag is not set, so a half-written record can never
// reach a dump or the panic digest. (The dropped counter is kept
// as an independent cross-check; the panic digest derives its own
// dropped figure from its claim snapshot, because the counter's
// increment can lag the claim it belongs to.)
//
// Output discipline: the hooks themselves only write the buffer —
// no printing, no allocation. Records reach the console (and with
// it the USB stream) from one place only: bp_ev_flush() runs at
// the end of boot_progress_exit, next to the persist rows that
// already print there on every process exit. One flush owner at a
// time prints, in sequence order (see bp_ev_flush for the
// BUSY|AGAIN gate that keeps a scan responsible for every record
// without any waiting). A scan stops at the first not-yet-ready
// slot. boot_progress_critical_exit prints nothing; the panic
// string carries only the digest bp_ev_append_digest appends
// there, read under the same ready discipline from a single
// snapshot of the claim counter and the flush cursor, so its
// kept, pending, unflushed and dropped figures share one basis.
// Observe only: nothing in the probe touches exit or restart
// behaviour.
extern uint64_t mach_absolute_time(void);

#define BP_WHO_SB	1
#define BP_WHO_BB	2

#define BP_EV_LM_ENTER		1	/* "exec load_machfile enter" */
#define BP_EV_LM_RETURNED	2	/* "exec load_machfile returned" */
#define BP_EV_SIG_ENTER		3	/* "exec process signature enter" */
#define BP_EV_SIG_ACCEPTED	4	/* "exec process signature accepted" */
#define BP_EV_SIG_REFUSED	5	/* "exec process signature REFUSED" */
#define BP_EV_MAC_REFUSED	6	/* "exec MAC policy REFUSED" */
#define BP_EV_EXIT		7	/* boot_progress_exit */

#define BP_EV_CAP	64u

struct bp_ev {
	unsigned int ready;	/* published last, release semantics */
	unsigned int seq;
	unsigned int who;
	unsigned int kind;
	int pid;
	uint64_t ticks;
	int status;
	unsigned int ns;
	uint64_t code;
};

static struct bp_ev bp_events[BP_EV_CAP];
static unsigned int bp_ev_claimed;
static unsigned int bp_ev_dropped;
static unsigned int bp_ev_flush_next;

#define BP_EV_FLUSH_BUSY	1u
#define BP_EV_FLUSH_AGAIN	2u
static unsigned int bp_ev_flush_state;

static unsigned int
bp_who(const char *name)
{
	if (bp_text_is(name, "SpringBoard")) {
		return BP_WHO_SB;
	}
	if (bp_text_is(name, "backboardd")) {
		return BP_WHO_BB;
	}
	return 0;
}

static const char *
bp_ev_kind_name(unsigned int kind)
{
	switch (kind) {
	case BP_EV_LM_ENTER:
		return "lm-enter";
	case BP_EV_LM_RETURNED:
		return "lm-returned";
	case BP_EV_SIG_ENTER:
		return "sig-enter";
	case BP_EV_SIG_ACCEPTED:
		return "sig-accepted";
	case BP_EV_SIG_REFUSED:
		return "sig-refused";
	case BP_EV_MAC_REFUSED:
		return "mac-refused";
	case BP_EV_EXIT:
		return "exit";
	default:
		return "?";
	}
}

static unsigned int
bp_ev_kept(void)
{
	unsigned int claimed = __atomic_load_n(&bp_ev_claimed,
	    __ATOMIC_RELAXED);

	return claimed < BP_EV_CAP ? claimed : BP_EV_CAP;
}

static int
bp_ev_ready(const struct bp_ev *ev)
{
	return __atomic_load_n(&ev->ready, __ATOMIC_ACQUIRE) != 0;
}

static void
bp_ev_print(const struct bp_ev *ev)
{
	if (ev->kind == BP_EV_EXIT) {
		printf("fuxi ev #%u %s exit pid=%d ppid=unavailable"
		    " t=%llu status=0x%x sig=%d ns=%u code=0x%llx"
		    " reason_presence=unavailable\n",
		    ev->seq, ev->who == BP_WHO_SB ? "sb" : "bb", ev->pid,
		    (unsigned long long)ev->ticks,
		    (unsigned int)ev->status, ev->status & 0x7f, ev->ns,
		    (unsigned long long)ev->code);
	} else {
		printf("fuxi ev #%u %s %s pid=%d ppid=unavailable"
		    " t=%llu\n",
		    ev->seq, ev->who == BP_WHO_SB ? "sb" : "bb",
		    bp_ev_kind_name(ev->kind), ev->pid,
		    (unsigned long long)ev->ticks);
	}
}

static void
bp_ev_record(unsigned int who, unsigned int kind, int pid, int status,
    unsigned int ns, uint64_t code)
{
	uint64_t ticks = mach_absolute_time();
	unsigned int claimed = __atomic_fetch_add(&bp_ev_claimed, 1,
	    __ATOMIC_RELAXED);

	if (claimed < BP_EV_CAP) {
		struct bp_ev *ev = &bp_events[claimed];

		ev->seq = claimed + 1;
		ev->who = who;
		ev->kind = kind;
		ev->pid = pid;
		ev->ticks = ticks;
		ev->status = status;
		ev->ns = ns;
		ev->code = code;
		__atomic_store_n(&ev->ready, 1, __ATOMIC_RELEASE);
	} else {
		__atomic_fetch_add(&bp_ev_dropped, 1, __ATOMIC_RELAXED);
	}
}

// Stage-2 fault probe (chain61, Phase 1 of the fault/KCDATA
// design): the boot-progress patch calls
// boot_progress_user_breakpoint() where the ARM trap handler is
// about to deliver EXC_ARM_BREAKPOINT, and
// boot_progress_user_abort() in the user-abort path with the
// fault address. Through chain60 both were weak no-op stubs in
// this file, so the EL0 fault state reached them and was
// discarded — chain60's stream holds fourteen signal-5
// SpringBoard exits and not one fault record. The hooks now
// capture the state under the discipline set for this phase:
//
//   - append-only: a fixed 32-slot array claimed in order and
//     never wrapped; overflow only bumps the dropped counter, so
//     evidence sequence numbers are never reused and no reader
//     can meet a half-overwritten record;
//   - the record carries its kind explicitly — the breakpoint
//     hook's signature has no fault address, so a zero FAR
//     cannot stand in for the kind;
//   - only SpringBoard and backboardd records are kept. The
//     trapping context is the faulting process itself, so
//     proc_selfname identifies it without any traversal; every
//     other process's fault only bumps a counter and can never
//     evict the evidence this probe exists for;
//   - capture fills every field first and publishes the slot's
//     ready flag last with release semantics, exactly like the
//     lifecycle records above; the trap path does no allocation,
//     no blocking and no user-memory access;
//   - printing happens only inside bp_ev_flush's single-owner
//     pass below: the owner advances a cursor over the lifecycle
//     records and, for each SpringBoard / backboardd exit it
//     passes, prints that pid's not-yet-consumed fault records
//     in claim order beside the exit's signal and ticks, marking
//     each consumed as it goes. A record therefore prints at
//     most once, only beside its own process's exit, and a later
//     process reusing the pid can never inherit it.
//
// What is recorded is what is printed: kind, pid, fault ticks,
// pc, lr, sp, fp, esr, far, the shared-region slide and
// x0-x28 — the field set of the official user-fault-evidence
// contract — plus the exit's signal and ticks on the same line.
// The kernel prints raw values only: the esr is not decoded
// here, and the pc is printed beside the slide, never minus it;
// whether the pc lies in the shared region at all is a
// host-side judgement. A fault line beside an exit is a
// same-pid fault/exit correlation, not yet a claim that the two
// are one exception chain; that judgement belongs to the
// analysis, with the exit's signal first — only exits with
// signal 5 enter the SIGTRAP attribution. The counters ride a
// fuxi faultstat line printed once per processed target exit,
// so the conditions under which "no fault record for this pid"
// may be read as "not captured in this window" (no target
// drops, no unavailable captures, nothing still pending) stay
// checkable from the stream itself.

#define BP_FLT_CAP	32u

#define BP_FLT_BREAKPOINT	1u
#define BP_FLT_ABORT		2u

struct bp_flt {
	unsigned int ready;	/* published last, release semantics */
	unsigned int consumed;	/* written by the flush owner only */
	unsigned int seq;
	unsigned int kind;
	unsigned int who;
	int pid;
	uint64_t ticks;
	uint64_t pc;
	uint64_t lr;
	uint64_t sp;
	uint64_t fp;
	uint64_t esr;
	uint64_t far;
	uint64_t slide;
	uint64_t x[29];
};

static struct bp_flt bp_faults[BP_FLT_CAP];
static unsigned int bp_flt_claimed;
static unsigned int bp_flt_dropped;
static unsigned int bp_flt_bp_attempts;
static unsigned int bp_flt_ab_attempts;
static unsigned int bp_flt_other;
static unsigned int bp_flt_unavail;
static unsigned int bp_flt_consumed;
static unsigned int bp_flt_ev_cursor;

static unsigned int
bp_flt_kept(void)
{
	unsigned int claimed = __atomic_load_n(&bp_flt_claimed,
	    __ATOMIC_RELAXED);

	return claimed < BP_FLT_CAP ? claimed : BP_FLT_CAP;
}

static int
bp_flt_ready(const struct bp_flt *flt)
{
	return __atomic_load_n(&flt->ready, __ATOMIC_ACQUIRE) != 0;
}

static void
bp_flt_capture(unsigned int kind, void *state, unsigned esr,
    uint64_t fault_addr)
{
	char name[32];
	unsigned int who;
	unsigned int claimed;
	struct bp_flt *flt;
	arm_saved_state_t *saved = (arm_saved_state_t *)state;
	unsigned int i;

	if (kind == BP_FLT_BREAKPOINT) {
		__atomic_fetch_add(&bp_flt_bp_attempts, 1,
		    __ATOMIC_RELAXED);
	} else {
		__atomic_fetch_add(&bp_flt_ab_attempts, 1,
		    __ATOMIC_RELAXED);
	}
	proc_selfname(name, (int)sizeof(name));
	name[sizeof(name) - 1] = '\0';
	who = bp_who(name);
	if (who == 0) {
		__atomic_fetch_add(&bp_flt_other, 1, __ATOMIC_RELAXED);
		return;
	}
	if (saved == NULL || !is_saved_state64(saved)) {
		__atomic_fetch_add(&bp_flt_unavail, 1,
		    __ATOMIC_RELAXED);
		return;
	}
	claimed = __atomic_fetch_add(&bp_flt_claimed, 1,
	    __ATOMIC_RELAXED);
	if (claimed >= BP_FLT_CAP) {
		__atomic_fetch_add(&bp_flt_dropped, 1,
		    __ATOMIC_RELAXED);
		return;
	}
	flt = &bp_faults[claimed];
	flt->seq = claimed + 1;
	flt->kind = kind;
	flt->who = who;
	flt->pid = proc_selfpid();
	flt->ticks = mach_absolute_time();
	flt->pc = (uint64_t)get_saved_state_pc(saved);
	flt->lr = (uint64_t)get_saved_state_lr(saved);
	flt->sp = (uint64_t)get_saved_state_sp(saved);
	flt->fp = (uint64_t)get_saved_state_fp(saved);
	flt->esr = (uint64_t)esr;
	flt->far = fault_addr;
	flt->slide = (uint64_t)current_task()->task_shared_region_slide;
	for (i = 0; i < 29; i++) {
		flt->x[i] = (uint64_t)get_saved_state_reg(saved, i);
	}
	__atomic_store_n(&flt->ready, 1, __ATOMIC_RELEASE);
}

static void
bp_flt_print(const struct bp_flt *flt, const struct bp_ev *exit_ev)
{
	char line[1408];
	int len = snprintf(line, sizeof(line),
	    "fuxi fault #%u %s kind=%s pid=%d ft=%llu pc=0x%llx"
	    " lr=0x%llx sp=0x%llx fp=0x%llx esr=0x%llx far=0x%llx"
	    " slide=0x%llx"
	    " x0=0x%llx x1=0x%llx x2=0x%llx x3=0x%llx x4=0x%llx"
	    " x5=0x%llx x6=0x%llx x7=0x%llx x8=0x%llx x9=0x%llx"
	    " x10=0x%llx x11=0x%llx x12=0x%llx x13=0x%llx x14=0x%llx"
	    " x15=0x%llx x16=0x%llx x17=0x%llx x18=0x%llx x19=0x%llx"
	    " x20=0x%llx x21=0x%llx x22=0x%llx x23=0x%llx x24=0x%llx"
	    " x25=0x%llx x26=0x%llx x27=0x%llx x28=0x%llx"
	    " exit_sig=%d et=%llu\n",
	    flt->seq, flt->who == BP_WHO_SB ? "sb" : "bb",
	    flt->kind == BP_FLT_BREAKPOINT ? "bp" : "abort",
	    flt->pid, (unsigned long long)flt->ticks,
	    (unsigned long long)flt->pc, (unsigned long long)flt->lr,
	    (unsigned long long)flt->sp, (unsigned long long)flt->fp,
	    (unsigned long long)flt->esr, (unsigned long long)flt->far,
	    (unsigned long long)flt->slide,
	    (unsigned long long)flt->x[0], (unsigned long long)flt->x[1],
	    (unsigned long long)flt->x[2], (unsigned long long)flt->x[3],
	    (unsigned long long)flt->x[4], (unsigned long long)flt->x[5],
	    (unsigned long long)flt->x[6], (unsigned long long)flt->x[7],
	    (unsigned long long)flt->x[8], (unsigned long long)flt->x[9],
	    (unsigned long long)flt->x[10], (unsigned long long)flt->x[11],
	    (unsigned long long)flt->x[12], (unsigned long long)flt->x[13],
	    (unsigned long long)flt->x[14], (unsigned long long)flt->x[15],
	    (unsigned long long)flt->x[16], (unsigned long long)flt->x[17],
	    (unsigned long long)flt->x[18], (unsigned long long)flt->x[19],
	    (unsigned long long)flt->x[20], (unsigned long long)flt->x[21],
	    (unsigned long long)flt->x[22], (unsigned long long)flt->x[23],
	    (unsigned long long)flt->x[24], (unsigned long long)flt->x[25],
	    (unsigned long long)flt->x[26], (unsigned long long)flt->x[27],
	    (unsigned long long)flt->x[28],
	    exit_ev->status & 0x7f, (unsigned long long)exit_ev->ticks);

	if (len > 0 && (size_t)len < sizeof(line)) {
		printf("%s", line);
	}
}

static void
bp_flt_print_stats(void)
{
	unsigned int kept = bp_flt_kept();
	unsigned int pending = 0;
	unsigned int i;

	for (i = 0; i < kept; i++) {
		const struct bp_flt *flt = &bp_faults[i];

		if (bp_flt_ready(flt) && !flt->consumed) {
			pending++;
		}
	}
	printf("fuxi faultstat bp_att=%u ab_att=%u other=%u kept=%u"
	    " drop=%u unavail=%u consumed=%u fpending=%u\n",
	    __atomic_load_n(&bp_flt_bp_attempts, __ATOMIC_RELAXED),
	    __atomic_load_n(&bp_flt_ab_attempts, __ATOMIC_RELAXED),
	    __atomic_load_n(&bp_flt_other, __ATOMIC_RELAXED), kept,
	    __atomic_load_n(&bp_flt_dropped, __ATOMIC_RELAXED),
	    __atomic_load_n(&bp_flt_unavail, __ATOMIC_RELAXED),
	    __atomic_load_n(&bp_flt_consumed, __ATOMIC_RELAXED),
	    pending);
}

// Owner-only, called from bp_ev_flush's pass with that pass's
// lifecycle snapshot: advance the fault cursor over the lifecycle
// records and, for each target exit passed, print and consume
// that pid's fault records, then print the counters. The cursor
// stops at the first not-yet-published lifecycle slot, exactly
// like the lifecycle scan itself, so a fault line can never
// precede the exit line it belongs to.
static void
bp_flt_process(unsigned int kept)
{
	unsigned int cursor = __atomic_load_n(&bp_flt_ev_cursor,
	    __ATOMIC_RELAXED);

	while (cursor < kept) {
		const struct bp_ev *ev = &bp_events[cursor];
		unsigned int fkept;
		unsigned int i;

		if (!bp_ev_ready(ev)) {
			break;
		}
		cursor++;
		__atomic_store_n(&bp_flt_ev_cursor, cursor,
		    __ATOMIC_RELAXED);
		if (ev->kind != BP_EV_EXIT) {
			continue;
		}
		fkept = bp_flt_kept();
		for (i = 0; i < fkept; i++) {
			struct bp_flt *flt = &bp_faults[i];

			if (!bp_flt_ready(flt) || flt->consumed ||
			    flt->pid != ev->pid) {
				continue;
			}
			bp_flt_print(flt, ev);
			flt->consumed = 1;
			__atomic_fetch_add(&bp_flt_consumed, 1,
			    __ATOMIC_RELAXED);
		}
		bp_flt_print_stats();
	}
}

// Print every ready, not-yet-printed record, in sequence order.
// Called only from boot_progress_exit, beside the persist rows.
// One owner at a time prints, so the stream cannot show a later
// record before an earlier one, and no record can print twice.
// The gate is a two-bit state, not a plain busy flag: a plain
// flag loses a window — a contender that finds the gate held and
// simply returns may have claimed a record after the owner took
// its kept snapshot, and with no later exit nothing would ever
// print that record. Here a contender instead sets AGAIN before
// returning; the owner, before releasing, either sees AGAIN
// (clears it, keeps the gate, and rescans with a fresh snapshot)
// or wins the release CAS — and a contender whose AGAIN CAS
// loses to that release observes the free state and acquires the
// gate itself. Either way some flush is always responsible for
// the next scan; nobody waits, and the only retries are on the
// atomic state transitions themselves. A scan stops at the first
// slot whose writer has not published yet and never waits for it.
//
// The state transitions are also the memory-ordering vehicle for
// the records themselves, which matters on this target's weakly
// ordered ARM64 model: the claim increment is relaxed and the
// slot publication a release store into the slot, neither of
// which a rescan could rely on seeing if the AGAIN handshake
// were relaxed too — the owner could observe AGAIN, rescan with
// a stale kept, clear AGAIN and release, and the new record
// would be stranded exactly as if no handshake existed. So the
// contender's notification CAS and the owner's handoff CAS
// operations are acquire-release (acquire on failure, and the
// owner's state loads are acquire): the notification is
// sequenced after the contender's bp_ev_record, so an owner
// that acquires the notified state has a happens-before path to
// that claim and publication before its next snapshot, and
// chained notifications republish earlier contenders' writes
// the same way. If the owner's release wins the race instead,
// the contender's CAS fails, it observes the free state, and it
// acquires the gate and scans itself. (A host stress run on a
// strongly ordered machine cannot exhibit the relaxed failure;
// the orderings above are the guarantee, not the test.)
static void
bp_ev_flush(void)
{
	unsigned int state = __atomic_load_n(&bp_ev_flush_state,
	    __ATOMIC_RELAXED);

	for (;;) {
		if ((state & BP_EV_FLUSH_BUSY) != 0) {
			unsigned int desired = state | BP_EV_FLUSH_AGAIN;

			if (__atomic_compare_exchange_n(&bp_ev_flush_state,
			    &state, desired, 0, __ATOMIC_ACQ_REL,
			    __ATOMIC_ACQUIRE)) {
				return;
			}
		} else {
			unsigned int desired = BP_EV_FLUSH_BUSY;

			if (__atomic_compare_exchange_n(&bp_ev_flush_state,
			    &state, desired, 0, __ATOMIC_ACQUIRE,
			    __ATOMIC_RELAXED)) {
				break;
			}
		}
	}

	for (;;) {
		unsigned int kept = bp_ev_kept();
		unsigned int next = __atomic_load_n(&bp_ev_flush_next,
		    __ATOMIC_RELAXED);

		while (next < kept) {
			const struct bp_ev *ev = &bp_events[next];

			if (!bp_ev_ready(ev)) {
				break;
			}
			bp_ev_print(ev);
			next++;
			__atomic_store_n(&bp_ev_flush_next, next,
			    __ATOMIC_RELAXED);
		}

		// The fault records ride the same owner pass, after
		// the lifecycle lines of this snapshot, so a fault
		// line can never precede the exit line it belongs
		// to and no second printer exists.
		bp_flt_process(kept);

		// Retain ownership and rescan if any contender arrived
		// during this pass. Otherwise release. The CAS makes
		// the release-vs-contender race lossless, as described
		// above.
		for (;;) {
			state = __atomic_load_n(&bp_ev_flush_state,
			    __ATOMIC_ACQUIRE);
			if ((state & BP_EV_FLUSH_AGAIN) != 0) {
				unsigned int desired = BP_EV_FLUSH_BUSY;

				if (__atomic_compare_exchange_n(
				    &bp_ev_flush_state, &state, desired, 0,
				    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
					break;
				}
			} else {
				unsigned int desired = 0;

				if (__atomic_compare_exchange_n(
				    &bp_ev_flush_state, &state, desired, 0,
				    __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
					return;
				}
			}
		}
	}
}

// Append text to the panic string only if it fits whole, NUL
// included; otherwise append nothing. The lifecycle digest below
// is built from these whole-or-nothing pieces so it can never
// contain half a field. The length check is in subtraction form
// so it cannot overflow, and the snprintf result is verified
// against the measured length.
static int
bp_append_whole(char *message, size_t size, size_t *used_io,
    const char *text)
{
	size_t len = 0;

	while (text[len] != '\0') {
		len++;
	}
	if (*used_io > size || len >= size - *used_io) {
		return 0;
	}
	if (snprintf(message + *used_io, size - *used_io,
	    "%s", text) != (int)len) {
		return 0;
	}
	*used_io += len;
	return 1;
}

// The panic-string digest of the lifecycle records, appended by
// boot_progress_critical_exit after the persist, skip-setup and
// census fields. Nothing is printed here; this only reads the
// ring. The whole digest is read from ONE snapshot of the claim
// counter and one of the flush cursor (the cursor clamped to the
// claim snapshot, in case the two independent atomics race), so
// its figures share a basis:
//   kept        the claim snapshot capped at the ring size;
//   evpending   kept slots whose writer had claimed the slot but
//               not yet published it when read (skipped, never
//               half-read; their kind is unknowable);
//   evunflushed kept, published slots at or past the flush
//               cursor in this snapshot: collected and
//               published, but not confirmed printed — the
//               cursor is only a sampling point, and printing
//               may be in flight concurrently, so this is not a
//               claim about the panic instant itself;
//   evdrop      the snapshot beyond the ring size, derived from
//               the snapshot rather than from the dropped
//               counter, whose increment can lag its claim.
// The first pass also freezes the ready/not-ready decision of
// every kept slot into a 64-bit mask: a slot may publish while
// the digest is being formatted, and the tuple pass must use the
// same observed set as the counts above, not a second, different
// one. The sbx value itself: one "#<seq>:0x<status>/<ns>/0x<code>"
// tuple per slot that was a published SpringBoard exit in that
// frozen set, in event order (raw hook arguments; reason presence
// is not encoded in them — see the probe comment). When no
// SpringBoard exit was published, the value is none-observed if
// nothing is pending, and unresolved-pending when slots are
// still unpublished, because an unpublished slot could be the
// very exit being looked for and must not read as a definite
// none.
//
// Space discipline: the exact suffix strings (evpending, evdrop,
// evunflushed) are staged first, and the minimum digest — the
// sbx head, the truncation marker, and every nonzero suffix — is
// reserved before anything is written. A tuple is appended only
// when it fits whole AND leaves that reserved room, and a refused
// tuple sets sbx-truncated=1 in space the reservation guarantees.
// If even the minimum cannot fit, the digest writes nothing at
// all rather than a partial, misleading one.
static void
bp_ev_append_digest(char *message, size_t size, size_t *used_io)
{
	unsigned int claimed = __atomic_load_n(&bp_ev_claimed,
	    __ATOMIC_ACQUIRE);
	unsigned int flushed = __atomic_load_n(&bp_ev_flush_next,
	    __ATOMIC_ACQUIRE);
	unsigned int kept = claimed < BP_EV_CAP ? claimed : BP_EV_CAP;
	unsigned int overflow = claimed > BP_EV_CAP ?
	    claimed - BP_EV_CAP : 0;
	unsigned int pending = 0;
	unsigned int observed = 0;
	unsigned int unflushed = 0;
	unsigned int i;
	uint64_t ready_mask = 0;
	char pbuf[24];
	char dbuf[24];
	char ubuf[24];
	int plen = 0;
	int dlen = 0;
	int ulen = 0;
	unsigned int suffix_len = 0;

	if (flushed > kept) {
		flushed = kept;
	}

	for (i = 0; i < kept; i++) {
		const struct bp_ev *ev = &bp_events[i];

		if (!bp_ev_ready(ev)) {
			pending++;
			continue;
		}
		ready_mask |= (uint64_t)1 << i;
		if (i >= flushed) {
			unflushed++;
		}
		if (ev->who == BP_WHO_SB && ev->kind == BP_EV_EXIT) {
			observed++;
		}
	}

	if (pending != 0) {
		plen = snprintf(pbuf, sizeof(pbuf), " evpending=%u",
		    pending);
		if (plen < 0 || (size_t)plen >= sizeof(pbuf)) {
			return;
		}
		suffix_len += (unsigned int)plen;
	}
	if (overflow != 0) {
		dlen = snprintf(dbuf, sizeof(dbuf), " evdrop=%u",
		    overflow);
		if (dlen < 0 || (size_t)dlen >= sizeof(dbuf)) {
			return;
		}
		suffix_len += (unsigned int)dlen;
	}
	if (unflushed != 0) {
		ulen = snprintf(ubuf, sizeof(ubuf), " evunflushed=%u",
		    unflushed);
		if (ulen < 0 || (size_t)ulen >= sizeof(ubuf)) {
			return;
		}
		suffix_len += (unsigned int)ulen;
	}

	if (observed == 0) {
		const char *head = pending != 0 ?
		    " sbx=unresolved-pending" : " sbx=none-observed";
		size_t head_len = 0;

		while (head[head_len] != '\0') {
			head_len++;
		}
		if (*used_io > size ||
		    head_len + (size_t)suffix_len >= size - *used_io) {
			return;
		}
		if (!bp_append_whole(message, size, used_io, head)) {
			return;
		}
	} else {
		static const char prefix[] = " sbx=";
		static const char marker[] = " sbx-truncated=1";
		size_t prefix_len = sizeof(prefix) - 1;
		size_t marker_len = sizeof(marker) - 1;
		unsigned int printed = 0;
		int truncated = 0;

		if (*used_io > size ||
		    prefix_len + marker_len + (size_t)suffix_len >=
		    size - *used_io) {
			return;
		}
		if (!bp_append_whole(message, size, used_io, prefix)) {
			return;
		}

		for (i = 0; i < kept; i++) {
			const struct bp_ev *ev = &bp_events[i];
			char tuple[64];
			int tlen;

			if ((ready_mask & ((uint64_t)1 << i)) == 0 ||
			    ev->who != BP_WHO_SB || ev->kind != BP_EV_EXIT) {
				continue;
			}
			tlen = snprintf(tuple, sizeof(tuple),
			    "%s#%u:0x%x/%u/0x%llx",
			    printed == 0 ? "" : ",", ev->seq,
			    (unsigned int)ev->status, ev->ns,
			    (unsigned long long)ev->code);
			if (tlen < 0 || (size_t)tlen >= sizeof(tuple)) {
				truncated = 1;
				break;
			}
			if (*used_io > size ||
			    (size_t)tlen + marker_len +
			    (size_t)suffix_len >= size - *used_io) {
				truncated = 1;
				break;
			}
			if (!bp_append_whole(message, size, used_io, tuple)) {
				truncated = 1;
				break;
			}
			printed++;
		}
		if (truncated &&
		    !bp_append_whole(message, size, used_io, marker)) {
			// The reservation above makes this unreachable
			// unless the caller's size/used contract is
			// violated.
			return;
		}
	}

	if (plen > 0 && !bp_append_whole(message, size, used_io, pbuf)) {
		return;
	}
	if (dlen > 0 && !bp_append_whole(message, size, used_io, dbuf)) {
		return;
	}
	if (ulen > 0 && !bp_append_whole(message, size, used_io, ubuf)) {
		return;
	}
}

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
	bp_flt_capture(BP_FLT_BREAKPOINT, state, esr, 0);
}

__attribute__((weak)) void
boot_progress_user_abort(void *state, unsigned esr, uint64_t fault_addr)
{
	bp_flt_capture(BP_FLT_ABORT, state, esr, fault_addr);
}

__attribute__((weak)) void
boot_progress_critical_exit(int pid, char *message, unsigned long size)
{
	(void)pid;
	if (message == NULL || size == 0) {
		return;
	}
	// The caller (proc_handle_critical_exit, via the zzz-boot-progress
	// patch) passes prefix_str_buf already holding "name[pid] exited"
	// together with its full size; the buffer becomes the panic
	// string verbatim, so the counters have to be appended in place.
	// Bounded strictly by size: locate the terminating NUL without
	// reading past the buffer, then let snprintf bound the rest. The
	// values are the same counters boot_progress_exit prints; they
	// are final long before a critical exit (the attach ran before
	// launchd).
	size_t used = 0;

	while (used < (size_t)size && message[used] != '\0') {
		used++;
	}
	if (used >= (size_t)size) {
		return;
	}
	if (&native_data_persist_state) {
		snprintf(message + used, (size_t)size - used,
		    " fuxi persist st=%u hdr=%u gpt=%x/%x lba=%llx"
		    " pres=%llu ld=%llu wr=%llu sy=%llu er=%llu",
		    native_data_persist_state, native_data_persist_header,
		    native_data_persist_gpt, native_data_persist_gpt_after,
		    (unsigned long long)native_data_persist_first_lba,
		    (unsigned long long)native_data_persist_present,
		    (unsigned long long)native_data_persist_loaded,
		    (unsigned long long)native_data_persist_writes,
		    (unsigned long long)native_data_persist_syncs,
		    (unsigned long long)native_data_persist_errors);
	} else {
		snprintf(message + used, (size_t)size - used,
		    " fuxi persist counters unavailable");
	}
	// Stage-2 observability (chain59): the skip-setup writer's
	// outcome and the UI census ride the same string, for the same
	// reason as the persist counters — both live only in the console
	// stream otherwise, which the photographed panic page never
	// shows. chain58's two boots left both questions open: the store
	// growth was consistent with the writer having run but proved
	// nothing, and the owner's watched boot showed no graphical
	// frame at any point without saying whether the UI processes
	// ever started.
	used = 0;
	while (used < (size_t)size && message[used] != '\0') {
		used++;
	}
	if (used >= (size_t)size) {
		return;
	}
	if (&sheng_skip_setup_result) {
		snprintf(message + used, (size_t)size - used,
		    " sksu=%d/%d",
		    sheng_skip_setup_result, sheng_skip_setup_probe);
	} else {
		snprintf(message + used, (size_t)size - used, " sksu=na");
	}
	used = 0;
	while (used < (size_t)size && message[used] != '\0') {
		used++;
	}
	if (used >= (size_t)size) {
		return;
	}
	snprintf(message + used, (size_t)size - used,
	    " ui=sb:%u/%u,bb:%u/%u",
	    bp_sb_stage, bp_sb_exit, bp_bb_stage, bp_bb_exit);
	// Stage-2 lifecycle probe (chain60): the digest of the
	// lifecycle records (see bp_ev_append_digest). Nothing is
	// printed here; the records themselves reached the console
	// stream through bp_ev_flush() at process exits.
	used = 0;
	while (used < (size_t)size && message[used] != '\0') {
		used++;
	}
	if (used >= (size_t)size) {
		return;
	}
	bp_ev_append_digest(message, (size_t)size, &used);
}

__attribute__((weak)) void
boot_progress_process_stage(int pid, const char *name, const char *stage)
{
	unsigned int who = bp_who(name);
	unsigned int kind = 0;

	if (bp_text_is(stage, "exec process signature enter")) {
		bp_census_exec(name);
		kind = BP_EV_SIG_ENTER;
	} else if (bp_text_is(stage, "exec load_machfile enter")) {
		kind = BP_EV_LM_ENTER;
	} else if (bp_text_is(stage, "exec load_machfile returned")) {
		kind = BP_EV_LM_RETURNED;
	} else if (bp_text_is(stage, "exec process signature accepted")) {
		kind = BP_EV_SIG_ACCEPTED;
	} else if (bp_text_is(stage, "exec process signature REFUSED")) {
		kind = BP_EV_SIG_REFUSED;
	} else if (bp_text_is(stage, "exec MAC policy REFUSED")) {
		kind = BP_EV_MAC_REFUSED;
	}
	if (who != 0 && kind != 0) {
		bp_ev_record(who, kind, pid, 0, 0, 0);
	}
}

__attribute__((weak)) void
boot_progress_exit(int pid, const char *name, int status, unsigned ns,
    uint64_t code)
{
	unsigned int who = bp_who(name);

	bp_census_exit(name);
	if (who != 0) {
		bp_ev_record(who, BP_EV_EXIT, pid, status, ns, code);
	}
	// The persist counters are final before the first process exit
	// (the attach ran before launchd). These rows are the
	// console-stream copy, repeated on every exit; the copy the
	// photographed panic page carries is the one
	// boot_progress_critical_exit appends to the panic string. The
	// formats are UniXNU-sheng's BootProgress.c rows: the GPT check
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
	// Stage-2 lifecycle probe: the one place records are printed,
	// beside the persist rows above. This exit's own record was
	// written before this point, so it is included in the flush.
	bp_ev_flush();
}
