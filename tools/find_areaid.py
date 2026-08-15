# -*- coding: utf-8 -*-
"""
ACHADOR do ID DA AREA ATUAL v2 (detector GENERICO).

Nao chuta uma codificacao unica. Cruza duas areas e procura, em enderecos ESTAVEIS,
qualquer valor que va de "area1" para "area2" por varios esquemas ao mesmo tempo:
  A) BYTEWISE  - um dword cujos bytes contem a area (M) e o bloco muda N1->N2 (qualquer ordem)
  B) DECIMAL   - inteiros tipo 1004->1002, 100400->100200, 10040000->10020000, 100004->100002
  C) ASCII     - a string "10_04" -> "10_02"

Fases (clique os botoes):
  1) fique na "Area atual", clique  [1) CAPTURAR ATUAL]
  2) VIAJE pra outra area; escolha-a e clique [2) CAPTURAR DESTINO + ACHAR]

Precisa: PS4CheaterNeo FECHADO. Salva em areaid_winner.txt
"""
import asyncio, time, struct, threading, queue, os, json
import numpy as np
import tkinter as tk

PS4_IP = "192.168.1.104"
CHUNK  = 64*1024*1024
_DIR   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(_DIR, "areaid_winner.txt")
W,H = 760,560
MAXREP = 60
msg_q = queue.Queue(); cmd_q = queue.Queue()

def dec_ints(M,N):
    return {
        "d_%d*100+n"%M:        M*100+N,        # 1004
        "d_%d*10000+n"%M:      M*10000+N,      # 100004
        "d_%d*10000+n*100"%M:  M*10000+N*100,  # 100400
        "d_%d*1e6+n*1e4"%M:    M*1000000+N*10000, # 10040000
    }

async def read_u32(ps4,pid,start,size):
    size&=~3; buf=bytearray(); off=0
    while off<size:
        n=min(CHUNK,size-off)
        d=await ps4.read_memory(pid,start+off,n)
        if isinstance(d,tuple): d=d[-1]
        if not d: break
        buf+=d; off+=len(d)
    return np.frombuffer(bytes(buf[:len(buf)&~3]),dtype='<u4')

def bytewise(a,b,M,N1,N2):
    """indices onde a->b = um so byte muda de N1 p/ N2 e existe um byte == M (area)."""
    xor=a^b; diff=np.uint32(N1^N2)
    a0=a&0xFF;a1=(a>>8)&0xFF;a2=(a>>16)&0xFF;a3=(a>>24)&0xFF
    hasM=(a0==M)|(a1==M)|(a2==M)|(a3==M)
    acc=np.zeros(len(a),bool)
    for p in range(4):
        sh=np.uint32(8*p)
        acc|= (xor==(diff<<sh)) & (((a>>sh)&0xFF)==N1) & (((b>>sh)&0xFF)==N2) & hasM
    return np.nonzero(acc)[0]

def layout(aval,bval,M,N1,N2):
    ab=[(aval>>(8*p))&0xFF for p in range(4)]; bb=[(bval>>(8*p))&0xFF for p in range(4)]
    pN=next(p for p in range(4) if ab[p]==N1 and bb[p]==N2)
    pM=next((p for p in range(4) if ab[p]==M and p!=pN), pN)
    return pM,pN

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
        regs=[(m.start,m.end-m.start) for m in maps if m.prot==0x3 and (m.end-m.start)>=64*1024]
        msg_q.put(("info",f"pid={pid} · {len(regs)} regioes rw")); msg_q.put(("ready1",None))

        while True:
            c=cmd_q.get()
            if c[0]=="cap1": (M1,N1)=c[1]; break
        A={}
        for i,(rs,sz) in enumerate(regs):
            msg_q.put(("phase",(f"AREA 1 = {M1:02d}_{N1:02d}","LENDO","NAO troque de area",f"{i+1}/{len(regs)}")))
            A[rs]=loop.run_until_complete(read_u32(ps4,pid,rs,sz))
        msg_q.put(("info","captura 1 ok - agora viaje")); msg_q.put(("ready2",None))

        while True:
            c=cmd_q.get()
            if c[0]=="cap2": (M2,N2)=c[1]; break

        hits=[]   # (method, addr, aval, bval, extra)
        di1=dec_ints(M1,N1); di2=dec_ints(M2,N2)
        same_world=(M1==M2)
        for i,(rs,sz) in enumerate(regs):
            msg_q.put(("phase",(f"AREA 2 = {M2:02d}_{N2:02d}","LENDO+CRUZANDO","",f"{i+1}/{len(regs)}")))
            a=A[rs]; b=loop.run_until_complete(read_u32(ps4,pid,rs,sz))
            n=min(len(a),len(b)); a=a[:n]; b=b[:n]
            # A) bytewise (so faz sentido no mesmo mundo M1==M2)
            if same_world:
                for j in bytewise(a,b,M1,N1,N2).tolist():
                    hits.append(("BYTEWISE",rs+j*4,int(a[j]),int(b[j]),None))
            # B) decimais
            for name in di1:
                v1=np.uint32(di1[name]); v2=np.uint32(di2[name])
                m=(a==v1)&(b==v2)
                for j in np.nonzero(m)[0].tolist():
                    hits.append(("DEC "+name,rs+j*4,int(a[j]),int(b[j]),None))
            # C) ASCII "MM_NN"
            s1=("%02d_%02d"%(M1,N1)).encode(); s2=("%02d_%02d"%(M2,N2)).encode()
            ba=a.tobytes(); pos=ba.find(s1)
            while pos!=-1:
                bb=b.tobytes()  # (poderia cachear; regioes pequenas o suficiente aqui)
                if bb[pos:pos+len(s2)]==s2:
                    hits.append(("ASCII",rs+pos,0,0,s1.decode()+"->"+s2.decode()))
                pos=ba.find(s1,pos+1)
            if len(hits)>4000: break

        # ---- escolhe vencedor: menor grupo por metodo (mais especifico) ----
        by_method={}
        for h in hits: by_method.setdefault(h[0],[]).append(h)
        with open(OUT,"w",encoding="utf-8") as fp:
            fp.write(f"AREA1={M1:02d}_{N1:02d}  AREA2={M2:02d}_{N2:02d}\n")
            fp.write(f"metodos com acerto: {len(by_method)}   total hits: {len(hits)}\n\n")
            if not by_method:
                fp.write("NADA. O map id migra de endereco OU usa outra representacao (indice interno?).\n")
                msg_q.put(("done","0 - o id provavelmente MIGRA de endereco")); return
            # ordena metodos pelo tamanho (menos = melhor)
            ordered=sorted(by_method.items(),key=lambda kv:len(kv[1]))
            for meth,lst in ordered:
                fp.write(f"== {meth}  ({len(lst)} endereco(s)) ==\n")
                if meth=="BYTEWISE" and lst:
                    pM,pN=layout(lst[0][2],lst[0][3],M1,N1,N2)
                    fp.write(f"   DECODE: area=(v>>{8*pM})&0xFF  bloco=(v>>{8*pN})&0xFF   [pM={pM} pN={pN}]\n")
                elif meth.startswith("DEC"):
                    fp.write(f"   DECODE: valor decimal; area1_val={lst[0][2]} area2_val={lst[0][3]}\n")
                elif meth=="ASCII":
                    fp.write(f"   DECODE: le 5 bytes 'MM_NN' e parseia\n")
                for h in lst[:MAXREP]:
                    fp.write(f"   0x{h[1]:X}   a={h[2]} b={h[3]}"+(f"  {h[4]}" if h[4] else "")+"\n")
                fp.write("\n")
            best=ordered[0]
            msg_q.put(("done",f"{best[0]}  {len(best[1])} addr  1o=0x{best[1][0][1]:X}"))
    except Exception as e:
        import traceback; msg_q.put(("err",f"{e} | {traceback.format_exc()[:200]}"))

# --------------------------- UI (igual v1) ---------------------------
def load_areas():
    try:
        with open(os.path.join(_DIR,"areas.json"),encoding="utf-8") as f: a=json.load(f)
        out=[]
        for it in a:
            k=it["key"]; p=k.split("_"); M=int(p[0]); N=int(p[1])
            out.append((f"{it.get('name',k)}  [{M:02d}_{N:02d}]",M,N))
        return out
    except Exception:
        return [("Majula [10_04]",10,4),("Things Betwixt [10_02]",10,2),("Forest of Fallen Giants [10_10]",10,10)]

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("DS2 - Achar ID da Area v2"); self.root.configure(bg="#101216")
        self.root.geometry(f"{W}x{H}+60+40")
        self.areas=load_areas(); names=[a[0] for a in self.areas]
        def dflt(sub):
            for i,a in enumerate(self.areas):
                if sub in a[0].lower(): return i
            return 0
        self.cv=tk.Canvas(self.root,width=W,height=250,bg="#101216",highlightthickness=0); self.cv.pack()
        bar=tk.Frame(self.root,bg="#101216"); bar.pack(pady=6)
        tk.Label(bar,text="Area ATUAL:",bg="#101216",fg="#9fb0cc",font=("Consolas",11)).grid(row=0,column=0,sticky="e",padx=4,pady=4)
        self.v1=tk.StringVar(value=names[dflt("majula")]); tk.OptionMenu(bar,self.v1,*names).grid(row=0,column=1,sticky="w",padx=4)
        tk.Label(bar,text="Area DESTINO:",bg="#101216",fg="#9fb0cc",font=("Consolas",11)).grid(row=1,column=0,sticky="e",padx=4,pady=4)
        self.v2=tk.StringVar(value=names[dflt("betwixt")]); tk.OptionMenu(bar,self.v2,*names).grid(row=1,column=1,sticky="w",padx=4)
        self.b1=tk.Button(self.root,text="1) CAPTURAR ATUAL",font=("Consolas",13,"bold"),bg="#243b55",fg="#fff",state="disabled",command=self.cap1); self.b1.pack(pady=4)
        self.b2=tk.Button(self.root,text="2) CAPTURAR DESTINO + ACHAR",font=("Consolas",13,"bold"),bg="#3a2b55",fg="#fff",state="disabled",command=self.cap2); self.b2.pack(pady=4)
        self.state=("CONECTANDO...","","",""); self.info=""; self.done=False
        threading.Thread(target=worker,daemon=True).start(); self.tick(); self.root.mainloop()
    def _sel(self,var):
        for a in self.areas:
            if a[0]==var.get(): return (a[1],a[2])
        return (10,4)
    def cap1(self): self.b1.config(state="disabled"); cmd_q.put(("cap1",self._sel(self.v1)))
    def cap2(self): self.b2.config(state="disabled"); cmd_q.put(("cap2",self._sel(self.v2)))
    def tick(self):
        while True:
            try:k,p=msg_q.get_nowait()
            except queue.Empty:break
            if k=="phase":self.state=p
            elif k=="info":self.info=str(p)
            elif k=="ready1":self.state=("PRONTO","fique na Area atual","clique 1) CAPTURAR ATUAL","");self.b1.config(state="normal")
            elif k=="ready2":self.state=("AREA 1 OK!","VIAJE pra outra area","escolha-a e clique 2)","");self.b2.config(state="normal")
            elif k=="done":self.state=("PRONTO!",str(p),"veja areaid_winner.txt","");self.done=True
            elif k=="err":self.state=("ERRO",str(p)[:70],"","")
        self.draw();self.root.after(100,self.tick)
    def draw(self):
        cv=self.cv;cv.delete("all");t,l1,l2,s=self.state
        col="#3fd07f" if self.done else "#ffd23f"
        cv.create_text(W/2,50,text=t,fill=col,font=("Consolas",22,"bold"))
        cv.create_text(W/2,110,text=l1,fill="#e8eefc",font=("Consolas",17,"bold"))
        cv.create_text(W/2,145,text=l2,fill="#9fb0cc",font=("Consolas",13))
        if s: cv.create_text(W/2,200,text=str(s),fill=col,font=("Consolas",18,"bold"))
        cv.create_text(W/2,235,text=self.info,fill="#5b6b86",font=("Consolas",11))

if __name__=="__main__":
    UI()
