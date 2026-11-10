"""
File    : test_cam_multi.py
Author  : Tomoki Noguchi
Adress  : Tomoki.Noguchi@yaskawa.co.jp
Date    : 2025-10-07
Version : 1.0.0

Description:
    このスクリプトは、YAMLファイルで定義されたカメラ設定を読み込み、
    複数のカメラ(RealSense, Basler, Triton+Helios など)を
    統一的に管理・制御するためのメインアプリケーションです。

Design Goals:
    1.CameraManager / CameraFactory によるカメラ生成・登録
    2.priority順での複数カメラ接続
    3.取得モード(ソフトウェアトリガ / ハードウェアトリガ / 共有メモリ)別の制御
    4.スレッドによるリアルタイムキャプチャ
    5.動的パラメータ変更(露光時間・ゲイン・FPSなど)
    6.画像保存・動画保存・点群生成(RealSense)

Flow:
    config.yaml
          ↓
    main_app.py
          ↓
    CameraManager.add_camera() ──> CameraFactory.create_camera() ──> Cameraクラス生成
          ↓
    CameraManager.connect_all() → priority順に全カメラ connect
          ↓
    get_frame() / update_settings() で統一管理
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Any, cast

import cv2
import numpy as np
import open3d
import yaml

try:
    from camlib import CameraManager, CameraRealsenseOpencv, FrameMode
except ImportError as error:
    print(f"ImportError message: {error}")
    print(f"ImportError name: {error.name}")
    print(f"ImportError path: {error.path}")
    traceback.print_exc()
    import sys
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from standard_arch.hardware.camera_v2 import (
        CameraManager,
        CameraRealsenseOpencv,
        FrameMode,
    )

logger = logging.getLogger(__name__)

try:
    import halcon as ha
except ImportError:

    class DummyHalcon:
        """HALCONが未インポート時に使用するダミークラス。"""

    ha = DummyHalcon()


def show_pointcloud(
    camera_manager: CameraManager,
    camera_name: str,
    *,
    colored: bool = True,
) -> None:
    """指定カメラの点群をOpen3Dで描画する。

    Args:
        camera_manager (CameraManager): カメラ管理インスタンス。
        camera_name (str): カメラの登録名。
        colored (bool): Trueなら色付き点群、FalseならXYZ点群を描画する。

    Raises:
        RuntimeError: 点群の取得に失敗した場合。
    """
    if colored:
        # 色付き点群はOpen3D形式、XYZ座標の単位はm
        pcd = camera_manager.get_colored_pointcloud(camera_name)
    else:
        # XYZ点群はNumPy形式、XYZ座標の単位はmm
        points_mm = camera_manager.get_pointcloud(camera_name)

        # Open3Dの表示用にmへ変換
        points_m = points_mm.astype(np.float64) / 1000.0
        pcd = open3d.geometry.PointCloud()
        pcd.points = open3d.utility.Vector3dVector(points_m)

    if not pcd.has_points():
        logger.warning("[%s] 点群データが空です。", camera_name)
        return

    logger.info(
        "[%s] 点群取得成功: %d points, colored=%s",
        camera_name,
        len(pcd.points),
        colored,
    )

    # Open3Dで点群を表示
    open3d.visualization.draw_geometries(
        [pcd],
        window_name=f"{camera_name} - {'Colored' if colored else 'XYZ'}",
        width=960,
        height=720,
    )


def main() -> None:
    """カメラのテストコード"""
    #################### 前準備 ####################
    # 1.クラス初期化
    camera_manager = CameraManager(
        r".\src\config\hardware_realsense\camera_param.yaml",
        r".\src\config\hardware_realsense\camera_id.yaml",
    )

    # 2.priority順で全カメラ起動
    camera_manager.connect_all_parallel()

    # 3.状態確認(しなくてもよい)
    print(camera_manager.get_all_status_df())

    #################### フレーム取得 ####################

    # フレーム取得例:特定のカメラ
    im, _ = camera_manager.get_frame("mech_eye_1", "color")
    if im is not None:
        cv2.imshow("test_cam", im)

    # HW,se,shmのカメラを抽出(こういう書き方もありますとだけ)
    sw_cameras = []
    hw_cameras = []
    shm_cameras = []
    for name, cam in camera_manager.cameras.items():
        if cam.mode == FrameMode.SOFTWARE_TRIGGER:
            sw_cameras.append(name)
        elif cam.mode == FrameMode.SHARED_MEMORY:
            shm_cameras.append(name)
        elif cam.mode == FrameMode.HARDWARE_TRIGGER:
            hw_cameras.append(name)

    # ループ処理(デバッグ用)
    while True:
        for name in shm_cameras:
            if camera_manager.cameras.get(name) is None:
                continue

            for buf_name in ["color", "depth", "xyz"]:
                try:
                    im, _ = camera_manager.get_frame(name, buf_name)
                    if im is None:
                        continue

                    if not isinstance(im, np.ndarray):
                        np_image = ha.himage_as_numpy_array(im)
                        img_show = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)

                    elif buf_name in ("depth", "xyz"):
                        # XYZの場合はZ成分をDepth画像として使用
                        depth = im[:, :, 2] if buf_name == "xyz" else im

                        # 無効なDepth値を除外
                        valid = np.isfinite(depth) & (depth > 0)

                        # Depth画像を表示用uint8へ変換
                        depth_vis = np.zeros(depth.shape, dtype=np.uint8)

                        if np.any(valid):
                            min_depth = float(np.min(depth[valid]))
                            max_depth = float(np.max(depth[valid]))

                            if max_depth > min_depth:
                                normalized = (depth[valid] - min_depth) / (max_depth - min_depth)
                                depth_vis[valid] = (normalized * 255).astype(np.uint8)

                        # Depthにカラーマップを適用
                        img_show = cv2.applyColorMap(
                            depth_vis,
                            cv2.COLORMAP_JET,
                        )

                        # 無効画素は黒で表示
                        img_show[~valid] = (0, 0, 0)

                    else:
                        # RGB画像
                        img_show = im.copy()

                    # 表示サイズを縮小
                    img_show = cv2.resize(
                        img_show,
                        None,
                        fx=0.3,
                        fy=0.3,
                        interpolation=cv2.INTER_AREA,
                    )

                    cv2.imshow(
                        f"{name}_{buf_name}_shm",
                        img_show,
                    )

                except (RuntimeError, ValueError, TypeError, cv2.error):
                    logger.exception("get frame error: %s", buf_name)

        key = cv2.waitKey(1)
        if key == ord("w"):
            camera_manager.pause_thread(name)
        elif key == ord("0"):
            camera_manager.resume_thread(name)
        elif key == ord("e"):
            camera_manager.stop_thread(name)
        elif key == ord("a"):
            camera_manager.start_thread(name)
        elif key == ord("b"):
            camera_manager.log_image(name, "aaa.tif")
        elif key == ord("k"):
            camera_manager.log_movie_start(name, "aaa.avi")
        elif key == ord("l"):
            camera_manager.log_movie_stop(name)
        elif key == ord("i"):
            print(camera_manager.get_status(name))
        elif key == ord("p"):
            # XYZ点群を描画
            try:
                show_pointcloud(camera_manager, name, colored=False)
            except (RuntimeError, ValueError, NotImplementedError):
                logger.exception("[%s] XYZ点群描画に失敗しました。", name)

        elif key == ord("o"):
            # 色付き点群を描画
            try:
                show_pointcloud(camera_manager, name, colored=True)
            except (RuntimeError, ValueError, NotImplementedError):
                logger.exception("[%s] 色付き点群描画に失敗しました。", name)
        elif key == ord("c"):
            for name in camera_manager.cameras:
                camera_manager.update_settings(name, exposure=10000)
            # 単体で書く場合
            # camera_manager.update_settings("triton_and_helios_1", exposure=10000)
        elif key == ord("t"):
            camera_manager.clear_buffer("hand_inspect_cam")
        elif key == ord("y"):
            # カメラオブジェクトから画像と深度を取得
            color, _ = camera_manager.get_frame("fixed_realsense", "color")
            depth, _ = camera_manager.get_frame("fixed_realsense", "depth")

            # --- 専用API利用 ---
            rs_cam = camera_manager.get_camera("fixed_realsense")
            if rs_cam is not None:
                print(rs_cam.allowed_settings)
            else:
                raise RuntimeError("Camera not initialized")

            # 点群作成 ruff準拠
            rs_cls = cast("CameraRealsenseOpencv", rs_cam)

            pcd, X_img, Y_img, Z_img = rs_cls.create_ply(color, depth)

            # 点群作成 ruff準拠じゃないけど使える
            # pcd = rs_cam.create_ply(color, depth)

            # 表示
            open3d.visualization.draw_geometries([pcd])

        elif key == ord("s"):
            for name in sw_cameras:
                if camera_manager.cameras.get(name) is None:
                    continue

                for buf_name in ["color"]:
                    try:
                        im, _ = camera_manager.get_frame(name, buf_name)
                        if im is None:
                            continue

                        if not isinstance(im, np.ndarray):
                            np_image = ha.himage_as_numpy_array(im)
                            np_image = cv2.resize(np_image, None, fx=0.3, fy=0.3)
                            img_show = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
                        else:
                            img_show = im.copy()

                        cv2.imshow(f"{name}_{buf_name}_sw", img_show)
                    except Exception:
                        logger.exception("get frame error")

        elif key == ord("h"):
            for name in hw_cameras:
                if camera_manager.cameras.get(name) is None:
                    continue

                for buf_name in ["color"]:
                    try:
                        im, _ = camera_manager.get_frame(name, buf_name)
                        if im is None:
                            continue

                        if not isinstance(im, np.ndarray):
                            np_image = ha.himage_as_numpy_array(im)
                            np_image = cv2.resize(np_image, None, fx=0.3, fy=0.3)
                            img_show = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
                        else:
                            img_show = im.copy()

                        cv2.imshow(f"{name}_{buf_name}_hw", img_show)
                    except Exception:
                        logger.exception("get frame error")
        elif key == ord("q"):
            break

        time.sleep(0.012)

    #################### 専用API利用 ####################

    # 動的設定変更 エラー例です。(スペルミス)
    # camera_manager.update_settings("realsense_1", exprosure=5000)

    # 動的設定変更 正しいほうです。
    # camera_manager.update_settings("fixed_realsense", exposure=5000)

    # カメラのインスタンスget
    # rs_cam = camera_manager.get_camera("fixed_realsense")

    # カメラのインスタンスから変数にアクセスするのは極力控えてください。
    # publicの関数ならば問題ありません。
    # 必要があれば変数を返す関数を作成しますので、ご連絡ください。

    # 動的設定変更ができるパラメータです。
    # if rs_cam is not None:
    #     print(rs_cam.allowed_settings)
    # else:
    #     raise RuntimeError("Camera not initialized")

    # # 内部パラメータです。 ruff準拠
    # rs_cls = cast("CameraRealsenseOpencv", rs_cam)
    # print(rs_cls.color_intr)

    # 内部パラメータです。 ruff準拠じゃないけど使える
    # print(rs_cam.color_intr)

    #################### 終了処理 #######################

    camera_manager.disconnect_all()


if __name__ == "__main__":
    main()
