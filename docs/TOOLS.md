# 当前工具

## 仍在使用

- FFmpeg：制作 16 kHz 分析副本；原采样率人声保留用于导出。
- audio-separator / Mel-Band RoFormer：抽取人声，模型为 `mel_band_roformer_kim_ft2_bleedless_unwa.ckpt`。默认 fp16 推理：在 RTX 4060 Laptop 上用同一段 3 分钟音频实测，fp16 比 fp32 快约 1.6 倍，与 fp32 输出的信噪比 73.5 dB，远在听感之下；bf16 更慢且差 15.6 dB，不选。换显卡架构需重测；怀疑分离伪影时用 `--precision fp32` 对照。
- pyannote community-1：只在字幕偏移未知时提取说话时间线；WeSpeaker 适配也依赖它。
- [ReDimNet2](https://github.com/PalabraAI/redimnet2)：当前声纹。通过 torch.hub 加载官方代码和模型。
- [anime_speaker_embedding](https://github.com/litagin02/anime_speaker_embedding)：动画域声纹，ECAPA-TDNN 把 BatchNorm 换成 GroupNorm，约 700 万条视觉小说音频上训练，MIT 许可，192 维，输入 16 kHz 单声道。两个变体：`anime-char` 按角色（7357 个），`anime-va` 按声优（989 位）。实测 `va` 更好，见 EXPERIMENTS。**它的相似度尺度和 VoxCeleb 系模型不同**，同人相似度中位 0.337 对 ReDimNet 的 0.541，阈值必须单独扫，别照搬。包里的 `get_embedding` 只收文件路径，我们绕开它直接喂数组，避免每条片段写临时文件。
- [WeSpeaker ResNet293](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet293-LM)：身份对照模型，两集全量缓存已完成，当前 Windows 用 CPU 后端。
- scikit-learn：全局分组与身份指标，已明确列为直接依赖。
- soundfile、pyloudnorm、pandas/pyarrow：读取原采样率音轨、响度处理、保存来源表。
- pysubs2、Typer：字幕与命令行。

Windows torch/torchaudio 使用 CUDA 12.8，Linux CI 使用 CPU 轮子；由锁文件选择。pyannote 从波形张量读取，避开 Windows torchcodec 的 FFmpeg DLL 问题。`audioread` 是 audio-separator 未声明但实际需要的依赖，保留。

实际版本以 `pyproject.toml` 和 `uv.lock` 为准。ReDimNet2 的 torch.hub 仓库代码不在 Python 锁文件中；升级模型或远程代码后，旧距离设置与缓存不能未经核验继续比较。

## 后置研究线索

- [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)：降噪线索。
- [ClearerVoice-Studio](https://github.com/modelscope/ClearerVoice-Studio)：语音增强与分离线索。
- [VoiceFilter](https://google.github.io/speaker-id/publications/VoiceFilter/)：目标说话人提取线索。

- 片段内多窗口声纹离散度（曾命名 `selfsim_spread`）：检测一条片段里是否混入第二个人。曾在第 1 集 34 条人工标注上做过时长配平对照，有信号但样本过小、无法定论；代码已随质量路线删除。以后处理多人片段时可重做，需要重新实现并用新标签验证。
- voxmap-studio（2026，开源）：人工修改分组的现成界面候选，支持拆分、合并、重指派和跨文件统一编号。仅调研过论文，未找到代码也未试用。

这些仅是旧调研留下的入口，不是已验证选型或当前执行计划；启用前重新核查。普通降噪不能等同于识别并去掉另一个角色的语气词。
