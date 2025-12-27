#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
#############################################################
#                                                           #
#      Copyright @ 2025 -  Dashingsoft corp.                #
#      All rights reserved.                                 #
#                                                           #
#      Pyarmor                                              #
#                                                           #
#      Version: 9.2.1 -                                     #
#                                                           #
#############################################################
#
#
#  @File: cli/shell.py
#
#  @Author: Jondy Zhao (pyarmor@163.com)
#
#  @Create Date: Wed Nov  5 20:22:52 CST 2025
#

"""This script could run batch pyarmor commands.

For example:

    python3 -m pyarmor.cli.batch build-script.sh

cd abc
pyarmor

The main purpose is to fix pyarmor CI License send too many request issues.

"""
import shlex
import os

from pyarmor.cli.__main__ import main_entry as pyarmor_run

# Do not run `pyarmor reg pyarmor-ci-xxxx.zip` here, run it before this script

build_commands = """
pyarmor gen main.py
cd ../package1
pyarmor gen -R --enable-bcc src/
cd ../package2
pyarmor gen -R --enable-jit --private src/
"""

for cmd in build_commands.splitlines():
    if cmd.startswith('#'):
        continue

    if cmd.startswith('cd '):
        path = cmd[3:].strip()
        print('Change current path:', path)
        os.chdir(path)

    elif cmd.startswith('pyarmor '):
        print('Execute: ', cmd)
        args = shlex.split(cmd[8:].strip())
        pyarmor_run(args)
