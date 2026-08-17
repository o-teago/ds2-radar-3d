# -*- coding: utf-8 -*-
"""
3D RADAR backend (with AUTO area switching):
  - HTTP (8080) serves radar.html + geometry (.bin)
  - WebSocket (8766) streams the live position  {x,y,z}
  - Detects the current AREA (reads the map name "MM_NN" from memory) -> {area:"10_04"}
    the browser swaps the 3D model automatically.
Usage:  python server.py   ->  http://localhost:8080/radar.html
Offsets come from config.ini (per game version). Requires ps4debug on the PS4.
"""
import asyncio, struct, json, os, threading, functools, http.server, socketserver, configparser
from collections import Counter
import websockets, ps4debug

_dir = os.path.dirname(os.path.abspath(__file__))

# ---- DEFAULTS (Dark Souls II SotFS CUSA01760 1.02, validado) — usados se faltar config.ini ----
PS4_IP  = "192.168.1.104"
# POSICAO: cadeia de ponteiro ESTATICA (pointer scan validado por reboot) -> bloco [1.0,X,Y,Z]x5
#   base = *( *(eboot_base + static_off) + offs[0] ) + offs[1] ...
POS_STATIC_OFF = 0x21976C0
POS_OFFS       = [0x290, 0x3AC]
# AREA: nome do mapa "MM_NN" em dados estaticos do eboot (offsets relativos ao eboot_base)
AREA_OFFS = [0x21C77D1,0x21C7801,0x21C7831,0x2209851,0x2209881]
GAME_INFO = "CUSA01760 1.02 (default embutido)"

def _hx(s):  return int(str(s).strip(),16)
def _hxl(s): return [int(x.strip(),16) for x in str(s).split(',') if x.strip()]
def load_config():
    global PS4_IP, POS_STATIC_OFF, POS_OFFS, AREA_OFFS, GAME_INFO
    p=os.path.join(_dir,"config.ini")
    if not os.path.exists(p):
        print("config.ini not found — using built-in defaults"); return
    try:
        c=configparser.ConfigParser(inline_comment_prefixes=(';','#')); c.read(p,encoding="utf-8")
        if c.has_option("ps4","ip"):            PS4_IP=c.get("ps4","ip").strip()
        if c.has_option("position","static_off"): POS_STATIC_OFF=_hx(c.get("position","static_off"))
        if c.has_option("position","offsets"):  POS_OFFS=_hxl(c.get("position","offsets"))
        if c.has_option("area","offsets"):      AREA_OFFS=_hxl(c.get("area","offsets"))
        if c.has_option("info","version"):      GAME_INFO=c.get("info","version").strip()
        print(f"config.ini loaded ({GAME_INFO})")
    except Exception as e:
        print("config.ini error (using defaults):",e)
load_config()

WS_PORT = 8766
HTTP_PORT = 8080
HZ = 15
clients = set()
last_area = None
eboot_base = 0x400000
AREA_ADDRS = []
PS4 = None; PID = None      # conexao atual (a auto-reconexao atualiza)

# map name prefix "MM_NN" -> full areas.json key (e.g. "10_04" -> "10_04_majula")
def load_area_map():
    m={}
    try:
        with open(os.path.join(_dir,"maps","areas.json"),encoding="utf-8") as f:
            for it in json.load(f):
                k=it["key"]; pre="_".join(k.split("_")[:2])
                m[pre]=k
    except Exception as e:
        print("areas.json:",e)
    return m
AREA_MAP = load_area_map()

def med(xs): s=sorted(xs); return s[len(s)//2] if s else 0.0

async def read_u64(ps4,pid,a):
    d=await ps4.read_memory(pid,a,8)
    if isinstance(d,tuple): d=d[-1]
    if not d or len(d)<8: return None
    return struct.unpack("<Q",d[:8])[0]

async def resolve_base(ps4,pid):   # resolve a cadeia estatica -> endereco do bloco de posicao
    a=eboot_base+POS_STATIC_OFF
    for o in POS_OFFS:
        v=await read_u64(ps4,pid,a)
        if v is None or v<0x10000 or v>0x800000000: return None
        a=v+o
    return a

def start_http():
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    handler = functools.partial(H, directory=_dir)
    httpd = socketserver.ThreadingTCPServer(("localhost", HTTP_PORT), handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

async def broadcast(msg):
    dead=[]
    for ws in clients:
        try: await ws.send(msg)
        except Exception: dead.append(ws)
    for ws in dead: clients.discard(ws)

async def handler(ws):
    clients.add(ws)
    try:
        if last_area:                      # cliente novo ja recebe a area atual
            await ws.send(json.dumps({"area":last_area}))
        async for _ in ws: pass
    finally:
        clients.discard(ws)

def parse_mmnn(b):
    # b = 5 bytes tipo '1','0','_','0','4' -> "10_04"; senao None
    if len(b)>=5 and b[2:3]==b"_" and b[0:2].isdigit() and b[3:5].isdigit():
        return b[0:5].decode()
    return None

async def read_area(ps4,pid):
    votes=[]; raws=[]
    for a in AREA_ADDRS:
        try:
            d=await ps4.read_memory(pid,a,5)
            if isinstance(d,tuple): d=d[-1]
            d=d or b""
            raws.append(bytes(d))
            mm=parse_mmnn(d)
            if mm: votes.append(mm)
        except Exception as e:
            raws.append(b"ERR")
    dbg="  ".join(r.decode('latin1',' ').replace(chr(0),'.') if isinstance(r,bytes) else str(r) for r in raws)
    if not votes:
        return None, None, "sem voto | "+dbg
    pre=Counter(votes).most_common(1)[0][0]     # maioria
    key=AREA_MAP.get(pre)                         # chave completa (ou None se sem geometria)
    return pre, key, f"{pre} -> {key or 'SEM GEOMETRIA'} | "+dbg

async def reader():
    global last_area
    tick=0; pend=None; pend_n=0; base=None; errs=0
    while True:
        ps4, pid = PS4, PID                    # usa a conexao atual (pode ter reconectado)
        try:
            # resolve a cadeia estatica -> bloco de posicao (segue realocacoes; permanente)
            nb=await resolve_base(ps4,pid)
            if nb: base=nb
            d = await ps4.read_memory(pid, base, 80) if base else None
            if isinstance(d, tuple): d=d[-1]
            if d and len(d)>=80:
                f=struct.unpack("<20f", d[:80])
                good=[(f[i*4+1],f[i*4+2],f[i*4+3]) for i in range(5) if all(abs(f[i*4+1+k])<3000 for k in range(3))]
                if good:
                    x=med([g[0] for g in good]); y=med([g[1] for g in good]); z=med([g[2] for g in good])
                    await broadcast(json.dumps({"x":round(x,3),"y":round(y,3),"z":round(z,3)}))
            # --- area: 1x por segundo, so troca depois de 2 leituras iguais (anti-flicker) ---
            if tick%HZ==0:
                pre,ar,dbg=await read_area(ps4,pid)
                print("AREA read:",dbg)
                await broadcast(json.dumps({"adbg":dbg}))     # sempre, pro HUD
                if ar and ar!=last_area:
                    if ar==pend: pend_n+=1
                    else: pend=ar; pend_n=1
                    if pend_n>=2:
                        last_area=ar; pend=None; pend_n=0
                        print("AREA CHANGE ->",ar)
                        await broadcast(json.dumps({"area":ar}))
            errs=0                               # leitura ok -> zera o contador de falhas
        except Exception as e:
            errs+=1; print("read err:", e)
            if errs>=3:                          # conexao ps4debug caiu -> reconecta (nao congela)
                print("conexao ps4debug caiu; reconectando...")
                if await connect(): errs=0; base=None
                else: await asyncio.sleep(2)
        tick+=1
        await asyncio.sleep(1.0/HZ)

async def connect():
    """(Re)estabelece a conexao ps4debug: acha o pid, resolve eboot_base. Retorna ps4 ou None.
    Usado no start E na auto-reconexao (ps4debug atende 1 cliente; outra ferramenta que conecte derruba a nossa)."""
    global eboot_base, AREA_ADDRS, PS4, PID
    try:
        ps4=ps4debug.PS4Debug(PS4_IP)
        if asyncio.iscoroutine(ps4): ps4=await ps4
        procs=await ps4.get_processes()
        pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
        if pid is None: print("DS2 process not found"); return None
        maps=await ps4.get_process_maps(pid)
        exe=[m.start for m in maps if 'executable' in str(getattr(m,'name','') or '')]
        eboot_base=min(exe) if exe else 0x400000
        AREA_ADDRS=[eboot_base+o for o in AREA_OFFS]
        PS4=ps4; PID=pid
        b=await resolve_base(ps4,pid)
        print(f"ps4debug OK — pid={pid} eboot_base=0x{eboot_base:X}" + (f" position->0x{b:X}" if b else " (position not resolved yet)"))
        return ps4
    except Exception as e:
        print("connect failed:", repr(e)); return None

async def main():
    start_http()
    ps4=await connect()
    while ps4 is None:
        print("retry connect em 3s..."); await asyncio.sleep(3); ps4=await connect()
    print(f">>> OPEN IN BROWSER:  http://localhost:{HTTP_PORT}/radar.html  <<<")
    async with websockets.serve(handler,"localhost",WS_PORT):
        await reader()

if __name__=="__main__":
    asyncio.run(main())
