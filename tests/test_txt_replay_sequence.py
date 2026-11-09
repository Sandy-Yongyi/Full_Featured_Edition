import queue
import shutil
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch


class TxtReplaySequenceTests(unittest.TestCase):
    def setUp(self):
        from model.utils.TomlLoader import TomlLoader
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.config = self.root / "config"
        self.config.mkdir()
        source = Path(__file__).resolve().parents[1] / "model" / "tomls"
        for name in ("ReadDataConfig.toml", "ProcessConfig.toml", "SystemConfig.toml"):
            shutil.copyfile(source / name, self.config / name)
        TomlLoader.save({"translate_data_origin": 1, "z_threshold": 10}, str(self.config / "ReadDataConfig.toml"))

    def worker(self, data_name=None, strategy="frame_by_frame", same_origin=True):
        from control.DataProcessWorker import DataProcessWorker
        from model.utils.TomlLoader import TomlLoader
        TomlLoader.save({"translate_data_origin": 1 if same_origin else 2}, str(self.config / "ReadDataConfig.toml"))
        return DataProcessWorker(queue.Queue(), queue.Queue(), queue.Queue(), str(self.root), data_name=data_name, strategy_name=strategy, config_dir=str(self.config))

    def write(self, name, x):
        (self.root / name).write_text(f"{x} 100 0\n", encoding="utf-8")

    def test_frame_replay_advances_through_all_datasets_without_resetting_plc_fifo(self):
        self.write("combined_10.txt", 10)
        self.write("combined_2.txt", 2)
        worker = self.worker()
        worker._load_all_frames()
        self.assertEqual(2, worker.all_frames["left"][0][0, 0])
        sent = []
        original = worker._process_current_frame

        def record(real_fifo_key, repeat_count):
            sent.append((real_fifo_key, worker.all_frames["left"][worker.current_frame_index][0, 0]))
            original(real_fifo_key, repeat_count)
        with patch.object(worker, "_process_current_frame", side_effect=record):
            self.assertEqual(2, worker._process_fifo_advance(20, 22))
        self.assertEqual([(21, 2), (22, 10)], sent)
        self.assertEqual([21, 22], [worker.machine_data_queue.get_nowait()["fifo"] for _ in range(2)])

    def test_explicit_name_processes_only_that_dataset(self):
        self.write("combined_2.txt", 2)
        self.write("combined_10.txt", 10)
        worker = self.worker("combined_10.txt")
        self.assertEqual(["10.txt"], [item["name"] for item in worker._discover_point_cloud_datasets()])
        worker._load_all_frames()
        self.assertEqual(10, worker.all_frames["left"][0][0, 0])

    def test_independent_origin_groups_directions_and_replays_groups_in_order(self):
        for suffix, x in (("10", 10), ("2", 2)):
            self.write(f"left_{suffix}.txt", x)
            self.write(f"right_{suffix}.txt", x + 100)
        worker = self.worker(same_origin=False)
        self.assertEqual(["2.txt", "10.txt"], [item["name"] for item in worker._discover_point_cloud_datasets()])
        worker._load_all_frames()
        worker._process_fifo_advance(0, 2)
        self.assertEqual(10, worker.all_frames["left"][0][0, 0])
        self.assertEqual(110, worker.all_frames["right"][0][0, 0])

    def test_same_origin_directory_accepts_plain_txt_without_counting_direction_files_twice(self):
        self.write("2.txt", 2)
        self.write("10.txt", 10)
        self.write("left_2.txt", 200)
        worker = self.worker()
        self.assertEqual(["2.txt", "10.txt"], [item["name"] for item in worker._discover_point_cloud_datasets()])
        named = self.worker("10.txt")
        named._load_all_frames()
        self.assertEqual(10, named.all_frames["left"][0][0, 0])

    def test_complete_workpiece_replay_sends_all_files_in_natural_order(self):
        self.write("combined_10.txt", 10)
        self.write("combined_2.txt", 2)
        worker = self.worker(strategy="complete_workpiece")
        with patch.object(worker, "_heartbeat_sleep"):
            worker._process_complete_workpieces()
        packets = [worker.machine_data_queue.get_nowait() for _ in range(2)]
        self.assertEqual([2, 10], [packet["all_data"][0, 0] for packet in packets])
        self.assertTrue(worker.machine_data_queue.empty())
