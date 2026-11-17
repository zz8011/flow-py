# flow-py 🎬🎵

> 适配新版 [Google Flow AI (`flow.google.com`)](https://flow.google.com) 与 [Google Flow Music (`flowmusic.app`)](https://www.flowmusic.app) 的非官方 Python SDK 与命令行工具（CLI），一站式打通 **视频生成、图像生成、视频编辑超分** 与 **Lyria 3.5 音乐创作、分轨、重混编辑**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

本项目基于 [eddie-fqh/flow-py](https://github.com/eddie-fqh/flow-py) 深度重构与扩展：
1. **Flow 视频与图像（`flow.google.com`）**：逆向适配新站 `batchexecute` RPC 传输层与创作智能体（Agent）UI 自动化管线，内置「先核价后批准」安全闸。
2. **Flow Music 音乐工作室（`flowmusic.app`）**：逆向适配 `/__api/*` REST + SSE 流协议与同 Profile Google SSO 自动续签，直连 **Lyria 3.5** 与 **Producer** 音乐制作智能体，支持毫秒级免浏览器 API 调用与无损 WAV / MP3 / M4A 无限下载。

> ⚠️ **免责声明**：本项目为非官方工具，基于浏览器自动化与前端接口协议实现，与 Google 无关。Google 可能随时调整前端结构或计费策略，仅供个人学习与研究使用。

---

## 功能特性总览

### 🎬 视频与图像（`flow.google.com`）

| 能力 | CLI 命令 | Python SDK | 说明 |
|---|---|---|---|
| 文生视频（T2V） | `flow video` | `generate_video()` | 支持 `Veo 3.1 - Lite / Fast / Quality`、`Omni 1.2 / 1.1 Flash`，支持横竖屏切换 |
| 图生视频（I2V） | `flow frames` / `flow video --start` | `generate_video(start_image=...)` | 支持上传本地图片或引用项目已有 `media_id` 作为首帧 |
| 多参考图生成（R2V / R2I） | `flow video -r` / `flow image -r` | `reference_images=[...]` | 支持挂载多张本地图片或项目素材保持风格/角色一致 |
| 文生图（T2I） | `flow image` | `generate_image()` | Nano Banana / Imagen 系列模型（Ultra 等档位 **0 积分免费**），支持 `16:9` / `9:16` / `1:1` |
| 视频延长 / 循环续写 | `flow extend` / `flow extend-loop` | `extend_video()` / `extend_loop()` | 单次延长或自动串联延长 N 次生成长视频 |
| 视频高清重塑（超分） | `flow upscale` | `upscale_video()` | **1080p 免费（0 积分）**，同时支持 4K 超分 |
| 镜头运镜与机位调整 | `flow camera` / `flow camera-pos` | `camera_motion()` / `camera_position()` | 8 种镜头运镜（推拉、环绕、滑动变焦）与 7 种机位调整 |
| 视频物体插入与移除 | `flow insert` / `flow remove` | `insert_object()` / `remove_object()` | 按自然语言描述在画面中融入新物体，或移除物体并自动补全背景 |
| 批量生成与现签下载 | `flow batch-*` / `flow download` | `download()` / `download_all()` | 每次通过 `as29s` 现签时效链接下载，不缓存过期 URL |

### 🎵 音乐创作与编辑（`flowmusic.app` / Lyria 3.5）

| 能力 | CLI 命令 | Python SDK (`FlowMusicClient`) | 说明 |
|---|---|---|---|
| 文生音乐 / 带词编曲 | `flow music generate` | `generate_song()` | 支持纯音乐（`--instrumental`）、自定义歌词、BPM、目标时长与随机种子 |
| Producer 对话式制作 | `flow music chat` | `chat()` | 与 AI 联合制作人多轮对话写歌/改歌，支持上传本地参考音频（`--audio`） |
| AI 歌词创作 | `flow music lyrics` | `generate_lyrics()` | 按主题与曲风一键生成结构化完整歌词（**0 积分免费**） |
| 风格翻唱 / 重混（Cover） | `flow music cover` | `cover_song()` | 保持原曲旋律结构，迁移至全新曲风/配器（可调 `--strength`） |
| 歌曲延长（Extend） | `flow music extend` | `extend_song()` | 从曲末或指定秒数向后自然续写延长 |
| 区间重绘（Replace） | `flow music replace` | `replace_section()` | 指定 `[start, end]` 时间窗局部重做过渡段或副歌 |
| 精准裁剪与淡入淡出 | `flow music trim` | `trim_song()` | 精确裁切时间区间并添加平滑淡入/淡出（**0 积分免费**） |
| 四轨分轨提取（Stems） | `flow music stems` | `split_stems()` | 分离提取 `vocals`（人声）、`drums`（鼓）、`bass`（贝斯）、`other`（伴奏） |
| 视频配乐 | `flow music score` | `score_video()` | Producer 看懂视频后作曲，自动按视频时长裁剪+淡出，`--mux` 直接合成带配乐的 mp4 |
| 多格式免费无限下载 | `flow music download` | `download_song()` | 支持无损 **`wav`**（48kHz PCM）、带封面标签 **`mp3`** 与 **`m4a`**（**0 积分免费**） |

---

## 工作原理

1. **统一登录态（`~/.flow-py/browser-profile`）**
   执行一次 `flow login` 完成 Google 账号登录后，视频站（`flow.google.com`）与音乐站（`flowmusic.app`）共享同一持久化 Chromium Profile：
   - 视频站走页面 `WIZ_global_data` 引导的 `batchexecute` RPC + Playwright 真实点击智能体面板，内置**「先核价后批准」安全闸**（比对 `HTrJv` 官方价目表一致后才点击批准）。
   - 音乐站自动通过同一 Google 会话完成一键 OAuth SSO，将短期 Supabase Bearer JWT 缓存在 `~/.flow-py/music_token.json`（权限 `0600`）。Token 有效期内所有音乐查询、生成、SSE 流与下载均直接走 `aiohttp`，无需启动浏览器（响应约 0.25s）；过期时自动在后台静默续签。

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

### 1. 登录与状态检查

```bash
# 1. 打开浏览器登录 Google（同时自动同步 Flow 与 Flow Music 会话）
flow login

# 2. 选择视频工作项目并查看视频站状态
flow projects
flow use <project_id>
flow status

# 3. 查看音乐站状态、独立音乐积分与最近歌曲
flow music status
```

### 2. 视频与图像 CLI 示例

> 所有 `media_id` / `clip_id` 参数均支持只填前 8~16 位唯一前缀（无需复制完整 UUID）。

```bash
# 文生图（0 积分；--aspect 支持 landscape / portrait / square）
flow image "清晨的海边白色灯塔，电影感晨光" --aspect portrait -n 2 -o ./images

# 多参考图融合生图
flow image "保持参考图角色与画风，站在樱花树下" -r ./ref1.jpg -r ./ref2.jpg -n 1 -o ./images

# 文生视频（可选 Veo 3.1 - Lite / Fast / Quality / Omni 1.2 Flash）
flow video "海浪轻拍礁石，晨光洒在海面" --model "Veo 3.1 - Lite" --aspect landscape -o ./videos

# 图生视频 I2V（本地静态图片一键动起来）
flow frames ./photo.jpg -p "镜头缓慢向前推进，微风吹动发丝" --aspect portrait -o ./videos

# 免费 1080p 高清重塑（0 积分！）
flow upscale <media_id> -r 1080p -o ./video_1080p.mp4

# 视频延长、运镜、机位、插入与移除物体
flow extend <media_id> -p "海浪继续向岸边推进" -o ./extended.mp4
flow camera <media_id> --motion dolly_in -o ./dolly_in.mp4
flow camera-pos <media_id> --position high -o ./high_angle.mp4
flow insert <media_id> -t "沙滩上有一只白色海鸥在踱步" -o ./inserted.mp4
flow remove <media_id> -t "沙滩上的白色海鸥" -o ./removed.mp4
```

### 3. Flow Music 音乐创作与编辑 CLI 示例

```bash
# 1. AI 生成完整歌词（0 积分）
flow music lyrics "一首关于清晨海边灯塔与希望的轻快民谣"

# 2. 生成纯音乐配乐（指定 BPM 与标题，下载为 MP3 或无损 WAV）
flow music generate "赛博朋克高科技产品发布会，强劲合成器低音与电子鼓" \
  --instrumental --bpm 128 --title "Cyber Launch" -f wav -o ./music

# 3. 自定义歌词编曲生成（--lyrics 也支持传 @lyrics.txt 读取文件）
flow music generate "温暖治愈的都市木吉他民谣" \
  --lyrics $'[Verse]\n海风吹醒清晨的街角\n[Chorus]\n迎着晨光奔跑' \
  --title "晨光街角" -f mp3 -o ./music

# 4. 与 Producer 智能体多轮对话做歌（支持 --session 续聊、--audio 上传参考音频）
flow music chat "帮我做一首轻快俏皮的尤克里里 Vlog 开场曲" -f mp3 -o ./music

# 5. 精准裁剪成 30 秒配乐并加 1.5 秒结尾淡出（0 积分）
flow music trim <clip_id> --start 0 --end 30 --fade-out 1.5 -f wav -o ./music/bgm_30s.wav

# 6. 四轨分轨提取（分离 vocals / drums / bass / other）
flow music stems <clip_id> -f wav -o ./stems

# 7. 风格翻唱（Cover）、续写延长（Extend）与段落替换（Replace）
flow music cover <clip_id> -p "改编成慵懒的 Bossa Nova 爵士吉他与萨克斯" --strength 0.6 -o ./music
flow music extend <clip_id> -s 20 -p "温暖的口琴与木吉他尾奏渐弱" -o ./music
flow music replace <clip_id> --start 30 --end 60 -p "加入清脆的钢琴独奏间奏" -o ./music

# 8. 给视频配乐（上传视频→生成 2 首→裁到视频时长→可合成进视频；约 10 积分）
flow music score ./video.mp4 -p "轻松舒缓的钢琴" -o ./music --mux

# 9. 将任意历史歌曲导出为无损 WAV / MP3 / M4A（0 积分）
flow music download <clip_id> -f wav -o ./music
```

### 4. Python SDK 示例

```python
import asyncio
from flow import FlowClient, FlowMusicClient

async def main():
    # 一、音乐客户端（缓存 Token 有效期内无需启动浏览器）
    async with await FlowMusicClient.create() as music:
        mc = await music.get_credits()
        print(f"音乐积分: {mc.credits_remaining:.0f}")

        # 生成歌曲 -> 裁剪 30s 配乐 -> 导出无损 WAV
        song = await music.generate_song(
            "未来感合成器电子配乐，节奏紧凑",
            instrumental=True,
            bpm=126,
            title="Future Pulse",
        )
        bgm_30s = await music.trim_song(song.id, start_s=0, end_s=30, fade_out_s=1.5)
        await music.download_song(bgm_30s, "./future_pulse_30s.wav", audio_format="wav")

    # 二、视频客户端（也可通过 client.music 直接访问音乐接口）
    async with await FlowClient.create(project_id="your-project-id", headless=True) as client:
        jobs = await client.generate_video(
            "清晨海边灯塔，海浪拍岸，电影感",
            model="Veo 3.1 - Lite",
            aspect="landscape",
        )
        status = await client.wait_for_video(jobs[0])
        await client.download(status.fife_url, "./lighthouse.mp4")

asyncio.run(main())
```

---

## CLI 命令速查表

### 视频与全局命令（`flow ...`）

```text
flow login / logout               登录 Google（同步视频与音乐会话） / 清除会话
flow status [--json]              检查视频站登录态、默认项目、积分与最近任务
flow projects / use <ID>          列出项目 / 绑定默认项目
flow credits / models             查看视频积分余额 / 列出视频模型与官方单价
flow workflows [-n 20]            列出项目内工作流与主媒体 ID
flow video <PROMPT>               文生视频 / 首帧图生视频 (--start) / 多参考图视频 (-r)
flow frames <IMAGE_PATH>          本地静态图片生成视频 (I2V)
flow image <PROMPT>               文生图 / 多参考图生图 (-r)
flow upscale <MEDIA_ID>           视频超分（默认 -r 1080p 免费；可选 -r 4k）
flow extend / extend-loop <ID>    单次延长视频 / 连续延长 N 次
flow camera <ID> --motion ...     镜头运镜（dolly_in/out, orbit_left/right/up/low, dolly_zoom_in/out）
flow camera-pos <ID> --position . 机位调整（center, left, right, high, low, closer, further）
flow insert <ID> -t "..."         在视频中插入物体
flow remove <ID> -t "..."         从视频中移除物体
flow poll / download / download-all 轮询状态 / 现签下载单个或全部媒体
flow batch-images / batch-videos  按文本文件批量生成图片或视频
```

### 音乐子命令（`flow music ...`）

```text
flow music status [--json]        检查音乐站登录态、订阅档位、音乐积分与最近歌曲
flow music credits / models       查看音乐积分余额 / 列出可用音乐模型 (Lyria 3.5 等)
flow music songs [-n 20]          列出音乐库歌曲（Clip ID、时长、操作类型、标题）
flow music sessions [-n 20]       列出 Producer 历史对话会话
flow music generate <PROMPT>      使用 Lyria 3.5 生成歌曲（支持 -l 歌词 / -i 纯音乐 / --bpm / -d 时长）
flow music chat <PROMPT>          与 Producer 智能体对话创作/改歌（支持 -s 续聊 / --audio 传音频）
flow music lyrics <PROMPT>        AI 生成结构化歌词（0 积分）
flow music cover <CLIP_ID> -p ..  风格翻唱 / 重混改编（--strength 调节改编幅度）
flow music extend <CLIP_ID>       续写延长歌曲（-s 延长秒数 / --from-sec 起始秒数 / -p 指令）
flow music replace <CLIP_ID>      区间局部重绘（--start 起始秒 --end 结束秒 -p 指令）
flow music trim <CLIP_ID>         精准时间裁剪与淡入淡出（--start / --end / --fade-in / --fade-out，0 积分）
flow music stems <CLIP_ID>        分离人声/鼓/贝斯/伴奏四轨并批量导出
flow music score <VIDEO>          为视频配乐（-p 风格 / --mux 合成进视频，约 5 积分/首）
flow music download <CLIP_ID>     导出 mp3 / wav（无损） / m4a 音频（0 积分）
```

---

## 参考积分消耗说明

视频站（`flow.google.com`）与音乐站（`flowmusic.app`）使用各自独立的积分池：

| 平台 | 操作 | 实测消耗参考（Ultra / Member 档） |
|---|---|---|
| **Flow 视频/图像** | `flow image`（Nano Banana） / `flow upscale -r 1080p` | **0 积分（免费）** |
| **Flow 视频/图像** | `flow video`（`Veo 3.1 - Lite` 4s / `Fast` 8s） | 5 积分 / 10 积分 |
| **Flow 视频/图像** | `flow frames` / `extend` / `camera` / `insert` / `remove`（`Omni 1.2 Flash`） | 3–9 积分（短片） |
| **Flow Music 音乐** | `flow music lyrics` / `trim` / `download`（WAV/MP3/M4A） | **0 积分（免费）** |
| **Flow Music 音乐** | `flow music stems`（四轨分离：首次 / 已分离缓存） | ~1.7 积分（20 tokens） / **0 积分** |
| **Flow Music 音乐** | `flow music generate` / `cover` / `extend` / `replace` / `chat` 生歌 | **5 积分**（60 tokens / 首） |

---

## 项目结构

```text
flow/
├── _rpc.py            # flow.google.com batchexecute RPC 传输层（积分/模型/媒体列表/as29s 现签）
├── _flow_ui.py        # Playwright 视频智能体面板 (AgentUI) 与编辑页超分自动化
├── _client.py         # FlowClient 视频与图像高层异步 SDK（含 client.music 入口）
├── _music_rpc.py      # flowmusic.app REST + SSE 流传输层、Google SSO 自动续签与 JWT 缓存
├── _music.py          # FlowMusicClient 音乐创作、编辑、分轨与多格式下载高层 SDK
├── _browser.py        # BrowserManager 浏览器持久化 Profile 与 CDP 连接管理
├── _api.py            # 视频/图像数据模型与轮询兼容封装
├── _storage.py        # 本地配置、项目注册表与会话缓存管理 (~/.flow-py/)
└── cli/
    ├── main.py        # Click 主命令行入口
    └── _music.py      # `flow music` 子命令组实现
```

---

## 致谢与许可证

- 原项目作者：[eddie-fqh/flow-py](https://github.com/eddie-fqh/flow-py)，灵感源自 [notebooklm-py](https://github.com/teng-lin/notebooklm-py)
- 开源协议：[MIT License](LICENSE)
