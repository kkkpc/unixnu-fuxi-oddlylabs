# 交接 / Handoff — 2026-11-10

**语言 / Language：** [中文](#中文) | [English](#english)

## 中文

### 当前基线

- 当前工作分支：`native-ufs-root`。
- **最后已知全绿构建：Build #143**，提交 `827f289e912776d1a49deac849406d95ddcf1869`。Build 与 Device documentation 均通过。
- #143 产物：`fuxi-boot-image-encrypted-1`（artifact id `13713918999`），Actions run：<https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/runs/42700730291>。
- #143 的 GPU userspace 链已经越过 Turnip iOS build、Adreno Metal bridge、addon、payload 与 boot image 构建；此前 #142 的 `patchFramebufferBranch` arm64 unused-function 问题通过只在 `__arm64e__` 编译该 iPadOS 27 helper 修复，没有关闭 `-Werror`。
- 后续无人值守迁移产生 `6733bad0`（#144）与 `06fbd3c8`（#145）。它们**不是新的已知良好基线**：
  - #144：Host tests / Scripts 失败。
  - #145：Host tests 报 `required boot argument is missing or changed: sheng-log=1`；Device documentation 同时报 `board.toml: update configuration findings or evidence with this change`。boot image job 因前置失败被跳过。
- 因此，在新的 CI 全绿以前，**回退判断与真机候选以 #143 / 827f289e 为准**。

### Xiaomi 13 V2 优先级

同机成功参考 `ljhhkx529/unixnu-fuxi` V2 已由机主真机确认可到锁屏且触控正常。后续 bring-up 顺序固定为：

1. 先对照 Xiaomi 13 V2 的已成功机制和参数；
2. 再审计本仓库的当前实现与 `cpu-legacy-display`；
3. 再用 UniXNU 上游与官方 UnixNu 文档校验接口、构建与阶段要求；
4. 最后才针对 CI/运行时单点做最小修复。

不得把“照官方文档搭出一条新路线”放在同机 V2 成功路径之前。

### 两条分支策略

保留：
- `native-ufs-root`：当前 GPU/userspace/完整系统工作线。
- `cpu-legacy-display`：旧的 Legacy display/FBS 单变量实验线。

两分支已分叉；`cpu-legacy-display` 相对当前线有 23 个独有提交。**禁止整分支 merge。** 逐项审计并只移植缺失、与锁屏直接相关且有证据的改动。

优先审计项：
- Legacy GOP/display provider 注册与 21H461 ABI 派生；
- 18 个 display callback 的 C linkage 修复；
- `native_adreno_fences` 的真实 board binding；
- `sheng-vsync=120` 单变量实验；
- display scale/rotation 在 `/chosen` 的发布；
- SpringBoard/FrontBoardServices 能否获得 main `CADisplay`；
- 已被当前线等效实现的项目只记录“已覆盖”，不重复 cherry-pick。

### “slot 345”用人话说明

这是 Legacy 显示接口表里的一个固定位置，系统会通过它询问：**“主屏的显示时序现在可用了吗？”**

当前实现只有在“主屏 + 启动 framebuffer 已映射 + 显示逻辑电源有效”时回答 yes。它不负责画图，也不等于 GPU 已工作；它只是显示初始化链中的一个“是否准备好”查询。修好它可以避免系统拿到错误的显示状态，但单独修好它不能保证出现锁屏。

### 无人值守规则

- #143 已全绿，所以它是可下载/可真机验证的稳定候选；任何后续迁移若失败，不覆盖这个事实。
- 后续失败：读取具体 job/step/log → 先查 V2 → 再查上游/官方文档 → 做最小修复 → push → 新 Build。
- 不允许通过关闭关键 warning、伪造 display、屏蔽 SpringBoard BRK、整体 merge 分支来换取绿色。
- 不自动刷机、不自动重启物理设备。
- 本轮累计 5 次有效 push 后，更新本 handoff/README/AGENTS，并列出 SHA、根因、参考来源、修改文件与 CI 结果。

### 当前下一步

1. 修复 #145 的 boot-contract 与 porting-record 一致性，恢复全绿；
2. 保持 #143 为 rollback/真机候选基线；
3. 继续完成 23 个 `cpu-legacy-display` 独有提交审计；
4. 只把锁屏所需且当前线缺失的改动移入 `native-ufs-root`；
5. 新 Build 全绿后再生成新的真机候选。

---

## English

### Current baseline

- Active branch: `native-ufs-root`.
- **Last known all-green build: Build #143**, commit `827f289e912776d1a49deac849406d95ddcf1869`. Both Build and Device documentation passed.
- #143 artifact: `fuxi-boot-image-encrypted-1` (artifact id `13713918999`), Actions run: <https://github.com/kkkpc/unixnu-fuxi-oddlylabs/actions/runs/42700730291>.
- #143 cleared the Turnip iOS build, native Adreno Metal bridge, addon, payload and boot-image path. The #142 arm64 unused `patchFramebufferBranch` failure was fixed by compiling that iPadOS 27 helper only for `__arm64e__`, without disabling `-Werror`.
- Later unattended migration commits `6733bad0` (#144) and `06fbd3c8` (#145) are **not** new known-good baselines:
  - #144 failed Host tests / Scripts.
  - #145 reports `required boot argument is missing or changed: sheng-log=1`; Device documentation also requires a matching `porting.toml` configuration finding/evidence update. The boot-image job was skipped.
- Until a newer build is fully green, **#143 / 827f289e remains the rollback and device-test baseline**.

### Xiaomi 13 V2 comes first

The same-device reference `ljhhkx529/unixnu-fuxi` V2 has been device-verified by the owner to reach the lock screen with working touch. The required order is now:

1. compare the proven Xiaomi 13 V2 mechanism first;
2. audit this repository and `cpu-legacy-display`;
3. validate interfaces/build/stage rules against upstream UniXNU and official UnixNu documentation;
4. only then apply the smallest CI/runtime-specific fix.

Do not invent a fresh official-doc-only path before checking the same-device V2 success path.

### Two-branch policy

Keep both `native-ufs-root` and `cpu-legacy-display`. The branches have diverged, and `cpu-legacy-display` has 23 unique commits relative to the current line. **Do not merge the branch wholesale.** Audit each commit and migrate only missing, evidence-backed changes that directly affect the lock-screen path.

Priority review: Legacy GOP/display provider registration and 21H461 ABI derivation; the 18 display callback C-linkage fix; real board binding for `native_adreno_fences`; the `sheng-vsync=120` experiment; display scale/rotation publication under `/chosen`; and whether SpringBoard/FrontBoardServices can obtain the main `CADisplay`.

### Slot 345 in plain language

It is one fixed entry in the Legacy display interface table. The system uses it to ask: **“is the primary display timing ready now?”** The current implementation answers yes only when the primary display, boot framebuffer mapping and logical display power are all valid. It does not render frames and does not prove the GPU works.

### Unattended rules

- Preserve #143 as the known-good candidate while later migration work is failing.
- On failure: read the exact job/step/log → check V2 first → check upstream/official docs → make a minimal fix → push → rebuild.
- Do not disable meaningful warnings, fake display state, suppress the SpringBoard BRK, or merge branches wholesale to get green CI.
- Never flash or reboot the physical device automatically.
- After five effective pushes in this round, update the handoff/README/AGENTS with SHA, root cause, reference source, files changed and CI result.

### Next

1. restore CI consistency after #145;
2. keep #143 as the rollback/device-test baseline;
3. finish the 23-commit `cpu-legacy-display` audit;
4. selectively migrate only missing lock-screen-critical changes;
5. produce a new device candidate only after the new Build is fully green.
