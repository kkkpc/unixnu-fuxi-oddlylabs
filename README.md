# unixnu-fuxi：小米 13（fuxi）的 UniXNU 设备仓库

[![Build](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/build.yml/badge.svg)](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/build.yml)
[![Device documentation](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/porting-record.yml/badge.svg)](https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/workflows/porting-record.yml)

Device repository for the Xiaomi 13 (fuxi, SM8550), created from UniXNU's `examples/device` template. It builds with the
fork [OddlyLabs/UniXNU](https://github.com/OddlyLabs/UniXNU) (branch `fuxi`), whose component catalog has
`FuxiFtsTouch`.

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

## Fast bring-up and iteration policy

The project optimises for the next verified boot milestone, not for completing every subsystem. Use the OnePlus 13T port's demonstrated workflow: preserve a known-good baseline, change one blocking variable at a time, make failures observable, and return a new testable image quickly.

1. **Keep the baseline immutable.** Reuse already-verified kernel inputs, firmware, ADT, trust cache, Data seed and packaging wherever compatible. Record exact commit/revision and hashes. Do not rebuild or reopen passed stages without evidence that the current failure implicates them.
2. **Work backwards from the next user-visible milestone.** The first hard userland milestone is `launchd` running; then verify Data/services; then SpringBoard/display. Do not block userland validation on Wi-Fi, audio, GPU acceleration or unrelated peripherals. State the exact acceptance signal for each milestone.
3. **Diagnose before changing code.** Identify the earliest unverified transition and capture the smallest decisive evidence (checkpoint, return code, symbol/PC, register, mount/UUID, service exit reason). Prefer persistent or screen-visible diagnostics that survive the next reboot. Distinguish documented facts, host-verified facts, device observations and hypotheses.
4. **One root cause / one controlled change per iteration.** Reproduce the old failure in a focused host regression where practical, prove the corrected case, and avoid bundling speculative cleanups. If a candidate regresses a known-good milestone, revert that change rather than layering workarounds on top.
5. **Use the shortest complete validation loop.** Run focused host tests → exact ABI/type checks → real ARM64 compile/link → artifact and input-pairing/readback checks → produce a uniquely identified candidate → obtain owner approval before any device boot. Device tests use temporary boot only; never flash or write partitions without separate explicit approval.
6. **Make every CI run useful.** Preserve full build logs and reports, including failure paths. Collect status/report artifacts even when the main build command fails; do not let shell `errexit` hide post-failure diagnostics. Keep artifact collection limits from silently excluding large logs.
7. **Stop when the milestone is reached.** Once `launchd` is confirmed, do not keep debugging kernel bring-up unless new evidence requires it. Once SpringBoard is reached, isolate display/user-space issues without reopening completed storage, trust or boot-chain work.
8. **Close the loop in the repository.** For each iteration record the changed variable, source revision, commands, test results, exact image/input identities, last confirmed boot stage, device observation and next single blocker. Update the affected porting-record area and README only with evidence-backed status.

### Current execution discipline

- The current project objective is the shortest evidence-backed path to a real userland/UI milestone, not broad driver completeness.
- Keep completed archive/build gates frozen. Do not repeat successful archive gates, ABI audits or setup work unless a new error points directly to them.
- For a linker or runtime failure, inspect the exact declaration, generated relocation/binding and linked artifact before proposing a source-level workaround. A source null check does not make an invalid relocation safe.
- Never infer success from a generated file's expected path or a workflow summary. Fetch the actual artifact/log and verify it.
- Follow the official UniXNU documentation for the current stage before relying on assumptions; explicitly label anything the docs do not specify.
- Do not claim a build, boot, code change or device result until the corresponding GitHub/CI/device evidence has been read back and verified.
