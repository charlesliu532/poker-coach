import re, time
from pathlib import Path
from faster_whisper import WhisperModel

SRC = Path.home()/"Downloads"
OUT = Path("data/transcripts"); OUT.mkdir(parents=True, exist_ok=True)

def num(f):
    m = re.match(r'(\d+)', f.name)
    return int(m.group(1)) if m else 99

files = [f for f in SRC.glob("*.mp4") if not f.name.startswith("QY")]
files.sort(key=num)
print("待转写：", [f.name for f in files], flush=True)
m = WhisperModel("small", device="cpu", compute_type="int8")
for f in files:
    dst = OUT/(f.stem.replace(" ", "_") + ".txt")
    if dst.exists() and dst.stat().st_size > 500:
        print("跳过", dst.name, flush=True); continue
    t0=time.time()
    segs,_ = m.transcribe(str(f), language="zh", vad_filter=True, beam_size=1,
                          condition_on_previous_text=False)
    lines=[]
    for s in segs:
        sec=int(s.start); lines.append(f"[{sec//60:02d}:{sec%60:02d}] {s.text.strip()}")
    dst.write_text("\n".join(lines), encoding="utf-8")
    print(f"完成 {f.name} -> {dst.name} 片段 {len(lines)} 用时 {time.time()-t0:.0f}s", flush=True)
print("TOYS_DONE", flush=True)
