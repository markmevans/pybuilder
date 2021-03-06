#  This file is part of PyBuilder
#
#  Copyright 2011-2014 PyBuilder Team
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
    The PyBuilder cli module.
    Contains the PyBuilder command-line entrypoint.
"""

import datetime
import optparse
import re
import sys
import traceback

from pybuilder import __version__
from pybuilder.core import Logger
from pybuilder.errors import PyBuilderException
from pybuilder.execution import ExecutionManager
from pybuilder.reactor import Reactor
from pybuilder.scaffolding import start_project
from pybuilder.terminal import (BOLD, BROWN, RED, GREEN, bold, styled_text,
                                fg, italic, print_text, print_text_line,
                                print_error, print_error_line, draw_line)
from pybuilder.utils import format_timestamp

PROPERTY_OVERRIDE_PATTERN = re.compile(r'^[a-zA-Z0-9_]+=.*')


class CommandLineUsageException(PyBuilderException):

    def __init__(self, usage, message):
        super(CommandLineUsageException, self).__init__(message)
        self.usage = usage


class StdOutLogger(Logger):

    def _level_to_string(self, level):
        if Logger.DEBUG == level:
            return "[DEBUG]"
        if Logger.INFO == level:
            return "[INFO] "
        if Logger.WARN == level:
            return "[WARN] "
        return "[ERROR]"

    def _do_log(self, level, message, *arguments):
        formatted_message = self._format_message(message, *arguments)
        log_level = self._level_to_string(level)
        print_text_line("{0} {1}".format(log_level, formatted_message))


class ColoredStdOutLogger(StdOutLogger):

    def _level_to_string(self, level):
        if Logger.DEBUG == level:
            return italic("[DEBUG]")
        if Logger.INFO == level:
            return bold("[INFO] ")
        if Logger.WARN == level:
            return styled_text("[WARN] ", BOLD, fg(BROWN))
        return styled_text("[ERROR]", BOLD, fg(RED))


def parse_options(args):
    parser = optparse.OptionParser(usage="%prog [options] task1 [[task2] ...]",
                                   version="%prog " + __version__)

    def error(msg):
        raise CommandLineUsageException(
            parser.get_usage() + parser.format_option_help(), msg)

    parser.error = error

    parser.add_option("-t", "--list-tasks",
                      action="store_true",
                      dest="list_tasks",
                      default=False,
                      help="List tasks")

    parser.add_option("--start-project",
                      action="store_true",
                      dest="start_project",
                      default=False,
                      help="Initialize a build descriptor and python project structure.")

    parser.add_option("-v", "--verbose",
                      action="store_true",
                      dest="verbose",
                      default=False,
                      help="Enable verbose output")

    project_group = optparse.OptionGroup(
        parser, "Project Options", "Customizes the project to build.")

    project_group.add_option("-D", "--project-directory",
                             dest="project_directory",
                             help="Root directory to execute in",
                             metavar="<project directory>",
                             default=".")
    project_group.add_option("-E", "--environment",
                             dest="environments",
                             help="Activate the given environment for this build. Can be used multiple times",
                             metavar="<environment>",
                             action="append",
                             default=[])
    project_group.add_option("-P",
                             action="append",
                             dest="property_overrides",
                             default=[],
                             metavar="<property>=<value>",
                             help="Set/ override a property value")

    parser.add_option_group(project_group)

    output_group = optparse.OptionGroup(
        parser, "Output Options", "Modifies the messages printed during a build.")

    output_group.add_option("-X", "--debug",
                            action="store_true",
                            dest="debug",
                            default=False,
                            help="Print debug messages")
    output_group.add_option("-q", "--quiet",
                            action="store_true",
                            dest="quiet",
                            default=False,
                            help="Quiet mode; print only warnings and errors")
    output_group.add_option("-Q", "--very-quiet",
                            action="store_true",
                            dest="very_quiet",
                            default=False,
                            help="Very quiet mode; print only errors")
    output_group.add_option("-C", "--no-color",
                            action="store_true",
                            dest="no_color",
                            default=False,
                            help="Disable colored output")

    parser.add_option_group(output_group)

    options, arguments = parser.parse_args(args=list(args))

    property_overrides = {}
    for pair in options.property_overrides:
        if not PROPERTY_OVERRIDE_PATTERN.match(pair):
            parser.error("%s is not a property definition." % pair)
        key, val = pair.split("=")
        property_overrides[key] = val

    options.property_overrides = property_overrides

    if options.very_quiet:
        options.quiet = True

    return options, arguments


def init_reactor(logger):
    execution_manager = ExecutionManager(logger)
    reactor = Reactor(logger, execution_manager)
    return reactor


def should_colorize(options):
    return sys.stdout.isatty() and not options.no_color


def init_logger(options):
    threshold = Logger.INFO
    if options.debug:
        threshold = Logger.DEBUG
    elif options.quiet:
        threshold = Logger.WARN

    if not should_colorize(options):
        logger = StdOutLogger(threshold)
    else:
        logger = ColoredStdOutLogger(threshold)

    return logger


def print_build_summary(options, summary):
    print_text_line("Build Summary")
    print_text_line("%20s: %s" % ("Project", summary.project.name))
    print_text_line("%20s: %s" % ("Version", summary.project.version))
    print_text_line("%20s: %s" % ("Base directory", summary.project.basedir))
    print_text_line("%20s: %s" %
                    ("Environments", ", ".join(options.environments)))

    task_summary = ""
    for task in summary.task_summaries:
        task_summary += " %s [%d ms]" % (task.task, task.execution_time)

    print_text_line("%20s:%s" % ("Tasks", task_summary))


def print_styled_text(text, options, *style_attributes):
    if should_colorize(options):
        text = styled_text(text, *style_attributes)
    print_text(text)


def print_styled_text_line(text, options, *style_attributes):
    print_styled_text(text + "\n", options, *style_attributes)


def print_build_status(failure_message, options, successful):
    draw_line()
    if successful:
        print_styled_text_line("BUILD SUCCESSFUL", options, BOLD, fg(GREEN))
    else:
        print_styled_text_line(
            "BUILD FAILED - {0}".format(failure_message), options, BOLD, fg(RED))
    draw_line()


def print_elapsed_time_summary(start, end):
    time_needed = end - start
    millis = ((time_needed.days * 24 * 60 * 60) + time_needed.seconds) * \
        1000 + time_needed.microseconds / 1000
    print_text_line("Build finished at %s" % format_timestamp(end))
    print_text_line("Build took %d seconds (%d ms)" %
                    (time_needed.seconds, millis))


def print_summary(successful, summary, start, end, options, failure_message):
    print_build_status(failure_message, options, successful)

    if successful and summary:
        print_build_summary(options, summary)

    print_elapsed_time_summary(start, end)


def length_of_longest_string(list_of_strings):
    if len(list_of_strings) == 0:
        return 0

    result = 0
    for string in list_of_strings:
        length_of_string = len(string)
        if length_of_string > result:
            result = length_of_string

    return result


def print_list_of_tasks(reactor):
    print_text_line('Tasks found for project "%s":' % reactor.project.name)

    tasks = reactor.get_tasks()
    column_length = length_of_longest_string(
        list(map(lambda task: task.name, tasks)))
    column_length += 4

    for task in sorted(tasks):
        task_name = task.name.rjust(column_length)
        task_description = " ".join(
            task.description) or "<no description available>"
        print_text_line("{0} - {1}".format(task_name, task_description))

        if task.dependencies:
            whitespace = (column_length + 3) * " "
            depends_on_message = "depends on tasks: %s" % " ".join(
                task.dependencies)
            print_text_line(whitespace + depends_on_message)


def main(*args):
    try:
        options, arguments = parse_options(args)
    except CommandLineUsageException as e:
        print_error_line("Usage error: %s\n" % e)
        print_error(e.usage)
        return 1

    start = datetime.datetime.now()

    logger = init_logger(options)
    reactor = init_reactor(logger)

    if options.start_project:
        return start_project()

    if options.list_tasks:
        reactor.prepare_build(property_overrides=options.property_overrides,
                              project_directory=options.project_directory)

        print_list_of_tasks(reactor)
        return 0

    if not options.very_quiet:
        print_styled_text_line(
            "PyBuilder version {0}".format(__version__), options, BOLD)
        print_text_line("Build started at %s" % format_timestamp(start))
        draw_line()

    successful = True
    failure_message = None
    summary = None

    try:
        try:
            reactor.prepare_build(
                property_overrides=options.property_overrides,
                project_directory=options.project_directory)

            if options.verbose or options.debug:
                logger.debug("Verbose output enabled.\n")
                reactor.project.set_property("verbose", True)

            summary = reactor.build(
                environments=options.environments, tasks=arguments)

        except KeyboardInterrupt:
            raise PyBuilderException("Build aborted")

    except Exception as e:
        failure_message = str(e)
        if options.debug:
            traceback.print_exc(file=sys.stderr)
        successful = False

    finally:
        end = datetime.datetime.now()
        if not options.very_quiet:
            print_summary(
                successful, summary, start, end, options, failure_message)

        if not successful:
            return 1

        return 0
