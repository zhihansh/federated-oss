/* Copyright 2021, The TensorFlow Federated Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License
==============================================================================*/

// This file contains the pybind11 defintions for exposing the C++ Executor
// interface in Python.
//
// General principles:
//   - Python methods defined here (e.g. `m.def_*()`) should not contain
//     "business logic". That should be implemented on the underlying C++ class.
//     The only logic that may exist here is parameter/result conversions (e.g.
//     `tf.EagerTensor` -> `tf::Tensor`, etc).

#include <Python.h>

#include "absl/status/statusor.h"
#include "include/pybind11/detail/common.h"
#include "include/pybind11/pybind11.h"
#include "include/pybind11/pytypes.h"
#include "pybind11_abseil/status_casters.h"
#include "pybind11_protobuf/wrapped_proto_caster.h"
#include "tensorflow/c/tf_status.h"
#include "tensorflow/c/tf_tensor.h"
#include "tensorflow/core/framework/tensor.h"
#include "tensorflow/core/platform/status.h"
#include "tensorflow/python/lib/core/ndarray_tensor.h"
#include "tensorflow/python/lib/core/safe_ptr.h"
#include "tensorflow_federated/cc/core/impl/executors/status_macros.h"
#include "tensorflow_federated/cc/core/impl/executors/tensor_serialization.h"
#include "tensorflow_federated/proto/v0/executor.pb.h"

namespace tensorflow {
Status TF_TensorToTensor(const TF_Tensor* src, Tensor* dst);
}  // namespace tensorflow

namespace tensorflow_federated {

namespace py = ::pybind11;

namespace {

////////////////////////////////////////////////////////////////////////////////
// The Python module defintion `serialization_bindings`.
//
// This will be used with `import serialization_bindigns` on the Python side.
// This module should _not_ be directly imported into the public pip API. The
// methods here will raise `NotOkStatus` errors from absl, which are not user
// friendly.
////////////////////////////////////////////////////////////////////////////////
PYBIND11_MODULE(serialization_bindings, m) {
  py::google::ImportStatusModule();
  pybind11_protobuf::ImportWrappedProtoCasters();

  m.doc() = "Bindings for the C++ value serialization";

  // v0::Value serialization methods.
  m.def("serialize_tensor_value",
        py::google::WithWrappedProtos(
            [](const tensorflow::Tensor& tensor) -> absl::StatusOr<v0::Value> {
              v0::Value value_pb;
              TFF_TRY(SerializeTensorValue(tensor, &value_pb));
              return value_pb;
            }));
  m.def("deserialize_tensor_value",
        py::google::WithWrappedProtos(&DeserializeTensorValue));
}
}  // namespace
}  // namespace tensorflow_federated

namespace pybind11 {
namespace detail {

template <>
struct type_caster<tensorflow::Tensor> {
 public:
  // Macro to create `value` variable which is used in `load` to store the
  // result of the conversion.
  PYBIND11_TYPE_CASTER(tensorflow::Tensor, _("Tensor"));

  // Pybind11 caster for PyArray (Python) -> tensorflow::Tensor (C++).
  bool load(handle src, bool) {
    tensorflow::Safe_TF_TensorPtr tf_tensor_ptr;
    tensorflow::Status status =
        tensorflow::NdarrayToTensor(/*ctx=*/nullptr, src.ptr(), &tf_tensor_ptr);
    if (!status.ok()) {
      LOG(ERROR) << status;
      return false;
    }
    tensorflow::Tensor tensor;
    status = TF_TensorToTensor(tf_tensor_ptr.get(), &tensor);
    if (!status.ok()) {
      LOG(ERROR) << status;
      return false;
    }
    return !PyErr_Occurred() && value.CopyFrom(tensor, tensor.shape());
  }

  // Convert tensorflow::Tensor (C++) back to a PyArray (Python).
  static handle cast(const tensorflow::Tensor tensor, return_value_policy,
                     handle) {
    PyObject* result = nullptr;
    tensorflow::Status status = tensorflow::TensorToNdarray(tensor, &result);
    if (!status.ok()) {
      PyErr_SetString(PyExc_ValueError, "Failed to create np.ndarray");
      return nullptr;
    }
    return result;
  }
};
}  // namespace detail
}  // namespace pybind11
