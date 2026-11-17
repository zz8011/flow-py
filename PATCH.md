# flow-py 修补说明（flow.google.com 适配）

- 日期：2026-11-18
- 原版：eddie-fqh/flow-py v0.1.0（commit bd01679），只读审查副本在 devbox `~/tools/flow-py-audit`（保持原样）
- 修补版：devbox `~/tools/flow-py-patched`，已装回沙盒 venv（`/home/zz8011/tools/flow-py-trial/venv`）；补丁源码副本在本目录 `src-patched/`
- 背景：阶段 B 试跑判死——labs.google/fx 整站重定向到 flow.google.com 单页应用，旧版的 token 提取（__NEXT_DATA__ / session 端点）与 aisandbox-pa 直连 API 全部失效。用户 2026-11-18 00:39 令修补。

## 新站协议（逆向实测，2026-11-18）

- 应用：Angular SPA "AiSandboxAngularFrontend"，**cookie 鉴权**，无 Bearer、无 aisandbox-pa 调用。
- 一切数据走 `POST https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute`，请求体只有 `f.req` + `at`；`at` / `f.sid` / `bl` 从页面 `WIZ_global_data` 的 SNlM0e / FdrFJe / cfb2h 取。响应为 `)]}'` 前缀 + `["wrb.fr", rpcid, payload-json, ...]` 行。
- RPC 字典：
  - `nzlxg`（req `[]`）= 积分：resp `[余额, tier, 3, 3, null, 余额, [重置ts, ns]]`
  - `UpteDb` = 项目列表；`jHPbke` = 建项目
  - `HTrJv` = 模型配置全表（家族 → 变体 [model_key, …, [[tier, [[_, cost]]]], …, duration@16]）
  - `Zzl0ze` = 项目 workflows + 媒体（**不含签名下载 URL**；媒体记录含海报 asb URL、大小、提示词、model_key、时长 [null,null,[秒]]）
  - `as29s`（req `["<media_id>"]`）= 单媒体记录，**含签名 flow-content URL**（下载靠它现签）
  - `o30O0e` = 用户信息
- 官方价（tier 2 实读）：Omni 1.2 Flash（macaron_cookie）10s = 30、Omni 1.1 Flash（abra）10s = 15、Veo 3.1 Fast = 20 / Lite = 10 / Quality = 100；图片（Nano Banana 系）本档 0 积分。
- 生成没有 API：项目页右侧是**智能体会话面板**，生成走 WebChannel 流。裸提示词会被 agent 路由去**生成图片**；视频必须明说「生成一段视频」。视频生成前 agent 弹确认卡（模型 + 时长 + 点数），卡上报价就是实扣额（两次实测均分毫不差）。

## 补丁内容

- **新增 `flow/_rpc.py`**：batchexecute 传输层（WIZ 引导、wrb.fr 解析）+ 类型化方法 get_credits / list_projects / create_project / get_model_config（按账号 tier 解码官方价）/ list_project_media（结构化解析，视频靠 model_key + 时长标记判型）/ get_media_url（as29s 现签）。
- **`flow/_api.py`**：get_credits、get_video_model_config、get_project_data / list_workflows、poll_video 改走 RPC（保持原签名与 Credits / Workflow / VideoStatus 返回形状，wait_for_video 等上层逻辑零改动）；直连生成方法（_video_call 扼流点 + generate_image）改为明确抛错指向 FlowClient；get_flow_app_config / get_user_settings 无对应 RPC，返回空。
- **`flow/_browser.py`**：基址改 flow.google.com，项目 URL 正则与 CDP 页偏好同步。
- **`flow/_flow_ui.py` 新增 `AgentUI`**：驱动创作智能体面板——开面板 / 新会话（edit_square）→ ProseMirror 输入（focus 兜底）→ arrow_forward 真实点击提交 → 失败回合点一次「重试」→ 等确认卡 → 解析卡上点数 / 时长 → 交调用方核价 → **真实输入点击**「批准」。
- **`flow/_client.py`**：项目 URL 改新格式；generate_video / generate_image 换成 agent 会话流（提交与完成融合：批准后轮询 RPC 媒体列表等新媒体出现，返回的 VideoJob 已 COMPLETE 且带签名 URL）；编辑类操作（extend / camera / insert / remove / upscale）显式抛「未移植」错，不再静默失败。
- **`flow/cli/main.py`**：login 改为在 flow.google.com 上以 WIZ_global_data 检出登录（每次 evaluate 防崩包裹，原版等待循环对页面跳转零容错会崩）；`use` 的 URL 改新格式；`projects` 改为实时拉取账号项目并回填本地注册表。

## 安全闸（补丁的核心纪律）

- 确认卡报价**先核价后批准**：报价必须命中模型配置官方价（卡上写明时长时必须命中该时长那一档），核不上**绝不批准**——验收首跑就拦下一次（卡片祖先文本缺时长字段，判核价失败、0 扣分），修好卡片文本抓取（向上 12 层、优先含「秒」的完整文本）与核价规则（时长缺失时按家族价目集合核）后通过。
- 批准必须用 Playwright 真实输入点击：DOM 合成 click（isTrusted=false）会被 agent 静默忽略；历史回合的卡带 `dimmed` 类 = 已失效，点它无反应。
- 图片回合若弹卡报价 > 0 直接中止（本档图片应为 0 积分）。

## 验收结果（2026-11-18 01:20–01:45，zeedzh / ULTRA）

- 只读全通：credits 读到实时余额；models 解出全表官方价（macaron_cookie_t2v_10s = 30 与卡片报价互证）；projects 实时列出 9 个项目；status / workflows 正常（workflow 显示名与主媒体 ID 正确关联）。
- 视频：修补版 CLI `flow video "清晨的海边，波浪轻拍沙滩，电影感"` 全程自动——提交 → 确认卡报价 30 → 核价通过 → 批准 → 实扣 **24,890 → 24,860（恰 −30）** → 媒体检出 → `flow poll` COMPLETE → `flow download` 落盘 9,456,088 字节（与媒体记录大小一致），ffprobe：H.264 1280×720 + AAC、10.03s。成品 `trial-beach-2.mp4`（本目录）。
- 图片：`flow image "清晨的海边灯塔，电影感"` → agent 按其设置出 2 张并下载，积分不变（0 扣）。
- 手动试生成的第一条（gen9，修补前）成品在 `trial-beach.mp4`。

## 已知限制 / 二期移植进展（2026-11-18 更新，详见 `PORT2.md`）

- **已全部移植并实测跑通**：
  - `generate_video(..., start_image=..., reference_images=...)`（`flow video --start` / `flow frames`）：支持挂载项目内已有图片 UUID 或直接上传本地图片作为首帧/多参考图生成视频。
  - `--model` 与 `--aspect`（`flow video` / `flow image`）：通过智能体指令精确指定模型家族（`Veo 3.1 - Lite`、`Veo 3.1 - Fast`、`Veo 3.1 - Quality`、`Omni 1.2 Flash`、`Omni 1.1 Flash`）与画幅（`16:9 横屏` / `9:16 竖屏` / `1:1 方形`），已实测产出对应分辨率。
  - `extend_video` / `extend_loop`（`flow extend` / `flow extend-loop`）：挂载源视频 chip 交由 `Omni 1.2 Flash` 延续镜头。
  - `camera_motion` / `camera_position`（`flow camera` / `flow camera-pos`）：挂载源视频 chip 交由 `Omni 1.2 Flash` 重新运镜或调整机位。
  - `insert_object` / `remove_object`（`flow insert` / `flow remove`）：挂载源视频 chip 交由 `Omni 1.2 Flash` 插入或移除物体（注：原版 `labs.google` 编辑页的画布涂抹像素蒙版及 `veo_2_0_object_removal` 在新站已下线，现由 `Omni 1.2 Flash` 按文本描述或 `(x, y)` 方位描述执行移除）。
  - `upscale_video`（`flow upscale`）：通过编辑页 `/project/<id>/edit/<wid>` 下载菜单触发 `1080p 已高清重塑`（0 积分免费）或 `4K`（50 积分），并通过 `as29s` 轮询 `<media_id>_upsampled` 现签下载。
- `flow login` 仍需有头浏览器（Xvfb 或桌面）由用户本人完成登录，补丁只修了登录检出逻辑。
- 签名 URL 有时效（Expires），download / poll 每次现签、不要缓存。

## 失败模式备忘（踩过的坑）

- DOM 合成 click 点「批准」无效（isTrusted），必须真实输入点击；dimmed 卡是死卡。
- agent 回合会偶发「出了点问题」，点该回合「重试」可恢复（gen9 即如此成功）。
- Zzl0ze 列表不给签名 URL——误以为「媒体只有海报」是假象，as29s 按 media_id 现签。
- 媒体判型不能靠签名 URL 有无（列表里根本没有），要用 model_key / 时长标记。
- `flow login` 旧版等待循环遇页面跳转即崩（Execution context destroyed），新版全程 try 包裹。
