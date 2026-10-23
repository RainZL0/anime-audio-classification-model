import { useEffect, useRef, useState, type RefObject, type SyntheticEvent } from "react";
import { media, type Clip, type Roles } from "../api";
import { lowTip, OTHER, type LabelText } from "../clips";
import { pct, stamp } from "../format";
import { tr } from "../language";
import { SPEEDS, VIDEO_PAD, type Sound } from "../playback";
import { Avatar } from "./Avatar";
import { RoleName } from "./RoleName";

interface StageProps {
  clip: Clip | null;
  roles: Roles;
  labelText: LabelText;
  sound: Sound;
  setSound: (sound: Sound) => void;
  speed: number;
  setSpeed: (speed: number) => void;
  onAssign: (name: string, low?: boolean) => void;
  onAccept: () => void;
  onPlayRef: (name: string) => void;
  hasVideo: boolean;
  /* The player on the stage: the video, or the vocals when there is no video. */
  videoRef: RefObject<HTMLMediaElement | null>;
  onAvatar: (name: string) => void;
  onNewRole: () => void;
  onClear: () => void;
  context: number;
  onContext: () => void;
  dock: string[];
}

/* ───────────── Stage: picture, line, who is it ───────────── */

export function Stage({
  clip,
  roles,
  labelText,
  sound,
  setSound,
  speed,
  setSpeed,
  onAssign,
  onAccept,
  onPlayRef,
  hasVideo,
  videoRef,
  onAvatar,
  onNewRole,
  onClear,
  context,
  onContext,
  dock,
}: StageProps) {
  const [loading, setLoading] = useState(true);
  /* The number key of each of the first 9 characters in the bottom bar; Shift + it is that character, low quality. */
  const slot = (name: string) => {
    const i = dock.indexOf(name);
    return i >= 0 && i < 9 ? i + 1 : null;
  };
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startVoice = useRef(0);
  useEffect(() => {
    setLoading(true);
    return () => clearTimeout(startVoice.current);
  }, [clip?.id, sound, context]);
  /* On a new clip the player resets its speed to defaultPlaybackRate, so set both. */
  useEffect(() => {
    for (const el of [videoRef.current, audioRef.current]) {
      if (el) {
        el.defaultPlaybackRate = speed;
        el.playbackRate = speed;
      }
    }
  }, [speed, clip?.id, sound, context, videoRef]);

  if (!clip) {
    return (
      <aside className="stage">
        <div className="screen">
          <div className="wait">{tr("在右边选一句台词", "Pick a line on the right")}</div>
        </div>
      </aside>
    );
  }
  const vocals = hasVideo && sound === "vocals";
  /* With vocals only, the picture plays muted and the separated vocals play instead, following the picture's
     play, pause and seek. The video clip starts VIDEO_PAD seconds before the line (less at the very start of an
     episode), so the vocals wait until the picture reaches the line. With extra context the vocals were cut
     with the same extra seconds, so both start at the same moment. */
  const follow = (e: SyntheticEvent<HTMLVideoElement>) => {
    const voice = audioRef.current;
    if (!vocals || !voice) return;
    clearTimeout(startVoice.current);
    const at = e.currentTarget.currentTime - (context ? 0 : Math.min(VIDEO_PAD, clip.start));
    voice.currentTime = Math.max(0, at);
    if (e.currentTarget.paused) voice.pause();
    else if (at >= 0) voice.play().catch(() => {});
    else {
      voice.pause();
      startVoice.current = setTimeout(() => voice.play().catch(() => {}), (-at * 1000) / speed);
    }
  };
  const isOther = !!clip.label && !!labelText[clip.label];
  const label = clip.label;
  return (
    <aside className="stage">
      <div className="screen">
        {hasVideo ? (
          <>
            <video
              ref={(el) => {
                videoRef.current = el;
              }}
              key={`${clip.id}-${sound}-${context}`}
              src={media("video", clip.id, context)}
              autoPlay
              playsInline
              muted={vocals}
              onCanPlay={() => setLoading(false)}
              onClick={(e) => {
                e.currentTarget.currentTime = 0;
                e.currentTarget.play();
              }}
              onPlay={follow}
              onPause={follow}
              onSeeked={follow}
            ></video>
            {vocals && (
              <audio
                ref={audioRef}
                key={`v-${clip.id}-${context}`}
                src={media("audio", clip.id, context)}
                preload="auto"
              ></audio>
            )}
          </>
        ) : (
          <>
            <div className="wait">
              {tr("这一集没有视频，只有人声", "This episode has no video, only vocals")}
            </div>
            <audio
              ref={(el) => {
                audioRef.current = el;
                videoRef.current = el;
              }}
              key={`${clip.id}-${context}`}
              src={media("audio", clip.id, context)}
              autoPlay
              onCanPlay={() => setLoading(false)}
            ></audio>
          </>
        )}
        <div className={`wait ${!hasVideo || !loading ? "hide" : ""}`}>
          <div className="spinner"></div>
        </div>
      </div>
      <div className="player">
        {hasVideo && (
          <span className="seg">
            <button className={sound === "vocals" ? "on" : ""} onClick={() => setSound("vocals")}>
              {tr("只听人声", "Vocals only")}
            </button>
            <button
              className={sound === "original" ? "on" : ""}
              onClick={() => setSound("original")}
            >
              {tr("画面原声", "Original sound")}
            </button>
          </span>
        )}
        <span
          className="seg"
          title={tr("播放速度，参考音也一样快", "Playback speed, also used for reference clips")}
        >
          {SPEEDS.map((s) => (
            <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </span>
      </div>
      <div className="line-text">
        {clip.text || (
          <span style={{ color: "var(--text-3)" }}>
            {tr("（字幕里没有这句的文字）", "(no text for this line in the subtitles)")}
          </span>
        )}
      </div>
      <div className="line-meta">
        <span>{clip.episode}</span>
        <span>{stamp(clip.start)}</span>
        <span>{tr(`${clip.duration.toFixed(2)} 秒`, `${clip.duration.toFixed(2)} s`)}</span>
        <button
          className={`context ${context ? "on" : ""}`}
          onClick={onContext}
          title={tr(
            "看不出是谁时，临时前后各多放一些；再按切到 15 秒、再按回到平常。换一句自动回到平常",
            "When you can't tell who it is, play a bit more on each side. Press again for 15 seconds, again for normal. Moving to another line goes back to normal",
          )}
        >
          {context
            ? tr(`前后多放 ${context} 秒`, `±${context} s`)
            : tr("多放前后文", "More context")}{" "}
          <kbd>L</kbd>
        </button>
      </div>

      {label ? (
        <>
          <div className="ask">{tr("已经确认", "Confirmed")}</div>
          <div className="confirmed-box">
            <Avatar
              role={roles[label]}
              name={label}
              blank={isOther}
              size="lg"
              onClick={!isOther && hasVideo ? () => onAvatar(label) : null}
              title={tr("从画面里截一块当头像", "Crop an avatar from the picture")}
            />
            <div>
              <div className="who">
                {isOther ? labelText[label] : <RoleName role={roles[label]} name={label} />}
                {clip.unusable && !labelText[label] && (
                  <>
                    {" "}
                    <span className="pill unusable" title={lowTip()}>
                      {tr("质量低", "Low quality")}
                    </span>
                  </>
                )}
              </div>
              <div style={{ fontSize: "12px" }}>
                {tr(
                  "要改的话，直接按别的数字键或在下面选；Shift + 数字是质量低",
                  "To change it, press another number key or pick below. Shift + number means low quality",
                )}
              </div>
            </div>
            <span className="actions">
              <button
                className="ghost"
                title={tr(
                  "清掉这句的标签，回到机器的猜测",
                  "Clear this line's label and go back to the machine's guess",
                )}
                onClick={onClear}
              >
                {tr("清掉标签", "Clear label")} <kbd>Backspace</kbd>
              </button>
            </span>
          </div>
        </>
      ) : (
        <>
          <div className="ask">
            {clip.guess.length
              ? tr("这是谁？机器的猜测", "Who is this? The machine's guesses")
              : clip.voiced
                ? tr("这是谁？", "Who is this?")
                : tr(
                    "这句太短，机器听不出来，请直接选人",
                    "Too short for the machine to tell. Pick the character yourself",
                  )}
          </div>
          {clip.familiar === false && (
            <div className="stranger">
              {tr(
                <>
                  跟已经确认过的角色都不太像，可能是还没标过的人。是新角色就按 <kbd>N</kbd>{" "}
                  新建，名字以后再起也行。
                </>,
                <>
                  Not much like any confirmed character, so it may be someone not labeled yet. If it
                  is a new character, press <kbd>N</kbd>; you can name it later.
                </>,
              )}
            </div>
          )}
          {clip.familiar === null && clip.guess.length > 0 && (
            <div className="stranger early">
              {tr(
                <>
                  机器现在只会在底部这几个角色里挑。都不是就按 <kbd>N</kbd> 新建；确认满 20
                  句后，它会自己提醒你哪句像新面孔。
                </>,
                <>
                  For now the machine only picks among the characters at the bottom. If it is none
                  of them, press <kbd>N</kbd>. After 20 confirmed lines it will point out lines that
                  sound like someone new.
                </>,
              )}
            </div>
          )}
          <div className="cands">
            {clip.guess
              .filter((g) => g.p >= 0.02 || g === clip.guess[0])
              .map((g, i) => {
                const k = slot(g.name);
                return (
                  <div
                    key={g.name}
                    className={`cand ${i === 0 ? "top" : ""}`}
                    onClick={() => onAssign(g.name)}
                  >
                    <Avatar role={roles[g.name]} name={g.name} blank={g.name === OTHER} size="md" />
                    <div className="name">
                      {g.name === OTHER ? (
                        labelText[OTHER]
                      ) : (
                        <RoleName role={roles[g.name]} name={g.name} />
                      )}
                    </div>
                    {g.name !== OTHER && (
                      <button
                        className="ref"
                        title={tr(
                          "听这个角色确认过的一句",
                          "Hear a confirmed line of this character",
                        )}
                        onClick={(e) => {
                          e.stopPropagation();
                          onPlayRef(g.name);
                        }}
                      >
                        {tr("参考音", "Reference")}
                        {i === 0 ? (
                          <>
                            {" "}
                            <kbd>R</kbd>
                          </>
                        ) : (
                          ""
                        )}
                      </button>
                    )}
                    {g.name !== OTHER && (
                      <button
                        className="low"
                        title={
                          tr(`标成 ${g.name}·质量低：`, `Label as ${g.name}, low quality: `) +
                          lowTip()
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          onAssign(g.name, true);
                        }}
                      >
                        {tr("质量低", "Low quality")}
                        {k ? (
                          <>
                            {" "}
                            <span className="k">⇧{k}</span>
                          </>
                        ) : (
                          ""
                        )}
                      </button>
                    )}
                    <span className="pct">{pct(g.p)}</span>
                    <div className="meter">
                      <i style={{ width: pct(g.p) }}></i>
                    </div>
                  </div>
                );
              })}
          </div>
          <div
            style={{
              marginTop: "10px",
              display: "flex",
              gap: "8px",
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {clip.guess.length > 0 && (
              <button className="primary" onClick={onAccept}>
                {tr("是", "It's")} {labelText[clip.guess[0].name] || clip.guess[0].name}
                <kbd style={{ marginLeft: "4px" }}>Enter</kbd>
              </button>
            )}
            <button
              onClick={onNewRole}
              title={tr(
                "新建一个目标角色，名字可以以后再起；有画面时接着截头像",
                "Make a new target character; you can name it later. With video, crop an avatar next",
              )}
            >
              {tr("新角色", "New character")} <kbd style={{ marginLeft: "4px" }}>N</kbd>
            </button>
            <span style={{ fontSize: "12px", color: "var(--text-3)" }}>
              {tr(
                "已有的人按数字键，或点底部的头像",
                "Existing characters: number keys, or click an avatar at the bottom",
              )}
            </span>
          </div>
        </>
      )}

      <div className="hint">
        {tr(
          <>
            <kbd>J</kbd> <kbd>K</kbd> 上下一句 · <kbd>空格</kbd> 重播 · <kbd>1</kbd>–<kbd>9</kbd>{" "}
            选下面的角色 ·<kbd>N</kbd> 新角色 · <kbd>Z</kbd> 撤销 · <kbd>?</kbd> 全部快捷键
          </>,
          <>
            <kbd>J</kbd> <kbd>K</kbd> next / previous · <kbd>Space</kbd> replay · <kbd>1</kbd>–
            <kbd>9</kbd> pick a character below ·<kbd>N</kbd> new character · <kbd>Z</kbd> undo ·{" "}
            <kbd>?</kbd> all shortcuts
          </>,
        )}
      </div>
    </aside>
  );
}
