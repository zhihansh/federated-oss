# Copyright 2019, The TensorFlow Federated Authors.
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
"""Utilities to save and load program state to a file system."""

import os
import os.path
from typing import Any, List, Optional, Union

from absl import logging
import tensorflow as tf

from tensorflow_federated.python.common_libs import py_typecheck
from tensorflow_federated.python.program import program_state_manager


# TODO(b/199737690): Update `FileProgramStateManager` to not require a structure
# to load program state.
class FileProgramStateManagerStructureError(Exception):
  pass


class FileProgramStateManager(program_state_manager.ProgramStateManager):
  """A `ProgramStateManager` backed by a file system.

  The `FileProgramStateManager` is a utility that can be used to save and load
  program state to a file system. This implemenation is compatible with any
  nested structure supported by `tf.convert_to_tensor` and is intended to
  support fault tolerance in programs. In particular, it is intended to only
  restart the same simulation, run with the same version of TensorFlow
  Federated.
  """

  def __init__(self,
               root_dir: Union[str, os.PathLike],
               prefix: str = 'program_state_',
               keep_total: int = 5,
               keep_first: bool = True):
    """Returns an initialized `ProgramStateManager`.

    Args:
      root_dir: A path on the file system to save program state. If this path
        does not exist it will be created.
      prefix: A string to use as the prefix for filenames.
      keep_total: An integer representing the total number of program states to
        keep. If the value is zero or smaller, all program states will be kept.
      keep_first: A boolean indicating if the first program state should be
        kept, irrespective of whether it is the oldest program state or not.
        This is desirable in settings where you would like to ensure full
        reproducibility of the simulation, especially in settings where model
        weights or optimizer states are initialized randomly. By loading from
        the initial program state, one can avoid re-initializing and obtaining
        different results.

    Raises:
      ValueError: If `root_dir` is an empty string.
    """
    py_typecheck.check_type(root_dir, (str, os.PathLike))
    if not root_dir:
      raise ValueError('Expected `root_dir` to not be an empty string.')
    py_typecheck.check_type(prefix, str)
    py_typecheck.check_type(keep_total, int)
    py_typecheck.check_type(keep_first, bool)
    if not tf.io.gfile.exists(root_dir):
      tf.io.gfile.makedirs(root_dir)
    self._root_dir = root_dir
    self._prefix = prefix
    self._keep_total = keep_total
    self._keep_first = keep_first
    self._structure = None

  # TODO(b/199737690): Update `FileProgramStateManager` to not require a
  # structure to load program state.
  def set_structure(self, structure: Any):
    """Configures a structure to use when loading program state.

    The structure must be set before calling `load`.

    Args:
      structure: A nested structure which `tf.convert_to_tensor` supports to use
        as a template when calling `load`.
    """
    self._structure = structure

  def versions(self) -> Optional[List[int]]:
    """Returns a list of saved versions or `None`.

    Returns:
      A list of saved versions or `None` if there is no saved program state.
    """
    if not tf.io.gfile.exists(self._root_dir):
      return None
    versions = []
    # Due to tensorflow/issues/19378, we cannot use `tf.io.gfile.glob` here
    # because it returns directory contents recursively on Windows.
    entries = tf.io.gfile.listdir(self._root_dir)
    for entry in entries:
      if entry.startswith(self._prefix):
        version = self._get_version_for_path(entry)
        if version is not None:
          versions.append(version)
    if not versions:
      return None
    return sorted(versions)

  def _get_version_for_path(self, path: Union[str,
                                              os.PathLike]) -> Optional[int]:
    """Returns the version for the given `path` or `None`.

    This method does not assert that the given `path` or the returned version
    represent saved program state, only that for a given `path` maps to the
    returned version.

    Args:
      path: The path to extract the version from.
    """
    py_typecheck.check_type(path, str, os.PathLike)
    basename = os.path.basename(path)
    if basename.startswith(self._prefix):
      version = basename[len(self._prefix):]
    else:
      version = None
    try:
      return int(version)
    except (TypeError, ValueError):
      return None

  def _get_path_for_version(self, version: int) -> str:
    """Returns the path for the given `version`.

    This method does not assert that the given `version` or the returned path
    represent saved program state, only that for a given `version` maps to the
    returned path.

    Args:
      version: The version to use to construct the path.
    """
    py_typecheck.check_type(version, int)
    basename = f'{self._prefix}{version}'
    return os.path.join(self._root_dir, basename)

  def load(self, version: int) -> Any:
    """Returns the program state for the given `version`.

    Args:
      version: A integer representing the version of a saved program state.

    Raises:
      ProgramStateManagerVersionNotFoundError: If there is no program state for
        the given `version`.
      FileProgramStateManagerStructureError: If `structure` has not been set.
    """
    py_typecheck.check_type(version, int)
    # TODO(b/199737690): Update `FileProgramStateManager` to not require a
    # structure to load program state.
    if self._structure is None:
      raise FileProgramStateManagerStructureError(
          'A structure is required to load program state.')
    path = self._get_path_for_version(version)
    if not tf.io.gfile.exists(path):
      raise program_state_manager.ProgramStateManagerVersionNotFoundError(
          f'No program state found for version: {version}')
    model = tf.saved_model.load(path)
    flat_obj = model.build_obj_fn()
    state = tf.nest.pack_sequence_as(self._structure, flat_obj)
    logging.info('Program state loaded: %s', path)
    return state

  def save(self, program_state: Any, version: int):
    """Saves `program_state` for the given `version`.

    Args:
      program_state: The program state to save.
      version: A strictly increasing integer representing the version of a saved
        `program_state`.
    """
    py_typecheck.check_type(version, int)
    path = self._get_path_for_version(version)
    if tf.io.gfile.exists(path):
      raise program_state_manager.ProgramStateManagerVersionAlreadyExistsError(
          f'Program state already exists for version: {version}')
    flat_obj = tf.nest.flatten(program_state)
    model = tf.Module()
    model.obj = flat_obj
    model.build_obj_fn = tf.function(lambda: model.obj, input_signature=())

    # First write to a temporary directory.
    temp_path = f'{path}_temp'
    try:
      tf.io.gfile.rmtree(temp_path)
    except tf.errors.NotFoundError:
      pass
    tf.io.gfile.makedirs(temp_path)
    tf.saved_model.save(model, temp_path, signatures={})

    # Rename the temp directory to the final location atomically.
    tf.io.gfile.rename(temp_path, path)
    logging.info('Program state saved: %s', path)

    self._remove_old_program_state()

  def _remove(self, version: int):
    """Removed the program state for the given `version`."""
    py_typecheck.check_type(version, int)
    path = self._get_path_for_version(version)
    if tf.io.gfile.exists(path):
      tf.io.gfile.rmtree(path)
      logging.info('Program state removed: %s', path)

  def _remove_old_program_state(self):
    """Removes the old program state."""
    if self._keep_total <= 0:
      return
    versions = self.versions()
    if versions is not None:
      if len(versions) > self._keep_total:
        start = 1 if self._keep_first else 0
        stop = start - self._keep_total
        for version in versions[start:stop]:
          self._remove(version)
