# 凍結基準設定（2026-10-06 起，之後所有實驗都用這組）

主線 2026-10-06 決定：不再逐項校準，直接凍結這組設定。之後所有報告都引用這份文件。不論 D−A 的結果如何都採用這組設定，
不會為了對上真卡而改參數。跟真卡仍有差異的地方列在「已知差異」一節。

## 1. 元件版本

| 元件 | 版本 | 位置 |
|---|---|---|
| Vulkan-Sim | fork `wxrrr123/vulkan-sim` 分支 `upstream-port`，模擬器程式碼 commit `0ecb3287`（本文件所在的 commit 只多了文件與 config） | container `/home/vulkan-sim-upstream11/vulkan-sim`（build v11） |
| Mesa（lavapipe + Vulkan-Sim 介面） | fork `wxrrr123/mesa-vulkan-sim` 分支 `upstream-port`，commit `c98094ac72f`（c98094ac72f4cf06b6e7cad9db46848e6790719e） | container `/home/vulkan-sim-upstream/mesa-vulkan-sim` |
| Lumen | `12610a7`（12610a779e1d72c23f5a196df9e8eadd46015813，修正 spatial-neighbor seed 預設值） | host `~/AQB8/Lumen`；container binary `/root/lumen-build/Lumen` |
| Embree | 3.12.2 | — |
| CUDA toolkit（ptxas，只用來算暫存器數） | 11.1 | `/usr/local/cuda-11.1` |

## 2. GPU 模型

兩份完整的設定檔在本 repo 的 `baseline/9sm/` 與 `baseline/1sm/`（`gpgpusim.config` + `config_turing_islip.icnt`，可直接當 run 目錄的設定；
各變體再附加第 5 節的選項）。

基礎是 Vulkan-Sim 附的 preset `configs/tested-cfgs/SM75_RTX2060`（`gpgpusim.config` 與 `config_turing_islip.icnt`），每 SM
的規格都不改，只改下面列出的項目。基礎檔另外多了三行執行用設定（不影響時序）：`-gpgpu_max_simulated_rt_kernels 9`、
`-save_embedded_ptx 1`、`-keep 1`。

### 兩種組態

| 項目 | 9 SM | 1 SM |
|---|---|---|
| 對應真卡 | 約 4.7 wave，對應 379×379 | 約 42.7 wave，對應 1072×1072 |
| `-gpgpu_n_clusters` | 9 | 1 |
| `-gpgpu_n_mem` | 4 | 1 |
| `-gpgpu_n_sub_partition_per_mchannel` | 2 | 1 |
| L2（`-gpgpu_cache:dl2`） | `S:64:128:99,L:B:m:L:P,A:192:4,32:0,32` | `S:64:128:88,L:B:m:L:P,A:192:4,32:0,32` |
| DRAM | 同 preset | `-dram_data_command_freq_ratio 2`、`-gpgpu_clock_domains 1365.0:1365.0:1365.0:3111.0` |

L2 用 Blackwell 每 SM 的大小（真卡 48 MiB／70 SM ≈ 702 KiB／SM）。sets 受 IPOLY hash 限制最多 64，所以用 ways 來放大
（9 SM：64 sets × 128 B × 99 ways × 8 sub-partitions；1 SM：88 ways × 1 sub-partition）。

### FP32／INT32 吞吐量改成 Blackwell 的值

```
-ptx_opcode_initiation_fp 1,1,1,1,4      # ADD,MAX,MUL,MAD,DIV；preset 是 2,2,2,2,4
-ptx_opcode_initiation_int 1,1,2,2,8,4   # ADD,MAX,MUL,MAD,DIV,SHFL；preset 是 2,2,2,2,8,4
```

FP32 add/mul/FMA 和 INT32 add/sub、compare/min/max 從每 SM 每 cycle 64 個改成 128 個。INT32 mul/mad 兩代都是 64，所以不改。
延遲不改。出處：CUDA C++ Programming Guide 12.9.1 的 Arithmetic Instructions 表，CC 7.5 欄與 CC 12.0 欄。

每個 scheduler 每 cycle 只發 1 條指令，所以每個 partition 每 cycle 最多執行 32 個 FP32 **或** INT32 運算，和 Blackwell
統一 FP32/INT32 單元的限制一致（RTX Blackwell whitepaper Figure 6）。

這項改動對結果幾乎沒有影響（和上一輪未改吞吐量的基準 `dn*` 相比，同 Lumen、同 L2）：

| 組態 | A cycles 變化 | D cycles 變化 | D−A（上一輪 → 凍結） |
|---|---|---|---|
| 9 SM | −1.3%～+0.1% | −0.5%～0.0% | Retrace +14.0/+15.1% → +15.0/+16.3%；Validate +14.9/+15.1% → +14.2/+14.9%；Temporal +3.1% → +3.3% |
| 1 SM | −0.3%～+0.1% | −0.2%～+0.1% | Retrace +16.0/+16.8% → +16.2/+16.8%；Validate +16.3/+16.7% → +16.0/+17.0%；Temporal +3.4% → +3.6% |

（Retrace、Validate 依序為 frame 0／frame 1。）差異都在雜訊內（9 SM ±1.5%，1 SM ±0.5%），issue 使用率也不變
（9 SM 約 37–39%、1 SM 約 40–42%，Temporal 約 26–28%）。

## 3. Lumen 執行設定

- 場景 `scenes/classroom/scene.xml`，128×128，path length 8，`LUMEN_FIXED_SEED=1`，跑 2 個 frame。
- 執行腳本 `/root/run_variant_sim.sh`，佇列 `/root/queue.sh`，產生凍結 run 的工作清單 `/root/mkqueue_frozen.sh`。
- 變體用環境變數選：`LUMEN_SER_VARIANT`、`LUMEN_VALIDATE_SER_VARIANT`、`LUMEN_TEMPORAL_SER_VARIANT`，值為 A／B／C／D。
- Cost sink：`LUMEN_RETRACE_COST_SINK=1 LUMEN_VALIDATE_COST_SINK=1 LUMEN_TEMPORAL_COST_SINK=1`。
  - 除了「A（無 sink）」以外，每個 run 都加。
  - 只有 Retrace 的 D−A 要和真卡比時才用無 sink 的 A，因為真卡的 Retrace D−A +4.17% 是用無 sink 的 A 量的。

## 4. 快速模式

只對量測的三個 pass 做時序模擬，Gen 和 Spatial 用功能模擬。

| launch | frame | pass | 模式 | `kernel_launch_uid` |
|---|---|---|---|---|
| 0 | 0 | Gen | 功能 | — |
| 1 | 0 | Retrace | 時序 | 2 |
| 2 | 0 | Validate | 時序 | 3 |
| 3 | 0 | Spatial | 功能 | — |
| 4 | 1 | Gen | 功能 | — |
| 5 | 1 | Temporal | 時序 | 6 |
| 6 | 1 | Retrace | 時序 | 7 |
| 7 | 1 | Validate | 時序 | 8 |
| 8 | 1 | Spatial | 功能 | — |

- 加 sink 的 run：`-vulkan_timing_marker CostSink`（shader 有 CostSink 標記的 launch 才做時序模擬）。
- A（無 sink）沒有標記，改用 `-vulkan_functional_launch_list 0,3,4,8` 選出同一組 launch。
- kernel 之間不清 L2（主線決定 (ii)）。注意：9 SM 的 Retrace f0 是第一個時序 kernel，L2 裡沒有 Gen 的資料，DRAM 讀取多約
  11%，cycles 多 0.7–1.9%。報告要註明這一點。
- 快速模式的結果不和舊的全時序結果混用。
- shader 的編號（`raygen_N`、`MESA_SHADER_RAYGEN_funcN_main`）每個 run 都不一樣，launch 的順序則固定。分析一律用
  `kernel_launch_uid` 對齊，模擬器選項一律用 launch 序號，不要用 shader 名稱。

## 5. 變體與重排單元設定

| 變體 | Lumen | 模擬器選項（9 SM／1 SM 不同處以「／」分隔） |
|---|---|---|
| A | A ＋ sink | `-gpgpu_rt_reorder_policy 0 -gpgpu_rt_reorder_release_k 0` |
| A（無 sink） | A | 同 A，加 `-vulkan_functional_launch_list 0,3,4,8`，不加 marker |
| D | D ＋ sink | 同 A |
| B | B ＋ sink | `-gpgpu_rt_reorder_policy 2 -gpgpu_rt_reorder_release_k 4 -gpgpu_rt_reorder_timeout 1000／500000` |
| C（天真版） | C ＋ sink | 同 B |
| C-TSU（M1，無存取成本） | C ＋ sink | `-gpgpu_rt_reorder_policy 3 -gpgpu_rt_tsu_pool_threads 128 或 512 -gpgpu_rt_reorder_timeout 500000` |
| C-TSU（M2，含存取成本） | C ＋ sink | M1 的設定，加 `-gpgpu_rt_tsu_spill_words 1=31,6=31,2=26,7=26,5=35` |

M2 的字數是 SASS 層在重排點活著的暫存器數（Retrace 31、Validate 26、Temporal 35）。量法：保留
`scripts/generate_rt_ptxinfo.py` 的 ptxas 輸出（sm_52、-m32），把 `reorder_thread_nv` 換成兩個寫到固定位址的 volatile store
當標記，再用 `nvdisasm -plr` 算標記處活著的 GPR。每個字對應一條 128 B 的 coalesced line：warp 進池時寫一條，regrouped warp 恢復時讀一條，
讀完才能繼續。這些 line 拆成 4 個 32 B 的 sector request 直接送進 interconnect，存在 L2。

## 6. 報告格式

- 一律和 A 比：C vs A 為主，再列 D vs A、C vs D、B vs A，最後列 C vs B 作參考。
- 和真卡 379×379 的數字並列。真卡數字是固定版 Lumen、三輪成對執行取中位數：

| | Retrace | Validate | Temporal |
|---|---|---|---|
| B−A | +4.80% | +1.39% | +14.35% |
| D−A | +4.17%（A 無 sink） | +6.40% | +1.13% |
| C−D | −3.34% | −8.84% | −17.50% |
| C−A | +0.95% | −3.02% | −16.14% |

- 單次 run 的雜訊：9 SM 約 ±1.5%（C 因為 SM 尾端不齊，最大到 3%）；1 SM 約 ±0.5%。

## 7. 已知限制：算鍵成本約為真卡的 3 倍

模擬器的 D−A（算鍵成本）在 Retrace、Validate 約 +14～+17%，真卡是 +4.17%（Retrace，A 無 sink）和 +6.40%（Validate），
約為真卡的 3 倍。主線決定列為已知限制，不再追查。已排除的來源（改了以後 D−A 都沒有明顯變化）：

| 來源 | 實驗 | 結果 |
|---|---|---|
| L1 大小 | L1D 32／64 KB、RT 不經 L1（2026-10-02 診斷） | D−A 仍 +14～+15% |
| L2 大小 | 改成 Blackwell 每 SM 的 L2（2026-10-04） | D 的重複讀取變成 L2 命中，D−A 只降 0～3 個百分點 |
| 指令數 | 真卡 D/A 的指令比例：Retrace warp ×1.070、thread ×1.186；Validate warp ×1.094、thread ×1.219 | 模擬器並沒有多跑指令，排除「模擬器指令較多」的假設 |
| FP32／INT32 吞吐量 | 64 → 128／cycle／SM（本文件第 2 節） | D−A 變化在 ±1 個百分點內 |

## 8. 已知差異（不改，只記錄）

| 項目 | 模擬器 | Turing 實測 [T4] | Blackwell 實測 [BW] |
|---|---|---|---|
| L2 命中延遲 | 約 190–220 cycles（推估，見註） | 約 188 | 約 358 |
| DRAM 延遲 | L1 miss 往返分布第二群在 256–511 cycles | 296 | 約 877 |
| SFU（MUFU）延遲 | 100 | 約 15 | 未知 |
| FP32／INT32 min/max 延遲 | 13 | 5（FMNMX） | 未知 |
| 位元運算、shift、mov 吞吐量 | 128／cycle／SM（ALU_OP 類，initiation 1） | 64 | 64 |
| L1 命中延遲 | config `l1_latency 20`，端到端未量 | 32 | 30–40 |
| 每 SM 最多 warps | 32 | 32 | 48（Lumen 各 kernel 都受暫存器限制，不影響） |

**時脈注意**：論文的延遲是以各自量測時的 SM cycle 計，而量測時脈、我們的真卡（鎖 1785 MHz）和模擬器（1365 MHz）三者都不同。
如果延遲的來源是固定的奈秒數（記憶體路徑大多如此），換算成我們真卡的 cycle 數是「論文 cycles × 1785 MHz ÷ 論文量測時脈」。
[BW] 沒有載明量測時脈；舉例來說，若是 2.6 GHz，358 cycles 約 138 ns，在 1785 MHz 的真卡上約 246 cycles，在 1365 MHz 的模擬器上
約 188 cycles。所以換成實際時間後，模擬器和真卡的差異可能比表上的 cycle 數小很多。

註：模擬器的 L1、L2 端到端延遲沒有實測，因為 Vulkan-Sim 的 CUDA 路徑跑不起來（pointer-chase kernel 最後判定 deadlock）。
L2 的數字是用 config（`l2_rop_latency 160` 加 interconnect）和 Lumen A run 的 `mf_lat_table` 推估的。

來源：
- [PG] CUDA C++ Programming Guide 12.9.1，Arithmetic Instructions 表與 Technical Specifications 表。
- [WP] NVIDIA RTX Blackwell GPU Architecture whitepaper v1.0，Figure 6。
- [BW] Jarmusch, Graddon, Chandrasekaran, "Dissecting the NVIDIA Blackwell Architecture with Microbenchmarks",
  arXiv 2507.10789v2，RTX 5080（GB203）：Table III、§VI-B、§VI-C、§VI-D。
- [T4] Jia, Maggioni, Smith, Scarpazza, "Dissecting the NVIDIA Turing T4 GPU via Microbenchmarking", arXiv 1903.07486，
  Table 3.1、Table 4.1。

完整對照表：`report-2026-10-06-compute-resources-a.md`。
