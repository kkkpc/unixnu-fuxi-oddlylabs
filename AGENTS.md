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

**语言 / Language：** [中文版](#中文版) | [English](#english)

## 中文版

# 设备 Agent 指南

本仓库维护小米 13（fuxi，SM8550）板级内容：DTS、外设连接、组件选择、固件输入、板级探针与打包。每次改动前先阅读 UniXNU 官方 [Porting](https://unixnu.com/porting/)、[device repository](https://unixnu.com/porting/device-repository) 和所用 fork 的组件目录；硬件数值必须来自原厂设备树或真机测量，并在数值旁记录来源。其他 fuxi 移植只能作为参考，不能当作事实来源。

### 必读资料

| 工作 | 必须阅读 |
| --- | --- |
| 每次改动 | [Porting](https://unixnu.com/porting/)、[device repository](https://unixnu.com/porting/device-repository)、fork 的 components.toml |
| 硬件事实 | fuxi_touch_panel_porting.md、facts/、所选 SoC DTSI |
| 触控 | [FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch)、package/FuxiTouchProbe.cpp、package/FuxiTouchBoard.h |
| 内核 | [Source and patches](https://unixnu.com/xnu/source-and-patches)、patches/xnu/series |
| 镜像 | [Prelink](https://unixnu.com/concepts/prelink)、[payload](https://unixnu.com/concepts/payload)、[UEFI](https://unixnu.com/porting/uefi-firmware) |

### 构建与记录

从 UniXNU fork checkout 执行：

```sh
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
./unixnu status --json
./unixnu build kernel
python3 scripts/porting-record.py check --device ../unixnu-fuxi
```

porting.toml 是共享移植记录。改动触及哪个区域，就更新该区域的发现或证据并运行检查器。主机测试结果与真机观察必须分开记录，并标注对应提交。不得把 GPL 的 Android fts_spi 驱动复制进本仓库；标记为上游原样副本的文件必须保持不变。

### 快速推进规则（强制）

本项目优化目标是尽快抵达下一个可验证的启动里程碑，而不是先补齐所有子系统。采用 OnePlus 13T 移植中验证有效的工作方式：冻结已知良好基线、每轮只改一个阻塞变量、让失败可观测，并尽快产出可测试候选镜像。

1. **冻结已知良好基线。** 按精确 revision/hash 复用已验证的内核输入、固件、ADT、trust cache、Data seed 和打包配置。没有证据表明故障来自已通过阶段时，不重建、不重开。
2. **围绕明确里程碑推进。** launchd 正在运行是 userland 的硬指标；随后验证 Data/services，再推进 SpringBoard/display。GPU 加速、Wi-Fi、音频或无关外设不得阻塞更早的里程碑。
3. **先诊断再改代码。** 找出最早尚未验证的转换点，采集最小而决定性的证据：checkpoint、返回码、symbol/PC、寄存器、mount/UUID 或服务退出原因。优先使用重启后仍保留或屏幕可见的诊断。明确区分文档事实、主机验证、设备观察和假设。
4. **每轮一个根因、一项受控改动。** 尽可能用聚焦的主机回归复现旧故障并验证修复。不要捆绑推测性清理；若候选版本破坏已知良好里程碑，回退该改动，不要叠加 workaround。
5. **使用最短完整验证闭环。** 聚焦主机回归 → 精确 ABI/type 检查 → 真正的 ARM64 编译/链接 → 构件与输入配对/readback → 唯一标识的候选镜像 → 经所有者明确要求后才进行临时真机启动。
6. **保护设备。** 设备测试只允许 fastboot boot 临时启动。没有单独、明确的所有者批准，绝不刷写或写入任何分区。
7. **让失败的 CI 也能诊断。** 成功和失败都保留完整日志与 build report。主构建命令失败后仍必须收集 status/report；不得让 shell errexit 跳过诊断，也不得因文件过大而静默漏收日志。
8. **到达里程碑就停止向前阶段返工。** launchd 已确认后，除非新证据要求，否则不继续重查内核 bring-up；SpringBoard 到达后，隔离显示/用户空间问题，不重开已完成的存储、trust 或启动链工作。
9. **分开证据等级。** 分别报告文档事实、主机测试、构建/链接、构件 readback 和真机观察。文件生成、主机测试通过、bootloader 接受或 workflow summary 都不能证明更后面的阶段成功。
10. **每轮在仓库闭环。** 记录改动变量、源码 revision、命令、测试结果、镜像/输入身份与 hash、最后确认的启动阶段、真机观察，以及唯一的下一阻塞点。只用有证据的状态更新受影响的 porting.toml 和 README。

### 当前执行纪律

- 当前目标是用最短的证据链抵达真实 userland/UI 里程碑，不是广泛补齐驱动。
- 冻结已完成的 archive/build gates。除非新错误直接指向它们，否则不重复成功的 archive gate、ABI 审计或 setup。
- 遇到链接或运行时错误，先检查真实声明、生成的 relocation/binding 和最终链接构件，再提出源码层 workaround。源码中的空指针检查不能使非法 relocation 自动安全。
- 不根据预期输出路径或 workflow 摘要推断成功；必须读取真实 artifact/log 并核验。
- 当前阶段先查 UniXNU 官方文档；文档未说明的部分明确标为假设，不得猜测。
- 未经 GitHub/CI/设备证据 readback，不得宣称编辑、构建或启动已完成。

## English

# Device Agent Guide

This repository owns the Xiaomi 13 (fuxi, SM8550) board: DTS, peripheral wiring, component selection, firmware inputs, board probes and packaging. Before every change, read the official UniXNU [Porting](https://unixnu.com/porting/), [device repository](https://unixnu.com/porting/device-repository), and the selected fork's component catalog. Hardware values must come from the stock device tree or a device measurement, with the source recorded next to each value. Other fuxi ports are references, not sources of truth.

### Required reading

| Task | Required reading |
| --- | --- |
| Every change | [Porting](https://unixnu.com/porting/), [device repository](https://unixnu.com/porting/device-repository), the fork's components.toml |
| Hardware facts | fuxi_touch_panel_porting.md, facts/, selected SoC DTSI |
| Touch | [FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch), package/FuxiTouchProbe.cpp, package/FuxiTouchBoard.h |
| Kernel | [Source and patches](https://unixnu.com/xnu/source-and-patches), patches/xnu/series |
| Images | [Prelink](https://unixnu.com/concepts/prelink), [payload](https://unixnu.com/concepts/payload), [UEFI](https://unixnu.com/porting/uefi-firmware) |

### Build and records

Run from the UniXNU fork checkout:

```sh
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
./unixnu status --json
./unixnu build kernel
python3 scripts/porting-record.py check --device ../unixnu-fuxi
```

porting.toml is the shared porting record. Update the findings or evidence for every area touched by a change, then run the checker. Record host test results separately from device observations and identify the commit for each. Do not copy the GPL Android fts_spi driver into this repository; files designated as unchanged upstream copies must remain unchanged.

### Fast iteration rules (mandatory)

The project optimises for the next verifiable boot milestone, not for completing every subsystem. Follow the workflow proven effective in the OnePlus 13T port: freeze the known-good baseline, change one blocking variable per iteration, make failures observable, and produce a testable candidate quickly.

1. **Freeze the known-good baseline.** Reuse verified kernel inputs, firmware, ADT, trust cache, Data seed and packaging by exact revision/hash. Do not rebuild or reopen passed stages without evidence that the current failure implicates them.
2. **Work toward explicit milestones.** launchd running is the hard userland milestone; then verify Data/services, followed by SpringBoard/display. GPU acceleration, Wi-Fi, audio and unrelated peripherals must not block an earlier milestone.
3. **Diagnose before editing.** Find the earliest unverified transition and capture the smallest decisive evidence: checkpoint, return code, symbol/PC, registers, mount/UUID or service exit reason. Prefer diagnostics that survive reboot or are visible on-screen. Separate documented facts, host verification, device observations and hypotheses.
4. **One root cause and one controlled change per iteration.** Reproduce the old failure with a focused host regression where practical, then prove the corrected case. Do not bundle speculative cleanup. If a candidate regresses a known-good milestone, revert that change instead of stacking workarounds.
5. **Use the shortest complete validation loop.** Focused host regression → exact ABI/type checks → real ARM64 compile/link → artifact and input-pairing/readback checks → uniquely identified candidate → temporary device boot only after an explicit owner request.
6. **Protect the device.** Device tests use fastboot boot only. Never flash or write partitions without separate, explicit owner approval.
7. **Make failed CI runs diagnosable.** Preserve complete logs and build reports on success and failure. Collect status/report artifacts after a failed build; do not let shell errexit hide diagnostics or silently omit oversized logs.
8. **Stop at the milestone.** Once launchd is confirmed, do not revisit kernel bring-up absent new evidence. Once SpringBoard is reached, isolate display/user-space issues without reopening completed storage, trust or boot-chain work.
9. **Keep evidence levels separate.** Report documented facts, host tests, build/link results, artifact readback and device observations separately. A generated file, passing host test, bootloader acceptance or workflow summary does not prove a later stage.
10. **Close every iteration in the repository.** Record the changed variable, source revisions, commands, test results, exact image/input identities and hashes, last confirmed boot stage, device observation and exactly one next blocker. Update the affected porting.toml area and README only with evidence-backed status.

### Current execution discipline

- The objective is the shortest evidence-backed path to a real userland/UI milestone, not broad driver completeness.
- Freeze completed archive/build gates. Do not repeat successful archive gates, ABI audits or setup unless new evidence points directly to them.
- For linker/runtime failures, inspect the real declaration, generated relocation/binding and final linked artifact before proposing a source workaround. A source null check does not make an invalid relocation safe.
- Never infer success from an expected output path or workflow summary; fetch and verify the actual artifact/log.
- Consult the official UniXNU documentation for the current stage. Label undocumented behavior as a hypothesis; do not guess.
- Never claim an edit, build or boot is complete without GitHub/CI/device readback evidence.

Never flash the device. Test images use fastboot boot only, and only after the owner explicitly requests a device test.
