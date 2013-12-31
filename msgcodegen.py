# Copyright 2013 Basho Technologies, Inc.
#
# This file is provided to you under the Apache License,
# Version 2.0 (the "License"); you may not use this file
# except in compliance with the License.  You may obtain
# a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
distutils commands for generating protocol message-code mappings.
"""

__all__ = ['build_messages', 'clean_messages']

import re
import csv
import os
from os.path import isfile
from distutils import log
from distutils.core import Command
from distutils.file_util import write_file
from datetime import date

LICENSE = """# Copyright {0} Basho Technologies, Inc.
#
# This file is provided to you under the Apache License,
# Version 2.0 (the "License"); you may not use this file
# except in compliance with the License.  You may obtain
# a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
""".format(date.today().year)


class MessageCodeMapping(object):
    def __init__(self, code, message, proto):
        self.code = int(code)
        self.message = message
        self.proto = proto
        self.message_code_name = self._message_code_name()
        self.module_name = "riak_pb.{0}_pb2".format(self.proto)
        self.message_class = self._message_class()

    def __cmp__(self, other):
        return cmp(self.code, other.code)

    def _message_code_name(self):
        strip_rpb = re.sub(r"^Rpb", "", self.message)
        word = re.sub(r"([A-Z]+)([A-Z][a-z])", r'\1_\2', strip_rpb)
        word = re.sub(r"([a-z\d])([A-Z])", r'\1_\2', word)
        word = word.replace("-", "_")
        return "MSG_CODE_" + word.upper()

    def _message_class(self):
        try:
            pbmod = __import__(self.module_name, globals(), locals(),
                               [self.message])
            klass = pbmod.__dict__[self.message]
            return klass
        except KeyError:
            log.debug("Did not find '{0}' message class in module '{1}'",
                      self.message, self.module_name)
        except ImportError:
            log.debug("Could not import module '{0}'", self.module_name)
        return None


class clean_messages(Command):
    """
    Cleans generated message code mappings. Add to the build process
    using::

        setup(cmd_class={'clean_messages': clean_messages})
    """

    description = "clean generated protocol message code mappings"

    user_options = [
        ('destination', None, 'destination Python source file')
    ]

    def initialize_options(self):
        self.destination = None

    def finalize_options(self):
        self.set_undefined_options('build_messages',
                                   ('destination', 'destination'))

    def run(self):
        if isfile(self.destination):
            self.execute(os.remove, [self.destination],
                         msg="removing {0}".format(self.destination))


class build_messages(Command):
    """
    Generates message code mappings. Add to the build process using::

        setup(cmd_class={'build_messages': build_messages})
    """

    description = "generate protocol message code mappings"

    user_options = [
        ('source=', None, 'source CSV file containing message code mappings'),
        ('destination=', None, 'destination Python source file')
    ]

    # Used in loading and generating
    _pb_imports = set()
    _messages = set()
    _empty_responses = set()
    _linesep = os.linesep
    _indented_item_sep = ',{0}    '.format(_linesep)

    _docstring = [
        ''
        '# This is a generated file. DO NOT EDIT.',
        '',
        '"""',
        'Constants and mappings between Riak protocol codes and messages.',
        '"""',
        ''
    ]

    def initialize_options(self):
        self.source = None
        self.destination = None

    def finalize_options(self):
        if self.source is None:
            self.source = 'src/riak_pb_messages.csv'
        if self.destination is None:
            self.destination = 'riak_pb/messages.py'

    def run(self):
        self.make_file(self.source, self.destination,
                       self._load_and_generate, [])

    def _load_and_generate(self):
        self._load()
        self._generate()

    def _load(self):
        with open(self.source, 'rb') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                message = MessageCodeMapping(*row)
                self._messages.add(message)
                self._pb_imports.add(message.module_name)
                if message.message_class is None:
                    self._empty_responses.add(message)

    def _generate(self):
        self._contents = []
        self._generate_doc()
        self._generate_imports()
        self._generate_codes()
        self._generate_empties()
        self._generate_classes()
        write_file(self.destination, self._contents)

    def _generate_doc(self):
        # Write the license and docstring header
        self._contents.append(LICENSE)
        self._contents.extend(self._docstring)

    def _generate_imports(self):
        # Write imports
        for im in sorted(self._pb_imports):
            self._contents.append("import {0}".format(im))

    def _generate_codes(self):
         # Write protocol code constants
        self._contents.extend(['', "# Protocol codes"])
        for message in sorted(self._messages):
            self._contents.append("{0} = {1}".format(message.message_code_name,
                                                     message.code))

    def _generate_empties(self):
        # Write empty responses
        names = [message.message_code_name
                 for message in sorted(self._empty_responses)]
        items = self._indented_item_sep.join(names)
        self._contents.extend(['',
                               "# These responses don't include messages",
                               'EMPTY_RESPONSES = [',
                               '    ' + items,
                               ']'
                               ])

    def _generate_classes(self):
        # Write message classes
        classes = [self._generate_mapping(message)
                   for message in sorted(self._messages)]

        classes = self._indented_item_sep.join(classes)
        self._contents.extend(['',
                               "# Mapping from code to protobuf class",
                               'MESSAGE_CLASSES = {',
                               '    ' + classes,
                               '}'])

    def _generate_mapping(self, m):
        if m.message_class is not None:
            klass = "{0}.{1}".format(m.module_name,
                                     m.message_class.__name__)
        else:
            klass = "None"
        pair = "{0}: {1}".format(m.message_code_name, klass)
        if len(pair) > 76:
            # Try to satisfy PEP8, lulz
            pair = (self._linesep + '    ').join(pair.split(' '))
        return pair
