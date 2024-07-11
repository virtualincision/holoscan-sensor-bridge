# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# See README.md for detailed information.

import ctypes
import datetime
import logging
import sys
from unittest import mock

import cupy as cp
import holoscan
import pytest

import hololink as hololink_module
from examples import imx274_player

MS_PER_SEC = 1000.0
US_PER_SEC = 1000.0 * MS_PER_SEC
NS_PER_SEC = 1000.0 * US_PER_SEC
SEC_PER_NS = 1.0 / NS_PER_SEC


class Profiler(holoscan.core.Operator):
    def __init__(
        self,
        *args,
        callback=None,
        metadata_callback=None,
        hololink_channel=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._count = 0
        self._callback = callback
        self._metadata_callback = metadata_callback
        self._timestamps = []
        self._hololink = hololink_channel.hololink()

    def setup(self, spec):
        logging.info("setup")
        spec.input("input")
        spec.output("output")

    def compute(self, op_input, op_output, context):
        self._count += 1
        in_message = op_input.receive("input")
        cp_frame = cp.from_dlpack(in_message.get(""))  # cp_frame.shape is (y,x,4)
        op_output.emit({"": cp_frame}, "output")
        #
        metadata = self.metadata()
        image_timestamp_ns = metadata["timestamp_ns"]
        received_timestamp_ns = metadata["received_ns"]
        pipeline_timestamp_ns = (
            datetime.datetime.now(datetime.timezone.utc).timestamp() * NS_PER_SEC
        )
        self._timestamps.append(
            (image_timestamp_ns, received_timestamp_ns, pipeline_timestamp_ns)
        )
        if self._count < 200:
            return
        self._callback(self._timestamps)

    def metadata(self):
        return self._metadata_callback()


timestamps = None
network_mode = None
roce_network_mode = "ROCE"
linux_network_mode = "Linux"


class PatternTestApplication(holoscan.core.Application):
    def __init__(
        self,
        headless,
        fullscreen,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        ibv_name,
        ibv_port,
        camera,
        camera_mode,
        frame_limit,
    ):
        logging.info("__init__")
        super().__init__()
        self._headless = headless
        self._fullscreen = fullscreen
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel = hololink_channel
        self._ibv_name = ibv_name
        self._ibv_port = ibv_port
        self._camera = camera
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit

    def compose(self):
        logging.info("compose")
        if self._frame_limit:
            self._count = holoscan.conditions.CountCondition(
                self,
                name="count",
                count=self._frame_limit,
            )
            condition = self._count
        else:
            self._ok = holoscan.conditions.BooleanCondition(
                self, name="ok", enable_tick=True
            )
            condition = self._ok
        self._camera.set_mode(self._camera_mode)

        csi_to_bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="pool",
            # storage_type of 1 is device memory
            storage_type=1,
            block_size=self._camera._width
            * ctypes.sizeof(ctypes.c_uint16)
            * self._camera._height,
            num_blocks=2,
        )
        csi_to_bayer_operator = hololink_module.operators.CsiToBayerOp(
            self,
            name="csi_to_bayer",
            allocator=csi_to_bayer_pool,
            cuda_device_ordinal=self._cuda_device_ordinal,
        )
        self._camera.configure_converter(csi_to_bayer_operator)

        frame_size = csi_to_bayer_operator.get_csi_length()
        logging.info(f"{frame_size=}")
        frame_context = self._cuda_context

        global network_mode, roce_network_mode, linux_network_mode
        if network_mode == roce_network_mode:
            receiver_operator = hololink_module.operators.RoceReceiverOp(
                self,
                condition,
                name="receiver",
                frame_size=frame_size,
                frame_context=frame_context,
                ibv_name=self._ibv_name,
                ibv_port=self._ibv_port,
                hololink_channel=self._hololink_channel,
                device=self._camera,
            )
        elif network_mode == linux_network_mode:
            receiver_operator = hololink_module.operators.LinuxReceiverOperator(
                self,
                condition,
                name="receiver",
                frame_size=frame_size,
                frame_context=frame_context,
                hololink_channel=self._hololink_channel,
                device=self._camera,
            )
        else:
            assert False and f"Invalid {network_mode=}"

        rgba_components_per_pixel = 4
        bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="pool",
            # storage_type of 1 is device memory
            storage_type=1,
            block_size=self._camera._width
            * rgba_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16)
            * self._camera._height,
            num_blocks=2,
        )
        bayer_format = self._camera.bayer_format()
        demosaic = holoscan.operators.BayerDemosaicOp(
            self,
            name="demosaic",
            pool=bayer_pool,
            generate_alpha=True,
            alpha_value=65535,
            bayer_grid_pos=bayer_format.value,
            interpolation_mode=0,
        )
        profiler = Profiler(
            self,
            name="profiler",
            hololink_channel=self._hololink_channel,
            callback=lambda timestamps: self._terminate(timestamps),
            metadata_callback=lambda: receiver_operator.metadata(),
        )
        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            fullscreen=self._fullscreen,
            headless=self._headless,
        )
        #
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        self.add_flow(csi_to_bayer_operator, demosaic, {("output", "receiver")})
        self.add_flow(demosaic, profiler, {("transmitter", "input")})
        self.add_flow(profiler, visualizer, {("output", "receivers")})

    def _terminate(self, recorded_timestamps):
        self._ok.disable_tick()
        global timestamps
        timestamps = recorded_timestamps


def to_s(timestamp_ns):
    return float(timestamp_ns) / 1000 / 1000 / 1000


def diff_s(later_timestamp_ns, earlier_timestamp_ns):
    diff_ns = later_timestamp_ns - earlier_timestamp_ns
    return to_s(diff_ns)


@pytest.mark.skip_unless_ptp
@pytest.mark.skip_unless_udp_server
@pytest.mark.accelerated_networking
@pytest.mark.parametrize(
    "camera_mode, roce_mode",  # noqa: E501
    [
        (
            hololink_module.sensors.imx274.imx274_mode.Imx274_Mode.IMX274_MODE_3840X2160_60FPS,
            True,
        ),
        (
            hololink_module.sensors.imx274.imx274_mode.Imx274_Mode.IMX274_MODE_1920X1080_60FPS,
            True,
        ),
        (
            hololink_module.sensors.imx274.imx274_mode.Imx274_Mode.IMX274_MODE_3840X2160_60FPS,
            False,
        ),
        (
            hololink_module.sensors.imx274.imx274_mode.Imx274_Mode.IMX274_MODE_1920X1080_60FPS,
            False,
        ),
    ],
)
def test_imx274_timestamps(
    camera_mode,
    roce_mode,
    headless,
    hololink_address,
    ibv_name,
    ibv_port,
):
    pattern = 10
    arguments = [
        sys.argv[0],
        "--camera-mode",
        str(camera_mode.value),
        "--hololink",
        hololink_address,
        "--ibv-name",
        ibv_name,
        "--ibv-port",
        str(ibv_port),
        f"--pattern={pattern}",
    ]
    if headless:
        arguments.extend(["--headless"])

    global network_mode, roce_network_mode, linux_network_mode
    if roce_mode:
        network_mode = roce_network_mode
    else:
        network_mode = linux_network_mode

    with mock.patch("sys.argv", arguments):
        with mock.patch(
            "examples.imx274_player.HoloscanApplication", PatternTestApplication
        ):
            imx274_player.main()

    # check for errors
    global timestamps
    pipeline_dts, receiver_dts = [], []
    # Allow for startup times to be a bit longer
    settled_timestamps = timestamps[5:-5]
    assert len(settled_timestamps) >= 100
    for (
        image_timestamp_ns,
        received_timestamp_ns,
        pipeline_timestamp_ns,
    ) in settled_timestamps:
        image_timestamp_s = datetime.datetime.fromtimestamp(
            to_s(image_timestamp_ns)
        ).isoformat()  # strftime("%H:%M:%S.%f")
        received_timestamp_s = datetime.datetime.fromtimestamp(
            to_s(received_timestamp_ns)
        ).isoformat()  # strftime("%H:%M:%S.%f")
        pipeline_timestamp_s = datetime.datetime.fromtimestamp(
            to_s(pipeline_timestamp_ns)
        ).isoformat()  # strftime("%H:%M:%S.%f")
        pipeline_dt = diff_s(pipeline_timestamp_ns, image_timestamp_ns)
        logging.debug(
            f"{image_timestamp_s=} {pipeline_timestamp_s=} {pipeline_dt=:0.6f}"
        )
        pipeline_dts.append(round(pipeline_dt, 4))
        receiver_dt = diff_s(received_timestamp_ns, image_timestamp_ns)
        logging.debug(
            f"{image_timestamp_s=} {received_timestamp_s=} {receiver_dt=:0.6f}"
        )
        receiver_dts.append(round(receiver_dt, 4))
    smallest_time_difference = min(pipeline_dts)
    largest_time_difference = max(pipeline_dts)
    logging.info(f"pipeline {smallest_time_difference=} {largest_time_difference=}")
    #
    smallest_time_difference = min(receiver_dts)
    largest_time_difference = max(receiver_dts)
    logging.info(f"receiver {smallest_time_difference=} {largest_time_difference=}")
    # The pipeline processing time should never exceed 50ms.
    assert 0 < smallest_time_difference < largest_time_difference < 0.05
    # The difference between the timestamp on the board and the local host
    # should never be more than 15ms.
    assert 0 < smallest_time_difference < largest_time_difference < 0.015
