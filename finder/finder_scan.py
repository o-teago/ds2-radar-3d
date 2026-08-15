# -*- coding: utf-8 -*-
"""
DS2 Radar - Offset Finder, STAGE 1 (scan).

Finds everything the radar needs for YOUR game version and saves it to
finder_state.json. Then you reboot the game and run finder_validate.py (stage 2),
which turns the state into a ready-to-use config.ini.

What stage 1 does, guided on screen:
  1) POSITION  - finds the live player position block (differential heap scan).
  2) AREA      - finds the "current map name" strings (needs TWO areas: you pick
                 the area you're in, capture, travel to another area, capture).
  3) POINTERS  - pointer-scans a static chain (eboot -> ... -> position block).

Requirements: PS4 with ps4debug payload loaded, PS4CheaterNeo CLOSED.
Be in an OPEN area with room to walk (Majula is ideal). No lock-on.
"""
import asyncio, time, struct, threading, queue, os, json, configparser
import numpy as np
import tkinter as tk

_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.dirname(_DIR)                     # package root (has config.ini, maps/)
STATE  = os.path.join(_DIR, "finder_state.json")
CHUNK  = 64*1024*1024
# pointer scan params
MAXOFF = 0x1800; DEPTH = 7; CAP = 12000; PER_TARGET = 1500; MAXCHAINS = 6000
msg_q = queue.Queue(); cmd_q = queue.Queue()
W,H = 780,560

def get_ip():
    p=os.path.join(ROOT,"config.ini")
    if os.path.exists(p):
        try:
            c=configparser.ConfigParser(inline_comment_prefixes=(';','#')); c.read(p,encoding="utf-8")
            if c.has_option("ps4","ip"): return c.get("ps4","ip").strip()
        except Exception: pass
    return "192.168.1.104"

async def read_bytes(ps4,pid,start,size):
    buf=bytearray(); off=0
    while off<size:
        n=min(CHUNK,size-off)
        d=await ps4.read_memory(pid,start+off,n)
        if isinstance(d,tuple): d=d[-1]
        if not d: break
        buf+=d; off+=len(d)
    return bytes(buf)

async def read_f4(ps4,pid,start,size):
    raw=await read_bytes(ps4,pid,start,size)
    return np.frombuffer(raw[:len(raw)&~3],dtype='<f4')

# ---------- POSITION (differential scan, from combined_find) ----------
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
def mdist(a,b): return ((a[0]-b[0])**2+(a[1]-b[1])**2+(a[2]-b[2])**2)**0.5

def find_position(loop,ps4,pid,regs):
    def rd(title,sub,hold):
        for s in range(hold,0,-1):
            msg_q.put(("phase",(title,sub,"",s))); time.sleep(1)
        out={}
        for k,(rs,sz) in enumerate(regs):
            msg_q.put(("phase",(title+" READING","DO NOT MOVE",f"{k+1}/{len(regs)}",0)))
            out[rs]=loop.run_until_complete(read_f4(ps4,pid,rs,sz))
        return out
    A=rd("POSITION 1/4: STAND STILL","don't move",5)
    idxA={rs:triplets(A[rs]) for rs in A}; vA={rs:V(A[rs],idxA[rs]) for rs in A}
    B=rd("POSITION 2/4: STAND STILL","keep still",2)
    stab={}
    for rs in idxA:
        idx=idxA[rs]; ok=idx+2<len(B[rs]); idx=idx[ok]; va=vA[rs][ok]
        vb=V(B[rs],idx); same=np.all(np.abs(va-vb)<0.05,axis=1); pl=plausible(va)
        m=same&pl; stab[rs]=(idx[m],va[m])
    for s in range(8,0,-1):
        msg_q.put(("phase",("POSITION 3/4: TAKE A FEW STEPS","walk a little","and STOP",s))); time.sleep(1)
    C=rd("POSITION 3/4: STAND STILL","stopped",2)
    cands=[]
    for rs in stab:
        idx,vs=stab[rs]; ok=idx+2<len(C[rs]); idx=idx[ok]; vs=vs[ok]
        vc=V(C[rs],idx); d=np.sqrt(((vc-vs)**2).sum(axis=1)); ch=np.abs(vc-vs); minch=ch.min(axis=1)
        keep=(d>1.5)&(d<40)&(minch<3.0)&plausible(vc)
        for j in np.nonzero(keep)[0]: cands.append(rs+int(idx[j])*4)
    cands=cands[:450]
    if not cands: return None,None
    hist={a:[] for a in cands}; t0=time.time()
    while time.time()-t0<16:
        left=int(16-(time.time()-t0))+1
        msg_q.put(("phase",("POSITION 4/4: KEEP WALKING",f"don't stop {left}s","tracking...",0)))
        for a in cands:
            try:
                d=loop.run_until_complete(ps4.read_memory(pid,a,12))
                if isinstance(d,tuple): d=d[-1]
                if d and len(d)>=12: hist[a].append(struct.unpack("<3f",d[:12]))
            except: pass
        time.sleep(0.4)
    ranked=[]
    for a in cands:
        seq=hist[a]
        if len(seq)<4: continue
        steps=[mdist(seq[i],seq[i-1]) for i in range(1,len(seq))]
        mx=max(steps) if steps else 0; path=sum(s for s in steps if s<10)
        if mx>25 or path<=0: continue
        if not all(np.isfinite(v).all() and (np.abs(v)<300).all() for v in seq): continue
        ranked.append((a,path,seq[-1]))
    ranked.sort(key=lambda r:-r[1])
    if not ranked: return None,None
    win=ranked[0][0]
    # the block base is 4 bytes before X (layout [1.0, X, Y, Z]); winner points at X
    d=loop.run_until_complete(ps4.read_memory(pid,win-4,16))
    if isinstance(d,tuple): d=d[-1]
    w,x,y,z=struct.unpack("<4f",d[:16])
    base = win-4 if 0.9<w<1.1 else win
    dd=loop.run_until_complete(ps4.read_memory(pid,base,16))
    if isinstance(dd,tuple): dd=dd[-1]
    _,x,y,z=struct.unpack("<4f",dd[:16])
    return base,(x,y,z)

# ---------- AREA (ASCII "MM_NN" intersection, from find_areaid) ----------
def scan_ascii(loop,ps4,pid,regs,s):
    found=set()
    for i,(rs,sz) in enumerate(regs):
        msg_q.put(("phase",("AREA: READING",f"looking for '{s.decode()}'",f"{i+1}/{len(regs)}",0)))
        raw=loop.run_until_complete(read_bytes(ps4,pid,rs,sz))
        pos=raw.find(s)
        while pos!=-1:
            found.add(rs+pos); pos=raw.find(s,pos+1)
    return found

# ---------- POINTER SCAN (from pointer_scan) ----------
def pointer_scan(loop,ps4,pid,maps,T):
    exe=[m for m in maps if 'executable' in str(getattr(m,'name','') or '')]
    eboot_base=min((m.start for m in exe), default=0x400000)
    data=[m for m in exe if m.prot==0x3]
    DLO=min((m.start for m in data),default=0x2478000); DHI=max((m.end for m in data),default=0x2868000)
    regs=[(m.start,m.end-m.start) for m in maps if m.prot==0x3 and (m.end-m.start)>=64*1024]
    vals=[]; addrs=[]
    for i,(rs,sz) in enumerate(regs):
        msg_q.put(("phase",("POINTERS: READING",f"{i+1}/{len(regs)}","",0)))
        raw=loop.run_until_complete(read_bytes(ps4,pid,rs,sz))
        a=np.frombuffer(raw[:len(raw)&~7],dtype='<u8')
        m=(a>=0x2000000)&(a<=0x800000000)
        if m.any():
            idx=np.nonzero(m)[0]; vals.append(a[idx]); addrs.append(rs+idx.astype(np.uint64)*8)
    if not vals: return eboot_base,[]
    vals=np.concatenate(vals); addrs=np.concatenate(addrs)
    msg_q.put(("phase",("POINTERS: SORTING",f"{len(vals):,} pointers","",0)))
    order=np.argsort(vals,kind='stable'); sv=vals[order]; sa=addrs[order]; del vals,addrs,order
    def ptrs_to(t,cap):
        lo=np.searchsorted(sv,np.uint64(t-MAXOFF),'left'); hi=np.searchsorted(sv,np.uint64(t),'right')
        if hi<=lo: return [],[]
        pa=sa[lo:hi]; off=(np.uint64(t)-sv[lo:hi])
        if hi-lo>cap: k=np.argsort(off)[:cap]; pa=pa[k]; off=off[k]
        return pa.tolist(), off.tolist()
    frontier=[(T,())]; chains=[]; seen={T}
    for depth in range(1,DEPTH+1):
        newf=[]; cap=100000 if depth==1 else PER_TARGET
        for (addr,offs) in frontier:
            pas,offos=ptrs_to(addr,cap)
            for pa,o in zip(pas,offos):
                pa=int(pa)
                if pa in seen: continue
                seen.add(pa); noffs=(int(o),)+offs
                if DLO<=pa<DHI: chains.append((pa,noffs))
                else: newf.append((pa,noffs))
                if len(chains)>=MAXCHAINS: break
            if len(chains)>=MAXCHAINS: break
        msg_q.put(("phase",("POINTERS: LEVEL "+str(depth),f"chains={len(chains)}",f"frontier={len(newf)}",0)))
        if len(chains)>=MAXCHAINS or not newf: break
        newf.sort(key=lambda n:(len(n[1]),sum(n[1]))); frontier=newf[:CAP]
    chains.sort(key=lambda c:(len(c[1]),sum(c[1])))
    return eboot_base,[(pa-eboot_base,list(offs)) for pa,offs in chains]

def worker():
    try:
        import ps4debug
        loop=asyncio.new_event_loop(); asyncio.set_event_loop(loop)
        ip=get_ip()
        ps4=ps4debug.PS4Debug(ip)
        if asyncio.iscoroutine(ps4): ps4=loop.run_until_complete(ps4)
        procs=loop.run_until_complete(ps4.get_processes())
        pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
        if pid is None: msg_q.put(("err","DS2 process not found")); return
        maps=loop.run_until_complete(ps4.get_process_maps(pid))
        heap=[(m.start,m.end-m.start) for m in maps
              if m.prot==0x3 and "anon" in (getattr(m,"name","")or"") and (m.end-m.start)>=4*1024*1024]
        exe=[m.start for m in maps if 'executable' in str(getattr(m,'name','') or '')]
        eboot_base=min(exe) if exe else 0x400000
        msg_q.put(("info",f"ip={ip} pid={pid} eboot_base=0x{eboot_base:X}"))
        msg_q.put(("ready_start",None))

        while True:
            c=cmd_q.get()
            if c[0]=="start": break
        # 1) POSITION
        posblock,coords=find_position(loop,ps4,pid,heap)
        if not posblock: msg_q.put(("err","Position not found. Retry: stand still, then walk.")); return
        msg_q.put(("info",f"position block=0x{posblock:X} at {tuple(round(v,1) for v in coords)}"))

        # 2) AREA (two captures)
        msg_q.put(("ready_area1",None))
        while True:
            c=cmd_q.get()
            if c[0]=="cap1": (m1,n1)=c[1]; break
        s1=("%02d_%02d"%(m1,n1)).encode(); S1=scan_ascii(loop,ps4,pid,heap,s1)
        msg_q.put(("info",f"area1 {m1:02d}_{n1:02d}: {len(S1)} strings"))
        msg_q.put(("ready_area2",None))
        while True:
            c=cmd_q.get()
            if c[0]=="cap2": (m2,n2)=c[1]; break
        s2=("%02d_%02d"%(m2,n2)).encode(); S2=scan_ascii(loop,ps4,pid,heap,s2)
        inter=sorted(a for a in S1 if a in S2)
        area_offs=[a-eboot_base for a in inter]
        msg_q.put(("info",f"area addresses (live map name): {len(area_offs)}"))
        if not area_offs:
            msg_q.put(("err","Area strings not found. Make sure you traveled to the 2nd area.")); return

        # 3) POINTER SCAN
        maps=loop.run_until_complete(ps4.get_process_maps(pid))
        eboot_base,chains=pointer_scan(loop,ps4,pid,maps,posblock)
        msg_q.put(("info",f"pointer chains found: {len(chains)}"))

        state={"ip":ip,"eboot_base":eboot_base,"pos_block":posblock,
               "coords":list(coords),"area_offsets":area_offs,
               "areas":[[m1,n1],[m2,n2]],"chains":chains}
        with open(STATE,"w",encoding="utf-8") as f: json.dump(state,f)
        msg_q.put(("done",f"{len(chains)} chains, {len(area_offs)} area addrs -> finder_state.json"))
    except Exception as e:
        import traceback; msg_q.put(("err",f"{e} | {traceback.format_exc()[:180]}"))

# --------------------------- UI ---------------------------
def load_areas():
    try:
        with open(os.path.join(ROOT,"maps","areas.json"),encoding="utf-8") as f: a=json.load(f)
        out=[]
        for it in a:
            k=it["key"]; p=k.split("_"); out.append((f"{it.get('name',k)} [{int(p[0]):02d}_{int(p[1]):02d}]",int(p[0]),int(p[1])))
        return out
    except Exception:
        return [("Majula [10_04]",10,4),("Things Betwixt [10_02]",10,2)]

class UI:
    def __init__(self):
        self.root=tk.Tk(); self.root.title("DS2 Radar - Finder (Stage 1: Scan)"); self.root.configure(bg="#101216")
        self.root.geometry(f"{W}x{H}+50+40")
        self.areas=load_areas(); names=[a[0] for a in self.areas]
        def dflt(sub):
            for i,a in enumerate(self.areas):
                if sub in a[0].lower(): return i
            return 0
        self.cv=tk.Canvas(self.root,width=W,height=330,bg="#101216",highlightthickness=0); self.cv.pack()
        bar=tk.Frame(self.root,bg="#101216"); bar.pack(pady=4)
        tk.Label(bar,text="Current area:",bg="#101216",fg="#9fb0cc",font=("Consolas",11)).grid(row=0,column=0,sticky="e",padx=4,pady=3)
        self.v1=tk.StringVar(value=names[dflt("majula")]); tk.OptionMenu(bar,self.v1,*names).grid(row=0,column=1,sticky="w")
        tk.Label(bar,text="Second area:",bg="#101216",fg="#9fb0cc",font=("Consolas",11)).grid(row=1,column=0,sticky="e",padx=4,pady=3)
        self.v2=tk.StringVar(value=names[dflt("betwixt")]); tk.OptionMenu(bar,self.v2,*names).grid(row=1,column=1,sticky="w")
        self.bStart=tk.Button(self.root,text="START SCAN",font=("Consolas",13,"bold"),bg="#243b55",fg="#fff",state="disabled",command=self.start); self.bStart.pack(pady=3)
        self.bA1=tk.Button(self.root,text="Capture current area",font=("Consolas",12,"bold"),bg="#243b55",fg="#fff",state="disabled",command=self.cap1); self.bA1.pack(pady=2)
        self.bA2=tk.Button(self.root,text="Capture 2nd area + continue",font=("Consolas",12,"bold"),bg="#3a2b55",fg="#fff",state="disabled",command=self.cap2); self.bA2.pack(pady=2)
        self.state=("CONNECTING...","","",0); self.info=""; self.done=False
        threading.Thread(target=worker,daemon=True).start(); self.tick(); self.root.mainloop()
    def _sel(self,var):
        for a in self.areas:
            if a[0]==var.get(): return (a[1],a[2])
        return (10,4)
    def start(self): self.bStart.config(state="disabled"); cmd_q.put(("start",))
    def cap1(self): self.bA1.config(state="disabled"); cmd_q.put(("cap1",self._sel(self.v1)))
    def cap2(self): self.bA2.config(state="disabled"); cmd_q.put(("cap2",self._sel(self.v2)))
    def tick(self):
        while True:
            try:k,p=msg_q.get_nowait()
            except queue.Empty:break
            if k=="phase":self.state=p
            elif k=="info":self.info=str(p)
            elif k=="ready_start":self.state=("READY","Be in Majula, stand still,","click START SCAN",0);self.bStart.config(state="normal")
            elif k=="ready_area1":self.state=("POSITION DONE","stay in this area","click 'Capture current area'",0);self.bA1.config(state="normal")
            elif k=="ready_area2":self.state=("NOW TRAVEL","go to the 2nd area, then","click 'Capture 2nd area'",0);self.bA2.config(state="normal")
            elif k=="done":self.state=("STAGE 1 DONE!",str(p)[:46],"REBOOT game -> run finder_validate.py",0);self.done=True
            elif k=="err":self.state=("ERROR",str(p)[:64],"",0)
        self.draw();self.root.after(100,self.tick)
    def draw(self):
        cv=self.cv;cv.delete("all");t,l1,l2,s=self.state
        col="#3fd07f" if self.done else "#ffd23f"
        cv.create_text(W/2,70,text=t,fill=col,font=("Consolas",20,"bold"))
        cv.create_text(W/2,140,text=l1,fill="#e8eefc",font=("Consolas",16,"bold"))
        cv.create_text(W/2,180,text=l2,fill="#9fb0cc",font=("Consolas",13))
        if s: cv.create_text(W/2,255,text=str(s),fill=col,font=("Consolas",52,"bold"))
        cv.create_text(W/2,310,text=self.info,fill="#5b6b86",font=("Consolas",10))

if __name__=="__main__":
    UI()
