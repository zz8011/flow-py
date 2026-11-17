# flow-py 🎬

> 适配新版 [Google Flow AI (`flow.google.com`)](https://flow.google.com) 的非官方 Python SDK 与命令行工具（CLI），实现视频生成、图像生成、视频编辑与无损超分的全流程自动化控制。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

本项目基于 [eddie-fqh/flow-py](https://github.com/eddie-fqh/flow-py) 深度重构与移植。由于旧版 `labs.google/fx` 站点及 `aisandbox-pa` 直连 API 已全面下线并迁移至 `flow.google.com` 单页应用，本仓库逆向适配了新站 **`batchexecute` RPC 传输层**与**创作智能体（Agent）UI 自动化管线**，恢复并跑通了全部查询、生成、多图参考、视频编辑与超分能力。

> ⚠️ **免责声明**：本项目为非官方工具，基于浏览器自动化与前端 RPC 协议实现，与 Google 无关。Google 可能随时调整前端结构或计费策略，仅供个人学习与研究使用。

---

## 功能特性

| 能力 | CLI 命令 | Python SDK | 说明 |
|---|---|---|---|
| 文生视频（T2V） | `flow video` | `generate_video()` | 支持 `Veo 3.1 - Lite / Fast / Quality`、`Omni 1.2 / 1.1 Flash`，支持横竖屏切换 |
| 图生视频（I2V） | `flow frames` / `flow video --start` | `generate_video(start_image=...)` | 支持直接上传本地图片或引用项目内已有 `media_id` 作为首帧 |
| 多参考图生成（R2V / R2I） | `flow video -r` / `flow image -r` | `reference_images=[...]` | 支持挂载多张本地图片或项目素材保持风格/角色一致 |
| 文生图（T2I） | `flow image` | `generate_image()` | Nano Banana / Imagen 系列模型（ULTRA 等档位 **0 积分免费**），支持 `16:9` / `9:16` / `1:1` |
| 视频延长 / 循环续写 | `flow extend` / `flow extend-loop` | `extend_video()` / `extend_loop()` | 单次延长或自动串联延长 N 次生成长视频 |
| 视频高清重塑（超分） | `flow upscale` | `upscale_video()` | **1080p 免费（0 积分）**，同时支持 4K 超分 |
| 镜头运镜重拍 | `flow camera` | `camera_motion()` | 推拉（Dolly）、环绕（Orbit）、希区柯克变焦（Dolly Zoom）等 8 种运镜 |
| 摄像机机位调整 | `flow camera-pos` | `camera_position()` | 高低机位、左右偏移、远近景别等 7 种机位 |
| 视频物体插入 | `flow insert` | `insert_object()` | 按自然语言描述在原视频画面中自然融入新物体 |
| 视频物体移除 | `flow remove` | `remove_object()` | 按物体描述或画面坐标区域移除物体并自动补全背景 |
| 批量生成 | `flow batch-images` / `batch-videos` | — | 从提示词文本文件批量生成图片或并发生成视频 |
| 项目 / 积分 / 模型管理 | `flow status` / `credits` / `models` / `projects` | `get_credits()` / `get_model_config()` | 实时读取积分余额、账号档位官方价目表、项目与媒体列表 |
| 实时现签下载 | `flow download` / `download-all` | `download()` / `download_all()` | 每次通过 `as29s` 现签时效下载链接，不缓存过期 URL |

---

## 工作原理与安全核价机制

新版 `flow.google.com` 采用双层混合架构驱动：

1. **RPC 数据与现签层（`flow/_rpc.py`）**
   复用浏览器持久化 Google Cookie，从页面 `WIZ_global_data` 提取 `SNlM0e` / `FdrFJe` 令牌，直接调用 `/_/AiSandboxAngularFrontend/data/batchexecute`：
   - `nzlxg`：查询实时积分余额与订阅档位
   - `HTrJv`：解码当前账号档位下的全量模型官方价目表
   - `UpteDb` / `Zzl0ze`：拉取项目列表、工作流（Workflow）与媒体元数据
   - `as29s`：按 `media_id` 实时签发 `flow-content` 高清媒体下载 URL
2. **智能体面板与编辑页自动化层（`flow/_flow_ui.py`）**
   生成与编辑请求通过 Playwright 真实输入事件（`isTrusted=true`）驱动右侧创作智能体面板：挂载素材 Chip（强校验 UUID / 海报 Token）→ 提交指令 → 解析确认卡 → 核价批准 → 轮询 `as29s` 直至新媒体签出非空下载 URL。
3. **内置「先核价后批准」安全闸**
   - 首次进入项目自动检查并将智能体设置锁定为**「生成前先确认：始终」**，防止无卡静默扣费。
   - 点击「批准」按钮前，强制将确认卡上的积分报价、时长与 `HTrJv` 官方价目表逐项比对；**核对不一致绝不点击批准**，图片生成若出现 `> 0` 积分报价立即中止。

---

## 安装

环境要求：**Python 3.10+**

```bash
git clone https://github.com/zz8011/flow-py.git
cd flow-py
pip install -e ".[dev]"
playwright install chromium
```

---

## 快速开始

### 1. 登录与绑定项目

配置与 Chromium 登录会话持久化保存在 `~/.flow-py/`，只需首次登录一次：

```bash
# 1. 打开有头浏览器完成 Google 登录，检测到会话后自动保存退出
flow login

# 2. 查看账号下的 Flow 项目列表（若为空请先在网页端新建一个项目）
flow projects

# 3. 绑定默认工作项目
flow use <project_id>

# 4. 检查认证状态、默认项目与剩余积分
flow status
```

### 2. 常用 CLI 示例

> 所有 `media_id` 参数均支持只填前 8~16 位唯一前缀（无需复制完整 UUID）；编辑类命令的 `-w/--workflow` 会自动反查，通常无需手填。

```bash
# 文生图（支持 landscape / portrait / square）
flow image "清晨的海边白色灯塔，电影感晨光" --aspect portrait -n 2 -o ./images

# 多参考图融合生图（-r 支持本地图片路径或项目内 media_id）
flow image "保持参考图角色与画风，站在樱花树下" -r ./ref1.jpg -r ./ref2.jpg -n 1 -o ./images

# 文生视频（默认无头运行并自动等待下载）
flow video "海浪轻拍礁石，晨光洒在海面" --model "Veo 3.1 - Lite" --aspect landscape -o ./videos

# 图生视频 I2V（直接传入本地静态图片）
flow frames ./photo.jpg -p "镜头缓慢向前推进，微风吹动发丝" --aspect portrait -o ./videos

# 图生视频 I2V（通过 --start 传入本地图片或已有图片 media_id）
flow video "镜头缓慢拉远展现全景" --start ./photo.jpg --aspect landscape -o ./videos

# 免费 1080p 高清重塑（0 积分！）
flow upscale <media_id> -r 1080p -o ./video_1080p.mp4

# 视频延长（单次延长 / 连续延长 3 次拼成长镜头）
flow extend <media_id> -p "海浪继续向岸边推进，退潮留下一层水光" -o ./extended.mp4
flow extend-loop <media_id> -n 3 -p "镜头持续向前飞行穿越云层" -o ./extensions

# 镜头运镜与机位调整
flow camera <media_id> --motion dolly_in -o ./dolly_in.mp4
flow camera-pos <media_id> --position high -o ./high_angle.mp4

# 视频物体插入与移除
flow insert <media_id> -t "沙滩上有一只白色海鸥在踱步" -o ./inserted.mp4
flow remove <media_id> -t "沙滩上的白色海鸥" -o ./removed.mp4
```

### 3. Python SDK 示例

```python
import asyncio
from flow import FlowClient

async def main():
    async with await FlowClient.create(
        project_id="your-project-id",
        headless=True,
    ) as client:
        # 查询积分
        credits = await client.get_credits()
        print(f"当前剩余积分: {credits.credits} (tier={credits.tier})")

        # 1. 文生视频
        jobs = await client.generate_video(
            "清晨的海边灯塔，海浪拍岸，电影感",
            model="Veo 3.1 - Lite",
            aspect="landscape",
        )
        status = await client.wait_for_video(jobs[0])
        await client.download(status.fife_url, "./lighthouse.mp4")

        # 2. 视频延长
        ext_job = await client.extend_video(
            jobs[0].media_name,
            prompt="镜头缓慢拉升俯瞰整片海岸线",
        )
        ext_status = await client.wait_for_video(ext_job)
        await client.download(ext_status.fife_url, "./lighthouse_extended.mp4")

        # 3. 免费 1080p 超分
        up_job = await client.upscale_video(jobs[0].media_name, resolution="1080p")
        up_status = await client.wait_for_video(up_job)
        await client.download(up_status.fife_url, "./lighthouse_1080p.mp4")

asyncio.run(main())
```

---

## CLI 命令参考

```text
认证与项目
  flow login                        打开浏览器登录 Google 账号并保存会话
  flow logout                       清除本地保存的浏览器会话
  flow status [--json]              一键检查登录态、当前项目、积分与最近任务
  flow config                       显示本地配置路径与超时参数
  flow projects                     实时拉取并列出账号下的全部项目
  flow use <PROJECT_ID>             设置当前默认项目
  flow workflows [-n 20]            列出项目内的工作流与主媒体 ID
  flow credits                      查看当前积分余额与订阅档位
  flow models [--json]              列出当前账号档位下所有可用模型与积分单价

生成与批处理
  flow video <PROMPT>               文生视频 / 首帧图生视频 (--start) / 多参考图视频 (-r)
  flow frames <IMAGE_PATH>          本地静态图片一键生成视频 (I2V)
  flow image <PROMPT>               文生图 / 多参考图生图 (-r)
  flow batch-images <PROMPTS_FILE>  按文本文件逐行批量生成图片
  flow batch-videos <PROMPTS_FILE>  按文本文件批量生成视频（支持 -c 并发）

视频编辑与超分
  flow extend <MEDIA_ID>            延长指定视频（-p 附加后续剧情描述）
  flow extend-loop <MEDIA_ID>       连续延长 N 次生成长视频（-n 次数）
  flow upscale <MEDIA_ID>           视频超分（默认 -r 1080p 免费；可选 -r 4k）
  flow camera <MEDIA_ID>            重新运镜（--motion 必填）
  flow camera-pos <MEDIA_ID>        调整摄像机机位（--position 必填）
  flow insert <MEDIA_ID>            在视频中插入物体（-t 必填描述）
  flow remove <MEDIA_ID>            从视频中移除物体（推荐用 -t 描述目标物体，或用 --x/--y 指定方位）

轮询与下载
  flow poll <MEDIA_ID> [--wait]     轮询媒体渲染状态并获取现签 URL
  flow download <MEDIA_ID>          下载指定视频或图片
  flow download-all                 批量下载项目或指定工作流内的全部媒体
```

---

## 参数枚举表

### 镜头运镜（`flow camera --motion`）

| 参数值 | 运镜效果 |
|---|---|
| `dolly_in` / `dolly_out` | 镜头向前推进 / 向后拉远 |
| `orbit_left` / `orbit_right` | 镜头向左环绕 / 向右环绕主体 |
| `orbit_up` / `orbit_low` | 镜头向上环绕升起 / 低角度下潜环绕 |
| `dolly_zoom_in` / `dolly_zoom_out` | 希区柯克推进变焦 / 拉远变焦（滑动变焦） |

### 摄像机机位（`flow camera-pos --position`）

| 参数值 | 机位效果 |
|---|---|
| `center` | 居中固定正视机位 |
| `left` / `right` | 偏左机位 / 偏右机位 |
| `high` / `low` | 高角度俯拍机位 / 低角度仰拍机位 |
| `closer` / `further` | 近景特写机位 / 远景全景机位 |

### 常用模型与参考积分（以 `flow models` 实测为准）

不同订阅档位（如 Pro / Ultra）单价不同，可通过 `flow models` 查询当前账号实时单价。以下为 Ultra 档位常见参考值：

| 模型显示名（`--model`） | 适用场景 | Ultra 档参考消耗 |
|---|---|---|
| `Veo 3.1 - Lite` | 快速轻量文生视频 / 图生视频 | 5 积分（4s） |
| `Veo 3.1 - Fast` | 高性价比标准视频生成 | 10 积分（8s） |
| `Veo 3.1 - Quality` | 电影级高画质视频生成 | 50–100 积分 |
| `Omni 1.2 Flash` | 多模态生成、延长、运镜、插入与移除编辑 | 3–9 积分（360p/720p 短片） / 30 积分（10s） |
| `1080p Upsampler` | `flow upscale -r 1080p` | **0 积分（免费）** |
| `4K Upsampler` | `flow upscale -r 4k` | 50 积分 |
| `Nano Banana` 系列 | `flow image` 文生图 / 参考图生图 | **0 积分（免费）** |

---

## 项目结构

```text
flow/
├── _rpc.py            # flow.google.com batchexecute RPC 传输层（积分/模型/媒体列表/as29s 现签）
├── _flow_ui.py        # Playwright 智能体面板 (AgentUI) 与编辑页超分自动化
├── _client.py         # FlowClient 高层异步 SDK（串联素材挂载、核价闸门、轮询与下载）
├── _browser.py        # BrowserManager 浏览器持久化 Profile 与 CDP 连接管理
├── _api.py            # 兼容层数据模型（VideoJob, VideoStatus, Credits, Workflow）与轮询封装
├── _storage.py        # 本地配置与项目注册表持久化 (~/.flow-py/)
├── _downloader.py     # 媒体流式下载工具
├── _exceptions.py     # 异常体系 (AuthError, GenerationError, GenerationTimeout...)
└── cli/
    └── main.py        # Click 命令行入口
```

更多关于 `flow.google.com` 协议细节、移植方案与实测台账请参阅 [PATCH.md](PATCH.md) 与 [PORT2.md](PORT2.md)。

---

## 已知说明与注意事项

1. **首次登录需图形界面**：`flow login` 需要打开可见浏览器窗口完成 Google 登录（无桌面服务器可配合 `Xvfb` 或在本地登录后同步 `~/.flow-py/browser-profile`）；登录完成后日常所有命令均默认 `--headless` 无头运行。
2. **签名链接时效性**：`as29s` 签发的媒体下载链接带有过期时间，请勿长期缓存 URL，需要文件时直接调用 `flow download <media_id>` 现签下载。
3. **物体移除方式变更**：`flow.google.com` 新站编辑页已下线旧版画笔涂抹像素蒙版，现通过 `Omni 1.2 Flash` 智能体按语义/方位指令移除物体并补全背景，使用 `flow remove` 时建议优先传入 `-t "要移除的物体描述"` 获得最佳效果。

---

## 致谢与许可证

- 原项目作者：[eddie-fqh/flow-py](https://github.com/eddie-fqh/flow-py)，灵感源自 [notebooklm-py](https://github.com/teng-lin/notebooklm-py)
- 开源协议：[MIT License](LICENSE)
