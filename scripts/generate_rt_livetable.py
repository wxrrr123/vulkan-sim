# Per-PTX-line live register table for the dynamic register allocation model
# (-gpgpu_dynreg). usage: python3 generate_rt_livetable.py <shader.ptx>
# writes <shader.ptx>live:
#   alloc <registers ptxas allocates for the kernel> sass <SASS instructions> mapped <with a PTX line>
#   <ptx line> <live GPRs> <live GPR set as hex, bit i = R<i>>
# The PTX goes through the same rewrite as generate_rt_ptxinfo.py (so the
# allocation matches the simulator's register count), with a '.loc' line before
# every PTX instruction that names its line in the original file. ptxas
# -lineinfo then attributes every SASS instruction to an original PTX line, and
# nvdisasm -plr gives the live GPRs at every SASS instruction. The line table is
# decoded with readelf: nvdisasm -g (CUDA 11.1) prints the line annotations at
# the wrong instructions (checked on a small kernel). A PTX line gets
# the largest count among its SASS instructions and the union of their sets.
# PTX lines with no SASS instruction are not listed.

import bisect
import os
import re
import shutil
import subprocess
import sys
import tempfile

ptx = os.path.abspath(sys.argv[1])
here = os.path.dirname(os.path.abspath(__file__))
bindir = os.path.join(os.environ.get("CUDA_INSTALL_PATH", ""), "bin")
ptxas = os.path.join(bindir, "ptxas") if os.path.exists(os.path.join(bindir, "ptxas")) else "ptxas"
nvdisasm = os.path.join(bindir, "nvdisasm") if os.path.exists(os.path.join(bindir, "nvdisasm")) else "nvdisasm"

work = tempfile.mkdtemp(prefix="livetable_")
try:
    # 1. '.loc 1 <line> 0' before every instruction, '.file 1' after .target
    out, filed = [], False
    for n, line in enumerate(open(ptx), 1):
        s = line.strip()
        code = s.split("//")[0].strip()
        is_inst = code and not code.startswith(".") and not code.startswith("{") \
            and not code.startswith("}") and not re.match(r"^[A-Za-z_$][\w$]*:$", code) \
            and not code.startswith("@@")
        if is_inst and filed:
            out.append("\t.loc 1 %d 0\n" % n)
        out.append(line)
        if not filed and (s.startswith(".address_size") or s.startswith(".target")):
            out.append('.file 1 "orig.ptx"\n')
            filed = True
    open(os.path.join(work, "loc.ptx"), "w").writelines(out)

    # 2. the simulator's rewrite, keeping its output
    env = dict(os.environ, GEN_RT_PTXINFO_KEEP=os.path.join(work, "rewritten.ptx"),
               PATH=bindir + os.pathsep + os.environ.get("PATH", ""))
    subprocess.run(["python3", os.path.join(here, "generate_rt_ptxinfo.py"), "loc.ptx"],
                   cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # 3. ptxas with line info, nvdisasm life ranges
    r = subprocess.run([ptxas, "-v", "-m", "32", "-lineinfo", "rewritten.ptx", "-o", "elf.o"],
                       cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.exit("livetable: ptxas failed on %s:\n%s" % (ptx, r.stdout.decode(errors="replace")))
    m = re.search(r"Used (\d+) registers", r.stdout.decode())
    alloc = int(m.group(1)) if m else 0
    dis = subprocess.run([nvdisasm, "-plr", "-lrm", "narrow", "elf.o"], cwd=work,
                         stdout=subprocess.PIPE, check=True).stdout.decode(errors="replace").splitlines()

    hdr = next(l for l in dis if re.search(r"\|\s+# 0\d*\s", l))
    off = hdr.index("# 0", hdr.index("|")) + 2   # column of R0
    width = hdr[off:].index(" ")         # number of GPR columns
    # line table: (start address, PTX line), the line holds up to the next start
    dec = subprocess.run(["readelf", "--debug-dump=decodedline", "elf.o"], cwd=work,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode(errors="replace")
    table = sorted((int(m.group(2), 16), int(m.group(1)))
                   for m in re.finditer(r"^orig\.ptx\s+(\d+)\s+(0x[0-9a-f]+|0)\s", dec, re.M))
    if not table:
        sys.exit("livetable: no line table in %s" % ptx)
    starts = [a for a, _ in table]
    cnt, regs, n_sass, n_mapped = {}, {}, 0, 0
    for l in dis:
        m = re.match(r"^\s*/\*([0-9a-f]+)\*/\s+(.*?)//\s*\|\s*(\d+)\s", l)
        if not m or len(l) < off + width:
            continue
        n_sass += 1
        i = bisect.bisect_right(starts, int(m.group(1), 16)) - 1
        if i < 0:
            continue
        line_no = table[i][1]
        n_mapped += 1
        live = int(m.group(3))
        bits = 0
        for i, c in enumerate(l[off:off + width]):
            if c in "^vx:":
                bits |= 1 << i
        cnt[line_no] = max(cnt.get(line_no, 0), live)
        regs[line_no] = regs.get(line_no, 0) | bits

    with open(ptx + "live", "w") as f:
        f.write("alloc %d sass %d mapped %d\n" % (alloc, n_sass, n_mapped))
        for k in sorted(cnt):
            f.write("%d %d %x\n" % (k, cnt[k], regs[k]))
    print("livetable %s: alloc %d, %d SASS (%d mapped), %d PTX lines" % (ptx, alloc, n_sass, n_mapped, len(cnt)))
finally:
    shutil.rmtree(work, ignore_errors=True)
