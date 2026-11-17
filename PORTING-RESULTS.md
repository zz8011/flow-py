# flow-py 二期移植说明（编辑类操作、I2V、多参考图、模型/画幅控制）

- 日期：2026-11-18
- 仓库：`/home/zz8011/Projects/flow-py`（同步至 `~/tools/flow-py-patched` 与 `~/workspace/flow-py-trial/src-patched/`）
- 测试项目：`d22a3a7b-7006-48a2-9ee3-fcb5b9974e21`（ULTRA 订阅档位）
- 积分总账：起始 **24,860** → 结束 **24,816**，10 项端到端 CLI 验收合计消耗 **44 积分**（远低于 200/300 上限），每笔确认卡报价、官方价目表（`HTrJv` tier=3）与实际扣费 100% 分毫不差。

---

## 1. 安全闸加固（修复一期 3 处隐患）

1. **`HTrJv` 价目表档位修正（`flow/_rpc.py`）**：
   - `nzlxg` 积分接口返回 `[balance, 2, 3, 3, null, balance, [reset_ts, ns]]`，ULTRA 账号在 `HTrJv` 对应的价格档位列在 `data[2]`（=3），而非 `data[1]`（=2）。
   - 例如 `Veo 3.1 - Fast` 8s 在第 2 档为 20 点、第 3 档（`veo_3_1_t2v_fast_ultra`）为 **10 点**；`Veo 3.1 - Lite` 在第 2 档为 10 点、第 3 档为 **5 点**。
   - 同时解析 `macaron_cookie_edit` / `macaron_cookie_edit_360p` 在 `variant[25][0]` 中的按时长/分辨率矩阵价目（消除 `variant[4]` 占位 `0` 带来的误判风险）。
2. **确认卡文本抓取范围收紧（`flow/_flow_ui.py` `_CARD_TEXT`）**：
   - 改为从当前未置灰的「批准」按钮向上定位 `closest('.agent-row, flow-chat-bubble, .agent-bubble, .agent-message-content')`，严禁越过 `.messages-list` 混入用户提示词或历史回合旧卡片。
3. **「生成前先确认：始终」前置校验（`flow/_flow_ui.py` `_ensure_confirm_always`）**：
   - 每个项目首次开启会话时自动检查智能体设置（`tune` 按钮），确保单选框处于「始终（生成前征求确认）」，防止被设为「永不」时跳过确认卡直接扣分；同时付费回合强制 `require_card=True`，无卡绝不静默放行。
4. **`as29s` 签名 URL 就绪判定（`flow/_api.py`、`flow/_client.py`）**：
   - 点击「批准」后，`Zzl0ze` 会立即出现一条尚在渲染中的媒体占位记录，此时 `as29s` 返回空串。`_wait_new_media` 与 `poll_video` 均改为必须等到 `as29s` 现签出非空 `flow-content.google` URL 后才判为 `COMPLETE`。

---

## 2. 各操作移植方式、指令模板与边界

### 2.1 素材挂载与本地上传（`AgentUI.attach_media` / `upload_media`）
- **项目已有媒体**：点击提示框 `+`（`button[aria-label='在提示框中添加素材']`）打开选择器。由于新站选择器按 `workflow_id` 聚合（同一 workflow 经过 extend/edit 后行缩略图会更新为最新版本海报），`attach_media` 聚合目标 `workflow_id` 下全部 `media_id` 与 `/asb/` 海报 token 进行匹配；若首行默认处于 `asset-item-active` 选中态则直接点右侧 `button.detail-add-to-prompt-btn`（「添加到提示」），避免二次点击反选。挂载后强校验 `<flow-ingredient-chip>` 内 `img[src]` 命中目标 UUID 或海报 token。
- **本地图片/视频文件**：通过选择器「上传媒体」触发 `expect_file_chooser`，上传后轮询 `Zzl0ze` 检出新 `media_id`，再复用 `attach_media` 挂上并校验 chip。

### 2.2 图生视频 I2V（`flow video --start` / `flow frames`）与多参考图（`-r`）
- **移植方式**：挂载首帧图片（项目 `media_id` 或本地图片路径）及可选参考图后，向智能体发送显式首帧生成指令。
- **指令模板**：
  - 首帧 I2V：`用这张图片作为首帧生成一段视频：{prompt}。使用 {model_display} 模型，{aspect_label}，时长 3 秒，分辨率 360p`
  - 多参考图 R2V：`参考所附图片生成一段视频：{prompt}。使用 {model_display} 模型，{aspect_label}`

### 2.3 `--model` 与 `--aspect` 参数生效（`flow video` / `flow image`）
- **移植方式**：无需持久化污染项目的默认设置，直接在智能体提示词末尾附加模型家族官方显示名（`Veo 3.1 - Lite`、`Veo 3.1 - Fast`、`Veo 3.1 - Quality`、`Omni 1.2 Flash`、`Omni 1.1 Flash`）与画幅指令（`16:9 横屏` / `9:16 竖屏` / `1:1 方形`）。实测智能体在确认卡中明确回应「由于您的默认视频模型设置是 Omni 1.2 Flash，这次我将使用您指定的 Veo 3.1 - Lite 模型」，产出分辨率严格对应目标画幅。

### 2.4 视频延长（`flow extend` / `flow extend-loop`）
- **移植方式**：挂载目标视频 chip，由 `Omni 1.2 Flash` 执行延续镜头生成（默认延长 3 秒、360p，若提示词中指定秒数则按指定秒数核价）。`extend-loop` 顺序串联每次延长后的新 `media_id`。
- **指令模板**：`使用 Omni 1.2 Flash 模型把这个视频延长 {ext_dur} 秒：{prompt}，分辨率 360p。`

### 2.5 镜头运镜与机位调整（`flow camera` / `flow camera-pos`）
- **移植方式**：挂载目标视频 chip，将 `CAMERA_MOTIONS`（`dolly_in`、`dolly_out`、`orbit_left`、`orbit_right`、`orbit_up`、`orbit_low`、`dolly_zoom_in`、`dolly_zoom_out`）与 `CAMERA_POSITIONS`（`center`、`left`、`right`、`high`、`low`、`closer`、`further`）映射为中英双语运镜/机位指令，交由 `Omni 1.2 Flash` 视频编辑模型重拍，按源视频所属 workflow 时长核验官方价。
- **指令模板**：
  - `camera`：`使用 Omni 1.2 Flash 模型给这个视频重新运镜：{desc}，画面主体内容保持不变，分辨率 360p。`
  - `camera-pos`：`使用 Omni 1.2 Flash 模型调整这个视频的机位：把摄像机位置调整为{desc}，画面主体内容保持不变，分辨率 360p。`

### 2.6 视频插入物体与移除物体（`flow insert` / `flow remove`）
- **移植方式**：
  - `insert`：挂载目标视频 chip，使用 `Omni 1.2 Flash` 按文本描述插入物体。
  - `remove`：**【原版画笔涂抹蒙版不支持说明】** 新站编辑页（`/project/<id>/edit/<wid>`）已彻底移除原版 `labs.google` 的画布涂抹蒙版控件，且 `HTrJv` 已下线 `veo_2_0_object_removal_*` 模型（见 `.scratch/out/p12.txt`、`p17.txt`、`p21.txt` 与 `htrjv.json`）。新站通过智能体面板 `Omni 1.2 Flash`（`macaron_cookie_edit`）按文本指令或方位描述移除物体并补全背景。`flow remove` 兼容原 `--x` / `--y` / `--brush` 参数（自动映射为画面九宫格方位描述）并新增可选 `-t / --text` 直接指定待移除物体。
- **指令模板**：
  - `insert`：`使用 Omni 1.2 Flash 模型对这个视频进行编辑，在画面中加入：{prompt}，其余内容保持不变，分辨率 360p。`
  - `remove`：`使用 Omni 1.2 Flash 模型对这个视频进行编辑，将{target_desc}移除并自然补全背景，其余画面内容保持不变，分辨率 360p。`

### 2.7 视频高清重塑（`flow upscale`）
- **移植方式**：导航至编辑页 `/project/<id>/edit/<workflow_id>`，点击顶部 `button[aria-label='下载媒体内容']`，核验菜单项价格（`1080p 已高清重塑` = 0 积分免费；`4K 已高清重塑` = 50 积分），点击后触发 `p0UkFb` RPC（`veo_3_1_upsampler_1080p`），轮询 `as29s` 直至 `<media_id>_upsampled` 签出下载 URL。

---

## 3. 端到端 CLI 实测台账與产物校验

| # | CLI 命令 / 功能 | 源媒体 / 参数 | 确认卡报价 | 余额前 → 后（实扣） | 产出 `media_id` | 落盘产物与 `ffprobe` 校验 |
|---|---|---|---|---|---|---|
| 1 | `flow upscale` (1080p) | `3cface19-9e0e-47dd-9ac5-405c790fed70` | 0（免费菜单项） | 24,860 → 24,860（**0**） | `3cface19-..._upsampled` | `.scratch/out/e2e_upscale_1080p.mp4` (`1920×1080`, H.264+AAC, 10.00s, 11.52MB) |
| 2 | `flow video --start` (I2V) | 首帧 `0d362518-...`（Omni 1.2 Flash 3s 360p） | 3 | 24,860 → 24,857（**−3**） | `c101a8d3-886d-4a96-b9a0-47dbd1abaffe` | `.scratch/out/e2e_i2v/video_001_c101a8d3.mp4` (`640×360`, H.264+AAC, 3.03s, 1.77MB) |
| 3 | `flow extend` | `c101a8d3-...`（延长 3s） | 9 | 24,857 → 24,848（**−9**） | `53878201-d579-416d-9b6e-6bec78926150` | `.scratch/out/e2e_extend.mp4` (`1280×720`, H.264+AAC, **6.04s**, 3.80MB) |
| 4 | `flow camera` | `c101a8d3-...` `--motion dolly_in` (360p) | 6 | 24,848 → 24,842（**−6**） | `7ee4d574-229a-4f48-b...` | `.scratch/out/e2e_camera.mp4` (`640×360`, H.264+AAC, 6.04s, 1.90MB) |
| 5 | `flow camera-pos` | `c101a8d3-...` `--position high` (360p) | 6 | 24,842 → 24,836（**−6**） | `258a56c0-aa22-49d8-a...` | `.scratch/out/e2e_camera_pos.mp4` (`640×360`, H.264+AAC, 6.04s, 2.00MB) |
| 6 | `flow insert` | `c101a8d3-...` `-t "沙滩上有一只白色海鸥在踱步"` (360p) | 6 | 24,836 → 24,830（**−6**） | `a1d2337d-c7e7-43b5-8...` | `.scratch/out/e2e_insert.mp4` (`640×360`, H.264+AAC, 6.04s, 1.87MB) |
| 7 | `flow remove` | `a1d2337d-...` `--x 0.5 --y 0.5 -t "沙滩上的白色海鸥"` (360p) | 6 | 24,830 → 24,824（**−6**） | `81a684e8-b78b-4cc1-8...` | `.scratch/out/e2e_remove.mp4` (`640×360`, H.264+AAC, 6.04s, 1.75MB) |
| 8 | `flow video --model --aspect` | `--model "Veo 3.1 - Lite" --aspect portrait` (4s) | 5 | 24,824 → 24,819（**−5**） | `db80928c-90cb-429b-9c6c-57b8b5c93f0e` | `.scratch/out/e2e_veolite_portrait/video_001_db80928c.mp4` (**`720×1280` 竖屏**, 3.92s, 1.48MB) |
| 9 | `flow image -r --aspect -n` | `--aspect portrait -n 1` + 双参考图 `-r` | 无卡（0） | 24,819 → 24,819（**0**） | 新图片媒体 | `.scratch/out/e2e_image_ref/image_001.jpg` (**`768×1376` 竖屏**, JPEG, 837KB) |
| 10 | `flow frames` (本地上传 I2V) | 上传 `image_001.jpg` `--aspect portrait` (3s 360p) | 3 | 24,819 → 24,816（**−3**） | `9f68ec62-...` | `.scratch/out/e2e_frames/animated_9f68ec62.mp4` (**`360×640` 竖屏**, 3.03s, 1.87MB) |

---

## 4. 踩坑与失败模式汇总

1. **素材选择器首行默认选中（反选陷阱）**：打开「在提示框中添加素材」时，列表第 0 行默认带 `asset-item-active` 且右侧「添加到提示」按钮已展开；若再对该行执行 `click()` 会触发反选导致「添加到提示」按钮消失。必须先判断 `asset-item-active` 不在 `class` 中才点击行。
2. **同 workflow 多版本海报覆盖**：`extend` / `edit` 产生的新视频与源视频共享同一个 `workflow_id`，素材选择器每个 workflow 只展示一行且缩略图更新为最新版本海报。匹配行与校验 `<flow-ingredient-chip>` 时必须按同 `workflow_id` 聚合所有 `media_id` 与海报 token。
3. **`Zzl0ze` 渲染中占位记录**：批准生成后，`Zzl0ze` 会立刻出现新 `media_id`，但此时视频尚在渲染、`as29s` 返回空串。轮询必须以 `as29s` 签出非空 URL 作为完成标志，否则会提前返回空 `fife_url`。
4. **CDK 浮层遮挡点击**：素材选择器或菜单未关闭时，`.cdk-overlay-backdrop` 会拦截后续 `edit_square` 点击导致超时；每次会话操作前需先清理 `.cdk-overlay-backdrop`。
