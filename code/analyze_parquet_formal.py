#!/usr/bin/env python3
"""Analyze saved measurements and regenerate figures without rerunning queries."""

import argparse
import csv
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/marine-course-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import run_parquet_pilot as common
import run_parquet_formal as formal


LABELS = {"random": "Random", "station_first": "Station first", "time_first": "Time first"}
COLORS = {"random": "#8c98a6", "station_first": "#ce8f39", "time_first": "#147d83"}
INTS = {"window_hours", "count", "repetitions", "execution_order", "repetition", "query_position", "layout_position", "start_monotonic_ns", "candidate_row_groups_estimate", "total_row_groups", "candidate_rows_estimate", "candidate_compressed_column_bytes_estimate", "candidate_groups", "groups_with_matching_rows", "false_positive_groups", "false_positive_boundary_groups", "matching_rows"}
FLOATS = {"elapsed_ms", "mean_sst", "mean_ms", "median_ms", "min_ms", "max_ms", "q25_ms", "q75_ms"}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return [{key: (None if value == "" else int(value) if key in INTS else float(value) if key in FLOATS else value)
                 for key, value in row.items()} for row in csv.DictReader(stream)]


def costs_for_role(rows, role, nonempty=False):
    selected = [row for row in rows if row["role"] == role and (not nonempty or row["count"] > 0)]
    return formal.mean_costs(selected)


def save_figure(fig, destination, name):
    fig.savefig(destination / (name + ".png"), dpi=160, facecolor="white")
    fig.savefig(destination / (name + ".pdf"), facecolor="white")
    plt.close(fig)


def plot_facets(records, value_key, title, ylabel, destination, name, logarithmic=False):
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7), squeeze=False)
    rng = __import__("random").Random(20261115)
    for row_index, (kind, windows) in enumerate([("Q1", [24, 168, 720]), ("Q2", [1, 24, 168])]):
        for column_index, hours in enumerate(windows):
            ax = axes[row_index][column_index]
            for index, layout in enumerate(common.LAYOUTS):
                values = [r[value_key] for r in records if r["role"] == "validation" and r["kind"] == kind and r["window_hours"] == hours and r["layout"] == layout]
                box = ax.boxplot([values], positions=[index], widths=0.48, patch_artist=True, showfliers=False,
                                 medianprops={"color": "#172c40", "linewidth": 1.6},
                                 whiskerprops={"color": COLORS[layout]}, capprops={"color": COLORS[layout]})
                box["boxes"][0].set(facecolor=COLORS[layout], alpha=0.23, edgecolor=COLORS[layout])
                ax.scatter([index + rng.uniform(-0.10, 0.10) for _ in values], values, color=COLORS[layout], s=16, alpha=0.8, zorder=3)
            duration = f"{hours // 24} day(s)" if hours >= 24 else f"{hours} hour"
            ax.set_title(f"{kind}: {duration}", fontsize=11)
            ax.set_xticks(range(3), list(LABELS.values()), fontsize=8)
            if logarithmic:
                ax.set_yscale("log")
            else:
                ax.set_ylim(-1, 47)
            ax.grid(axis="y", alpha=0.2)
            if column_index == 0:
                ax.set_ylabel(ylabel)
    fig.suptitle(title, fontsize=15, y=0.98)
    note = ("Each dot: one query's median over 5 warm executions. Scheduled empty queries are retained."
            if logarithmic else "Each dot: a metadata candidate-group estimate. These are not measured DuckDB reads or disk I/O.")
    fig.text(0.5, 0.02, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    save_figure(fig, destination, name)


def analyze(run_dir):
    status = json.loads((run_dir / "run_status.json").read_text())
    protocol = json.loads((run_dir / "protocol.json").read_text())
    selection_path = run_dir / "frozen_selection.json"
    selection = json.loads(selection_path.read_text())
    rows = read_csv(run_dir / "measurements.csv")
    summaries = read_csv(run_dir / "query_summary.csv")
    candidates = read_csv(run_dir / "candidate_row_groups.csv")
    diagnosis = read_csv(run_dir / "joint_match_summary.csv")
    correctness = json.loads((run_dir / "correctness.json").read_text())
    queries = json.loads((run_dir / "queries.json").read_text())
    layouts = json.loads((run_dir / "verified_layouts.json").read_text())
    tuning = [row for row in rows if row["role"] == "tuning"]
    validation = [row for row in rows if row["role"] == "validation"]
    recomputed = formal.fit_decisions(tuning, protocol["config"], protocol["pilot_config"])
    measured_counts = Counter((row["query_id"], row["layout"]) for row in rows if row["phase"] == "measured")
    warmup_counts = Counter((row["query_id"], row["layout"]) for row in rows if row["phase"] == "warmup")
    checks = {
        "run_passed": status["status"] == "passed",
        "108_unique_queries": len(queries) == len({q["query_id"] for q in queries}) == 108,
        "324_correct_answers": len(correctness["checks"]) == 324 and all(r["passed"] for r in correctness["checks"]),
        "1620_timings_five_per_combination": len(measured_counts) == 324 and set(measured_counts.values()) == {5} and sum(measured_counts.values()) == 1620,
        "324_extra_warmups": len(warmup_counts) == 324 and set(warmup_counts.values()) == {1},
        "selection_only_reproduced_from_tuning": recomputed["decisions"] == selection["decisions"],
        "frozen_selection_unchanged": common.digest(selection_path) == status["selection_sha256_before_validation"],
        "selection_frozen_before_validation": common.timestamp(selection["frozen_at_utc"]) <= common.timestamp(status["validation_started_at_utc"]),
        "tuning_file_matches_freeze": common.digest(run_dir / "measurements_tuning.csv") == selection["tuning_measurements_sha256"],
        "all_tuning_before_all_validation": max(r["execution_order"] for r in tuning) < min(r["execution_order"] for r in validation),
        "frozen_plan_matches": common.digest(run_dir / "formal_plan_frozen.md") == protocol["plan_sha256"],
        "script_and_helper_match": common.digest(Path(formal.__file__)) == protocol["script_sha256"] and common.digest(Path(common.__file__)) == protocol["helper_script_sha256"],
        "configuration_matches": common.digest(Path("config/formal_v1.json")) == protocol["config_sha256"],
        "parquet_files_unchanged": all(common.digest(Path(v["path"])) == v["file_sha256"] for v in layouts.values()),
        "same_44_row_groups": all(v["row_groups"] == 44 for v in layouts.values()),
        "all_diagnostic_counts_match_reference": all(r["matching_rows"] == json.loads((run_dir / "reference_answers.json").read_text())[r["query_id"]][0] for r in diagnosis),
    }
    if not all(checks.values()):
        raise AssertionError(checks)
    common.save_json(run_dir / "artifact_verification.json", checks)
    costs = {role: costs_for_role(rows, role) for role in ["tuning", "validation"]}
    nonempty_costs = {role: costs_for_role(rows, role, nonempty=True) for role in ["tuning", "validation"]}
    grid = []
    for decision in selection["decisions"]:
        p = decision["q1_proportion"]
        val = {layout: p * costs["validation"][layout]["Q1"] + (1 - p) * costs["validation"][layout]["Q2"] for layout in common.LAYOUTS}
        best = min(val[layout] for layout in protocol["config"]["candidate_layouts"])
        chosen_cost = val[decision["chosen_layout"]]
        grid.append({"q1_proportion": p, "chosen_layout": decision["chosen_layout"],
                     "tuning_station_first_ms": decision["tuning_costs_ms"]["station_first"],
                     "tuning_time_first_ms": decision["tuning_costs_ms"]["time_first"],
                     "validation_chosen_ms": chosen_cost, "validation_station_first_ms": val["station_first"],
                     "validation_time_first_ms": val["time_first"], "validation_random_ms": val["random"],
                     "validation_oracle_among_two_ms": best, "regret_ms": chosen_cost - best,
                     "regret_percent": 100 * (chosen_cost / best - 1),
                     "matches_validation_best": math.isclose(chosen_cost, best, abs_tol=1e-12)})
    common.save_csv(run_dir / "selection_validation.csv", grid)
    class_rows = []
    for role in ["tuning", "validation"]:
        for kind in ["Q1", "Q2"]:
            matching = [q for q in queries if q["role"] == role and q["kind"] == kind]
            empty = sum(next(r for r in summaries if r["query_id"] == q["query_id"])["count"] == 0 for q in matching)
            class_rows.append({"role": role, "kind": kind, "queries": len(matching), "empty_queries": empty,
                               **{layout + "_mean_ms": costs[role][layout][kind] for layout in common.LAYOUTS},
                               **{layout + "_nonempty_mean_ms": nonempty_costs[role][layout][kind] for layout in common.LAYOUTS}})
    common.save_csv(run_dir / "class_costs.csv", class_rows)
    boundary_rows = []
    for kind in ["Q1", "Q2"]:
        for layout in protocol["config"]["diagnostic_layouts"]:
            values = [r for r in diagnosis if r["role"] == "validation" and r["kind"] == kind and r["layout"] == layout and r["matching_rows"] > 0]
            boundary_rows.append({"kind": kind, "layout": layout, "nonempty_validation_queries": len(values),
                                  "mean_candidate_groups": statistics.mean(r["candidate_groups"] for r in values),
                                  "mean_groups_with_matches": statistics.mean(r["groups_with_matching_rows"] for r in values),
                                  "mean_false_positive_groups": statistics.mean(r["false_positive_groups"] for r in values),
                                  "total_false_positive_groups": sum(r["false_positive_groups"] for r in values),
                                  "boundary_false_positive_groups": sum(r["false_positive_boundary_groups"] for r in values)})
    common.save_csv(run_dir / "boundary_summary.csv", boundary_rows)
    metrics = {"costs_ms": costs, "nonempty_costs_ms": nonempty_costs,
               "selection_grid": grid, "class_summary": class_rows, "boundary_summary": boundary_rows,
               "selection_choices": sorted({r["chosen_layout"] for r in grid}),
               "grid_choices_matching_validation_best": sum(r["matches_validation_best"] for r in grid),
               "max_regret_percent": max(r["regret_percent"] for r in grid),
               "scope": "one dataset, two tuning dates and two validation dates, warm single-thread execution; grid points reuse the same measurements",
               "analysis_script_sha256": common.digest(Path(__file__)), "matplotlib_version": matplotlib.__version__}
    common.save_json(run_dir / "analysis_summary.json", metrics)
    figures = run_dir / "figures"
    figures.mkdir(exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    plot_facets(summaries, "median_ms", "Validation query latency (2024)", "Warm latency (ms, log scale)", figures, "validation_latency", True)
    plot_facets(candidates, "candidate_row_groups_estimate", "Validation metadata candidate row groups", "Candidate groups (out of 44)", figures, "validation_candidate_groups")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    for i, role in enumerate(["tuning", "validation"]):
        for layout in ["station_first", "time_first"]:
            values = [r[("tuning_" if role == "tuning" else "validation_") + layout + "_ms"] for r in grid]
            axes[i].plot([r["q1_proportion"] for r in grid], values, color=COLORS[layout], label=LABELS[layout], linewidth=2)
        if role == "validation":
            axes[i].scatter([r["q1_proportion"] for r in grid], [r["validation_chosen_ms"] for r in grid], facecolors="none", edgecolors="#172c40", s=48, linewidth=1.5, label="Tuning-selected policy", zorder=4)
        axes[i].set(title="Tuning (2023)" if i == 0 else "Held-out validation (2024)", xlabel="Proportion of Q1 queries", ylabel="Weighted mean warm latency (ms)")
        axes[i].set_xticks([0, 0.25, 0.5, 0.75, 1])
        axes[i].grid(alpha=0.2)
        axes[i].legend(fontsize=9)
    fig.suptitle("Sorting choice across query mixtures", fontsize=15)
    fig.text(0.5, 0.015, "Q1 and Q2 are normalized separately; mixture points reuse the same query measurements.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.045, 1, 0.94))
    save_figure(fig, figures, "selection_validation")
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    size_values = [layouts[layout]["file_bytes"] / 1024**2 for layout in common.LAYOUTS]
    bars = axes[0].bar(list(LABELS.values()), size_values, color=list(COLORS.values()))
    axes[0].bar_label(bars, fmt="%.2f", padding=3)
    axes[0].set(title="Same records and writer settings", ylabel="Parquet file size (MiB)", ylim=(0, max(size_values) * 1.17))
    labels = [r["kind"] + "\n" + LABELS[r["layout"]] for r in boundary_rows]
    values = [r["mean_false_positive_groups"] for r in boundary_rows]
    bars = axes[1].bar(labels, values, color=[COLORS[r["layout"]] for r in boundary_rows])
    axes[1].bar_label(bars, fmt="%.2f", padding=3)
    axes[1].set(title="Nonempty validation queries only", ylabel="Mean candidate groups with no matching rows", ylim=(0, max(values) * 1.25 + 0.1))
    axes[1].tick_params(axis="x", labelsize=8)
    fig.suptitle("Compression and conservative metadata ranges", fontsize=15)
    fig.text(0.5, 0.015, "Right panel: independent Arrow inspection, not a record of DuckDB's actual reads.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    save_figure(fig, figures, "layout_and_boundary")
    write_report(run_dir, status, metrics, selection, layouts)
    print(json.dumps({"checks_passed": len(checks), "costs_ms": costs, "nonempty_costs_ms": nonempty_costs,
                      "selection_choices": metrics["selection_choices"], "grid_matches": metrics["grid_choices_matching_validation_best"],
                      "max_regret_percent": metrics["max_regret_percent"], "boundary": boundary_rows}, ensure_ascii=False), flush=True)


def write_report(run_dir, status, metrics, selection, layouts):
    costs = metrics["costs_ms"]
    completed = datetime.fromisoformat(status["completed_at_utc"]).astimezone(timezone(timedelta(hours=8)))
    rel = "../" + run_dir.as_posix()
    lines = ["# 正式实验结果与排序选择验证", "", "仓库：https://github.com/wzyonepp/ocean-data-mining", "",
             f"完成时间：{completed.isoformat()}（香港时间）。", "",
             "## 1. 完成情况与研究范围", "",
             "按预留方案执行 108 条查询：54 条调整查询、54 条验证查询。三个 Parquet 布局均保持 713,823 条逻辑记录、44 个行组，以及相同的写入设置。324 次基表答案检查全部通过，保存 1,620 次计时和 324 次额外预热。", "",
             "调整集有 3 条空查询，验证集有 6 条空查询，均为 Q1；按原计划保留，不依据性能替换。额外报告非空查询结果。", "",
             "计时条件：Python 3.12.14、PyArrow 26.0.1、DuckDB 2.0.0，单查询线程，UTC，ZSTD 级别 3，每行组上限 16,384 行。查询直接读取同一组 Parquet 文件，采用预热后的引擎与系统缓存。", "",
             "## 2. 类型归一后的平均耗时", "",
             "下表按每条查询五次计时求平均，再在各查询类别内求平均，单位毫秒。Q1 与 Q2 分别归一，避免 48 条 Q1、6 条 Q2 的数量差异改变混合比例。图中的单查询分布另用五次中位数展示。", "",
             "| 集合 | 类型 | 查询数（空结果数） | 随机 | 站点优先 | 时间优先 |", "|---|---|---:|---:|---:|---:|"]
    for row in metrics["class_summary"]:
        lines.append(f"| {'调整集' if row['role']=='tuning' else '验证集'} | {row['kind']} | {row['queries']}（{row['empty_queries']}） | {row['random_mean_ms']:.3f} | {row['station_first_mean_ms']:.3f} | {row['time_first_mean_ms']:.3f} |")
    lines += ["", f"![验证集查询耗时]({rel}/figures/validation_latency.png)", "",
              "每个点代表一个查询五次测量的中位数，纵轴为对数刻度；箱线图描述不同查询的分布，不是置信区间。保留空查询，不能将所有点视作独立、同分布的重复实验。", "",
              "## 3. 调整集选择与验证集评价", "",
              "选择规则仅使用调整集耗时：对 Q1 比例 p∈{0,0.1,…,1}，按 p×Q1 平均耗时+(1-p)×Q2 平均耗时，选择站点优先或时间优先。选择结果在验证计时开始前保存，之后未修改。", ""]
    if metrics["selection_choices"] == ["time_first"]:
        lines += ["**调整集在全部 11 个设定比例上都选择时间优先。** 本次数据没有支持“随 Q1 比例变化而切换排序”这一预期；选择规则退化为固定时间优先。它不构成相对固定时间优先的额外性能改进。", ""]
    else:
        lines += ["调整集产生的具体排序建议、验证代价与遗憾值见逐比例结果；选择规则未经验证集调参。", ""]
    lines += [f"11 个比例点中，有 {metrics['grid_choices_matching_validation_best']} 个选择与验证集两种固定排序中的较低均值一致，最大相对遗憾为 {metrics['max_regret_percent']:.3f}%。比例点复用同一批查询测量，不能称为 11 次独立验证，也不意味着具有普遍最优性。", "",
              "比例曲线由已保存的单查询计时加权估算，不是另行回放 11 组混合查询序列；本次没有检验比例改变时缓存或并发交互是否满足这一可加模型。", "",
              f"![查询比例与选择验证]({rel}/figures/selection_validation.png)", "",
              "| Q1 比例 | 选择 | 验证：所选方案 ms | 验证：固定站点 ms | 验证：固定时间 ms | 遗憾 % |", "|---:|---|---:|---:|---:|---:|"]
    for row in metrics["selection_grid"]:
        if row["q1_proportion"] in [0, 0.5, 1]:
            lines.append(f"| {row['q1_proportion']:.1f} | {'时间优先' if row['chosen_layout']=='time_first' else '站点优先'} | {row['validation_chosen_ms']:.3f} | {row['validation_station_first_ms']:.3f} | {row['validation_time_first_ms']:.3f} | {row['regret_percent']:.3f} |")
    lines += ["", "## 4. 缺测与空查询的敏感性检查", "",
              "去除空查询只用于已有测量的补充分析，不重新选择正式查询、不替换主结果。验证集非空 Q1 共 42 条，非空 Q2 共 6 条：", "",
              "| 非空验证查询 | 随机 ms | 站点优先 ms | 时间优先 ms |", "|---|---:|---:|---:|"]
    for kind in ["Q1", "Q2"]:
        c = metrics["nonempty_costs_ms"]["validation"]
        lines.append(f"| {kind} | {c['random'][kind]:.3f} | {c['station_first'][kind]:.3f} | {c['time_first'][kind]:.3f} |")
    lines += ["", "该表用于检查结论是否主要由空结果驱动；其均值仍不能替代分站点、分窗口的具体结果。", "",
              "## 5. 行组范围、边界混合与压缩", "",
              f"![元数据候选行组]({rel}/figures/validation_candidate_groups.png)", "",
              "候选行组只表示按逐列 min/max 无法排除的组，不是 DuckDB 实际扫描行组或实际磁盘 I/O。另在全部计时结束后，用 PyArrow 单独读取两个有序布局的候选组，检查是否存在同时满足查询条件的记录。", "",
              "| 非空验证查询 | 布局 | 平均候选组 | 平均含匹配组 | 平均无匹配候选组 |", "|---|---|---:|---:|---:|"]
    for row in metrics["boundary_summary"]:
        lines.append(f"| {row['kind']} | {'站点优先' if row['layout']=='station_first' else '时间优先'} | {row['mean_candidate_groups']:.3f} | {row['mean_groups_with_matches']:.3f} | {row['mean_false_positive_groups']:.3f} |")
    lines += ["", f"![压缩体积与边界统计]({rel}/figures/layout_and_boundary.png)", "",
              "跨站点的边界组会使站点和时间的独立范围覆盖较宽，即使各条件都落在范围内，也可能没有联合匹配记录。独立行组诊断验证的是这一现象，不代表读取器没有其他跳过手段。统计跨查询累计次数时，同一物理行组可能被多个查询计入，因此是查询—行组组合次数，不是不同物理组的数量。", "",
              "文件大小也受排序影响：随机为 {:,} 字节，站点优先为 {:,} 字节，时间优先为 {:,} 字节。因此，本实验比较的是固定写入设置下排序的总体效果，不能把全部耗时差异单独归因于数据跳过。".format(*(layouts[name]["file_bytes"] for name in common.LAYOUTS)), "",
              "## 6. 成本、局限和可写入报告的贡献", "",
              f"选择计算本身约 {selection['calculation_ms']:.3f} ms；用于调整集的两个候选布局探测查询（含额外预热）累计约 {selection['tuning_candidate_query_ms_including_warmup']:.3f} ms，尚需考虑构建并保有两个布局的成本。本次未证明这些成本相对固定时间优先有额外回报。", "",
              "结论限于当前 8 个站点、两个调整日期与两个验证日期、既定窗口、单机暖缓存及五次重复。当前样本不能代表全部浮标系统，也没有进行跨硬件或冷缓存验证；个别查询的均值或中位数差异不等于统计显著性。", "",
              "可支撑的课程探索是：以受控实验检验站点/时间排序的适用边界，发现并核对边界行组的联合范围误保留，以及真实报告工作负载选择建议的验证结果和未获益情况。排序和工作负载布局已有研究，不声称算法首创。", "",
              "若进一步探索按站点对齐行组，应另设扩展方案，因为它会改变行组边界；不能混入本次仅改变排序的对照。", "",
              "## 7. 复现与原始证据", "",
              "在仓库根目录安装 requirements-formal.txt 中的锁定依赖，然后按快照校验恢复本地输入。不要用重新筛查覆盖已提交的数据清单，否则取得时间等变化会使快照哈希改变。运行：", "", "```bash",
              "python code/restore_parquet_inputs.py",
              "python code/run_parquet_formal.py --run-id formal_v1_replication",
              "python code/analyze_parquet_formal.py --run-dir results/formal_v1_replication", "```", "",
              "恢复脚本只写 data/ 下的输入和恢复日志，不改动已提交的源数据或结果清单；若上游响应无法匹配原 SHA-256，会明确失败，不静默使用新版本。新运行 ID 用于保留本次证据；分析脚本只读取保存结果，不再次执行查询。", "",
              f"- [冻结条件与实际环境]({rel}/protocol.json)",
              f"- [冻结的调整集选择]({rel}/frozen_selection.json)",
              f"- [逐次测量]({rel}/measurements.csv)",
              f"- [逐查询耗时汇总]({rel}/query_summary.csv)",
              f"- [逐比例选择验证]({rel}/selection_validation.csv)",
              f"- [逐候选组联合匹配诊断]({rel}/joint_match_diagnostic.csv)",
              f"- [结果完整性检查]({rel}/artifact_verification.json)",
              f"- [图表 PNG 与 PDF]({rel}/figures/)", ""]
    Path("report/07_formal_results.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path("results/formal_v1"))
    args = parser.parse_args()
    analyze(args.run_dir)
