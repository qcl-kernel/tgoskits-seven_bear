#!/usr/bin/env python3
"""Generate competition charts from the normalized evidence snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


COLORS = {
    "navy": "#16324F",
    "blue": "#247BA0",
    "cyan": "#39A9DB",
    "green": "#2A9D8F",
    "amber": "#E9C46A",
    "orange": "#F4A261",
    "red": "#E76F51",
    "ink": "#273043",
    "muted": "#687386",
    "grid": "#D9E2EC",
    "paper": "#F8FAFC",
    "white": "#FFFFFF",
}


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(args.repo_root).resolve())
    snapshot = load_json(root / args.snapshot)
    labels = load_json(root / args.labels)
    output = root / args.output
    output.mkdir(parents=True, exist_ok=True)

    configure_matplotlib()
    charts = (
        ("01-system-architecture", draw_architecture),
        ("02-rt-worst-of-runs", draw_rt_worst_of_runs),
        ("03-rt-p99-pairs", draw_rt_p99_pairs),
        ("04-control-effect", draw_control_effect),
        ("05-vision-loop-latency", draw_vision_loop_latency),
        ("06-vision-optimization", draw_vision_optimization),
        ("07-native-zephyr", draw_native_zephyr),
        ("08-isolation", draw_isolation),
        ("09-so100-id1", draw_so100),
        ("10-labeled-pilot", draw_labeled_pilot),
    )
    for stem, renderer in charts:
        figure = renderer(snapshot, labels)
        save_figure(figure, output / stem)
        plt.close(figure)
    print(f"CHART_GENERATION_PASS count={len(charts)} output={output.relative_to(root).as_posix()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--snapshot",
        default="competition/submission/data/evidence-snapshot.json",
    )
    parser.add_argument(
        "--labels",
        default="competition/submission/copy/chart-labels.json",
    )
    parser.add_argument(
        "--output",
        default="competition/submission/assets/charts",
    )
    return parser.parse_args()


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "competition/requirement.md").is_file():
            return candidate
    raise RuntimeError(f"repository root not found from {start}")


def load_json(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise TypeError(f"expected object in {path}")
    return parsed


def configure_matplotlib() -> None:
    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [
                "Source Han Sans SC",
                "Noto Sans CJK SC",
                "Noto Sans SC",
                "Microsoft YaHei",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "axes.edgecolor": COLORS["grid"],
            "axes.labelcolor": COLORS["ink"],
            "axes.titlecolor": COLORS["navy"],
            "axes.facecolor": COLORS["paper"],
            "figure.facecolor": COLORS["white"],
            "savefig.facecolor": COLORS["white"],
            "xtick.color": COLORS["muted"],
            "ytick.color": COLORS["muted"],
            "grid.color": COLORS["grid"],
            "grid.alpha": 0.65,
            "figure.dpi": 150,
        }
    )


def save_figure(figure: plt.Figure, stem: Path) -> None:
    figure.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
    figure.savefig(stem.with_suffix(".png"), dpi=220, bbox_inches="tight")


def title(ax: plt.Axes, text: str, subtitle: str | None = None) -> None:
    ax.set_title(text, loc="left", fontsize=18, fontweight="bold", pad=18)
    if subtitle:
        ax.text(
            0,
            1.015,
            subtitle,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9.5,
            color=COLORS["muted"],
        )


def draw_architecture(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    figure, ax = plt.subplots(figsize=(13.2, 7.4))
    ax.set_xlim(0, 13.2)
    ax.set_ylim(0, 7.4)
    ax.axis("off")
    ax.text(0.35, 7.05, labels["architecture_title"], fontsize=20, fontweight="bold", color=COLORS["navy"])
    ax.text(0.35, 6.72, labels["architecture_subtitle"], fontsize=10.5, color=COLORS["muted"])

    board = FancyBboxPatch(
        (0.35, 0.45),
        12.5,
        5.9,
        boxstyle="round,pad=0.02,rounding_size=0.18",
        linewidth=1.4,
        edgecolor=COLORS["navy"],
        facecolor="#F2F7FB",
    )
    ax.add_patch(board)
    ax.text(0.62, 6.05, "Orange Pi 5 Plus / RK3588", fontsize=12.5, fontweight="bold", color=COLORS["navy"])

    add_box(ax, 0.8, 3.55, 3.35, 2.0, COLORS["blue"], labels["starry_box"], fontsize=10.4)
    add_box(ax, 8.95, 3.55, 3.15, 2.0, COLORS["green"], labels["zephyr_box"])
    add_box(
        ax,
        4.75,
        4.05,
        3.55,
        1.15,
        COLORS["navy"],
        labels["axvisor_box"].replace("、设备拓扑、", "、设备拓扑、\n"),
        fontsize=9.4,
    )
    add_box(ax, 0.8, 1.05, 3.35, 1.65, COLORS["cyan"], labels["camera_npu_box"])
    add_box(
        ax,
        8.95,
        1.05,
        3.15,
        1.65,
        COLORS["orange"],
        labels["actuator_box"].replace(" + ", " +\n"),
        fontsize=9.4,
    )
    add_box(ax, 4.85, 1.05, 3.35, 1.65, COLORS["amber"], labels["network_box"], dark_text=True)

    connect(ax, (4.15, 4.55), (4.75, 4.55), COLORS["blue"])
    connect(ax, (8.3, 4.55), (8.95, 4.55), COLORS["green"])
    connect(ax, (2.48, 2.7), (2.48, 3.55), COLORS["cyan"])
    connect(ax, (10.52, 3.55), (10.52, 2.7), COLORS["orange"])
    connect(ax, (4.15, 1.88), (4.85, 1.88), COLORS["cyan"])
    connect(ax, (8.2, 1.88), (8.95, 1.88), COLORS["orange"])

    ax.text(6.52, 3.28, labels["closed_loop_label"], ha="center", va="center", fontsize=11, fontweight="bold", color=COLORS["navy"])
    ax.text(6.52, 0.66, labels["claim_boundary_label"], ha="center", fontsize=9.5, color=COLORS["red"])
    return figure


def add_box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    color: str,
    text: str,
    *,
    dark_text: bool = False,
    fontsize: float = 11.2,
) -> None:
    box = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.03,rounding_size=0.15",
        linewidth=0,
        facecolor=color,
        alpha=0.96,
    )
    ax.add_patch(box)
    ax.text(
        x + width / 2,
        y + height / 2,
        text,
        ha="center",
        va="center",
        fontsize=fontsize,
        fontweight="bold",
        color=COLORS["ink"] if dark_text else COLORS["white"],
        linespacing=1.45,
    )


def connect(ax: plt.Axes, start: tuple[float, float], end: tuple[float, float], color: str) -> None:
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=14,
            linewidth=2,
            color=color,
        )
    )


def draw_rt_worst_of_runs(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    metrics = snapshot["realtime"]["metrics"]
    keys = ["dispatch", "emulated_irq", "periodic_jitter", "direct_irq"]
    names = [labels[f"rt_metric_{key}"] for key in keys]
    shared = [metrics[key]["shared_worst_max_ns"] / 1_000_000.0 for key in keys]
    partitioned = [metrics[key]["partitioned_worst_max_ns"] / 1_000_000.0 for key in keys]
    improvements = [metrics[key]["worst_max_improvement_percent"] for key in keys]

    figure, ax = plt.subplots(figsize=(12.5, 6.8))
    y = list(range(len(keys)))
    height = 0.34
    ax.barh([value + height / 2 for value in y], shared, height, color=COLORS["red"], label=labels["shared_profile"])
    ax.barh([value - height / 2 for value in y], partitioned, height, color=COLORS["green"], label=labels["partitioned_profile"])
    ax.set_xscale("log")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.grid(axis="x")
    ax.set_xlabel(labels["rt_max_axis"])
    title(ax, labels["rt_worst_title"], labels["rt_worst_subtitle"])
    ax.legend(frameon=False, loc="upper right")
    for index, improvement in enumerate(improvements):
        ax.text(
            max(shared[index], partitioned[index]) * 1.08,
            index,
            f"{improvement:.3f}%",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=COLORS["navy"],
        )
    ax.text(0.99, -0.17, labels["observed_max_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["muted"])
    figure.tight_layout()
    return figure


def draw_rt_p99_pairs(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    metrics = snapshot["realtime"]["metrics"]
    keys = ["dispatch", "emulated_irq", "periodic_jitter", "direct_irq"]
    figure, axes = plt.subplots(2, 2, figsize=(12.4, 7.6), sharex=True)
    for ax, key in zip(axes.flat, keys, strict=True):
        values = metrics[key]["p99_pair_improvement_percent"]
        color = COLORS["blue"] if key == "dispatch" else COLORS["green"]
        ax.plot(range(1, 6), values, marker="o", linewidth=2.2, color=color)
        ax.axhline(0, color=COLORS["red"], linewidth=1, linestyle="--")
        ax.fill_between(range(1, 6), 0, values, alpha=0.12, color=color)
        ax.set_title(labels[f"rt_metric_{key}"], fontsize=11.5, fontweight="bold", loc="left")
        ax.set_xticks(range(1, 6))
        ax.grid(axis="y")
        for pair, value in enumerate(values, 1):
            ax.annotate(f"{value:.3f}%", (pair, value), xytext=(0, 7 if value >= 0 else -14), textcoords="offset points", ha="center", fontsize=7.6)
    figure.suptitle(labels["rt_p99_title"], x=0.07, ha="left", fontsize=18, fontweight="bold", color=COLORS["navy"])
    figure.text(0.07, 0.93, labels["rt_p99_subtitle"], fontsize=9.5, color=COLORS["muted"])
    figure.text(0.5, 0.035, labels["pair_axis"], ha="center", color=COLORS["muted"])
    figure.text(0.015, 0.5, labels["improvement_axis"], va="center", rotation="vertical", color=COLORS["muted"])
    figure.tight_layout(rect=(0.04, 0.06, 1, 0.9))
    return figure


def draw_control_effect(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    effect = snapshot["ai_control"]["control_effect"]
    keys = ["rmse_milli_c", "iae_milli_c_s", "max_overshoot_milli_c"]
    names = [labels[f"control_{key}"] for key in keys]
    manual = [100.0, 100.0, 100.0]
    neural = [effect[key]["neural"] / effect[key]["manual"] * 100.0 for key in keys]
    colors = [COLORS["green"], COLORS["green"], COLORS["red"]]

    figure, ax = plt.subplots(figsize=(11.8, 6.5))
    x = list(range(len(keys)))
    width = 0.34
    ax.bar([value - width / 2 for value in x], manual, width, color=COLORS["grid"], label=labels["manual_baseline"])
    bars = ax.bar([value + width / 2 for value in x], neural, width, color=colors, label=labels["neural_policy"])
    ax.axhline(100, color=COLORS["muted"], linewidth=1, linestyle="--")
    ax.set_xticks(x, names)
    ax.set_ylabel(labels["normalized_axis"])
    ax.set_ylim(0, 225)
    ax.grid(axis="y")
    title(ax, labels["control_title"], labels["control_subtitle"])
    ax.legend(frameon=False, loc="upper left")
    for bar, key, ratio in zip(bars, keys, neural, strict=True):
        change = effect[key]["neural_change_percent"]
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            ratio + 6,
            f"{change:+.2f}%",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
            color=COLORS["green"] if change < 0 else COLORS["red"],
        )
    ax.text(0.99, -0.16, labels["control_tradeoff_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["muted"])
    figure.tight_layout()
    return figure


def draw_vision_loop_latency(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    latency = snapshot["vision"]["continuous_loop"]["latency_us"]
    stages = ["inference_to_send", "transport", "end_to_end"]
    names = [labels[f"vision_{stage}"] for stage in stages]
    figure, ax = plt.subplots(figsize=(12, 6.7))
    x = list(range(len(stages)))
    width = 0.24
    for offset, statistic, color in (
        (-width, "median", COLORS["green"]),
        (0, "p95", COLORS["amber"]),
        (width, "max", COLORS["red"]),
    ):
        values = [latency[stage][statistic] / 1000.0 for stage in stages]
        bars = ax.bar([value + offset for value in x], values, width, color=color, label=labels[f"stat_{statistic}"])
        for bar, value in zip(bars, values, strict=True):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 18, f"{value:,.1f}", ha="center", fontsize=8, rotation=0)
    ax.set_xticks(x, names)
    ax.set_ylabel(labels["latency_ms_axis"])
    ax.grid(axis="y")
    title(ax, labels["vision_latency_title"], labels["vision_latency_subtitle"])
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.text(0.99, -0.16, labels["vision_latency_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["muted"])
    figure.tight_layout()
    return figure


def draw_vision_optimization(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    preprocess = snapshot["vision"]["preprocess"]
    core = snapshot["vision"]["npu_core"]
    metrics = [
        (labels["preprocess_letterbox_avg"], preprocess["letterbox_ms_avg"]["paired_improvement_median_percent"]),
        (labels["preprocess_total_avg"], preprocess["total_ms_avg"]["paired_improvement_median_percent"]),
        (labels["preprocess_total_p95"], preprocess["total_ms_p95"]["paired_improvement_median_percent"]),
        (labels["core_run_avg"], core["rknn_perf_run_ms_avg"]["paired_improvement_median_percent"]),
        (labels["core_run_p95"], core["rknn_perf_run_ms_p95"]["paired_improvement_median_percent"]),
        (labels["core_total_p95"], core["total_ms_p95"]["paired_improvement_median_percent"]),
    ]
    names = [item[0] for item in metrics]
    values = [item[1] for item in metrics]
    colors = [COLORS["green"] if value >= 0 else COLORS["red"] for value in values]
    figure, ax = plt.subplots(figsize=(12.2, 7.1))
    y = list(range(len(metrics)))
    bars = ax.barh(y, values, color=colors)
    ax.axvline(0, color=COLORS["ink"], linewidth=1)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlabel(labels["improvement_axis"])
    ax.grid(axis="x")
    title(ax, labels["vision_optimization_title"], labels["vision_optimization_subtitle"])
    for bar, value in zip(bars, values, strict=True):
        x = value + 0.8 if value >= 0 else -0.2
        ax.text(
            x,
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.3f}%",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=10,
            fontweight="bold",
        )
    ax.text(0.99, -0.14, labels["core_tradeoff_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["muted"])
    figure.tight_layout()
    return figure


def draw_native_zephyr(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    workloads = snapshot["native_rtos"]["workloads"]
    categories = [labels["native_wake_p99"], labels["native_wake_max"], labels["native_dispatch_p99"], labels["native_dispatch_max"]]
    idle = [
        workloads["idle"]["wake_p99_median_ns"],
        workloads["idle"]["wake_max_median_ns"],
        workloads["idle"]["dispatch_p99_median_ns"],
        workloads["idle"]["dispatch_max_median_ns"],
    ]
    stress = [
        workloads["cpu-stress"]["wake_p99_median_ns"],
        workloads["cpu-stress"]["wake_max_median_ns"],
        workloads["cpu-stress"]["dispatch_p99_median_ns"],
        workloads["cpu-stress"]["dispatch_max_median_ns"],
    ]
    figure, ax = plt.subplots(figsize=(12, 6.8))
    x = list(range(len(categories)))
    width = 0.35
    ax.bar([value - width / 2 for value in x], idle, width, color=COLORS["blue"], label=labels["idle_workload"])
    ax.bar([value + width / 2 for value in x], stress, width, color=COLORS["orange"], label=labels["stress_workload"])
    ax.set_xticks(x, categories)
    ax.set_ylabel(labels["nanoseconds_axis"])
    ax.grid(axis="y")
    title(ax, labels["native_title"], labels["native_subtitle"])
    ax.legend(frameon=False)
    for index, values in enumerate(zip(idle, stress, strict=True)):
        for offset, value in zip((-width / 2, width / 2), values, strict=True):
            ax.text(index + offset, value + 85, f"{value:,.0f}", ha="center", fontsize=8.5)
    ax.text(0.99, -0.16, labels["native_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["muted"])
    figure.tight_layout()
    return figure


def draw_isolation(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    isolation = snapshot["isolation"]
    figure, ax = plt.subplots(figsize=(12.8, 7.2))
    ax.set_xlim(0, 12.8)
    ax.set_ylim(0, 7.2)
    ax.axis("off")
    ax.text(0.3, 6.85, labels["isolation_title"], fontsize=19, fontweight="bold", color=COLORS["navy"])
    ax.text(0.3, 6.52, labels["isolation_subtitle"], fontsize=10, color=COLORS["muted"])

    add_box(ax, 0.7, 3.75, 2.7, 1.3, COLORS["blue"], labels["vm1_box"])
    add_box(ax, 4.0, 3.75, 2.7, 1.3, COLORS["green"], labels["vm2_box"])
    add_box(ax, 9.35, 3.75, 2.7, 1.3, COLORS["orange"], labels["vm3_box"])
    add_box(ax, 2.05, 1.45, 3.3, 1.0, COLORS["navy"], labels["segment1_box"])
    add_box(ax, 9.05, 1.45, 3.3, 1.0, COLORS["red"], labels["segment2_box"])
    connect(ax, (2.05, 3.75), (3.0, 2.45), COLORS["blue"])
    connect(ax, (5.35, 3.75), (4.4, 2.45), COLORS["green"])
    connect(ax, (10.7, 3.75), (10.7, 2.45), COLORS["orange"])
    ax.add_patch(FancyArrowPatch((5.35, 1.95), (9.05, 1.95), arrowstyle="|-|", linewidth=2.2, linestyle="--", color=COLORS["red"]))
    ax.text(7.2, 2.25, labels["isolation_barrier"], ha="center", color=COLORS["red"], fontsize=10.5, fontweight="bold")
    counters = labels["isolation_counters"].format(
        tcp_bytes=isolation["same_segment_tcp_bytes"],
        probes=isolation["cross_segment_udp_probes"],
        received=isolation["cross_segment_received"],
        unknown=isolation["drop_unknown_unicast"],
        spoof=isolation["drop_spoofed_sources"],
    )
    ax.text(0.7, 0.72, counters, fontsize=10.5, color=COLORS["ink"], linespacing=1.55)
    return figure


def draw_so100(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    actuator = snapshot["physical_actuator"]
    trace = actuator["trace"]
    elapsed = [sample["elapsed_ms"] for sample in trace]
    positions = [sample["position"] for sample in trace]
    torque = [sample["torque_enabled"] for sample in trace]
    figure, ax = plt.subplots(figsize=(12.5, 6.8))
    ax.plot(elapsed, positions, color=COLORS["blue"], linewidth=2.4, label=labels["encoder_position"])
    ax.axhline(actuator["trajectory"][0], color=COLORS["muted"], linestyle="--", linewidth=1, label=labels["planned_start"])
    ax.axhline(actuator["trajectory"][1], color=COLORS["orange"], linestyle="--", linewidth=1, label=labels["planned_outbound"])
    torque_start = next((elapsed[index] for index, enabled in enumerate(torque) if enabled), None)
    torque_end = next((elapsed[index] for index in range(len(torque) - 1, -1, -1) if torque[index]), None)
    if torque_start is not None and torque_end is not None:
        ax.axvspan(torque_start, torque_end, color=COLORS["amber"], alpha=0.18, label=labels["torque_window"])
    ax.scatter([elapsed[-1]], [positions[-1]], color=COLORS["green"], zorder=5)
    ax.annotate(
        labels["so100_final_annotation"].format(position=positions[-1]),
        (elapsed[-1], positions[-1]),
        xytext=(-125, -42),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": COLORS["green"]},
        fontsize=9.5,
    )
    ax.set_xlabel(labels["elapsed_ms_axis"])
    ax.set_ylabel(labels["encoder_axis"])
    ax.grid()
    title(ax, labels["so100_title"], labels["so100_subtitle"])
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.text(0.99, -0.16, labels["so100_boundary_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["red"])
    figure.tight_layout()
    return figure


def draw_labeled_pilot(snapshot: dict[str, Any], labels: dict[str, str]) -> plt.Figure:
    pilot = snapshot["vision"]["labeled_pilot"]
    baselines = pilot["fixed_baselines"]
    names = [labels["pilot_ai"], *[labels[item["policy_id"].replace("-", "_")] for item in baselines]]
    accuracy = [pilot["ai_accuracy_percent"], *[item["action_accuracy_percent"] for item in baselines]]
    wrong = [pilot["ai_wrong_direction_percent"], *[item["wrong_direction_percent"] for item in baselines]]
    figure, ax = plt.subplots(figsize=(11.8, 6.6))
    x = list(range(len(names)))
    width = 0.34
    first = ax.bar([value - width / 2 for value in x], accuracy, width, color=COLORS["green"], label=labels["pilot_accuracy"])
    second = ax.bar([value + width / 2 for value in x], wrong, width, color=COLORS["red"], label=labels["pilot_wrong_direction"])
    ax.set_xticks(x, names)
    ax.set_ylim(0, 105)
    ax.set_ylabel(labels["percent_axis"])
    ax.grid(axis="y")
    title(ax, labels["pilot_title"], labels["pilot_subtitle"])
    ax.legend(frameon=False)
    for bars in (first, second):
        for bar in bars:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2.5, f"{bar.get_height():.1f}%", ha="center", fontsize=9)
    ax.text(0.99, -0.16, labels["pilot_boundary_note"], transform=ax.transAxes, ha="right", fontsize=9, color=COLORS["red"])
    figure.tight_layout()
    return figure


if __name__ == "__main__":
    raise SystemExit(main())
