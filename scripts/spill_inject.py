# Spill injection for a register-capped static baseline (VKSIM_SPILL_SPEC).
#
#   python3 spill_inject.py spec <elf.o> <orig.ptx> <ptxas log> <out.spec>
#       From a ptxas -lineinfo -maxrregcount N object of the shader: every STL/LDL
#       in the SASS, its width and stack offset, and the original PTX line it maps
#       to through the ELF line table (readelf --debug-dump=decodedline; nvdisasm -g
#       puts line annotations at the wrong instructions in CUDA 11.1).
#   python3 spill_inject.py inject <shader.ptx> <spec>
#       Exit 0 and write spill_injected/<shader.ptx> (same file name, which the
#       simulator reads the shader number from) when the shader is the one the spec
#       was made from, exit 3 when it is another shader. The accesses of a line are
#       put on that same line, so PTX line numbers do not change: LDLs before the
#       instruction, STLs after it (before it for a branch / return / call). They
#       read and write a .local array the size of the SASS stack frame at the SASS
#       offsets, with dummy registers, so results are unchanged. Loads go round a
#       pool of 256 registers (%__spl*); stores read %__sps0-3.
#   python3 spill_inject.py info <shader.ptx> <spec>
#       Set the register count in <shader.ptx>info to the spec's.
#   python3 spill_inject.py tsave <orig.ptx> <orig.ptxlive> <out.spec> [<spill spec>]
#       Registers saved across every trace_ray: the GPRs live both at the nearest
#       PTX line before the trace_ray and at the nearest one after its end_trace_ray
#       that have SASS (per-line live sets of generate_rt_livetable.py, i.e. the
#       ptxas allocation the simulator uses). They are stored after the PTX
#       instruction before the trace_ray and loaded before the first one after the
#       end_trace_ray, 16 bytes per access (the rest 8 / 4), into an area after the
#       spill spec's frame when one is given (its accesses and register count are
#       kept), else with the shader's own register count.
# <spec> can be several specs separated by ':'; a shader gets the first one it matches.
# Shaders are matched by line count and by the text of every line with a spill,
# with label numbers masked (Mesa numbers labels across all shaders it compiles,
# so the same shader gets different label numbers in different runs).

import bisect
import hashlib
import os
import re
import subprocess
import sys

POOL = 256
CTRL = ("bra", "brx", "ret", "exit", "call", "trap")


def norm(line):
    s = line.strip()
    # digits in every name that is not a %register (labels, the entry name)
    s = re.sub(r"(?<![%\w])[A-Za-z_]\w*", lambda m: re.sub(r"\d+", "#", m.group(0)), s)
    return hashlib.md5(s.encode()).hexdigest()[:12]


def make_spec(obj, ptx, log, out):
    env = dict(os.environ, PATH="/usr/local/cuda-11.1/bin:" + os.environ.get("PATH", ""))
    dis = subprocess.run(["nvdisasm", obj], env=env, stdout=subprocess.PIPE, check=True).stdout.decode().splitlines()
    dec = subprocess.run(["readelf", "--debug-dump=decodedline", obj], stdout=subprocess.PIPE).stdout.decode()
    table = sorted((int(m.group(2), 16), int(m.group(1)))
                   for m in re.finditer(r"^orig\.ptx\s+(\d+)\s+(0x[0-9a-f]+|0)\s", dec, re.M))
    starts = [a for a, _ in table]
    txt = open(log).read()
    regs = int(re.search(r"Used (\d+) registers", txt).group(1))
    frame = int(re.search(r"(\d+) bytes stack frame", txt).group(1))
    lines = open(ptx).read().split("\n")
    acc, text_sec = [], False
    for l in dis:
        if re.match(r"^\s*\.section\s", l):
            text_sec = ".text." in l
            continue
        m = re.match(r"^\s*/\*([0-9a-f]{4,})\*/\s+(.*?)\s*[;}]", l)
        if not text_sec or not m:
            continue
        t = m.group(2).strip().lstrip("{").strip()
        s = re.match(r"(?:@!?P\w+\s+)?(STL|LDL)(\S*)\s+(.*)$", t)
        if not s:
            continue
        w = 16 if ".128" in s.group(2) else 8 if ".64" in s.group(2) else 4
        if re.search(r"\.(U|S)(8|16)", s.group(2)):
            sys.exit("spill_inject: sub-word spill %s" % t)
        a = re.search(r"\[R1(?:\+(0x[0-9a-f]+))?\]", s.group(3))
        if not a:
            sys.exit("spill_inject: spill not relative to R1: %s" % t)
        off = int(a.group(1), 16) if a.group(1) else 0
        i = bisect.bisect_right(starts, int(m.group(1), 16)) - 1
        if i < 0:
            sys.exit("spill_inject: no line for %s" % t)
        assert off + w <= frame and off % w == 0, t
        acc.append((table[i][1], "LD" if s.group(1) == "LDL" else "ST", w, off))
    with open(out, "w") as f:
        f.write("spill_spec 1\nregs %d\nframe %d\nlines %d\n" % (regs, frame, len(lines)))
        for line in sorted({a[0] for a in acc}):
            f.write("L %d %s\n" % (line, norm(lines[line - 1])))
        for a in acc:
            f.write("A %d %s %d %d\n" % a)
    print("spill spec %s: regs %d, frame %d, %d STL, %d LDL on %d lines"
          % (out, regs, frame, sum(a[1] == "ST" for a in acc), sum(a[1] == "LD" for a in acc),
             len({a[0] for a in acc})))


def read_spec(path):
    spec = dict(L={}, A={})
    for l in open(path):
        p = l.split()
        if p[0] in ("regs", "frame", "lines"):
            spec[p[0]] = int(p[1])
        elif p[0] == "L":
            spec["L"][int(p[1])] = p[2]
        elif p[0] == "A":
            spec["A"].setdefault(int(p[1]), []).append((p[2], int(p[3]), int(p[4])))
    return spec


def matches(lines, spec):
    if len(lines) != spec["lines"]:
        return False
    return all(norm(lines[n - 1]) == h for n, h in spec["L"].items())


def find_spec(lines, spec_paths):
    for p in spec_paths.split(":"):
        spec = read_spec(p)
        if matches(lines, spec):
            return spec
    return None


INST = re.compile(r"^\s*(?:@!?%\S+\s+)?[a-z_]\w*(?:\.\S+)?(?:\s|;)")


def is_inst(line):
    code = line.split("//")[0].strip()
    return bool(code) and not code.startswith(".") and not code.endswith(":") and bool(INST.match(code))


def make_tsave(ptx, livetab, out, spill=None):
    lines = open(ptx).read().split("\n")
    live = {}
    for l in open(livetab):
        p = l.split()
        if p[0] == "alloc":
            alloc = int(p[1])
        else:
            live[int(p[0])] = int(p[2], 16)
    base = read_spec(spill) if spill else dict(regs=alloc, frame=0, L={}, A={})
    assert not spill or base["lines"] == len(lines), "spill spec is for another shader"
    area = (base["frame"] + 15) // 16 * 16
    tr = [i for i, l in enumerate(lines, 1) if l.strip().startswith("trace_ray ")]
    en = [i for i, l in enumerate(lines, 1) if l.strip().startswith("end_trace_ray")]
    assert len(tr) == len(en) and all(t < e for t, e in zip(tr, en))
    acc, L, nmax = [], dict(base["L"]), 0
    for t, e in zip(tr, en):
        pre = max(n for n in live if n < t)
        post = min(n for n in live if n > e)
        n = bin(live[pre] & live[post]).count("1")
        st = max(i for i in range(1, t) if is_inst(lines[i - 1]))
        ld = min(i for i in range(e + 1, len(lines) + 1) if is_inst(lines[i - 1]))
        for i in list(range(st + 1, t)) + list(range(e + 1, ld)):   # same block: no label in between
            assert not lines[i - 1].split("//")[0].strip().endswith(":"), (t, i)
        offs, o = [], 0
        while o < 4 * n:
            w = 16 if 4 * n - o >= 16 else 8 if 4 * n - o >= 8 else 4
            offs.append((w, area + o))
            o += w
        acc += [(st, "ST", w, off) for w, off in offs] + [(ld, "LD", w, off) for w, off in offs]
        L[st], L[ld] = norm(lines[st - 1]), norm(lines[ld - 1])
        nmax = max(nmax, n)
        print("tsave %s: trace_ray line %d: %d registers (live %d before at line %d, %d after at line %d); "
              "%d st after line %d, %d ld before line %d"
              % (ptx, t, n, bin(live[pre]).count("1"), pre, bin(live[post]).count("1"), post, len(offs), st, len(offs), ld))
    frame = area + (4 * nmax + 15) // 16 * 16
    with open(out, "w") as f:
        f.write("spill_spec 1\nregs %d\nframe %d\nlines %d\n" % (base["regs"], frame, len(lines)))
        for line in sorted(L):
            f.write("L %d %s\n" % (line, L[line]))
        for line, a in base["A"].items():
            for kind, w, off in a:
                f.write("A %d %s %d %d\n" % (line, "LD" if kind == "LD" else "ST", w, off))
        for a in acc:
            f.write("A %d %s %d %d\n" % a)
    print("tsave spec %s: regs %d, frame %d (save area at %d), %d trace_ray" % (out, base["regs"], frame, area, len(tr)))


def inject(ptx, spec_path):
    lines = open(ptx).read().split("\n")
    spec = find_spec(lines, spec_path)
    if not spec:
        return 3
    entry = next(i for i, l in enumerate(lines) if l.lstrip().startswith(".entry") and l.rstrip().endswith("{"))
    assert entry + 1 not in spec["A"]
    lines[entry] += (" .local .align 16 .b8 __spill_frame[%d]; .reg .b32 %%__sps<4>; .reg .b32 %%__spl<%d>;"
                     % (spec["frame"], POOL)) + "".join(" mov.b32 %%__sps%d, 0;" % i for i in range(4))
    nxt = 0
    for n, accs in spec["A"].items():
        text = lines[n - 1]
        c = text.find("//")
        code, comment = (text[:c], text[c:]) if c >= 0 else (text, "")
        indent = code[:len(code) - len(code.lstrip())]
        code = code.strip()
        assert code.endswith(";"), (n, text)
        opcode = re.sub(r"^@!?%\S+\s+", "", code).split()[0]
        lds, sts = [], []
        for kind, w, off in accs:
            k = w // 4
            if kind == "LD":
                if nxt + k > POOL:
                    nxt = 0
                regs = ["%%__spl%d" % (nxt + j) for j in range(k)]
                nxt += k
                dst = regs[0] if k == 1 else "{%s}" % ",".join(regs)
                lds.append("ld.local%s.b32 %s, [__spill_frame+%d];" % ("" if k == 1 else ".v%d" % k, dst, off))
            else:
                src = "%__sps0" if k == 1 else "{%s}" % ",".join("%%__sps%d" % j for j in range(k))
                sts.append("st.local%s.b32 [__spill_frame+%d], %s;" % ("" if k == 1 else ".v%d" % k, off, src))
        if opcode.split(".")[0] in CTRL or opcode.startswith("call"):
            parts = lds + sts + [code]
        else:
            parts = lds + [code] + sts
        lines[n - 1] = indent + " ".join(parts) + (" " + comment if comment else "")
    out = os.path.join(os.path.dirname(os.path.abspath(ptx)), "spill_injected", os.path.basename(ptx))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write("\n".join(lines))
    print("spill_inject: %s -> %s (%d lines, frame %d, regs %d)"
          % (ptx, out, len(spec["A"]), spec["frame"], spec["regs"]))
    return 0


def info(ptx, spec_path):
    spec = find_spec(open(ptx).read().split("\n"), spec_path)
    assert spec, ptx
    path = ptx + "info"
    txt = open(path).read()
    new, n = re.subn(r"Used \d+ registers", "Used %d registers" % spec["regs"], txt)
    assert n >= 1, path
    open(path, "w").write(new)
    print("spill_inject: %s registers -> %d" % (path, spec["regs"]))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "spec":
        make_spec(*sys.argv[2:6])
    elif cmd == "inject":
        sys.exit(inject(sys.argv[2], sys.argv[3]))
    elif cmd == "info":
        sys.exit(info(sys.argv[2], sys.argv[3]))
    elif cmd == "tsave":
        make_tsave(*sys.argv[2:6])
    else:
        sys.exit("usage: spill_inject.py spec|inject|info|tsave ...")
