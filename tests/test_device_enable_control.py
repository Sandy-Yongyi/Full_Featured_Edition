import unittest
import queue
from types import SimpleNamespace


class DeviceEnableTests(unittest.TestCase):
    def test_new_operate_and_control_fields_serialize_independently(self):
        import struct
        from model.MovingFrameData import SendMovingFrameData
        frame = SendMovingFrameData(Operate=127, Control=2, HeartBeat=123)
        raw = frame.to_bytes()
        self.assertEqual(127, struct.unpack_from('>i', raw, 0)[0])
        self.assertEqual(2, struct.unpack_from('>h', raw, 12)[0])
        restored, _ = SendMovingFrameData.from_bytes(raw)
        self.assertEqual((127, 2, 123), (restored.Operate, restored.Control, restored.HeartBeat))
        self.assertFalse(hasattr(frame, 'Enable'))

    def test_worker_interlock_and_command_frame(self):
        from control.PlcCommunicationProcess import PlcCommunicationProcess
        from model.motionplan.motionutil.DeviceEnableHelper import requested_operate
        p = PlcCommunicationProcess.__new__(PlcCommunicationProcess)
        p.device_enable_mask = 0
        p.plc_data = SimpleNamespace(Operate=0, Status=3)
        p._all_devices_at_safe = lambda: True
        p.control_queue = queue.Queue()
        p.control_queue.put({'device_enable_mask': 126})
        p._update_enable_value()
        self.assertEqual(0, p.device_enable_mask)
        p.control_queue.put({'device_enable_mask': 127})
        p._update_enable_value()
        self.assertEqual(127, p.device_enable_mask)
        self.assertEqual(127, requested_operate(p))
        p.control_queue.put({'device_enable_mask': 0})
        p._update_enable_value()
        self.assertEqual(127, requested_operate(p))
        p.control_queue.put({'device_enable_mask': 1})
        p._update_enable_value()
        p.control_queue.put({'device_enable_mask': 0})
        p._update_enable_value()
        self.assertEqual(0, requested_operate(p))

    def test_controller_rejects_offline_commands(self):
        from control.ControlCenter import ControlCenter
        from model.telemetry.UiState import DeviceState
        sent = []
        center = ControlCenter(SimpleNamespace(control_type=2), 'complete_workpiece', send_control=sent.append)
        with self.assertRaises(RuntimeError):
            center.set_device_enable_mask(127)
        center._state = center._replace_state(running=True, pc_auto_mode=True, all_devices_safe=True, devices=(DeviceState('PLC', True),))
        center.set_device_enable_mask(126)
        self.assertEqual([{'device_enable_mask': 0}], sent)
        center.set_device_enable_mask(3)
        self.assertEqual({'device_enable_mask': 3}, sent[-1])

    def test_speed_uses_live_chain_feedback_and_page_interlock(self):
        from PyQt6.QtWidgets import QApplication
        from model.telemetry.UiState import UiState, DeviceState
        from view.qt.pages import RealtimeControlPage, DeviceControlPage
        qt_app = QApplication.instance() or QApplication([])
        self.addCleanup(lambda: qt_app.processEvents())
        sent = []
        controller = SimpleNamespace(set_device_enable_mask=sent.append)
        realtime = RealtimeControlPage(controller)
        realtime.apply_state(UiState(strategy_name='complete_workpiece', chain_speed_mm_s=25))
        self.assertIn('1.50 m/min', realtime.scan_speed.text())
        page = DeviceControlPage(controller)
        state = UiState(strategy_name='complete_workpiece', running=True, pc_auto_mode=True, all_devices_safe=True, devices=(DeviceState('PLC', True),))
        page.apply_state(state)
        self.assertTrue(all(not b.isEnabled() for b in page.device_buttons))
        for index, button in enumerate(page.device_buttons):
            self.assertIs(page.device_grid.itemAtPosition(index % 3 + 2, index // 3).widget(), button)
            button.click()
        self.assertEqual([], sent)
        page.enable_button.click()
        self.assertEqual(1, sent[-1])
        page.device_buttons[0].click()
        self.assertEqual(3, sent[-1])
        self.assertIn("#12613f", page.device_buttons[0].styleSheet())
        self.assertFalse(page.enable_button.isEnabled())
        page.enable_button.click()
        self.assertEqual(3, sent[-1])
        page.device_buttons[0].click()
        self.assertEqual(1, sent[-1])
        page.enable_button.click()
        self.assertEqual(0, sent[-1])
        self.assertTrue(all(not b.isChecked() and not b.isEnabled() for b in page.device_buttons))
        self.assertNotIn("#12613f", page.device_buttons[0].styleSheet())
        for button in page.device_buttons:
            button.click()
        self.assertEqual(0, sent[-1])
