"""Turn deserialized ROS 2 messages into flat, numeric feature dictionaries.

Only a few message types are decoded in detail. Every other type falls back to
an empty feature dict, so any bag can be ingested and its timing still analysed.
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np


def _header_ns(msg: Any) -> int | None:
    header = getattr(msg, "header", None)
    if header is None:
        return None
    return int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)


def _yaw(q: Any) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _odometry(msg: Any) -> dict[str, float]:
    p = msg.pose.pose
    t = msg.twist.twist
    return {
        "x": float(p.position.x), "y": float(p.position.y), "yaw": _yaw(p.orientation),
        "v": float(t.linear.x), "w": float(t.angular.z),
    }


def _laser_scan(msg: Any) -> dict[str, float]:
    ranges = np.asarray(msg.ranges, dtype=float)
    finite = np.isfinite(ranges) & (ranges >= msg.range_min) & (ranges <= msg.range_max)
    valid = ranges[finite]
    return {
        "n_ranges": float(ranges.size),
        "valid_fraction": float(finite.mean()) if ranges.size else 0.0,
        "min_range": float(valid.min()) if valid.size else float("nan"),
        "mean_range": float(valid.mean()) if valid.size else float("nan"),
    }


def _imu(msg: Any) -> dict[str, float]:
    a, g = msg.linear_acceleration, msg.angular_velocity
    return {"ax": float(a.x), "ay": float(a.y), "az": float(a.z),
            "gx": float(g.x), "gy": float(g.y), "gz": float(g.z)}


def _twist(msg: Any) -> dict[str, float]:
    return {"lin_x": float(msg.linear.x), "ang_z": float(msg.angular.z)}


EXTRACTORS: dict[str, Callable[[Any], dict[str, float]]] = {
    "nav_msgs/msg/Odometry": _odometry,
    "sensor_msgs/msg/LaserScan": _laser_scan,
    "sensor_msgs/msg/Imu": _imu,
    "geometry_msgs/msg/Twist": _twist,
}

# Features that must be finite for the message to count as valid.
# LaserScan min/mean are legitimately NaN when nothing is in range, so they are excluded.
REQUIRED_FINITE: dict[str, tuple[str, ...]] = {
    "nav_msgs/msg/Odometry": ("x", "y", "yaw", "v", "w"),
    "sensor_msgs/msg/Imu": ("ax", "ay", "az", "gx", "gy", "gz"),
    "geometry_msgs/msg/Twist": ("lin_x", "ang_z"),
}


def extract(msgtype: str, msg: Any) -> dict[str, float | None]:
    """Return features for a message. NaN/inf are stored as None so JSON stays valid."""
    func = EXTRACTORS.get(msgtype)
    values: dict[str, float | None] = {}
    if func is not None:
        for key, val in func(msg).items():
            values[key] = val if math.isfinite(val) else None
    header = _header_ns(msg)
    if header is not None:
        values["header_ns"] = header  # type: ignore[assignment]
    return values


def is_valid(msgtype: str, values: dict[str, float | None]) -> bool:
    """True if every required feature for this message type is finite."""
    return all(values.get(key) is not None for key in REQUIRED_FINITE.get(msgtype, ()))
