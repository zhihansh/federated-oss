# Copyright 2021, The TensorFlow Federated Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Utilities for working with structured data."""

import collections
from typing import Any, OrderedDict

import tree


def flatten_with_name(structure: Any) -> OrderedDict[str, Any]:
  """Creates a flattened representation of the given `structure` with names.

  Args:
    structure: A possibly nested structure.

  Returns:
    A `collections.OrderedDict` representing the flattened version of the given
    `structure`, where the keys are names uniquely identifying the position of
    the values in the structure of the given `structure`.
  """
  flattened = tree.flatten_with_path(structure)

  def name(path):
    return '/'.join(map(str, path))

  named = [(name(path), item) for path, item in flattened]
  return collections.OrderedDict(named)
