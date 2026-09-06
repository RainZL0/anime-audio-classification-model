# anime-voice-sorter

按字幕切出动画对白，再把同一角色的声音归到一起。**先完成说话人分类，偶发语气词和噪声后置。** 不按音质排名丢掉一半，也不把小组混进一个杂物桶。

流程已跑通，分组仍需改善。进度、结论和下一步统一见 [项目现状](docs/STATUS.md)，名词解释见 [流程与名词](docs/HOW_IT_WORKS.md#名词表)；本页只写怎么用。

## 装好

需要 FFmpeg 在 PATH 里。GPU 环境和各模型说明见 [工具](docs/TOOLS.md)。

```powershell
uv sync --locked
uv run avs doctor
```

`uv run avs --help` 列出全部命令。

## 处理新的一集

```powershell
uv run avs prepare data/raw/uma_s2_04.flac --subs "data/ass/uma/[FLsnow][UmamusumeS2][04][HEVC_FLAC][BDRIP].chs.ass" --name ep04 --out runs/episodes/ep04 --offset -0.96
uv run avs embed runs/episodes/ep04
uv run avs coverage runs/episodes/ep04 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][04][HEVC_FLAC][BDRIP].chs.ass" --out runs/coverage/ep04
```

`prepare` 分离整集人声并按每条字幕行切片段。**建议直接给 `--offset`**：同一片源同一字幕组的偏移是稳定的（第 1 至 3 集实测 -0.95、-0.96、-0.96），给了就完全不跑语音检测；省略时才用说话时间线自动量，吻合度太低会报错。

`coverage` 用来验收切得对不对：按字幕行切的话，「有片段的对白行」应该等于对白行总数（第 3 集是 375/375）。它顺便把没有片段的台词切成音频放在 `below_floor`（行本身太短）和 `no_speech_found`（行够长却没切出）两个目录，另出 `lines.txt` 和 `report.json`。

## 分组、打分、导出

```powershell
uv run avs group runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --out runs/groups/uma-next.json
uv run avs evaluate runs/groups/uma-next.json --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --out runs/groups/uma-next-evaluation.json
uv run avs export runs/groups/uma-next.json --out out/uma-next
```

`group` 不指定 `--threshold` 时用该模型自己的默认分界线并把它打印出来。`--model` 可选 `anime-va`（默认）、`redimnet2-b6`、`anime-char`、`wespeaker-resnet293`；**换模型必须重新扫分界线**，不同模型的相似度刻度不通用。

`--method` 除默认的 `average`（按整组平均距离合并）外还有 `single`、`complete`、`mutual_knn`、`two_stage`，都已实测不如 `average`，留着只为可复算。

分组文件和导出目录每次用新名字，免得旧音频混进新结果。导出回到原采样率人声轨，16 kHz 副本只用于分析；没有声纹的片段留在 `_unassigned`，不会被悄悄丢掉。

## 标注

```powershell
uv run avs label runs/episodes/ep04 --archive annotations/ep04-full.json --all --known annotations/ep03-full.json --known annotations/names.json --video "D:/_Search/_Animation/uma/[DHR][Uma Musume S2][04][BIG5][1080P][HEVC_AAC].mp4"
```

对照画面报名字，每条按下就存进人工归档。不是凭记忆听音分组。

- `--all`：标这一集全部片段，按时间顺序连着走。整集连着标比抽样省力，因为顺着画面往下看，不用为每条重新定位。不给 `--all` 就随机抽 `--count` 条。片段表后来补进新片段时，再跑一次 `--all` 会把它们以空标签追加到已有归档，已标的一条不动。
- `--known`：页面上可点的角色名从哪来，可以重复给。给人工归档时，那里面的片段还能在页面上回放，用来想起某个名字是谁；给 `annotations/names.json` 这种只有名字的词表就只有名字。名字按出现条数排序，数字键 1 至 9 对应前九个。
- `--video`：放当前片段对应的画面，前后各多给 0.5 秒。按需现切，翻到哪条才用 ffmpeg 切哪条（一段两三秒实测不到半秒），同时预热下一条。源片多是 HEVC，浏览器支不支持看机器，所以统一转成 360p 的 H.264，存在 `runs/episodes/<集>/label_audio/<归档名>/video/`，一集约 46 MB。

  **视频和音轨必须是同一条时间线。** 本项目 `data/raw/*.flac` 就是从这些 mp4 里抽的，时长精确一致、波形对齐位移 0 毫秒，所以片段时间可以直接当视频时间用。换片源前先核对，否则画面会对错人。

页面上角色名排成小块，点一下就给当前片段打标。`__multiple__` 这类特殊标签也成块显示，否则标成「不止一个人」的片段就再也翻不出来复核。

名字右边的数字打开面板，里面按集和时间列出这个名字下的全部片段：本轮的点一下跳过去，旧归档里的点一下就地试听（用单独的播放器，不打断正在标的那条）。面板里可以改名、整批撤掉标签，**也可以把某一条片段直接拖到另一个名字上改归属**，包括拖到特殊标签上。整集标完回头核对时，改错一条不必重新定位重听。

在筛名字框里敲一个新名字，点「＋ 建这个名字」就能先把名字建出来再往上拖。建了没用到的名字和从列表里删掉的名字都只影响当前页面，不落盘——真正用到的名字已经在归档里。

**页面始终不显示机器分组、组号或候选归属。** 看过机器的答案，标出来的就不再是独立的真值。

试听旧标签只用来想起某个名字是谁，判断仍以画面为准。

## 补片段

```powershell
uv run avs extend runs/episodes/ep02 --subtitle "data/ass/uma/[FLsnow][UmamusumeS2][02][HEVC_FLAC][BDRIP].chs.ass"
uv run avs embed runs/episodes/ep02
```

把字幕里没有对应片段的对白行补进片段表。片段 ID 是集名加起止时间的哈希，**只增不改，已有标签照旧有效**。补完片段表变了，声纹缓存失效，要重跑 `embed`。

补进来的行里必然混着解说、群体欢呼这类不属于任何角色的声音。这里不猜，统一收进来，由人在标注时打上「不是说话」之类的标签。

## 对照实验

扫分界线，比模型和合并规则：

```powershell
uv run avs compare runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --model redimnet2-b6 --method average --low 0.25 --high 1.15 --out runs/comparison-next.json
```

会先核验各模型覆盖同一批片段。`--low` / `--high` 必须按模型的相似度刻度给，默认的 0.20 至 0.90 是给 `redimnet2-b6` 定的，对 `anime-va` 几乎全无意义。用人工标签挑出来的分界线只能算探索，要另找一份没参与过的数据检验。

只比同一角色和不同角色的配对分不分得开，不做分组：

```powershell
uv run avs scores runs/episodes/ep03 --annotation annotations/ep03-full.json --model anime-va --norm none --out runs/score-next.json
```

报告给排序正确率和相等错误率，按片段时长和是否跨集分层。`--norm` 可重复（`none` / `snorm` / `asnorm`），后两个是分数归一化，已实测无效。`--window` 读用别的最小音频长度算出的声纹。

近邻检索与距离分布：

```powershell
uv run avs diagnose runs/episodes/ep01 runs/episodes/ep02 runs/episodes/ep03 --annotation annotations/ep01-full.json --annotation annotations/ep02-full.json --annotation annotations/ep03-full.json --groups runs/groups/uma3.json --out runs/diagnosis-next
```

输出报告、全部标签配对的距离，以及 `examples/` 下可试听的错误实例。近邻检索排除查询自身；只有一条标签的角色不作为提问对象，但留在候选池里当陪衬；没有名字的近邻只算线索。

`avs embed --window` 给短片段向两侧借相邻音频补到指定长度，片段本身的时间范围不变。不同长度的声纹存在不同目录（`embeddings/<模型>@w<秒数>`），互不覆盖。已实测无效，留着可复算。

`avs references` 和 `avs label-plan` 属于已关闭的路线（少量身份参考、只标候选改动过的片段），留着可复算，不要作为当前做法。

[文档导航](docs/README.md) · [人工标注](annotations/README.md)
