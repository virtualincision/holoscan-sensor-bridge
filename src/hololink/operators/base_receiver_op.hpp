/**
 * SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * See README.md for detailed information.
 */

#ifndef SRC_HOLOLINK_OPERATORS_BASE_RECEIVER_OP
#define SRC_HOLOLINK_OPERATORS_BASE_RECEIVER_OP

#include <functional>
#include <memory>
#include <tuple>

#include <cuda.h>

#include <holoscan/core/operator.hpp>
#include <holoscan/core/parameter.hpp>

#include <hololink/metadata.hpp>
#include <hololink/native/cuda_helper.hpp>
#include <hololink/native/networking.hpp>

namespace hololink {
class DataChannel;
} // namespace hololink

namespace hololink::operators {

class BaseReceiverOp : public holoscan::Operator {
public:
    HOLOSCAN_OPERATOR_FORWARD_ARGS(BaseReceiverOp);

    virtual ~BaseReceiverOp() = default;

    void setup(holoscan::OperatorSpec& spec) override;
    void start() override;
    void stop() override;
    void compute(holoscan::InputContext&, holoscan::OutputContext& op_output,
        holoscan::ExecutionContext&) override;

    std::shared_ptr<Metadata> metadata() const;

protected:
    holoscan::Parameter<DataChannel*> hololink_channel_;
    holoscan::Parameter<std::function<void()>> device_start_;
    holoscan::Parameter<std::function<void()>> device_stop_;
    holoscan::Parameter<CUcontext> frame_context_;
    holoscan::Parameter<size_t> frame_size_;
    holoscan::Parameter<CUdeviceptr> user_frame_memory_;

    native::UniqueFileDescriptor data_socket_;
    CUdeviceptr frame_memory_;

    virtual void start_receiver() = 0;
    virtual void stop_() = 0;
    virtual std::shared_ptr<Metadata> get_next_frame(double timeout_ms) = 0;
    virtual std::tuple<std::string, uint32_t> local_ip_and_port();

private:
    std::shared_ptr<Metadata> metadata_;
    bool ok_ = false;

    native::UniqueCUdeviceptr deviceptr_;
    native::UniqueCUhostptr host_deviceptr_;

    CUdeviceptr allocate(size_t size, uint32_t flags = 0);
};

} // namespace hololink::operators

#endif /* SRC_HOLOLINK_OPERATORS_BASE_RECEIVER_OP */
