# -*- coding: utf-8 -*-
"""
Achador DEFINITIVO da posicao logica (heap normal).
Fases guiadas na tela:
  1 PARADO      -> le heap (S1)
  2 PARADO      -> le heap (S2)  -> mantem IGUAIS (estaveis parado)
  3 ANDE POUCO  -> le heap (S3)  -> mantem os que mudaram pouco (2..40) e sao coord plausivel
  4 ANDE SEM PARAR (ao vivo) -> le so os candidatos rapido -> quem segue SUAVE = VOCE
Salva o vencedor em winner.txt
"""
import asyncio, time, struct, threading, queue
import numpy as np
import tkinter as tk

PS4_IP = "192.168.1.104"
CHUNK  = 64*1024*1024
OUT    = "winner.txt"
MAXC   = 450          # teto de candidatos pra fase ao vivo
LIVE_S = 18
W,H = 720,520
msg_q = queue.Queue()

async def read_region(ps4,pid,start,size):
    buf=bytearray(); off=0
    while off<size:
        n=min(CHUNK,size-off)
        d=await ps4.read_memory(pid,start+off,n)
        if isinstance(d,tuple): d=d[-1]
        if not d: break
        buf+=d; off+=n
    return np.frombuffer(bytes(buf),dtype='<f4')

def triplets(arr):
    a=np.abs(arr); world=np.isfinite(arr)&(a>1.0)&(a<300.0)
    if len(world)<3: return np.array([],dtype=np.int64)
    t=world[:-2]&world[1:-1]&world[2:]; idx=np.nonzero(t)[0]
    if len(idx):
        v0,v1,v2=arr[idx],arr[idx+1],arr[idx+2]
        rnd=(v0*4==np.floor(v0*4))&(v1*4==np.floor(v1*4))&(v2*4==np.floor(v2*4))
        idx=idx[~rnd]
    return idx

def V(arr,idx): return np.stack([arr[idx],arr[idx+1],arr[idx+2]],axis=1)
def plausible(v):
    a=np.abs(v); return (a<250).all(axis=1)&(a.max(axis=1)>3)

def worker():
    try:
        import ps4debug
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        ps4=ps4debug.PS4Debug(PS4_IP)
        if asyncio.iscoroutine(ps4): ps4=loop.run_until_complete(ps4)
        procs=loop.run_until_complete(ps4.get_processes())
        pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
        if pid is None: msg_q.put(("err","DS2?")); return
        maps=loop.run_until_complete(ps4.get_process_maps(pid))
        regs=[(m.start,m.end-m.start) for m in maps
              if m.prot==0x3 and "anon" in (getattr(m,"name","") or "") and (m.end-m.start)>=4*1024*1024]

        def rd(title,sub,hold):
            for s in range(hold,0,-1):
                msg_q.put(("phase",(title,sub,"prepare...",s))); time.sleep(1)
            out={}
            for k,(rs,sz) in enumerate(regs):
                msg_q.put(("phase",(title+" LENDO","NAO SE MOVA",f"{k+1}/{len(regs)}",0)))
                out[rs]=loop.run_until_complete(read_region(ps4,pid,rs,sz))
            return out

        A=rd("FASE 1: PARADO","fique parado",5)
        idxA={rs:triplets(A[rs]) for rs in A}; vA={rs:V(A[rs],idxA[rs]) for rs in A}
        B=rd("FASE 2: PARADO","continue parado",2)
        stab={}
        for rs in idxA:
            idx=idxA[rs]; ok=idx+2<len(B[rs]); idx=idx[ok]; va=vA[rs][ok]
            vb=V(B[rs],idx); same=np.all(np.abs(va-vb)<0.05,axis=1)
            pl=plausible(va)
            m=same&pl; stab[rs]=(idx[m],va[m])
        nstab=sum(len(v[0]) for v in stab.values()); msg_q.put(("info",f"estaveis+plausiveis: {nstab}"))
        for s in range(8,0,-1):
            msg_q.put(("phase",("FASE 3: ANDE POUCO","de uns passos","e PARE",s))); time.sleep(1)
        C=rd("FASE 3: PARADO","fique parado",2)
        cands=[]
        for rs in stab:
            idx,vs=stab[rs]; ok=idx+2<len(C[rs]); idx=idx[ok]; vs=vs[ok]
            vc=V(C[rs],idx); d=np.sqrt(((vc-vs)**2).sum(axis=1))
            ch=np.abs(vc-vs); minch=ch.min(axis=1)
            keep=(d>1.5)&(d<40)&(minch<3.0)&plausible(vc)
            for j in np.nonzero(keep)[0]:
                cands.append((rs+int(idx[j])*4, float(d[j])))
        cands.sort(key=lambda c:abs(c[1]-8))  # prefere movimento ~passos
        cands=cands[:MAXC]
        msg_q.put(("info",f"candidatos p/ ao vivo: {len(cands)}"))
        if not cands:
            with open(OUT,"w") as fp: fp.write("nenhum candidato na fase 3\n")
            msg_q.put(("done","0 candidatos")); return

        # ---- FASE 4 AO VIVO ----
        hist={a:[] for a,_ in cands}
        t0=time.time()
        while time.time()-t0<LIVE_S:
            left=int(LIVE_S-(time.time()-t0))+1
            msg_q.put(("phase",("FASE 4: ANDE SEM PARAR",f"continue andando {left}s","rastreando...",0)))
            for a,_ in cands:
                try:
                    d=loop.run_until_complete(ps4.read_memory(pid,a,12))
                    if isinstance(d,tuple): d=d[-1]
                    if d and len(d)>=12:
                        hist[a].append(struct.unpack("<3f",d[:12]))
                except: pass
            time.sleep(0.4)
        # analise: caminho suave
        def score(seq):
            if len(seq)<4: return -1,0,0
            steps=[math_dist(seq[i],seq[i-1]) for i in range(1,len(seq))]
            mx=max(steps) if steps else 0
            path=sum(s for s in steps if s<10)
            if mx>25: return -1, path, mx     # pulou -> lixo
            if not all(np.isfinite(v).all() and (np.abs(v)<300).all() for v in seq): return -1,path,mx
            return path, path, mx
        ranked=[]
        for a,_ in cands:
            sc,path,mx=score(hist[a])
            if sc>0: ranked.append((a,sc,mx,hist[a][-1]))
        ranked.sort(key=lambda r:-r[1])
        with open(OUT,"w") as fp:
            fp.write(f"candidatos={len(cands)}  com movimento suave={len(ranked)}\n")
            for a,sc,mx,last in ranked[:15]:
                fp.write(f"0x{a:X}  path_suave={sc:6.1f}  maxstep={mx:4.1f}  ultimo=({last[0]:.1f},{last[1]:.1f},{last[2]:.1f})\n")
        msg_q.put(("done",f"vencedor: 0x{ranked[0][0]:X}" if ranked else "nenhum seguiu suave"))
    except Exception as e:
        import traceback; msg_q.put(("err",f"{e}|{traceback.format_exc()[:180]}"))

def math_dist(a,b):
    return ((a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2)**0.5

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("DS2 Find"); self.root.configure(bg="#101216")
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
            elif k=="done":self.state=("PRONTO!",str(p),"escreva 'pronto'",0);self.done=True
            elif k=="err":self.state=("ERRO",str(p)[:60],"",0)
        self.draw();self.root.after(100,self.tick)
    def draw(self):
        cv=self.cv;cv.delete("all");t,l1,l2,s=self.state
        col="#3fd07f" if self.done else "#ffd23f"
        cv.create_text(W/2,100,text=t,fill=col,font=("Consolas",24,"bold"))
        cv.create_text(W/2,175,text=l1,fill="#e8eefc",font=("Consolas",20,"bold"))
        cv.create_text(W/2,215,text=l2,fill="#9fb0cc",font=("Consolas",14))
        if s: cv.create_text(W/2,320,text=f"{s}",fill=col,font=("Consolas",60,"bold"))
        cv.create_text(W/2,H-22,text=self.info,fill="#5b6b86",font=("Consolas",11))

if __name__=="__main__":
    UI()
