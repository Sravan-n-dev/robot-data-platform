"""Generate a synthetic ROS 2 bag (no ROS install needed) with deliberate faults.

Topics: /odom (20 Hz), /scan (10 Hz), /imu (50 Hz).
Injected faults (when --faults is on):
  * /odom   : ~0.3 s of dropped messages around t=10 s        -> message_drop
  * /scan   : sensor stops for 3 s starting t=15 s            -> sensor_dropout
  * /imu    : one header stamp jumps backwards at t=20 s      -> timestamp_regression
  * /odom   : one message with NaN position at t=5 s          -> invalid_values
"""
from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import Writer
from rosbags.typesys import Stores, get_typestore

NS = 1_000_000_000


def generate_bag(path: Path, duration_s: float = 30.0, faults: bool = True) -> Path:
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)
    ts = get_typestore(Stores.ROS2_HUMBLE)
    T = ts.types
    Header, Time = T["std_msgs/msg/Header"], T["builtin_interfaces/msg/Time"]
    Point, Quat, V3 = (T["geometry_msgs/msg/Point"], T["geometry_msgs/msg/Quaternion"],
                       T["geometry_msgs/msg/Vector3"])

    def header(t_ns: int, frame: str):
        return Header(stamp=Time(sec=t_ns // NS, nanosec=t_ns % NS), frame_id=frame)

    def odom_msg(t_ns: int, x: float, y: float, yaw: float):
        return T["nav_msgs/msg/Odometry"](
            header=header(t_ns, "odom"), child_frame_id="base_link",
            pose=T["geometry_msgs/msg/PoseWithCovariance"](
                pose=T["geometry_msgs/msg/Pose"](
                    position=Point(x=x, y=y, z=0.0),
                    orientation=Quat(x=0.0, y=0.0, z=math.sin(yaw / 2), w=math.cos(yaw / 2))),
                covariance=np.zeros(36)),
            twist=T["geometry_msgs/msg/TwistWithCovariance"](
                twist=T["geometry_msgs/msg/Twist"](linear=V3(x=0.2, y=0.0, z=0.0),
                                                   angular=V3(x=0.0, y=0.0, z=0.4)),
                covariance=np.zeros(36)))

    def scan_msg(t_ns: int, rng: np.random.Generator):
        ranges = (2.0 + 0.2 * rng.standard_normal(360)).astype(np.float32)
        return T["sensor_msgs/msg/LaserScan"](
            header=header(t_ns, "laser"), angle_min=-math.pi, angle_max=math.pi,
            angle_increment=2 * math.pi / 360, time_increment=0.0, scan_time=0.1,
            range_min=0.12, range_max=3.5, ranges=ranges, intensities=np.zeros(360, dtype=np.float32))

    def imu_msg(t_ns: int, header_ns: int, rng: np.random.Generator):
        return T["sensor_msgs/msg/Imu"](
            header=header(header_ns, "imu"),
            orientation=Quat(x=0.0, y=0.0, z=0.0, w=1.0), orientation_covariance=np.zeros(9),
            angular_velocity=V3(x=0.0, y=0.0, z=0.4 + 0.01 * rng.standard_normal()),
            angular_velocity_covariance=np.zeros(9),
            linear_acceleration=V3(x=0.0, y=0.0, z=9.81 + 0.05 * rng.standard_normal()),
            linear_acceleration_covariance=np.zeros(9))

    rng = np.random.default_rng(0)
    base = 1_700_000_000 * NS
    with Writer(path, version=9) as w:
        odom_c = w.add_connection("/odom", "nav_msgs/msg/Odometry", typestore=ts)
        scan_c = w.add_connection("/scan", "sensor_msgs/msg/LaserScan", typestore=ts)
        imu_c = w.add_connection("/imu", "sensor_msgs/msg/Imu", typestore=ts)

        for i in range(int(duration_s * 20)):                      # /odom 20 Hz
            t = i / 20.0
            if faults and 10.0 <= t < 10.3:
                continue
            tn = base + int(t * NS)
            x, y = math.cos(0.4 * t), math.sin(0.4 * t)
            if faults and abs(t - 5.0) < 1e-9:
                x = float("nan")
            w.write(odom_c, tn, ts.serialize_cdr(odom_msg(tn, x, y, 0.4 * t), odom_c.msgtype))
        for i in range(int(duration_s * 10)):                      # /scan 10 Hz
            t = i / 10.0
            if faults and 15.0 <= t < 18.0:
                continue
            tn = base + int(t * NS)
            w.write(scan_c, tn, ts.serialize_cdr(scan_msg(tn, rng), scan_c.msgtype))
        for i in range(int(duration_s * 50)):                      # /imu 50 Hz
            t = i / 50.0
            tn = base + int(t * NS)
            hdr = tn - 500_000_000 if faults and abs(t - 20.0) < 1e-9 else tn
            w.write(imu_c, tn, ts.serialize_cdr(imu_msg(tn, hdr, rng), imu_c.msgtype))
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="bags/sample_run")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--no-faults", action="store_true")
    args = ap.parse_args()
    print("wrote", generate_bag(Path(args.out), args.duration, faults=not args.no_faults))
