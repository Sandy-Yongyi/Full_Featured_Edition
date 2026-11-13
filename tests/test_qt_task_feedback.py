import os
import queue
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TaskFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def make_process(self):
        from acquisition_sdk._internal.formats.complete_workpiece.BlockDataFormat import BlockData, DistribeGunData, GunGroupData, SingleMachineData
        block = BlockData(distribe_gun_list=[SingleMachineData(machine_id=1, gun_groups=[
            GunGroupData(group_type="outside", group_id=0, gundata_list=[
                DistribeGunData(gun_id=5, gun_y_enable=1, gun_y_upper=400, gun_y_downer=100, gun_r_angle=0)
            ])])])
        frames = [{"data": block}]
        return SimpleNamespace(
            strategy_name="complete_workpiece", machine_config={"1": {"type": "xn_side", "install_orietation": "left"}},
            frame_queue_manager=SimpleNamespace(queues={"left": {1: frames}}),
            complete_workpiece_planner=SimpleNamespace(xn_side_planner=SimpleNamespace(_work_states={1: {"state": "recip_front_outside", "spray_mode": "cabinet"}})),
        )

    def test_planned_gun_ids_and_stage_come_from_current_workpiece(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        process = self.make_process()
        task = build_task_feedback(process)
        self.assertEqual(5, task.gun_plans[0].gun_id)
        self.assertEqual(1, task.gun_plans[0].machine_id)
        self.assertEqual(400, task.gun_plans[0].y_upper)
        self.assertIn("外侧前喷", task.stage)
        self.assertIsNone(task.progress)
        self.assertEqual(1, len(process.frame_queue_manager.queues["left"][1]))

    def test_plc_status_message_contains_current_workpiece_plan(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        from model.utils.UiTelemetry import UiStatusPublisher
        process = self.make_process()
        output = queue.Queue()
        process.ui_status = UiStatusPublisher(output, "plc")
        process.simulation_mode = False
        process.chain_motion_status = "moving_forward"
        process.plc_data = SimpleNamespace(ChainPulse=18229)
        PlcCommunicationProcess._publish_ui_status(process, connected=True)
        message = output.get_nowait()
        self.assertEqual((), message["task"].gun_plans)
        self.assertIn("外侧前喷", message["task"].stage)

    def test_frame_mode_reports_fifo_timeout_and_cache_slots_without_consuming_frames(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        frames = [object(), object(), object()]
        process = SimpleNamespace(
            strategy_name="frame_by_frame", plc_data=SimpleNamespace(ChainCountCM=228),
            raw_data_timeout_active=True,
            frame_queue_manager=SimpleNamespace(frame_stack={"left": frames}),
        )

        task = build_task_feedback(process)

        self.assertIn("原始数据超时", task.stage)
        details = {row.name: row for row in task.details}
        self.assertEqual("228", details["链条 FIFO"].status)
        self.assertEqual("3 个槽位（含空帧）", details["左侧缓存"].detail)
        self.assertEqual(3, len(frames))
        self.assertIs(frames, process.frame_queue_manager.frame_stack["left"])
        self.assertEqual((), task.gun_plans)
        self.assertIsNone(task.progress)

    def test_frame_mode_missing_feedback_does_not_show_zero_fifo_or_normal_input(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        task = build_task_feedback(SimpleNamespace(strategy_name="frame_by_frame"))
        self.assertTrue(getattr(task, "details", ()))
        details = {row.name: row for row in task.details}
        self.assertEqual("待反馈", details["链条 FIFO"].status)
        self.assertEqual("待反馈", details["原始数据输入"].status)

    def test_frame_mode_does_not_treat_untriggered_timeout_as_confirmed_healthy_input(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        task = build_task_feedback(SimpleNamespace(strategy_name="frame_by_frame", raw_data_timeout_active=False))
        details = {row.name: row for row in task.details}
        self.assertEqual("未触发超时", details["原始数据输入"].status)

    def test_continuous_mode_translates_all_scan_stages_and_keeps_progress_unknown(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        for source, expected in (
            ("startup", "扫描初始化"), ("homing", "扫描轴回零"),
            ("waiting", "等待扫描"), ("scanning", "往复扫描中"),
            ("complete", "本趟扫描完成"), ("retry_wait", "等待重采确认"),
            ("retry_position", "重采定位中"), ("fault", "扫描故障"),
        ):
            with self.subTest(stage=source):
                process = SimpleNamespace(strategy_name="continuous_bidirectional", continuous_scan=SimpleNamespace(stage=source, error=""))
                task = build_task_feedback(process)
                self.assertEqual(expected, task.stage)
                self.assertIsNone(task.progress)
                self.assertEqual((), task.gun_plans)

    def test_continuous_mode_reads_station_phases_without_moving_point_clouds(self):
        import numpy as np
        from model.utils.UiTaskFeedback import build_task_feedback
        cloud = np.ones((4, 3))
        manager = SimpleNamespace(continuous_phases=["release", "transit", "empty"], frame_stack={"left": [cloud, cloud, None], "right": [None, cloud, None]},)
        process = SimpleNamespace(strategy_name="continuous_bidirectional", frame_queue_manager=manager, continuous_scan=SimpleNamespace(stage="fault", error="axes out of sync"),)

        task = build_task_feedback(process)

        self.assertTrue(getattr(task, "details", ()))
        details = {row.name: row for row in task.details}
        self.assertEqual("axes out of sync", details["扫描状态"].detail)
        self.assertEqual("请求放行", details["激光位"].status)
        self.assertEqual("转运中", details["手补位"].status)
        self.assertEqual("空闲", details["自动位"].status)
        self.assertEqual("有点云数据", details["激光位"].detail)
        self.assertEqual("无点云数据", details["自动位"].detail)
        self.assertEqual(["release", "transit", "empty"], manager.continuous_phases)
        self.assertIs(cloud, manager.frame_stack["left"][0])
        self.assertIs(cloud, manager.frame_stack["left"][1])

    def test_continuous_mode_missing_station_feedback_is_unknown_instead_of_empty(self):
        from model.utils.UiTaskFeedback import build_task_feedback
        task = build_task_feedback(SimpleNamespace(strategy_name="continuous_bidirectional"))
        self.assertTrue(getattr(task, "details", ()))
        details = {row.name: row for row in task.details}
        for name in ("激光位", "手补位", "自动位"):
            self.assertEqual("待反馈", details[name].status)
            self.assertEqual("点云占用待反馈", details[name].detail)

    def test_task_details_pass_through_plc_transport_and_expire_with_feedback(self):
        import pickle
        from unittest.mock import patch
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        from control.PipelineRuntime import PipelineRuntime
        from model.utils.UiTelemetry import UiStatusPublisher
        output = queue.Queue()
        process = SimpleNamespace(
            strategy_name="continuous_bidirectional", simulation_mode=False,
            plc_data=SimpleNamespace(ChainPulse=10),
            continuous_scan=SimpleNamespace(stage="retry_position", error="", motion_status="stopped"),
            ui_status=UiStatusPublisher(output, "plc"),
        )
        with patch("model.utils.UiTelemetry.time.monotonic", return_value=100):
            PlcCommunicationProcess._publish_ui_status(process, connected=True)
        # multiprocessing.Queue serializes the new UI-neutral detail rows.
        message = pickle.loads(pickle.dumps(output.get_nowait()))
        runtime = PipelineRuntime()
        runtime.ui_status_queue = queue.Queue()
        runtime.ui_status_queue.put(message)
        runtime.plc_handler = SimpleNamespace(is_alive=lambda: True)
        with patch("control.PipelineRuntime.time.monotonic", return_value=101):
            fresh_task = runtime.poll()["task"]
        self.assertEqual("重采定位中", fresh_task.stage)
        self.assertEqual((), fresh_task.details)
        with patch("control.PipelineRuntime.time.monotonic", return_value=110):
            stale_task = runtime.poll()["task"]
        self.assertEqual((), stale_task.details)
        self.assertEqual((), stale_task.gun_plans)
