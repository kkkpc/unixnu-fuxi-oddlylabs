# unixnu-fuxi：小米 13（fuxi）的 UniXNU 设备仓库

**语言 / Language：** [中文版](#中文版) | [English](#english)

**当前进展 / Current progress：** [中文进展](#2026-11-10-当前进展) | [English progress](#2026-11-10-current-progress) | [handoff.md](handoff.md) | [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

## 中文版

[![Build](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/build.yml/badge.svg)](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/build.yml)
[![Device documentation](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/porting-record.yml/badge.svg)](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/porting-record.yml)

本仓库是小米 13（fuxi，SM8550）的 UniXNU 设备仓库，基于 UniXNU 的 `examples/device` 模板创建，使用 [OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) 的 `fuxi` 分支构建；该分支的组件目录包含 `FuxiFtsTouch`。

主文档：[fuxi_touch_panel_porting.md](fuxi_touch_panel_porting.md)。各子系统的状态以 [porting.toml](porting.toml) 为准。

本仓库是机主导入的工作副本；`native-ufs-root` 分支是原生 UFS 根 + 完整系统启动线（见下表存储行），与上游 main 的恢复盘状态不同。当前进度交接见 [Issue #2](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/2)（2026-11-06，持久化 Data 阶段关闭）与 [Issue #4](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/4)（2026-11-07，阶段 ② 打开、SpringBoard 退出定位、显示审计汇总）。分支结构：`main` 是导入基线，`native-ufs-root` 是当前工作主线；旧分支 `ram-system-probe` 已于 2026-11-07 归档为标签 `archive/ram-system-probe-2026-11-07` 并删除（其 5 个独有提交从该标签完整可达）。在 UniXNU 官方移植主线（Port a device，8 步）上，本线位于第 6 步（按依赖顺序适配驱动）进行中：存储完成、触摸已验证、显示是当前关口。

## 现状

| 子系统 | 状态 |
|---|---|
| 触控（ST FTM5） | 驱动和分阶段探针已写好。2026-11-02 第 3 阶段上机通过：上电、时钟、引脚和 12 MHz SPI 都正常，复位后收到就绪事件，读到芯片 ID `36 40`。第 4 阶段通过：轮询和中断两种模式都读到了完整的点击（按下、移动、抬起和坐标），两根手指也能分别跟踪，8 个核都在运行时也正常。触控电源必须由探针投 RPMh 票，不投时控制器不应答。开中断的启动共 8 次，有 1 次在内核启动几秒后自己重启，原因还没查清。HID 层（`ShengHidInput`）已接入并上机验证：事件驱动挂在 sheng 默认的组合设备上，每组触点都作为 HID 报告送进系统（一次 68 组，全部成功） |
| 固件和启动镜像 | CI 构建 DEBUG 固件和 `fastboot boot` 用的启动镜像，只上传加密版本。2026-11-02 上机：bootloader 接受镜像，固件、UniXNU 菜单和 DarwinBoot 正常，XNU 启动到 `bsd_init`。途中修了两处：缺 sheng 的 AMP 补丁（CPU 拓扑）；内核按树莓派的固定地址读写 panic 日志区（打开 `CONFIG_XNU_DT_PANIC_REGION`）。记录见 `evidence/2026-11-02-first-boot.md`。固件内存表已按 8 GB 和 12 GB 两台手机修正（uefi-fuxi `c5793bc2`），在这台 12 GB 手机上启动正常 |
| 存储 | 原生 UFS 根已上机。ShengUfs 驱动读 userdata 开头的 SHNGROOT 清单，发布 OS 与 SystemOS 两个只读窗口；几何由官方 ROM 的 GPT 核实，根镜像由 `scripts/build-userdata-root-image.py` 构建，2026-11-05 经机主批准刷入（Android 的 /data 已清除，回滚需重刷官方 ROM），probe=11 在机上读回校验通过。出版门缺陷与 root_match 的 UUID 误读修好后 APFS System 卷挂载成功；owner 信任链已移植（双卷全量签名策略编入内核，约 73 MB），chain41 上机：根认证通过、`/sbin/launchd` 执行。payload 自 Build #45 起带双模块系统信任束（`7416ca4f…`），chain45 上机：exec 关口通过、dyld 启动，停在找不到 shared cache——cache 在 SystemOS 卷里而该卷此前未挂载。Build #46 已打开 `OWNER_CACHE_MOUNT` / `OWNER_CACHE_STARTUP` / `OWNER_UNION_SYSTEMOS`（内核在 exec initproc 前把 SystemOS union 挂到 `/`），chain46 上机通过：launchd 到达 LC_MAIN，终态是上游验收脚本钉死的 `mount[3]` 以状态 66 退出——dyld 关关闭。Data 卷（临时种子形态）已接通并关闭：方案 A 接线（`OWNER_BOOT_MANIFEST` + `OWNER_DATA_MOUNT` + 上游 pin 的 Data 卷 UUID）后，chain47/48/49 三次纯黑屏；判别镜像 disc1（chain46 内核 + chain49 负载）证明故障在固件的 dense 种子负载投递、不在内核 Data 代码——256 MiB 种子整份直拷死在内核启动前。改用 packed 投递（DBRDISK1，种子压到约 1 MB，payload 回 192 MiB）后 chain50 上机正常启动（watchdogd[139]），launchd 拉起上百进程、越过 66 终态。形态已正式化进 CI（种子 job 打包、payload 吃 .dbr，head `da47a1eb`，Build 与文档检查 #62 双绿），chain51 用纯 CI 构件上机复现同一终态（watchdogd[140]）。持久化 Data 已完成（2026-11-06，Phase A/B/C 全关闭）：机制本就在内核里（NativeRamBlock 的 persist 路径 + ShengUfs 的 store 钩子），存储窗口是 userdata 尾部空闲区（first_lba `0x57bd52`，种子容器长到 213 GiB），不用重刷。Phase A 把上游 seed grower 接进 CI 的种子 job（head `64572e94`，Build #67 校验通过，产物逻辑尺寸精确 213 GiB）。persist 计数没有现成渲染者：计数行放控制台两次都没进照片（照片页是 panic 页、只承载 panic 记录），改为把计数追加进 panic 串本身后才拍到。Phase B（`sheng-data-persist=1` 只读证明）chain54 上机：`st=1 hdr=1 pres=0 ld=1 wr=0 sy=0 er=0`，窗口按设计几何打开、零写入。Phase C 经机主单独批准：chain55 安装启动（persist=2 + `sheng-data-reset=1`）`st=3 pres=33223 wr=33243 sy=280`，窗口初始化并写入约 130 MiB；chain56 续跑被拒（`st=7 hdr=3`）——CI 每轮新长的种子字节不同，而 header 按种子身份（尺寸 + 非零页哈希）校验，换种子即外来 header，窗口原样不动；chain57 改用 chain55 的原种子本地组装续跑，上机 `st=2 hdr=0 pres=81386 ld=19214 wr=9226 sy=1310 er=0`：上一启动写下的状态被认出、读回并继续写入，跨重启持久化成立。持久化关闭的验收镜像是 chain57；现行标准启动镜像是 chain61（同一份种子配对，见下「用户空间与阶段 ②」行），chain61 上机时存储窗口第七次续上并继续写入（最终流 pres=107654）。今后要保住窗口里的状态，启动镜像必须继续带同一份种子（`df83bf77…`）。恢复盘路径保留：2026-11-03 经 RAM 块设备把恢复盘作为根挂载，跑起了 `launchd`、`restored_external`、`mount_tmpfs` |
| CPU | 2026-11-02 上机：`sheng-smp=1 armcpu-spi-ipi=1` 时 7 个副核都经 PSCI 启动成功，调度器认到 8 个核；再加 `armcpu-self-ipi=1` 核间中断才通。两个小核（1、2 号）还没见到时钟中断。默认镜像已打开多核（含 `armcpu-self-ipi=1`）。2026-11-03：去掉 `armcpu-spi-ipi=1` 时核间中断送不到（SGI 在这台机器上不通）；9 次多核启动里有 1 次副核全都没起来，原因未知 |
| 用户空间与阶段 ②（功能 UI/显示） | 2026-11-07 打开。Skip Setup 采用路线 (b)：内核 writer（`package/BootWatchdogPolicy.c`）在持久化 Data 上写入官方 21H461 偏好集，设备未进入 Setup 页面、已到达 SpringBoard——功能目标经真机验证达成（实现路径有意偏离官方 payload `--skip-setup` 种子副本方式；`SetupDone` 的值未直接读取验证，`payload.json` 为 `skip_setup: false`）。chain58 上机：全程盯屏无任何图形帧（「先渲染后被覆盖」排除）。chain59 探针读得 `sksu=0/1`（SetupDone 键存在）。chain60 生命周期探针：14 个 SpringBoard 周期全部在签名通过后以 status=0x5 / ns=2 / code=0x5 退出，ns/code 经钉版 xnu-10063.141.1 `reason.h` 核实为 OS_REASON_SIGNAL / SIGTRAP。chain61 故障探针（Phase 1）：16/16 次退出都带同 PID 的 EL0 breakpoint 记录，pc = lr = `0x1a721f2ec`、esr `0xf2000000`——执行的指令是 BRK #0。主机侧 dyld 缓存解析（缓存经证明为 arm64，非 arm64e）定位到 FrontBoardServices 的 `-[FBSDisplaySource initWithCADisplay:]` +0x47c：其主 CADisplay 查找返回空，记下 `failed to find the main CADisplay` 后顺序落入 BRK #0——刻意的致命断言，不是外部终止。退出原因 kcdata 读出（Phase 2）经复审暂缓：核心问题已被 Phase 1 + 符号解析回答，设计稿保留待未来重启 |
| 显示 | 当前关口（官方第 6 步条目）。三份只读审计（初始化链 / iPad7,1 固件与硬件信息 / XNU 驱动与构建集成）合并结论：第一断点在 L2 显示提供者层——固件扫出（ABL splash `0xb8000000`、GOP 1080×2400）与内核文本控制台都通，原厂 IOMobileFramebuffer/IOSurface 部件都在预链接内核里，唯独把 GOP 帧缓冲发布成 IOKit 显示服务的提供者从未接线：目录组件 `GopFramebuffer`（pin `19ef3a75`，ABI 覆盖 21H461）未被 `board.toml` 选型、`fuxi_defconfig` 无 `CONFIG_XNU_NATIVE_LEGACY_DISPLAY`、无设备 builder、内核参数无 `offline-legacy-*` 组，产物内核中其字符串数为 0。ADT 无显示节点不是缺口（ADT 由板级 FDT 合成，苹果显示子树描述的 A10X 硬件在 SM8550 上不存在）。参照线 sheng（同 SM8550、同 iPadOS 17 配置）已用同一组件真机验证，其构建集成形态可迁移；面板细节不迁移（fuxi 是 Samsung DDIC AMOLED、DSI 命令模式 + DSC，背光走 DCS 命令）。单变量实验序列 E1–E7 已备（E1–E3 纯宿主核验、E4 构建接线、E5 单次真机启用），待机主评审；真机启动暂停中。注意：unixnu.com/devices/fuxi 现挂的是 sheng 的记录，不描述本线 |
| USB 调试 | QcomXnuUsbDebug（ljhhkx529）已采纳并上机验证：模块 vendored 至 `package/drivers/QcomXnuUsbDebug/`，wrapper 构建（`scripts/build-fuxi-usb-debug.py`）；usb1/chain60/chain61 三次启动的内核日志全量经 USB CDC 通道采集（VID 0x1209 / PID 0x316d）。reset 层是模块留给消费方内核的集成边界：本线以 `QUD_CONTROL_REBOOT=0` 正规编译关闭，远程 reset 保持关闭、不重开 REBOOT 动词，已向上游提 Issue 说明。Stage ③ 记录（finding 50）已入 `porting.toml` |
| GPU、网络、音频 | 计划中；显示和电源的硬件资料已整理（阶段顺序与理由见 Issue #1 的计划评论） |

## 相关仓库

| 仓库 | 作用 |
|---|---|
| [OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) | fork 自 UniXNU/UniXNU。分支 `fuxi`：组件目录加了 `FuxiFtsTouch`；`bootimg` 加了 fuxi 需要的两个选项（镜像头加载偏移、把负载放进内核镜像） |
| [OddlyLabs/uefi-fuxi](https://github.com/OddlyLabs/uefi-fuxi) | fork 自官方固件 UniXNU/uefi-sheng。分支 `fuxi`：移植了 matejkoo217/uefi-fuxi 的 9 个 fuxi 提交（保留原作者），这些提交里的结论都在真机上测量过 |
| [OddlyLabs/FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch) | 触控组件：FTM5 协议和触点跟踪，纯 C，带主机测试；本仓库用子模块引用它 |
| 本仓库 | 板级文件、探针、启动钩子补丁、硬件资料 |

UniXNU 自己提供启动菜单（UniXNUPkg）和 XNU 加载器（DarwinBoot），但它们是 UEFI 模块，要靠板级 UEFI 固件才能在手机上运行。fuxi 的固件选的是官方 uefi-sheng 加上经过真机验证的 fuxi 提交：官方部分可以直接合并上游更新，fuxi 部分来源清楚。

## 目录

| 路径 | 内容 |
|---|---|
| `board.toml`、`feeds.toml`、`configs/fuxi_defconfig` | 板子、组件、归档顺序、SoC 版本、内核配置 |
| `dts/fuxi.dts` | 设备树（包含 UniXNU-sm8550-common 的 `sm8550.dtsi`） |
| `patches/xnu/` | `fuxi-touch-probe.patch`：`bsd_init` 调用触控探针 |
| `package/` | 在构建树里是 `kits/fuxi`。`FuxiTouchProbe.cpp`（探针）、`FuxiTouchBoard.h`、`FuxiPanelBoard.h`（板级常量，每项注明来源）；`TouchBoard.h`、`QcomRpmh.*`、`SmmuBypass.h`、`ShengPlatformPower.cpp`（AMFI 需要的 PMGR 桥）原样取自 UniXNU-sheng |
| `scripts/build-fuxi-touch.py` | 用 XNU 构建的编译记录编译探针和驱动，打包成 `libFuxiTouch.a` |
| `scripts/build-fuxi-platform-power.py`、`ci/check-pmgr-bridge.py` | 编译 PMGR 桥（改自 sheng 的构建脚本，改动见文件开头）；CI 在链接后核对它和 AMFI 的约定 |
| `scripts/build-fuxi-data-seed.py`、`scripts/pack-fuxi-data-seed.py`、`scripts/grow-fuxi-data-seed.py` | Data 种子：在 macOS 上造 256 MiB APFS 种子卷（UUID 改 pin、特征字归一化），无损打包成 DBRDISK1，再把容器长大到 userdata 存储窗口尺寸（持久化用） |
| `scripts/build-fuxi-usb-debug.py`、`package/drivers/QcomXnuUsbDebug/` | USB 调试通道：vendored 的 QcomXnuUsbDebug 模块 + wrapper 构建（日志/控制通道；reset 以 `QUD_CONTROL_REBOOT=0` 编译关闭） |
| `drivers/FuxiFtsTouch` | 子模块，指向 FuxiFtsTouch |
| `porting.toml` | 移植记录（UniXNU 格式） |
| `tests/board_test.c` | 板级常量测试 |
| `ci/boot-image-recipient.pem`、`ci/decrypt-boot-image.sh`、`ci/check-boot-image.py` | 启动镜像加密用的公钥、本地解密脚本，以及启动前核对镜像的脚本 |
| `facts/` | 从官方设备树导出的触控、面板事实，以及 73 组面板 DSI 命令序列 |

本地另有 `dtb/`、`firmware/`、`power/`、`ref_src/` 四个目录，不进 Git（见 `.gitignore`）：官方 DTB 和触控固件是厂商文件；dmesg 里有使用痕迹；`ref_src/` 是 GPL 参考源码，只供查阅。

## 构建

需要 macOS 和 Xcode 26（UniXNU 也支持 Linux 工具链，见其文档）。三个仓库放在同一个目录下：

```bash
git clone --recurse-submodules https://github.com/OddlyLabs/unixnu-fuxi
```
```bash
git clone -b fuxi https://github.com/OddlyLabs/UniXNU
```
```bash
git clone -b fuxi https://github.com/OddlyLabs/uefi-fuxi
```

在 UniXNU 目录里依次运行：

```bash
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
```
```bash
./unixnu build kernel
```
```bash
./unixnu build payload --uefi ../uefi-fuxi --unique-chip-id 0x0123456789abcdef
```
```bash
./unixnu build firmware --uefi ../uefi-fuxi --target DEBUG
```
```bash
./unixnu bootimg --uefi ../uefi-fuxi --target DEBUG --dtb ../uefi-fuxi/Platforms/Xiaomi/fuxiPkg/FdtBlob/sm8550-xiaomi-fuxi.dtb
```

`--unique-chip-id` 这里用的是固定的测试值（CI 镜像同理，只做 bring-up 验证）。完整系统的验证镜像在本地组装，那时换成手机自己的值——真值不进仓库。

固件这一步不涉及苹果的文件，也可以在 Linux 上单独跑，适合只改固件时快速验证：除了 clang、lld 和 llvm 工具，BaseTools 还要 `uuid-dev`。2026-11-01 在 Ubuntu 26.04（WSL，clang 21.1.8）上用上面的 `defconfig` 和 `build firmware` 两条命令构建通过，固件卷 0x300000 字节。

## CI（GitHub Actions）

| 任务 | 运行环境 | 检查内容 |
|---|---|---|
| Host tests | Ubuntu | FuxiFtsTouch 测试（gcc/clang，ASan/UBSan）、板级常量测试、脚本语法 |
| Kernel-target compile | macOS 26 + Xcode | 驱动的 C 代码按 arm64 内核代码编译，确认不调用 libc |
| fuxi boot image | macOS 26 + Xcode | 编译内核（XNU 构建、归档、链接、prelink），确认触控探针在内核里、`bsd_init` 调用了它；然后构建 payload、固件和启动镜像，加密后上传 |
| Porting record | Ubuntu | 用 fork 里的 UniXNU 检查器验证 `porting.toml` |

启动镜像里有苹果 kernelcache 的内容，所以只上传用 `ci/boot-image-recipient.pem` 加密过的版本，私钥只在机主自己的电脑上；其余产物只上传文本日志。

## 上机

只用 `fastboot boot` 临时启动，不写任何分区。步骤：

1. 下载 CI 的 `fuxi-boot-image-encrypted-*` 产物，用私钥解密：`bash ci/decrypt-boot-image.sh <私钥> <产物目录>`。
2. 核对镜像：`python3 ci/check-boot-image.py <产物目录>/boot.img <产物目录>/boot.json ../uefi-fuxi`。它按 `board.toml` 和固件配置检查镜像头、加载偏移、固件卷、payload 里的文件、ADT 和启动参数，全部 `ok` 再继续。
3. 手机进入 fastboot，运行 `fastboot boot boot.img`。
4. 默认（bring-up）镜像跑到触控第 4 阶段并把触点作为 HID 报告送进系统，屏幕停在触控报告页。完整系统的验证镜像在本地用解密产物和手机自己的芯片 ID 组装（见存储行），仍只用 `fastboot boot`：屏幕上的 SYS 行、`initproc` 的失败原因就是每一关的读数，停在哪一行就说明停在哪一关。
5. 重启手机回到 Android 引导；userdata 已刷入后，Android 的 /data 不再可用（见存储行）。

### 探针镜像：定位 XNU 早期卡在哪

XNU 自己的控制台出来之前，能看到的只有屏幕顶部的色条：绿色是 DarwinBoot 交出控制权，蓝色是进入内核，品红是即将打开 MMU。再往后，就用会自动重启的“入口探针”来判断：探针放在某个位置，内核走到那里就等几秒然后重启手机。所以手机重启了，说明走到了那里；一直停在色条上，说明在那之前就卡住了。

做法遵循 UniXNU 调试指南（Entry probe reset 一节）。内核由 CI 编译，payload 和启动镜像在本地生成，不需要 Mac：

1. 解密产物：除了 `boot.img`，还会在旁边得到没有打过补丁的 `kernel.macho`。
2. 导出这次测过的固件卷，保证探针镜像里的固件和测过的完全相同：`python3 ci/check-boot-image.py boot.img boot.json ../uefi-fuxi --fd-out fd.bin`。
3. 在设备仓库的一份临时副本里，给 `board.toml` 的 `[payload]` 加上探针设置（不要提交），例如 `entry_probe_reset_delay = 6`（打开 MMU 之后重启），或者再加 `entry_probe_reset_after = "_arm_vm_init"`（`arm_init` 调用完它之后重启）。
4. 在 UniXNU 目录里依次运行（`-D` 指向那份临时副本）：

   ```bash
   ./unixnu build payload -D <临时副本> --uefi ../uefi-fuxi --kernel <kernel.macho> --unique-chip-id 0x0123456789abcdef
   ```
   ```bash
   ./unixnu bootimg -D <临时副本> --uefi ../uefi-fuxi --fd <fd.bin> --dtb ../uefi-fuxi/Platforms/Xiaomi/fuxiPkg/FdtBlob/sm8550-xiaomi-fuxi.dtb -o probe.img
   ```

   Linux 上需要 clang、lld、llvm 工具、`dtc` 和 `mtools`。
5. `fastboot boot probe.img`。设了延时的探针镜像不需要拍照：手机自己重启回系统，就说明走到了探针的位置。

## 维护

- 上游更新：把 UniXNU/UniXNU 的 `main` 合并进 OddlyLabs/UniXNU 的 `fuxi`；把 UniXNU/uefi-sheng 的 `sheng` 合并进 OddlyLabs/uefi-fuxi 的 `fuxi`。
- 更新后改 `.github/workflows/build.yml` 里固定的两个提交（`UNIXNU_REF`、`UEFI_REF`），让 CI 重新跑一遍。
- 改动了哪个子系统，就同步更新 `porting.toml` 里对应区域的发现或证据，并运行记录检查。

## 本地测试

```bash
cd drivers/FuxiFtsTouch && for t in fts-protocol touch-core; do gcc -std=c11 -Wall -Wextra -Werror -I. Test/$t.c FtsProtocol.c FtsTouchCore.c -o /tmp/$t && /tmp/$t; done
```

## 许可证

BSD-2-Clause-Patent，见 [LICENSE](LICENSE)。


## English

# unixnu-fuxi: UniXNU device repository for Xiaomi 13 (fuxi)

This repository contains the board-specific files, probes, boot hooks and hardware facts for Xiaomi 13 (fuxi, SM8550). The primary technical reference is [fuxi_touch_panel_porting.md](fuxi_touch_panel_porting.md); subsystem status is tracked in [porting.toml](porting.toml).

This is the owner's imported working copy. The native UFS root and full-system boot line lives on native-ufs-root; main is the imported baseline. Current handoffs: [Issue #2](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/2) (persistent Data closed, 2026-11-06) and [Issue #4](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/4) (Stage ② opened, SpringBoard exit diagnosis and display audit, 2026-11-07). The old ram-system-probe branch was archived as tag archive/ram-system-probe-2026-11-07; its five unique commits remain reachable from that tag. The project is in step 6 of the official eight-step device-porting path: storage is complete, touch is validated, and display is the current blocker.

## Current status

| Subsystem | Status |
|---|---|
| Touch (ST FTM5) | Driver and staged probes are implemented. Stage 3 passed on-device on 2026-11-02: power, clocks, pins and 12 MHz SPI worked; the controller returned its ready event and chip ID 36 40. Stage 4 passed in polling and interrupt modes, including press/move/release coordinates and two-finger tracking; it also worked with all eight cores running. The probe must vote for touch power through RPMh. ShengHidInput is integrated and verified: touch events are emitted as HID reports (68 groups in one run, all successful). One spontaneous reboot occurred in eight interrupt-enabled boots; its cause remains unknown. |
| Firmware and boot image | CI builds DEBUG firmware and fastboot-bootable images; only encrypted images are uploaded. On 2026-11-02 the bootloader accepted the image, firmware, UniXNU menu and DarwinBoot worked, and XNU reached bsd_init. The missing Sheng AMP patch and the panic-region address configuration were corrected. Firmware memory maps were corrected for 8 GB and 12 GB devices; the 12 GB device boots. See evidence/2026-11-02-first-boot.md. |
| Storage | Native UFS root is verified on-device. ShengUfs reads the SHNGROOT manifest from userdata and publishes read-only OS and SystemOS windows. The geometry was derived from the stock GPT; the root image was flashed on 2026-11-05 with the owner's one-time approval (Android /data was erased; rollback requires reflashing the stock ROM). APFS System mounting and owner trust authentication passed. chain46 reached launchd at LC_MAIN after the SystemOS union/cache mount was enabled. Temporary Data boot was converted from dense delivery (black-screen failures) to packed DBRDISK1 delivery; chain51 reproduced the CI result on-device. Persistent Data Phase A/B/C closed on 2026-11-06. The storage window starts at first_lba 0x57bd52 and uses a 213 GiB seed container. chain55 initialised and wrote the window; chain56 was correctly rejected because its newly generated CI seed had different bytes; chain57 resumed using the exact chain55 seed and proved cross-reboot persistence. Preserve the exact chain55 seed identity (SHA-256 prefix df83bf77); do not substitute a newly generated seed. The recovery-disk path also previously booted launchd, restored_external and mount_tmpfs. |
| CPU | On 2026-11-02, PSCI started all seven secondary cores with sheng-smp=1 and armcpu-spi-ipi=1; the scheduler saw eight cores. armcpu-self-ipi=1 was also required for working IPIs. Cores 1 and 2 have not shown timer interrupts. Removing armcpu-spi-ipi caused SGIs to stop working; one of nine multicore boots failed to start all secondary cores, cause unknown. |
| Userland and Stage ② (functional UI/display) | Skip Setup's functional goal was reached on-device on 2026-11-07: the device did not enter Setup and reached SpringBoard. The implementation intentionally uses a kernel writer (package/BootWatchdogPolicy.c) on persistent Data rather than the official payload --skip-setup seed-copy route; SetupDone's value has not been read directly and payload.json remains skip_setup: false. chain58 showed no graphical frames. chain59 proved only that the SetupDone key exists. chain60 observed 14 SpringBoard cycles ending in SIGTRAP. chain61 correlated all 16 exits with the same EL0 breakpoint at PC/LR 0x1a721f2ec, ESR 0xf2000000 (BRK #0). Host-side dyld-cache analysis located it in FrontBoardServices -[FBSDisplaySource initWithCADisplay:] +0x47c: main CADisplay lookup fails, logs failed to find the main CADisplay, then falls through to BRK #0. This is a deliberate assertion, not an external kill. Phase 2 exit-reason kcdata work was deferred after Phase 1 and symbol analysis answered the core question. |
| Display | Current step-6 blocker. Read-only audits found the first gap at the L2 display-provider layer. Firmware GOP and the kernel text console work; Apple IOMobileFramebuffer/IOSurface components are present in the prelinked kernel, but the GOP framebuffer is not published as an IOKit display provider. GopFramebuffer (pin 19ef3a75) is not selected by board.toml, fuxi_defconfig lacks CONFIG_XNU_NATIVE_LEGACY_DISPLAY, and no device builder or offline-legacy-* boot arguments are wired. The same-SoC sheng port has verified the component integration shape, but its panel details must not be copied: fuxi uses a Samsung DDIC AMOLED, DSI command mode with DSC, and DCS backlight control. Host-only experiment plan E1–E7 is prepared; device boots remain paused pending review. |
| USB diagnostics | QcomXnuUsbDebug is vendored under package/drivers/QcomXnuUsbDebug and built by scripts/build-fuxi-usb-debug.py. USB CDC logging was captured on usb1/chain60/chain61 (VID 0x1209, PID 0x316d). The remote reset integration remains disabled with QUD_CONTROL_REBOOT=0; do not enable the REBOOT verb. |
| GPU, networking and audio | Planned. Display and power hardware references have been collected. See the plan comment on Issue #1. |

## Related repositories

| Repository | Role |
|---|---|
| [OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) | UniXNU fork on branch fuxi; adds FuxiFtsTouch to the component catalog and the fuxi-specific bootimg options. |
| [OddlyLabs/uefi-fuxi](https://github.com/OddlyLabs/uefi-fuxi) | Firmware fork based on UniXNU/uefi-sheng, carrying nine fuxi commits from matejkoo217/uefi-fuxi with original authorship retained. |
| [OddlyLabs/FuxiFtsTouch](https://github.com/OddlyLabs/FuxiFtsTouch) | Pure-C FTM5 protocol and touch-tracking component with host tests; referenced as a submodule. |
| This repository | Board files, probes, boot-hook patches and hardware references. |

UniXNU provides the UniXNUPkg boot menu and DarwinBoot XNU loader as UEFI modules. They require board-specific UEFI firmware. This device uses official uefi-sheng plus the verified fuxi commits, keeping upstream changes separable from device-specific changes.

## Repository layout

| Path | Contents |
|---|---|
| board.toml, feeds.toml, configs/fuxi_defconfig | Board, component selection, archive order, SoC version and kernel configuration. |
| dts/fuxi.dts | Device tree, including sm8550.dtsi from UniXNU-sm8550-common. |
| patches/xnu/ | fuxi-touch-probe.patch; calls the touch probe from bsd_init. |
| package/ | Build-tree kit for fuxi: touch probe and board constants; selected PMGR bridge files are unchanged copies from UniXNU-sheng. |
| scripts/build-fuxi-touch.py | Uses XNU build records to compile the probe and driver into libFuxiTouch.a. |
| scripts/build-fuxi-platform-power.py, ci/check-pmgr-bridge.py | Build and verify the PMGR bridge contract with AMFI. |
| scripts/build-fuxi-data-seed.py, scripts/pack-fuxi-data-seed.py, scripts/grow-fuxi-data-seed.py | Create the APFS Data seed, pack it as DBRDISK1 and grow the persistent container. |
| scripts/build-fuxi-usb-debug.py, package/drivers/QcomXnuUsbDebug/ | Vendored USB diagnostic module and wrapper; reset is compiled out. |
| drivers/FuxiFtsTouch | FuxiFtsTouch submodule. |
| porting.toml | UniXNU-format porting record. |
| tests/board_test.c | Board-constant tests. |
| ci/boot-image-recipient.pem, ci/decrypt-boot-image.sh, ci/check-boot-image.py | Boot-image encryption public key, local decryption helper and pre-boot image checker. |
| facts/ | Touch/panel facts extracted from the stock device tree, including 73 DSI command groups. |

Local dtb/, firmware/, power/ and ref_src/ directories are ignored by Git. They contain vendor files, diagnostic references or GPL reference source for inspection only.

## Build

The reference build environment is macOS with Xcode 26; UniXNU also supports Linux toolchains. Clone the device repository and the two fuxi forks side by side:

```bash
git clone --recurse-submodules https://github.com/OddlyLabs/unixnu-fuxi
git clone -b fuxi https://github.com/OddlyLabs/UniXNU
git clone -b fuxi https://github.com/OddlyLabs/uefi-fuxi
```

From the UniXNU directory:

```bash
./unixnu defconfig fuxi_defconfig -D ../unixnu-fuxi
./unixnu build kernel
./unixnu build payload --uefi ../uefi-fuxi --unique-chip-id 0x0123456789abcdef
./unixnu build firmware --uefi ../uefi-fuxi --target DEBUG
./unixnu bootimg --uefi ../uefi-fuxi --target DEBUG --dtb ../uefi-fuxi/Platforms/Xiaomi/fuxiPkg/FdtBlob/sm8550-xiaomi-fuxi.dtb
```

The sample unique-chip-id is a fixed test value, also used in CI bring-up images. A full-system verification image is assembled locally with the device's actual ID; the real ID must never enter the repository. Firmware-only builds do not require Apple files and can run on Linux; in addition to clang/lld/LLVM tools, BaseTools requires uuid-dev. The commands above passed on Ubuntu 26.04 under WSL with clang 21.1.8 on 2026-11-01; the firmware volume was 0x300000 bytes.

## CI (GitHub Actions)

| Job | Environment | Checks |
|---|---|---|
| Host tests | Ubuntu | FuxiFtsTouch tests with gcc/clang and ASan/UBSan, board constants and script syntax. |
| Kernel-target compile | macOS 26 + Xcode | Compiles driver C as arm64 kernel code and checks that it does not call libc. |
| fuxi boot image | macOS 26 + Xcode | Builds XNU through archive/link/prelink, checks the touch probe and bsd_init call, then builds payload, firmware and boot image; encrypted image is uploaded. |
| Porting record | Ubuntu | Runs the fork's UniXNU checker against porting.toml. |

The boot image contains Apple kernelcache material, so only the version encrypted with ci/boot-image-recipient.pem is uploaded. The private key stays on the owner's computer; other artifacts are text logs only.

## Device boot

Use fastboot boot only; do not write partitions.

1. Download the encrypted fuxi-boot-image artifact and decrypt it locally with bash ci/decrypt-boot-image.sh <private-key> <artifact-directory>.
2. Run python3 ci/check-boot-image.py <artifact-directory>/boot.img <artifact-directory>/boot.json ../uefi-fuxi. Continue only when all image/header, load-offset, firmware-volume, payload, ADT and boot-argument checks report ok.
3. Put the phone in fastboot mode and run fastboot boot boot.img.
4. The default bring-up image reaches touch stage 4 and reports touch events as HID; the screen stops at the touch report page. Full-system images are assembled locally with the decrypted artifacts and the phone's actual chip ID, still using fastboot boot only. SYS lines and initproc failure reasons are the stage diagnostics.
5. Reboot to Android. Because userdata was repurposed, Android /data is no longer available; see the storage status and rollback warning above.

### Entry-probe images for early XNU diagnosis

Before the XNU console is available, the top-of-screen colour bar is the visible signal: green means DarwinBoot handed off control, blue means the kernel was entered, and magenta means the MMU is about to be enabled. Later checkpoints can be tested with an entry probe that waits briefly and reboots. If the phone reboots, execution reached the probe; if it remains at the colour bar, it stopped earlier.

Follow the Entry probe reset section of the UniXNU debugging guide. CI builds the kernel; payload and boot image can be generated locally without a Mac:

1. Decrypt the artifact; alongside boot.img, obtain the unpatched kernel.macho.
2. Export the exact tested firmware volume: python3 ci/check-boot-image.py boot.img boot.json ../uefi-fuxi --fd-out fd.bin.
3. In a temporary device-repository copy, add entry_probe_reset_delay = 6 under board.toml [payload] (reboot after MMU enable), optionally with entry_probe_reset_after = "_arm_vm_init". Do not commit these probe settings.
4. Build the payload and image from the UniXNU directory, pointing -D to the temporary copy:

```bash
./unixnu build payload -D <temporary-copy> --uefi ../uefi-fuxi --kernel <kernel.macho> --unique-chip-id 0x0123456789abcdef
./unixnu bootimg -D <temporary-copy> --uefi ../uefi-fuxi --fd <fd.bin> --dtb ../uefi-fuxi/Platforms/Xiaomi/fuxiPkg/FdtBlob/sm8550-xiaomi-fuxi.dtb -o probe.img
```

Linux requires clang, lld, LLVM tools, dtc and mtools. Boot the probe with fastboot boot. A delayed probe needs no photo: an automatic reboot proves that execution reached the configured checkpoint.

## Maintenance

- Merge UniXNU/UniXNU main into OddlyLabs/UniXNU fuxi; merge UniXNU/uefi-sheng sheng into OddlyLabs/uefi-fuxi fuxi.
- Update the pinned UNIXNU_REF and UEFI_REF commits in .github/workflows/build.yml and rerun CI.
- For every subsystem change, update the corresponding finding/evidence in porting.toml and run the record checker.

## Local tests

```bash
cd drivers/FuxiFtsTouch && for t in fts-protocol touch-core; do gcc -std=c11 -Wall -Wextra -Werror -I. Test/$t.c FtsProtocol.c FtsTouchCore.c -o /tmp/$t && /tmp/$t; done
```

## License

BSD-2-Clause-Patent; see [LICENSE](LICENSE).


**语言 / Language：** [中文版](#中文版) | [English](#english)

## 中文版

## 快速 bring-up 与证据驱动迭代政策

本项目优先抵达下一个可验证启动里程碑，而不是先完成所有子系统。采用 OnePlus 13T 移植中验证有效的节奏：固定已知良好基线、每轮只改变一个阻塞变量、让失败可观测，并尽快产出可测试候选。

1. **冻结基线：** 按精确 revision/hash 复用已验证的内核输入、固件、ADT、trust cache、Data seed 与打包配置；无证据不得重开已通过阶段。
2. **明确里程碑：** `launchd` 正在运行是 userland 硬指标；随后验证 Data/services，再推进 SpringBoard/display。无关 GPU、Wi-Fi、音频和外设不得阻塞更早里程碑。
3. **先诊断：** 找到最早未验证的启动转换点，采集 checkpoint、返回码、symbol/PC、寄存器、mount/UUID 或服务退出原因。优先使用可持久化或屏幕可见的诊断，并区分文档事实、主机验证、真机观察与假设。
4. **单点修复：** 每轮只处理一个根因/一个变量；用聚焦回归复现旧故障并验证修复。若破坏已知良好阶段，回退该改动，不叠加 workaround。
5. **最短完整闭环：** 主机回归 → 精确 ABI/type 检查 → 真 ARM64 编译/链接 → 构件与输入配对/readback → 唯一标识候选镜像 → 经所有者明确要求后临时启动。
6. **设备安全：** 设备验证只用 `fastboot boot`；任何刷写或分区写入都必须另行取得明确批准。
7. **CI 可诊断：** 成功与失败都保留完整日志和 build report；构建失败后仍收集 status/report，避免 shell `errexit` 隐藏证据或因文件过大漏收日志。
8. **到点停止：** 确认 `launchd` 后不无故重查内核；到达 SpringBoard 后只隔离显示/用户空间问题，不重开已完成的存储、trust、启动链。
9. **证据分级：** 文档事实、主机测试、构建/链接、构件 readback、真机观察分开报告。文件生成、主机测试通过、bootloader 接受或 workflow summary 都不能证明后续阶段成功。
10. **每轮闭环记录：** 记录改动变量、源码 revision、命令、测试结果、镜像/输入身份与 hash、最后确认阶段、真机观察和唯一下一阻塞点；README 与 porting.toml 只写有证据的状态。

### 当前应用

- 冻结已完成的 archive/build gates；除非新错误直接指向它们，否则不重复 archive-01～18、ABI 审计或 setup。
- 对链接/运行时错误，先核对真实声明、relocation/binding 和最终构件。源码空指针检查不能消除非法链接 relocation。
- 不按预期路径或 workflow 摘要推断成功，必须读取并核验真实 artifact/log。
- 当前阶段先查 UniXNU 官方文档；没有文档依据的部分标为假设，不猜测。
- 未经 GitHub/CI/设备 readback，不得宣称修改、构建或启动成功。

## English

## Fast bring-up and evidence-driven iteration policy

The project prioritises the next verifiable boot milestone over completing every subsystem. Follow the proven OnePlus 13T cadence: freeze the known-good baseline, change one blocking variable per iteration, make failures observable, and produce a testable candidate quickly.

1. **Freeze the baseline:** Reuse verified kernel inputs, firmware, ADT, trust cache, Data seed and packaging by exact revision/hash. Do not reopen passed stages without evidence.
2. **Name the milestone:** `launchd` running is the hard userland signal; then verify Data/services, followed by SpringBoard/display. Unrelated GPU, Wi-Fi, audio and peripherals must not block an earlier milestone.
3. **Diagnose first:** Find the earliest unverified boot transition and capture checkpoints, return codes, symbols/PCs, registers, mount/UUID or service exit reasons. Prefer persistent or screen-visible diagnostics. Separate documented facts, host verification, device observations and hypotheses.
4. **Fix one thing:** One root cause/one variable per iteration. Use a focused regression to reproduce the old failure and prove the fix. Revert a change that regresses a known-good milestone; do not stack workarounds.
5. **Shortest complete loop:** Host regression → exact ABI/type checks → real ARM64 compile/link → artifact and input pairing/readback → uniquely identified candidate → temporary boot only after an explicit owner request.
6. **Device safety:** Device validation uses `fastboot boot` only. Any flashing or partition write requires separate explicit approval.
7. **Diagnosable CI:** Preserve full logs and build reports on success and failure. Collect status/report after failed builds; do not let shell `errexit` hide evidence or omit oversized logs.
8. **Stop at the milestone:** After `launchd` is confirmed, do not revisit kernel bring-up without new evidence. After SpringBoard is reached, isolate display/user-space issues without reopening completed storage, trust or boot-chain work.
9. **Evidence levels:** Report documentation, host tests, build/link, artifact readback and device observations separately. A generated file, passing host test, bootloader acceptance or workflow summary does not prove a later stage.
10. **Repository closure:** Record the changed variable, source revisions, commands, results, image/input identities and hashes, last confirmed stage, device observation and one next blocker. Update README and porting.toml only with evidence-backed status.

### Current application

- Freeze completed archive/build gates; do not repeat archive-01 through archive-18, ABI audits or setup unless new evidence points to them.
- For linker/runtime failures, inspect the real declaration, relocation/binding and final artifact. A source null check does not neutralise an invalid linker relocation.
- Verify actual artifacts/logs; never infer success from expected paths or workflow summaries.
- Read the official UniXNU documentation for the current stage and label undocumented behavior as a hypothesis.
- Never claim an edit, build or boot succeeded without GitHub/CI/device readback.


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

## 2026-11-10 当前进展

[English progress](#2026-11-10-current-progress) · [完整 handoff](handoff.md) · [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

- **最后已知全绿基线是 Build #143 / `827f289e`。** Build 与 Device documentation 均通过；加密真机候选产物为 `fuxi-boot-image-encrypted-1`。Actions：<https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/runs/42700730291>。
- #143 已越过 Turnip iOS、Adreno Metal bridge、userspace addon、payload 与 boot image 构建。#142 的 arm64 unused `patchFramebufferBranch` 已通过把 iPadOS 27 helper 限制到 `__arm64e__` 修复，保留 `-Werror`。
- 后续无人值守迁移 `6733bad0`（#144）和 `06fbd3c8`（#145）尚未形成新基线。#145 当前明确失败点：Host contract 要求的 `sheng-log=1` 缺失；Device documentation 要求 `board.toml` 改动同步 `porting.toml` 的 configuration finding/evidence。boot image job 因前置失败被跳过。
- **后续参考顺序固定：Xiaomi 13 V2 同机成功实现 → 本仓库/CPU Legacy 差异 → UniXNU 上游与官方 UnixNu 文档 → 最小 CI/运行时修复。** 不再先照官方文档另起一条路线。
- 保留 `native-ufs-root` 与 `cpu-legacy-display` 两条分支。后者有 23 个独有提交；禁止整分支 merge，只审计并选择性移植与锁屏直接相关、当前线尚缺失的显示/FBS/GPU handoff 改动。
- “slot 345”只表示 Legacy 显示接口中的“主屏显示时序是否准备好”查询；它不是绘图功能，也不代表 GPU 已经工作。
- 设备安全规则不变：自动化只处理 GitHub/CI；不自动刷机、不自动重启真机。新候选必须全绿后再交给机主用 `fastboot boot` 临时验证。

## 2026-11-10 Current progress

[中文进展](#2026-11-10-当前进展) · [Full handoff](handoff.md) · [Issue #7](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/issues/7)

- **The last known all-green baseline is Build #143 / `827f289e`.** Build and Device documentation both passed; the encrypted device candidate is `fuxi-boot-image-encrypted-1`. Actions: <https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/runs/42700730291>.
- #143 cleared the Turnip iOS, native Adreno Metal bridge, userspace addon, payload and boot-image path. The #142 arm64 unused `patchFramebufferBranch` issue was fixed by restricting the iPadOS 27 helper to `__arm64e__` while keeping `-Werror`.
- Later unattended migration commits `6733bad0` (#144) and `06fbd3c8` (#145) are not new known-good baselines. #145 currently fails because the host contract still requires `sheng-log=1`, and the Device documentation check requires the `board.toml` change to be reflected in the matching `porting.toml` configuration finding/evidence. The boot-image job was skipped.
- **Required reference order: proven Xiaomi 13 V2 path → local/CPU Legacy diff → upstream UniXNU and official UnixNu docs → smallest CI/runtime fix.** Do not start a fresh documentation-only route before comparing the same-device V2 success path.
- Keep both `native-ufs-root` and `cpu-legacy-display`. The latter has 23 unique commits; do not merge it wholesale. Audit and selectively migrate only missing, lock-screen-critical display/FBS/GPU-handoff work.
- “slot 345” is only the Legacy display query for whether primary-display timing is ready. It does not render frames and does not prove GPU functionality.
- Automation may modify GitHub/CI only. Never flash or reboot the physical device automatically; a new device candidate must be fully green before the owner tests it with temporary `fastboot boot`.
