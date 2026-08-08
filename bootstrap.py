import platform
import os
import sys
import subprocess
import shutil
from pathlib import Path
from input import Input
from output import Output
from argparser import ArgParser
from state import State
from target import Target
from dependencies import Dependencies
from projects import Projects
from cmake import CMake
from compilers import Compilers
from build import BuildTools, BuildConfiguration
from config import Config
from utils import Utils


def try_restore_previous_state(input, default, state, config):
    if state.previous_state_found:
        resume = input.query(
            "Previous execution detected. Do you want to resume it?",
            ["y", "n"], default)
        if resume == "n":
            state.reset()
            Utils.rmdir_with_retry(config.build_dir, input)


def download_source_packages(projects, skip, input, state, output, config):
    print("")
    output.print_step_title("Downloading source packages")
    if skip:
        print("    Skipping downloads")
    elif not state.download_complete:
        Utils.rmdir_with_retry(config.downloads_dir, input)
        projects.download()
    else:
        print("    Using previous execution")
    state.set_download_complete()
    output.next_step()


def select_target(input, state, output):
    platform_name = platform.system()
    is_64bit_supported = ((platform.machine() == "AMD64") or (platform.machine() == "x86_64"))
    
    print("")
    output.print_step_title("Architecture choice")
    print("    Platform: " + platform_name)
    selected_architecture = ""
    if state.architecture == "":
        if is_64bit_supported:
            selected_architecture = input.query("    Select architecture.", ["32", "64"], "64")
        else:
            print("    Only 32-bit build supported")
            selected_architecture = "32"
    else:
        selected_architecture = state.architecture
        print("    Using previous selection: " + selected_architecture)
    state.set_architecture(selected_architecture)
    output.next_step()
    return Target(platform_name, selected_architecture)


def main_bootstrap_build(args, input, state, output, config):
    try:
        print("")
        output.print_main_title()

        try_restore_previous_state(input, "n", state, config)

        target = select_target(input, state, output)

        Path(config.build_dir).mkdir(exist_ok=True)

        dependencies = Dependencies()
        dependencies.check(output)

        projects = Projects(target, config)

        projects.set_environment_variables(output)

        download_source_packages(projects, args.skip_downloads, input, state,
                                 output, config)

        compilers = Compilers(target)
        compiler = compilers.select_compiler(input, state, output)

        build_configuration = BuildConfiguration()
        build_configuration.select_configuration(target.architecture,
                                                 compiler, input, state)

        cmake = CMake(compiler.cmake_generator, compiler.cmake_architecture, config)
        cmake.install(target, state, output)

        build_tools = BuildTools(cmake, compiler)
        
        projects.build(build_tools, build_configuration,
                       input, state, output)

        print("")
        output.print_step_title("Running tests")
        if args.skip_tests:
            print("    Skipping tests")
        else:
            projects.test(compiler, build_configuration.architecture_dir_name,
                          input)
        output.next_step()

        print("")
        output.print_step_title("Setting up second-phase of bootstrap")
        second_phase_path = str(Path(os.getcwd()).parent) + \
                            "/SecondPhaseBootstrap"
        Path(second_phase_path).mkdir(exist_ok=True)
        print(second_phase_path)
        # TODO
        shutil.copyfile(config.build_dir + "/codesmithyide/codesmithy/bin/x64/CodeSmithy.exe", second_phase_path + "/CodeSmithy.exe")
        output.next_step()
    except RuntimeError as error:
        print("")
        print("ERROR:", error)
        sys.exit(-1)


def main_launch_project(args, input, state, output, config):
    projects = Projects(None, config)

    try_restore_previous_state(input, "y", state, config)

    # It is not possible to instruct Visual Studio to start with a specific
    # configuration so we do not ask the user and randomly specify "x64"
    selected_architecture = "x64"
    
    compilers = Compilers(selected_architecture)
    compiler = compilers.select_compiler(input, state, output)

    projects.get(args.launch).launch(compiler)


def main():
    args = ArgParser().parse()

    input = Input(not args.non_interactive)
    output = Output()
    state = State()
    config = Config()

    if args.launch is None:
        main_bootstrap_build(args, input, state, output, config)
    else:
        try:
            main_launch_project(args, input, state, output, config)
        except RuntimeError as error:
            print("")
            print("ERROR:", error)
            sys.exit(-1)


if __name__ == "__main__":
    main()
