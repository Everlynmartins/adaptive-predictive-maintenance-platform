"""Static, reproducible EDA figures drawn exclusively from training telemetry."""

from pathlib import Path
import os
import tempfile

# Keep font cache writable on restricted Windows environments; respect user config.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "pm-matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from predictive_maintenance.analysis.fd001 import normalized_unit_curves
from predictive_maintenance.data.cmapss_schema import SENSOR_COLUMNS, SETTING_COLUMNS


def plot_training(
    train: pd.DataFrame, summary: dict, output: Path, *,
    failure_horizon: int, critical_horizon: int, normalized_points: int,
) -> list[str]:
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.titlesize": 11, "savefig.facecolor": "white",
    })
    filenames = []

    def save(fig, name):
        fig.savefig(output / name, dpi=170, bbox_inches="tight")
        plt.close(fig)
        filenames.append(name)

    lifetime = train.groupby("unit_id").cycle.max().sort_values(kind="stable")
    units = lifetime.iloc[[0, len(lifetime) // 2, -1]].index.tolist()
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    ax.hist(lifetime, bins="fd", color="#236b8e", edgecolor="white")
    ax.axvline(lifetime.median(), color="#c35322", label=f"Mediana: {lifetime.median():g}")
    ax.set(xlabel="Ciclo terminal da unidade", ylabel="Número de motores",
           title=f"Distribuição da vida útil — treino ({len(lifetime)} motores)")
    ax.legend()
    save(fig, "lifetime_distribution.png")

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for unit_id in units:
        unit = train[train.unit_id == unit_id]
        ax.plot(unit.cycle, unit.cycle.max() - unit.cycle,
                label=f"Motor {unit_id} | T={unit.cycle.max()}")
    ax.axhline(failure_horizon, color="#c35322", ls="--", label=f"H experimental={failure_horizon}")
    ax.axhline(critical_horizon, color="#7b3294", ls=":", label=f"H crítico experimental={critical_horizon}")
    ax.set(xlabel="Ciclo observado", ylabel="RUL real (ciclos)",
           title="Alvo retrospectivo RUL — motores de vida curta, mediana e longa")
    ax.legend(fontsize=9)
    save(fig, "rul_over_time.png")

    # Fixed examples support comparison across reruns, not an automatic feature selector.
    representatives = ["sensor_2", "sensor_11", "sensor_12", "sensor_14", "sensor_21", "sensor_6"]
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), layout="constrained")
    for ax, sensor in zip(axes.flat, representatives):
        for unit_id in units:
            unit = train[train.unit_id == unit_id]
            ax.plot(unit.cycle, unit[sensor], lw=.8, alpha=.85, label=f"Motor {unit_id}")
        ax.set(title=sensor, xlabel="Ciclo", ylabel="Valor original")
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Trajetórias brutas representativas — somente treino")
    save(fig, "sensor_trajectories.png")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    variances = [summary["columns"][s]["variance"] for s in SENSOR_COLUMNS]
    nonzero = [v if v > 0 else np.nan for v in variances]
    axes[0].bar(SENSOR_COLUMNS, nonzero, color="#236b8e")
    axes[0].set_yscale("log")
    axes[0].set(ylabel="Variância amostral (log)", title="Escalas originais: variâncias não são importância")
    for i, value in enumerate(variances):
        if value == 0:
            axes[0].text(i, .02, "zero", rotation=90, ha="center",
                         transform=axes[0].get_xaxis_transform(), fontsize=8)
    axes[1].bar(SENSOR_COLUMNS, [
        summary["columns"][s]["dominant_fraction"] for s in SENSOR_COLUMNS
    ], color="#42876c")
    axes[1].set(ylabel="Fração no valor mais comum", ylim=(0, 1.05))
    for ax in axes:
        ax.tick_params(axis="x", labelrotation=60)
    fig.suptitle("Variabilidade e concentração dos sensores — treino")
    save(fig, "sensor_variance.png")

    active = [s for s in SENSOR_COLUMNS if not summary["columns"][s]["constant"]]
    centered = train[active] - train.groupby("unit_id")[active].transform("mean")
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), layout="constrained")
    for ax, data, title in zip(
        axes, [train[active], centered],
        ["Pearson: todas as linhas", "Pearson: centralização por motor (retrospectiva)"],
    ):
        mat = data.corr()
        im = ax.imshow(mat, vmin=-1, vmax=1, cmap="RdBu_r")
        ax.set_xticks(range(len(active)), active, rotation=90)
        ax.set_yticks(range(len(active)), active)
        ax.set_title(title)
    fig.colorbar(im, ax=axes, shrink=.65, label="Correlação")
    fig.suptitle("Correlações no treino — constantes excluídas apenas desta figura")
    save(fig, "sensor_correlations.png")

    fig, axes = plt.subplots(5, 3, figsize=(13, 15), layout="constrained")
    for ax, sensor in zip(axes.flat, active):
        grid, curves, _ = normalized_unit_curves(train, sensor, normalized_points)
        center = float(train[sensor].mean())
        scale = float(train[sensor].std(ddof=1))
        curves = (curves - center) / scale
        mean = curves.mean(axis=0)
        ax.fill_between(grid, np.quantile(curves, .1, axis=0),
                        np.quantile(curves, .9, axis=0), color="#236b8e", alpha=.2)
        ax.plot(grid, mean, color="#236b8e")
        ax.set(title=sensor, xlabel="Vida normalizada retrospectiva", ylabel="z do treino")
    for ax in list(axes.flat)[len(active):]:
        ax.set_visible(False)
    fig.suptitle("Média por motor e faixa P10–P90 | cada motor tem o mesmo peso\n"
                 "Eixo e padronização apenas para EDA; não são atributos de inferência")
    save(fig, "normalized_sensor_life.png")

    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout="constrained")
    for ax, setting in zip(axes, SETTING_COLUMNS):
        ax.hist(train[setting], bins=25, color="#42876c", edgecolor="white")
        ax.set(title=setting, xlabel="Valor original", ylabel="Observações")
        ax.ticklabel_format(axis="x", style="plain", useOffset=False)
        ax.xaxis.set_major_locator(MaxNLocator(4))
    fig.suptitle("Configurações operacionais — distribuição no treino")
    save(fig, "operating_settings.png")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    for ax, sensor in zip(axes, ["sensor_11", "sensor_14"]):
        group = train.groupby("unit_id")[sensor]
        low, high = group.quantile(.1), group.quantile(.9)
        mean = group.mean()
        # Plot ranges independently: mean need not be contained in [P10, P90].
        ax.vlines(mean.index, low, high, color="#236b8e", alpha=.5)
        ax.scatter(mean.index, mean, s=12, color="#c35322")
        ax.set(title=f"{sensor}: média e P10–P90 por motor",
               xlabel="unit_id (identificador, não atributo)", ylabel="Valor original")
    fig.suptitle("Diferenças entre motores — mistura de nível, evolução e duração")
    save(fig, "between_engines.png")
    return filenames
