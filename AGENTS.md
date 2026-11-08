# Device agent guide

This repository owns the Xiaomi 13 (fuxi, SM8550) board: DTS, peripheral wiring, component selection, firmware inputs,
the board probe and packaging. Shared SM8550 resources belong to `UniXNU-sm8550-common`; the build driver, the component
catalog and the documentation belong to UniXNU. This board builds with the fork
[OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) (branch `fuxi`), whose catalog has the `FuxiFtsTouch`
component and whose `bootimg` takes the fuxi boot image options; upstream UniXNU has neither yet. The firmware is
[OddlyLabs/uefi-fuxi](https://github.com/OddlyLabs/uefi-fuxi) (branch `fuxi`): UniXNU/uefi-sheng with the fuxi commits of
matejkoo217/uefi-fuxi. Keep both forks as their upstream plus a small set of fuxi commits, merge upstream into them, and
update the pinned revisions in `.github/workflows/build.yml` after each merge.

## Read first

| Task | Required reading |
| --- | --- |
| Every change | [Porting](https://unixnu.com/porting/), [device repository](https://unixnu.com/porting/device-repository), the fork's `components.toml` |
| Hardware facts | `fuxi_touch_panel_porting.md` and `facts/` (every value names its source), the selected SoC DTSI |
| Touch | [FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch), `package/FuxiTouchProbe.cpp`, `package/FuxiTouchBoard.h` |
| Kernel | [Source and patches](https://unixnu.com/xnu/source-and-patches), `patches/xnu/series` |
| Images | [Prelink](https://unixnu.com/concepts/prelink), [payload](https://unixnu.com/concepts/payload), [UEFI](https://unixnu.com/porting/uefi-firmware) |

## Work

Take hardware values from the stock device tree or a measurement on the device, and record the source next to the value.
Other fuxi ports are references, not sources of truth. Do not copy GPL code (the Android `fts_spi` driver) into this
repository. `package/TouchBoard.h`, `package/QcomRpmh.*`, `package/SmmuBypass.h` and `package/ShengPlatformPower.cpp`
are unchanged copies from UniXNU-sheng `package/`, `package/NativeHidInput.cpp` is an unchanged copy of UniXNU
ShengHidInput (71a40e7), and `package/NativeRamBlock.cpp`, `package/SparseDisk.h`, `package/SeedDisk.h`,
`package/DirectDisk.h` and `package/PersistOverlay.h` are unchanged copies of UniXNU RamBlock (4be2d7e); keep them
unchanged so they can be compared with their origin.

Run from the UniXNU fork checkout:

```sh
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
./unixnu status --json
./unixnu build kernel
python3 scripts/porting-record.py check --device ../unixnu-fuxi
```

Never flash the device. A test image is started with `fastboot boot` only, and only when the owner asks for it.

## Porting record

`porting.toml` is the shared record. Update the findings or evidence of each area whose files a change touches, and run
the record checker. Report host results and device observations separately, with the commit they were made at.

## Fast iteration rules (mandatory)

- Optimise for the next verified boot milestone, not subsystem completeness. Name the next acceptance signal before editing.
- Preserve a known-good baseline and reuse compatible kernel, firmware, ADT, trust, Data seed and package inputs by exact revision/hash. Never reopen a passed gate without evidence.
- Diagnose the earliest failing transition before coding. Capture decisive checkpoints, return codes, symbols/PCs, registers, mount/UUID state or service exit reasons. Prefer diagnostics that survive reboot or are visible on-screen.
- Change one root cause / one variable per candidate. Add a focused regression that demonstrates the old failure and corrected behavior. Avoid speculative cleanup bundled with a fix; revert regressions rather than stacking workarounds.
- Use the shortest complete loop: focused host regression → exact ABI/type validation → real ARM64 compile/link → artifact/input pairing and readback → uniquely identified candidate → owner-approved temporary device boot.
- Device testing is `fastboot boot` only. Never flash or write partitions without separate, explicit owner approval.
- Preserve full logs and build reports on both success and failure. Ensure shell failure handling still collects status/report artifacts; do not silently omit oversized logs.
- Stop at the milestone: `launchd` confirms userland; then validate Data/services; then SpringBoard/display. Unrelated GPU, Wi-Fi, audio or peripheral work must not delay an earlier milestone.
- Record exact source revisions, changed variable, commands, test outcomes, image/input hashes, last confirmed stage, device observation and one next blocker. Separate documented facts, host tests, device evidence and hypotheses.
- Consult the official UniXNU guide for the current stage before reasoning; do not guess. Never report an edit/build/boot as complete without read-back evidence.
