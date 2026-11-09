**中文** | [English](README.en.md)

---

# Music Selector — 本地音乐快速试听与选歌工具

一款**纯本地运行**（无需 Flask、无需云服务）的音乐试听与筛选工具，帮助你在几千首歌中快速挑选喜欢的歌曲并导出播放列表。

后端使用 **Python 标准库 `http.server`**，前端使用 **原生 HTML/CSS/JS**，无框架依赖。

---

## 功能特性

- 扫描指定目录，递归索引所有音频文件（mp3/flac/wav/m4a/aac/ogg 等）
- 自动计算「副歌候选起点」`chorus_start`，试听时直接跳到精彩片段
- 三栏布局：左侧歌曲列表 / 中间播放器 / 右侧已选列表
- 支持按歌名、歌手、专辑、文件名、相对路径搜索
- 支持「全部 / 未选 / 已选」三种筛选模式
- **试听模式**：每首歌播放指定秒数（5~60 秒，默认 20 秒）后自动切下一首
- 一键加入 / 移除已选列表
- 导出 `.m3u` 播放列表（绝对路径，UTF-8，兼容主流播放器）
- 完整键盘快捷键
- 已选数据持久化，重启不丢失

---

## 环境要求

- Windows / macOS / Linux
- Python 3.8+（自带 pip）

---

## 安装

```bash
cd music-selector
pip install -r requirements.txt
```

> 核心依赖仅 `mutagen`（读取音频元数据）。

**可选：精确副歌检测（强烈推荐）**：

```bash
pip install pychorus librosa numpy -i https://pypi.tuna.tsinghua.edu.cn/simple
```

装好后重新运行一次索引生成（`analyze_music.py` 或界面「换目录」重新扫描），即可对全部歌曲做真实副歌检测（多进程并行，2779 首约 17 分钟）。不装也不影响使用，自动用 35% 兜底起点。

---

## 使用步骤

### 0. 一键启动（推荐，Windows）

直接双击项目根目录下的 **`启动.bat`**：

1. 自动检查 Python 与依赖（首次自动安装 `mutagen`）；
2. 若尚无音乐库索引，提示你输入音乐目录并自动生成；
3. 启动本地服务并自动打开浏览器。

> 已经生成过索引后，以后每次只需双击 `启动.bat` 即可直接进入界面。

### 1. 生成音乐库索引

```bash
python analyze_music.py "你的音乐目录路径"
```

示例：

```bash
python analyze_music.py "D:\Music"
python analyze_music.py "C:\Users\hailo\Music"
```

脚本会递归扫描目录，读取元数据并计算副歌候选起点，结果保存到 `data/library.json`（UTF-8）。

> 再次运行时自动复用缓存：已分析过的歌曲不重复检测，仅处理新增文件，几秒即可完成增量更新。

### 2. 启动 Web 应用

```bash
python app.py
```

程序会自动打开浏览器，访问 **http://localhost:5000**。

### 3. 使用界面

| 区域 | 功能 |
|------|------|
| 左侧 | 歌曲列表，支持搜索与筛选，点击即播放 |
| 中间 | 播放器控制、进度条、音量、试听模式开关 |
| 右侧 | 已选歌曲列表，点击跳转播放，× 移除 |

**试听模式**：勾选后每首歌播放指定秒数自动切下一首，拖动滑块调整时长（5~60 秒）。

### 4. 快捷键

| 按键 | 功能 |
|------|------|
| `Space` | 播放 / 暂停 |
| `↑` | 上一首 |
| `↓` | 下一首 |
| `A` | 当前歌曲加入已选 |
| `D` | 当前歌曲从已选移除 |
| `F` | 聚焦搜索框 |
| `Esc` | 退出搜索框 |

> 在搜索框输入文字时快捷键自动屏蔽，不会误触发。

### 5. 导出播放列表

点击右上角「导出 M3U」，浏览器下载 `playlist.m3u`，同时保存一份到 `data/playlist.m3u`。文件使用绝对路径，可直接导入 foobar2000、MusicBee、VLC 等播放器。

---

## 项目结构

```
music-selector/
├── 启动.bat            # 一键启动脚本（Windows 双击即可）
├── analyze_music.py     # 扫描音乐目录，生成 library.json
├── app.py               # Web 服务（标准库 http.server，无 Flask）
├── templates/
│   └── index.html       # 前端页面（单文件，含 CSS/JS）
├── data/                # 自动生成
│   ├── library.json     # 音乐库索引
│   ├── selected.json    # 已选歌曲（相对路径列表）
│   ├── config.json      # 当前音乐目录（界面「换目录」使用）
│   └── playlist.m3u     # 导出的播放列表
├── TECHNICAL.md          # 技术文档（架构、API、数据格式、容错设计）
├── requirements.txt
└── README.md
```

---

## 副歌候选起点策略

`analyze_music.py` 按以下优先级计算 `chorus_start`：

1. **pychorus**（推荐安装）— 基于 chromagram 色度特征 + 时滞相似度矩阵，检测最重复的副歌段落
2. **兜底策略** — 使用歌曲时长的 **35%** 位置

> 你的 2779 首在安装 pychorus 后全量检测：**82% 命中真实副歌**，耗时约 17 分钟（多进程并行）。

**加速机制**：
- **多进程并行**：自动按 CPU 核数并行检测（可设 `analyze_music.py` 顶部 `CHORUS_WORKERS`）
- **只分析前 80%**：副歌几乎不出现在歌曲末尾，显著减少解码时间
- **增量缓存升级**：每条记录带 `chorus_source` 标记（`pychorus`/`fallback`），二次扫描时 pychorus 命中的直接复用，仅重测兜底歌曲

> 前端起播时还有二次校验：`chorus_start` 无效或超出时长时自动回退到 0。

---

## 修改音乐目录

**在界面里改（推荐）**：点击右上角「换目录」→ 输入新路径 → 开始扫描，带实时进度条，完成后自动刷新列表。

**命令行方式**：直接在命令行传入新的目录路径即可，无需改代码：

```bash
python analyze_music.py "D:\新的音乐目录"
```

这会更新 `data/library.json`（缓存复用已分析歌曲）。已选列表 (`selected.json`) 使用**相对路径**存储，只要歌曲文件名结构不变就不会丢失。

---

## 常见问题

**Q: 页面显示「加载失败」**
A: 确认已运行 `python analyze_music.py ...` 生成了 `data/library.json`，且 `python app.py` 正在运行。

**Q: 点击歌曲没有声音**
A: 检查音频文件是否仍在磁盘上（目录是否移动）。部分浏览器不支持 `.wma` 等格式，建议转码为 mp3/flac。

**Q: 副歌起点不准**
A: 安装 pychorus 三件套后重新扫描：`pip install pychorus librosa numpy -i https://pypi.tuna.tsinghua.edu.cn/simple`，然后通过界面「换目录」重新扫描一次（或删除 `data/library.json` 后重跑 analyze_music.py）。

**Q: 副歌检测太慢**
A: 已默认多进程并行 + 只分析前 80% 时长。可在 `analyze_music.py` 顶部调整 `CHORUS_WORKERS`（进程数）与 `ANALYZE_MAX_RATIO`（分析比例）。检测结果会带 `chorus_source` 标记缓存，之后增量扫描只重测兜底歌曲，秒级完成。

**Q: 几千首歌加载慢**
A: 首次分析所有文件较慢（每首仅读元数据，通常 1~3 分钟内完成）；之后为增量缓存，很快。网页端一次性加载，3000~5000 首在现代浏览器上流畅。

**Q: 换电脑后绝对路径变了**
A: 重新运行 `python analyze_music.py "新路径"` 即可。已选列表基于相对路径不受影响。

**Q: 端口 5000 被占用**
A: 修改 `app.py` 顶部的 `PORT = 5000` 为其他端口（如 8000）。

---

## 注意事项

- 所有数据纯本地存储，不上传任何云端
- 已选数据保存在 `data/selected.json`，请勿手动破坏格式
- 导出的 `.m3u` 使用 UTF-8 编码与绝对路径
- 播放依赖浏览器 HTML5 Audio，格式兼容性取决于浏览器（Chrome/Edge 对 mp3/flac/m4a/ogg 支持良好）