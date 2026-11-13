"""沿线路里程的一维DBSCAN缺陷密度聚类，保留噪声点。"""
import numpy as np
from sklearn.cluster import DBSCAN


def metadata():
    return {
        "name": "轨检缺陷密度追踪", "short": "rail-density",
        "tagline": "沿实际里程识别密集缺陷带，把孤立点与成片问题分开复核。",
        "client": "临江工务段 · 8名线路分析员 · 南环上行120公里巡检区段",
        "workflow": "分析员在里程表上按整公里汇总缺陷，人工拼接跨公里的密集异常。",
        "pains": ["整公里边界切断真实缺陷带", "单个高等级缺陷与密集低等级缺陷混在一起", "密度参数变化没有可重复的结果记录"],
        "upstream": "轨检车轨距与表面缺陷复核记录 south_loop_defects.csv",
        "downstream": "工务复核会确定人工加密检查区段，保留孤立严重缺陷单独复核",
        "entities": ["线路缺陷点", "密度追踪试验", "区段复核简报"],
        "dataset_name": "南环上行线路185个缺陷点",
        "columns": [{"key": "defect_id", "label": "缺陷编号", "type": "string"}, {"key": "mileage_km", "label": "线路里程(km)", "type": "number"}, {"key": "lateral_mm", "label": "横向偏差(mm)", "type": "number"}, {"key": "severity", "label": "复核等级(1~5)", "type": "number"}],
        "parameters": [{"key": "eps_m", "label": "邻域沿线半径(m)", "type": "number", "default": 100, "min": 20, "max": 400}, {"key": "min_points", "label": "核心点最少邻居(含自身)", "type": "number", "default": 5, "min": 3, "max": 12}],
        "workbench_title": "沿线缺陷密度追踪", "action_label": "识别密集缺陷带", "unit": "个缺陷点",
        "accent": "oklch(62% 0.14 65)", "style": "survey-archive",
        "seed_story": ["06:50 线路分析员导入 south_loop_defects.csv 的185个缺陷点", "07:00 确认所有里程均为南环上行同一方向", "07:10 创建半径100米、最少5点的密度试验", "07:11 后端将公里转成米计算一维DBSCAN", "07:20 查看缺陷带起止里程、跨度及最高等级", "07:30 将半径收紧到30米观察缺陷带分裂与噪声变化", "07:40 下载复核区段表，并单独核查孤立高等级点", "08:00 组长设置每日08:15内部线路简报"],
        "method": "仅按同一线路方向的沿线里程距离做一维DBSCAN；eps单位为米，min_samples包含自身；无密度支撑的点标为噪声，横向偏差和等级仅用于结果解释。",
        "limitations": ["必须上传同一线路同一方向的数据", "密度带不等同于安全风险等级", "密度可达链可能使整带跨度大于eps，需结合原始点核查"],
    }


def seed_records():
    rng = np.random.default_rng(1011)
    rows = []
    for center, spread in [(12.4, 0.14), (48.2, 0.20), (93.7, 0.10)]:
        for _ in range(55):
            rows.append({"defect_id": f"NJ-{len(rows)+1:04}", "mileage_km": round(float(rng.normal(center, spread)), 4), "lateral_mm": round(float(rng.normal(2.4, 1.1)), 2), "severity": int(rng.integers(1, 5))})
    for _ in range(20):
        rows.append({"defect_id": f"NJ-{len(rows)+1:04}", "mileage_km": round(float(rng.uniform(1, 119)), 4), "lateral_mm": round(float(rng.normal(2, 1)), 2), "severity": int(rng.integers(1, 6))})
    return sorted(rows, key=lambda row: row["mileage_km"])


def analyze(records, params):
    try:
        eps = float(params.get("eps_m", 100))
        raw_min = float(params.get("min_points", 5))
        minimum = int(raw_min)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("邻域半径与最少点数必须是有效数值。") from exc
    if not 20 <= eps <= 400 or minimum != raw_min or not 3 <= minimum <= 12:
        raise ValueError("半径须20~400米，最少点数须3~12的整数。")
    if len(records) < max(10, minimum):
        raise ValueError("至少需要10个缺陷点，且不少于最少邻居点数。")
    try:
        mileage = np.asarray([float(row["mileage_km"]) for row in records])
        lateral = np.asarray([float(row["lateral_mm"]) for row in records])
        severity = np.asarray([float(row["severity"]) for row in records])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("里程、横向偏差与复核等级必须完整且为数值。") from exc
    if not np.isfinite(np.column_stack([mileage, lateral, severity])).all() or (mileage < 0).any() or not np.isin(severity, [1, 2, 3, 4, 5]).all():
        raise ValueError("里程须非负有限，横向偏差须有限，复核等级须为1~5整数。")
    labels = DBSCAN(eps=eps, min_samples=minimum).fit_predict((mileage * 1000).reshape(-1, 1))
    clusters = sorted([int(v) for v in np.unique(labels) if v >= 0], key=lambda v: float(np.min(mileage[labels == v])))
    rows = []
    for display, cluster in enumerate(clusters, 1):
        mask = labels == cluster
        start, end = float(mileage[mask].min()), float(mileage[mask].max())
        rows.append({"band": f"缺陷带{display}", "count": int(mask.sum()), "from_km": round(start, 4), "to_km": round(end, 4), "span_m": round((end - start) * 1000, 1), "max_severity": int(severity[mask].max()), "mean_lateral": round(float(lateral[mask].mean()), 2), "review": "人工加密检查"})
    noise = labels == -1
    noise_count = int(noise.sum())
    high_noise = int(np.sum(noise & (severity >= 4)))
    if noise_count:
        rows.append({"band": "孤立/稀疏点", "count": noise_count, "from_km": round(float(mileage[noise].min()), 4), "to_km": round(float(mileage[noise].max()), 4), "span_m": "—", "max_severity": int(severity[noise].max()), "mean_lateral": round(float(lateral[noise].mean()), 2), "review": "逐点复核，不连成区段"})
    return {
        "summary": f"在{len(records)}个缺陷点中识别{len(clusters)}条密集带，保留{noise_count}个孤立/稀疏点；邻域半径{eps:g}米。",
        "metrics": [{"label": "密集缺陷带", "value": len(clusters), "unit": "条"}, {"label": "密集带内点数", "value": int((labels >= 0).sum())}, {"label": "噪声占比", "value": round(noise_count / len(records) * 100, 2), "unit": "%"}, {"label": "孤立高等级点", "value": high_noise}],
        "table": {"columns": [{"key": "band", "label": "密度分组"}, {"key": "count", "label": "缺陷点数"}, {"key": "from_km", "label": "起点km"}, {"key": "to_km", "label": "终点km"}, {"key": "span_m", "label": "跨度m"}, {"key": "max_severity", "label": "最高等级"}, {"key": "mean_lateral", "label": "平均横偏mm"}, {"key": "review", "label": "复核动作"}], "rows": rows},
        "chart": {"type": "bar", "labels": [row["band"] for row in rows], "series": [{"name": "缺陷点数", "values": [row["count"] for row in rows]}]},
        "findings": [f"孤立点中有{high_noise}个等级≥4的缺陷，不能因为被标为噪声而忽略。", "收紧邻域半径会使密度带分裂或增加噪声；扩大半径可能把相邻问题连接。", "缺陷带按起始里程排序，标签仅用于定位，不表示处理优先级。"],
        "method": metadata()["method"], "warnings": ["噪声仅指不满足当前密度条件，不代表无效数据或低风险。"] + (["当前参数未识别出密集带，可核查数据范围或适度增大半径。"] if not clusters else []),
    }
