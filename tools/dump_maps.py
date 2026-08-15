# -*- coding: utf-8 -*-
"""
Dumpa o MAPA DE MEMORIA do processo do DS2 (pra identificar a regiao real do eboot).
Escreve maps_dump.txt e mostra um resumo. Precisa PS4CheaterNeo FECHADO.
"""
import asyncio, os
PS4_IP="192.168.1.104"
_DIR=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(_DIR,"maps_dump.txt")

async def main():
    import ps4debug
    ps4=ps4debug.PS4Debug(PS4_IP)
    if asyncio.iscoroutine(ps4): ps4=await ps4
    procs=await ps4.get_processes()
    pid=next((getattr(p,"pid",None) for p in procs if "eboot" in str(getattr(p,"name",""))),None)
    if pid is None: print("DS2 nao encontrado"); return
    maps=await ps4.get_process_maps(pid)
    maps=sorted(maps,key=lambda m:m.start)
    lines=[]
    for m in maps:
        name=getattr(m,"name","") or ""
        prot=getattr(m,"prot",0)
        sz=(m.end-m.start)
        lines.append(f"0x{m.start:>011X} - 0x{m.end:>011X}  {sz/1024/1024:8.2f}MB  prot=0x{prot:X}  {name}")
    with open(OUT,"w",encoding="utf-8") as f:
        f.write(f"pid={pid}  total regioes={len(maps)}\n\n")
        f.write("\n".join(lines))
        # resumo: regioes executaveis (modulo) e as que tem nome de eboot
        f.write("\n\n=== EXECUTAVEIS (prot & 0x4) ===\n")
        for m in maps:
            if getattr(m,"prot",0)&0x4:
                f.write(f"0x{m.start:X} - 0x{m.end:X}  prot=0x{m.prot:X}  {getattr(m,'name','')}\n")
        f.write("\n=== COM 'eboot'/'DRAKS'/'.self' NO NOME ===\n")
        for m in maps:
            nm=str(getattr(m,"name","") or "")
            if any(t in nm.lower() for t in ("eboot","draks","self","cusa")):
                f.write(f"0x{m.start:X} - 0x{m.end:X}  prot=0x{m.prot:X}  {nm}\n")
    print(f"OK -> {OUT}  ({len(maps)} regioes)")
    # tambem imprime as primeiras/executaveis no console
    print("\nEXECUTAVEIS:")
    for m in maps:
        if getattr(m,"prot",0)&0x4:
            print(f"  0x{m.start:X} - 0x{m.end:X}  prot=0x{m.prot:X}  {getattr(m,'name','')}")

if __name__=="__main__":
    asyncio.run(main())
