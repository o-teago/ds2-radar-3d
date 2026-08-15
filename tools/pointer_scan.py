# -*- coding: utf-8 -*-
"""
POINTER SCAN (fase 1: achar cadeias) — offset PERMANENTE da posicao do player.

Objetivo: achar cadeias de ponteiros que, a partir da regiao ESTATICA do eboot,
resolvem ate o bloco da posicao (T = 0x20A71386C, [1.0,X,Y,Z]x5).

Resolver(root, offs):   # como o server vai resolver depois
    a = root
    for o in offs: a = read_u64(a) + o
    return a            # == T

Fase 2 (outro script, apos REINICIAR o jogo): revalida as cadeias e mantem a que
ainda cai na posicao viva = a permanente. root e guardado como (eboot_base + static_off).

Precisa: PS4CheaterNeo FECHADO. Salva em pointer_chains.txt
"""
import asyncio, time, struct, threading, queue, os, re
import numpy as np
import tkinter as tk

PS4_IP     = "192.168.1.104"
T_DEFAULT  = 0x20A71386C       # fallback
CHUNK      = 64*1024*1024
MAXOFF     = 0x1800            # offsets de 0..6KB (struct pode ser grande)
DEPTH      = 7
CAP        = 12000            # no maximo N nos por nivel (poda)
PER_TARGET = 1500            # no maximo N ponteiros por alvo (nivel>1)
MAXCHAINS  = 6000
STATIC_MAX = 0x100000000      # enderecos < 4GB = eboot/modulos (heap fica em ~8GB+)
PLAUS_LO, PLAUS_HI = 0x2000000, 0x800000000
_DIR = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(_DIR, "pointer_chains.txt")
msg_q = queue.Queue()
W,H = 760,520

def _load_target():   # alvo = bloco desta sessao (winner.txt do combined_find)
    p=os.path.join(_DIR,"winner.txt")
    if os.path.exists(p):
        with open(p,encoding="utf-8") as f:
            for ln in f:
                m=re.search(r"0x([0-9A-Fa-f]{6,})",ln)
                if m: return int(m.group(1),16)
    return T_DEFAULT
T=_load_target()

async def read_region(ps4,pid,start,size):
    buf=bytearray(); off=0
    while off<size:
        n=min(CHUNK,size-off)
        d=await ps4.read_memory(pid,start+off,n)
        if isinstance(d,tuple): d=d[-1]
        if not d: break
        buf+=d; off+=len(d)
    return bytes(buf)

def worker():
    try:
        import ps4debug
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        ps4=ps4debug.PS4Debug(PS4_IP)
        if asyncio.iscoroutine(ps4): ps4=loop.run_until_complete(ps4)
        procs=loop.run_until_complete(ps4.get_processes())
        pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
        if pid is None: msg_q.put(("err","DS2 nao encontrado")); return
        maps=loop.run_until_complete(ps4.get_process_maps(pid))

        # eboot real = regioes com nome 'executable'; dados estaticos = a parte prot 0x3
        exe=[m for m in maps if 'executable' in str(getattr(m,'name','') or '')]
        eboot_base=min((m.start for m in exe), default=0x400000)
        data=[m for m in exe if m.prot==0x3]
        if data: DLO=min(m.start for m in data); DHI=max(m.end for m in data)
        else: DLO,DHI=0x2478000,0x2868000
        # regioes rw p/ scan de ponteiros (heap + dados estaticos)
        regs=[(m.start,m.end-m.start) for m in maps if m.prot==0x3 and (m.end-m.start)>=64*1024]
        msg_q.put(("info",f"eboot=0x{eboot_base:X} data=[0x{DLO:X},0x{DHI:X}) regioes={len(regs)}"))

        # confere alvo
        td=loop.run_until_complete(ps4.read_memory(pid,T,16))
        if isinstance(td,tuple): td=td[-1]
        w,x,y,z=struct.unpack("<4f",td[:16])
        msg_q.put(("info",f"alvo T=0x{T:X}  w={w:.2f} X={x:.1f} Y={y:.1f} Z={z:.1f}"))

        # --- monta tabela global de ponteiros (valor, endereco) ---
        vals=[]; addrs=[]
        for i,(rs,sz) in enumerate(regs):
            msg_q.put(("phase",(f"LENDO PONTEIROS {i+1}/{len(regs)}","", "",0)))
            raw=loop.run_until_complete(read_region(ps4,pid,rs,sz))
            a=np.frombuffer(raw[:len(raw)&~7],dtype='<u8')
            m=(a>=PLAUS_LO)&(a<=PLAUS_HI)
            if m.any():
                idx=np.nonzero(m)[0]
                vals.append(a[idx]); addrs.append(rs+idx.astype(np.uint64)*8)
        if not vals: msg_q.put(("done","0 ponteiros plausiveis")); return
        vals=np.concatenate(vals); addrs=np.concatenate(addrs)
        msg_q.put(("info",f"ponteiros plausiveis: {len(vals):,}  ordenando..."))
        order=np.argsort(vals,kind='stable'); sv=vals[order]; sa=addrs[order]
        del vals,addrs,order

        # diagnostico: quantos ponteiros apontam pra perto de T (varias janelas)
        def near(win):
            lo=np.searchsorted(sv,np.uint64(T-win),'left'); hi=np.searchsorted(sv,np.uint64(T),'right')
            return int(hi-lo)
        diag=f"ptrs perto de T: <=0x600:{near(0x600)}  <=0x1800:{near(0x1800)}  <=0x4000:{near(0x4000)}  <=0x40000:{near(0x40000)}"
        msg_q.put(("info",diag))

        def ptrs_to(t,cap):
            lo=np.searchsorted(sv,np.uint64(t-MAXOFF),'left')
            hi=np.searchsorted(sv,np.uint64(t),'right')
            if hi<=lo: return [],[]
            pa=sa[lo:hi]; off=(np.uint64(t)-sv[lo:hi])
            if hi-lo>cap:
                k=np.argsort(off)[:cap]; pa=pa[k]; off=off[k]
            return pa.tolist(), off.tolist()

        # --- BFS reverso a partir de T ---
        frontier=[(T,())]; chains=[]; seen={T}; levellog=[diag]
        for depth in range(1,DEPTH+1):
            newf=[]
            cap = 100000 if depth==1 else PER_TARGET   # nivel 1: pega todos os ponteiros p/ T
            for (addr,offs) in frontier:
                pas,offos=ptrs_to(addr,cap)
                for pa,o in zip(pas,offos):
                    pa=int(pa)
                    if pa in seen: continue
                    seen.add(pa)
                    noffs=(int(o),)+offs
                    if DLO<=pa<DHI:                     # raiz na faixa de dados estaticos do eboot
                        chains.append((pa,noffs))
                        if len(chains)>=MAXCHAINS: break
                    else:
                        newf.append((pa,noffs))
                if len(chains)>=MAXCHAINS: break
            levellog.append(f"nivel {depth}: novos={len(newf)}  estaticas_ate_agora={len(chains)}")
            msg_q.put(("phase",(f"NIVEL {depth}",f"estaticas={len(chains)}",f"frontier={len(newf)}",0)))
            if len(chains)>=MAXCHAINS: break
            newf.sort(key=lambda n:(len(n[1]),sum(n[1])))
            frontier=newf[:CAP]
            if not frontier: break

        # ordena cadeias: menos offsets (mais curtas) primeiro
        chains.sort(key=lambda c:(len(c[1]),sum(c[1])))
        with open(OUT,"w",encoding="utf-8") as fp:
            fp.write(f"eboot_base=0x{eboot_base:X}\nT=0x{T:X}  (X={x:.1f} Y={y:.1f} Z={z:.1f})\n")
            fp.write("\n".join(levellog)+"\n")
            fp.write(f"cadeias estaticas encontradas: {len(chains)}\n")
            fp.write("formato: static_off (=root-eboot_base) | offsets\n\n")
            for pa,offs in chains[:400]:
                so=pa-eboot_base
                fp.write(f"0x{so:X} | "+" ".join(f"0x{o:X}" for o in offs)+f"   (root=0x{pa:X})\n")
        msg_q.put(("done",f"{len(chains)} cadeias -> pointer_chains.txt (agora reinicie o jogo p/ validar)"))
    except Exception as e:
        import traceback; msg_q.put(("err",f"{e}|{traceback.format_exc()[:200]}"))

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("DS2 - Pointer Scan (fase 1)"); self.root.configure(bg="#101216")
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
            elif k=="done":self.state=("PRONTO!",str(p)[:52],"veja pointer_chains.txt",0);self.done=True
            elif k=="err":self.state=("ERRO",str(p)[:64],"",0)
        self.draw();self.root.after(120,self.tick)
    def draw(self):
        cv=self.cv;cv.delete("all");t,l1,l2,s=self.state
        col="#3fd07f" if self.done else "#ffd23f"
        cv.create_text(W/2,110,text=t,fill=col,font=("Consolas",20,"bold"))
        cv.create_text(W/2,185,text=l1,fill="#e8eefc",font=("Consolas",15,"bold"))
        cv.create_text(W/2,225,text=l2,fill="#9fb0cc",font=("Consolas",13))
        cv.create_text(W/2,H-30,text=self.info,fill="#5b6b86",font=("Consolas",10))

if __name__=="__main__":
    UI()
