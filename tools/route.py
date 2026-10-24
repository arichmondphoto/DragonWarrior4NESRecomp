# usage: route.py SPEC OUT ; SPEC lines: "tap BTN [n] [gap]" or "wait N" or "at F"
import sys
f=0; out=[]
for ln in open(sys.argv[1]):
    p=ln.split('#')[0].split()
    if not p: continue
    if p[0]=='at': f=int(p[1])
    elif p[0]=='wait': f+=int(p[1])
    elif p[0]=='hold':
        out+=[f"{f} {p[1]}",f"{f+int(p[2])} -"]; f+=int(p[2])+(int(p[3]) if len(p)>3 else 10)
    elif p[0]=='tap':
        n=int(p[2]) if len(p)>2 else 1; gap=int(p[3]) if len(p)>3 else 12
        for _ in range(n): out+=[f"{f} {p[1]}",f"{f+4} -"]; f+=gap
open(sys.argv[2],'w').write("\n".join(out)+"\n"); print("end frame",f)
