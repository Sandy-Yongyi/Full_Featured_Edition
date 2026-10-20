# PyQt6 Industrial Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the wxPython interface with a PyQt6 industrial control center while preserving all existing acquisition, processing, PLC, configuration, and safety behavior.

**Architecture:** Keep `control/` and `model/` framework-agnostic. A new PyQt6 presentation package owns the window, pages, theme and OpenGL widget; `MainFrameController` becomes a controller/service that emits UI-neutral snapshots through a dedicated Qt bridge. The new bridge is the only component permitted to update Qt widgets from queue, subprocess, timer, or shutdown activity.

**Tech Stack:** Python 3.11, PyQt6 6.7.x, PyOpenGL, NumPy, pytest, existing multiprocessing queues and TOML configuration services.

**Spec:** `docs/superpowers/specs/2026-10-20-pyqt6-industrial-ui-design.md`

## Global Constraints

- Preserve `strategy_name`, PLC protocol, multiprocessing topology, queues, TOML format, and existing processing/motion-planning behavior.
- Use PyQt6 for all replacement presentation-layer controls; do not mix wx widgets into the new main window.
- Keep business modules independent of PyQt6 imports.
- Use Qt signals/slots for UI updates; worker threads/process callbacks must never mutate a Qt widget directly.
- Retain password confirmation, bounded safe shutdown, and disabled-control behavior from the existing controller.
- Use the selected dark industrial theme: cyan for online/point-cloud state, orange for active model/path state, red only for alarms or emergency stop.

## Review Focus

- Password cancellation or wrong password must not start/stop a pipeline or open device configuration.
- A stale, empty, or bursty visualization queue must not freeze the UI or overwrite newer point clouds with older frames.
- Point-cloud widgets must release OpenGL VBO resources when the window closes, even after an OpenGL upload failure.
- A process heartbeat, save-service, or PLC failure must surface once, trigger the same bounded stop behavior, and retain a visible error record.
- Strategy-specific configuration pages must omit non-applicable fields and preserve both xn_side cabinet and flat configuration values.

## File Structure

- Create: `view/qt/theme.py` — palette, stylesheet, visual constants.
- Create: `view/qt/widgets.py` — reusable status badge, panel title, primary/action buttons, log view.
- Create: `view/qt/point_cloud_view.py` — `QOpenGLWidget` port exposing the current canvas data API.
- Create: `view/qt/pages.py` — control center pages and their typed view-update methods.
- Create: `view/qt/main_window.py` — navigation shell, stacked workspace, top bar and page composition.
- Create: `view/qt/dialogs.py` — PyQt6 password prompt and page-level error/information helpers.
- Create: `view/qt/__init__.py` — public UI imports only.
- Create: `control/UiState.py` — immutable UI snapshot/value objects independent of Qt.
- Create: `control/QtUiBridge.py` — timer-driven queue polling and Qt signals that translate controller state into `UiState` updates.
- Modify: `control/MainFrameControl.py` — convert wx-specific event/timer/widget calls into controller methods consumed by `QtUiBridge`; retain process lifecycle implementation.
- Modify: `control/MachineConfigFrameControl.py` only if a UI-neutral read/save API is absent.
- Modify: `main.py` — start `QApplication`, create the controller, bridge and `IndustrialMainWindow`.
- Modify: `requirements.txt` — replace wxPython and wxgl runtime requirements with PyQt6 while retaining PyOpenGL.
- Modify: `setup.py` — remove wx-specific UI dependencies from packaging only if present; retain compiled business extensions.
- Create: `tests/test_ui_state.py`, `tests/test_qt_ui_bridge.py`, `tests/test_qt_device_config.py`, `tests/test_qt_point_cloud_view.py`, `tests/test_main_controller_lifecycle.py`.

### Task 1: Establish Qt Dependency and UI-Neutral State Contract

**Files:**
- Create: `control/UiState.py`
- Modify: `requirements.txt`
- Test: `tests/test_ui_state.py`

**Interfaces:**
- Produces: `UiState`, `DeviceState`, `TaskState`, and `LogEvent` frozen dataclasses used by the bridge and pages.
- Produces: `UiState.empty(strategy_name: str) -> UiState` and `UiState.with_log(event: LogEvent, limit: int = 500) -> UiState`.

- [ ] **Step 1: Write the failing state-contract tests**

```python
def test_empty_state_uses_safe_offline_defaults():
    state = UiState.empty("complete_workpiece")
    assert state.running is False
    assert state.strategy_name == "complete_workpiece"
    assert state.devices == ()

def test_log_history_is_bounded_to_latest_events():
    state = UiState.empty("frame_by_frame")
    for index in range(3):
        state = state.with_log(LogEvent("info", str(index)), limit=2)
    assert [event.message for event in state.logs] == ["1", "2"]
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `pytest tests/test_ui_state.py -v`

Expected: FAIL because `control.UiState` does not exist.

- [ ] **Step 3: Implement the immutable snapshot contract in `control/UiState.py`**

Define only dataclasses and pure transformation methods. Include connection state, chain position/speed, running/stopping flags, active strategy, task progress/stage, device records, alarms, logs, and optional NumPy point/box payload references. Do not import PyQt6 or wx.

- [ ] **Step 4: Add `PyQt6~=6.7.0` and remove `wxPython`/`wxgl` from `requirements.txt`**

Leave existing algorithm, OpenGL, NumPy, and packaging dependencies unchanged.

- [ ] **Step 5: Run the focused tests to verify passing behavior**

Run: `pytest tests/test_ui_state.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the state contract**

```bash
git add requirements.txt control/UiState.py tests/test_ui_state.py
git commit -m "feat: add UI-neutral control state"
```

### Task 2: Build the Dark Industrial PyQt6 Shell and Navigation

**Files:**
- Create: `view/qt/theme.py`
- Create: `view/qt/widgets.py`
- Create: `view/qt/pages.py`
- Create: `view/qt/main_window.py`
- Create: `view/qt/__init__.py`
- Test: `tests/test_qt_main_window.py`

**Interfaces:**
- Consumes: `UiState` from Task 1.
- Produces: `IndustrialMainWindow(controller, bridge)`, `RealtimeControlPage.apply_state(state: UiState) -> None`, and page routes `realtime`, `acquisition`, `tasks`, `configuration`, `logs`.

- [ ] **Step 1: Write failing offscreen window tests**

```python
def test_main_window_exposes_all_workspace_routes(qtbot):
    window = IndustrialMainWindow(controller=FakeController(), bridge=FakeBridge())
    qtbot.addWidget(window)
    assert window.route_names() == ("realtime", "acquisition", "tasks", "configuration", "logs")

def test_stop_action_remains_enabled_while_running(qtbot):
    from dataclasses import replace
    page = RealtimeControlPage(FakeController())
    page.apply_state(replace(UiState.empty("complete_workpiece"), running=True))
    assert page.stop_button.isEnabled()
```

- [ ] **Step 2: Run the window tests headlessly to verify failure**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_main_window.py -v`

Expected: FAIL because the PyQt6 window classes do not exist.

- [ ] **Step 3: Implement theme tokens and reusable widgets**

Use a single Qt stylesheet from `build_industrial_stylesheet() -> str`. Implement `StatusBadge`, `PanelHeader`, `ControlButton`, and an append-only bounded `RuntimeLogView`. Use cyan, orange, green, and red roles exactly as defined in the global constraints.

- [ ] **Step 4: Implement the main shell and read-only pages**

Use a left navigation rail and `QStackedWidget`. The center of `RealtimeControlPage` reserves the point-cloud widget; the right column contains chain, device, task, and safety cards. Include disabled placeholders for pages not connected until later tasks.

- [ ] **Step 5: Run the window tests to verify passing behavior**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_main_window.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the shell**

```bash
git add view/qt tests/test_qt_main_window.py
git commit -m "feat: add industrial PyQt6 control shell"
```

### Task 3: Port the Point Cloud Canvas to `QOpenGLWidget`

**Files:**
- Create: `view/qt/point_cloud_view.py`
- Test: `tests/test_qt_point_cloud_view.py`

**Interfaces:**
- Consumes: `numpy.ndarray` point arrays and existing `BlockData`/dictionary box input.
- Produces: `QtPointCloudView.set_points(points: np.ndarray | None) -> None`, `set_boxes(boxes_data: object | None) -> None`, `reset_camera() -> None`, and `clear() -> None`.
- Compatibility: Preserve the coordinate, color, VBO upload, box generation, orbit/pan/zoom, and double-click orbit-center semantics of `model.plot.PointCloudCanvas.PointCloudCanvas`.

- [ ] **Step 1: Write failing data and cleanup tests**

```python
def test_set_points_normalizes_rgb_and_requests_repaint(qtbot):
    view = QtPointCloudView()
    qtbot.addWidget(view)
    view.set_points(np.array([[0, 0, 0, 0, 128, 255]], dtype=np.float32))
    assert np.allclose(view.colors[0], [0.0, 128 / 255, 1.0])

def test_clear_releases_scene_arrays_without_gl_context(qtbot):
    view = QtPointCloudView()
    qtbot.addWidget(view)
    view.set_points(np.array([[1, 2, 3]], dtype=np.float32))
    view.clear()
    assert view.points.shape == (0, 3)
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_point_cloud_view.py -v`

Expected: FAIL because `QtPointCloudView` does not exist.

- [ ] **Step 3: Implement `QtPointCloudView` by porting the existing rendering contract**

Move pure geometry/color helpers from `PointCloudCanvas` without importing wx. Map OpenGL lifecycle to `initializeGL`, `resizeGL`, `paintGL`, and `closeEvent`; replace `wx.Timer` repaint coalescing with a Qt timer capped at 30 FPS. Preserve the current VBO fallback to client arrays and protect VBO deletion when no valid context exists.

- [ ] **Step 4: Add mouse interaction and box compatibility tests**

Test left-drag rotation, right-drag pan, wheel zoom clamping to `[0.1, 10.0]`, and `BlockData` box extraction without requiring an actual GPU render.

- [ ] **Step 5: Run point-cloud tests to verify passing behavior**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_point_cloud_view.py -v`

Expected: PASS; GPU-specific rendering assertions remain manual visual verification.

- [ ] **Step 6: Commit the point-cloud port**

```bash
git add view/qt/point_cloud_view.py tests/test_qt_point_cloud_view.py
git commit -m "feat: port point cloud view to Qt OpenGL"
```

### Task 4: Decouple the Existing Controller from wx and Add the Qt Bridge

**Files:**
- Create: `control/QtUiBridge.py`
- Modify: `control/MainFrameControl.py`
- Test: `tests/test_qt_ui_bridge.py`
- Test: `tests/test_main_controller_lifecycle.py`

**Interfaces:**
- Consumes: existing controller methods `start()`, `stop()`, `save_lidar_scan_speed(speed: int)`, `open_machine_config(sn: int)`, and state from `UiState`.
- Produces: `MainFrameController.build_ui_state() -> UiState`, `QtUiBridge.state_changed: pyqtSignal(UiState)`, `QtUiBridge.error_raised: pyqtSignal(str, str)`, and `QtUiBridge.start(interval_ms: int = 100) -> None`.

- [ ] **Step 1: Write failing bridge and lifecycle tests**

```python
def test_bridge_emits_newest_visualization_frame_only(qtbot):
    old_frame = np.array([[0, 0, 0]], dtype=np.float32)
    new_frame = np.array([[1, 2, 3]], dtype=np.float32)
    controller = FakeController(viz_frames=[old_frame, new_frame])
    bridge = QtUiBridge(controller)
    received = []
    bridge.state_changed.connect(received.append)
    bridge.poll_once()
    assert received[-1].points is new_frame

def test_stop_disables_start_until_workers_finish(controller):
    controller.running = True
    controller.stop()
    assert controller.build_ui_state().stopping is True
```

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_ui_bridge.py tests/test_main_controller_lifecycle.py -v`

Expected: FAIL because controller APIs and bridge do not exist.

- [ ] **Step 3: Extract wx-free controller commands from `MainFrameController`**

Replace inheritance from `view.MainFrame.MainFrame` with composition. Rename event handlers into UI-neutral commands (`start`, `stop`, `save_lidar_scan_speed`, `request_machine_config`); keep compatibility wrappers only during this migration. Replace direct widget mutation, `wx.CallAfter`, wx timers, and wx message boxes with state updates, callbacks, or bridge signals.

- [ ] **Step 4: Implement the bridge’s bounded polling model**

Use one Qt-owned timer. Drain at most the documented current bounds (20 log entries per tick), select only the newest visualization item, emit a snapshot on change, and forward process/save failures exactly once. Keep worker lifecycle and shutdown thread behavior in the controller.

- [ ] **Step 5: Run lifecycle, bridge, and existing saving tests**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_ui_bridge.py tests/test_main_controller_lifecycle.py tests/test_save_lifecycle.py tests/test_lidar_save_integration.py -v`

Expected: PASS.

- [ ] **Step 6: Commit controller/bridge decoupling**

```bash
git add control/MainFrameControl.py control/QtUiBridge.py tests/test_qt_ui_bridge.py tests/test_main_controller_lifecycle.py
git commit -m "refactor: bridge controller state into Qt"
```

### Task 5: Replace Dialog-Based Device Configuration with a Page

**Files:**
- Create: `view/qt/device_config_page.py`
- Modify: `view/qt/pages.py`
- Modify: `control/MachineConfigFrameControl.py` if a UI-neutral adapter is needed
- Test: `tests/test_qt_device_config.py`

**Interfaces:**
- Consumes: `load_machine_config_for_ui(sn, strategy_name)` and `save_machine_config_from_ui(sn, values, control_queue, strategy_name)`.
- Produces: `DeviceConfigPage.load_device(sn: int) -> None`, `DeviceConfigPage.collect_values() -> dict`, and `DeviceConfigPage.save_current() -> bool`.

- [ ] **Step 1: Write failing configuration page tests**

```python
def test_complete_workpiece_xn_side_shows_cabinet_and_flat_tabs(qtbot, config_page):
    config_page.load_device(1)
    assert config_page.tab_names() == ("柜体配置", "平板配置")

def test_invalid_integer_does_not_call_save(config_page):
    config_page.save_callback = lambda *_args: pytest.fail("save must not be called")
    config_page.set_field("x_pos_speed", "fast")
    assert config_page.save_current() is False
```

- [ ] **Step 2: Run the configuration tests to verify failure**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_device_config.py -v`

Expected: FAIL because `DeviceConfigPage` does not exist.

- [ ] **Step 3: Implement strategy-aware configuration forms**

Port `MachineConfigFrame` field-selection constants and labels into a pure form schema. Render controls inside the configuration workspace, preserve continuous-mode English labels, and use a page-local confirmation/error banner instead of a modal save result. Do not alter TOML keys or save service signatures.

- [ ] **Step 4: Connect protected page entry to the controller**

Require the same password policy before allowing configuration edits. On cancellation or a wrong password, keep the current configuration read-only and log a warning event.

- [ ] **Step 5: Run configuration tests and targeted regression tests**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_qt_device_config.py tests/test_save_config_loading.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the configuration page**

```bash
git add view/qt/device_config_page.py view/qt/pages.py control/MachineConfigFrameControl.py tests/test_qt_device_config.py
git commit -m "feat: add in-place Qt device configuration"
```

### Task 6: Switch Application Entry Point and Validate Safety Workflows

**Files:**
- Modify: `main.py`
- Modify: `setup.py`
- Modify: `view/PasswordDialog.py` only to remove obsolete wx usage after the Qt replacement is wired
- Test: `tests/test_main_qt_entry.py`
- Test: `tests/test_qt_safety_workflows.py`

**Interfaces:**
- Consumes: `MainFrameController`, `QtUiBridge`, `IndustrialMainWindow`.
- Produces: `main.build_application(argv: list[str] | None = None) -> tuple[QApplication, IndustrialMainWindow]`.

- [ ] **Step 1: Write failing application wiring and safety tests**

```python
def test_build_application_creates_qt_window(monkeypatch):
    app, window = build_application([])
    assert isinstance(window, IndustrialMainWindow)
    assert app is QApplication.instance()

def test_close_while_running_requests_safe_stop(qtbot, window, controller):
    controller.running = True
    qtbot.addWidget(window)
    window.close()
    assert controller.stop_requested is True
```

- [ ] **Step 2: Run the entry tests to verify failure**

Run: `set QT_QPA_PLATFORM=offscreen && pytest tests/test_main_qt_entry.py tests/test_qt_safety_workflows.py -v`

Expected: FAIL because the Qt application builder does not exist.

- [ ] **Step 3: Replace wx startup and shutdown wiring in `main.py`**

Keep the single-instance mutex and Windows console protection. Create one `QApplication`, apply the theme, instantiate controller/bridge/window, and call `app.exec()`. Map the close event to the controller’s existing password gate and bounded stop path.

- [ ] **Step 4: Update packaging and remove obsolete wx presentation imports**

Do not delete legacy view files until all tests pass and the new entrypoint launches. Ensure `setup.py` continues compiling only business extensions and does not compile/import PyQt6 widgets as Cython extensions.

- [ ] **Step 5: Run the full regression suite and manual smoke test**

Run: `set QT_QPA_PLATFORM=offscreen && pytest -q`

Expected: PASS.

Manual smoke test: start the desktop application with a valid configuration; verify start/stop/password/configuration/page navigation, a point-cloud preview, device/PLC status, and safe close behavior with no hardware command changes.

- [ ] **Step 6: Commit entrypoint migration**

```bash
git add main.py setup.py view control tests requirements.txt
git commit -m "feat: launch industrial PyQt6 control center"
```

## Plan Self-Review

- **Spec coverage:** Tasks 1–2 implement the UI shell and visual language; Task 3 covers point-cloud parity; Task 4 isolates queue, process, log, fault and safety state; Task 5 replaces dialog configuration; Task 6 wires entrypoint and validates the entire application lifecycle.
- **Step scan:** Every task begins with a failing focused test, adds an explicit interface, implements one bounded deliverable, verifies it, and commits it.
- **Type consistency:** `UiState` is the only view update payload; `QtUiBridge` emits it; all pages consume it; controller commands remain business-layer methods.
- **Review-focus coverage:** Task 3 covers VBO lifecycle and bursty frames; Task 4 covers process fault and safe-stop transitions; Task 5 covers configuration visibility and validation; Task 6 covers password-gated close/start safety.
- **Proportion:** The plan gives interfaces and test outcomes without duplicating implementation bodies or the existing PLC/business algorithms.
