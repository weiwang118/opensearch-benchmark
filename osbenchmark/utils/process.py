# SPDX-License-Identifier: Apache-2.0
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import logging
import os
import shlex
import subprocess
import time

import psutil


def run_subprocess(command_line):
    return os.system(command_line)


def run_subprocess_with_output(command_line):
    logger = logging.getLogger(__name__)
    logger.debug("Running subprocess [%s] with output.", command_line)
    command_line_args = shlex.split(command_line)

    with subprocess.Popen(command_line_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL) as command_line_process:
        has_output = True
        lines = []
        while has_output:
            line = command_line_process.stdout.readline()
            if line:
                lines.append(line.decode("UTF-8").strip())
            else:
                has_output = False
    return lines


def run_subprocess_with_out_and_err(command_line):
    logger = logging.getLogger(__name__)
    logger.debug("Running subprocess [%s] with stdout and stderr.", command_line)
    command_line_args = shlex.split(command_line)

    sp = subprocess.Popen(command_line_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    sp.wait()
    out, err = sp.communicate()
    return out.decode('UTF-8'), err.decode('UTF-8'), sp.returncode


def run_subprocess_with_stderr(command_line):
    logger = logging.getLogger(__name__)
    logger.debug("Running subprocess [%s] with stderr but no stdout.", command_line)
    command_line_args = shlex.split(command_line)

    sp = subprocess.Popen(command_line_args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
    sp.wait()
    _, err = sp.communicate()
    return err.decode('UTF-8'), sp.returncode


def exit_status_as_bool(runnable, quiet=False):
    """

    :param runnable: A runnable returning an int as exit status assuming ``0`` is meaning success.
    :param quiet: Suppress any output (default: False).
    :return: True iff the runnable has terminated successfully.
    """
    try:
        return_code = runnable()
        return return_code == 0 or return_code is None
    except OSError:
        if not quiet:
            logging.getLogger(__name__).exception("Could not execute command.")
        return False


def run_subprocess_with_logging(command_line, header=None, level=logging.INFO, stdin=None, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=None, detach=False, capture_output=False):
    """
    Runs the provided command line in a subprocess. All output will be captured by a logger.

    :param command_line: The command line of the subprocess to launch.
    :param header: An optional header line that should be logged (this will be logged on info level, regardless of the defined log level).
    :param level: The log level to use for output (default: logging.INFO).
    :param stdin: The stdout object returned by subprocess.Popen(stdout=PIPE) allowing chaining of shell operations with pipes
      (default: None).
    ;param stdout: The form that the stdout of Popen will take. If this argument is of type PIPE, the output of the command
      will be returned as a stream.
    ;param stderr: The form that the stderr of Popen will take. If this argument is  of type PIPE, the output of the command
      will be returned as a stream.
    :param env: Use specific environment variables (default: None).
    :param detach: Whether to detach this process from its parent process (default: False).
    :return: The process exit code as an int.
    """
    logger = logging.getLogger(__name__)
    logger.debug("Running subprocess [%s] with logging.", command_line)
    command_line_args = shlex.split(command_line)
    pre_exec = os.setpgrp if detach else None
    if header is not None:
        logger.info(header)

    # pylint: disable=subprocess-popen-preexec-fn
    with subprocess.Popen(command_line_args,
                          stdout=stdout,
                          stderr=stderr,
                          universal_newlines=True,
                          env=env,
                          stdin=stdin if stdin else None,
                          preexec_fn=pre_exec) as command_line_process:
        stdout, _ = command_line_process.communicate()
        if stdout:
            logger.log(level=level, msg=stdout)

    logger.debug("Subprocess [%s] finished with return code [%s].", command_line, str(command_line_process.returncode))
    return (stdout, command_line_process.returncode) if capture_output else command_line_process.returncode


def is_benchmark_process(p):
    cmdline = p.cmdline()
    return p.name() == "opensearch-benchmark" or \
        (len(cmdline) > 1 and
         os.path.basename(cmdline[0].lower()).startswith("python") and
         os.path.basename(cmdline[1]) == "opensearch-benchmark")


def find_all_other_benchmark_processes():
    others = []
    for_all_other_processes(is_benchmark_process, others.append)
    return others


def kill_all(predicate):
    def kill(p):
        logging.getLogger(__name__).info("Killing lingering process with PID [%s] and command line [%s].", p.pid, p.cmdline())
        p.kill()
        # wait until process has terminated, at most 3 seconds. Otherwise we might run into race conditions with actor system
        # sockets that are still open.
        for _ in range(3):
            try:
                p.status()
                time.sleep(1)
            except psutil.NoSuchProcess:
                break
    for_all_other_processes(predicate, kill)


def for_all_other_processes(predicate, action):
    # no harakiri please
    my_pid = os.getpid()
    for p in psutil.process_iter():
        try:
            if p.pid != my_pid and predicate(p):
                action(p)
        except (psutil.ZombieProcess, psutil.AccessDenied, psutil.NoSuchProcess):
            pass


def kill_running_benchmark_instances():
    kill_all(is_benchmark_process)
