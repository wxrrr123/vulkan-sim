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


def inject(ptx, spec_path):
    spec = read_spec(spec_path)
    lines = open(ptx).read().split("\n")
    if not matches(lines, spec):
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
    spec = read_spec(spec_path)
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
    else:
        sys.exit("usage: spill_inject.py spec|inject|info ...")
