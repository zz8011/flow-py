# 任务：把 flow-py 剩余功能移植到 flow.google.com 新站

你在 devbox 上，工作目录就是这个仓库（~/Projects/flow-py）。这是一个已打过补丁的
flow-py 副本：原版（labs.google 时代）已于 2026-11-18 被修补到 flow.google.com，
**先通读仓库根目录的 PATCH.md**，里面有新站协议（batchexecute RPC 字典、官方价）、
已移植范围、安全闸设计和踩过的坑。不读完不要动手。

## 已完成（不要重做）

- RPC 层 flow/_rpc.py：积分、项目列表、模型配置（官方价）、项目媒体列表、as29s 现签下载 URL
- CLI：login / credits / models / projects / status / workflows / poll / download 全通
- generate_video（文生视频）与 generate_image：走项目页创作智能体面板
  （flow/_flow_ui.py 的 AgentUI + flow/_client.py），确认卡先核价后批准，已实测扣分准确

## 你的任务：完成剩余移植

1. **编辑类操作**：flow/_client.py 里 extend_video / extend_loop / camera_motion /
   camera_position / insert_object / remove_object / upscale_video 目前显式抛
   「not ported」错，flow/_api.py 的直连路已死。先在新站实地探索这些能力现在的形态
   （大概率是：媒体查看/编辑界面，或在智能体对话里引用某个媒体让 agent 改），
   然后逐个实现 + 实测。CLI 侧已有 extend / camera / insert / remove / upscale 命令
   （flow/cli/main.py），保持它们的签名可用。
2. **图生视频 I2V**：FlowClient.generate_video(start_image=...) 目前抛错。
   探索把图片附到智能体对话里让它动起来的路径（模型配置里有 macaron_cookie_i2v_10s
   等变体），实现并实测。
3. **--model / --aspect 真正生效**：现在只是签名兼容的摆设，实际由项目 agent 的
   已存设置决定。探索 agent 设置面板（tune 图标）能否被驱动，或在提示词里明确
   指令是否有效；选可行路径实现，让 CLI 的 video / image 命令的模型与画幅参数
   真实影响产出，文档里写清机制与边界。

## 测试环境（现成，别重建）

- 沙盒 venv：/home/zz8011/tools/flow-py-trial/venv；改完代码后装回：
  `/home/zz8011/tools/flow-py-trial/venv/bin/pip install --force-reinstall --no-deps /home/zz8011/Projects/flow-py`
  （必须用绝对路径；注意把 HOME 设成沙盒后 ~ 会指错地方）
- 跑 CLI 时：`export HOME=/home/zz8011/tools/flow-py-trial/home DISPLAY=:99`
  （沙盒 profile 里有 zeedzh 的有效登录会话；Xvfb :99 已在跑，没有就
  `Xvfb :99 -screen 0 1440x900x24 &` 拉起来）
- 试验项目：d22a3a7b-7006-48a2-9ee3-fcb5b9974e21（`flow use` 已设为活跃项目）
  现成测试媒体：视频 b88af6e0-76fe-4a66-a173-ce32192f0e57、
  3cface19-9e0e-47dd-9ac5-405c790fed70；图片 0d362518-9017-4f04-a2fa-cd06e21d7753、
  2a5ab672-e11c-43d9-bb0a-121d93b15d6e
- 账号 zeedzh（ULTRA），积分约 24,860

## 硬纪律（违反即停）

- **先核价后批准**：任何确认卡，报价必须命中 HTrJv 官方价才准点批准；
  generate_video 里的 verify() 就是范式，复用它。核不上就放弃并记录。
- **花销上限**：全程付费实测总共不超过约 6 次生成、总扣分不超过 200；
  能选便宜变体（360p / 最短时长）就选便宜的。每次实测在 PORTING-LOG.md
  （仓库根目录，你新建）里记一行：功能、提示词/操作、报价、余额前后。
- 图片生成本档免费，可以多试。
- 禁用 --cdp；不许碰用户日常 Chrome 和它的 profile，只用沙盒 profile。
- 某个功能在新站确实不存在/做不到时，拿证据（截图或 DOM/RPC 记录）在
  PORTING-LOG.md 里写明「不可移植 + 原因」，代码里保留显式报错，不要假装实现。
- 批准点击必须真实输入点击，DOM 合成 click 无效；dimmed 的卡是死卡（见 PATCH.md）。

## 交付

- 代码改在本仓库；先把当前未提交的补丁状态提交一笔
  （message: `patch: flow.google.com support (RPC + agent UI)`），
  之后每个功能一笔提交，message 写清功能名。
- 更新 PATCH.md 的「已知限制 / 未移植」一节，或新建 PORTING-RESULTS.md，
  写明每个功能：移植结论、实现机制、实测证据（扣分/产物文件）。
- 仓库 tests/ 里有测试，能跑的跑一遍，别弄挂已通的功能
  （credits / models / video / image 最后要各复验一次）。
