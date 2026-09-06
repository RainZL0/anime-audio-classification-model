# anime-voice-sorter

按字幕切出动画对白，再把同一角色的声音归到一起。**先完成说话人分类，偶发语气词和噪声后置。** 不按音质排名丢掉一半，也不把短小组混到一个人物桶里。

流程已跑通，身份分组仍需改善。当前进度、假设和下一步统一见 [项目现状](docs/STATUS.md)；本页只维护使用方法。

## 使用

安装后用 `uv run avs --help` 查看命令。需要 FFmpeg；GPU 环境、字幕对齐与模型说明见 [工具](docs/TOOLS.md)。

```powershell
uv sync --locked
uv run avs doctor
# 新的一集；省略 --offset 时自动估计字幕偏移
uv run avs prepare data/raw/uma_s2_03.flac --subs "对应字幕.ass" --name ep03 --out runs/episodes/ep03
uv run avs embed runs/episodes/ep03
```

本机第 1、2 集已迁移好，可直接分组，不必重算模型：

```powershell
uv run avs group runs/episodes/ep01 runs/episodes/ep02 --out runs/groups/uma-next.json --threshold 0.5
uv run avs evaluate runs/groups/uma-next.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --out runs/groups/uma-next-evaluation.json
uv run avs export runs/groups/uma-next.json --out out/uma-next
```

重新调分组只需再跑 `group`；`--method` 可选 average（默认）、single、complete、mutual_knn、two_stage。前三种已实测都不超过 average；two_stage 先分长片段再挂短片段，是旧标签上唯一有改善的候选，等待新标签验证后才会成为默认。分组文件与导出目录用新名字，避免旧音频残留混进新结果。

固定片段比较两个模型（阈值 0.20—0.90，步长 0.01，保留错合与漏合完整曲线）：

```powershell
uv run avs embed runs/episodes/ep01 runs/episodes/ep02 --model wespeaker-resnet293
uv run avs compare runs/episodes/ep01 runs/episodes/ep02 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --out runs/comparison-next.json
```

比较前会核验两种声纹覆盖同一批片段；使用人工标签挑出的阈值只能算探索结果。`--model` 可只比一个模型，`--method` 可重复给出连接规则，同时比较规则曲线。

身份参考实验（保留原分组；每个目标角色至少有 4 条精确标签）：

```powershell
uv run avs references runs/groups/uma.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --role teo --role trainer --role 皇帝 --out runs/references-next
# 增加 --nearest：按最近参考声音归属，扫描四个距离阈值
```

每角色分别取 1/2 条参考，各重复 20 次划分。报告中的基线和参考方法始终用同一批剩余片段评分；参考候选带有已用标签 ID，`evaluate` 会自动排除它们。输出仅为实验候选，当前实测不足以替换默认分组。

嵌入诊断（固定片段，两模型缓存，不重跑音频模型；`--groups` 可选，用来区分组内与组间错误）：

```powershell
uv run avs diagnose runs/episodes/ep01 runs/episodes/ep02 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --groups runs/groups/uma.json --out runs/diagnosis-next
```

输出报告、全部标签配对的距离，以及 `examples/` 下可试听的错误实例。近邻排除查询自身；只有一条标签的角色不作查询，但留作干扰项；未标注近邻只算线索。

对白覆盖核对（字幕里哪些台词根本没有片段）：

```powershell
uv run avs coverage runs/episodes/ep02 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][02][HEVC_FLAC][BDRIP].chs.ass" --out runs/coverage/ep02 --pad 0.3
```

现有片段是「字幕范围 ∩ 检测到有人说话」，还带 1 秒下限，所以片段数远少于字幕对白行数。`coverage` 把没有片段的台词切成音频，按原因分到 `below_floor`（行本身短于 1 秒，不可能切出合格片段）和 `no_speech_found`（行够长却没切出来）两个目录，另出 `lines.txt` 和 `report.json`。偏移取片段与字幕行边界差的众数，不需要当初的语音检测结果。

```powershell
uv run avs label runs/episodes/ep01 --archive annotations/ep01-full.json --all --known annotations/names.json --video "D:/_Search/_Animation/uma/[DHR][Uma Musume S2][01][BIG5][1080P][HEVC_AAC].mp4"
uv run avs label runs/episodes/ep03 --archive annotations/ep03.json --count 50
```

`label` 对照画面报名字，每条直接存进人工归档。不是让你凭记忆听音分组。`--all` 标这一集的全部片段，按时间顺序连着走；不给 `--all` 就随机抽 `--count` 条。整集连着标其实更省力：顺着画面往下看，不用为每条重新定位，也不必猜这一条属不属于抽样范围。`--known` 指定页面词表和参考音的来源，可以是 `annotations/names.json` 这种只有名字的词表，也可以是人工归档；给归档时那里面的片段就能在页面上回放。

`--video` 给这一集的视频，页面就直接放当前片段对应的画面，前后各多给 0.5 秒。画面按需现切：翻到哪条才用 ffmpeg 切哪条，一段两三秒实测不到半秒，同时预热下一条，翻页时通常已经在了。源片多是 HEVC，浏览器支不支持看机器，所以统一转成 360p 的 H.264，切好的存在 `runs/episodes/<集>/label_audio/<归档名>/video/` 下，一集约 46 MB。需要 `ffmpeg` 在 PATH 里。

视频与音轨必须是同一条时间线。本项目的 `data/raw/*.flac` 就是从这些 mp4 里抽的，时长完全一致、互相关位移 0 毫秒，所以片段时间可以直接当视频时间用。换片源前先核对这一点，否则画面会对错人。

验收一个候选分组时不必整集重标，先划出它改动过的范围：

```powershell
uv run avs label-plan --candidate runs/groups/uma-two-stage.json --baseline runs/groups/uma.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --out runs/label-plan.json
uv run avs label runs/episodes/ep01 --archive annotations/ep01-short.json --plan runs/label-plan.json
```

`label-plan` 只挑候选挂进多条组、又还没被任何人工归档覆盖的短片段，并标出哪些在两套分组里归属不同（`reason` 为 `moved`）。`label --plan` 只取该集计划里的片段，仍按时间顺序展示，因为标注者是顺着画面找人，来回跳时间点比多标几条还慢。计划不安排已标过的片段，新旧归档不会给同一条片段两个名字。

标注页把 `--known` 给的角色名列成小块，点一下就打标，数字键 1-9 对应前九个，名字多时可以先筛。不给 `--known` 就只有本轮自己标出来的名字。`__multiple__` 这类特殊标签也会成块出现，否则标成「不止一个人」的片段就再也翻不出来复核。

名字右边的数字打开面板：里面列出这个名字下的全部片段，可以跳过去、改名、整批撤掉标签，**也可以把某一条直接拖到另一个名字上改归属**，包括拖到特殊标签上。整集标完回头核对时，改错一条不必重新定位重听。在筛名字框里敲一个新名字再点「＋ 建这个名字」，可以先把名字建出来再往上拖；建了没用到的名字，以及从列表里删掉的名字，都只影响当前页面，不落盘，因为真正用到的名字已经在归档里了。

名字右边的数字是「本轮 N 条 · 旧标签 N 条」，点开的面板里两边的片段都按集和时间列出：本轮的点了跳过去，旧标签的点了就地试听，用单独的播放器，不打断正在标的那一条。标第二集时把第一集的归档传给 `--known`，第一集标过的片段就成了可回放的参考。旧归档记的音轨路径可能已经搬走，参考音按人声文件名去 `runs/episodes` 下的各集里找同名音轨；找不到就整份跳过，不拿别的音轨凑。试听只用来想起这个名字是谁，判断仍以画面为准。

页面始终不显示机器分组、组号或候选归属：看过机器的答案，标出来的就不再是独立真值。

导出回到原始采样率的人声轨；16 kHz 副本只用于分析。短于 1 秒、没有可靠声纹的片段保留在 `_unassigned`，不会被安静丢弃。

[文档导航](docs/README.md) · [人工标注](annotations/README.md)
