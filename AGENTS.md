**语言 / Language：** [中文版](#中文版) | [English](#english)

**交接进展 / Handoff progress：** [中文](#2026-11-10-当前交接状态) | [English](#2026-11-10-current-handoff-state) | [handoff.md](handoff.md) | [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

## 中文版

# 设备 Agent 指南

本仓库维护小米 13（fuxi，SM8550）板级内容：DTS、外设连接、组件选择、固件输入、板级探针与打包。共享 SM8550 资源归 `UniXNU-sm8550-common`；构建驱动、组件目录和文档归 UniXNU。本板使用 [OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) 的 `fuxi` 分支构建，该分支包含 `FuxiFtsTouch` 组件及 fuxi 所需的 bootimg 参数，上游 UniXNU 目前尚不包含这些内容。固件使用 [OddlyLabs/uefi-fuxi](https://github.com/OddlyLabs/uefi-fuxi) 的 `fuxi` 分支，基于 UniXNU/uefi-sheng 并包含 matejkoo217/uefi-fuxi 的 fuxi 提交。两个 fork 应保持为上游加少量 fuxi 专属提交；合并上游后，更新 `.github/workflows/build.yml` 中 pin 住的 revision。

### 必读资料

| 工作 | 必须阅读 |
| --- | --- |
| 每次改动 | [Porting](https://unixnu.com/porting/)、[device repository](https://unixnu.com/porting/device-repository)、fork 的 `components.toml` |
| 硬件事实 | `fuxi_touch_panel_porting.md`、`facts/`（每个数值注明来源）、所选 SoC DTSI |
| 触控 | [FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch)、`package/FuxiTouchProbe.cpp`、`package/FuxiTouchBoard.h` |
| 内核 | [Source and patches](https://unixnu.com/xnu/source-and-patches)、`patches/xnu/series` |
| 镜像 | [Prelink](https://unixnu.com/concepts/prelink)、[payload](https://unixnu.com/concepts/payload)、[UEFI](https://unixnu.com/porting/uefi-firmware) |

### 工作约定

硬件数值必须来自原厂设备树或真机测量，并在数值旁记录来源。其他 fuxi 移植只能作为参考，不能作为事实来源。不得把 GPL 的 Android `fts_spi` 驱动复制进本仓库。`package/TouchBoard.h`、`package/QcomRpmh.*`、`package/SmmuBypass.h`、`package/ShengPlatformPower.cpp` 是 UniXNU-sheng `package/` 的原样副本；`package/NativeHidInput.cpp` 是 UniXNU ShengHidInput（`71a40e7`）的原样副本；`package/NativeRamBlock.cpp`、`package/SparseDisk.h`、`package/SeedDisk.h`、`package/DirectDisk.h` 和 `package/PersistOverlay.h` 是 UniXNU RamBlock（`4be2d7e`）的原样副本。保持这些文件不变，以便与来源逐项比较。

从 UniXNU fork checkout 执行：

```sh
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
./unixnu status --json
./unixnu build kernel
python3 scripts/porting-record.py check --device ../unixnu-fuxi
```

绝不刷写设备。测试镜像只允许使用 `fastboot boot` 临时启动，并且只有机主明确要求时才执行。

### 移植记录

`porting.toml` 是共享移植记录。改动触及哪个区域，就更新该区域的发现或证据并运行记录检查器。主机测试结果与真机观察必须分开报告，并注明对应提交。

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

---

**语言 / Language：** [中文版](#中文版) | [English](#english)


## 2026-11-08 快速 Bring-up：Userland → SpringBoard → Lock Screen

**目标与里程碑。** 快速 bring-up 不是“所有驱动一次完成”，而是沿最短、可证明的路径到达下一个真实系统里程碑。按 M4/M5 口径：M4 = launchd 已实际运行（userland 硬里程碑）；M5 = 可见且稳定的图形登录/锁屏界面。中间必须分别验证 Data、关键系统服务与 SpringBoard，不能把“SpringBoard 进程被拉起”写成“锁屏已到达”。

**冻结输入，不重造已通过的地基。**
- 固定 iPadOS 17.7.11 / 21H461 与已证明的 arm64 用户态；每轮记录内核源码 revision、kernel.macho、固件、ADT、trust cache、Data seed、镜像和工具链身份/hash。
- 复用已验证的 root / OS / SystemOS、信任链、持久化 Data 与启动打包输入。除非新的第一手证据指向它们，不重做 archive、ABI、trust、UFS/Data 或已通过的启动阶段。
- 持久化窗口必须配对沿用 chain55 的原始种子字节（SHA-256 前缀 df83bf77；完整值见交接记录）。不得用每轮新生成的 CI 种子替代，不得重新格式化或改写种子来“试试看”。
- 本线禁止 payload --skip-setup 和主机侧修改种子；当前 Skip Setup 功能目标采用持久化 Data 上的内核 writer 路线。其功能目标已在真机上达到（未进入 Setup 页面并到达 SpringBoard），但 SetupDone 的值尚未直接读取；不得把它表述成官方 Skip Setup 全部 Verify 项通过。

**最短推进顺序。**
1. DarwinBoot → XNU → root / OS / SystemOS：只核对启动链确实到达已知检查点；不重复修已关闭阶段。
2. launchd（M4）：以实际运行证据为准，不以镜像生成、bootloader 接受或单一日志字符串代替。到达后把内核启动问题冻结，除非新证据明确回指内核。
3. Data 与关键服务：确认持久化 Data 被识别并按预期续跑，核对挂载、UUID、读写状态和关键服务退出原因；种子身份与窗口几何必须保持一致。
4. SpringBoard：区分“服务签名入口/启动尝试计数”“exec 成功”“进程稳定存活”。任何计数都要按其真实采样点命名，不能把入口计数写成成功计数。
5. Lock Screen（M5）：只有真机上实际出现并保持可交互的锁屏界面，才算达标。SpringBoard 已启动、Setup 页面被跳过、或显示初始化日志出现，都不等于锁屏成功。

**当前已知的 SpringBoard 阻塞点（不要误诊）。**
- chain60/chain61 已将循环退出定位到 FrontBoardServices 的 -[FBSDisplaySource initWithCADisplay:]：主 CADisplay 查找失败，记录 failed to find the main CADisplay 后顺序执行 BRK #0，随后走 SIGTRAP 退出路径。
- 因此当前直接阻塞点是显示提供者/显示初始化链，不是尚未解释的外部 kill，也不是需要继续追加退出原因 kcdata 探针。Phase 2 已 Deferred / Not Approved：不编码、不改 XNU、不加 exit-reason hook、不构建 chain62，除非未来出现能改变决策的新证据并重新评审。
- 先完成主机侧只读核验与单变量设计评审。现有审计指向 L2 provider 缺口：GopFramebuffer 尚未接入本设备的 board/defconfig/builder/启动参数。以同 SoC 的 sheng 线作为集成形态参考；不得照搬其面板细节。fuxi 面板事实仍以本机硬件资料为准。
- 不要通过屏蔽 SpringBoard 的 BRK、伪造 CADisplay、放宽签名或堆叠 workaround 来制造“启动成功”。先让真实显示服务提供者正确发布，再验证 FrontBoardServices 能找到 main CADisplay。

**一加 13T 快速迭代节奏（强制）。**
1. 先读当前阶段的 UniXNU 官方指南；把文档明确规定、源码证据、主机验证、真机观察和假设分开写。
2. 先定位最早失败转换点，优先用已有 USB CDC 日志、持久化计数或屏幕可见 checkpoint；不要先加新钩子。USB 调试的日志通道可用，但远程 reset 必须保持关闭，不启用 REBOOT 动词。
3. 每轮只修一个根因、改变一个变量。先做聚焦 host regression，再做真实 ARM64 编译/链接，检查 relocation/binding 与最终构件；源码空指针检查不能替代链接产物审计。
4. 固定已验证输入，产出唯一标识候选镜像；逐项核对镜像、kernel、ADT、trust、Data seed 配对及 hash。构建失败也要收集完整原始日志和 build report。
5. 只有机主明确要求时才上机；只用 fastboot boot，不刷写、不写分区。每次只验证一个假设，记录屏幕/USB 日志、最后确认里程碑和唯一下一阻塞点。
6. 若回退到已知良好里程碑，撤销本轮变量，不叠加补丁。达到 M4 后停止无证据的内核重查；达到 SpringBoard 后把工作收敛到显示与 userland；达到 M5 后再规划 GPU、触控体验等非锁屏必需项。

**每轮必须记录。** 改动变量及根因、基线与所有输入 hash、源码 revision、命令、host tests、ARM64 build/link 结果、镜像 readback、真机启动方式、实际可见界面、日志/计数语义、最后确认的 M 阶段、一个下一阻塞点。README、AGENTS.md 与 porting.toml 只记录已被证据支持的状态。


---


## 2026-11-08 Fast Bring-up: Userland → SpringBoard → Lock Screen

**Goal and milestones.** Fast bring-up does not mean completing every driver at once. It means reaching the next real, evidence-backed system milestone through the shortest safe path. Use the M4/M5 convention: M4 = launchd is demonstrably running (the hard userland milestone); M5 = a visible, stable graphical login/lock-screen interface. Verify Data, critical services and SpringBoard separately. A SpringBoard launch attempt is not proof that the lock screen has been reached.

**Freeze inputs; do not rebuild a proven foundation.**
- Pin iPadOS 17.7.11 / 21H461 and the proven arm64 userspace. Record the kernel source revision and the identities/hashes of kernel.macho, firmware, ADT, trust cache, Data seed, image and toolchain on every iteration.
- Reuse verified root / OS / SystemOS, trust-chain, persistent Data and boot-packaging inputs. Do not repeat archive, ABI, trust, UFS/Data or passed boot stages unless new first-hand evidence implicates them.
- The persistent window must continue using the exact original chain55 seed bytes (SHA-256 prefix df83bf77; see the handoff for the full digest). Do not substitute a newly generated per-run CI seed, reformat the seed or mutate it experimentally.
- This line prohibits payload --skip-setup and host-side seed modification. The current Skip Setup functional route is the kernel writer on persistent Data. The device-level functional goal was reached (no Setup page; SpringBoard reached), but the SetupDone value has not been read directly. Do not claim that every item in the official Skip Setup verification checklist passed.

**Shortest progression.**
1. DarwinBoot → XNU → root / OS / SystemOS: verify only that the boot chain reaches its known checkpoints; do not reopen closed stages.
2. launchd (M4): require evidence that it actually runs. Image generation, bootloader acceptance or one log string is insufficient. Once reached, freeze kernel bring-up unless new evidence points back to the kernel.
3. Data and critical services: confirm persistent Data is recognised and resumed as expected; check mounts, UUIDs, read/write state and critical-service exit reasons. Preserve seed identity and storage-window geometry.
4. SpringBoard: distinguish signed-entry/launch-attempt counters from successful exec and stable process lifetime. Name every counter after its actual sampling point; never label an entry counter as a success counter.
5. Lock Screen (M5): count it only when the device visibly displays a stable, interactive lock screen. SpringBoard launch, bypassing Setup, or a display-initialisation log is not lock-screen success.

**Known SpringBoard blocker (avoid misdiagnosis).**
- chain60/chain61 localised the restart loop to FrontBoardServices -[FBSDisplaySource initWithCADisplay:]: lookup of the main CADisplay fails, the code logs failed to find the main CADisplay, then falls through to BRK #0 and exits through SIGTRAP.
- The immediate blocker is therefore the display-provider/initialisation path, not an unexplained external kill and not a reason to add another exit-reason kcdata probe. Phase 2 is Deferred / Not Approved: do not implement it, patch XNU, add an exit-reason hook or build chain62 unless new evidence changes the decision and the design is reviewed again.
- Complete read-only host verification and single-variable design review first. The current audit points to a missing L2 provider integration: GopFramebuffer is not yet wired into this device's board/defconfig/builder/boot arguments. Use the same-SoC sheng line as an integration-shape reference only; do not copy its panel details. fuxi panel facts must come from this device's hardware evidence.
- Do not manufacture apparent success by suppressing SpringBoard's BRK, faking CADisplay, weakening signing or stacking workarounds. Publish a real display provider first, then verify that FrontBoardServices can find the main CADisplay.

**OnePlus 13T fast-iteration cadence (mandatory).**
1. Read the official UniXNU guide for the current stage first. Separate documented requirements, source evidence, host verification, device observations and hypotheses.
2. Find the earliest failing transition. Prefer existing USB CDC logs, persistent counters or visible checkpoints; do not add a new hook first. The USB diagnostic log channel is available, but remote reset must remain disabled and the REBOOT verb must not be enabled.
3. Fix one root cause and change one variable per iteration. Run a focused host regression, then a real ARM64 compile/link; inspect relocations/bindings and the final artifact. A source null check is not a substitute for auditing the linked output.
4. Freeze verified inputs and produce a uniquely identified candidate image. Verify image, kernel, ADT, trust, Data-seed pairing and hashes. Preserve complete raw logs and build reports even when a build fails.
5. Boot the device only when the owner explicitly requests it; use fastboot boot only, with no flashing or partition writes. Test one hypothesis per boot and record screen/USB evidence, the last confirmed milestone and exactly one next blocker.
6. If a change regresses a known-good milestone, revert that variable rather than stacking patches. After M4, stop unsupported kernel re-investigation; after SpringBoard, focus on display and userland; after M5, plan nonessential GPU and touch-experience work separately.

**Required iteration record.** Record the changed variable and root cause, baseline and every input hash, source revision, commands, host tests, ARM64 build/link results, image readback, device boot method, actually visible UI, log/counter semantics, last confirmed M milestone and one next blocker. Update README, AGENTS.md and porting.toml only with evidence-backed status.

---

## 2026-11-10 当前交接状态

[English](#2026-11-10-current-handoff-state) · [handoff.md](handoff.md) · [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

1. **已知良好基线锁定为 Build #143 / `827f289e`。** 后续分支 HEAD 失败时，不得把新 HEAD 当成已验证基线。
2. #144/#145 是无人值守迁移实验，不是完成态。#145 已知 gate：缺 `sheng-log=1` 的 host-contract 一致性，以及 `board.toml` 变更未同步 `porting.toml` configuration evidence。
3. **任何显示/GPU/锁屏问题先查 Xiaomi 13 V2。** V2 是同机型真机成功参考；之后才查本仓库 `cpu-legacy-display`、UniXNU 上游和官方 UnixNu 文档。文档用于校验，不得替代同机成功路径对比。
4. `cpu-legacy-display` 的 23 个独有提交逐项分类为：已等效覆盖 / 锁屏关键且缺失 / 非关键诊断或文档 / 不适用于当前 pinned 组件。只 cherry-pick 或重实现第二类；**禁止整分支 merge**。
5. 优先审计 Legacy GOP/provider、21H461 display ABI、18 个 callback C linkage、`native_adreno_fences`、`sheng-vsync=120`、display scale/rotation、main `CADisplay` 发布链。
6. “slot 345”在讨论与文档中优先写成人话：**显示系统询问主屏时序是否已经准备好**。不得把它描述成 GPU 渲染或“锁屏修复完成”。
7. 每个修复循环必须记录：旧失败、V2/上游/官方依据、最小改动、提交 SHA、CI run 与结果。累计 5 个有效 push 后同步 README、AGENTS、handoff 与 Issue #7。
8. 自动化不得执行物理设备刷写、reboot 或 fastboot。真机候选只在 Build 全绿后交给机主。

## 2026-11-10 Current handoff state

[中文](#2026-11-10-当前交接状态) · [handoff.md](handoff.md) · [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

1. **Pin Build #143 / `827f289e` as the known-good baseline.** A later failing HEAD must never be treated as a validated baseline.
2. #144/#145 are unattended migration experiments, not completion states. Known #145 gates are the missing `sheng-log=1` host-contract requirement and missing matching `porting.toml` configuration evidence for the `board.toml` change.
3. **For display/GPU/lock-screen work, inspect Xiaomi 13 V2 first.** It is the same-device, device-proven success reference. Only then inspect local `cpu-legacy-display`, upstream UniXNU and official UnixNu docs. Documentation validates the path; it must not replace the same-device comparison.
4. Classify the 23 unique `cpu-legacy-display` commits as already-equivalent / missing lock-screen-critical / non-critical diagnostics-docs / incompatible with current pins. Cherry-pick or reimplement only the missing critical class; **never merge the branch wholesale**.
5. Review Legacy GOP/provider, 21H461 display ABI, the 18 callback C-linkage fix, `native_adreno_fences`, `sheng-vsync=120`, display scale/rotation and main-`CADisplay` publication first.
6. Describe “slot 345” in plain language: **the display stack asks whether primary-display timing is ready**. It is not GPU rendering and is not proof that the lock screen is fixed.
7. Every fix loop records the previous failure, V2/upstream/official basis, minimal change, commit SHA, CI run and result. After five effective pushes, synchronize README, AGENTS, handoff and Issue #7.
8. Automation must never flash, reboot or fastboot the physical device. Hand a candidate to the owner only after the Build is fully green.


## 2026-11-10 五次 Push 检查点 / 5-Push Checkpoint

- 基线：827f289e。此前四个有效提交：6733bad0、06fbd3c8、a132feb0、51f050ca；本提交为第 5 次。
- Build #146 真机已证明 16 GiB Data 路线正确：OwnerData 正常挂载，persistent 写入持续增长且 er=0，#143 的 device-not-ready/APFS corruption 消失。
- #146 当前阻塞收敛到显示提交链：GPU fence 9/9 retire、CP 无 fault，但 frames=0、gop offers=0，gop_wait 持续超时。
- 直接解析机主提供的成功 t50-auto-sb3.img：实际 unixnu.toml 使用 offline-legacy-unit-scale=3 与 sheng-vsync=120。因此冻结 scale=3；本轮只引入 vsync=120。
- Persistent 迁移已完成：下一镜像删除一次性的 sheng-data-reset=1，并固定复用 Build #146 / run 42744943462 / artifact 13731556139 的同一份 16 GiB seed，禁止 CI 重新生成 seed 破坏 identity。
- cpu-legacy-display 的 23 个独有提交继续作为审计源而非整体 merge 源；b408dd56 的 vsync=120 是本轮选中的显示变量，a4cfdac3 的 scale/rotation 暂不移植。
- 安全边界不变：CI 不刷机、不重启真机、不执行 fastboot；QUD reboot 继续编译为 0。

### English

- Baseline: 827f289e. The prior four effective commits are 6733bad0, 06fbd3c8, a132feb0 and 51f050ca; this is push 5.
- The #146 device boot validates the 16 GiB Data path: OwnerData mounts, persistent writes grow with er=0, and the old device-not-ready/APFS-corruption signatures are gone.
- The remaining blocker is display presentation: GPU fences retire 9/9 with no CP fault, while frames=0, GOP offers=0 and GOP waits keep timing out.
- Direct inspection of the owner's successful t50-auto-sb3.img shows offline-legacy-unit-scale=3 plus sheng-vsync=120. Scale 3 is frozen and vsync=120 is the only display variable added now.
- The one-time migration reset is removed while CI pins the exact Build #146 seed artifact so persistent identity cannot drift.
- The 23 unique cpu-legacy-display commits remain an audit source, never a wholesale merge source; b408dd56 is selected, while a4cfdac3 stays out for now.
