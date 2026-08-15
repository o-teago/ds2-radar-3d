# -*- coding: utf-8 -*-
"""
POINTER SCAN fase 2 — VALIDAR as cadeias APOS REINICIAR o jogo.

Le pointer_chains.txt, resolve cada cadeia com o eboot_base NOVO, e mantem
as que ainda caem num bloco de posicao valido E que ACOMPANHAM o player
quando voce anda. O que sobreviver = offset PERMANENTE.

Resolver(base, static_off, offs):
    a = base + static_off
    for o in offs: a = read_u64(a) + o
    return a

Fases:
  1  resolve todas as cadeias -> mantem as que dao [~1.0, X, Y, Z] plausivel
  2  ANDE EM CIRCULOS ~15s -> mantem as que se movem SUAVE (acompanham voce)
Precisa: PS4CheaterNeo FECHADO. Salva em pointer_final.txt
"""
import asyncio, struct, threading, queue, os, time, re
import tkinter as tk

PS4_IP = "192.168.1.104"
_DIR   = os.path.dirname(os.path.abspath(__file__))
SRC    = os.path.join(_DIR, "pointer_chains.txt")
OUT    = os.path.join(_DIR, "pointer_final.txt")
LIVE_S = 16
W,H = 740,520
msg_q = queue.Queue()

def parse_chains():
    chains=[]
    with open(SRC,encoding="utf-8") as f:
        for ln in f:
            m=re.match(r"\s*0x([0-9A-Fa-f]+)\s*\|\s*([0-9xA-Fa-f ]+?)(?:\s+\(root|$)", ln)
            if not m: continue
            so=int(m.group(1),16)
            offs=[int(o,16) for o in m.group(2).split()]
            if offs: chains.append((so,offs))
    return chains

async def ru64(ps4,pid,a):
    d=await ps4.read_memory(pid,a,8)
    if isinstance(d,tuple): d=d[-1]
    if not d or len(d)<8: return None
    return struct.unpack("<Q",d[:8])[0]

async def resolve(ps4,pid,base,so,offs):
    a=base+so
    for o in offs:
        v=await ru64(ps4,pid,a)
        if v is None or v<0x10000 or v>0x800000000: return None
        a=v+o
    return a

async def readpos(ps4,pid,a):
    d=await ps4.read_memory(pid,a,16)        # nosso bloco: [1.0, X, Y, Z]
    if isinstance(d,tuple): d=d[-1]
    if not d or len(d)<16: return None
    w,x,y,z=struct.unpack("<4f",d[:16])
    return (w,x,y,z)

def plausible(p):
    if not p: return False
    w,x,y,z=p
    return 0.9<w<1.1 and all(abs(v)<3000 for v in (x,y,z)) and any(abs(v)>0.01 for v in (x,y,z))

def worker():
    try:
        import ps4debug
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        chains=parse_chains()
        msg_q.put(("info",f"cadeias lidas: {len(chains)}"))
        ps4=ps4debug.PS4Debug(PS4_IP)
        if asyncio.iscoroutine(ps4): ps4=loop.run_until_complete(ps4)
        procs=loop.run_until_complete(ps4.get_processes())
        pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
        if pid is None: msg_q.put(("err","DS2 nao encontrado")); return
        maps=loop.run_until_complete(ps4.get_process_maps(pid))
        exe=[m.start for m in maps if 'executable' in str(getattr(m,'name','') or '')]
        base=min(exe) if exe else 0x400000       # MESMO metodo do pointer_scan (consistente!)
        msg_q.put(("info",f"eboot_base novo=0x{base:X}"))

        # FASE 1: resolve + filtra validas (guarda o endereco resolvido)
        valid=[]
        for i,(so,offs) in enumerate(chains):
            if i%25==0: msg_q.put(("phase",("FASE 1: RESOLVENDO",f"{i}/{len(chains)}",f"validas={len(valid)}",0)))
            a=loop.run_until_complete(resolve(ps4,pid,base,so,offs))
            if a is None: continue
            p=loop.run_until_complete(readpos(ps4,pid,a))
            if plausible(p): valid.append((so,offs,a))
        msg_q.put(("info",f"validas apos reboot: {len(valid)}"))
        if not valid:
            open(OUT,"w").write("0 cadeias validas apos reboot\n"); msg_q.put(("done","0 validas - cadeias quebraram")); return

        # FASE 2: ao vivo — so RE-LE os enderecos UNICOS (rapido) enquanto anda
        addrs=sorted(set(a for _,_,a in valid))
        hist={a:[] for a in addrs}
        t0=time.time()
        while time.time()-t0<LIVE_S:
            left=int(LIVE_S-(time.time()-t0))+1
            msg_q.put(("phase",("FASE 2: ANDE EM CIRCULOS",f"sem parar {left}s",f"enderecos={len(addrs)}",0)))
            for a in addrs:
                p=loop.run_until_complete(readpos(ps4,pid,a))
                hist[a].append((p[1],p[2],p[3]) if plausible(p) else None)
            time.sleep(0.12)

        # quais ENDERECOS se moveram suave (= o bloco vivo)
        moving={}
        for a in addrs:
            seq=[v for v in hist[a] if v]
            if len(seq)<6: continue
            steps=[((seq[j][0]-seq[j-1][0])**2+(seq[j][2]-seq[j-1][2])**2)**0.5 for j in range(1,len(seq))]
            path=sum(s for s in steps if s<10); mx=max(steps) if steps else 0
            if path>2.0 and mx<25 and len(seq)>=0.5*len(hist[a]):
                moving[a]=(path,seq[-1])
        msg_q.put(("info",f"enderecos que se moveram: {len(moving)}"))
        surv=[(len(offs),so,offs,moving[a][0],moving[a][1]) for so,offs,a in valid if a in moving]
        surv.sort()   # menos offsets primeiro (cadeia mais curta = melhor)
        with open(OUT,"w",encoding="utf-8") as fp:
            fp.write(f"eboot_base=0x{base:X}\nsobreviventes (acompanham o player): {len(surv)}\n")
            fp.write("formato: static_off | offsets   (mais curta = melhor)\n\n")
            for n,so,offs,path,last in surv[:60]:
                fp.write(f"0x{so:X} | "+" ".join(f"0x{o:X}" for o in offs)+
                         f"   mov={path:.0f} pos=({last[0]:.0f},{last[1]:.0f},{last[2]:.0f})\n")
        if surv: msg_q.put(("done",f"{len(surv)} sobreviventes! menor: 0x{surv[0][1]:X} | "+" ".join(f'0x{o:X}' for o in surv[0][2])))
        else: msg_q.put(("done","0 acompanharam - repita andando mais"))
    except Exception as e:
        import traceback; msg_q.put(("err",f"{e}|{traceback.format_exc()[:200]}"))

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("DS2 - Pointer Scan (fase 2: validar)"); self.root.configure(bg="#101216")
        self.root.geometry(f"{W}x{H}+60+50")
        self.cv=tk.Canvas(self.root,width=W,height=H,bg="#101216",highlightthickness=0); self.cv.pack()
        self.state=("CONECTANDO...","","",0); self.info=""; self.done=False
        threading.Thread(target=worker,daemon=True).start(); self.tick(); self.root.mainloop()
    def tick(self):
        while True:
            try:k,p=msg_q.get_nowait()
            except queue.Empty:break
            if k=="phase":self.state=p
            elif k=="info":self.info=str(p)
            elif k=="done":self.state=("PRONTO!",str(p)[:56],"veja pointer_final.txt",0);self.done=True
            elif k=="err":self.state=("ERRO",str(p)[:64],"",0)
        self.draw();self.root.after(100,self.tick)
    def draw(self):
        cv=self.cv;cv.delete("all");t,l1,l2,s=self.state
        col="#3fd07f" if self.done else "#ffd23f"
        cv.create_text(W/2,110,text=t,fill=col,font=("Consolas",20,"bold"))
        cv.create_text(W/2,185,text=l1,fill="#e8eefc",font=("Consolas",16,"bold"))
        cv.create_text(W/2,228,text=l2,fill="#9fb0cc",font=("Consolas",13))
        cv.create_text(W/2,H-28,text=self.info,fill="#5b6b86",font=("Consolas",10))

if __name__=="__main__":
    UI()
