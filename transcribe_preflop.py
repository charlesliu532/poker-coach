import re, time
from pathlib import Path
from faster_whisper import WhisperModel

SRC = Path.home()/"Downloads"
OUT = Path("data/transcripts"); OUT.mkdir(parents=True, exist_ok=True)

def prio(f):
    n = f.name
    if n.startswith("0 "): return (0, 0)
    m = re.match(r'(\d{2})-(\d{2})', n)
    if m:
        mod = int(m.group(1)); idx = int(m.group(2))
        order = {2: 1, 3: 2, 4: 3}          # 先 GTO 基准，再池剥削，再极端画像
        return (order.get(mod, 9), idx)
    return (8, 0)

files = sorted(SRC.glob("*压制.mp4"), key=prio)
print(f"待转写 {len(files)} 个：", [f.name[:40] for f in files[:6]], "...", flush=True)
m = WhisperModel("small", device="cpu", compute_type="int8")
done = 0
for f in files:
    dst = OUT/(f.stem.replace(" ", "_") + ".txt")
    if dst.exists() and dst.stat().st_size > 500:
        continue
    t0 = time.time()
    segs, _ = m.transcribe(str(f), language="zh", vad_filter=True, beam_size=1,
                           condition_on_previous_text=False)
    lines = []
    for s in segs:
        sec = int(s.start); lines.append(f"[{sec//60:02d}:{sec%60:02d}] {s.text.strip()}")
    dst.write_text("\n".join(lines), encoding="utf-8")
    done += 1
    print(f"[{done}/{len(files)}] {f.name[:44]} -> {dst.name} 片段 {len(lines)} {time.time()-t0:.0f}s", flush=True)
print("PREFLOP_DONE", flush=True)
