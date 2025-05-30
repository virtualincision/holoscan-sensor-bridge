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

cmake_minimum_required(VERSION 3.20)

# Options
option(HOLOLINK_BUILD_PYTHON "Build Hololink Python Bindings" ON)

project(hololink)

include(CTest)

# Find Holoscan
find_package(holoscan 0.6 REQUIRED CONFIG PATHS "/opt/nvidia/holoscan")

# Find pybind11
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

set(HOLOSCAN_SDK_VERSION "$ENV{HOLOSCAN_SDK_VERSION}")
set(HOLOSCAN_SDK_VERSION_EXPECTED "2.7.0")

if(NOT HOLOSCAN_SDK_VERSION VERSION_EQUAL HOLOSCAN_SDK_VERSION_EXPECTED)
  message(FATAL_ERROR "Expected Holoscan version ${HOLOSCAN_SDK_VERSION_EXPECTED} but found ${HOLOSCAN_SDK_VERSION}, please check pybind11 version of the Holoscan SDK and update here if needed")
endif()

# We fetch pybind11 since we need the same version as the Holoscan SDK
# and it's not necessarily available on all the platforms
include(FetchContent)
FetchContent_Declare(pybind11
  GIT_REPOSITORY https://github.com/pybind/pybind11
  GIT_TAG v2.11.1
  GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(pybind11)

# add CMAKE_MODULE_PATH for pybind11_add_hololink_module
list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/cmake)

# enabled trace and debug log messages in debug buld only
if(CMAKE_BUILD_TYPE STREQUAL "Release")
  add_compile_definitions(HOLOSCAN_LOG_ACTIVE_LEVEL=2)
else()
  add_compile_definitions(HOLOSCAN_LOG_ACTIVE_LEVEL=0)
endif()

if(NOT CMAKE_INSTALL_LIBDIR)
  set(CMAKE_INSTALL_LIBDIR lib)
endif()

add_subdirectory(src)

if(HOLOLINK_BUILD_PYTHON)
  add_subdirectory(python)
endif()

add_subdirectory(examples)
