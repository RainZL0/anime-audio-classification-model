# 依赖、模型和运行环境

实际版本以 `pyproject.toml` 和 `uv.lock` 为准。各模型实测谁好谁坏见 [EXPERIMENTS.md](EXPERIMENTS.md)，这里只说它们是什么、怎么接进来。

## 音频处理

- **FFmpeg**：制作 16 kHz 分析副本；标注页按需切视频画面并转成 360p H.264。原采样率人声保留给导出用。
- **audio-separator / Mel-Band RoFormer**：抽人声，模型文件 `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`。默认 fp16：在 RTX 4060 Laptop 上用同一段 3 分钟音频实测，比 fp32 快约 1.6 倍，与 fp32 输出的信噪比 73.5 dB，远在听感之下；bf16 更慢且差 15.6 dB，不选。换显卡架构要重测；怀疑分离伪影时用 `--precision fp32` 对照。`audioread` 是它没声明但实际需要的依赖，保留。
- **pyannote community-1**：只在没给 `--offset` 时用来量字幕偏移；WeSpeaker 适配也依赖它。从波形张量读取，避开 Windows torchcodec 的 FFmpeg DLL 问题。
- soundfile、pyloudnorm、pandas/pyarrow：读原采样率音轨、响度处理、保存来源表。pysubs2、Typer：字幕与命令行。scikit-learn：分组、打分指标和界面里的小分类器。

## 声纹模型

| 命令行名字 | 来源 | 现状 |
| --- | --- | --- |
| `anime-va` | [anime_speaker_embedding](https://github.com/litagin02/anime_speaker_embedding) 按声优训练的变体（989 位声优） | 分组的默认；界面里三个拼用 |
| `anime-char` | 同上，按角色训练的变体（7357 个角色） | 界面里三个拼用 |
| `redimnet2-b6` | [ReDimNet2](https://github.com/PalabraAI/redimnet2)，只在 VoxCeleb2 上训练的默认变体 | 界面里三个拼用；2026-09-07 前是分组的默认 |
| `wespeaker-resnet293` | [WeSpeaker ResNet293](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet293-LM) | 已排除，Windows 上用 CPU |

- **anime_speaker_embedding**：ECAPA-TDNN 把 BatchNorm 换成 GroupNorm，约 700 万条视觉小说音频上训练，MIT 许可，192 维，输入 16 kHz 单声道。包里的 `get_embedding` 只收文件路径，我们绕开它直接喂数组，免得每条片段写临时文件。
- **ReDimNet2**：通过 torch.hub 加载官方代码和模型。官方还有 `vb2+vox2`、`vb2+vox2+cnc2` 两个跨库更好的变体，没试过。torch.hub 的远程代码不在锁文件里；升级模型或远程代码后，旧的分界线和缓存不能未经核验继续比较。
- 不同模型的相似度刻度不一样，分界线各自扫，见 [DECISIONS.md](DECISIONS.md#已经定下的)。

## 界面

- **FastAPI + uvicorn**：`avs app` 的网页服务，只在 127.0.0.1 上监听。
- **Preact + htm**：前端，用 htm 3.1.1 的单文件版（`src/avs/app/static/vendor/preact-htm.js`，Apache-2.0，许可放在同目录），不需要 Node 和打包工具。
- 测试用 httpx 驱动 FastAPI 的测试客户端。

## 运行环境

Windows 上 torch/torchaudio 用 CUDA 12.8，Linux CI 用 CPU 轮子，由锁文件选择。

## 以后可能用的线索

只是旧调研留下的入口，不是已验证的选型，也不是当前计划，启用前重新核查。

- [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)：降噪。
- [ClearerVoice-Studio](https://github.com/modelscope/ClearerVoice-Studio)：语音增强与分离。
- [VoiceFilter](https://google.github.io/speaker-id/publications/VoiceFilter/)：只提取指定说话人的声音。
- 片段内多窗口声纹的离散程度（曾叫 `selfsim_spread`）：检测一条片段里是否混入第二个人。曾在第 1 集 34 条人工标注上做过时长配平对照，有信号但样本太小、无法定论；代码已删，以后处理多人片段时要重新实现并用新标签验证。
- voxmap-studio（2026，开源）：人工修改分组的现成界面，支持拆分、合并、重新指派和跨文件统一编号。只看过论文，没找到代码也没试用。
