"""Stable Python interface to the private acquisition implementation.

The source package is for development. Distribution replaces this package with
the compiled acquisition_sdk extension while keeping the same imports.
"""

from importlib import import_module

__version__ = "0.1.0"
SDK_API_VERSION = 1

_EXPORT_GROUPS = {
    "lidar.LidarAcquisitionProcess": ("LidarAcquisitionProcess",),
    "plc.PlcCommon": ("PlcManager",),
    "plc.PlcFrame": ("PlcFrame", "WireType", "Int16", "UInt16", "Int32", "UInt32", "Float32", "FixedStr", "Repeat"),
    "dataprocess.DataFilter": ("DataFilter",),
    "dataprocess.DataSplitting": ("DataSplitting",),
    "dataprocess.complete_workpiece.DataFindBlocks": ("DataFindBlocks",),
    "dataprocess.frame_by_frame.BuildSideFrame": ("build_side_frame",),
    "dataprocess.frame_by_frame.BeamDetector": ("BeamDetector", "BeamResult"),
    "formats.FrameQueueManager": ("FrameQueueManager",),
    "formats.frame_by_frame.AxisFrameDataFormat": ("AxisFrameData",),
    "formats.complete_workpiece.BlockDataFormat": ("BlockData", "JigData", "OutsideData", "InsideData", "SubInsideData", "DistribeGunData", "GunGroupData", "SingleMachineData"),
    "formats.complete_workpiece.FrameDataFormat": ("PartitionData", "MergePartitionData", "LateralData"),
    "pointcloud.PointCloudFileProcess": ("PointCloudFileProcess", "resolve_txt_files"),
    "pointcloud.PointCloudSaveService": ("PointCloudSaveService", "stop_pipeline"),
    "pointcloud.PointCloudSaveProcess": ("PointCloudSaveProcess",),
    "pointcloud.PointCloudSaveBuffer": ("PointCloudSaveBuffer", "SharedPointCloudPool", "SaveBufferFull", "read_blocks"),
}
_EXPORTS = {name: ("acquisition_sdk._internal." + module, name) for module, names in _EXPORT_GROUPS.items() for name in names}
_EXPORTS["FrameAxisData"] = ("acquisition_sdk._internal.formats.frame_by_frame.AxisFrameDataFormat", "AxisData")
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(module), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
